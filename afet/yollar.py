"""Projedeki bütün dosya ve klasör yolları — tek yerde.

Kod modülleri yolları kendileri kurmaz, buradan alır; bir klasörün adı ya da
yeri değişirse yalnız bu dosya değişir.

Depoda olanlar: sinir/, sel_model/, dogrulama/, denetim/, egitim/, docs/veri/.
Depoda olmayan (indirilen, yeniden üretilebilir) ham veriler: sel_veri/,
sinir_veri/, itfaiye_veri/, dem_cache/, osm_indirme/; sunucu günlükleri: logs/.
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
ITFAIYE_HAM_DIR = _kok("itfaiye_veri")              # itfaiye çağrıları, nüfus, hava arşivi yanıtları

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

# Erken uyarı (GeoAI): eğitim verisi ve sonuçları
EGITIM_DIR = _kok("egitim")
ILCE_GUN_CSV = os.path.join(EGITIM_DIR, "ilce_gun.csv")              # hesap/ilce_gun.py
ILCE_CSV = os.path.join(EGITIM_DIR, "ilce.csv")
OLS_SONUC = os.path.join(EGITIM_DIR, "ols_sonuc.json")               # hesap/ols_model.py
SINIFLANDIRMA_SONUC = os.path.join(EGITIM_DIR, "siniflandirma_sonuc.json")
TAHMIN_SINAMASI_SONUC = os.path.join(EGITIM_DIR, "tahmin_sinamasi.json")
GUVENILIRLIK_SONUC = os.path.join(EGITIM_DIR, "guvenilirlik.json")
GWR_SONUC = os.path.join(EGITIM_DIR, "gwr_sonuc.json")

# Sunucusuz yayın sitesi (GitHub Pages kökü) ve verisi
SITE_DIR = _kok("docs")
SITE_VERI_DIR = os.path.join(SITE_DIR, "veri")
VITRIN = os.path.join(SITE_VERI_DIR, "vitrin.json")                  # hesap/vitrin_hazirla.py
SENARYO_PNG_DIR = os.path.join(SITE_VERI_DIR, "senaryo")             # {mm}_{saat}.png
SITE_IL_SINIRI = os.path.join(SITE_VERI_DIR, "izmir_sinir.geojson")
DENETIM_JSON = os.path.join(SITE_VERI_DIR, "denetim.json")           # hesap/toplanma_denetimi.py
SITE_DENETIM_CSV = os.path.join(SITE_VERI_DIR, "toplanma_denetimi.csv")
UYARI_JSON = os.path.join(SITE_VERI_DIR, "uyari.json")               # hesap/uyari_hazirla.py
UYARI_MODEL_JSON = os.path.join(SITE_VERI_DIR, "uyari_model.json")
ROTA_VERI_DIR = os.path.join(SITE_VERI_DIR, "rota")                  # hesap/rota_agi_hazirla.py
ROTA_AGI = os.path.join(ROTA_VERI_DIR, "ag.json")

# Sunucu günlükleri (depoda değil)
GUNLUK_DIR = _kok("logs")
