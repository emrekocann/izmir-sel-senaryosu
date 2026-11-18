"""İlçe-gün eğitim veri seti: İzmir İtfaiyesi su baskını çağrıları × yağış.

Soru: "Bir ilçede bir günde X mm yağış düşerse itfaiyeye kaç su baskını
çağrısı gelir?" Bu soruyu öğrenen bir regresyon modelinin (OLS, sonra GWR)
eğitim verisi burada kurulur; model ayrı betikte.

Kaynaklar (hepsi açık):
  • Çağrılar — İBB Açık Veri, "İzmir İtfaiyesi Kontrol, Emniyet, Tedbir ve
    Vatandaşa Verilen Hizmetlerin İstatistiği" (2019–), yıllık Excel. Her satır
    bir hizmet: tarih, saat, hizmet tipi, ilçe. Mahalle / adres YOK; bu yüzden
    birim ilçedir. Su ile ilgili hizmet tipleri CAGRI_TURLERI'nde.
  • Yağış — Open-Meteo geçmiş arşivi (ERA5 / ERA5-Land yeniden analizi,
    saatlik, ~10–25 km). Her ilçe için tek nokta: ilçedeki yapılaşmış
    hücrelerin ağırlık merkezi (çağrılar kentten gelir; Ödemiş gibi geniş bir
    ilçenin geometrik merkezi dağda kalır). Yeniden analiz yerel sağanağı
    yumuşatır: 2 Şubat 2021'de merkezde ölçülen ~128 mm'nin ~70 mm'sini verir.
    Model bu yüzden "ölçülen yağış" değil "arşivdeki yağış" ile kurulur.
  • İlçe nüfusu — İBB Açık Veri, "İzmir İlçelerinin Cinsiyete Göre Nüfus
    Bilgileri" (TÜİK ADNKS). Çağrı sayısı suyun yanında insan sayısına da bağlıdır.
  • Yapılaşma payı — ESA WorldCover (sel_veri/cn_60m_v3.npz, sel senaryosu
    hesabının ara çıktısı) ilçe sınırlarıyla (TKGM).

Gün: takvim günü (Europe/Istanbul). Gece yarısını aşan fırtınalar iki güne
bölünür; bu yüzden önceki günün yağışı ayrı kolondur.

Çıktılar (depoda):
  egitim/ilce_gun.csv  ilçe × gün: çağrı sayıları ve yağış özellikleri
  egitim/ilce.csv      ilçe başına sabit özellikler (nüfus, kent alanı, yağış noktası)

Çalıştırma: venv/bin/python -m hesap.ilce_gun
(ilk çalıştırmada ~10 MB Excel ve yağış arşivi indirilir, itfaiye_veri/ önbelleğine)
"""
import logging
import os
import re
import unicodedata
import urllib.parse

import numpy as np
import pandas as pd
import shapely

from afet import ag
from afet.sinir import tkgm_ilceler
from afet.yollar import CN_DOSYASI, DEM_TIF, EGITIM_DIR, ITFAIYE_HAM_DIR

log = logging.getLogger("ilce_gun")
HAM_DIR = ITFAIYE_HAM_DIR                                  # indirilen ham dosyalar (depoda değil)
CIKTI_DIR = EGITIM_DIR
ILCE_GUN_CSV = os.path.join(CIKTI_DIR, "ilce_gun.csv")
ILCE_CSV = os.path.join(CIKTI_DIR, "ilce.csv")

CKAN = "https://acikveri.bizizmir.com/api/3/action/package_show?id="
HIZMET_PAKETI = "izmir-itfaiyesi-kontrol-emniyet-tedbir-ve-vatandasa-verilen-hizmetlerin-istatistigi"
NUFUS_PAKETI = "izmir-ilcelerinin-cinsiyete-gore-nufus-bilgileri"
ARSIV_URL = "https://archive-api.open-meteo.com/v1/archive"

# Su ile ilgili hizmet tipleri → kolon. "kontrol": su baskını yerinde
# kontrol / emniyet / tetkik; "cekme": pompayla su çekme (bodrum, alt geçit).
# Eşleme büyük harf ve Türkçe karakterden bağımsızdır (anahtar()).
CAGRI_TURLERI = {
    "kontrol": ("SU BASKINI",),
    "cekme": ("SU CEKME",),
}
ILK_YIL = 2019


def anahtar(metin) -> str:
    """Ad karşılaştırma anahtarı: Türkçe büyük/küçük harf ve aksan farkı,
    boşluklar yok sayılır ('KARŞIYAKA' = 'Karşiyaka' = 'karsiyaka')."""
    s = str(metin).strip().replace("İ", "i").replace("I", "ı").lower()
    s = s.replace("ı", "i")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


