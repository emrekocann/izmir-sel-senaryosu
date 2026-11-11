import numpy as np

from hesap.sel_senaryo_hazirla import (DRENAJ_MM_SA, SEVIYE_M, havuz_doldur, kesit_debisi, scs_akis,
                                 senaryo_akisi, seviye_bul)


def test_scs_akis_tr55_degerleri():
    # TR-55: CN 94, P = 50 mm → Q ≈ 34.7 mm; CN 74, P = 25 mm → başlangıç kaybını aşmaz (≈ 0.5)
    assert abs(float(scs_akis(np.array(50.0), 94)) - 34.7) < 0.2
    assert float(scs_akis(np.array(10.0), 74)) == 0.0
    # yağış arttıkça akış artar, akış yağışı geçemez
    p = np.array([10, 25, 50, 100, 250.0])
    q = scs_akis(p, 85)
    assert np.all(np.diff(q) > 0) and np.all(q < p)


def test_kent_drenaji_uzun_yagisi_tasir():
    tam_kent = (np.array([80.0]), np.array([94.0]), np.array([1.0]))
    # aynı 50 mm: 1 saatte yüzeyde su kalır, 24 saate yayılınca drenaj taşır
    assert senaryo_akisi(50, 1, *tam_kent)[0] > 10
    assert senaryo_akisi(50, 24, *tam_kent)[0] == 0
    # yapılaşmamış alanda drenaj yok: süre akışı değiştirmez
    kir = (np.array([80.0]), np.array([94.0]), np.array([0.0]))
    assert senaryo_akisi(50, 1, *kir)[0] == senaryo_akisi(50, 24, *kir)[0]
    assert DRENAJ_MM_SA > 0


def test_cukur_alttan_dolar_ve_tasmaz():
    et = np.array([[1, 1, 1, 0]])
    taban = np.array([[0.0, 1.0, 2.0, 5.0]])
    tasma = np.full((1, 4), 3.0)
    alan = np.ones((1, 4))
    d = lambda v: havuz_doldur(et, taban, tasma, alan, np.array([0, v]))[0]
    assert np.allclose(d(0), 0)
    assert np.allclose(d(1), [1, 0, 0, 0])            # 1 m³ dipteki hücreyi 1 m doldurur
    assert np.allclose(d(2), [1.5, 0.5, 0, 0])        # seviye 1.5 m
    assert np.allclose(d(1000), [3, 2, 1, 0])         # taşma seviyesinde (3 m) durur


def test_su_yuzeyi_akis_uretmez():
    hucre = (np.array([80.0]), np.array([94.0]), np.array([0.0]))
    assert senaryo_akisi(100, 1, *hucre, su=np.array([1.0]))[0] == 0
    assert senaryo_akisi(100, 1, *hucre, su=np.array([0.5]))[0] == senaryo_akisi(100, 1, *hucre)[0] / 2


def test_anahtar_egrisi_genis_ovada_sig_kalir():
    # aynı fazla debi: 60 m'lik dar vadiye karşı 1 km'lik düz ova (HAND ≈ 0)
    dar = [kesit_debisi(h * 60 * 60, 60 * 60, 60, 0.005) for h in SEVIYE_M]
    genis = [kesit_debisi(h * 1000 * 60, 1000 * 60, 60, 0.005) for h in SEVIYE_M]
    egri = np.array([dar, genis], np.float32)
    assert np.all(np.diff(egri, axis=1) > 0)
    h = seviye_bul(np.array([50.0, 50.0]), egri)
    assert h[1] < h[0] / 2
    assert seviye_bul(np.array([0.0, -1.0]), egri).tolist() == [0, 0]
    assert seviye_bul(np.array([1e9, 1e9]), egri).tolist() == [SEVIYE_M[-1]] * 2


def test_alan_azaltma():
    from hesap.sel_senaryo_hazirla import alan_azaltma
    # nokta ≈ 1; büyüdükçe azalır; uzun yağışta azalma daha az (TP-29 eğilimi)
    assert alan_azaltma(1, 1) > 0.99
    a = alan_azaltma(np.array([10, 100, 1000, 10000]), 1)
    assert np.all(np.diff(a) < 0) and 0.6 < a[-1] < 0.75
    assert alan_azaltma(1000, 24) > alan_azaltma(1000, 1)
