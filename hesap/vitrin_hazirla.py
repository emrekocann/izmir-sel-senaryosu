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
import logging
import os
import shutil

import numpy as np
import shapely
from affine import Affine
from PIL import Image
from rasterio.features import rasterize

from afet.dosya import json_oku, json_yaz
from afet.izgara import mercator_y
from afet.sel.senaryo import BELIRSIZ, senaryolar
from afet.sinir import il_poligonu
from afet.veritabani.baglanti import db
from afet.veritabani.depo import AfetDeposu, depo
from afet.yollar import IL_SINIRI, OLAY_2021, SITE_VERI_DIR, SONUC_2021, VITRIN
from hesap import gunlugu_kur
from hesap.sel_dogrulama import adli_caddeler, ilceler_ve_mahalleler, osm_adli_cizgiler

log = logging.getLogger("vitrin")

# 2 Şubat 2021'in yağışını (merkezde 8–14 saatte 100–140 mm) kuşatan senaryolar
OLAY_SENARYOLARI = ["100_6", "150_24"]
# Doğrulama puanlarının aralığı bu senaryolardan verilir (olaya yakın yağışlar;
# 50 mm / 1 saat yalnız en yoğun saati temsil eder, aralığa girmez)
DOGRULAMA_SENARYOLARI = ["100_6", "150_6", "100_24", "150_24"]
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
    merc = lambda lat: np.degrees(mercator_y(lat))             # derece ölçeğinde Mercator y
    sinir = il_poligonu()
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
    olay = json_oku(OLAY_2021)
    sonuc = json_oku(SONUC_2021)
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


def merkez_alanlari(ilce_adlari):
    """Olayın yaşandığı ilçelerde olay senaryolarının su alanı (km²):
    {senaryo: {su_30, su_10, belirsiz}} ve bölgenin (alan km², geometri)."""
    ozet = senaryolar.ozet()
    ilce, _ = ilceler_ve_mahalleler(set(ilce_adlari))
    bolge = shapely.union_all(list(ilce.values()))
    tr = Affine(ozet["dx"], 0, ozet["bati"], 0, ozet["dy"], ozet["kuzey"])
    npz = senaryolar.veri
    shape = npz[f"d_{OLAY_SENARYOLARI[0]}"].shape
    icinde = rasterize([(bolge, 1)], out_shape=shape, transform=tr, fill=0, dtype="uint8").astype(bool)
    lat = tr.f + (np.arange(shape[0]) + 0.5) * tr.e
    hucre_km2 = np.repeat((abs(tr.e) * 111.32 * tr.a * 111.32 * np.cos(np.radians(lat)))[:, None],
                          shape[1], axis=1)
    out = {}
    for sen in OLAY_SENARYOLARI:
        d = npz[f"d_{sen}"]
        b = d == BELIRSIZ
        out[sen] = {"su_30_km2": round(float(hucre_km2[icinde & ~b & (d >= 3)].sum()), 1),
                    "su_10_km2": round(float(hucre_km2[icinde & ~b & (d >= 1)].sum()), 1),
                    "belirsiz_km2": round(float(hucre_km2[icinde & b].sum()), 1)}
    return out, round(float(hucre_km2[icinde].sum())), bolge


