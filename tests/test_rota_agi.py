"""Tarayıcıda rota: ağın zincirlenmesi, senaryo suyu ve JS Dijkstra motoru."""
import json
import os
import shutil
import subprocess

import numpy as np
import pytest

from afet.dosya import json_oku
from afet.yollar import ROTA_AGI, ROTA_VERI_DIR, SITE_DIR, VITRIN
from hesap import rota_agi_hazirla as ra

MOTOR = os.path.join(SITE_DIR, "js", "cekirdek", "rota_motoru.js")


def test_cift_yonlu_ikizler_atilir():
    # 0: 1→2, 1: 2→1 (ikizi), 2: 1→2 başka uzunlukta (paralel ayrı yol)
    tut, ikiz = ra.ikizleri_ayikla([1, 2, 1], [2, 1, 2], [100.0, 100.2, 250.0])
    assert tut.tolist() == [True, False, True] and ikiz == {1: 0}


def test_zincirleme_kavsak_alan_ve_otoyol_sinirinda_durur():
    #  1 —a— 2 —b— 3 —c— 4 ,  3 —d— 5 ;  2 toplanma alanı düğümü değil
    kaynak = [1, 3, 3, 3]
    hedef = [2, 2, 4, 5]
    z = ra.zincirle(kaynak, hedef, korunan=set(), ayri=np.array([False, False, False, False]))
    # 2 iki kenarlı: a+b birleşir; 3 kavşak (üç kenar)
    uzun = [p for _, _, p in z if len(p) == 2]
    assert len(z) == 3 and len(uzun) == 1
    bas, son, parcalar = next(t for t in z if len(t[2]) == 2)
    assert {bas, son} == {1, 3}
    # parçalar baştan sona sıralı, yönü doğru
    yol = [bas]
    for e, ters in parcalar:
        assert (kaynak[e] if not ters else hedef[e]) == yol[-1]
        yol.append(hedef[e] if not ters else kaynak[e])
    assert yol[-1] == son
    # 2 toplanma alanının düğümüyse korunur
    assert len(ra.zincirle(kaynak, hedef, {2}, np.zeros(4, bool))) == 4
    # a otoyol, b değil: 2'de birleşmez (otoyola bağlanılmaz)
    assert len(ra.zincirle(kaynak, hedef, set(), np.array([True, False, False, False]))) == 4


def test_su_ozeti_sunucu_maliyetiyle_ayni():
    taban = np.array([100.0, 200.0, 50.0])
    parcalar = [(0, False), (1, False), (2, False)]
    su = {0: (0.2, False), 1: (0.0, True), 2: (0.5, False)}     # sığ, düz ova, derin
    ek, en_derin, derin, islak = ra.su_ozeti(parcalar, taban, su)
    assert ek == pytest.approx((100 + 200) * (ra.ISLAK_K - 1) + ra.KAPALI_EK)
    assert (en_derin, derin, islak) == (0.5, 1, 2)
    assert ra.su_ozeti(parcalar, taban, {}) == (0.0, 0.0, 0, 0)


def test_fark_kodlama_geri_cozulur():
    s = [5, 7, 7, 3, 100]
    assert np.cumsum(ra.fark_kodla(s)).tolist() == s and ra.fark_kodla([]) == []


