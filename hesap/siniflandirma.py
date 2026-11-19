"""Sınıflandırma: "Bu yağışta bu ilçede su baskını olayı olur mu?" (ilçe-gün).

Gözetimli öğrenme (Lund GeoAI, "Classification" ve "Ensemble learning &
hyper-parameter tuning" dersleri). OLS (hesap/ols_model.py) kaç çağrı
geleceğini tahmin eder ve olay günlerini çok düşük tahmin eder; çünkü
ortalamayı hedefler. Kurumun sorusu ise bir eşiktir: "Bugün bu ilçede itfaiyeye
sel yükü binecek mi?" Bu bir sınıflandırma sorusudur.

Hedef (olay): bir ilçede bir günde ≥ OLAY_ESIK su baskını çağrısı. 1 çağrı
eşik olamaz: tek çağrıların %43'ü yağışsız günde (boru patlağı, tek bodrum).
≥ 3 çağrıda bu pay %27'ye iner; kalanların çoğu büyük fırtınaların artçı
günleridir (önceki günlerin yağışı modelde var). İlçe-günlerin ~%1.3'ü olaydır.

Modeller (aynı veriyle, aynı sınamalarla):
  • temel      — yağışsız lojistik regresyon (yalnız nüfus + kent payı).
                 Yağış bir şey katıyor mu sorusunun ölçüsü.
  • lojistik   — OLS ile aynı değişkenler (log yağış, etkileşim). Okunabilir.
  • agac       — karar ağacı (tek ağaç; kuralları okunabilir ama kararsız).
  • rf         — Random Forest (bagging: önyükleme örnekleriyle çok ağaç).
  • gb         — gradient boosting (boosting: ağaçlar bir öncekinin hatasını
                 düzeltir). Yağış değişkenleri MONOTON kısıtlı: başka her şey
                 aynıyken daha çok yağış olasılığı düşüremez. Fiziksel bilgi
                 modele böyle girer; ilçe × yağış olasılık tablosu da bu
                 sayede kendi içinde tutarlı olur.
  Ağaç modelleri ham mm değerlerini ve en yoğun 1 / 3 saati de görür;
  çoklu doğrusallık ağaçlar için sorun değildir (OLS'de VIF ≈ 17 idi).

Dengesiz veri: sınıf ağırlıklandırma (class_weight="balanced") denendi ve
kullanılmadı. Ayırt etme gücünü (AP) değiştirmiyor, olasılıkları ~8 kat
şişiriyor (Brier 0.015 → 0.13). Bu çalışmada olasılığın kendisi çıktıdır
("%30 olasılık"), bu yüzden kalibrasyon korunur. Dengesizlik bunun yerine
ölçüde ele alınır:
  • AP (average precision, PR eğrisinin altı): olayların nadir olduğu yerde
    ROC-AUC'tan daha dürüst. Rastgele tahminin AP'si olay oranına (~0.013)
    eşittir.
  • Alarm eşiği 0.5 değildir: eğitim yıllarındaki dışarıda tahminlerde F1'i
    en yükselten olasılık seçilir, sonra hiç dokunulmadan test yıllarına
    uygulanır.

Hiperparametre ayarı: ızgara araması, yalnız eğitim yıllarında (2020–2024),
her yıl sırayla dışarıda bırakılarak (LeaveOneGroupOut). Rastgele katlar
kullanılmaz: aynı fırtına 30 ilçeye birden düşer; rastgele bölmede fırtınanın
bir ilçesi eğitimde, öteki test katında olur ve model fırtınayı "ezberler".
En iyi model test sonucuna göre değil, bu iç sınamanın AP'sine göre seçilir.

Sınama (OLS ile aynı iki soru, artı bir uyarı):
  1. Zaman — 2020–24 ile eğitilir, 2025–26 (hiç görülmemiş) tahmin edilir.
  2. Mekân — her ilçe sırayla dışarıda (Geographical ML: aktarılabilirlik).
  3. Rastgele 5-katlı — yalnız KIYAS için: sızıntılı sınamanın sonucu ne
     kadar iyimser gösterdiğini ölçer. Raporlanan başarı bu değildir.

Ek çıktılar: permütasyon önemi (test yıllarında bir değişken karıştırılınca
AP ne kadar düşüyor), ilçe başına yakalanan / kaçırılan olay (mekân
sınamasından; harita için), ilçe × günlük yağış olasılık tablosu (bütün
verilerle eğitilmiş seçili modelden; önceki günler kuru varsayımıyla).

Çıktı: egitim/siniflandirma_sonuc.json. Süre ~5 dk.
Çalıştırma: venv/bin/python -m hesap.siniflandirma
"""
import logging
import os
import time

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve, roc_auc_score
from sklearn.model_selection import GridSearchCV, KFold, LeaveOneGroupOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from afet.dosya import json_yaz
from hesap import ols_model as om
from hesap.ilce_gun import CIKTI_DIR, ILCE_GUN_CSV

