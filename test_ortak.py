"""Ortak yardımcılar: indirme, süreli önbellek, PNG, ara değer, raster örnekleme."""
import asyncio
import io
import json
import urllib.error

import numpy as np
import pytest


class _Yanit(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_getir_yansi_dener_dogrular_ve_onbellekler(tmp_path, monkeypatch):
    import ag
    istenen = []
    yanitlar = [urllib.error.URLError("502"), b"zaman asimi duz metin", b'{"elements": [1, 2]}']

    def sahte_urlopen(req, timeout):
        istenen.append(req.full_url)
        y = yanitlar.pop(0)
        if isinstance(y, Exception):
            raise y
        return _Yanit(y)

    monkeypatch.setattr(ag.urllib.request, "urlopen", sahte_urlopen)
    monkeypatch.setattr(ag.time, "sleep", lambda s: None)
    yol = tmp_path / "x.json"
    assert ag.json_getir(["https://a/", "https://b/"], str(yol), deneme=5) == {"elements": [1, 2]}
    # sırayla yansılar denenir; JSON olmayan 200 yanıtı geçersiz sayılır
    assert istenen == ["https://a/", "https://b/", "https://a/"]
    assert json.loads(yol.read_bytes()) == {"elements": [1, 2]}
    # ikinci çağrı ağa gitmez
    assert ag.json_getir("https://a/", str(yol)) == {"elements": [1, 2]}
    assert len(istenen) == 3


def test_getir_bozuk_onbellegi_yeniler(tmp_path, monkeypatch):
    import ag
    yol = tmp_path / "x.json"
    yol.write_text("{yarim")
    monkeypatch.setattr(ag.urllib.request, "urlopen", lambda req, timeout: _Yanit(b'{"ok": 1}'))
    assert ag.json_getir("https://a/", str(yol)) == {"ok": 1}


def test_getir_vazgecer(monkeypatch):
    import ag

    def hep_hata(req, timeout):
        raise urllib.error.URLError("kapali")

    monkeypatch.setattr(ag.urllib.request, "urlopen", hep_hata)
    monkeypatch.setattr(ag.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        ag.getir("https://a/", deneme=2)


def test_sureli_onbellek_tek_uretim_ve_eski_veri():
    from onbellek import SureliOnbellek

    async def senaryo():
        sayac = {"n": 0}

        async def uret():
            sayac["n"] += 1
            await asyncio.sleep(0.01)
            return sayac["n"]

        o = SureliOnbellek(60)
        # aynı anda gelen istekler tek üretimi paylaşır
        assert await asyncio.gather(*[o.al(uret) for _ in range(10)]) == [1] * 10
        assert sayac["n"] == 1
        o.zaman = 0                                   # süre doldu

        async def bozuk():
            raise RuntimeError("servis kapalı")

        assert await o.al(bozuk, eskiyi_kullan=True) == 1
        with pytest.raises(RuntimeError):
            await o.al(bozuk)

    asyncio.run(senaryo())


def test_renkli_png_saydam_ve_renkler():
    from PIL import Image
    from harita_yardim import renkli_png

    sinif = np.array([[0, 1], [2, 0]], dtype=np.uint8)
    img = Image.open(io.BytesIO(renkli_png(sinif, [(255, 0, 0, 200), (0, 0, 255, 255)])))
    p = np.asarray(img)
    assert p[0, 0, 3] == 0 and p[1, 1, 3] == 0                  # 0 saydam
    assert tuple(p[0, 1]) == (255, 0, 0, 200)
    assert tuple(p[1, 0]) == (0, 0, 255, 255)


def test_ara_deger_bilinear_ve_yayin():
    from sel_riski import YAGIS_DERECE, _ara_deger

    lats = np.array([38.0, 38.0 + YAGIS_DERECE])
    lons = np.array([27.0, 27.0 + YAGIS_DERECE])
    yagis = {"lats": lats, "lons": lons, "F": np.array([[1.0, 2.0], [3.0, 4.0]])}
    orta = _ara_deger(yagis, 38.0 + YAGIS_DERECE / 2, 27.0 + YAGIS_DERECE / 2)
    assert orta == pytest.approx(2.5)
    assert _ara_deger(yagis, 30.0, 20.0) == pytest.approx(1.0)        # dışarısı kenara kırpılır
    izgara = _ara_deger(yagis, lats[:, None], lons[None, :])
    assert np.allclose(izgara, yagis["F"])


def test_raster_ornekle_ve_yakinlik():
    shapely = pytest.importorskip("shapely")          # çevrimdışı hesap bağımlılıkları
    Affine = pytest.importorskip("affine").Affine
    from dem_hidroloji import raster_ornekle, yakin_mi

    tr = Affine(0.1, 0, 27.0, 0, -0.1, 39.0)                  # batı 27, kuzey 39
    s = np.arange(6, dtype=np.float32).reshape(2, 3)
    x = np.array([27.05, 27.25, 26.0])
    y = np.array([38.95, 38.85, 38.95])
    assert raster_ornekle(s, tr, x, y).tolist() == [0, 5, 0]   # ızgara dışı 0
    cizgi = [shapely.LineString([(27.0, 38.95), (27.1, 38.95)])]
    assert yakin_mi(x, y, cizgi, 0.01).tolist() == [True, False, False]
    assert not yakin_mi(x, y, [], 0.01).any()


def test_veritabani_sonradan_acilinca_baglanir(monkeypatch):
    """Açılışta kapalı olan veritabanı açılınca sunucu yeniden başlatılmadan
    bağlanır; kapalıyken her istekte değil, aralıklı denenir."""
    import database

    class SahteHavuz:
        def acquire(self):
            class Baglanti:
                async def __aenter__(self):
                    return "baglanti"

                async def __aexit__(self, *a):
                    return False
            return Baglanti()

    async def senaryo():
        d = database.Database()
        acik = {"durum": False, "deneme": 0}

        async def ac():
            acik["deneme"] += 1
            if not acik["durum"]:
                raise OSError("bağlantı reddedildi")
            d.read_pool = d.write_pool = SahteHavuz()

        monkeypatch.setattr(d, "_havuzlari_ac", ac)
        saat = {"t": 1000.0}
        monkeypatch.setattr(database.time, "monotonic", lambda: saat["t"])

        with pytest.raises(ConnectionError):
            async with d.baglan():
                pass
        with pytest.raises(ConnectionError):          # hemen ardından: yeniden denenmez
            async with d.baglan():
                pass
        assert acik["deneme"] == 1
        acik["durum"] = True
        saat["t"] += database.YENIDEN_DENEME_SN
        async with d.baglan(yazma=True) as conn:
            assert conn == "baglanti"
        assert acik["deneme"] == 2

    asyncio.run(senaryo())
