"""İzmir yol ağlarını OSM'den indirip pgRouting tablolarına yükler.

İki ayrı graf kurulur:
  - drive → izmir_roads_noded (araç tahliye rotası + MVT katmanı)
  - walk  → izmir_yaya_noded  (yaya tahliyesi: patika, merdiven, yaya yolu
            ve servis yolları dahil — OSM'deki yürünebilir her yol)

Akış:
  1. sinir/izmir_sinir.geojson poligonu içindeki ağ osmnx ile
     Overpass'tan indirilir (kavşaklarda düğümlenmiş gelir).
  2. Düğüm yükseklikleri AWS terrain-tiles (SRTM, kimlik doğrulamasız)
     HGT karolarından örneklenir; kenar eğimi (%) hesaplanır.
  3. Kenarlar <tablo>, düğümler <tablo>_vertices_pgr tablolarına yazılır —
     afet.veritabani.depo.AfetDeposu.akilli_rota'un beklediği şema.

Çalıştırma: venv/bin/python -m hesap.yol_agi_kur [drive|walk|all] [--pbf dosya]
  --pbf: Overpass yoğunken Geofabrik il/ülke dosyasından (ör. turkey-latest.osm.pbf)
         aynı filtre ve osmnx adımlarıyla kurar.
Varsayılan: all. Yeniden çalıştırmak tabloları baştan kurar (idempotent).
"""
import gzip
import logging
import math
import os
import re
import time

import osmnx as ox
import rasterio

from afet import ag
from afet.sinir import il_poligonu
from afet.veritabani.baglanti import db
from afet.yollar import DEM_KARO_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("yol_agi")

OVERPASS_URLS = [u.rsplit("/", 1)[0] for u in ag.OVERPASS_URLS]   # osmnx kök adresi ister
TERRAIN_URL = "https://s3.amazonaws.com/elevation-tiles-prod/skadi/{lat_dir}/{name}.hgt.gz"


# mod → (osmnx network_type, kenar tablosu). Düğüm tablosu "<kenar>_vertices_pgr".
AGLAR = {
    "drive": ("drive", "izmir_roads_noded"),
    "walk": ("walk", "izmir_yaya_noded"),
}


def graf_indir(polygon, network_type):
    log.info("OSM '%s' ağı indiriliyor (Overpass, dakikalar sürebilir)...",
             network_type)
    ox.settings.log_console = False
    ox.settings.requests_timeout = 300
    # Küçük alt sorgular (~300 km²): yoğun sunucuda zaman aşımına düşmez ve
    # her başarılı parça ./cache'e yazılır → yeniden çalıştırma kaldığı yerden sürer
    ox.settings.max_query_area_size = 3e8
    # Kıyıya oturan sınırın on binlerce köşesi Overpass sorgusunu şişirir:
    # ~200 m genişletilmiş sade poligonla indirilir (kıyı yolları kesilmez).
    sorgu = polygon.buffer(0.002).simplify(0.001)
    for i, url in enumerate(OVERPASS_URLS * 2):   # ana sunucu sık 502/kapasite dolu
        ox.settings.overpass_url = url
        try:
            graph = ox.graph_from_polygon(sorgu, network_type=network_type,
                                          simplify=True)
            break
        except Exception as e:
            if i == 2 * len(OVERPASS_URLS) - 1:
                raise
            log.warning("Overpass %s başarısız (%s) — sıradaki deneniyor", url, e)
            time.sleep(30)
    log.info("Graf (%s): %d düğüm, %d kenar",
             network_type, len(graph.nodes), len(graph.edges))
    return graph


def dem_karolari(polygon):
    """Sınırı kapsayan 1°x1° SRTM karolarını indirir, yolları döner."""
    os.makedirs(DEM_KARO_DIR, exist_ok=True)
    min_lon, min_lat, max_lon, max_lat = polygon.bounds
    paths = []
    for lat in range(math.floor(min_lat), math.floor(max_lat) + 1):
        for lon in range(math.floor(min_lon), math.floor(max_lon) + 1):
            name = f"N{lat:02d}E{lon:03d}"
            hgt = os.path.join(DEM_KARO_DIR, f"{name}.hgt")
            if not os.path.exists(hgt):
                log.info("DEM karosu indiriliyor: %s", name)
                gz = ag.getir(TERRAIN_URL.format(lat_dir=f"N{lat:02d}", name=name),
                              timeout=120, dogrula=gzip.decompress)
                with open(hgt + ".tmp", "wb") as f:
                    f.write(gzip.decompress(gz))
                os.replace(hgt + ".tmp", hgt)
            paths.append(hgt)
    return paths


