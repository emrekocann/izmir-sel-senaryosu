# 2 Şubat 2021 İzmir seli yeniden yaşansa ne olur?

**Açık veriyle bir sel senaryosu modeli, tahliye rotası, gerçek olayla karşılaştırma ve itfaiye kayıtlarıyla eğitilmiş bir erken uyarı modeli**

> Taslak — yayın sayfasının (GitHub Pages) Türkçe metni. Sayılar `hesap/sel_dogrulama.py`,
> `sel_model/senaryo_ozet.json`, veritabanı ve `egitim/` altındaki sonuç dosyalarından alınmıştır (20 Kasım 2026).

## Özet

İzmir için, yalnız herkese açık verilerle (uydu yükseklik verisi, OpenStreetMap, ESA arazi örtüsü, İBB toplanma alanları) bir sel senaryosu modeli kurdum. Model "şu kadar yağmur şu kadar saatte yağarsa nereyi su basar, hangi yollar kapanır, toplanma alanına hangi yoldan gidilir" sorusunu yanıtlıyor. Sonra modeli gerçek bir olayla, 2 Şubat 2021 seliyle sınadım.

Ardından ikinci bir soruya geçtim: **hangi gün hangi ilçede sel olur?** Bunun için İzmir İtfaiyesi'nin 2020–2026 su baskını kayıtlarıyla bir erken uyarı modeli eğittim ve her yılı, yalnız kendinden önceki yıllarla eğitilen modelle sınadım.

Sonuç iki parçalı:

- **Çalışan kısım:** veri hattı, su derinliği haritası, su basan yollardan kaçan rota ve hepsini gösteren web haritası uçtan uca çalışıyor. Erken uyarı modeli, büyük sel ataklarının 23'ünden 17'sinde ilk gün alarm veriyor; bir gün önceki hava tahminiyle de çalışıyor.
- **Sınırı:** senaryo modeli büyük dere hatlarını ve ana caddeleri kısmen yakalıyor, ama su basan mahalleleri ötekilerden ayırt edemiyor. Kıyıdaki kanalizasyon taşkınını ve küçük kent derelerini göremiyor. Erken uyarı ilçe düzeyinde zayıf: alarmların yalnız beşte biri isabetli ve dar alanlı sağanağı yağış verisi göremiyor. İki parçada da sınırı çoğunlukla yöntem değil, verinin çözünürlüğü belirliyor.

Bu çalışma resmî bir uyarı sistemi değil; açık veriyle nereye kadar gidilebildiğini ve kurum verisinin nerede şart olduğunu gösteren bir vaka çalışmasıdır.

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

## 2. Sel senaryosu modeli

Senaryo modeli eğitilmiş bir yapay zekâ modeli değil; fizik tabanlı, basitleştirilmiş bir hesap (veriden öğrenen model 6. bölümde). Dört adım:

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

**Modelin de su gösterdiği yerler**
- Karşıyaka Anadolu Caddesi: modelde 0.4–1.8 m su.
- Poligon Deresi hattı: 0.2–0.8 m su.
- Örnekköy ve Yamanlar mahalleleri en ıslak %12–20 içinde.

