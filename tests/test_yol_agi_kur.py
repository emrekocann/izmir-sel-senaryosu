"""Yol ağı kurulumu: pgRouting kenar / düğüm kayıtları ve OSM ağ filtresi."""
import networkx as nx
import pytest
import shapely

from hesap import yol_agi_kur as ya


def _graf():
    g = nx.MultiDiGraph()
    for n, x in ((10, 27.0), (20, 27.001), (30, 27.002)):
        g.add_node(n, x=x, y=38.4)
    g.add_edge(10, 20, length=100.0, highway="primary")
    g.add_edge(20, 30, length=0.0, highway=["residential", "service"],
               geometry=shapely.LineString([(27.001, 38.4), (27.002, 38.4)]))
    return g


def test_kenar_ve_dugum_kayitlari():
    g = _graf()
    no = ya.dugum_numaralari(g)
    yuks = {10: 0.0, 20: 10.0, 30: 50.0}
    k1, k2 = ya.kenar_kayitlari(g, yuks, no)
    assert k1 == (1, 2, 100.0, 10.0, "primary", "SRID=4326;LINESTRING(27.0 38.4,27.001 38.4)")
    # uzunluğu 0 gelen kenar en kısa kenar sayılır; eğim üst sınırda kırpılır; ilk yol türü alınır
    assert k2[2:5] == (ya.EN_KISA_KENAR_M, ya.EN_BUYUK_EGIM, "residential")
    assert k2[5].startswith("SRID=4326;LINESTRING")
    assert ya.dugum_kayitlari(g, yuks, no)[1] == (2, 10.0, "SRID=4326;POINT(27.001 38.4)")


@pytest.mark.parametrize("etiket, drive, walk", [
    ({"highway": "primary"}, True, True),
    ({"highway": "footway"}, False, True),
    ({"highway": "motorway", "access": "private"}, False, False),
    ({}, False, False),
])
def test_osm_filtresi(etiket, drive, walk):
    assert ya._filtre("drive")(etiket) is drive
    assert ya._filtre("walk")(etiket) is walk


def test_komut_satiri_yanlis_mod():
    with pytest.raises(SystemExit):
        ya.main(["bisiklet"])
