"""İl sınırını statik koddan değil, sınır GeoJSON dosyasından okur.

Sistemi başka bir ile taşımak için static/izmir_sinir.geojson dosyasını
o ilin sınır poligonu ile değiştirmek yeterlidir; bounding box, merkez
noktası ve AFAD sorgu parametreleri buradan otomatik türetilir.
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOUNDARY_FILE = os.path.join(BASE_DIR, "static", "izmir_sinir.geojson")

# Sınırın hemen dışındaki olayları da yakalamak için derece cinsinden pay
MARGIN = 0.05


def _iter_coords(geom):
    if geom["type"] == "Polygon":
        for ring in geom["coordinates"]:
            yield from ring
    elif geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            for ring in poly:
                yield from ring


def load_bounds(path: str = BOUNDARY_FILE, margin: float = MARGIN) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        gj = json.load(f)

    lons, lats = [], []
    for feature in gj.get("features", []):
        for lon, lat in _iter_coords(feature.get("geometry", {})):
            lons.append(lon)
            lats.append(lat)

    if not lons:
        raise ValueError(f"Sınır dosyasında koordinat bulunamadı: {path}")

    return {
        "lat_min": round(min(lats) - margin, 4),
        "lat_max": round(max(lats) + margin, 4),
        "lon_min": round(min(lons) - margin, 4),
        "lon_max": round(max(lons) + margin, 4),
    }


BOUNDS = load_bounds()
CENTER_LAT = round((BOUNDS["lat_min"] + BOUNDS["lat_max"]) / 2, 4)
CENTER_LON = round((BOUNDS["lon_min"] + BOUNDS["lon_max"]) / 2, 4)

def cercevede(lat: float, lon: float) -> bool:
    """Nokta il çerçevesinin (+pay) içinde mi?"""
    return (BOUNDS["lat_min"] <= lat <= BOUNDS["lat_max"]
            and BOUNDS["lon_min"] <= lon <= BOUNDS["lon_max"])
