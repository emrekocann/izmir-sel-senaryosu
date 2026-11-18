"""Sel hesaplarının (duyarlılık haritası ve yağış senaryosu) ortak yükseklik /
akış altyapısı. Çevrimdışı betikler kullanır; çalışma zamanında yüklenmez.

  dem_mozaik   SRTM karolarını il çerçevesi + tampon için ~60 m'ye ortalar
  akis_agi     çukur doldurma, akış yönü, birikim, hücre alanları
  hand_hesapla en yakın dere hücresine göre yükseklik (HAND) ve o hücrenin indisi
  cukurlar     kapalı çukurlar (derinlik, etiket)
  kopru_tunel  OSM köprü / alt geçit / uzun tünel çizgileri
  osm_cizgileri  Geofabrik PBF dosyasından çerçevedeki seçili yollar / dereler
  yol_noktalari, raster_ornekle, yakin_mi  yol ağını ızgarayla eşleme
"""
import logging
import os
import time

import numpy as np
import shapely
from scipy import ndimage

from afet import ag
from afet.yollar import DEM_TIF, KOPRU_TUNEL, OSM_PBF, SEL_HAM_DIR

log = logging.getLogger("dem")

COZUNURLUK = 2 / 3600          # 2 açı-saniye ≈ 62 m (enlem) × 48 m (boylam)
TAMPON = 0.15                  # il dışına taşan havzaların bir kısmı için (derece)
DIRMAP = (64, 128, 1, 2, 4, 8, 16, 32)               # pysheds D8: K KD D GD G GB B KB
VERI_YOK = -9999
ORNEK_ARALIK = 0.00025         # yol örnekleme aralığı ≈ 25 m (derece)
ALT_GECIT_MAX_M = 400          # bundan kısa tünel kentte alt geçittir


def dem_mozaik(sinir):
    """SRTM karolarını il çerçevesi + tampon için ~60 m'ye ortalar (bir kez)."""
    if os.path.exists(DEM_TIF):
        return
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.merge import merge
    from hesap.yol_agi_kur import fetch_dem_tiles
    os.makedirs(SEL_HAM_DIR, exist_ok=True)
    minx, miny, maxx, maxy = sinir.bounds
    b = (minx - TAMPON, miny - TAMPON, maxx + TAMPON, maxy + TAMPON)
    ds = [rasterio.open(p) for p in fetch_dem_tiles(sinir.buffer(TAMPON))]
    arr, tr = merge(ds, bounds=b, res=COZUNURLUK, resampling=Resampling.average, nodata=-32768)
    for d in ds:
        d.close()
    z = arr[0].astype(np.float32)
    z[(z <= 0) | (z < -1000)] = VERI_YOK          # deniz ve boşluklar: veri yok
    with rasterio.open(DEM_TIF, "w", driver="GTiff", height=z.shape[0], width=z.shape[1],
                       count=1, dtype="float32", crs="EPSG:4326", transform=tr,
                       nodata=VERI_YOK, compress="deflate") as out:
        out.write(z, 1)
    log.info("DEM mozaiği: %d×%d", *z.shape)


def akis_agi():
    """DEM'den akış ağı. Dönüş sözlüğü:
    grid, fdir, duz (düzlükleri çözülmüş dolu DEM), acc (birikim, hücre sayısı),
    tr, alan (hücre alanı m², enleme göre), hucre_km2 (ortalama), drenaj_km2,
    veri_yok, taban (yalnız tek hücrelik çukurları dolu DEM), tasma (dolu DEM)."""
    from pysheds.grid import Grid
    if not hasattr(np, "in1d"):        # pysheds 0.5, numpy 2.4'te kaldırılan in1d'yi kullanıyor
        np.in1d = np.isin
    t = time.time()
    grid = Grid.from_raster(DEM_TIF)
    dem = grid.read_raster(DEM_TIF)
    veri_yok = np.asarray(dem) == VERI_YOK
    # pysheds doldurmayı girdinin üstüne yazar: çukur tabanı için kopya alınır
    pit = grid.fill_pits(dem)
    taban = np.array(pit, np.float32, copy=True)
    dolu = grid.fill_depressions(pit)
    tasma = np.array(dolu, np.float32, copy=True)
    duz = grid.resolve_flats(dolu)
    fdir = grid.flowdir(duz, dirmap=DIRMAP)
    acc = grid.accumulation(fdir, dirmap=DIRMAP)
    tr = grid.affine
    h, w = veri_yok.shape
    lat = tr.f + (np.arange(h) + 0.5) * tr.e
    dy_m = abs(tr.e) * 111320.0
    dx_m = tr.a * 111320.0 * np.cos(np.radians(lat))
    alan = np.repeat((dx_m * dy_m)[:, None], w, axis=1).astype(np.float32)
    hucre_km2 = float(alan.mean()) / 1e6
    log.info("Akış yönü + birikim: %.0f sn", time.time() - t)
    return dict(grid=grid, fdir=fdir, duz=duz, acc=acc, tr=tr, alan=alan, hucre_km2=hucre_km2,
                dx_m=dx_m, dy_m=dy_m, drenaj_km2=np.asarray(acc, np.float32) * hucre_km2,
                veri_yok=veri_yok, taban=taban, tasma=tasma)


