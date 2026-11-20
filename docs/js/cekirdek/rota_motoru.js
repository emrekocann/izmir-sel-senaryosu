// Tarayıcıda rota: merkez ilçelerin araç yol ağı üzerinde Dijkstra.
// Ağ ve senaryo suyu hesap/rota_agi_hazirla.py'nin yazdığı dosyalardan gelir;
// maliyet sunucudaki pgRouting sorgusunun senaryo kısmıyla aynıdır:
//   uzunluk × (1 + eğim × k)  (dosyada hazır: kenar_maliyet)
//   + ıslak kenarın ek maliyeti (sığ su / düz ova ×5, 30 cm+ su +100 km)
//   + senaryoda alt geçitler doluysa alt geçit kenarı başına +100 km
// Bu modül Leaflet'e dokunmaz (node ile de sınanır: tests/test_rota_motoru.py).

/** Farkla yazılmış tamsayı dizisini çözer. */
function farkCoz(dizi) {
  const out = new Float64Array(dizi.length);
  let t = 0;
  for (let i = 0; i < dizi.length; i++) { t += dizi[i]; out[i] = t; }
  return out;
}

/** Küçük ikili yığın (öncelik kuyruğu): [maliyet, düğüm] çiftleri. */
class Yigin {
  constructor() { this.m = []; this.d = []; }
  get bos() { return this.m.length === 0; }
  ekle(maliyet, dugum) {
    const m = this.m, d = this.d;
    let i = m.length;
    m.push(maliyet); d.push(dugum);
    while (i > 0) {
      const u = (i - 1) >> 1;
      if (m[u] <= maliyet) break;
      m[i] = m[u]; d[i] = d[u]; i = u;
    }
    m[i] = maliyet; d[i] = dugum;
  }
  al() {
    const m = this.m, d = this.d, ustM = m[0], ustD = d[0];
    const sonM = m.pop(), sonD = d.pop(), n = m.length;
    if (n > 0) {
      let i = 0;
      for (;;) {
        let c = 2 * i + 1;
        if (c >= n) break;
        if (c + 1 < n && m[c + 1] < m[c]) c++;
        if (m[c] >= sonM) break;
        m[i] = m[c]; d[i] = d[c]; i = c;
      }
      m[i] = sonM; d[i] = sonD;
    }
    return [ustM, ustD];
  }
}

/** ag.json → ağ nesnesi. */
export function agKur(ham) {
  const olcek = ham.olcek;
  const x = farkCoz(ham.dugum_x), y = farkCoz(ham.dugum_y);
  const n = x.length, e = ham.kenar_a.length;
  const lon = new Float64Array(n), lat = new Float64Array(n);
  for (let i = 0; i < n; i++) { lon[i] = x[i] / olcek; lat[i] = y[i] / olcek; }
  const a = Int32Array.from(ham.kenar_a), b = Int32Array.from(ham.kenar_b);
  const metre = Float64Array.from(ham.kenar_m), maliyet = Float64Array.from(ham.kenar_maliyet);

  // komşuluk (CSR): düğüm → kenarlar
  const derece = new Int32Array(n + 1);
  for (let k = 0; k < e; k++) { derece[a[k] + 1]++; derece[b[k] + 1]++; }
  for (let i = 0; i < n; i++) derece[i + 1] += derece[i];
  const komsuKenar = new Int32Array(2 * e), dolu = derece.slice(0, n);
  for (let k = 0; k < e; k++) { komsuKenar[dolu[a[k]]++] = k; komsuKenar[dolu[b[k]]++] = k; }

  // kenar ara noktaları: ic dizisinde başlangıç (nokta çifti sırası)
  const icBas = new Int32Array(e + 1);
  for (let k = 0; k < e; k++) icBas[k + 1] = icBas[k] + ham.ic_sayi[k];
  const ic = Int32Array.from(ham.ic);

  const otoyol = new Uint8Array(e);
  for (const k of farkCoz(ham.otoyol)) otoyol[k] = 1;
  const altGecit = new Uint16Array(e);
  for (const [k, sayi] of Object.entries(ham.alt_gecit)) altGecit[Number(k)] = sayi;

  // bir düğüme bağlanılabilir mi: otoyol olmayan en az bir kenarı var
  const baglanir = new Uint8Array(n);
  for (let k = 0; k < e; k++) if (!otoyol[k]) { baglanir[a[k]] = 1; baglanir[b[k]] = 1; }

  // toplanma alanları: düğüm → alanlar
  const alanlar = ham.alanlar.map(([dugum, lo, la, id, adi, ilce, mahalle]) => ({ dugum, lon: lo, lat: la, id, adi, ilce, mahalle }));
  const dugumAlan = new Map();
  for (const alan of alanlar) {
    if (!dugumAlan.has(alan.dugum)) dugumAlan.set(alan.dugum, []);
    dugumAlan.get(alan.dugum).push(alan);
  }

  // en yakın düğüm için ızgara (yalnız bağlanılabilir düğümler)
  const HUCRE = 0.005;
  const izgara = new Map();
  const hucre = (lo, la) => `${Math.floor(lo / HUCRE)},${Math.floor(la / HUCRE)}`;
  for (let i = 0; i < n; i++) {
    if (!baglanir[i]) continue;
    const h = hucre(lon[i], lat[i]);
    if (!izgara.has(h)) izgara.set(h, []);
    izgara.get(h).push(i);
  }

  return { olcek, n, e, lon, lat, a, b, metre, maliyet, derece, komsuKenar, icBas, ic, otoyol, altGecit,
    baglanir, alanlar, dugumAlan, izgara, HUCRE, kapsam: ham.kapsam, ilceler: ham.ilceler, ayar: ham.maliyet };
}

