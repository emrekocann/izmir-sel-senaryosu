// Yarının canlı sel tahmini. Sayfa açılınca ilçelerin yağış noktaları için
// saatlik hava tahmini (ECMWF, Open-Meteo) alınır; eğitimdeki yağış girdileri
// hesap/ilce_gun.py gunluk_yagis'in kurallarıyla hesaplanır ve dışa aktarılmış
// model (veri/uyari_model.json, hesap/uyari_hazirla.py) burada çalıştırılır.
// Sunucu, anahtar ya da zamanlanmış iş yok. Bu koşulun geçmişteki başarısı:
// hesap/guvenilirlik.py "ecmwf_canli". Tarayıcıya bağlı değil (Node'da sınanır).

const TAHMIN_URL = 'https://api.open-meteo.com/v1/forecast';
const GECMIS_GUN = 7;                  // girdilerin en uzun geçmişi: önceki 7 gün
const SAKLA_DK = 60;                   // aynı tarayıcıda bu süre içinde yeniden istenmez
const ZAMAN_ASIMI_MS = 20000;
const DEPO_ANAHTARI = 'canli-tahmin';

/** numpy.round(x, 1) ile aynı (tam yarıda çifte yuvarlar); eğitimde girdiler böyle yuvarlandı. */
export function yuvarla1(x) {
  const y = x * 10, r = Math.round(y);
  return (r - y === 0.5 && r % 2 !== 0 ? r - 1 : r) / 10;
}

