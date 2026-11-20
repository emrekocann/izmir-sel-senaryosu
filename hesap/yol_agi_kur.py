"""İzmir yol ağlarını OSM'den indirip pgRouting tablolarına yükler.

İki ayrı graf kurulur:
  - drive → izmir_roads_noded (araç tahliye rotası + MVT katmanı)
  - walk  → izmir_yaya_noded  (yaya tahliyesi: patika, merdiven, yaya yolu
            ve servis yolları dahil — OSM'deki yürünebilir her yol)

Akış:
  1. sinir/izmir_sinir.geojson poligonu içindeki ağ osmnx ile
     Overpass'tan indirilir (kavşaklarda düğümlenmiş gelir).
  2. Düğüm yükseklikleri SRTM karolarından (hesap.dem_hidroloji.dem_karolari)
     örneklenir; kenar eğimi (%) hesaplanır.
  3. Kenarlar <tablo>, düğümler <tablo>_vertices_pgr tablolarına yazılır —
     afet.veritabani.depo.AfetDeposu.akilli_rota'nın beklediği şema.

Çalıştırma: venv/bin/python -m hesap.yol_agi_kur [drive|walk|all] [--pbf dosya]
  --pbf: Overpass yoğunken Geofabrik il/ülke dosyasından (ör. turkey-latest.osm.pbf)
         aynı filtre ve osmnx adımlarıyla kurar.
Varsayılan: all. Yeniden çalıştırmak tabloları baştan kurar (idempotent).
"""
import argparse
import asyncio
import contextlib
import logging
import re
import time

import osmnx as ox
import rasterio

from afet import ag
from afet.sinir import il_poligonu
from afet.veritabani.baglanti import db
from hesap import gunlugu_kur
from hesap.dem_hidroloji import dem_karolari

log = logging.getLogger("yol_agi")

OVERPASS_URLS = [u.rsplit("/", 1)[0] for u in ag.OVERPASS_URLS]   # osmnx kök adresi ister
EN_BUYUK_EGIM = 40.0          # % — DEM gürültüsüyle kısa kenarlarda çıkan uç değerler kırpılır
EN_KISA_KENAR_M = 0.1         # uzunluğu 0 gelen kenar (eğim bölmesi için)

# mod → (osmnx ağ türü, kenar tablosu). Düğüm tablosu "<kenar>_vertices_pgr".
AGLAR = {
    "drive": ("drive", "izmir_roads_noded"),
    "walk": ("walk", "izmir_yaya_noded"),
}

# Geometri, asyncpg binary COPY'de kodlanamadığı için önce EWKT metni olarak
# yüklenir, sonra SQL ile geometry tipine çevrilir.
TABLOLARI_KUR = """
    DROP TABLE IF EXISTS {kenar};
    DROP TABLE IF EXISTS {dugum};
    CREATE TABLE {kenar} (
        id BIGSERIAL PRIMARY KEY,
        source BIGINT NOT NULL,
        target BIGINT NOT NULL,
        length DOUBLE PRECISION NOT NULL,
        slope DOUBLE PRECISION,
        highway TEXT,
        the_geom TEXT NOT NULL
    );
    CREATE TABLE {dugum} (
        id BIGINT PRIMARY KEY,
        elevation DOUBLE PRECISION,
        the_geom TEXT NOT NULL
    );
"""
GEOMETRIYE_CEVIR = """
    ALTER TABLE {kenar}
        ALTER COLUMN the_geom TYPE GEOMETRY(LineString, 4326)
        USING ST_GeomFromEWKT(the_geom);
    ALTER TABLE {dugum}
        ALTER COLUMN the_geom TYPE GEOMETRY(Point, 4326)
        USING ST_GeomFromEWKT(the_geom);
    CREATE INDEX {kenar}_geom_idx
        ON {kenar} USING GIST (the_geom);
    CREATE INDEX {dugum}_geom_idx
        ON {dugum} USING GIST (the_geom);
    ANALYZE {kenar};
    ANALYZE {dugum};
"""
KENAR_KOLONLARI = ["source", "target", "length", "slope", "highway", "the_geom"]
DUGUM_KOLONLARI = ["id", "elevation", "the_geom"]


