"""Coğrafi ağırlıklı lojistik regresyon (GWR): yağışın etkisi ilçeden ilçeye değişiyor mu?

Lund GeoAI, "Geographical machine learning" dersi. Global model bütün
ilçelere tek denklem uygular; OLS'te ilçe artıkları örüntülüydü ve
sınıflandırmada kıyı ilçeleri sürekli kaçırılıyordu. GWR her ilçe için ayrı
bir model kurar: o ilçenin verisi tam, komşularınınki uzaklıkla azalan
ağırlıkla girer.

Model (her ilçe i için, lojistik):
    logit P(olay) = b0_i + b1_i·log(1+yağış) + b2_i·log(1+dünkü yağış)
                    + b3_i·log(1+önceki 7 gün)
  • Değişkenler eğitim verisinde standartlaştırılır; katsayılar karşılaştırılabilir.
  • Nüfus ve kent payı yok: ilçe başına sabittirler, yerel sabit (b0_i)
    onları zaten taşır.
  • Hafif L2 düzenlileştirme (C = 1): olayı az ilçelerde katsayılar patlamasın.
Ağırlık: uyarlanır bisquare çekirdeği. Konum: ilçenin yağış noktası
(yapılaşmış alanın ağırlık merkezi). Bant genişliği k = en yakın k ilçe
(kendisi dahil); w = (1 − (d/d_k+1)²)², d_k+1 dışı 0. k küçükse model yerel;
k = 1 her ilçe için ayrı (komşusuz) model demektir.
k = 30 bile global DEĞİLDİR: bütün ilçeler girer ama ağırlık uzaklıkla
sıfıra iner. Gerçek global kıyas ayrı bir global lojistik modeldir.

Bant genişliği seçimi: 2020–24'te yıl dışarıda bırakılarak, AP en yüksek k
(GWR dersi: CV ile seçim). Kıyas: aynı değişkenlerle global lojistik (+ nüfus,
kent payı) ve sınıflandırmadaki lojistik (yağış × kent payı etkileşimiyle;
ilçe farkının en basit hâli). Sınama guvenilirlik ile aynı: 2022–26 yıl yıl,
eşik her katmanda yeniden; AP farkı eşleştirilmiş hafta bootstrap'ıyla.

Harita çıktısı (bütün verilerle eğitilmiş): her ilçenin yerel katsayıları ve
okunur karşılığı — her değişken için 10 → 40 mm'nin olasılık oranı (odds
ratio, "çarpan"; öteki değişkenler sabit) ve %95 aralığı; kuru geçmişte 10 ve
40 mm'deki olasılık. Sitenin Uyarı sekmesi çarpanları haritada gösterir.

Sağlamlık (ek_degiskenler.csv varsa): günün yağışı tek noktadan değil, ilçe
içindeki en yağışlı ızgara noktasından (log_max_nokta) alınarak aynı bantla
yeniden kurulur. Soru: büyük ilçelerde (Bergama, Dikili) günün yağışının zayıf
etkisi, sağanağın tek noktayı ıskalamasının yan etkisi mi? Önceki 7 günün
toplamı bu ıskalamaya daha az duyarlıdır; örüntü yalnız ölçüm kaynaklıysa
çok noktalı yağışta kaybolmalı.

Çıktı: egitim/gwr_sonuc.json. Çalıştırma: venv/bin/python -m hesap.gwr (~2 dk)
Önkoşul (sağlamlık için): hesap.ek_degiskenler
"""
import logging
import os
import time

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

from afet.yollar import EK_DEGISKENLER_CSV, GWR_SONUC, ILCE_CSV, ILCE_GUN_CSV
from hesap import ek_degiskenler as ed
from hesap import gunlugu_kur, sonucu_yaz
from hesap import guvenilirlik as gv
from hesap import ols_model as om
from hesap import siniflandirma as sn

log = logging.getLogger("gwr")
DEGISKENLER = ["log_yagis", "log_dun", "log_onceki7g"]
COK_NOKTA = ["log_max_nokta", "log_dun", "log_onceki7g"]     # sağlamlık: günün yağışı en yağışlı noktadan
GLOBAL_EK = ["log_nufus", "kent_payi"]
BANTLAR = [1, 2, 3, 4, 5, 6, 9, 12, 16, 20, 25, 30]
KATSAYI_BOOTSTRAP = 100      # ilçe katsayılarının güven aralığı (hafta blokları)
C = 1.0
DUYARLILIK_MM = (10, 40)