async def veritabani_ozetleri(bolge):
    """Örnek rotalar (aynı başlangıçtan senaryosuz ve olay senaryolarında araç
    rotası) ve olay ilçelerinde su altında kalan toplanma alanı / yol parçası
    sayıları — tek bağlantıda."""
    ozetler = senaryolar.ozet()["senaryolar"]
    out, etki = [], {}
    icinde = "ST_Within({}, ST_SetSRID(ST_GeomFromWKB(decode($1, 'hex')), 4326))"
    wkb = shapely.to_wkb(bolge, hex=True)
    K = AfetDeposu.SENARYO_KAPALI_M
    async with db.oturum():
        async with db.baglan() as c:
            toplanma = await c.fetchval(
                f"SELECT count(*) FROM toplanma_alanlari WHERE {icinde.format('konum')}", wkb)
            for sen in OLAY_SENARYOLARI:
                t = await c.fetchrow(f"""
                    SELECT count(*) FILTER (WHERE s.derinlik >= {K}) AS su,
                           count(*) FILTER (WHERE s.derinlik < {K} AND s.belirsiz) AS belirsiz
                    FROM sel_senaryo_su s JOIN toplanma_alanlari a ON a.id = s.kimlik
                    WHERE s.katman = 'toplanma' AND s.senaryo = $2 AND {icinde.format('a.konum')}""",
                    wkb, sen)
                yol = await c.fetchval(f"""
                    SELECT count(*) FROM sel_senaryo_su s JOIN izmir_roads_noded rn ON rn.id = s.kimlik
                    WHERE s.katman = 'drive' AND s.senaryo = $2 AND s.derinlik >= {K}
                      AND {icinde.format('rn.the_geom')}""", wkb, sen)
                etki[sen] = {"toplanma_su": t["su"], "toplanma_belirsiz": t["belirsiz"],
                             "yol_parcasi_su": yol}
        for sen in [None] + OLAY_SENARYOLARI:
            r = await depo.akilli_rota(
                ROTA_BASLANGIC["lon"], ROTA_BASLANGIC["lat"], mode="drive", senaryo=sen,
                alt_gecit_dolu=bool(sen and ozetler[sen]["alt_gecit_dolu"]))
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
    return out, etki, toplanma


def main():
    gunlugu_kur()
    os.makedirs(os.path.join(SITE_VERI_DIR, "senaryo"), exist_ok=True)
    y = senaryolar.yanit()
    maske = {}
    for p in y["yagis_mm"]:
        for sure in y["sure_sa"]:
            with open(os.path.join(SITE_VERI_DIR, "senaryo", f"{p}_{sure}.png"), "wb") as f:
                f.write(kirpili_png(senaryolar.harita_png(p, sure), maske, y["bounds"]))
    shutil.copy(IL_SINIRI, os.path.join(SITE_VERI_DIR, "izmir_sinir.geojson"))
    yerler, dogrulama = olay_yerleri()
    ilceler = json_oku(SONUC_2021)["ilceler"]
    alan, bolge_km2, bolge = merkez_alanlari(ilceler)
    rotalar, etki, toplanma = asyncio.run(veritabani_ozetleri(bolge))
    vitrin = {
        "yagis_mm": y["yagis_mm"], "sure_sa": y["sure_sa"], "bounds": y["bounds"],
        "siniflar": y["siniflar"], "olay_senaryolari": OLAY_SENARYOLARI,
        "senaryolar": {k: {a: v[a] for a in ("su_alan_km2", "belirsiz_km2", "yol_kapali_km",
                                              "alt_gecit_dolu", "toplanma_etkilenen_sayi",
                                              "toplanma_toplam")}
                       for k, v in y["senaryolar"].items()},
        "yerler": yerler, "dogrulama": dogrulama, "dogrulama_senaryolari": DOGRULAMA_SENARYOLARI,
        # olayın yaşandığı ilçelerde olay senaryolarının etkisi
        "merkez": {"ilceler": ilceler, "km2": bolge_km2, "toplanma": toplanma,
                   "senaryolar": {sen: {**alan[sen], **etki[sen]} for sen in OLAY_SENARYOLARI}},
        "rota_baslangic": ROTA_BASLANGIC, "rotalar": rotalar,
    }
    json_yaz(VITRIN, vitrin)
    boyut = sum(os.path.getsize(os.path.join(kok, d)) for kok, _, ds in os.walk(SITE_VERI_DIR) for d in ds)
    log.info("Yazıldı: %s — %d haber yeri (%d yakalandı), %d rota, toplam %.1f MB", SITE_VERI_DIR,
             len(yerler), sum(v["yakalandi"] for v in yerler), len(vitrin["rotalar"]), boyut / 1e6)


if __name__ == "__main__":
    main()