def yukseklik_ornekle(graph, dem_paths):
    """Her düğüme metre cinsinden yükseklik atar (karo başına toplu okuma)."""
    datasets = [rasterio.open(p) for p in dem_paths]
    coords = {n: (d["x"], d["y"]) for n, d in graph.nodes(data=True)}
    elev = {}
    for ds in datasets:
        left, bottom, right, top = ds.bounds
        batch = [(n, xy) for n, xy in coords.items()
                 if n not in elev and left <= xy[0] < right and bottom <= xy[1] < top]
        if not batch:
            continue
        for (n, _), val in zip(batch, ds.sample([xy for _, xy in batch])):
            v = float(val[0])
            elev[n] = v if v > -1000 else 0.0  # nodata → deniz seviyesi
    for ds in datasets:
        ds.close()
    missing = set(coords) - set(elev)
    for n in missing:
        elev[n] = 0.0
    log.info("Yükseklik örneklendi: %d düğüm (%d karo dışı)", len(elev), len(missing))
    return elev


async def tablolari_yaz(graph, elev, edge_table):
    vertex_table = f"{edge_table}_vertices_pgr"
    node_ids = {osmid: i + 1 for i, osmid in enumerate(graph.nodes)}
    async with db.baglan(yazma=True) as conn:
        async with conn.transaction():
            # Geometri, asyncpg binary COPY'de kodlanamadığı için önce EWKT
            # metni olarak yüklenir, sonra SQL ile geometry tipine çevrilir.
            await conn.execute(f"""
                DROP TABLE IF EXISTS {edge_table};
                DROP TABLE IF EXISTS {vertex_table};
                CREATE TABLE {edge_table} (
                    id BIGSERIAL PRIMARY KEY,
                    source BIGINT NOT NULL,
                    target BIGINT NOT NULL,
                    length DOUBLE PRECISION NOT NULL,
                    slope DOUBLE PRECISION,
                    highway TEXT,
                    the_geom TEXT NOT NULL
                );
                CREATE TABLE {vertex_table} (
                    id BIGINT PRIMARY KEY,
                    elevation DOUBLE PRECISION,
                    the_geom TEXT NOT NULL
                );
            """)
            await conn.copy_records_to_table(
                vertex_table,
                records=(
                    (node_ids[n], elev[n], f"SRID=4326;POINT({d['x']} {d['y']})")
                    for n, d in graph.nodes(data=True)
                ),
                columns=["id", "elevation", "the_geom"],
            )
            edge_records = []
            for u, v, data in graph.edges(data=True):
                geom = data.get("geometry")
                if geom is None:
                    xu, yu = graph.nodes[u]["x"], graph.nodes[u]["y"]
                    xv, yv = graph.nodes[v]["x"], graph.nodes[v]["y"]
                    wkt = f"LINESTRING({xu} {yu},{xv} {yv})"
                else:
                    wkt = geom.wkt
                length = float(data.get("length", 0.0)) or 0.1
                slope = abs(elev[u] - elev[v]) / length * 100.0
                hw = data.get("highway")
                if isinstance(hw, list):
                    hw = hw[0]
                edge_records.append((node_ids[u], node_ids[v], length,
                                     min(slope, 40.0), hw, f"SRID=4326;{wkt}"))
            await conn.copy_records_to_table(
                edge_table, records=edge_records,
                columns=["source", "target", "length", "slope", "highway", "the_geom"],
            )
            await conn.execute(f"""
                ALTER TABLE {edge_table}
                    ALTER COLUMN the_geom TYPE GEOMETRY(LineString, 4326)
                    USING ST_GeomFromEWKT(the_geom);
                ALTER TABLE {vertex_table}
                    ALTER COLUMN the_geom TYPE GEOMETRY(Point, 4326)
                    USING ST_GeomFromEWKT(the_geom);
                CREATE INDEX {edge_table}_geom_idx
                    ON {edge_table} USING GIST (the_geom);
                CREATE INDEX {vertex_table}_geom_idx
                    ON {vertex_table} USING GIST (the_geom);
                ANALYZE {edge_table};
                ANALYZE {vertex_table};
            """)
    log.info("%s yazıldı: %d kenar, %d düğüm",
             edge_table, len(edge_records), len(node_ids))


def _filtre(network_type):
    """osmnx'in Overpass ağ filtresi → Python koşulları. Overpass'ta ~ / !~
    kısmi (çapasız) düzenli ifade eşleşmesidir; değer yoksa !~ geçer."""
    from osmnx import _overpass
    kosullar = re.findall(r'\["([^"]+)"(?:(!?~)"([^"]*)")?\]',
                          _overpass._get_network_filter(network_type))
    derli = [(k, op, re.compile(v) if op else None) for k, op, v in kosullar]

    def gecer(tags):
        for k, op, rx in derli:
            v = tags.get(k)
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


