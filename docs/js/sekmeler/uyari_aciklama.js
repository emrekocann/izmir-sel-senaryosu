// Erken uyarı sekmesinin "nasıl çalışıyor" bölümü: model nasıl eğitildi, ne
// kadar doğru, hangi sel dalgalarını yakaladı ve nerede duruyor. Yalnız
// uyari.json'u okur (sekmenin seçim durumuna bağlı değildir).
import { T, sayi } from '../cekirdek/dil.js';
import { yerAdi, kacis, aralik, yuzde, yilAraligi, tarih, tarihAraligi } from '../cekirdek/bicim.js';
import { sayiKutulari } from '../cekirdek/arayuz.js';

// Modelin girdileri ve denenen yöntemler, sade adlarıyla (uyari.json'daki kısa ad → [tr, en]).
const GIRDI = {
  yagis_onceki7g_mm: ['önceki 7 günün yağışı', 'rain over the previous 7 days'],
  log_nufus: ['ilçenin nüfusu', "the district's population"],
  yagis_mm: ['o günün yağışı', "the day's rain"],
  kent_payi: ['ilçede binaların ve yolların kapladığı alan', 'how much of the district is buildings and roads'],
  yagis_onceki3g_mm: ['önceki 3 günün yağışı', 'rain over the previous 3 days'],
  yagis_max3s_mm: ['günün en yoğun 3 saatinde yağan', "the day's heaviest 3 hours of rain"],
  yagis_dun_mm: ['dünkü yağış', "yesterday's rain"],
  yagis_max1s_mm: ['günün en yoğun 1 saatinde yağan', "the day's heaviest hour of rain"],
};
const YONTEM = {
  temel: [['yağışsız basit model', 'no-rain baseline'],
    ['yalnız nüfus ve yapılaşma; yağışın ne kattığını ölçmek için', 'population and built-up area only; to measure what rain adds']],
  lojistik: [['lojistik regresyon', 'logistic regression'], ['klasik istatistik modeli', 'the classic statistical model']],
  agac: [['karar ağacı', 'decision tree'], ['evet/hayır sorularıyla dallanan tek bir ağaç', 'a single tree of yes/no questions']],
  rf: [['Random Forest', 'Random Forest'], ['çok sayıda karar ağacının ortak kararı', 'the joint vote of many decision trees']],
  gb: [['gradient boosting', 'gradient boosting'], ['her ağaç bir öncekinin hatasını düzeltir', 'each tree corrects the errors of the one before']],
};
const girdiAdi = (o) => (GIRDI[o.ad] ? T(...GIRDI[o.ad]) : kacis(o.aciklama));
const yontemAdi = (ad) => (YONTEM[ad] ? T(...YONTEM[ad][0]) : kacis(ad));

// Sel dalgasının sonucu: ilk gün alarm, yalnız sonraki günlerde alarm, hiç alarm yok.
const DALGA = {
  ilk: ['iyi', () => T('✓ ilk gün alarm', '✓ alert on day one')],
  gec: ['gec', () => T('◐ alarm sonraki günlerde', '◐ alert on a later day')],
  yok: ['kotu', () => T('✗ alarm yok', '✗ no alert')],
};
const dalgaSonucu = (d) => (d.ilk_gun_alarm ? 'ilk' : d.herhangi_alarm ? 'gec' : 'yok');

/** Oran → "her 100'de kaç": 0,363 → "36". */
export const yuzdeSayi = (oran) => sayi(Math.round(oran * 100));

