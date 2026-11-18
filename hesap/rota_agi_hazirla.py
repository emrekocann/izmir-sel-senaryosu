"""Sunucusuz sayfada tarayıcının kendisinin rota hesaplayabilmesi için merkez
ilçelerin araç yol ağını ve her yağış senaryosunun suyunu dosyaya yazar.

Sayfa (docs/js/cekirdek/rota_motoru.js) bu ağ üzerinde Dijkstra çalıştırır:
kullanıcı haritada istediği noktayı seçer, yağışı değiştirir, rota anında
yeniden hesaplanır. Maliyet sunucudaki pgRouting sorgusunun
(repository.AfetRepository._maliyet_sql) senaryo kısmıyla aynıdır:

  uzunluk × (1 + eğim × 0.05)
    × 5          kenarda sığ su (0.1–0.3 m) ya da düz ova belirsizliği varsa
    + 100 km     kenarın bir noktası 30 cm'den derin suda ise (yol kapalı)
    + 100 km     senaryoda alt geçitler doluysa alt geçit kenarında

Canlı veriler (son 24 saatin depremleri, trafik) sayfada yoktur.

Çıktı:
  docs/veri/rota/ag.json         düğümler, kenarlar (yalın geometriyle),
                                 toplanma alanları, kapsama sınırı
  docs/veri/rota/su_<mm>_<sa>.json  senaryoda ıslak kenarların ek maliyeti,
                                 en derin noktası, kapalı toplanma alanları

Ağ boyutu: kavşak olmayan (iki kenarlı) düğümler zincir halinde birleştirilir;
152 bin yol parçası ~60 bin kenara iner. Koordinatlar 1e-5 derece (~1 m)
tamsayı farkları olarak yazılır.

Çalıştırma: venv/bin/python -m hesap.rota_agi_hazirla
Önkoşul: yol ağı (hesap/build_road_network.py), sel_senaryo_su tablosu
(hesap/sel_senaryo_yollar.py), toplanma alanları, DB açık.
"""
import asyncio
import json
import logging
import os
from collections import defaultdict

import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from database import db
from hesap.sel_dogrulama import ilceler_ve_mahalleler
from repository import AfetRepository as R

log = logging.getLogger("rota_agi")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIKTI = os.path.join(BASE_DIR, "docs", "veri", "rota")
VITRIN = os.path.join(BASE_DIR, "docs", "veri", "vitrin.json")

# İzmir'in kent merkezini oluşturan ilçeler (TKGM yazımıyla)
ILCELER = ["Balçova", "Bayrakli", "Bornova", "Buca", "Çiğli", "Gaziemir", "Güzelbahçe",
           "Karabağlar", "Karşiyaka", "Konak", "Narlidere"]
OLCEK = 100_000              # derece → tamsayı (1e-5° ≈ 1 m)
SADELESTIR = 0.00003         # ~3 m: kenar geometrisi sadeleştirme (uçlar korunur)
EGIM_K = R.ROUTE_MODES["drive"][1]
ISLAK_K = R.SENARYO_ISLAK_K
KAPALI_M = R.SENARYO_KAPALI_M
KAPALI_EK = R.SENARYO_KAPALI_EK
SNAP_HARIC = set(R.SNAP_HARIC)
ISE_YARAMAZ = ("demolished", "escape", "emergency_bay")


def en_buyuk_bilesen(kaynak, hedef):
    """En büyük bağlı bileşendeki kenarların maskesi (yönsüz)."""
    dugum, ters = np.unique(np.r_[kaynak, hedef], return_inverse=True)
    n, m = len(dugum), len(kaynak)
    a, b = ters[:m], ters[m:]
    _, etiket = connected_components(coo_matrix((np.ones(m), (a, b)), shape=(n, n)), directed=False)
    buyuk = np.bincount(etiket).argmax()
    return etiket[a] == buyuk


def ikizleri_ayikla(kaynak, hedef, uzunluk):
    """Çift yönlü yol OSM'den iki yönlü iki kenar olarak gelir (rota yönsüz
    hesaplanır, ikisi aynıdır). Aynı iki düğümü bağlayan, uzunluğu aynı (1 m)
    kenarlardan ilki tutulur. Dönüş: (tutulan maske, {atılan sıra: tutulan sıra})."""
    ilk, ikiz = {}, {}
    tut = np.ones(len(kaynak), bool)
    for i, (a, b, m) in enumerate(zip(kaynak, hedef, uzunluk)):
        anahtar = (min(a, b), max(a, b), round(float(m)))
        if anahtar in ilk:
            tut[i] = False
            ikiz[i] = ilk[anahtar]
        else:
            ilk[anahtar] = i
    return tut, ikiz


