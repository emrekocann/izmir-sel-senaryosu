// Metin biçimleme: senaryo adı, yer adları, yüzde, tarih, HTML kaçışı.
import { T, sayi, aktifDil } from './dil.js';

// TKGM yazımı (noktasız ı yok) → doğru yazım
const YAZIM = { 'Güzelyali': 'Güzelyalı', 'Karşiyaka': 'Karşıyaka', 'Bayrakli': 'Bayraklı', 'Kinik': 'Kınık',
  'Narlidere': 'Narlıdere', 'Bayindir': 'Bayındır', 'Torbali': 'Torbalı' };
export const yerAdi = (ad) => YAZIM[ad] || ad;

/** "100_6" → "100 mm / 6 saat" */
export function senaryoAdi(anahtar) {
  const [mm, saat] = anahtar.split('_');
  return `${mm} mm / ${saat} ${T('saat', 'h')}`;
}

/** "ÇETİN EMEÇ" → "Çetin Emeç" (Türkçe büyük/küçük harf kurallarıyla) */
export const baslik = (metin) => (metin || '').toLocaleLowerCase('tr')
  .replace(/(^|[\s/.(-])(\S)/g, (tumu, once, harf) => once + harf.toLocaleUpperCase('tr'));

/** "3 NO LU AFET VE ACİL DURUM TOPLANMA ALANI" → "3 No'lu Alan" */
export function alanAdi(alan) {
  const eslesme = (alan.adi || '').match(/^\s*(\d+)\s*NO\s*'?\s*LU/i);
  return eslesme ? T(`${eslesme[1]} No'lu Alan`, `Area No. ${eslesme[1]}`) : baslik(alan.adi);
}

export const mesafe = (metre) => (metre >= 1000 ? `${sayi(metre / 1000, 1)} km` : `${sayi(metre)} m`);

/** Oran (0–1) → yüzde, dile göre: tr "%36", en "36%". */
export const yuzde = (oran) => T(`%${sayi(oran * 100)}`, `${sayi(oran * 100)}%`);

/** "2025-10-23" → tr "23 Ekim 2025", en "23 October 2025". */
export const tarih = (gun) => new Date(`${gun}T12:00:00`).toLocaleDateString(aktifDil() === 'tr' ? 'tr-TR' : 'en-GB',
  { day: 'numeric', month: 'long', year: 'numeric' });

/** Veriden gelen metni HTML'e güvenle koymak için. */
export const kacis = (metin) => String(metin ?? '').replace(/[&<>"']/g,
  (k) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[k]));

/** Değer listesinin "en küçük–en büyük" aralığı (eşitse tek değer). */
export function aralik(degerler, kesir = 2) {
  const kucuk = Math.min(...degerler), buyuk = Math.max(...degerler);
  return kucuk === buyuk ? sayi(kucuk, kesir) : `${sayi(kucuk, kesir)}–${sayi(buyuk, kesir)}`;
}
