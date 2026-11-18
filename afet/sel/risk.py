"""Sel / su baskını — günlük risk (çalışma zamanı).

Arazi duyarlılığı S (hesap/sel_duyarlilik_hesapla.py, 0–1) × yağış katsayısı f
(Open-Meteo saatlik yağış tahmini, 0–1) = günlük risk. Hiçbiri eğitilmiş
model değildir; eşikler aşağıda açıkça yazılıdır.

Yağış katsayısı: önümüzdeki 24 saatin en yüksek SAATLİK yağışı, WMO yağış
şiddeti sınıflarıyla (hafif <2.5, orta <7.6, kuvvetli <50, çok kuvvetli ≥50
mm/sa). 24 saatlik toplam ≥50 mm ise en az "kuvvetli", ≥100 mm ise
"çok kuvvetli" sayılır (proje varsayımı — uzun süreli yağış da taşkın yapar).
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from afet import ag
from afet.izgara import IzgaraKatmani, mercator_satirlari, renkli_png
from afet.onbellek import SureliOnbellek
from afet.yollar import DUYARLILIK

YAGIS_DERECE = 0.25
# (saatlik üst sınır mm, ad, katsayı f)
YAGIS_SEVIYELERI = [
    (0.5, "Yağış yok", 0.0),
    (2.5, "Hafif", 0.15),
    (7.6, "Orta", 0.4),
    (50.0, "Kuvvetli", 0.8),
    (float("inf"), "Çok kuvvetli", 1.0),
]
TOPLAM_ESIK = [(50.0, 0.8), (100.0, 1.0)]       # 24 saat toplamı → en az f
# Harita ve rota için risk/duyarlılık bantları (0–1 değer üzerinde)
BANT_ESIK = [0.3, 0.6, 0.85]
BANTLAR = ["Orta", "Yüksek", "Çok Yüksek"]
BANT_RENK = [(56, 189, 248, 120), (37, 99, 235, 175), (30, 27, 140, 215)]
# Bantların altı (düşük risk): il içi boş görünmesin diye soluk ton
DUSUK_RENK = (186, 214, 236, 110)

def yagis_katsayisi(maks_saatlik, toplam_24):
    """(f, seviye adı) — saatlik şiddet + 24 saat toplamı."""
    for ust, ad, f in YAGIS_SEVIYELERI:
        if maks_saatlik < ust:
            break
    for esik, fmin in TOPLAM_ESIK:
        if toplam_24 >= esik and f < fmin:
            f, ad = fmin, next(a for _, a, k in YAGIS_SEVIYELERI if k == fmin)
    return f, ad


def en_yogun(yagis):
    """İl içi (ya da 0.1° yakını) noktalar arasında en yoğun yağış."""
    il = [p for p in yagis["noktalar"] if p["il"]] or yagis["noktalar"]
    return max(il, key=lambda p: (p["f"], p["maks_saatlik"], p["toplam_24"]))


def _ara_deger(yagis, lat, lon):
    """Yağış katsayısının çift doğrusal (bilinear) değeri; lat ve lon numpy
    yayınıyla (broadcast) birleşir: skaler nokta ya da [:, None] × [None, :] ızgara.
    Izgara dışı kenara kırpılır."""
    lats, lons, F = yagis["lats"], yagis["lons"], yagis["F"]
    fi = np.clip((np.asarray(lat, float) - lats[0]) / YAGIS_DERECE, 0, len(lats) - 1)
    fj = np.clip((np.asarray(lon, float) - lons[0]) / YAGIS_DERECE, 0, len(lons) - 1)
    i0 = np.minimum(fi.astype(int), len(lats) - 2)
    j0 = np.minimum(fj.astype(int), len(lons) - 2)
    di, dj = fi - i0, fj - j0
    return (F[i0, j0] * (1 - di) * (1 - dj) + F[i0 + 1, j0] * di * (1 - dj)
            + F[i0, j0 + 1] * (1 - di) * dj + F[i0 + 1, j0 + 1] * di * dj)


def katsayi_noktada(yagis, lon, lat):
    """Yağış katsayısının (lon, lat)'taki değeri."""
    return float(_ara_deger(yagis, lat, lon))


