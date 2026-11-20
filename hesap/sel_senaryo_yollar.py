"""Yağış senaryosundaki suyu yollara ve toplanma alanlarına yazar.

Tahliye rotası seçilen senaryoda su basan yoldan kaçsın, su altındaki
toplanma alanını hedef seçmesin diye her senaryonun derinlik ızgarası
(sel_model/senaryo.npz) araç ve yaya yol ağının kenarlarında ve toplanma
alanlarının konumunda örneklenir:

  • Kenar ~25 m'de bir örneklenir (hesap/sel_duyarlilik_hesapla.py ile aynı
    noktalar); kenarın derinliği örneklerin EN BÜYÜĞÜDÜR — yolun tek bir
    noktası suyun altındaysa o yoldan geçilemez.
  • Köprü ve uzun tünel üstündeki noktalar sayılmaz (su altından geçer).
  • Düz ovada "derinlik belirsiz" (gri) hücreye değen kenar belirsiz işaretlenir.
  • Yalnız derinlik ≥ 0.1 m ya da belirsiz olanlar yazılır (migrations/011).

Çalıştırma: venv/bin/python -m hesap.sel_senaryo_yollar
(hesap/sel_senaryo_hazirla.py sonunda kendisi çağırır; yol ağı ya da toplanma
alanları yeniden yüklenirse bu betik tek başına çalıştırılır, ~2 dk.)
Önkoşul: migrations/011_sel_senaryo_su.sql, sel_model/senaryo.npz, DB açık.
"""
import asyncio
import logging
import time

import numpy as np
from affine import Affine

from afet.dosya import json_oku
from afet.sel.senaryo import BELIRSIZ
from afet.sinir import il_poligonu
from afet.veritabani.baglanti import db
from afet.yollar import SENARYO, SENARYO_OZETI
from hesap import gunlugu_kur
from hesap.dem_hidroloji import kopru_tunel, raster_ornekle, yakin_mi, yol_noktalari

log = logging.getLogger("sel")

YAZ_ESIK_M = 0.1                 # bunun altı "kuru" sayılır, yazılmaz
KOPRU_TAMPON = 0.00012           # ~12 m (hesap/sel_duyarlilik_hesapla.py ile aynı)
YOL_TABLOLARI = {"drive": "izmir_roads_noded", "walk": "izmir_yaya_noded"}


def kenar_derinligi(dm, ki, kenar_sayisi, haric=None):
    """Örnek noktalardaki desimetre değerinden kenar başına (en büyük derinlik
    m, belirsiz mi). ki sıralıdır (shapely.get_coordinates) ve her kenarın en
    az bir noktası vardır; haric noktalar (köprü) kuru sayılır."""
    belirsiz = dm == BELIRSIZ
    d = np.where(belirsiz, 0, dm) / 10.0
    if haric is not None:
        d[haric] = 0
        belirsiz &= ~haric
    bas = np.r_[0, np.flatnonzero(np.diff(ki)) + 1]
    if len(bas) != kenar_sayisi:
        raise ValueError(f"örneksiz kenar var: {kenar_sayisi} kenar, {len(bas)} örnekli")
    return np.maximum.reduceat(d, bas), np.logical_or.reduceat(belirsiz, bas)


def satirlar(katman, senaryo, kimlikler, derinlik, belirsiz):
    """Yazılacak (ıslak ya da belirsiz) satırlar."""
    sec = (derinlik >= YAZ_ESIK_M) | belirsiz
    return [(katman, senaryo, int(k), round(float(d), 1), bool(b))
            for k, d, b in zip(kimlikler[sec], derinlik[sec], belirsiz[sec])]


async def yaz():
    ozet = json_oku(SENARYO_OZETI)
    tr = Affine(ozet["dx"], 0, ozet["bati"], 0, ozet["dy"], ozet["kuzey"])
    senaryo_npz = np.load(SENARYO)
    senaryolar = sorted(k[2:] for k in senaryo_npz.files if k.startswith("d_"))
    kopru, _, uzun_tunel = kopru_tunel(il_poligonu())

    async with db.oturum():
        async with db.baglan(yazma=True) as conn:
            for katman, tablo in YOL_TABLOLARI.items():
                t = time.time()
                rows = await conn.fetch(f"SELECT id, ST_AsBinary(the_geom) AS wkb FROM {tablo} ORDER BY id")
                ids = np.array([r["id"] for r in rows], dtype=np.int64)
                _, x, y, ki = yol_noktalari([r["wkb"] for r in rows])
                del rows
                koprude = yakin_mi(x, y, kopru + uzun_tunel, KOPRU_TAMPON)
                kayit = []
                for s in senaryolar:
                    d, b = kenar_derinligi(raster_ornekle(senaryo_npz[f"d_{s}"], tr, x, y),
                                           ki, len(ids), koprude)
                    kayit += satirlar(katman, s, ids, d, b)
                await _degistir(conn, katman, kayit, len(senaryolar))
                log.info("%s: %d kenar × %d senaryo → %d ıslak/belirsiz satır — %.0f sn",
                         katman, len(ids), len(senaryolar), len(kayit), time.time() - t)

            alanlar = await conn.fetch("SELECT id, ST_X(konum) AS lon, ST_Y(konum) AS lat "
                                       "FROM toplanma_alanlari ORDER BY id")
            ids = np.array([a["id"] for a in alanlar], dtype=np.int64)
            ax = np.array([a["lon"] for a in alanlar])
            ay = np.array([a["lat"] for a in alanlar])
            kayit = []
            for s in senaryolar:
                dm = raster_ornekle(senaryo_npz[f"d_{s}"], tr, ax, ay)
                b = dm == BELIRSIZ
                kayit += satirlar("toplanma", s, ids, np.where(b, 0, dm) / 10.0, b)
            await _degistir(conn, "toplanma", kayit, len(senaryolar))
            log.info("toplanma: %d alan × %d senaryo → %d ıslak/belirsiz satır",
                     len(ids), len(senaryolar), len(kayit))


async def _degistir(conn, katman, kayit, senaryo_sayisi):
    """Katmanın eski satırlarını tek işlemde yenileriyle değiştirir."""
    async with conn.transaction():
        await conn.execute("DELETE FROM sel_senaryo_su WHERE katman = $1", katman)
        await conn.copy_records_to_table(
            "sel_senaryo_su", records=kayit,
            columns=["katman", "senaryo", "kimlik", "derinlik", "belirsiz"])
        await conn.execute("""INSERT INTO sel_senaryo_yazim (katman, senaryo_sayisi) VALUES ($1, $2)
                              ON CONFLICT (katman) DO UPDATE
                              SET yazildi = now(), senaryo_sayisi = EXCLUDED.senaryo_sayisi""",
                           katman, senaryo_sayisi)
    await conn.execute("ANALYZE sel_senaryo_su")


if __name__ == "__main__":
    gunlugu_kur()
    asyncio.run(yaz())
