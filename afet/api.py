"""İzmir Afet Radar sunucusu: sel senaryosu, günlük sel riski ve tahliye
rotası uçları; arka planda rota maliyetine giren deprem / trafik verisi.

Çalıştırma: `uvicorn afet.api:app`. Arayüz sunucusuz yayın sitesidir
(docs/); bu sunucu yalnız API'dir, kök adres etkileşimli belgeye yönlenir.
HTTP yolları, sorgu parametreleri ve JSON anahtarları istemcilerle
sözleşmedir; değiştirilmez."""
import hashlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from loguru import logger

from afet import ag, canli_veri, gunluk
from afet.sel.risk import en_yogun, katsayi_noktada, risk
from afet.sel.senaryo import senaryolar
from afet.veritabani.baglanti import db
from afet.veritabani.depo import depo
from afet.yollar import IL_SINIRI, ILCE_SINIRLARI


@asynccontextmanager
async def omur(_app: FastAPI):
    gunluk.kur()
    await db.ac()
    canli_veri.baslat()
    logger.success("İzmir Afet Radar API çalışıyor.")
    yield
    await ag.kapat()
    await db.kapat()


app = FastAPI(title="İzmir Afet Radar — Sel ve Tahliye", version="2.0", lifespan=omur)
# Büyük JSON yanıtları (ör. senaryo özetleri) sıkıştırılarak gider
app.add_middleware(GZipMiddleware, minimum_size=2000)


# ── Ortak yanıt yardımcıları ────────────────────────────────────────────────

def _etag_yaniti(request, etag, uret, **kw):
    """Değişmediyse 304 (gövdesiz); değiştiyse uret() ile yanıt. Tarayıcı her
    açılışta doğrular, böylece yeni tahmin / yeniden üretilen dosya hemen görünür."""
    basliklar = {"Cache-Control": "no-cache", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=basliklar)
    return uret(headers=basliklar, **kw)


def _png_yaniti(png, request):
    etag = '"' + hashlib.md5(png).hexdigest() + '"'
    return _etag_yaniti(request, etag, lambda **kw: Response(content=png, media_type="image/png", **kw))


def _dosya_yaniti(yol, request, media_type):
    st = os.stat(yol)
    return _etag_yaniti(request, f'"{st.st_mtime_ns:x}-{st.st_size:x}"',
                        lambda **kw: FileResponse(yol, media_type=media_type, **kw))


def _hazir_degil(neden):
    return {"status": "unavailable", "detail": neden}


def _senaryo_var(p, sure) -> bool:
    return senaryolar.hazir() and senaryolar.gecerli(p, sure)


# ── Kök ve sınırlar ─────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def kok():
    return RedirectResponse("/docs")


@app.get("/api/v1/izmir_ilce")
async def ilce_sinirlari(request: Request):
    return _dosya_yaniti(ILCE_SINIRLARI, request, "application/geo+json")


@app.get("/api/v1/izmir_sinir")
async def il_siniri(request: Request):
    return _dosya_yaniti(IL_SINIRI, request, "application/geo+json")


# ── Rota ────────────────────────────────────────────────────────────────────

@app.get("/api/v1/toplanma_alanlari")
async def toplanma_alanlari():
    """İBB afet ve acil durum toplanma alanları (nokta listesi)."""
    return await depo.toplanma_alanlari()