/** Yaklaşık metre (enlem düzeltmeli eşdikdörtgen). */
export function metreArasi(lon1, lat1, lon2, lat2) {
  const k = Math.cos(((lat1 + lat2) / 2) * Math.PI / 180);
  return Math.hypot((lon2 - lon1) * k, lat2 - lat1) * 111_320;
}

/** Noktaya en yakın bağlanılabilir düğüm: { dugum, metre } ya da null. */
export function enYakinDugum(ag, lon, lat, enCokMetre = 1500) {
  const cx = Math.floor(lon / ag.HUCRE), cy = Math.floor(lat / ag.HUCRE);
  const halka = Math.ceil(enCokMetre / 111_320 / ag.HUCRE / Math.cos(lat * Math.PI / 180)) + 1;
  let enIyi = -1, enKisa = Infinity;
  for (let r = 0; r <= halka; r++) {
    for (let dx = -r; dx <= r; dx++) {
      for (let dy = -r; dy <= r; dy++) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue;
        for (const i of ag.izgara.get(`${cx + dx},${cy + dy}`) || []) {
          const m = metreArasi(lon, lat, ag.lon[i], ag.lat[i]);
          if (m < enKisa) { enKisa = m; enIyi = i; }
        }
      }
    }
    // bulunan düğüm bu halkanın içinde kalan kesin mesafedeyse daha ileri bakmaya gerek yok
    if (enIyi >= 0 && enKisa <= r * ag.HUCRE * 111_320 * Math.cos(lat * Math.PI / 180)) break;
  }
  return enIyi >= 0 && enKisa <= enCokMetre ? { dugum: enIyi, metre: enKisa } : null;
}

/** su_<senaryo>.json → senaryo suyu (kenar başına ek maliyet ve derinlik). */
export function suKur(ag, ham) {
  const ek = new Float64Array(ag.e), derinDm = new Uint8Array(ag.e);
  const derinParca = new Uint16Array(ag.e), sigParca = new Uint16Array(ag.e);
  const kenar = farkCoz(ham.kenar);
  for (let i = 0; i < kenar.length; i++) {
    const k = kenar[i];
    ek[k] = ham.ek[i]; derinDm[k] = ham.derin_dm[i];
    derinParca[k] = ham.derin_parca[i]; sigParca[k] = ham.sig_parca[i];
  }
  return { ek, derinDm, derinParca, sigParca, kapaliAlan: new Set(ham.kapali_alan) };
}