def cagri_turu(hizmet_tipi):
    """Hizmet tipinin CAGRI_TURLERI'ndeki kolonu; su ile ilgisizse None."""
    a = anahtar(hizmet_tipi).upper()
    for kolon, onekler in CAGRI_TURLERI.items():
        if any(a.startswith(o) for o in onekler):
            return kolon
    return None


# ── İndirme ─────────────────────────────────────────────────────────────────

def _paket_kaynaklari(paket):
    return ag.json_getir(CKAN + paket, os.path.join(HAM_DIR, f"{paket}.json"))["result"]["resources"]


def hizmet_dosyalari():
    """Yıllık hizmet çizelgeleri: [(yıl, yerel yol)], indirilmiş."""
    out = []
    for r in _paket_kaynaklari(HIZMET_PAKETI):
        yil = re.search(r"(20\d\d)", r.get("name") or r["url"])
        if not yil or int(yil.group(1)) < ILK_YIL:
            continue
        uzanti = ".xls" if r["url"].lower().endswith(".xls") else ".xlsx"
        yol = os.path.join(HAM_DIR, f"hizmet_{yil.group(1)}{uzanti}")
        ag.getir(r["url"], yol, dogrula=_excel_mi)
        out.append((int(yil.group(1)), yol))
    return sorted(out)


def _excel_mi(govde):
    """XLSX bir zip dosyasıdır; eski XLS bir OLE dosyası (hata sayfası değil)."""
    if not (govde.startswith(b"PK") or govde.startswith(b"\xd0\xcf\x11\xe0")):
        raise ValueError("Excel değil")


# ── Çağrılar ────────────────────────────────────────────────────────────────

def _kolon(df, onek):
    """Yıldan yıla adı değişen kolon (ör. 'VARIS_SURESI (DK.)')."""
    for k in df.columns:
        if anahtar(k).upper().startswith(onek):
            return k
    raise KeyError(f"{onek} kolonu yok: {list(df.columns)}")


def tarih_coz(seri):
    """Çizelgelerdeki tarih: bazı yıllarda Excel tarihi ('2023-01-01 00:00:00'),
    bazılarında metin '01.10.2024' (gün.ay.yıl — ay.gün değil). İkisi de
    açıkça çözülür; tahmin yürütülmez."""
    s = seri.astype(str).str.strip()
    noktali = s.str.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}")
    out = pd.to_datetime(s.where(~noktali), format="ISO8601", errors="coerce")
    out = out.fillna(pd.to_datetime(s.where(noktali), format="%d.%m.%Y", errors="coerce"))
    return out.dt.date


def hizmet_tablosu(yol):
    """Çizelgenin veri sayfası. Bazı yıllarda dosyada açılır liste sayfası da
    vardır (2023: 'Sheet2'); başlığında HIZMET_TIPI olan ilk sayfa alınır."""
    x = pd.ExcelFile(yol)
    for sayfa in x.sheet_names:
        ham = x.parse(sayfa, header=None, dtype=str, nrows=10)
        for i, satir in ham.iterrows():
            if any(anahtar(v).upper() == "HIZMET_TIPI" for v in satir if isinstance(v, str)):
                return x.parse(sayfa, header=i, dtype=str)
    raise ValueError(f"{yol}: HIZMET_TIPI başlıklı sayfa yok")


def cagrilari_oku(dosyalar, ilce_adlari):
    """Su ile ilgili çağrılar: DataFrame(gun, saat, ilce, tur). ilce_adlari:
    anahtar → TKGM ilçe adı; eşleşmeyen ilçe satırları sayılıp atılır."""
    parcalar = []
    for yil, yol in dosyalar:
        df = hizmet_tablosu(yol)
        tip, ilce, tarih, saat = (_kolon(df, k) for k in ("HIZMET_TIPI", "ILCE", "TARIH", "SAAT"))
        df = pd.DataFrame({"tur": df[tip].map(cagri_turu), "ilce_ham": df[ilce],
                           "gun": tarih_coz(df[tarih]),
                           "saat": pd.to_numeric(df[saat].str[:2], errors="coerce")})
        su = df[df.tur.notna()].copy()
        su["ilce"] = su.ilce_ham.map(lambda x: ilce_adlari.get(anahtar(x)))
        disarida = su.ilce.isna() | su.gun.isna()
        if disarida.any():
            log.warning("%d: %d su çağrısı eşleşmedi (ilçe/tarih): %s", yil, int(disarida.sum()),
                        su.loc[disarida, "ilce_ham"].value_counts().head(5).to_dict())
        su = su[~disarida]
        log.info("%d: %d satır, %d su çağrısı", yil, len(df), len(su))
        parcalar.append(su[["gun", "saat", "ilce", "tur"]])
    return pd.concat(parcalar, ignore_index=True)


