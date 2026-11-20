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

Çalıştırma: venv/bin/python -m hesap.toplanma_alanlari_yukle
Önkoşul: migrations/005_toplanma_alanlari.sql uygulanmış olmalı.
Başka ile taşırken CSV_URL o ilin toplanma alanı verisiyle değiştirilir.
"""
import csv
import io
import logging

from afet import ag
from afet.veritabani.baglanti import db
from afet.veritabani.depo import AfetDeposu
from hesap import gunlugu_kur

log = logging.getLogger("toplanma")

CSV_URL = ("https://openfiles.izmir.bel.tr/100104/docs/"
           "izbb-afet-ve-acil-durum-toplanma-alanlari.csv")

# Yol ağı düğümünden bu kadar uzak alanlar rota hedefi yapılmaz (metre)
EN_UZAK_BAGLANMA_M = 500


def satir_coz(row):
    """CSV satırını (kod, adi, ilce, mahalle, yol, kapino, lon, lat) yapar;
    koordinatı eksik/geçersizse None döner."""
    try:
        lat, lon = float(row["ENLEM"]), float(row["BOYLAM"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    def temiz(k):
        return (row.get(k) or "").strip() or None

    return (temiz("ACIKLAMA"), temiz("ADI") or "Toplanma Alanı",
            temiz("ILCE") or "", temiz("MAHALLE"), temiz("YOL"),
            temiz("KAPINO"), lon, lat)


def satirlari_indir():
    log.info("Toplanma alanları indiriliyor: %s", CSV_URL)
    text = ag.getir(CSV_URL, deneme=3, timeout=60).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    kayitlar = [r for r in map(satir_coz, rows) if r]
    log.info("%d satır okundu, %d geçerli", len(rows), len(kayitlar))
    return kayitlar


async def main():
    kayitlar = satirlari_indir()
    async with db.oturum():
        async with db.baglan(yazma=True) as conn, conn.transaction():
            await conn.execute("TRUNCATE toplanma_alanlari RESTART IDENTITY")
            await conn.executemany("""
                INSERT INTO toplanma_alanlari
                    (kod, adi, ilce, mahalle, yol, kapino, konum)
                VALUES ($1, $2, $3, $4, $5, $6, ST_SetSRID(ST_Point($7, $8), 4326))
            """, kayitlar)

            # Rota sorgusuyla aynı bağlanma kuralı (otoyola bağlanmaz)
            for mode, (edge_table, _, _) in AfetDeposu.ROTA_MODLARI.items():
                col = f"{mode}_vid"
                if not await conn.fetchval("SELECT to_regclass($1)", edge_table):
                    log.warning("%s yok — %s boş kalır (hesap/yol_agi_kur.py)", edge_table, col)
                    continue
                await conn.execute(f"""
                    UPDATE toplanma_alanlari t
                    SET {col} = {AfetDeposu.baglanma_sql(edge_table, 't.konum')}
                """)
                await conn.execute(f"""
                    UPDATE toplanma_alanlari t SET {col} = NULL
                    FROM {edge_table}_vertices_pgr v
                    WHERE v.id = t.{col}
                      AND NOT ST_DWithin(v.the_geom::geography, t.konum::geography, $1)
                """, EN_UZAK_BAGLANMA_M)
                n = await conn.fetchval(
                    f"SELECT count(*) FROM toplanma_alanlari WHERE {col} IS NOT NULL")
                log.info("%s: %d / %d alan yol ağına bağlandı", col, n, len(kayitlar))


if __name__ == "__main__":
    import asyncio
    gunlugu_kur()
    asyncio.run(main())
