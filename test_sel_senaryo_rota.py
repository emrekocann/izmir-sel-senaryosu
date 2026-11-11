"""Rota ↔ yağış senaryosu bağlantısı: kenar derinliği, maliyet SQL'i, rapor."""
import numpy as np
import pytest

from repository import AfetRepository as R
from sel_senaryo import BELIRSIZ
from sel_senaryo_yollar import kenar_derinligi, satirlar


def test_kenar_derinligi_en_derin_nokta_ve_kopru():
    # 3 kenar: 0 → [0.0, 0.4 m], 1 → [0.2, belirsiz], 2 → [köprüde 1.5 m, 0]
    dm = np.array([0, 4, 2, BELIRSIZ, 15, 0], dtype=np.float32)
    ki = np.array([0, 0, 1, 1, 2, 2])
    kopru = np.array([False, False, False, False, True, False])
    d, b = kenar_derinligi(dm, ki, 3, kopru)
    assert np.allclose(d, [0.4, 0.2, 0.0])          # en derin nokta, köprü kuru
    assert b.tolist() == [False, True, False]
    with pytest.raises(ValueError):                    # örneksiz kenar sessiz kaymasın
        kenar_derinligi(dm, ki, 4)


def test_yalniz_islak_ya_da_belirsiz_satirlar_yazilir():
    ids = np.array([10, 11, 12, 13])
    d = np.array([0.0, 0.05, 0.1, 0.0])
    b = np.array([False, False, False, True])
    assert satirlar("drive", "50_1", ids, d, b) == [
        ("drive", "50_1", 12, 0.1, False), ("drive", "50_1", 13, 0.0, True)]


def test_maliyet_sql_senaryo_cezasi():
    duz = R._maliyet_sql("izmir_roads_noded", 0.05, True, 1.0, 0.0)
    assert "sel_senaryo_su" not in duz
    join = R._senaryo_join("drive", "50_1")
    sql = R._maliyet_sql("izmir_roads_noded", 0.05, True, 1.0, 0.0, join, alt_gecit_kapali=True)
    assert "ss.senaryo = '50_1'" in sql and "ss.katman = 'drive'" in sql
    assert "ss.kimlik = rn.id" in sql
    assert f"ss.derinlik >= {R.SENARYO_KAPALI_M}" in sql      # su basan yol kapalı
    assert "rn.alt_gecit" in sql                               # dolu alt geçit kapalı
    assert "alt_gecit" not in R._maliyet_sql("izmir_roads_noded", 0.05, True, 1.0, 0.0, join)


@pytest.mark.parametrize("senaryo", ["50_1'; DROP TABLE x; --", "50", "abc_1", "1234_1"])
def test_senaryo_adi_dogrulanir(senaryo):
    # kenar sorgusu pgr_dijkstra'ya metin gider: senaryo adı metne gömülmeden doğrulanır
    with pytest.raises(ValueError):
        R._senaryo_join("drive", senaryo)


def test_senaryo_ozeti_yer_sayisi():
    def k(d, b=None, uz=100.0, ag=False):
        return {"su_derinlik": d, "su_belirsiz": b, "length": uz, "alt_gecit": ag}
    # kuru, derin, derin (aynı yer), sığ, kuru, derin, belirsiz
    rows = [k(None), k(0.5, False), k(0.8, False), k(0.2, False), k(None),
            k(0.4, False), k(0.0, True, 250.0)]
    o = R._senaryo_ozeti(rows, "50_1", True, True, False, None, None)
    assert o["derin_yer"] == 2 and o["sig_yer"] == 1
    assert o["en_derin_m"] == 0.8 and o["belirsiz_m"] == 250
    assert o["alt_gecit_rotada"] == 0 and o["hedef_su"] is None


def test_rota_ucu_senaryo_parametresi():
    from fastapi.testclient import TestClient
    import main
    istemci = TestClient(main.app)
    r = istemci.get("/api/v1/routing/smart",
                    params={"user_lon": 27.2, "user_lat": 38.45, "senaryo": "50_1; --"})
    assert r.status_code == 422          # biçim dışı senaryo reddedilir
