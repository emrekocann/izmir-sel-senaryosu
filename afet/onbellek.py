"""Süreli önbellek: dış servisten gelen veriyi belirli süre saklar.

Aynı anda gelen istekler kilitle sıraya girer; böylece önbellek boşken gelen
yüz istek dış servise yüz kez değil, bir kez gider.
"""
import asyncio
import time

from loguru import logger


class SureliOnbellek:
    def __init__(self, sure_sn: float, ad: str = ""):
        self.sure_sn = sure_sn
        self.ad = ad
        self.deger = None
        self.zaman = 0.0
        self._kilit = asyncio.Lock()

    def taze(self) -> bool:
        return self.deger is not None and time.time() - self.zaman < self.sure_sn

    async def al(self, uret, eskiyi_kullan: bool = False):
        """Taze değer varsa onu, yoksa `await uret()` sonucunu döner.
        eskiyi_kullan: üretim hata verirse (servis kapalı) eski değer döner."""
        async with self._kilit:
            if self.taze():
                return self.deger
            try:
                self.deger = await uret()
            except Exception as e:
                if eskiyi_kullan and self.deger is not None:
                    logger.warning(f"{self.ad}: yenilenemedi, eski veri sunuluyor ({e})")
                    return self.deger
                raise
            self.zaman = time.time()
            return self.deger
