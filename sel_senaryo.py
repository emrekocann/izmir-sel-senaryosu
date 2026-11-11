"""Kademeli yağış senaryosu (çalışma zamanı): sel_senaryo_hazirla.py'nin
çevrimdışı hesapladığı su derinliklerini harita görüntüsü ve özet olarak sunar."""
import json
import os

import numpy as np

from harita_yardim import izgara_sinirlari, mercator_satirlari, renkli_png

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SENARYO_FILE = os.path.join(BASE_DIR, "sel_model", "senaryo.npz")
OZET_FILE = os.path.join(BASE_DIR, "sel_model", "senaryo_ozet.json")

# Su derinliği sınıfları (m) ve renkleri: sığ / dize kadar / derin / çok derin
DERINLIK_ESIK = [0.1, 0.3, 1.0, 2.0]
DERINLIK_AD = ["Sığ (10–30 cm)", "Diz boyu (30 cm–1 m)", "Derin (1–2 m)", "Çok derin (2 m+)"]
DERINLIK_RENK = [(125, 211, 252, 150), (56, 130, 246, 190), (30, 64, 175, 220), (23, 23, 110, 235)]
BELIRSIZ = 255
BELIRSIZ_AD = "Düz ova: su gelir, derinlik belirsiz"
BELIRSIZ_RENK = (148, 163, 184, 150)

_ozet = None
_npz = None
_png = {}


def hazir() -> bool:
    return os.path.exists(SENARYO_FILE) and os.path.exists(OZET_FILE)


def ozet():
    global _ozet
    if _ozet is None:
        with open(OZET_FILE, encoding="utf-8") as f:
            _ozet = json.load(f)
    return _ozet


def sinirlar():
    o = ozet()
    return izgara_sinirlari(o["bati"], o["kuzey"], o["dx"], o["dy"],
                            _dizi(o["yagis_mm"][0], o["sure_sa"][0]).shape)


def _dizi(p, sure):
    global _npz
    if _npz is None:
        _npz = np.load(SENARYO_FILE)
    return _npz[f"d_{p}_{sure}"]


def gecerli(p, sure) -> bool:
    o = ozet()
    return p in o["yagis_mm"] and sure in o["sure_sa"]


def yanit():
    """Ön yüz için: senaryo listesi, sınırlar, sınıflar ve her senaryonun özeti."""
    o = ozet()
    bati, guney, dogu, kuzey = sinirlar()
    return {
        "status": "ok",
        "yagis_mm": o["yagis_mm"], "sure_sa": o["sure_sa"], "drenaj_mm_sa": o["drenaj_mm_sa"],
        "bounds": [[guney, bati], [kuzey, dogu]],
        "siniflar": [{"ad": ad, "renk": "rgba(%d,%d,%d,%.2f)" % (*r[:3], r[3] / 255)}
                     for ad, r in zip(DERINLIK_AD + [BELIRSIZ_AD], DERINLIK_RENK + [BELIRSIZ_RENK])],
        "il_km2": o["il_km2"],
        "senaryolar": o["senaryolar"],
    }


def harita_png(p, sure):
    """Su derinliği sınıfları (desimetre dizisinden), satırlar Mercator'a."""
    anahtar = (p, sure)
    if anahtar not in _png:
        o = ozet()
        dm = _dizi(p, sure)
        sinif = np.digitize(dm, np.array(DERINLIK_ESIK) * 10)       # 0 = <10 cm (boyanmaz)
        sinif[dm == BELIRSIZ] = len(DERINLIK_RENK) + 1
        b = mercator_satirlari(sinif, o["kuzey"], o["dy"], kat=2)
        _png[anahtar] = renkli_png(b, DERINLIK_RENK + [BELIRSIZ_RENK])
    return _png[anahtar]
