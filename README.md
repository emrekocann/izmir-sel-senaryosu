# 🌊 İzmir Afet Radar — Sel Senaryosu ve Tahliye Rotası

Tek bir soruyu yanıtlayan, PostGIS + pgRouting tabanlı bir karar destek haritası: **"X mm yağış Y saatte düşerse İzmir'de nereyi su basar, hangi yollar kapanır, hangi toplanma alanları etkilenir ve insanlar en güvenli toplanma alanına hangi yoldan gider?"**

**Yayın sitesi:** [docs/](docs/index.html) — "2 Şubat 2021 İzmir seli yeniden yaşansa ne olur?" Harita merkezli, Türkçe / İngilizce, sunucusuz çalışan site (GitHub Pages: Settings → Pages → dal + `/docs`). Dört sekme: yağış senaryoları, 2021 seliyle karşılaştırma, tarayıcıda hesaplanan tahliye rotası, toplanma alanı denetimi; yöntem ve doğrulama "Hakkında" penceresinde. Sitedeki bütün sayılar `docs/veri/` dosyalarından gelir; bunları `venv/bin/python -m hesap.vitrin_hazirla`, `-m hesap.rota_agi_hazirla` ve `-m hesap.toplanma_denetimi` üretir. Yerelde: `python -m http.server --directory docs`. Düz metin özeti: [docs/vaka-calismasi.md](docs/vaka-calismasi.md).

## 🚀 Neler var

- **Yağış senaryosu** (açılış ekranı): 10–250 mm yağış, 1 / 6 / 24 saat. Su derinliği haritası ve özet: su basan alan, araçla geçilemez yol, alt geçitler, su basan toplanma alanları, en çok etkilenen mahalleler. Ayrıntı: aşağıda "Kademeli yağış senaryosu".
- **Önümüzdeki 24 saat:** arazi duyarlılığı × Open-Meteo yağış tahmini.
- **Arazi duyarlılığı:** yağıştan bağımsız; kuvvetli yağışta suyun toplandığı ya da taştığı yerler.
- **Tahliye rotası (🧭):** İBB'nin 2.380 afet ve acil durum toplanma alanına araç ya da yaya rotası. Maliyete eğim, son 24 saatin depremleri (Kandilli) ve ciddi trafik olayları (TomTom, isteğe bağlı) girer. **Rota, haritada seçili yağış senaryosuna göre çizilir:** o yağışta su basan yollar kapalı sayılır, su altındaki toplanma alanları hedef seçilmez; rota yine de suya girmek zorundaysa nerede ve ne derinlikte girdiği söylenir. Diğer sel modlarında yağış bekleniyorsa sel duyarlılığı cezası uygulanır.
- **Sınır verisi:** Kara sınırları resmî **TKGM** (MEGSİS idari yapı servisi) ilçe sınırlarıdır — harita altlığının (Esri/HERE) çizdiği il sınırıyla örtüşür; OSM idari sınırları kara sınırında ortalama ~0.6 km, en çok ~4 km sapıyordu. TKGM kıyısı kaba ve adasız olduğundan kıyı ve adalar OSM kıyı çizgisinden tamamlanır. TKGM kara alanı OSM ile kırpılmaz: OSM tuzla, lagün ve dolgu alanlarını (ör. Çamaltı, Karşıyaka–Çiğli kıyısı) deniz sayar, altlık ve TKGM kara sayar. İl içinde TKGM'de hiçbir ilçeye verilmemiş boşluklar (Çeşme–Urla arası) da il alanına katılır. İlçeler boşluksuz/örtüşmesiz paylaştırılır; `izmir_sinir.geojson` ilçelerin birleşimidir (kara ~12.185 km²). Üretim: `venv/bin/python -m hesap.sinir_hazirla`. Yol ağı ve sel hesapları bu sınırla üretilir; sınır değişirse hepsi yeniden üretilmelidir. Sunucunun il çerçevesi ve merkezi de bu dosyadan türetilir (`afet/sinir.py`).

**Ana daldan çıkarılanlar:** önceki sürümdeki sıcaklık, rüzgâr, hava kalitesi, uydu ısı anomalisi, trafik akış katmanı, heksagon risk ızgarası, deprem zaman makinesi ve GeoAI yangın riski modeli `arsiv/tum-katmanlar` dalında durur. Proje tek bir soruya odaklansın diye çıkarıldılar; tabloları `migrations/010` siler.

## 🛠️ Teknoloji Yığını

- **Backend:** Python, FastAPI (async), asyncpg, Uvicorn
- **Veritabanı:** PostgreSQL + PostGIS + pgRouting
- **Hesap:** pysheds, rasterio, scipy, shapely (çevrimdışı; sonuçlar depoda)
- **Frontend:** HTML5, CSS3, JavaScript, Leaflet.js
- **Container:** Docker Compose (PostGIS + backend)

## 📦 Kurulum

```bash
# 1. Ortam değişkenleri: .env.example'ı .env olarak kopyalayıp doldurun
#    (DB_*; isteğe bağlı TOMTOM_API_KEY — rota trafik cezası)

# 2. Servisleri başlat
docker compose up -d

# 3. Göçleri sırayla uygula
psql -h localhost -p $DB_PORT -U $DB_USER -d $DB_NAME -f migrations/003_baseline_schema.sql
psql -h localhost -p $DB_PORT -U $DB_USER -d $DB_NAME -f migrations/002_quake_timestamp.sql
# Eski veritabanları: 010_sadelestirme.sql (kaldırılan katmanların tabloları),
# 007'yi uygulamış olanlar ayrıca 009_buzlanma_kaldir.sql

# Sıfırdan tam kurulum (yol ağı, toplanma alanları, sel kolonları):
#   004, 005 göçleri → CREATE EXTENSION pgrouting;
#   hesap/yol_agi_kur.py all --pbf osm_indirme/turkey-latest.osm.pbf  (Geofabrik, ~650 MB;
#     Overpass genel sunucuları çoğu zaman "kapasite dolu" — dosyayla ~25 dk)
#   hesap/toplanma_alanlari_yukle.py → 006 göçü → hesap/sel_duyarlilik_hesapla.py
#   → 011 göçü → hesap/sel_senaryo_hazirla.py (sonunda hesap/sel_senaryo_yollar.py'yi kendisi çalıştırır)
# Eski veritabanları rota ↔ senaryo bağlantısı için: 011 göçü → hesap/sel_senaryo_yollar.py (~30 sn)

# Yerel geliştirme (Docker'sız backend)
pip install -r requirements.txt           # yalnız sunucu
pip install -r requirements-hesap.txt     # + çevrimdışı hesap betikleri (yol ağı, sel, sınır)
uvicorn afet.api:app --reload        # API: http://127.0.0.1:8000/docs
```

