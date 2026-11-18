"""Yağış senaryosunu geçmiş bir selle karşılaştırır (ilk doğrulama).

Gerçek olay: dogrulama/olay_<tarih>.json — haberlerde adı geçen, su basan
mahalle, cadde, dere ve alt geçitler (kaynaklarıyla elle derlendi). Model:
olaya yakın yağış senaryoları (sel_model/senaryo.npz).

Soru: haberde "su bastı" denen yerler, modelde aynı ilçelerdeki öteki
yerlerden daha ıslak mı? Haber yalnız su basan yeri söyler; su basmayan yer
listesi yoktur. Bu yüzden karşılaştırma, aynı ilçelerdeki bütün mahalleler
(ve adlı caddeler) içinde haberdekilerin sırasıdır:

  • Mahalle: alanının ıslak payı (10 cm+ ya da düz ova). Her haber mahallesi
    için "kaçıncı yüzdelik" ve hepsi için AUC (rastgele bir haber mahallesinin
    rastgele bir öteki mahalleden ıslak çıkma olasılığı; 0.5 = yazı tura).
  • Cadde: modelde araçla geçilemez (30 cm+) noktası var mı; aynı oran
    ilçelerdeki öteki adlı caddelerde ne?
  • Dere hattı ve alt geçit: tek tek raporlanır.

Habersiz yerlerin bir kısmı da gerçekte su almış olabilir (haber her yeri
yazmaz); bu, AUC'yi düşürür, yani sonuç temkinlidir. Örnek küçüktür:
istatistiksel kanıt değil, modelin neyi yakalayıp neyi kaçırdığını gösteren
ilk kontroldür.

Çalıştırma: venv/bin/python -m hesap.sel_dogrulama [dogrulama/olay_2021_02_02.json]
(ilk çalıştırmada OSM dosyasından adlı yollar/dereler çıkarılır, ~1.5 dk)
Çıktı: dogrulama/sonuc_<tarih>.json ve ekrana tablo.
"""
import logging
import os
import sys

import numpy as np
import shapely
from affine import Affine
from rasterio.features import rasterize

from afet.dosya import json_oku, json_yaz
from afet.sel.senaryo import BELIRSIZ
from afet.sinir import il_poligonu, tkgm_ilceler, tkgm_mahalleler
from afet.yollar import OLAY_2021, OSM_ADLI_YOLLAR, SENARYO, SENARYO_OZETI
from hesap.dem_hidroloji import kopru_tunel, osm_cizgileri, raster_ornekle, yakin_mi, yol_noktalari

log = logging.getLogger("dogrulama")
CERCEVE = (26.90, 38.30, 27.35, 38.55)       # İzmir merkez ilçeleri (OSM çıkarımı)

# Olaya yakın senaryolar: 2 Şubat 2021'de merkezde 100–140 mm, 8–14 saatte
# düştü. Senaryolarda 6 ve 24 saat var; ikisi aralığı kuşatır. 50 mm / 1 saat
# yağışın en yoğun saatine bakar (kent drenajı ve alt geçitler için).
SENARYOLAR = ["50_1", "100_6", "150_6", "100_24", "150_24"]
ISLAK_DM = 1          # 10 cm
KAPALI_DM = 3         # 30 cm: araçla geçilemez (sel_senaryo_hazirla.YOL_KAPALI_M)
CADDE_EKLERI = ("Caddesi", "Bulvarı")
CADDE_MIN_M = 500     # karşılaştırılan caddeler en az bu uzunlukta
M_DERECE = 111_320.0


def osm_adli_cizgiler():
    """Çerçevedeki adlı yollar ve (adlı ya da adsız) dereler — önbellekli."""
    if os.path.exists(OSM_ADLI_YOLLAR):
        return json_oku(OSM_ADLI_YOLLAR)["features"]
    log.info("OSM dosyasından adlı yollar çıkarılıyor (~1.5 dk)…")
    out = [{"type": "Feature",
            "properties": {"tur": tur, "ad": t.get("name"), "highway": t.get("highway")},
            "geometry": {"type": "LineString", "coordinates": xy}}
           for tur, t, xy in osm_cizgileri(CERCEVE, _adli_yol_ya_da_dere)]
    json_yaz(OSM_ADLI_YOLLAR, {"type": "FeatureCollection", "features": out})
    return out


