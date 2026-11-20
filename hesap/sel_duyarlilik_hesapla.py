"""Sel / su baskını arazi duyarlılığı (çevrimdışı, bir kez çalışır).

Soru: "Kuvvetli yağışta su nerede toplanır, nerede taşar?" — bu bir eğitilmiş
model DEĞİL, yükseklik verisinden hidrolojik hesap; ağırlıklar uzman
varsayımıdır ve README'de açıkça yazılıdır.

Adımlar (SRTM, ~60 m'ye ortalanarak — 8 GB bellekte il geneli 30 m sığmıyor):
  1. Çukurlar doldurulur, her hücrenin akış yönü ve kendisine akan alan
     (drenaj alanı, km²) hesaplanır (pysheds).
  2. HAND — en yakın dere yatağına göre yükseklik (m). İki eşikle:
     küçük dereler (≥1 km² drenaj) ve büyük dere/çaylar (≥50 km²).
  3. Çukur derinliği: suyun dışarı akamayıp biriktiği kapalı alanlar.
  4. Duyarlılık S (0–1) = max(0.7·h₁, h₅₀, ç)
        h = 1 − HAND/6 m (0'da kesilir; Nobre vd. 2011: HAND<~5 m taşkına açık)
        ç = çukur derinliği / 1 m
  5. Yol kenarları: kenar boyunca ~25 m'de bir örneklenen S'nin ortalaması
     (rota cezası maruz kalınan uzunlukla orantılı — tek dereyi geçen 2 km'lik
     anayolun tamamı riskli sayılmasın) ve S≥0.6 kısmın oranı (rapor için).
     OSM köprüleri (yol suyun üstünden geçer) hariç tutulur; kısa tüneller
     (<400 m, kentte = alt geçit) DEM'de görünmediği için S≥0.9 sayılır.

Çıktılar: sel_model/duyarlilik.npz (harita için, il dışı 0) ve
izmir_roads_noded / izmir_yaya_noded tablolarında sel_duyarlilik,
sel_riskli_oran, alt_gecit.

Çalıştırma: venv/bin/python -m hesap.sel_duyarlilik_hesapla
Önkoşul: migrations/006_sel_duyarlilik.sql, yol ağı tabloları, DB açık.
"""
import asyncio
import logging
import os
import time

import numpy as np
import shapely

from afet.izgara import hucre_merkezleri, sinira_degen
from afet.sinir import il_poligonu
from afet.veritabani.baglanti import db
from afet.yollar import DUYARLILIK, MODEL_DIR
from hesap import gunlugu_kur
from hesap.dem_hidroloji import (akis_agi, cukurlar, dem_mozaik, hand_hesapla, kopru_tunel,
                                 raster_ornekle, yakin_mi, yol_noktalari)

log = logging.getLogger("sel")

DERE_KUCUK_KM2, DERE_BUYUK_KM2 = 1.0, 50.0
HAND_UST_M = 6.0
CUKUR_UST_M = 1.0
ALT_GECIT_S = 0.9
RISKLI_S = 0.6
TABLOLAR = ("izmir_roads_noded", "izmir_yaya_noded")


def hidroloji():
    """HAND (iki dere eşiği) ve çukur derinliği."""
    agi = akis_agi()
    hand = {esik: hand_hesapla(agi, esik)[0] for esik in (DERE_KUCUK_KM2, DERE_BUYUK_KM2)}
    return agi["tr"], hand, cukurlar(agi)[0], agi["veri_yok"]


def duyarlilik(hand, cukur, veri_yok):
    def h(x):
        x = np.where(np.isfinite(x), x, np.inf)
        return np.clip(1 - x / HAND_UST_M, 0, 1)
    s = np.maximum.reduce([
        0.7 * h(hand[DERE_KUCUK_KM2]),
        h(hand[DERE_BUYUK_KM2]),
        np.clip(cukur / CUKUR_UST_M, 0, 1),
    ]).astype(np.float32)
    s[veri_yok] = 0
    return s


