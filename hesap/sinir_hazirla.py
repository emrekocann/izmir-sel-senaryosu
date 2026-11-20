"""İl ve ilçe sınırlarını resmî TKGM idari sınırlarından, kıyıyı OSM kıyı
çizgisine oturtarak üretir.

Neden iki kaynak: Harita altlığı (Esri/HERE) resmî sınırı çizer; TKGM MEGSİS
servisinin ilçe sınırları onunla örtüşür (OSM idari sınırları kara sınırında
ortalama ~0.6 km, en çok ~4 km sapar). TKGM'nin kıyısı ise kaba ve ada
içermez; kıyı ve adalar OSM kıyı çizgisinden alınır.

Çıktı (birebir örtüşen iki dosya):
  sinir/izmir_ilce.geojson  — 30 ilçe, boşluksuz/örtüşmesiz, adalar dahil
  sinir/izmir_sinir.geojson — ilçelerin birleşimi

Akış:
  1. TKGM: il listesi (komşu iller için) ve İzmir ilçeleri; OSM: il kutusundaki
     natural=coastline yolları (Overpass) ve İzmir'in OSM ilişkisi (yalnız
     hangi adaların İzmir'e ait olduğunu belirlemek için).
  2. Kara: kutu, kıyı çizgisiyle yüzlere bölünür; OSM kıyı yolunda kara SOLDA
     kaldığından her yüz sol/sağ örnek noktalarıyla kara/deniz diye oylanır.
  3. İl = [TKGM ilçeleri ∪ (kıyıya KIYI_PAYI km'den yakın tampon − komşu
     iller)] ∩ kara ∪ İzmir adaları. Kara sınırı TKGM'nin aynısıdır.
  4. İlçeler: her ilçenin yalnız kendine ait (örtüşmesiz) kısmı korunur;
     örtüşmeler, ilçe arası boşluklar, kıyı şeridi ve adalar en yakın ilçe
     sınırına göre (Voronoi) paylaştırılır.
  5. Paylaşılan kenarlar korunarak ~10 m'ye sadeleştirilir (coverage_simplify).

Sınır değişince yol ağı ve sel hesapları yeniden üretilmelidir
(README → Sınır verisi).
Çalıştırma: venv/bin/python -m hesap.sinir_hazirla
"""
import json
import logging
import os

import numpy as np
import shapely
from shapely.geometry import LineString, Point, box, shape
from shapely.ops import polygonize, unary_union

from afet import ag
from afet.dosya import json_yaz
from afet.yollar import IL_SINIRI, ILCE_SINIRLARI, SINIR_HAM_DIR
from hesap import gunlugu_kur

log = logging.getLogger("sinir")

TKGM_URL = "https://cbsapi.tkgm.gov.tr/megsiswebapi.v3/api/idariYapi/"
TKGM_IL_ID = 57                                  # İzmir (TKGM idari yapı kimliği)
OSM_IL_KODU = "TR-35"
KUTU = (26.05, 37.70, 28.70, 39.60)              # batı, güney, doğu, kuzey
KIYI_PAYI = 0.03                                 # derece (~3 km): TKGM kıyısının en kötü sapması ~2.7 km
SADELESTIRME = 1e-4                              # derece (~10 m)
VORONOI_ADIM = 0.0005                            # ilçe sınırı örnekleme (~50 m)


def _getir(url, ad, veri=None):
    """JSON kaynağı, sinir_veri/<ad>.json'a önbelleklenir."""
    return ag.json_getir(url, os.path.join(SINIR_HAM_DIR, f"{ad}.json"), veri, deneme=9, bekle_sn=20)


def _overpass(sorgu, ad):
    return ag.overpass(sorgu, os.path.join(SINIR_HAM_DIR, f"{ad}.json"), deneme=9, bekle_sn=20)


def iliski_poligonu(rel):
    hat = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in rel["members"]
           if m["type"] == "way" and m.get("role") in ("outer", "") and "geometry" in m]
    return unary_union(list(polygonize(unary_union(hat))))


