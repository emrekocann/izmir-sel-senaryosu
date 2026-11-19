"""Sitenin "Uyarı" sekmesinin verisi: docs/veri/uyari.json.

Sekme şu soruyu gösterir: "Yarın X mm yağarsa hangi ilçede itfaiyeye sel
yükü biner?" Bütün sayılar buradan gelir; sitede elle yazılı sayı yoktur.

  • Olasılık tablosu: seçili sınıflandırma modeli (siniflandirma_sonuc.json:
    model türü, parametreler, alarm eşiği) 2020–26'nın bütün verisiyle
    yeniden eğitilir; her ilçe × günlük yağış için olay olasılığı, iki
    geçmiş koşulunda:
      kuru  — önceki 7 gün yağışsız
      islak — olay günlerinde gözlenen önceki gün / 3 gün / 7 gün yağışlarının
              ortancası (veriden; "tipik bir olay gününün geçmişi")
    Önceki 7 günün yağışı modelin en önemli değişkenidir; bu yüzden iki koşul.
  • Sınama özeti: guvenilirlik.json (yıl yıl, ataklar, %95 aralık, öğlen
    uyarısı) — sekmedeki başlık sayıları.
  • İlçe sınırları: sinir/izmir_ilce.geojson, sadeleştirilmiş.
  • Örnek: 23 Ekim 2025 Foça sağanağı. Haberdeki yağış elle (kaynaklı);
    arşiv ve tahmin yağışı ile çağrılar veriden.

Çalıştırma: venv/bin/python -m hesap.uyari_hazirla
Önkoşul: hesap.siniflandirma, hesap.guvenilirlik (ve tahmin arşivi önbelleği).
"""
import datetime as dt
import logging
import os

import pandas as pd
import shapely

from afet.dosya import json_oku, json_yaz
from afet.yollar import SITE_VERI_DIR
from hesap import guvenilirlik as gv
from hesap import ols_model as om
from hesap import siniflandirma as sn
from hesap import tahmin_sinamasi as ts
from hesap.ilce_gun import ILCE_CSV, ILCE_GUN_CSV, anahtar

log = logging.getLogger("uyari")
UYARI_JSON = os.path.join(SITE_VERI_DIR, "uyari.json")
ILCE_GEOJSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sinir", "izmir_ilce.geojson")
SADELESTIR = 0.002            # ~200 m: ilçe ölçeğinde yeterli, dosya küçük kalır
ORNEK = {
    "ilce": "Foça", "gun": "2025-10-23", "sonraki_gun": 4,
    "haber_mm": 144, "haber_saat": 1.5,
    "kaynaklar": [
        {"ad": "Sabah", "url": "https://www.sabah.com.tr/gundem/2025/10/24/son-dakika-focadaki-sel-felaketinde-son-durum"},
        {"ad": "CNN Türk", "url": "https://www.cnnturk.com/turkiye/focayi-sel-aldi-izmir-valiligi-selde-kaybolan-1-kisi-araniyor-2351207"},
    ],
}


def islak_gecmis(t):
    """Olay günlerinde önceki günlerin yağışının ortancası (mm, 1 ondalık)."""
    o = t[t.olay == 1]
    return {k: round(float(o[k].median()), 1) for k in sn.KURU}


def ilce_geometrileri(adlar):
    """ilce_gun adı → sadeleştirilmiş GeoJSON geometrisi (TKGM adları anahtar() ile eşlenir)."""
    geo = json_oku(ILCE_GEOJSON)
    harita = {anahtar(ad): ad for ad in adlar}
    out = {}
    for f in geo["features"]:
        ad = harita.get(anahtar(f["properties"]["ILCEADI"]))
        if ad:
            g = shapely.set_precision(shapely.simplify(shapely.geometry.shape(f["geometry"]), SADELESTIR), 1e-4)
            out[ad] = shapely.geometry.mapping(g)
    eksik = set(adlar) - set(out)
    if eksik:
        raise ValueError(f"Sınırı bulunamayan ilçe: {sorted(eksik)}")
    return out


