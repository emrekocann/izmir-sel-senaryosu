"""Hava tahminiyle sınama: eksik gün atma, yalnız bugünün yağışının değişmesi, uçtan uca."""
import json
import os

import numpy as np
import pandas as pd
import pytest

from hesap import tahmin_sinamasi as ts
from tests.test_siniflandirma import _sentetik


def test_tahmin_gunluk_eksik_saatli_gunu_atar():
    zaman = pd.date_range("2025-03-01", periods=48, freq="h")
    mm = np.ones(48)
    mm[30] = np.nan                                   # 2 Mart'ta bir saat eksik
    g = ts.tahmin_gunluk(pd.DataFrame({"ilce": "a", "zaman": zaman, "mm": mm}))
    assert g.gun.tolist() == ["2025-03-01"]
    assert g.yagis_mm.iloc[0] == 24 and g.yagis_max3s_mm.iloc[0] == 3


def test_tahminle_degistir_yalniz_bugunu_degistirir():
    from hesap import siniflandirma as sn
    test = sn.hazirla(_sentetik(n_ilce=1, n_gun=30))
    tahmin = test[["ilce", "gun"]].assign(yagis_mm=99.0, yagis_max1s_mm=9.0, yagis_max3s_mm=19.0)
    x = ts.tahminle_degistir(test, tahmin)
    assert (x.yagis_mm == 99).all() and np.allclose(x.log_yagis, np.log1p(99))
    for k in ("yagis_dun_mm", "yagis_onceki7g_mm", "olay", "cagri_su"):
        assert np.allclose(x[k].values, test[k].values), k


def test_egitilmis_kisaltilmis_parametreyi_acar():
    m = ts.egitilmis("lojistik", {"modeller": {"lojistik": {"parametreler": {"C": 0.1}}}})
    assert m.get_params()["logisticregression__C"] == 0.1


def test_uctan_uca_sentetik():
    t = _sentetik()
    test = t[t.yil.isin((2025, 2026))]
    iyi = test[["ilce", "gun", "yagis_mm", "yagis_max1s_mm", "yagis_max3s_mm"]]   # kusursuz tahmin
    sonuc = {"secili": "lojistik", "modeller": {"temel": {"parametreler": {}, "esik": 0.05},
                                                "lojistik": {"parametreler": {"C": 1}, "esik": 0.2}}}
    r = ts.calistir(t, {"kusursuz": iyi}, sonuc, modeller=["temel", "lojistik"])
    s = r["sonuclar"]["lojistik"]
    assert s["kusursuz"]["ap"] == s["gozlem"]["ap"]                    # kusursuz tahmin = gözlem
    assert s["tahminsiz"]["ap"] < s["gozlem"]["ap"]                    # bugünün yağışı bilgi taşıyor
    assert r["yagis_uyumu"]["kusursuz"]["korelasyon"] == 1.0


@pytest.mark.skipif(not os.path.exists(ts.SONUC_JSON), reason="sınama çalıştırılmadı")
def test_sonuc_dosyasi_sozlesmesi():
    r = json.load(open(ts.SONUC_JSON, encoding="utf-8"))
    assert r["ana"] in r["tahmin_modelleri"]
    for ad, k in r["sonuclar"].items():
        assert set(k) == {"gozlem", "tahminsiz", *r["tahmin_modelleri"]}
    s = r["sonuclar"][r["secili"]]
    # tahmin, hiç tahmin olmamasından iyi; gözlemden çok kötü değil
    assert s[r["ana"]]["duyarlilik"] > 2 * s["tahminsiz"]["duyarlilik"]
    assert s[r["ana"]]["ap"] > 0.7 * s["gozlem"]["ap"]
