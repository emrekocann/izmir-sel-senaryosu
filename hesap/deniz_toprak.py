"""Toprak nemi ve deniz kabarması: hesap/ek_degiskenler.py'nin sınadığı iki ek değişken.

  • toprak_nemi: günün başında (00:00) toprağın üst 28 cm'sindeki su payı
    (m³/m³, iki katmanın kalınlık ağırlıklı ortalaması; ERA5-Land, Open-Meteo
    geçmiş arşivi). Toprağın önceki yağışlarla ne kadar doyduğunu doğrudan
    ölçer; modelde bu şimdiye kadar "önceki 7 günün yağışı" ile dolaylı
    ölçülüyordu. Günün başındaki değer alınır: o günün yağışını içermez.
  • kabarma_cm: kıyı ilçelerinde denizin hava yüzünden kabarması (cm). Kıyıda
    yağmur suyu kabaran denize akamaz. Geçmiş deniz seviyesi Open-Meteo'da yalnız
    2023'ten beri ve boşluklu (ör. Şubat 2025 yok); model 2020'den eğitildiği
    için gösterge 2020'den beri eksiksiz olan iki veriden kurulur: günün en
    düşük basıncı (alçak basınç denizi yükseltir) ve lodos. Katsayılar, deniz
    seviyesinin bulunduğu günlerde körfez noktasında en küçük kareler ile
    bulunur; göstergenin deniz seviyesini ne kadar açıkladığı (R²) sonuçla
    birlikte yazılır. Kıyısı olmayan ilçelerde 0.
"""
import logging
import os

import numpy as np
import pandas as pd
import shapely

from afet import ag
from afet.yollar import ITFAIYE_HAM_DIR
from hesap.ilce_gun import anahtar

log = logging.getLogger("deniz_toprak")

# toprak katmanı → kalınlık (cm): üst 28 cm'nin ağırlıklı ortalaması için
TOPRAK_KATMANLARI = {"soil_moisture_0_to_7cm": 7, "soil_moisture_7_to_28cm": 21}
BASINC = "pressure_msl"
DENIZ = "sea_level_height_msl"
NORMAL_BASINC = 1013.25                     # hPa
KORFEZ = (38.44, 27.05)                     # İzmir iç körfez (deniz modeli hücresi)
KORFEZ_ILCESI = "Konak"                     # körfez noktasının basınç ve lodos değerleri
KIYI_ESIGI = 0.001                          # derece (~100 m): ilçe sınırı kıyı çizgisine bu kadar yakınsa kıyı ilçesi


# ── Veri ────────────────────────────────────────────────────────────────────

def saatlik_arsiv(ilce_df, bas, bit):
    """İlçe noktalarında saatlik toprak nemi (iki katman) ve deniz düzeyi basıncı;
    tek istekte üç değişken, yıl yıl, önbellekli: DataFrame(ilce, zaman, <değişkenler>)."""
    degiskenler = [*TOPRAK_KATMANLARI, BASINC]
    parcalar = []
    for yil, b, s in ag.yillara_bol(bas, bit):
        veri = ag.open_meteo_arsiv(ag.OPEN_METEO_ARSIV_URL, ilce_df.yagis_lat, ilce_df.yagis_lon, b, s,
                                   os.path.join(ITFAIYE_HAM_DIR, f"toprak_basinc_{yil}_{b}_{s}.json"), timeout=300,
                                   hourly=",".join(degiskenler))
        parcalar += [pd.DataFrame({"ilce": ilce, "zaman": pd.to_datetime(v["hourly"]["time"]),
                                   **{d: pd.to_numeric(v["hourly"][d]) for d in degiskenler}})
                     for ilce, v in zip(ilce_df.ilce, veri)]
        log.info("Toprak nemi ve basınç %d: %s – %s", yil, b, s)
    return pd.concat(parcalar, ignore_index=True)


def deniz_seviyesi(bas, bit):
    """Körfez noktasında günün en yüksek deniz seviyesi (m; gelgit dahil).
    Verinin olmadığı günler NaN: Series(gun → m)."""
    parcalar = []
    for yil, b, s in ag.yillara_bol(bas, bit):
        v = ag.open_meteo_arsiv(ag.OPEN_METEO_DENIZ_URL, [KORFEZ[0]], [KORFEZ[1]], b, s,
                                os.path.join(ITFAIYE_HAM_DIR, f"deniz_{yil}_{b}_{s}.json"), hourly=DENIZ)[0]
        parcalar.append(pd.Series(pd.to_numeric(v["hourly"][DENIZ]), index=pd.to_datetime(v["hourly"]["time"])))
    saatlik = pd.concat(parcalar)
    return saatlik.groupby(saatlik.index.strftime("%Y-%m-%d")).max().rename("deniz_m").rename_axis("gun")