/**
 * Başlangıç düğümünden en düşük maliyetle ulaşılan açık toplanma alanına rota.
 * su: suKur sonucu ya da null (yağış yok). altGecitDolu: senaryoda alt
 * geçitler dolu mu. Dönüş: { alan, kenarlar, dugumler, maliyet } ya da null.
 */
export function rotaBul(ag, baslangic, su = null, altGecitDolu = false) {
  const hedef = new Map();                         // düğüm → açık alan
  for (const [dugum, liste] of ag.dugumAlan) {
    const acik = liste.find((alan) => !su || !su.kapaliAlan.has(alan.id));
    if (acik) hedef.set(dugum, acik);
  }
  if (!hedef.size) return null;
  const kapaliEk = ag.ayar.kapali_ek;
  const uzaklik = new Float64Array(ag.n).fill(Infinity);
  const onceki = new Int32Array(ag.n).fill(-1);
  const bitti = new Uint8Array(ag.n);
  const yigin = new Yigin();
  uzaklik[baslangic] = 0;
  yigin.ekle(0, baslangic);
  let varis = -1;
  while (!yigin.bos) {
    const [d, u] = yigin.al();
    if (bitti[u]) continue;
    bitti[u] = 1;
    if (hedef.has(u)) { varis = u; break; }
    for (let j = ag.derece[u]; j < ag.derece[u + 1]; j++) {
      const k = ag.komsuKenar[j];
      const v = ag.a[k] === u ? ag.b[k] : ag.a[k];
      if (bitti[v]) continue;
      let c = ag.maliyet[k];
      if (su) c += su.ek[k];
      if (altGecitDolu) c += ag.altGecit[k] * kapaliEk;
      const yeni = d + c;
      if (yeni < uzaklik[v]) { uzaklik[v] = yeni; onceki[v] = k; yigin.ekle(yeni, v); }
    }
  }
  if (varis < 0) return null;
  const kenarlar = [], dugumler = [varis];
  for (let v = varis; v !== baslangic;) {
    const k = onceki[v];
    kenarlar.push(k);
    v = ag.a[k] === v ? ag.b[k] : ag.a[k];
    dugumler.push(v);
  }
  kenarlar.reverse(); dugumler.reverse();
  return { alan: hedef.get(varis), kenarlar, dugumler, maliyet: uzaklik[varis] };
}

/** Kenarın [boylam, enlem] noktaları; ters=true ise b'den a'ya. */
function kenarCizgisi(ag, k, ters = false) {
  const nokta = [[ag.lon[ag.a[k]], ag.lat[ag.a[k]]]];
  let x = Math.round(ag.lon[ag.a[k]] * ag.olcek), y = Math.round(ag.lat[ag.a[k]] * ag.olcek);
  for (let p = ag.icBas[k]; p < ag.icBas[k + 1]; p++) {
    x += ag.ic[2 * p]; y += ag.ic[2 * p + 1];
    nokta.push([x / ag.olcek, y / ag.olcek]);
  }
  nokta.push([ag.lon[ag.b[k]], ag.lat[ag.b[k]]]);
  return ters ? nokta.reverse() : nokta;
}

/** Rotanın çizgisi: [boylam, enlem] listesi, başlangıçtan hedefe. */
export function rotaCizgisi(ag, rota) {
  const out = [[ag.lon[rota.dugumler[0]], ag.lat[rota.dugumler[0]]]];
  rota.kenarlar.forEach((k, i) => out.push(...kenarCizgisi(ag, k, ag.a[k] !== rota.dugumler[i]).slice(1)));
  return out;
}

/** Rotanın özeti: uzunluk ve geçtiği su. */
export function rotaOzeti(ag, rota, su = null, altGecitDolu = false) {
  let metre = 0, derinParca = 0, sigParca = 0, enDerinDm = 0, altGecit = 0;
  for (const k of rota.kenarlar) {
    metre += ag.metre[k];
    if (su) {
      derinParca += su.derinParca[k]; sigParca += su.sigParca[k];
      enDerinDm = Math.max(enDerinDm, su.derinDm[k]);
    }
    if (altGecitDolu) altGecit += ag.altGecit[k];
  }
  return { metre, derinParca, sigParca, enDerinM: enDerinDm / 10, altGecit };
}