def _adli_yol_ya_da_dere(t):
    if "highway" in t:
        return "yol" if "name" in t else None
    return "dere" if t.get("waterway") in ("river", "stream", "canal", "drain", "ditch") else None


def ilceler_ve_mahalleler(ilce_adlari):
    """{ilçe: poligon}, [(ilçe, mahalle, poligon)] — TKGM."""
    ilce_id, ilce = {}, {}
    for kimlik, ad, geom in tkgm_ilceler():
        if ad in ilce_adlari:
            ilce_id[kimlik] = ad
            ilce[ad] = shapely.geometry.shape(geom)
    mahalleler = [(ilce_id[k], ad, shapely.geometry.shape(geom))
                  for k, ad, geom in tkgm_mahalleler() if k in ilce_id]
    return ilce, mahalleler


def uzunluk_m(g):
    """Derece geometrinin yaklaşık metre uzunluğu (enlem düzeltmeli)."""
    k = np.cos(np.radians(g.centroid.y))
    return shapely.length(shapely.transform(g, lambda c: c * [k, 1.0])) * M_DERECE


def adli_caddeler(cizgiler, ilce, ekler=()):
    """(ilçe, ad) → ilçe sınırına kırpılmış birleşik çizgi; Cadde/Bulvar ve
    haberdeki adı OSM'de farklı geçen yollar (ekler)."""
    gruplar = {}
    for f in cizgiler:
        p = f["properties"]
        if p["tur"] == "yol" and p["ad"] and (p["ad"].endswith(CADDE_EKLERI) or p["ad"] in ekler):
            gruplar.setdefault(p["ad"], []).append(shapely.geometry.shape(f["geometry"]))
    out = {}
    for ad, parca in gruplar.items():
        g = shapely.union_all(parca)
        for ilce_ad, poli in ilce.items():
            k = shapely.intersection(g, poli)
            if not k.is_empty and uzunluk_m(k) >= CADDE_MIN_M:
                out[(ilce_ad, ad)] = k
    return out


def cizgi_skoru(dizi, tr, g, haric_cizgiler):
    """Çizgi boyunca ~25 m'de bir: en derin nokta (m), 30 cm+ var mı,
    10 cm+ ıslak pay, düz ova (belirsiz) var mı. Köprü üstü sayılmaz."""
    parca = list(getattr(g, "geoms", [g]))
    parca = [p for p in parca if p.geom_type == "LineString"]
    if not parca:
        return None
    _, x, y, _ = yol_noktalari(shapely.to_wkb(parca).tolist())
    dm = raster_ornekle(dizi, tr, x, y)
    dm[yakin_mi(x, y, haric_cizgiler, 0.00012)] = 0
    belirsiz = dm == BELIRSIZ
    d = np.where(belirsiz, 0, dm)
    return {"en_derin_m": round(float(d.max()) / 10, 1),
            "kapali": bool((d >= KAPALI_DM).any()),
            "islak_pay": round(float(((d >= ISLAK_DM) | belirsiz).mean()), 3),
            "belirsiz": bool(belirsiz.any())}


def auc(poz, neg):
    """Mann–Whitney AUC (beraberlik yarım sayılır)."""
    poz, neg = np.asarray(poz, float), np.asarray(neg, float)
    if not len(poz) or not len(neg):
        return None
    buyuk = (poz[:, None] > neg[None, :]).sum() + 0.5 * (poz[:, None] == neg[None, :]).sum()
    return round(float(buyuk / (len(poz) * len(neg))), 2)


def yuzdelik(deger, nufus):
    nufus = np.asarray(nufus, float)
    return round(float(((nufus < deger).sum() + 0.5 * (nufus == deger).sum()) / len(nufus) * 100))


