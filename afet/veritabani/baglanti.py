"""PostGIS bağlantı havuzları: okuma ve yazma ayrı havuz.

Sunucu açılışta veritabanına ulaşamazsa kapanmaz; istekler geldikçe en sık
YENIDEN_DENEME_SN'de bir yeniden bağlanmayı dener. Çevrimdışı betikler
`async with db.oturum():` ile bağlanıp iş bitince havuzları kapatır."""
import asyncio
import time
from contextlib import asynccontextmanager

import asyncpg
from loguru import logger

from afet.ayarlar import ayarlar

YENIDEN_DENEME_SN = 15     # veritabanı kapalıyken en sık bu aralıkla yeniden bağlanılır


class Veritabani:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.okuma_havuzu = None
        self.yazma_havuzu = None
        self._kilit = asyncio.Lock()
        self._son_deneme = 0.0

    async def _havuzlari_ac(self):
        okuma = await asyncpg.create_pool(self.dsn, min_size=5, max_size=20)
        try:
            yazma = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)
        except Exception:
            await okuma.close()
            raise
        self.okuma_havuzu, self.yazma_havuzu = okuma, yazma
        logger.success("PostGIS bağlantısı kuruldu.")

    async def ac(self, deneme: int = 5):
        """Havuzları açar; olmazsa `deneme` kez 2 sn arayla dener."""
        for i in range(1, deneme + 1):
            try:
                await self._havuzlari_ac()
                return
            except Exception as e:
                logger.warning(f"Bağlantı denemesi {i}/{deneme} başarısız: {e}")
                await asyncio.sleep(2)
        self._son_deneme = time.monotonic()
        logger.error("PostGIS'e ulaşılamıyor; sunucu açık kalır, istekler geldikçe "
                     f"en sık {YENIDEN_DENEME_SN} sn'de bir yeniden bağlanmayı dener.")

    async def _yeniden_baglan(self):
        """Açılışta veritabanı kapalıysa sunucu yeniden başlatılmadan bağlanır
        (istek başına değil, en sık YENIDEN_DENEME_SN'de bir denenir)."""
        async with self._kilit:
            if self.okuma_havuzu is not None or time.monotonic() - self._son_deneme < YENIDEN_DENEME_SN:
                return
            self._son_deneme = time.monotonic()
            try:
                await self._havuzlari_ac()
            except Exception as e:
                logger.warning(f"PostGIS hâlâ kapalı: {e}")

    @asynccontextmanager
    async def baglan(self, yazma: bool = False):
        """Havuzdan bağlantı; havuz yoksa önce yeniden bağlanmayı dener."""
        if self.okuma_havuzu is None:
            await self._yeniden_baglan()
        havuz = self.yazma_havuzu if yazma else self.okuma_havuzu
        if havuz is None:
            raise ConnectionError("PostGIS'e ulaşılamıyor")
        async with havuz.acquire() as conn:
            yield conn

    @asynccontextmanager
    async def oturum(self):
        """Betikler için: havuzları açar, blok bitince (hata olsa da) kapatır."""
        await self.ac()
        try:
            yield self
        finally:
            await self.kapat()

    async def kapat(self):
        for havuz in (self.okuma_havuzu, self.yazma_havuzu):
            if havuz:
                await havuz.close()
        self.okuma_havuzu = self.yazma_havuzu = None
        logger.info("Veritabanı bağlantıları kapatıldı.")


db = Veritabani(ayarlar.dsn)
