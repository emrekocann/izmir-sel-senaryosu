def test_parse_row_gecerli_satir():
    from load_toplanma_alanlari import parse_row

    row = {"ILCE": "ÇEŞME", "KAPINO": "", "ENLEM": "38.3597", "ACIKLAMA": "3509-024-01",
           "MAHALLE": "ÜNİVERSİTE", "ADI": "1 NO LU AFET VE ACİL DURUM TOPLANMA ALANI",
           "BOYLAM": "26.3096", "YOL": "4261/1 Sk."}
    kod, adi, ilce, mahalle, yol, kapino, lon, lat = parse_row(row)
    assert (kod, ilce, mahalle, yol) == ("3509-024-01", "ÇEŞME", "ÜNİVERSİTE", "4261/1 Sk.")
    assert kapino is None            # boş alanlar NULL olur
    assert (lon, lat) == (26.3096, 38.3597)


def test_parse_row_gecersiz_koordinat_atlanir():
    from load_toplanma_alanlari import parse_row

    assert parse_row({"ENLEM": "", "BOYLAM": "27.1"}) is None
    assert parse_row({"ENLEM": "abc", "BOYLAM": "27.1"}) is None
    assert parse_row({"ENLEM": "138.4", "BOYLAM": "27.1"}) is None
    assert parse_row({}) is None


def test_snap_sql_otoyola_baglanmaz():
    from repository import AfetRepository

    sql = AfetRepository.snap_sql("izmir_roads_noded", "ST_SetSRID(ST_Point($1, $2), 4326)")
    for haric in ("motorway", "motorway_link"):
        assert f"'{haric}'" in sql
    assert "izmir_roads_noded_vertices_pgr" in sql


def test_toplanma_endpoint_repository_metodu_var():
    from repository import AfetRepository

    assert callable(getattr(AfetRepository, "get_toplanma_alanlari", None))
    assert AfetRepository.TOPLANMA_ADAY >= 1
