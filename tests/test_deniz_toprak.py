"""Toprak nemi ve deniz kabarması: günlük özellikler, kabarma uyumu, kıyı ilçeleri."""
import numpy as np
import pandas as pd
import pytest

from hesap import deniz_toprak as dt


def _saatlik():
    zaman = pd.date_range("2024-01-01 00:00", periods=48, freq="h")
    return pd.DataFrame({"ilce": "a", "zaman": zaman,
                         "soil_moisture_0_to_7cm": np.where(zaman.hour == 0, 0.40, 0.10),
                         "soil_moisture_7_to_28cm": np.where(zaman.hour == 0, 0.20, 0.10),
                         "pressure_msl": np.r_[np.full(24, 1010.0), np.full(24, 1020.0)] - np.r_[0, 5, np.zeros(46)]})


def test_gunluk_gece_toprak_nemi_ve_en_dusuk_basinc():
    g = dt.gunluk(_saatlik()).set_index("gun")
    # 00:00 değeri, kalınlık ağırlıklı: (0.40·7 + 0.20·21) / 28 = 0.25 (gün içindeki 0.10'lar değil)
    assert g.loc["2024-01-01", "toprak_nemi"] == pytest.approx(0.25)
    assert g.loc["2024-01-01", "basinc_min_hpa"] == 1005.0 and g.loc["2024-01-02", "basinc_min_hpa"] == 1020.0


def test_kabarma_katsayilari_bilinen_iliskiyi_bulur():
    r = np.random.default_rng(0)
    acik = r.uniform(-10, 20, 200)
    lodos = r.uniform(0, 40, 200)
    deniz_cm = 5 + 1.0 * acik + 0.3 * lodos
    g = pd.DataFrame({"gun": pd.date_range("2024-01-01", periods=200).strftime("%Y-%m-%d"),
                      "deniz_m": deniz_cm / 100, "basinc_min_hpa": dt.NORMAL_BASINC - acik, "lodos_kmh": lodos})
    g.loc[:9, "deniz_m"] = np.nan                       # deniz verisi olmayan günler atılır
    k = dt.kabarma_katsayilari(g)
    assert k["gun"] == 190 and k["r2"] == pytest.approx(1.0)
    assert (k["sabit_cm"], k["cm_hpa"], k["cm_kmh"]) == pytest.approx((5, 1.0, 0.3), abs=1e-3)


def test_kabarma_yalniz_kiyida_ve_sifirin_ustunde():
    x = pd.DataFrame({"ilce": ["kiyi", "kiyi", "ic"], "basinc_min_hpa": [1003.25, 1023.25, 1003.25],
                      "lodos_kmh": [10.0, 0.0, 10.0]})
    k = {"cm_hpa": 1.0, "cm_kmh": 0.5}
    assert dt.kabarma(x, k, ["kiyi"]).tolist() == [15.0, 0.0, 0.0]   # yüksek basınç: kabarma yok; iç ilçe: 0


def test_kiyi_ilceleri_kiyi_cizgisine_degen():
    def kare(x0):
        return {"type": "Polygon", "coordinates": [[[x0, 38], [x0 + 0.1, 38], [x0 + 0.1, 38.1], [x0, 38.1], [x0, 38]]]}

    geo = {"features": [{"properties": {"ILCEADI": "KIYI"}, "geometry": kare(27.0)},
                        {"properties": {"ILCEADI": "İÇ"}, "geometry": kare(27.5)}]}
    kiyi = [{"geometry": [{"lat": 37.9, "lon": 27.05}, {"lat": 38.2, "lon": 27.05}]}, {"geometry": []}]
    assert dt.kiyi_ilceleri(pd.DataFrame({"ilce": ["Kıyı", "İç"]}), geo, kiyi) == ["Kıyı"]
