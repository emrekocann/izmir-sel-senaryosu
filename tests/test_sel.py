import numpy as np


def test_yagis_katsayisi_wmo_siniflari():
    from afet.sel.risk import yagis_katsayisi

    assert yagis_katsayisi(0.2, 0.4) == (0.0, "Yağış yok")
    assert yagis_katsayisi(1.0, 3.0) == (0.15, "Hafif")
    assert yagis_katsayisi(5.0, 20.0) == (0.4, "Orta")
    assert yagis_katsayisi(12.0, 30.0) == (0.8, "Kuvvetli")
    assert yagis_katsayisi(60.0, 80.0) == (1.0, "Çok kuvvetli")


def test_uzun_sureli_yagis_toplami_seviyeyi_yukseltir():
    from afet.sel.risk import yagis_katsayisi

    # saatlik hafif ama gün boyu süren yağış
    assert yagis_katsayisi(2.0, 55.0) == (0.8, "Kuvvetli")
    assert yagis_katsayisi(6.0, 120.0) == (1.0, "Çok kuvvetli")


def test_katsayi_noktada_bilinear():
    from afet.sel.risk import katsayi_noktada

    yagis = {"lats": np.array([38.0, 38.25]), "lons": np.array([27.0, 27.25]),
             "F": np.array([[0.0, 1.0], [0.0, 1.0]])}
    assert katsayi_noktada(yagis, 27.0, 38.0) == 0.0
    assert abs(katsayi_noktada(yagis, 27.125, 38.1) - 0.5) < 1e-9
    assert katsayi_noktada(yagis, 30.0, 38.1) == 1.0          # ızgara dışı kenara kırpılır


def test_duyarlilik_formulu():
    from hesap.sel_duyarlilik_hesapla import DERE_BUYUK_KM2, DERE_KUCUK_KM2, duyarlilik

    hand = {DERE_KUCUK_KM2: np.array([0.0, 3.0, 10.0, np.nan, 10.0]),
            DERE_BUYUK_KM2: np.array([20.0, 20.0, 0.0, np.nan, 20.0])}
    cukur = np.array([0.0, 0.0, 0.0, 0.0, 0.5])
    veri_yok = np.array([False, False, False, False, False])
    s = duyarlilik(hand, cukur, veri_yok)
    # küçük dere kenarı 0.7 ile sınırlı, büyük dere tabanı 1, HAND yok → 0, çukur 0.5 m → 0.5
    assert np.allclose(s, [0.7, 0.35, 1.0, 0.0, 0.5])
    assert duyarlilik(hand, cukur, np.ones(5, bool)).max() == 0

