"""Güvenilirlik: sınıflandırma sonuçları şans mı, tek bir dönemin özelliği mi?

hesap/siniflandirma.py ve hesap/tahmin_sinamasi.py tek bir test dönemine
(2025–26, 28 büyük olay günü) dayanır. Bu betik üç soruyu yanıtlar:

1. Yıl yıl geriye dönük sınama (rolling origin). Her test yılı Y için model
   yalnız Y'den önceki yıllarla eğitilir: 2020–21 → 2022, 2020–22 → 2023, …
   2020–25 → 2026. Hiperparametre ızgara araması ve alarm eşiği de her
   katmanda yeniden, yalnız o katmanın eğitim yıllarıyla seçilir (yıl
   dışarıda; sn.ayarla). Böylece her tahmin "o gün elde olacak bilgiyle"
   yapılmıştır ve sonuç 1 yerine 5 test yılına dayanır.
   Tek kalan sızıntı: model TÜRÜ (gradient boosting) 2020–24'e bakılarak
   seçildi. Bu yüzden lojistik regresyon (ayarı neredeyse yok) yanında
   raporlanır.

2. Güven aralığı. Aynı gün 30 ilçe aynı fırtınayı yaşar; satırlar bağımsız
   değildir. Bu yüzden bootstrap satır değil GÜN üzerinden yapılır: günler
   yerine koyarak yeniden çekilir, ölçü yeniden hesaplanır (BOOTSTRAP kez);
   %2.5 ve %97.5 yüzdelikler %95 aralığıdır.

3. Katı zamanlama — öğlen uyarısı. tahmin_sinamasi uyarının D-1 sonunda
   verildiğini varsayar (D-1'in yağışı gözlenmiş). Burada uyarı D-1 saat
   12:00'de verilir ve o anda elde olmayan hiçbir bilgi kullanılmaz:
     • D 00–11 saatleri: 1 gün önceki koşu (D-1 00–11'de yayımlandı)
     • D 12–23 saatleri: 2 gün önceki koşu (D-2 12–23'te yayımlandı)
     • D-1 12–23 saatleri (dün, önceki 3 / 7 gün içinde): gözlem yerine 1 gün
       önceki koşu (D-2 12–23'te yayımlandı)
   Geçmiş tahmin arşivi 2024'te başladığı için tahminli sınama 2024–26'yı
   kapsar.

Çıktı: egitim/guvenilirlik.json. Süre ~10 dk (her katmanda ızgara araması).
Çalıştırma: venv/bin/python -m hesap.guvenilirlik
"""
import datetime as dt
import logging
import os
import time

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import average_precision_score

from afet.dosya import json_yaz
from hesap import ols_model as om
from hesap import siniflandirma as sn
from hesap import tahmin_sinamasi as ts
from hesap.ilce_gun import ILCE_CSV, ILCE_GUN_CSV, yagis_arsivi

log = logging.getLogger("guvenilirlik")
SONUC_JSON = os.path.join(sn.CIKTI_DIR, "guvenilirlik.json")

TEST_YILLARI = [2022, 2023, 2024, 2025, 2026]
TAHMIN_ILK_YIL = 2024                 # geçmiş tahmin arşivinin başladığı yıl
MODELLER = ["lojistik", "gb"]
BOOTSTRAP = 1000
TOHUM = 0
OGLEN = 12
ONCEKI = ["yagis_dun_mm", "yagis_onceki3g_mm", "yagis_onceki7g_mm"]   # hepsi D-1'i içerir
ARSIV_ARALIGI = (dt.date(2019, 6, 3), dt.date(2026, 9, 29))           # ilce_gun önbelleğinin aralığı


# ── 3. Öğlen uyarısı girdileri ──────────────────────────────────────────────

def oglen_girdisi(gozlem_saatlik, tahmin1, tahmin2):
    """Öğlen (D-1 12:00) elde olan bilgiyle ilçe-gün yağış kolonları.

    Döner: DataFrame(ilce, gun, yagis_mm, yagis_max1s_mm, yagis_max3s_mm,
    duzeltme_mm). duzeltme_mm, D-1 öğleden sonrası için (tahmin − gözlem):
    dün / önceki 3 / önceki 7 gün kolonlarına eklenir."""
    a = tahmin1.set_index(["ilce", "zaman"]).mm
    b = tahmin2.set_index(["ilce", "zaman"]).mm
    ortak = a.index.intersection(b.index)
    saat = ortak.get_level_values("zaman").hour
    karma = pd.Series(np.where(saat < OGLEN, a.loc[ortak].values, b.loc[ortak].values), index=ortak)
    gun = ts.tahmin_gunluk(karma.rename("mm").reset_index())
    # D-1 öğleden sonrası: gözlem → 1 gün önceki tahmin
    g = gozlem_saatlik.set_index(["ilce", "zaman"]).mm
    o = a.index.intersection(g.index)
    ogle = o[o.get_level_values("zaman").hour >= OGLEN]
    fark = pd.DataFrame({"ilce": ogle.get_level_values("ilce"),
                         "gun": (ogle.get_level_values("zaman") + pd.Timedelta(days=1)).date.astype(str),
                         "f": a.loc[ogle].values - g.loc[ogle].fillna(0).values})
    eksik = fark.f.isna().groupby([fark.ilce, fark.gun]).any()
    duz = fark.groupby(["ilce", "gun"]).f.sum().where(~eksik).rename("duzeltme_mm").reset_index()
    return gun.merge(duz.dropna(), on=["ilce", "gun"])


