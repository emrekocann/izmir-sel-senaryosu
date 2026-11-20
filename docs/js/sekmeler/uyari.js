// Sekme: erken uyarı. İki görünüm:
//   olasılık   — itfaiye su baskını kayıtlarıyla eğitilmiş sınıflandırma modeli:
//                "bu yağışta bu ilçede olay (≥ 3 çağrı) olur mu?"
//   duyarlılık — coğrafi ağırlıklı lojistik regresyon (GWR): her ilçede sel
//                neyle geliyor, o günün yağışıyla mı, önceki haftanınkiyle mi?
// Veri: hesap/uyari_hazirla.py → veri/uyari.json (model, sınama, GWR, ilçe sınırları).
import { T, sayi } from '../cekirdek/dil.js';
import { yerAdi, kacis, yuzde, tarih } from '../cekirdek/bicim.js';
import { secimHtml, secimDinle, sayiKutulari, lejantOgesi } from '../cekirdek/arayuz.js';

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

const MODEL_EN = { gb: 'gradient boosting', rf: 'Random Forest', lojistik: 'logistic regression', agac: 'decision tree' };
/** Olasılık aralığı etiketi: tr "%5–10", en "5–10%". */
const araligi = (a, b) => T(`%${sayi(a * 100)}–${sayi(b * 100)}`, `${sayi(a * 100)}–${sayi(b * 100)}%`);
// 1'e yakın değerler iki ondalıkla: [1,04–2,2] "1'i içeriyor" diye okunmasın.
const carpanSayi = (x) => sayi(x, Math.abs(x - 1) < 0.1 ? 2 : 1);
const carpan = (x) => `×${carpanSayi(x)}`;
const carpanAraligi = (c) => `[${carpanSayi(c.aralik_95[0])}–${carpanSayi(c.aralik_95[1])}]`;
const kanitsizEtiket = () => T('kanıtlanmamış', 'not proven');

/** GWR: etkisi kanıtlanmış ilçeler, çarpanı büyükten küçüğe (Hakkında penceresi de kullanır). */
export const enDuyarlilar = (gwr, etken) => Object.keys(gwr.ilceler).filter((ad) => gwr.ilceler[ad][etken].kanitli)
  .sort((a, b) => gwr.ilceler[b][etken].deger - gwr.ilceler[a][etken].deger);

