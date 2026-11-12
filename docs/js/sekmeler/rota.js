// Sekme: tahliye rotası örneği. Aynı başlangıçtan en yakın toplanma alanına
// araç rotası; yağış yokken ve olay senaryolarında (önceden hesaplanmış).
import { T, sayi } from '../cekirdek/dil.js';
import { senaryoAdi, alanAdi, baslik, kacis } from '../cekirdek/bicim.js';
import { secimHtml, secimDinle, lejantOgesi, suLejanti } from '../cekirdek/arayuz.js';

const ROTA_RENGI = '#4f46e5', ALAN_RENGI = '#059669';

export function rotaSekmesi({ vitrin, harita }) {
  const durum = { sira: 1 };          // 0: yağış yok, 1..: olay senaryoları
  let icerik = null, katman = null;

  const secenekAdi = (rota) => (rota.senaryo ? senaryoAdi(rota.senaryo) : T('Yağış yok', 'No rain'));

  function suMetni(rota) {
    if (!rota.su) return T('Yağış yokken en yakın toplanma alanına giden yol.', 'The way to the nearest assembly area with no rain.');
    if (rota.su.derin_yer) {
      return T(`Kuru bir yol yok: rota ${rota.su.derin_yer} yerde 30 cm'den derin sudan geçiyor (en derin ${sayi(rota.su.en_derin_m, 1)} m).`,
               `No dry way: the route crosses water deeper than 30 cm at ${rota.su.derin_yer} place(s) (deepest ${sayi(rota.su.en_derin_m, 1)} m).`);
    }
    const sig = rota.su.sig_yer ? T(` Yalnız ${rota.su.sig_yer} yerde ${sayi(rota.su.en_derin_m * 100)} cm'lik sığ sudan geçiyor.`,
                                    ` It crosses ${sayi(rota.su.en_derin_m * 100)} cm of shallow water at ${rota.su.sig_yer} place(s) only.`) : '';
    return T('Rota 30 cm\'den derin sudan geçmiyor.', 'The route avoids water deeper than 30 cm.') + sig;
  }

  function rotayiCiz() {
    const rota = vitrin.rotalar[durum.sira], bas = vitrin.rota_baslangic;
    if (katman) harita.harita.removeLayer(katman);
    const cizgi = rota.cizgi.map((parca) => parca.map(([boylam, enlem]) => [enlem, boylam]));
    katman = L.featureGroup([
      L.polyline(cizgi, { color: '#fff', weight: 9, opacity: 0.95, interactive: false }),
      L.polyline(cizgi, { color: ROTA_RENGI, weight: 5, interactive: false }),
      L.circleMarker([bas.lat, bas.lon], { radius: 7, color: '#fff', weight: 2, fillColor: ROTA_RENGI, fillOpacity: 1 })
        .bindTooltip(T('Başlangıç', 'Start'), { permanent: true, direction: 'top', offset: [0, -6] }),
      L.circleMarker([rota.hedef.lat, rota.hedef.lon], { radius: 8, color: '#fff', weight: 2, fillColor: ALAN_RENGI, fillOpacity: 1 })
        .bindTooltip(T('Toplanma alanı', 'Assembly area'), { permanent: true, direction: 'top', offset: [0, -6] }),
    ]).addTo(harita.harita);
    harita.suGoster(rota.senaryo);
    harita.sigdir(katman.getBounds().pad(0.2), 15);
  }

  function ciz() {
    const rota = vitrin.rotalar[durum.sira], ilk = vitrin.rotalar[0];
    icerik.innerHTML = `
      <h2>${T('Tahliye rotası', 'Evacuation route')}</h2>
      <p>${T(`${kacis(vitrin.rota_baslangic.ad)}'da aynı noktadan en yakın toplanma alanına araç rotası. Yağışı değiştir, rotanın nasıl değiştiğini gör.`,
             `A drive route from one point in ${kacis(vitrin.rota_baslangic.ad)} to the nearest assembly area. Change the rain and watch the route change.`)}</p>
      ${secimHtml('rota', vitrin.rotalar.map((r, i) => [i, secenekAdi(r)]), durum.sira)}
      <div class="sayilar">
        <div><b>${sayi(rota.km, 1)} km</b><span>${T('rota uzunluğu', 'route length')}</span></div>
        <div><b>${rota.senaryo ? `+${sayi(rota.km - ilk.km, 1)} km` : '–'}</b><span>${T('yağışsız rotaya göre', 'versus no rain')}</span></div>
      </div>
      <p><b>${alanAdi(rota.hedef)}</b> · ${kacis(baslik(rota.hedef.ilce))} / ${kacis(baslik(rota.hedef.mahalle))}</p>
      <p>${suMetni(rota)}</p>
      <h3>${T('Rota nasıl hesaplanıyor?', 'How is the route computed?')}</h3>
      <ul>
        <li>${T("30 cm'den derin su olan yol kapalı sayılır.", 'Roads under more than 30 cm of water count as closed.')}</li>
        <li>${T('Su altındaki ya da düz ovadaki toplanma alanı hedef seçilmez.', 'Assembly areas under water or on a flat plain are never chosen.')}</li>
        <li>${T('Eğim, son 24 saatin depremleri ve trafik de maliyete girer.', 'Slope, earthquakes of the last 24 hours and traffic also add cost.')}</li>
        <li>${T('Kuru yol yoksa rota yine çizilir ve suya nerede girdiği söylenir.', 'If no dry way exists the route is still drawn and says where it enters water.')}</li>
      </ul>
      <div class="kutu not">${T('Sel anında resmi tavsiye çoğu zaman yola çıkmamak ve yüksekte kalmaktır. Bu rota bir "ne yapmalı" tavsiyesi değil; hangi yolların ve alanların kullanılamaz hale geldiğini gösteren bir planlama aracıdır.',
                                 'During a flood the official advice is usually to stay put on high ground. This route is not advice on what to do; it is a planning aid that shows which roads and areas become unusable.')}</div>
      <p class="kucuk">${T('Rotalar önceden hesaplanmıştır (PostGIS + pgRouting, 920 bin yol parçası). Haritaya tıklayarak herhangi bir noktadan rota alma özelliği sunuculu sürümde çalışır; kaynak kodda.',
                           'Routes are precomputed (PostGIS + pgRouting, 920k road segments). Click-anywhere routing runs in the server version; see the source code.')}</p>`;
  }

  return {
    id: 'rota',
    baslik: () => T('Rota', 'Route'),
    goster(yeniIcerik) {
      icerik = yeniIcerik;
      secimDinle(icerik, (grup, deger) => { durum.sira = Number(deger); ciz(); rotayiCiz(); });
      ciz();
      rotayiCiz();
    },
    gizle() {
      if (katman) harita.harita.removeLayer(katman);
      katman = null;
      harita.suGoster(null);
    },
    ciz() { ciz(); rotayiCiz(); },     // dil değişince haritadaki etiketler de yenilenir
    lejant: () => lejantOgesi(ROTA_RENGI, T('rota', 'route'), 'cizgi') + lejantOgesi(ALAN_RENGI, T('toplanma alanı', 'assembly area'), 'daire')
      + (harita.suAcik() ? suLejanti(vitrin.siniflar) : ''),
  };
}
