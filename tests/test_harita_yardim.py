import numpy as np


def test_mercator_satirlari_dogru_enlemi_okur():
    """Görüntü satırı Mercator'da eşit aralıklı; her satır kendi gerçek
    enlemindeki raster satırını taşımalı (kuzeye kayma olmamalı)."""
    from harita_yardim import _merc, mercator_satir_enlemleri, mercator_satirlari

    kuzey, dy, n = 39.4, -0.001, 1600            # ~İzmir: 37.8–39.4°
    dizi = np.arange(n)                           # satır no = değer
    m = mercator_satirlari(dizi, kuzey, dy)
    lat = mercator_satir_enlemleri(kuzey + n * dy, kuzey, n)
    assert (m == np.floor((lat - kuzey) / dy)).all()
    # Leaflet'in doğrusal Mercator gerdirmesiyle satır merkezi gerçek enleme düşer
    y = _merc(kuzey) - (np.arange(n) + 0.5) / n * (_merc(kuzey) - _merc(kuzey + n * dy))
    assert np.allclose(_merc(lat), y)
    # düz enlem dağıtımına göre orta satırlarda belirgin fark (eski hata)
    assert abs(m[n // 2] - n // 2) >= 3
