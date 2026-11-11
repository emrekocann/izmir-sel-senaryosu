"""Kademeli yağış senaryosu: "X mm yağış Y saatte düşerse nereyi su basar?"

Fizik tabanlı, basitleştirilmiş bir taşkın simülasyonu (eğitilmiş model
DEĞİL). Her senaryo (yağış miktarı × süre) çevrimdışı bir kez hesaplanır,
site hazır sonuçları sunar. Varsayımlar aşağıda sabit olarak yazılıdır.

  1. Yüzey akışı — SCS eğri numarası (CN) yöntemi (USDA TR-55):
        S = 25400/CN − 254,  Ia = 0.2·S,  Q = (P − Ia)² / (P − Ia + S)
     CN, ESA WorldCover 2021 arazi örtüsünden (uydu görüntülerinden yapay
     zekâ ile üretilmiş, 10 m) hücre başına alan ağırlıklı ortalamadır.
     Toprak grubu il genelinde C kabul edilir (toprak haritası yok).
  2. Kent drenajı — yapılaşmış kısımda yağmur suyu şebekesi saatte
     DRENAJ_MM_SA kadar yağışı taşır; ancak bunun üstü yüzeyde kalır.
  3. Akış — yüzey suyu SRTM (~60 m) akış yönünde biriktirilir (pysheds):
     her hücreden geçen toplam hacim V (m³).
  4. Dere taşkını — tepe debisi Qp = 2V / ((D + Tc)·3600) (üçgen hidrograf,
     Tc = 0.3·A^0.4 saat, A drenaj alanı km²). Yatak Qbf kadarını taşmadan
     taşır (2 yılda bir görülen yağış varsayımı: 1 saatte 25 mm ya da 24
     saatte 60 mm senaryolarının büyüğü); fazlası (Qp − Qbf) yatak dışına
     taşar. Taşkın seviyesi HAND'dan türetilen sentetik anahtar eğrisiyle
     bulunur (Zheng vd. 2018; NOAA OWP HAND-FIM): her dere hücresi için h
     seviyesinde ıslanan kesit A(h), ıslak genişlik W(h) DEM'den ölçülür ve
     Manning Q(h) = A/n · (A/W)^(2/3) · √S hesaplanır. Böylece düz ovada su
     geniş alana yayılıp sığ kalır, dar vadide derinleşir. HAND: hücrenin,
     aktığı en yakın dere hücresine göre yüksekliği (Nobre vd. 2011).
  5. Çukurlar — kapalı çukurlar kendilerine akan hacim kadar alttan dolar
     (taşma seviyesini geçemez). 10 m'den derin çukurlar (baraj gölü, taş
     ocağı, SRTM hatası), içinden dere geçen çukurlar (köprü / yol dolgusu
     izi; su menfezden geçer) ve kalıcı su yüzeyleri (WorldCover) hesaba
     girmez.
  6. Düz ova — içinden dere geçen, 1 km²'den büyük DEM düzlükleri (Gediz
     deltası, Menemen ovası gibi; derinliklerine bakılmaz) SRTM'nin ±birkaç
     metre hatası yüzünden akış yönü çözülemeyen yerlerdir. Buralarda
     derinlik verilmez: düzlüğün (göl / deniz yüzeyi hariç) %10'u ıslanırsa
     tamamı "su gelir, derinlik belirsiz" gösterilir.
  Yağış yalnız il sınırı içine düşer (il dışı havzalardan gelen su yok);
  geniş havzalarda alan azaltma katsayısı (ARF, TP-29) uygulanır. Havzası
  5000 km²'den büyük nehir (Gediz) baraj ve DSİ seddeleriyle kontrol
  edildiği için taşırılmaz.

Çıktılar: sel_model/senaryo.npz (her senaryo için derinlik, desimetre),
sel_model/senaryo_ozet.json (alan, yol, alt geçit, toplanma alanı, mahalle)
ve tahliye rotası için sel_senaryo_su tablosu (sel_senaryo_yollar.py).

Çalıştırma: venv/bin/python sel_senaryo_hazirla.py  (sel_duyarlilik_hesapla.py'nin
DEM'ini ve köprü/alt geçit önbelleğini kullanır; ~20–30 dk)
"""
import asyncio
import glob
import json
import logging
import math
import os
import time

