"""İBB açık verisinden afet ve acil durum toplanma alanlarını yükler.

Kaynak: İzmir Büyükşehir Belediyesi Açık Veri Portalı —
"Afet ve Acil Durum Toplanma Alanları" (İBB Açık Veri Lisansı).

Akış:
  1. CSV İBB sunucusundan indirilir (; ayraçlı, UTF-8 BOM'lu).
  2. Koordinatı geçersiz satırlar atlanır; toplanma_alanlari tablosu
     baştan doldurulur (kaynakta tekil anahtar yok).
  3. Yol ağı tabloları varsa her alanın en yakın araç ve yaya düğümü
     (drive_vid / walk_vid) önceden hesaplanır — rota sorgusu bunları
     hedef olarak kullanır.

Çalıştırma: venv/bin/python load_toplanma_alanlari.py
Önkoşul: migrations/005_toplanma_alanlari.sql uygulanmış olmalı.
Başka ile taşırken CSV_URL o ilin toplanma alanı verisiyle değiştirilir.
"""
import csv
import io
import logging

import ag
from database import db
from repository import AfetRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("toplanma")

CSV_URL = ("https://openfiles.izmir.bel.tr/100104/docs/"
           "izbb-afet-ve-acil-durum-toplanma-alanlari.csv")

# Yol ağı düğümünden bu kadar uzak alanlar rota hedefi yapılmaz (metre)
MAX_SNAP_M = 500


def parse_row(row):
    """CSV satırını (kod, adi, ilce, mahalle, yol, kapino, lon, lat) yapar;
    koordinatı eksik/geçersizse None döner."""
    try:
        lat, lon = float(row["ENLEM"]), float(row["BOYLAM"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    clean = lambda k: (row.get(k) or "").strip() or None
    return (clean("ACIKLAMA"), clean("ADI") or "Toplanma Alanı",
            clean("ILCE") or "", clean("MAHALLE"), clean("YOL"),
            clean("KAPINO"), lon, lat)


def download_rows():
    log.info("Toplanma alanları indiriliyor: %s", CSV_URL)
    text = ag.getir(CSV_URL, deneme=3, timeout=60).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    records = [r for r in map(parse_row, rows) if r]
    log.info("%d satır okundu, %d geçerli", len(rows), len(records))
    return records


async def main():
    records = download_rows()
    await db.connect()
    try:
        async with db.write_pool.acquire() as conn, conn.transaction():
            await conn.execute("TRUNCATE toplanma_alanlari RESTART IDENTITY")
            await conn.executemany("""
                INSERT INTO toplanma_alanlari
                    (kod, adi, ilce, mahalle, yol, kapino, konum)
                VALUES ($1, $2, $3, $4, $5, $6, ST_SetSRID(ST_Point($7, $8), 4326))
            """, records)

            # Rota sorgusuyla aynı bağlanma kuralı (otoyola bağlanmaz)
            for mode, (edge_table, _, _) in AfetRepository.ROUTE_MODES.items():
                col = f"{mode}_vid"
                if not await conn.fetchval("SELECT to_regclass($1)", edge_table):
                    log.warning("%s yok — %s boş kalır (build_road_network.py)", edge_table, col)
                    continue
                await conn.execute(f"""
                    UPDATE toplanma_alanlari t
                    SET {col} = {AfetRepository.snap_sql(edge_table, 't.konum')}
                """)
                await conn.execute(f"""
                    UPDATE toplanma_alanlari t SET {col} = NULL
                    FROM {edge_table}_vertices_pgr v
                    WHERE v.id = t.{col}
                      AND NOT ST_DWithin(v.the_geom::geography, t.konum::geography, $1)
                """, MAX_SNAP_M)
                n = await conn.fetchval(
                    f"SELECT count(*) FROM toplanma_alanlari WHERE {col} IS NOT NULL")
                log.info("%s: %d / %d alan yol ağına bağlandı", col, n, len(records))
    finally:
        await db.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
