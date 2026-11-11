"""İzmir Afet Radar sunucusu: sel senaryosu, günlük sel riski ve tahliye
rotası uçları; arka planda rota maliyetine giren deprem / trafik verisi."""
import hashlib
import json
import os
from contextlib import asynccontextmanager

import logging_config  # noqa: F401
from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

import ag
import sel_riski
import sel_senaryo
from bounds import BOUNDS
from database import db
from ingestion import start_ingestion
from repository import AfetRepository

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    start_ingestion()
    logger.success("🚀 İzmir Afet Radar v2.0: sistem aktif.")
    yield
    await ag.kapat()
    await db.disconnect()


app = FastAPI(title="İzmir Afet Radar — Sel ve Tahliye", version="2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
# Büyük JSON yanıtları (ör. senaryo özetleri) sıkıştırılarak gider
app.add_middleware(GZipMiddleware, minimum_size=2000)


@app.middleware("http")
async def _surumlu_varlik(request: Request, call_next):
    """?v=<içerik özeti> taşıyan css/js adresi içerik değişince değişir: tarayıcı
    bir yıl önbellekten kullanır, her açılışta sunucuya sormaz."""
    yanit = await call_next(request)
    if request.url.path.startswith("/static/") and "v" in request.query_params and yanit.status_code == 200:
        yanit.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return yanit


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


def _dosya_yaniti(ad, request, media_type):
    yol = os.path.join(STATIC_DIR, ad)
    st = os.stat(yol)
    return _etag_yaniti(request, f'"{st.st_mtime_ns:x}-{st.st_size:x}"',
                        lambda **kw: FileResponse(yol, media_type=media_type, **kw))


def _hazir_degil(neden):
    return {"status": "unavailable", "detail": neden}


# ── Sayfa ve sınırlar ───────────────────────────────────────────────────────

_sayfa = {"anahtar": None, "html": ""}
_VARLIKLAR = ("index.html", "css/app.css", "js/app.js")


@app.get("/", response_class=HTMLResponse)
async def read_root():
    """index.html bir kez okunur (dosyalar değişince yeniden). İl çerçevesi
    tek kaynaktan (static/izmir_sinir.geojson → bounds.py) yerleştirilir;
    css/js adreslerine içerik özeti eklenir: değişince tarayıcı eskisini kullanmaz."""
    yollar = [os.path.join(STATIC_DIR, a) for a in _VARLIKLAR]
    anahtar = tuple(os.stat(y).st_mtime_ns for y in yollar)
    if _sayfa["anahtar"] != anahtar:
        def ozet(y):
            with open(y, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()[:10]
        with open(yollar[0], encoding="utf-8") as f:
            html = f.read()
        _sayfa["html"] = (html
                          .replace("__SINIR_KUTUSU__", json.dumps({
                              "latMin": BOUNDS["lat_min"], "latMax": BOUNDS["lat_max"],
                              "lonMin": BOUNDS["lon_min"], "lonMax": BOUNDS["lon_max"]}))
                          .replace("__CSS_SURUM__", ozet(yollar[1]))
                          .replace("__JS_SURUM__", ozet(yollar[2])))
        _sayfa["anahtar"] = anahtar
    return _sayfa["html"]


@app.get("/api/v1/izmir_ilce")
async def get_izmir_ilce(request: Request):
    return _dosya_yaniti("izmir_ilce.geojson", request, "application/geo+json")


@app.get("/api/v1/izmir_sinir")
async def get_izmir_sinir(request: Request):
    return _dosya_yaniti("izmir_sinir.geojson", request, "application/geo+json")


# ── Rota ────────────────────────────────────────────────────────────────────

@app.get("/api/v1/toplanma_alanlari")
async def get_toplanma_alanlari():
    """İBB afet ve acil durum toplanma alanları (nokta listesi)."""
    return await AfetRepository.get_toplanma_alanlari()


@app.get("/api/v1/routing/smart")
async def get_smart_routes(
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
        if not sel_senaryo.hazir() or not sel_senaryo.gecerli(p, sure):
            return {"status": "error", "message": f"Bilinmeyen yağış senaryosu: {senaryo}"}
        alt_gecit_dolu = sel_senaryo.ozet()["senaryolar"][f"{p}_{sure}"]["alt_gecit_dolu"] > 0
        senaryo = f"{p}_{sure}"     # baştaki sıfırlar atılır (DB anahtarı)
    elif sel_riski.hazir():
        try:
            yagis = await sel_riski.yagis_durumu(ag.istemci())
            sel_f = sel_riski.katsayi_noktada(yagis, user_lon, user_lat)
            sel_seviye = sel_riski.en_yogun(yagis)["seviye"]
        except Exception as e:
            logger.warning(f"Yağış tahmini alınamadı, rota sel cezasız: {e}")
    sonuc = await AfetRepository.get_smart_routes(
        user_lon=user_lon, user_lat=user_lat, dest_lon=dest_lon, dest_lat=dest_lat,
        severity=severity, mode=mode, sel_f=sel_f,
        senaryo=senaryo, alt_gecit_dolu=alt_gecit_dolu)
    if isinstance(sonuc.get("sel"), dict):
        sonuc["sel"]["il_geneli_seviye"] = sel_seviye
    return sonuc


# ── Sel ───────────────────────────────────────────────────────────────────────

@app.get("/api/v1/sel_riski")
async def get_sel_riski():
    """Sel/su baskını: arazi duyarlılığı + 24 saatlik yağış tahminine göre günlük risk."""
    if not sel_riski.hazir():
        return _hazir_degil("Duyarlılık hesaplanmadı (sel_duyarlilik_hesapla.py)")
    try:
        veri = await sel_riski.ozet(ag.istemci())
        veri["alt_gecitler"] = await AfetRepository.get_alt_gecitler()
        return veri
    except Exception as e:
        logger.error(f"Sel riski hesaplanamadı: {e}")
        return {"status": "error", "detail": "Yağış tahmini alınamadı"}


@app.get("/api/v1/sel_riski/harita.png")
async def get_sel_harita(request: Request, tur: str = Query("gunluk", pattern="^(gunluk|duyarlilik)$")):
    if not sel_riski.hazir():
        return Response(status_code=204)
    try:
        png, _ = await sel_riski.harita_png(ag.istemci(), tur)
        return _png_yaniti(png, request)
    except Exception as e:
        logger.error(f"Sel haritası üretilemedi: {e}")
        return Response(status_code=503)


@app.get("/api/v1/sel_senaryo")
async def get_sel_senaryo():
    """Kademeli yağış senaryosu: 'X mm yağış Y saatte düşerse' su derinliği özetleri."""
    if not sel_senaryo.hazir():
        return _hazir_degil("Senaryolar hesaplanmadı (sel_senaryo_hazirla.py)")
    return sel_senaryo.yanit()


@app.get("/api/v1/sel_senaryo/toplanma")
async def get_sel_senaryo_toplanma(p: int = Query(...), sure: int = Query(...)):
    """Senaryoda su altındaki / düz ovadaki toplanma alanları (rota bunları seçmez)."""
    if not sel_senaryo.hazir() or not sel_senaryo.gecerli(p, sure):
        return _hazir_degil("Bilinmeyen senaryo")
    return {"status": "ok", "senaryo": f"{p}_{sure}",
            "alanlar": await AfetRepository.get_senaryo_toplanma(f"{p}_{sure}")}


@app.get("/api/v1/sel_senaryo/harita.png")
async def get_sel_senaryo_harita(request: Request, p: int = Query(...), sure: int = Query(...)):
    if not sel_senaryo.hazir() or not sel_senaryo.gecerli(p, sure):
        return Response(status_code=404)
    return _png_yaniti(sel_senaryo.harita_png(p, sure), request)