async def kenarlara_yaz(s, tr, kopru, alt_gecit, uzun_tunel):
    async with db.oturum():
        async with db.baglan(yazma=True) as conn:
            for tablo in TABLOLAR:
                t = time.time()
                rows = await conn.fetch(f"SELECT id, ST_AsBinary(the_geom) AS wkb FROM {tablo}")
                ids = np.array([r["id"] for r in rows])
                geoms, x, y, ki = yol_noktalari([r["wkb"] for r in rows])
                deger = raster_ornekle(s, tr, x, y)
                deger[yakin_mi(x, y, kopru + uzun_tunel, 0.00012)] = 0      # ~12 m
                ag = yakin_mi(x, y, alt_gecit, 0.00008)
                deger[ag] = np.maximum(deger[ag], ALT_GECIT_S)
                sayi = np.bincount(ki, minlength=len(ids)).clip(min=1)
                kenar_s = np.bincount(ki, weights=deger, minlength=len(ids)) / sayi
                oran = np.bincount(ki, weights=deger >= RISKLI_S, minlength=len(ids)) / sayi
                kenar_ag = np.zeros(len(ids), dtype=bool)
                np.logical_or.at(kenar_ag, ki, ag)
                await conn.execute("DROP TABLE IF EXISTS _sel_tmp; "
                                   "CREATE TEMP TABLE _sel_tmp (id bigint, s real, o real, ag boolean)")
                await conn.copy_records_to_table("_sel_tmp", records=zip(
                    ids.tolist(), np.round(kenar_s, 3).tolist(), np.round(oran, 3).tolist(),
                    kenar_ag.tolist()))
                await conn.execute(f"""UPDATE {tablo} e
                                       SET sel_duyarlilik = t.s, sel_riskli_oran = t.o, alt_gecit = t.ag
                                       FROM _sel_tmp t WHERE e.id = t.id""")
                uz = shapely.length(geoms)
                log.info("%s: %d kenar (%d örnek nokta), yol uzunluğunun %%%.1f'i S≥%.1f, alt geçit: %d — %.0f sn",
                         tablo, len(ids), len(x), (uz * oran).sum() / uz.sum() * 100, RISKLI_S,
                         kenar_ag.sum(), time.time() - t)


def harita_kaydet(s, tr, sinir):
    """Harita için 0–255 tamsayı (sıkıştırılmış): il dışı 0, il içi en az 1
    (böylece s > 0 aynı zamanda il maskesidir; 1/255 sapma ihmal edilebilir)."""
    os.makedirs(MODEL_DIR, exist_ok=True)
    lon, lat = hucre_merkezleri(tr, s.shape)
    icinde = shapely.contains_xy(sinir, lon, lat)
    # haritaya sınıra değen hücreler de girer (tarayıcı il sınırıyla kırpar)
    kapsa = sinira_degen(sinir, lon, lat, tr.a, tr.e)
    u8 = np.where(kapsa, np.maximum(np.round(s * 255), 1), 0).astype(np.uint8)
    np.savez_compressed(DUYARLILIK, s=u8, bati=tr.c, kuzey=tr.f, dx=tr.a, dy=tr.e)
    v = s[icinde]
    log.info("İl içi alan payı — S≥0.3: %%%.1f, S≥0.6: %%%.1f, S≥0.85: %%%.1f",
             (v >= 0.3).mean() * 100, (v >= 0.6).mean() * 100, (v >= 0.85).mean() * 100)


async def main():
    sinir = il_poligonu()
    dem_mozaik(sinir)
    tr, hand, cukur, veri_yok = hidroloji()
    s = duyarlilik(hand, cukur, veri_yok)
    del hand, cukur
    harita_kaydet(s, tr, sinir)
    await kenarlara_yaz(s, tr, *kopru_tunel(sinir))


if __name__ == "__main__":
    gunlugu_kur()
    asyncio.run(main())
