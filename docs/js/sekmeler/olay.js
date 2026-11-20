// Sekme: 2 Şubat 2021 seli. Haberlerde su bastığı yazılan yerler ile modelin
// karşılaştırması (hesap/sel_dogrulama.py → hesap/vitrin_hazirla.py).
import { T, sayi } from '../cekirdek/dil.js';
import { senaryoAdi, yerAdi, kacis, aralik, yuzde, yuzdeIsareti } from '../cekirdek/bicim.js';
import { secimDinle, senaryoSecimi, listeDinle, lejantOgesi, suLejanti } from '../cekirdek/arayuz.js';

const RENK = { yakalandi: '#047857', kacirildi: '#dc2626' };

export function olaySekmesi({ vitrin, harita }) {
  const durum = { senaryo: vitrin.olay_senaryolari[0] };
  let icerik = null, katman = null;
  const sekiller = new Map();      // yer sırası → Leaflet katmanı

  const turAdi = (tur) => ({
    mahalle: T('Mahalle', 'Neighbourhood'), cadde: T('Cadde', 'Street'),
    dere: T('Dere', 'Stream'), alt_gecit: T('Alt geçit', 'Underpass'),
  }[tur]);

  function modelSonucu(yer) {
    const o = yer.olcum[durum.senaryo];
    if (yer.tur === 'mahalle') {
      const sira = o.derin_yuzdelik >= 50 ? T(`en ıslak ${yuzdeIsareti(100 - o.derin_yuzdelik)}`, `wettest ${yuzdeIsareti(100 - o.derin_yuzdelik)}`)
        : T(`en kuru ${yuzdeIsareti(o.derin_yuzdelik)}`, `driest ${yuzdeIsareti(o.derin_yuzdelik)}`);
      return T(`alanın ${yuzde(o.derin_pay, 1)} kadarı ıslak; ${sira} içinde`, `${yuzde(o.derin_pay, 1)} of area wet; ${sira}`);
    }
    if (yer.tur === 'alt_gecit') return o.alt_gecit_dolu ? T('alt geçitler dolu', 'underpasses flooded') : T('alt geçitler kuru', 'underpasses dry');
    return o.en_derin_m > 0 ? T(`en derin nokta ${sayi(o.en_derin_m, 1)} m`, `deepest point ${sayi(o.en_derin_m, 1)} m`) : T('su yok', 'no water');
  }

  const rozet = (yer) => `<span class="rozet ${yer.yakalandi ? 'iyi' : 'kotu'}">${yer.yakalandi ? T('model de gösterdi', 'model shows it') : T('model göstermedi', 'model does not')}</span>`;

  const acilir = (yer) => `<b>${kacis(yerAdi(yer.ad))}</b> · ${kacis(yerAdi(yer.ilce))} ${rozet(yer)}<br>
    <span class="soluk">${T('Haber', 'Report')}:</span> ${kacis(yer.anlatim)}<br>
    <span class="soluk">Model (${senaryoAdi(durum.senaryo)}):</span> ${modelSonucu(yer)}<br>
    ${yer.kaynak.map((adres, i) => `<a href="${kacis(adres)}" target="_blank" rel="noopener">${T('kaynak', 'source')} ${i + 1}</a>`).join(' · ')}`;

  function katmanlariKur() {
    katman = L.layerGroup();
    vitrin.yerler.forEach((yer, sira) => {
      if (!yer.geometri) return;
      const renk = yer.yakalandi ? RENK.yakalandi : RENK.kacirildi;
      const sekil = L.geoJSON(yer.geometri, {
        style: yer.tur === 'mahalle' ? { color: renk, weight: 2, fillColor: renk, fillOpacity: 0.12 }
          : { color: renk, weight: 5, opacity: 0.9 },
      }).bindPopup(() => acilir(yer), { maxWidth: 290 });
      sekiller.set(sira, sekil);
      katman.addLayer(sekil);
    });
  }

  /** Doğrulama özeti: olaya yakın senaryolardaki puan aralıkları. */
  function sonucKutusu() {
    const d = vitrin.dogrulama_senaryolari.map((s) => vitrin.dogrulama[s]);
    const yakalanan = vitrin.yerler.filter((y) => y.yakalandi).length;
    const ilk = d[0];
    const haberCadde = d.map((x) => Math.round(x.cadde_kapali_oran.haber * x.cadde_sayisi.haber));
    return `<div class="kutu kotu">
      <b>${T(`Haberlerde su bastığı yazılan ${vitrin.yerler.length} yerden ${yakalanan} tanesinde model de su gösteriyor.`, `Of the ${vitrin.yerler.length} places the news reported as flooded, the model also shows water at ${yakalanan}.`)}</b>
      <ul>
        <li>${T(`<b>Mahalle puanı ${aralik(d.map((x) => x.mahalle_auc_yalniz_derinlik))}:</b> model, su basan ${ilk.mahalle_sayisi.haber} mahalleyi aynı ilçelerin öteki ${ilk.mahalle_sayisi.oteki} mahallesinden ayırt edemiyor (0,5 yazı-tura, 1 kusursuz).`,
                 `<b>Neighbourhood score ${aralik(d.map((x) => x.mahalle_auc_yalniz_derinlik))}:</b> the model cannot tell the ${ilk.mahalle_sayisi.haber} flooded neighbourhoods from the other ${ilk.mahalle_sayisi.oteki} in the same districts (0.5 is a coin toss, 1 is perfect).`)}</li>
        <li>${T(`<b>Cadde puanı ${aralik(d.map((x) => x.cadde_auc))}:</b> zayıf bir işaret. 30 cm+ su görülen haber caddesi: ${aralik(haberCadde, 0)} / ${ilk.cadde_sayisi.haber}; öteki ${ilk.cadde_sayisi.oteki} caddede bu oran %${aralik(d.map((x) => x.cadde_kapali_oran.oteki * 100), 0)}.`,
                 `<b>Street score ${aralik(d.map((x) => x.cadde_auc))}:</b> a weak signal. ${aralik(haberCadde, 0)} of the ${ilk.cadde_sayisi.haber} reported streets have 30 cm+ water, against ${aralik(d.map((x) => x.cadde_kapali_oran.oteki * 100), 0)}% of the other ${ilk.cadde_sayisi.oteki}.`)}</li>
      </ul></div>`;
  }

  function merkezTablosu() {
    const m = vitrin.merkez;
    const satir = (etiket, alan, kesir = 0, birim = '') => `<tr><td>${etiket}</td>${vitrin.olay_senaryolari.map((s) =>
      `<td class="s">${sayi(m.senaryolar[s][alan], kesir)}${birim}</td>`).join('')}</tr>`;
    return `<h3>${T('Aynı yağış yeniden yağsa', 'If the same rain fell again')}</h3>
      <p class="kucuk">${T(`Su basan ${m.ilceler.length} merkez ilçede (${sayi(m.km2)} km², ${sayi(m.toplanma)} toplanma alanı) modelin gösterdiği:`,
                           `What the model shows for the ${m.ilceler.length} central districts that flooded (${sayi(m.km2)} km², ${sayi(m.toplanma)} assembly areas):`)}</p>
      <div class="tablo-sar"><table>
        <tr><th></th>${vitrin.olay_senaryolari.map((s) => `<th class="s">${senaryoAdi(s)}</th>`).join('')}</tr>
        ${satir(T("30 cm'den derin su", 'Water deeper than 30 cm'), 'su_30_km2', 1, ' km²')}
        ${satir(T("10 cm'den derin su", 'Water deeper than 10 cm'), 'su_10_km2', 1, ' km²')}
        ${satir(T('Düz ova, derinlik belirsiz', 'Flat plain, depth unknown'), 'belirsiz_km2', 1, ' km²')}
        ${satir(T('Su altında toplanma alanı', 'Assembly areas under water'), 'toplanma_su')}
        ${satir(T('Düz ovadaki toplanma alanı', 'Assembly areas on flat plain'), 'toplanma_belirsiz')}
        ${satir(T('30 cm+ su noktası olan yol parçası', 'Road segments with a 30 cm+ point'), 'yol_parcasi_su')}
      </table></div>`;
  }

  function ciz() {
    icerik.innerHTML = `
      <h2>${T('2 Şubat 2021 seli', '2 February 2021 flood')}</h2>
      <p>${T('Haberlerde su bastığı yazılan yerleri kaynaklarıyla derledim ve modelin gösterdiğiyle karşılaştırdım. Mavi katman modelin su derinliği.',
             'I compiled the places the news reported as flooded, with sources, and compared them with the model. The blue layer is modelled depth.')}</p>
      ${sonucKutusu()}
      <div class="alan-baslik">${T('Olaya yakın senaryo', 'Scenario close to the event')}</div>
      ${senaryoSecimi('senaryo', vitrin.olay_senaryolari, durum.senaryo)}
      <ul class="liste">${vitrin.yerler.map((yer, sira) => `
        <li ${yer.geometri ? `data-yer-sira="${sira}" tabindex="0" role="button"` : 'class="pasif"'}>
          <div><b>${kacis(yerAdi(yer.ad))}</b> ${rozet(yer)}</div>
          <div class="soluk">${turAdi(yer.tur)} · ${kacis(yerAdi(yer.ilce))} · ${modelSonucu(yer)}</div>
        </li>`).join('')}</ul>
      <p class="kucuk">${T('"Model de gösterdi" ne demek: mahalle, modelin en ıslak gösterdiği %25 mahalle arasında; cadde ya da dere hattında modelde 30 cm\'den derin su olan bir nokta var. Konak Alt Geçidi OpenStreetMap\'te adıyla bulunmadığı için haritada yok.',
                           '"Model shows it" means: the neighbourhood is among the 25% the model shows wettest; the street or stream has a point under more than 30 cm of water in the model. The Konak underpass is not named in OpenStreetMap, so it is not on the map.')}</p>
      <div class="kutu not"><b>${T('Model neden bazı yerlerde su göstermedi?', 'Why does the model show no water at some places?')}</b>
        <ul>
          <li>${T('<b>Kıyıdaki kanalizasyon taşkını:</b> su dereden değil, dolan şebekeden geldi. Modelde şebeke yok.',
                   '<b>Coastal sewer flooding:</b> the water came from a surcharged network, not a stream. The model has no sewer network.')}</li>
          <li>${T('<b>Küçük kent dereleri:</b> 60 m\'lik yükseklik verisi, kapatılmış ya da beton kanala alınmış dar dereleri ayırt edemiyor.',
                   '<b>Small urban creeks:</b> 60 m elevation data cannot resolve narrow, culverted or channelised creeks.')}</li>
        </ul>
        <button type="button" class="baglanti" data-hakkinda="dogrulama">${T('Yöntem ve ayrıntılar', 'Method and details')} →</button>
      </div>
      ${merkezTablosu()}`;
  }

  function yereGit(sira) {
    const sekil = sekiller.get(sira);
    if (!sekil) return;
    harita.sigdir(sekil.getBounds(), 15);
    sekil.openPopup(sekil.getBounds().getCenter());
  }

  return {
    id: 'olay',
    baslik: () => T('2021 seli', '2021 flood'),
    goster(yeniIcerik) {
      icerik = yeniIcerik;
      if (!katman) katmanlariKur();
      secimDinle(icerik, (grup, deger) => {
        durum.senaryo = deger;
        harita.suGoster(durum.senaryo);
        ciz();
      });
      listeDinle(icerik, 'data-yer-sira', (sira) => yereGit(Number(sira)));
      ciz();
      harita.suGoster(durum.senaryo);
      katman.addTo(harita.harita);
      harita.sigdir(L.featureGroup([...sekiller.values()]).getBounds(), 13);
    },
    gizle() {
      harita.harita.closePopup();
      harita.harita.removeLayer(katman);
      harita.suGoster(null);
    },
    ciz,
    lejant: () => lejantOgesi(RENK.yakalandi, T('haberde su bastı, model de gösterdi', 'reported flooded, model shows it')) + lejantOgesi(RENK.kacirildi, T('haberde su bastı, model göstermedi', 'reported flooded, model does not')) + suLejanti(vitrin.siniflar),
  };
}
