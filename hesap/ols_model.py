"""OLS regresyonu: yağış → itfaiye su baskını çağrısı (ilçe-gün).

Gözetimli öğrenme (Lund GeoAI, "Regression" dersi): girdi (yağış, ilçe
özellikleri) ile çıktı (çağrı sayısı) arasındaki ilişki eğitim verisinden
öğrenilir, görülmemiş veride sınanır. Veri: egitim/ilce_gun.csv
(hesap/ilce_gun.py).

Model (sıradan en küçük kareler):
    log(1 + çağrı) = b0 + b1·log(1 + yağış) + b2·log(1 + dünkü yağış)
                     + b3·log(1 + önceki 7 gün) + b4·log(nüfus) + b5·kent payı
                     + b6·log(1 + yağış)·kent payı + hata
  • Logaritma: çağrı sayısı çarpık (günlerin %95'inde 0, birkaç günde 100+)
    ve yağışın etkisi doğrusal değil (ilk 10 mm, 50 mm'den sonraki 10 mm'den
    daha çok fark yaratır).
  • yağış × kent payı: aynı yağış betonlaşmış ilçede daha çok çağrı getirir mi?
    Bu, etkinin ilçeden ilçeye değiştiğinin en basit hâlidir; tam hâli GWR.
  • Önceki günler: çağrılar olaydan sonra günlerce sürer (bodrum boşaltma).
  • En yoğun saatin yağışı modelde YOK: günlük toplamla birlikte VIF ≈ 17
    (çoklu doğrusallık; ikisi aynı bilgiyi taşıyor), katsayısı anlamsızdı
    (p = 0.87). Çıkarılınca bütün VIF'ler < 2 (vif() raporlar).

Neden önce OLS: katsayılar okunabilir ve sınanabilir; sonraki modeller (GWR,
sayım modeli) buna göre ölçülür. Sınırı: hedef bir sayımdır ve çoğu 0'dır;
log(1 + y) üzerinde OLS bir yaklaşımdır. Geri dönüşümde (çağrı sayısına) Duan
smearing düzeltmesi uygulanır. Bu düzeltme sabit bir çarpandır: toplamı yaklaşık
tutturur ama çağrıları sakin günlere de yayar, fırtına günlerini çok düşük
tahmin eder. Bu yüzden aynı değişkenlerle bir Poisson regresyonu (sayım için
genelleştirilmiş doğrusal model; log(beklenen çağrı) doğrusal) kıyas olarak
sınanır.

Standart hatalar güne göre kümelenir: aynı gün 30 ilçenin hepsi aynı fırtınayı
yaşar, satırlar bağımsız değildir (yoksa katsayılar olduğundan kesin görünür).

Sınama (iki ayrı soru):
  1. Zaman — 2020–2024 ile eğitilir, 2025–2026 (hiç görülmemiş yıllar) tahmin
     edilir. "Gelecek fırtınayı tahmin edebilir mi?"
  2. Mekân — her ilçe sırayla dışarıda bırakılır, öteki 29 ilçeyle eğitilen
     model o ilçeyi tahmin eder. "Verisi olmayan bir ilçeye taşınabilir mi?"
     (Geographical ML dersi: aktarılabilirlik.)
  Her ikisinde yağışsız temel model (yalnız nüfus + kent payı) ile kıyaslanır.
  Sıfırların çokluğu genel R²'yi şişirir/bozar; bu yüzden "olay günleri"
  (il genelinde ≥ OLAY_CAGRI çağrı) ayrıca raporlanır.

2019 eğitime alınmaz: çizelge Haziran'da başlar ve "su baskını kontrol" kaydı o
yıl neredeyse hiç kullanılmamış (çağrıların %11'i, sonraki yıllarda %53–79).

Çıktı: egitim/ols_sonuc.json (katsayılar, güven aralıkları, VIF, sınama
ölçüleri, ilçe artıkları). Çalıştırma: venv/bin/python -m hesap.ols_model
"""
import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor

from afet.yollar import ILCE_GUN_CSV, OLS_SONUC
from hesap import gunlugu_kur, sonucu_yaz

log = logging.getLogger("ols")

ILK_YIL = 2020
TEST_YILLARI = (2025, 2026)
OLAY_CAGRI = 50            # il genelinde bu kadar çağrı olan gün "olay günü"
OZELLIKLER = ["log_yagis", "log_dun", "log_onceki7g", "log_nufus", "kent_payi", "log_yagis_x_kent"]
TEMEL = ["log_nufus", "kent_payi"]          # yağışsız kıyas modeli
ACIKLAMA = {
    "log_yagis": "o günün yağışı, log(1+mm)",
    "log_max1s": "o günün en yoğun saati, log(1+mm)",
    "log_dun": "dünkü yağış, log(1+mm)",
    "log_onceki7g": "önceki 7 günün yağışı, log(1+mm)",
    "log_nufus": "ilçe nüfusu, log(kişi)",
    "kent_payi": "yapılaşmış alan payı (0–1)",
    "log_yagis_x_kent": "yağış × kent payı",
}


