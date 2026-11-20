"""hesap/dem_hidroloji: SRTM karolarının seçimi ve önbelleği (ağa çıkmadan)."""
import shapely

from hesap import dem_hidroloji as dh


def test_dem_karolari_alani_kapsayan_karolari_onbellekten_doner(tmp_path, monkeypatch):
    monkeypatch.setattr(dh, "DEM_KARO_DIR", str(tmp_path))
    for ad in ("N38E026", "N38E027", "N39E026", "N39E027"):
        (tmp_path / f"{ad}.hgt").write_bytes(b"")

    def indirme(*_, **__):
        raise AssertionError("önbellekteki karo indirilmemeli")

    monkeypatch.setattr(dh.ag, "getir", indirme)
    yollar = dh.dem_karolari(shapely.box(26.5, 38.2, 27.4, 39.1))
    assert [p.rsplit("/", 1)[1] for p in yollar] == ["N38E026.hgt", "N38E027.hgt", "N39E026.hgt", "N39E027.hgt"]