def kiyi_ilceleri(ilce_df, geo, kiyi):
    """Sınırı OSM kıyı çizgisine KIYI_ESIGI'nden yakın ilçeler (ilce_df adlarıyla)."""
    cizgi = shapely.union_all([shapely.LineString([(n["lon"], n["lat"]) for n in e["geometry"]])
                               for e in kiyi if len(e.get("geometry", [])) > 1])
    pol = {anahtar(f["properties"]["ILCEADI"]): shapely.geometry.shape(f["geometry"]) for f in geo["features"]}
    return sorted(i for i in ilce_df.ilce if pol[anahtar(i)].distance(cizgi) < KIYI_ESIGI)


# ── Özellikler ──────────────────────────────────────────────────────────────

def gunluk(saatlik):
    """Saatlik → ilçe-gün: toprak_nemi (00:00, üst 28 cm) ve basinc_min_hpa."""
    s = saatlik.assign(gun=saatlik.zaman.dt.strftime("%Y-%m-%d"))
    kalinlik = sum(TOPRAK_KATMANLARI.values())
    s["toprak_nemi"] = sum(s[k] * cm for k, cm in TOPRAK_KATMANLARI.items()) / kalinlik
    # tam 0 arşivin boşluğudur (toprakta hep biraz su vardır): eksik sayılır
    gece = s[s.zaman.dt.hour == 0].set_index(["ilce", "gun"]).toprak_nemi.where(lambda v: v > 0).round(3)
    basinc = s.groupby(["ilce", "gun"])[BASINC].min().round(1).rename("basinc_min_hpa")
    return pd.concat([gece, basinc], axis=1).reset_index()


def kabarma_katsayilari(g):
    """Deniz seviyesinin (cm) basınç açığı ve lodosla en küçük kareler uyumu:
    deniz = sabit + cm_hpa·(NORMAL_BASINC − en düşük basınç) + cm_kmh·lodos.
    g: deniz_m, basinc_min_hpa, lodos_kmh (deniz verisi olmayan günler atılır)."""
    g = g.dropna(subset=["deniz_m", "basinc_min_hpa", "lodos_kmh"])
    X = np.column_stack([np.ones(len(g)), NORMAL_BASINC - g.basinc_min_hpa, g.lodos_kmh])
    y = g.deniz_m.to_numpy() * 100
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    r2 = 1 - ((y - X @ b) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return {"gun": int(len(g)), "ilk": g.gun.min(), "son": g.gun.max(), "sabit_cm": round(float(b[0]), 2),
            "cm_hpa": round(float(b[1]), 3), "cm_kmh": round(float(b[2]), 3), "r2": round(float(r2), 3)}


def kabarma(x, k, kiyi):
    """Kıyı ilçelerinde basınç açığı ve lodostan gelen kabarma (cm, ≥ 0); öteki ilçelerde 0."""
    cm = k["cm_hpa"] * (NORMAL_BASINC - x.basinc_min_hpa) + k["cm_kmh"] * x.lodos_kmh
    return cm.clip(lower=0).where(x.ilce.isin(kiyi), 0).fillna(0).round(1)


def degiskenler(ilce_df, geo, kiyi_cizgisi, bas, bit, lodos):
    """İlçe-gün toprak_nemi, kabarma_cm ve göstergenin doğrulaması.
    lodos: ek_degiskenler.ozellikler çıktısı (ilce, gun, lodos_kmh)."""
    x = gunluk(saatlik_arsiv(ilce_df, bas, bit)).merge(lodos[["ilce", "gun", "lodos_kmh"]], on=["ilce", "gun"],
                                                        how="left")
    korfez = x[x.ilce == KORFEZ_ILCESI].merge(deniz_seviyesi(bas, bit).reset_index(), on="gun", how="left")
    k = kabarma_katsayilari(korfez)
    kiyi = kiyi_ilceleri(ilce_df, geo, kiyi_cizgisi)
    x["kabarma_cm"] = kabarma(x, k, kiyi)
    log.info("Kabarma göstergesi: deniz seviyesinin %%%.0f'ini açıklıyor (%d gün); %d kıyı ilçesi",
             k["r2"] * 100, k["gun"], len(kiyi))
    return x[["ilce", "gun", "toprak_nemi", "basinc_min_hpa", "kabarma_cm"]], {**k, "kiyi_ilceleri": kiyi}
