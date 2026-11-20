"""Geçmiş selle doğrulama: ölçüler ve olay dosyası."""
from afet.dosya import json_oku
from afet.yollar import OLAY_2021
from hesap.sel_dogrulama import auc, yuzdelik


def test_auc():
    assert auc([3, 4], [1, 2]) == 1.0          # haberdekiler hep daha ıslak
    assert auc([1, 2], [3, 4]) == 0.0
    assert auc([1, 1], [1, 1]) == 0.5          # beraberlik yarım: ayırt edemiyor
    assert auc([], [1]) is None


def test_yuzdelik():
    assert yuzdelik(5, [1, 2, 3, 4]) == 100
    assert yuzdelik(0, [0, 0, 1, 1]) == 25     # 0'da beraberlik yarım sayılır


def test_olay_dosyasi_kaynakli():
    olay = json_oku(OLAY_2021)
    for y in olay["yerler"]:
        assert y["tur"] in ("mahalle", "cadde", "dere", "alt_gecit")
        assert y["kaynak"] and all(k in olay["kaynaklar"] for k in y["kaynak"])
        assert y["neden"] in ("dere", "kiyi_drenaj", "belirsiz")