def uzakliklar(ilce_df):
    """İlçe noktaları arası büyük çember uzaklığı (km), DataFrame (ilçe × ilçe)."""
    la, lo = np.radians(ilce_df.yagis_lat.values), np.radians(ilce_df.yagis_lon.values)
    a = (np.sin((la[:, None] - la) / 2) ** 2
         + np.cos(la[:, None]) * np.cos(la) * np.sin((lo[:, None] - lo) / 2) ** 2)
    return pd.DataFrame(6371 * 2 * np.arcsin(np.sqrt(a)), index=ilce_df.ilce, columns=ilce_df.ilce)


def agirliklar(d, ilce, k):
    """Uyarlanır bisquare: en yakın k ilçe (kendisi dahil) ağırlık alır."""
    s = d.loc[ilce].sort_values()
    sinir = s.iloc[k] if k < len(s) else s.iloc[-1] * 1.0001 + 1e-9
    w = (1 - (s / sinir) ** 2) ** 2
    return w[s < sinir]


class GWLR:
    """Coğrafi ağırlıklı lojistik regresyon (ilçe konumlu)."""

    def __init__(self, d, k, kolonlar=DEGISKENLER, c=C):
        self.d, self.k, self.kolonlar, self.c = d, k, kolonlar, c

    def fit(self, t):
        self.ort = t[self.kolonlar].mean()
        self.ss = t[self.kolonlar].std().replace(0, 1)
        X = ((t[self.kolonlar] - self.ort) / self.ss).values
        self.modeller = {}
        ilce = t.ilce.values
        for i in sorted(set(ilce)):
            w = agirliklar(self.d, i, self.k)
            sw = pd.Series(ilce).map(w).fillna(0).values
            m = sw > 0
            y = t.olay.values[m]
            if y.min() == y.max():                       # komşulukta hiç olay yok
                self.modeller[i] = None
                continue
            self.modeller[i] = LogisticRegression(C=self.c, max_iter=2000).fit(X[m], y, sample_weight=sw[m])
        self.taban = float(t.olay.mean())
        return self

    def predict_proba(self, t):
        X = ((t[self.kolonlar] - self.ort) / self.ss).values
        p = np.full(len(t), self.taban)
        for i, m in self.modeller.items():
            sec = (t.ilce == i).values
            if m is not None and sec.any():
                p[sec] = m.predict_proba(X[sec])[:, 1]
        return p

    def katsayilar(self):
        """İlçe → {sabit, değişken: standart katsayı}."""
        return {i: {"sabit": float(m.intercept_[0]), **dict(zip(self.kolonlar, map(float, m.coef_[0])))} if m else None
                for i, m in self.modeller.items()}


def yil_disarida_ap(t, d, k, yillar, kolonlar=DEGISKENLER):
    """Eğitim yıllarında yıl dışarıda: birleşik AP ve dışarıda tahminler."""
    p = np.zeros(len(t))
    for y in yillar:
        m = (t.yil == y).values
        p[m] = GWLR(d, k, kolonlar).fit(t[~m]).predict_proba(t[m])
    return float(average_precision_score(t.olay, p)), p


def bant_sec(t, d, bantlar=BANTLAR):
    yillar = sorted(t.yil.unique())
    skor = {}
    for k in bantlar:
        s = time.time()
        skor[k] = round(yil_disarida_ap(t, d, k, yillar)[0], 4)
        log.info("bant k=%d: AP %.4f (%.0f sn)", k, skor[k], time.time() - s)
    return max(skor, key=skor.get), skor


def yil_yil(t, d, k, test_yillari=gv.TEST_YILLARI, kolonlar=DEGISKENLER):
    """GWR'yi guvenilirlik ile aynı biçimde sına: her yıl önceki yıllarla, eşik iç sınamayla."""
    parcalar = []
    for yil in test_yillari:
        egitim, test = t[t.yil < yil].reset_index(drop=True), t[t.yil == yil]
        _, oof = yil_disarida_ap(egitim, d, k, sorted(egitim.yil.unique()), kolonlar)
        esik = sn.f1_esigi(egitim.olay, oof)
        p = GWLR(d, k, kolonlar).fit(egitim).predict_proba(test)
        parcalar.append(gv.tahmin_tablosu(test, p, esik))
        log.info("GWR %d: AP %.3f", yil, average_precision_score(test.olay, p))
    return pd.concat(parcalar, ignore_index=True)


