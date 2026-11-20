"""Hava tahminiyle sınama: model bir gün önceden uyarı verebilir mi?

hesap/siniflandirma.py modelleri o günün GERÇEKTE yağan yağmuruyla (ERA5
arşivi) sınanır; bu sayı gün bitince bilinir. Gerçek bir uyarıda elde olan
şey önceki günün hava tahminidir. Bu betik aynı modelleri, hiç
değiştirmeden, yağış yerine tahmini koyarak sınar.

Senaryo — uyarı D-1 günü sonunda verilir:
  • D gününün yağışı (günlük toplam, en yoğun 1 / 3 saat): D'nin her saati
    için modelin ~1 gün önceki koşusu (Open-Meteo "previous runs" arşivi,
    precipitation_previous_day1). Yani D-1 içinde yayımlanmış tahmin.
  • Önceki günlerin yağışı (dün, önceki 3 ve 7 gün): arşivden (gözlenmiş).
    D-1'in son saatleri uyarı anında henüz tam gözlenmemiş olabilir; bu küçük
    bir iyimserliktir.
Modeller 2020–24'te ERA5 ile eğitilmiştir ve yeniden eğitilmez (geçmiş
tahmin arşivi 2020–24'ü kapsamaz). Tahmin modelinin yağışı ERA5'ten
sistematik farklıysa (ör. sağanağı daha düşük veriyorsa) bu da başarıya
yansır; gerçek kullanımda da böyle olurdu.

Tahmin modelleri: ECMWF IFS 0.25° (ana), GFS ve Open-Meteo'nun karma
tahmini (best_match) yalnız kıyas için. Aynı gün için modeller arasında
kat kat fark olabilir (13 Şubat 2026, Konak: ECMWF 14 mm, GFS 28 mm,
ERA5 46 mm).

Kontrol — "tahminsiz": D'nin yağışı 0 verilir (hiç tahmin yok). Başarının
ne kadarının bugünün yağışından, ne kadarının zaten gözlenmiş geçmiş
günlerden (önceki 7 günün yağışı en önemli değişken) geldiğini ayırır.

Karşılaştırma aynı satırlar üzerinde yapılır: test yıllarında (2025–26)
her tahmin modelinin eksiksiz saatleri olan ilçe-günler.

Çıktı: egitim/tahmin_sinamasi.json. Çalıştırma: venv/bin/python -m hesap.tahmin_sinamasi
(ilk çalıştırmada tahmin arşivi itfaiye_veri/ önbelleğine indirilir)
"""
import logging
import os

import numpy as np
import pandas as pd

from afet import ag
from afet.dosya import json_oku
from hesap import gunlugu_kur, sonucu_yaz
from hesap import ols_model as om
from hesap import siniflandirma as sn
from hesap.ilce_gun import ILCE_CSV, ILCE_GUN_CSV, gunluk_yagis, saatlik_arsiv

log = logging.getLogger("tahmin_sinamasi")
SONUC_JSON = os.path.join(sn.CIKTI_DIR, "tahmin_sinamasi.json")
TAHMIN_MODELLERI = {"ecmwf_ifs025": "ECMWF IFS 0.25°", "gfs_seamless": "GFS (NOAA)",
                    "best_match": "Open-Meteo karma"}
ANA = "ecmwf_ifs025"
GUNUN_YAGISI = ["yagis_mm", "yagis_max1s_mm", "yagis_max3s_mm"]   # tahminden gelen kolonlar


def tahmin_arsivi(ilce_df, model, bas, bit, once=1):
    """Her ilçe noktası için saatlik tahmin: DataFrame(ilce, zaman, mm). Her saatin
    değeri, modelin `once` gün önceki koşusundan; once=0: modelin kendi kaydı (her
    saat, o saati kapsayan en yeni koşudan — canlı sayfada geçmiş saatler budur).
    Eksik saatler NaN kalır."""
    degisken = "precipitation" if once == 0 else f"precipitation_previous_day{once}"
    ek = "" if once == 1 else f"_d{once}"
    return saatlik_arsiv(ag.OPEN_METEO_GECMIS_TAHMIN_URL, ilce_df, bas, bit, degisken,
                         f"tahmin_{model}{ek}_{{bas}}_{{bit}}.json", models=model)


def tam_gunler(saatlik):
    """İlçe-gün başına 24 saatin hepsi var mı: DataFrame(ilce, gun, tam)."""
    return (saatlik.assign(gun=saatlik.zaman.dt.date).groupby(["ilce", "gun"]).mm
            .agg(lambda x: x.notna().sum() == 24).rename("tam").reset_index())


def tahmin_gunluk(saatlik):
    """Günün tahmin kolonları; 24 saati eksiksiz olmayan ilçe-günler atılır."""
    g = gunluk_yagis(saatlik).merge(tam_gunler(saatlik), on=["ilce", "gun"])
    g = g[g.tam][["ilce", "gun"] + GUNUN_YAGISI]
    g["gun"] = g.gun.astype(str)
    return g


def tahminle_degistir(test, tahmin):
    """Test satırlarının o günkü yağışını tahminle değiştirir; geçmiş günler aynı kalır."""
    t = test.drop(columns=GUNUN_YAGISI).merge(tahmin, on=["ilce", "gun"], how="inner")
    return sn.hazirla(t.drop(columns=[c for c in t.columns if c.startswith("log_") or c in ("y", "olay")]))


def egitilmis(ad, sonuc):
    """siniflandirma_sonuc.json'daki parametrelerle model (kısaltılmış adlar geri açılır)."""
    m = sn.MODELLER[ad][0]()
    gecerli = m.get_params()
    prm = {}
    for k, v in sonuc["modeller"][ad]["parametreler"].items():
        prm[k if k in gecerli else next(g for g in gecerli if g.endswith("__" + k))] = v
    return m.set_params(**prm)


