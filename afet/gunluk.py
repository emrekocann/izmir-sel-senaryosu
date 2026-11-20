"""Sunucu günlüğü (loguru): renkli konsol + dönen dosya günlükleri.

İçe aktarılınca değil, sunucu açılırken bir kez kurulur (kur())."""
import os
import sys

from loguru import logger

from afet.yollar import GUNLUK_DIR


def kur():
    os.makedirs(GUNLUK_DIR, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>")
    logger.add(os.path.join(GUNLUK_DIR, "sunucu.log"), rotation="10 MB", retention="10 days", compression="zip")
    logger.add(os.path.join(GUNLUK_DIR, "hatalar.log"), level="ERROR")
