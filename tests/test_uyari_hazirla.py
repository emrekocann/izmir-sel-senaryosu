"""Uyarı sekmesi verisi: ıslak geçmiş ve ilçe sınırı eşlemesi."""
import pandas as pd

from hesap import siniflandirma as sn
from hesap import uyari_hazirla as uh
from hesap.ilce_gun import ILCE_CSV


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
        c = lambda a: {"deger": 2.0, "aralik_95": [round(1 + a[0], 2), round(1 + a[1], 2)]}
        return {"ilce": ad, "katsayi": {"log_yagis": k, "log_max_nokta": k * 1.1},
                "aralik_95": {"log_yagis": ay, "log_onceki7g": a7},
                "carpan_10_40": {"log_yagis": c(ay), "log_onceki7g": c(a7)}}
    satir = [ilce(ad, ay, a7, k) for k, (ad, (ay, a7)) in enumerate(ilceler.items())]
    return {"bant": 3, "ilceler": satir,
            "cok_nokta": {"degiskenler": ["log_max_nokta"], "ilceler": satir},
            "sonuclar": {"gwr": {"ap": 0.2, "duyarlilik": 0.4, "kesinlik": 0.2, "yillar": [2022, 2023],
                                 "ap_farki_globale_gore": [0.01, -0.01, 0.03]},
                         "global": {"ap": 0.19, "duyarlilik": 0.4, "kesinlik": 0.2, "yillar": [2022, 2023]}}}


def test_gwr_ozeti_kanit_ve_sira():
    g = _gwr_sonucu({"a": ([0.2, 0.9], [-0.3, 0.4]), "b": ([0.1, 0.5], [0.8, 2.0]), "c": ([-0.9, -0.1], [0.2, 0.6])})
    o = uh.gwr_ozeti(g, ["a", "b", "c"])
    assert set(o["ilceler"]) == {"a", "b", "c"} and o["bant"] == 3
    assert o["ilceler"]["a"]["gunun_yagisi"]["kanitli"] and not o["ilceler"]["a"]["onceki_hafta"]["kanitli"]
    assert o["ilceler"]["c"]["gunun_yagisi"]["kanitli"]          # sıfırın altında da kanıtlı (ters etki)
    assert o["cok_nokta_sira_korelasyonu"] == 1.0
    try:
        uh.gwr_ozeti(g, ["a", "b"])
        assert False, "eksik ilçe hata vermeli"
    except ValueError:
        pass
