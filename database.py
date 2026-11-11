import asyncio
import time
from contextlib import asynccontextmanager

import asyncpg
from loguru import logger

from config import settings

YENIDEN_DENEME_SN = 15     # veritabanı kapalıyken en sık bu aralıkla yeniden bağlanılır


class Database:
    def __init__(self):
        self.dsn = (
            f"postgresql://{settings.db_user}:{settings.db_pass}"
            f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
        )
        self.read_pool = None
        self.write_pool = None
        self._kilit = asyncio.Lock()
        self._son_deneme = 0.0

    async def _havuzlari_ac(self):
        okuma = await asyncpg.create_pool(self.dsn, min_size=5, max_size=20)
        try:
            yazma = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)
        except Exception:
            await okuma.close()
            raise
        self.read_pool, self.write_pool = okuma, yazma

    async def connect(self, deneme: int = 5):
        for i in range(1, deneme + 1):
            try:
                await self._havuzlari_ac()
                logger.success("✅ PostGIS Bağlantısı Başarılı: Veri Damarları Açıldı.")
                return
            except Exception as e:
                logger.warning(f"⚠️ Bağlantı denemesi {i}/{deneme} başarısız: {e}")
                await asyncio.sleep(2)
        self._son_deneme = time.monotonic()
        logger.error("❌ PostGIS'e ulaşılamıyor; sunucu açık kalır, istekler geldikçe "
                     f"en sık {YENIDEN_DENEME_SN} sn'de bir yeniden bağlanmayı dener.")

    async def _yeniden_baglan(self):
        """Açılışta veritabanı kapalıysa sunucu yeniden başlatılmadan bağlanır
        (istek başına değil, en sık YENIDEN_DENEME_SN'de bir denenir)."""
        async with self._kilit:
            if self.read_pool is not None or time.monotonic() - self._son_deneme < YENIDEN_DENEME_SN:
                return
            self._son_deneme = time.monotonic()
            try:
                await self._havuzlari_ac()
                logger.success("✅ PostGIS bağlantısı kuruldu.")
            except Exception as e:
                logger.warning(f"⚠️ PostGIS hâlâ kapalı: {e}")

    @asynccontextmanager
    async def baglan(self, yazma: bool = False):
        """Havuzdan bağlantı; havuz yoksa önce yeniden bağlanmayı dener."""
        if self.read_pool is None:
            await self._yeniden_baglan()
        havuz = self.write_pool if yazma else self.read_pool
        if havuz is None:
            raise ConnectionError("PostGIS'e ulaşılamıyor")
        async with havuz.acquire() as conn:
            yield conn

    async def disconnect(self):
        if self.read_pool:
            await self.read_pool.close()
        if self.write_pool:
            await self.write_pool.close()
        logger.info("🔌 Veritabanı bağlantıları kapatıldı.")


db = Database()
