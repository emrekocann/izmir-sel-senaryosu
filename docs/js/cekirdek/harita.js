// Tek harita ve ortak katmanlar. Sekmeler haritayı doğrudan değil, buradaki
// işlevlerle kullanır: su katmanı, il sınırı, panele göre sığdırma.
import { senaryoGorseli, IL_SINIRI, jsonOku } from './veri.js';

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas';
const ATIF = 'Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors';
const DAR_EKRAN = 720;        // css/app.css'teki mobil kırılımıyla aynı

/* Su katmanı: senaryo görüntüsü (4623×6724 piksel) tek parça olarak haritaya
   konursa her yakınlaştırmada tarayıcı tamamını yeniden ölçekler ve harita
   takılır. Görüntü bir kez çözülür, her harita karosu yalnız kendi parçasını
   tuvale çizer. Görüntü satırları Mercator aralıklıdır: karo pikseli ↔ görüntü
   pikseli doğrusal eşlenir.
   Uzaklaşınca görüntü onlarca kat küçülür; tarayıcı bunu birkaç piksele bakarak
   yapar ve tek piksellik dereler kaybolur (il üstünde soluk bir sis kalır). Bu
   yüzden görüntü yüklenince yarıya yarıya küçültülmüş kopyaları hazırlanır,
   her adımda ince çizgiler kalınlaştırılır; karo, ölçeğine en yakın kopyadan
   çizilir. */
const EN_KUCUK_KOPYA = 256;   // kopya zinciri bu boyutun altına inmez (piksel)

/** Görüntünün yarıya yarıya küçülen kopyaları: [görüntü, ½, ¼, …].
    Her küçültmede çizim bir piksel kaydırılarak bir kez daha yapılır: ince
    çizgi hem kalınlaşır hem soluklaşmaz. */
function kucukKopyalar(resim) {
  const kopyalar = [resim];
  let onceki = resim, en = resim.naturalWidth, boy = resim.naturalHeight;
  while (Math.max(en, boy) / 2 >= EN_KUCUK_KOPYA) {
    en = Math.round(en / 2); boy = Math.round(boy / 2);
    const tuval = document.createElement('canvas');
    tuval.width = en; tuval.height = boy;
    const cizim = tuval.getContext('2d');
    cizim.imageSmoothingQuality = 'high';
    cizim.drawImage(onceki, 0, 0, en, boy);
    cizim.drawImage(onceki, 1, 1, en, boy);
    kopyalar.push(tuval);
    onceki = tuval;
  }
  return kopyalar;
}

const SuKatmani = L.GridLayer.extend({
  initialize(sinir, secenek) {
    this._sinir = L.latLngBounds(sinir);
    this._kopyalar = null;
    L.setOptions(this, secenek);
  },
  setUrl(url) {
    if (url === this._url) return;
    this._url = url;
    const resim = new Image();
    resim.onload = () => { if (this._url === url) { this._kopyalar = kucukKopyalar(resim); this.redraw(); } };
    resim.src = url;
  },
  createTile(karo) {
    const boy = this.getTileSize();
    const tuval = document.createElement('canvas');
    tuval.width = boy.x; tuval.height = boy.y;
    if (!this._kopyalar) return tuval;
    const kb = this._map.project(this._sinir.getNorthWest(), karo.z);
    const gd = this._map.project(this._sinir.getSouthEast(), karo.z);
    const tam = this._kopyalar[0];
    const kat = Math.min(this._kopyalar.length - 1,
      Math.max(0, Math.floor(Math.log2(tam.naturalWidth / (gd.x - kb.x)))));
    const resim = this._kopyalar[kat];                  // harita pikseline en yakın ölçekli kopya
    const ox = resim.width / (gd.x - kb.x);             // görüntü pikseli / harita pikseli
    const oy = resim.height / (gd.y - kb.y);
    // Karo, kenarından PAY piksel taşacak biçimde çizilir (tuval taşanı kırpar):
    // kenar pikselleri komşu karoyla aynı görüntü pikselleriyle yumuşatılır,
    // karolar arasında ince çizgi kalmaz.
    const PAY = 2, kx = karo.x * boy.x, ky = karo.y * boy.y;
    const x0 = Math.max(kx - PAY, kb.x), x1 = Math.min(kx + boy.x + PAY, gd.x);
    const y0 = Math.max(ky - PAY, kb.y), y1 = Math.min(ky + boy.y + PAY, gd.y);
    if (x1 <= x0 || y1 <= y0) return tuval;
    const cizim = tuval.getContext('2d');
    cizim.imageSmoothingEnabled = ox > 1;     // uzaklaşınca yumuşat, yakınlaşınca hücreler net kalsın
    cizim.drawImage(resim, (x0 - kb.x) * ox, (y0 - kb.y) * oy, (x1 - x0) * ox, (y1 - y0) * oy,
      x0 - kx, y0 - ky, x1 - x0, y1 - y0);
    return tuval;
  },
});

