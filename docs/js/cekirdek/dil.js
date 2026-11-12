// Dil durumu ve çeviri yardımcıları. Sabit metinler HTML'de .tr / .en
// sınıflarıyla durur (CSS gizler); veriyle üretilen metinler T() kullanır.

let dil = 'tr';
const dinleyiciler = new Set();

/** Etkin dile göre metin seçer. */
export const T = (tr, en) => (dil === 'tr' ? tr : en);
export const aktifDil = () => dil;

/** Dil değişince çağrılacak işlev ekler. */
export const dilDegisince = (islev) => dinleyiciler.add(islev);

export function dilAyarla(yeni) {
  dil = yeni === 'en' ? 'en' : 'tr';
  document.documentElement.lang = dil;
  try { localStorage.setItem('dil', dil); } catch (hata) { /* gizli pencere: yok say */ }
  dinleyiciler.forEach((islev) => islev(dil));
}

/** İlk açılış: kayıtlı tercih, yoksa tarayıcı dili. */
export function ilkDil() {
  let kayitli = null;
  try { kayitli = localStorage.getItem('dil'); } catch (hata) { /* yok say */ }
  const tarayici = (navigator.language || 'tr').startsWith('tr') ? 'tr' : 'en';
  dilAyarla(kayitli || tarayici);
}

/** Sayıyı etkin dilin biçimiyle yazar (tr: 1.234,5 — en: 1,234.5). */
export const sayi = (deger, kesir = 0) =>
  Number(deger).toLocaleString(dil === 'tr' ? 'tr-TR' : 'en-US', { maximumFractionDigits: kesir });
