// Sekme: erken uyarı. İtfaiye su baskını kayıtlarıyla eğitilmiş sınıflandırma
// modeli: "bu yağışta bu ilçede olay (≥ 3 çağrı) olur mu?" Veri:
// hesap/uyari_hazirla.py → veri/uyari.json (model, sınama, ilçe sınırları).
import { T, sayi, aktifDil } from '../cekirdek/dil.js';
import { yerAdi, kacis } from '../cekirdek/bicim.js';
import { secimHtml, secimDinle, sayiKutulari, lejantOgesi } from '../cekirdek/arayuz.js';

// Tek tonlu (turuncu) sıralı ölçek, açıktan koyuya. Mavi öteki sekmelerde su
// derinliği demek; olasılık onunla karışmasın diye turuncu.
const RENK = ['#fbe4d9', '#f6bfa3', '#ef9469', '#e0612e', '#a3401b'];
const SINIR = [0.05, 0.10, 0.20, 0.40];
const sinif = (p) => SINIR.filter((s) => p >= s).length;
const yuzde = (p) => `%${sayi(p * 100)}`;
const yuzdeEn = (p) => `${sayi(p * 100)}%`;
const oran = (p) => T(yuzde(p), yuzdeEn(p));
const tarih = (gun) => new Date(`${gun}T12:00:00`).toLocaleDateString(aktifDil() === 'tr' ? 'tr-TR' : 'en-GB',
  { day: 'numeric', month: 'long', year: 'numeric' });
const MODEL_EN = { gb: 'gradient boosting', rf: 'Random Forest', lojistik: 'logistic regression', agac: 'decision tree' };
/** Olasılık aralığı etiketi: tr "%5–10", en "5–10%". */
const araligi = (a, b) => T(`%${sayi(a * 100)}–${sayi(b * 100)}`, `${sayi(a * 100)}–${sayi(b * 100)}%`);

