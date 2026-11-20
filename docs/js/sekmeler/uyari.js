// Sekme: erken uyarı. İki görünüm:
//   olasılık   — itfaiye su baskını kayıtlarıyla eğitilmiş sınıflandırma modeli:
//                "yarın bu yağışta bu ilçeye ≥ 3 su baskını çağrısı gelir mi?"
//                Altında: model nasıl eğitildi, ne kadar doğru (dört kutu),
//                hangi sel dalgalarını yakaladı, hangilerini kaçırdı ve neden.
//   duyarlılık — coğrafi ağırlıklı lojistik regresyon (GWR): her ilçede sel
//                neyle geliyor, o günün yağışıyla mı, önceki haftanınkiyle mi?
// Metin sade dildedir; bütün sayılar veriden gelir (hesap/uyari_hazirla.py → veri/uyari.json).
import { T, sayi } from '../cekirdek/dil.js';
import { yerAdi, kacis, aralik, yuzde, yuzdeAraligi, yilAraligi, tarih, tarihAraligi } from '../cekirdek/bicim.js';
import { secimHtml, secimDinle, listeDinle, sayiKutulari, lejantOgesi } from '../cekirdek/arayuz.js';

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

// 1'e yakın değerler iki ondalıkla: [1,04–2,2] "1'i içeriyor" diye okunmasın.
const carpanSayi = (x) => sayi(x, Math.abs(x - 1) < 0.1 ? 2 : 1);
const kat = (x) => T(`${carpanSayi(x)} kat`, `${carpanSayi(x)}×`);
const carpanAraligi = (c) => `[${carpanSayi(c.aralik_95[0])}–${carpanSayi(c.aralik_95[1])}]`;
const kanitsizEtiket = () => T('etkisi kanıtlanamadı', 'no proven effect');
/** Oran → "her 100'de kaç": 0,363 → "36". */
const yuzdeSayi = (oran) => sayi(Math.round(oran * 100));
const alarmRozeti = () => `<span class="rozet kotu">${T('alarm', 'alert')}</span>`;

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
  const { ilce_cagri: ilceCagri, il_cagri: ilCagri, dalga_arasi_gun: dalgaArasi } = uyari.olay_tanimi;

  const olasilik = (ad) => uyari.kosullar[durum.gecmis].olasilik[ad][uyari.yagis_mm.indexOf(durum.mm)];
  const alarm = (p) => p >= esik;
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
    return alarm(p) ? { color: '#1f2937', weight: 2.5, dashArray: null, fillColor: RENK[sinif(p)], fillOpacity: 0.85 }
      : { color: '#ffffff', weight: 1, dashArray: null, fillColor: RENK[sinif(p)], fillOpacity: 0.8 };
  };

  const acilir = (ilce) => {
    const ad = `<b>${kacis(yerAdi(ilce.ad))}</b>`;
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
      <span class="soluk">${T(`Sel olan gün sayısı (${yilAraligi(uyari.veri.yillar)})`, `Flood days (${yilAraligi(uyari.veri.yillar)})`)}:</span> ${sayi(ilce.olay_gunu)}`;
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
        ${alarm(p) ? alarmRozeti() : ''}</li>`).join('');
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
    const ilceler = uyari.ilceler.map((i) => ({ ad: i.ad, p: olasilik(i.ad) }));
    const enYuksek = ilceler.reduce((a, b) => (b.p > a.p ? b : a));
    yer.innerHTML = `
      ${sayiKutulari([
        [`${sayi(ilceler.filter((x) => alarm(x.p)).length)} / ${sayi(ilceler.length)}`, T('ilçede alarm', 'districts on alert')],
        [yuzde(enYuksek.p), T(`en yüksek olasılık: ${kacis(yerAdi(enYuksek.ad))}`, `highest probability: ${kacis(yerAdi(enYuksek.ad))}`)],
      ])}
      <ul class="liste kaydir" data-yer="liste">${olasilikListesi()}</ul>`;
  }

  // ── Olasılık görünümü: denetimler, eğitim, doğruluk, sel dalgaları, sınırlar ──

  function denetimHtml() {
    const isl = uyari.kosullar.islak.onceki, ornek = SINIR[2];
    return `
      <div class="alan-baslik">${T('Yarın kaç mm yağsın?', 'How much rain tomorrow?')}</div>
      ${secimHtml('mm', uyari.yagis_mm.filter((m) => m > 0).map((m) => [m, `${m} mm`]), durum.mm)}
      <div class="alan-baslik">${T('Son bir hafta nasıl geçti?', 'How was the past week?')}</div>
      ${secimHtml('gecmis', [['kuru', T('Kuru', 'Dry')], ['islak', T('Yağışlı', 'Wet')]], durum.gecmis)}
      <p class="soluk kucuk bosluk-ust">${T(`Kuru: önceki 7 gün hiç yağmamış. Yağışlı: önceki 7 günde ${sayi(isl.yagis_onceki7g_mm)} mm, son 3 günde ${sayi(isl.yagis_onceki3g_mm)} mm yağmış; sel olan günlerden önce tipik olarak bu kadar yağıyor. Toprak ve kanallar doluysa az yağmur da sel getirir.`,
             `Dry: no rain in the previous 7 days. Wet: ${sayi(isl.yagis_onceki7g_mm)} mm over the previous 7 days, ${sayi(isl.yagis_onceki3g_mm)} mm in the last 3; that is typical before flood days. When soil and drains are full, even a little rain floods.`)}</p>
      <div data-yer="secim"></div>
      <p class="soluk kucuk">${T(`<b>Haritayı okumak:</b> renk, seçtiğiniz yağışta o ilçede sel olma olasılığı (${yuzde(ornek)}: böyle ${sayi(Math.round(1 / ornek))} günün birinde sel olur). Kalın siyah çerçeve: alarm, yani olasılık ${yuzde(esik)} ve üstü. Bu eşik, eğitim yıllarında kaçan sel ile boşa alarm arasındaki en iyi dengeyi verdi. Yağış, yağış arşivinin (ERA5) ölçeğinde: arşiv sağanağı yumuşatır, istasyonda ölçülen yağış genelde daha yüksektir.`,
             `<b>Reading the map:</b> colour is the probability of a flood in that district with the rain you chose (${yuzde(ornek)}: a flood on one in ${sayi(Math.round(1 / ornek))} such days). Thick black outline: alert, i.e. probability ${yuzde(esik)} or more. This threshold gave the best balance between missed floods and false alerts in the training years. Rain is on the scale of the rain archive (ERA5), which smooths downpours; station rainfall is usually higher.`)}</p>`;
  }

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
    const s = uyari.sinama, tum = s.tum_yillar, og = s.oglen_tahmin, yok = s.tahminsiz, k = tum.dort_kutu;
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
      <p>${T(`<b>Bir gün önceden de çalışıyor.</b> Yukarıdaki sınamada o günün yağışı arşivden alındı, yani yağış önceden biliniyormuş gibi. Gerçek uyarı bir gün önce, hava tahminiyle verilir. ${yilAraligi(og.yillar)} böyle de sınandı: önceki gün öğlen elde olan hava tahminiyle (ECMWF) her 100 selin ${yuzdeSayi(og.duyarlilik)} tanesinde alarm vardı ve her 100 alarmın ${yuzdeSayi(og.kesinlik)} tanesi doğru çıktı. Hava tahmini kullanılmasaydı, yalnız geçmiş günlerin yağışıyla, her 100 selin ${yuzdeSayi(yok.duyarlilik)} tanesinde alarm olurdu.`,
             `<b>It also works a day ahead.</b> The test above took the day's rain from the archive, as if it were known in advance. A real alert is issued the day before, from a weather forecast. ${yilAraligi(og.yillar)} was tested this way too: with the ECMWF forecast available at noon the day before, ${yuzdeSayi(og.duyarlilik)} of every 100 floods had an alert and ${yuzdeSayi(og.kesinlik)} of every 100 alerts came true. Without a forecast, from earlier days' rain alone, only ${yuzdeSayi(yok.duyarlilik)} of every 100 floods would have had an alert.`)}</p>
      <p class="soluk kucuk">${T(`Sonuçlar az sayıda büyük olaya dayanıyor. Başka yıllar yaşansaydı her 100 selden önceden görülen ${yuzdeSayi(yA)} ile ${yuzdeSayi(yB)} arasında, her 100 alarmdan doğru çıkan ${yuzdeSayi(iA)} ile ${yuzdeSayi(iB)} arasında olabilirdi (%95 güven aralığı).`,
                                 `The results rest on few big events. Had other years happened, floods seen in advance could be anywhere from ${yuzdeSayi(yA)} to ${yuzdeSayi(yB)} in 100, and alerts that came true from ${yuzdeSayi(iA)} to ${yuzdeSayi(iB)} in 100 (95% confidence interval).`)}
        ${temiz.length ? T(` Yöntem ${yilAraligi(secim)} yıllarına bakılarak seçildi; ${yilAraligi(temiz)} hiçbir seçimde kullanılmadı, en temiz sınav o yıllar.`,
                           ` The method was chosen by looking at ${yilAraligi(secim)}; ${yilAraligi(temiz)} played no part in any choice and is the cleanest test.`) : ''}</p>`;
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

  const olasilikHtml = () => denetimHtml() + egitimHtml() + dogrulukHtml() + dalgalarHtml() + sinirlarHtml();

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
        <li>${T(`<b>Tek yağış noktasının yanılgısı değil.</b> Büyük ilçelerde sağanak, yağışın okunduğu noktayı ıskalayabilir. Yağış ilçenin en yağışlı noktasından alınınca da ilçelerin sıralaması neredeyse aynı kalıyor (benzerlik ${sayi(gwr.cok_nokta_sira_korelasyonu, 2)}; 1 tamamen aynı demek).`,
                 `<b>Not an artefact of the single rain point.</b> In large districts a downpour can miss the point where rain is read. Taking the rain from the district's wettest point leaves the ranking almost unchanged (similarity ${sayi(gwr.cok_nokta_sira_korelasyonu, 2)}; 1 means identical).`)}</li>
        <li>${T(`<b>Uyarıyı iyileştirmiyor.</b> ${yillar} yıl yıl sınandığında ayrı modeller her 100 selin ${yuzdeSayi(s.gwr.duyarlilik)} tanesini önceden görüyor, tek model ${yuzdeSayi(s.global.duyarlilik)} tanesini; her 100 alarmdan doğru çıkan ${yuzdeSayi(s.gwr.kesinlik)} ve ${yuzdeSayi(s.global.kesinlik)}. Değeri, ilçeler arasındaki farkı göstermesinde.`,
                 `<b>It does not improve the alert.</b> Tested year by year (${yillar}), the separate models see ${yuzdeSayi(s.gwr.duyarlilik)} of every 100 floods in advance, the single model ${yuzdeSayi(s.global.duyarlilik)}; of every 100 alerts, ${yuzdeSayi(s.gwr.kesinlik)} and ${yuzdeSayi(s.global.kesinlik)} come true. Its value is in showing how districts differ.`)}</li>
        <li>${T('<b>Nedeni bu veriyle ayrılamıyor.</b> Havzanın biçimi ve toprağı yağışa farklı tepki veriyor olabilir; yağış arşivi de bazı yerlerde sağanağı daha çok yumuşatıyor olabilir.',
                 '<b>The cause cannot be separated with this data.</b> Catchment shape and soil may respond differently to rain, or the rain archive may smooth downpours more in some places.')}</li>
      </ul>`;
  }

  function gorunumCiz() {
    icerik.querySelector('[data-yer="gorunum"]').innerHTML = duyarlilikta() ? duyarlilikHtml() : olasilikHtml();
    secimCiz();
  }

  function ciz() {
    icerik.innerHTML = `
      <h2>${T('Erken uyarı: yarın hangi ilçede sel olabilir?', 'Early warning: which district may flood tomorrow?')}</h2>
      <p>${T(`Bu sekmedeki model, İzmir İtfaiyesi'nin ${yilAraligi(uyari.veri.yillar)} su baskını kayıtlarından öğrendi. Her ilçe için tek bir soruyu yanıtlıyor: <b>yarın bu ilçeye en az ${ilceCagri} su baskını çağrısı gelir mi?</b> Aşağıda buna kısaca "sel" diyoruz.`,
             `The model in this tab learned from İzmir Fire Department flood calls, ${yilAraligi(uyari.veri.yillar)}. For each district it answers one question: <b>will the district get at least ${ilceCagri} flood calls tomorrow?</b> Below, we call that a "flood".`)}</p>
      <div class="alan-baslik">${T('Harita ne göstersin?', 'What should the map show?')}</div>
      ${secimHtml('gorunum', [['olasilik', T('Sel olasılığı', 'Flood probability')], ['duyarlilik', T('Hangi yağış etkili?', 'Which rain matters?')]], durum.gorunum)}
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

  const olasilikLejanti = () => lejantBasligi(T('Sel olasılığı', 'Flood probability'),
    T(`bir ilçeye ≥ ${ilceCagri} su baskını çağrısı · ${durum.mm} mm, ${gecmisAdi()}`, `≥ ${ilceCagri} flood calls in a district · ${durum.mm} mm, ${gecmisAdi()}`))
    + [yuzdeAraligi(0, SINIR[0]), ...SINIR.slice(1).map((s, i) => yuzdeAraligi(SINIR[i], s)),
      T(`${yuzde(SINIR[SINIR.length - 1])} ve üstü`, `${yuzde(SINIR[SINIR.length - 1])} or more`)]
      .map((etiket, i) => lejantOgesi(RENK[i], etiket)).join('')
    + `<span class="lej"><i style="--renk:${RENK[2]};border:2.5px solid #1f2937;box-shadow:0 0 0 1px #e5e7eb"></i>${T(`kalın çerçeve: alarm (${yuzde(esik)} ve üstü)`, `thick outline: alert (${yuzde(esik)} or more)`)}</span>`;

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
      listeDinle(icerik, 'data-ilce', ilceyeGit);
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
