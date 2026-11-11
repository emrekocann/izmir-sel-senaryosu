"""Yayın sayfası verisi: 'yakalandı' ölçütü."""
from hesap.vitrin_hazirla import MAHALLE_YUZDELIK, OLAY_SENARYOLARI, yakalandi


def _sonuc(**alanlar):
    yer = {"tur": alanlar.pop("tur"), "ilce": "X", "ad": "Y", **alanlar}
    return {"senaryolar": {s: {"yerler": [yer]} for s in OLAY_SENARYOLARI}}


def test_yakalandi_olcutu():
    assert yakalandi(_sonuc(tur="mahalle", derin_yuzdelik=MAHALLE_YUZDELIK), "mahalle", "X", "Y")
    assert not yakalandi(_sonuc(tur="mahalle", derin_yuzdelik=MAHALLE_YUZDELIK - 1), "mahalle", "X", "Y")
    assert yakalandi(_sonuc(tur="cadde", en_derin_m=0.3), "cadde", "X", "Y")
    assert not yakalandi(_sonuc(tur="cadde", en_derin_m=0.2), "cadde", "X", "Y")
    assert not yakalandi(_sonuc(tur="alt_gecit", alt_gecit_dolu=False), "alt_gecit", "X", "Y")