def hand_hesapla(agi, esik_km2):
    """Drenaj alanı ≥ esik_km2 olan hücreler dere sayılır. Dönüş:
    (hand m — dere bağlantısı yoksa inf, en yakın dere hücresinin düz indisi
    — yoksa -1, dere maskesi)."""
    t = time.time()
    dere_r = agi["acc"] >= esik_km2 / agi["hucre_km2"]          # pysheds Raster olarak kalmalı
    idx = np.asarray(agi["grid"].compute_hand(agi["fdir"], agi["duz"], dere_r, dirmap=DIRMAP,
                                              return_index=True)).astype(np.int64)
    z = np.asarray(agi["duz"], np.float32).ravel()
    h = np.full(idx.size, np.inf, np.float32)
    ok = idx.ravel() >= 0
    h[ok] = z[ok] - z[idx.ravel()[ok]]
    log.info("HAND (≥%g km²): %.0f sn", esik_km2, time.time() - t)
    return h.reshape(idx.shape), idx, np.asarray(dere_r, bool)


def cukurlar(agi, en_az_m=0.1, en_cok_m=10.0):
    """Kapalı çukurlar: (derinlik m, etiket 1..n, çukur sayısı, derin).
    derin[i] True ise i+1 nolu çukur en_cok_m'den derindir (baraj gölü, taş
    ocağı, SRTM hatası ya da geniş ova düzlüğü); derinliği 0 sayılır, etiketi
    korunur (dolgu hesabından çıkarmak çağıranın işi)."""
    d = np.where(agi["veri_yok"], 0, agi["tasma"] - agi["taban"])
    etiket, n = ndimage.label(d > en_az_m)
    derin = ndimage.maximum(d, etiket, index=np.arange(1, n + 1)) > en_cok_m
    d[np.isin(etiket, np.flatnonzero(derin) + 1)] = 0
    log.info("Çukur: %d (%d tanesi %g m'den derin)", n, int(derin.sum()), en_cok_m)
    return d, etiket, n, derin


def kopru_tunel(sinir):
    """OSM yol köprüleri ve tünelleri (tek Overpass sorgusu, önbellekli):
    (köprüler, alt geçitler, uzun tüneller) çizgi listeleri."""
    minx, miny, maxx, maxy = sinir.bounds
    elems = ag.overpass(f"""[out:json][timeout:180];
        way[highway][~"^(bridge|tunnel)$"~"."]({miny},{minx},{maxy},{maxx});
        out tags geom;""", KOPRU_TUNEL, timeout=240)
    kopru, alt_gecit, uzun_tunel = [], [], []
    for e in elems:
        tg, geom = e.get("tags", {}), e.get("geometry") or []
        if len(geom) < 2:
            continue
        line = shapely.LineString([(p["lon"], p["lat"]) for p in geom])
        if tg.get("bridge", "no") != "no":
            kopru.append(line)
        elif tg.get("tunnel", "no") not in ("no", "building_passage", "passage"):
            uzun = line.length * 111_320 * 0.79 > ALT_GECIT_MAX_M
            (uzun_tunel if uzun else alt_gecit).append(line)
    log.info("OSM: %d köprü, %d alt geçit, %d uzun tünel", len(kopru), len(alt_gecit), len(uzun_tunel))
    return kopru, alt_gecit, uzun_tunel


def osm_cizgileri(cerceve, secici, pbf=OSM_PBF):
    """PBF dosyasındaki çizgilerden (way) çerçeveye (batı, güney, doğu, kuzey)
    değenler: (secici(etiketler), etiketler, [(lon, lat), …]). secici None
    dönerse çizgi atlanır. Etiketler yalnız döngü adımı içinde geçerlidir."""
    import osmium
    x0, y0, x1, y1 = cerceve
    fp = osmium.FileProcessor(pbf).with_locations().with_filter(
        osmium.filter.EntityFilter(osmium.osm.WAY))
    for o in fp:
        tur = secici(o.tags)
        if tur is None:
            continue
        try:
            xy = [(n.lon, n.lat) for n in o.nodes]
        except osmium.InvalidLocationError:
            continue
        xs, ys = [p[0] for p in xy], [p[1] for p in xy]
        if len(xy) < 2 or max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
            continue
        yield tur, o.tags, xy


def yol_noktalari(wkb_listesi):
    """Kenarları ~25 m'de bir örnekler: (geometriler, x, y, kenar indisi)."""
    geoms = shapely.segmentize(shapely.from_wkb(wkb_listesi), ORNEK_ARALIK)
    xy, ki = shapely.get_coordinates(geoms, return_index=True)
    return geoms, xy[:, 0], xy[:, 1], ki


def raster_ornekle(s, tr, x, y):
    """Noktalardaki ızgara değeri (ızgara dışı 0)."""
    c = np.floor((x - tr.c) / tr.a).astype(int)
    r = np.floor((y - tr.f) / tr.e).astype(int)
    ok = (r >= 0) & (r < s.shape[0]) & (c >= 0) & (c < s.shape[1])
    out = np.zeros(len(x), dtype=np.float32)
    out[ok] = s[r[ok], c[ok]]
    return out


def yakin_mi(x, y, cizgiler, tampon):
    """Noktalar çizgilere `tampon` dereceden yakın mı (STRtree)?"""
    out = np.zeros(len(x), dtype=bool)
    if cizgiler:
        agac = shapely.STRtree(shapely.buffer(cizgiler, tampon))
        out[agac.query(shapely.points(x, y), predicate="intersects")[0]] = True
    return out
