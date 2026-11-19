"""Ek değişkenler: ilçe içinde çok noktalı yağış ve lodos. Sınıflandırmaya katkı var mı?

İki eksiği hedefler (hesap/guvenilirlik.py, README "Güvenilirlik"):
  • Tek yağış noktası: her ilçe için yalnız yapılaşmış alanın ağırlık
    merkezindeki yağış kullanılıyor. Sağanak ilçenin başka köşesine düşünce
    görünmüyor (28 Ekim 2025, Bergama: ilçe içindeki noktalarda 6–58 mm).
    → yagis_max_nokta_mm: ilçe sınırı içindeki 0.1° (~10 km) ızgara noktaları
      ve asıl noktanın günlük yağışlarının en büyüğü.
  • Kıyı taşkını: İzmir'de güneyli kuvvetli rüzgâr (lodos / kıble) deniz suyunu
    körfeze ve yağmur suyu kanallarına iter; Seferihisar, Dikili gibi kıyı
    ilçelerinin olayları çoğu kaçırılıyordu.
    → lodos_kmh: asıl noktada günün en kuvvetli rüzgârı, baskın yön
      LODOS_YON aralığındaysa (güney–güneybatı), değilse 0.
Kaynak: Open-Meteo geçmiş arşivi, günlük (ilce_gun ile aynı kaynak).

Değerlendirme: guvenilirlik ile aynı yıl yıl geriye dönük sınama (2022–26;
her yıl yalnız önceki yıllarla). Dört değişken seti × iki model (lojistik,
gradient boosting). Lojistik her katmanda ızgara aramasıyla ayarlanır;
gradient boosting maliyet yüzünden guvenilirlik.json'daki katman
parametreleriyle (temel sette seçilmiş) eğitilir: yeni değişkenler bu yüzden
hafif dezavantajlıdır. Eşik her katmanda yeniden seçilir. Fark anlamlı mı:
aynı hafta bloklarıyla eşleştirilmiş bootstrap (her tekrarda iki setin AP
farkı); %95 aralık sıfırı içeriyorsa fark kanıtlanmamıştır.

Çıktılar: egitim/ek_degiskenler.csv (ilçe-gün), egitim/ek_degiskenler_sonuc.json
Çalıştırma: venv/bin/python -m hesap.ek_degiskenler   (~5 dk; ilk seferde arşiv iner, kota yüzünden ~30 dk)
"""
import logging
import os
import time
import urllib.parse

import numpy as np
import pandas as pd
import shapely
from sklearn.base import clone
from sklearn.metrics import average_precision_score

from afet import ag
from afet.dosya import json_oku, json_yaz
from afet.yollar import ILCE_SINIRLARI
from hesap import guvenilirlik as gv
from hesap import ols_model as om
from hesap import siniflandirma as sn
from hesap.ilce_gun import ARSIV_URL, CIKTI_DIR, HAM_DIR, ILCE_CSV, ILCE_GUN_CSV, anahtar

log = logging.getLogger("ek_degiskenler")
EK_CSV = os.path.join(CIKTI_DIR, "ek_degiskenler.csv")
SONUC_JSON = os.path.join(CIKTI_DIR, "ek_degiskenler_sonuc.json")
IZGARA = 0.1                      # derece; ERA5-Land / IFS ölçeği
LODOS_YON = (150, 260)            # baskın rüzgâr yönü (derece, nereden estiği): G–GB
BOOTSTRAP = 1000
MODELLER = ["lojistik", "gb"]
YENI_YAGIS = ["yagis_max_nokta_mm"]
SETLER = {"temel": [], "cok_nokta": ["yagis_max_nokta_mm"], "lodos": ["lodos_kmh"],
          "ikisi": ["yagis_max_nokta_mm", "lodos_kmh"]}
LOG_KARSILIK = {"yagis_max_nokta_mm": "log_max_nokta", "lodos_kmh": "lodos_kmh"}   # lojistik için


# ── Veri ────────────────────────────────────────────────────────────────────

def noktalar(ilce_df, geo):
    """İlçe başına yağış noktaları: asıl nokta + sınır içindeki 0.1° ızgara merkezleri."""
    pol = {anahtar(f["properties"]["ILCEADI"]): shapely.geometry.shape(f["geometry"]) for f in geo["features"]}
    satir = []
    for r in ilce_df.itertuples():
        satir.append({"ilce": r.ilce, "lat": round(r.yagis_lat, 4), "lon": round(r.yagis_lon, 4), "ana": True})
        p = pol[anahtar(r.ilce)]
        b = p.bounds
        for x in np.arange(np.floor(b[0] / IZGARA) * IZGARA + IZGARA / 2, b[2], IZGARA):
            for y in np.arange(np.floor(b[1] / IZGARA) * IZGARA + IZGARA / 2, b[3], IZGARA):
                if p.contains(shapely.Point(x, y)):
                    satir.append({"ilce": r.ilce, "lat": round(float(y), 4), "lon": round(float(x), 4), "ana": False})
    return pd.DataFrame(satir)