def kara_alani(kiyi):
    """Kutudaki kara: kutu kenarı + kıyı çizgisiyle bölünen yüzlerden, kıyı
    yolunun solunda kalanlar (kıyıya değmeyen yüz: kara)."""
    kutu = box(*KUTU)
    cizgiler = unary_union([kutu.boundary] + [k.intersection(kutu) for k in kiyi])
    yuzler = list(polygonize(cizgiler))
    agac = shapely.STRtree(yuzler)
    kara, deniz = np.zeros(len(yuzler)), np.zeros(len(yuzler))
    e = 2e-5
    for k in kiyi:
        c = np.asarray(k.coords)
        for (x0, y0), (x1, y1) in zip(c[:-1], c[1:]):
            dx, dy = x1 - x0, y1 - y0
            L = (dx * dx + dy * dy) ** 0.5
            if L < 1e-9:
                continue
            mx, my, nx, ny = (x0 + x1) / 2, (y0 + y1) / 2, -dy / L * e, dx / L * e   # sol normal
            for pt, oy in ((Point(mx + nx, my + ny), kara), (Point(mx - nx, my - ny), deniz)):
                for i in agac.query(pt, predicate="within"):
                    oy[i] += 1
    return unary_union([f for f, a, b in zip(yuzler, kara, deniz) if a >= b])


def dis_kabuk(g):
    """İç boşlukları (TKGM ilçe birleşimindeki kıymıklar) doldurur."""
    return unary_union([shapely.Polygon(p.exterior) for p in getattr(g, "geoms", [g])])


def paylastir(il, ilceler):
    """İli ilçelere boşluksuz/örtüşmesiz böler: her ilçenin yalnız kendine ait
    kısmı korunur, kalan (örtüşme, boşluk, kıyı şeridi, adalar) en yakın ilçe
    sınırına göre Voronoi ile paylaştırılır."""
    adlar = list(ilceler)
    G = [ilceler[n] for n in adlar]
    cekirdek = [shapely.make_valid(g.difference(unary_union(G[:i] + G[i + 1:]))).intersection(il)
                for i, g in enumerate(G)]
    kalan = il.difference(unary_union(cekirdek))
    noktalar, etiket = [], []
    for i, c in enumerate(cekirdek):
        b = c.boundary
        for t in np.arange(0, b.length, VORONOI_ADIM):
            p = b.interpolate(t)
            noktalar.append((p.x, p.y))
            etiket.append(i)
    noktalar, etiket = np.round(np.array(noktalar), 7), np.array(etiket)
    noktalar, tekil = np.unique(noktalar, axis=0, return_index=True)
    etiket = etiket[tekil]
    hucre = shapely.voronoi_polygons(shapely.multipoints(noktalar), extend_to=box(*KUTU).buffer(0.5))
    hucreler = np.array(hucre.geoms)
    # voronoi_polygons hücre sırasını garanti etmez → her hücreyi içindeki noktayla eşle
    agac = shapely.STRtree(hucreler)
    eslesme = agac.query(shapely.points(noktalar), predicate="within")
    bolge = {i: [] for i in range(len(adlar))}
    for nokta_i, hucre_i in zip(*eslesme):
        bolge[etiket[nokta_i]].append(hucreler[hucre_i])
    sonuc = {}
    for i, n in enumerate(adlar):
        ek = kalan.intersection(unary_union(bolge[i])) if bolge[i] else shapely.Polygon()
        sonuc[n] = shapely.make_valid(unary_union([cekirdek[i], ek]))
    return sonuc


# TKGM bazı adlarda "ı" yerine "i" yazar (Bayindir, Kinik …)
AD_DUZELTME = {"Bayindir": "Bayındır", "Bayrakli": "Bayraklı", "Karşiyaka": "Karşıyaka",
               "Kinik": "Kınık", "Narlidere": "Narlıdere", "Torbali": "Torbalı"}


def km2(g):
    """Derece alanı → km² (il ortalama enleminde)."""
    return g.area * 111.32 ** 2 * np.cos(np.radians(38.4))


def buyuk_harf(ad):
    """TKGM ilçe adı → geojson'daki büyük harfli Türkçe ad (BAYINDIR, İZMİR…)."""
    return AD_DUZELTME.get(ad, ad).replace("i", "İ").replace("ı", "I").upper()


