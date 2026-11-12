"""Toplanma alanı denetimi: öncelik kuralı."""
from hesap.toplanma_denetimi import en_kucuk_yagis, oncelik


def test_oncelik_kurali():
    assert oncelik({"50_24": 0.4}, set()) == 1                 # 24 saate yayılmış ≤ 100 mm
    assert oncelik({"100_6": 0.3}, set()) == 2                 # 2021 benzeri yağış
    assert oncelik({"150_24": 1.2, "250_1": 2.0}, set()) == 2
    assert oncelik({"250_1": 0.5}, set()) == 3                 # yalnız şiddetli senaryo
    assert oncelik({"100_6": 0.2}, set()) is None              # 30 cm'in altı sayılmaz
    assert oncelik({"100_6": 0.2}, {"50_1"}) == "ova"          # düz ova, derinlik belirsiz
    assert oncelik({"50_24": 0.4}, {"50_1"}) == 1              # hesaplanan derinlik önce gelir


def test_en_kucuk_yagis():
    assert en_kucuk_yagis({"100_6": 0.5, "50_1": 0.4, "50_6": 0.3, "25_24": 0.1}) == (50, 6)
    assert en_kucuk_yagis({"100_6": 0.2}) is None
