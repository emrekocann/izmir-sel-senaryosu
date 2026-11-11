-- Migration 002: Deprem gerçek zamanı + tekrar önleme
-- Çalıştır: psql -d postgres -f migrations/002_quake_timestamp.sql

-- 1. Gerçek deprem zamanı sütunu
ALTER TABLE canli_deprem_verileri
    ADD COLUMN IF NOT EXISTS deprem_zamani TIMESTAMPTZ;

-- 2. Kandilli earthquake_id — tekrar önlemek için
ALTER TABLE canli_deprem_verileri
    ADD COLUMN IF NOT EXISTS earthquake_id VARCHAR(100);

-- 3. Unique constraint → ON CONFLICT (earthquake_id) DO NOTHING çalışsın.
-- PostgreSQL'de "ADD CONSTRAINT IF NOT EXISTS" yoktur (eski sürüm bu satırda
-- hata veriyordu); tekrar çalıştırılabilir olması için katalog denetlenir.
-- Kısıttan önce aynı kimlikli kopyalar silinir (en eski kayıt kalır).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_deprem_earthquake_id') THEN
        DELETE FROM canli_deprem_verileri a USING canli_deprem_verileri b
        WHERE a.earthquake_id = b.earthquake_id AND a.id > b.id;
        ALTER TABLE canli_deprem_verileri
            ADD CONSTRAINT uq_deprem_earthquake_id UNIQUE (earthquake_id);
    END IF;
END $$;
