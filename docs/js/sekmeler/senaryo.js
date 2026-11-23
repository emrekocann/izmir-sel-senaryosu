// Sekme: yağış senaryoları. "X mm yağış Y saatte düşerse nereyi su basar?"
import { T, sayi } from '../cekirdek/dil.js';
import { cm, senaryoAnahtari, senaryoCoz, siklik, sureAdi } from '../cekirdek/bicim.js';
import { yagisSecimiDinle, sayiKutulari, senaryoSecimi, sureSecimi, suLejanti } from '../cekirdek/arayuz.js';

export function senaryoSekmesi({ vitrin, risk, harita }) {
  // açılış: 2 Şubat 2021'e en yakın kısa senaryo
  const [ilkMm, ilkSaat] = senaryoCoz(vitrin.olay_senaryolari[0]);
  const durum = { sira: Math.max(0, vitrin.yagis_mm.indexOf(ilkMm)), saat: ilkSaat };
  let icerik = null;

  const anahtar = () => senaryoAnahtari(vitrin.yagis_mm[durum.sira], durum.saat);

  /** Bu yağış ne sıklıkla düşer? 24 saatten kısa sürede düşmesi, 24 saatte düşmesinden seyrektir. */
  function siklikMetni() {
    const r = risk.senaryolar[anahtar()], mm = vitrin.yagis_mm[durum.sira];
    if (!r.alt_sinir) return T(`<b>Ne sıklıkla:</b> ${mm} mm 24 saatte ${siklik(r.donus_yil)} düşer.`,
                               `<b>How often:</b> ${mm} mm within 24 hours falls ${siklik(r.donus_yil)}.`);
    return T(`<b>Ne sıklıkla:</b> ${mm} mm 24 saatte bile ${siklik(r.donus_yil)} düşer; ${sureAdi(durum.saat)} içinde düşmesi bundan da seyrektir.`,
             `<b>How often:</b> even over 24 hours ${mm} mm falls ${siklik(r.donus_yil)}; within ${sureAdi(durum.saat)} it is rarer still.`);
  }

  function ozet() {
    const o = vitrin.senaryolar[anahtar()], r = risk.senaryolar[anahtar()];
    const esik = vitrin.esikler.yol_kapali_m, kapali = cm(esik);
    return sayiKutulari([
      [sayi(r.nufus), T(`kişi ${kapali}'den derin suyun geldiği yerde oturuyor`, `people live where water is deeper than ${kapali}`)],
      [`${sayi(r.hastane)} / ${sayi(r.okul)}`, T(`hastane / okul ${kapali}'den derin suda`, `hospitals / schools in water deeper than ${kapali}`)],
      [`${sayi(o.su_alan_km2[String(esik)])} km²`, T(`${kapali}'den derin su`, `water deeper than ${kapali}`)],
      [`${sayi(o.yol_kapali_km)} km`, T('araçla geçilemez yol', 'roads impassable by car')],
      [`${sayi(o.toplanma_etkilenen_sayi)} / ${sayi(o.toplanma_toplam)}`, T('su altında toplanma alanı', 'assembly areas under water')],
      [`${sayi(o.belirsiz_km2)} km²`, T(`düz ova: derinlik belirsiz (${sayi(r.nufus_belirsiz)} kişi)`, `flat plain: depth unknown (${sayi(r.nufus_belirsiz)} people)`)],
      [o.alt_gecit_dolu ? T('dolu', 'flooded') : T('kuru', 'dry'), T('alt geçitler', 'underpasses')],
    ]);
  }

  /** Kaydırıcı sürüklenirken yalnız değişen kısımlar yenilenir. */
  function guncelle() {
    harita.suGoster(anahtar());
    icerik.querySelector('[data-yer="yagis"]').textContent = `${vitrin.yagis_mm[durum.sira]} mm`;
    icerik.querySelector('[data-yer="sure"]').innerHTML = sureSecimi(vitrin.sure_sa, durum.saat);
    icerik.querySelector('[data-yer="olay"]').innerHTML = senaryoSecimi('olay', vitrin.olay_senaryolari, anahtar());
    icerik.querySelector('[data-yer="siklik"]').innerHTML = siklikMetni();
    icerik.querySelector('[data-yer="ozet"]').innerHTML = ozet();
  }

  function ciz() {
    icerik.innerHTML = `
      <h2>${T('Yağış senaryoları', 'Rainfall scenarios')}</h2>
      <p>${T('Bu kadar yağmur bu kadar sürede yağarsa model nereyi, ne derinlikte su altında gösteriyor?',
             'If this much rain falls in this much time, where and how deep does the model put the water?')}</p>
      <label class="alan-baslik" for="sen-kaydir">${T('Yağış', 'Rainfall')}: <b data-yer="yagis"></b></label>
      <input type="range" id="sen-kaydir" min="0" max="${vitrin.yagis_mm.length - 1}" step="1" value="${durum.sira}">
      <div class="olcek"><span>${vitrin.yagis_mm[0]}</span><span>${vitrin.yagis_mm[vitrin.yagis_mm.length - 1]} mm</span></div>
      <div class="alan-baslik">${T('Kaç saatte düşüyor?', 'Over how many hours?')}</div>
      <div data-yer="sure"></div>
      <div class="alan-baslik">${T("2 Şubat 2021'e yakın yağışlar", 'Closest to 2 February 2021')}</div>
      <div data-yer="olay"></div>
      <p class="siklik" data-yer="siklik"></p>
      <div data-yer="ozet"></div>
      <p class="kucuk">${T('Sayılar il geneli içindir; senaryo yağışı ilin tamamına aynı anda düşer, bu yüzden gerçekte aynı anda etkilenen kişi daha azdır. Gri alanlar düz ovalardır: yükseklik verisi burada suyun yönünü çözemez, model derinlik vermez.',
                           'Figures are province-wide; scenario rain falls on the whole province at once, so in reality fewer people are hit at the same time. Grey areas are flat plains where the elevation data cannot resolve flow direction, so the model gives no depth.')}</p>
      <p class="kucuk">${T(`Sıklık: ${risk.tekerrur.istasyon} istasyonunun ${risk.tekerrur.yillar.length} yıllık günlük yağış kaydı; 2 Şubat 2021'deki yağış (istasyonda ${sayi(risk.tekerrur.olay_2021_mm)} mm) ${siklik(risk.tekerrur.olay_2021_yil)} görülür. Nüfus: TÜİK 2023 mahalle nüfusu, yapılaşmış alana dağıtılmış. Hastane ve okul: OpenStreetMap. Kapsam yalnız dere taşkınıdır: sokakta biriken yağmur suyu ve denizden gelen su yoktur.`,
                           `Frequency: ${risk.tekerrur.yillar.length} years of daily rainfall at ${risk.tekerrur.istasyon}; the 2 February 2021 rain (${sayi(risk.tekerrur.olay_2021_mm)} mm at the station) comes ${siklik(risk.tekerrur.olay_2021_yil)}. Population: TÜİK 2023 neighbourhood counts spread over built-up land. Hospitals and schools: OpenStreetMap. Covers river flooding only: no street ponding of rainwater and no water from the sea.`)}</p>
      <div class="kutu not">${T('Bu harita bir tahmin değil, "olursa ne olur" hesabıdır. Model, 2021 selinde su basan mahalleleri ayırt edemedi; sonucu <b>2021 seli</b> sekmesinde.',
                                 'This map is a what-if calculation, not a forecast. The model could not single out the neighbourhoods flooded in 2021; see the <b>2021 flood</b> tab.')}</div>`;
    icerik.querySelector('#sen-kaydir').addEventListener('input', (olay) => {
      durum.sira = Number(olay.target.value);
      guncelle();
    });
    guncelle();
  }

  return {
    id: 'senaryo',
    baslik: () => T('Senaryolar', 'Scenarios'),
    goster(yeniIcerik) {
      icerik = yeniIcerik;
      yagisSecimiDinle(icerik, { yagisMm: vitrin.yagis_mm, durum, kaydirici: '#sen-kaydir', sonra: guncelle });
      ciz();
      harita.ilGorunumu();
    },
    gizle() { harita.suGoster(null); },
    ciz,
    lejant: () => suLejanti(vitrin.siniflar),
  };
}
