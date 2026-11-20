"""Dış servislere erişim — tek yerde.

Çalışma zamanı (FastAPI + veri toplama döngüleri): tüm istekler tek bir
paylaşılan httpx.AsyncClient üzerinden gider. Her istekte yeni istemci açmak
her seferinde yeni TCP/TLS bağlantısı demekti; paylaşılan istemci bağlantıları
havuzda tutar ve aynı anda açık bağlantı sayısını sınırlar.

Çevrimdışı betikler (model eğitimi, sınır, sel hesapları): `getir` yansı
listesi, yeniden deneme, 429 beklemesi, yanıt doğrulama ve dosya önbelleğini
tek fonksiyonda toplar; `open_meteo_arsiv` geçmiş hava verisini (ERA5 arşivi,
geçmiş tahmin koşuları) çok noktalı tek istekle ve önbellekli getirir.
"""
import datetime as dt
import json
import logging
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import httpx

from afet.dosya import atomik_yaz

UA = "izmir-afet-radar/1.5"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARSIV_URL = "https://archive-api.open-meteo.com/v1/archive"                    # ERA5 yeniden analizi
OPEN_METEO_GECMIS_TAHMIN_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"     # eski tahmin koşuları
# Ana Overpass sunucusu sık 502 / kapasite dolu veriyor → sırayla yansılar
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

WORLDCOVER_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                  "ESA_WorldCover_10m_2021_v200_{karo}_Map.tif")

log = logging.getLogger("ag")

# ── Çalışma zamanı: paylaşılan asenkron istemci ─────────────────────────────

class PaylasilanIstemci:
    """Uygulama boyunca tek httpx.AsyncClient: ilk istekte (olay döngüsü içinde)
    açılır, kapatılmışsa yeniden açılır."""

    def __init__(self):
        self._istemci: httpx.AsyncClient | None = None

    def al(self) -> httpx.AsyncClient:
        if self._istemci is None or self._istemci.is_closed:
            self._istemci = httpx.AsyncClient(
                timeout=15.0, follow_redirects=True, headers={"User-Agent": UA},
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20))
        return self._istemci

    async def kapat(self):
        if self._istemci is not None and not self._istemci.is_closed:
            await self._istemci.aclose()


_PAYLASILAN = PaylasilanIstemci()
istemci = _PAYLASILAN.al
kapat = _PAYLASILAN.kapat


async def open_meteo(client, lats, lons, **params) -> list:
    """Open-Meteo'dan çok noktalı tek istek; her nokta için bir yanıt (liste)."""
    r = await client.get(OPEN_METEO_URL, params={
        "latitude": ",".join(f"{float(v):.2f}" for v in lats),
        "longitude": ",".join(f"{float(v):.2f}" for v in lons),
        **params,
    }, timeout=30)
    r.raise_for_status()
    veri = r.json()
    return veri if isinstance(veri, list) else [veri]


# ── Çevrimdışı: yeniden denemeli indirme ────────────────────────────────────

def _onbellekten(yol, dogrula):
    """Önbellek dosyasının gövdesi; dosya yoksa None, bozuksa silinir ve None."""
    if not (yol and os.path.exists(yol)):
        return None
    with open(yol, "rb") as f:
        govde = f.read()
    try:
        if dogrula:
            dogrula(govde)
        return govde
    except Exception:
        log.warning("Bozuk önbellek siliniyor: %s", yol)
        os.remove(yol)
        return None


def bekleme_sn(hata, sira, bekle_sn):
    """sira. başarısız denemeden sonra bekleme: 429 (kota) ise 5 dakika,
    değilse bekle_sn × sira (en çok 2 dakika)."""
    if isinstance(hata, urllib.error.HTTPError) and hata.code == 429:
        return 300
    return min(bekle_sn * sira, 120)


