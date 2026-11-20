"""Ek değişkenler: ızgara noktaları, ilçe-gün özellikleri, eşleştirilmiş AP farkı."""
import numpy as np
import pandas as pd

from hesap import ek_degiskenler as ed


def _geo():
    def kare(x0, y0, a):
        return {"type": "Polygon", "coordinates": [[[x0, y0], [x0 + a, y0], [x0 + a, y0 + a], [x0, y0 + a], [x0, y0]]]}

    return {"features": [{"properties": {"ILCEADI": "BÜYÜK"}, "geometry": kare(27.0, 38.0, 0.3)},
                         {"properties": {"ILCEADI": "KÜÇÜK"}, "geometry": kare(28.01, 38.01, 0.02)}]}


def test_noktalar_asil_nokta_ve_izgara():
    ilce = pd.DataFrame({"ilce": ["Büyük", "Küçük"], "yagis_lat": [38.1, 38.02], "yagis_lon": [27.1, 28.02]})
    n = ed.noktalar(ilce, _geo())
    assert n.groupby("ilce").ana.sum().to_dict() == {"Büyük": 1, "Küçük": 1}
    assert (n.ilce == "Büyük").sum() == 1 + 9          # 0.3° kare → 3 × 3 ızgara merkezi
    assert (n.ilce == "Küçük").sum() == 1              # ızgara merkezi düşmeyen küçük ilçe: yalnız asıl nokta


def test_ozellikler_en_buyuk_yagis_ve_lodos():
    g = pd.DataFrame({"ilce": ["a"] * 3 + ["b"], "gun": ["g1"] * 4, "ana": [True, False, False, True],
                      "yagis": [5.0, 40.0, np.nan, 2.0], "ruzgar": [50.0, np.nan, np.nan, 50.0],
                      "yon": [220.0, np.nan, np.nan, 20.0]})
    o = ed.ozellikler(g).set_index("ilce")
    assert o.loc["a", "yagis_max_nokta_mm"] == 40 and o.loc["b", "yagis_max_nokta_mm"] == 2
    assert o.loc["a", "lodos_kmh"] == 50 and o.loc["b", "lodos_kmh"] == 0      # kuzeyli rüzgâr lodos değil
    assert o.loc["b", "ruzgar_max_kmh"] == 50


def test_eslesik_fark_ayni_tahminde_sifir_daha_iyide_pozitif():
    r = np.random.default_rng(0)
    gun = pd.date_range("2024-01-01", periods=300).strftime("%Y-%m-%d").repeat(3)
    olay = (r.random(len(gun)) < 0.1).astype(int)
    a = pd.DataFrame({"ilce": np.tile(["x", "y", "z"], 300), "gun": gun, "olay": olay, "p": r.random(len(gun))})
    assert ed.eslesik_fark(a, a, n=50) == [0.0, 0.0, 0.0]
    b = a.assign(p=olay * 0.5 + r.random(len(gun)) * 0.5)
    fark, alt, ust = ed.eslesik_fark(a, b, n=100)
    assert fark > 0 and alt > 0 and alt <= fark <= ust


def test_gunluk_arsiv_ruzgari_yalniz_asil_noktaya_baglar(monkeypatch):
    nok = pd.DataFrame({"ilce": ["a", "a", "b"], "lat": [38.0, 38.1, 38.2], "lon": [27.0, 27.1, 27.2],
                        "ana": [True, False, True]})
    gun = ["2025-01-01", "2025-01-02"]

    def sahte(n, b, s, degiskenler, ad):
        if ad == "yagis":
            return [{"daily": {"time": gun, "precipitation_sum": [i, i + 10]}} for i in range(len(n))]
        return [{"daily": {"time": gun, "wind_speed_10m_max": [30 + i, 60], "wind_direction_10m_dominant": [200, 10]}}
                for i in range(len(n))]

    monkeypatch.setattr(ed, "_gunluk", sahte)
    import datetime as dt
    g = ed.gunluk_arsiv(nok, dt.date(2025, 1, 1), dt.date(2025, 1, 2))
    assert len(g) == 6 and g[~g.ana].ruzgar.isna().all() and g[g.ana].ruzgar.notna().all()
    o = ed.ozellikler(g).set_index(["ilce", "gun"])
    assert o.loc[("a", "2025-01-02"), "yagis_max_nokta_mm"] == 11
    assert o.loc[("b", "2025-01-01"), "lodos_kmh"] == 31 and o.loc[("b", "2025-01-02"), "lodos_kmh"] == 0
