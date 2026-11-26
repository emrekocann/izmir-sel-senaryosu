"""Senaryoları sel riskine bağlar: "ne sıklıkla?" ve "kimi etkiler?"

Senaryo hesabı (hesap/sel_senaryo_hazirla.py) suyun nereye geldiğini verir.
Risk için iki soru daha gerekir; ikisi de bitmiş derinlik ızgaralarından,
veritabanı olmadan hesaplanır ve docs/veri/risk.json'a yazılır.

1. Ne sıklıkla? — İzmir Güzelyalı (MGM 17220) istasyonunun günlük yağış kaydı
   (NOAA GHCN-Daily, açık). Kaydı tam yıllar (≥ EN_AZ_GUN ölçümlü gün) 1951–59
   ve 2013–24: 21 yıl. Her yılın en yağışlı günü alınır; takvim günü sabit
   aralıktır, kayan 24 saatin en büyüğü ortalama HERSHFIELD kat büyüktür
   (WMO-No. 1045). Bu yıllık en büyükler Gumbel dağılımına L-momentleriyle
   oturtulur (MGM'nin tekerrür analizlerinde kullandığı dağılımlardan biri).
   21 yıl, seyrek olayları kaba bilir: istasyonun 1938'den beri en büyük günlük
   yağışı (145.3 mm, 29 Eylül 2006, MGM; GHCN'de bu yıl eksik) bu eğriye göre
   ~250 yılda birdir, yani eğri kuyruğu hafife alıyor olabilir. Site bu yüzden
   100 yıldan seyrek değerleri sayıyla yazmaz.
   Yalnız günlük kayıt açık olduğu için tekerrür 24 saatlik yağışa göredir.
   1 ve 6 saatlik senaryolarda bu bir ALT SINIRDIR: X mm'nin 6 saatte düşmesi,
   24 saatte düşmesinden daha seyrektir. Saatlik yeniden analiz arşivi (ERA5)
   bunun yerine kullanılamaz: yerel sağanağı kaçırır (2006'da 145 mm yerine 7 mm).

2. Kimi etkiler? — Senaryoda suyun ESIK_DM'den (30 cm) derin olduğu hücrelerde
   yaşayan nüfus, hastane ve okul.
   • Nüfus: İBB Açık Veri, mahalle nüfusları 2023 (TÜİK ADNKS). Hücrelere
     yapılaşmış alanla orantılı dağıtılır (ESA WorldCover, sel_veri/cn_60m_v3.npz).
     TKGM mahalle sınırları kent merkezinde eksiktir (Karşıyaka 19, Çiğli 9
     mahalle); adı eşleşen mahallenin nüfusu kendi sınırına, ilçenin kalanı
     ilçenin eşleşmeyen yapılaşmış alanına dağıtılır.
   • Hastane ve okul: OpenStreetMap (amenity=hospital / school), nokta ya da
     alanın ortası; yalnız il sınırı içindekiler. amenity=hospital etiketlilerin
     üçte biri aile / ağız ve diş sağlığı merkezi, poliklinik, laboratuvardır:
     yalnız adında "hastane" geçenler sayılır. amenity=school etiketli kurslar,
     halk eğitim ve rehberlik merkezleri okul sayılmaz. OSM'de nokta ve alan
     olarak iki kez çizilen tesis bir kez sayılır.
   Düz ovada (su gelir, derinlik belirsiz) yaşayanlar ayrıca sayılır: kıyı
   düzlüklerinde (Karşıyaka, Bayraklı, Çiğli, Bornova) yüz binlerce kişidir.

Çalıştırma: venv/bin/python -m hesap.risk_hazirla
(ilk çalıştırmada istasyon kaydı ve mahalle nüfusu indirilir; OSM'den tesis
çıkarımı ~5 dk sürer, sonra önbellekten okunur)
"""
import logging
import re

import numpy as np
import pandas as pd
import shapely
from affine import Affine
from rasterio.features import rasterize

from afet import ag
from afet.dosya import json_oku, json_yaz
from afet.sel.senaryo import BELIRSIZ, senaryolar
from afet.sinir import il_poligonu, tkgm_ilceler
from afet.yollar import CN_DOSYASI, ISTASYON_YAGIS, MAHALLE_NUFUS, OSM_PBF, OSM_TESISLER, RISK_JSON
from hesap import gunlugu_kur, sonucu_yaz
from hesap.dem_hidroloji import raster_ornekle
from hesap.ilce_gun import anahtar
from hesap.sel_senaryo_hazirla import mahalle_izgara

log = logging.getLogger("risk")

ISTASYON_URL = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/TUM00017220.csv"
NUFUS_URL = ("https://acikveri.bizizmir.com/dataset/133f2cf5-4202-4da7-97cc-7fbfd6365abe/resource/"
             "5b0761ce-e97d-4f0d-bcbe-99ff6b8afc91/download/cinsiyete-gore-mahalle-nufuslari.csv")