import numpy as np
import shapely
from rasterio.features import rasterize
from rasterio.windows import from_bounds
from scipy import ndimage

import ag
import sel_senaryo_yollar
from build_road_network import load_boundary
from database import db
from dem_hidroloji import (DIRMAP, VERI_DIR, akis_agi, cukurlar, dem_mozaik, hand_hesapla,
                           kopru_tunel, raster_ornekle, yakin_mi, yol_noktalari)
from harita_yardim import hucre_merkezleri, sinira_degen
from sel_riski import MODEL_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("senaryo")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SENARYO_FILE = os.path.join(MODEL_DIR, "senaryo.npz")
OZET_FILE = os.path.join(MODEL_DIR, "senaryo_ozet.json")
CN_FILE = os.path.join(VERI_DIR, "cn_60m_v2.npz")
MAHALLE_DIR = os.path.join(BASE_DIR, "sinir_veri", "tkgm", "mahalle")

YAGIS_MM = [10, 25, 50, 75, 100, 150, 200, 250]
SURE_SA = [1, 6, 24]
DRENAJ_MM_SA = 20.0          # kent yağmur suyu şebekesinin taşıyabildiği yağış (varsayım)
DERE_KM2 = 1.0               # bu drenaj alanından büyük akışlar dere sayılır
MANNING_N = 0.06             # yatak dışı (taşkın ovası) pürüzlülüğü
SEVIYE_M = np.array([0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 7, 10], np.float32)
# Dereler yaklaşık 2 yılda bir görülen yağışı taşmadan taşır (varsayım): yatak
# kapasitesi bu senaryoların en büyük tepe debisidir (mm, saat)
YATAK_SENARYO = [(25, 1), (60, 24)]
ARF_KADEME = [1.0, 0.9, 0.8, 0.7, 0.6]   # alan azaltma katsayısı için ara hesap kademeleri
DUZ_OVA_KM2 = 1.0            # bundan büyük, içinden dere geçen DEM düzlüğü "belirsiz" gösterilir
DUZ_ISLAK_PAY = 0.1          # düzlüğün bu kadarı ıslaksa tamamı "su gelir" sayılır
BELIRSIZ = 255               # derinlik dizisinde "düz ova, derinlik belirsiz" kodu
SETLI_KM2 = 5000.0           # bundan büyük havzalı nehir (Gediz): baraj + DSİ seddesi, taşmaz
CUKUR_MIN_M = 0.1
CUKUR_MAX_M = 10.0           # daha derin çukurlar baraj gölü / taş ocağı / SRTM hatası sayılır
YOL_KAPALI_M = 0.3           # araçlar için geçilmez derinlik
DERIN_SINIF = [0.1, 0.3, 1.0]   # sığ / diz / derin (m)

# ESA WorldCover sınıfı → CN (toprak grubu C, TR-55 tabloları)
CN_TABLO = {10: 73, 20: 74, 30: 79, 40: 85, 50: 94, 60: 89, 70: 98, 80: 100, 90: 98, 95: 98, 100: 79}
WC_KAT = 3                   # WorldCover 60 m hücreye 3×3 örnekle (≈20 m) ortalanır
KOMSU = {64: (-1, 0), 128: (-1, 1), 1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1)}


def scs_akis(p, cn):
    """SCS-CN yüzey akışı (mm); p yağış (mm), cn eğri numarası."""
    s = 25400.0 / np.clip(cn, 30, 100) - 254.0
    ia = 0.2 * s
    return np.where(p > ia, (p - ia) ** 2 / np.maximum(p - ia + s, 1e-6), 0.0)


def senaryo_akisi(p, sure, cn_dogal, cn_kent, kent, su=0.0):
    """Hücre başına yüzeyde kalan su (mm): doğal kısım + kentte drenajın
    taşıyamadığı kısım. Kalıcı su yüzeyi (göl, baraj, deniz; payı su) akış
    üretmez."""
    q_dogal = scs_akis(p, cn_dogal)
    q_kent = np.maximum(scs_akis(p, cn_kent) - DRENAJ_MM_SA * sure, 0.0)
    return np.maximum(1 - kent - su, 0) * q_dogal + kent * q_kent


