"""İlçe-gün eğitim veri seti: ad eşleme, çağrı türü, tarih, yağış özellikleri."""
import os

import pandas as pd
import pytest

from afet.yollar import ILCE_GUN_CSV
from hesap import ilce_gun as ig


def test_ilce_adlari_turkce_buyuk_harften_bagimsiz_eslesir():
    # itfaiye çizelgesi BÜYÜK harf, TKGM 'Karşiyaka' / 'Bayindir' yazar
    assert ig.anahtar("KARŞIYAKA") == ig.anahtar("Karşiyaka")
    assert ig.anahtar("BAYINDIR") == ig.anahtar("Bayindir")
    assert ig.anahtar("İZMİR ") == ig.anahtar("izmir")
    assert ig.anahtar("ÖDEMİŞ") == ig.anahtar("Ödemiş")


def test_yalniz_su_baskini_ve_su_cekme_sayilir():
    assert ig.cagri_turu("SU BASKINI (KONTROL/EMNİYET/TETKİK)") == "kontrol"
    assert ig.cagri_turu("SU BASKINI (KONTROL VE EMNİYET)") == "kontrol"           # 2019 adı
    assert ig.cagri_turu("SU ÇEKME-KÜÇÜK ÖLÇEKLİ (DALGIÇ POMPA, MOTOPOMP) MOTORLA") == "cekme"
    assert ig.cagri_turu("SU ÇEKME (KÜÇÜK MOTOPOMP İLE)") == "cekme"
    # arazözle su vermek (içme / yangın tedbiri) su baskını değildir
    assert ig.cagri_turu("SU VERME-ACİL DURUM HARİCİ ARAZÖZLE") is None
    assert ig.cagri_turu("YANGIN TEDBİR") is None


def test_tarih_gun_ay_yil_ve_excel_bicimi():
    s = pd.Series(["01.10.2024", "2023-08-27 01:12:49.990000", "2021-02-02 00:00:00", "9.03.2024"])
    assert [str(d) for d in ig.tarih_coz(s)] == ["2024-10-01", "2023-08-27", "2021-02-02", "2024-03-09"]


def test_gunluk_yagis_ozellikleri():
    zaman = pd.date_range("2021-02-01", periods=72, freq="h")
    mm = [0.0] * 72
    mm[24 + 10], mm[24 + 11], mm[24 + 12] = 5.0, 10.0, 3.0          # 2 Şubat 10–12
    g = ig.gunluk_yagis(pd.DataFrame({"ilce": "Konak", "zaman": zaman, "mm": mm}))
    g = g.set_index(g.gun.astype(str))
    assert g.loc["2021-02-02", "yagis_mm"] == 18.0
    assert g.loc["2021-02-02", "yagis_max1s_mm"] == 10.0
    assert g.loc["2021-02-02", "yagis_max3s_mm"] == 18.0
    assert g.loc["2021-02-03", "yagis_dun_mm"] == 18.0
    assert g.loc["2021-02-03", "yagis_onceki7g_mm"] == 18.0
    assert g.loc["2021-02-01", "yagis_dun_mm"] == 0.0


def test_cagrisiz_gunler_sifir_satir_olarak_kalir():
    yagis = pd.DataFrame({"ilce": ["Konak", "Konak", "Buca"], "gun": pd.to_datetime(
        ["2021-02-02", "2021-02-03", "2021-02-02"]).date, "yagis_mm": [65.0, 2.0, 40.0]})
    cagri = pd.DataFrame({"ilce": ["Konak", "Konak", "Konak"], "gun": pd.to_datetime(
        ["2021-02-02"] * 3).date, "saat": [10, 11, 12], "tur": ["kontrol", "kontrol", "cekme"]})
    ilce = pd.DataFrame({"ilce": ["Konak", "Buca"], "nufus": [1, 2], "kent_km2": [1.0, 2.0],
                         "kent_payi": [0.5, 0.1]})
    t = ig.ilce_gun_tablosu(cagri, yagis, ilce).set_index(["ilce", "gun"])
    k = t.loc[("Konak", pd.Timestamp("2021-02-02").date())]
    assert (k.cagri_kontrol, k.cagri_cekme, k.cagri_su) == (2, 1, 3)
    assert t.loc[("Buca", pd.Timestamp("2021-02-02").date()), "cagri_su"] == 0
    assert len(t) == 3


@pytest.mark.skipif(not os.path.exists(ILCE_GUN_CSV), reason="veri seti üretilmedi")
def test_uretilen_veri_seti_sozlesmesi():
    t = pd.read_csv(ILCE_GUN_CSV)
    assert t.ilce.nunique() == 30
    assert not t.duplicated(["ilce", "gun"]).any()
    assert t.groupby("ilce").size().nunique() == 1               # her ilçe her gün
    for k in ("cagri_su", "cagri_kontrol", "cagri_cekme", "yagis_mm", "yagis_max1s_mm",
              "yagis_dun_mm", "yagis_onceki7g_mm", "nufus", "kent_payi"):
        assert k in t.columns and t[k].notna().all(), k
    assert (t.cagri_su == t.cagri_kontrol + t.cagri_cekme).all()
    # 2 Şubat 2021 seli veride görünür
    assert t[t.gun == "2021-02-02"].cagri_su.sum() > 400
