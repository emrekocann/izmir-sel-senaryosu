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
    uyarısı, canlı sayfa koşulu) — sekmedeki başlık sayıları. Ayrıca dört
    kutulu sonuç tablosu (doğru alarm, boşa alarm, kaçan sel, doğru
    sessizlik; ilçe-gün) ve büyük
    sel dalgalarının (atak) listesi: her dalganın ilk gününde en çok çağrının
    geldiği ilçe ve oradaki arşiv yağışı — model neyi neden kaçırdı?
  • Eğitim: karşılaştırılan yöntemler ve yöntemin seçildiği yıllar.
  • İlçe sınırları: sinir/izmir_ilce.geojson, sadeleştirilmiş.
  • Örnek: 23 Ekim 2025 Foça sağanağı. Haberdeki yağış elle (kaynaklı);
    arşiv ve tahmin yağışı ile çağrılar veriden.
  • Duyarlılık haritası: gwr_sonuc.json. Her ilçe için o günün ve önceki 7
    günün yağışı 10 mm yerine 40 mm olunca olay olasılık oranı (çarpan), %95
    aralığı ve etkinin kanıtlanıp kanıtlanmadığı (katsayı aralığı sıfırı
    içermiyor); çok noktalı yağışla sağlamlık için sıra korelasyonu.

Ayrıca docs/veri/uyari_model.json: aynı model, sayfanın tarayıcıda
çalıştıracağı biçimde (docs/js/cekirdek/canli.js "yarının tahmini"): karar
ağaçları ve ilçelerin sabit girdileri (yağış noktası, nüfus, kent payı).
Yazmadan önce, dışa aktarılan modelin bütün satırlarda sklearn ile aynı
olasılığı verdiği denetlenir.

Çalıştırma: venv/bin/python -m hesap.uyari_hazirla
Önkoşul: hesap.siniflandirma, hesap.guvenilirlik (ve tahmin arşivi önbelleği), hesap.gwr.
"""
import datetime as dt
import logging
from statistics import median

import numpy as np
import pandas as pd
import shapely
from sklearn.ensemble import HistGradientBoostingClassifier

from afet.dosya import json_oku, json_yaz
from afet.yollar import (GUVENILIRLIK_SONUC, GWR_SONUC, ILCE_CSV, ILCE_GUN_CSV, ILCE_SINIRLARI, SINIFLANDIRMA_SONUC,
                         UYARI_JSON, UYARI_MODEL_JSON)
from hesap import gunlugu_kur
from hesap import guvenilirlik as gv
from hesap import gwr
from hesap import ols_model as om
from hesap import siniflandirma as sn
from hesap import tahmin_sinamasi as ts
from hesap.ilce_gun import anahtar

log = logging.getLogger("uyari")
SADELESTIR = 0.002            # ~200 m: ilçe ölçeğinde yeterli, dosya küçük kalır
GWR_GORUNUMLER = {"gunun_yagisi": "log_yagis", "onceki_hafta": "log_onceki7g"}   # sekmedeki görünüm → değişken
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
    geo = json_oku(ILCE_SINIRLARI)
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


def dort_kutu(t, o):
    """Sonucun dört kutusu (ilçe-gün): alarm × sel. Doğru sessizlik, sınanan
    ilçe-gün sayısından çıkar; satırların guvenilirlik'le aynı olduğunu sel
    sayısı denetler. t: sn.hazirla'dan geçmiş ilce_gun tablosu."""
    x = t[t.yil.isin(o["yillar"])]
    if int(x.olay.sum()) != o["olay"]:
        raise ValueError("ilce_gun ile guvenilirlik.json uyuşmuyor: önce hesap.guvenilirlik")
    return {"ilce_gun": len(x), "gun": int(x.gun.nunique()), "sel": o["olay"],
            "dogru_alarm": o["dogru_alarm"], "bosa_alarm": o["yanlis_alarm"], "kacan": o["kacirilan"],
            "dogru_sessiz": len(x) - o["dogru_alarm"] - o["yanlis_alarm"] - o["kacirilan"]}


def dalgalar(t, ataklar):
    """Büyük sel dalgaları (guvenilirlik atakları) ve her birinin ilk gününde en
    çok çağrının geldiği ilçe: çağrısı, arşivdeki o günkü ve önceki 7 günlük
    yağışı. İlk gününde alarm alan / almayan dalgaların ortanca yağışı, modelin
    neyi göremediğini gösterir."""
    liste = []
    for a in ataklar:
        gun = t[t.gun == a["ilk"]]
        en = gun.loc[gun.cagri_su.idxmax()]
        liste.append({**a, "il_cagri": int(gun.cagri_su.sum()), "ilce": en.ilce, "cagri": int(en.cagri_su),
                      "yagis_mm": round(float(en.yagis_mm), 1), "onceki7g_mm": round(float(en.yagis_onceki7g_mm), 1)})

    def ortanca(alarmli):
        x = [a for a in liste if a["ilk_gun_alarm"] == alarmli]
        orta = {k: round(median(a[k] for a in x), 1) if x else None for k in ("yagis_mm", "onceki7g_mm")}
        return {"dalga": len(x), **orta}
    return {"liste": liste, "ilk_gun_alarmli": ortanca(True), "ilk_gun_alarmsiz": ortanca(False)}