def global_tanim():
    """Aynı değişkenler + nüfus, kent payı; global lojistik (sn.ModelTanimi)."""
    return sn.MODELLER["lojistik"]._replace(kolonlar=DEGISKENLER + GLOBAL_EK, aciklama="global lojistik")


def katsayi_araliklari(t, d, k, n=KATSAYI_BOOTSTRAP, tohum=gv.TOHUM, kolonlar=DEGISKENLER):
    """Yerel katsayıların %95 aralığı: haftalar yerine koyarak çekilir, GWR
    yeniden eğitilir. Aralık sıfırı içeriyorsa o ilçedeki etki kanıtlanmamış;
    iki ilçenin aralığı örtüşmüyorsa aralarındaki fark gerçek sayılabilir."""
    _, satirlar = gv.blok_satirlari(gv.hafta(t.gun))
    ornek = {}
    for j, (_, idx) in enumerate(gv.blok_cek(satirlar, n, tohum)):
        for ilce, kk in GWLR(d, k, kolonlar).fit(t.iloc[idx].reset_index(drop=True)).katsayilar().items():
            if kk:
                for v in kolonlar:
                    ornek.setdefault((ilce, v), []).append(kk[v])
        if (j + 1) % 20 == 0:
            log.info("katsayı bootstrap %d/%d", j + 1, n)
    return {key: gv.aralik_95(v) for key, v in ornek.items()}


def harita_ozeti(t, d, k, n=KATSAYI_BOOTSTRAP, kolonlar=DEGISKENLER):
    """Bütün verilerle eğitilmiş GWR: ilçe başına katsayılar, %95 aralıkları
    ve okunur duyarlılık. kolonlar[0] günün yağışıdır (log1p mm)."""
    g = GWLR(d, k, kolonlar).fit(t)
    kat = g.katsayilar()
    aralik = katsayi_araliklari(t, d, k, n, kolonlar=kolonlar) if n else {}
    a, b = DUYARLILIK_MM
    yagis = kolonlar[0]
    adim = {v: (np.log1p(b) - np.log1p(a)) / g.ss[v] for v in kolonlar}      # standart birimde 10 → 40 mm

    def carp(v, x):
        return round(float(np.exp(x * adim[v])), 2)

    out = []
    for ilce, kk in kat.items():
        satir = pd.DataFrame({"ilce": [ilce, ilce], **{v: [0.0, 0.0] for v in kolonlar}})
        satir[yagis] = [np.log1p(a), np.log1p(b)]
        p = g.predict_proba(satir)
        out.append({"ilce": ilce, "katsayi": {k2: round(v, 3) for k2, v in kk.items()} if kk else None,
                    "aralik_95": {v: aralik[(ilce, v)] for v in kolonlar if (ilce, v) in aralik},
                    "carpan_10_40": {v: {"deger": carp(v, kk[v]),
                                         **({"aralik_95": [carp(v, x) for x in aralik[(ilce, v)]]}
                                            if (ilce, v) in aralik else {})}
                                     for v in kolonlar} if kk else None,
                    "p_10": round(float(p[0]), 4), "p_40": round(float(p[1]), 4)})
    return out


def cok_nokta_sinamasi(t_ham, ek, d, k, tek_nokta, test_yillari=gv.TEST_YILLARI, n=gv.BOOTSTRAP,
                       n_katsayi=KATSAYI_BOOTSTRAP):
    """Sağlamlık: aynı bantla, günün yağışı ilçedeki en yağışlı noktadan.
    tek_nokta: asıl GWR'nin yıl yıl tahminleri (AP farkı için)."""
    x = ed.birlestir(t_ham, ek)
    tahmin = yil_yil(x, d, k, test_yillari, COK_NOKTA)
    o = ed.kisa_ozet(tahmin, n)
    o["ap_farki_tek_noktaya_gore"] = ed.eslesik_fark(tek_nokta, tahmin, n)
    return {"degiskenler": COK_NOKTA, "sonuc": o, "ilceler": harita_ozeti(x, d, k, n_katsayi, COK_NOKTA)}


