// Sekme: yağış senaryoları. "X mm yağış Y saatte düşerse nereyi su basar?"
import { T, sayi } from '../cekirdek/dil.js';
import { senaryoAnahtari, senaryoCoz } from '../cekirdek/bicim.js';
import { secimDinle, sayiKutulari, senaryoSecimi, sureSecimi, suLejanti } from '../cekirdek/arayuz.js';

export function senaryoSekmesi({ vitrin, harita }) {
  // açılış: 2 Şubat 2021'e en yakın kısa senaryo
  const [ilkMm, ilkSaat] = senaryoCoz(vitrin.olay_senaryolari[0]);
  const durum = { sira: Math.max(0, vitrin.yagis_mm.indexOf(ilkMm)), saat: ilkSaat };
  let icerik = null;

  const anahtar = () => senaryoAnahtari(vitrin.yagis_mm[durum.sira], durum.saat);

  function ozet() {
    const o = vitrin.senaryolar[anahtar()];
    return sayiKutulari([
      [`${sayi(o.su_alan_km2['0.3'])} km²`, T("30 cm'den derin su", 'water deeper than 30 cm')],
      [`${sayi(o.yol_kapali_km)} km`, T('araçla geçilemez yol', 'roads impassable by car')],
      [`${sayi(o.toplanma_etkilenen_sayi)} / ${sayi(o.toplanma_toplam)}`, T('su altında toplanma alanı', 'assembly areas under water')],
      [`${sayi(o.belirsiz_km2)} km²`, T('düz ova: derinlik belirsiz', 'flat plain: depth unknown')],
      [o.alt_gecit_dolu ? T('dolu', 'flooded') : T('kuru', 'dry'), T('alt geçitler', 'underpasses')],
    ]);
  }

  /** Kaydırıcı sürüklenirken yalnız değişen kısımlar yenilenir. */
  function guncelle() {
    harita.suGoster(anahtar());
    icerik.querySelector('[data-yer="yagis"]').textContent = `${vitrin.yagis_mm[durum.sira]} mm`;
    icerik.querySelector('[data-yer="sure"]').innerHTML = sureSecimi(vitrin.sure_sa, durum.saat);
    icerik.querySelector('[data-yer="olay"]').innerHTML = senaryoSecimi('olay', vitrin.olay_senaryolari, anahtar());
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
      <div data-yer="ozet"></div>
      <p class="kucuk">${T('Sayılar il geneli içindir; senaryo yağışı ilin tamamına aynı anda düşer. Gri alanlar düz ovalardır: yükseklik verisi burada suyun yönünü çözemez, model derinlik vermez.',
                           'Figures are province-wide; scenario rain falls on the whole province at once. Grey areas are flat plains where the elevation data cannot resolve flow direction, so the model gives no depth.')}</p>
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
      secimDinle(icerik, (grup, deger) => {
        if (grup === 'saat') durum.saat = Number(deger);
        if (grup === 'olay') {
          const [mm, saat] = senaryoCoz(deger);
          durum.sira = vitrin.yagis_mm.indexOf(mm);
          durum.saat = saat;
          icerik.querySelector('#sen-kaydir').value = durum.sira;
        }
        guncelle();
      });
      ciz();
      harita.ilGorunumu();
    },
    gizle() { harita.suGoster(null); },
    ciz,
    lejant: () => suLejanti(vitrin.siniflar),
  };
}