def kesit_debisi(hacim, yuzey, boy, egim):
    """Islanan hacim (m³) ve yüzeyden (m²), boy uzunluğundaki erim için
    Manning debisi (m³/s): A = hacim/boy, R = hacim/yüzey."""
    a = hacim / boy
    r = hacim / np.maximum(yuzey, 1e-9)
    return a / MANNING_N * r ** (2 / 3) * np.sqrt(egim)


def seviye_bul(fazla, egri):
    """Her satır için egri (debi, SEVIYE_M sırasıyla artan) üzerinde fazla
    debinin seviyesi (m); doğrusal ara değer, uçlarda 0 ve SEVIYE_M[-1]."""
    k = (egri < fazla[:, None]).sum(axis=1)
    q0 = np.where(k > 0, egri[np.arange(len(k)), np.maximum(k - 1, 0)], 0)
    h0 = np.where(k > 0, SEVIYE_M[np.maximum(k - 1, 0)], 0)
    kk = np.minimum(k, len(SEVIYE_M) - 1)
    q1, h1 = egri[np.arange(len(k)), kk], SEVIYE_M[kk]
    h = h0 + (h1 - h0) * (fazla - q0) / np.maximum(q1 - q0, 1e-9)
    return np.where(fazla <= 0, 0, np.where(k >= len(SEVIYE_M), SEVIYE_M[-1], h)).astype(np.float32)


def havuz_doldur(etiket, taban, tasma, alan, hacim_giren):
    """Çukurları alttan doldurur. etiket: çukur no (0 = çukur değil),
    taban/tasma: hücre tabanı ve çukurun taşma seviyesi (m), alan: hücre alanı
    (m²), hacim_giren: çukur başına giren hacim (m³, dizi; indeks = etiket).
    Dönüş: hücre başına su derinliği (m)."""
    i = np.flatnonzero(etiket)
    if i.size == 0:
        return np.zeros(etiket.shape, np.float32)
    e, z, a = etiket.ravel()[i], taban.ravel()[i], alan.ravel()[i]
    sira = np.lexsort((z, e))
    e, z, a, i = e[sira], z[sira], a[sira], i[sira]
    bas = np.r_[0, np.flatnonzero(np.diff(e)) + 1]            # her çukurun ilk satırı
    grup = np.repeat(np.arange(len(bas)), np.diff(np.r_[bas, len(e)]))
    # su seviyesi k. hücrenin tabanındayken depolanan hacim: Σ_{j≤k} (z_k − z_j)·a_j
    ka = np.cumsum(a)
    kaz = np.cumsum(a * z)
    ka -= np.repeat(np.r_[0, ka[bas[1:] - 1]], np.diff(np.r_[bas, len(e)]))
    kaz -= np.repeat(np.r_[0, kaz[bas[1:] - 1]], np.diff(np.r_[bas, len(e)]))
    v_k = z * ka - kaz
    v_in = hacim_giren[e]
    dolu = (v_k <= v_in) & (v_in > 0)                          # bu seviyeye kadar su yetiyor
    # her çukurda suyun ulaştığı son hücre ve oradaki seviye
    son = np.full(len(bas), -1)
    np.maximum.at(son, grup, np.where(dolu, np.arange(len(e)), -1))
    gecerli = son >= 0                                         # en dipteki hücreye bile su yoksa 0
    s = np.where(gecerli, son, bas)
    seviye = z[s] + (v_in[s] - v_k[s]) / ka[s]
    seviye = np.minimum(seviye, tasma.ravel()[i][s])          # taşma seviyesini geçemez
    d = np.maximum(np.where(gecerli[grup], seviye[grup], -np.inf) - z, 0)
    out = np.zeros(etiket.size, np.float32)
    out[i] = d
    return out.reshape(etiket.shape)