**Modelin su göstermediği yerler**
- **Kıyıdaki kanalizasyon taşkını** (Alsancak, Güzelyalı, Mithatpaşa ve Cemal Gürsel caddeleri). Burada su dereden değil, dolan şebekeden geldi. Modelde şebeke yok.
- **Küçük kent dereleri** (Soğukkuyu, Çetin Emeç'teki Hacı Ahmet Deresi). Modelde bu mahallelerde neredeyse hiç su yok.

**Bir düzeltme denemesi ve sonucu.** Küçük derelerde su görünmemesinin nedeni "dere modelde yok" olabilir diye düşündüm. OpenStreetMap'teki 3.713 dere hattını yükseklik verisine işledim ve küçük dereleri de taşabilir yaptım. Mahalle puanı yalnız 0.02–0.03 arttı; Soğukkuyu yine kuru kaldı, Yamanlar kötüleşti. Değişikliği geri aldım. Çıkardığım sonuç: sorun dere haritasının eksikliği değil. 60 m'lik yükseklik verisi, kent içinde kapatılmış ya da beton kanala alınmış dar dereleri ayırt edemiyor.

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

## 6. Erken uyarı: hangi gün hangi ilçede sel olur?

Senaryo modeli fizikle çalışıyor ve gerçek bir olayla yalnız bir kez sınanabildi. Bu bölümdeki model ise veriden öğreniyor ve beş yıl boyunca her yıl yeniden sınanıyor.

**Veri**
- **Çağrılar:** İzmir İtfaiyesi'nin hizmet istatistikleri (İBB Açık Veri, Haziran 2019 – Eylül 2026); 18.623 su baskını ve su çekme çağrısı. Kayıtlarda adres yok, bu yüzden birim ilçe.
- **Olay:** bir ilçede bir günde en az 3 su baskını çağrısı.
- **Yağış:** Open-Meteo geçmiş arşivi (ERA5). Her ilçe için yapılaşmış alanın ağırlık merkezinde o günün, önceki günün ve önceki 3 ve 7 günün yağışı.
- **Eğitim verisi:** 2020–2026, 30 ilçe × 2.464 gün = 73.920 ilçe-gün; bunların 964'ü olay (%1.3).

**Model.** Beş model karşılaştırıldı: yağışsız temel model, lojistik regresyon, karar ağacı, Random Forest ve gradient boosting. Gradient boosting'e "daha çok yağış olasılığı düşüremez" kısıtı kondu. Parametreler ve model seçimi yalnız 2020–24 verisiyle yapıldı; seçilen model gradient boosting. Alarm eşiği, eğitim yıllarında isabet ile yakalama arasında en iyi dengeyi veren olasılık (%11.4).

| 2025–26 (modelin görmediği yıllar) | AP | Yakalanan olay | İsabetli alarm |
|---|---|---|---|
| yağışsız temel | 0.02 | %8 | %4 |
| lojistik regresyon | 0.25 | %44 | %26 |
| gradient boosting | 0.29 | %49 | %27 |

AP, modelin olay günlerini ne kadar öne sıraladığını ölçer: rastgele tahminde olay oranına (~0.02) eşittir, kusursuz modelde 1. Gradient boosting, 2025–26'nın 28 büyük sel gününün (il genelinde en az 50 çağrı) 22'sinde en az bir ilçede alarm verdi.

**Bir gün önceden: hava tahminiyle sınama.** Yukarıdaki sınama o günün gerçekte yağan yağmurunu kullanıyor; bu sayı gün bitince bilinir. Gerçek bir uyarıda elde olan, önceki günün hava tahminidir. Aynı model, o günün yağışı yerine bir gün önceki tahmin konarak sınandı (Open-Meteo geçmiş tahmin arşivi):
- ECMWF tahminiyle AP 0.29'dan 0.26'ya iniyor; 28 büyük sel gününün 23'ünde alarm var.
- Tahmin olmadan (yalnız geçmiş günlerin yağışıyla) yakalanan olay payı %43'ten %10'a düşüyor. Başarıyı hava tahmini taşıyor.

**Yıl yıl sınama ve ataklar.** Tek bir test dönemi şansa bağlı olabilir. Bu yüzden her yıl (2022–2026), yalnız kendinden önceki yıllarla eğitilen modelle tahmin edildi; parametreler ve eşik her yıl yeniden seçildi. Büyük sel günleri bağımsız değil, yağışlı dönemler günlerce sürüyor. Arka arkaya gelen günler tek **atak** sayıldı ve asıl erken uyarı sorusu soruldu: atağın ilk gününde alarm var mıydı? %95 aralıklar haftalık bloklarla bootstrap yöntemiyle hesaplandı.

| Gradient boosting, gerçek yağış | 2022 | 2023 | 2024 | 2025 | 2026 | 2022–26 |
|---|---|---|---|---|---|---|
| AP | 0.10 | 0.15 | 0.05 | 0.06 | 0.38 | 0.19 [0.12–0.26] |
| Büyük sel günü alarmlı | 4/7 | 15/18 | 2/4 | 3/9 | 19/19 | 43/57 |
| Atak, ilk gününde alarmlı | | | | | | 17/23 |

- İlçe olaylarının %36'sı yakalanıyor [%26–44]; alarmların %19'u isabetli [%13–26].
- Uyarı önceki gün öğlen, o anda elde olan ECMWF tahminiyle verildiğinde (2024–26): 8 atağın 6'sı ilk gününde alarmlı. Tahmin olmadan 2'si.
- Gradient boosting, lojistik regresyondan anlamlı biçimde iyi değil (2022–26 AP: 0.19'a 0.18). Basit model işin çoğunu yapıyor.

**2024–25 neden zayıf?**
- **Foça, 23 Ekim 2025:** 2025'in 9 büyük sel gününün 7'si bu tek yerel sağanağa ait. Valiliğe göre 1.5 saatte ~144 mm yağdı; yağış arşivi o gün Foça için 7 mm diyor, bir gün önceki tahminler 9–18 mm. Model değil, veri kör.
- **2024'te toprak kuruydu:** olay günlerinden önceki 7 günün ortalama yağışı 2024'te 16 mm, 2026'da 89 mm. Aynı yağış daha az sel getirdi, model fazla alarm verdi.
- Kaçırılan atakların çoğu tek günlük, dar alanlı yaz ve sonbahar sağanakları.

**Denediğim ve işe yaramayan iki değişken.** Kıyı ilçelerinin olayları çoğunlukla kaçırılıyordu. Güneyli kuvvetli rüzgâr (lodos) deniz suyunu kıyıya ve yağmur suyu kanallarına iter diye lodosu ekledim. Büyük ilçelerde sağanak, yağışın okunduğu tek noktayı ıskalayabilir diye ilçe içindeki ızgara noktalarının (~10 km aralıklı, 30 ilçede 156 nokta) en yağışlısını da ekledim.

| Gradient boosting, 2022–26 | AP | Fark [%95] |
|---|---|---|
| önceki değişkenler | 0.188 | |
| + lodos | 0.192 | +0.004 [−0.003, +0.012] |
| + en yağışlı nokta | 0.185 | −0.003 [−0.008, +0.002] |

İki farkın aralığı da sıfırı içeriyor: kazanç kanıtlanmadı, uyarı modelini değiştirmedim. Foça'da ilçenin en yağışlı noktası bile 16 mm diyor. Sorun nokta sayısı değil, yağış arşivinin kendisi.

**Sel her ilçede aynı yağışla gelmiyor (GWR).** Yukarıdaki modeller bütün ilçelere tek denklem uyguluyor. Coğrafi ağırlıklı lojistik regresyon (GWR) her ilçe için ayrı bir model kuruyor: ilçenin kendi kayıtları tam ağırlıkla, en yakın komşularınınki uzaklıkla azalan ağırlıkla girer. Komşu sayısı görülmemiş yıllarda seçildi: ilçenin kendisi ve en yakın iki komşusu. Sonuç okunması kolay olsun diye bir çarpanla verildi: yağış 10 mm yerine 40 mm olunca olay olasılığı (olasılık oranı) kabaca kaç katına çıkıyor?

| | O günün yağışı | Önceki 7 günün yağışı |
|---|---|---|
| En duyarlı | Selçuk ×5.3 [3.4–9.6], Urla ×4.8, Ödemiş ×4.7 | Dikili ×8.2 [4.7–16.7], Bergama ×5.5, Kınık ×4.1 |
| En az duyarlı | Seferihisar ×1.6, Dikili ×1.8, Bergama ×1.9 | Etkisi kanıtlanmamış: Bayındır, Beydağ, Kiraz, Ödemiş, Selçuk, Tire ve Seferihisar |

- **Bakırçay havzasında (Dikili, Bergama, Kınık)** sel ancak günlerce yağdıktan sonra geliyor: o günün yağışının etkisi en zayıflar arasında, önceki haftanınki en güçlü.
- **Küçük Menderes havzasında (Bayındır, Beydağ, Kiraz, Ödemiş, Selçuk, Tire)** sel o günün sağanağıyla geliyor; önceki haftanın etkisi kanıtlanmamış.
- **Tek yağış noktasının yan etkisi değil.** O günün yağışı ilçedeki en yağışlı noktadan alınınca da ilçelerin sıralaması neredeyse aynı kalıyor (sıra korelasyonu 0.96).
- **Uyarıyı iyileştirmiyor.** 2022–26 yıl yıl sınamada AP 0.184, tek denklemle 0.176; fark [−0.009, +0.028], yani kanıtlanmadı. Değeri ilçeler arasındaki farkı göstermesinde.
- **Nedeni bu veriyle ayrılamıyor.** Havzaların biçimi ve toprağı yağışa farklı tepki veriyor olabilir; yağış arşivi de bazı yerlerde sağanağı daha çok yumuşatıyor olabilir. İkisi de hipotez.

**Nasıl okunmalı**
- Bir ön uyarı sinyali, karar değil: alarmların beşte dördü boşa çıkıyor, olayların üçte ikisi kaçıyor.
- Mahalle yok: itfaiye kayıtlarında adres olmadığı için birim ilçe.
- Yağış miktarları arşivin (ERA5) ölçeğinde; istasyonda ölçülen sağanak daha yüksektir.

Sitede: "Uyarı" sekmesi. İki harita var: seçilen yağışta her ilçenin olay olasılığı ve ilçe ilçe yağışa duyarlılık.

## 7. Kurum verisiyle ne değişir?

| Eksik | Gereken veri | Düzelteceği şey |
|---|---|---|
| Kıyıdaki şebeke taşkını | İZSU yağmur suyu ve kanalizasyon şebekesi | Modelin su göstermediği Alsancak, Güzelyalı gibi yerler |
| Küçük kent dereleri | Belediyenin hassas yükseklik ölçümü (LiDAR, 1 m) | Soğukkuyu, Hacı Ahmet gibi dar dere yatakları |
| Zayıf doğrulama, ilçe düzeyinde uyarı | Belediyenin ve itfaiyenin adresli su baskını ihbar kayıtları | 14 yer yerine yüzlerce noktayla sınama; mahalle düzeyinde uyarı |
| Dar alanlı sağanak | MGM istasyon ve radar yağışı | Erken uyarının göremediği yerel sağanak (ör. Foça, Ekim 2025) |
| Düz ovalardaki belirsizlik | DSİ taşkın haritaları, sedde ve baraj işletmesi | Gediz deltası ve Menemen ovası |

## 8. Bu çalışmada neler var?

- **Mekânsal veri hattı:** OSM'den yol ağı kurma, yükseklik verisinden eğim, TKGM sınırlarıyla il ve mahalle maskeleri.
- **Hidrolojik modelleme:** yüzey akışı, akış yönü ve birikimi, dere taşkını, kapalı çukurların dolması.
- **Ağ analizi:** pgRouting ile eğim, deprem, trafik ve sel cezalı tahliye rotası; 920 bin yol parçasında ~1 saniyede yanıt. Sunucusuz sitede aynı maliyetle tarayıcıda çalışan Dijkstra (82 bin yol parçası, birkaç ms).
- **Makine öğrenmesi:** itfaiye kayıtları ve yağış arşivinden ilçe-gün eğitim verisi; lojistik regresyon, karar ağacı, Random Forest ve gradient boosting (scikit-learn); yıl yıl ve ilçe dışarıda bırakılarak sınama.
- **Mekânsal istatistik:** her ilçeye ayrı model, coğrafi ağırlıklı lojistik regresyon (GWR); komşu sayısı görülmemiş yıllarda seçildi.
- **Web uygulaması:** FastAPI + PostGIS arka uç, Leaflet harita, mobil uyumlu arayüz.
- **Doğrulama ve test:** gerçek olayla karşılaştırma betiği, geçmiş hava tahminleriyle sınama, haftalık bloklarla güven aralığı, 96 otomatik test, tekrar üretilebilir kurulum adımları.
- **Dürüst raporlama:** varsayımlar, sınırlar ve işe yaramayan denemeler açıkça yazılı.