EN_AZ_GUN = 330             # yıl, bu kadar günü ölçülmüşse "tam" sayılır
HERSHFIELD = 1.13           # takvim günü → kayan 24 saat
EULER = 0.5772
DONUS_YILLARI = [2, 5, 10, 25, 50, 100]
OLAY_2021 = "2021-02-02"
ESIK_DM = 3                 # 30 cm: araçla geçilemez, yürümek tehlikeli (sel_senaryo_hazirla.YOL_KAPALI_M)
TESISLER = {"hospital": "hastane", "school": "okul"}
# Ad kalıpları anahtar() biçiminde (küçük harf, Türkçe karaktersiz) aranır
HASTANE_ADI = re.compile(r"\bhasta[nh]e|\bhospital")
HASTANE_DEGIL = re.compile(r"sagligi merkezi|poliklinigi")      # ruh / ağız ve diş sağlığı merkezi
OKUL_DEGIL = re.compile(r"\bkursu?\b|\bhalk egitim|\brehberlik ve arastirma")
AYNI_TESIS_M = 300          # aynı adlı (ya da adsız) iki kayıt bu kadar yakınsa aynı tesis
M_DERECE = 111_320


# ── 1. Ne sıklıkla? ─────────────────────────────────────────────────────────

def gunluk_yagis(yol=ISTASYON_YAGIS):
    """İstasyonun günlük yağışı (mm), tarih dizinli. GHCN değerleri mm/10."""
    ag.getir(ISTASYON_URL, yol)
    d = pd.read_csv(yol, usecols=["DATE", "PRCP"], parse_dates=["DATE"]).dropna()
    return d.set_index("DATE").PRCP / 10


def yillik_en_buyuk(gunluk, en_az_gun=EN_AZ_GUN):
    """Kaydı tam yılların en yağışlı günü (mm), kayan 24 saate çevrilmiş."""
    yil = gunluk.groupby(gunluk.index.year)
    tam = yil.size() >= en_az_gun
    return yil.max()[tam] * HERSHFIELD


def gumbel_oturt(x):
    """Gumbel konum ve ölçeği, L-momentleriyle (u, a)."""
    x = np.sort(np.asarray(x, float))
    n = len(x)
    b0 = x.mean()
    b1 = np.sum(np.arange(n) / (n - 1) * x) / n
    a = (2 * b1 - b0) / np.log(2)
    return b0 - EULER * a, a


def donus_suresi(mm, u, a):
    """mm'lik 24 saatlik yağışın ortalama kaç yılda bir aşıldığı."""
    return 1 / (1 - np.exp(-np.exp(-(np.asarray(mm, float) - u) / a)))


def yagis_duzeyi(yil, u, a):
    """yil yılda bir aşılan 24 saatlik yağış (mm)."""
    return u - a * np.log(-np.log(1 - 1 / np.asarray(yil, float)))


def tekerrur():
    gunluk = gunluk_yagis()
    x = yillik_en_buyuk(gunluk)
    u, a = gumbel_oturt(x)
    olay = float(gunluk.get(pd.Timestamp(OLAY_2021), np.nan))
    return {"istasyon": "İzmir Güzelyalı (MGM 17220)", "kaynak": "NOAA GHCN-Daily",
            "yillar": [int(y) for y in x.index], "gumbel": {"u": round(u, 2), "a": round(a, 2)},
            "duzeyler": {str(t): round(float(yagis_duzeyi(t, u, a))) for t in DONUS_YILLARI},
            "olay_2021_mm": olay, "olay_2021_yil": round(float(donus_suresi(olay * HERSHFIELD, u, a)))}


# ── 2. Kimi etkiler? ────────────────────────────────────────────────────────

def ad_anahtari(ad):
    """Mahalle / ilçe adı eşleme anahtarı: harf farkı, "Köyü", boşluk ve noktalama yok sayılır."""
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(mahallesi|koyu)\b", "", anahtar(ad)))


def mahalle_nufuslari(yol=MAHALLE_NUFUS):
    """(ilçe anahtarı, mahalle anahtarı) → nüfus. Gizli ("C") değerler 0."""
    ag.getir(NUFUS_URL, yol)
    d = pd.read_csv(yol, sep=";", dtype=str)
    sayi = sum(pd.to_numeric(d[k], errors="coerce").fillna(0) for k in ("NUFUS_ERKEK_TOPLAM", "NUFUS_KADIN_TOPLAM"))
    return {(ad_anahtari(i), ad_anahtari(m)): float(n) for i, m, n in zip(d.ILCE_ADI, d.MAHALLE_ADI, sayi)}


