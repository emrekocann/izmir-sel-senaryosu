"""Yayın sayfası verisi: 'yakalandı' ölçütü ve sitenin okuduğu alanların sözleşmesi
(betik değişip site sessizce bozulmasın)."""
import os
import re

import numpy as np
import pandas as pd

from afet.dosya import json_oku
from afet.yollar import (DENETIM_JSON, ILCE_GUN_CSV, SENARYO_PNG_DIR, SITE_DENETIM_CSV, SITE_DIR, UYARI_JSON,
                         UYARI_MODEL_JSON, VITRIN)
from hesap import siniflandirma as sn
from hesap import tahmin_sinamasi as ts
from hesap import uyari_hazirla as uh
from hesap.vitrin_hazirla import MAHALLE_YUZDELIK, OLAY_SENARYOLARI, yakalandi


def _metin(*yol):
    with open(os.path.join(SITE_DIR, *yol), encoding="utf-8") as f:
        return f.read()


def _sonuc(**alanlar):
    yer = {"tur": alanlar.pop("tur"), "ilce": "X", "ad": "Y", **alanlar}
    return {"senaryolar": {s: {"yerler": [yer]} for s in OLAY_SENARYOLARI}}


def test_yakalandi_olcutu():
    assert yakalandi(_sonuc(tur="mahalle", derin_yuzdelik=MAHALLE_YUZDELIK), "mahalle", "X", "Y")
    assert not yakalandi(_sonuc(tur="mahalle", derin_yuzdelik=MAHALLE_YUZDELIK - 1), "mahalle", "X", "Y")
    assert yakalandi(_sonuc(tur="cadde", en_derin_m=0.3), "cadde", "X", "Y")
    assert not yakalandi(_sonuc(tur="cadde", en_derin_m=0.2), "cadde", "X", "Y")
    assert not yakalandi(_sonuc(tur="alt_gecit", alt_gecit_dolu=False), "alt_gecit", "X", "Y")


def test_site_verisi_sozlesmesi():
    """docs/js modüllerinin okuduğu alanlar veri dosyalarında var mı."""
    v = json_oku(VITRIN)
    d = json_oku(DENETIM_JSON)
    assert {"yagis_mm", "sure_sa", "bounds", "siniflar", "olay_senaryolari", "senaryolar", "yerler",
            "dogrulama", "dogrulama_senaryolari", "merkez", "rota_baslangic", "rotalar", "esikler"} <= set(v)
    assert {"yol_kapali_m", "mahalle_yuzdelik", "hucre_m"} <= set(v["esikler"])
    # her senaryonun görüntüsü ve özeti var
    for p in v["yagis_mm"]:
        for saat in v["sure_sa"]:
            assert f"{p}_{saat}" in v["senaryolar"]
            assert os.path.exists(os.path.join(SENARYO_PNG_DIR, f"{p}_{saat}.png"))
    for s in v["olay_senaryolari"]:
        assert {"su_30_km2", "su_10_km2", "belirsiz_km2", "toplanma_su", "toplanma_belirsiz",
                "yol_parcasi_su"} <= set(v["merkez"]["senaryolar"][s])
        assert all(s in y["olcum"] for y in v["yerler"])
    assert all(s in v["dogrulama"] for s in v["dogrulama_senaryolari"])
    assert v["rotalar"][0]["senaryo"] is None and len(v["rotalar"]) == 1 + len(v["olay_senaryolari"])
    assert {"toplam", "sayim", "dere_yakin", "dere_yakin_m", "noktalar", "liste", "senaryolar"} <= set(d)
    assert {"oncelik_1", "oncelik_2"} <= set(d["senaryolar"])
    assert len(d["noktalar"]) == d["toplam"]
    assert len(d["liste"]) == d["sayim"]["1"] + d["sayim"]["2"]
    assert os.path.exists(SITE_DENETIM_CSV)


