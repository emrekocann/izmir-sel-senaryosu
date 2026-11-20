"""Çevrimdışı hesap betikleri (yol ağı, sınır, sel modeli, doğrulama, yayın verisi).

Proje kökünden modül olarak çalıştırılır: venv/bin/python -m hesap.<betik>
Betiklerin ortak giriş / çıkış adımları burada.
"""
import logging

from afet.dosya import json_yaz


def gunlugu_kur():
    """Betik günlüğü: saat + ileti, INFO düzeyi. Giriş noktasında (main) bir kez çağrılır."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def sonucu_yaz(yol, sonuc, yazdir):
    """Sonucu girintili JSON olarak yazar, okunur özetini (yazdir) basar."""
    json_yaz(yol, sonuc, okunur=True)
    yazdir(sonuc)
    print(f"\nYazıldı: {yol}")