def sinama_ozeti(g, secili):
    """guvenilirlik.json → sekmenin başlık sayıları."""
    s = g["sonuclar"][secili]
    tum, oglen, yok = s["tum_yillar"], s["tahminli_donem"]["ecmwf_oglen"], s["tahminli_donem"]["tahminsiz"]
    al = lambda o: {"atak": o["atak"]["atak"], "atak_ilk_gun": o["atak"]["ilk_gun_alarmli"],
                    "buyuk_gun": o["il"]["buyuk_olay_gunu"], "buyuk_gun_alarmli": o["il"]["alarmli"],
                    "duyarlilik": o["duyarlilik"], "kesinlik": o["kesinlik"], "ap": o["ap"],
                    "yillar": o["yillar"], "aralik_95": o["aralik_95"]}
    return {"tum_yillar": al(tum), "oglen_tahmin": al(oglen), "tahminsiz": al(yok),
            "yillar": [{"yil": k["test_yili"], "ap": k["ap"], "buyuk_gun": k["il"]["buyuk_olay_gunu"],
                        "buyuk_gun_alarmli": k["il"]["alarmli"]} for k in s["katmanlar"]]}


def ornek_ozeti(t, ilce_df):
    gun = dt.date.fromisoformat(ORNEK["gun"])
    satir = t[(t.ilce == ORNEK["ilce"]) & (t.gun == ORNEK["gun"])].iloc[0]
    son = (gun + dt.timedelta(days=ORNEK["sonraki_gun"])).isoformat()
    cagri = int(t[(t.ilce == ORNEK["ilce"]) & (t.gun >= ORNEK["gun"]) & (t.gun <= son)].cagri_su.sum())
    tahmin = {}
    for model in ts.TAHMIN_MODELLERI:
        s = ts.tahmin_arsivi(ilce_df, model, dt.date(gun.year, 1, 1), dt.date(gun.year, 12, 31))
        s = s[(s.ilce == ORNEK["ilce"]) & (s.zaman.dt.date == gun)]
        tahmin[model] = round(float(s.mm.sum()), 1)
    return {**ORNEK, "arsiv_mm": round(float(satir.yagis_mm), 1), "tahmin_mm": tahmin,
            "cagri_gun_sayisi": ORNEK["sonraki_gun"] + 1, "cagri": cagri}


def hazirla():
    sonuc = json_oku(sn.SONUC_JSON)
    secili = sonuc["secili"]
    t = sn.hazirla(pd.read_csv(ILCE_GUN_CSV))
    ilce_df = pd.read_csv(ILCE_CSV)
    kolonlar = sn.MODELLER[secili][1]
    m = ts.egitilmis(secili, sonuc).fit(t[kolonlar], t.olay)
    kosullar = {"kuru": sn.KURU, "islak": islak_gecmis(t)}
    tablolar = {k: sn.olasilik_tablosu(t, m, kolonlar, o) for k, o in kosullar.items()}
    adlar = sorted(t.ilce.unique())
    olay_gunu = t.groupby("ilce").olay.sum()
    return {
        "model": {"ad": secili, "aciklama": sonuc["modeller"][secili]["aciklama"],
                  "esik": sonuc["modeller"][secili]["esik"], "egitim_yillari": [int(t.yil.min()), int(t.yil.max())]},
        "olay_tanimi": {"ilce_cagri": sn.OLAY_ESIK, "il_cagri": om.OLAY_CAGRI},
        "veri": sonuc["veri"],
        "yagis_mm": tablolar["kuru"]["yagis_mm"],
        "kosullar": {k: {"onceki": o, "olasilik": tablolar[k]["ilce"]} for k, o in kosullar.items()},
        "ilceler": [{"ad": ad, "olay_gunu": int(olay_gunu[ad]), "geometri": g}
                    for ad, g in ilce_geometrileri(adlar).items()],
        "sinama": sinama_ozeti(json_oku(gv.SONUC_JSON), secili),
        "onem": sonuc["onem"],
        "ornek": ornek_ozeti(t, ilce_df),
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    r = hazirla()
    json_yaz(UYARI_JSON, r)
    log.info("Yazıldı: %s (%.0f KB)", UYARI_JSON, os.path.getsize(UYARI_JSON) / 1024)
    i = r["kosullar"]["islak"]["onceki"]
    print("Islak geçmiş:", i)
    for k in ("kuru", "islak"):
        print(k, "Konak:", r["kosullar"][k]["olasilik"]["Konak"])
    print("Örnek:", {k: v for k, v in r["ornek"].items() if k != "kaynaklar"})


if __name__ == "__main__":
    main()
