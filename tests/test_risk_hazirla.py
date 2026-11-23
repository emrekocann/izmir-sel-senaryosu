"""Risk: tekerrür (Gumbel, L-momentleri) ve nüfusun hücrelere dağıtılması."""
import os

import numpy as np
import pandas as pd
import pytest

from afet.dosya import json_oku
from afet.yollar import RISK_JSON, VITRIN
from hesap import risk_hazirla as rh


def test_gumbel_bilinen_dagilimi_bulur():
    r = np.random.default_rng(0)
    u, a = rh.gumbel_oturt(r.gumbel(60, 20, 20_000))
    assert u == pytest.approx(60, abs=0.5) and a == pytest.approx(20, abs=0.5)


def test_donus_suresi_ve_yagis_duzeyi_birbirinin_tersi():
    for yil in rh.DONUS_YILLARI:
        assert rh.donus_suresi(rh.yagis_duzeyi(yil, 60, 20), 60, 20) == pytest.approx(yil)
    assert rh.donus_suresi(150, 60, 20) > rh.donus_suresi(100, 60, 20) > 1


def test_yillik_en_buyuk_yalniz_tam_yillar_kayan_gune_cevrilir():
    gun = pd.date_range("2000-01-01", "2001-12-31")
    seri = pd.Series(1.0, index=gun)
    seri["2000-06-01"] = 50
    seri = seri.drop(seri["2001-03-01":].index)          # 2001 eksik
    x = rh.yillik_en_buyuk(seri)
    assert list(x.index) == [2000] and x[2000] == pytest.approx(50 * rh.HERSHFIELD)


def test_ad_anahtari_turkce_ve_koy_farkini_yok_sayar():
    assert rh.ad_anahtari("KARŞIYAKA") == rh.ad_anahtari("Karşiyaka")
    assert rh.ad_anahtari("SANCAKLI") == rh.ad_anahtari("Sancakli Köyü")
    assert rh.ad_anahtari("R.ŞEVKET İNCE") == rh.ad_anahtari("R. Şevket İnce")


def test_nufus_dagit_agirlikla_ve_agirliksiz_birimde_esit():
    birim = np.array([[1, 1, 2], [2, 0, 0]])
    agirlik = np.array([[3.0, 1.0, 0.0], [0.0, 5.0, 5.0]])
    n = rh.nufus_dagit(birim, agirlik, [0, 100, 50])
    assert n[0, 0] == 75 and n[0, 1] == 25                # yapılaşmayla orantılı
    assert n[0, 2] == n[1, 0] == 25                       # yapılaşma yok: hücreye eşit
    assert n[1, 1:].sum() == 0 and n.sum() == 150         # birimsiz hücreye nüfus düşmez


@pytest.mark.skipif(not os.path.exists(RISK_JSON), reason="risk_hazirla çalıştırılmadı")
def test_risk_dosyasi_sozlesmesi():
    r, v = json_oku(RISK_JSON), json_oku(VITRIN)
    assert set(r["senaryolar"]) == set(v["senaryolar"])
    assert r["esik_m"] == v["esikler"]["yol_kapali_m"]          # sitede aynı "30 cm" metni
    for k, s in r["senaryolar"].items():
        assert {"donus_yil", "alt_sinir", "nufus", "nufus_belirsiz", "hastane", "okul", "hastane_adlari"} <= set(s)
        assert s["alt_sinir"] == (not k.endswith("_24"))
    # aynı sürede yağış arttıkça etkilenen nüfus azalmaz
    for saat in v["sure_sa"]:
        n = [r["senaryolar"][f"{p}_{saat}"]["nufus"] for p in v["yagis_mm"]]
        assert n == sorted(n)
    assert {"istasyon", "yillar", "duzeyler", "olay_2021_mm", "olay_2021_yil"} <= set(r["tekerrur"])
