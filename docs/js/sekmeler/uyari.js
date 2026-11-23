// Sekme: erken uyarı. İtfaiye su baskını kayıtlarıyla eğitilmiş sınıflandırma
// modeli: "yarın bu ilçeye ≥ 3 su baskını çağrısı gelir mi?" Üç görünüm:
//   canlı      — yarının gerçek hava tahminiyle (sayfa açılınca alınır;
//                cekirdek/canli.js) her ilçede sel olasılığı ve alarm.
//   olasılık   — "kendin dene": yağışı ve geçen haftayı kullanıcı seçer (hazır tablo).
//                Bu ikisinin altında: model nasıl eğitildi, ne kadar doğru (dört
//                kutu), hangi sel dalgalarını yakaladı, hangilerini kaçırdı ve neden
//                (uyari_aciklama.js).
//   duyarlılık — coğrafi ağırlıklı lojistik regresyon (GWR): her ilçede sel
//                neyle geliyor, o günün yağışıyla mı, önceki haftanınkiyle mi?
// Metin sade dildedir; bütün sayılar veriden gelir (hesap/uyari_hazirla.py →
// veri/uyari.json; canlıda veri/uyari_model.json ve Open-Meteo hava tahmini).
import { T, sayi } from '../cekirdek/dil.js';
import { yerAdi, kacis, yuzde, yuzdeAraligi, yilAraligi, tarih, tarihSaat } from '../cekirdek/bicim.js';
import { secimHtml, secimDinle, listeDinle, sayiKutulari, lejantOgesi } from '../cekirdek/arayuz.js';
import { jsonOku, UYARI_MODELI } from '../cekirdek/veri.js';
import { yarininGirdileri, tahminler } from '../cekirdek/canli.js';
import { aciklamaHtml, yuzdeSayi } from './uyari_aciklama.js';

// Olasılık: tek tonlu (turuncu) sıralı ölçek, açıktan koyuya. Mavi öteki
// sekmelerde su derinliği demek; olasılık onunla karışmasın diye turuncu.
const RENK = ['#fbe4d9', '#f6bfa3', '#ef9469', '#e0612e', '#a3401b'];
const SINIR = [0.05, 0.10, 0.20, 0.40];
const sinif = (p) => SINIR.filter((s) => p >= s).length;
// Duyarlılık (GWR çarpanı): üçüncü ton, mor; sıralı sınıflar. En açık adım bile
// gri zeminden ayrışır (≥ 2:1), çünkü zemine en yakın görünüm "etki
// kanıtlanmamış"a ayrıldı: gri dolgu ve kesik çizgi (renk tek başına taşımaz).
const MOR = ['#a194ee', '#7c6be2', '#5844cc', '#33247f'];
const CARPAN_SINIR = [2, 3, 5];
const carpanSinifi = (c) => CARPAN_SINIR.filter((s) => c >= s).length;
const KANITSIZ_RENK = '#d1d5db';
const KANITSIZ_STIL = { color: '#6b7280', weight: 1.2, dashArray: '4 3', fillColor: KANITSIZ_RENK, fillOpacity: 0.5 };
// Canlı tahmin henüz yok (alınıyor ya da o ilçe için eksik): açık gri, kesik çizgi.
const VERISIZ_RENK = '#f3f4f6';
const VERISIZ_STIL = { color: '#9ca3af', weight: 1, dashArray: '3 3', fillColor: VERISIZ_RENK, fillOpacity: 0.6 };

// 1'e yakın değerler iki ondalıkla: [1,04–2,2] "1'i içeriyor" diye okunmasın.
const carpanSayi = (x) => sayi(x, Math.abs(x - 1) < 0.1 ? 2 : 1);
const kat = (x) => T(`${carpanSayi(x)} kat`, `${carpanSayi(x)}×`);
const carpanAraligi = (c) => `[${carpanSayi(c.aralik_95[0])}–${carpanSayi(c.aralik_95[1])}]`;
const kanitsizEtiket = () => T('etkisi kanıtlanamadı', 'no proven effect');
const alarmRozeti = () => `<span class="rozet kotu">${T('alarm', 'alert')}</span>`;

/** GWR: etkisi kanıtlanmış ilçeler, çarpanı büyükten küçüğe (Hakkında penceresi de kullanır). */
export const enDuyarlilar = (gwr, etken) => Object.keys(gwr.ilceler).filter((ad) => gwr.ilceler[ad][etken].kanitli)
  .sort((a, b) => gwr.ilceler[b][etken].deger - gwr.ilceler[a][etken].deger);