@app.get("/api/v1/routing/smart")
async def akilli_rota(
    user_lon: float, user_lat: float,
    dest_lon: float = None, dest_lat: float = None,
    severity: float = 1.0,
    mode: str = Query("drive", pattern="^(drive|walk)$"),
    senaryo: str = Query(None, pattern=r"^\d{1,3}_\d{1,2}$",
                         description="Yağış senaryosu '<mm>_<saat>', ör. 50_1: o yağışta "
                                     "su basan yollar kapalı, su altındaki alanlar hedef dışı"),
):
    # Senaryo seçiliyse rota o yağışın su derinliğine göre; değilse yağış
    # bekleniyorsa sel duyarlı yollar cezalandırılır (tahmin alınamazsa ceza yok)
    sel_f, sel_seviye, alt_gecit_dolu = 0.0, None, False
    if senaryo:
        p, sure = map(int, senaryo.split("_"))
        if not _senaryo_var(p, sure):
            return {"status": "error", "message": f"Bilinmeyen yağış senaryosu: {senaryo}"}
        alt_gecit_dolu = senaryolar.alt_gecit_dolu(p, sure)
        senaryo = f"{p}_{sure}"     # baştaki sıfırlar atılır (DB anahtarı)
    elif risk.hazir():
        try:
            yagis = await risk.yagis_durumu(ag.istemci())
            sel_f = katsayi_noktada(yagis, user_lon, user_lat)
            sel_seviye = en_yogun(yagis)["seviye"]
        except Exception as e:
            logger.warning(f"Yağış tahmini alınamadı, rota sel cezasız: {e}")
    sonuc = await depo.akilli_rota(
        lon=user_lon, lat=user_lat, hedef_lon=dest_lon, hedef_lat=dest_lat,
        siddet=severity, mod=mode, sel_f=sel_f,
        senaryo=senaryo, alt_gecit_dolu=alt_gecit_dolu)
    if isinstance(sonuc.get("sel"), dict):
        sonuc["sel"]["il_geneli_seviye"] = sel_seviye
    return sonuc


# ── Sel ─────────────────────────────────────────────────────────────────────

@app.get("/api/v1/sel_riski")
async def sel_riski():
    """Sel/su baskını: arazi duyarlılığı + 24 saatlik yağış tahminine göre günlük risk."""
    if not risk.hazir():
        return _hazir_degil("Duyarlılık hesaplanmadı (hesap/sel_duyarlilik_hesapla.py)")
    try:
        veri = await risk.ozet(ag.istemci())
        veri["alt_gecitler"] = await depo.alt_gecitler()
        return veri
    except Exception as e:
        logger.error(f"Sel riski hesaplanamadı: {e}")
        return {"status": "error", "detail": "Yağış tahmini alınamadı"}


@app.get("/api/v1/sel_riski/harita.png")
async def sel_riski_haritasi(request: Request, tur: str = Query("gunluk", pattern="^(gunluk|duyarlilik)$")):
    if not risk.hazir():
        return Response(status_code=204)
    try:
        png, _ = await risk.harita_png(ag.istemci(), tur)
        return _png_yaniti(png, request)
    except Exception as e:
        logger.error(f"Sel haritası üretilemedi: {e}")
        return Response(status_code=503)


@app.get("/api/v1/sel_senaryo")
async def sel_senaryolari():
    """Kademeli yağış senaryosu: 'X mm yağış Y saatte düşerse' su derinliği özetleri."""
    if not senaryolar.hazir():
        return _hazir_degil("Senaryolar hesaplanmadı (hesap/sel_senaryo_hazirla.py)")
    return senaryolar.yanit()


@app.get("/api/v1/sel_senaryo/toplanma")
async def senaryo_toplanma(p: int = Query(...), sure: int = Query(...)):
    """Senaryoda su altındaki / düz ovadaki toplanma alanları (rota bunları seçmez)."""
    if not _senaryo_var(p, sure):
        return _hazir_degil("Bilinmeyen senaryo")
    return {"status": "ok", "senaryo": f"{p}_{sure}",
            "alanlar": await depo.senaryo_toplanma(f"{p}_{sure}")}


@app.get("/api/v1/sel_senaryo/harita.png")
async def senaryo_haritasi(request: Request, p: int = Query(...), sure: int = Query(...)):
    if not _senaryo_var(p, sure):
        return Response(status_code=404)
    return _png_yaniti(senaryolar.harita_png(p, sure), request)