def _gunluk(nok, b, s, degiskenler, ad):
    """Open-Meteo arşivinden noktaların günlük değişkenleri (tek istek, önbellekli)."""
    q = urllib.parse.urlencode({
        "latitude": ",".join(f"{v:.4f}" for v in nok.lat), "longitude": ",".join(f"{v:.4f}" for v in nok.lon),
        "start_date": b.isoformat(), "end_date": s.isoformat(), "timezone": "Europe/Istanbul",
        "daily": ",".join(degiskenler)})
    veri = ag.json_getir(f"{ARSIV_URL}?{q}", os.path.join(HAM_DIR, f"ek_{ad}_{len(nok)}n_{b}_{s}.json"), timeout=300)
    return veri if isinstance(veri, list) else [veri]


def gunluk_arsiv(nok, bas, bit):
    """Her nokta için günlük yağış; asıl noktalarda ayrıca en kuvvetli rüzgâr ve
    baskın yön. Yıl yıl, önbellekli. İki ayrı istek: Open-Meteo kotası nokta ×
    gün × değişken sayısıyla ölçülür, rüzgâr yalnız asıl noktada gerekir."""
    ana = nok[nok.ana].reset_index(drop=True)
    parcalar = []
    for yil in range(bas.year, bit.year + 1):
        b = max(bas, pd.Timestamp(f"{yil}-01-01").date())
        s = min(bit, pd.Timestamp(f"{yil}-12-31").date())
        yag = _gunluk(nok, b, s, ["precipitation_sum"], "yagis")
        rz = _gunluk(ana, b, s, ["wind_speed_10m_max", "wind_direction_10m_dominant"], "ruzgar")
        yagis = pd.concat([pd.DataFrame({"ilce": n.ilce, "ana": n.ana, "gun": v["daily"]["time"],
                                         "yagis": pd.to_numeric(v["daily"]["precipitation_sum"])})
                           for n, v in zip(nok.itertuples(), yag)])
        ruzgar = pd.concat([pd.DataFrame({"ilce": n.ilce, "ana": True, "gun": v["daily"]["time"],
                                          "ruzgar": pd.to_numeric(v["daily"]["wind_speed_10m_max"]),
                                          "yon": pd.to_numeric(v["daily"]["wind_direction_10m_dominant"])})
                            for n, v in zip(ana.itertuples(), rz)])
        parcalar.append(yagis.merge(ruzgar, on=["ilce", "gun", "ana"], how="left"))
        log.info("Arşiv %d: %s – %s (%d yağış, %d rüzgâr noktası)", yil, b, s, len(nok), len(ana))
    return pd.concat(parcalar, ignore_index=True)


def ozellikler(g):
    """Nokta-gün → ilçe-gün: yagis_max_nokta_mm, lodos_kmh, ruzgar_max_kmh."""
    yag = g.groupby(["ilce", "gun"]).yagis.max().fillna(0).round(1).rename("yagis_max_nokta_mm")
    a = g[g.ana].set_index(["ilce", "gun"])
    lodos = a.yon.between(*LODOS_YON)
    out = pd.concat([yag, a.ruzgar.round(1).rename("ruzgar_max_kmh"),
                     a.ruzgar.where(lodos, 0).fillna(0).round(1).rename("lodos_kmh")], axis=1)
    return out.reset_index()


def birlestir(t, ek):
    """ilce_gun tablosuna ek değişkenler; sınıflandırma kolonları + lojistik karşılıkları."""
    x = sn.hazirla(t.merge(ek, on=["ilce", "gun"], how="left"))
    x["yagis_max_nokta_mm"] = x.yagis_max_nokta_mm.fillna(x.yagis_mm)
    x["lodos_kmh"] = x.lodos_kmh.fillna(0)
    x["log_max_nokta"] = np.log1p(x.yagis_max_nokta_mm)
    return x


# ── Değerlendirme ───────────────────────────────────────────────────────────

def model_tanimi(ad, ek, prm=None):
    """(kurucu, kolonlar, ızgara, açıklama) — sn.ayarla'nın beklediği biçimde."""
    if ad == "lojistik":
        _, kol, izg, ac = sn.MODELLER["lojistik"]
        return (sn._lojistik, kol + [LOG_KARSILIK[k] for k in ek], izg, ac)
    kol = sn.AGAC_OZ + ek
    mono = {k: 1 for k in sn.YAGIS_HAM + [k for k in ek if k in YENI_YAGIS]}
    kur = lambda: sn._gb().set_params(monotonic_cst=mono, **(prm or {}))
    return (kur, kol, {}, sn.MODELLER["gb"][3])


def yil_yil(t, ad, ek, gb_prm, test_yillari=gv.TEST_YILLARI):
    """Her test yılı için (önceki yıllarla) tahmin; birleşik DataFrame(ilce, gun, olay, cagri_su, p, esik)."""
    parcalar = []
    for yil in test_yillari:
        tanim = model_tanimi(ad, ek, gb_prm.get(yil))
        egitim, test = t[t.yil < yil], t[t.yil == yil]
        m, _, _, esik = sn.ayarla(ad, egitim, {ad: tanim})
        m = clone(m).fit(egitim[tanim[1]], egitim.olay)
        parcalar.append(test[["ilce", "gun", "olay", "cagri_su"]].assign(
            p=m.predict_proba(test[tanim[1]])[:, 1], esik=esik))
    return pd.concat(parcalar, ignore_index=True)