# ── İlçeler ─────────────────────────────────────────────────────────────────

def ilceler():
    """TKGM ilçeleri: [(ad, poligon)]."""
    return [(ad, shapely.geometry.shape(geom)) for _, ad, geom in tkgm_ilceler()]


def kent_ozellikleri(ilce_listesi):
    """İlçe başına yapılaşmış alan (km²), payı ve yapılaşmış hücrelerin ağırlık
    merkezi (yağış noktası). ESA WorldCover payı, 60 m sel ızgarasında."""
    import rasterio
    from rasterio.features import rasterize
    with rasterio.open(DEM_TIF) as ds:
        tr, shape = ds.transform, (ds.height, ds.width)
    kent = np.load(CN_DOSYASI)["kent"]
    if kent.shape != shape:
        raise ValueError(f"CN ızgarası {kent.shape}, DEM {shape}: sel_senaryo_hazirla yeniden çalıştırılmalı")
    et = rasterize([(g, i + 1) for i, (_, g) in enumerate(ilce_listesi)], out_shape=shape,
                   transform=tr, fill=0, dtype="int32")
    rows, cols = np.indices(shape)
    lat_satir = tr.f + (np.arange(shape[0]) + 0.5) * tr.e
    hucre_km2 = (abs(tr.e) * 111.32) * (tr.a * 111.32 * np.cos(np.radians(lat_satir)))
    alan = np.repeat(hucre_km2[:, None], shape[1], axis=1)
    n = len(ilce_listesi) + 1
    toplam = np.bincount(et.ravel(), weights=alan.ravel(), minlength=n)
    k_alan = np.bincount(et.ravel(), weights=(kent * alan).ravel(), minlength=n)
    w = (kent * alan).ravel()
    lon = np.bincount(et.ravel(), weights=w * (tr.c + (cols.ravel() + 0.5) * tr.a), minlength=n)
    lat = np.bincount(et.ravel(), weights=w * (tr.f + (rows.ravel() + 0.5) * tr.e), minlength=n)
    out = []
    for i, (ad, g) in enumerate(ilce_listesi, start=1):
        if k_alan[i] > 0:
            nokta = (lon[i] / k_alan[i], lat[i] / k_alan[i])
        else:
            p = g.representative_point()
            nokta = (p.x, p.y)
        out.append({"ilce": ad, "alan_km2": round(float(toplam[i]), 1),
                    "kent_km2": round(float(k_alan[i]), 2),
                    "kent_payi": round(float(k_alan[i] / max(toplam[i], 1e-9)), 4),
                    "yagis_lon": round(float(nokta[0]), 4), "yagis_lat": round(float(nokta[1]), 4)})
    return pd.DataFrame(out)


def nufus(ilce_adlari):
    """İlçe nüfusu (en son yıl): Series ilce → kişi."""
    r = next(r for r in _paket_kaynaklari(NUFUS_PAKETI) if (r.get("format") or "").upper() == "CSV")
    yol = os.path.join(HAM_DIR, "ilce_nufus.csv")
    ag.getir(r["url"], yol)
    df = pd.read_csv(yol, sep=";", encoding="utf-8-sig", dtype={"ERKEK": float, "KADIN": float})
    df = df[df.TARIH == df.TARIH.max()]
    df["ilce"] = df.ILCE_ADI.map(lambda x: ilce_adlari.get(anahtar(x)))
    if df.ilce.isna().any():
        raise ValueError(f"Nüfusta eşleşmeyen ilçe: {df.loc[df.ilce.isna(), 'ILCE_ADI'].tolist()}")
    log.info("Nüfus yılı: %s", df.TARIH.max())
    return (df.ERKEK + df.KADIN).groupby(df.ilce).sum().rename("nufus").astype(int), int(df.TARIH.max())


# ── Yağış ───────────────────────────────────────────────────────────────────

def yagis_arsivi(ilce_df, bas, bit):
    """Her ilçe noktası için saatlik yağış (mm): DataFrame(ilce, zaman, mm).
    Open-Meteo arşivi çok noktayı tek istekte verir; yıl yıl istenir ve önbelleklenir."""
    parcalar = []
    for yil in range(bas.year, bit.year + 1):
        b = max(bas, pd.Timestamp(f"{yil}-01-01").date())
        s = min(bit, pd.Timestamp(f"{yil}-12-31").date())
        q = urllib.parse.urlencode({
            "latitude": ",".join(f"{v:.4f}" for v in ilce_df.yagis_lat),
            "longitude": ",".join(f"{v:.4f}" for v in ilce_df.yagis_lon),
            "start_date": b.isoformat(), "end_date": s.isoformat(),
            "hourly": "precipitation", "timezone": "Europe/Istanbul"})
        veri = ag.json_getir(f"{ARSIV_URL}?{q}", os.path.join(HAM_DIR, f"yagis_{yil}_{b}_{s}.json"),
                             timeout=180)
        veri = veri if isinstance(veri, list) else [veri]
        for ad, v in zip(ilce_df.ilce, veri):
            parcalar.append(pd.DataFrame({"ilce": ad, "zaman": pd.to_datetime(v["hourly"]["time"]),
                                          "mm": v["hourly"]["precipitation"]}))
        log.info("Yağış %d: %s – %s", yil, b, s)
    return pd.concat(parcalar, ignore_index=True)


