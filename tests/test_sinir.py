import pytest

from afet import sinir


def test_cerceve_sinir_dosyasindan_turetilir():
    b = sinir.cerceve_hesapla()
    assert b["lat_min"] < b["lat_max"]
    assert b["lon_min"] < b["lon_max"]


def test_cerceve_dogu_ilcelerini_kapsar():
    # Eski hardcoded bbox (27.50°D) Ödemiş/Kiraz/Beydağ'ı dışarıda bırakıyordu;
    # sınır dosyasından türetilen bbox ilin tamamını kapsamalı (Kiraz ~28.20°D).
    assert sinir.CERCEVE["lon_max"] > 28.2
    assert sinir.CERCEVE["lat_max"] > 39.3
    assert sinir.CERCEVE["lat_min"] < 37.9


def test_merkez_cercevenin_icinde():
    assert sinir.CERCEVE["lat_min"] <= sinir.MERKEZ_ENLEM <= sinir.CERCEVE["lat_max"]
    assert sinir.CERCEVE["lon_min"] <= sinir.MERKEZ_BOYLAM <= sinir.CERCEVE["lon_max"]


def test_il_poligonu_cerceveyle_uyusur():
    pytest.importorskip("shapely")
    bati, guney, dogu, kuzey = sinir.il_poligonu().bounds
    c = sinir.cerceve_hesapla(pay=0)
    assert (round(guney, 4), round(kuzey, 4)) == (c["lat_min"], c["lat_max"])
    assert (round(bati, 4), round(dogu, 4)) == (c["lon_min"], c["lon_max"])