def _kucuk_ag():
    """   0 ——(kuru, 3 km)—— 1 ——— 2 [alan 10]
          0 ——(kısa ama derin su)—— 2
          0 ——— 3 [alan 20, senaryoda su altında, en yakın]
          0 ——(otoyol)—— 4  """
    xy = [(27.0, 38.4), (27.02, 38.41), (27.03, 38.40), (26.999, 38.399), (26.99, 38.41)]
    a, b = [0, 1, 0, 0, 0], [1, 2, 2, 3, 4]
    m = [2500, 500, 1000, 150, 900]
    return {
        "olcek": 100000, "ilceler": ["X"],
        "dugum_x": ra.fark_kodla([round(x * 1e5) for x, _ in xy]),
        "dugum_y": ra.fark_kodla([round(y * 1e5) for _, y in xy]),
        "kenar_a": a, "kenar_b": b, "kenar_m": m, "kenar_maliyet": m,
        "ic_sayi": [1, 0, 0, 0, 0], "ic": [1000, 500],
        "otoyol": [4], "alt_gecit": {"1": 1},
        "alanlar": [[2, 27.03, 38.40, 10, "1 NO LU", "X", "Y"], [3, 26.999, 38.399, 20, "2 NO LU", "X", "Z"]],
        "kapsam": {"type": "Polygon", "coordinates": []},
        "maliyet": {"egim_k": 0.05, "islak_k": 5.0, "kapali_m": 0.3, "kapali_ek": 100000.0},
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node yok")
def test_js_motoru(tmp_path):
    ag = tmp_path / "ag.json"
    ag.write_text(json.dumps(_kucuk_ag()))
    su = {"kenar": [2], "ek": [100000], "derin_dm": [6], "derin_parca": [1], "sig_parca": [0], "kapali_alan": [20]}
    betik = tmp_path / "dene.mjs"
    betik.write_text(f"""
import fs from 'fs';
import * as M from {json.dumps(MOTOR)};
const ag = M.agKur(JSON.parse(fs.readFileSync({json.dumps(str(ag))})));
const su = M.suKur(ag, {json.dumps(su)});
const kuru = M.rotaBul(ag, 0, null);
const islak = M.rotaBul(ag, 0, su);
const herSey = {{ ...su, kapaliAlan: new Set([10, 20]) }};
const dolu = M.rotaBul(ag, 0, su, true);
const kuruOzet = M.rotaOzeti(ag, islak, su);
console.log(JSON.stringify({{
  kuru: kuru.alan.id, islak: islak.alan.id, islakKenar: islak.kenarlar, islakM: kuruOzet.metre,
  hicAlanYok: M.rotaBul(ag, 0, herSey),
  ters: M.rotaCizgisi(ag, {{ dugumler: [1, 0], kenarlar: [0] }}),
  dolu: [dolu.kenarlar, M.rotaOzeti(ag, dolu, su, true)],
  yakinOtoyol: M.enYakinDugum(ag, 26.99, 38.41),
  uzak: M.enYakinDugum(ag, 28.5, 39.0),
}}));
""")
    r = json.loads(subprocess.run(["node", str(betik)], capture_output=True, text=True, check=True).stdout)
    assert r["kuru"] == 20                       # yağışsız: en yakın alan
    # senaryoda alan 20 su altında, 0–2 kısa yolu derin suda: 3 km'lik kuru yoldan alan 10
    assert r["islak"] == 10 and r["islakKenar"] == [0, 1] and r["islakM"] == 3000
    assert r["hicAlanYok"] is None
    # kenar ters yönde geçilince ara nokta da ters sırada
    assert r["ters"] == [[27.02, 38.41], [27.01, 38.405], [27.0, 38.4]]
    # alt geçit (kenar 1) de doluysa iki yol da kapalı: kısa olan derin sudan
    # geçilir ve söylenir
    kenarlar, ozet = r["dolu"]
    assert kenarlar == [2] and ozet["derinParca"] == 1 and ozet["enDerinM"] == 0.6 and ozet["altGecit"] == 0
    # otoyola bağlanılmaz: otoyolun ucundaki 4 değil, en yakın sıradan düğüm
    assert r["yakinOtoyol"]["dugum"] != 4
    assert r["uzak"] is None


@pytest.mark.skipif(not os.path.exists(ROTA_AGI), reason="rota ağı üretilmedi")
def test_rota_verisi_sozlesmesi():
    ag = json_oku(ROTA_AGI)
    v = json_oku(VITRIN)
    n, e = len(ag["dugum_x"]), len(ag["kenar_a"])
    assert len(ag["dugum_y"]) == n and e == len(ag["kenar_b"]) == len(ag["kenar_m"]) == len(ag["ic_sayi"])
    assert len(ag["ic"]) == 2 * sum(ag["ic_sayi"])
    assert max(max(ag["kenar_a"]), max(ag["kenar_b"])) < n
    assert ag["alanlar"] and all(0 <= a[0] < n for a in ag["alanlar"])
    # sayfadaki her senaryonun su dosyası var ve kenar sırası ağın içinde
    for mm in v["yagis_mm"]:
        for saat in v["sure_sa"]:
            su = json_oku(os.path.join(ROTA_VERI_DIR, f"su_{mm}_{saat}.json"))
            k = np.cumsum(su["kenar"])
            assert len(k) == len(su["ek"]) == len(su["derin_dm"]) and (len(k) == 0 or k.max() < e)
