import bounds


def test_bounds_derived_from_boundary_file():
    b = bounds.load_bounds()
    assert b["lat_min"] < b["lat_max"]
    assert b["lon_min"] < b["lon_max"]


def test_bounds_cover_eastern_districts():
    # Eski hardcoded bbox (27.50°D) Ödemiş/Kiraz/Beydağ'ı dışarıda bırakıyordu;
    # sınır dosyasından türetilen bbox ilin tamamını kapsamalı (Kiraz ~28.20°D).
    assert bounds.BOUNDS["lon_max"] > 28.2
    assert bounds.BOUNDS["lat_max"] > 39.3
    assert bounds.BOUNDS["lat_min"] < 37.9


def test_center_inside_bounds():
    assert bounds.BOUNDS["lat_min"] <= bounds.CENTER_LAT <= bounds.BOUNDS["lat_max"]
    assert bounds.BOUNDS["lon_min"] <= bounds.CENTER_LON <= bounds.BOUNDS["lon_max"]