export function uyariSekmesi({ uyari, harita }) {
  const ilk = uyari.yagis_mm.includes(40) ? 40 : uyari.yagis_mm[Math.floor(uyari.yagis_mm.length / 2)];
  const durum = { mm: ilk, gecmis: 'islak' };
  let icerik = null, katman = null;
  const sekiller = new Map();          // ilçe adı → Leaflet katmanı
  const esik = uyari.model.esik;

  const olasilik = (ad) => uyari.kosullar[durum.gecmis].olasilik[ad][uyari.yagis_mm.indexOf(durum.mm)];
  const alarm = (p) => p >= esik;

  const stil = (ad) => {
    const p = olasilik(ad);
    return alarm(p) ? { color: '#1f2937', weight: 2.5, fillColor: RENK[sinif(p)], fillOpacity: 0.85 }
      : { color: '#ffffff', weight: 1, fillColor: RENK[sinif(p)], fillOpacity: 0.8 };
  };

  const acilir = (ilce) => {
    const p = olasilik(ilce.ad);
    return `<b>${kacis(yerAdi(ilce.ad))}</b> ${alarm(p) ? `<span class="rozet kotu">${T('alarm', 'alert')}</span>` : ''}<br>
      <span class="soluk">${T('Olay olasılığı', 'Event probability')}:</span> ${oran(p)}<br>
      <span class="soluk">${T(`${uyari.model.egitim_yillari.join('–')} olay günü`, `Event days ${uyari.model.egitim_yillari.join('–')}`)}:</span> ${sayi(ilce.olay_gunu)}`;
  };

  function katmanlariKur() {
    katman = L.layerGroup();
    uyari.ilceler.forEach((ilce) => {
      const sekil = L.geoJSON(ilce.geometri, { style: () => stil(ilce.ad) })
        .bindTooltip(() => `${kacis(yerAdi(ilce.ad))}: ${oran(olasilik(ilce.ad))}`, { sticky: true })
        .bindPopup(() => acilir(ilce), { maxWidth: 260 });
      sekiller.set(ilce.ad, sekil);
      katman.addLayer(sekil);
    });
  }

  const boya = () => uyari.ilceler.forEach((ilce) => sekiller.get(ilce.ad).setStyle(stil(ilce.ad)));

  function listeHtml() {
    return uyari.ilceler.map((i) => ({ ad: i.ad, p: olasilik(i.ad) })).sort((a, b) => b.p - a.p)
      .map(({ ad, p }) => `<li data-ilce="${kacis(ad)}" tabindex="0" role="button">
        <i class="olcek-kare" style="--renk:${RENK[sinif(p)]}"></i> <b>${kacis(yerAdi(ad))}</b> ${oran(p)}
        ${alarm(p) ? `<span class="rozet kotu">${T('alarm', 'alert')}</span>` : ''}</li>`).join('');
  }

  function secimCiz() {
    const alarmli = uyari.ilceler.filter((i) => alarm(olasilik(i.ad)));
    icerik.querySelector('[data-yer="secim"]').innerHTML = `
      ${sayiKutulari([
        [`${sayi(alarmli.length)} / ${sayi(uyari.ilceler.length)}`, T('ilçede alarm', 'districts on alert')],
        [oran(Math.max(...uyari.ilceler.map((i) => olasilik(i.ad)))), T('en yüksek olasılık', 'highest probability')],
      ])}
      <ul class="liste kaydir" data-yer="liste">${listeHtml()}</ul>`;
  }

  function ciz() {
    const s = uyari.sinama, tum = s.tum_yillar, og = s.oglen_tahmin, yok = s.tahminsiz;
    const isl = uyari.kosullar.islak.onceki, o = uyari.ornek, yil = (x) => `${x.yillar[0]}–${x.yillar[x.yillar.length - 1]}`;
    const ar = (x, k) => araligi(...x.aralik_95[k]);
    icerik.innerHTML = `
      <h2>${T('Erken uyarı: hangi ilçede sel olur?', 'Early warning: which district floods?')}</h2>
      <p>${T(`İzmir İtfaiyesi'nin ${uyari.veri.yillar.join('–')} su baskını kayıtlarıyla eğitilmiş bir makine öğrenmesi modeli: ${kacis(uyari.model.aciklama)}. Soru: <b>bir ilçede bir günde en az ${uyari.olay_tanimi.ilce_cagri} su baskını çağrısı gelir mi?</b>`,
             `A machine-learning model trained on İzmir Fire Department flood calls, ${uyari.veri.yillar.join('–')}. Model: ${MODEL_EN[uyari.model.ad] || uyari.model.ad}. Question: <b>will a district get at least ${uyari.olay_tanimi.ilce_cagri} flood calls in a day?</b>`)}</p>
      <h3>${T('Yarın bu kadar yağarsa', 'If this much rain falls tomorrow')}</h3>
      <p class="alt-baslik">${T('Günlük yağış', 'Daily rain')}</p>
      ${secimHtml('mm', uyari.yagis_mm.filter((m) => m > 0).map((m) => [m, `${m} mm`]), durum.mm)}
      <p class="alt-baslik">${T('Önceki hafta', 'Previous week')}</p>
      ${secimHtml('gecmis', [['kuru', T('kuru', 'dry')], ['islak', T('ıslak', 'wet')]], durum.gecmis)}
      <p class="soluk kucuk">${T(`Islak: önceki 7 günde ${sayi(isl.yagis_onceki7g_mm)} mm, son 3 günde ${sayi(isl.yagis_onceki3g_mm)} mm (olay günlerinde tipik geçmiş). Önceki haftanın yağışı modelin en önemli değişkeni: toprak ve kanallar doluysa az yağmur da sel getirir.`,
             `Wet: ${sayi(isl.yagis_onceki7g_mm)} mm in the previous 7 days, ${sayi(isl.yagis_onceki3g_mm)} mm in the last 3 (typical history of an event day). The previous week's rain is the model's most important input: when soil and drains are full, little rain floods.`)}</p>
      <div data-yer="secim"></div>
      <p class="soluk kucuk">${T(`Kalın çerçeve: alarm (olasılık ≥ ${yuzde(esik)}, eğitim yıllarında en iyi isabet/yakalama dengesini veren eşik). Yağış miktarı yağış arşivinin (ERA5) ölçeğindedir; arşiv sağanağı yumuşattığı için istasyonda ölçülen yağış daha yüksektir.`,
             `Thick outline: alert (probability ≥ ${yuzdeEn(esik)}, the threshold with the best precision/recall balance in training years). Rain is on the scale of the reanalysis archive (ERA5), which smooths downpours; station rainfall is higher.`)}</p>

      <h3>${T('Model nasıl sınandı?', 'How was it tested?')}</h3>
      <p>${T(`Her yıl, yalnız kendinden önceki yıllarla eğitilen modelle tahmin edildi (${yil(tum)}). Arka arkaya gelen büyük sel günleri (il genelinde ≥ ${uyari.olay_tanimi.il_cagri} çağrı) tek <b>atak</b> sayıldı; soru: atağın ilk gününde alarm var mıydı?`,
             `Each year was predicted by a model trained only on earlier years (${yil(tum)}). Consecutive major flood days (≥ ${uyari.olay_tanimi.il_cagri} calls province-wide) count as one <b>episode</b>; the question is whether there was an alert on its first day.`)}</p>
      ${sayiKutulari([
        [`${tum.atak_ilk_gun} / ${tum.atak}`, T('atak ilk gününde alarmlı', 'episodes alerted on day one')],
        [`${og.atak_ilk_gun} / ${og.atak}`, T(`bir gün önceki tahminle (${yil(og)})`, `with the day-before forecast (${yil(og)})`)],
        [oran(tum.duyarlilik), T('ilçe olaylarının yakalanan payı', 'of district events caught')],
        [oran(tum.kesinlik), T('alarmların isabetli payı', 'of alerts that were right')],
      ])}
      <ul>
        <li>${T(`<b>Bir gün önceden çalışıyor.</b> Uyarı önceki gün öğlen, o anda elde olan ECMWF hava tahminiyle verildiğinde de sonuç neredeyse aynı. Tahmin olmadan ilçe olaylarının yalnız ${oran(yok.duyarlilik)} kadarı yakalanıyor (tahminle ${oran(og.duyarlilik)}).`,
                 `<b>It works a day ahead.</b> With the alert issued at noon the day before, using the ECMWF forecast available then, results barely change. Without a forecast only ${oran(yok.duyarlilik)} of district events are caught (${oran(og.duyarlilik)} with it).`)}</li>
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
    secimCiz();
  }

  function ilceyeGit(ad) {
    const sekil = sekiller.get(ad);
    harita.sigdir(sekil.getBounds(), 11);
    sekil.openPopup(sekil.getBounds().getCenter());
  }

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
        boya();
        secimCiz();
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
    lejant: () => [`< ${oran(SINIR[0])}`, ...SINIR.slice(1).map((s, i) => araligi(SINIR[i], s)), `≥ ${oran(SINIR[SINIR.length - 1])}`]
      .map((etiket, i) => lejantOgesi(RENK[i], etiket)).join('')
      + `<span class="lej"><i style="--renk:${RENK[2]};border:2.5px solid #1f2937;box-shadow:0 0 0 1px #e5e7eb"></i>${T('alarm', 'alert')}</span>`,
  };
}