def nufus_dagit(birim, agirlik, nufus):
    """Her birimin nüfusunu birimin hücrelerine ağırlıkla orantılı dağıtır.
    birim: hücre → birim no (0 = yok); nufus[k]: k. birimin nüfusu.
    Ağırlığı sıfır olan birimin nüfusu hücre sayısına göre dağıtılır."""
    b = birim.ravel()
    toplam_w = np.bincount(b, weights=agirlik.ravel(), minlength=len(nufus))
    adet = np.bincount(b, minlength=len(nufus))
    w = np.where(toplam_w[b] > 0, agirlik.ravel() / np.where(toplam_w > 0, toplam_w, 1)[b],
                 1 / np.maximum(adet, 1)[b])
    return (np.asarray(nufus, float)[b] * w * (b > 0)).reshape(birim.shape)


class Maruziyet:
    """İl ızgarasında hücre başına nüfus ve tesis konumları; senaryo başına etkilenen sayısı."""

    def __init__(self):
        o = senaryolar.ozet()
        self.tr = Affine(o["dx"], 0, o["bati"], 0, o["dy"], o["kuzey"])
        self.shape = senaryolar.dizi(o["yagis_mm"][0], o["sure_sa"][0]).shape
        self.nufus, self.eslesen_pay = self._nufus_izgarasi()
        self.tesisler = tesisleri_ayikla(osm_tesisleri(), il_poligonu())

    def _nufus_izgarasi(self):
        kent = np.load(CN_DOSYASI)["kent"]
        assert kent.shape == self.shape, "arazi ve senaryo ızgarası aynı olmalı"
        lat = self.tr.f + (np.arange(self.shape[0]) + 0.5) * self.tr.e
        hucre_km2 = (abs(self.tr.e) * 111.32) * (self.tr.a * 111.32) * np.cos(np.radians(lat))
        agirlik = kent * hucre_km2[:, None]                     # yapılaşmış alan (km²)
        sayim = mahalle_nufuslari()

        ilceler = tkgm_ilceler()
        ilce_id = rasterize([(g, k + 1) for k, (_, _, g) in enumerate(ilceler)], out_shape=self.shape,
                            transform=self.tr, fill=0, dtype="int32")
        mah_id, mah_adlari = mahalle_izgara(self.tr, self.shape)
        mah_nufus = [0.0] + [sayim.get((ad_anahtari(i), ad_anahtari(m)), 0.0) for i, m in mah_adlari]
        eslesen = np.array(mah_nufus) > 0
        # adı eşleşen mahalleler kendi sınırında
        n_mah = nufus_dagit(np.where(eslesen[mah_id], mah_id, 0), agirlik, mah_nufus)
        # ilçenin kalanı, ilçenin eşleşmeyen kısmında
        ilce_toplam = {}
        for (i, _), n in sayim.items():
            ilce_toplam[i] = ilce_toplam.get(i, 0.0) + n
        kalan = [0.0] + [max(ilce_toplam.get(ad_anahtari(ad), 0.0)
                             - sum(n for (i2, _), n in zip(mah_adlari, mah_nufus[1:]) if i2 == ad), 0.0)
                         for _, ad, _ in ilceler]
        n_ilce = nufus_dagit(np.where(eslesen[mah_id], 0, ilce_id), agirlik, kalan)
        toplam = sum(ilce_toplam.values())
        log.info("Nüfus: %.0f kişi (TÜİK 2023), ızgarada %.0f; mahallesiyle eşleşen %%%.0f",
                 toplam, n_mah.sum() + n_ilce.sum(), 100 * n_mah.sum() / toplam)
        return (n_mah + n_ilce).astype(np.float32), round(float(n_mah.sum() / toplam), 2)

    def senaryo(self, anahtar_):
        d = senaryolar.veri[f"d_{anahtar_}"]
        derin = (d >= ESIK_DM) & (d != BELIRSIZ)
        out = {"nufus": int(round(float(self.nufus[derin].sum()), -2)),
               "nufus_belirsiz": int(round(float(self.nufus[d == BELIRSIZ].sum()), -2))}
        for tur, ad in TESISLER.items():
            t = [x for x in self.tesisler if x["tur"] == tur]
            dd = raster_ornekle(d, self.tr, np.array([x["lon"] for x in t]), np.array([x["lat"] for x in t]))
            sec = (dd >= ESIK_DM) & (dd != BELIRSIZ)
            out[ad] = int(sec.sum())
            if tur == "hospital":
                out["hastane_adlari"] = sorted({t[i]["ad"] for i in np.flatnonzero(sec) if t[i]["ad"]})
        out["toplam"] = {ad: sum(x["tur"] == tur for x in self.tesisler) for tur, ad in TESISLER.items()}
        return out