/** uyari.json → açıklama HTML'i (dil değişince yeniden çağrılır). */
export function aciklamaHtml(uyari) {
  const { ilce_cagri: ilceCagri, il_cagri: ilCagri, dalga_arasi_gun: dalgaArasi } = uyari.olay_tanimi;

  function egitimHtml() {
    const v = uyari.veri, e = uyari.egitim, secilen = uyari.model.ad;
    const enBuyuk = Math.max(...uyari.onem.map((o) => o.ap_dususu));
    const monoton = secilen === 'gb'
      ? T(' Modele bir de fizik kuralı verildi: başka her şey aynıyken daha çok yağış sel olasılığını düşüremez.',
          ' It was also given one physical rule: all else equal, more rain cannot lower the flood probability.') : '';
    return `
      <h3>${T('Model nasıl eğitildi?', 'How was the model trained?')}</h3>
      <p>${T(`<b>Veri:</b> ${yilAraligi(v.yillar)} arasında ${sayi(v.ilce)} ilçenin her günü bir satır, toplam ${sayi(v.satir)} ilçe-gün. Her satırda iki şey var: o gün ilçeye en az ${ilceCagri} su baskını çağrısı geldi mi (İzmir İtfaiyesi, İBB Açık Veri) ve o gün ile önceki günlerde ne kadar yağdı (yağış arşivi). Satırların yalnız ${sayi(v.olay)} tanesinde sel var (${yuzde(v.olay_orani, 1)}).`,
             `<b>Data:</b> one row for every day of ${sayi(v.ilce)} districts, ${yilAraligi(v.yillar)}: ${sayi(v.satir)} district-days. Each row says whether the district got at least ${ilceCagri} flood calls that day (İzmir Fire Department, İzmir open data) and how much rain fell that day and the days before (rain archive). Only ${sayi(v.olay)} rows are floods (${yuzde(v.olay_orani, 1)}).`)}</p>
      <p>${T(`Modelin gördüğü ${sayi(uyari.onem.length)} bilgi, en çok dikkate aldığından en aza:`,
             `The ${sayi(uyari.onem.length)} inputs the model sees, from the one it relies on most to the least:`)}</p>
      <ol class="onem">${uyari.onem.map((o) => `<li>${girdiAdi(o)}<i style="--oran:${(o.ap_dususu / enBuyuk).toFixed(3)}"></i></li>`).join('')}</ol>
      <p class="soluk kucuk">${T('Sıra şöyle ölçüldü: bir bilgi karıştırılıp anlamsız hale getirilince tahminler ne kadar kötüleşiyor.',
                                 'Ranked by how much the predictions worsen when that input is shuffled into noise.')}</p>
      <p>${T(`<b>Yöntem:</b> ${sayi(e.modeller.length)} yöntem aynı veriyle denendi:`, `<b>Method:</b> ${sayi(e.modeller.length)} methods were tried on the same data:`)}</p>
      <ul>${e.modeller.map((ad) => `<li><b>${yontemAdi(ad)}</b>${YONTEM[ad] ? `: ${T(...YONTEM[ad][1])}` : ''}${ad === secilen ? ` <span class="rozet iyi">${T('seçildi', 'chosen')}</span>` : ''}</li>`).join('')}</ul>
      <p>${T(`Seçim ${yilAraligi(e.secim_yillari)} verisiyle yapıldı: her yıl sırayla dışarıda bırakıldı, yöntem öteki yıllarla eğitilip o yılı tahmin etti. Sel günlerini öteki günlerden en iyi ayıran seçildi: <b>${yontemAdi(secilen)}</b>.${monoton} Haritadaki model, bütün yılların (${yilAraligi(v.yillar)}) verisiyle yeniden eğitildi.`,
             `The choice was made on ${yilAraligi(e.secim_yillari)}: each year was left out in turn, and each method, trained on the other years, predicted it. The one that best told flood days from the rest was chosen: <b>${yontemAdi(secilen)}</b>.${monoton} The model on the map was then retrained on all years (${yilAraligi(v.yillar)}).`)}</p>`;
  }

  function dogrulukHtml() {
    const s = uyari.sinama, tum = s.tum_yillar, og = s.oglen_tahmin, yok = s.tahminsiz, cn = s.canli_tahmin, k = tum.dort_kutu;
    const dogruluk = (k.dogru_alarm + k.dogru_sessiz) / k.ilce_gun, hicAlarmsiz = (k.ilce_gun - k.sel) / k.ilce_gun;
    const [yA, yB] = tum.aralik_95.duyarlilik, [iA, iB] = tum.aralik_95.kesinlik;
    const secim = uyari.egitim.secim_yillari, temiz = tum.yillar.filter((y) => y > secim[1]);
    const kutu = (renk, n, etiket) => `<td class="${renk}"><b>${sayi(n)}</b><span>${etiket}</span></td>`;
    return `
      <h3>${T('Model ne kadar doğru?', 'How accurate is it?')}</h3>
      <p>${T(`Model, görmediği günlerle sınandı: ${yilAraligi(tum.yillar)} arasında her yıl, yalnız kendinden önceki yıllarla eğitilen bir modelle tahmin edildi; tahminler sonra itfaiye kayıtlarıyla karşılaştırıldı. Toplam ${sayi(k.ilce_gun)} ilçe-gün; bunların ${sayi(k.sel)} tanesinde sel oldu.`,
             `The model was tested on days it had not seen: each year ${yilAraligi(tum.yillar)} was predicted by a model trained only on the years before it, and the predictions were then checked against the fire records. ${sayi(k.ilce_gun)} district-days in all, ${sayi(k.sel)} of them with a flood.`)}</p>
      ${sayiKutulari([
        [`${yuzdeSayi(tum.duyarlilik)} / 100`, T('selde önceden alarm vardı', 'floods had an alert beforehand')],
        [`${yuzdeSayi(tum.kesinlik)} / 100`, T('alarmda gerçekten sel oldu', 'alerts were followed by a flood')],
      ])}
      <p class="soluk kucuk">${T('Sınanan ilçe-günler dört kutuya ayrılıyor:', 'The tested district-days fall into four boxes:')}</p>
      <div class="tablo-sar"><table class="dortlu">
        <tr><th></th><th scope="col">${T('Sel oldu', 'Flood')}</th><th scope="col">${T('Sel olmadı', 'No flood')}</th></tr>
        <tr><th scope="row">${T('Alarm verildi', 'Alert')}</th>${kutu('iyi', k.dogru_alarm, T('doğru alarm', 'correct alert'))}${kutu('kotu', k.bosa_alarm, T('boşa alarm', 'false alert'))}</tr>
        <tr><th scope="row">${T('Alarm yok', 'No alert')}</th>${kutu('kotu', k.kacan, T('kaçan sel', 'missed flood'))}${kutu('iyi', k.dogru_sessiz, T('doğru sessizlik', 'correct silence'))}</tr>
      </table></div>
      <div class="kutu not"><p><b>${T(`Neden "${yuzde(dogruluk)} doğru" demiyoruz?`, `Why not just say "${yuzde(dogruluk)} accurate"?`)}</b>
        ${T(`Model ilçe-günlerin ${yuzde(dogruluk, 1)} kadarında doğru tahminde bulundu. Ama hiç alarm vermeyen bir model ${yuzde(hicAlarmsiz, 1)} kadarında doğru olurdu, çünkü günlerin çoğunda sel olmaz. Bu yüzden başarı iki soruyla ölçülür: seller önceden görüldü mü, alarmlar doğru çıktı mı?`,
            `The model was right on ${yuzde(dogruluk, 1)} of district-days. But a model that never alerts would be right on ${yuzde(hicAlarmsiz, 1)}, because most days have no flood. So success is measured by two questions: were floods seen in advance, and did the alerts come true?`)}</p></div>
      <p class="soluk kucuk">${T(`Sonuçlar az sayıda büyük olaya dayanıyor. Başka yıllar yaşansaydı her 100 selden önceden görülen ${yuzdeSayi(yA)} ile ${yuzdeSayi(yB)} arasında, her 100 alarmdan doğru çıkan ${yuzdeSayi(iA)} ile ${yuzdeSayi(iB)} arasında olabilirdi (%95 güven aralığı).`,
                                 `The results rest on few big events. Had other years happened, floods seen in advance could be anywhere from ${yuzdeSayi(yA)} to ${yuzdeSayi(yB)} in 100, and alerts that came true from ${yuzdeSayi(iA)} to ${yuzdeSayi(iB)} in 100 (95% confidence interval).`)}
        ${temiz.length ? T(` Yöntem ${yilAraligi(secim)} yıllarına bakılarak seçildi; ${yilAraligi(temiz)} hiçbir seçimde kullanılmadı, en temiz sınav o yıllar.`,
                           ` The method was chosen by looking at ${yilAraligi(secim)}; ${yilAraligi(temiz)} played no part in any choice and is the cleanest test.`) : ''}</p>
      <p>${T(`<b>Bir gün önceden de çalışıyor.</b> Yukarıdaki sınamada o günün yağışı arşivden alındı, yani yağış önceden biliniyormuş gibi. Gerçek uyarı bir gün önce, hava tahminiyle verilir. ${yilAraligi(og.yillar)} böyle de sınandı: önceki gün öğlen elde olan hava tahminiyle (ECMWF) her 100 selin ${yuzdeSayi(og.duyarlilik)} tanesinde alarm vardı ve her 100 alarmın ${yuzdeSayi(og.kesinlik)} tanesi doğru çıktı. Hava tahmini kullanılmasaydı, yalnız geçmiş günlerin yağışıyla, her 100 selin ${yuzdeSayi(yok.duyarlilik)} tanesinde alarm olurdu.`,
             `<b>It also works a day ahead.</b> The test above took the day's rain from the archive, as if it were known in advance. A real alert is issued the day before, from a weather forecast. ${yilAraligi(og.yillar)} was tested this way too: with the ECMWF forecast available at noon the day before, ${yuzdeSayi(og.duyarlilik)} of every 100 floods had an alert and ${yuzdeSayi(og.kesinlik)} of every 100 alerts came true. Without a forecast, from earlier days' rain alone, only ${yuzdeSayi(yok.duyarlilik)} of every 100 floods would have had an alert.`)}</p>
      <p>${T(`<b>Sayfadaki canlı tahmin de böyle sınandı.</b> "Yarının tahmini" her gün aynısını yapıyor; tek farkı, son günlerin yağışının da tahmin modelinin kendi kaydından gelmesi (yağış arşivi birkaç gün geç yayımlanır). Böyle sınanınca her 100 selin ${yuzdeSayi(cn.duyarlilik)} tanesinde alarm vardı, her 100 alarmın ${yuzdeSayi(cn.kesinlik)} tanesi doğru çıktı.`,
             `<b>The live forecast on this page was tested the same way.</b> "Tomorrow's forecast" does the same every day; the only difference is that the last few days' rain also comes from the forecast model's own record (the rain archive is published a few days late). Tested that way, ${yuzdeSayi(cn.duyarlilik)} of every 100 floods had an alert and ${yuzdeSayi(cn.kesinlik)} of every 100 alerts came true.`)}</p>`;
  }

  const dalgaSatiri = (d) => {
    const [renk, etiket] = DALGA[dalgaSonucu(d)];
    return `<li><span class="rozet ${renk}">${etiket()}</span> <b>${tarihAraligi(d.ilk, d.son)}</b><br>
      <span class="soluk">${T(`${kacis(yerAdi(d.ilce))}: ${sayi(d.cagri)} çağrı (il geneli ${sayi(d.il_cagri)}) · yağış ${sayi(d.yagis_mm, 1)} mm, önceki 7 gün ${sayi(d.onceki7g_mm, 1)} mm`,
                              `${kacis(yerAdi(d.ilce))}: ${sayi(d.cagri)} calls (province ${sayi(d.il_cagri)}) · rain ${sayi(d.yagis_mm, 1)} mm, previous 7 days ${sayi(d.onceki7g_mm, 1)} mm`)}</span></li>`;
  };

  function dalgalarHtml() {
    const s = uyari.sinama, tum = s.tum_yillar, d = tum.dalgalar, al = d.ilk_gun_alarmli, alma = d.ilk_gun_alarmsiz, o = uyari.ornek;
    const kaynaklar = o.kaynaklar.map((k) => `<a href="${kacis(k.url)}" target="_blank" rel="noopener">${kacis(k.ad)}</a>`).join(' · ');
    return `
      <h3>${T('Neleri yakaladı, neleri kaçırdı?', 'What did it catch, what did it miss?')}</h3>
      <p>${T(`İlçe ilçe bakınca zayıf; il genelindeki büyük sellerde daha iyi. İl genelinde en az ${ilCagri} su baskını çağrısının geldiği gün <b>büyük sel günü</b> sayıldı; arka arkaya gelen büyük sel günleri (aralarında en çok ${sayi(dalgaArasi)} gün ara) tek bir <b>sel dalgası</b>. Bir günde herhangi bir ilçede alarm varsa o gün alarmlı sayıldı.`,
             `District by district it is weak; for big floods across the province it does better. A day with at least ${ilCagri} flood calls province-wide is a <b>major flood day</b>; consecutive major flood days (at most ${sayi(dalgaArasi)} day apart) form one <b>flood wave</b>. A day counts as alerted if any district had an alert.`)}</p>
      ${sayiKutulari([
        [`${sayi(tum.atak_ilk_gun)} / ${sayi(tum.atak)}`, T('sel dalgasında ilk gün alarm vardı', 'flood waves had an alert on day one')],
        [`${sayi(tum.buyuk_gun_alarmli)} / ${sayi(tum.buyuk_gun)}`, T('büyük sel gününde alarm vardı', 'major flood days had an alert')],
      ])}
      <div class="tablo-sar"><table>
        <tr><th>${T('Yıl', 'Year')}</th><th class="s">${T('Büyük sel günü', 'Major flood days')}</th><th class="s">${T('Alarm vardı', 'With an alert')}</th></tr>
        ${s.yillar.map((y) => `<tr><td>${y.yil}</td><td class="s">${sayi(y.buyuk_gun)}</td><td class="s">${sayi(y.buyuk_gun_alarmli)}</td></tr>`).join('')}
      </table></div>
      <p class="soluk kucuk">${T('Yıldan yıla çok değişiyor: sonuç birkaç büyük fırtınaya bağlı.', 'It varies a lot from year to year: the result hangs on a few big storms.')}</p>
      <div class="alan-baslik">${T(`Bütün sel dalgaları (${yilAraligi(tum.yillar)})`, `All flood waves (${yilAraligi(tum.yillar)})`)}</div>
      <p class="soluk kucuk">${T('Her satırda: dalganın tarihi, ilk gün en çok çağrının geldiği ilçe, oradaki çağrı sayısı ve yağış arşivinin o ilçe için gösterdiği yağış.',
                                 'Each row: the dates of the wave, the district with the most calls on day one, its calls, and the rain the archive shows there.')}</p>
      <ul class="liste kaydir dalgalar">${d.liste.map(dalgaSatiri).join('')}</ul>
      ${alma.dalga ? `<p>${T(`<b>Neden kaçtı?</b> İlk gün alarm almayan ${sayi(alma.dalga)} dalgada, en çok çağrının geldiği ilçede yağış arşivi o gün tipik olarak yalnız ${sayi(alma.yagis_mm, 1)} mm, önceki 7 günde ${sayi(alma.onceki7g_mm, 1)} mm gösteriyor (ortanca). İlk gün yakalanan ${sayi(al.dalga)} dalgada bu sayılar ${sayi(al.yagis_mm, 1)} mm ve ${sayi(al.onceki7g_mm, 1)} mm. Yani kaçanlar çoğunlukla kuru bir haftanın ardından gelen ve yağış arşivinin göremediği ya da hafife aldığı sağanaklar.`,
                                    `<b>Why were they missed?</b> In the ${sayi(alma.dalga)} waves with no alert on day one, the rain archive typically shows only ${sayi(alma.yagis_mm, 1)} mm that day and ${sayi(alma.onceki7g_mm, 1)} mm over the previous 7 days in the busiest district (median). In the ${sayi(al.dalga)} waves caught on day one, these are ${sayi(al.yagis_mm, 1)} mm and ${sayi(al.onceki7g_mm, 1)} mm. So the misses are mostly downpours after a dry week that the rain archive did not see or underestimated.`)}</p>` : ''}
      <div class="kutu not"><p>${T(`<b>Örnek: ${kacis(yerAdi(o.ilce))}, ${tarih(o.gun)}.</b> Valiliğe göre ${sayi(o.haber_saat, 1)} saatte ~${sayi(o.haber_mm)} mm yağdı; ${sayi(o.cagri_gun_sayisi)} günde ${sayi(o.cagri)} çağrı geldi. Yağış arşivi o gün ilçe için ${sayi(o.arsiv_mm, 1)} mm diyor, bir gün önceki hava tahminleri ${aralik(Object.values(o.tahmin_mm), 1)} mm. Model değil, veri kör: bu sağanağı gören istasyon ya da radar verisi olmadan hiçbir model yakalayamaz.`,
                                    `<b>Example: ${kacis(yerAdi(o.ilce))}, ${tarih(o.gun)}.</b> The governor's office reported ~${sayi(o.haber_mm)} mm in ${sayi(o.haber_saat, 1)} hours; ${sayi(o.cagri)} calls came in over ${sayi(o.cagri_gun_sayisi)} days. The rain archive says ${sayi(o.arsiv_mm, 1)} mm for the district that day, day-before forecasts ${aralik(Object.values(o.tahmin_mm), 1)} mm. The data is blind, not the model: without station or radar data that saw this downpour, no model could catch it.`)}
        ${kaynaklar}</p></div>`;
  }

  const sinirlarHtml = () => `
      <div class="kutu kotu"><b>${T('Nerede duruyor?', 'Where it stops')}</b>
        <ul>
          <li>${T('<b>İlçe düzeyinde zayıf:</b> alarmların çoğu boşa çıkıyor, sellerin çoğu kaçıyor. Bu bir ön uyarı sinyali, karar değil.',
                   '<b>Weak at district level:</b> most alerts are false and most floods are missed. It is an early signal, not a decision.')}</li>
          <li>${T('<b>Dar alana düşen sağanağı göremiyor:</b> yağış arşivi ve hava tahmini bu ölçekte kör. İstasyon ve radar yağışı bunu düzeltir.',
                   '<b>It cannot see narrow downpours:</b> the rain archive and the forecast are blind at that scale. Station and radar rainfall would fix it.')}</li>
          <li>${T('<b>Mahalle yok:</b> itfaiye kayıtlarında adres olmadığı için birim ilçe.', '<b>No neighbourhoods:</b> fire records carry no address, so the unit is the district.')}</li>
        </ul></div>`;

  return egitimHtml() + dogrulukHtml() + dalgalarHtml() + sinirlarHtml();
}