def calistir(t_ham, ilce_df, ek=None, bantlar=BANTLAR, test_yillari=gv.TEST_YILLARI, n=gv.BOOTSTRAP,
             n_katsayi=KATSAYI_BOOTSTRAP):
    t = sn.hazirla(t_ham)
    d = uzakliklar(ilce_df)
    egitim = t[~t.yil.isin(om.TEST_YILLARI)].reset_index(drop=True)
    k, skor = bant_sec(egitim, d, bantlar)
    log.info("seçilen bant: k=%d", k)
    tahmin = {"gwr": yil_yil(t, d, k, test_yillari),
              "global": gv.yil_yil(t, "global", lambda _: global_tanim(), test_yillari),
              "lojistik": gv.yil_yil(t, "lojistik", test_yillari=test_yillari)}
    sonuc = {}
    for ad, x in tahmin.items():
        o = ed.kisa_ozet(x, n)
        if ad != "global":
            o["ap_farki_globale_gore"] = ed.eslesik_fark(tahmin["global"], x, n)
        sonuc[ad] = o
    r = {"degiskenler": DEGISKENLER, "global_ek": GLOBAL_EK, "bantlar": skor, "bant": k,
         "c": C, "sonuclar": sonuc, "katsayi_bootstrap": n_katsayi, "ilceler": harita_ozeti(t, d, k, n_katsayi)}
    if ek is not None:
        r["cok_nokta"] = cok_nokta_sinamasi(t_ham, ek, d, k, tahmin["gwr"], test_yillari, n, n_katsayi)
    return r


def yazdir(r):
    print(f"\nBant seçimi (2020–24, yıl dışarıda AP): {r['bantlar']} → k = {r['bant']}")
    print(f"\n{'model':9} {'AP':>6} {'ΔAP globale göre [%95]':>26} {'duyarlılık':>10} {'kesinlik':>8} "
          f"{'atak ilk gün':>12} {'kıyı':>8}")
    for ad, o in r["sonuclar"].items():
        f = o.get("ap_farki_globale_gore")
        print(f"{ad:9} {o['ap']:6.3f} {str(f) if f else '':>26} {o['duyarlilik']:10.2f} {o['kesinlik']:8.2f} "
              f"{o['atak']['ilk_gun_alarmli']:>5}/{o['atak']['atak']:<6} "
              f"{o['kiyi']['yakalanan']:>4}/{o['kiyi']['olay']}")
    print("\nİlçe başına (bütün veri): 10 → 40 mm çarpanı [%95], P(40 mm, kuru)")
    for i in sorted(r["ilceler"], key=lambda x: -x["carpan_10_40"]["log_yagis"]["deger"]):
        c = i["carpan_10_40"]
        print(f"  {i['ilce']:12} günün yağışı ×{c['log_yagis']['deger']} {c['log_yagis'].get('aralik_95')}"
              f"  önceki 7 gün ×{c['log_onceki7g']['deger']} {c['log_onceki7g'].get('aralik_95')}  P40 {i['p_40']:.3f}")
    c = r.get("cok_nokta")
    if not c:
        return
    o, y = c["sonuc"], c["degiskenler"][0]
    print(f"\nÇok noktalı yağışla (k = {r['bant']}): AP {o['ap']:.3f}, "
          f"ΔAP tek noktaya göre {o['ap_farki_tek_noktaya_gore']}, "
          f"duyarlılık {o['duyarlilik']:.2f}, kesinlik {o['kesinlik']:.2f}, "
          f"atak ilk gün {o['atak']['ilk_gun_alarmli']}/{o['atak']['atak']}, "
          f"kıyı {o['kiyi']['yakalanan']}/{o['kiyi']['olay']}")
    tek = {i["ilce"]: i for i in r["ilceler"]}
    print(f"  {'ilçe':12} {'günün yağışı: tek nokta':>32} {'çok nokta':>22}   {'önceki 7 gün: tek':>18} {'çok':>6}")
    for i in sorted(c["ilceler"], key=lambda x: -(x["katsayi"] or {}).get(y, 0)):
        t1 = tek[i["ilce"]]
        print(f"  {i['ilce']:12} {t1['katsayi']['log_yagis']:>8} {str(t1['aralik_95'].get('log_yagis')):>23} "
              f"{i['katsayi'][y]:>7} {str(i['aralik_95'].get(y)):>14}   "
              f"{t1['katsayi']['log_onceki7g']:>18} {i['katsayi']['log_onceki7g']:>6}")


def main():
    gunlugu_kur()
    ek = pd.read_csv(EK_DEGISKENLER_CSV) if os.path.exists(EK_DEGISKENLER_CSV) else None
    if ek is None:
        log.warning("%s yok: çok noktalı sağlamlık sınaması atlanıyor (önce hesap.ek_degiskenler)", EK_DEGISKENLER_CSV)
    sonucu_yaz(GWR_SONUC, calistir(pd.read_csv(ILCE_GUN_CSV), pd.read_csv(ILCE_CSV), ek), yazdir)


if __name__ == "__main__":
    main()
