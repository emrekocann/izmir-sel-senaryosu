-- İzmir Büyükşehir Belediyesi açık verisi: Afet ve Acil Durum Toplanma Alanları
-- (acikveri.bizizmir.com, İBB Açık Veri Lisansı). load_toplanma_alanlari.py
-- tabloyu kaynaktan baştan doldurur — kaynakta tekil anahtar yok (kod boş /
-- tekrarlı olabiliyor), bu yüzden id yükleme sırasından gelir.
-- drive_vid / walk_vid: alanın en yakın yol ağı düğümü (rota hedefi olarak
-- önceden hesaplanır; yol ağı yoksa NULL kalır).
CREATE TABLE IF NOT EXISTS toplanma_alanlari (
    id          SERIAL PRIMARY KEY,
    kod         TEXT,
    adi         TEXT NOT NULL,
    ilce        TEXT NOT NULL,
    mahalle     TEXT,
    yol         TEXT,
    kapino      TEXT,
    konum       GEOMETRY(Point, 4326) NOT NULL,
    drive_vid   BIGINT,
    walk_vid    BIGINT
);

CREATE INDEX IF NOT EXISTS toplanma_alanlari_konum_idx
    ON toplanma_alanlari USING GIST (konum);
