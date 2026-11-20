import pytest
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_depo_arayuzu():
    from afet.veritabani.depo import depo

    for metot in ("depremleri_yaz", "trafik_olaylarini_yaz", "eski_kayitlari_sil",
                  "toplanma_alanlari", "senaryo_toplanma", "alt_gecitler", "akilli_rota"):
        assert callable(getattr(depo, metot, None)), f"{metot} depo katmanında eksik"


@pytest.mark.asyncio
async def test_akilli_rota_imzasi():
    import inspect
    from afet.veritabani.depo import AfetDeposu

    sig = inspect.signature(AfetDeposu.akilli_rota)
    params = sig.parameters

    assert {"lon", "lat", "hedef_lon", "hedef_lat", "siddet", "mod", "senaryo"} <= set(params)

def test_tomtom_kategori_adi():
    from afet.canli_veri import tomtom_kategori_adi

    assert tomtom_kategori_adi(1) == "Kaza"
    assert tomtom_kategori_adi(8) == "Yol Kapalı"
    assert tomtom_kategori_adi("6") == "Trafik Sıkışıklığı"
    assert tomtom_kategori_adi(99) == "Diğer"
    assert tomtom_kategori_adi(None) == "Diğer"


def test_trafik_olayi_dogrulama():
    from afet.veritabani.kayitlar import TrafikOlayi

    t = TrafikOlayi(
        olay_id="abc", kategori="Kaza", lat=38.4, lon=27.1)
    assert t.buyukluk == 0 and t.gecikme_sn is None

    with pytest.raises(ValidationError):
        TrafikOlayi(
            olay_id="abc", kategori="Kaza", lat=38.4, lon=27.1, buyukluk=7)


def test_rota_modlari():
    from afet.veritabani.depo import AfetDeposu

    assert set(AfetDeposu.ROTA_MODLARI) == {"drive", "walk"}
    drive_table, drive_slope, drive_trafik = AfetDeposu.ROTA_MODLARI["drive"]
    walk_table, walk_slope, walk_trafik = AfetDeposu.ROTA_MODLARI["walk"]
    assert drive_table != walk_table
    assert walk_slope > drive_slope      # yaya eğime daha duyarlı
    assert drive_trafik and not walk_trafik  # trafik cezası yalnızca araçta
