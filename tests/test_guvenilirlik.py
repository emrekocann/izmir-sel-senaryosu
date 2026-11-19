"""Güvenilirlik: öğlen uyarısı girdisi, güne göre bootstrap, yıl yıl sınama."""
import json
import os

import numpy as np
import pandas as pd
import pytest

from hesap import guvenilirlik as gv
from hesap import siniflandirma as sn
from tests.test_siniflandirma import _sentetik


def _saatlik(deger, gun_sayisi=3, ilce="a"):
    z = pd.date_range("2025-03-01", periods=24 * gun_sayisi, freq="h")
    d = deger(z) if callable(deger) else np.full(len(z), float(deger))
    return pd.DataFrame({"ilce": ilce, "zaman": z, "mm": d})


def test_oglen_girdisi_saatleri_dogru_kosudan_alir():
    t1 = _saatlik(1.0)                                    # 1 gün önceki koşu: saatte 1 mm
    t2 = _saatlik(2.0)                                    # 2 gün önceki koşu: saatte 2 mm
    gozlem = _saatlik(lambda z: np.where(z.hour >= 12, 5.0, 0.0))
    g = gv.oglen_girdisi(gozlem, t1, t2).set_index("gun")
    # D: 12 saat × 1 mm (sabah, 1 gün önce) + 12 saat × 2 mm (öğleden sonra, 2 gün önce)
    assert g.loc["2025-03-02", "yagis_mm"] == 36
    # D-1 öğleden sonrası: gözlem 12 × 5 = 60 yerine tahmin 12 × 1 = 12 → düzeltme −48
    assert g.loc["2025-03-02", "duzeltme_mm"] == pytest.approx(-48)


def test_oglen_degistir_gecmisi_duzeltir_sifirin_altina_inmez():
    test = sn.hazirla(_sentetik(n_ilce=1, n_gun=10))
    gun = test.gun.iloc[5]
    girdi = pd.DataFrame({"ilce": ["ilce0"], "gun": [gun], "yagis_mm": [7.0], "yagis_max1s_mm": [2.0],
                          "yagis_max3s_mm": [4.0], "duzeltme_mm": [-1e6]})
    x = gv.oglen_degistir(test, girdi)
    assert len(x) == 1 and x.yagis_mm.iloc[0] == 7
    assert (x[gv.ONCEKI].values == 0).all()


def test_bootstrap_gun_blogu_ve_aralik():
    r = np.random.default_rng(0)
    gun = np.repeat([f"g{i}" for i in range(200)], 5)
    olay = (r.random(len(gun)) < 0.1).astype(int)
    p = np.clip(olay * 0.6 + r.random(len(gun)) * 0.4, 0, 1)
    x = pd.DataFrame({"gun": gun, "olay": olay, "p": p, "cagri_su": olay * 60})
    a = gv.bootstrap(x, p >= 0.5, n=200)
    for k in ("ap", "kesinlik", "duyarlilik", "buyuk_gun_yakalama"):
        alt, ust = a[k]
        assert 0 <= alt <= ust <= 1, k
    assert a["ap"][0] > 0.5                                # güçlü ayırıcı


def test_calistir_yillar_ve_tahminli_donem():
    t = _sentetik()
    sifir = lambda x: x.assign(**{k: 0.0 for k in ("yagis_mm", "yagis_max1s_mm", "yagis_max3s_mm")}).pipe(
        lambda y: sn.hazirla(y.drop(columns=[c for c in y.columns if c.startswith("log_") or c in ("y", "olay")])))
    r = gv.calistir(t, {"sifir": (2025, sifir)}, test_yillari=[2024, 2025, 2026], modeller=["lojistik"], n=50)
    s = r["sonuclar"]["lojistik"]
    assert [k["test_yili"] for k in s["katmanlar"]] == [2024, 2025, 2026]
    for k in s["katmanlar"]:
        assert k["egitim"] == [2021, k["test_yili"] - 1]
    assert s["tum_yillar"]["yillar"] == [2024, 2025, 2026]
    assert set(s["tahminli_donem"]) == {"gozlem", "sifir"}
    assert s["tahminli_donem"]["gozlem"]["yillar"] == [2025, 2026]
    assert s["tahminli_donem"]["gozlem"]["olay"] == s["tahminli_donem"]["sifir"]["olay"]   # aynı satırlar
    assert s["tahminli_donem"]["sifir"]["ap"] < s["tahminli_donem"]["gozlem"]["ap"]


@pytest.mark.skipif(not os.path.exists(gv.SONUC_JSON), reason="güvenilirlik çalıştırılmadı")
def test_sonuc_dosyasi_sozlesmesi():
    r = json.load(open(gv.SONUC_JSON, encoding="utf-8"))
    for ad, s in r["sonuclar"].items():
        assert [k["test_yili"] for k in s["katmanlar"]] == r["test_yillari"]
        for o in [s["tum_yillar"], *s["tahminli_donem"].values()]:
            for k in ("ap", "duyarlilik", "kesinlik"):
                alt, ust = o["aralik_95"][k]
                assert alt <= o[k] + 0.02 and o[k] - 0.02 <= ust, (ad, k)
        olaylar = {o["olay"] for o in s["tahminli_donem"].values()}
        assert len(olaylar) == 1                          # tahminli kıyas aynı satırlarda