def zincirle(kaynak, hedef, korunan, ayri):
    """Kavşak olmayan düğümleri (tam iki kenarlı, korunmayan) kaldırıp kenar
    zincirlerini tek kenara birleştirir. ayri[i]: kenarın bağlanma sınıfı
    (otoyol mu); farklı sınıftaki iki kenarın birleştiği düğüm korunur.
    Kendine dönen kenarlar atılır (en kısa yolda hiç kullanılmaz).

    Dönüş: [(bas, son, [(kenar, ters_mi), ...]), ...] — bas/son özgün düğüm
    kimliği, parçalar bas'tan son'a sırayla; ters_mi: parça hedef→kaynak
    yönünde geçilir."""
    komsu = defaultdict(list)
    for i, (a, b) in enumerate(zip(kaynak, hedef)):
        if a == b:
            continue
        komsu[a].append(i)
        komsu[b].append(i)

    def kavsak(d):
        k = komsu[d]
        return len(k) != 2 or d in korunan or ayri[k[0]] != ayri[k[1]]

    gorulen = np.zeros(len(kaynak), bool)
    zincirler = []
    for u in list(komsu):
        if not kavsak(u):
            continue
        for e in komsu[u]:
            if gorulen[e]:
                continue
            parcalar, cur = [], u
            while True:
                gorulen[e] = True
                ters = kaynak[e] != cur
                parcalar.append((e, ters))
                cur = kaynak[e] if ters else hedef[e]
                if kavsak(cur):
                    break
                e = komsu[cur][0] if komsu[cur][1] == e else komsu[cur][1]
            zincirler.append((u, cur, parcalar))
    kalan = int((~gorulen & (np.asarray(kaynak) != np.asarray(hedef))).sum())
    if kalan:
        raise ValueError(f"{kalan} kenar kavşaksız halkada kaldı (en büyük bileşen süzülmedi mi?)")
    return zincirler


def su_ozeti(parcalar, taban, su):
    """Bir zincirin senaryodaki suyu: (ek maliyet, en derin m, derin parça,
    belirsiz/sığ parça). su: {kenar: (derinlik, belirsiz)} yalnız ıslak
    kenarlar (sel_senaryo_su). Ek maliyet, ıslak parçaların
    pgRouting maliyetine eklediği kısımdır (_maliyet_sql ile aynı)."""
    ek, en_derin, derin, islak = 0.0, 0.0, 0, 0
    for e, _ in parcalar:
        s = su.get(e)
        if s is None:
            continue
        d, _belirsiz = s
        if d >= KAPALI_M:
            ek += KAPALI_EK
            derin += 1
        else:
            ek += taban[e] * (ISLAK_K - 1)
            islak += 1
        en_derin = max(en_derin, d)
    return ek, en_derin, derin, islak


def fark_kodla(sayilar):
    """Tamsayı dizisini ilk değer + ardışık farklar olarak yazar (gzip'te
    küçülür)."""
    s = np.asarray(sayilar, dtype=np.int64)
    return np.r_[s[:1], np.diff(s)].tolist() if len(s) else []


def bolge():
    ilce, _ = ilceler_ve_mahalleler(set(ILCELER))
    eksik = set(ILCELER) - set(ilce)
    if eksik:
        raise ValueError(f"TKGM'de bulunamayan ilçe: {eksik}")
    return shapely.union_all(list(ilce.values()))


async def oku(alan):
    haric = ", ".join(f"'{h}'" for h in ISE_YARAMAZ)
    async with db.baglan() as c:
        kenarlar = await c.fetch(f"""
            SELECT id, source, target, length, COALESCE(slope, 0) AS slope,
                   COALESCE(highway, '') AS highway, COALESCE(alt_gecit, false) AS alt_gecit,
                   ST_AsBinary(ST_Simplify(the_geom, {SADELESTIR})) AS wkb
            FROM izmir_roads_noded
            WHERE ST_Intersects(the_geom, ST_GeomFromText($1, 4326))
              AND COALESCE(highway, '') NOT IN ({haric})""", alan.wkt)
        alanlar = await c.fetch("""
            SELECT id, adi, ilce, mahalle, drive_vid, ST_X(konum) AS lon, ST_Y(konum) AS lat
            FROM toplanma_alanlari
            WHERE drive_vid IS NOT NULL AND ST_Intersects(konum, ST_GeomFromText($1, 4326))
            ORDER BY id""", alan.wkt)
        su = await c.fetch("""
            SELECT senaryo, katman, kimlik, derinlik, belirsiz FROM sel_senaryo_su
            WHERE katman IN ('drive', 'toplanma')""")
    return kenarlar, alanlar, su


