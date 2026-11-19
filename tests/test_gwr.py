"""GWR: çekirdek ağırlıkları ve bölgeye göre değişen etkiyi bulma."""
import json
import os

import numpy as np
import pandas as pd
import pytest

from hesap import gwr


def _ilceler():
    """Batıda 4, doğuda 4 ilçe (aralarında ~150 km)."""
    lon = [26.6, 26.7, 26.6, 26.7, 28.4, 28.5, 28.4, 28.5]
    lat = [38.3, 38.3, 38.4, 38.4, 38.3, 38.3, 38.4, 38.4]
    return pd.DataFrame({"ilce": [f"i{k}" for k in range(8)], "yagis_lon": lon, "yagis_lat": lat})


def _veri(n_gun=1500, tohum=0):
    """Batıda yağış olayı güçlü belirler, doğuda neredeyse hiç."""
    r = np.random.default_rng(tohum)
    satir = []
    for k in range(8):
        etki = 2.0 if k < 4 else 0.1
        ly = np.log1p(r.gamma(0.4, 15, n_gun) * (r.random(n_gun) < 0.3))
        p = 1 / (1 + np.exp(-(-4 + etki * ly)))
        satir.append(pd.DataFrame({"ilce": f"i{k}", "log_yagis": ly, "log_dun": r.random(n_gun),
                                   "log_onceki7g": r.random(n_gun), "olay": (r.random(n_gun) < p).astype(int),
                                   "yil": np.repeat(np.arange(2020, 2025), n_gun // 5 + 1)[:n_gun]}))
    return pd.concat(satir, ignore_index=True)


def test_agirliklar_bisquare():
    d = gwr.uzakliklar(_ilceler())
    w = gwr.agirliklar(d, "i0", 4)
    assert len(w) == 4 and w["i0"] == 1 and set(w.index) == {"i0", "i1", "i2", "i3"}
    assert ((w > 0) & (w <= 1)).all()
    assert len(gwr.agirliklar(d, "i0", 8)) == 8                     # bant = bütün ilçeler


def test_bolgeye_gore_degisen_etkiyi_bulur():
    d = gwr.uzakliklar(_ilceler())
    k = gwr.GWLR(d, 4).fit(_veri()).katsayilar()
    bati = np.mean([k[f"i{i}"]["log_yagis"] for i in range(4)])
    dogu = np.mean([k[f"i{i}"]["log_yagis"] for i in range(4, 8)])
    assert bati > 3 * max(dogu, 0.05)
    # global (bütün uzaklıklar 0: her ilçe her modele tam ağırlıkla) iki bölgeyi ortalar
    g = gwr.GWLR(d * 0, 8).fit(_veri()).katsayilar()
    assert abs(g["i0"]["log_yagis"] - g["i7"]["log_yagis"]) < abs(k["i0"]["log_yagis"] - k["i7"]["log_yagis"])


def test_yerel_model_yil_disarida_globali_gecer():
    d = gwr.uzakliklar(_ilceler())
    t = _veri()
    yerel, _ = gwr.yil_disarida_ap(t, d, 4, sorted(t.yil.unique()))
    globl, _ = gwr.yil_disarida_ap(t, d * 0, 8, sorted(t.yil.unique()))
    assert yerel > globl


def test_harita_ozeti_baska_yagis_kolonuyla():
    """Sağlamlık sınaması günün yağışını başka bir kolondan alır (ilk kolon)."""
    d = gwr.uzakliklar(_ilceler())
    t = _veri().rename(columns={"log_yagis": "log_max_nokta"})
    h = {i["ilce"]: i for i in gwr.harita_ozeti(t, d, 4, 0, gwr.COK_NOKTA)}
    assert set(h["i0"]["katsayi"]) == {"sabit", *gwr.COK_NOKTA}
    assert h["i0"]["odds_orani_10_40"] > h["i7"]["odds_orani_10_40"]
    assert h["i0"]["p_40"] > h["i0"]["p_10"]


@pytest.mark.skipif(not os.path.exists(gwr.SONUC_JSON), reason="GWR çalıştırılmadı")
def test_sonuc_dosyasi_sozlesmesi():
    r = json.load(open(gwr.SONUC_JSON, encoding="utf-8"))
    assert str(r["bant"]) in r["bantlar"]
    assert {"gwr", "global", "lojistik"} == set(r["sonuclar"])
    assert len(r["ilceler"]) == 30
    for i in r["ilceler"]:
        assert {"ilce", "katsayi", "aralik_95", "odds_orani_10_40", "p_10", "p_40"} <= set(i)
    c = r["cok_nokta"]
    assert c["degiskenler"] == gwr.COK_NOKTA and len(c["ilceler"]) == 30
    assert len(c["sonuc"]["ap_farki_tek_noktaya_gore"]) == 3
    assert all(set(gwr.COK_NOKTA) <= set(i["aralik_95"]) for i in c["ilceler"])