def pbf_okuma(pbf, polygon, network_types):
    """Geofabrik .osm.pbf'ten, Overpass yanıtıyla aynı biçimde (osmnx
    response JSON) ağ öğeleri. Tek geçiş: düğüm konumları bellekte tutulur.
    Overpass gibi poligona (osmnx'in 500 m tamponu) en az bir düğümü giren
    yolun tamamı alınır."""
    import osmium
    import shapely
    from osmnx import projection

    proj, crs = projection.project_geometry(polygon)
    tampon, _ = projection.project_geometry(proj.buffer(500), crs=crs, to_latlong=True)
    tampon = tampon.simplify(0.0005)
    shapely.prepare(tampon)
    minx, miny, maxx, maxy = tampon.bounds
    filtreler = {nt: _filtre(nt) for nt in network_types}
    dugum_etiket = set(ox.settings.useful_tags_node)
    yol_etiket = set(ox.settings.useful_tags_way) | {
        k for nt in network_types for k in re.findall(r'\["([^"]+)"', _overpass_filtre(nt))}
    etiketli, yollar = {}, {nt: [] for nt in network_types}
    konum = {}

    fp = osmium.FileProcessor(pbf).with_locations().with_filter(
        osmium.filter.EntityFilter(osmium.osm.NODE | osmium.osm.WAY))
    for o in fp:
        if o.is_node():
            if o.tags and minx <= o.lon <= maxx and miny <= o.lat <= maxy:
                t = {t.k: t.v for t in o.tags if t.k in dugum_etiket}
                if t:
                    etiketli[o.id] = t
            continue
        if "highway" not in o.tags:
            continue
        tags = {t.k: t.v for t in o.tags}
        uyan = [nt for nt, f in filtreler.items() if f(tags)]
        if not uyan:
            continue
        xs = [n.lon for n in o.nodes]
        ys = [n.lat for n in o.nodes]
        if max(xs) < minx or min(xs) > maxx or max(ys) < miny or min(ys) > maxy:
            continue
        if not shapely.contains_xy(tampon, xs, ys).any():
            continue
        ids = [n.ref for n in o.nodes]
        for i, x, y in zip(ids, xs, ys):
            konum[i] = (y, x)
        yol = {"type": "way", "id": o.id, "nodes": ids,
               "tags": {k: v for k, v in tags.items() if k in yol_etiket}}
        for nt in uyan:
            yollar[nt].append(yol)
    log.info("PBF okundu: %s", {nt: len(v) for nt, v in yollar.items()})
    sonuc = {}
    for nt, ws in yollar.items():
        gerekli = {i for w in ws for i in w["nodes"]}
        dugumler = [{"type": "node", "id": i, "lat": konum[i][0], "lon": konum[i][1],
                     "tags": etiketli.get(i, {})} for i in gerekli]
        sonuc[nt] = ({"elements": dugumler + ws}, tampon)
    return sonuc


def _overpass_filtre(nt):
    from osmnx import _overpass
    return _overpass._get_network_filter(nt)


def pbf_grafi(yanit, tampon, polygon, network_type):
    """osmnx.graph_from_polygon'un adımlarının aynısı, indirme yerine PBF."""
    from osmnx import graph as oxg, simplification, truncate
    bidirectional = network_type in ox.settings.bidirectional_network_types
    g = oxg._create_graph([yanit], bidirectional)
    g = truncate.truncate_graph_polygon(g, tampon, truncate_by_edge=False)
    g = truncate.largest_component(g, strongly=False)
    g = simplification.simplify_graph(g)
    g = truncate.truncate_graph_polygon(g, polygon, truncate_by_edge=False)
    g = truncate.largest_component(g, strongly=False)
    log.info("Graf (%s): %d düğüm, %d kenar", network_type, len(g.nodes), len(g.edges))
    return g


async def main(modes, pbf=None):
    polygon = il_poligonu()
    dem_paths = dem_karolari(polygon)
    pbf_veri = pbf_okuma(pbf, polygon, [AGLAR[m][0] for m in modes]) if pbf else None
    async with db.oturum():
        for mode in modes:
            network_type, edge_table = AGLAR[mode]
            if pbf_veri:
                yanit, tampon = pbf_veri.pop(network_type)
                graph = pbf_grafi(yanit, tampon, polygon, network_type)
                del yanit
            else:
                graph = graf_indir(polygon, network_type)
            elev = yukseklik_ornekle(graph, dem_paths)
            await tablolari_yaz(graph, elev, edge_table)
            del graph, elev  # il geneli graf birkaç GB RAM tutar


if __name__ == "__main__":
    import asyncio
    import sys

    args = sys.argv[1:]
    pbf = None
    if "--pbf" in args:                    # Overpass yerine Geofabrik dosyası
        i = args.index("--pbf")
        pbf = args[i + 1]
        del args[i:i + 2]
    arg = args[0] if args else "all"
    if arg not in ("all", *AGLAR):
        raise SystemExit(f"Kullanım: hesap/yol_agi_kur.py [{'|'.join(AGLAR)}|all] [--pbf dosya.osm.pbf]")
    asyncio.run(main(list(AGLAR) if arg == "all" else [arg], pbf))
