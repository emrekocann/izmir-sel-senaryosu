"""Sunucusuz yayın sayfasının (docs/, GitHub Pages) verisini üretir.

Sayfa canlı sunucu ve veritabanı olmadan çalışsın diye her şey önceden
hesaplanıp dosyaya yazılır:

  docs/veri/senaryo/<mm>_<saat>.png   24 senaryonun su derinliği görüntüsü
  docs/veri/vitrin.json               senaryo özetleri, harita sınırları,
                                      2 Şubat 2021 doğrulama yerleri (geometri +
                                      modelin sonucu), örnek tahliye rotaları
  docs/veri/izmir_sinir.geojson       il sınırı

Çalıştırma: venv/bin/python -m hesap.vitrin_hazirla
Önkoşul: sel_model/senaryo.npz, dogrulama/sonuc_2021_02_02.json
(hesap/sel_dogrulama.py), yol ağı ve sel_senaryo_su tablosu, DB açık.
"""
import asyncio
import io
import json
import logging
import os
import shutil

import numpy as np
import shapely
from affine import Affine
from PIL import Image
from rasterio.features import rasterize

import sel_senaryo
from database import db
from repository import AfetRepository
from hesap.sel_dogrulama import adli_caddeler, ilceler_ve_mahalleler, osm_adli_cizgiler

log = logging.getLogger("vitrin")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # proje kökü
CIKTI = os.path.join(BASE_DIR, "docs", "veri")
OLAY = os.path.join(BASE_DIR, "dogrulama", "olay_2021_02_02.json")
SONUC = os.path.join(BASE_DIR, "dogrulama", "sonuc_2021_02_02.json")

# 2 Şubat 2021'in yağışını (merkezde 8–14 saatte 100–140 mm) kuşatan senaryolar
OLAY_SENARYOLARI = ["100_6", "150_24"]
# Haberdeki yer "yakalandı" sayılır: mahalle modelde en ıslak çeyrekte, cadde /
# dere hattında 30 cm+ su noktası var — olay senaryolarından herhangi birinde
MAHALLE_YUZDELIK = 75
ROTA_BASLANGIC = {"ad": "Bornova", "lat": 38.452, "lon": 27.205}
SADELESTIR = 0.0002          # ~20 m: sayfa için geometri sadeleştirme


def il_maskesi(boyut, bounds):
    """Görüntü ızgarasında (satırlar Mercator aralıklı) il sınırı içi maskesi.
    Canlı uygulamada bu kırpmayı tarayıcı yapar; burada dosyaya işlenir
    (yoksa "düz ova" grisi körfezin üstünü de boyar)."""
    w, h = boyut
    (guney, bati), (kuzey, dogu) = bounds
    merc = lambda lat: np.degrees(np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)))
    sinir = shapely.geometry.shape(json.load(open(
        os.path.join(BASE_DIR, "static", "izmir_sinir.geojson"), encoding="utf-8"))["features"][0]["geometry"])
    sinir_m = shapely.transform(sinir, lambda c: np.column_stack([c[:, 0], merc(c[:, 1])]))
    tr = Affine((dogu - bati) / w, 0, bati, 0, (merc(guney) - merc(kuzey)) / h, merc(kuzey))
    return rasterize([(sinir_m, 1)], out_shape=(h, w), transform=tr, fill=0, all_touched=True,
                     dtype="uint8").astype(bool)


def kirpili_png(png, maske_onbellek, bounds):
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    if "m" not in maske_onbellek:
        maske_onbellek["m"] = il_maskesi(im.size, bounds)
    a = np.array(im)
    a[~maske_onbellek["m"], 3] = 0
    # az renkli görüntü: palete indirilince dosya küçülür
    out = io.BytesIO()
    Image.fromarray(a).quantize(colors=16, method=Image.Quantize.FASTOCTREE).save(out, "PNG", optimize=True)
    return out.getvalue()


def yakalandi(sonuc, tur, ilce, ad):
    for sen in OLAY_SENARYOLARI:
        s = next(y for y in sonuc["senaryolar"][sen]["yerler"]
                 if (y["tur"], y["ilce"], y["ad"]) == (tur, ilce, ad))
        if tur == "mahalle" and s["derin_yuzdelik"] >= MAHALLE_YUZDELIK:
            return True
        if tur in ("cadde", "dere") and (s.get("en_derin_m") or 0) >= 0.3:
            return True
        if tur == "alt_gecit" and s["alt_gecit_dolu"]:
            return True
    return False