def dogrula(olay_yolu):
    olay = json_oku(olay_yolu)
    ozet = json_oku(SENARYO_OZETI)
    tr = Affine(ozet["dx"], 0, ozet["bati"], 0, ozet["dy"], ozet["kuzey"])
    npz = np.load(SENARYO)
    yerler = olay["yerler"]
    ilce_adlari = sorted({y["ilce"] for y in yerler} | {"Bornova"})
    ilce, mahalleler = ilceler_ve_mahalleler(ilce_adlari)
    cizgiler = osm_adli_cizgiler()
    # haberdeki ad OSM'de farklıysa (ör. "Caddesi" ↔ "Sokak") osm_ad kullanılır
    for y in yerler:
        y["osm"] = y.get("osm_ad", y["ad"])
    caddeler = adli_caddeler(cizgiler, ilce, {y["osm"] for y in yerler if y["tur"] == "cadde"})
    kopru, _, uzun_tunel = kopru_tunel(il_poligonu())
    haric = kopru + uzun_tunel

    shape = npz[f"d_{SENARYOLAR[0]}"].shape
    mah_et = rasterize([(g, i + 1) for i, (_, _, g) in enumerate(mahalleler)],
                       out_shape=shape, transform=tr, fill=0, dtype="int32")
    mah_n = np.bincount(mah_et.ravel(), minlength=len(mahalleler) + 1)
    mah_anahtar = {(i, m): k for k, (i, m, _) in enumerate(mahalleler)}

    eksik = [y for y in yerler if
             (y["tur"] == "mahalle" and (y["ilce"], y["ad"]) not in mah_anahtar) or
             (y["tur"] == "cadde" and (y["ilce"], y["osm"]) not in caddeler)]
    if eksik:
        raise ValueError(f"Haritada bulunamayan yerler: {[(y['ilce'], y['ad']) for y in eksik]}")

    sonuc = {"olay": olay["olay"], "ilceler": ilce_adlari, "senaryolar": {}}
    for sen in SENARYOLAR:
        dizi = npz[f"d_{sen}"]
        # iki ölçü: düz ova (gri, "su gelir") dahil ve yalnız hesaplanan derinlik
        derin = (dizi >= ISLAK_DM) & (dizi != BELIRSIZ)
        islak = derin | (dizi == BELIRSIZ)
        pay = lambda m: (np.bincount(mah_et.ravel(), weights=m.ravel(), minlength=len(mahalleler) + 1)
                         / np.maximum(mah_n, 1))[1:]
        mah_pay, mah_derin = pay(islak), pay(derin)
        gecerli = mah_n[1:] > 0                          # ızgaraya düşen mahalleler
        cadde_skor = {k: cizgi_skoru(dizi, tr, g, haric) for k, g in caddeler.items()}

        satirlar = []
        poz_mah, poz_cadde = set(), set()
        for y in yerler:
            s = {"tur": y["tur"], "ilce": y["ilce"], "ad": y["ad"], "neden": y["neden"]}
            if y["tur"] == "mahalle":
                k = mah_anahtar[(y["ilce"], y["ad"])]
                poz_mah.add(k)
                s.update(islak_pay=round(float(mah_pay[k]), 3),
                         yuzdelik=yuzdelik(mah_pay[k], mah_pay[gecerli]),
                         derin_pay=round(float(mah_derin[k]), 3),
                         derin_yuzdelik=yuzdelik(mah_derin[k], mah_derin[gecerli]))
            elif y["tur"] == "cadde":
                poz_cadde.add((y["ilce"], y["osm"]))
                s.update(cadde_skor[(y["ilce"], y["osm"])])
            elif y["tur"] == "dere":
                g = shapely.union_all([shapely.geometry.shape(f["geometry"]) for f in cizgiler
                                       if f["properties"]["tur"] == "dere" and f["properties"]["ad"] == y["ad"]])
                s.update(cizgi_skoru(dizi, tr, g, haric) or {"bulunamadi": True})
            elif y["tur"] == "alt_gecit":
                s.update(alt_gecit_dolu=ozet["senaryolar"][sen]["alt_gecit_dolu"] > 0)
            satirlar.append(s)

        neg_mah = [mah_pay[k] for k in range(len(mahalleler)) if gecerli[k] and k not in poz_mah]
        neg_cadde = [v for k, v in cadde_skor.items() if k not in poz_cadde and v]
        poz_c = [s for s in satirlar if s["tur"] == "cadde"]
        # cadde için "yalnız derinlik": 30 cm+ nokta (düz ova sayılmaz) zaten kapali
        sonuc["senaryolar"][sen] = {
            "yerler": satirlar,
            "mahalle_auc": auc([mah_pay[k] for k in poz_mah], neg_mah),
            "mahalle_auc_yalniz_derinlik": auc(
                [mah_derin[k] for k in poz_mah],
                [mah_derin[k] for k in range(len(mahalleler)) if gecerli[k] and k not in poz_mah]),
            "mahalle_sayisi": {"haber": len(poz_mah), "oteki": len(neg_mah)},
            "mahalle_islak_pay_medyan": {"haber": round(float(np.median([mah_pay[k] for k in poz_mah])), 3),
                                         "oteki": round(float(np.median(neg_mah)), 3)},
            "cadde_kapali_oran": {"haber": round(sum(s["kapali"] for s in poz_c) / len(poz_c), 2),
                                  "oteki": round(sum(v["kapali"] for v in neg_cadde) / len(neg_cadde), 2)},
            "cadde_sayisi": {"haber": len(poz_c), "oteki": len(neg_cadde)},
            "cadde_auc": auc([s["en_derin_m"] for s in poz_c], [v["en_derin_m"] for v in neg_cadde]),
        }
    return sonuc


