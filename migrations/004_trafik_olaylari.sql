-- TomTom Traffic Incident Details verisi (10 dk'da bir tazelenir).
-- buyukluk = magnitudeOfDelay (0 bilinmiyor .. 4 belirsiz süreli kapanma).
CREATE TABLE IF NOT EXISTS canli_trafik_olaylari (
    olay_id     TEXT PRIMARY KEY,
    kategori    TEXT NOT NULL,
    aciklama    TEXT,
    gecikme_sn  INTEGER,
    buyukluk    SMALLINT NOT NULL DEFAULT 0,
    konum       GEOMETRY(Point, 4326) NOT NULL,
    guncellendi TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS canli_trafik_konum_idx
    ON canli_trafik_olaylari USING GIST (konum);
CREATE INDEX IF NOT EXISTS canli_trafik_guncellendi_idx
    ON canli_trafik_olaylari (guncellendi);
