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