def gunluk_yagis(saatlik):
    """Saatlik yağıştan ilçe-gün özellikleri: günlük toplam, en yoğun saat,
    en yoğun 3 saat, önceki gün, önceki 3 günün (toprak doygunluğu) ve önceki 7
    günün toplamı. Çağrılar olaydan sonra günlerce sürer (2021'de 4–9 Şubat,
    yağışsız günlerde günde 460–850 çağrı: bodrum boşaltma, kontrol); bunu
    model ancak geçmiş günlerin yağışından görebilir."""
    s = saatlik.sort_values(["ilce", "zaman"]).copy()
    s["mm"] = s.mm.fillna(0.0)
    s["mm3"] = s.groupby("ilce").mm.transform(lambda x: x.rolling(3, min_periods=1).sum())
    s["gun"] = s.zaman.dt.date
    g = s.groupby(["ilce", "gun"]).agg(yagis_mm=("mm", "sum"), yagis_max1s_mm=("mm", "max"),
                                       yagis_max3s_mm=("mm3", "max")).reset_index()
    g = g.sort_values(["ilce", "gun"])
    grp = g.groupby("ilce").yagis_mm
    g["yagis_dun_mm"] = grp.shift(1).fillna(0.0)
    for n in (3, 7):
        g[f"yagis_onceki{n}g_mm"] = grp.transform(
            lambda x: x.shift(1).rolling(n, min_periods=1).sum()).fillna(0.0)
    for k in ("yagis_mm", "yagis_max1s_mm", "yagis_max3s_mm", "yagis_dun_mm",
              "yagis_onceki3g_mm", "yagis_onceki7g_mm"):
        g[k] = g[k].round(1)
    return g


# ── Birleştirme ─────────────────────────────────────────────────────────────

def ilce_gun_tablosu(cagri, yagis, ilce_df):
    """Her ilçe × her gün bir satır (çağrı yoksa 0)."""
    sayim = (cagri.groupby(["ilce", "gun", "tur"]).size().unstack("tur", fill_value=0)
             .reindex(columns=list(CAGRI_TURLERI), fill_value=0).reset_index())
    sayim.columns = ["ilce", "gun"] + [f"cagri_{k}" for k in CAGRI_TURLERI]
    t = yagis.merge(sayim, on=["ilce", "gun"], how="left")
    for k in CAGRI_TURLERI:
        t[f"cagri_{k}"] = t[f"cagri_{k}"].fillna(0).astype(int)
    t["cagri_su"] = sum(t[f"cagri_{k}"] for k in CAGRI_TURLERI)
    t = t.merge(ilce_df[["ilce", "nufus", "kent_km2", "kent_payi"]], on="ilce", how="left")
    gun = pd.to_datetime(t.gun)
    t["ay"] = gun.dt.month
    t["yil"] = gun.dt.year
    return t.sort_values(["gun", "ilce"]).reset_index(drop=True)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    os.makedirs(HAM_DIR, exist_ok=True)
    os.makedirs(CIKTI_DIR, exist_ok=True)
    il = ilceler()
    ilce_adlari = {anahtar(ad): ad for ad, _ in il}

    cagri = cagrilari_oku(hizmet_dosyalari(), ilce_adlari)
    bas, bit = min(cagri.gun), max(cagri.gun)
    log.info("Su çağrısı: %d (%s – %s)", len(cagri), bas, bit)

    ilce_df = kent_ozellikleri(il)
    nf, nufus_yili = nufus(ilce_adlari)
    ilce_df = ilce_df.merge(nf, left_on="ilce", right_index=True, how="left")
    ilce_df["nufus_yili"] = nufus_yili

    yagis = gunluk_yagis(yagis_arsivi(ilce_df, bas, bit))
    tablo = ilce_gun_tablosu(cagri, yagis, ilce_df)
    tablo.to_csv(ILCE_GUN_CSV, index=False)
    ilce_df.to_csv(ILCE_CSV, index=False)
    log.info("Yazıldı: %s (%d satır, %d ilçe, %d gün) ve %s", ILCE_GUN_CSV, len(tablo),
             tablo.ilce.nunique(), tablo.gun.nunique(), ILCE_CSV)


if __name__ == "__main__":
    main()