### Klasör düzeni

```
docs/         Yayın sitesi (GitHub Pages), derleme adımı yok:
                index.html        sayfa iskeleti + "Hakkında" metni
                css/app.css       düzen ve tema
                js/main.js        giriş: veri, harita, sekme yönetimi
                js/cekirdek/      dil, biçim, veri, harita, arayüz yardımcıları
                js/sekmeler/      her sekme bir modül (senaryo, olay, rota, denetim)
                veri/             önceden hesaplanmış veri (JSON, PNG, CSV)
hesap/        Çevrimdışı hesap betikleri — kökten "python -m hesap.<betik>" ile çalışır
              (yol ağı, sınır, sel duyarlılığı, senaryolar, doğrulama, yayın verisi)
tests/        Otomatik testler (pytest)
migrations/   Veritabanı göçleri (SQL)
sinir/        İl ve ilçe sınırı (GeoJSON; hesap/sinir_hazirla.py üretir)
sel_model/    Hesaplanmış sel sonuçları (senaryo.npz, duyarlilik.npz)
dogrulama/    2 Şubat 2021 olay verisi ve karşılaştırma sonucu
denetim/      Toplanma alanı denetim listesi (CSV)
egitim/       İtfaiye çağrısı × yağış ilçe-gün eğitim veri seti (CSV)
afet/         Python paketi: API sunucusu ve hesap betiklerinin ortak kodu

Depoda olmayan, yerelde üretilen / indirilen klasörler (.gitignore):
osm_indirme/  Geofabrik OSM dosyası        sel_veri/    DEM, arazi örtüsü, OSM önbellekleri
dem_cache/    SRTM karoları                sinir_veri/  TKGM ve OSM sınır önbellekleri
cache/        osmnx / Overpass önbelleği   logs/        sunucu günlükleri
itfaiye_veri/ İBB itfaiye Excel'leri, yağış arşivi önbelleği
```

### Kod düzeni

```
afet/
  api.py              FastAPI uç noktaları (yalnız API; kök adres /docs'a yönlenir)
  canli_veri.py       rota maliyetine giren canlı veri döngüleri (Kandilli, TomTom)
  veritabani/
    baglanti.py       Veritabani: okuma / yazma havuzları, yeniden bağlanma, oturum()
    depo.py           AfetDeposu: bütün SQL tek yerde (pgRouting rotası dahil)
    kayitlar.py       DepremKaydi, TrafikOlayi (pydantic doğrulama)
  sel/
    senaryo.py        SelSenaryolari: yağış senaryosu su derinliği katmanı
    risk.py           SelRiski: arazi duyarlılığı × saatlik yağış tahmini
  izgara.py           IzgaraKatmani (iki sel katmanının ortak tabanı), Mercator PNG
  sinir.py            il çerçevesi / merkezi / poligonu, TKGM ilçe ve mahalleleri
  ag.py               dış servisler: paylaşılan HTTP istemcisi, yeniden denemeli getir, Overpass
  onbellek.py         SureliOnbellek: aynı anda gelen istekler dış servise tek istek gönderir
  dosya.py            JSON okuma / yazma (betiklerin ortak biçimi)
  yollar.py           projedeki bütün dosya ve klasör yolları — tek yerde
  ayarlar.py, gunluk.py  .env ayarları, sunucu günlüğü
hesap/dem_hidroloji.py  sel hesaplarının ortak yükseklik / akış altyapısı (DEM, HAND,
                        çukurlar, köprü/alt geçit, OSM çizgileri, yol örnekleme)
```

Sunucu ile çevrimdışı betikler aynı kodu paylaşır: rota maliyeti sabitleri (`AfetDeposu.SENARYO_*`) sunucunun pgRouting sorgusunda, `hesap/` betiklerinde ve tarayıcının rota dosyalarında aynıdır.

**Saklama süresi:** canlı tablolar saatte bir temizlenir (`afet/veritabani/depo.py`, `SAKLAMA`): deprem 24 saat, trafik 2 saat.

## 🛣️ Yol Ağı & Tahliye Rotası (kurulum gerektirir)

`/api/v1/routing/smart` endpoint'i, kenar maliyetini **uzunluk × (1 + eğim×0.05) × deprem cezası × trafik cezası × sel cezası × şiddet** formülüyle hesaplayan pgRouting tabanlı rota üretir (son 24 saatte M≥3 deprem merkez üssüne 2 km'den yakın yollar 5 kat cezalandırılır; trafik ve sel cezası aşağıda). `senaryo=50_1` gibi bir yağış senaryosu verilirse sel cezası yerine o senaryodaki su kullanılır (aşağıda "Rota ve yağış senaryosu"). Çalışması için:

1. pgRouting uzantısı: docker-compose'daki `imresamu/postgis:14-3.4-bundle0` imajı pgRouting içerir (arm64 dahil); `CREATE EXTENSION pgrouting;` yeterlidir.
2. Yol ağı tabloları: `venv/bin/python -m hesap.yol_agi_kur [drive|walk|all]` — İzmir sınırı içindeki OSM ağını Overpass'tan indirir (Overpass yoğunsa `--pbf turkey-latest.osm.pbf` ile Geofabrik dosyasından aynı filtrelerle kurar), düğüm yüksekliklerini AWS terrain-tiles (SRTM) karolarından örnekleyip kenar eğimini (%) hesaplar ve tabloları yazar (yeniden çalıştırmak baştan kurar):
   - **drive** → `izmir_roads_noded` (~367 bin kenar): araç ağı
   - **walk** → `izmir_yaya_noded`: yaya ağı — patika, merdiven, yaya yolu, servis yolları dahil OSM'deki yürünebilir her yol

   Rota endpoint'i `mode=drive|walk` parametresiyle ağ seçer; yaya modunda eğim katsayısı 2 kat (0.10), trafik cezası yok.

Bunlar kurulmadıysa endpoint dürüstçe `status: "unavailable"` döner.

Nokta → yol ağı bağlantısında otoyol ve bağlantı rampaları atlanır (otoyolun yanındaki biri otoyolda değildir); en yakın 8 uygun kenarın uçlarından en yakın düğüm seçilir.

### 🏕️ Toplanma alanları

Hedef verilmeyen rota, **İzmir Büyükşehir Belediyesi açık verisindeki 2.380 afet ve acil durum toplanma alanına** gider: kuş uçuşu en yakın 8 alan aday olur, aralarından risk ağırlıklı rota maliyeti en düşük olan seçilir (en yakın alan yokuş, deprem ya da trafik yüzünden en güvenlisi olmayabilir). Yağış senaryosu seçiliyse adaylar o senaryoda su altında olmayan en yakın 8 alandır. Kurulum (yol ağı kurulduktan sonra):

```bash
psql -h localhost -p $DB_PORT -U $DB_USER -d $DB_NAME -f migrations/005_toplanma_alanlari.sql
venv/bin/python -m hesap.toplanma_alanlari_yukle   # İBB CSV'sini indirir, alanları yol ağına bağlar
```