def test_uyari_verisi_sozlesmesi():
    """docs/js/sekmeler/uyari.js'in okuduğu alanlar (hesap/uyari_hazirla.py)."""
    u = json_oku(UYARI_JSON)
    assert {"ad", "aciklama", "esik", "egitim_yillari"} <= set(u["model"])
    assert {"ilce_cagri", "il_cagri", "dalga_arasi_gun"} <= set(u["olay_tanimi"]) and "yillar" in u["veri"]
    adlar = {i["ad"] for i in u["ilceler"]}
    assert len(adlar) == 30 and all({"olay_gunu", "geometri"} <= set(i) for i in u["ilceler"])
    for k in ("kuru", "islak"):
        kosul = u["kosullar"][k]
        assert {"yagis_onceki3g_mm", "yagis_onceki7g_mm"} <= set(kosul["onceki"])
        assert set(kosul["olasilik"]) == adlar
        for p in kosul["olasilik"].values():
            assert len(p) == len(u["yagis_mm"]) and all(0 <= x <= 1 for x in p)
            if u["model"]["ad"] == "gb":                      # yağışa monoton
                assert all(a <= b + 1e-9 for a, b in zip(p, p[1:]))
    for k in ("tum_yillar", "oglen_tahmin", "tahminsiz", "canli_tahmin"):
        s = u["sinama"][k]
        assert {"atak", "atak_ilk_gun", "duyarlilik", "kesinlik", "yillar", "aralik_95"} <= set(s)
        assert {"duyarlilik", "kesinlik"} <= set(s["aralik_95"])
    assert all({"yil", "buyuk_gun", "buyuk_gun_alarmli"} <= set(y) for y in u["sinama"]["yillar"])
    tum = u["sinama"]["tum_yillar"]
    k = tum["dort_kutu"]                                     # dört kutu: alarm × sel (ilçe-gün)
    assert k["dogru_alarm"] + k["bosa_alarm"] + k["kacan"] + k["dogru_sessiz"] == k["ilce_gun"]
    assert k["dogru_alarm"] + k["kacan"] == k["sel"]
    assert abs(k["dogru_alarm"] / k["sel"] - tum["duyarlilik"]) < 1e-3
    assert abs(k["dogru_alarm"] / (k["dogru_alarm"] + k["bosa_alarm"]) - tum["kesinlik"]) < 1e-3
    d = tum["dalgalar"]                                      # büyük sel dalgaları
    assert len(d["liste"]) == tum["atak"] and d["ilk_gun_alarmli"]["dalga"] == tum["atak_ilk_gun"]
    assert d["ilk_gun_alarmli"]["dalga"] + d["ilk_gun_alarmsiz"]["dalga"] == tum["atak"]
    assert sum(a["herhangi_alarm"] for a in d["liste"]) == tum["atak_herhangi"]
    assert all({"ilk", "son", "gun", "ilk_gun_alarm", "herhangi_alarm", "ilce", "cagri", "il_cagri", "yagis_mm",
                "onceki7g_mm"} <= set(a) and a["ilce"] in adlar for a in d["liste"])
    e = u["egitim"]
    assert u["model"]["ad"] in e["modeller"] and e["secim_yillari"][0] < e["secim_yillari"][1]
    assert any(y > e["secim_yillari"][1] for y in tum["yillar"])     # seçimde hiç kullanılmamış sınav yılı var
    o = u["ornek"]
    assert {"ilce", "gun", "haber_mm", "haber_saat", "arsiv_mm", "tahmin_mm", "cagri", "cagri_gun_sayisi",
            "kaynaklar"} <= set(o) and o["ilce"] in adlar
    g = u["gwr"]
    assert {"bant", "olcek_mm", "sinama", "cok_nokta_sira_korelasyonu", "ilceler"} <= set(g)
    assert len(g["sinama"]["ap_farki"]) == 3
    assert all({"ap", "duyarlilik", "kesinlik", "yillar"} <= set(g["sinama"][m]) for m in ("gwr", "global"))
    assert set(g["ilceler"]) == adlar
    for i in g["ilceler"].values():
        for gorunum in ("gunun_yagisi", "onceki_hafta"):
            c = i[gorunum]
            assert c["aralik_95"][0] <= c["deger"] <= c["aralik_95"][1] and isinstance(c["kanitli"], bool)


