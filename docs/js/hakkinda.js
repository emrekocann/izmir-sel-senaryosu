// "Hakkında" penceresi: olay, senaryo modeli, doğrulama, erken uyarı, eksik
// veri, yöntem. Metin index.html'de durur; doğrulama ve erken uyarı sayıları
// veriden doldurulur (data-doldur).
import { sayi } from './cekirdek/dil.js';
import { aralik, yerAdi, yuzde, yuzdeIsareti, yilAraligi, tarih } from './cekirdek/bicim.js';
import { enDuyarlilar } from './sekmeler/uyari.js';

/** Erken uyarı bölümünün sayıları (uyari.json; Uyarı sekmesiyle aynı kaynak). */
function uyariDegerleri(uyari) {
  const s = uyari.sinama, tum = s.tum_yillar, og = s.oglen_tahmin, o = uyari.ornek, gwr = uyari.gwr;
  const ilkUc = (etken) => enDuyarlilar(gwr, etken).slice(0, 3).map(yerAdi).join(', ');
  return {
    'uyari-yillari': yilAraligi(uyari.veri.yillar),
    'ilce-cagri': sayi(uyari.olay_tanimi.ilce_cagri),
    'il-cagri': sayi(uyari.olay_tanimi.il_cagri),
    'sinama-yillari': yilAraligi(tum.yillar),
    'atak': `${tum.atak_ilk_gun}\u00a0/\u00a0${tum.atak}`,
    'atak-oglen': `${og.atak_ilk_gun}\u00a0/\u00a0${og.atak}`,
    'oglen-yillari': yilAraligi(og.yillar),
    'yakalama': yuzde(tum.duyarlilik),
    'isabet': yuzde(tum.kesinlik),
    'yakalama-oglen': yuzde(og.duyarlilik),
    'yakalama-tahminsiz': yuzde(s.tahminsiz.duyarlilik),
    'ornek-yer': `${yerAdi(o.ilce)}, ${tarih(o.gun)}`,
    'ornek-saat': sayi(o.haber_saat, 1),
    'ornek-haber': `~${sayi(o.haber_mm)} mm`,
    'ornek-arsiv': `${sayi(o.arsiv_mm, 1)} mm`,
    'gwr-gunun': ilkUc('gunun_yagisi'),
    'gwr-hafta': ilkUc('onceki_hafta'),
    'gwr-kanitsiz': sayi(Object.values(gwr.ilceler).filter((i) => !i.onceki_hafta.kanitli).length),
  };
}

export function hakkindaKur(pencere, { vitrin, uyari }) {
  /** data-doldur="ad" taşıyan öğelere güncel sayıları yazar (dil değişince yeniden). */
  function doldur() {
    const d = vitrin.dogrulama_senaryolari.map((s) => vitrin.dogrulama[s]);
    const ilk = d[0];
    const otekiCadde = aralik(d.map((x) => x.cadde_kapali_oran.oteki * 100), 0);
    const degerler = {
      ...uyariDegerleri(uyari),
      'yer-sayisi': sayi(vitrin.yerler.length),
      'yakalanan': sayi(vitrin.yerler.filter((y) => y.yakalandi).length),
      'mahalle-puani': aralik(d.map((x) => x.mahalle_auc_yalniz_derinlik)),
      'cadde-puani': aralik(d.map((x) => x.cadde_auc)),
      'haber-cadde': `${aralik(d.map((x) => Math.round(x.cadde_kapali_oran.haber * x.cadde_sayisi.haber)), 0)} / ${ilk.cadde_sayisi.haber}`,
      'oteki-cadde': yuzdeIsareti(otekiCadde),
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