def ag_kur(kenarlar, alanlar):
    """Zincirlenmiş ağ ve dosyaya yazılacak sözlük."""
    kimlik = np.array([r["id"] for r in kenarlar])
    kaynak = np.array([r["source"] for r in kenarlar])
    hedef = np.array([r["target"] for r in kenarlar])
    tut, ikiz = ikizleri_ayikla(kaynak, hedef, [r["length"] for r in kenarlar])
    ikiz_kimlik = {int(kimlik[i]): int(kimlik[j]) for i, j in ikiz.items()}
    log.info("Çift yönlü ikizler atıldı: %d → %d yol parçası", len(tut), tut.sum())
    kenarlar = [r for r, t in zip(kenarlar, tut) if t]
    kimlik, kaynak, hedef = kimlik[tut], kaynak[tut], hedef[tut]
    sec = en_buyuk_bilesen(kaynak, hedef)
    kenarlar = [r for r, s in zip(kenarlar, sec) if s]
    kimlik, kaynak, hedef = kimlik[sec], kaynak[sec], hedef[sec]
    log.info("En büyük bileşen: %d / %d yol parçası", sec.sum(), len(sec))

    uzunluk = np.array([r["length"] for r in kenarlar])
    taban = uzunluk * (1 + np.array([r["slope"] for r in kenarlar]) * EGIM_K)
    ayri = np.array([r["highway"] in SNAP_HARIC for r in kenarlar])
    alt = np.array([r["alt_gecit"] for r in kenarlar])
    geo = [shapely.get_coordinates(shapely.from_wkb(r["wkb"])) for r in kenarlar]

    dugumler = set(kaynak) | set(hedef)
    alanlar = [a for a in alanlar if a["drive_vid"] in dugumler]
    zincirler = zincirle(kaynak, hedef, {a["drive_vid"] for a in alanlar}, ayri)

    # düğüm konumu: kenar geometrisinin ucu
    konum = {}
    for i in range(len(kenarlar)):
        konum.setdefault(kaynak[i], geo[i][0])
        konum.setdefault(hedef[i], geo[i][-1])
    sira = {}
    for u, v, _ in zincirler:
        for d in (u, v):
            sira.setdefault(d, len(sira))
    xy = np.round(np.array([konum[d] for d in sira]) * OLCEK).astype(np.int64)

    a, b, m, c, ag_sayi, otoyol, ic_sayi, ic = [], [], [], [], [], [], [], []
    for z, (u, v, parcalar) in enumerate(zincirler):
        a.append(sira[u]); b.append(sira[v])
        idx = [e for e, _ in parcalar]
        m.append(round(float(uzunluk[idx].sum())))
        c.append(round(float(taban[idx].sum())))
        ag_sayi.append(int(alt[idx].sum()))
        if ayri[idx[0]]:
            otoyol.append(z)
        nokta = [geo[e][::-1] if ters else geo[e] for e, ters in parcalar]
        cizgi = np.vstack([nokta[0]] + [p[1:] for p in nokta[1:]])
        icteki = np.round(cizgi[1:-1] * OLCEK).astype(np.int64)
        onceki = xy[sira[u]]
        for p in icteki:                         # önceki noktaya göre fark
            ic.extend((p - onceki).tolist())
            onceki = p
        ic_sayi.append(len(icteki))

    alan_kayit = [[sira[a_["drive_vid"]], round(a_["lon"], 5), round(a_["lat"], 5), a_["id"],
                   a_["adi"] or "", a_["ilce"] or "", a_["mahalle"] or ""] for a_ in alanlar]
    ag = {
        "olcek": OLCEK,
        "ilceler": ILCELER,
        "dugum_x": fark_kodla(xy[:, 0]), "dugum_y": fark_kodla(xy[:, 1]),
        "kenar_a": a, "kenar_b": b, "kenar_m": m, "kenar_maliyet": c,
        "ic_sayi": ic_sayi, "ic": ic,
        "otoyol": fark_kodla(otoyol),
        "alt_gecit": {str(z): n for z, n in enumerate(ag_sayi) if n},
        "alanlar": alan_kayit,
        "maliyet": {"egim_k": EGIM_K, "islak_k": ISLAK_K, "kapali_m": KAPALI_M, "kapali_ek": KAPALI_EK},
    }
    zincir_kimlik = {int(kimlik[e]): z for z, (_, _, p) in enumerate(zincirler) for e, _ in p}
    return ag, zincirler, kimlik, taban, zincir_kimlik, ikiz_kimlik


