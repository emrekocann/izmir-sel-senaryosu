"""İl ve ilçe sınırları — tek kaynaktan.

İl çerçevesi ve merkez noktası koda yazılmaz, sinir/izmir_sinir.geojson
dosyasından türetilir; sistemi başka bir ile taşımak için o dosyayı (ve
hesap/sinir_hazirla.py'deki il kimliğini) değiştirmek yeterlidir.

TKGM ilçe ve mahalle poligonları (sinir_veri/tkgm, hesap/sinir_hazirla.py
indirir) da buradan okunur.
"""
import glob
import os

from afet.dosya import json_oku
from afet.yollar import IL_SINIRI, TKGM_ILCE, TKGM_MAHALLE_DIR

# Sınırın hemen dışındaki olayları da yakalamak için derece cinsinden pay
PAY = 0.05


def _koordinatlar(geom):
    if geom["type"] == "Polygon":
        for halka in geom["coordinates"]:
            yield from halka
    elif geom["type"] == "MultiPolygon":
        for poligon in geom["coordinates"]:
            for halka in poligon:
                yield from halka


def cerceve_hesapla(yol: str = IL_SINIRI, pay: float = PAY) -> dict:
    """Sınır dosyasının (+pay) çerçevesi: lat_min, lat_max, lon_min, lon_max."""
    boylamlar, enlemler = [], []
    for oge in json_oku(yol).get("features", []):
        for lon, lat in _koordinatlar(oge.get("geometry", {})):
            boylamlar.append(lon)
            enlemler.append(lat)
    if not boylamlar:
        raise ValueError(f"Sınır dosyasında koordinat bulunamadı: {yol}")
    return {
        "lat_min": round(min(enlemler) - pay, 4),
        "lat_max": round(max(enlemler) + pay, 4),
        "lon_min": round(min(boylamlar) - pay, 4),
        "lon_max": round(max(boylamlar) + pay, 4),
    }


CERCEVE = cerceve_hesapla()
MERKEZ_ENLEM = round((CERCEVE["lat_min"] + CERCEVE["lat_max"]) / 2, 4)
MERKEZ_BOYLAM = round((CERCEVE["lon_min"] + CERCEVE["lon_max"]) / 2, 4)


def cercevede(lat: float, lon: float) -> bool:
    """Nokta il çerçevesinin (+pay) içinde mi?"""
    return (CERCEVE["lat_min"] <= lat <= CERCEVE["lat_max"]
            and CERCEVE["lon_min"] <= lon <= CERCEVE["lon_max"])


def il_poligonu(yol: str = IL_SINIRI):
    """İl sınırı (shapely): dosyadaki bütün parçaların birleşimi."""
    from shapely.geometry import shape
    from shapely.ops import unary_union
    return unary_union([shape(oge["geometry"]) for oge in json_oku(yol)["features"]])


def tkgm_ilceler() -> list:
    """TKGM ilçeleri: [(kimlik, ad, GeoJSON geometrisi)]."""
    return [(oge["properties"]["id"], oge["properties"]["text"], oge["geometry"])
            for oge in json_oku(TKGM_ILCE)["features"]]


def tkgm_mahalleler():
    """TKGM mahalleleri, ilçe dosyası sırasıyla: (ilçe kimliği, mahalle adı,
    GeoJSON geometrisi). Geometrisi boş kayıtlar atlanır."""
    for yol in sorted(glob.glob(os.path.join(TKGM_MAHALLE_DIR, "*.json"))):
        ilce_kimlik = int(os.path.basename(yol)[:-5])
        for oge in json_oku(yol)["features"]:
            if oge["geometry"]:
                yield ilce_kimlik, oge["properties"]["text"], oge["geometry"]