def yazdir(sonuc):
    print(f"\n{sonuc['olay']} — ilçeler: {', '.join(sonuc['ilceler'])}")
    for sen, o in sonuc["senaryolar"].items():
        p, sure = sen.split("_")
        print(f"\n=== {p} mm / {sure} saat ===")
        print(f"Mahalle AUC {o['mahalle_auc']}, yalnız derinlik {o['mahalle_auc_yalniz_derinlik']} (haber {o['mahalle_sayisi']['haber']}, öteki {o['mahalle_sayisi']['oteki']}); "
              f"ıslak pay medyanı haber {o['mahalle_islak_pay_medyan']['haber']:.1%} / öteki {o['mahalle_islak_pay_medyan']['oteki']:.1%}")
        print(f"Cadde: 30 cm+ noktası olan haber {o['cadde_kapali_oran']['haber']:.0%} / öteki "
              f"{o['cadde_kapali_oran']['oteki']:.0%} ({o['cadde_sayisi']['oteki']} cadde), AUC {o['cadde_auc']}")
        for s in o["yerler"]:
            if s["tur"] == "mahalle":
                ek = (f"ıslak pay {s['islak_pay']:.1%} (yüzdelik {s['yuzdelik']}), "
                      f"yalnız derinlik {s['derin_pay']:.1%} (yüzdelik {s['derin_yuzdelik']})")
            elif s["tur"] == "alt_gecit":
                ek = "alt geçitler dolu" if s["alt_gecit_dolu"] else "alt geçitler kuru (drenaj yetiyor)"
            elif s.get("bulunamadi"):
                ek = "OSM'de yok"
            else:
                ek = (f"en derin {s['en_derin_m']} m, ıslak pay {s['islak_pay']:.0%}"
                      + (", düz ova" if s["belirsiz"] else ""))
            print(f"  {s['tur']:9} {s['ilce']:10} {s['ad']:22} [{s['neden']:11}] {ek}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    olay_yolu = sys.argv[1] if len(sys.argv) > 1 else OLAY_2021
    sonuc = dogrula(olay_yolu)
    cikti = os.path.join(os.path.dirname(olay_yolu),
                         os.path.basename(olay_yolu).replace("olay_", "sonuc_"))
    json_yaz(cikti, sonuc, okunur=True)
    yazdir(sonuc)
    print(f"\nYazıldı: {cikti}")


if __name__ == "__main__":
    main()