# ── Graf: Overpass ya da Geofabrik PBF ──────────────────────────────────────

def graf_indir(poligon, ag_turu):
    log.info("OSM '%s' ağı indiriliyor (Overpass, dakikalar sürebilir)...", ag_turu)
    ox.settings.log_console = False
    ox.settings.requests_timeout = 300
    # Küçük alt sorgular (~300 km²): yoğun sunucuda zaman aşımına düşmez ve
    # her başarılı parça ./cache'e yazılır → yeniden çalıştırma kaldığı yerden sürer
    ox.settings.max_query_area_size = 3e8
    # Kıyıya oturan sınırın on binlerce köşesi Overpass sorgusunu şişirir:
    # ~200 m genişletilmiş sade poligonla indirilir (kıyı yolları kesilmez).
    sorgu = poligon.buffer(0.002).simplify(0.001)
    adresler = OVERPASS_URLS * 2                  # ana sunucu sık 502/kapasite dolu
    for sira, url in enumerate(adresler, 1):
        ox.settings.overpass_url = url
        try:
            graf = ox.graph_from_polygon(sorgu, network_type=ag_turu, simplify=True)
            break
        except Exception as e:
            if sira == len(adresler):
                raise
            log.warning("Overpass %s başarısız (%s) — sıradaki deneniyor", url, e)
            time.sleep(30)
    log.info("Graf (%s): %d düğüm, %d kenar", ag_turu, len(graf.nodes), len(graf.edges))
    return graf


def _overpass_filtre(ag_turu):
    """osmnx'in bu ağ türü için kullandığı Overpass yol filtresi (metin)."""
    from osmnx import _overpass
    return _overpass._get_network_filter(ag_turu)


def _filtre(ag_turu):
    """osmnx'in Overpass ağ filtresi → Python koşulu (etiketler → bool). Overpass'ta
    ~ / !~ kısmi (çapasız) düzenli ifade eşleşmesidir; değer yoksa !~ geçer."""
    kosullar = re.findall(r'\["([^"]+)"(?:(!?~)"([^"]*)")?\]', _overpass_filtre(ag_turu))
    derli = [(k, op, re.compile(v) if op else None) for k, op, v in kosullar]

    def gecer(etiketler):
        for k, op, rx in derli:
            v = etiketler.get(k)
            if not op:
                if v is None:
                    return False
            elif op == "~":
                if v is None or not rx.search(v):
                    return False
            elif v is not None and rx.search(v):
                return False
        return True
    return gecer


def _pbf_tamponu(poligon):
    """osmnx'in Overpass sorgusundaki gibi poligonun 500 m tamponu (sade, hazır)."""
    import shapely
    from osmnx import projection
    proj, crs = projection.project_geometry(poligon)
    tampon, _ = projection.project_geometry(proj.buffer(500), crs=crs, to_latlong=True)
    tampon = tampon.simplify(0.0005)
    shapely.prepare(tampon)
    return tampon