log = logging.getLogger("siniflandirma")
SONUC_JSON = os.path.join(CIKTI_DIR, "siniflandirma_sonuc.json")

OLAY_ESIK = 3                         # ilçe-günde ≥ bu kadar su çağrısı = olay
TOHUM = 0
YAGIS_HAM = ["yagis_mm", "yagis_max1s_mm", "yagis_max3s_mm", "yagis_dun_mm",
             "yagis_onceki3g_mm", "yagis_onceki7g_mm"]
AGAC_OZ = YAGIS_HAM + ["log_nufus", "kent_payi"]
TABLO_YAGIS = [0, 10, 20, 30, 40, 60, 80, 120]     # olasılık tablosunun günlük yağış adımları (mm)
ACIKLAMA = {**om.ACIKLAMA,
            "yagis_mm": "o günün yağışı (mm)", "yagis_max1s_mm": "en yoğun 1 saat (mm)",
            "yagis_max3s_mm": "en yoğun 3 saat (mm)", "yagis_dun_mm": "dünkü yağış (mm)",
            "yagis_onceki3g_mm": "önceki 3 gün (mm)", "yagis_onceki7g_mm": "önceki 7 gün (mm)"}


def _lojistik():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000))


def _gb():
    # yağış ↑ → olasılık ↓ olamaz; nüfus ve kent payı serbest
    return HistGradientBoostingClassifier(max_iter=300, random_state=TOHUM,
                                          monotonic_cst={k: 1 for k in YAGIS_HAM})


# ad → (kurucu, kolonlar, ızgara, açıklama)
MODELLER = {
    "temel": (_lojistik, om.TEMEL, {}, "yağışsız lojistik regresyon (nüfus + kent payı)"),
    "lojistik": (_lojistik, om.OZELLIKLER,
                 {"logisticregression__C": [0.01, 0.1, 1, 10]}, "lojistik regresyon (OLS değişkenleri)"),
    "agac": (lambda: DecisionTreeClassifier(random_state=TOHUM), AGAC_OZ,
             {"max_depth": [3, 5, 8], "min_samples_leaf": [20, 50, 100]}, "karar ağacı"),
    "rf": (lambda: RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=TOHUM), AGAC_OZ,
           {"min_samples_leaf": [5, 20, 50], "max_features": [0.33, 0.66]}, "Random Forest"),
    "gb": (_gb, AGAC_OZ,
           {"learning_rate": [0.03, 0.1], "max_leaf_nodes": [7, 15, 31], "min_samples_leaf": [20, 100]},
           "gradient boosting (yağışa monoton)"),
}


def hazirla(t):
    t = om.hazirla(t)
    t["olay"] = (t.cagri_su >= OLAY_ESIK).astype(int)
    return t


