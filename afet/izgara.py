"""Izgara (raster) katmanları ve harita görüntüleri için ortak yardımcılar.

Leaflet L.imageOverlay görüntüyü iki köşesinden Web Mercator'da DOĞRUSAL
gerer. Raster ise eşit ENLEM aralıklıdır; satırları olduğu gibi vermek,
İzmir enlem aralığının (~1.6–1.9°) ortasında görüntüyü ~0.5 km kuzeye
kaydırır. Bu yüzden görüntünün her satırı Mercator'da eşit aralıklı seçilir
ve o satırın gerçek enlemindeki raster satırı okunur.
"""
import os

import numpy as np


def mercator_y(lat):
    """Enlemin (derece) Web Mercator y koordinatı (birim küre üzerinde)."""
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def mercator_satir_enlemleri(guney, kuzey, n):
    """Mercator'da eşit aralıklı n satırın (üstten alta) merkez enlemleri."""
    y = mercator_y(kuzey) - (np.arange(n) + 0.5) / n * (mercator_y(kuzey) - mercator_y(guney))
    return np.degrees(2 * np.arctan(np.exp(y)) - np.pi / 2)


def sinira_degen(sinir, lon, lat, dx, dy):
    """Hücre merkezi (lon, lat) il içinde YA DA hücre sınıra değiyor: merkezi
    sınırın yarım köşegen kadar dışına kadar olan hücreler. Görüntü tarayıcıda
    il poligonuyla kırpıldığından kıyı/sınır şeridinde boşluk kalmaz."""
    import shapely
    pay = 0.5 * float(np.hypot(dx, dy))
    return shapely.contains_xy(sinir.buffer(pay), lon, lat)


def mercator_satirlari(dizi, kuzey, dy, guney=None, kat=1):
    """Eşit enlem aralıklı (satır 0 = kuzey, adım dy < 0) diziyi Mercator
    satırlarına yeniden örnekler (en yakın satır). Satır kenarları kaynakla
    örtüşmediğinden ince şeritlerde bir satırlık sapma olur; kat=2 satır
    sayısını ikiye katlayıp bu sapmayı yarıya indirir."""
    n = dizi.shape[0]
    guney = kuzey + n * dy if guney is None else guney
    lat = mercator_satir_enlemleri(guney, kuzey, n * kat)
    kaynak = np.clip(np.floor((lat - kuzey) / dy).astype(int), 0, n - 1)
    return dizi[kaynak]


def hucre_merkezleri(tr, shape):
    """Affine dönüşümlü ızgaranın hücre merkezleri: (lon, lat) dizileri."""
    rr, cc = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing="ij")
    return tr.c + (cc + 0.5) * tr.a, tr.f + (rr + 0.5) * tr.e


def izgara_sinirlari(bati, kuzey, dx, dy, shape):
    """(batı, güney, doğu, kuzey) — satır 0 kuzeyde, dy < 0."""
    h, w = shape
    return bati, kuzey + h * dy, bati + w * dx, kuzey


def renkli_png(sinif, renkler) -> bytes:
    """Sınıf dizisini PNG'ye çevirir: 0 saydam, k → renkler[k-1] (RGBA)."""
    import io
    from PIL import Image
    tablo = np.zeros((256, 4), dtype=np.uint8)
    tablo[1:len(renkler) + 1] = renkler
    buf = io.BytesIO()
    Image.fromarray(tablo[np.asarray(sinif, dtype=np.uint8)], "RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


class IzgaraKatmani:
    """Çevrimdışı üretilmiş bir ızgara dosyasının çalışma zamanı katmanı.

    Dosya ilk erişimde bir kez yüklenir (`veri`); çerçeve, Leaflet sınırları
    ve üretilen PNG'lerin önbelleği bütün katmanlarda ortaktır. Alt sınıf
    `_yukle()` ile veriyi okur ve `cerceve()` ile ızgaranın batı ve kuzey
    kenarını, hücre adımlarını ve boyutunu verir."""

    def __init__(self, *dosyalar):
        self.dosyalar = dosyalar
        self._veri = None
        self._png = {}

    def hazir(self) -> bool:
        """Katmanın dosyaları üretilmiş mi?"""
        return all(os.path.exists(d) for d in self.dosyalar)

    @property
    def veri(self):
        if self._veri is None:
            self._veri = self._yukle()
        return self._veri

    def _yukle(self):
        raise NotImplementedError

    def cerceve(self):
        """(batı, kuzey, dx, dy, (satır, sütun))."""
        raise NotImplementedError

    def sinirlar(self):
        """(batı, güney, doğu, kuzey)."""
        return izgara_sinirlari(*self.cerceve())

    def leaflet_sinirlari(self):
        """L.imageOverlay sınırı: [[güney, batı], [kuzey, doğu]]."""
        bati, guney, dogu, kuzey = self.sinirlar()
        return [[guney, bati], [kuzey, dogu]]

    def _onbellekli_png(self, anahtar, uret):
        if anahtar not in self._png:
            self._png[anahtar] = uret()
        return self._png[anahtar]
