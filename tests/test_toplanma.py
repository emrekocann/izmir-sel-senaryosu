def test_satir_coz_gecerli_satir():
    from hesap.toplanma_alanlari_yukle import satir_coz

    row = {"ILCE": "ÇEŞME", "KAPINO": "", "ENLEM": "38.3597", "ACIKLAMA": "3509-024-01",
           "MAHALLE": "ÜNİVERSİTE", "ADI": "1 NO LU AFET VE ACİL DURUM TOPLANMA ALANI",
           "BOYLAM": "26.3096", "YOL": "4261/1 Sk."}
    kod, _, ilce, mahalle, yol, kapino, lon, lat = satir_coz(row)
    assert (kod, ilce, mahalle, yol) == ("3509-024-01", "ÇEŞME", "ÜNİVERSİTE", "4261/1 Sk.")
    assert kapino is None            # boş alanlar NULL olur
    assert (lon, lat) == (26.3096, 38.3597)


def test_satir_coz_gecersiz_koordinat_atlanir():
    from hesap.toplanma_alanlari_yukle import satir_coz

    assert satir_coz({"ENLEM": "", "BOYLAM": "27.1"}) is None
    assert satir_coz({"ENLEM": "abc", "BOYLAM": "27.1"}) is None
    assert satir_coz({"ENLEM": "138.4", "BOYLAM": "27.1"}) is None
    assert satir_coz({}) is None


def test_baglanma_sql_otoyola_baglanmaz():
    from afet.veritabani.depo import AfetDeposu

    sql = AfetDeposu.baglanma_sql("izmir_roads_noded", "ST_SetSRID(ST_Point($1, $2), 4326)")
    for haric in ("motorway", "motorway_link"):
        assert f"'{haric}'" in sql
    assert "izmir_roads_noded_vertices_pgr" in sql


def test_toplanma_alanlari_depoda_var():
    from afet.veritabani.depo import AfetDeposu

    assert callable(getattr(AfetDeposu, "toplanma_alanlari", None))
    assert AfetDeposu.TOPLANMA_ADAY >= 1