def olay_yerleri():
    """Haberdeki yerler: geometri + modelin olay senaryolarındaki sonucu."""
    olay = json.load(open(OLAY, encoding="utf-8"))
    sonuc = json.load(open(SONUC, encoding="utf-8"))
    ilce, mahalleler = ilceler_ve_mahalleler({y["ilce"] for y in olay["yerler"]})
    mah = {(i, m): g for i, m, g in mahalleler}
    cizgiler = osm_adli_cizgiler()
    caddeler = adli_caddeler(cizgiler, ilce, {y.get("osm_ad", y["ad"]) for y in olay["yerler"]
                                              if y["tur"] == "cadde"})
    out = []
    for y in olay["yerler"]:
        if y["tur"] == "mahalle":
            g = mah[(y["ilce"], y["ad"])]
        elif y["tur"] == "cadde":
            g = caddeler[(y["ilce"], y.get("osm_ad", y["ad"]))]
        elif y["tur"] == "dere":
            g = shapely.union_all([shapely.geometry.shape(f["geometry"]) for f in cizgiler
                                   if f["properties"]["tur"] == "dere" and f["properties"]["ad"] == y["ad"]])
        else:
            g = None                     # alt geçit: OSM'de adıyla yok, yalnız listede
        olcum = {sen: {k: v for k, v in next(
            s for s in sonuc["senaryolar"][sen]["yerler"]
            if (s["tur"], s["ilce"], s["ad"]) == (y["tur"], y["ilce"], y["ad"])).items()
            if k in ("derin_pay", "derin_yuzdelik", "en_derin_m", "alt_gecit_dolu")}
            for sen in OLAY_SENARYOLARI}
        out.append({
            "tur": y["tur"], "ilce": y["ilce"], "ad": y["ad"], "neden": y["neden"],
            "anlatim": y["anlatim"], "kaynak": [olay["kaynaklar"][k] for k in y["kaynak"]],
            "yakalandi": yakalandi(sonuc, y["tur"], y["ilce"], y["ad"]), "olcum": olcum,
            "geometri": shapely.geometry.mapping(g.simplify(SADELESTIR)) if g is not None else None,
        })
    ozet = {sen: {k: sonuc["senaryolar"][sen][k] for k in
                  ("mahalle_auc_yalniz_derinlik", "cadde_auc", "cadde_kapali_oran",
                   "mahalle_sayisi", "cadde_sayisi")} for sen in sonuc["senaryolar"]}
    return out, ozet


async def ornek_rotalar():
    """Aynı başlangıçtan senaryosuz ve olay senaryolarında araç rotası."""
    senaryolar = sel_senaryo.ozet()["senaryolar"]
    out = []
    await db.connect()
    try:
        for sen in [None] + OLAY_SENARYOLARI:
            r = await AfetRepository.get_smart_routes(
                ROTA_BASLANGIC["lon"], ROTA_BASLANGIC["lat"], mode="drive", senaryo=sen,
                alt_gecit_dolu=bool(sen and senaryolar[sen]["alt_gecit_dolu"]))
            if r["status"] != "ok":
                raise RuntimeError(f"Rota hesaplanamadı ({sen}): {r}")
            a = r["toplanma_alani"]
            out.append({
                "senaryo": sen,
                "km": round(sum(s["length"] for s in r["segments"]) / 1000, 1),
                "hedef": {"adi": a["adi"], "ilce": a["ilce"], "mahalle": a["mahalle"],
                          "lat": a["lat"], "lon": a["lon"]},
                "su": r["senaryo"] and {k: r["senaryo"][k] for k in
                                        ("derin_yer", "sig_yer", "en_derin_m")},
                "cizgi": [[[round(x, 5), round(y, 5)] for x, y in s["geometry"]["coordinates"]]
                          for s in r["segments"]],
            })
    finally:
        await db.disconnect()
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    os.makedirs(os.path.join(CIKTI, "senaryo"), exist_ok=True)
    y = sel_senaryo.yanit()
    maske = {}
    for p in y["yagis_mm"]:
        for sure in y["sure_sa"]:
            with open(os.path.join(CIKTI, "senaryo", f"{p}_{sure}.png"), "wb") as f:
                f.write(kirpili_png(sel_senaryo.harita_png(p, sure), maske, y["bounds"]))
    shutil.copy(os.path.join(BASE_DIR, "static", "izmir_sinir.geojson"),
                os.path.join(CIKTI, "izmir_sinir.geojson"))
    yerler, dogrulama = olay_yerleri()
    vitrin = {
        "yagis_mm": y["yagis_mm"], "sure_sa": y["sure_sa"], "bounds": y["bounds"],
        "siniflar": y["siniflar"], "olay_senaryolari": OLAY_SENARYOLARI,
        "senaryolar": {k: {a: v[a] for a in ("su_alan_km2", "belirsiz_km2", "yol_kapali_km",
                                              "alt_gecit_dolu", "toplanma_etkilenen_sayi",
                                              "toplanma_toplam")}
                       for k, v in y["senaryolar"].items()},
        "yerler": yerler, "dogrulama": dogrulama,
        "rota_baslangic": ROTA_BASLANGIC, "rotalar": asyncio.run(ornek_rotalar()),
    }
    with open(os.path.join(CIKTI, "vitrin.json"), "w", encoding="utf-8") as f:
        json.dump(vitrin, f, ensure_ascii=False, separators=(",", ":"))
    boyut = sum(os.path.getsize(os.path.join(kok, d)) for kok, _, ds in os.walk(CIKTI) for d in ds)
    log.info("Yazıldı: %s — %d haber yeri (%d yakalandı), %d rota, toplam %.1f MB", CIKTI,
             len(yerler), sum(v["yakalandi"] for v in yerler), len(vitrin["rotalar"]), boyut / 1e6)


if __name__ == "__main__":
    main()
