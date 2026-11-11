-- Migration 003: Temel şema + mekânsal (GIST) ve zaman indeksleri
-- Bugüne kadar tablolar elle oluşturulmuştu; bu migration şemayı repoda
-- resmileştirir. Mevcut veritabanında güvenle tekrar çalıştırılabilir.
-- (Sadeleştirmeyle kaldırılan canlı tablolar burada yok; eski
-- veritabanlarında 010_sadelestirme.sql siler.)
-- Çalıştır: psql -d <veritabanı> -f migrations/003_baseline_schema.sql

CREATE EXTENSION IF NOT EXISTS postgis;

-- ─── Tablolar ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS canli_deprem_verileri (
    id            SERIAL PRIMARY KEY,
    earthquake_id VARCHAR(100),
    buyukluk      FLOAT NOT NULL,
    yer           VARCHAR(255) NOT NULL,
    konum         GEOMETRY(Point, 4326) NOT NULL,
    deprem_zamani TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- earthquake_id üzerinde unique constraint (ON CONFLICT için) — idempotent
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_deprem_earthquake_id'
    ) THEN
        ALTER TABLE canli_deprem_verileri
            ADD CONSTRAINT uq_deprem_earthquake_id UNIQUE (earthquake_id);
    END IF;
END $$;

-- ─── Mekânsal indeksler (GIST) ──────────────────────────────

CREATE INDEX IF NOT EXISTS idx_deprem_konum_gist   ON canli_deprem_verileri USING GIST (konum);

-- ─── Zaman indeksleri (son-24-saat sorguları için) ──────────

CREATE INDEX IF NOT EXISTS idx_deprem_zamani  ON canli_deprem_verileri (deprem_zamani DESC);