def tesis_mi(t):
    """OSM kaydı gerçekten hastane / okul mu (ada göre)."""
    ad = anahtar(t["ad"])
    if t["tur"] == "hospital":
        return bool(HASTANE_ADI.search(ad)) and not HASTANE_DEGIL.search(ad)
    return not OKUL_DEGIL.search(ad)


def uzaklik_m(a, b):
    return float(np.hypot((a["lon"] - b["lon"]) * np.cos(np.radians(a["lat"])), a["lat"] - b["lat"]) * M_DERECE)


def tekillestir(tesisler, yakin_m=AYNI_TESIS_M):
    """OSM'de aynı tesis nokta ve alan olarak iki kez çizilebilir: aynı türde,
    adı aynı (ya da biri adsız) ve yakın kayıtlardan yalnız biri kalır, adlısı yeğlenir."""
    kalan = []
    for t in sorted(tesisler, key=lambda t: not t["ad"]):
        if not any(k["tur"] == t["tur"] and (not t["ad"] or anahtar(k["ad"]) == anahtar(t["ad"]))
                   and uzaklik_m(k, t) < yakin_m for k in kalan):
            kalan.append(t)
    return kalan


def tesisleri_ayikla(tesisler, sinir):
    """İl sınırı içindeki gerçek hastane ve okullar, her tesis bir kez."""
    ic = shapely.contains_xy(sinir, np.array([t["lon"] for t in tesisler]), np.array([t["lat"] for t in tesisler]))
    return tekillestir([t for t, i in zip(tesisler, ic) if i and tesis_mi(t)])


def osm_tesisleri(yol=OSM_TESISLER):
    """İl çerçevesindeki ham OSM kayıtları (amenity=hospital / school):
    [{tur, ad, lon, lat}] (önbellekli; ayıklama tesisleri_ayikla'da)."""
    try:
        return json_oku(yol)
    except FileNotFoundError:
        pass
    import osmium
    o = senaryolar.ozet()
    bati, kuzey = o["bati"], o["kuzey"]
    h, w = senaryolar.dizi(o["yagis_mm"][0], o["sure_sa"][0]).shape
    dogu, guney = bati + w * o["dx"], kuzey + h * o["dy"]
    out = []
    fp = osmium.FileProcessor(OSM_PBF).with_locations().with_filter(
        osmium.filter.TagFilter(*[("amenity", t) for t in TESISLER]))
    for e in fp:
        try:
            xy = [(e.location.lon, e.location.lat)] if e.is_node() else (
                [(n.lon, n.lat) for n in e.nodes] if e.is_way() else [])
        except osmium.InvalidLocationError:
            continue
        if not xy:
            continue
        lon, lat = np.mean(xy, axis=0)
        if bati <= lon <= dogu and guney <= lat <= kuzey:
            out.append({"tur": e.tags["amenity"], "ad": e.tags.get("name", ""),
                        "lon": round(float(lon), 6), "lat": round(float(lat), 6)})
    json_yaz(yol, out)
    log.info("OSM: %d hastane, %d okul", *(sum(x["tur"] == t for x in out) for t in TESISLER))
    return out


# ── Çıktı ───────────────────────────────────────────────────────────────────

def hazirla():
    t = tekerrur()
    u, a = t["gumbel"]["u"], t["gumbel"]["a"]
    m = Maruziyet()
    o = senaryolar.ozet()
    sen = {}
    for p in o["yagis_mm"]:
        for s in o["sure_sa"]:
            k = f"{p}_{s}"
            # 24 saatten kısa sürede düşen yağış için 24 saatlik tekerrür alt sınırdır
            sen[k] = {"donus_yil": round(float(donus_suresi(p, u, a)), 1), "alt_sinir": s < 24, **m.senaryo(k)}
    return {"tekerrur": t, "esik_m": ESIK_DM / 10, "nufus_eslesen_pay": m.eslesen_pay, "senaryolar": sen}


def yazdir(r):
    t = r["tekerrur"]
    print(f"{t['istasyon']}: {len(t['yillar'])} yıl; "
          + ", ".join(f"{k} yılda bir {v} mm" for k, v in t["duzeyler"].items()))
    print(f"2 Şubat 2021: {t['olay_2021_mm']} mm → ~{t['olay_2021_yil']} yılda bir")
    for k, s in r["senaryolar"].items():
        print(f"  {k:>7}: {'≥' if s['alt_sinir'] else ' '}{s['donus_yil']:>9.1f} yıl, "
              f"{s['nufus']:>8} kişi (+{s['nufus_belirsiz']} düz ova), {s['hastane']} hastane, {s['okul']} okul")


def main():
    gunlugu_kur()
    sonucu_yaz(RISK_JSON, hazirla(), yazdir)


if __name__ == "__main__":
    main()
