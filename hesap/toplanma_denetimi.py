"""Toplanma alanı denetimi: hangi alanlar yerinde kontrol edilmeli?

İBB'nin 2.380 afet ve acil durum toplanma alanı, yağış senaryolarındaki su
derinliği ve arazi duyarlılığıyla karşılaştırılır. Çıktı bir hüküm değil,
bir ÖN ELEME listesidir: model 60 m'lik yükseklik verisine dayanır ve tek
olayla sınandığında mahalle düzeyinde ayırt edici çıkmamıştır (README,
"Geçmiş selle doğrulama"). Liste "şu alanlar güvensiz" demez; "ilk önce
şunlara yerinde bakın" der.

Öncelik kuralı (alanın konumundaki su ≥ 0.3 m — araçla geçilmez derinlik):
  1  yağış 24 saate yayılsa bile ≤ 100 mm'de su altında: yoğun sağanak
     gerekmeden, dere taşkını ya da çukurda birikmeyle su alıyor
  2  2 Şubat 2021'e yakın yağışta (100 mm / 6 saat ya da 150 mm / 24 saat)
     su altında
  3  yalnız daha şiddetli senaryolarda su altında
  ova  düz ovada: su gelebilir, derinlik bilinmiyor (hiçbir senaryoda
       ≥ 0.3 m hesaplanmamış ama en az bir senaryoda "belirsiz")
Ek işaretler (önceliği değiştirmez):
  duyarlı   arazi duyarlılığı çok yüksek (S ≥ 0.85: dere yatağı / çukur)
  erişim    alan kuru ama yaya ağında bağlandığı kavşağa çıkan bütün yollar
            2021 senaryolarından birinde su altında
Bağımsız sağlama: her alanın OpenStreetMap'te çizili en yakın dereye / kanala
uzaklığı (dereye_m). Model dereleri yükseklik verisinden türetir, OSM'yi
kullanmaz; öncelikli alanların OSM derelerine yakın çıkması modelden bağımsız
bir işarettir.

Çıktılar: denetim/toplanma_denetimi.csv (işaretli alanlar, öncelik sırasıyla),
docs/veri/denetim.json ve docs/veri/toplanma_denetimi.csv (yayın sayfası).

Çalıştırma: venv/bin/python -m hesap.toplanma_denetimi
Önkoşul: toplanma_alanlari ve sel_senaryo_su tabloları (hesap/sel_senaryo_yollar.py),
sel_model/duyarlilik.npz, DB açık.
"""
import asyncio
import csv
import logging
import os
import shutil
from collections import Counter

import numpy as np
import shapely
from affine import Affine

from afet.dosya import json_oku, json_yaz
from afet.sel.risk import BANT_ESIK
from afet.sinir import il_poligonu
from afet.veritabani.baglanti import db
from afet.veritabani.depo import AfetDeposu
from afet.yollar import DENETIM_CSV, DENETIM_JSON, DUYARLILIK, OSM_DERELER, SITE_DENETIM_CSV
from hesap import gunlugu_kur
from hesap.dem_hidroloji import osm_cizgileri, raster_ornekle

log = logging.getLogger("denetim")

SU_M = AfetDeposu.SENARYO_KAPALI_M          # 0.3 m
ONCELIK_1 = ["25_24", "50_24", "75_24", "100_24"]      # 24 saate yayılmış ≤ 100 mm
ONCELIK_2 = ["100_6", "150_24"]                        # 2 Şubat 2021'e yakın yağış
DUYARLI_S = BANT_ESIK[-1]                    # 0.85: çok yüksek duyarlılık
OSM_DERE_TURLERI = ("river", "stream", "canal", "drain")     # hendek (ditch) alınmaz
DERE_YAKIN_M = 100
ONCELIK_AD = {1: "1", 2: "2", 3: "3", "ova": "ova", None: ""}


def oncelik(su, belirsiz):
    """su: {senaryo: derinlik m} (yalnız ıslak olanlar), belirsiz: senaryo
    kümesi. Dönüş: 1 / 2 / 3 / 'ova' / None."""
    derin = {s for s, d in su.items() if d >= SU_M}
    if derin & set(ONCELIK_1):
        return 1
    if derin & set(ONCELIK_2):
        return 2
    if derin:
        return 3
    return "ova" if belirsiz else None


def en_kucuk_yagis(su):
    """Alanın ≥ 0.3 m su aldığı en küçük yağış (mm) ve o yağışın en uzun süresi."""
    derin = [tuple(map(int, s.split("_"))) for s, d in su.items() if d >= SU_M]
    if not derin:
        return None
    p = min(x[0] for x in derin)
    return p, max(x[1] for x in derin if x[0] == p)


def _dere_mi(etiket):
    """osm_cizgileri seçicisi: dere / kanal hattı (değilse None: atlanır)."""
    return True if etiket.get("waterway") in OSM_DERE_TURLERI else None


