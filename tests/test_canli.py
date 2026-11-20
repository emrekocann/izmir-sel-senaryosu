"""Canlı tahmin (docs/js/cekirdek/canli.js) Python hesabıyla birebir aynı mı?

Sayfa yarının tahminini tarayıcıda hesaplar: yağış girdileri
hesap/ilce_gun.gunluk_yagis'in, olasılık sklearn modelinin aynısı olmalı.
Modül Node ile çalıştırılır; Node yoksa bu testler atlanır."""
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier

from afet.yollar import SITE_DIR
from hesap import uyari_hazirla as uh
from hesap.ilce_gun import gunluk_yagis

CANLI_JS = Path(SITE_DIR) / "js" / "cekirdek" / "canli.js"
YAGIS = ["yagis_mm", "yagis_max1s_mm", "yagis_max3s_mm", "yagis_dun_mm", "yagis_onceki3g_mm", "yagis_onceki7g_mm"]
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node yok")


def _js(ifade, veri=None):
    """canli.js'i Node'da yükler; `ifade` (m: modül, v: veri) değerlendirilir, sonucu JSON döner."""
    kod = ("const m = await import(" + json.dumps(CANLI_JS.as_uri()) + ");"
           "process.stdin.setEncoding('utf8'); let s = ''; for await (const parca of process.stdin) s += parca;"
           "const v = JSON.parse(s);"
           "process.stdout.write(JSON.stringify(await (" + ifade + ")));")
    r = subprocess.run(["node", "--input-type=module", "-e", kod], input=json.dumps(veri), capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _saatlik(gun_sayisi=14, tohum=0):
    """0,1 mm adımlı saatlik yağış: kuru saatler, sağanaklar; ilk gün bir saat eksik."""
    r = np.random.default_rng(tohum)
    zaman = pd.date_range("2026-01-01", periods=24 * gun_sayisi, freq="h")
    mm = np.where(r.random(len(zaman)) < 0.7, 0.0, np.round(r.gamma(0.6, 3.0, len(zaman)), 1))
    mm[r.integers(0, len(zaman), 6)] += 25.0                  # birkaç sağanak saati
    mm[5] = np.nan
    return zaman, mm


def test_yagis_girdileri_gunluk_yagis_ile_ayni():
    zaman, mm = _saatlik()
    beklenen = gunluk_yagis(pd.DataFrame({"ilce": "a", "zaman": zaman, "mm": mm})).set_index("gun")
    hedefler = [str(g) for g in beklenen.index[8:]]          # önceki 7 günü tam olan günler
    saatler = [z.strftime("%Y-%m-%dT%H:%M") for z in zaman]
    js = _js("v.hedefler.map((h) => m.yagisGirdileri(v.saatler, v.mm, h))",
             {"saatler": saatler, "mm": [None if np.isnan(x) else float(x) for x in mm], "hedefler": hedefler})
    for hedef, g in zip(hedefler, js):
        b = beklenen.loc[pd.Timestamp(hedef).date()]
        assert g == {k: float(b[k]) for k in YAGIS}, hedef


def test_eksik_saat_ya_da_eksik_gecmis_tahmin_vermez():
    zaman, mm = _saatlik(gun_sayisi=10)
    saatler = [z.strftime("%Y-%m-%dT%H:%M") for z in zaman]
    temiz = [float(x) if not np.isnan(x) else 0.0 for x in mm]
    hedef_eksik = list(temiz)
    hedef_eksik[-3] = None                                   # hedef günde bir saat yok
    gecmis_eksik = list(temiz)
    gecmis_eksik[24 * 5] = None                              # önceki 7 günden birinde bir saat yok
    js = _js("[m.yagisGirdileri(v.s, v.temiz, '2026-01-10'), m.yagisGirdileri(v.s, v.hedef, '2026-01-10'),"
             " m.yagisGirdileri(v.s, v.gecmis, '2026-01-10'),"
             " m.yagisGirdileri(v.s.slice(72), v.temiz.slice(72), '2026-01-10')]",
             {"s": saatler, "temiz": temiz, "hedef": hedef_eksik, "gecmis": gecmis_eksik})
    assert js[0] is not None and js[1:] == [None, None, None]   # son: kayıt hedeften 7 gün öncesine gitmiyor


def test_yuvarlama_numpy_ile_ayni():
    x = [0.05, 0.15, 0.25, 0.35, 2.45, 2.55, 12.25, 7.85, 1.0000000000000002, 0.30000000000000004, 99.95, 0.0]
    assert _js("v.map(m.yuvarla1)", x) == [float(v) for v in np.round(x, 1)]


def _model(tohum=1):
    """Küçük, yağışa monoton gradient boosting (sayfadaki modelin biçimi) ve girdileri.
    Sayfadaki gibi: yağış 0,1 mm adımlı, nüfus ve kent payı 30 ilçenin sabit değerleri."""
    r = np.random.default_rng(tohum)
    ilce = r.integers(0, 30, 4000)
    X = np.column_stack([np.round(r.gamma(0.8, 8, 4000), 1) for _ in YAGIS]
                        + [r.normal(11, 1, 30)[ilce], np.round(r.random(30), 4)[ilce]])
    y = (r.random(4000) < 1 / (1 + np.exp(-(X[:, 0] / 15 + X[:, 5] / 40 - 4)))).astype(int)
    m = HistGradientBoostingClassifier(max_iter=40, max_leaf_nodes=15, early_stopping=False, random_state=0,
                                       monotonic_cst=[1] * len(YAGIS) + [0, 0]).fit(X, y)
    return m, X


def test_olasilik_sklearn_ile_ayni():
    m, X = _model()
    model = uh.model_disa_aktar(m, YAGIS + ["log_nufus", "kent_payi"])
    X = X[:300]
    js = np.array(_js("v.X.map((x) => m.olasilik(v.model, x))", {"model": model, "X": X.tolist()}))
    p = m.predict_proba(X)[:, 1]
    assert np.abs(js - p).max() < 1e-9
    assert np.abs(js - uh.agac_olasiligi(model, X)).max() < 1e-12      # Python kopyası da aynı kural


def test_tahminler_girdileri_modelin_sirasiyla_dizer():
    m, X = _model()
    model = {**uh.model_disa_aktar(m, YAGIS + ["log_nufus", "kent_payi"]),
             "ilceler": {"a": {"log_nufus": float(X[0, 6]), "kent_payi": float(X[0, 7])},
                         "b": {"log_nufus": 11.0, "kent_payi": 0.5}}}
    yagis = dict(zip(YAGIS, X[0, :6].tolist()))
    js = _js("m.tahminler(v.model, { a: v.yagis, b: null }, 0.3)", {"model": model, "yagis": yagis})
    p = float(m.predict_proba(X[:1])[0, 1])
    assert js["b"] is None and js["a"]["yagis"] == yagis
    assert abs(js["a"]["p"] - p) < 1e-9 and js["a"]["alarm"] == (p >= 0.3)


def test_istanbul_gunu_ve_yarin():
    js = _js("v.map(([an, k]) => m.istanbulGunu(new Date(an), k))",
             [["2026-11-20T20:59:00Z", 0], ["2026-11-20T21:00:00Z", 0], ["2026-11-20T21:00:00Z", 1],
              ["2026-12-31T21:30:00Z", 1]])
    assert js == ["2026-11-20", "2026-11-21", "2026-11-22", "2027-01-02"]   # İstanbul UTC+3


def test_yarinin_girdileri_tek_istek_ve_hata():
    """Sahte servisle: istenen adres, yarının günü, servis hatasının iletisi."""
    saat = pd.date_range("2026-11-13", "2026-11-21 23:00", freq="h").strftime("%Y-%m-%dT%H:%M").tolist()
    nokta = {"hourly": {"time": saat, "precipitation": [0.2] * len(saat)}}
    model = {"tahmin_modeli": "ecmwf_ifs025",
             "ilceler": {"a": {"lat": 38.41234, "lon": 27.1}, "b": {"lat": 38.5, "lon": 27.2}}}
    js = _js("""(async () => {
      let adres;
      const tamam = await m.yarininGirdileri(v.model, { simdi: new Date('2026-11-20T09:00:00Z'),
        getir: async (a) => { adres = a; return { ok: true, json: async () => [v.nokta, v.nokta] }; } });
      const hata = await m.yarininGirdileri(v.model, { simdi: new Date('2026-11-20T09:00:00Z'),
        getir: async () => ({ ok: false, status: 429, json: async () => ({ error: true, reason: 'çok istek' }) }) })
        .catch((h) => h.message);
      return { adres, tamam, hata };
    })()""", {"model": model, "nokta": nokta})
    q = dict(x.split("=") for x in js["adres"].split("?")[1].split("&"))
    assert q["models"] == "ecmwf_ifs025" and q["past_days"] == "7" and q["forecast_days"] == "2"
    assert q["latitude"] == "38.4123%2C38.5000" and q["timezone"] == "Europe%2FIstanbul"
    assert js["tamam"]["hedef"] == "2026-11-21" and set(js["tamam"]["girdiler"]) == {"a", "b"}
    assert js["tamam"]["girdiler"]["a"]["yagis_mm"] == 4.8 and js["tamam"]["girdiler"]["a"]["yagis_onceki7g_mm"] == 33.6
    assert js["hata"] == "çok istek"