def test_uyari_modeli_sozlesmesi():
    """docs/js/cekirdek/canli.js'in okuduğu model: ilçeler (yağış noktası + sabit girdiler),
    tahmin modeli, ağaçlar. Ayrıca "kendin dene" tablosunu (sklearn'le hesaplanmış) aynen
    yeniden üretir: sayfadaki iki görünüm aynı modeli kullanıyor."""
    u, m = json_oku(UYARI_JSON), json_oku(UYARI_MODEL_JSON)
    assert m["tahmin_modeli"] == ts.ANA and m["girdiler"] == sn.MODELLER[u["model"]["ad"]].kolonlar
    assert set(m["ilceler"]) == {i["ad"] for i in u["ilceler"]}
    sabit = [g for g in m["girdiler"] if not g.startswith("yagis_")]
    for i in m["ilceler"].values():
        assert set(sabit) <= set(i) and 37.5 < i["lat"] < 39.5 and 26 < i["lon"] < 28.6   # İzmir
    assert all(len(d) in (1, 4) for agac in m["agaclar"] for d in agac)

    class Disa:                                          # dışa aktarılmış model, sklearn arayüzüyle
        def predict_proba(self, X):
            p = uh.agac_olasiligi(m, X)
            return np.column_stack([1 - p, p])

    t = sn.hazirla(pd.read_csv(ILCE_GUN_CSV))
    for k, kosul in u["kosullar"].items():
        tb = sn.olasilik_tablosu(t, Disa(), m["girdiler"], kosul["onceki"])["ilce"]
        for ad, p in kosul["olasilik"].items():
            assert np.allclose(tb[ad], p, atol=1.01e-3), (k, ad)


def test_hakkinda_doldurma_alanlari():
    """index.html'deki her data-doldur alanını docs/js/hakkinda.js dolduruyor
    (adı yanlış yazılan alan sitede sessizce boş kalırdı)."""
    alanlar = set(re.findall(r'data-doldur="([^"]+)"', _metin("index.html")))
    tanimli = set(re.findall(r"'([a-z0-9-]+)':", _metin("js", "hakkinda.js")))
    assert alanlar and alanlar <= tanimli, sorted(alanlar - tanimli)


def test_sekmelerde_elle_yazili_esik_yok():
    """Eşikler ve ağ büyüklüğü sekme metinlerine elle yazılmaz; veriden gelir
    (vitrin.esikler, denetim.senaryolar, rota ağı)."""
    klasor = os.path.join(SITE_DIR, "js", "sekmeler")
    for ad in sorted(os.listdir(klasor)):
        metin = _metin("js", "sekmeler", ad)
        bulunan = re.findall(r"\b(?:30 cm|60 m\b|100 mm|150 mm|82 bin|873\b|11 ilçe|5 kat)|%25", metin)
        assert not bulunan, (ad, bulunan)


def test_dis_dosyalar_butunluk_denetimli():
    """Başka sunucudan yüklenen her betik ve stil dosyası parmak iziyle (SRI)
    yüklenir: dosya değiştirilirse tarayıcı onu çalıştırmaz."""
    sayfa = _metin("index.html")
    etiketler = re.findall(r"<(?:script|link)\b[^>]*\b(?:src|href)=\"https?://[^>]*>", sayfa)
    assert etiketler
    for etiket in etiketler:
        assert re.search(r'integrity="sha(?:256|384|512)-[A-Za-z0-9+/=]+"', etiket), etiket
        assert 'crossorigin="anonymous"' in etiket, etiket
