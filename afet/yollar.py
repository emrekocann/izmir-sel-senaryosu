"""Projedeki bütün dosya ve klasör yolları — tek yerde.

Kod modülleri yolları kendileri kurmaz, buradan alır; bir klasörün adı ya da
yeri değişirse yalnız bu dosya değişir.

Depoda olanlar: sinir/, sel_model/, dogrulama/, denetim/, egitim/, docs/veri/.
Depoda olmayan (indirilen, yeniden üretilebilir) ham veriler: sel_veri/,
sinir_veri/, itfaiye_veri/, dem_cache/, osm_indirme/.
"""
import os

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _kok(*parca):
    return os.path.join(KOK, *parca)


# İl ve ilçe sınırı (hesap/sinir_hazirla.py üretir)
SINIR_DIR = _kok("sinir")
IL_SINIRI = os.path.join(SINIR_DIR, "izmir_sinir.geojson")
ILCE_SINIRLARI = os.path.join(SINIR_DIR, "izmir_ilce.geojson")

# Ham veri önbellekleri (depoda değil)
SINIR_HAM_DIR = _kok("sinir_veri")                 # TKGM / OSM yanıtları
TKGM_DIR = os.path.join(SINIR_HAM_DIR, "tkgm")
TKGM_ILCE = os.path.join(TKGM_DIR, "izmir_ilce.json")
TKGM_MAHALLE_DIR = os.path.join(TKGM_DIR, "mahalle")
SEL_HAM_DIR = _kok("sel_veri")                     # DEM, arazi örtüsü, OSM çıkarımları
DEM_TIF = os.path.join(SEL_HAM_DIR, "dem_60m.tif")
CN_DOSYASI = os.path.join(SEL_HAM_DIR, "cn_60m_v3.npz")
KOPRU_TUNEL = os.path.join(SEL_HAM_DIR, "kopru_tunel.json")
OSM_ADLI_YOLLAR = os.path.join(SEL_HAM_DIR, "osm_adli_yollar.geojson")
OSM_DERELER = os.path.join(SEL_HAM_DIR, "osm_dereler.json")
DEM_KARO_DIR = _kok("dem_cache")                   # SRTM HGT karoları
OSM_PBF = _kok("osm_indirme", "turkey-latest.osm.pbf")
ITFAIYE_HAM_DIR = _kok("itfaiye_veri")

# Model çıktıları
MODEL_DIR = _kok("sel_model")
DUYARLILIK = os.path.join(MODEL_DIR, "duyarlilik.npz")
SENARYO = os.path.join(MODEL_DIR, "senaryo.npz")
SENARYO_OZETI = os.path.join(MODEL_DIR, "senaryo_ozet.json")

# Doğrulama, denetim ve eğitim çıktıları
DOGRULAMA_DIR = _kok("dogrulama")
OLAY_2021 = os.path.join(DOGRULAMA_DIR, "olay_2021_02_02.json")
SONUC_2021 = os.path.join(DOGRULAMA_DIR, "sonuc_2021_02_02.json")
DENETIM_CSV = _kok("denetim", "toplanma_denetimi.csv")
EGITIM_DIR = _kok("egitim")

# Sunucusuz yayın sitesinin verisi
SITE_VERI_DIR = _kok("docs", "veri")
ROTA_VERI_DIR = os.path.join(SITE_VERI_DIR, "rota")
VITRIN = os.path.join(SITE_VERI_DIR, "vitrin.json")