def _sinama_sayilari(o):
    """Bir sınama koşulunun sekmede gösterilen sayıları."""
    return {"atak": o["atak"]["atak"], "atak_ilk_gun": o["atak"]["ilk_gun_alarmli"],
            "atak_herhangi": o["atak"]["herhangi_alarmli"],
            "buyuk_gun": o["il"]["buyuk_olay_gunu"], "buyuk_gun_alarmli": o["il"]["alarmli"],
            "duyarlilik": o["duyarlilik"], "kesinlik": o["kesinlik"], "ap": o["ap"],
            "yillar": o["yillar"], "aralik_95": o["aralik_95"]}


def sinama_ozeti(g, secili, t):
    """guvenilirlik.json → sekmenin sınama sayıları (t: ilce_gun, dört kutu ve dalgalar için)."""
    s = g["sonuclar"][secili]
    tum, oglen, yok = s["tum_yillar"], s["tahminli_donem"]["ecmwf_oglen"], s["tahminli_donem"]["tahminsiz"]
    return {"tum_yillar": {**_sinama_sayilari(tum), "dort_kutu": dort_kutu(t, tum),
                           "dalgalar": dalgalar(t, tum["atak"]["liste"])},
            "oglen_tahmin": _sinama_sayilari(oglen), "tahminsiz": _sinama_sayilari(yok),
            "canli_tahmin": _sinama_sayilari(s["tahminli_donem"]["ecmwf_canli"]),
            "yillar": [{"yil": k["test_yili"], "ap": k["ap"], "buyuk_gun": k["il"]["buyuk_olay_gunu"],
                        "buyuk_gun_alarmli": k["il"]["alarmli"]} for k in s["katmanlar"]]}


def model_disa_aktar(m, kolonlar):
    """Gradient boosting modelini tarayıcının çalıştıracağı biçime çevirir. Her
    ağaç bir düğüm listesidir: iç düğüm [girdi sırası, eşik, sol, sağ] (girdi ≤
    eşik → sol), yaprak [değer]. Olasılık = 1 / (1 + e^−(baslangic + her ağacın
    yaprağı)). Eşikler 6 ondalığa yuvarlanır: yağış girdileri 0,1 mm adımlı,
    eşikler iki değerin ortası (ya da değerin kendisi) olduğundan karar değişmez;
    agac_olasiligi ile denetlenir."""
    if not isinstance(m, HistGradientBoostingClassifier) or m.n_trees_per_iteration_ != 1:
        raise ValueError(f"Canlı tahmin yalnız iki sınıflı gradient boosting için: {type(m).__name__}")
    agaclar = []
    for (agac,) in m._predictors:
        d = agac.nodes
        if d["is_categorical"].any():
            raise ValueError("Kategorik girdi desteklenmiyor")
        agaclar.append([[float(f"{n['value']:.10g}")] if n["is_leaf"] else
                        [int(n["feature_idx"]), round(float(n["num_threshold"]), 6), int(n["left"]), int(n["right"])]
                        for n in d])
    return {"girdiler": list(kolonlar), "baslangic": float(m._baseline_prediction.ravel()[0]), "agaclar": agaclar}


def agac_olasiligi(model, X):
    """Dışa aktarılmış modelin olasılığı; X: (satır, girdi) dizisi. canli.js'teki
    olasilik() ile aynı kural (testler ikisini ve sklearn'ü karşılaştırır)."""
    X = np.asarray(X, dtype=float)
    ham = np.full(len(X), model["baslangic"])
    for agac in model["agaclar"]:
        ic = np.array([len(d) == 4 for d in agac])
        oz, esik, sol, sag = (np.array([d[k] if len(d) == 4 else 0 for d in agac]) for k in range(4))
        deger = np.array([0.0 if len(d) == 4 else d[0] for d in agac])
        i = np.zeros(len(X), dtype=int)
        while (ic_mi := ic[i]).any():
            j = i[ic_mi]
            i[ic_mi] = np.where(X[ic_mi, oz[j].astype(int)] <= esik[j], sol[j], sag[j]).astype(int)
        ham += deger[i]
    return 1 / (1 + np.exp(-ham))


def canli_modeli(m, kolonlar, t, ilce_df):
    """Sayfanın "yarının tahmini" için model ve ilçelerin sabit girdileri: yağış
    noktası (hava tahmini burada okunur; eğitim ve sınamayla aynı nokta, aynı
    tahmin modeli), nüfusun logaritması ve kent payı."""
    sabit = t.groupby("ilce")[["log_nufus", "kent_payi"]].first()
    nokta = ilce_df.set_index("ilce")
    return {**model_disa_aktar(m, kolonlar), "tahmin_modeli": ts.ANA,
            "ilceler": {ad: {"lat": float(nokta.yagis_lat[ad]), "lon": float(nokta.yagis_lon[ad]),
                             "log_nufus": float(r.log_nufus), "kent_payi": float(r.kent_payi)}
                        for ad, r in sabit.iterrows()}}