/** 'YYYY-AA-GG' gününe n gün ekler. */
export function gunKaydir(gun, n) {
  const d = new Date(`${gun}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** İstanbul takvimine göre gün (YYYY-AA-GG); kaydir: eklenecek gün sayısı. */
export function istanbulGunu(an = new Date(), kaydir = 0) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(an).map((x) => [x.type, x.value]));
  return gunKaydir(`${p.year}-${p.month}-${p.day}`, kaydir);
}

/**
 * Saatlik yağıştan bir günün yağış girdileri (gunluk_yagis'in aynısı): günün
 * toplamı, en yoğun 1 ve 3 saati (3 saatlik pencere önceki günün son saatlerine
 * taşabilir), dün, önceki 3 ve 7 günün toplamı. Hedef gün ya da önceki 7 günden
 * birinin 24 saati tam değilse null (sınamada da böyle günler atıldı).
 * saatler: ['2026-11-20T00:00', …] saat saat sürekli; mm: aynı sırada, eksik null.
 */
export function yagisGirdileri(saatler, mm, hedef) {
  const gunler = new Map();            // gün → { toplam, max1, max3, saat }
  let once1 = 0, once2 = 0;            // önceki iki saatin yağışı (eksik saat sıfır)
  saatler.forEach((zaman, i) => {
    const gun = zaman.slice(0, 10), varMi = mm[i] !== null && mm[i] !== undefined, x = varMi ? mm[i] : 0;
    const g = gunler.get(gun) || { toplam: 0, max1: -Infinity, max3: -Infinity, saat: 0 };
    g.toplam += x;
    g.max1 = Math.max(g.max1, x);
    g.max3 = Math.max(g.max3, once2 + once1 + x);
    g.saat += varMi ? 1 : 0;
    gunler.set(gun, g);
    [once2, once1] = [once1, x];
  });
  const gunu = gunler.get(hedef);
  const onceki = Array.from({ length: GECMIS_GUN }, (_, k) => gunler.get(gunKaydir(hedef, -(k + 1))));
  if ([gunu, ...onceki].some((g) => !g || g.saat < 24)) return null;
  const topla = (n) => onceki.slice(0, n).reduce((a, g) => a + g.toplam, 0);
  return {
    yagis_mm: yuvarla1(gunu.toplam), yagis_max1s_mm: yuvarla1(gunu.max1), yagis_max3s_mm: yuvarla1(gunu.max3),
    yagis_dun_mm: yuvarla1(onceki[0].toplam), yagis_onceki3g_mm: yuvarla1(topla(3)), yagis_onceki7g_mm: yuvarla1(topla(7)),
  };
}

/** Dışa aktarılmış ağaç modeliyle olasılık (sklearn predict_proba ile aynı).
 *  Ağaç düğümü: iç [girdi sırası, eşik, sol, sağ] (girdi ≤ eşik → sol), yaprak [değer]. */
export function olasilik(model, girdi) {
  let ham = model.baslangic;
  for (const agac of model.agaclar) {
    let d = agac[0];
    while (d.length === 4) d = agac[girdi[d[0]] <= d[1] ? d[2] : d[3]];
    ham += d[0];
  }
  return 1 / (1 + Math.exp(-ham));
}

/** Bir ilçenin yağış girdileri + sabit girdileri → modelin girdi sırasıyla dizi. */
export const girdiDizisi = (model, yagis, ilce) => model.girdiler.map((k) => (k in yagis ? yagis[k] : ilce[k]));

/** Open-Meteo yanıtı (nokta başına bir öğe, model.ilceler sırasıyla) → ilçe adı → yağış girdileri ya da null. */
export function yanittanGirdiler(model, yanit, hedef) {
  const adlar = Object.keys(model.ilceler);
  if (!Array.isArray(yanit) || yanit.length !== adlar.length) throw new Error('beklenmeyen yanıt');
  return Object.fromEntries(adlar.map((ad, i) => [ad, yagisGirdileri(yanit[i].hourly.time, yanit[i].hourly.precipitation, hedef)]));
}

/** İlçe adı → yağış girdileri ⇒ { ilçe: { p, alarm, yagis } } (girdisi olmayan ilçe: null). */
export function tahminler(model, girdiler, esik) {
  return Object.fromEntries(Object.entries(girdiler).map(([ad, yagis]) => {
    if (!yagis) return [ad, null];
    const p = olasilik(model, girdiDizisi(model, yagis, model.ilceler[ad]));
    return [ad, { p, alarm: p >= esik, yagis }];
  }));
}

/** Bütün ilçe noktaları için tek istek: saatlik yağış, önceki 7 gün + bugün + yarın, İstanbul saati. */
export function tahminAdresi(model) {
  const noktalar = Object.values(model.ilceler);
  const q = new URLSearchParams({
    latitude: noktalar.map((n) => n.lat.toFixed(4)).join(','),
    longitude: noktalar.map((n) => n.lon.toFixed(4)).join(','),
    hourly: 'precipitation', models: model.tahmin_modeli, timezone: 'Europe/Istanbul',
    past_days: String(GECMIS_GUN), forecast_days: '2',
  });
  return `${TAHMIN_URL}?${q}`;
}

function depodan(hedef, model, simdi) {
  try {
    const k = JSON.parse(localStorage.getItem(DEPO_ANAHTARI));
    const taze = k && k.hedef === hedef && k.tahmin_modeli === model.tahmin_modeli
      && simdi - new Date(k.alindi) < SAKLA_DK * 60000;
    return taze ? k : null;
  } catch (hata) { return null; }   // gizli pencere, Node ya da bozuk kayıt
}

/**
 * Yarının yağış girdileri: { hedef: 'YYYY-AA-GG', alindi: ISO zaman, girdiler: { ilçe: {...} | null } }.
 * Aynı tarayıcıda SAKLA_DK boyunca saklanır (yeniden açılışta servis yeniden çağrılmaz).
 */
export async function yarininGirdileri(model, { simdi = new Date(), getir = fetch } = {}) {
  const hedef = istanbulGunu(simdi, 1);
  const kayitli = depodan(hedef, model, simdi);
  if (kayitli) return kayitli;
  const durdur = new AbortController();
  const zamanlayici = setTimeout(() => durdur.abort(), ZAMAN_ASIMI_MS);
  let yanit;
  try {
    yanit = await getir(tahminAdresi(model), { signal: durdur.signal });
  } finally {
    clearTimeout(zamanlayici);
  }
  const govde = await yanit.json().catch(() => null);
  if (!yanit.ok) throw new Error(govde?.reason || `HTTP ${yanit.status}`);
  const sonuc = { hedef, alindi: simdi.toISOString(), tahmin_modeli: model.tahmin_modeli,
    girdiler: yanittanGirdiler(model, govde, hedef) };
  try { localStorage.setItem(DEPO_ANAHTARI, JSON.stringify(sonuc)); } catch (hata) { /* yer yok: yok say */ }
  return sonuc;
}