def kaynaklari_getir():
    """TKGM il / ilçe sınırları, OSM kıyı çizgisi ve OSM il ilişkisi (önbellekli)
    → (iller, ilçe özellikleri, kıyı çizgileri, OSM il poligonu)."""
    os.makedirs(SINIR_HAM_DIR, exist_ok=True)
    iller = _getir(TKGM_URL + "ilListe", "tkgm/il")["features"]
    ilce_f = _getir(TKGM_URL + f"ilceListe/{TKGM_IL_ID}", "tkgm/izmir_ilce")["features"]
    w, s, e, n = KUTU
    kiyi = [LineString([(p["lon"], p["lat"]) for p in yol["geometry"]])
            for yol in _overpass(f'[out:json][timeout:170];way["natural"="coastline"]({s},{w},{n},{e});out geom;',
                                 "kiyi")]
    osm_il = iliski_poligonu(_overpass(
        f'[out:json][timeout:170];rel["ISO3166-2"="{OSM_IL_KODU}"]["admin_level"="4"];out geom;', "il")[0])
    log.info("TKGM: %d ilçe; OSM: %d kıyı yolu", len(ilce_f), len(kiyi))
    return iller, ilce_f, kiyi, osm_il


def il_alani(iller, tkgm, kiyi, osm_il):
    """İl kara alanı: TKGM ilçelerinin dış kabuğu + kıyıdaki eksik + adalar."""
    kara = kara_alani(kiyi)
    T = dis_kabuk(unary_union(list(tkgm.values())))
    komsu = unary_union([shape(f["geometry"]) for f in iller          # bazı illerde geometri boş gelir
                         if f["geometry"] and f["properties"]["id"] != TKGM_IL_ID
                         and shape(f["geometry"]).intersects(box(*KUTU))])
    kiyi_seridi = unary_union(kiyi).buffer(KIYI_PAYI)
    # TKGM kara sınırı OSM'ye göre kırpılmaz: tuzla, lagün ve dolgu alanlarını OSM
    # deniz sayar ama altlık ve TKGM kara sayar. OSM yalnız kıyıdaki eksiği tamamlar.
    ana = unary_union([T, T.buffer(KIYI_PAYI).intersection(kiyi_seridi).difference(komsu).intersection(kara)])
    ana = max(getattr(ana, "geoms", [ana]), key=lambda g: g.area)       # kıyı tamponunun kopuk kırıntıları hariç
    ana = dis_kabuk(ana)    # il içinde kalan, TKGM'de hiçbir ilçeye verilmemiş boşluklar (Çeşme–Urla arası)
    # Adalar: OSM'de İzmir ilişkisi içinde kalan, ana karaya değmeyen kara parçaları
    adalar = [p for p in getattr(kara, "geoms", [kara])
              if not p.intersects(ana) and p.representative_point().within(osm_il)]
    log.info("İl: ana kara %.0f km², %d ada %.1f km²; TKGM kara sınırı aynen korunur",
             km2(ana), len(adalar), sum(km2(a) for a in adalar))
    return shapely.make_valid(unary_union([ana] + adalar))


def yaz(adlar, ilce_geo, il):
    ozellik = [{"type": "Feature", "properties": {"ILADI": "İZMİR", "ILCEADI": buyuk_harf(a)},
                "geometry": json.loads(shapely.to_geojson(g))} for a, g in zip(adlar, ilce_geo)]
    json_yaz(ILCE_SINIRLARI, {"type": "FeatureCollection", "features": ozellik})
    json_yaz(IL_SINIRI, {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"name": "İzmir", "kaynak": "TKGM MEGSİS ilçe sınırları + OSM kıyı çizgisi, ilçe birleşimi"},
        "geometry": json.loads(shapely.to_geojson(il))}]})
    log.info("Yazıldı: %d ilçe, kara alanı ~%.0f km², %d köşe; ilçe alanları: %s", len(ilce_geo), km2(il),
             shapely.get_num_coordinates(il), {a: round(km2(g)) for a, g in zip(adlar, ilce_geo)})


def main():
    gunlugu_kur()
    iller, ilce_f, kiyi, osm_il = kaynaklari_getir()
    tkgm = {f["properties"]["text"]: shapely.make_valid(shape(f["geometry"])) for f in ilce_f}
    ilceler = paylastir(il_alani(iller, tkgm, kiyi, osm_il), tkgm)
    adlar = sorted(ilceler)
    ilce_geo = shapely.set_precision(shapely.coverage_simplify(np.array([ilceler[a] for a in adlar]), SADELESTIRME),
                                     1e-5)
    yaz(adlar, ilce_geo, shapely.set_precision(unary_union(ilce_geo), 1e-5))

if __name__ == "__main__":
    main()
