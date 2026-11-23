"""Uyarı sekmesi verisi: ıslak geçmiş, ilçe sınırı eşlemesi, sonuç kutuları, sel dalgaları,
canlı tahmin için modelin dışa aktarımı."""
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from afet.yollar import ILCE_CSV
from hesap import siniflandirma as sn
from hesap import uyari_hazirla as uh


def test_islak_gecmis_olay_gunlerinin_ortancasi():
    t = pd.DataFrame({"olay": [1, 1, 1, 0], "yagis_dun_mm": [0, 10, 20, 99],
                      "yagis_onceki3g_mm": [5, 5, 50, 99], "yagis_onceki7g_mm": [10, 30, 70, 99]})
    assert uh.islak_gecmis(t) == {"yagis_dun_mm": 10, "yagis_onceki3g_mm": 5, "yagis_onceki7g_mm": 30}
    assert set(uh.islak_gecmis(t)) == set(sn.KURU)


def test_butun_ilceler_sinirla_eslesir():
    adlar = pd.read_csv(ILCE_CSV).ilce.tolist()        # TKGM yazımı (Karşiyaka, Bayrakli…)
    g = uh.ilce_geometrileri(adlar)
    assert set(g) == set(adlar) and all(x["type"] in ("Polygon", "MultiPolygon") for x in g.values())


def _gwr_sonucu(ilceler):
    """gwr_sonuc.json biçiminde küçük örnek: ad → (günün yağışı katsayı aralığı, önceki 7 gün aralığı)."""
    def ilce(ad, ay, a7, k):
        def c(a):
            return {"deger": 2.0, "aralik_95": [round(1 + a[0], 2), round(1 + a[1], 2)]}

        return {"ilce": ad, "katsayi": {"log_yagis": k},
                "aralik_95": {"log_yagis": ay, "log_onceki7g": a7},
                "carpan_10_40": {"log_yagis": c(ay), "log_onceki7g": c(a7)}}
    satir = [ilce(ad, ay, a7, k) for k, (ad, (ay, a7)) in enumerate(ilceler.items())]
    return {"bant": 3, "ilceler": satir,
            "sonuclar": {"gwr": {"ap": 0.2, "duyarlilik": 0.4, "kesinlik": 0.2, "yillar": [2022, 2023],
                                 "ap_farki_globale_gore": [0.01, -0.01, 0.03]},
                         "global": {"ap": 0.19, "duyarlilik": 0.4, "kesinlik": 0.2, "yillar": [2022, 2023]}}}


def test_gwr_ozeti_kanit_ve_sira():
    g = _gwr_sonucu({"a": ([0.2, 0.9], [-0.3, 0.4]), "b": ([0.1, 0.5], [0.8, 2.0]), "c": ([-0.9, -0.1], [0.2, 0.6])})
    o = uh.gwr_ozeti(g, ["a", "b", "c"])
    assert set(o["ilceler"]) == {"a", "b", "c"} and o["bant"] == 3
    assert o["ilceler"]["a"]["gunun_yagisi"]["kanitli"] and not o["ilceler"]["a"]["onceki_hafta"]["kanitli"]
    assert o["ilceler"]["c"]["gunun_yagisi"]["kanitli"]          # sıfırın altında da kanıtlı (ters etki)
    with pytest.raises(ValueError):                              # eksik ilçe
        uh.gwr_ozeti(g, ["a", "b"])


def _ilce_gun():
    """İki gün × üç ilçe; 1. gün a'da, 2. gün b'de sel."""
    return pd.DataFrame({"gun": ["2022-01-01"] * 3 + ["2022-01-02"] * 3, "yil": 2022, "ilce": ["a", "b", "c"] * 2,
                         "olay": [1, 0, 0, 0, 1, 0], "cagri_su": [12, 3, 0, 1, 20, 9],
                         "yagis_mm": [30.0, 5.0, 1.0, 0.0, 12.34, 8.0],
                         "yagis_onceki7g_mm": [2.0, 2.0, 2.0, 40.0, 41.26, 39.0]})


def test_dort_kutu_toplami_ilce_gun_sayisi():
    o = {"yillar": [2022], "olay": 2, "dogru_alarm": 1, "yanlis_alarm": 2, "kacirilan": 1}
    assert uh.dort_kutu(_ilce_gun(), o) == {"ilce_gun": 6, "gun": 2, "sel": 2, "dogru_alarm": 1,
                                            "bosa_alarm": 2, "kacan": 1, "dogru_sessiz": 2}
    with pytest.raises(ValueError):                              # sel sayısı tutmuyor
        uh.dort_kutu(_ilce_gun(), {**o, "olay": 3})


def test_dalgalar_ilk_gunun_en_cok_cagrili_ilcesi():
    ataklar = [{"ilk": "2022-01-01", "son": "2022-01-01", "gun": 1, "ilk_gun_alarm": True, "herhangi_alarm": True},
               {"ilk": "2022-01-02", "son": "2022-01-02", "gun": 1, "ilk_gun_alarm": False, "herhangi_alarm": False}]
    d = uh.dalgalar(_ilce_gun(), ataklar)
    assert [(a["ilce"], a["cagri"], a["il_cagri"]) for a in d["liste"]] == [("a", 12, 15), ("b", 20, 30)]
    assert (d["liste"][1]["yagis_mm"], d["liste"][1]["onceki7g_mm"]) == (12.3, 41.3)
    assert d["ilk_gun_alarmli"] == {"dalga": 1, "yagis_mm": 30.0, "onceki7g_mm": 2.0}
    assert d["ilk_gun_alarmsiz"] == {"dalga": 1, "yagis_mm": 12.3, "onceki7g_mm": 41.3}
    assert uh.dalgalar(_ilce_gun(), ataklar[:1])["ilk_gun_alarmsiz"] == {"dalga": 0, "yagis_mm": None,
                                                                         "onceki7g_mm": None}


def _kucuk_gb():
    """Yağışa monoton küçük gradient boosting: yağış 0,1 mm adımlı, ikinci girdi 5 ilçenin sabit değeri."""
    r = np.random.default_rng(0)
    X = np.column_stack([np.round(r.gamma(0.8, 8, 2000), 1), r.integers(0, 5, 2000) / 4])
    y = (r.random(2000) < 1 / (1 + np.exp(-(X[:, 0] / 10 - 3)))).astype(int)
    m = HistGradientBoostingClassifier(max_iter=20, early_stopping=False, random_state=0, monotonic_cst=[1, 0])
    return m.fit(X, y), X


def test_model_disa_aktarimi_sklearn_ile_ayni():
    m, X = _kucuk_gb()
    model = uh.model_disa_aktar(m, ["yagis_mm", "kent_payi"])
    assert model["girdiler"] == ["yagis_mm", "kent_payi"] and len(model["agaclar"]) == m.n_iter_
    assert all(len(d) in (1, 4) for agac in model["agaclar"] for d in agac)     # yaprak ya da iç düğüm
    assert uh.aktarimi_denetle(model, m, X, 0.3) < 1e-9


def test_bozuk_aktarim_yazilmaz_ve_yalniz_gradient_boosting():
    m, X = _kucuk_gb()
    model = uh.model_disa_aktar(m, ["yagis_mm", "kent_payi"])
    with pytest.raises(ValueError):
        uh.aktarimi_denetle({**model, "baslangic": model["baslangic"] + 0.5}, m, X, 0.3)
    X1 = np.arange(20.0).reshape(-1, 1)
    with pytest.raises(ValueError):
        uh.model_disa_aktar(LogisticRegression().fit(X1, (X1[:, 0] > 9).astype(int)), ["yagis_mm"])