def oglen_degistir(test, girdi):
    """Bugünün yağışını öğlen tahminiyle değiştirir, geçmiş günleri düzeltir."""
    t = test.merge(girdi[["ilce", "gun", "duzeltme_mm"]], on=["ilce", "gun"], how="inner")
    for k in ONCEKI:
        t[k] = (t[k] + t.duzeltme_mm).clip(lower=0)
    return ts.tahminle_degistir(t.drop(columns="duzeltme_mm"), girdi.drop(columns="duzeltme_mm"))


# ── 2. Güne göre bootstrap ──────────────────────────────────────────────────

def bootstrap(x, alarm, n=BOOTSTRAP, tohum=TOHUM):
    """x: DataFrame(gun, olay, p, cagri_su); alarm: bool dizi. Günler yerine
    koyarak çekilir. Döner: {ölçü: [alt, üst]} (%95)."""
    x = x.reset_index(drop=True).assign(a=np.asarray(alarm))
    gunler = x.gun.values
    benzersiz, ters = np.unique(gunler, return_inverse=True)
    satirlar = [np.flatnonzero(ters == i) for i in range(len(benzersiz))]
    il = x.groupby("gun").agg(c=("cagri_su", "sum"), a=("a", "any")).reindex(benzersiz)
    buyuk, il_alarm = (il.c >= om.OLAY_CAGRI).values, il.a.values
    y, p, a = x.olay.values, x.p.values, x.a.values
    r = np.random.default_rng(tohum)
    olc = {"ap": [], "kesinlik": [], "duyarlilik": [], "buyuk_gun_yakalama": []}
    for _ in range(n):
        sec = r.integers(0, len(benzersiz), len(benzersiz))
        idx = np.concatenate([satirlar[i] for i in sec])
        yy, aa = y[idx], a[idx]
        if yy.sum() == 0:
            continue
        olc["ap"].append(average_precision_score(yy, p[idx]))
        olc["kesinlik"].append((aa & (yy == 1)).sum() / max(aa.sum(), 1))
        olc["duyarlilik"].append((aa & (yy == 1)).sum() / yy.sum())
        b = buyuk[sec]
        if b.sum():
            olc["buyuk_gun_yakalama"].append((il_alarm[sec] & b).sum() / b.sum())
    return {k: [round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)]
            for k, v in olc.items() if v}


# ── 1. Yıl yıl geriye dönük sınama ──────────────────────────────────────────

def katman(t, yil, ad, girdiler=None):
    """yil'dan önceki yıllarla ayarla + eğit, yil'i her girdiyle tahmin et.
    girdiler: {ad: (DataFrame) -> DataFrame} test satırlarını dönüştürür."""
    egitim, test = t[t.yil < yil], t[t.yil == yil]
    m, prm, _, esik = sn.ayarla(ad, egitim)
    kolonlar = sn.MODELLER[ad][1]
    m = clone(m).fit(egitim[kolonlar], egitim.olay)
    out = {}
    for kaynak, donustur in {"gozlem": lambda x: x, **(girdiler or {})}.items():
        x = donustur(test).sort_values(["gun", "ilce"]).reset_index(drop=True)
        if len(x):
            out[kaynak] = x[["ilce", "gun", "olay", "cagri_su"]].assign(
                p=m.predict_proba(x[kolonlar])[:, 1], esik=esik)
    return out, {k.split("__")[-1]: v for k, v in prm.items()}, esik


def ozet(x, n=BOOTSTRAP):
    """Birleştirilmiş katman tahminleri (her satırın kendi katman eşiği var)."""
    alarm = x.p.values >= x.esik.values
    y = x.olay.values == 1
    dp, yp, yn = int((alarm & y).sum()), int((alarm & ~y).sum()), int((~alarm & y).sum())
    return {**sn.olculer(x.olay, x.p), "dogru_alarm": dp, "yanlis_alarm": yp, "kacirilan": yn,
            "kesinlik": round(dp / max(dp + yp, 1), 3), "duyarlilik": round(dp / max(dp + yn, 1), 3),
            "il": sn.il_gunleri(x, alarm.astype(float), 0.5), "aralik_95": bootstrap(x, alarm, n),
            "yillar": sorted({int(g[:4]) for g in x.gun})}


