"""Veri erişim katmanı: canlı kayıtların yazımı, toplanma alanları ve
pgRouting ile risk ağırlıklı rota.

SQL kurucuları (baglanma_sql, _maliyet_sql, _senaryo_join) veritabanına
dokunmaz; sınıf düzeyinde çağrılabilir ve çevrimdışı betikler de kullanır.
Sorgu çalıştıranlar bir `Veritabani` örneği üzerinden çalışır (`depo`)."""
import json
import re
from dataclasses import dataclass

from loguru import logger

from afet.sinir import MERKEZ_BOYLAM, MERKEZ_ENLEM
from afet.veritabani.baglanti import Veritabani, db
from afet.veritabani.kayitlar import DepremKaydi, TrafikOlayi

NOKTA = "ST_SetSRID(ST_Point({}, {}), 4326)"      # $lon, $lat yer tutucularıyla
LONLAT = "ST_X(konum::geometry) AS lon, ST_Y(konum::geometry) AS lat"

# Canlı tabloların saklama süresi: (zaman kolonu, süre). Rota yalnız son 24
# saatin depremlerine ve güncel trafik olaylarına bakar.
SAKLAMA = {
    "canli_deprem_verileri": ("deprem_zamani", "24 hours"),
    "canli_trafik_olaylari": ("guncellendi", "2 hours"),     # TomTom'dan gelmeyen olay kapanmıştır
}