Kaynak: [acikveri.bizizmir.com — Afet ve Acil Durum Toplanma Alanları](https://acikveri.bizizmir.com/dataset/afet-ve-acil-durum-toplanma-alanlari) (İBB Açık Veri Lisansı). Alan listesi `/api/v1/toplanma_alanlari`'ndan sunulur. Hedef verilmezse otomatik seçilen alana, `dest_lon`/`dest_lat` verilirse o noktaya rota çizilir.

Rota yalnızca OSM yol verisi (sokak, patika, merdiven, yaya yolu) üzerinde hesaplanır. Tıklanan noktadan yol ağına ve ağdan alanın kendisine kalan kısım veride yoktur; yanıttaki `ag_giris` / `ag_cikis` düğümleriyle haritada kesikli çizgi (kuş uçuşu, yürüyerek) olarak gösterilir ve mesafeye eklenir.

## 🌊 Sel / Su Baskını Riski

Soldaki **🌊 Sel / Su Baskını** paneli üç harita gösterir:

- **Arazi duyarlılığı** (yağıştan bağımsız): kuvvetli yağışta suyun toplandığı ya da taştığı yerler.
- **Önümüzdeki 24 saat:** duyarlılık × yağış şiddeti. Yağış beklenmiyorsa risk yoktur.
- **Yağış senaryosu:** "X mm yağış Y saatte düşerse nereyi, ne derinlikte su basar?" (aşağıda).

**Duyarlılık nasıl hesaplanır** (`hesap/sel_duyarlilik_hesapla.py`, pysheds). Bu bir eğitilmiş model **değil**, yükseklik verisinden hidrolojik hesaptır; eşikler uzman varsayımıdır:

1. SRTM yükseklik verisi ~60 m'ye ortalanır (8 GB bellekte il geneli 30 m sığmıyor). Çukurlar doldurulur, her hücrenin akış yönü ve kendisine akan alan hesaplanır.
2. **Dere yatağına göre yükseklik (HAND):** küçük dereler (≥1 km² drenaj) ve büyük dere/çaylar (≥50 km²) için ayrı ayrı. `h = 1 − HAND/6 m`; HAND < ~5 m alanlar taşkına açıktır (Nobre vd. 2011).
3. **Çukur derinliği:** suyun akıp gidemediği kapalı alanlar. `ç = derinlik / 1 m`.
4. **S = max(0.7·h₁, h₅₀, ç)**, 0–1 arası. Bantlar: Orta ≥0.3, Yüksek ≥0.6, Çok Yüksek ≥0.85.
5. **Yol kenarları:** kenar boyunca ~25 m'de bir örneklenen S'nin en büyüğü (`sel_duyarlilik` kolonu).
   - OSM köprüleri hariç tutulur, çünkü yol suyun üstünden geçer.
   - Kısa tüneller (<400 m; kentte alt geçit) yükseklik verisinde görünmez ama su biriktirir. Bunlar S ≥ 0.9 sayılır (`alt_gecit` kolonu, haritada 🚇).

**Yağış katsayısı f** (`afet/sel/risk.py`): Open-Meteo saatlik tahmini 0.25° ızgarada çekilir (1 saat önbellek) ve WMO şiddet sınıflarına çevrilir:

| Saatlik yağış | Sınıf | f |
|---|---|---|
| < 0.5 mm | Yok | 0 |
| < 2.5 mm | Hafif | 0.15 |
| < 7.6 mm | Orta | 0.4 |
| < 50 mm | Kuvvetli | 0.8 |
| ≥ 50 mm | Çok kuvvetli | 1 |

Bu sınıflamaya iki kural eklenir:
- 24 saat toplamı ≥ 50 mm ise en az kuvvetli, ≥ 100 mm ise çok kuvvetli sayılır (proje varsayımı).
- Son 6 saatte düşen yağış da hesaba girer.

**Rota:** yağış bekleniyorsa (f > 0) kenar maliyeti `× (1 + 4·f·S)` olur. Toplanma alanı rotası dere yatağı, çukur ve alt geçitlerden kaçar. Rota özeti, rotanın duyarlı kesimden geçen uzunluğunu ve alt geçit sayısını verir; bu kesimler haritada mavi kesikli çizilir. Yağış yoksa rota değişmez.

**Sınırlar:**
- 60 m çözünürlük tek tek sokakları ayırt edemez.
- Kanalizasyon kapasitesi, dere ıslahı ve kıyı taşkını (fırtına kabarması) hesapta yoktur.
- İl dışından gelen büyük havzaların (ör. Gediz) yukarı kesimi ancak 0.15° tampon kadar dahildir.
- Belediyenin LiDAR yükseklik verisi ve su baskını ihbar kayıtları ile sonuç doğrulanıp eğitilmiş bir modele (GeoAI) dönüştürülebilir.

```bash
psql -h localhost -p $DB_PORT -U $DB_USER -d $DB_NAME -f migrations/006_sel_duyarlilik.sql
venv/bin/python -m hesap.sel_duyarlilik_hesapla   # yol ağı yeniden kurulursa tekrar çalıştırılmalı
```

### 🌧️ Kademeli yağış senaryosu (`hesap/sel_senaryo_hazirla.py`, `afet/sel/senaryo.py`)

Kullanıcı kaydırıcıyla yağış miktarını (10–250 mm) ve süresini (1 / 6 / 24 saat) seçer. Harita suyun derinliğini dört sınıfta gösterir: 10–30 cm, 30 cm–1 m, 1–2 m, 2 m+. Özet şunları verir:
- 30 cm'den derin su alanı (km²)
- araçla geçilemez yol uzunluğu
- alt geçitlerde birikme riski
- su basan toplanma alanları
- en çok etkilenen mahalleler (TKGM)

Bu bir **fizik tabanlı, basitleştirilmiş simülasyondur**, eğitilmiş model değildir. 24 senaryo çevrimdışı bir kez hesaplanır (~2 dk):

1. **Yüzey akışı:** SCS eğri numarası (USDA TR-55). CN, **ESA WorldCover** arazi örtüsünden (uydu görüntülerinden yapay zekâ ile üretilmiş, 10 m) alınır; toprak grubu C kabul edilir. Göl, baraj ve deniz yüzeyi akış üretmez.
2. **Kent drenajı:** yapılaşmış alanda şebeke saatte 20 mm taşır; fazlası yüzeyde kalır.
3. **Dere taşkını:** akış SRTM (~60 m) üzerinde biriktirilir; tepe debisi üçgen hidrografla bulunur. Dereler 2 yılda bir görülen yağışı (1 saatte 25 mm ya da 24 saatte 60 mm) taşmadan taşır. Fazlası, HAND'dan türetilen sentetik anahtar eğrisiyle (Zheng vd. 2018, NOAA OWP HAND-FIM) yatak dışına yayılır: düz ovada su geniş alana yayılıp sığ kalır, dar vadide derinleşir.
4. **Çukurlar:** kendilerine akan hacim kadar alttan dolar. Şunlar hariç tutulur: 10 m'den derin çukurlar, içinden dere geçen çukurlar (köprü / yol dolgusu izi) ve kalıcı su yüzeyleri.
5. **Yağış alanı:** senaryo yağışı yalnızca il sınırı içine düşer; Manisa'dan gelen Gediz suyu senaryoya girmez. Geniş havzalarda alan azaltma katsayısı uygulanır (ARF, Leclerc & Schaake 1972 / NWS TP-29): 10.000 km²'lik havzaya 1 saatte noktadaki yağışın ~%67'si düşer.
6. **Gediz:** havzası 5000 km²'den büyük nehir taşırılmaz. Taşkını DSİ baraj işletmesine ve seddelere bağlıdır.
7. **Düz ova (gri):** Gediz deltası ve Menemen ovası gibi içinden dere geçen, 1 km²'den büyük düzlüklerde (il içinde ~520 km²) SRTM'nin birkaç metrelik hatası akış yönünü belirsiz kılar. Bu düzlüklerin derinliğine bakılmaz: Menemen ovası yükseklik verisinde taşma seviyesinin 13 m altına inen 411 km²'lik tek bir çukurdur. Burada derinlik verilmez; aksi hâlde pysheds'in düzlüğe çizdiği yapay düz akış çizgileri yıldız biçimli sahte taşkın üretir. Düzlüğün (göl / deniz yüzeyi hariç) %10'u ıslanırsa tamamı "su gelir, derinlik belirsiz" gösterilir ve ayrı km² olarak verilir.

**Makullük kontrolü:**
- 10 mm yağış il genelinde ~2 km², 25 mm / 1 saat ~7 km² su (30 cm+) verir.
- 50 mm / 1 saat ~250 km², 100 mm / 24 saat ~170 km² verir.
- En çok etkilenen yerler Küçük Menderes (Torbalı, Bayındır, Selçuk, Tire) ve Bakırçay (Bergama, Kınık) ovalarıdır. Bu ovaların bilinen taşkın geçmişi vardır.
- Gerçek bir olayla karşılaştırma için aşağıdaki "Geçmiş selle doğrulama" bölümüne bakın.

**Sınırlar:**
- Kıyıdaki düz kent alanlarında kanalizasyon geri tepmesiyle oluşan birikmeyi yakalamaz (2021'de Bostanlı, Alsancak gibi). Bunun için İZSU şebeke verisi gerekir.
- Alt geçitler tek kurala bağlıdır: kent drenajı aşılırsa hepsi risk altında sayılır.
- Gediz gibi il dışı havzaların yukarı kesimi, deniz kabarması, baraj işletmesi ve bina içleri hesapta yoktur.
- Tahmin değil, "olursa ne olur" aracıdır.

```bash
venv/bin/python -m hesap.sel_senaryo_hazirla   # hesap/sel_duyarlilik_hesapla.py'nin DEM önbelleğini kullanır
```

### ✅ Geçmiş selle doğrulama (`hesap/sel_dogrulama.py`, `dogrulama/`)

Senaryo modeli **2 Şubat 2021 İzmir seliyle** karşılaştırıldı. O gün merkezde 8–14 saatte 100–140 mm yağış düştü; 2 kişi öldü.

**Gerçek veri:** haberlerde (AA, Cumhuriyet, İnşaport, İBB) adı geçen, su basan yerler elle derlendi: `dogrulama/olay_2021_02_02.json`. Her kayıtta kaynak bağlantısı ve suyun nedeni vardır (dere taşkını / kıyı-drenaj / belirtilmemiş). Konumu belirsiz anlatımlar ("bazı sokaklar") alınmadı. Toplam:
- 7 mahalle
- 5 cadde
- 1 dere hattı (Poligon)
- 1 alt geçit (Konak)

**Yöntem:** haber yalnız su basan yeri söyler, basmayan yerlerin listesi yoktur. Bu yüzden şu soru soruldu: haberdeki yerler, modelde aynı 6 ilçenin (Balçova, Bayraklı, Bornova, Karabağlar, Karşıyaka, Konak) öteki 167 mahallesinden ve 207 caddesinden daha mı ıslak?
- **AUC** ölçüsü kullanıldı. 0.5 yazı-tura demektir, 1 kusursuz demektir.
- Olaya en yakın senaryolar 100–150 mm / 6–24 saattir. 50 mm / 1 saat yağışın en yoğun saatini temsil eder.

**Sonuç (dürüst özet):**

| Ölçü | 6 saatlik senaryolar | 24 saatlik senaryolar |
|---|---|---|
| Mahalle AUC (yalnız hesaplanan derinlik) | 0.51–0.53 | 0.53–0.56 |
| Haberdeki caddelerde 30 cm+ nokta | 3/5 | 2/5 |
| Öteki caddelerde 30 cm+ nokta | %24–29 | %17–22 |
| Cadde AUC | 0.61–0.64 | 0.63–0.65 |

- **Mahalle düzeyinde model bu seli ayırt edemiyor** (AUC ≈ 0.5).
- **Cadde düzeyinde zayıf bir sinyal var:** haberdeki caddelerde 30 cm+ su noktası öteki caddelerden ~2 kat sık. Ancak örnek yalnız 5 caddedir.
- **Yakaladıkları:**
  - Örnekköy ve Yamanlar (Bayraklı) mahalleleri ıslaklıkta ilk %12–20'dedir.
  - Poligon Deresi hattında 0.2–0.8 m su vardır.
  - Karşıyaka Anadolu Caddesi'nde 0.4–1.8 m su vardır.
- **Kıyıdaki drenaj taşkınını kaçırıyor** (Alsancak, Güzelyalı, Mithatpaşa ve Cemal Gürsel caddeleri). Model buralarda derinlik hesaplamaz. Kısa senaryolarda bu yerler yalnız "düz ova, su gelebilir" (gri) çıkar; düz ova ıslak sayılırsa mahalle AUC'si 0.56–0.57'ye çıkar. Bu, bilinen sınırdır: İZSU şebeke verisi gerekir.
- **Küçük kent derelerini kaçırıyor** (Soğukkuyu ve Çetin Emeç'teki Hacı Ahmet deresi). Bu mahallelerde OSM'de 1–1.5 km dere var. Modelde dere ancak 1 km² drenaj alanından başlar ve 60 m ızgara dar dere yatağını göremez. Bu, varsayımdır; henüz doğrulanmadı.
- **Alt geçit:** Konak Alt Geçidi doldu. Model alt geçitleri yalnız kent drenajının (saatte 20 mm) belirgin aşıldığı senaryolarda dolu sayar: bu karşılaştırmada 50 mm / 1 saat ve 150 mm / 6 saat, 100 mm / 6 saat ve 24 saatlikler değil. O günün saatlik en yüksek yağışı kaynaklarda yok.

**Ne anlama gelir:** model geniş dere taşkınında ve büyük caddelerde yön gösterir. Bu selin asıl hasarını veren küçük dereleri ve kıyı drenajını ise henüz göstermez. Sonuçlar tek olaya ve küçük bir örneğe dayanır; istatistiksel kanıt değildir. Habersiz yerlerin bir kısmı da gerçekte su almış olabilir, bu da AUC'yi düşürür.

```bash
venv/bin/python -m hesap.sel_dogrulama   # ilk çalıştırmada OSM'den adlı yollar çıkarılır (~1 dk); sonuç dogrulama/sonuc_2021_02_02.json
```

### 🏕️ Toplanma alanı denetimi (`hesap/toplanma_denetimi.py`, `denetim/`)

2.380 toplanma alanı, senaryolardaki su derinliğiyle karşılaştırılır ve yerinde kontrol için önceliklendirilir. Bu bir **ön eleme listesidir**, hüküm değildir (model mahalle düzeyinde doğrulanamadı).

- **1. öncelik (25 alan):** yağış 24 saate yayılsa bile ≤ 100 mm'de alanın bulunduğu yerde 30 cm+ su.
- **2. öncelik (41 alan):** 100 mm / 6 saat ya da 150 mm / 24 saatte 30 cm+ su.
- **3. öncelik (131 alan):** yalnız daha şiddetli senaryolarda.
- **Düz ova (315 alan):** su gelebilir, derinlik bilinmiyor.
- **Ek işaretler:** arazi duyarlılığı çok yüksek (S ≥ 0.85) 102 alan; kendisi kuru ama yaya ağında bağlandığı kavşağın bütün yolları 2021 senaryosunda su altında kalan 27 alan.
- **Bağımsız sağlama:** 1.–2. öncelikli 66 alanın 13'i OSM'de çizili bir dereye 100 m'den yakın (%20); öteki alanlarda %5. Model OSM derelerini kullanmaz.

Çıktı: `denetim/toplanma_denetimi.csv` (işaretli alanlar) ve yayın sayfasındaki denetim bölümü.

```bash
venv/bin/python -m hesap.toplanma_denetimi   # ilk çalıştırmada OSM dereleri çıkarılır (~1 dk)
```

### 🚒 İtfaiye çağrıları: ilçe-gün eğitim veri seti (`hesap/ilce_gun.py`, `egitim/`)

Gözetimli bir regresyon modelinin (OLS, sonra coğrafi ağırlıklı regresyon) eğitim verisi. Soru: **"Bir ilçede bir günde X mm yağış düşerse itfaiyeye kaç su baskını çağrısı gelir?"** Model bu verinin üstüne ayrı betikte kurulacak.

- **Çağrılar:** İBB Açık Veri, "İzmir İtfaiyesi Kontrol, Emniyet, Tedbir ve Vatandaşa Verilen Hizmetlerin İstatistiği" (Haziran 2019 – Eylül 2026). "SU BASKINI (kontrol/emniyet/tetkik)" ve "SU ÇEKME (pompa)" hizmetleri sayılır; arazözle su verme sayılmaz. Toplam 18.623 su çağrısı. Kayıtlarda **mahalle ve adres yoktur**, bu yüzden birim ilçedir.
- **Yağış:** Open-Meteo geçmiş arşivi (ERA5 yeniden analizi, saatlik). Her ilçe için tek nokta: ilçedeki yapılaşmış alanın ağırlık merkezi. Kolonlar: günlük toplam, en yoğun 1 ve 3 saat, önceki gün, önceki 3 ve 7 gün.
- **İlçe özellikleri** (`egitim/ilce.csv`): nüfus (İBB / TÜİK, 2023), yapılaşmış alan ve payı (ESA WorldCover).
- **Çıktı:** `egitim/ilce_gun.csv` — 30 ilçe × 2.676 gün = 80.280 satır; çağrı olmayan günler 0 olarak durur.

**İlk bakış:** 100 bin kişi başına günlük çağrı yağışla düzenli artar: kuru günde 0.06, 10–20 mm'de 0.8, 40–80 mm'de 3.9. 2 Şubat 2021'de 545 çağrı var (Konak 132, Foça 87, Bayraklı 66).

**Bilinen sınırlar:**
- **Arşiv yağışı yerel sağanağı yumuşatır.** 2 Şubat 2021'de merkezde ölçülen ~128 mm'nin ~65 mm'sini verir. Konak, Bayraklı ve Karşıyaka aynı hücreye düşer (30 ilçede 24 farklı yağış serisi). Bazı günlerde şüphelidir: 11 Kasım 2023'te Torbalı için 148 mm verir, o gün çağrı yoktur. MGM istasyon verisi bunu düzeltir.
- **Çağrılar olaydan sonra günlerce sürer.** 4–9 Şubat 2021'de yağış yokken günde 460–850 çağrı var (bodrum boşaltma, kontrol). Önceki günlerin yağışı bu yüzden kolondur.
- **Kayıt pratiği yıldan yıla değişir.** "Su baskını kontrol" kaydı 2019'da 76, 2021'de 5.184'tür. Model yıl etkisini ayrıca hesaba katmalıdır.
- **Su çağrılarının %15'i iki gündür kuru günlerde gelir** (boru patlağı, kapalı alan). Bu, yağıştan bağımsız bir taban değerdir.

```bash
venv/bin/python -m hesap.ilce_gun   # ilk çalıştırmada itfaiye_veri/ önbelleğine ~10 MB indirir (~1 dk)
```

### 📈 OLS regresyonu: yağış → itfaiye çağrısı (`hesap/ols_model.py`)

Gözetimli öğrenme: model, ilçe-gün veri setinden (2020–2026; 2019 kısmi yıl ve farklı kayıt pratiği yüzünden dışarıda) yağış ile itfaiye su çağrısı arasındaki ilişkiyi öğrenir.

`log(1+çağrı) ~ yağış + dünkü yağış + önceki 7 gün + log(nüfus) + kent payı + yağış × kent payı` (yağışlar log(1+mm)). En yoğun saatin yağışı modelden çıkarıldı: günlük toplamla birlikte VIF ≈ 17 (iki değişken aynı bilgiyi taşıyor), katsayısı anlamsızdı (p = 0.87); çıkınca bütün VIF'ler < 2. Standart hatalar güne göre kümelenir (aynı gün bütün ilçeler aynı fırtınayı yaşar).

**Bulgular:**
- **Yağışın etkisi kentleşmeye bağlı.** En güçlü terim yağış × kent payı (p ≈ 10⁻²⁰). Aynı yağış artışı, kent payı 0.79 olan Konak'ta, 0.006 olan Kiraz'dan ~6 kat fazla çağrı artışı getirir (log ölçekte eğim 0.25'e karşı 0.04).
- **Önceki günler önemli:** dünkü yağış ve önceki 7 günün yağışı anlamlı. Çağrılar olaydan sonra sürer.
- **Görülmemiş yıllarda da tutuyor:** 2020–2024 ile eğitilen model 2025–2026'da R² 0.114 verir (eğitimde 0.11); yağışsız temel model 0.

| Sınama | Model | R² (log) | İl geneli günlük r | Olay günleri: gerçek / tahmin |
|---|---|---|---|---|
| Zaman (2025–26) | OLS | 0.114 | 0.56 | 3.409 / 387 |
| | yağışsız temel | −0.007 | 0.00 | 3.409 / 194 |
| | Poisson | — | **0.74** | 3.409 / **2.131** |
| Mekân (ilçe dışarıda) | OLS | 0.100 | 0.34 | 13.222 / 1.139 |
| | Poisson | — | 0.43 | 13.222 / 3.674 |

Olay günü: il genelinde ≥ 50 çağrı.

**Sınırlar:**
- **OLS fırtına günlerini çok düşük tahmin ediyor.** Günlerin %95'inde çağrı yok. log(1+y) üzerinde OLS'nin geri dönüşümü (Duan smearing) sabit bir çarpandır; çağrıları sakin günlere yayar. Aynı değişkenlerle Poisson regresyonu (sayım modeli) olay günlerini 5 kat daha iyi yakalıyor. Sayım verisi için doğru araç bu; OLS okunabilir temel model olarak kalıyor. Poisson'un R²(log) değeri anlamlı değildir (log ölçeği optimize etmez), bu yüzden tabloda yok.
- **R² düşük (~0.1) ama bu beklenen bir sonuç.** Günlük çağrının çoğu yağıştan bağımsız (boru patlağı, tek tük bodrum), arşiv yağışı yerel sağanağı yumuşatıyor (veri seti bölümüne bakın).
- **Mekânda olay günleri tutmuyor:** 2020–24'ün en büyük olay günleri 2021 selinin yağışsız artçı günleri (4–9 Şubat). Model bunları önceki 7 günün yağışından ancak kısmen görebilir.
- **İlçe artıkları örüntülü:** Foça, Seferihisar, Konak ve Dikili sürekli az; Bayraklı, Gaziemir ve Balçova sürekli fazla tahmin ediliyor. Tek global denklem bütün ilçelere uymuyor; bu, GWR'nin konusu.

```bash
venv/bin/python -m hesap.ols_model   # ~5 sn; sonuç egitim/ols_sonuc.json
```

### 🧭 Rota ve yağış senaryosu (`hesap/sel_senaryo_yollar.py`, `migrations/011`)

Sel panelinde "Yağış senaryosu" açıkken tahliye rotası haritada görünen senaryoya göre çizilir; kaydırıcı ya da süre değişince rota yeniden hesaplanır.

**Hazırlık:** her senaryonun derinlik ızgarası, araç ve yaya ağının her kenarında ~25 m'de bir örneklenir. Kenarın derinliği bu örneklerin **en büyüğüdür**, çünkü yolun tek bir noktası suyun altındaysa o yoldan geçilemez. Köprü ve uzun tünel üstündeki noktalar sayılmaz. Toplanma alanları kendi konumlarında örneklenir. Yalnız 10 cm+ ıslak ya da düz ovada (gri) kalan kenarlar ve alanlar `sel_senaryo_su` tablosuna yazılır.

**Maliyet:**
- Kenarın en derin noktası **30 cm+** ise yol kapalı sayılır: maliyetine 100 km eklenir. Bu, başka yol varsa her geçişin ~100 km dolambaçtan pahalı olduğu anlamına gelir. Başka yol yoksa (ör. başlangıç su içinde) rota yine çizilir ve uyarı verilir.
- **10–30 cm** su ya da düz ova belirsizliği maliyeti 5 kat artırır.
- Senaryoda kent drenajı aşılıyorsa (özetteki alt geçit riski) alt geçitler de kapalıdır.
- 24 saatlik yağış tahmininin sel cezası senaryo seçiliyken uygulanmaz.

**Toplanma alanı:** 30 cm+ su altındaki ya da düz ovadaki (derinliği belirsiz) alanlar aday olmaz; haritada gri görünürler. Kullanıcı gri bir alanı kendisi seçerse rota çizilir ama uyarı verilir.

**Rota özeti:** rotanın kaç yerde 30 cm+ ve 10–30 cm sudan geçtiği, en derin nokta, düz ovadan geçen uzunluk, alt geçit durumu ve suda kaldığı için atlanan daha yakın alanlar. Art arda ıslak kenarlar tek "yer" sayılır. Kenarın tamamı değil yalnız bir noktası suda olabileceği için metre yerine yer sayısı verilir. Suyun bastığı kesimler haritada kırmızı (30 cm+) ve turuncu (10–30 cm) kesikli çizilir.

**Örnek (50 mm / 1 saat, araç):** Bornova'da (38.452, 27.205) senaryosuz rota en yakın alana 1.0 km gider. Senaryoda bu yol dere hattında 1.2 m'ye kadar su altında kalır; rota sudan kaçarak 2.5 km'lik başka bir alana gider. Gediz deltasında (38.585, 27.000) düz ovadaki 15 alan atlanır ve rota ova dışındaki bir alana 9 km gider.

**Sınırlar:**
- Su derinliği 60 m ızgaradandır. Dere kenarındaki bir sokak, yan sokaktan ayırt edilemeyebilir; rota bazen gerçekte kuru olan bir yoldan kaçar ya da tersi olur.
- Düz ovadaki belirsizlik temkinli yorumlanır: ovanın tamamı "su gelebilir" sayılır. Kısa ve şiddetli senaryolarda (50 mm / 1 saat) Gediz deltası ve Menemen ovasındaki kişiler ova dışına yönlendirilir; bu gerçek sudan çok veri belirsizliğinden kaynaklanabilir.
- Senaryo suyun en yüksek anını gösterir; zamanla çekilmesi (hangi yolun kaç saat kapalı kaldığı) hesapta yoktur.

```bash
psql -h localhost -p $DB_PORT -U $DB_USER -d $DB_NAME -f migrations/011_sel_senaryo_su.sql
venv/bin/python -m hesap.sel_senaryo_yollar   # yol ağı ya da toplanma alanları yenilenirse tekrar
```

### 🗺️ Sunucusuz sitede rota: tarayıcıda Dijkstra (`hesap/rota_agi_hazirla.py`, `docs/js/cekirdek/rota_motoru.js`)

Yayın sitesinin Rota sekmesinde kullanıcı haritada istediği yere tıklar ya da işaretçiyi sürükler, yağışı ve süresini değiştirir. Rota her değişiklikte **tarayıcıda** yeniden hesaplanır (1–3 ms); sunucu ya da veritabanı gerekmez.

- **Ağ:** merkezdeki 11 ilçenin (Balçova, Bayraklı, Bornova, Buca, Çiğli, Gaziemir, Güzelbahçe, Karabağlar, Karşıyaka, Konak, Narlıdere) araç yolu ağı. OSM iki yönlü yolu iki kenar olarak verir; rota yönsüz hesaplandığı için ikizler atılır (152 bin → 82 bin yol parçası). Kavşak olmayan düğümler zincir halinde birleştirilir, geometri ~3 m'de sadeleştirilir, koordinatlar 1e-5° tamsayı farkları olarak yazılır: `docs/veri/rota/ag.json` 2.5 MB (gzip ~0.8 MB), 54 bin düğüm, 873 toplanma alanı.
- **Su:** her senaryo için ayrı küçük dosya (`su_<mm>_<saat>.json`, gzip 2–60 kB): ıslak kenarın ek maliyeti, en derin noktası, kapalı toplanma alanları. Yalnız seçilen senaryonun dosyası indirilir.
- **Maliyet:** sunucudaki pgRouting sorgusunun senaryo kısmıyla aynı (yukarıda): uzunluk × (1 + eğim × 0.05); sığ su / düz ova ×5; 30 cm+ su ve dolu alt geçit +100 km. Canlı deprem ve trafik cezası sayfada yoktur.
- **Hedef:** sunucu kuş uçuşu en yakın 8 alanı aday alıyordu; tarayıcıdaki çok hedefli Dijkstra, açık alanların **hepsi** arasından en düşük maliyetle ulaşılanı bulur (ilk ulaşılan açık alan düğümünde durur).
- **Karşılaştırma:** yağış seçiliyken aynı başlangıçtan yağışsız günün rotası da hesaplanır ve kesikli gri çizilir. Panel rotanın ne kadar uzadığını, hedefin değişip değişmediğini ve hangi sudan geçtiğini söyler.

```bash
venv/bin/python -m hesap.rota_agi_hazirla   # DB açık; ~10 sn
```

## 🚦 Trafik (isteğe bağlı, TomTom API anahtarı gerektirir)

`.env`'e `TOMTOM_API_KEY=...` eklenirse TomTom Incident Details v5, il çerçevesi 2×2 çeyreğe bölünerek 10 dk'da bir çekilir (576 istek/gün — ücretsiz katman 2500 sınırının altında). Olaylar `canli_trafik_olaylari` tablosunda tutulur, 2 saattir görünmeyenler silinir (`migrations/004`). Araç rotasında ciddi olaylara (şiddet ≥2 veya yol kapalı) ~300 m'den yakın kenarlar 3× cezalandırılır. Anahtar yoksa trafik döngüsü başlamaz, rota trafik cezasız çalışır.

## 🧪 Test

```bash
pytest
```

## 📚 Veri kaynakları ve lisanslar

Kod **MIT** lisanslıdır (`LICENSE`). Veriler kendi koşullarına tabidir; depodaki türetilmiş dosyalar (`sel_model/`, `sinir/*.geojson`, `docs/veri/`, `dogrulama/`, `egitim/`) bu kaynaklardan üretilmiştir:

| Veri | Kaynak | Koşul |
|---|---|---|
| Yollar, dereler, köprüler, kıyı çizgisi | © OpenStreetMap katkıcıları (Geofabrik dökümü, Overpass) | ODbL 1.0 — atıf ve türetilmiş veritabanında aynı lisans |
| Yükseklik | SRTM (NASA / USGS), AWS Terrain Tiles üzerinden | Kamu malı; atıf önerilir |
| Arazi örtüsü | ESA WorldCover 2021 v200 | CC BY 4.0 |
| Toplanma alanları | İzmir Büyükşehir Belediyesi Açık Veri Portalı | İBB Açık Veri Lisansı — atıf |
| İlçe ve mahalle sınırları | TKGM (MEGSİS idari yapı servisi) | Açık bir veri lisansı yayımlanmamıştır; yalnız görselleştirme ve analiz için, atıfla kullanılmıştır |
| Deprem (canlı, rota maliyeti) | Boğaziçi Üniversitesi Kandilli Rasathanesi (KRDAE), api.orhanaydogdu.com.tr aracılığıyla | Atıf zorunlu; ticari kullanım izne bağlı; veri depoda tutulmaz |
| Yağış tahmini | Open-Meteo | CC BY 4.0 |
| Geçmiş yağış (eğitim verisi) | Open-Meteo Historical Weather API (Copernicus ERA5 / ERA5-Land) | CC BY 4.0; ERA5 için Copernicus atfı |
| İtfaiye hizmet kayıtları | İzmir Büyükşehir Belediyesi Açık Veri Portalı | İBB Açık Veri Lisansı — atıf |
| İlçe nüfusu | İzmir Büyükşehir Belediyesi Açık Veri Portalı (TÜİK ADNKS) | İBB Açık Veri Lisansı — atıf |
| Trafik olayları (isteğe bağlı) | TomTom Traffic API | TomTom kullanım koşulları; veri depoda tutulmaz |
| Harita altlığı | Esri (Light Gray Canvas vb.), OpenTopoMap | Sağlayıcı koşulları; haritada atıf gösterilir |
| 2 Şubat 2021 olay yerleri | Anadolu Ajansı, Cumhuriyet, İnşaport, İBB haberleri | Yalnız yer adları ve kısa özet; her kayıtta kaynak bağlantısı |

Bu çalışma bir araştırma ve yetkinlik gösterimidir; resmî bir uyarı ya da planlama ürünü değildir.
