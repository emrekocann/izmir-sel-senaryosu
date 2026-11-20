// Küçük arayüz parçaları: seçim düğmeleri, tıklanır listeler, lejant, sayı kutuları.
import { T } from './dil.js';
import { kacis, senaryoAdi, senaryoCoz, sureAdi } from './bicim.js';

const SINIF_EN = ['Shallow (10–30 cm)', 'Knee-deep (30 cm–1 m)', 'Deep (1–2 m)', 'Very deep (2 m+)',
  'Flat plain: water arrives, depth unknown'];

/** Düğme grubu HTML'i. Tıklama, kapsayıcıda data-secim ile yakalanır. */
export function secimHtml(grup, secenekler, secili) {
  return `<span class="secim" role="group">${secenekler.map(([deger, etiket]) =>
    `<button type="button" data-secim="${kacis(grup)}" data-deger="${kacis(deger)}"
       class="${String(deger) === String(secili) ? 'secili' : ''}" aria-pressed="${String(deger) === String(secili)}">${kacis(etiket)}</button>`).join('')}</span>`;
}

/** Kapsayıcıdaki data-secim düğmelerine tıklamayı dinler: islev(grup, değer). */
export function secimDinle(kapsayici, islev) {
  kapsayici.addEventListener('click', (olay) => {
    const dugme = olay.target.closest('[data-secim]');
    if (dugme && kapsayici.contains(dugme)) islev(dugme.dataset.secim, dugme.dataset.deger);
  });
}

/** Yağış süresi düğmeleri (senaryo ve rota sekmeleri). */
export const sureSecimi = (sureler, saat) => secimHtml('saat', sureler.map((s) => [s, sureAdi(s)]), saat);

/** Hazır senaryoların düğmeleri ("100 mm / 6 saat"). */
export const senaryoSecimi = (grup, senaryolar, secili) =>
  secimHtml(grup, senaryolar.map((s) => [s, senaryoAdi(s)]), secili);

/** Senaryo ve rota sekmelerinin yağış seçimi: süre düğmesi durum.saat'i, hazır
 * senaryo düğmesi durum.sira ile durum.saat'i değiştirir; ardından sonra() çağrılır.
 * bosluk: kaydırıcının başındaki "yağış yok" adımı (rota sekmesinde 1). */
export function yagisSecimiDinle(kapsayici, { yagisMm, durum, kaydirici, bosluk = 0, sonra }) {
  secimDinle(kapsayici, (grup, deger) => {
    if (grup === 'saat') durum.saat = Number(deger);
    if (grup === 'olay') {
      const [mm, saat] = senaryoCoz(deger);
      durum.sira = yagisMm.indexOf(mm) + bosluk;
      durum.saat = saat;
      kapsayici.querySelector(kaydirici).value = durum.sira;
    }
    sonra();
  });
}

/** Listede `ozellik` taşıyan öğeye tıklanınca ya da Enter'a basılınca islev(özelliğin değeri). */
export function listeDinle(kapsayici, ozellik, islev) {
  const sec = (olay) => {
    const oge = olay.target.closest(`[${ozellik}]`);
    if (oge && (olay.type === 'click' || olay.key === 'Enter')) islev(oge.getAttribute(ozellik));
  };
  kapsayici.addEventListener('click', sec);
  kapsayici.addEventListener('keydown', sec);
}

export const sayiKutulari = (ogeler) => `<div class="sayilar">${ogeler.map(([deger, etiket]) =>
  `<div><b>${deger}</b><span>${etiket}</span></div>`).join('')}</div>`;

export const lejantOgesi = (renk, etiket, bicim = 'kare') =>
  `<span class="lej"><i class="${bicim}" style="--renk:${renk}"></i>${etiket}</span>`;

/** Su derinliği sınıflarının lejantı (vitrin.siniflar). */
export const suLejanti = (siniflar) => siniflar.map((sinif, i) =>
  lejantOgesi(sinif.renk, T(kacis(sinif.ad), SINIF_EN[i]))).join('');