def eslesik_fark(a, b, n=BOOTSTRAP, tohum=gv.TOHUM):
    """b − a AP farkı, hafta bloklarıyla eşleştirilmiş bootstrap: [fark, alt, üst]."""
    a = a.sort_values(["gun", "ilce"]).reset_index(drop=True)
    b = b.sort_values(["gun", "ilce"]).reset_index(drop=True)
    hafta = pd.to_datetime(a.gun).dt.strftime("%G-%V").values
    bloklar, ters = np.unique(hafta, return_inverse=True)
    satirlar = [np.flatnonzero(ters == i) for i in range(len(bloklar))]
    y, pa, pb = a.olay.values, a.p.values, b.p.values
    r = np.random.default_rng(tohum)
    farklar = []
    for _ in range(n):
        idx = np.concatenate([satirlar[i] for i in r.integers(0, len(bloklar), len(bloklar))])
        if y[idx].sum():
            farklar.append(average_precision_score(y[idx], pb[idx]) - average_precision_score(y[idx], pa[idx]))
    fark = average_precision_score(y, pb) - average_precision_score(y, pa)
    return [round(float(fark), 3), round(float(np.percentile(farklar, 2.5)), 3), round(float(np.percentile(farklar, 97.5)), 3)]


KIYI = ["Foça", "Dikili", "Seferihisar", "Çeşme", "Urla", "Karaburun", "Konak", "Karşiyaka"]


def kiyi_yakalama(x):
    k = x[x.ilce.isin(KIYI) & (x.olay == 1)]
    return {"olay": int(len(k)), "yakalanan": int((k.p >= k.esik).sum())}


def calistir(t, ek, gb_prm, setler=SETLER, modeller=MODELLER, n=BOOTSTRAP, test_yillari=gv.TEST_YILLARI):
    x = birlestir(t, ek)
    out = {}
    for ad in modeller:
        tahmin, sonuc = {}, {}
        for set_adi, ekler in setler.items():
            s = time.time()
            tahmin[set_adi] = yil_yil(x, ad, ekler, gb_prm, test_yillari)
            o = gv.ozet(tahmin[set_adi], n)
            o["atak"].pop("liste")
            o["kiyi"] = kiyi_yakalama(tahmin[set_adi])
            sonuc[set_adi] = o
            if set_adi != "temel":
                sonuc[set_adi]["ap_farki_temele_gore"] = eslesik_fark(tahmin["temel"], tahmin[set_adi], n)
            log.info("%s / %s (%.0f sn): AP %.3f", ad, set_adi, time.time() - s, o["ap"])
        out[ad] = sonuc
    return {"setler": setler, "lodos_yon": LODOS_YON, "kiyi_ilceler": KIYI, "test_yillari": test_yillari,
            "gb_parametreleri": "guvenilirlik.json katman parametreleri (temel sette seçilmiş)", "sonuclar": out}


def yazdir(r):
    for ad, s in r["sonuclar"].items():
        print(f"\n{ad}:")
        print(f"  {'set':10} {'AP':>6} {'ΔAP [%95]':>22} {'duyarlılık':>10} {'kesinlik':>8} {'atak ilk gün':>12} {'kıyı yakalanan':>15}")
        for k, o in s.items():
            f = o.get("ap_farki_temele_gore")
            print(f"  {k:10} {o['ap']:6.3f} {str(f) if f else '':>22} {o['duyarlilik']:10.2f} {o['kesinlik']:8.2f} "
                  f"{o['atak']['ilk_gun_alarmli']:>5}/{o['atak']['atak']:<6} {o['kiyi']['yakalanan']:>7}/{o['kiyi']['olay']}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    t = pd.read_csv(ILCE_GUN_CSV)
    ilce_df = pd.read_csv(ILCE_CSV)
    nok = noktalar(ilce_df, json_oku(ILCE_SINIRLARI))
    bas = pd.Timestamp(f"{om.ILK_YIL}-01-01").date()
    bit = pd.Timestamp(t.gun.max()).date()
    ek = ozellikler(gunluk_arsiv(nok, bas, bit))
    ek.to_csv(EK_CSV, index=False)
    log.info("Yazıldı: %s (%d satır, %d nokta)", EK_CSV, len(ek), len(nok))
    gb_prm = {k["test_yili"]: k["parametreler"] for k in json_oku(gv.SONUC_JSON)["sonuclar"]["gb"]["katmanlar"]}
    r = calistir(t, ek, gb_prm)
    json_yaz(SONUC_JSON, r, okunur=True)
    yazdir(r)
    print(f"\nYazıldı: {SONUC_JSON}")


if __name__ == "__main__":
    main()
