// Sekme: toplanma alanı denetimi. 2.380 alanın yerinde kontrol için
// önceliklendirilmesi (hesap/toplanma_denetimi.py). Ön eleme listesidir.
import { T, sayi } from '../cekirdek/dil.js';
import { alanAdi, baslik, kacis, mesafe } from '../cekirdek/bicim.js';
import { sayiKutulari, lejantOgesi } from '../cekirdek/arayuz.js';
import { DENETIM_CSV } from '../cekirdek/veri.js';

// nokta kodu (denetim.json): 0 işaretsiz, 1–3 öncelik, 4 düz ova
const RENK = ['#10b981', '#b91c1c', '#ea580c', '#eab308', '#94a3b8'];
const CIZIM_SIRASI = [0, 4, 3, 2, 1];     // işaretsizler altta, öncelikliler üstte

export function denetimSekmesi({ denetim, harita }) {
  const durum = { arama: '' };
  let icerik = null, katman = null, vurgu = null;
  const isaretler = new Map();      // liste sırası → tıklanabilir işaret

  const kunye = (alan) => `${kacis(baslik(alan.ilce))} / ${kacis(baslik(alan.mahalle))}${alan.yol ? ` · ${kacis(alan.yol)}` : ''}`;

  const acilir = (alan) => `<b>${alanAdi(alan)}</b> <span class="rozet oncelik-${alan.oncelik}">${T(`${alan.oncelik}. öncelik`, `priority ${alan.oncelik}`)}</span><br>
    ${kunye(alan)}<br>
    <span class="soluk">${T('Su aldığı en küçük yağış', 'Smallest rain that floods it')}:</span> ${alan.en_kucuk_yagis_mm} mm / ${alan.en_kucuk_yagis_saat} ${T('saat', 'h')}<br>
    <span class="soluk">${T('2021 benzeri yağışta su', 'Depth in 2021-like rain')}:</span> ${alan.su_m > 0 ? `${sayi(alan.su_m, 1)} m` : '–'}<br>
    <span class="soluk">${T("OSM'de çizili en yakın dere", 'Nearest stream drawn in OSM')}:</span> ${mesafe(alan.dereye_m)}`;

  function katmanlariKur() {
    const tuval = L.canvas({ padding: 0.3 });
    katman = L.layerGroup();
    CIZIM_SIRASI.forEach((kod) => denetim.noktalar.filter((n) => n[2] === kod).forEach((n) =>
      katman.addLayer(L.circleMarker([n[0], n[1]], {
        renderer: tuval, interactive: false, radius: kod === 0 ? 2.5 : 4,
        color: '#fff', weight: kod === 0 ? 0 : 1, fillColor: RENK[kod], fillOpacity: kod === 0 ? 0.45 : 0.95,
      }))));
    // 1. ve 2. öncelikli alanlar tıklanabilir, daha büyük işaretlerle
    denetim.liste.forEach((alan, sira) => {
      const isaret = L.circleMarker([alan.lat, alan.lon], {
        radius: 7, color: '#fff', weight: 1.5, fillColor: RENK[alan.oncelik], fillOpacity: 1,
      }).bindPopup(() => acilir(alan), { maxWidth: 280 });
      isaretler.set(sira, isaret);
      katman.addLayer(isaret);
    });
  }

  function listeHtml() {
    const aranan = durum.arama.toLocaleLowerCase('tr').trim();
    const uyan = denetim.liste.map((alan, sira) => ({ alan, sira })).filter(({ alan }) =>
      !aranan || `${alan.ilce} ${alan.mahalle} ${alan.yol || ''} ${alan.adi}`.toLocaleLowerCase('tr').includes(aranan));
    if (!uyan.length) return `<li class="pasif">${T('Eşleşen alan yok.', 'No matching area.')}</li>`;
    return uyan.map(({ alan, sira }) => `
      <li data-alan-sira="${sira}" tabindex="0" role="button">
        <div><span class="rozet oncelik-${alan.oncelik}">${alan.oncelik}</span> <b>${alanAdi(alan)}</b></div>
        <div class="soluk">${kunye(alan)}</div>
        <div class="soluk">${alan.en_kucuk_yagis_mm} mm / ${alan.en_kucuk_yagis_saat} ${T('saat', 'h')}${alan.su_m > 0 ? ` · ${sayi(alan.su_m, 1)} m` : ''} · ${T('dereye', 'to stream')} ${mesafe(alan.dereye_m)}</div>
      </li>`).join('');
  }

  function ciz() {
    const s = denetim.sayim, y = denetim.dere_yakin;
    const pay = (grup) => sayi((grup.yakin / grup.toplam) * 100);
    icerik.innerHTML = `
      <h2>${T('Toplanma alanı denetimi', 'Assembly-area audit')}</h2>
      <p>${T(`İzmir Büyükşehir Belediyesi'nin ${sayi(denetim.toplam)} afet ve acil durum toplanma alanını modelin su derinliğiyle tek tek karşılaştırdım. Çıktı bir <b>ön eleme listesi</b>: "şu alanlar güvensiz" demiyor, "yerinde ilk önce şunlara bakın" diyor.`,
             `I compared each of the municipality's ${sayi(denetim.toplam)} emergency assembly areas with the modelled water depth. The output is a <b>screening list</b>: it does not say "these are unsafe", it says "check these on site first".`)}</p>
      ${sayiKutulari([
        [sayi(s['1']), T('1. öncelik', 'priority 1')], [sayi(s['2']), T('2. öncelik', 'priority 2')],
        [sayi(s['3']), T('3. öncelik', 'priority 3')], [sayi(s.ova), T('düz ovada', 'on flat plain')],
      ])}
      <div class="tablo-sar"><table>
        <tr><th></th><th>${T("Alanın bulunduğu yerde 30 cm'den derin su", 'More than 30 cm of water at the area')}</th></tr>
        <tr><td><span class="rozet oncelik-1">1</span></td><td>${T("Yağış 24 saate yayılsa bile 100 mm ya da daha azında: şiddetli sağanak gerekmeden su alıyor.", 'At 100 mm or less even spread over 24 hours: floods without an intense downpour.')}</td></tr>
        <tr><td><span class="rozet oncelik-2">2</span></td><td>${T("2 Şubat 2021'e yakın yağışta (100 mm / 6 saat ya da 150 mm / 24 saat).", 'In rain close to 2 February 2021 (100 mm / 6 h or 150 mm / 24 h).')}</td></tr>
        <tr><td><span class="rozet oncelik-3">3</span></td><td>${T('Yalnız daha şiddetli senaryolarda.', 'Only in more severe scenarios.')}</td></tr>
      </table></div>
      <h3>${T('1. ve 2. öncelikli alanlar', 'Priority 1 and 2 areas')} (${denetim.liste.length})</h3>
      <input type="search" id="den-ara" placeholder="${T('İlçe, mahalle ya da sokak ara', 'Search district, neighbourhood or street')}" value="${kacis(durum.arama)}" aria-label="${T('Alan ara', 'Search areas')}">
      <ul class="liste kaydir" data-yer="liste">${listeHtml()}</ul>
      <p><a href="${DENETIM_CSV}" download>${T('İşaretli bütün alanları indir (CSV)', 'Download all flagged areas (CSV)')}</a></p>
      <div class="kutu not"><b>${T('Bu liste nasıl okunmalı?', 'How to read this list')}</b>
        <ul>
          <li>${T('<b>Model burada kanıt değil, işaret.</b> Aynı model 2021 selinde su basan mahalleleri ayırt edemedi. Liste, sahada bakılacak yerleri daraltmak içindir.',
                   '<b>The model is a pointer here, not evidence.</b> It could not single out the neighbourhoods flooded in 2021. The list narrows down where to look on site.')}</li>
          <li>${T('<b>Her alan tek bir noktadır</b> ve su derinliği 60 m\'lik hücrelerden gelir. Büyük bir parkın yalnız bir köşesi dere kenarında olabilir.',
                   '<b>Each area is a single point</b> and depth comes from 60 m cells. Only one corner of a large park may lie next to a stream.')}</li>
          <li>${T(`<b>Bağımsız sağlama:</b> model dereleri yükseklik verisinden türetir, OpenStreetMap'i kullanmaz. Öncelikli ${y.oncelikli.toplam} alanın ${y.oncelikli.yakin} tanesi (%${pay(y.oncelikli)}) OSM'de çizili bir dereye ${denetim.dere_yakin_m} m'den yakın; öteki alanlarda bu oran %${pay(y.oteki)}. Öncelikli alanlar derelere belirgin biçimde daha yakın, ama çoğunun yanında haritada çizili bir dere yok.`,
                   `<b>Independent check:</b> the model derives streams from elevation and does not use OpenStreetMap. ${y.oncelikli.yakin} of the ${y.oncelikli.toplam} priority areas (${pay(y.oncelikli)}%) lie within ${denetim.dere_yakin_m} m of a waterway drawn in OSM, against ${pay(y.oteki)}% of the rest. Priority areas are clearly closer to streams, but most have no mapped stream nearby.`)}</li>
          <li>${T('<b>Kıyıdaki kanalizasyon taşkını listede yok.</b> Model onu göremiyor.', '<b>Coastal sewer flooding is not in the list.</b> The model cannot see it.')}</li>
        </ul></div>`;
    icerik.querySelector('#den-ara').addEventListener('input', (olay) => {
      durum.arama = olay.target.value;
      icerik.querySelector('[data-yer="liste"]').innerHTML = listeHtml();
    });
  }

  function alanaGit(sira) {
    const alan = denetim.liste[sira], isaret = isaretler.get(sira);
    if (vurgu) harita.harita.removeLayer(vurgu);
    vurgu = L.circleMarker([alan.lat, alan.lon], { radius: 14, color: '#1d4ed8', weight: 3, fill: false, interactive: false }).addTo(harita.harita);
    harita.sigdir([[alan.lat, alan.lon], [alan.lat, alan.lon]], 15);
    isaret.openPopup();
  }

  return {
    id: 'denetim',
    baslik: () => T('Denetim', 'Audit'),
    goster(yeniIcerik) {
      icerik = yeniIcerik;
      if (!katman) katmanlariKur();
      const sec = (olay) => {
        const oge = olay.target.closest('[data-alan-sira]');
        if (oge && (olay.type === 'click' || olay.key === 'Enter')) alanaGit(Number(oge.dataset.alanSira));
      };
      icerik.addEventListener('click', sec);
      icerik.addEventListener('keydown', sec);
      ciz();
      katman.addTo(harita.harita);
      harita.ilGorunumu();
    },
    gizle() {
      harita.harita.closePopup();
      harita.harita.removeLayer(katman);
      if (vurgu) harita.harita.removeLayer(vurgu);
      vurgu = null;
    },
    ciz,
    lejant: () => [T('1. öncelik', 'priority 1'), T('2. öncelik', 'priority 2'), T('3. öncelik', 'priority 3'),
      T('düz ova', 'flat plain')].map((etiket, i) => lejantOgesi(RENK[i + 1], etiket, 'daire')).join('')
      + lejantOgesi(RENK[0], T('işaretlenmedi', 'not flagged'), 'daire'),
  };
}