def hazirla(t):
    """Model kolonları. Girdi ilce_gun.csv tablosudur."""
    t = t[t.yil >= ILK_YIL].copy()
    t["y"] = np.log1p(t.cagri_su)
    t["log_yagis"] = np.log1p(t.yagis_mm)
    t["log_max1s"] = np.log1p(t.yagis_max1s_mm)
    t["log_dun"] = np.log1p(t.yagis_dun_mm)
    t["log_onceki7g"] = np.log1p(t.yagis_onceki7g_mm)
    t["log_nufus"] = np.log(t.nufus)
    t["log_yagis_x_kent"] = t.log_yagis * t.kent_payi
    return t.reset_index(drop=True)


def egit(t, kolonlar=OZELLIKLER, kume=True):
    X = sm.add_constant(t[kolonlar], has_constant="add")
    m = sm.OLS(t.y, X)
    if kume:
        return m.fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(t.gun)[0]})
    return m.fit()


def tahmin(sonuc, t, kolonlar):
    return np.asarray(sonuc.predict(sm.add_constant(t[kolonlar], has_constant="add")))


def smearing(sonuc):
    """Duan (1983) geri dönüşüm katsayısı: E[1+y] = exp(tahmin) · ort(exp(artık))."""
    return float(np.mean(np.exp(sonuc.resid)))


def olculer(y_log, p_log, cagri, cagri_tahmin, gun):
    """Log ölçekte R² / RMSE; çağrı ölçeğinde MAE; olay günlerinde il geneli
    toplamın tahmini (gerçek ve tahmin il toplamlarının korelasyonu ve oranı)."""
    y_log, p_log = np.asarray(y_log), np.asarray(p_log)
    ss_res = float(((y_log - p_log) ** 2).sum())
    ss_tot = float(((y_log - y_log.mean()) ** 2).sum())
    il = pd.DataFrame({"gun": np.asarray(gun), "g": np.asarray(cagri), "t": np.asarray(cagri_tahmin)}
                      ).groupby("gun").sum()
    olay = il[il.g >= OLAY_CAGRI]
    return {
        "r2_log": round(1 - ss_res / ss_tot, 3),
        "rmse_log": round(float(np.sqrt(ss_res / len(y_log))), 3),
        "mae_cagri": round(float(np.abs(np.asarray(cagri) - np.asarray(cagri_tahmin)).mean()), 3),
        "il_gunluk_korelasyon": round(float(np.corrcoef(il.g, il.t)[0, 1]), 3),
        "olay_gunu": int(len(olay)),
        "olay_gercek_toplam": int(olay.g.sum()),
        "olay_tahmin_toplam": round(float(olay.t.sum())),
        "olay_korelasyon": round(float(np.corrcoef(olay.g, olay.t)[0, 1]), 3) if len(olay) > 2 else None,
    }


def poisson(t, kolonlar=OZELLIKLER, kume=False):
    m = sm.GLM(t.cagri_su, sm.add_constant(t[kolonlar], has_constant="add"), family=sm.families.Poisson())
    if kume:      # raporlanan katsayılar: OLS gibi güne göre kümelenmiş standart hata
        return m.fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(t.gun)[0]})
    return m.fit()


def tahmin_et(egitim, test, tur, kolonlar):
    """(log(1+çağrı) tahmini, çağrı tahmini). tur: 'ols' ya da 'poisson'."""
    if tur == "poisson":
        c = np.asarray(poisson(egitim, kolonlar).predict(sm.add_constant(test[kolonlar], has_constant="add")))
        return np.log1p(c), c
    s = egit(egitim, kolonlar, kume=False)
    p = tahmin(s, test, kolonlar)
    return p, np.exp(p) * smearing(s) - 1


MODELLER = {"model": ("ols", OZELLIKLER), "temel": ("ols", TEMEL), "poisson": ("poisson", OZELLIKLER)}


def sinama(egitim, test, tur, kolonlar):
    p_log, p_cagri = tahmin_et(egitim, test, tur, kolonlar)
    return olculer(test.y, p_log, test.cagri_su, p_cagri, test.gun)


def zaman_sinamasi(t):
    egitim, test = t[~t.yil.isin(TEST_YILLARI)], t[t.yil.isin(TEST_YILLARI)]
    return {"egitim_yillari": sorted(egitim.yil.unique().tolist()),
            "test_yillari": sorted(test.yil.unique().tolist()),
            **{ad: sinama(egitim, test, *m) for ad, m in MODELLER.items()}}


def mekan_sinamasi(t):
    """Her ilçe dışarıda bırakılarak tahmin edilir; tahminler birleştirilip
    ölçülür (bir kerede tek ilçenin R²'si az olay yüzünden kararsızdır)."""
    out = {}
    for ad, (tur, kolonlar) in MODELLER.items():
        p_log = np.zeros(len(t))
        p_cagri = np.zeros(len(t))
        for ilce in t.ilce.unique():
            m = (t.ilce == ilce).values
            p_log[m], p_cagri[m] = tahmin_et(t[~m], t[m], tur, kolonlar)
        out[ad] = olculer(t.y, p_log, t.cagri_su, p_cagri, t.gun)
        if ad == "model":
            t = t.assign(_p=p_cagri)
            # ilçe başına: toplam gerçek / tahmin çağrı (dışarıda bırakılmışken)
            out["ilce"] = [{"ilce": k, "gercek": int(g.cagri_su.sum()), "tahmin": round(float(g._p.sum()))}
                           for k, g in t.groupby("ilce")]
    return out