export function uyariSekmesi({ uyari, harita }) {
  const ilk = uyari.yagis_mm.includes(40) ? 40 : uyari.yagis_mm[Math.floor(uyari.yagis_mm.length / 2)];
  const durum = { gorunum: 'olasilik', etken: 'gunun_yagisi', mm: ilk, gecmis: 'islak' };
  let icerik = null, katman = null;
  const sekiller = new Map();          // ilçe adı → Leaflet katmanı
  const esik = uyari.model.esik;
  const gwr = uyari.gwr;
  const [mmA, mmB] = gwr.olcek_mm;

  const olasilik = (ad) => uyari.kosullar[durum.gecmis].olasilik[ad][uyari.yagis_mm.indexOf(durum.mm)];
  const alarm = (p) => p >= esik;
  const etki = (ad, etken = durum.etken) => gwr.ilceler[ad][etken];
  const duyarlilikta = () => durum.gorunum === 'duyarlilik';
  const etkiMetni = (c) => (c.kanitli ? carpan(c.deger) : kanitsizEtiket());

  const stil = (ad) => {
    if (duyarlilikta()) {
      const c = etki(ad);
      return c.kanitli ? { color: '#ffffff', weight: 1, dashArray: null, fillColor: MOR[carpanSinifi(c.deger)], fillOpacity: 0.85 }
        : KANITSIZ_STIL;
    }
    const p = olasilik(ad);
    return alarm(p) ? { color: '#1f2937', weight: 2.5, dashArray: null, fillColor: RENK[sinif(p)], fillOpacity: 0.85 }
      : { color: '#ffffff', weight: 1, dashArray: null, fillColor: RENK[sinif(p)], fillOpacity: 0.8 };
  };

  const acilir = (ilce) => {
    const ad = `<b>${kacis(yerAdi(ilce.ad))}</b>`;
    if (duyarlilikta()) {
      const satir = (etken, etiket) => {
        const c = etki(ilce.ad, etken);
        return `<span class="soluk">${etiket}:</span> ${carpan(c.deger)} <span class="soluk">${carpanAraligi(c)}${c.kanitli ? '' : ` ${kanitsizEtiket()}`}</span>`;
      };
      return `${ad}<br><span class="soluk kucuk">${T(`${mmA} mm yerine ${mmB} mm yağarsa olasılık çarpanı`, `Odds multiplier, ${mmB} mm instead of ${mmA} mm`)}</span><br>
        ${satir('gunun_yagisi', T('o gün', 'on the day'))}<br>${satir('onceki_hafta', T('önceki 7 günde', 'previous 7 days'))}`;
    }
    const p = olasilik(ilce.ad);
    return `${ad} ${alarm(p) ? `<span class="rozet kotu">${T('alarm', 'alert')}</span>` : ''}<br>
      <span class="soluk">${T('Olay olasılığı', 'Event probability')}:</span> ${yuzde(p)}<br>
      <span class="soluk">${T(`${uyari.model.egitim_yillari.join('–')} olay günü`, `Event days ${uyari.model.egitim_yillari.join('–')}`)}:</span> ${sayi(ilce.olay_gunu)}`;
  };

  function katmanlariKur() {
    katman = L.layerGroup();
    uyari.ilceler.forEach((ilce) => {
      const sekil = L.geoJSON(ilce.geometri, { style: () => stil(ilce.ad) })
        .bindTooltip(() => `${kacis(yerAdi(ilce.ad))}: ${duyarlilikta() ? etkiMetni(etki(ilce.ad)) : yuzde(olasilik(ilce.ad))}`, { sticky: true })
        .bindPopup(() => acilir(ilce), { maxWidth: 260 });
      sekiller.set(ilce.ad, sekil);
      katman.addLayer(sekil);
    });
  }

  const boya = () => uyari.ilceler.forEach((ilce) => sekiller.get(ilce.ad).setStyle(stil(ilce.ad)));

  function olasilikListesi() {
    return uyari.ilceler.map((i) => ({ ad: i.ad, p: olasilik(i.ad) })).sort((a, b) => b.p - a.p)
      .map(({ ad, p }) => `<li data-ilce="${kacis(ad)}" tabindex="0" role="button">
        <i class="olcek-kare" style="--renk:${RENK[sinif(p)]}"></i> <b>${kacis(yerAdi(ad))}</b> ${yuzde(p)}
        ${alarm(p) ? `<span class="rozet kotu">${T('alarm', 'alert')}</span>` : ''}</li>`).join('');
  }

  // Tablo görünümü: kanıtlananlar çarpana göre, kanıtlanmayanlar sonda ama değeriyle.
  function etkiListesi() {
    return uyari.ilceler.map((i) => ({ ad: i.ad, c: etki(i.ad) }))
      .sort((a, b) => (b.c.kanitli - a.c.kanitli) || (b.c.deger - a.c.deger))
      .map(({ ad, c }) => `<li data-ilce="${kacis(ad)}" tabindex="0" role="button"${c.kanitli ? '' : ' class="pasif"'}>
        <i class="olcek-kare${c.kanitli ? '' : ' kanitsiz'}" style="--renk:${c.kanitli ? MOR[carpanSinifi(c.deger)] : KANITSIZ_RENK}"></i>
        <b>${kacis(yerAdi(ad))}</b> ${carpan(c.deger)} <span class="soluk">${carpanAraligi(c)}${c.kanitli ? '' : ` ${kanitsizEtiket()}`}</span></li>`).join('');
  }

  function secimCiz() {
    const yer = icerik.querySelector('[data-yer="secim"]');
    if (duyarlilikta()) {
      const hepsi = uyari.ilceler.map((i) => ({ ad: i.ad, c: etki(i.ad) }));
      const kanitli = hepsi.filter((x) => x.c.kanitli);
      const enCok = kanitli.reduce((a, b) => (b.c.deger > a.c.deger ? b : a), kanitli[0]);
      yer.innerHTML = `
        <p>${durum.etken === 'gunun_yagisi'
          ? T(`Renk: <b>o gün ${mmA} mm yerine ${mmB} mm yağarsa</b> olay olasılığı kabaca kaç katına çıkıyor (önceki günlerin yağışı aynıyken).`,
              `Colour: how many times likelier an event becomes <b>if ${mmB} mm falls on the day instead of ${mmA} mm</b> (earlier days unchanged).`)
          : T(`Renk: <b>önceki 7 günde ${mmA} mm yerine ${mmB} mm yağmışsa</b> olay olasılığı kabaca kaç katına çıkıyor (o günün yağışı aynıyken).`,
              `Colour: how many times likelier an event becomes <b>if ${mmB} mm fell over the previous 7 days instead of ${mmA} mm</b> (the day's rain unchanged).`)}</p>
        ${sayiKutulari([
          [enCok ? carpan(enCok.c.deger) : '–', enCok ? T(`en duyarlı: ${kacis(yerAdi(enCok.ad))}`, `most sensitive: ${kacis(yerAdi(enCok.ad))}`) : ''],
          [`${sayi(kanitli.length)} / ${sayi(hepsi.length)}`, T('ilçede etki kanıtlanmış', 'districts with a proven effect')],
        ])}
        <ul class="liste kaydir" data-yer="liste">${etkiListesi()}</ul>`;
      return;
    }
    const alarmli = uyari.ilceler.filter((i) => alarm(olasilik(i.ad)));
    yer.innerHTML = `
      ${sayiKutulari([
        [`${sayi(alarmli.length)} / ${sayi(uyari.ilceler.length)}`, T('ilçede alarm', 'districts on alert')],
        [yuzde(Math.max(...uyari.ilceler.map((i) => olasilik(i.ad)))), T('en yüksek olasılık', 'highest probability')],
      ])}
      <ul class="liste kaydir" data-yer="liste">${olasilikListesi()}</ul>`;
  }

  function olasilikHtml() {
    const s = uyari.sinama, tum = s.tum_yillar, og = s.oglen_tahmin, yok = s.tahminsiz;
    const isl = uyari.kosullar.islak.onceki, o = uyari.ornek, yil = (x) => `${x.yillar[0]}–${x.yillar[x.yillar.length - 1]}`;
    const ar = (x, k) => araligi(...x.aralik_95[k]);
    return `
      <h3>${T('Yarın bu kadar yağarsa', 'If this much rain falls tomorrow')}</h3>
      <p class="soluk kucuk">${T(`Model: ${kacis(uyari.model.aciklama)}.`, `Model: ${MODEL_EN[uyari.model.ad] || uyari.model.ad}.`)}</p>
      <p class="alt-baslik">${T('Günlük yağış', 'Daily rain')}</p>
      ${secimHtml('mm', uyari.yagis_mm.filter((m) => m > 0).map((m) => [m, `${m} mm`]), durum.mm)}
      <p class="alt-baslik">${T('Önceki hafta', 'Previous week')}</p>
      ${secimHtml('gecmis', [['kuru', T('kuru', 'dry')], ['islak', T('ıslak', 'wet')]], durum.gecmis)}
      <p class="soluk kucuk">${T(`Islak: önceki 7 günde ${sayi(isl.yagis_onceki7g_mm)} mm, son 3 günde ${sayi(isl.yagis_onceki3g_mm)} mm (olay günlerinde tipik geçmiş). Önceki haftanın yağışı modelin en önemli değişkeni: toprak ve kanallar doluysa az yağmur da sel getirir.`,
             `Wet: ${sayi(isl.yagis_onceki7g_mm)} mm in the previous 7 days, ${sayi(isl.yagis_onceki3g_mm)} mm in the last 3 (typical history of an event day). The previous week's rain is the model's most important input: when soil and drains are full, little rain floods.`)}</p>
      <div data-yer="secim"></div>
      <p class="soluk kucuk">${T(`Kalın çerçeve: alarm (olasılık ≥ ${yuzde(esik)}, eğitim yıllarında en iyi isabet/yakalama dengesini veren eşik). Yağış miktarı yağış arşivinin (ERA5) ölçeğindedir; arşiv sağanağı yumuşattığı için istasyonda ölçülen yağış daha yüksektir.`,
             `Thick outline: alert (probability ≥ ${yuzde(esik)}, the threshold with the best precision/recall balance in training years). Rain is on the scale of the reanalysis archive (ERA5), which smooths downpours; station rainfall is higher.`)}</p>

      <h3>${T('Model nasıl sınandı?', 'How was it tested?')}</h3>
      <p>${T(`Her yıl, yalnız kendinden önceki yıllarla eğitilen modelle tahmin edildi (${yil(tum)}). Arka arkaya gelen büyük sel günleri (il genelinde ≥ ${uyari.olay_tanimi.il_cagri} çağrı) tek <b>atak</b> sayıldı; soru: atağın ilk gününde alarm var mıydı?`,
             `Each year was predicted by a model trained only on earlier years (${yil(tum)}). Consecutive major flood days (≥ ${uyari.olay_tanimi.il_cagri} calls province-wide) count as one <b>episode</b>; the question is whether there was an alert on its first day.`)}</p>
      ${sayiKutulari([
        [`${tum.atak_ilk_gun} / ${tum.atak}`, T('atak ilk gününde alarmlı', 'episodes alerted on day one')],
        [`${og.atak_ilk_gun} / ${og.atak}`, T(`bir gün önceki tahminle (${yil(og)})`, `with the day-before forecast (${yil(og)})`)],
        [yuzde(tum.duyarlilik), T('ilçe olaylarının yakalanan payı', 'of district events caught')],
        [yuzde(tum.kesinlik), T('alarmların isabetli payı', 'of alerts that were right')],
      ])}
      <ul>
        <li>${T(`<b>Bir gün önceden çalışıyor.</b> Uyarı önceki gün öğlen, o anda elde olan ECMWF hava tahminiyle verildiğinde de sonuç neredeyse aynı. Tahmin olmadan ilçe olaylarının yalnız ${yuzde(yok.duyarlilik)} kadarı yakalanıyor (tahminle ${yuzde(og.duyarlilik)}).`,
                 `<b>It works a day ahead.</b> With the alert issued at noon the day before, using the ECMWF forecast available then, results barely change. Without a forecast only ${yuzde(yok.duyarlilik)} of district events are caught (${yuzde(og.duyarlilik)} with it).`)}</li>
        <li>${T(`<b>Yıldan yıla çok oynuyor.</b> Büyük sel günlerinde alarm: ${s.yillar.map((y) => `${y.yil}: ${y.buyuk_gun_alarmli}/${y.buyuk_gun}`).join(', ')}. %95 aralıklar geniş: yakalama ${ar(tum, 'duyarlilik')}, isabet ${ar(tum, 'kesinlik')}.`,
                 `<b>It varies a lot from year to year.</b> Major flood days alerted: ${s.yillar.map((y) => `${y.yil}: ${y.buyuk_gun_alarmli}/${y.buyuk_gun}`).join(', ')}. 95% intervals are wide: recall ${ar(tum, 'duyarlilik')}, precision ${ar(tum, 'kesinlik')}.`)}</li>
      </ul>

      <div class="kutu kotu"><b>${T('Nerede duruyor?', 'Where it stops')}</b>
        <ul>
          <li>${T(`<b>Dar alanlı sağanağı göremiyor.</b> ${kacis(yerAdi(o.ilce))}, ${tarih(o.gun)}: valiliğe göre ${sayi(o.haber_saat, 1)} saatte ~${sayi(o.haber_mm)} mm yağdı, ${o.cagri_gun_sayisi} günde ${sayi(o.cagri)} çağrı geldi. Yağış arşivi o gün ${sayi(o.arsiv_mm, 1)} mm, bir gün önceki tahminler ${sayi(Math.min(...Object.values(o.tahmin_mm)), 1)}–${sayi(Math.max(...Object.values(o.tahmin_mm)), 1)} mm diyor. Model değil, veri kör.`,
                   `<b>It cannot see narrow downpours.</b> ${kacis(yerAdi(o.ilce))}, ${tarih(o.gun)}: the governor's office reported ~${sayi(o.haber_mm)} mm in ${sayi(o.haber_saat, 1)} hours, and ${sayi(o.cagri)} calls came in over ${o.cagri_gun_sayisi} days. The rain archive says ${sayi(o.arsiv_mm, 1)} mm that day, day-before forecasts ${sayi(Math.min(...Object.values(o.tahmin_mm)), 1)}–${sayi(Math.max(...Object.values(o.tahmin_mm)), 1)} mm. The data is blind, not the model.`)}
            ${o.kaynaklar.map((k) => `<a href="${kacis(k.url)}" target="_blank" rel="noopener">${kacis(k.ad)}</a>`).join(' · ')}</li>
          <li>${T(`<b>İlçe düzeyinde zayıf:</b> çoğu alarm boşa çıkıyor ve olayların çoğu kaçıyor. Bu bir ön uyarı sinyali, karar değil.`,
                   `<b>Weak at district level:</b> most alerts are false and most events are missed. It is an early signal, not a decision.`)}</li>
          <li>${T('<b>Mahalle yok:</b> itfaiye kayıtlarında adres olmadığı için birim ilçedir.', '<b>No neighbourhoods:</b> fire records carry no address, so the unit is the district.')}</li>
        </ul></div>`;
  }

  function duyarlilikHtml() {
    const s = gwr.sinama, yillar = `${s.gwr.yillar[0]}–${s.gwr.yillar[s.gwr.yillar.length - 1]}`;
    const enUst = (etken) => enDuyarlilar(gwr, etken).slice(0, 3).map((ad) => kacis(yerAdi(ad))).join(', ');
    const kanitsiz = uyari.ilceler.filter((i) => !etki(i.ad, 'onceki_hafta').kanitli).map((i) => yerAdi(i.ad))
      .sort((a, b) => a.localeCompare(b, 'tr')).map(kacis);
    const komsu = gwr.bant - 1;
    return `
      <h3>${T('Bu ilçede sel neyle geliyor?', 'What brings floods to each district?')}</h3>
      <p>${T(`Her ilçeye ayrı bir model kuruldu: coğrafi ağırlıklı lojistik regresyon (GWR). Model ilçenin kendi kayıtlarını ve en yakın ${komsu} komşusununkini, uzaklıkla azalan ağırlıkla kullanır.`,
             `A separate model for each district: geographically weighted logistic regression (GWR). It uses the district's own records and those of its ${komsu} nearest neighbours, weighted down with distance.`)}</p>
      <p class="alt-baslik">${T('Hangi yağış?', 'Which rain?')}</p>
      ${secimHtml('etken', [['gunun_yagisi', T('O günün yağışı', "The day's rain")], ['onceki_hafta', T('Önceki 7 gün', 'Previous 7 days')]], durum.etken)}
      <div data-yer="secim"></div>
      <p class="soluk kucuk">${T(`Kesik çizgili gri: etki kanıtlanmamış (%95 aralık 1'i içeriyor). Köşeli parantez: %95 aralık. Çarpan bir olasılık oranıdır (odds ratio); olasılık küçükken olasılığın kaç katına çıktığıyla hemen hemen aynıdır.`,
             `Dashed grey: no proven effect (the 95% interval includes 1). Brackets: 95% interval. The multiplier is an odds ratio; when probabilities are small it is close to how many times likelier the event becomes.`)}</p>
      <ul>
        <li>${T(`<b>Sel her yerde aynı yağışla gelmiyor.</b> O günün yağışına en duyarlı: ${enUst('gunun_yagisi')}. Önceki haftanın yağışına en duyarlı: ${enUst('onceki_hafta')}. Önceki haftanın etkisi ${sayi(kanitsiz.length)} ilçede kanıtlanmamış: ${kanitsiz.join(', ')}.`,
                 `<b>Floods do not come with the same rain everywhere.</b> Most sensitive to the day's rain: ${enUst('gunun_yagisi')}. Most sensitive to the previous week's rain: ${enUst('onceki_hafta')}. The previous week has no proven effect in ${sayi(kanitsiz.length)} districts: ${kanitsiz.join(', ')}.`)}</li>
        <li>${T(`<b>Tek yağış noktasının yan etkisi değil.</b> Büyük ilçelerde sağanak, yağışın okunduğu noktayı ıskalayabilir. O günün yağışı ilçenin en yağışlı noktasından alınınca da ilçelerin sıralaması neredeyse aynı kalıyor (sıra korelasyonu ${sayi(gwr.cok_nokta_sira_korelasyonu, 2)}).`,
                 `<b>Not an artefact of the single rain point.</b> In large districts a downpour can miss the point where rain is read. Taking the day's rain from the wettest point in the district leaves the ranking almost unchanged (rank correlation ${sayi(gwr.cok_nokta_sira_korelasyonu, 2)}).`)}</li>
        <li>${T(`<b>Uyarıyı iyileştirmiyor.</b> ${yillar} yıl yıl sınandığında ayrı modeller ilçe olaylarının ${yuzde(s.gwr.duyarlilik)} kadarını yakalıyor (tek model: ${yuzde(s.global.duyarlilik)}), alarmlarının ${yuzde(s.gwr.kesinlik)} kadarı isabetli (tek model: ${yuzde(s.global.kesinlik)}). Değeri ilçeler arasındaki farkı göstermesinde.`,
                 `<b>It does not improve the alert.</b> Tested year by year (${yillar}), the separate models catch ${yuzde(s.gwr.duyarlilik)} of district events (single model: ${yuzde(s.global.duyarlilik)}) and ${yuzde(s.gwr.kesinlik)} of their alerts are right (single model: ${yuzde(s.global.kesinlik)}). Its value is in showing how districts differ.`)}</li>
        <li>${T(`<b>Nedeni bu veriyle ayrılamıyor.</b> Havzanın biçimi ve toprağı yağışa farklı tepki veriyor olabilir; yağış arşivi de bazı yerlerde sağanağı daha çok yumuşatıyor olabilir.`,
                 `<b>The cause cannot be separated with this data.</b> Catchment shape and soil may respond differently to rain, or the rain archive may smooth downpours more in some places.`)}</li>
      </ul>`;
  }

  function gorunumCiz() {
    icerik.querySelector('[data-yer="gorunum"]').innerHTML = duyarlilikta() ? duyarlilikHtml() : olasilikHtml();
    secimCiz();
  }

  function ciz() {
    icerik.innerHTML = `
      <h2>${T('Erken uyarı: hangi ilçede sel olur?', 'Early warning: which district floods?')}</h2>
      <p>${T(`İzmir İtfaiyesi'nin ${uyari.veri.yillar.join('–')} su baskını kayıtlarıyla eğitilmiş makine öğrenmesi modelleri. Soru: <b>bir ilçede bir günde en az ${uyari.olay_tanimi.ilce_cagri} su baskını çağrısı gelir mi?</b>`,
             `Machine-learning models trained on İzmir Fire Department flood calls, ${uyari.veri.yillar.join('–')}. Question: <b>will a district get at least ${uyari.olay_tanimi.ilce_cagri} flood calls in a day?</b>`)}</p>
      <p class="alt-baslik">${T('Harita', 'Map')}</p>
      ${secimHtml('gorunum', [['olasilik', T('Olay olasılığı', 'Event probability')], ['duyarlilik', T('Yağışa duyarlılık', 'Sensitivity to rain')]], durum.gorunum)}
      <div data-yer="gorunum"></div>`;
    gorunumCiz();
  }

  function ilceyeGit(ad) {
    const sekil = sekiller.get(ad);
    harita.sigdir(sekil.getBounds(), 11);
    sekil.openPopup(sekil.getBounds().getCenter());
  }

  const olasilikLejanti = () => [`< ${yuzde(SINIR[0])}`, ...SINIR.slice(1).map((s, i) => araligi(SINIR[i], s)), `≥ ${yuzde(SINIR[SINIR.length - 1])}`]
    .map((etiket, i) => lejantOgesi(RENK[i], etiket)).join('')
    + `<span class="lej"><i style="--renk:${RENK[2]};border:2.5px solid #1f2937;box-shadow:0 0 0 1px #e5e7eb"></i>${T('alarm', 'alert')}</span>`;

  const duyarlilikLejanti = () => `<span class="soluk">${T(`${mmA} → ${mmB} mm, olasılık çarpanı`, `${mmA} → ${mmB} mm, odds multiplier`)}</span>`
    + [`< ×${sayi(CARPAN_SINIR[0])}`, ...CARPAN_SINIR.slice(1).map((s, i) => `×${sayi(CARPAN_SINIR[i])}–${sayi(s)}`), `≥ ×${sayi(CARPAN_SINIR[CARPAN_SINIR.length - 1])}`]
      .map((etiket, i) => lejantOgesi(MOR[i], etiket)).join('')
    + lejantOgesi(KANITSIZ_RENK, kanitsizEtiket(), 'kanitsiz');

  return {
    id: 'uyari',
    baslik: () => T('Uyarı', 'Alert'),
    goster(yeniIcerik) {
      icerik = yeniIcerik;
      if (!katman) katmanlariKur();
      secimDinle(icerik, (grup, deger) => {
        durum[grup] = grup === 'mm' ? Number(deger) : deger;
        icerik.querySelectorAll(`[data-secim="${grup}"]`).forEach((d) => {
          const secili = d.dataset.deger === String(durum[grup]);
          d.classList.toggle('secili', secili);
          d.setAttribute('aria-pressed', secili);
        });
        harita.harita.closePopup();
        if (grup === 'gorunum') gorunumCiz(); else secimCiz();
        boya();
      });
      const sec = (olay) => {
        const oge = olay.target.closest('[data-ilce]');
        if (oge && (olay.type === 'click' || olay.key === 'Enter')) ilceyeGit(oge.dataset.ilce);
      };
      icerik.addEventListener('click', sec);
      icerik.addEventListener('keydown', sec);
      ciz();
      boya();
      katman.addTo(harita.harita);
      harita.ilGorunumu();
    },
    gizle() {
      harita.harita.closePopup();
      harita.harita.removeLayer(katman);
    },
    ciz,
    lejant: () => (duyarlilikta() ? duyarlilikLejanti() : olasilikLejanti()),
  };
}