def pbf_okuma(pbf, poligon, ag_turleri):
    """Geofabrik .osm.pbf'ten, Overpass yanıtıyla aynı biçimde (osmnx
    response JSON) ağ öğeleri: ağ türü → (yanıt, tampon). Tek geçiş: düğüm
    konumları bellekte tutulur. Overpass gibi tampona en az bir düğümü giren
    yolun tamamı alınır."""
    import osmium
    import shapely

    tampon = _pbf_tamponu(poligon)
    minx, miny, maxx, maxy = tampon.bounds
    filtreler = {nt: _filtre(nt) for nt in ag_turleri}
    dugum_etiket = set(ox.settings.useful_tags_node)
    yol_etiket = set(ox.settings.useful_tags_way) | {
        k for nt in ag_turleri for k in re.findall(r'\["([^"]+)"', _overpass_filtre(nt))}
    etiketli, konum, yollar = {}, {}, {nt: [] for nt in ag_turleri}

    dosya = osmium.FileProcessor(pbf).with_locations().with_filter(
        osmium.filter.EntityFilter(osmium.osm.NODE | osmium.osm.WAY))
    for o in dosya:
        if o.is_node():
            if o.tags and minx <= o.lon <= maxx and miny <= o.lat <= maxy:
                t = {t.k: t.v for t in o.tags if t.k in dugum_etiket}
                if t:
                    etiketli[o.id] = t
            continue
        if "highway" not in o.tags:
            continue
        etiketler = {t.k: t.v for t in o.tags}
        uyan = [nt for nt, gecer in filtreler.items() if gecer(etiketler)]
        if not uyan:
            continue
        xs, ys = [n.lon for n in o.nodes], [n.lat for n in o.nodes]
        if max(xs) < minx or min(xs) > maxx or max(ys) < miny or min(ys) > maxy:
            continue
        if not shapely.contains_xy(tampon, xs, ys).any():
            continue
        kimlikler = [n.ref for n in o.nodes]
        for k, x, y in zip(kimlikler, xs, ys):
            konum[k] = (y, x)
        yol = {"type": "way", "id": o.id, "nodes": kimlikler,
               "tags": {k: v for k, v in etiketler.items() if k in yol_etiket}}
        for nt in uyan:
            yollar[nt].append(yol)
    log.info("PBF okundu: %s", {nt: len(v) for nt, v in yollar.items()})
    return {nt: (_overpass_yaniti(ws, konum, etiketli), tampon) for nt, ws in yollar.items()}


def _overpass_yaniti(yollar, konum, etiketli):
    """Yollar + kullandıkları düğümler → Overpass JSON yanıtı."""
    gerekli = {k for w in yollar for k in w["nodes"]}
    dugumler = [{"type": "node", "id": k, "lat": konum[k][0], "lon": konum[k][1],
                 "tags": etiketli.get(k, {})} for k in gerekli]
    return {"elements": dugumler + yollar}


def pbf_grafi(yanit, tampon, poligon, ag_turu):
    """osmnx.graph_from_polygon'un adımlarının aynısı, indirme yerine PBF."""
    from osmnx import graph as oxg
    from osmnx import simplification, truncate
    iki_yonlu = ag_turu in ox.settings.bidirectional_network_types
    g = oxg._create_graph([yanit], iki_yonlu)
    g = truncate.truncate_graph_polygon(g, tampon, truncate_by_edge=False)
    g = truncate.largest_component(g, strongly=False)
    g = simplification.simplify_graph(g)
    g = truncate.truncate_graph_polygon(g, poligon, truncate_by_edge=False)
    g = truncate.largest_component(g, strongly=False)
    log.info("Graf (%s): %d düğüm, %d kenar", ag_turu, len(g.nodes), len(g.edges))
    return g


# ── Yükseklik ve tablo kayıtları ────────────────────────────────────────────

def yukseklik_ornekle(graf, dem_yollari):
    """Her düğüme metre cinsinden yükseklik atar (karo başına toplu okuma);
    karo dışı ya da veri yok → 0 (deniz seviyesi)."""
    konumlar = {n: (d["x"], d["y"]) for n, d in graf.nodes(data=True)}
    yukseklik = {}
    with contextlib.ExitStack() as yigin:
        for ds in (yigin.enter_context(rasterio.open(p)) for p in dem_yollari):
            bati, guney, dogu, kuzey = ds.bounds
            toplu = [(n, xy) for n, xy in konumlar.items()
                     if n not in yukseklik and bati <= xy[0] < dogu and guney <= xy[1] < kuzey]
            for (n, _), deger in zip(toplu, ds.sample([xy for _, xy in toplu])):
                v = float(deger[0])
                yukseklik[n] = v if v > -1000 else 0.0
    eksik = set(konumlar) - set(yukseklik)
    for n in eksik:
        yukseklik[n] = 0.0
    log.info("Yükseklik örneklendi: %d düğüm (%d karo dışı)", len(yukseklik), len(eksik))
    return yukseklik