def worldcover_cn(tr, shape):
    """60 m ızgarada alan ağırlıklı CN (doğal ve kent ayrı) ve yapılaşma payı."""
    if os.path.exists(CN_FILE):
        v = np.load(CN_FILE)
        return v["cn_dogal"], v["cn_kent"], v["kent"], v["su"]
    h, w = shape
    b = (tr.c, tr.f + h * tr.e, tr.c + w * tr.a, tr.f)
    toplam = np.zeros(shape, np.float32)
    cn_t = np.zeros(shape, np.float32)
    kent_t = np.zeros(shape, np.float32)
    su_t = np.zeros(shape, np.float32)
    lut = np.zeros(256, np.float32)
    for k, v in CN_TABLO.items():
        lut[k] = v
    for karo, ds in ag.worldcover_karolari(*b):
        kb = ds.bounds
        # karo ile ızgaranın kesiştiği satır/sütun aralığı (60 m hücre sınırlarına hizalı)
        c0 = max(0, math.ceil((kb.left - tr.c) / tr.a))
        c1 = min(w, math.floor((kb.right - tr.c) / tr.a))
        r0 = max(0, math.ceil((kb.top - tr.f) / tr.e))
        r1 = min(h, math.floor((kb.bottom - tr.f) / tr.e))
        if c0 >= c1 or r0 >= r1:
            continue
        log.info("WorldCover %s: satır %d–%d, sütun %d–%d", karo, r0, r1, c0, c1)
        for s0 in range(r0, r1, 400):                  # şerit şerit (bellek)
            s1 = min(s0 + 400, r1)
            win = from_bounds(tr.c + c0 * tr.a, tr.f + s1 * tr.e, tr.c + c1 * tr.a,
                              tr.f + s0 * tr.e, transform=ds.transform)
            arr = ds.read(1, window=win, out_shape=((s1 - s0) * WC_KAT, (c1 - c0) * WC_KAT))
            blok = lambda x: x.reshape(s1 - s0, WC_KAT, c1 - c0, WC_KAT).sum(axis=(1, 3))
            gecerli = arr > 0
            kent = arr == 50
            su = arr == 80
            toplam[s0:s1, c0:c1] += blok(gecerli)
            kent_t[s0:s1, c0:c1] += blok(kent)
            su_t[s0:s1, c0:c1] += blok(su)
            cn_t[s0:s1, c0:c1] += blok(np.where(gecerli & ~kent & ~su, lut[arr], 0))
    dogal_say = toplam - kent_t - su_t
    cn_dogal = np.where(dogal_say > 0, cn_t / np.maximum(dogal_say, 1), CN_TABLO[30]).astype(np.float32)
    kent = (kent_t / np.maximum(toplam, 1)).astype(np.float32)
    # WorldCover'ın kapsamadığı (deniz) hücreler de su sayılır
    su = np.where(toplam > 0, su_t / np.maximum(toplam, 1), 1).astype(np.float32)
    cn_kent = np.full(shape, CN_TABLO[50], np.float32)
    np.savez_compressed(CN_FILE, cn_dogal=cn_dogal, cn_kent=cn_kent, kent=kent, su=su)
    return cn_dogal, cn_kent, kent, su


