// ═══════════════════════════════════════════════
//  İZMİR AFET RADAR — sel senaryosu ve tahliye rotası
// ═══════════════════════════════════════════════
const API_BASE = "/api/v1";
// Uç noktadan JSON (yol API_BASE'e göre, ör. '/sel_senaryo')
const api = yol => fetch(API_BASE + yol).then(r => r.json());

// İl çerçevesi (+0.05° pay): sunucu static/izmir_sinir.geojson'dan doldurur
// (bounds.py) — sınır değişince katman çerçeveleri kendiliğinden uyar.
const IZMIR = window.IZMIR_SINIR;

// ═══════════════════════════════════════════════
//  HARİTA
// ═══════════════════════════════════════════════
// Telefonda çeyrek zoom adımı: il tam zoom seviyeleri arasında kalıyor
// (8 dar, 7 fazla uzak) — kesirli zoom ili ekrana tam oturtur
const MOBIL = document.getElementById('map').clientWidth <= 640;
const map = L.map("map", { zoomControl: false, zoomSnap: MOBIL ? 0.25 : 1 });
map.attributionControl.setPrefix(false);
// İl çerçevesi panellerin örtmediği alana sığdırılır: masaüstünde soldaki sel
// panelinin (76 + 300 px) sağına, telefonda başlık ile alttan açılan sel
// paneli (≤40vh) arasına
map.fitBounds([[IZMIR.latMin, IZMIR.lonMin], [IZMIR.latMax, IZMIR.lonMax]], MOBIL
  ? { paddingTopLeft: [10, 60], paddingBottomRight: [10, Math.round(innerHeight * 0.4) + 16], animate: false }
  : { paddingTopLeft: [392, 70], paddingBottomRight: [20, 20], animate: false });

// Altlıklar — hepsi anahtarsız. CARTO artık API anahtarı istiyor
// ("API KEY REQUIRED" karosu döndürüyor), bu yüzden Esri tuvaline geçildi.
// labels: gri tuvalin ayrı etiket katmanı (base ile birlikte eklenir)
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const ESRI_ATTR = 'Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors';
const BASEMAPS = {
  light: { url: `${ESRI}/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
           labels: `${ESRI}/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
           maxNativeZoom: 16, attribution: ESRI_ATTR },
  dark:  { url: `${ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
           labels: `${ESRI}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
           maxNativeZoom: 16, attribution: ESRI_ATTR },
  sat:   { url: `${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`,
           attribution: 'Tiles © Esri — Esri, Maxar, Earthstar Geographics' },
  topo:  { url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
           maxNativeZoom: 17, attribution: '© OpenStreetMap contributors, SRTM | © OpenTopoMap (CC-BY-SA)' },
};
function makeBasemap(type) {
  const b = BASEMAPS[type];
  const opts = { attribution: b.attribution, maxNativeZoom: b.maxNativeZoom || 19, maxZoom: 19 };
  const layers = [L.tileLayer(b.url, opts)];
  if (b.labels) layers.push(L.tileLayer(b.labels, { maxNativeZoom: b.maxNativeZoom, maxZoom: 19 }));
  return L.layerGroup(layers);
}

let currentTile = makeBasemap('light').addTo(map);

// ═══════════════════════════════════════════════
//  İZMİR İDARİ SINIRLAR (30 İlçe)
// ═══════════════════════════════════════════════
window.izmirGeoJSON = null;
window.izmirSinirGeoJSON = null;
api('/izmir_ilce')
  .then(geojson => {
    window.izmirGeoJSON = geojson;
    L.geoJSON(geojson, {
      style: {
        color: '#6366f1',
        weight: 1.5,
        opacity: 0.55,
        fill: false,
        lineCap: 'round',
        lineJoin: 'round',
      },
      interactive: false,
    }).addTo(map);
  })
  .catch(err => console.warn('İzmir ilçe sınırları yüklenemedi:', err));

api('/izmir_sinir')
  .then(geojson => { window.izmirSinirGeoJSON = geojson; })
  .catch(err => console.warn('İzmir dış sınır yüklenemedi:', err));

