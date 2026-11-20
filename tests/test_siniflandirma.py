"""Sınıflandırma: olay tanımı, ölçüler, eşik seçimi, uçtan uca sonuç ve dosya sözleşmesi."""
import os

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier

from afet.dosya import json_oku
from afet.yollar import SINIFLANDIRMA_SONUC
from hesap import siniflandirma as sn


def _sentetik(n_ilce=5, n_gun=6 * 365, tohum=1):
    """Yağış ve kent payıyla artan olay: yağışlı modeller temel modeli geçmeli."""
    r = np.random.default_rng(tohum)
    gunler = pd.date_range("2021-01-01", periods=n_gun)
    ortak = r.gamma(0.4, 20, n_gun) * (r.random(n_gun) < 0.25)        # aynı fırtına bütün ilçelere
    satir = []
    for i in range(n_ilce):
        kent = 0.05 + 0.2 * i
        y = ortak * r.uniform(0.6, 1.4, n_gun)
        s = pd.Series(y)
        lam = np.exp(-5 + 0.9 * np.log1p(y) * (0.5 + kent))
        for g, yi, c, d, h3, h7 in zip(gunler, y, r.poisson(lam * 4), s.shift(1).fillna(0),
                                       s.shift(1).rolling(3, min_periods=1).sum().fillna(0),
                                       s.shift(1).rolling(7, min_periods=1).sum().fillna(0)):
            satir.append({"ilce": f"ilce{i}", "gun": str(g.date()), "yil": g.year, "cagri_su": int(c),
                          "yagis_mm": yi, "yagis_max1s_mm": yi / 4, "yagis_max3s_mm": yi / 2,
                          "yagis_dun_mm": d, "yagis_onceki3g_mm": h3, "yagis_onceki7g_mm": h7,
                          "nufus": 50_000 * (i + 1), "kent_payi": kent})
    return pd.DataFrame(satir)


# testte hızlı: küçük ızgaralar, küçük orman
HIZLI = {
    "temel": sn.MODELLER["temel"],
    "lojistik": sn.MODELLER["lojistik"]._replace(izgara={"logisticregression__C": [0.1, 1]}),
    "rf": sn.ModelTanimi(lambda: RandomForestClassifier(n_estimators=30, n_jobs=-1, random_state=0), sn.AGAC_OZ,
                         {"min_samples_leaf": [20]}, "rf"),
}


def test_olay_esigi():
    t = sn.hazirla(_sentetik(n_ilce=1, n_gun=400))
    assert ((t.cagri_su >= sn.OLAY_ESIK) == (t.olay == 1)).all()


def test_olculer_alarm_sayimlari():
    o = sn.olculer([1, 0, 1, 0, 0], [0.9, 0.8, 0.1, 0.2, 0.05], esik=0.5)
    assert (o["dogru_alarm"], o["yanlis_alarm"], o["kacirilan"]) == (1, 1, 1)
    assert o["kesinlik"] == 0.5 and o["duyarlilik"] == 0.5 and o["olay"] == 2


def test_f1_esigi_ayiran_esigi_bulur():
    y = np.array([0] * 90 + [1] * 10)
    p = np.r_[np.linspace(0, 0.3, 90), np.linspace(0.6, 0.9, 10)]
    e = sn.f1_esigi(y, p)
    assert 0.3 < e <= 0.6


def test_uctan_uca_sentetik():
    r = sn.calistir(_sentetik(), modeller=HIZLI)
    z = r["zaman_sinamasi"]
    assert r["secili"] in ("lojistik", "rf")
    assert z[r["secili"]]["auc"] > z["temel"]["auc"] + 0.1                 # yağış bilgi taşıyor
    assert set(r["mekan_sinamasi"]["lojistik"]) == {"ilce_disarida", "rastgele_5kat"}
    assert len(r["ilce"]) == r["veri"]["ilce"]
    tb = r["olasilik_tablosu"]
    for p in tb["ilce"].values():
        assert len(p) == len(sn.TABLO_YAGIS) and all(0 <= x <= 1 for x in p)
        assert p[-1] > p[0]                                                 # çok yağış, daha çok olasılık


@pytest.mark.skipif(not os.path.exists(SINIFLANDIRMA_SONUC), reason="model eğitilmedi")
def test_sonuc_dosyasi_sozlesmesi():
    r = json_oku(SINIFLANDIRMA_SONUC)
    assert set(r["modeller"]) == set(sn.MODELLER) and r["secili"] in sn.MODELLER
    for ad in sn.MODELLER:
        assert {"auc", "ap", "brier", "kesinlik", "duyarlilik", "esik", "il"} <= set(r["zaman_sinamasi"][ad])
        assert {"ilce_disarida", "rastgele_5kat"} == set(r["mekan_sinamasi"][ad])
    z = r["zaman_sinamasi"]
    assert z[r["secili"]]["ap"] > 3 * z["temel"]["ap"]                      # yağış görülmemiş yıllarda iş görür
    assert len(r["ilce"]) == r["veri"]["ilce"] == len(r["olasilik_tablosu"]["ilce"])
    # gradient boosting yağışa monoton: tablo her ilçede azalmaz
    if r["secili"] == "gb":
        for p in r["olasilik_tablosu"]["ilce"].values():
            assert all(a <= b + 1e-9 for a, b in zip(p, p[1:]))