def hidroloji():
    """Akış yönü, dere ağı, HAND + en yakın dere hücresi, eğim, anahtar
    eğrileri, çukurlar ve düz ovalar."""
    hd = akis_agi()
    hand, idx, dere = hand_hesapla(hd, DERE_KM2)
    alan, duz, fdir = hd["alan"], hd["duz"], hd["fdir"]
    dx_m, dy_m = hd["dx_m"], hd["dy_m"]
    h, w = alan.shape
    ok = idx.ravel() >= 0

    # akış yönündeki komşuya göre eğim (dere hücrelerinde Manning için)
    z = np.asarray(duz, np.float64)
    fd = np.asarray(fdir)
    egim = np.full(z.shape, 0.001, np.float32)
    for kod, (dr, dc) in KOMSU.items():
        m = fd == kod
        rr, cc = np.nonzero(m)
        r2, c2 = np.clip(rr + dr, 0, h - 1), np.clip(cc + dc, 0, w - 1)
        mesafe = np.hypot(dr * dy_m, dc * dx_m[rr])
        egim[rr, cc] = (z[rr, cc] - z[r2, c2]) / mesafe
    egim = np.clip(egim, 0.001, 0.2)
    # dere boyunca yumuşat (60 m'de tek hücrelik basamaklar Manning'i bozar)
    egim = np.where(dere, ndimage.uniform_filter(np.where(dere, egim, 0), 5)
                    / np.maximum(ndimage.uniform_filter(dere.astype(np.float32), 5), 1e-3), egim)
    egim = np.clip(egim, 0.001, 0.2).astype(np.float32)

    # sentetik anahtar eğrisi: her dere hücresi için SEVIYE_M seviyelerinde debi
    t = time.time()
    iflat = idx.ravel()
    hf, af = hand.ravel(), alan.ravel()
    dere_no = np.flatnonzero(dere.ravel())
    egri = np.zeros((len(dere_no), len(SEVIYE_M)), np.float32)
    boy = np.sqrt(af[dere_no])
    for k, hs in enumerate(SEVIYE_M):
        islak = ok & (hf < hs)
        hacim = np.bincount(iflat[islak], weights=(hs - hf[islak]) * af[islak], minlength=idx.size)
        yuzey = np.bincount(iflat[islak], weights=af[islak], minlength=idx.size)
        egri[:, k] = kesit_debisi(hacim[dere_no], yuzey[dere_no], boy, egim.ravel()[dere_no])
    egri = np.maximum.accumulate(egri, axis=1)
    log.info("Anahtar eğrileri (%d dere hücresi): %.0f sn", len(dere_no), time.time() - t)

    _, etiket, n_cukur, derin = cukurlar(hd, CUKUR_MIN_M, CUKUR_MAX_M)
    no = np.arange(1, n_cukur + 1)
    # dere geçen çukurlar çoğunlukla DEM'deki köprü / yol dolgusu izidir: su
    # menfezden geçer, birikmez
    dereli = ndimage.maximum(dere, etiket, index=no) > 0
    # büyük dereli dolgu alanları (delta / ova düzlükleri): SRTM burada akış
    # yönünü çözemez, pysheds düzlüğe yapay düz akış çizgileri çizer; su
    # gelip gelmediği söylenir, derinlik söylenmez. Derinliğe bakılmaz:
    # Menemen ovası taşma seviyesinin 13 m altına iner
    buyuk = ndimage.sum(alan, etiket, index=no) / 1e6 >= DUZ_OVA_KM2
    duz_et = np.where(np.isin(etiket, np.flatnonzero(dereli & buyuk) + 1), etiket, 0)
    etiket[np.isin(etiket, np.flatnonzero(dereli | derin) + 1)] = 0
    log.info("Dere hücresi: %d, çukur: %d (%d tanesi dere üstünde, %d tanesi derin; dolmaz)",
             int(dere.sum()), n_cukur, int(dereli.sum()), int((derin & ~dereli).sum()))
    for gereksiz in ("acc", "duz"):          # bellek: sonraki adımlarda kullanılmıyor
        del hd[gereksiz]
    hd.update(dere=dere, hand=hand, idx=idx, egim=egim, dere_no=dere_no, egri=egri,
              etiket=etiket, n_cukur=n_cukur, duz_et=duz_et)
    return hd


def debi(hd, q_mm, sure):
    """Hücreden geçen tepe debisi (m³/s) ve toplam hacim (m³)."""
    agirlik = (q_mm / 1000.0 * hd["alan"]).astype(np.float64)
    from pysheds.sview import Raster
    agirlik = Raster(agirlik, viewfinder=hd["fdir"].viewfinder)
    v = np.asarray(hd["grid"].accumulation(hd["fdir"], weights=agirlik, dirmap=DIRMAP), np.float64)
    tc = 0.3 * np.maximum(hd["drenaj_km2"], 0.01) ** 0.4
    return 2 * v / ((sure + tc) * 3600.0), v


