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


def test_site_verisi_sozlesmesi():
    """docs/js modüllerinin okuduğu alanlar veri dosyalarında var mı
    (betik değişip site sessizce bozulmasın)."""
    import json
    import os
    kok = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "veri")
    v = json.load(open(os.path.join(kok, "vitrin.json"), encoding="utf-8"))
    d = json.load(open(os.path.join(kok, "denetim.json"), encoding="utf-8"))
    assert {"yagis_mm", "sure_sa", "bounds", "siniflar", "olay_senaryolari", "senaryolar", "yerler",
            "dogrulama", "dogrulama_senaryolari", "merkez", "rota_baslangic", "rotalar"} <= set(v)
    # her senaryonun görüntüsü ve özeti var
    for p in v["yagis_mm"]:
        for saat in v["sure_sa"]:
            assert f"{p}_{saat}" in v["senaryolar"]
            assert os.path.exists(os.path.join(kok, "senaryo", f"{p}_{saat}.png"))
    for s in v["olay_senaryolari"]:
        assert {"su_30_km2", "su_10_km2", "belirsiz_km2", "toplanma_su", "toplanma_belirsiz",
                "yol_parcasi_su"} <= set(v["merkez"]["senaryolar"][s])
        assert all(s in y["olcum"] for y in v["yerler"])
    assert all(s in v["dogrulama"] for s in v["dogrulama_senaryolari"])
    assert v["rotalar"][0]["senaryo"] is None and len(v["rotalar"]) == 1 + len(v["olay_senaryolari"])
    assert {"toplam", "sayim", "dere_yakin", "dere_yakin_m", "noktalar", "liste"} <= set(d)
    assert len(d["noktalar"]) == d["toplam"]
    assert len(d["liste"]) == d["sayim"]["1"] + d["sayim"]["2"]
    assert os.path.exists(os.path.join(kok, "toplanma_denetimi.csv"))
