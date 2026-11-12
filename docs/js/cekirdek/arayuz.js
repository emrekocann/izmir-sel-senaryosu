// Küçük arayüz parçaları: seçim düğmeleri, lejant, sayı kutuları.
import { T } from './dil.js';
import { kacis } from './bicim.js';

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

export const sayiKutulari = (ogeler) => `<div class="sayilar">${ogeler.map(([deger, etiket]) =>
  `<div><b>${deger}</b><span>${etiket}</span></div>`).join('')}</div>`;

export const lejantOgesi = (renk, etiket, bicim = 'kare') =>
  `<span class="lej"><i class="${bicim}" style="--renk:${renk}"></i>${etiket}</span>`;

/** Su derinliği sınıflarının lejantı (vitrin.siniflar). */
export const suLejanti = (siniflar) => siniflar.map((sinif, i) =>
  lejantOgesi(sinif.renk, T(kacis(sinif.ad), SINIF_EN[i]))).join('');
