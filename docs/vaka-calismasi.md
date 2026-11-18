# 2 Şubat 2021 İzmir seli yeniden yaşansa ne olur?

**Açık veriyle bir sel senaryosu modeli, tahliye rotası ve gerçek olayla karşılaştırma**

> Taslak — yayın sayfasının (GitHub Pages) Türkçe metni. Sayılar `hesap/sel_dogrulama.py`,
> `sel_model/senaryo_ozet.json` ve veritabanından üretilmiştir (11 Kasım 2026).

## Özet

İzmir için, yalnız herkese açık verilerle (uydu yükseklik verisi, OpenStreetMap, ESA arazi örtüsü, İBB toplanma alanları) bir sel senaryosu modeli kurdum. Model "şu kadar yağmur şu kadar saatte yağarsa nereyi su basar, hangi yollar kapanır, toplanma alanına hangi yoldan gidilir" sorusunu yanıtlıyor. Sonra modeli gerçek bir olayla, 2 Şubat 2021 seliyle sınadım.

Sonuç iki parçalı:

- **Çalışan kısım:** veri hattı, su derinliği haritası, su basan yollardan kaçan rota ve hepsini gösteren web haritası uçtan uca çalışıyor.
- **Sınırı:** model büyük dere hatlarını ve ana caddeleri kısmen yakalıyor, ama su basan mahalleleri ötekilerden ayırt edemiyor. Kıyıdaki kanalizasyon taşkınını ve küçük kent derelerini göremiyor. Bunun nedeni yöntemden çok verinin çözünürlüğü.

Bu çalışma bir uyarı sistemi değil; açık veriyle nereye kadar gidilebildiğini ve kurum verisinin nerede şart olduğunu gösteren bir vaka çalışmasıdır.

## 1. Olay

2 Şubat 2021'de İzmir merkezine bir gecede aylık ortalamanın üstünde yağmur düştü.

| İstasyon | Yağış | Süre |
|---|---|---|
| İzmir merkez | 128–142 mm | 11–14 saat |
| Bayraklı | 115–129 mm | 11–14 saat |
| Güzelyalı | 126 mm | bir gece |
| Karabağlar | 119 mm | bir gece |
| Balçova | 99–109 mm | 11–14 saat |
| Bornova | 71–87 mm | 11–14 saat |

- 2 kişi hayatını kaybetti.
- Hacı Ahmet, Poligon, Soğukkuyu ve başka dereler taştı.
- Alsancak, Güzelyalı ve Mithatpaşa Caddesi'nde ev ve iş yerlerini su bastı.
- Konak Alt Geçidi doldu; Karşıyaka'da Anadolu Caddesi trafiğe kapandı.

