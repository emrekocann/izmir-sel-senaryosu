// Önceden hesaplanmış veri dosyaları (hesap/vitrin_hazirla.py ve
// hesap/toplanma_denetimi.py üretir). Sayfadaki bütün sayılar buradan gelir.

const DOSYALAR = { vitrin: 'veri/vitrin.json', denetim: 'veri/denetim.json' };

async function oku(yol) {
  // 'no-cache': tarayıcı dosyayı saklar ama her açılışta sunucuya sorar;
  // veri yeniden üretildiğinde eski kopya gösterilmez
  const yanit = await fetch(yol, { cache: 'no-cache' });
  if (!yanit.ok) throw new Error(`${yol}: ${yanit.status}`);
  return yanit.json();
}

/** { vitrin, denetim } — ikisi birlikte yüklenir. */
export async function veriYukle() {
  const adlar = Object.keys(DOSYALAR);
  const sonuclar = await Promise.all(adlar.map((ad) => oku(DOSYALAR[ad])));
  return Object.fromEntries(adlar.map((ad, i) => [ad, sonuclar[i]]));
}

export const senaryoGorseli = (anahtar) => `veri/senaryo/${anahtar}.png`;
export const IL_SINIRI = 'veri/izmir_sinir.geojson';
export const ROTA_AGI = 'veri/rota/ag.json';
export const rotaSuyu = (anahtar) => `veri/rota/su_${anahtar}.json`;
export const DENETIM_CSV = 'veri/toplanma_denetimi.csv';