/* İl sınırı poligon değil, kenar ÇİZGİSİ olarak çizilir. Leaflet poligonu
   ekranın biraz dışından kırpar ve kırpma kutusunun kenarlarını da poligonun
   parçası olarak çizer; içi boş poligonda bu kenarlar çizgi olarak görünür.
   Durağan hâlde ekran dışında kalırlar, ama uzaklaştırma ve kaydırma sırasında
   ekrana girer: haritada kayan düz "sınır" çizgileri. Çizgi kırpılınca yalnız
   kesilir, kutu kenarı eklenmez. */
export function kenarCizgileri(geo) {
  const halkalar = [];
  for (const oge of geo.features) {
    const g = oge.geometry;
    const poligonlar = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
    for (const p of poligonlar) halkalar.push(...p);
  }
  return { type: 'Feature', properties: {}, geometry: { type: 'MultiLineString', coordinates: halkalar } };
}

/**
 * Haritayı kurar. Dönüş:
 *   harita            Leaflet haritası (sekmeler kendi katmanlarını ekler)
 *   suGoster(anahtar) senaryonun su derinliği katmanı; null → gizle
 *   suAcik()          su katmanı görünüyor mu
 *   sigdir(sinir, enCokYakin)  görünümü, panelin örtmediği alana sığdırır
 *   ilGorunumu()      bütün il
 */
export function haritaKur(kapsayici, panel, vitrin) {
  // fadeAnimation kapalı: karo belirme animasyonu requestAnimationFrame ister;
  // sayfa arka planda açılınca (yeni sekmede link) bu durur, Leaflet eski
  // yakınlaştırma düzeyinin karolarını silmez ve saydam yer adı katmanında
  // dev, bulanık bir "İzmir" yazısı kalır
  // zoomSnap: il, tam sayı düzeye yuvarlanmadan panelin yanındaki alanı doldursun
  const harita = L.map(kapsayici, { zoomControl: false, minZoom: 7, maxZoom: 18, zoomSnap: 0.25, fadeAnimation: false });
  L.control.zoom({ position: 'topright' }).addTo(harita);
  L.tileLayer(`${ESRI}/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    { maxNativeZoom: 16, maxZoom: 18, attribution: ATIF }).addTo(harita);
  // yer adları su katmanının üstünde kalsın
  harita.createPane('etiket').style.zIndex = 450;
  harita.getPane('etiket').style.pointerEvents = 'none';
  L.tileLayer(`${ESRI}/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
    { maxNativeZoom: 16, maxZoom: 18, pane: 'etiket' }).addTo(harita);

  const ilSiniri = L.latLngBounds(vitrin.bounds);
  jsonOku(IL_SINIRI).then((geo) =>
    L.geoJSON(kenarCizgileri(geo), { style: { color: '#475569', weight: 1.2 }, interactive: false }).addTo(harita))
    .catch((hata) => console.warn('İl sınırı yüklenemedi:', hata));

  const su = new SuKatmani(vitrin.bounds, { opacity: 0.85, zIndex: 2, updateWhenZooming: false, keepBuffer: 1 });
  let suAnahtari = null;

  /** Panelin (masaüstünde solda, mobilde altta) örttüğü kısım kadar dolgu. */
  function dolgu() {
    const kutu = panel.getBoundingClientRect();
    const gorunur = !panel.classList.contains('kapali') && kutu.width > 0;
    if (!gorunur) return { paddingTopLeft: [24, 24], paddingBottomRight: [24, 24] };
    if (window.innerWidth <= DAR_EKRAN) {
      return { paddingTopLeft: [16, 16], paddingBottomRight: [16, kapsayici.clientHeight - (kutu.top - kapsayici.getBoundingClientRect().top) + 12] };
    }
    return { paddingTopLeft: [kutu.right - kapsayici.getBoundingClientRect().left + 20, 24], paddingBottomRight: [56, 40] };
  }

  const api = {
    harita,
    suGoster(anahtar) {
      suAnahtari = anahtar;
      if (!anahtar) { harita.removeLayer(su); return; }
      su.setUrl(senaryoGorseli(anahtar));
      if (!harita.hasLayer(su)) su.addTo(harita);
    },
    suAcik: () => suAnahtari !== null,
    sigdir(sinir, enCokYakin = 16) {
      harita.fitBounds(L.latLngBounds(sinir), { maxZoom: enCokYakin, ...dolgu() });
    },
    ilGorunumu() { api.sigdir(ilSiniri, 11); },
  };
  api.ilGorunumu();
  return api;
}
