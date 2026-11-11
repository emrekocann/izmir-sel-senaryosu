import pytest


@pytest.mark.asyncio
async def test_repository_interface_integrity():
    from repository import AfetRepository
    repo = AfetRepository()

    required_methods = [
        'upsert_quakes',
        'upsert_traffic_incidents',
        'temizle_eski_kayitlar',
        'get_toplanma_alanlari',
        'get_alt_gecitler',
        'get_smart_routes',
    ]

    for method in required_methods:
        assert hasattr(repo, method), f"KRİTİK HATA: {method} metodu Repository katmanında eksik!"
        assert callable(getattr(repo, method)), f"HATA: {method} bir fonksiyon olarak tanımlanmamış!"


@pytest.mark.asyncio
async def test_smart_routing_logic_presence():
    from repository import AfetRepository
    import inspect

    sig = inspect.signature(AfetRepository.get_smart_routes)
    params = sig.parameters

    assert 'user_lon' in params
    assert 'user_lat' in params
    assert 'severity' in params

def test_tomtom_kategori_adi():
    from ingestion import tomtom_kategori_adi

    assert tomtom_kategori_adi(1) == "Kaza"
    assert tomtom_kategori_adi(8) == "Yol Kapalı"
    assert tomtom_kategori_adi("6") == "Trafik Sıkışıklığı"
    assert tomtom_kategori_adi(99) == "Diğer"
    assert tomtom_kategori_adi(None) == "Diğer"


def test_traffic_incident_schema_validation():
    import pytest as _pytest
    from schemas import TrafficIncidentCreateRequest

    t = TrafficIncidentCreateRequest(
        olay_id="abc", kategori="Kaza", lat=38.4, lon=27.1)
    assert t.buyukluk == 0 and t.gecikme_sn is None

    with _pytest.raises(Exception):
        TrafficIncidentCreateRequest(
            olay_id="abc", kategori="Kaza", lat=38.4, lon=27.1, buyukluk=7)


def test_route_modes_defined():
    from repository import AfetRepository

    assert set(AfetRepository.ROUTE_MODES) == {"drive", "walk"}
    drive_table, drive_slope, drive_trafik = AfetRepository.ROUTE_MODES["drive"]
    walk_table, walk_slope, walk_trafik = AfetRepository.ROUTE_MODES["walk"]
    assert drive_table != walk_table
    assert walk_slope > drive_slope      # yaya eğime daha duyarlı
    assert drive_trafik and not walk_trafik  # trafik cezası yalnızca araçta