def alan_azaltma(alan_km2, sure):
    """Alan azaltma katsayısı (ARF): geniş bir havzanın ortalama yağışı, tek
    noktada ölçülen yağıştan azdır. Leclerc & Schaake (1972), ABD NWS TP-29
    eğrilerine uyum: ARF = 1 − e^(−1.1·D^0.25) + e^(−1.1·D^0.25 − 0.01·A),
    D saat, A mil²."""
    k = 1.1 * sure ** 0.25
    return 1 - np.exp(-k) + np.exp(-k - 0.01 * np.asarray(alan_km2) / 2.59)


def havza_debisi(hd, p, sure, akis, maske=None):
    """Alan azaltmalı tepe debisi ve hacim. Her hücrenin havzasına P·ARF(A)
    yağar; bunun için ARF_KADEME yağışlarıyla debi hesaplanıp hücrenin ARF'sine
    göre ara değer alınır. akis(p) → mm ızgarası; maske dışına yağış düşmez."""
    a = np.clip(alan_azaltma(hd["drenaj_km2"], sure), ARF_KADEME[-1], 1.0)
    qp = np.zeros(a.shape)
    v = np.zeros(a.shape)
    onceki = None
    for k in ARF_KADEME:
        q = akis(p * k)
        if maske is not None:
            q = np.where(maske, q, 0)
        simdi = (k,) + debi(hd, q, sure)
        if onceki is not None:
            k1, qp1, v1 = onceki
            ara = (a <= k1) & (a >= k)
            w = np.where(ara, (a - k) / (k1 - k), 0)
            qp = np.where(ara, simdi[1] + w * (qp1 - simdi[1]), qp)
            v = np.where(ara, simdi[2] + w * (v1 - simdi[2]), v)
        onceki = simdi
    return qp, v


def derinlik(hd, qp, v, qbf):
    dn = hd["dere_no"]
    seviye = np.zeros(qp.size, np.float32)
    seviye[dn] = seviye_bul((qp.ravel() - qbf.ravel())[dn], hd["egri"])
    seviye[hd["drenaj_km2"].ravel() >= SETLI_KM2] = 0
    idx = hd["idx"].ravel()
    ok = idx >= 0
    d_dere = np.zeros(idx.size, np.float32)
    d_dere[ok] = seviye[idx[ok]] - hd["hand"].ravel()[ok]
    d_dere = np.maximum(d_dere, 0).reshape(hd["alan"].shape)
    giren = np.zeros(hd["n_cukur"] + 1)
    np.maximum.at(giren, hd["etiket"].ravel(), v.ravel())
    giren[0] = 0
    d_cukur = havuz_doldur(hd["etiket"], hd["taban"], hd["tasma"], hd["alan"], giren)
    d = np.maximum(d_dere, d_cukur)
    d[hd["veri_yok"] | hd["kalici_su"]] = 0             # göl, baraj, deniz taşkın sayılmaz
    return d


def mahalle_izgara(tr, shape):
    """TKGM mahalle poligonlarını ızgaraya basar: (kimlik ızgarası, [(ilçe, mahalle)])."""
    adlar, sekiller = [], []
    ilceler = {f["properties"]["id"]: f["properties"]["text"] for f in
               json.load(open(os.path.join(BASE_DIR, "sinir_veri", "tkgm", "izmir_ilce.json")))["features"]}
    for yol in sorted(glob.glob(os.path.join(MAHALLE_DIR, "*.json"))):
        ilce = ilceler.get(int(os.path.basename(yol)[:-5]), "?")
        for f in json.load(open(yol, encoding="utf-8"))["features"]:
            if f["geometry"]:
                adlar.append((ilce, f["properties"]["text"]))
                sekiller.append((f["geometry"], len(adlar)))
    return rasterize(sekiller, out_shape=shape, transform=tr, fill=0, dtype="int32"), adlar