def olculer(y, p, esik=None):
    """Olasılık ölçüleri; eşik verilirse alarm ölçüleri de."""
    y, p = np.asarray(y), np.asarray(p)
    o = {"auc": round(float(roc_auc_score(y, p)), 3),
         "ap": round(float(average_precision_score(y, p)), 3),
         "brier": round(float(brier_score_loss(y, p)), 4),
         "olay": int(y.sum()), "olay_orani": round(float(y.mean()), 4)}
    if esik is not None:
        a = p >= esik
        dp, yp, yn = int((a & (y == 1)).sum()), int((a & (y == 0)).sum()), int((~a & (y == 1)).sum())
        o.update({"dogru_alarm": dp, "yanlis_alarm": yp, "kacirilan": yn,
                  "kesinlik": round(dp / max(dp + yp, 1), 3), "duyarlilik": round(dp / max(dp + yn, 1), 3)})
    return o


def f1_esigi(y, p):
    """F1'i en yükselten olasılık eşiği (dışarıda tahminlerden)."""
    k, d, e = precision_recall_curve(y, p)
    f1 = 2 * k[:-1] * d[:-1] / np.maximum(k[:-1] + d[:-1], 1e-12)
    return float(e[int(np.argmax(f1))])


def ayarla(ad, egitim, modeller=MODELLER):
    """Izgara araması, eğitim yıllarında yıl-dışarıda; (en iyi model, parametre, iç AP, eşik)."""
    kur, kolonlar, izgara, _ = modeller[ad]
    cv, g = LeaveOneGroupOut(), egitim.yil.values
    if izgara:
        ara = GridSearchCV(kur(), izgara, scoring="average_precision", cv=cv, refit=False)
        ara.fit(egitim[kolonlar], egitim.olay, groups=g)
        prm, ic_ap = ara.best_params_, float(ara.best_score_)
    else:
        prm, ic_ap = {}, None
    m = kur().set_params(**prm)
    oof = cross_val_predict(m, egitim[kolonlar], egitim.olay, groups=g, cv=cv, method="predict_proba")[:, 1]
    if ic_ap is None:
        ic_ap = float(average_precision_score(egitim.olay, oof))
    return m, prm, round(ic_ap, 3), f1_esigi(egitim.olay, oof)


def il_gunleri(test, p, esik):
    """İl geneli: büyük olay günlerinin (≥ OLS'deki OLAY_CAGRI çağrı) kaçında
    en az bir ilçede alarm vardı; kaç günde alarm verildi."""
    d = pd.DataFrame({"gun": test.gun.values, "c": test.cagri_su.values, "a": np.asarray(p) >= esik}
                     ).groupby("gun").agg(c=("c", "sum"), a=("a", "any"))
    buyuk = d[d.c >= om.OLAY_CAGRI]
    return {"buyuk_olay_gunu": int(len(buyuk)), "alarmli": int(buyuk.a.sum()),
            "alarm_gunu": int(d.a.sum()), "gun": int(len(d))}


def zaman_sinamasi(t, ayar):
    egitim, test = t[~t.yil.isin(om.TEST_YILLARI)], t[t.yil.isin(om.TEST_YILLARI)]
    out, tahminler = {}, {}
    for ad, (m, prm, ic_ap, esik) in ayar.items():
        kolonlar = MODELLER[ad][1]
        m = clone(m).fit(egitim[kolonlar], egitim.olay)
        p = m.predict_proba(test[kolonlar])[:, 1]
        out[ad] = {**olculer(test.olay, p, esik), "esik": round(esik, 3), "il": il_gunleri(test, p, esik)}
        tahminler[ad] = (m, p)
    return out, tahminler, test


def mekan_sinamasi(t, ayar):
    """Her ilçe dışarıda; tahminler birleştirilip ölçülür. Rastgele 5-katlı
    sınama sızıntının etkisini göstermek için yanında hesaplanır."""
    out, ilce_p = {}, {}
    for ad, (m, _, _, esik) in ayar.items():
        kolonlar = MODELLER[ad][1]
        p = np.zeros(len(t))
        for ilce in t.ilce.unique():
            k = (t.ilce == ilce).values
            p[k] = clone(m).fit(t.loc[~k, kolonlar], t.olay[~k]).predict_proba(t.loc[k, kolonlar])[:, 1]
        r = cross_val_predict(clone(m), t[kolonlar], t.olay, method="predict_proba",
                              cv=KFold(5, shuffle=True, random_state=TOHUM))[:, 1]
        out[ad] = {"ilce_disarida": olculer(t.olay, p, esik), "rastgele_5kat": olculer(t.olay, r, esik)}
        ilce_p[ad] = p
    return out, ilce_p