def osm_dereleri():
    """İl çerçevesindeki OSM dere / kanal hatları (Geofabrik dosyasından bir
    kez okunur, ~1 dk; önbellekli)."""
    if not os.path.exists(OSM_DERELER):
        json_yaz(OSM_DERELER, [xy for _, _, xy in osm_cizgileri(il_poligonu().bounds, _dere_mi)])
    return [shapely.LineString(h) for h in json_oku(OSM_DERELER)]


def dereye_uzaklik_m(lon, lat, dereler):
    """Noktaların en yakın dere hattına uzaklığı (m). Boylam, il ortalama
    enleminin kosinüsüyle ölçeklenir (yerel düzlem yaklaşımı)."""
    k = np.cos(np.radians(np.mean(lat)))
    agac = shapely.STRtree(shapely.transform(dereler, lambda c: c * [k, 1.0]))
    _, uzaklik = agac.query_nearest(shapely.points(np.asarray(lon) * k, lat), return_distance=True,
                                    all_matches=False)
    return uzaklik * 111_320.0


async def veri():
    async with db.oturum():
        async with db.baglan() as c:
            alanlar = [dict(r) for r in await c.fetch(
                "SELECT id, kod, adi, ilce, mahalle, yol, walk_vid, "
                "ST_X(konum) AS lon, ST_Y(konum) AS lat FROM toplanma_alanlari ORDER BY id")]
            su = await c.fetch("SELECT senaryo, kimlik, derinlik, belirsiz FROM sel_senaryo_su "
                               "WHERE katman = 'toplanma'")
            # alanın yaya ağındaki kavşağına çıkan yolların hepsi su altında mı
            erisim = await c.fetch(f"""
                SELECT a.id, s.senaryo
                FROM toplanma_alanlari a
                JOIN izmir_yaya_noded e ON a.walk_vid IN (e.source, e.target)
                CROSS JOIN unnest($1::text[]) AS s(senaryo)
                LEFT JOIN sel_senaryo_su ss ON ss.katman = 'walk' AND ss.senaryo = s.senaryo
                     AND ss.kimlik = e.id AND ss.derinlik >= {SU_M}
                WHERE a.walk_vid IS NOT NULL
                GROUP BY a.id, s.senaryo
                HAVING count(*) = count(ss.kimlik)""", ONCELIK_2)
    return alanlar, su, erisim


def denetle(alanlar, su_satirlari, erisim_satirlari, duyarlilik, dereye_m):
    su, belirsiz = {}, {}
    for r in su_satirlari:
        if r["derinlik"] > 0:
            su.setdefault(r["kimlik"], {})[r["senaryo"]] = round(float(r["derinlik"]), 1)
        if r["belirsiz"]:
            belirsiz.setdefault(r["kimlik"], set()).add(r["senaryo"])
    erisim = {}
    for r in erisim_satirlari:
        erisim.setdefault(r["id"], set()).add(r["senaryo"])
    out = []
    for a, s, dm in zip(alanlar, duyarlilik, dereye_m):
        d = su.get(a["id"], {})
        o = oncelik(d, belirsiz.get(a["id"], set()))
        kucuk = en_kucuk_yagis(d)
        out.append({
            **{k: a[k] for k in ("id", "kod", "adi", "ilce", "mahalle", "yol", "lon", "lat")},
            "oncelik": o,
            "en_kucuk_yagis_mm": kucuk and kucuk[0], "en_kucuk_yagis_saat": kucuk and kucuk[1],
            **{f"su_{sen}_m": d.get(sen, 0.0) for sen in ONCELIK_2},
            "duyarlilik": round(float(s), 2), "duyarli": bool(s >= DUYARLI_S),
            "dereye_m": int(round(float(dm))),
            # erişim işareti yalnız kendisi kuru alanlar için anlamlıdır
            "erisim_kapali": bool(erisim.get(a["id"])) and o in (None, 3, "ova")
                             and not any(d.get(sen, 0) >= SU_M for sen in ONCELIK_2),
        })
    return out


def sirala(satirlar):
    sira = {1: 0, 2: 1, 3: 2, "ova": 3, None: 4}
    return sorted(satirlar, key=lambda r: (sira[r["oncelik"]], r["en_kucuk_yagis_mm"] or 999,
                                           -max(r[f"su_{s}_m"] for s in ONCELIK_2), r["ilce"], r["id"]))