def aktarimi_denetle(model, m, X, esik):
    """Dışa aktarılan model sklearn ile aynı olasılığı ve aynı alarmı veriyor mu?"""
    p, q = m.predict_proba(X)[:, 1], agac_olasiligi(model, X)
    fark = float(np.abs(p - q).max())
    if fark > 1e-7 or ((p >= esik) != (q >= esik)).any():
        raise ValueError(f"Dışa aktarılan model sklearn'den ayrılıyor (en büyük fark {fark:.2e})")
    return fark


def _sifir_disinda(aralik):
    """%95 aralığı sıfırı içermiyor mu (etki kanıtlı)."""
    return bool(aralik[0] > 0 or aralik[1] < 0)


def gwr_ozeti(g, adlar):
    """gwr_sonuc.json → duyarlılık haritası. kanitli: katsayının %95 aralığı
    sıfırı içermiyor (çarpan aralığı 1'i içermiyor)."""
    tek = {i["ilce"]: i for i in g["ilceler"]}
    if set(tek) != set(adlar):
        raise ValueError(f"GWR ilçeleri uyuşmuyor: {sorted(set(tek) ^ set(adlar))}")
    s = g["sonuclar"]
    sayilar = {m: {k: s[m][k] for k in ("ap", "duyarlilik", "kesinlik", "yillar")} for m in ("gwr", "global")}
    return {
        "bant": g["bant"], "olcek_mm": list(gwr.DUYARLILIK_MM),
        "sinama": {**sayilar, "ap_farki": s["gwr"]["ap_farki_globale_gore"]},
        "ilceler": {ad: {gor: {**tek[ad]["carpan_10_40"][v], "kanitli": _sifir_disinda(tek[ad]["aralik_95"][v])}
                         for gor, v in GWR_GORUNUMLER.items()} for ad in adlar},
    }


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
    """Döner: (uyari.json içeriği, uyari_model.json içeriği)."""
    sonuc = json_oku(SINIFLANDIRMA_SONUC)
    secili = sonuc["secili"]
    t = sn.hazirla(pd.read_csv(ILCE_GUN_CSV))
    ilce_df = pd.read_csv(ILCE_CSV)
    kolonlar = sn.MODELLER[secili].kolonlar
    m = ts.egitilmis(secili, sonuc).fit(t[kolonlar], t.olay)
    kosullar = {"kuru": sn.KURU, "islak": islak_gecmis(t)}
    tablolar = {k: sn.olasilik_tablosu(t, m, kolonlar, o) for k, o in kosullar.items()}
    adlar = sorted(t.ilce.unique())
    olay_gunu = t.groupby("ilce").olay.sum()
    esik = sonuc["modeller"][secili]["esik"]
    model = canli_modeli(m, kolonlar, t, ilce_df)
    log.info("Dışa aktarılan model sklearn ile aynı (en büyük fark %.1e)",
             aktarimi_denetle(model, m, t[kolonlar], esik))
    return {
        "model": {"ad": secili, "aciklama": sonuc["modeller"][secili]["aciklama"],
                  "esik": esik, "egitim_yillari": [int(t.yil.min()), int(t.yil.max())]},
        "olay_tanimi": {"ilce_cagri": sn.OLAY_ESIK, "il_cagri": om.OLAY_CAGRI, "dalga_arasi_gun": gv.ATAK_BOSLUK},
        "veri": sonuc["veri"],
        "yagis_mm": tablolar["kuru"]["yagis_mm"],
        "kosullar": {k: {"onceki": o, "olasilik": tablolar[k]["ilce"]} for k, o in kosullar.items()},
        "ilceler": [{"ad": ad, "olay_gunu": int(olay_gunu[ad]), "geometri": g}
                    for ad, g in ilce_geometrileri(adlar).items()],
        "egitim": {"modeller": list(sonuc["modeller"]),
                   "secim_yillari": [int(t.yil.min()), min(om.TEST_YILLARI) - 1]},
        "sinama": sinama_ozeti(json_oku(GUVENILIRLIK_SONUC), secili, t),
        "onem": sonuc["onem"],
        "ornek": ornek_ozeti(t, ilce_df),
        "gwr": gwr_ozeti(json_oku(GWR_SONUC), adlar),
    }, model


def main():
    gunlugu_kur()
    r, model = hazirla()
    for yol, veri in ((UYARI_JSON, r), (UYARI_MODEL_JSON, model)):
        log.info("Yazıldı: %s (%.0f KB)", yol, json_yaz(yol, veri) / 1024)
    i = r["kosullar"]["islak"]["onceki"]
    print("Islak geçmiş:", i)
    for k in ("kuru", "islak"):
        print(k, "Konak:", r["kosullar"][k]["olasilik"]["Konak"])
    print("Örnek:", {k: v for k, v in r["ornek"].items() if k != "kaynaklar"})


if __name__ == "__main__":
    main()