def ilce_sonuclari(t, p, esik):
    a = np.asarray(p) >= esik
    g = t.assign(a=a, dp=a & (t.olay == 1), yp=a & (t.olay == 0), yn=~a & (t.olay == 1))
    return [{"ilce": k, "olay": int(x.olay.sum()), "yakalanan": int(x.dp.sum()), "kacirilan": int(x.yn.sum()),
             "yanlis_alarm": int(x.yp.sum()), "ort_olasilik": round(float(np.asarray(p)[x.index].mean()), 4)}
            for k, x in g.groupby("ilce")]


def onem(m, test, kolonlar, n=5):
    r = permutation_importance(m, test[kolonlar], test.olay, scoring="average_precision",
                               n_repeats=n, random_state=TOHUM)
    return sorted(({"ad": k, "aciklama": ACIKLAMA.get(k, k), "ap_dususu": round(float(o), 4),
                    "std": round(float(s), 4)} for k, o, s in zip(kolonlar, r.importances_mean, r.importances_std)),
                  key=lambda x: -x["ap_dususu"])


KURU = {"yagis_dun_mm": 0.0, "yagis_onceki3g_mm": 0.0, "yagis_onceki7g_mm": 0.0}


def olasilik_tablosu(t, m, kolonlar, onceki=None):
    """İlçe × günlük yağış → olay olasılığı. onceki: önceki günlerin yağışı
    (varsayılan kuru); en yoğun 1 / 3 saat, yağışlı günlerde (≥ 10 mm)
    gözlenen ortanca oranla türetilir."""
    onceki = onceki or KURU
    yagisli = t[t.yagis_mm >= 10]
    o1 = float((yagisli.yagis_max1s_mm / yagisli.yagis_mm).median())
    o3 = float((yagisli.yagis_max3s_mm / yagisli.yagis_mm).median())
    ilceler = t.groupby("ilce")[["nufus", "kent_payi"]].first()
    satir = []
    for ilce, r in ilceler.iterrows():
        for mm in TABLO_YAGIS:
            satir.append({"ilce": ilce, "yagis_mm": mm, "yagis_max1s_mm": mm * o1, "yagis_max3s_mm": mm * o3,
                          **onceki, "nufus": r.nufus, "kent_payi": r.kent_payi})
    g = om.hazirla(pd.DataFrame(satir).assign(yil=om.ILK_YIL, cagri_su=0, gun="-"))
    g["p"] = m.predict_proba(g[kolonlar])[:, 1]
    return {"yagis_mm": TABLO_YAGIS, "max1s_orani": round(o1, 3), "max3s_orani": round(o3, 3),
            "varsayim": "en yoğun saatler yağışlı günlerin ortanca oranıyla", "onceki": onceki,
            "ilce": {k: [round(float(v), 3) for v in x.sort_values("yagis_mm").p]
                     for k, x in g.groupby("ilce")}}