def yaz(satirlar):
    isaretli = [r for r in sirala(satirlar) if r["oncelik"] or r["duyarli"] or r["erisim_kapali"]]
    os.makedirs(os.path.dirname(DENETIM_CSV), exist_ok=True)
    kolonlar = ["oncelik", "ilce", "mahalle", "adi", "yol", "kod", "lat", "lon",
                "en_kucuk_yagis_mm", "en_kucuk_yagis_saat"] + [f"su_{s}_m" for s in ONCELIK_2] + [
                "duyarlilik", "duyarli", "dereye_m", "erisim_kapali", "id"]
    with open(DENETIM_CSV, "w", encoding="utf-8-sig", newline="") as f:      # BOM: Excel Türkçe karakter
        w = csv.DictWriter(f, fieldnames=kolonlar, extrasaction="ignore")
        w.writeheader()
        for r in isaretli:
            w.writerow({**r, "oncelik": ONCELIK_AD[r["oncelik"]], "lat": round(r["lat"], 6),
                        "lon": round(r["lon"], 6), "duyarli": int(r["duyarli"]),
                        "erisim_kapali": int(r["erisim_kapali"])})
    shutil.copy(DENETIM_CSV, SITE_DENETIM_CSV)

    say = Counter(ONCELIK_AD[r["oncelik"]] for r in satirlar)
    ilce = {}
    for r in satirlar:
        i = ilce.setdefault(r["ilce"], Counter())
        i["toplam"] += 1
        i[ONCELIK_AD[r["oncelik"]] or "temiz"] += 1
    ozet = {
        "toplam": len(satirlar), "sayim": {k: say.get(k, 0) for k in ("1", "2", "3", "ova")},
        "duyarli": sum(r["duyarli"] for r in satirlar),
        "duyarli_ve_oncelikli": sum(r["duyarli"] and r["oncelik"] in (1, 2, 3) for r in satirlar),
        "erisim_kapali": sum(r["erisim_kapali"] for r in satirlar),
        # bağımsız sağlama: OSM'de çizili bir dereye DERE_YAKIN_M'den yakın olanların payı
        "dere_yakin_m": DERE_YAKIN_M,
        "dere_yakin": {ad: {"yakin": sum(r["dereye_m"] <= DERE_YAKIN_M for r in grup), "toplam": len(grup)}
                       for ad, grup in (("oncelikli", [r for r in satirlar if r["oncelik"] in (1, 2)]),
                                        ("oteki", [r for r in satirlar if r["oncelik"] not in (1, 2)]))},
        "senaryolar": {"oncelik_1": ONCELIK_1, "oncelik_2": ONCELIK_2},
        "ilce": sorted(({"ilce": k, **{a: v.get(a, 0) for a in ("toplam", "1", "2", "3", "ova")}}
                        for k, v in ilce.items()), key=lambda x: (-(x["1"] + x["2"]), -x["3"], x["ilce"])),
        # harita: [lat, lon, öncelik kodu (0 temiz, 1, 2, 3, 4 ova), duyarlı, erişim]
        "noktalar": [[round(r["lat"], 5), round(r["lon"], 5),
                      {None: 0, 1: 1, 2: 2, 3: 3, "ova": 4}[r["oncelik"]],
                      int(r["duyarli"]), int(r["erisim_kapali"])] for r in satirlar],
        # tablo: 1. ve 2. öncelik
        "liste": [{k: r[k] for k in ("oncelik", "adi", "ilce", "mahalle", "yol", "lat", "lon",
                                     "en_kucuk_yagis_mm", "en_kucuk_yagis_saat", "duyarli", "dereye_m")
                   } | {"su_m": max(r[f"su_{s}_m"] for s in ONCELIK_2)}
                  for r in isaretli if r["oncelik"] in (1, 2)],
    }
    json_yaz(DENETIM_JSON, ozet)
    return ozet, len(isaretli)


def main():
    gunlugu_kur()
    alanlar, su, erisim = asyncio.run(veri())
    z = np.load(DUYARLILIK)
    tr = Affine(float(z["dx"]), 0, float(z["bati"]), 0, float(z["dy"]), float(z["kuzey"]))
    lon, lat = np.array([a["lon"] for a in alanlar]), np.array([a["lat"] for a in alanlar])
    s = raster_ornekle(z["s"], tr, lon, lat) / 255.0
    ozet, n = yaz(denetle(alanlar, su, erisim, s, dereye_uzaklik_m(lon, lat, osm_dereleri())))
    dy = ozet["dere_yakin"]
    log.info("OSM deresine ≤ %d m: öncelikli %d / %d, öteki %d / %d", DERE_YAKIN_M,
             dy["oncelikli"]["yakin"], dy["oncelikli"]["toplam"], dy["oteki"]["yakin"], dy["oteki"]["toplam"])
    log.info("%d alan: 1. öncelik %d, 2. öncelik %d, 3. öncelik %d, düz ova %d; çok duyarlı arazi %d "
             "(%d'i öncelikli), erişimi kapanan %d — %d işaretli alan %s",
             ozet["toplam"], *[ozet["sayim"][k] for k in ("1", "2", "3", "ova")], ozet["duyarli"],
             ozet["duyarli_ve_oncelikli"], ozet["erisim_kapali"], n, DENETIM_CSV)


if __name__ == "__main__":
    main()
