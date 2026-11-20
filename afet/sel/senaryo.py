"""Kademeli yağış senaryosu (çalışma zamanı): hesap/sel_senaryo_hazirla.py'nin
çevrimdışı hesapladığı su derinliklerini harita görüntüsü ve özet olarak sunar."""
import numpy as np

from afet.dosya import json_oku
from afet.izgara import IzgaraKatmani, mercator_satirlari, renkli_png
from afet.yollar import SENARYO, SENARYO_OZETI

# Su derinliği sınıfları (m) ve renkleri: sığ / dize kadar / derin / çok derin
DERINLIK_ESIK = [0.1, 0.3, 1.0, 2.0]
DERINLIK_AD = ["Sığ (10–30 cm)", "Diz boyu (30 cm–1 m)", "Derin (1–2 m)", "Çok derin (2 m+)"]
DERINLIK_RENK = [(125, 211, 252, 150), (56, 130, 246, 190), (30, 64, 175, 220), (23, 23, 110, 235)]
BELIRSIZ = 255
BELIRSIZ_AD = "Düz ova: su gelir, derinlik belirsiz"
BELIRSIZ_RENK = (148, 163, 184, 150)


class SelSenaryolari(IzgaraKatmani):
    """Her (yağış mm, süre sa) senaryosunun su derinliği ızgarası (desimetre,
    BELIRSIZ = düz ova) ve senaryo özeti."""

    def __init__(self, dizi_dosyasi=SENARYO, ozet_dosyasi=SENARYO_OZETI):
        super().__init__(dizi_dosyasi, ozet_dosyasi)
        self.dizi_dosyasi, self.ozet_dosyasi = dizi_dosyasi, ozet_dosyasi
        self._ozet = None

    def _yukle(self):
        return np.load(self.dizi_dosyasi)

    def ozet(self):
        if self._ozet is None:
            self._ozet = json_oku(self.ozet_dosyasi)
        return self._ozet

    def dizi(self, p, sure):
        return self.veri[f"d_{p}_{sure}"]

    def cerceve(self):
        o = self.ozet()
        return (o["bati"], o["kuzey"], o["dx"], o["dy"],
                self.dizi(o["yagis_mm"][0], o["sure_sa"][0]).shape)

    def gecerli(self, p, sure) -> bool:
        o = self.ozet()
        return p in o["yagis_mm"] and sure in o["sure_sa"]

    def alt_gecit_dolu(self, p, sure) -> bool:
        return self.ozet()["senaryolar"][f"{p}_{sure}"]["alt_gecit_dolu"] > 0

    def yanit(self):
        """Ön yüz için: senaryo listesi, sınırlar, sınıflar ve her senaryonun özeti."""
        o = self.ozet()
        return {
            "status": "ok",
            "yagis_mm": o["yagis_mm"], "sure_sa": o["sure_sa"], "drenaj_mm_sa": o["drenaj_mm_sa"],
            "bounds": self.leaflet_sinirlari(),
            "siniflar": [{"ad": ad, "renk": f"rgba({r[0]},{r[1]},{r[2]},{r[3] / 255:.2f})"}
                         for ad, r in zip(DERINLIK_AD + [BELIRSIZ_AD], DERINLIK_RENK + [BELIRSIZ_RENK])],
            "il_km2": o["il_km2"],
            "senaryolar": o["senaryolar"],
        }

    def harita_png(self, p, sure):
        """Su derinliği sınıfları (desimetre dizisinden), satırlar Mercator'a."""
        def uret():
            o = self.ozet()
            dm = self.dizi(p, sure)
            sinif = np.digitize(dm, np.array(DERINLIK_ESIK) * 10)       # 0 = <10 cm (boyanmaz)
            sinif[dm == BELIRSIZ] = len(DERINLIK_RENK) + 1
            b = mercator_satirlari(sinif, o["kuzey"], o["dy"], kat=2)
            return renkli_png(b, DERINLIK_RENK + [BELIRSIZ_RENK])
        return self._onbellekli_png((p, sure), uret)


senaryolar = SelSenaryolari()
