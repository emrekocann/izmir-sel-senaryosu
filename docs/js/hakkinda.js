// "Hakkında" penceresi: olay, model, doğrulama, eksik veri, yöntem. Metin
// index.html'de durur; doğrulama sayıları veriden doldurulur (data-doldur).
import { sayi } from './cekirdek/dil.js';
import { aralik } from './cekirdek/bicim.js';

export function hakkindaKur(pencere, { vitrin }) {
  /** data-doldur="ad" taşıyan öğelere güncel sayıları yazar (dil değişince yeniden). */
  function doldur() {
    const d = vitrin.dogrulama_senaryolari.map((s) => vitrin.dogrulama[s]);
    const ilk = d[0];
    const degerler = {
      'yer-sayisi': sayi(vitrin.yerler.length),
      'yakalanan': sayi(vitrin.yerler.filter((y) => y.yakalandi).length),
      'mahalle-puani': aralik(d.map((x) => x.mahalle_auc_yalniz_derinlik)),
      'cadde-puani': aralik(d.map((x) => x.cadde_auc)),
      'haber-cadde': `${aralik(d.map((x) => Math.round(x.cadde_kapali_oran.haber * x.cadde_sayisi.haber)), 0)} / ${ilk.cadde_sayisi.haber}`,
      'oteki-cadde': `%${aralik(d.map((x) => x.cadde_kapali_oran.oteki * 100), 0)}`,
      'mahalle-haber': sayi(ilk.mahalle_sayisi.haber),
      'mahalle-oteki': sayi(ilk.mahalle_sayisi.oteki),
      'cadde-oteki': sayi(ilk.cadde_sayisi.oteki),
      'ilce-sayisi': sayi(vitrin.merkez.ilceler.length),
    };
    pencere.querySelectorAll('[data-doldur]').forEach((oge) => {
      if (oge.dataset.doldur in degerler) oge.textContent = degerler[oge.dataset.doldur];
    });
  }

  pencere.querySelector('[data-kapat]').addEventListener('click', () => pencere.close());
  // pencerenin dışına (arka plana) tıklayınca kapanır
  pencere.addEventListener('click', (olay) => { if (olay.target === pencere) pencere.close(); });
  // içindekiler bağlantıları pencerenin içinde kaydırır
  pencere.addEventListener('click', (olay) => {
    const bag = olay.target.closest('a[href^="#hk-"]');
    if (!bag) return;
    olay.preventDefault();
    pencere.querySelector(bag.getAttribute('href'))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  doldur();

  return {
    doldur,
    /** Pencereyi açar; bolum verilirse o başlığa kaydırır (ör. "dogrulama"). */
    ac(bolum) {
      if (!pencere.open) pencere.showModal();
      const hedef = bolum && pencere.querySelector(`#hk-${bolum}`);
      if (hedef) hedef.scrollIntoView({ block: 'start' });
      else pencere.querySelector('.hk-govde').scrollTop = 0;
    },
  };
}