Kaynaklar: [Anadolu Ajansı](https://www.aa.com.tr/tr/turkiye/izmirde-saganak-sel-ve-su-baskinlarina-neden-oldu-/2130674), [Cumhuriyet](https://www.cumhuriyet.com.tr/haber/tunc-soyerden-evden-cikmayin-uyarisi-1810674), [İnşaport](https://www.insaport.com/haberler/izmirde-sel-felaketi-can-kaybi-2ye-yukseldi/), [İzmir Büyükşehir Belediyesi](https://www.izmir.bel.tr/tr/Haberler/bir-yillik-yagmurun-yuzde-18-i-bir-gecede-yagdi/44620/156).

## 2. Model

Eğitilmiş bir yapay zekâ modeli değil; fizik tabanlı, basitleştirilmiş bir hesap. Dört adım:

1. **Yağmurun ne kadarı yüzeyde kalır?** Arazi örtüsüne göre (beton, tarla, orman) hesaplanır. Kentte yağmur suyu kanallarının saatte 20 mm taşıdığı varsayılır.
2. **Su nereye akar?** Yükseklik verisi üzerinde her hücrenin suyu en alçak komşusuna gönderilir; dereler böyle ortaya çıkar.
3. **Dere ne zaman taşar?** Her derenin iki yılda bir görülen yağışı taşıdığı varsayılır. Fazlası yatağın dışına, arazinin dereye göre yüksekliğine bakılarak yayılır.
4. **Sonuç yollara ve toplanma alanlarına yazılır.** Araç ve yaya ağındaki her yol parçası için o senaryodaki en derin su noktası bulunur.

| Veri | Kaynak | Çözünürlük |
|---|---|---|
| Yükseklik | SRTM (uydu) | ~60 m |
| Arazi örtüsü | ESA WorldCover | 10 m |
| Yollar, dereler, köprüler | OpenStreetMap | 367 bin araç, 553 bin yaya yol parçası |
| Toplanma alanları | İBB Açık Veri | 2.380 alan |
| İlçe ve mahalle sınırları | TKGM | – |

Teknoloji: PostGIS, pgRouting, Python (pysheds, rasterio, shapely), FastAPI, Leaflet. 24 senaryo (10–250 mm, 1 / 6 / 24 saat) önceden hesaplanır; yeniden hesap ~5 dakika sürer.

## 3. Karşılaştırma

**Gerçek veri:** haberlerde adıyla geçen, su basan 7 mahalle, 5 cadde, 1 dere hattı ve 1 alt geçit. Her kayıt kaynağıyla birlikte `dogrulama/olay_2021_02_02.json` dosyasında.

**Yöntem:** haberler yalnız su basan yerleri yazar. Bu yüzden şunu sordum: haberdeki yerler, modelde aynı 6 ilçenin öteki 167 mahallesinden ve 207 caddesinden daha mı ıslak? Puan 0.5 ise model yazı-tura kadar iyidir, 1 ise kusursuzdur. O günün yağışına en yakın senaryolar 100–150 mm / 6–24 saattir.

| Ölçü | Sonuç |
|---|---|
| Mahalle puanı | 0.51–0.56 |
| Cadde puanı | 0.61–0.65 |
| Haberdeki caddelerde 30 cm+ su | 5 caddeden 2–3'ü |
| Öteki caddelerde 30 cm+ su | %17–29 |

**Yakaladıkları**
- Karşıyaka Anadolu Caddesi: modelde 0.4–1.8 m su.
- Poligon Deresi hattı: 0.2–0.8 m su.
- Örnekköy ve Yamanlar mahalleleri en ıslak %12–20 içinde.

**Kaçırdıkları**
- **Kıyıdaki kanalizasyon taşkını** (Alsancak, Güzelyalı, Mithatpaşa ve Cemal Gürsel caddeleri). Burada su dereden değil, dolan şebekeden geldi. Modelde şebeke yok.
- **Küçük kent dereleri** (Soğukkuyu, Çetin Emeç'teki Hacı Ahmet Deresi). Modelde bu mahallelerde neredeyse hiç su yok.

**Bir düzeltme denemesi ve sonucu.** Küçük derelerin kaçmasının nedeni "dere modelde yok" olabilir diye düşündüm. OpenStreetMap'teki 3.713 dere hattını yükseklik verisine işledim ve küçük dereleri de taşabilir yaptım. Mahalle puanı yalnız 0.02–0.03 arttı; Soğukkuyu yine kuru kaldı, Yamanlar kötüleşti. Değişikliği geri aldım. Çıkardığım sonuç: sorun dere haritasının eksikliği değil. 60 m'lik yükseklik verisi, kent içinde kapatılmış ya da beton kanala alınmış dar dereleri ayırt edemiyor.

**Bu karşılaştırmanın sınırı:** tek olay ve küçük bir örnek. Habere girmeyen yerlerin bir kısmı da su almış olabilir; bu, puanı olduğundan düşük gösterir. Sonuçlar istatistiksel kanıt değil, modelin neyi görüp neyi göremediğinin ilk ölçümüdür.

## 4. Etki: aynı yağış yeniden yağsa

O günün yağışını kuşatan iki senaryo için, su basan 6 merkez ilçede (Balçova, Bayraklı, Bornova, Karabağlar, Karşıyaka, Konak; 441 km², 507 toplanma alanı, 6.773 km araç yolu) model şunu veriyor:

| | 100 mm / 6 saat | 150 mm / 24 saat |
|---|---|---|
| 30 cm'den derin su | 7.9 km² | 5.9 km² |
| 10 cm'den derin su | 18.6 km² | 14.6 km² |
| Su altında kalan toplanma alanı (30 cm+) | 15 | 11 |
| En az bir noktası 30 cm+ suda kalan yol parçası | 4.182 | 3.324 |

Kısa ve yoğun senaryoda (6 saat) ayrıca 34 km²'lik düz kıyı kesimi ve içindeki 147 toplanma alanı "su gelebilir, derinlik bilinmiyor" olarak işaretleniyor. Yükseklik verisi bu düzlüklerde suyun yönünü çözemiyor; model burada tahmin yürütmek yerine bilmediğini söylüyor.

**Tahliye rotası örneği (Bornova, 38.452 K, 27.205 D, araç):**
- Senaryo yokken en yakın toplanma alanına 1.0 km.
- 100 mm / 6 saatte bu yol su altında kaldığı için rota başka bir alana gidiyor: 2.1 km, yalnız iki yol parçasında sığ su.
- 150 mm / 24 saatte 2.1 km, sudan geçmeden.

Sitede başlangıç noktası sabit değil: haritada herhangi bir yere tıklanır ya da işaretçi sürüklenir, yağış değiştirilir, rota tarayıcıda birkaç milisaniyede yeniden hesaplanır. Yağışsız günün rotası da kesikli çizgiyle yanında gösterilir.

Rota hesabı, 30 cm'den derin su olan yolu kapalı sayar ve su altındaki toplanma alanını hedef seçmez. Kuru yol yoksa bunu açıkça söyler.

Bir uyarı: sel anında resmi tavsiye çoğu zaman yola çıkmamak ve yüksekte kalmaktır. Buradaki rota bir "ne yapmalı" tavsiyesi değil; hangi yolların ve alanların kullanılamaz hale geldiğini gösteren bir planlama aracıdır.

## 5. Toplanma alanı denetimi: önce hangilerine bakılmalı?

İBB'nin 2.380 toplanma alanını modelin su derinliğiyle tek tek karşılaştırdım. Çıktı bir hüküm değil, bir **ön eleme listesi**: "şu alanlar güvensiz" demiyor, "yerinde ilk önce şunlara bakın" diyor.

| Öncelik | Kural (alanın bulunduğu yerde 30 cm'den derin su) | Alan |
|---|---|---|
| 1 | Yağış 24 saate yayılsa bile 100 mm ya da daha azında | 25 |
| 2 | 2 Şubat 2021'e yakın yağışta (100 mm / 6 saat ya da 150 mm / 24 saat) | 41 |
| 3 | Yalnız daha şiddetli senaryolarda | 131 |
| Düz ova | Su gelebilir, derinlik bilinmiyor | 315 |

Tam liste: `denetim/toplanma_denetimi.csv` (ilçe, mahalle, alan adı, koordinat, en küçük yağış, su derinliği).

**Nasıl okunmalı**
- Model burada kanıt değil, işaret. Aynı model 2021 selinde su basan mahalleleri ayırt edemedi.
- Her alan tek bir noktayla temsil ediliyor ve su derinliği 60 m'lik hücrelerden geliyor.
- Bağımsız sağlama: model dereleri yükseklik verisinden türetir, OpenStreetMap'i kullanmaz. 1. ve 2. öncelikli 66 alanın 13'i (%20) OSM'de çizili bir dereye 100 m'den yakın; öteki alanlarda bu oran %5. Öncelikli alanlar derelere belirgin biçimde daha yakın, ama çoğunun yanında haritada çizili bir dere yok.
- Kıyıdaki kanalizasyon taşkını listede yok; model onu göremiyor.

## 6. Kurum verisiyle ne değişir?

| Eksik | Gereken veri | Düzelteceği şey |
|---|---|---|
| Kıyıdaki şebeke taşkını | İZSU yağmur suyu ve kanalizasyon şebekesi | Alsancak, Güzelyalı gibi kaçırılan yerler |
| Küçük kent dereleri | Belediyenin hassas yükseklik ölçümü (LiDAR, 1 m) | Soğukkuyu, Hacı Ahmet gibi dar dere yatakları |
| Zayıf doğrulama | Belediyenin ve itfaiyenin su baskını ihbar kayıtları | 14 yer yerine yüzlerce noktayla sınama |
| Düz ovalardaki belirsizlik | DSİ taşkın haritaları, sedde ve baraj işletmesi | Gediz deltası ve Menemen ovası |

## 7. Bu çalışmada neler var?

- **Mekânsal veri hattı:** OSM'den yol ağı kurma, yükseklik verisinden eğim, TKGM sınırlarıyla il ve mahalle maskeleri.
- **Hidrolojik modelleme:** yüzey akışı, akış yönü ve birikimi, dere taşkını, kapalı çukurların dolması.
- **Ağ analizi:** pgRouting ile eğim, deprem, trafik ve sel cezalı tahliye rotası; 920 bin yol parçasında ~1 saniyede yanıt. Sunucusuz sitede aynı maliyetle tarayıcıda çalışan Dijkstra (82 bin yol parçası, birkaç ms).
- **Web uygulaması:** FastAPI + PostGIS arka uç, Leaflet harita, mobil uyumlu arayüz.
- **Doğrulama ve test:** gerçek olayla karşılaştırma betiği, 47 otomatik test, tekrar üretilebilir kurulum adımları.
- **Dürüst raporlama:** varsayımlar, sınırlar ve işe yaramayan deneme açıkça yazılı.