class SelRiski(IzgaraKatmani):
    """Arazi duyarlılığı ızgarası S (0–255 → 0–1) ve saatlik yağış tahmini.
    Tahmin bir saat önbellekte tutulur; harita görüntüleri tahmin
    yenilenene kadar."""

    def __init__(self, dosya=DUYARLILIK):
        super().__init__(dosya)
        self.dosya = dosya
        self._yagis = SureliOnbellek(3600, "Sel yağış tahmini")
        self._zaman = None                 # PNG'lerin üretildiği tahmin zamanı

    def _yukle(self):
        v = np.load(self.dosya)
        return {"s": v["s"], "bati": float(v["bati"]), "kuzey": float(v["kuzey"]),
                "dx": float(v["dx"]), "dy": float(v["dy"])}

    def cerceve(self):
        s = self.veri
        return s["bati"], s["kuzey"], s["dx"], s["dy"], s["s"].shape

    async def _tahmin(self, client):
        """0.25° düzenli ızgarada saatlik yağış: son 6 saat + önümüzdeki 24 saat."""
        bati, guney, dogu, kuzey = self.sinirlar()
        lats = np.arange(np.floor(guney / YAGIS_DERECE), np.ceil(kuzey / YAGIS_DERECE) + 1) * YAGIS_DERECE
        lons = np.arange(np.floor(bati / YAGIS_DERECE), np.ceil(dogu / YAGIS_DERECE) + 1) * YAGIS_DERECE
        LA, LO = np.meshgrid(lats, lons, indexing="ij")
        veri = await ag.open_meteo(client, LA.ravel(), LO.ravel(), hourly="precipitation",
                                   past_days=1, forecast_days=2, timezone="Europe/Istanbul")

        simdi = datetime.now(ZoneInfo("Europe/Istanbul")).replace(minute=0, second=0, microsecond=0, tzinfo=None)
        F = np.zeros(LA.shape)
        noktalar = []
        for k, nokta in enumerate(veri):
            saat = [datetime.fromisoformat(t) for t in nokta["hourly"]["time"]]
            mm = np.array([v or 0.0 for v in nokta["hourly"]["precipitation"]])
            sonra = np.array([simdi <= t < simdi + timedelta(hours=24) for t in saat])
            once = np.array([simdi - timedelta(hours=6) <= t < simdi for t in saat])
            maks, top = float(mm[sonra].max(initial=0)), float(mm[sonra].sum())
            f, ad = yagis_katsayisi(max(maks, float(mm[once].max(initial=0))), top)
            F.flat[k] = f
            noktalar.append({"lat": float(LA.flat[k]), "lon": float(LO.flat[k]),
                             "il": self.il_icinde(float(LA.flat[k]), float(LO.flat[k])),
                             "maks_saatlik": round(maks, 1), "toplam_24": round(top, 1),
                             "son_6_saat": round(float(mm[once].sum()), 1), "seviye": ad, "f": f})
        return {"lats": lats, "lons": lons, "F": F, "noktalar": noktalar,
                "zaman": simdi.isoformat(timespec="minutes")}

    async def yagis_durumu(self, client):
        return await self._yagis.al(lambda: self._tahmin(client))

    def _katsayi_raster(self, yagis, shape):
        """Duyarlılık ızgarasıyla aynı çerçevede, `shape` çözünürlüğünde katsayı."""
        s = self.veri
        lat = s["kuzey"] + (np.arange(shape[0]) + 0.5) * s["dy"] * (s["s"].shape[0] / shape[0])
        lon = s["bati"] + (np.arange(shape[1]) + 0.5) * s["dx"] * (s["s"].shape[1] / shape[1])
        return _ara_deger(yagis, lat[:, None], lon[None, :])

    def _deger(self, tur, yagis):
        """tur='duyarlilik' → S; 'gunluk' → S × f. 2×2 en büyük ile yarı çözünürlük
        (ince dere yatakları kaybolmasın)."""
        s = self.veri["s"]
        h, w = s.shape[0] // 2 * 2, s.shape[1] // 2 * 2
        v = s[:h, :w].reshape(h // 2, 2, w // 2, 2).max(axis=(1, 3)).astype(np.float32) / 255
        if tur == "gunluk":
            v = v * self._katsayi_raster(yagis, v.shape)
        return v

    def bant_paylari(self, tur, yagis):
        """İl alanının bantlara düşen yüzdesi (tam çözünürlükte; s > 0 = il içi)."""
        s = self.veri["s"]
        il = s > 0
        v = s[il].astype(np.float32) / 255
        if tur == "gunluk":
            v = v * self._katsayi_raster(yagis, s.shape)[il]
        b = np.digitize(v, BANT_ESIK)
        return {ad: round(float((b == k + 1).mean()) * 100, 1) for k, ad in enumerate(BANTLAR)}

    def il_icinde(self, lat, lon, tampon=0.1):
        """Nokta il sınırına `tampon` dereceden yakın mı (duyarlılık maskesinden)."""
        s = self.veri
        r0 = int((lat + tampon - s["kuzey"]) / s["dy"])
        r1 = int((lat - tampon - s["kuzey"]) / s["dy"])
        c0 = int((lon - tampon - s["bati"]) / s["dx"])
        c1 = int((lon + tampon - s["bati"]) / s["dx"])
        h, w = s["s"].shape
        pencere = s["s"][max(r0, 0):min(r1, h), max(c0, 0):min(c1, w)]
        return bool(pencere.size and pencere.max() > 0)

    async def harita_png(self, client, tur):
        """(png, bant payları) — yağış tahmini yenilenene kadar önbellekte."""
        yagis = await self.yagis_durumu(client)
        if self._zaman != yagis["zaman"]:
            self._zaman, self._png = yagis["zaman"], {}
        if tur not in self._png:
            s = self.veri
            # 0 = il dışı, 1 = düşük, 2.. = bantlar (s > 0 il içi; v = 0 yalnız dışarıda)
            sinif = np.where(self._deger("duyarlilik", None) > 0, np.digitize(self._deger(tur, yagis), BANT_ESIK) + 1, 0)
            # Leaflet görüntüyü Mercator'da doğrusal gerer → satırlar Mercator'a
            # (yarı çözünürlük: adım 2·dy; sınırlar tam ızgaranınki)
            b = mercator_satirlari(sinif, s["kuzey"], 2 * s["dy"], guney=self.sinirlar()[1], kat=2)
            self._png[tur] = (renkli_png(b, [DUSUK_RENK] + BANT_RENK), self.bant_paylari(tur, yagis))
        return self._png[tur]

    async def ozet(self, client):
        yagis = await self.yagis_durumu(client)
        _, pay_d = await self.harita_png(client, "duyarlilik")
        _, pay_g = await self.harita_png(client, "gunluk")
        en = en_yogun(yagis)
        return {
            "status": "ok",
            "bounds": self.leaflet_sinirlari(),
            "tahmin_zamani": yagis["zaman"],
            "genel_seviye": en["seviye"], "genel_f": en["f"],
            "en_yogun": en,
            "noktalar": yagis["noktalar"],
            "bantlar": BANTLAR, "bant_esik": BANT_ESIK,
            "alan_payi": {"duyarlilik": pay_d, "gunluk": pay_g},
            "yagis_seviyeleri": [{"ad": ad, "ust_mm_sa": None if ust == float("inf") else ust, "f": f}
                                 for ust, ad, f in YAGIS_SEVIYELERI],
        }


risk = SelRiski()
