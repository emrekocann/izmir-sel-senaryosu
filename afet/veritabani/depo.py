"""Veri erişim katmanı: canlı kayıtların yazımı, toplanma alanları ve
pgRouting ile risk ağırlıklı rota.

SQL kurucuları (baglanma_sql, _maliyet_sql, _senaryo_join) veritabanına
dokunmaz; sınıf düzeyinde çağrılabilir ve çevrimdışı betikler de kullanır.
Sorgu çalıştıranlar bir `Veritabani` örneği üzerinden çalışır (`depo`)."""
import json
import re

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
    async def _sel_kolon_var(cls, conn, edge_table: str) -> bool:
        """migration 006 uygulanmış mı (kolonlar tablo başına bir kez okunur)."""
        if edge_table not in cls._sel_kolon:
            cls._sel_kolon[edge_table] = {r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
                edge_table)}
        return "sel_duyarlilik" in cls._sel_kolon[edge_table]

    @classmethod
    def baglanma_sql(cls, edge_table: str, point_sql: str) -> str:
        """point_sql noktasına en yakın, BAGLANMA_HARIC dışı yol düğümünün id'sini
        veren skaler alt sorgu (hesap/toplanma_alanlari_yukle.py de kullanır)."""
        haric = ", ".join(f"'{h}'" for h in cls.BAGLANMA_HARIC)
        return f"""(SELECT v.id FROM (
                        SELECT source, target FROM {edge_table}
                        WHERE COALESCE(highway, '') NOT IN ({haric})
                        ORDER BY the_geom <-> {point_sql} LIMIT {cls.BAGLANMA_KENAR}
                    ) e
                    JOIN {edge_table}_vertices_pgr v ON v.id IN (e.source, e.target)
                    ORDER BY v.the_geom <-> {point_sql} LIMIT 1)"""

    @classmethod
    def _maliyet_sql(cls, edge_table, slope_k, trafik_var, sev, sel_k_f,
                     senaryo_join=None, alt_gecit_kapali=False):
        """pgr_dijkstra'nın kenar sorgusu (metin). Eğim (%) maliyeti artırır;
        son 24 saatte M≥3 deprem üssüne ~2 km'den yakın kenarlar 5 kat, ciddi
        trafik olayına (buyukluk≥2 ya da yol kapalı) ~300 m'den yakın kenarlar
        3 kat, yağış bekleniyorsa sel duyarlı kenarlar (1 + k·S) kat
        cezalandırılır. Cezalı kenarlar kenar başına EXISTS yerine GIST
        indeksli tek uzamsal birleştirmeyle önden toplanır (364 bin kenarda
        EXISTS dakikalar sürüyordu). ST_DWithin derecedir: 0.018° ≈ 2 km,
        0.003° ≈ 300 m (ceza sezgiseldir, ölçüm değildir). senaryo_join
        (_senaryo_join) verilirse seçilen yağış senaryosunda su basan kenarlar
        kapalı, sığ sulu / belirsiz kenarlar pahalı sayılır."""
        R = cls
        trafik_cte = f"""
            , trafik_ceza AS (
                SELECT DISTINCT rn.id FROM {edge_table} rn
                JOIN canli_trafik_olaylari t
                  ON (t.buyukluk >= 2 OR t.kategori = 'Yol Kapalı')
                 AND ST_DWithin(rn.the_geom, t.konum, 0.003)
            )""" if trafik_var else ""
        return f"""
            WITH deprem_ceza AS (
                SELECT DISTINCT rn.id FROM {edge_table} rn
                JOIN canli_deprem_verileri d
                  ON d.deprem_zamani > NOW() - INTERVAL '24 hours'
                 AND d.buyukluk >= 3.0
                 AND ST_DWithin(rn.the_geom, d.konum, 0.018)
            ){trafik_cte}
            SELECT rn.id, rn.source, rn.target,
                   rn.length
                   * (1 + COALESCE(rn.slope, 0) * {slope_k})
                   * (CASE WHEN dc.id IS NOT NULL THEN 5.0 ELSE 1.0 END)
                   {"* (CASE WHEN tc.id IS NOT NULL THEN 3.0 ELSE 1.0 END)" if trafik_var else ""}
                   {f"* (1 + {sel_k_f:.3f} * COALESCE(rn.sel_duyarlilik, 0))" if sel_k_f > 0 else ""}
                   {f"""* (CASE WHEN ss.kimlik IS NOT NULL AND ss.derinlik < {R.SENARYO_KAPALI_M}
                              THEN {R.SENARYO_ISLAK_K} ELSE 1.0 END)""" if senaryo_join else ""}
                   * {sev}
                   {f"+ (CASE WHEN ss.derinlik >= {R.SENARYO_KAPALI_M} THEN {R.SENARYO_KAPALI_EK} ELSE 0 END)"
                    if senaryo_join else ""}
                   {f"+ (CASE WHEN rn.alt_gecit THEN {R.SENARYO_KAPALI_EK} ELSE 0 END)"
                    if alt_gecit_kapali else ""} AS cost
            FROM {edge_table} rn
            LEFT JOIN deprem_ceza dc ON dc.id = rn.id
            {"LEFT JOIN trafik_ceza tc ON tc.id = rn.id" if trafik_var else ""}
            {senaryo_join + "rn.id" if senaryo_join else ""}
        """

    @classmethod
    def _senaryo_ozeti(cls, rows, senaryo, sen_yol, sen_alan, ag_kapali, atlanan, hedef_su):
        """Rotanın senaryodaki suyu: art arda gelen ıslak kenarlar tek "yer"
        sayılır (kenarın tamamı değil, en derin noktası suda olabilir — bu
        yüzden metre yerine yer sayısı ve en derin nokta raporlanır)."""
        K = cls.SENARYO_KAPALI_M
        yer = {"derin": 0, "sig": 0}
        belirsiz_m, en_derin, onceki = 0.0, 0.0, None
        for r in rows:
            d = r["su_derinlik"]
            sinif = (None if d is None else "derin" if d >= K else "sig" if d >= 0.1
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
            "alt_gecit_rotada": sum(1 for r in rows if r["alt_gecit"]) if ag_kapali else 0,
            "atlanan_alan_su": atlanan["su"] if atlanan else 0,
            "atlanan_alan_belirsiz": atlanan["belirsiz"] if atlanan else 0,
            "hedef_su": dict(hedef_su) if hedef_su else None,
        }

    async def akilli_rota(self, user_lon: float, user_lat: float,
                               dest_lon: float = None, dest_lat: float = None,
                               severity: float = 1.0, mode: str = "drive",
                               sel_f: float = 0.0, senaryo: str = None,
                               alt_gecit_dolu: bool = False):
        """pgRouting ile risk ağırlıklı rota (maliyet: _maliyet_sql). Hedef
        verilmezse en yakın TOPLANMA_ADAY toplanma alanı arasından rota
        maliyeti en düşük olana gidilir (alan verisi yoksa il merkezine).
        mode=walk yaya ağını kullanır. senaryo ('50_1': 50 mm / 1 saat)
        verilirse o yağışta su basan yollar kapalı sayılır, su altındaki
        toplanma alanları aday olmaz (SENARYO_*); alt_gecit_dolu o senaryoda
        alt geçitlerin dolduğunu söyler (sel_senaryo özeti). Yol ağı ve
        pgRouting kurulmamışsa dürüst bir 'unavailable' cevabı döner."""
        R = self
        if mode not in R.ROTA_MODLARI:
            return {"status": "error",
                    "message": f"Geçersiz mod: {mode}. Seçenekler: "
                               f"{', '.join(R.ROTA_MODLARI)}"}
        edge_table, slope_k, trafik_var = R.ROTA_MODLARI[mode]
        vid_col = f"{mode}_vid"   # toplanma_alanlari.drive_vid / walk_vid
        hedefsiz = dest_lon is None or dest_lat is None
        if hedefsiz:
            dest_lon, dest_lat = MERKEZ_BOYLAM, MERKEZ_ENLEM
        sev = max(float(severity), 0.1)
        start_sql = R.baglanma_sql(edge_table, NOKTA.format("$1", "$2"))
        try:
            async with self.db.baglan() as conn:
                sel_var = await R._sel_kolon_var(conn, edge_table)
                sel_f = min(max(float(sel_f), 0.0), 1.0) if sel_var and not senaryo else 0.0
                # senaryo suyu bu mod ve toplanma alanları için yazılmış mı
                sen_katman = await R._senaryo_katmanlari(conn) if senaryo else set()
                sen_yol, sen_alan = mode in sen_katman, "toplanma" in sen_katman
                yol_join = R._senaryo_join(mode, senaryo) if sen_yol else None
                ag_kapali = sen_yol and alt_gecit_dolu and sel_var
                cost_sql = R._maliyet_sql(edge_table, slope_k, trafik_var, sev,
                                          R.SEL_K * sel_f, yol_join, ag_kapali)
                sel_kol = ("rn.sel_duyarlilik, rn.sel_riskli_oran, rn.alt_gecit," if sel_var
                           else "NULL::real AS sel_duyarlilik, NULL::real AS sel_riskli_oran, "
                                "NULL::boolean AS alt_gecit,")
                sel_kol += ("ss.derinlik AS su_derinlik, ss.belirsiz AS su_belirsiz," if sen_yol
                            else "NULL::real AS su_derinlik, NULL::boolean AS su_belirsiz,")
                sen_jn = yol_join + "rn.id" if sen_yol else ""
                # su altındaki (≥ SENARYO_KAPALI_M) ya da düz ovadaki alan aday olmaz
                alan_su = (f"s.kimlik = a.id AND s.katman = 'toplanma' AND s.senaryo = $3 "
                           f"AND (s.derinlik >= {R.SENARYO_KAPALI_M} OR s.belirsiz)")
                adaylar = []
                if hedefsiz:
                    try:
                        haric = (f"AND NOT EXISTS (SELECT 1 FROM sel_senaryo_su s WHERE {alan_su})"
                                 if sen_alan else "")
                        adaylar = await conn.fetch(f"""
                            SELECT a.id, a.adi, a.ilce, a.mahalle, a.yol, a.{vid_col} AS vid,
                                   ST_X(a.konum) AS lon, ST_Y(a.konum) AS lat
                            FROM toplanma_alanlari a
                            WHERE a.{vid_col} IS NOT NULL {haric}
                            ORDER BY a.konum <-> {NOKTA.format('$1', '$2')}
                            LIMIT {R.TOPLANMA_ADAY};
                        """, user_lon, user_lat, *([senaryo] if sen_alan else []))
                    except Exception as e:   # migration 005 uygulanmamış
                        logger.warning(f"Toplanma alanları okunamadı, il merkezine rota: {e}")

                hedef_alan = atlanan = hedef_su = None
                if adaylar:
                    # Çok hedefli Dijkstra: her adaya yol bulunur, toplam
                    # maliyeti (agg_cost, yol sonu satırı edge=-1) en düşük seçilir
                    rows = await conn.fetch(f"""
                        WITH r AS (
                            SELECT * FROM pgr_dijkstra($3, {start_sql}, $4::bigint[],
                                                       directed := false)
                        ), best AS (
                            SELECT end_vid FROM r WHERE edge = -1
                            ORDER BY agg_cost LIMIT 1
                        )
                        SELECT r.seq, r.node, r.edge, r.cost, r.end_vid, rn.length,
                               rn.source, rn.target, {sel_kol}
                               ST_AsGeoJSON(rn.the_geom)::json AS geometry
                        FROM r JOIN best USING (end_vid)
                        JOIN {edge_table} rn ON r.edge = rn.id
                        {sen_jn}
                        ORDER BY r.seq;
                    """, user_lon, user_lat, cost_sql, [a["vid"] for a in adaylar])
                    # Başlangıç zaten bir alanın düğümündeyse yol boş döner → en yakın aday
                    end_vid = rows[0]["end_vid"] if rows else adaylar[0]["vid"]
                    secilen = next(a for a in adaylar if a["vid"] == end_vid)
                    hedef_alan = {k: secilen[k] for k in
                                  ("id", "adi", "ilce", "mahalle", "yol", "lon", "lat")}
                    hedef_alan["aday_sayisi"] = len(adaylar)
                    if sen_alan:
                        # seçilen alandan (kuş uçuşu) yakın olup suda kaldığı için atlananlar
                        atlanan = await conn.fetchrow(f"""
                            SELECT count(*) FILTER (WHERE s.derinlik >= {R.SENARYO_KAPALI_M}) AS su,
                                   count(*) FILTER (WHERE s.derinlik < {R.SENARYO_KAPALI_M}) AS belirsiz
                            FROM toplanma_alanlari a JOIN sel_senaryo_su s ON {alan_su}
                            WHERE a.{vid_col} IS NOT NULL
                              AND a.konum <-> {NOKTA.format('$1', '$2')} <
                                  (SELECT konum <-> {NOKTA.format('$1', '$2')}
                                   FROM toplanma_alanlari WHERE id = $4)
                        """, user_lon, user_lat, senaryo, secilen["id"])
                else:
                    rows = await conn.fetch(f"""
                        SELECT seq, node, edge, cost, rn.length, rn.source, rn.target, {sel_kol}
                               ST_AsGeoJSON(rn.the_geom)::json AS geometry
                        FROM pgr_dijkstra(
                            $5, {start_sql},
                            {R.baglanma_sql(edge_table, NOKTA.format('$3', '$4'))},
                            directed := false
                        ) r
                        JOIN {edge_table} rn ON r.edge = rn.id
                        {sen_jn}
                        ORDER BY seq;
                    """, user_lon, user_lat, dest_lon, dest_lat, cost_sql)
                    if sen_alan and not hedefsiz:
                        # kullanıcının seçtiği hedef bir toplanma alanıysa: suda mı?
                        hedef_su = await conn.fetchrow(f"""
                            SELECT s.derinlik, s.belirsiz FROM toplanma_alanlari a
                            JOIN sel_senaryo_su s ON {alan_su}
                            WHERE ST_DWithin(a.konum, {NOKTA.format('$1', '$2')}, 0.00001)
                            LIMIT 1""", dest_lon, dest_lat, senaryo)

                # Rotanın yol ağındaki ilk ve son düğümü: tıklanan nokta ve
                # toplanma alanı ağın üstünde değildir, aradaki "yol dışı"
                # kısım ön yüzde kesikli çizgiyle gösterilir
                if rows:
                    ilk = rows[0]["node"]
                    son_kenar = rows[-1]
                    son = (son_kenar["target"] if son_kenar["node"] == son_kenar["source"]
                           else son_kenar["source"])
                elif adaylar:
                    ilk = son = end_vid
                else:
                    ilk = son = await conn.fetchval(f"SELECT {start_sql}", user_lon, user_lat)
                dugumler = {r["id"]: {"lon": r["lon"], "lat": r["lat"]} for r in await conn.fetch(
                    f"""SELECT id, ST_X(the_geom) AS lon, ST_Y(the_geom) AS lat
                        FROM {edge_table}_vertices_pgr WHERE id = ANY($1::bigint[])""",
                    [ilk, son])}

                # Rotanın sel duyarlı kısmı (yağıştan bağımsız, arazi bazlı)
                sel_riskli_m = sum(r["length"] * (r["sel_riskli_oran"] or 0) for r in rows)
                alt_gecit = sum(1 for r in rows if r["alt_gecit"])
                sen_ozet = (R._senaryo_ozeti(rows, senaryo, sen_yol, sen_alan, ag_kapali,
                                             atlanan, hedef_su) if senaryo else None)
                segments = []
                for r in rows:
                    seg = {k: v for k, v in dict(r).items() if k not in ("end_vid", "source", "target")}
                    # asyncpg json kolonunu str döndürür — obje olarak sunulmalı
                    if isinstance(seg.get("geometry"), str):
                        seg["geometry"] = json.loads(seg["geometry"])
                    segments.append(seg)
                return {
                    "status": "ok",
                    "mode": mode,
                    "cost_model": f"uzunluk × (1 + eğim×{slope_k}) × deprem_cezası"
                                  + (" × trafik_cezası" if trafik_var else "")
                                  + (f" × (1 + {R.SEL_K:g}·{sel_f:.2f}·sel_duyarlılık)"
                                     if sel_f > 0 else "")
                                  + (f" × sığ_su_cezası + su_basan_yol_cezası ({senaryo})"
                                     if sen_yol else "")
                                  + " × şiddet",
                    "sel": {"veri_var": sel_var, "yagis_f": round(sel_f, 2),
                            "riskli_m": round(sel_riskli_m), "alt_gecit": alt_gecit},
                    # seçilen yağış senaryosunda rotadaki su (senaryo yoksa None)
                    "senaryo": sen_ozet,
                    # hedefsiz istekte seçilen toplanma alanı; yoksa None
                    "toplanma_alani": hedef_alan,
                    # yol ağına giriş/çıkış düğümleri (yol dışı bağlantı için)
                    "ag_giris": dugumler.get(ilk),
                    "ag_cikis": dugumler.get(son),
                    "segments": segments,
                }
        except Exception as e:
            logger.warning(f"Smart routing kullanılamıyor (yol ağı/pgRouting eksik): {e}")
            return {
                "status": "unavailable",
                "message": f"Yol ağı ({edge_table}) veya pgRouting uzantısı kurulu değil. "
                           "Kurulum: README 'Yol Ağı & Rota' bölümü.",
                "user_location": {"lon": user_lon, "lat": user_lat},
                "destination": {"lon": dest_lon, "lat": dest_lat},
            }


depo = AfetDeposu(db)
