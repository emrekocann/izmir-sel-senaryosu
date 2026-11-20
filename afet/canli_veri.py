"""Canlı veri toplama döngüleri: tahliye rotasının maliyetine giren son 24
saatin depremleri (Kandilli) ve trafik olayları (TomTom). Paylaşılan HTTP
istemcisini (ag.istemci) kullanır; satırlar veritabanına toplu yazılır."""
import asyncio
import datetime

from loguru import logger

from afet import ag
from afet.ayarlar import ayarlar
from afet.sinir import CERCEVE, cercevede
from afet.veritabani.depo import depo
from afet.veritabani.kayitlar import DepremKaydi, TrafikOlayi

TR_SAATI = datetime.timezone(datetime.timedelta(hours=3))
KANDILLI_URL = "https://api.orhanaydogdu.com.tr/deprem/kandilli/live"
TOMTOM_OLAY_URL = "https://api.tomtom.com/traffic/services/5/incidentDetails"

# TomTom iconCategory → Türkçe kategori (v5 Incident Details)
TOMTOM_KATEGORI = {
    1: "Kaza", 2: "Sis", 3: "Tehlikeli Koşullar", 4: "Yağmur", 5: "Buzlanma",
    6: "Trafik Sıkışıklığı", 7: "Şerit Kapalı", 8: "Yol Kapalı",
    9: "Yol Çalışması", 10: "Rüzgar", 11: "Su Baskını", 14: "Arızalı Araç",
}


def tomtom_kategori_adi(icon_category) -> str:
    try:
        return TOMTOM_KATEGORI.get(int(icon_category), "Diğer")
    except (TypeError, ValueError):
        return "Diğer"


async def depremleri_getir(client):
    r = await client.get(KANDILLI_URL, timeout=10)
    data = r.json()
    if not data.get("status"):
        return
    depremler = []
    # Kandilli listesi günler öncesine uzanır; 24 saati aşanlar zaten
    # temizlikte silinir — yazılıp silinip yeniden yazılmasınlar
    esik = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    for eq in data["result"]:
        lon, lat = eq["geojson"]["coordinates"][:2]
        if not cercevede(lat, lon):
            continue
        # Kandilli date_time Türkiye saatidir (UTC+3)
        try:
            zaman = datetime.datetime.strptime(eq.get("date_time", ""), "%Y-%m-%d %H:%M:%S") \
                .replace(tzinfo=TR_SAATI)
        except ValueError:
            zaman = datetime.datetime.now(datetime.timezone.utc)
        if zaman < esik:
            continue
        depremler.append(DepremKaydi(
            earthquake_id=eq.get("earthquake_id", ""), buyukluk=float(eq["mag"]),
            yer=eq["title"], lat=lat, lon=lon, deprem_zamani=zaman))
    await depo.depremleri_yaz(depremler)


async def trafik_olaylarini_getir(client):
    """TomTom Incident Details v5. API bbox başına ~10.000 km² kabul ettiği
    için il çerçevesi 2x2 çeyreğe bölünerek sorgulanır."""
    b = CERCEVE
    lon_orta, lat_orta = (b["lon_min"] + b["lon_max"]) / 2, (b["lat_min"] + b["lat_max"]) / 2
    ceyrekler = [(lo0, la0, lo1, la1)
                 for lo0, lo1 in ((b["lon_min"], lon_orta), (lon_orta, b["lon_max"]))
                 for la0, la1 in ((b["lat_min"], lat_orta), (lat_orta, b["lat_max"]))]
    fields = ("{incidents{properties{id,iconCategory,magnitudeOfDelay,delay,"
              "events{description}},geometry{type,coordinates}}}")
    olaylar = []
    for bbox in ceyrekler:
        try:
            r = await client.get(TOMTOM_OLAY_URL, params={
                "key": ayarlar.tomtom_api_key, "bbox": ",".join(f"{v:.4f}" for v in bbox),
                "fields": fields, "language": "tr-TR"}, timeout=15)
            r.raise_for_status()
            for inc in r.json().get("incidents", []):
                props = inc.get("properties", {})
                coords = inc.get("geometry", {}).get("coordinates")
                if not coords or not props.get("id"):
                    continue
                nokta = coords[0] if isinstance(coords[0], list) else coords   # LineString → ilk nokta
                aciklama = "; ".join(e["description"] for e in props.get("events") or []
                                     if e.get("description")) or None
                olaylar.append(TrafikOlayi(
                    olay_id=str(props["id"]), kategori=tomtom_kategori_adi(props.get("iconCategory")),
                    aciklama=aciklama, gecikme_sn=props.get("delay"),
                    buyukluk=props.get("magnitudeOfDelay") or 0,
                    lon=float(nokta[0]), lat=float(nokta[1])))
        except Exception as e:
            logger.error(f"TomTom trafik hatası (bbox={bbox}): {e}")
    await depo.trafik_olaylarini_yaz(olaylar)
    await depo.eski_kayitlari_sil(["canli_trafik_olaylari"])
    if olaylar:
        logger.info(f"Trafik: {len(olaylar)} olay güncellendi.")


async def _temizlik(_client):
    await depo.eski_kayitlari_sil()


async def _dongu(ad, is_, aralik_sn, gecikme_sn=0):
    await asyncio.sleep(gecikme_sn)
    while True:
        try:
            await is_(ag.istemci())
        except Exception as e:
            logger.error(f"{ad} döngüsü hatası: {e}")
        await asyncio.sleep(aralik_sn)


# (ad, iş, aralık sn, ilk gecikme sn). Trafik: 4 çeyrek × 144 tur/gün = 576
# istek/gün (TomTom ücretsiz katman 2500 sınırında).
DONGULER = [
    ("Deprem", depremleri_getir, 60, 0),
    ("Trafik", trafik_olaylarini_getir, 600, 5),
    ("Temizlik", _temizlik, 3600, 30),
]

_gorevler = []      # görev referansları (asyncio yalnız zayıf referans tutar)


def baslat():
    """Döngüleri arka plan görevi olarak başlatır (uygulama açılışında)."""
    for ad, is_, aralik, gecikme in DONGULER:
        if is_ is trafik_olaylarini_getir and not ayarlar.tomtom_api_key:
            logger.warning("TOMTOM_API_KEY yok — rota trafik cezasız çalışır.")
            continue
        _gorevler.append(asyncio.create_task(_dongu(ad, is_, aralik, gecikme)))