def dugum_numaralari(graf):
    """OSM düğüm kimliği → pgRouting düğüm no (1'den)."""
    return {osmid: i + 1 for i, osmid in enumerate(graf.nodes)}


def dugum_kayitlari(graf, yukseklik, no):
    return [(no[n], yukseklik[n], f"SRID=4326;POINT({d['x']} {d['y']})") for n, d in graf.nodes(data=True)]


def kenar_kayitlari(graf, yukseklik, no):
    """(source, target, length m, eğim %, highway, EWKT) — KENAR_KOLONLARI sırasıyla."""
    kayitlar = []
    for u, v, d in graf.edges(data=True):
        geom = d.get("geometry")
        if geom is None:
            a, b = graf.nodes[u], graf.nodes[v]
            wkt = f"LINESTRING({a['x']} {a['y']},{b['x']} {b['y']})"
        else:
            wkt = geom.wkt
        uzunluk = float(d.get("length", 0.0)) or EN_KISA_KENAR_M
        egim = abs(yukseklik[u] - yukseklik[v]) / uzunluk * 100.0
        yol_turu = d.get("highway")
        if isinstance(yol_turu, list):
            yol_turu = yol_turu[0]
        kayitlar.append((no[u], no[v], uzunluk, min(egim, EN_BUYUK_EGIM), yol_turu, f"SRID=4326;{wkt}"))
    return kayitlar


async def tablolari_yaz(graf, yukseklik, kenar_tablosu):
    dugum_tablosu = f"{kenar_tablosu}_vertices_pgr"
    no = dugum_numaralari(graf)
    kenarlar = kenar_kayitlari(graf, yukseklik, no)
    adlar = {"kenar": kenar_tablosu, "dugum": dugum_tablosu}
    async with db.baglan(yazma=True) as conn:
        async with conn.transaction():
            await conn.execute(TABLOLARI_KUR.format(**adlar))
            await conn.copy_records_to_table(dugum_tablosu, records=dugum_kayitlari(graf, yukseklik, no),
                                             columns=DUGUM_KOLONLARI)
            await conn.copy_records_to_table(kenar_tablosu, records=kenarlar, columns=KENAR_KOLONLARI)
            await conn.execute(GEOMETRIYE_CEVIR.format(**adlar))
    log.info("%s yazıldı: %d kenar, %d düğüm", kenar_tablosu, len(kenarlar), len(no))


# ── Çalıştırma ──────────────────────────────────────────────────────────────

async def kur(modlar, pbf=None):
    poligon = il_poligonu()
    dem_yollari = dem_karolari(poligon)
    pbf_veri = pbf_okuma(pbf, poligon, [AGLAR[m][0] for m in modlar]) if pbf else None
    async with db.oturum():
        for mod in modlar:
            ag_turu, kenar_tablosu = AGLAR[mod]
            if pbf_veri:
                yanit, tampon = pbf_veri.pop(ag_turu)
                graf = pbf_grafi(yanit, tampon, poligon, ag_turu)
                del yanit
            else:
                graf = graf_indir(poligon, ag_turu)
            yukseklik = yukseklik_ornekle(graf, dem_yollari)
            await tablolari_yaz(graf, yukseklik, kenar_tablosu)
            del graf, yukseklik  # il geneli graf birkaç GB RAM tutar


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m hesap.yol_agi_kur", description=__doc__.split("\n", 1)[0])
    p.add_argument("mod", nargs="?", default="all", choices=["all", *AGLAR])
    p.add_argument("--pbf", help="Overpass yerine Geofabrik .osm.pbf dosyası")
    a = p.parse_args(argv)
    gunlugu_kur()
    asyncio.run(kur(list(AGLAR) if a.mod == "all" else [a.mod], a.pbf))


if __name__ == "__main__":
    main()