def calistir(t, modeller=MODELLER):
    t = hazirla(t)
    egitim = t[~t.yil.isin(om.TEST_YILLARI)]
    ayar = {}
    for ad in modeller:
        s = time.time()
        ayar[ad] = ayarla(ad, egitim, modeller)
        log.info("%s ayarlandı (%.0f sn): %s, iç AP %s", ad, time.time() - s, ayar[ad][1], ayar[ad][2])
    # seçim: yağışlı modeller içinde iç sınama AP'si en yüksek olan (test sonucuna bakılmaz)
    secili = max((a for a in ayar if a != "temel"), key=lambda a: ayar[a][2])
    zaman, tahminler, test = zaman_sinamasi(t, ayar)
    log.info("zaman sınaması bitti")
    mekan, ilce_p = mekan_sinamasi(t, ayar)
    log.info("mekân sınaması bitti")
    kolonlar = modeller[secili][1]
    tum = clone(ayar[secili][0]).fit(t[kolonlar], t.olay)
    return {
        "veri": {"satir": len(t), "ilce": int(t.ilce.nunique()), "gun": int(t.gun.nunique()),
                 "yillar": [int(t.yil.min()), int(t.yil.max())], "olay": int(t.olay.sum()),
                 "olay_orani": round(float(t.olay.mean()), 4)},
        "olay_tanimi": f"ilçe-günde ≥ {OLAY_ESIK} su baskını çağrısı",
        "modeller": {ad: {"aciklama": modeller[ad][3], "degiskenler": modeller[ad][1],
                          "parametreler": {k.split("__")[-1]: v for k, v in ayar[ad][1].items()},
                          "ic_ap": ayar[ad][2], "esik": round(ayar[ad][3], 3)} for ad in modeller},
        "secili": secili,
        "secim": "yağışlı modeller içinde eğitim yıllarındaki yıl-dışarıda sınamanın AP'si en yüksek olan",
        "zaman_sinamasi": zaman,
        "mekan_sinamasi": mekan,
        "ilce": ilce_sonuclari(t, ilce_p[secili], ayar[secili][3]),
        "onem": onem(tahminler[secili][0], test, kolonlar),
        "olasilik_tablosu": olasilik_tablosu(t, tum, kolonlar),
    }


def yazdir(r):
    v = r["veri"]
    print(f"\nSınıflandırma — {r['olay_tanimi']}")
    print(f"{v['satir']} ilçe-gün, {v['olay']} olay (%{v['olay_orani'] * 100:.1f}); seçili model: {r['secili']}\n")
    print(f"{'model':9} {'iç AP':>6} | {'zaman AUC':>9} {'AP':>6} {'kesinlik':>8} {'duyarlılık':>10} | "
          f"{'ilçe-dış AUC':>12} {'AP':>6} | {'rastgele AP':>11}")
    for ad, m in r["modeller"].items():
        z, k = r["zaman_sinamasi"][ad], r["mekan_sinamasi"][ad]
        print(f"{ad:9} {m['ic_ap']:6.3f} | {z['auc']:9.3f} {z['ap']:6.3f} {z['kesinlik']:8.2f} {z['duyarlilik']:10.2f} | "
              f"{k['ilce_disarida']['auc']:12.3f} {k['ilce_disarida']['ap']:6.3f} | {k['rastgele_5kat']['ap']:11.3f}")
    z = r["zaman_sinamasi"][r["secili"]]
    print(f"\nTest yıllarında (seçili, eşik {z['esik']}): {z['dogru_alarm']} doğru alarm, {z['yanlis_alarm']} yanlış alarm, "
          f"{z['kacirilan']} kaçırılan olay; büyük olay günlerinin {z['il']['alarmli']}/{z['il']['buyuk_olay_gunu']}'inde alarm")
    print("Önem (AP düşüşü):", ", ".join(f"{o['ad']} {o['ap_dususu']:.3f}" for o in r["onem"]))
    tb = r["olasilik_tablosu"]
    print(f"\nOlasılık tablosu (günlük mm: {tb['yagis_mm']}), örnekler:")
    for ilce in ("Konak", "Bornova", "Karşiyaka", "Ödemiş", "Kiraz"):
        if ilce in tb["ilce"]:
            print(f"  {ilce:10}", " ".join(f"{p:5.2f}" for p in tb["ilce"][ilce]))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    r = calistir(pd.read_csv(ILCE_GUN_CSV))
    json_yaz(SONUC_JSON, r, okunur=True)
    yazdir(r)
    print(f"\nYazıldı: {SONUC_JSON}")


if __name__ == "__main__":
    main()