def vif(t, kolonlar=OZELLIKLER):
    """Çoklu doğrusallık (Regression / GWR dersleri): VIF > 10 sorunlu sayılır."""
    X = sm.add_constant(t[kolonlar], has_constant="add").values
    return {k: round(float(variance_inflation_factor(X, i + 1)), 1) for i, k in enumerate(kolonlar)}


def ilce_artiklari(t, sonuc):
    """İlçe başına ortalama artık (log ölçek): model ilçeyi sürekli az ya da
    çok mu tahmin ediyor? Mekânsal örüntü varsa tek global model yetmez (GWR)."""
    r = t.assign(r=sonuc.resid.values).groupby("ilce").r.mean()
    return {k: round(float(v), 3) for k, v in r.sort_values().items()}


def calistir(t):
    t = hazirla(t)
    s = egit(t)
    ci = s.conf_int()
    pz = poisson(t, kume=True)
    return {
        "veri": {"satir": len(t), "ilce": int(t.ilce.nunique()), "gun": int(t.gun.nunique()),
                 "yillar": [int(t.yil.min()), int(t.yil.max())], "cagri": int(t.cagri_su.sum()),
                 "sifir_payi": round(float((t.cagri_su == 0).mean()), 3)},
        "denklem": "log(1+çağrı) ~ " + " + ".join(OZELLIKLER),
        "katsayilar": [{"ad": k, "aciklama": ACIKLAMA.get(k, "sabit"), "b": round(float(s.params[k]), 4),
                        "alt": round(float(ci.loc[k, 0]), 4), "ust": round(float(ci.loc[k, 1]), 4),
                        "p": float(f"{s.pvalues[k]:.2g}")} for k in s.params.index],
        "r2_egitim": round(float(s.rsquared), 3),
        "r2_duzeltilmis": round(float(s.rsquared_adj), 3),
        "aic": round(float(s.aic), 1),
        "smearing": round(smearing(s), 4),
        "vif": vif(t),
        # aynı değişkenlerle Poisson: katsayı exp(b) = çarpan (ör. 1.3 → %30 artış)
        "poisson_katsayilar": [{"ad": k, "b": round(float(pz.params[k]), 4),
                                "carpan": round(float(np.exp(pz.params[k])), 3),
                                "p": float(f"{pz.pvalues[k]:.2g}")} for k in pz.params.index],
        "zaman_sinamasi": zaman_sinamasi(t),
        "mekan_sinamasi": mekan_sinamasi(t),
        "ilce_artik": ilce_artiklari(t, s),
        "standart_hata": "güne göre kümelenmiş (cluster-robust)",
    }


def yazdir(r):
    print(f"\nOLS — {r['denklem']}")
    print(f"{r['veri']['satir']} satır ({r['veri']['ilce']} ilçe × {r['veri']['gun']} gün), "
          f"günlerin %{r['veri']['sifir_payi'] * 100:.1f}'inde çağrı yok")
    print(f"R² {r['r2_egitim']} (düzeltilmiş {r['r2_duzeltilmis']}), AIC {r['aic']}\n")
    print(f"{'değişken':20} {'katsayı':>9} {'%95 aralık':>20} {'p':>8} {'VIF':>6}")
    for k in r["katsayilar"]:
        print(f"{k['ad']:20} {k['b']:9.4f} [{k['alt']:8.4f}, {k['ust']:8.4f}] {k['p']:8.2g} "
              f"{r['vif'].get(k['ad'], ''):>6}")
    for ad, s in (("Zaman (2025–26 görülmemiş)", r["zaman_sinamasi"]),
                  ("Mekân (ilçe dışarıda)", r["mekan_sinamasi"])):
        print(f"\n{ad}:")
        for m in MODELLER:
            o = s[m]
            print(f"  {m:7} R²(log) {o['r2_log']:6.3f}  MAE {o['mae_cagri']:.3f} çağrı  "
                  f"il günlük r {o['il_gunluk_korelasyon']:.2f}  olay günleri ({o['olay_gunu']}): "
                  f"gerçek {o['olay_gercek_toplam']} / tahmin {o['olay_tahmin_toplam']}, r {o['olay_korelasyon']}")
    a = r["ilce_artik"]
    print("\nEn çok az tahmin edilen ilçeler:", dict(list(a.items())[-4:]))
    print("En çok fazla tahmin edilen ilçeler:", dict(list(a.items())[:4]))


def main():
    gunlugu_kur()
    r = calistir(pd.read_csv(ILCE_GUN_CSV))
    sonucu_yaz(OLS_SONUC, r, yazdir)


if __name__ == "__main__":
    main()
