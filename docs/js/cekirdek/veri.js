// Önceden hesaplanmış veri dosyaları (hesap/vitrin_hazirla.py,
// hesap/toplanma_denetimi.py ve hesap/uyari_hazirla.py üretir). Sayfadaki bütün sayılar buradan gelir.

const DOSYALAR = { vitrin: 'veri/vitrin.json', denetim: 'veri/denetim.json', uyari: 'veri/uyari.json' };

/** JSON dosyası. 'no-cache': tarayıcı dosyayı saklar ama her açılışta
 *  sunucuya sorar; veri yeniden üretildiğinde eski kopya gösterilmez. */
export async function jsonOku(yol) {
  const yanit = await fetch(yol, { cache: 'no-cache' });
  if (!yanit.ok) throw new Error(`${yol}: ${yanit.status}`);
  return yanit.json();
}

/** { vitrin, denetim, uyari } — hepsi birlikte yüklenir. */
export async function veriYukle() {
  const adlar = Object.keys(DOSYALAR);
  const sonuclar = await Promise.all(adlar.map((ad) => jsonOku(DOSYALAR[ad])));
  return Object.fromEntries(adlar.map((ad, i) => [ad, sonuclar[i]]));
}

/** Uyarı sekmesinin canlı tahmin modeli: yalnız "Yarının tahmini" açılınca yüklenir. */
export const UYARI_MODELI = 'veri/uyari_model.json';
export const senaryoGorseli = (anahtar) => `veri/senaryo/${anahtar}.png`;
export const IL_SINIRI = 'veri/izmir_sinir.geojson';
export const ROTA_AGI = 'veri/rota/ag.json';
export const rotaSuyu = (anahtar) => `veri/rota/su_${anahtar}.json`;
export const DENETIM_CSV = 'veri/toplanma_denetimi.csv';