// ═══════════════════════════════════════════════
//  İZMİR SINIR YARDIMCI FONKSİYONLAR
// ═══════════════════════════════════════════════
// Polygon veya MultiPolygon feature'ının tüm dış ring'lerini döndür
function _outerRings(feature) {
  const geom = feature.geometry;
  if (geom.type === 'Polygon') return [geom.coordinates[0]];
  if (geom.type === 'MultiPolygon') return geom.coordinates.map(poly => poly[0]);
  return [];
}
// Verilen konuma en yakın ilçe merkezinin adı (DISTRICT_CENTERS + haversine)
function nearestDistrict(lat, lng) {
  let best = null, bestD = Infinity;
  for (const c of DISTRICT_CENTERS) {
    const d = haversineKm(lat, lng, c.lat, c.lon);
    if (d < bestD) { bestD = d; best = c; }
  }
  return best ? best.name : '';
}
// Tuvalde çizilmiş görüntüyü il dış sınırıyla kırpar (sınır dışı saydam).
// Görüntü sinir = [[güney, batı], [kuzey, doğu]] çerçevesini kaplar ve
// satırları Mercator'da eşit aralıklıdır (L.imageOverlay böyle gerer).
// Sınır yüklenmediyse ilçe poligonları, o da yoksa kırpılmaz.
function ilSinirMaskesi(ctx, W, H, sinir) {
  const gj = window.izmirSinirGeoJSON || window.izmirGeoJSON;
  if (!gj) return;
  const [[latS, lonW], [latN, lonE]] = sinir;
  ctx.save();
  ctx.globalCompositeOperation = 'destination-in';
  ctx.beginPath();
  for (const f of gj.features || [gj]) {
    for (const ring of _outerRings(f)) {
      ring.forEach(([lo, la], k) => {
        const x = (lo - lonW) / (lonE - lonW) * W, y = mercSatirY(latS, latN, H, la);
        k === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.closePath();
    }
  }
  ctx.fill();
  ctx.restore();
}

// ═══════════════════════════════════════════════
//  YARDIMCI FONKSİYONLAR
// ═══════════════════════════════════════════════
function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371, dL = (lat2-lat1)*Math.PI/180, dLo = (lon2-lon1)*Math.PI/180;
  const a = Math.sin(dL/2)**2 + Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLo/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

// İlçe merkezleri (nearestDistrict)
const DISTRICT_CENTERS = [
  { name: "Konak",       lat: 38.4189, lon: 27.1287 },
  { name: "Bornova",     lat: 38.4673, lon: 27.2222 },
  { name: "Karşıyaka",   lat: 38.4575, lon: 27.1117 },
  { name: "Buca",        lat: 38.3830, lon: 27.1833 },
  { name: "Karabağlar",  lat: 38.3667, lon: 27.1167 },
  { name: "Balçova",     lat: 38.3886, lon: 27.0328 },
  { name: "Bayraklı",    lat: 38.4623, lon: 27.1667 },
  { name: "Çiğli",       lat: 38.4920, lon: 27.0833 },
  { name: "Gaziemir",    lat: 38.3222, lon: 27.1333 },
  { name: "Narlıdere",   lat: 38.3906, lon: 26.9819 },
  { name: "Güzelbahçe",  lat: 38.3909, lon: 26.9814 },
  { name: "Menemen",     lat: 38.6108, lon: 27.0592 },
  { name: "Aliağa",      lat: 38.7983, lon: 26.9756 },
  { name: "Foça",        lat: 38.6700, lon: 26.7567 },
  { name: "Karaburun",   lat: 38.6333, lon: 26.5100 },
  { name: "Dikili",      lat: 39.0700, lon: 26.8833 },
  { name: "Bergama",     lat: 39.1200, lon: 27.1800 },
  { name: "Kınık",       lat: 39.0861, lon: 27.3981 },
  { name: "Kemalpaşa",   lat: 38.4317, lon: 27.4208 },
  { name: "Torbalı",     lat: 38.1667, lon: 27.3667 },
  { name: "Selçuk",      lat: 37.9503, lon: 27.3695 },
  { name: "Bayındır",    lat: 38.2197, lon: 27.6503 },
  { name: "Tire",        lat: 38.0933, lon: 27.7336 },
  { name: "Ödemiş",      lat: 38.2253, lon: 27.9739 },
  { name: "Kiraz",       lat: 38.2325, lon: 28.2003 },
  { name: "Beydağ",      lat: 38.0833, lon: 28.2167 },
  { name: "Menderes",    lat: 38.2553, lon: 27.1356 },
  { name: "Seferihisar", lat: 38.1981, lon: 26.8339 },
  { name: "Urla",        lat: 38.3219, lon: 26.7619 },
  { name: "Çeşme",       lat: 38.3239, lon: 26.3047 },
];

// ═══════════════════════════════════════════════
//  BASEMAP DEĞİŞTİR
// ═══════════════════════════════════════════════
function changeBasemap(type) {
  map.removeLayer(currentTile);
  currentTile = makeBasemap(type).addTo(map);
}

// ═══════════════════════════════════════════════
//  UI TOGGLE FONKSIYONLARI
// ═══════════════════════════════════════════════
function togglePanel(id) {
  const p = document.getElementById(id);
  p.style.display = (p.style.display === 'block') ? 'none' : 'block';
}
function toggleSelPanel() {
  const gizli = document.getElementById('sel-panel').classList.toggle('hidden');
  document.getElementById('btn-sel').classList.toggle('active', !gizli);
}

// ═══════════════════════════════════════════════
//  GÖRÜNTÜ KATMANI (L.imageOverlay)
// ═══════════════════════════════════════════════
// Görüntü katmanını günceller ya da ilk kez oluşturur
function goruntuKatmani(katman, url, sinir, opacity) {
  if (katman) { katman.setUrl(url); katman.setBounds(L.latLngBounds(sinir)); }
  else katman = L.imageOverlay(url, sinir, { opacity, interactive: false });
  if (!map.hasLayer(katman)) katman.addTo(map);
  return katman;
}

// L.imageOverlay görüntüyü köşelerinden Web Mercator'da DOĞRUSAL gerer;
// satırları eşit enlem aralıklı çizmek il ortasında ~0.5 km kayma yapar.
// Bu yüzden görüntü satırları Mercator'da eşit aralıklı seçilir:
// mercSatirY → enlemin görüntüdeki satırı.
const _merc = lat => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
function mercSatirY(latS, latN, H, lat) {
  const yN = _merc(latN);
  return (yN - _merc(lat)) / (yN - _merc(latS)) * H;
}

// ═══════════════════════════════════════════════
//  SEL / SU BASKINI — /api/v1/sel_riski (+ harita.png)
//  Sunucu arazi duyarlılığını (SRTM hidrolojisi) 24 saatlik yağış
//  tahminiyle çarpıp PNG olarak verir; burada yalnız serilir.
// ═══════════════════════════════════════════════
const SEL_RENK = ['rgba(56,189,248,.75)', 'rgba(37,99,235,.85)', 'rgba(30,27,140,.9)'];
const SEL_DUSUK = 'rgba(186,214,236,.6)';
const altGecitLayer = L.layerGroup();
let selVeri = null, selTur = 'senaryo', _selOverlay = null;

async function loadSelRiski() {
  const kutu = document.getElementById('sel-yagis');
  try {
    const d = await api('/sel_riski');
    if (d.status !== 'ok') { kutu.textContent = '⚠️ ' + (d.detail || 'Sel riski hesaplanamadı'); return; }
    selVeri = d;
  } catch (err) {
    kutu.textContent = '⚠️ Sel riski servisine ulaşılamadı.';
    console.error('Sel riski hatası:', err);
    return;
  }
  altGecitLayer.clearLayers();
  selVeri.alt_gecitler.forEach(a => L.marker([a.lat, a.lon], {
    icon: L.divIcon({ className: '', html: '<div style="font-size:13px;filter:drop-shadow(0 1px 1px rgba(0,0,0,.35))">🚇</div>', iconSize: [16, 16], iconAnchor: [8, 8] }),
  }).bindTooltip('Alt geçit — kuvvetli yağışta su birikebilir').addTo(altGecitLayer));
  altGecitGoster();
  if (selTur !== 'senaryo') renderSelRiski();
}

// Alt geçitler yalnız yakın ölçekte (il ölçeğinde binlercesi kalabalık)
function altGecitGoster() {
  const ok = map.getZoom() >= 13;
  if (ok && !map.hasLayer(altGecitLayer)) map.addLayer(altGecitLayer);
  if (!ok && map.hasLayer(altGecitLayer)) map.removeLayer(altGecitLayer);
}
map.on('zoomend', altGecitGoster);

function selTurSec(t) {
  selTur = t;
  ['gunluk', 'duyarlilik', 'senaryo'].forEach(k => document.getElementById('sel-tur-' + k).classList.toggle('active', k === t));
  document.getElementById('sel-senaryo').style.display = t === 'senaryo' ? 'block' : 'none';
  document.getElementById('sel-gunluk-kutu').style.display = t === 'senaryo' ? 'none' : 'block';
  document.getElementById('sel-yagis').style.display = t === 'senaryo' ? 'none' : 'block';
  if (t === 'senaryo') renderSelSenaryo();
  else {
    if (selVeri) renderSelRiski();
    rotaSenaryoyaUy();
  }
}

// ═══════════════════════════════════════════════
//  KADEMELİ YAĞIŞ SENARYOSU — /api/v1/sel_senaryo (+ harita.png)
//  "X mm yağış Y saatte düşerse nereyi su basar?" (çevrimdışı hesaplı)
// ═══════════════════════════════════════════════
let senaryoVeri = null, senP = 50, senSure = 1;

async function renderSelSenaryo() {
  const kutu = document.getElementById('sen-ozet');
  if (!senaryoVeri) {
    try {
      const d = await api('/sel_senaryo');
      if (d.status !== 'ok') { kutu.textContent = '⚠️ ' + (d.detail || 'Senaryolar hazır değil'); return; }
      senaryoVeri = d;
    } catch (err) {
      kutu.textContent = '⚠️ Senaryo servisine ulaşılamadı.';
      console.error('Senaryo hatası:', err);
      return;
    }
    const sl = document.getElementById('sen-p');
    sl.max = senaryoVeri.yagis_mm.length - 1;
    sl.value = Math.max(0, senaryoVeri.yagis_mm.indexOf(senP));
    document.getElementById('sen-drenaj').textContent = senaryoVeri.drenaj_mm_sa;
    document.getElementById('sen-siniflar').innerHTML = senaryoVeri.siniflar.map(s =>
      `<div class="yr-satir"><span class="yr-kutu" style="background:${s.renk}"></span>${s.ad}</div>`).join('');
  }
  if (selTur !== 'senaryo') return;
  rotaSenaryoyaUy();
  const d = senaryoVeri;
  const url = `/api/v1/sel_senaryo/harita.png?p=${senP}&sure=${senSure}`;
  ilSinirinaKirp(url, d.bounds).then(veri => {
    if (selTur !== 'senaryo') return;
    _selOverlay = goruntuKatmani(_selOverlay, veri, d.bounds, 0.9);
  });
  const o = d.senaryolar[`${senP}_${senSure}`];
  const saatlik = senP / senSure;
  const siddet = saatlik >= 50 ? 'çok kuvvetli' : saatlik >= 7.6 ? 'kuvvetli' : saatlik >= 2.5 ? 'orta' : 'hafif';
  const km = v => v >= 10 ? Math.round(v) : v.toFixed(1);
  kutu.innerHTML = `<b>${senP} mm yağış ${senSure} saatte</b> (saatte ~${saatlik < 10 ? saatlik.toFixed(1) : Math.round(saatlik)} mm, ${siddet})<br>
    🌊 30 cm'den derin su: <b>${km(o.su_alan_km2['0.3'])} km²</b> (10 cm+: ${km(o.su_alan_km2['0.1'])} km²)<br>
    ${o.belirsiz_km2 ? `▒ Düz ovada su gelen alan: ${km(o.belirsiz_km2)} km² (derinlik belirsiz)<br>` : ''}
    🚗 Araçla geçilemez yol: <b>${km(o.yol_kapali_km)} km</b><br>
    🚇 Alt geçitler: ${o.alt_gecit_dolu ? `kent drenajı aşılıyor, <b>${o.alt_gecit_dolu}</b> alt geçidin hepsinde su birikme riski` : 'kent drenajı yağışı taşır'}<br>
    🏕️ Toplanma alanı: ${o.toplanma_etkilenen_sayi ? `<b>${o.toplanma_etkilenen_sayi}</b> / ${o.toplanma_toplam} alanda 30 cm+ su` : 'etkilenmiyor'}`;
  document.getElementById('sen-mahalle').innerHTML = o.mahalleler.length
    ? '<b>En çok etkilenen mahalleler</b> (30 cm+ su):<br>' + o.mahalleler.slice(0, 6).map(m =>
        `${m.mahalle} (${m.ilce}) — ${m.km2 < 1 ? Math.round(m.km2 * 100) + ' ha' : m.km2.toFixed(1) + ' km²'}`).join('<br>')
    : '';
}

function senaryoYagisSec(i) {
  senP = senaryoVeri ? senaryoVeri.yagis_mm[+i] : senP;
  document.getElementById('sen-p-yazi').textContent = senP + ' mm';
  if (senaryoVeri) renderSelSenaryo();
}

function senaryoSureSec(s) {
  senSure = s;
  [1, 6, 24].forEach(k => document.getElementById('sen-sure-' + k).classList.toggle('active', k === s));
  if (senaryoVeri) renderSelSenaryo();
}

// Sunucu görüntüsünü (sınıra değen hücreler dahil, satırlar Mercator) il
// sınırıyla kırpar: kenarda boşluk da taşma da kalmaz. url → Promise<dataURL>
const _kirpiliOnbellek = new Map();
function ilSinirinaKirp(url, bounds) {
  if (_kirpiliOnbellek.has(url)) return _kirpiliOnbellek.get(url);
  const p = new Promise((tamam, hata) => {
    const img = new Image();
    img.onload = () => {
      const W = img.naturalWidth, H = img.naturalHeight;
      const cv = document.createElement('canvas');
      cv.width = W; cv.height = H;
      const ctx = cv.getContext('2d');
      ctx.drawImage(img, 0, 0);
      ilSinirMaskesi(ctx, W, H, bounds);
      tamam(cv.toDataURL('image/png'));
    };
    img.onerror = hata;
    img.src = url;
  });
  _kirpiliOnbellek.set(url, p);
  return p;
}

function renderSelRiski() {
  if (selTur === 'senaryo') { renderSelSenaryo(); return; }
  const d = selVeri;
  const url = `/api/v1/sel_riski/harita.png?tur=${selTur}&t=${encodeURIComponent(d.tahmin_zamani)}`;
  ilSinirinaKirp(url, d.bounds).then(veri => {
    if (selTur === 'senaryo') return;
    _selOverlay = goruntuKatmani(_selOverlay, veri, d.bounds, 0.9);
  });
  const e = d.en_yogun;
  const yer = nearestDistrict(e.lat, e.lon);
  document.getElementById('sel-yagis').innerHTML = d.genel_f > 0
    ? `<b>Önümüzdeki 24 saat: ${d.genel_seviye} yağış</b><br>
       En yoğun: ${yer} çevresi — saatte en çok <b>${e.maks_saatlik} mm</b>, 24 saatte toplam <b>${e.toplam_24} mm</b>.`
    : `<b>Önümüzdeki 24 saatte kayda değer yağış beklenmiyor.</b><br>
       En çok: ${yer} çevresi, toplam ${e.toplam_24} mm. Günlük risk haritası bu yüzden boş; arazi duyarlılığına bakabilirsiniz.`;
  document.getElementById('sel-aciklama').innerHTML = selTur === 'gunluk'
    ? 'Arazi duyarlılığı × yağış şiddeti. Yağış yoksa risk yoktur. Rota da bu değere göre sel duyarlı yollardan kaçar.'
    : 'Yağıştan bağımsız: kuvvetli yağışta suyun toplandığı ya da taştığı yerler (dere yatağına yakın alçak alanlar ve çukurlar).';
  const pay = d.alan_payi[selTur];
  const yuzde = x => x < 1 && x > 0 ? x.toFixed(1) : Math.round(x);
  const dusuk = Math.max(0, 100 - d.bantlar.reduce((t, ad) => t + pay[ad], 0));
  document.getElementById('sel-bantlar').innerHTML = `
    <div class="yr-satir"><span class="yr-kutu" style="background:${SEL_DUSUK}"></span>Düşük
      <span class="yr-pay">ilin %${yuzde(dusuk)} kadarı</span></div>` + d.bantlar.map((ad, k) => `
    <div class="yr-satir"><span class="yr-kutu" style="background:${SEL_RENK[k]}"></span>${ad}
      <span class="yr-pay">ilin %${yuzde(pay[ad])} kadarı</span></div>`).join('');
}

// ═══════════════════════════════════════════════
//  TAHLİYE ROTASI (pgRouting /routing/smart)
// ═══════════════════════════════════════════════
const routeLayer = L.layerGroup().addTo(map);   // tab'lardan bağımsız araç katmanı
const routeState = { active: false, mode: 'drive', start: null, dest: null, destAlan: null,
                     istek: 0, senaryo: null };

// Rota, haritada görünen yağış senaryosuna göre çizilir: sel panelinde
// "Yağış senaryosu" seçiliyse o yağışta su basan yollar kapalı, su altındaki
// toplanma alanları hedef dışıdır. Diğer modlarda null (yağış tahmini cezası).
function rotaSenaryosu() {
  return selTur === 'senaryo' && senaryoVeri ? `${senP}_${senSure}` : null;
}

// Senaryo değişince (kaydırıcı hızlı oynatılabilir: 350 ms beklenir) not,
// toplanma alanı renkleri ve rota tazelenir
let _senaryoZamanlayici = null;
function rotaSenaryoyaUy() {
  rotaSenaryoNotu();
  clearTimeout(_senaryoZamanlayici);
  _senaryoZamanlayici = setTimeout(() => {
    toplanmaSenaryoBoya();
    if (routeState.start && routeState.senaryo !== rotaSenaryosu()) {
      otomatikHedefiBirak();
      fetchRoute();
    }
  }, 350);
}

function rotaSenaryoNotu() {
  const el = document.getElementById('route-senaryo-not');
  const sen = rotaSenaryosu();
  el.style.display = sen ? 'block' : 'none';
  if (!sen) return;
  const [p, sure] = sen.split('_');
  el.innerHTML = `🌧️ Rota <b>${p} mm / ${sure} saat</b> yağış senaryosuna göre çizilir: su basan yollar
    kapalı sayılır; su altındaki toplanma alanları ${TOPLANMA_SUDA_ORNEK} gösterilir ve seçilmez.`;
}

// Rota sembolojisi — araç: beyaz haleli düz yol çizgisi; yaya: haleli
// nokta dizisi (yürüyüş rotasının yerleşik kartografik gösterimi).
// dashArray '0.1 12' + lineCap round → 12 px arayla yuvarlak noktalar.
const ROTA_STIL = {
  drive: {
    ad: 'Araç', simge: '🚗', pinRenk: '#4f46e5',
    katmanlar: [
      { color: '#ffffff', weight: 9, opacity: 0.95, lineCap: 'round' },
      { color: '#4f46e5', weight: 5, opacity: 1, lineCap: 'round' },
    ],
    ornek: `<svg width="30" height="10" style="vertical-align:middle"><line x1="4" y1="5" x2="26" y2="5" stroke="#fff" stroke-width="8" stroke-linecap="round"/><line x1="4" y1="5" x2="26" y2="5" stroke="#4f46e5" stroke-width="4" stroke-linecap="round"/></svg>`,
  },
  walk: {
    ad: 'Yaya', simge: '🚶', pinRenk: '#0284c7',
    katmanlar: [
      { color: '#ffffff', weight: 10, opacity: 0.95, lineCap: 'round', dashArray: '0.1 12' },
      { color: '#0284c7', weight: 6, opacity: 1, lineCap: 'round', dashArray: '0.1 12' },
    ],
    ornek: `<svg width="30" height="10" style="vertical-align:middle">${[5, 15, 25].map(x => `<circle cx="${x}" cy="5" r="3.6" fill="#fff"/><circle cx="${x}" cy="5" r="2.6" fill="#0284c7"/>`).join('')}</svg>`,
  },
};
// Yol verisi dışı (kuş uçuşu) kısım: iki modda da aynı, nötr gri kesikli
const YOL_DISI_STIL = { color: '#64748b', weight: 2.5, opacity: 0.85, dashArray: '6 6', lineCap: 'butt' };
const YOL_DISI_ORNEK = `<svg width="22" height="8" style="vertical-align:middle"><line x1="1" y1="4" x2="21" y2="4" stroke="#64748b" stroke-width="2.5" stroke-dasharray="5 4"/></svg>`;

// ── Toplanma alanları (İBB açık verisi) — rota paneli açıkken görünür ──
// 2380 nokta: canvas renderer ile tek tuvalde çizilir. Tuval tüm haritayı
// kaplar; overlayPane'de olsaydı harita tıklama filtresi her tıklamayı
// yutardı — bu yüzden ayrı pane'de.
map.createPane('toplanmaPane').style.zIndex = 450;
const toplanmaLayer = L.layerGroup();
const toplanmaRenderer = L.canvas({ padding: 0.3, pane: 'toplanmaPane' });
let toplanmaYuklendi = false;
const toplanmaIsaret = new Map();   // id → { m: circleMarker, tip: tooltip html }
const TOPLANMA_STIL = { color: '#fff', weight: 1.5, fillColor: '#059669', fillOpacity: 0.9 };
// Seçili senaryoda su altında (≥30 cm) ya da düz ovada: rota hedef seçmez
const TOPLANMA_SUDA = { color: '#fff', weight: 1.5, fillColor: '#94a3b8', fillOpacity: 0.95 };
const TOPLANMA_SUDA_ORNEK = `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${TOPLANMA_SUDA.fillColor};border:1.5px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,.15);vertical-align:-1px"></span> gri`;

const trBaslik = s => (s || '').toLocaleLowerCase('tr')
  .replace(/(^|[\s/.(-])(\S)/g, (m, a, b) => a + b.toLocaleUpperCase('tr'));
// "3 NO LU AFET VE ACİL DURUM TOPLANMA ALANI" → "3 No'lu Toplanma Alanı"
function toplanmaAdi(a) {
  const m = (a.adi || '').match(/^\s*(\d+)\s*NO\s*'?\s*LU/i);
  return m ? `${m[1]} No'lu Toplanma Alanı` : trBaslik(a.adi);
}
function toplanmaYeri(a) {
  return [trBaslik(a.ilce), a.mahalle ? trBaslik(a.mahalle) + ' Mah.' : null]
    .filter(Boolean).join(' / ');
}

async function loadToplanmaAlanlari() {
  if (toplanmaYuklendi) return;
  toplanmaYuklendi = true;
  try {
    const alanlar = await api('/toplanma_alanlari');
    alanlar.forEach(a => {
      const tip = `<b>${toplanmaAdi(a)}</b><br>${toplanmaYeri(a)}${a.yol ? ' · ' + a.yol : ''}`;
      const m = L.circleMarker([a.lat, a.lon], { renderer: toplanmaRenderer, radius: 4.5, ...TOPLANMA_STIL })
        .bindTooltip(tip, { direction: 'top', offset: [0, -4] })
        .on('click', e => { L.DomEvent.stopPropagation(e); selectToplanmaAlani(a); })
        .addTo(toplanmaLayer);
      toplanmaIsaret.set(a.id, { m, tip });
    });
    toplanmaSenaryoBoya();
  } catch (err) {
    toplanmaYuklendi = false;
    console.warn('Toplanma alanları yüklenemedi:', err);
  }
}

// Seçili senaryoda su altındaki / düz ovadaki alanlar gri boyanır
const _senaryoAlanlari = new Map();   // senaryo → [{id, derinlik, belirsiz}]
async function toplanmaSenaryoBoya() {
  if (!toplanmaIsaret.size) return;
  const sen = rotaSenaryosu();
  if (sen && !_senaryoAlanlari.has(sen)) {
    try {
      const [p, sure] = sen.split('_');
      const d = await api(`/sel_senaryo/toplanma?p=${p}&sure=${sure}`);
      if (d.status === 'ok') _senaryoAlanlari.set(sen, d.alanlar);
    } catch (err) {
      console.warn('Senaryo toplanma alanları alınamadı:', err);
    }
    if (sen !== rotaSenaryosu()) return;   // beklerken senaryo değişti
  }
  const suda = new Map((sen && _senaryoAlanlari.get(sen) || []).map(a => [a.id, a]));
  toplanmaIsaret.forEach(({ m, tip }, id) => {
    const a = suda.get(id);
    m.setStyle(a ? TOPLANMA_SUDA : TOPLANMA_STIL);
    m.setTooltipContent(a ? `${tip}<br><span style="color:#b91c1c">🌊 ${a.derinlik >= 0.3
      ? `Bu senaryoda ~${a.derinlik.toFixed(1)} m su altında` : 'Düz ova: su gelebilir, derinlik belirsiz'} — rota seçmez</span>` : tip);
  });
}

// Toplanma alanına tıklandı: başlangıç varsa hedef yapılır
function selectToplanmaAlani(a) {
  if (!routeState.start) {
    document.getElementById('route-summary').style.display = 'block';
    document.getElementById('route-summary').innerHTML =
      '📍 Önce haritaya tıklayıp <b>başlangıç</b> noktasını seç.';
    return;
  }
  setRouteDest(L.latLng(a.lat, a.lon), a);
  fetchRoute();
}

function toggleRoutePanel() {
  const panel = document.getElementById('route-panel');
  routeState.active = panel.style.display !== 'block';
  panel.style.display = routeState.active ? 'block' : 'none';
  document.getElementById('btn-route').classList.toggle('active', routeState.active);
  document.body.classList.toggle('rota-acik', routeState.active);
  map.getContainer().style.cursor = routeState.active ? 'crosshair' : '';
  if (routeState.active) {
    loadToplanmaAlanlari();
    toplanmaLayer.addTo(map);
  } else {
    map.removeLayer(toplanmaLayer);
    clearRoute();
  }
}

function setRouteMode(mode) {
  routeState.mode = mode;
  document.getElementById('route-mode-drive').classList.toggle('active', mode === 'drive');
  document.getElementById('route-mode-walk').classList.toggle('active', mode === 'walk');
  otomatikHedefiBirak();   // otomatik seçilen alan moda göre değişebilir
  if (routeState.start) fetchRoute();   // mod değişince rota tazelenir
}

// Otomatik seçilen hedefi bırakır (mod/senaryo değişti: yeniden seçilsin);
// kullanıcının kendi seçtiği alan korunur
function otomatikHedefiBirak() {
  if (!routeState.autoSecim) return;
  routeLayer.removeLayer(routeState.destPin);
  routeState.dest = routeState.destAlan = routeState.destPin = null;
  routeState.autoSecim = false;
}

function routePin(latlng, renk, etiket) {
  return L.marker(latlng, {
    icon: L.divIcon({
      className: '',
      html: `<div style="display:flex;flex-direction:column;align-items:center">
               <div style="font-size:11px;font-weight:800;background:${renk};color:#fff;
                    padding:1px 7px;border-radius:8px;white-space:nowrap;
                    box-shadow:0 1px 3px rgba(0,0,0,.35)">${etiket}</div>
               <div style="width:3px;height:9px;background:${renk};border-radius:2px"></div>
             </div>`,
      iconSize: [110, 30], iconAnchor: [55, 30],   // geniş kutu: uzun etiket ortalı kalsın
    }),
  });
}

function clearRoute() {
  routeLayer.clearLayers();
  routeState.start = routeState.dest = routeState.destAlan = null;
  routeState.destPin = routeState.startPin = null;
  routeState.autoSecim = false;
  document.getElementById('route-summary').style.display = 'none';
  document.getElementById('route-panel').classList.remove('has-route');
}

// Hedef pinini (tek) yerleştirir; alan verilirse toplanma alanıdır
function setRouteDest(latlng, alan) {
  if (routeState.destPin) routeLayer.removeLayer(routeState.destPin);
  routeState.autoSecim = false;   // otomatik seçimde fetchRoute tekrar true yapar
  routeState.dest = latlng;
  routeState.destAlan = alan || null;
  routeState.destPin = routePin(latlng, alan ? '#059669' : '#dc2626', alan ? 'TOPLANMA' : 'HEDEF');
  routeLayer.addLayer(routeState.destPin);
}

// Her harita tıklaması yeni başlangıçtır; hedef her zaman otomatik seçilen
// en güvenli toplanma alanıdır (kullanıcıya hedef seçtirilmez)
function handleRouteClick(latlng) {
  clearRoute();
  routeState.start = latlng;
  const stil = ROTA_STIL[routeState.mode];
  routeState.startPin = routePin(latlng, stil.pinRenk, `${stil.simge} BAŞLANGIÇ`);
  routeLayer.addLayer(routeState.startPin);
  fetchRoute();
}

function routeUseMyLocation() {
  if (!navigator.geolocation) return alert('Tarayıcı konum desteklemiyor.');
  navigator.geolocation.getCurrentPosition(
    p => handleRouteClick(L.latLng(p.coords.latitude, p.coords.longitude)),
    () => alert('Konum alınamadı — izin verildiğinden emin ol.'),
    { enableHighAccuracy: true, timeout: 8000 }
  );
}

// Rotayı açık panellerin (solda sel paneli, sağda rota paneli) arasındaki
// boş alana sığdırmak için fitBounds dolguları — panellerin gerçek konumundan
function routeFitPadding() {
  const W = map.getContainer().clientWidth;
  const kutu = id => {
    const el = document.getElementById(id);
    if (!el || el.classList.contains('hidden') || getComputedStyle(el).display === 'none') return null;
    return el.getBoundingClientRect();
  };
  const sol = kutu('sel-panel'), sag = kutu('route-panel');
  const top = 70;
  // Mobilde (CSS @media 640px) rota paneli alttan açılan sayfadır:
  // rota üstteki boş alana sığdırılır
  if (W <= 640) {
    const H = map.getContainer().clientHeight;
    const alt = sag ? H - sag.top + 12 : (sol ? H - sol.top + 12 : 20);
    return { paddingTopLeft: [60, top], paddingBottomRight: [16, alt] };
  }
  let left = sol ? sol.right + 16 : 76, right = sag ? W - sag.left + 16 : 20;
  if (left + right > W - 200) { left = 76; right = 20; }   // dar pencerede paneller yok sayılır
  return { paddingTopLeft: [left, top], paddingBottomRight: [right, 20] };
}

// Rota üstünde su vurgusu (rota çizgisinin üstüne kesikli)
const SU_STIL = {
  derin: { color: '#dc2626', weight: 5, opacity: 1, dashArray: '5 6', lineCap: 'butt' },
  sig: { color: '#f59e0b', weight: 4, opacity: 1, dashArray: '5 6', lineCap: 'butt' },
  duyarli: { color: '#1d4ed8', weight: 3, opacity: 0.95, dashArray: '3 7', lineCap: 'round' },
};

// Seçili yağış senaryosunda rotadaki su (sunucu: get_smart_routes → senaryo)
function senaryoSatiri(sn, mode) {
  const [p, sure] = sn.ad.split('_');
  const kutu = (renk, ic) => `<div style="margin-top:5px;padding:6px 8px;border-radius:7px;background:${renk};font-size:11px;line-height:1.5">${ic}</div>`;
  if (!sn.veri_var) {
    return kutu('rgba(217,119,6,.1)', `🌧️ <b>${p} mm / ${sure} saat</b> senaryosunun yol verisi hazır değil
      (sel_senaryo_yollar.py) — rota senaryodaki suyu hesaba katmadı.`);
  }
  const m = v => v >= 1000 ? (v / 1000).toFixed(1) + ' km' : v + ' m';
  const satir = [];
  if (sn.derin_yer) {
    satir.push(`<span style="color:#b91c1c"><b>⚠️ ${sn.derin_yer} yerde 30 cm+ sudan geçiyor</b>
      (en derin ~${sn.en_derin_m.toFixed(1)} m, kırmızı) — kuru bir yol bulunamadı.</span>
      ${mode === 'drive' ? 'Sel suyuna araçla girilmez; ' : 'Akan suya girilmez; '}mümkünse yüksek bir yerde bekle.`);
  }
  if (sn.sig_yer) satir.push(`${sn.sig_yer} yerde sığ su (10–30 cm, turuncu)`);
  if (sn.belirsiz_m >= 50) satir.push(`${m(sn.belirsiz_m)}'si düz ovadan geçiyor: su gelebilir, derinlik bilinmiyor (gri alan)`);
  if (!satir.length) satir.push('✅ Rota su basan yollardan geçmiyor.');
  if (sn.alt_gecit_kapali) {
    satir.push(sn.alt_gecit_rotada
      ? `🚇 ${sn.alt_gecit_rotada} alt geçitten geçiyor — bu yağışta su birikir`
      : '🚇 Bu yağışta alt geçitler dolar; rota alt geçit kullanmıyor');
  }
  const atl = sn.atlanan_alan_su + sn.atlanan_alan_belirsiz;
  if (atl) {
    const neden = sn.atlanan_alan_su && sn.atlanan_alan_belirsiz ? 'su altında ya da düz ovada'
      : sn.atlanan_alan_su ? 'su altında' : 'düz ovada (su gelebilir)';
    satir.push(`🏕️ Daha yakın ${atl} toplanma alanı ${neden} — atlandı`);
  }
  if (sn.hedef_su) {
    satir.push(`<span style="color:#b91c1c">⚠️ Seçtiğin alan ${sn.hedef_su.derinlik >= 0.3
      ? `bu senaryoda ~${sn.hedef_su.derinlik.toFixed(1)} m su altında` : 'düz ovada: su gelebilir'}</span>`);
  }
  return kutu('rgba(29,78,216,.08)', `🌧️ <b>${p} mm / ${sure} saat senaryosu</b><br>${satir.join('<br>')}`);
}

async function fetchRoute() {
  const s = routeState.start;
  if (!s) return;
  const sum = document.getElementById('route-summary');
  sum.style.display = 'block';
  sum.innerHTML = '⏳ Rota hesaplanıyor...';
  const params = new URLSearchParams({
    user_lon: s.lng, user_lat: s.lat, mode: routeState.mode,
  });
  if (routeState.dest) {
    params.set('dest_lon', routeState.dest.lng);
    params.set('dest_lat', routeState.dest.lat);
  }
  const sen = rotaSenaryosu();
  if (sen) params.set('senaryo', sen);
  routeState.senaryo = sen;
  const istek = ++routeState.istek;   // senaryo hızlı değişirse yalnız son yanıt çizilir
  try {
    const d = await api(`/routing/smart?${params}`);
    if (istek !== routeState.istek) return;
    if (d.status !== 'ok') {
      sum.innerHTML = `⚠️ ${d.message || 'Rota hesaplanamadı.'}`;
      return;
    }
    // Eski rota çizgilerini sil, pinleri koru
    routeLayer.eachLayer(l => { if (!(l instanceof L.Marker)) routeLayer.removeLayer(l); });
    const stil = ROTA_STIL[routeState.mode];
    // Her stil katmanı (beyaz hale + renk) tüm segmentlere ayrı geoJSON olarak
    const geometriler = d.segments.map(seg => seg.geometry);
    stil.katmanlar.forEach(k => {
      routeLayer.addLayer(L.geoJSON(geometriler, { style: { lineJoin: 'round', ...k }, interactive: false }));
    });
    // Başlangıç pinini moda göre etiketle (🚗 / 🚶)
    if (routeState.startPin) routeLayer.removeLayer(routeState.startPin);
    routeState.startPin = routePin(s, stil.pinRenk, `${stil.simge} BAŞLANGIÇ`);
    routeLayer.addLayer(routeState.startPin);
    // Hedefsiz istekte backend en güvenli toplanma alanını seçti — pinle
    const otomatik = !routeState.dest && d.toplanma_alani;
    if (otomatik) {
      const a = d.toplanma_alani;
      setRouteDest(L.latLng(a.lat, a.lon), a);
      routeState.autoSecim = true;
    }
    // Yol dışı kısımlar: tıklanan nokta → ağa giriş, ağdan çıkış → alan.
    // Yol verisi (OSM sokak/patika/merdiven) bu kısımları kapsamaz;
    // kuş uçuşu kesikli çizgiyle gösterilir ve mesafeye eklenir.
    let yolDisiM = 0;
    const yolDisi = (a, b) => {
      if (!a || !b) return;
      const m = L.latLng(a).distanceTo(b);
      if (m < 5) return;
      yolDisiM += m;
      routeLayer.addLayer(L.polyline([a, b], { ...YOL_DISI_STIL, interactive: false }));
    };
    if (d.ag_giris) yolDisi(s, [d.ag_giris.lat, d.ag_giris.lon]);
    if (d.ag_cikis && routeState.dest) yolDisi([d.ag_cikis.lat, d.ag_cikis.lon], routeState.dest);

    const km = d.segments.reduce((a, s2) => a + (s2.length || 0), 0) / 1000;
    const hizKmSa = routeState.mode === 'drive' ? 35 : 4.5;   // kaba şehir içi ortalama
    // Yol dışı kısım her iki modda da yürünür (4.5 km/sa)
    const dk = Math.round(km / hizKmSa * 60 + yolDisiM / 1000 / 4.5 * 60);
    const toplamKm = km + yolDisiM / 1000;
    const yolDisiSatiri = yolDisiM >= 20
      ? `<br><span style="font-size:10.5px;opacity:.75">${YOL_DISI_ORNEK} ${Math.round(yolDisiM)} m yol verisi dışında (kuş uçuşu, yürüyerek)</span>`
      : '';
    const alan = routeState.destAlan;
    const hedefSatiri = alan
      ? `<div style="margin:4px 0 5px;padding:6px 8px;border-radius:7px;background:rgba(5,150,105,.1);line-height:1.45">
           🏕️ <b>${toplanmaAdi(alan)}</b><br>
           <span style="font-size:11px;opacity:.75">${toplanmaYeri(alan)}${alan.yol ? ' · ' + alan.yol : ''}</span>
           ${routeState.autoSecim ? `<br><span style="font-size:10.5px;color:#059669;font-weight:600">${d.senaryo && d.senaryo.alan_veri_var ? 'Su basmayan e' : 'E'}n yakın ${d.toplanma_alani.aday_sayisi} alan içinden en güvenli rota</span>` : ''}
         </div>`
      : (routeState.dest ? '' : '<span style="opacity:.6">(→ il merkezi)</span><br>');
    // 🌊 Sel: senaryo seçiliyse suyun bastığı kesimler (kırmızı 30 cm+,
    // turuncu 10–30 cm), değilse arazisi sel duyarlı kesimler (mavi) kesikli
    const sel = d.sel || {};
    const sn = d.senaryo;
    d.segments.forEach(sg => {
      if (!sg.geometry) return;
      const stilSu = sn && sn.veri_var
        ? (sg.su_derinlik >= 0.3 ? SU_STIL.derin : sg.su_derinlik >= 0.1 ? SU_STIL.sig : null)
        : ((sg.sel_riskli_oran || 0) >= 0.5 ? SU_STIL.duyarli : null);
      if (stilSu) routeLayer.addLayer(L.geoJSON(sg.geometry, { interactive: false, style: stilSu }));
    });
    let selSatiri = '';
    if (sn) selSatiri = senaryoSatiri(sn, routeState.mode);
    else if (sel.veri_var && (sel.riskli_m > 0 || sel.yagis_f > 0)) {
      const ag = sel.alt_gecit ? `, ${sel.alt_gecit} alt geçit` : '';
      selSatiri = sel.yagis_f > 0
        ? `<div style="margin-top:5px;padding:6px 8px;border-radius:7px;background:rgba(29,78,216,.09);font-size:11px;line-height:1.45">
             🌊 <b>Yağış bekleniyor</b> — sel duyarlı yollar (dere yatağı, çukur, alt geçit) rotada cezalandırıldı.
             ${sel.riskli_m > 0 ? `Yine de <b>${sel.riskli_m >= 1000 ? (sel.riskli_m / 1000).toFixed(1) + ' km' : sel.riskli_m + ' m'}</b>'si duyarlı kesimden geçiyor${ag} (mavi kesikli).` : 'Rota duyarlı kesimden geçmiyor.'}
           </div>`
        : `<br><span style="font-size:10.5px;opacity:.7">🌊 ${sel.riskli_m >= 1000 ? (sel.riskli_m / 1000).toFixed(1) + ' km' : sel.riskli_m + ' m'}'si sel duyarlı kesimden geçiyor${ag} — şu an yağış beklenmiyor</span>`;
    }
    sum.innerHTML = `
      <b>${stil.simge} ${stil.ad} rotası</b> ${stil.ornek}<br>
      ${hedefSatiri}
      📏 ${toplamKm.toFixed(1)} km · ⏱️ ~${dk} dk${yolDisiSatiri}${selSatiri}<br>
      <span style="font-size:10.5px;opacity:.55">Eğim + deprem${routeState.mode === 'drive' ? ' + trafik' : ''}${sn && sn.veri_var ? ' + senaryodaki su' : sel.yagis_f > 0 ? ' + sel' : ''} riskine göre ağırlıklı</span>`;
    // fitBounds'tan önce: panel küçülür, dolgu yeni yüksekliğe göre hesaplanır
    document.getElementById('route-panel').classList.add('has-route');
    const hepsi = L.featureGroup(routeLayer.getLayers());
    // maxZoom: çok kısa (ör. 0 km) rotada harita bina ölçeğine dalmasın
    if (hepsi.getLayers().length) map.fitBounds(hepsi.getBounds().pad(0.15),
      { maxZoom: 16, ...routeFitPadding() });
  } catch (err) {
    if (istek !== routeState.istek) return;
    sum.innerHTML = '⚠️ Rota servisine ulaşılamadı.';
    console.error('Rota hatası:', err);
  }
}

// Rota paneli açıkken haritaya tıklama yeni başlangıç seçer
map.on('click', function(e) {
  const t = e.originalEvent.target;
  if (t.classList.contains('leaflet-interactive') ||
      (t.closest && t.closest('.leaflet-marker-pane,.leaflet-overlay-pane'))) return;
  const { lat, lng } = e.latlng;
  if (lat < IZMIR.latMin || lat > IZMIR.latMax || lng < IZMIR.lonMin || lng > IZMIR.lonMax) return;
  if (routeState.active) handleRouteClick(e.latlng);
});

// ═══════════════════════════════════════════════
//  BAŞLANGIÇ
// ═══════════════════════════════════════════════
selTurSec('senaryo');
loadSelRiski();
// Günlük risk Open-Meteo tahminine bağlı (sunucuda saatlik önbellek)
setInterval(loadSelRiski, 30 * 60 * 1000);