async def yol_ornekleri():
    """Araç yol ağını ~25 m'de bir örnekler: (x, y, kenar no, kenar uzunluğu °)."""
    await db.connect()
    try:
        async with db.read_pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, ST_AsBinary(the_geom) AS wkb FROM izmir_roads_noded")
            alanlar = await conn.fetch("SELECT id, adi, ilce, ST_X(konum) AS lon, ST_Y(konum) AS lat "
                                       "FROM toplanma_alanlari")
    finally:
        await db.disconnect()
    geoms, x, y, ki = yol_noktalari([r["wkb"] for r in rows])
    return x, y, ki, shapely.length(geoms), [dict(a) for a in alanlar]


def main():
    sinir = load_boundary()
    dem_mozaik(sinir)
    t0 = time.time()
    hd = hidroloji()
    tr, shape = hd["tr"], hd["alan"].shape
    cn_dogal, cn_kent, kent, su = worldcover_cn(tr, shape)
    hd["kalici_su"] = su > 0.5
    # göl / deniz yüzeyi düz ovaya sayılmaz (ıslanma payı karadan hesaplanır)
    hd["duz_et"] = np.where(hd["kalici_su"], 0, hd["duz_et"])
    duz_n = np.bincount(hd["duz_et"].ravel())
    log.info("Düz ova (belirsiz) alanı: %d parça, %.0f km²", int((duz_n[1:] > 0).sum()),
             hd["alan"][hd["duz_et"] > 0].sum() / 1e6)
    log.info("Arazi: yapılaşma payı il çerçevesinde %%%.1f, ortalama doğal CN %.0f",
             kent.mean() * 100, cn_dogal.mean())

    lon, lat = hucre_merkezleri(tr, shape)
    kapsa = sinira_degen(sinir, lon, lat, tr.a, tr.e)
    icinde = shapely.contains_xy(sinir, lon, lat)
    del lon, lat
    mah_id, mah_adlari = mahalle_izgara(tr, shape)

    x, y, ki, uzunluk, alanlar = asyncio.run(yol_ornekleri())
    kopru, alt_gecit, uzun_tunel = kopru_tunel(sinir)
    koprude = yakin_mi(x, y, kopru + uzun_tunel, 0.00012)
    ag_xy = np.array([shapely.get_coordinates(g).mean(axis=0) for g in alt_gecit]) if alt_gecit else np.zeros((0, 2))
    a_xy = np.array([(a["lon"], a["lat"]) for a in alanlar]) if alanlar else np.zeros((0, 2))
    km_derece = 111.32   # kenar uzunluğu (°) → km (enlem/boylam ortalaması yeterli)
    nokta_uzunluk = (uzunluk / np.bincount(ki, minlength=len(uzunluk)).clip(1))[ki]

    akis = lambda sure: (lambda p: senaryo_akisi(p, sure, cn_dogal, cn_kent, kent, su))
    # yatak kapasitesi tüm havzaya (il dışı dahil) yağan 2 yıllık yağışa göre
    qbf = np.maximum.reduce([havza_debisi(hd, p, sure, akis(sure))[0] for p, sure in YATAK_SENARYO])
    hucre_km2 = hd["alan"] / 1e6
    il_km2 = float(hucre_km2[icinde].sum())
    sonuc, ozet = {}, {"yagis_mm": YAGIS_MM, "sure_sa": SURE_SA, "drenaj_mm_sa": DRENAJ_MM_SA,
                       "derinlik_sinif_m": DERIN_SINIF, "yol_kapali_m": YOL_KAPALI_M,
                       "il_km2": round(il_km2), "bati": tr.c, "kuzey": tr.f, "dx": tr.a, "dy": tr.e,
                       "senaryolar": {}}
    for sure in SURE_SA:
        for p in YAGIS_MM:
            t = time.time()
            # senaryo yağışı yalnız il sınırı içine düşer
            d = derinlik(hd, *havza_debisi(hd, p, sure, akis(sure), icinde), qbf)
            # düz ovada: parçanın ≥ %10'u ıslaksa tümü "su gelir, derinlik belirsiz"
            et = hd["duz_et"]
            islak_pay = (np.bincount(et.ravel(), weights=(d >= DERIN_SINIF[0]).ravel(), minlength=len(duz_n))
                         / np.maximum(duz_n, 1))
            belirsiz = (et > 0) & (islak_pay[et] >= DUZ_ISLAK_PAY)
            d = np.where(et > 0, 0, d)
            sonuc[f"d_{p}_{sure}"] = np.where(kapsa, np.where(belirsiz, BELIRSIZ,
                                                              np.clip(np.round(d * 10), 0, BELIRSIZ - 1)), 0).astype(np.uint8)
            di = np.where(icinde, d, 0)
            alan_km2 = {f"{e}": round(float(hucre_km2[di >= e].sum()), 1) for e in DERIN_SINIF}
            # yollar: suyun ≥ YOL_KAPALI_M olduğu örnek noktalarının temsil ettiği
            # uzunluk (köprüler hariç); her nokta kenar uzunluğunun 1/n'i
            yd = raster_ornekle(d, tr, x, y)
            yd[koprude] = 0
            kapali_km = float((nokta_uzunluk * (yd >= YOL_KAPALI_M)).sum() * km_derece)
            # alt geçitler: kentte drenajın taşıyamadığı su ≥ 10 mm ise dolar
            q_kent_fazla = np.maximum(scs_akis(p, CN_TABLO[50]) - DRENAJ_MM_SA * sure, 0)
            ag_dolu = int(len(ag_xy)) if q_kent_fazla >= 10 else 0
            ad = raster_ornekle(d, tr, a_xy[:, 0], a_xy[:, 1]) if len(a_xy) else np.zeros(0)
            etk = np.bincount(mah_id.ravel(), weights=((di >= DERIN_SINIF[1]) * hucre_km2).ravel(),
                              minlength=len(mah_adlari) + 1)
            en_cok = np.argsort(etk)[::-1][:15]
            ozet["senaryolar"][f"{p}_{sure}"] = {
                "yagis_mm": p, "sure_sa": sure,
                "su_alan_km2": alan_km2,
                "belirsiz_km2": round(float(hucre_km2[belirsiz & icinde].sum()), 1),
                "yol_kapali_km": round(kapali_km, 1),
                "alt_gecit_dolu": ag_dolu, "alt_gecit_toplam": int(len(ag_xy)),
                "toplanma_etkilenen": [{"adi": alanlar[i]["adi"], "ilce": alanlar[i]["ilce"],
                                        "derinlik_m": round(float(ad[i]), 1)}
                                       for i in np.argsort(ad)[::-1] if ad[i] >= YOL_KAPALI_M][:30],
                "toplanma_etkilenen_sayi": int((ad >= YOL_KAPALI_M).sum()),
                "toplanma_toplam": len(alanlar),
                "mahalleler": [{"ilce": mah_adlari[i - 1][0], "mahalle": mah_adlari[i - 1][1],
                                "km2": round(float(etk[i]), 2)} for i in en_cok if i > 0 and etk[i] >= 0.01],
            }
            log.info("%3d mm / %2d sa: ≥0.3 m su %.1f km², kapalı yol %.0f km, toplanma %d, alt geçit %d — %.0f sn",
                     p, sure, alan_km2["0.3"], ozet["senaryolar"][f"{p}_{sure}"]["yol_kapali_km"],
                     ozet["senaryolar"][f"{p}_{sure}"]["toplanma_etkilenen_sayi"], ag_dolu, time.time() - t)
    os.makedirs(MODEL_DIR, exist_ok=True)
    np.savez_compressed(SENARYO_FILE, **sonuc)
    with open(OZET_FILE, "w", encoding="utf-8") as f:
        json.dump(ozet, f, ensure_ascii=False, indent=1)
    log.info("Yazıldı: %s (%d senaryo) — toplam %.0f dk", SENARYO_FILE, len(sonuc), (time.time() - t0) / 60)
    # tahliye rotası senaryodaki suyu kullanır: yollar ve toplanma alanları tazelenir
    try:
        asyncio.run(sel_senaryo_yollar.yaz())
    except Exception as e:
        log.warning("Senaryo suyu yollara yazılamadı (migrations/011 uygulandı mı?): %s — "
                    "sonra 'venv/bin/python sel_senaryo_yollar.py' çalıştırın", e)


if __name__ == "__main__":
    main()