def yagis_uyumu(gozlem, tahmin):
    """Tahmin edilen günlük yağış, arşivdekine ne kadar yakın?"""
    b = gozlem[["ilce", "gun", "yagis_mm"]].merge(tahmin[["ilce", "gun", "yagis_mm"]], on=["ilce", "gun"],
                                                   suffixes=("_g", "_t"))
    yagisli = b[b.yagis_mm_g >= 20]
    return {"korelasyon": round(float(np.corrcoef(b.yagis_mm_g, b.yagis_mm_t)[0, 1]), 3),
            "ort_gozlem_mm": round(float(b.yagis_mm_g.mean()), 2), "ort_tahmin_mm": round(float(b.yagis_mm_t.mean()), 2),
            "yagisli_gun": int(len(yagisli)),
            "yagisli_gunde_tahmin_orani": round(float(yagisli.yagis_mm_t.sum() / max(yagisli.yagis_mm_g.sum(), 1e-9)), 3)}


def calistir(t, tahminler, sonuc, modeller=None):
    """t: ilce_gun tablosu; tahminler: {tahmin modeli: tahmin_gunluk çıktısı};
    sonuc: siniflandirma_sonuc.json içeriği."""
    modeller = modeller or list(sn.MODELLER)
    t = sn.hazirla(t)
    egitim, test = t[~t.yil.isin(om.TEST_YILLARI)], t[t.yil.isin(om.TEST_YILLARI)]
    # ortak satırlar: her tahmin modelinin eksiksiz olduğu ilçe-günler
    ortak = test[["ilce", "gun"]]
    for g in tahminler.values():
        ortak = ortak.merge(g[["ilce", "gun"]], on=["ilce", "gun"])
    test = test.merge(ortak, on=["ilce", "gun"]).reset_index(drop=True)
    # tahminsiz: bugünün yağışı hiç bilinmiyor (0) — başarının ne kadarı yalnız geçmiş günlerden?
    sifir = test[["ilce", "gun"]].assign(**{k: 0.0 for k in GUNUN_YAGISI})
    girdiler = {"gozlem": test, **{k: tahminle_degistir(test, g) for k, g in tahminler.items()},
                "tahminsiz": tahminle_degistir(test, sifir)}
    out = {}
    for ad in modeller:
        kolonlar = sn.MODELLER[ad][1]
        esik = sonuc["modeller"][ad]["esik"]
        m = egitilmis(ad, sonuc).fit(egitim[kolonlar], egitim.olay)
        out[ad] = {}
        for kaynak, x in girdiler.items():
            x = x.sort_values(["gun", "ilce"]).reset_index(drop=True)
            p = m.predict_proba(x[kolonlar])[:, 1]
            out[ad][kaynak] = {**sn.olculer(x.olay, p, esik), "il": sn.il_gunleri(x, p, esik)}
        log.info("%s sınandı", ad)
    return {
        "senaryo": "uyarı D-1 sonunda: D'nin yağışı 1 gün önceki tahminden, önceki günler arşivden",
        "test": {"satir": len(test), "gun": int(test.gun.nunique()), "olay": int(test.olay.sum()),
                 "ilk": str(test.gun.min()), "son": str(test.gun.max())},
        "tahmin_modelleri": {k: TAHMIN_MODELLERI.get(k, k) for k in tahminler},
        "ana": ANA if ANA in tahminler else next(iter(tahminler)),
        "secili": sonuc["secili"],
        "yagis_uyumu": {k: yagis_uyumu(test, g.merge(ortak, on=["ilce", "gun"])) for k, g in tahminler.items()},
        "sonuclar": out,
    }


def yazdir(r):
    s = r["test"]
    print(f"\nHava tahminiyle sınama — {r['senaryo']}")
    print(f"{s['ilk']} – {s['son']}: {s['satir']} ilçe-gün, {s['olay']} olay\n")
    print("Tahmin edilen yağış, arşive göre:")
    for k, u in r["yagis_uyumu"].items():
        print(f"  {r['tahmin_modelleri'][k]:18} r {u['korelasyon']:.2f}  ≥20 mm günlerde tahmin/gözlem "
              f"{u['yagisli_gunde_tahmin_orani']:.2f} ({u['yagisli_gun']} gün)")
    kaynaklar = ["gozlem", *r["tahmin_modelleri"], "tahminsiz"]
    print(f"\n{'model':9} {'girdi':12} {'AUC':>6} {'AP':>6} {'kesinlik':>8} {'duyarlılık':>10} {'büyük gün':>10} {'alarm günü':>10}")
    for ad, k in r["sonuclar"].items():
        for kaynak in kaynaklar:
            o = k[kaynak]
            print(f"{ad:9} {kaynak[:12]:12} {o['auc']:6.3f} {o['ap']:6.3f} {o['kesinlik']:8.2f} {o['duyarlilik']:10.2f} "
                  f"{o['il']['alarmli']:>4}/{o['il']['buyuk_olay_gunu']:<5} {o['il']['alarm_gunu']:>10}")


def main():
    gunlugu_kur()
    sonuc = json_oku(sn.SONUC_JSON)
    t = pd.read_csv(ILCE_GUN_CSV)
    ilce_df = pd.read_csv(ILCE_CSV)
    bas = pd.Timestamp(f"{min(om.TEST_YILLARI)}-01-01").date()
    bit = pd.Timestamp(t.gun.max()).date()
    tahminler = {k: tahmin_gunluk(tahmin_arsivi(ilce_df, k, bas, bit)) for k in TAHMIN_MODELLERI}
    sonucu_yaz(SONUC_JSON, calistir(t, tahminler, sonuc), yazdir)


if __name__ == "__main__":
    main()