def senaryo_dosyalari(su_satirlari, zincirler, kimlik, taban, zincir_kimlik, alan_kimlikleri,
                      ikiz_kimlik=None):
    """{senaryo: dosya sözlüğü}. Atılan ikiz kenarın suyu tutulan ikizine
    yazılır (ikisinden derin olanı); kendine dönen ya da ağ dışında kalan
    kenarın suyu yok sayılır."""
    ikiz_kimlik = ikiz_kimlik or {}
    sira = {int(k): i for i, k in enumerate(kimlik)}
    yol = defaultdict(dict)
    alan_kapali = defaultdict(list)
    senaryolar = set()
    for r in su_satirlari:
        senaryolar.add(r["senaryo"])
        if r["katman"] == "drive":
            i = sira.get(ikiz_kimlik.get(r["kimlik"], r["kimlik"]))
            if i is not None and int(kimlik[i]) in zincir_kimlik:
                d = (float(r["derinlik"]), bool(r["belirsiz"]))
                yol[r["senaryo"]][i] = max(d, yol[r["senaryo"]].get(i, d))
        elif r["kimlik"] in alan_kimlikleri and (r["derinlik"] >= KAPALI_M or r["belirsiz"]):
            alan_kapali[r["senaryo"]].append(int(r["kimlik"]))

    cikti = {}
    for sen in sorted(senaryolar):
        su = yol[sen]
        etkilenen = sorted({zincir_kimlik[int(kimlik[i])] for i in su})
        e, ek, d, n, s = [], [], [], [], []
        for z in etkilenen:
            ekm, en_derin, derin, islak = su_ozeti(zincirler[z][2], taban, su)
            e.append(z); ek.append(round(ekm)); d.append(round(en_derin * 10))
            n.append(derin); s.append(islak)
        cikti[sen] = {"kenar": fark_kodla(e), "ek": ek, "derin_dm": d, "derin_parca": n,
                      "sig_parca": s, "kapali_alan": sorted(alan_kapali[sen])}
    return cikti


def kapsam_siniri(alan):
    """Haritada kesikli çizilen ağ sınırı (GeoJSON geometri). TKGM ilçe
    poligonlarının birleşimi aralarındaki ince boşluklarda delik bırakır: ~200 m
    şişirip daraltarak kapatılır, kalan delikler atılır."""
    g = alan.buffer(0.002).buffer(-0.002)
    parcalar = [shapely.Polygon(p.exterior) for p in getattr(g, "geoms", [g])]
    g = shapely.simplify(shapely.MultiPolygon(parcalar), 0.001)
    return json.loads(shapely.to_geojson(shapely.set_precision(g, 1e-5)))


def yaz(ad, veri):
    yol = os.path.join(CIKTI, ad)
    with open(yol, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(yol)


async def calistir():
    alan = bolge()
    await db.connect()
    kenarlar, alanlar, su = await oku(alan)
    log.info("%d yol parçası, %d toplanma alanı, %d su satırı", len(kenarlar), len(alanlar), len(su))
    ag, zincirler, kimlik, taban, zincir_kimlik, ikiz = ag_kur(kenarlar, alanlar)
    ag["kapsam"] = kapsam_siniri(alan)
    os.makedirs(CIKTI, exist_ok=True)
    boyut = yaz("ag.json", ag)
    log.info("ag.json: %d düğüm, %d kenar, %d alan, %.1f MB", len(ag["dugum_x"]),
             len(ag["kenar_a"]), len(ag["alanlar"]), boyut / 1e6)
    dosyalar = senaryo_dosyalari(su, zincirler, kimlik, taban, zincir_kimlik,
                                 {a[3] for a in ag["alanlar"]}, ikiz)
    for sen, veri in dosyalar.items():
        b = yaz(f"su_{sen}.json", veri)
        log.info("su_%s.json: %d ıslak kenar, %d kapalı alan, %.0f kB", sen, len(veri["ek"]),
                 len(veri["kapali_alan"]), b / 1e3)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(calistir())