class AfetDeposu:

    def __init__(self, veritabani: Veritabani):
        self.db = veritabani

    # ── Ortak erişim: her sorgu tek yerden, hata loglanır, varsayılan döner ──

    async def _yaz(self, etiket, sql, *args):
        try:
            async with self.db.baglan(yazma=True) as conn:
                return await conn.execute(sql, *args)
        except Exception as e:
            logger.error(f"DB yazma hatası ({etiket}): {e}")

    async def _toplu_yaz(self, etiket, sql, satirlar):
        """Çok satırı tek bağlantı ve tek hazırlanmış sorguyla yazar."""
        if not satirlar:
            return
        try:
            async with self.db.baglan(yazma=True) as conn:
                await conn.executemany(sql, satirlar)
        except Exception as e:
            logger.error(f"DB toplu yazma hatası ({etiket}, {len(satirlar)} satır): {e}")

    async def _oku(self, etiket, sql, *args) -> list:
        try:
            async with self.db.baglan() as conn:
                return [dict(r) for r in await conn.fetch(sql, *args)]
        except Exception as e:
            logger.error(f"DB okuma hatası ({etiket}): {e}")
            return []

    # --- YAZMA ---

    async def depremleri_yaz(self, depremler: list[DepremKaydi]):
        await self._toplu_yaz("deprem", f"""
            INSERT INTO canli_deprem_verileri (earthquake_id, buyukluk, yer, konum, deprem_zamani)
            VALUES ($1, $2, $3, {NOKTA.format('$4', '$5')}, $6)
            ON CONFLICT (earthquake_id) DO NOTHING""",
            [(d.earthquake_id, d.buyukluk, d.yer, d.lon, d.lat, d.deprem_zamani) for d in depremler])

    async def trafik_olaylarini_yaz(self, olaylar: list[TrafikOlayi]):
        await self._toplu_yaz("trafik", f"""
            INSERT INTO canli_trafik_olaylari (olay_id, kategori, aciklama, gecikme_sn, buyukluk, konum)
            VALUES ($1, $2, $3, $4, $5, {NOKTA.format('$6', '$7')})
            ON CONFLICT (olay_id) DO UPDATE SET
                kategori = EXCLUDED.kategori, aciklama = EXCLUDED.aciklama,
                gecikme_sn = EXCLUDED.gecikme_sn, buyukluk = EXCLUDED.buyukluk,
                konum = EXCLUDED.konum, guncellendi = NOW()""",
            [(o.olay_id, o.kategori, o.aciklama, o.gecikme_sn, o.buyukluk, o.lon, o.lat) for o in olaylar])

    async def eski_kayitlari_sil(self, tablolar=None):
        """SAKLAMA süresini aşan canlı kayıtları siler."""
        for tablo in tablolar or SAKLAMA:
            kolon, sure = SAKLAMA[tablo]
            sonuc = await self._yaz(f"temizlik {tablo}",
                                    f"DELETE FROM {tablo} WHERE {kolon} < NOW() - INTERVAL '{sure}'")
            if sonuc and sonuc != "DELETE 0":
                logger.info(f"Temizlik: {tablo} — {sonuc.split()[-1]} eski kayıt silindi.")

    # --- OKUMA ---

    async def toplanma_alanlari(self):
        """İBB afet ve acil durum toplanma alanları (hesap/toplanma_alanlari_yukle.py)."""
        return await self._oku("toplanma alanı", f"""
            SELECT id, adi, ilce, mahalle, yol, {LONLAT} FROM toplanma_alanlari ORDER BY id""")

    async def senaryo_toplanma(self, senaryo: str):
        """Yağış senaryosunda rotanın hedef seçmediği toplanma alanları: su
        altındakiler (≥ SENARYO_KAPALI_M) ve düz ovadakiler (belirsiz)."""
        return await self._oku("senaryo toplanma", f"""
            SELECT kimlik AS id, derinlik, belirsiz FROM sel_senaryo_su
            WHERE katman = 'toplanma' AND senaryo = $1
              AND (derinlik >= {self.SENARYO_KAPALI_M} OR belirsiz)""", senaryo)

    async def alt_gecitler(self):
        """Araç ağındaki alt geçitler (OSM kısa tünel) — orta noktaları."""
        return await self._oku("alt geçit", """
            SELECT ST_X(p) AS lon, ST_Y(p) AS lat, highway FROM (
                SELECT ST_LineInterpolatePoint(the_geom, 0.5) AS p, highway
                FROM izmir_roads_noded WHERE alt_gecit) s""")

    # --- ROTA (pgRouting) ---

    # Hedefsiz rotada kuş uçuşu en yakın bu kadar toplanma alanı aday olur;
    # aralarından risk ağırlıklı rota maliyeti en düşük olan seçilir
    # (en yakın alan yokuş/deprem/trafik yüzünden en güvenlisi olmayabilir).
    TOPLANMA_ADAY = 8

    # mod → (kenar tablosu, eğim katsayısı, trafik cezası uygulanır mı).
    # Yaya %eğimden araçtan çok etkilenir; trafik sıkışıklığı yayayı etkilemez.
    ROTA_MODLARI = {
        "drive": ("izmir_roads_noded", 0.05, True),
        "walk": ("izmir_yaya_noded", 0.10, False),
    }

    # Bir noktayı yol ağına bağlarken bu yol tiplerine bağlanılmaz: otoyolun
    # yanındaki biri otoyolda değildir (en yakın düğüm otoyoldaysa rota
    # rampadan dolaşıyordu). Yol tipi kenarlarda olduğu için önce en yakın
    # BAGLANMA_KENAR uygun KENAR (GIST), sonra uçları arasından en yakın düğüm
    # seçilir (tek kenarın ucu, kenar uzunsa yüzlerce metre ötede kalabilir).
    BAGLANMA_HARIC = ("motorway", "motorway_link", "trunk_link")
    BAGLANMA_KENAR = 8

    # Sel cezası: yağış katsayısı f (0–1, afet.sel.risk) × kenarın arazi
    # duyarlılığı S (0–1) → maliyet × (1 + SEL_K·f·S). Yağış yoksa (f=0) etkisiz.
    # S kenar boyunca ortalamadır; rotanın S ≥ 0.6 kısmı (sel_riskli_oran ×
    # uzunluk) yanıtta raporlanır.
    SEL_K = 4.0
    _sel_kolon = {}

    # Yağış senaryosu (migrations/011, hesap/sel_senaryo_yollar.py): kenarın en
    # derin noktası ≥ SENARYO_KAPALI_M ise yol kapalı sayılır — maliyetine
    # SENARYO_KAPALI_EK metre eklenir (her geçiş ~100 km dolambaç kadar
    # pahalı; başka yol yoksa yine de geçilir ve yanıtta raporlanır). Sığ su
    # (0.1–0.3 m) ya da düz ova belirsizliği maliyeti SENARYO_ISLAK_K kat
    # artırır. Senaryoda alt geçitler doluysa (özetteki alt_gecit_dolu) alt
    # geçit kenarları da kapalıdır. Toplanma alanı adayları su altındaki
    # (≥ SENARYO_KAPALI_M) ya da düz ovada (belirsiz) alanları içermez.
    # Senaryo verilince 24 saatlik yağış tahmininin sel cezası uygulanmaz.
    SENARYO_KAPALI_M = 0.3
    SENARYO_KAPALI_EK = 100_000.0
    SENARYO_ISLAK_K = 5.0
    SENARYO_DESEN = re.compile(r"\d{1,3}_\d{1,2}")

    @staticmethod
    async def _senaryo_katmanlari(conn) -> set:
        """Senaryo suyu yazılmış katmanlar (drive / walk / toplanma);
        migration 011 uygulanmamışsa boş küme."""
        try:
            return {r["katman"] for r in await conn.fetch("SELECT katman FROM sel_senaryo_yazim")}
        except Exception:
            return set()

    @classmethod
    def _senaryo_join(cls, katman: str, senaryo: str, takma: str = "ss") -> str:
        """Kenara (ya da alana) senaryo suyunu bağlayan LEFT JOIN. senaryo
        SENARYO_DESEN'e, katman sabit listeye uyar (metne gömülür: pgr_dijkstra
        kenar sorgusunu metin olarak alır, parametre bağlanamaz)."""
        if not cls.SENARYO_DESEN.fullmatch(senaryo) or katman not in (
                "drive", "walk", "toplanma"):
            raise ValueError(f"Geçersiz senaryo: {senaryo!r} / {katman!r}")
        return (f"LEFT JOIN sel_senaryo_su {takma} ON {takma}.katman = '{katman}' "
                f"AND {takma}.senaryo = '{senaryo}' AND {takma}.kimlik = ")

    @classmethod
    async def _sel_kolon_var(cls, conn, kenar_tablosu: str) -> bool:
        """migration 006 uygulanmış mı (kolonlar tablo başına bir kez okunur)."""
        if kenar_tablosu not in cls._sel_kolon:
            cls._sel_kolon[kenar_tablosu] = {r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
                kenar_tablosu)}
        return "sel_duyarlilik" in cls._sel_kolon[kenar_tablosu]

    @classmethod
    def baglanma_sql(cls, kenar_tablosu: str, nokta_sql: str) -> str:
        """nokta_sql noktasına en yakın, BAGLANMA_HARIC dışı yol düğümünün id'sini
        veren skaler alt sorgu (hesap/toplanma_alanlari_yukle.py de kullanır)."""
        haric = ", ".join(f"'{h}'" for h in cls.BAGLANMA_HARIC)
        return f"""(SELECT v.id FROM (
                        SELECT source, target FROM {kenar_tablosu}
                        WHERE COALESCE(highway, '') NOT IN ({haric})
                        ORDER BY the_geom <-> {nokta_sql} LIMIT {cls.BAGLANMA_KENAR}
                    ) e
                    JOIN {kenar_tablosu}_vertices_pgr v ON v.id IN (e.source, e.target)
                    ORDER BY v.the_geom <-> {nokta_sql} LIMIT 1)"""

    @classmethod
    def _maliyet_sql(cls, kenar_tablosu, egim_k, trafik_var, siddet, sel_k_f,
                     su_join_sql=None, alt_gecit_kapali=False):
        """pgr_dijkstra'nın kenar sorgusu (metin). Eğim (%) maliyeti artırır;
        son 24 saatte M≥3 deprem üssüne ~2 km'den yakın kenarlar 5 kat, ciddi
        trafik olayına (buyukluk≥2 ya da yol kapalı) ~300 m'den yakın kenarlar
        3 kat, yağış bekleniyorsa sel duyarlı kenarlar (1 + k·S) kat
        cezalandırılır. Cezalı kenarlar kenar başına EXISTS yerine GIST
        indeksli tek uzamsal birleştirmeyle önden toplanır (364 bin kenarda
        EXISTS dakikalar sürüyordu). ST_DWithin derecedir: 0.018° ≈ 2 km,
        0.003° ≈ 300 m (ceza sezgiseldir, ölçüm değildir). su_join_sql
        (_senaryo_join) verilirse seçilen yağış senaryosunda su basan kenarlar
        kapalı, sığ sulu / belirsiz kenarlar pahalı sayılır."""
        trafik_cte = f"""
            , trafik_ceza AS (
                SELECT DISTINCT rn.id FROM {kenar_tablosu} rn
                JOIN canli_trafik_olaylari t
                  ON (t.buyukluk >= 2 OR t.kategori = 'Yol Kapalı')
                 AND ST_DWithin(rn.the_geom, t.konum, 0.003)
            )""" if trafik_var else ""
        return f"""
            WITH deprem_ceza AS (
                SELECT DISTINCT rn.id FROM {kenar_tablosu} rn
                JOIN canli_deprem_verileri d
                  ON d.deprem_zamani > NOW() - INTERVAL '24 hours'
                 AND d.buyukluk >= 3.0
                 AND ST_DWithin(rn.the_geom, d.konum, 0.018)
            ){trafik_cte}
            SELECT rn.id, rn.source, rn.target,
                   rn.length
                   * (1 + COALESCE(rn.slope, 0) * {egim_k})
                   * (CASE WHEN dc.id IS NOT NULL THEN 5.0 ELSE 1.0 END)
                   {"* (CASE WHEN tc.id IS NOT NULL THEN 3.0 ELSE 1.0 END)" if trafik_var else ""}
                   {f"* (1 + {sel_k_f:.3f} * COALESCE(rn.sel_duyarlilik, 0))" if sel_k_f > 0 else ""}
                   {f"""* (CASE WHEN ss.kimlik IS NOT NULL AND ss.derinlik < {cls.SENARYO_KAPALI_M}
                              THEN {cls.SENARYO_ISLAK_K} ELSE 1.0 END)""" if su_join_sql else ""}
                   * {siddet}
                   {f"+ (CASE WHEN ss.derinlik >= {cls.SENARYO_KAPALI_M} THEN {cls.SENARYO_KAPALI_EK} ELSE 0 END)"
                    if su_join_sql else ""}
                   {f"+ (CASE WHEN rn.alt_gecit THEN {cls.SENARYO_KAPALI_EK} ELSE 0 END)"
                    if alt_gecit_kapali else ""} AS cost
            FROM {kenar_tablosu} rn
            LEFT JOIN deprem_ceza dc ON dc.id = rn.id
            {"LEFT JOIN trafik_ceza tc ON tc.id = rn.id" if trafik_var else ""}
            {su_join_sql + "rn.id" if su_join_sql else ""}
        """

    @classmethod
    def _senaryo_ozeti(cls, satirlar, senaryo, sen_yol, sen_alan, ag_kapali, atlanan, hedef_su):
        """Rotanın senaryodaki suyu: art arda gelen ıslak kenarlar tek "yer"
        sayılır (kenarın tamamı değil, en derin noktası suda olabilir — bu
        yüzden metre yerine yer sayısı ve en derin nokta raporlanır)."""
        yer = {"derin": 0, "sig": 0}
        belirsiz_m, en_derin, onceki = 0.0, 0.0, None
        for r in satirlar:
            d = r["su_derinlik"]
            sinif = (None if d is None else "derin" if d >= cls.SENARYO_KAPALI_M else "sig" if d >= 0.1
                     else "belirsiz")
            if sinif in yer and sinif != onceki:
                yer[sinif] += 1
            if r["su_belirsiz"]:
                belirsiz_m += r["length"] or 0
            if d is not None:
                en_derin = max(en_derin, d)
            onceki = sinif
        return {
            "ad": senaryo, "veri_var": sen_yol, "alan_veri_var": sen_alan,
            "derin_yer": yer["derin"], "sig_yer": yer["sig"],
            "en_derin_m": round(en_derin, 1), "belirsiz_m": round(belirsiz_m),
            "alt_gecit_kapali": bool(ag_kapali),
            "alt_gecit_rotada": sum(1 for r in satirlar if r["alt_gecit"]) if ag_kapali else 0,
            "atlanan_alan_su": atlanan["su"] if atlanan else 0,
            "atlanan_alan_belirsiz": atlanan["belirsiz"] if atlanan else 0,
            "hedef_su": dict(hedef_su) if hedef_su else None,
        }

    async def akilli_rota(self, lon: float, lat: float, hedef_lon: float = None, hedef_lat: float = None,
                          siddet: float = 1.0, mod: str = "drive", sel_f: float = 0.0, senaryo: str = None,
                          alt_gecit_dolu: bool = False):
        """pgRouting ile risk ağırlıklı rota (maliyet: _maliyet_sql). Hedef
        verilmezse en yakın TOPLANMA_ADAY toplanma alanı arasından rota
        maliyeti en düşük olana gidilir (alan verisi yoksa il merkezine).
        mod=walk yaya ağını kullanır. senaryo ('50_1': 50 mm / 1 saat)
        verilirse o yağışta su basan yollar kapalı sayılır, su altındaki
        toplanma alanları aday olmaz (SENARYO_*); alt_gecit_dolu o senaryoda
        alt geçitlerin dolduğunu söyler (sel_senaryo özeti). Yol ağı ve
        pgRouting kurulmamışsa dürüst bir 'unavailable' cevabı döner."""
        if mod not in self.ROTA_MODLARI:
            return {"status": "error",
                    "message": f"Geçersiz mod: {mod}. Seçenekler: {', '.join(self.ROTA_MODLARI)}"}
        kenar_tablosu = self.ROTA_MODLARI[mod][0]
        hedefsiz = hedef_lon is None or hedef_lat is None
        if hedefsiz:
            hedef_lon, hedef_lat = MERKEZ_BOYLAM, MERKEZ_ENLEM
        try:
            async with self.db.baglan() as conn:
                b = await self._rota_baglami(conn, mod, siddet, sel_f, senaryo, alt_gecit_dolu)
                adaylar = await self._aday_alanlar(conn, b, lon, lat) if hedefsiz else []
                hedef_alan = atlanan = hedef_su = None
                if adaylar:
                    satirlar, hedef_alan, atlanan, bitis = await self._adaylara_rota(conn, b, lon, lat, adaylar)
                else:
                    bitis = None
                    satirlar = await self._hedefe_rota(conn, b, lon, lat, hedef_lon, hedef_lat)
                    if b.sen_alan and not hedefsiz:
                        hedef_su = await self._hedef_suyu(conn, b, hedef_lon, hedef_lat)
                giris, cikis = await self._ag_uclari(conn, b, satirlar, lon, lat, bitis)
        except Exception as e:
            logger.warning(f"Akıllı rota kullanılamıyor (yol ağı/pgRouting eksik): {e}")
            return {
                "status": "unavailable",
                "message": f"Yol ağı ({kenar_tablosu}) veya pgRouting uzantısı kurulu değil. "
                           "Kurulum: README 'Yol Ağı & Rota' bölümü.",
                "user_location": {"lon": lon, "lat": lat},
                "destination": {"lon": hedef_lon, "lat": hedef_lat},
            }
        return {
            "status": "ok",
            "mode": mod,
            "cost_model": self._maliyet_aciklamasi(b),
            "sel": {"veri_var": b.sel_var, "yagis_f": round(b.sel_f, 2),
                    # rotanın sel duyarlı kısmı (yağıştan bağımsız, arazi bazlı)
                    "riskli_m": round(sum(r["length"] * (r["sel_riskli_oran"] or 0) for r in satirlar)),
                    "alt_gecit": sum(1 for r in satirlar if r["alt_gecit"])},
            # seçilen yağış senaryosunda rotadaki su (senaryo yoksa None)
            "senaryo": (self._senaryo_ozeti(satirlar, senaryo, b.sen_yol, b.sen_alan, b.ag_kapali,
                                            atlanan, hedef_su) if senaryo else None),
            # hedefsiz istekte seçilen toplanma alanı; yoksa None
            "toplanma_alani": hedef_alan,
            # yol ağına giriş/çıkış düğümleri (yol dışı bağlantı için)
            "ag_giris": giris,
            "ag_cikis": cikis,
            "segments": [self._parca(r) for r in satirlar],
        }

    async def _rota_baglami(self, conn, mod, siddet, sel_f, senaryo, alt_gecit_dolu):
        """İsteğin rota sorgularında ortak kullanılan parçaları (_RotaBaglami)."""
        kenar_tablosu, egim_k, trafik_var = self.ROTA_MODLARI[mod]
        sel_var = await self._sel_kolon_var(conn, kenar_tablosu)
        sel_f = min(max(float(sel_f), 0.0), 1.0) if sel_var and not senaryo else 0.0
        # senaryo suyu bu mod ve toplanma alanları için yazılmış mı
        sen_katman = await self._senaryo_katmanlari(conn) if senaryo else set()
        sen_yol, sen_alan = mod in sen_katman, "toplanma" in sen_katman
        yol_join = self._senaryo_join(mod, senaryo) if sen_yol else None
        ag_kapali = sen_yol and alt_gecit_dolu and sel_var
        kolonlar = ("rn.sel_duyarlilik, rn.sel_riskli_oran, rn.alt_gecit," if sel_var
                    else "NULL::real AS sel_duyarlilik, NULL::real AS sel_riskli_oran, NULL::boolean AS alt_gecit,")
        kolonlar += ("ss.derinlik AS su_derinlik, ss.belirsiz AS su_belirsiz," if sen_yol
                     else "NULL::real AS su_derinlik, NULL::boolean AS su_belirsiz,")
        return _RotaBaglami(
            mod=mod, kenar_tablosu=kenar_tablosu, egim_k=egim_k, trafik_var=trafik_var, senaryo=senaryo,
            sel_var=sel_var, sel_f=sel_f, sen_yol=sen_yol, sen_alan=sen_alan, ag_kapali=ag_kapali,
            maliyet_sql=self._maliyet_sql(kenar_tablosu, egim_k, trafik_var, max(float(siddet), 0.1),
                                          self.SEL_K * sel_f, yol_join, ag_kapali),
            kolonlar=kolonlar, su_join=yol_join + "rn.id" if sen_yol else "",
            baslangic_sql=self.baglanma_sql(kenar_tablosu, NOKTA.format("$1", "$2")))

    def _alan_su_kosulu(self):
        """Su altındaki (≥ SENARYO_KAPALI_M) ya da düz ovadaki alan (senaryo: $3)."""
        return (f"s.kimlik = a.id AND s.katman = 'toplanma' AND s.senaryo = $3 "
                f"AND (s.derinlik >= {self.SENARYO_KAPALI_M} OR s.belirsiz)")

    async def _aday_alanlar(self, conn, b, lon, lat):
        """Kuş uçuşu en yakın TOPLANMA_ADAY alan; senaryoda suda kalanlar aday olmaz."""
        haric = (f"AND NOT EXISTS (SELECT 1 FROM sel_senaryo_su s WHERE {self._alan_su_kosulu()})"
                 if b.sen_alan else "")
        try:
            return await conn.fetch(f"""
                SELECT a.id, a.adi, a.ilce, a.mahalle, a.yol, a.{b.mod}_vid AS vid,
                       ST_X(a.konum) AS lon, ST_Y(a.konum) AS lat
                FROM toplanma_alanlari a
                WHERE a.{b.mod}_vid IS NOT NULL {haric}
                ORDER BY a.konum <-> {NOKTA.format('$1', '$2')}
                LIMIT {self.TOPLANMA_ADAY};
            """, lon, lat, *([b.senaryo] if b.sen_alan else []))
        except Exception as e:   # migration 005 uygulanmamış
            logger.warning(f"Toplanma alanları okunamadı, il merkezine rota: {e}")
            return []

    async def _adaylara_rota(self, conn, b, lon, lat, adaylar):
        """Çok hedefli Dijkstra: her adaya yol bulunur, toplam maliyeti (agg_cost,
        yol sonu satırı edge=-1) en düşük seçilir → (satırlar, hedef alan, atlanan, bitiş düğümü)."""
        satirlar = await conn.fetch(f"""
            WITH r AS (
                SELECT * FROM pgr_dijkstra($3, {b.baslangic_sql}, $4::bigint[], directed := false)
            ), best AS (
                SELECT end_vid FROM r WHERE edge = -1 ORDER BY agg_cost LIMIT 1
            )
            SELECT r.seq, r.node, r.edge, r.cost, r.end_vid, rn.length,
                   rn.source, rn.target, {b.kolonlar}
                   ST_AsGeoJSON(rn.the_geom)::json AS geometry
            FROM r JOIN best USING (end_vid)
            JOIN {b.kenar_tablosu} rn ON r.edge = rn.id
            {b.su_join}
            ORDER BY r.seq;
        """, lon, lat, b.maliyet_sql, [a["vid"] for a in adaylar])
        # Başlangıç zaten bir alanın düğümündeyse yol boş döner → en yakın aday
        bitis = satirlar[0]["end_vid"] if satirlar else adaylar[0]["vid"]
        secilen = next(a for a in adaylar if a["vid"] == bitis)
        hedef_alan = {k: secilen[k] for k in ("id", "adi", "ilce", "mahalle", "yol", "lon", "lat")}
        hedef_alan["aday_sayisi"] = len(adaylar)
        atlanan = None
        if b.sen_alan:
            # seçilen alandan (kuş uçuşu) yakın olup suda kaldığı için atlananlar
            atlanan = await conn.fetchrow(f"""
                SELECT count(*) FILTER (WHERE s.derinlik >= {self.SENARYO_KAPALI_M}) AS su,
                       count(*) FILTER (WHERE s.derinlik < {self.SENARYO_KAPALI_M}) AS belirsiz
                FROM toplanma_alanlari a JOIN sel_senaryo_su s ON {self._alan_su_kosulu()}
                WHERE a.{b.mod}_vid IS NOT NULL
                  AND a.konum <-> {NOKTA.format('$1', '$2')} <
                      (SELECT konum <-> {NOKTA.format('$1', '$2')} FROM toplanma_alanlari WHERE id = $4)
            """, lon, lat, b.senaryo, secilen["id"])
        return satirlar, hedef_alan, atlanan, bitis

    async def _hedefe_rota(self, conn, b, lon, lat, hedef_lon, hedef_lat):
        return await conn.fetch(f"""
            SELECT seq, node, edge, cost, rn.length, rn.source, rn.target, {b.kolonlar}
                   ST_AsGeoJSON(rn.the_geom)::json AS geometry
            FROM pgr_dijkstra(
                $5, {b.baslangic_sql},
                {self.baglanma_sql(b.kenar_tablosu, NOKTA.format('$3', '$4'))},
                directed := false
            ) r
            JOIN {b.kenar_tablosu} rn ON r.edge = rn.id
            {b.su_join}
            ORDER BY seq;
        """, lon, lat, hedef_lon, hedef_lat, b.maliyet_sql)

    async def _hedef_suyu(self, conn, b, hedef_lon, hedef_lat):
        """Kullanıcının seçtiği hedef bir toplanma alanıysa senaryoda suda mı?"""
        return await conn.fetchrow(f"""
            SELECT s.derinlik, s.belirsiz FROM toplanma_alanlari a
            JOIN sel_senaryo_su s ON {self._alan_su_kosulu()}
            WHERE ST_DWithin(a.konum, {NOKTA.format('$1', '$2')}, 0.00001)
            LIMIT 1""", hedef_lon, hedef_lat, b.senaryo)

    async def _ag_uclari(self, conn, b, satirlar, lon, lat, bitis=None):
        """Rotanın yol ağındaki ilk ve son düğümü ({lon, lat} ya da None): tıklanan
        nokta ve toplanma alanı ağın üstünde değildir, aradaki "yol dışı" kısım
        ön yüzde kesikli çizgiyle gösterilir. bitis: yol boşsa (başlangıç zaten
        seçilen alanın düğümünde) o düğüm."""
        if satirlar:
            ilk, son_kenar = satirlar[0]["node"], satirlar[-1]
            son = son_kenar["target"] if son_kenar["node"] == son_kenar["source"] else son_kenar["source"]
        elif bitis is not None:
            ilk = son = bitis
        else:
            ilk = son = await conn.fetchval(f"SELECT {b.baslangic_sql}", lon, lat)
        dugumler = {r["id"]: {"lon": r["lon"], "lat": r["lat"]} for r in await conn.fetch(
            f"""SELECT id, ST_X(the_geom) AS lon, ST_Y(the_geom) AS lat
                FROM {b.kenar_tablosu}_vertices_pgr WHERE id = ANY($1::bigint[])""", [ilk, son])}
        return dugumler.get(ilk), dugumler.get(son)

    def _maliyet_aciklamasi(self, b):
        return (f"uzunluk × (1 + eğim×{b.egim_k}) × deprem_cezası"
                + (" × trafik_cezası" if b.trafik_var else "")
                + (f" × (1 + {self.SEL_K:g}·{b.sel_f:.2f}·sel_duyarlılık)" if b.sel_f > 0 else "")
                + (f" × sığ_su_cezası + su_basan_yol_cezası ({b.senaryo})" if b.sen_yol else "")
                + " × şiddet")

    @staticmethod
    def _parca(satir):
        """Rota satırı → yanıttaki parça (asyncpg json kolonunu str döndürür: nesneye çevrilir)."""
        parca = {k: v for k, v in dict(satir).items() if k not in ("end_vid", "source", "target")}
        if isinstance(parca.get("geometry"), str):
            parca["geometry"] = json.loads(parca["geometry"])
        return parca


@dataclass(frozen=True)
class _RotaBaglami:
    """Bir rota isteğinin sorgularda ortak kullanılan parçaları (AfetDeposu._rota_baglami)."""
    mod: str
    kenar_tablosu: str
    egim_k: float
    trafik_var: bool
    senaryo: str | None
    sel_var: bool
    sel_f: float
    sen_yol: bool            # senaryo suyu bu modun yollarına yazılmış
    sen_alan: bool           # … ve toplanma alanlarına
    ag_kapali: bool          # senaryoda alt geçitler kapalı
    maliyet_sql: str
    kolonlar: str            # rota satırlarına eklenen sel / su kolonları
    su_join: str             # kenarlara senaryo suyu (yoksa boş)
    baslangic_sql: str

depo = AfetDeposu(db)