def calistir(t, girdiler=None, test_yillari=TEST_YILLARI, modeller=MODELLER, n=BOOTSTRAP):
    """girdiler: {ad: (ilk_yil, dönüştürücü)} — tahminli girdiler yalnız ilk_yil'dan itibaren.
    Döner: her model için katmanlar, bütün test yıllarının birleşimi (gözlem) ve
    tahminli dönemde bütün girdilerin AYNI satırlardaki kıyası."""
    t = sn.hazirla(t)
    girdiler = girdiler or {}
    sonuc = {}
    for ad in modeller:
        tahminler, katmanlar = {}, []
        for yil in test_yillari:
            s = time.time()
            g = {k: f for k, (ilk, f) in girdiler.items() if yil >= ilk}
            out, prm, esik = katman(t, yil, ad, g)
            for kaynak, x in out.items():
                tahminler.setdefault(kaynak, []).append(x)
            y = out["gozlem"]
            katmanlar.append({"test_yili": yil, "egitim": [int(t.yil.min()), yil - 1], "parametreler": prm,
                              "esik": round(esik, 3), **sn.olculer(y.olay, y.p, esik),
                              "il": sn.il_gunleri(y, y.p, esik)})
            log.info("%s %d (%.0f sn): AP %.3f", ad, yil, time.time() - s, katmanlar[-1]["ap"])
        birlesik = {k: pd.concat(v, ignore_index=True) for k, v in tahminler.items()}
        tahminli = {}
        if girdiler:
            ortak = birlesik["gozlem"][["ilce", "gun"]]
            for k in girdiler:
                ortak = ortak.merge(birlesik[k][["ilce", "gun"]], on=["ilce", "gun"])
            tahminli = {k: ozet(birlesik[k].merge(ortak, on=["ilce", "gun"]), n) for k in ["gozlem", *girdiler]}
        sonuc[ad] = {"katmanlar": katmanlar, "tum_yillar": ozet(birlesik["gozlem"], n), "tahminli_donem": tahminli}
    return {
        "yontem": "her test yılı yalnız önceki yıllarla eğitilir; ızgara araması ve eşik her katmanda yeniden",
        "test_yillari": test_yillari, "bootstrap": f"günler yerine koyarak, {n} tekrar, %95 yüzdelik",
        "oglen_uyarisi": "D 00–11: 1 gün önceki koşu; D 12–23: 2 gün önceki koşu; D-1 12–23: gözlem yerine 1 gün önceki koşu",
        "sonuclar": sonuc,
    }


def yazdir(r):
    for ad, s in r["sonuclar"].items():
        print(f"\n{ad} — yıl yıl (gözlenen yağış):")
        print(f"  {'yıl':5} {'olay':>5} {'AUC':>6} {'AP':>6} {'kesinlik':>8} {'duyarlılık':>10} {'büyük gün':>10} {'alarm günü':>10}")
        for k in s["katmanlar"]:
            print(f"  {k['test_yili']:<5} {k['olay']:5} {k['auc']:6.3f} {k['ap']:6.3f} {k['kesinlik']:8.2f} "
                  f"{k['duyarlilik']:10.2f} {k['il']['alarmli']:>4}/{k['il']['buyuk_olay_gunu']:<5} {k['il']['alarm_gunu']:>10}")
        print("  birleşik (%95 aralık):")
        for kaynak, o in {"tüm yıllar": s["tum_yillar"], **s["tahminli_donem"]}.items():
            a = o["aralik_95"]
            print(f"  {kaynak:14} {o['yillar'][0]}–{o['yillar'][-1]}  AP {o['ap']:.3f} {a['ap']}  "
                  f"duyarlılık {o['duyarlilik']:.2f} {a['duyarlilik']}  kesinlik {o['kesinlik']:.2f} {a['kesinlik']}  "
                  f"büyük gün {o['il']['alarmli']}/{o['il']['buyuk_olay_gunu']} {a.get('buyuk_gun_yakalama')}  "
                  f"alarm günü {o['il']['alarm_gunu']}/{o['il']['gun']}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    t = pd.read_csv(ILCE_GUN_CSV)
    ilce_df = pd.read_csv(ILCE_CSV)
    bas, bit = dt.date(TAHMIN_ILK_YIL, 1, 1), pd.Timestamp(t.gun.max()).date()
    t1 = ts.tahmin_arsivi(ilce_df, ts.ANA, bas, bit, once=1)
    t2 = ts.tahmin_arsivi(ilce_df, ts.ANA, bas, bit, once=2)
    gozlem = yagis_arsivi(ilce_df, *ARSIV_ARALIGI)
    aksam = ts.tahmin_gunluk(t1)
    oglen = oglen_girdisi(gozlem, t1, t2)
    girdiler = {
        "ecmwf_aksam": (TAHMIN_ILK_YIL, lambda x: ts.tahminle_degistir(x, aksam)),
        "ecmwf_oglen": (TAHMIN_ILK_YIL, lambda x: oglen_degistir(x, oglen)),
        "tahminsiz": (TAHMIN_ILK_YIL, lambda x: ts.tahminle_degistir(
            x, x[["ilce", "gun"]].assign(**{k: 0.0 for k in ts.GUNUN_YAGISI}))),
    }
    r = calistir(t, girdiler)
    json_yaz(SONUC_JSON, r, okunur=True)
    yazdir(r)
    print(f"\nYazıldı: {SONUC_JSON}")


if __name__ == "__main__":
    main()
