"""OLS modeli: bilinen ilişkiyi geri bulur, sınama ölçüleri ve sonuç dosyası."""
import os

import numpy as np
import pandas as pd
import pytest

from afet.dosya import json_oku
from hesap import ols_model as om


def _sentetik(n_ilce=6, n_gun=400, tohum=0):
    """Yağış ve kent payıyla artan çağrı: model bu yönü bulmalı."""
    r = np.random.default_rng(tohum)
    satir = []
    gunler = pd.date_range("2021-01-01", periods=n_gun).date
    for i in range(n_ilce):
        kent = 0.05 + 0.15 * i
        yagis = r.gamma(0.3, 15, n_gun) * (r.random(n_gun) < 0.3)
        lam = np.exp(-4 + 0.5 * np.log1p(yagis) + 2.5 * kent * np.log1p(yagis) / 3)
        dun = np.r_[0.0, yagis[:-1]]
        hafta = pd.Series(yagis).shift(1).rolling(7, min_periods=1).sum().fillna(0).values
        for g, y, d, h, c in zip(gunler, yagis, dun, hafta, r.poisson(lam * 5)):
            satir.append({"ilce": f"ilce{i}", "gun": str(g), "yil": g.year, "cagri_su": int(c),
                          "yagis_mm": y, "yagis_max1s_mm": y / 4, "yagis_dun_mm": d,
                          "yagis_onceki7g_mm": h, "nufus": 50_000 * (i + 1), "kent_payi": kent})
    return pd.DataFrame(satir)


def test_hazirla_2019u_atar_ve_kolonlari_kurar():
    t = _sentetik(n_gun=10)
    t.loc[t.index[:5], "yil"] = 2019
    h = om.hazirla(t)
    assert (h.yil >= om.ILK_YIL).all()
    for k in om.OZELLIKLER + ["y"]:
        assert h[k].notna().all(), k
    assert np.allclose(h.log_yagis_x_kent, h.log_yagis * h.kent_payi)


def test_bilinen_iliskiyi_geri_bulur():
    t = om.hazirla(_sentetik())
    s = om.egit(t)
    assert s.params["log_yagis"] + s.params["log_yagis_x_kent"] * 0.8 > 0      # kentte yağış çağrı getirir
    assert s.params["log_yagis_x_kent"] > 0
    assert om.smearing(s) >= 1.0                                              # Jensen: exp(artık) ortalaması ≥ 1


def test_olculer_olay_gunlerini_il_toplamiyla_sayar():
    gun = ["a", "a", "b", "b", "c"]
    o = om.olculer(np.log1p([30, 30, 1, 0, 60]), np.log1p([20, 20, 1, 0, 30]),
                   [30, 30, 1, 0, 60], [20, 20, 1, 0, 30], gun)
    assert o["olay_gunu"] == 2 and o["olay_gercek_toplam"] == 120 and o["olay_tahmin_toplam"] == 70


@pytest.mark.skipif(not os.path.exists(om.SONUC_JSON), reason="model eğitilmedi")
def test_sonuc_dosyasi_sozlesmesi():
    r = json_oku(om.SONUC_JSON)
    assert [k["ad"] for k in r["katsayilar"]] == ["const"] + om.OZELLIKLER
    assert max(r["vif"].values()) < 5                         # çoklu doğrusallık giderildi
    for s in ("zaman_sinamasi", "mekan_sinamasi"):
        for m in om.MODELLER:
            assert {"r2_log", "mae_cagri", "olay_gercek_toplam", "olay_tahmin_toplam"} <= set(r[s][m])
    # yağış, yağışsız temel modele göre görülmemiş yılları daha iyi açıklar
    z = r["zaman_sinamasi"]
    assert z["model"]["r2_log"] > z["temel"]["r2_log"]
    assert len(r["mekan_sinamasi"]["ilce"]) == r["veri"]["ilce"]