export function uyariSekmesi({ uyari, harita, lejantiYenile }) {
  const ilk = uyari.yagis_mm.includes(40) ? 40 : uyari.yagis_mm[Math.floor(uyari.yagis_mm.length / 2)];
  const durum = { gorunum: 'canli', etken: 'gunun_yagisi', mm: ilk, gecmis: 'islak' };
  // Yarının tahmini. hal: bekliyor | yukleniyor | hazir | hata; ilceler: ad → { p, alarm, yagis } | null
  const canli = { hal: 'bekliyor', hedef: null, alindi: null, ilceler: {}, hata: null };
  let icerik = null, katman = null, acik = false, model = null;
  const sekiller = new Map();          // ilçe adı → Leaflet katmanı
  const esik = uyari.model.esik;
  const gwr = uyari.gwr;
  const [mmA, mmB] = gwr.olcek_mm;
  const ilceCagri = uyari.olay_tanimi.ilce_cagri;

  const canlida = () => durum.gorunum === 'canli';
  /** Seçili görünümde ilçenin sel olasılığı; canlı tahmin yoksa null. */
  const olasilik = (ad) => (canlida() ? canli.ilceler[ad]?.p ?? null
    : uyari.kosullar[durum.gecmis].olasilik[ad][uyari.yagis_mm.indexOf(durum.mm)]);
  const alarm = (p) => p !== null && p >= esik;
  const verisizMetni = () => (canli.hal === 'hazir' ? T('tahmin yok', 'no forecast') : T('tahmin alınıyor…', 'fetching forecast…'));
  const olasilikMetni = (p) => (p === null ? verisizMetni() : yuzde(p));
  const etki = (ad, etken = durum.etken) => gwr.ilceler[ad][etken];
  const duyarlilikta = () => durum.gorunum === 'duyarlilik';
  const etkiMetni = (c) => (c.kanitli ? kat(c.deger) : kanitsizEtiket());
  const gecmisAdi = () => (durum.gecmis === 'islak' ? T('yağışlı hafta', 'wet week') : T('kuru hafta', 'dry week'));
  const etkenAdi = () => (durum.etken === 'gunun_yagisi'
    ? T(`o gün ${mmA} yerine ${mmB} mm yağınca`, `${mmB} mm instead of ${mmA} mm on the day`)
    : T(`önceki 7 günde ${mmA} yerine ${mmB} mm yağınca`, `${mmB} mm instead of ${mmA} mm over the previous 7 days`));

  const stil = (ad) => {
    if (duyarlilikta()) {
      const c = etki(ad);
      return c.kanitli ? { color: '#ffffff', weight: 1, dashArray: null, fillColor: MOR[carpanSinifi(c.deger)], fillOpacity: 0.85 }
        : KANITSIZ_STIL;
    }
    const p = olasilik(ad);
    if (p === null) return VERISIZ_STIL;
    return alarm(p) ? { color: '#1f2937', weight: 2.5, dashArray: null, fillColor: RENK[sinif(p)], fillOpacity: 0.85 }
      : { color: '#ffffff', weight: 1, dashArray: null, fillColor: RENK[sinif(p)], fillOpacity: 0.8 };
  };

  const olayGunuSatiri = (ilce) => `<span class="soluk">${T(`Sel olan gün sayısı (${yilAraligi(uyari.veri.yillar)})`, `Flood days (${yilAraligi(uyari.veri.yillar)})`)}:</span> ${sayi(ilce.olay_gunu)}`;

  const acilir = (ilce) => {
    const ad = `<b>${kacis(yerAdi(ilce.ad))}</b>`;
    if (canlida()) {
      const t = canli.ilceler[ilce.ad];
      if (!t) return `${ad}<br><span class="soluk">${verisizMetni()}</span>`;
      const y = t.yagis;
      return `${ad} ${t.alarm ? alarmRozeti() : ''}<br>
        <span class="soluk">${T('Yarın sel olasılığı', 'Flood probability tomorrow')}:</span> ${yuzde(t.p)}<br>
        <span class="soluk">${T('Yarın beklenen yağış', 'Rain expected tomorrow')}:</span> ${sayi(y.yagis_mm, 1)} mm
        <span class="soluk">(${T('en yoğun saatte', 'heaviest hour')} ${sayi(y.yagis_max1s_mm, 1)} mm)</span><br>
        <span class="soluk">${T('Son 7 günün yağışı (bugün dahil)', 'Rain over the last 7 days (incl. today)')}:</span> ${sayi(y.yagis_onceki7g_mm, 1)} mm<br>
        ${olayGunuSatiri(ilce)}`;
    }
    if (duyarlilikta()) {
      const satir = (etken, etiket) => {
        const c = etki(ilce.ad, etken);
        return `<span class="soluk">${etiket}:</span> ${kat(c.deger)} <span class="soluk">${carpanAraligi(c)}${c.kanitli ? '' : ` ${kanitsizEtiket()}`}</span>`;
      };
      return `${ad}<br><span class="soluk kucuk">${T(`${mmA} yerine ${mmB} mm yağınca sel kaç kat olası:`, `How many times likelier a flood is with ${mmB} mm instead of ${mmA} mm:`)}</span><br>
        ${satir('gunun_yagisi', T('o gün', 'on the day'))}<br>${satir('onceki_hafta', T('önceki 7 günde', 'over the previous 7 days'))}`;
    }
    const p = olasilik(ilce.ad);
    return `${ad} ${alarm(p) ? alarmRozeti() : ''}<br>
      <span class="soluk">${T(`Yarın ${durum.mm} mm yağarsa sel olasılığı`, `Flood probability with ${durum.mm} mm tomorrow`)}:</span> ${yuzde(p)}<br>
      ${olayGunuSatiri(ilce)}`;
  };

  function katmanlariKur() {
    katman = L.layerGroup();
    uyari.ilceler.forEach((ilce) => {
      const sekil = L.geoJSON(ilce.geometri, { style: () => stil(ilce.ad) })
        .bindTooltip(() => `${kacis(yerAdi(ilce.ad))}: ${duyarlilikta() ? etkiMetni(etki(ilce.ad)) : olasilikMetni(olasilik(ilce.ad))}`, { sticky: true })
        .bindPopup(() => acilir(ilce), { maxWidth: 260 });
      sekiller.set(ilce.ad, sekil);
      katman.addLayer(sekil);
    });
  }

  const boya = () => uyari.ilceler.forEach((ilce) => sekiller.get(ilce.ad).setStyle(stil(ilce.ad)));

  // Olasılığa göre sıralı; canlıda yarının ve son 7 günün yağışıyla, tahmini olmayanlar sonda.
  function olasilikListesi() {
    const yagisi = (ad) => {
      const y = canlida() && canli.ilceler[ad]?.yagis;
      return y ? ` <span class="soluk kucuk">· ${T(`yarın ${sayi(y.yagis_mm, 1)} mm, son 7 gün ${sayi(y.yagis_onceki7g_mm, 1)} mm`,
        `tomorrow ${sayi(y.yagis_mm, 1)} mm, last 7 days ${sayi(y.yagis_onceki7g_mm, 1)} mm`)}</span>` : '';
    };
    return uyari.ilceler.map((i) => ({ ad: i.ad, p: olasilik(i.ad) })).sort((a, b) => (b.p ?? -1) - (a.p ?? -1))
      .map(({ ad, p }) => `<li data-ilce="${kacis(ad)}" tabindex="0" role="button">
        <i class="olcek-kare${p === null ? ' kanitsiz' : ''}" style="--renk:${p === null ? VERISIZ_RENK : RENK[sinif(p)]}"></i>
        <b>${kacis(yerAdi(ad))}</b> ${olasilikMetni(p)} ${alarm(p) ? alarmRozeti() : ''}${yagisi(ad)}</li>`).join('');
  }

  // Tablo görünümü: kanıtlananlar çarpana göre, kanıtlanmayanlar sonda ama değeriyle.
  function etkiListesi() {
    return uyari.ilceler.map((i) => ({ ad: i.ad, c: etki(i.ad) }))
      .sort((a, b) => (b.c.kanitli - a.c.kanitli) || (b.c.deger - a.c.deger))
      .map(({ ad, c }) => `<li data-ilce="${kacis(ad)}" tabindex="0" role="button"${c.kanitli ? '' : ' class="pasif"'}>
        <i class="olcek-kare${c.kanitli ? '' : ' kanitsiz'}" style="--renk:${c.kanitli ? MOR[carpanSinifi(c.deger)] : KANITSIZ_RENK}"></i>
        <b>${kacis(yerAdi(ad))}</b> ${kat(c.deger)} <span class="soluk">${carpanAraligi(c)}${c.kanitli ? '' : ` ${kanitsizEtiket()}`}</span></li>`).join('');
  }

  function secimCiz() {
    const yer = icerik.querySelector('[data-yer="secim"]');
    if (duyarlilikta()) {
      const hepsi = uyari.ilceler.map((i) => ({ ad: i.ad, c: etki(i.ad) }));
      const kanitli = hepsi.filter((x) => x.c.kanitli);
      const enCok = kanitli.reduce((a, b) => (b.c.deger > a.c.deger ? b : a), kanitli[0]);
      const sabit = durum.etken === 'gunun_yagisi'
        ? T('önceki günlerin yağışı aynıyken', 'earlier days unchanged') : T('o günün yağışı aynıyken', "the day's rain unchanged");
      yer.innerHTML = `
        <p>${T(`Renk: <b>${etkenAdi()}</b> sel kaç kat olası hale geliyor (${sabit}).`,
               `Colour: how many times likelier a flood becomes with <b>${etkenAdi()}</b> (${sabit}).`)}</p>
        ${sayiKutulari([
          [enCok ? kat(enCok.c.deger) : '–', enCok ? T(`en duyarlı ilçe: ${kacis(yerAdi(enCok.ad))}`, `most sensitive: ${kacis(yerAdi(enCok.ad))}`) : ''],
          [`${sayi(kanitli.length)} / ${sayi(hepsi.length)}`, T('ilçede etkisi kanıtlandı', 'districts with a proven effect')],
        ])}
        <ul class="liste kaydir" data-yer="liste">${etkiListesi()}</ul>`;
      return;
    }
    if (canlida() && canli.hal !== 'hazir') {
      yer.innerHTML = `<p class="soluk">${T('Yarının hava tahmini alınıyor…', "Fetching tomorrow's weather forecast…")}</p>`;
      return;
    }
    const ilceler = uyari.ilceler.map((i) => ({ ad: i.ad, p: olasilik(i.ad) })).filter((x) => x.p !== null);
    if (!ilceler.length) {
      yer.innerHTML = `<p class="soluk">${T('Hiçbir ilçe için tahmin yok.', 'No forecast for any district.')}</p>`;
      return;
    }
    const enYuksek = ilceler.reduce((a, b) => (b.p > a.p ? b : a));
    yer.innerHTML = `
      ${sayiKutulari([
        [`${sayi(ilceler.filter((x) => alarm(x.p)).length)} / ${sayi(uyari.ilceler.length)}`, T('ilçede alarm', 'districts on alert')],
        [yuzde(enYuksek.p), T(`en yüksek olasılık: ${kacis(yerAdi(enYuksek.ad))}`, `highest probability: ${kacis(yerAdi(enYuksek.ad))}`)],
      ])}
      <ul class="liste kaydir" data-yer="liste">${olasilikListesi()}</ul>`;
  }

  // ── Canlı ve olasılık görünümleri: tahmin ya da denetimler, sonra eğitim,
  //    doğruluk, sel dalgaları, sınırlar ──

  /** "Haritayı okumak": renk neyin olasılığı, alarm çerçevesi ve eşik; son: görünüme özgü not. */
  const okumaNotu = (renkTr, renkEn, sonTr, sonEn) => {
    const ornek = SINIR[2], n = sayi(Math.round(1 / ornek));
    return `<p class="soluk kucuk">${T(`<b>Haritayı okumak:</b> renk, ${renkTr} (${yuzde(ornek)}: böyle ${n} günün birinde sel olur). Kalın siyah çerçeve: alarm, yani olasılık ${yuzde(esik)} ve üstü. Bu eşik, eğitim yıllarında kaçan sel ile boşa alarm arasındaki en iyi dengeyi verdi. ${sonTr}`,
      `<b>Reading the map:</b> colour is ${renkEn} (${yuzde(ornek)}: a flood on one in ${n} such days). Thick black outline: alert, i.e. probability ${yuzde(esik)} or more. This threshold gave the best balance between missed floods and false alerts in the training years. ${sonEn}`)}</p>`;
  };

  function canliHtml() {
    const c = uyari.sinama.canli_tahmin;
    const ne = canli.hal === 'hazir'
      ? T(`<b>${tarih(canli.hedef)}</b> için, her ilçenin yağış noktasındaki hava tahminiyle (ECMWF). Tahmin bu sayfa açılınca alındı: ${tarihSaat(canli.alindi)} (Türkiye saati).`,
          `For <b>${tarih(canli.hedef)}</b>, from the weather forecast (ECMWF) at each district's rain point. Fetched when this page opened: ${tarihSaat(canli.alindi)} (Turkey time).`)
      : T('Yarının hava tahmini, her ilçenin yağış noktası için alınıyor…', "Fetching tomorrow's weather forecast for each district's rain point…");
    return `
      <div class="kutu not"><p><b>${T('Araştırma amaçlıdır, resmî uyarı değildir.', 'For research only, not an official warning.')}</b>
        ${T('Resmî uyarılar için <a href="https://meteouyari.mgm.gov.tr" target="_blank" rel="noopener">MGM</a> ve <a href="https://www.afad.gov.tr" target="_blank" rel="noopener">AFAD</a>.',
            'For official warnings see <a href="https://meteouyari.mgm.gov.tr" target="_blank" rel="noopener">MGM</a> (Turkish Meteorological Service) and <a href="https://www.afad.gov.tr" target="_blank" rel="noopener">AFAD</a>.')}</p></div>
      <p>${ne}</p>
      <div data-yer="secim"></div>
      ${okumaNotu('yarın o ilçede sel olma olasılığı', 'the probability of a flood in that district tomorrow',
        'Model yarının tahmini yağışına (günün toplamı, en yoğun 1 ve 3 saati) ve son günlerin yağışına bakar. Hava tahmini yaklaşık 25 km\'lik karelerle hesaplanır; yan yana ilçeler bu yüzden çoğu zaman aynı yağışı alır.',
        "The model looks at tomorrow's forecast rain (the day's total, its heaviest 1 and 3 hours) and the rain of the last few days. The forecast is computed on squares of about 25 km, so neighbouring districts often get the same rain.")}
      <h3>${T('Bu haliyle ne kadar doğru?', 'How accurate is it, like this?')}</h3>
      <p>${T(`Sayfanın yaptığının aynısı ${yilAraligi(c.yillar)} için geriye dönük denendi: her gün için, önceki gün öğlen elde olan hava tahmini, son günlerin yağışı da aynı tahmin modelinin kendi kaydından. Sonuç:`,
             `Exactly what this page does was replayed for ${yilAraligi(c.yillar)}: for each day, the weather forecast available at noon the day before, with the last few days' rain also from the forecast model's own record. The result:`)}</p>
      ${sayiKutulari([
        [`${yuzdeSayi(c.duyarlilik)} / 100`, T('selde önceden alarm vardı', 'floods had an alert beforehand')],
        [`${yuzdeSayi(c.kesinlik)} / 100`, T('alarmda gerçekten sel oldu', 'alerts were followed by a flood')],
      ])}
      <p class="soluk kucuk">${T('Hava tahmini: <a href="https://open-meteo.com" target="_blank" rel="noopener">Open-Meteo.com</a> (ECMWF açık verisi, CC BY 4.0). Aynı tarayıcıda bir saat saklanır; sonra yeniden alınır.',
                                 'Weather forecast: <a href="https://open-meteo.com" target="_blank" rel="noopener">Open-Meteo.com</a> (ECMWF open data, CC BY 4.0). Kept for an hour in the same browser, then fetched again.')}</p>`;
  }

  /** Canlı tahmin alınamadıysa "kendin dene"nin başında nedeni. */
  const hataNotu = () => (canli.hal !== 'hata' ? '' : `
      <div class="kutu not"><p><b>${T('Yarının hava tahmini şu an alınamadı', "Tomorrow's weather forecast could not be fetched right now")}</b>
        <span class="soluk">(${kacis(canli.hata === 'zaman' ? T('yanıt gelmedi', 'no response') : canli.hata)})</span>.
        ${T('Yağışı aşağıdan kendin seçebilirsin; yeniden denemek için "Yarının tahmini"ne bas.', 'You can choose the rain below; press "Tomorrow\'s forecast" to try again.')}</p></div>`);

  function denetimHtml() {
    const isl = uyari.kosullar.islak.onceki;
    return `
      <div class="alan-baslik">${T('Yarın kaç mm yağsın?', 'How much rain tomorrow?')}</div>
      ${secimHtml('mm', uyari.yagis_mm.filter((m) => m > 0).map((m) => [m, `${m} mm`]), durum.mm)}
      <div class="alan-baslik">${T('Son bir hafta nasıl geçti?', 'How was the past week?')}</div>
      ${secimHtml('gecmis', [['kuru', T('Kuru', 'Dry')], ['islak', T('Yağışlı', 'Wet')]], durum.gecmis)}
      <p class="soluk kucuk bosluk-ust">${T(`Kuru: önceki 7 gün hiç yağmamış. Yağışlı: önceki 7 günde ${sayi(isl.yagis_onceki7g_mm)} mm, son 3 günde ${sayi(isl.yagis_onceki3g_mm)} mm yağmış; sel olan günlerden önce tipik olarak bu kadar yağıyor. Toprak ve kanallar doluysa az yağmur da sel getirir.`,
             `Dry: no rain in the previous 7 days. Wet: ${sayi(isl.yagis_onceki7g_mm)} mm over the previous 7 days, ${sayi(isl.yagis_onceki3g_mm)} mm in the last 3; that is typical before flood days. When soil and drains are full, even a little rain floods.`)}</p>
      <div data-yer="secim"></div>
      ${okumaNotu('seçtiğiniz yağışta o ilçede sel olma olasılığı', 'the probability of a flood in that district with the rain you chose',
        'Yağış, yağış arşivinin (ERA5) ölçeğinde: arşiv sağanağı yumuşatır, istasyonda ölçülen yağış genelde daha yüksektir.',
        'Rain is on the scale of the rain archive (ERA5), which smooths downpours; station rainfall is usually higher.')}`;
  }


  function duyarlilikHtml() {
    const s = gwr.sinama, yillar = yilAraligi(s.gwr.yillar);
    const enUst = (etken) => enDuyarlilar(gwr, etken).slice(0, 3).map((ad) => kacis(yerAdi(ad))).join(', ');
    const kanitsiz = uyari.ilceler.filter((i) => !etki(i.ad, 'onceki_hafta').kanitli).map((i) => yerAdi(i.ad))
      .sort((a, b) => a.localeCompare(b, 'tr')).map(kacis);
    const komsu = gwr.bant - 1;
    return `
      <h3>${T('Hangi yağış seli getiriyor?', 'Which rain brings the floods?')}</h3>
      <p>${T(`Her ilçe yağışa aynı tepkiyi vermiyor. Bunu görmek için her ilçeye ayrı bir model kuruldu; model ilçenin kendi kayıtlarını ve en yakın ${komsu} komşusununkini kullanır (coğrafi ağırlıklı regresyon, GWR). Harita şunu gösteriyor: yağış ${mmA} yerine ${mmB} mm olunca o ilçede sel kaç kat olası hale geliyor?`,
             `Districts do not all react to rain the same way. To see this, a separate model was fitted for each district, using its own records and those of its ${komsu} nearest neighbours (geographically weighted regression, GWR). The map shows how many times likelier a flood becomes in each district when ${mmB} mm falls instead of ${mmA} mm.`)}</p>
      <div class="alan-baslik">${T('Hangi yağış?', 'Which rain?')}</div>
      ${secimHtml('etken', [['gunun_yagisi', T('O günün yağışı', "The day's rain")], ['onceki_hafta', T('Önceki 7 günün yağışı', 'Rain over the previous 7 days')]], durum.etken)}
      <div data-yer="secim"></div>
      <p class="soluk kucuk">${T('Köşeli parantez: %95 güven aralığı, yani gerçek değerin büyük olasılıkla bulunduğu aralık. Aralık 1 katı da içeriyorsa, yani etkisi hiç olmayabilirse, etkisi kanıtlanamadı sayılır (haritada kesik çizgili gri). İstatistik terimiyle bu çarpan bir olasılık oranıdır (odds ratio); olasılık küçükken "kaç kat olası" ile hemen hemen aynıdır.',
                                 'Brackets: 95% confidence interval, the range the true value very likely lies in. If it also contains 1×, meaning there may be no effect at all, the effect counts as not proven (dashed grey on the map). Statistically the multiplier is an odds ratio; when probabilities are small it is almost the same as "how many times likelier".')}</p>
      <ul>
        <li>${T(`<b>Sel her yerde aynı yağışla gelmiyor.</b> O günün sağanağına en duyarlı ilçeler: ${enUst('gunun_yagisi')}. Günlerce süren yağışa (önceki hafta) en duyarlılar: ${enUst('onceki_hafta')}.${kanitsiz.length ? ` Önceki haftanın etkisi ${sayi(kanitsiz.length)} ilçede kanıtlanamadı: ${kanitsiz.join(', ')}.` : ''}`,
                 `<b>Floods do not come with the same rain everywhere.</b> Most sensitive to the day's downpour: ${enUst('gunun_yagisi')}. Most sensitive to days of rain (the previous week): ${enUst('onceki_hafta')}.${kanitsiz.length ? ` The previous week has no proven effect in ${sayi(kanitsiz.length)} districts: ${kanitsiz.join(', ')}.` : ''}`)}</li>
        <li>${T(`<b>Uyarıyı iyileştirmiyor.</b> ${yillar} yıl yıl sınandığında ayrı modeller her 100 selin ${yuzdeSayi(s.gwr.duyarlilik)} tanesini önceden görüyor, tek model ${yuzdeSayi(s.global.duyarlilik)} tanesini; her 100 alarmdan doğru çıkan ${yuzdeSayi(s.gwr.kesinlik)} ve ${yuzdeSayi(s.global.kesinlik)}. Değeri, ilçeler arasındaki farkı göstermesinde.`,
                 `<b>It does not improve the alert.</b> Tested year by year (${yillar}), the separate models see ${yuzdeSayi(s.gwr.duyarlilik)} of every 100 floods in advance, the single model ${yuzdeSayi(s.global.duyarlilik)}; of every 100 alerts, ${yuzdeSayi(s.gwr.kesinlik)} and ${yuzdeSayi(s.global.kesinlik)} come true. Its value is in showing how districts differ.`)}</li>
        <li>${T('<b>Nedeni bu veriyle ayrılamıyor.</b> Havzanın biçimi ve toprağı yağışa farklı tepki veriyor olabilir; yağış arşivi de bazı yerlerde sağanağı daha çok yumuşatıyor olabilir.',
                 '<b>The cause cannot be separated with this data.</b> Catchment shape and soil may respond differently to rain, or the rain archive may smooth downpours more in some places.')}</li>
      </ul>`;
  }

  const GORUNUMLER = {
    canli: () => canliHtml() + aciklamaHtml(uyari),
    olasilik: () => hataNotu() + denetimHtml() + aciklamaHtml(uyari),
    duyarlilik: duyarlilikHtml,
  };

  function gorunumCiz() {
    icerik.querySelector('[data-yer="gorunum"]').innerHTML = GORUNUMLER[durum.gorunum]();
    secimCiz();
  }

  const dugmeleriGuncelle = (grup) => icerik.querySelectorAll(`[data-secim="${grup}"]`).forEach((d) => {
    const secili = d.dataset.deger === String(durum[grup]);
    d.classList.toggle('secili', secili);
    d.setAttribute('aria-pressed', secili);
  });

  /** Yarının tahmini: model dosyası (bir kez) + hava tahmini. Alınamazsa "kendin dene"ye döner. */
  async function canliYukle() {
    Object.assign(canli, { hal: 'yukleniyor', hata: null });
    let dondu = false;
    try {
      model = model || await jsonOku(UYARI_MODELI);
      const g = await yarininGirdileri(model);
      Object.assign(canli, { hal: 'hazir', hedef: g.hedef, alindi: g.alindi, ilceler: tahminler(model, g.girdiler, esik) });
    } catch (hata) {
      console.warn('Yarının tahmini alınamadı:', hata);
      Object.assign(canli, { hal: 'hata', ilceler: {}, hata: hata.name === 'AbortError' ? 'zaman' : String(hata.message || hata) });
      if (canlida()) { durum.gorunum = 'olasilik'; dondu = true; }
    }
    if (!acik || !(canlida() || dondu)) return;      // sekme kapalı ya da başka görünümde: açılınca çizilir
    dugmeleriGuncelle('gorunum');
    gorunumCiz();
    boya();
    lejantiYenile();
  }

  function ciz() {
    icerik.innerHTML = `
      <h2>${T('Erken uyarı: yarın hangi ilçede sel olabilir?', 'Early warning: which district may flood tomorrow?')}</h2>
      <p>${T(`Bu sekmedeki model, İzmir İtfaiyesi'nin ${yilAraligi(uyari.veri.yillar)} su baskını kayıtlarından öğrendi. Her ilçe için tek bir soruyu yanıtlıyor: <b>yarın bu ilçeye en az ${ilceCagri} su baskını çağrısı gelir mi?</b> Aşağıda buna kısaca "sel" diyoruz.`,
             `The model in this tab learned from İzmir Fire Department flood calls, ${yilAraligi(uyari.veri.yillar)}. For each district it answers one question: <b>will the district get at least ${ilceCagri} flood calls tomorrow?</b> Below, we call that a "flood".`)}</p>
      <div class="alan-baslik">${T('Harita ne göstersin?', 'What should the map show?')}</div>
      ${secimHtml('gorunum', [['canli', T('Yarının tahmini', "Tomorrow's forecast")], ['olasilik', T('Kendin dene', 'Try it yourself')],
        ['duyarlilik', T('Hangi yağış etkili?', 'Which rain matters?')]], durum.gorunum)}
      <div data-yer="gorunum"></div>`;
    gorunumCiz();
  }

  function ilceyeGit(ad) {
    const sekil = sekiller.get(ad);
    harita.sigdir(sekil.getBounds(), 11);
    sekil.openPopup(sekil.getBounds().getCenter());
  }

  // Lejant: başlık ve neyin olasılığı / çarpanı olduğu, seçili yağışla birlikte.
  const lejantBasligi = (baslik, alt) => `<span class="lej-baslik">${baslik}</span><span class="lej-alt">${alt}</span>`;

  const olasilikSiniflari = () => [yuzdeAraligi(0, SINIR[0]), ...SINIR.slice(1).map((s, i) => yuzdeAraligi(SINIR[i], s)),
    T(`${yuzde(SINIR[SINIR.length - 1])} ve üstü`, `${yuzde(SINIR[SINIR.length - 1])} or more`)]
    .map((etiket, i) => lejantOgesi(RENK[i], etiket)).join('')
    + `<span class="lej"><i style="--renk:${RENK[2]};border:2.5px solid #1f2937;box-shadow:0 0 0 1px #e5e7eb"></i>${T(`kalın çerçeve: alarm (${yuzde(esik)} ve üstü)`, `thick outline: alert (${yuzde(esik)} or more)`)}</span>`;

  const olasilikLejanti = () => lejantBasligi(T('Sel olasılığı', 'Flood probability'),
    T(`bir ilçeye ≥ ${ilceCagri} su baskını çağrısı · ${durum.mm} mm, ${gecmisAdi()}`, `≥ ${ilceCagri} flood calls in a district · ${durum.mm} mm, ${gecmisAdi()}`))
    + olasilikSiniflari();

  const canliLejanti = () => {
    const eksik = canli.hal !== 'hazir' || uyari.ilceler.some((i) => !canli.ilceler[i.ad]);
    return lejantBasligi(T('Yarın sel olasılığı', 'Flood probability tomorrow'), canli.hal === 'hazir'
      ? T(`${tarih(canli.hedef)} · hava tahmini: ECMWF · bir ilçeye ≥ ${ilceCagri} su baskını çağrısı`,
          `${tarih(canli.hedef)} · forecast: ECMWF · ≥ ${ilceCagri} flood calls in a district`)
      : T('tahmin alınıyor…', 'fetching forecast…'))
      + olasilikSiniflari() + (eksik ? lejantOgesi(VERISIZ_RENK, verisizMetni(), 'kanitsiz') : '');
  };

  const duyarlilikLejanti = () => lejantBasligi(T('Sel kaç kat olası?', 'How many times likelier?'), etkenAdi())
    + [T(`${CARPAN_SINIR[0]} kattan az`, `under ${CARPAN_SINIR[0]}×`),
      ...CARPAN_SINIR.slice(1).map((s, i) => T(`${CARPAN_SINIR[i]}–${s} kat`, `${CARPAN_SINIR[i]}–${s}×`)),
      T(`${CARPAN_SINIR[CARPAN_SINIR.length - 1]} kat ve üstü`, `${CARPAN_SINIR[CARPAN_SINIR.length - 1]}× or more`)]
      .map((etiket, i) => lejantOgesi(MOR[i], etiket)).join('')
    + lejantOgesi(KANITSIZ_RENK, kanitsizEtiket(), 'kanitsiz');

  return {
    id: 'uyari',
    baslik: () => T('Uyarı', 'Alert'),
    goster(yeniIcerik) {
      icerik = yeniIcerik;
      acik = true;
      if (!katman) katmanlariKur();
      const canliIste = () => { if (canlida() && ['bekliyor', 'hata'].includes(canli.hal)) canliYukle(); };
      secimDinle(icerik, (grup, deger) => {
        durum[grup] = grup === 'mm' ? Number(deger) : deger;
        dugmeleriGuncelle(grup);
        harita.harita.closePopup();
        if (grup === 'gorunum') { canliIste(); gorunumCiz(); } else secimCiz();
        boya();
      });
      listeDinle(icerik, 'data-ilce', ilceyeGit);
      canliIste();
      ciz();
      boya();
      katman.addTo(harita.harita);
      harita.ilGorunumu();
    },
    gizle() {
      acik = false;
      harita.harita.closePopup();
      harita.harita.removeLayer(katman);
    },
    ciz,
    lejant: () => (duyarlilikta() ? duyarlilikLejanti() : canlida() ? canliLejanti() : olasilikLejanti()),
  };
}
