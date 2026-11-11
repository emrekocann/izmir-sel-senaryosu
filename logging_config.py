from loguru import logger
import sys
import os

# Logs klasörü yoksa oluştur
if not os.path.exists("logs"):
    os.makedirs("logs")

# Mevcut ayarları temizle
logger.remove()

# 1. Konsol Logu (Renkli ve okunaklı)
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>", colorize=True)

# 2. Genel Dosya Logu (Tüm olaylar)
logger.add("logs/ingestion.log", rotation="10 MB", retention="10 days", compression="zip")

# 3. Kritik Hata Logu (Sadece INVALID data ve ALERT durumları)
logger.add("logs/invalid_data.log", filter=lambda record: "INVALID" in record["message"] or record["level"] == "CRITICAL")

logger.info("--- Loglama Sistemi Başlatıldı: Gözlemlenebilirlik Aktif ---")