def getir(url, yol=None, veri=None, deneme=6, bekle_sn=10, timeout=300, dogrula=None) -> bytes:
    """url (tek adres ya da sırayla denenecek yansı listesi) gövdesini döner.

    yol verilirse dosya önbelleğidir: geçerli dosya varsa okunur, yoksa
    indirilip atomik yazılır. dogrula(gövde) hata atarsa yanıt (ya da bozuk
    önbellek) geçersiz sayılır — ör. zaman aşımında 200 ile dönen düz metin.
    Hatadan sonra bekleme_sn kadar beklenir. veri: POST gövdesi (bytes)."""
    govde = _onbellekten(yol, dogrula)
    if govde is not None:
        return govde
    adresler = url if isinstance(url, (list, tuple)) else [url]
    for i in range(deneme):
        u = adresler[i % len(adresler)]
        try:
            req = urllib.request.Request(u, data=veri, headers={"User-Agent": UA,
                                                                "Accept": "application/json, */*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                govde = r.read()
            if dogrula:
                dogrula(govde)
            if yol:
                atomik_yaz(yol, govde)
            return govde
        except Exception as e:
            bekle = bekleme_sn(e, i + 1, bekle_sn)
            log.warning("%s: %s — %d sn sonra tekrar (%d/%d)",
                        urllib.parse.urlsplit(u).netloc, str(e)[:100], bekle, i + 1, deneme)
            if i < deneme - 1:
                time.sleep(bekle)
    raise RuntimeError(f"Kaynak yanıt vermedi: {adresler[0]}")


def json_getir(url, yol=None, veri=None, **kw):
    return json.loads(getir(url, yol, veri, dogrula=kw.pop("dogrula", json.loads), **kw))


def yillara_bol(bas, bit):
    """[bas, bit] tarih aralığını takvim yıllarına böler: (yıl, ilk gün, son gün)."""
    for yil in range(bas.year, bit.year + 1):
        yield yil, max(bas, dt.date(yil, 1, 1)), min(bit, dt.date(yil, 12, 31))


def open_meteo_arsiv(url, lats, lons, bas, bit, yol, timeout=180, **params) -> list:
    """Çevrimdışı, çok noktalı tek Open-Meteo isteği (arşiv ya da geçmiş tahmin),
    yol'da önbellekli; her nokta için bir yanıt (liste). Saatler Europe/Istanbul.
    params: hourly / daily değişkenleri, models …"""
    q = urllib.parse.urlencode({
        "latitude": ",".join(f"{float(v):.4f}" for v in lats),
        "longitude": ",".join(f"{float(v):.4f}" for v in lons),
        "start_date": bas.isoformat(), "end_date": bit.isoformat(), "timezone": "Europe/Istanbul", **params})
    veri = json_getir(f"{url}?{q}", yol, timeout=timeout)
    return veri if isinstance(veri, list) else [veri]


def overpass(sorgu, yol=None, **kw) -> list:
    """Overpass sorgusunun öğeleri (yansılar sırayla denenir)."""
    return json_getir(OVERPASS_URLS, yol, urllib.parse.urlencode({"data": sorgu}).encode(), **kw)["elements"]


def worldcover_karolari(bati, guney, dogu, kuzey):
    """Çerçeveyi kapsayan ESA WorldCover 2021 (10 m, 3°×3° karo) karolarını
    sırayla açar: (karo adı, rasterio veri kümesi). Karolar indirilmez; GDAL
    yalnız istenen pencereyi HTTP aralık isteğiyle okur."""
    import rasterio
    adlar = sorted({f"N{la:02d}E{lo:03d}"
                    for la in range(math.floor(guney / 3) * 3, math.ceil(kuzey / 3) * 3, 3)
                    for lo in range(math.floor(bati / 3) * 3, math.ceil(dogu / 3) * 3, 3)})
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4"):
        for ad in adlar:
            with rasterio.open(WORLDCOVER_URL.format(karo=ad)) as ds:
                yield ad, ds
