// Sekme: tahliye rotası. Kullanıcı haritada bir nokta seçer (ya da işaretçiyi
// sürükler) ve yağışı değiştirir; tarayıcı, merkez ilçelerin yol ağında su
// basan yollardan kaçarak en yakın açık toplanma alanına araç rotasını o anda
// hesaplar (js/cekirdek/rota_motoru.js). Sunucu gerekmez.
import { T, sayi } from '../cekirdek/dil.js';
import { senaryoAdi, alanAdi, baslik, kacis, mesafe, yerAdi } from '../cekirdek/bicim.js';
import { secimHtml, secimDinle, sayiKutulari, lejantOgesi, suLejanti } from '../cekirdek/arayuz.js';
import { ROTA_AGI, jsonOku, rotaSuyu } from '../cekirdek/veri.js';
import { kenarCizgileri } from '../cekirdek/harita.js';
import { agKur, suKur, enYakinDugum, rotaBul, rotaCizgisi, rotaOzeti } from '../cekirdek/rota_motoru.js';

const ROTA_RENGI = '#4f46e5', KURU_RENGI = '#64748b', ALAN_RENGI = '#059669';

export function rotaSekmesi({ vitrin, harita }) {
  const [ilkMm, ilkSaat] = vitrin.olay_senaryolari[0].split('_').map(Number);
  // sira 0: yağış yok; 1..: vitrin.yagis_mm[sira - 1]
  const durum = { sira: vitrin.yagis_mm.indexOf(ilkMm) + 1, saat: ilkSaat,
    bas: { lon: vitrin.rota_baslangic.lon, lat: vitrin.rota_baslangic.lat } };
  const suOnbellek = new Map();
  let ag = null, agSozu = null, icerik = null, katman = null, kapsam = null, isaretci = null;
  let sonuc = null, istekNo = 0, kare = 0, ilkSigdirma = true;

  const anahtar = () => (durum.sira ? `${vitrin.yagis_mm[durum.sira - 1]}_${durum.saat}` : null);
  const altGecitDolu = (a) => Boolean(a && vitrin.senaryolar[a]?.alt_gecit_dolu);

  function agYukle() {
    agSozu ??= jsonOku(ROTA_AGI).then((ham) => { ag = agKur(ham); return ag; });
    return agSozu;
  }
  function suYukle(a) {
    if (!suOnbellek.has(a)) suOnbellek.set(a, jsonOku(rotaSuyu(a)).then((ham) => suKur(ag, ham)));
    return suOnbellek.get(a);
  }

  /** Veri hazırsa rotayı hemen hesaplar (sürüklerken her karede çağrılır). */
  function hesapla(su) {
    const t0 = performance.now();
    const a = anahtar(), dolu = altGecitDolu(a);
    const yakin = enYakinDugum(ag, durum.bas.lon, durum.bas.lat);
    if (!yakin) { sonuc = { disarida: true }; return; }
    const rota = rotaBul(ag, yakin.dugum, su, dolu);
    const kuru = su ? rotaBul(ag, yakin.dugum, null) : rota;
    if (!rota) { sonuc = { alanYok: true, yakin }; return; }
    sonuc = { yakin, rota, kuru, su, a, ozet: rotaOzeti(ag, rota, su, dolu), kuruOzet: rotaOzeti(ag, kuru),
      ms: performance.now() - t0 };
  }

  /** Yağış ya da başlangıç değişince: gereken dosyalar gelince hesapla, çiz. */
  async function yenile() {
    const no = ++istekNo;
    const a = anahtar();
    harita.suGoster(a);
    try {
      await agYukle();
      const su = a ? await suYukle(a) : null;
      if (no !== istekNo || !icerik) return;          // bu arada başka seçim yapıldı
      hesapla(su);
    } catch (hata) {
      console.error(hata);
      sonuc = { hata: true };
    }
    if (no !== istekNo || !icerik) return;
    haritayaCiz();
    sonucCiz();
  }

  function suMetni(s) {
    const o = s.ozet, parcalar = [];
    if (o.derinParca) {
      parcalar.push(T(`<b>Kuru yol yok:</b> rota ${o.derinParca} yol parçasında 30 cm'den derin sudan geçiyor (en derin ${sayi(o.enDerinM, 1)} m).`,
                      `<b>No dry way:</b> the route crosses water deeper than 30 cm on ${o.derinParca} road segment(s) (deepest ${sayi(o.enDerinM, 1)} m).`));
    } else if (s.a) {
      parcalar.push(T("Rota 30 cm'den derin sudan geçmiyor.", 'The route avoids water deeper than 30 cm.'));
    }
    if (o.sigParca) {
      parcalar.push(T(`${o.sigParca} yol parçasında sığ su ya da derinliği bilinmeyen düz ova var.`,
                      `${o.sigParca} road segment(s) have shallow water or flat plain of unknown depth.`));
    }
    if (o.altGecit) {
      parcalar.push(T(`${o.altGecit} dolu alt geçitten geçiyor.`, `It passes through ${o.altGecit} flooded underpass(es).`));
    }
    return parcalar.join(' ');
  }

  function karsilastirma(s) {
    if (!s.a) return T('Yağış yokken en yakın toplanma alanına giden yol.', 'The way to the nearest assembly area with no rain.');
    const ayniAlan = s.rota.alan.id === s.kuru.alan.id;
    const fark = s.ozet.metre - s.kuruOzet.metre;
    if (s.su.kapaliAlan.has(s.kuru.alan.id)) {
      return T(`Yağışsız günde gidilecek alan (${alanAdi(s.kuru.alan)}) bu yağışta su altında: rota başka bir alana gidiyor.`,
               `The area used on a dry day (${alanAdi(s.kuru.alan)}) is under water in this rain: the route goes to another area.`);
    }
    if (ayniAlan && Math.abs(fark) < 50) return T('Bu yağışta rota değişmiyor.', 'This rain does not change the route.');
    if (ayniAlan) {
      return T(`Su basan yollardan kaçmak için rota ${mesafe(Math.abs(fark))} ${fark > 0 ? 'uzuyor' : 'kısalıyor'} (kesikli gri çizgi: yağışsız rota).`,
               `Avoiding flooded roads makes the route ${mesafe(Math.abs(fark))} ${fark > 0 ? 'longer' : 'shorter'} (dashed grey line: dry-day route).`);
    }
    return T('Yağışsız günün yolu ıslak: rota başka bir toplanma alanına yöneliyor (kesikli gri çizgi: yağışsız rota).',
             'The dry-day way is wet: the route turns to another assembly area (dashed grey line: dry-day route).');
  }

  function sonucCiz() {
    const kutu = icerik?.querySelector('[data-yer="sonuc"]');
    if (!kutu) return;
    const s = sonuc;
    if (!s) { kutu.innerHTML = `<p class="kucuk">${T('Yol ağı yükleniyor…', 'Loading the road network…')}</p>`; return; }
    if (s.hata) { kutu.innerHTML = `<p class="kutu kotu">${T('Yol ağı yüklenemedi.', 'The road network failed to load.')}</p>`; return; }
    if (s.disarida) {
      kutu.innerHTML = `<p class="kutu not">${T('Bu nokta rota ağının dışında. Ağ, kesikli çizgiyle gösterilen merkez 11 ilçeyi kapsar; içinde bir yere tıkla.',
        'This point is outside the road network. It covers the 11 central districts inside the dashed line; click somewhere inside.')}</p>`;
      return;
    }
    if (s.alanYok) {
      kutu.innerHTML = `<p class="kutu kotu">${T('Bu yağışta ulaşılabilen açık toplanma alanı yok.', 'No open assembly area is reachable in this rain.')}</p>`;
      return;
    }
    const alan = s.rota.alan;
    const ekstra = s.a ? `${s.ozet.metre - s.kuruOzet.metre >= 0 ? '+' : '−'}${mesafe(Math.abs(s.ozet.metre - s.kuruOzet.metre))}` : '–';
    kutu.innerHTML = `
      ${sayiKutulari([[mesafe(s.ozet.metre), T('rota uzunluğu', 'route length')], [ekstra, T('yağışsız rotaya göre', 'versus a dry day')]])}
      <p><b>${kacis(alanAdi(alan))}</b> · ${kacis(baslik(yerAdi(alan.ilce)))} / ${kacis(baslik(alan.mahalle))}</p>
      <p>${karsilastirma(s)}</p>
      ${s.a ? `<p>${suMetni(s)}</p>` : ''}
      ${s.yakin.metre > 150 ? `<p class="kucuk">${T(`Seçilen nokta en yakın yola bağlandı (${mesafe(s.yakin.metre)}).`, `The chosen point was joined to the nearest road (${mesafe(s.yakin.metre)}).`)}</p>` : ''}
      <p class="kucuk">${T(`Rota tarayıcında ${sayi(Math.max(s.ms, 1))} ms'de hesaplandı.`, `Route computed in your browser in ${sayi(Math.max(s.ms, 1))} ms.`)}</p>`;
  }

  function haritayaCiz() {
    const h = harita.harita;
    if (katman) h.removeLayer(katman);
    katman = null;
    const s = sonuc;
    if (!s || !s.rota) return;
    const enBo = (cizgi) => cizgi.map(([boylam, enlem]) => [enlem, boylam]);
    const cizgi = enBo(rotaCizgisi(ag, s.rota));
    const parcalar = [];
    if (s.a && (s.kuru.alan.id !== s.rota.alan.id || Math.abs(s.ozet.metre - s.kuruOzet.metre) >= 50)) {
      parcalar.push(L.polyline(enBo(rotaCizgisi(ag, s.kuru)), { color: KURU_RENGI, weight: 4, dashArray: '2 8', lineCap: 'round', interactive: false }));
      if (s.kuru.alan.id !== s.rota.alan.id) {
        parcalar.push(L.circleMarker([s.kuru.alan.lat, s.kuru.alan.lon], { radius: 5, color: '#fff', weight: 2, fillColor: KURU_RENGI, fillOpacity: 1 })
          .bindTooltip(`${kacis(alanAdi(s.kuru.alan))} · ${T('yağışsız günün hedefi', 'dry-day target')}`, { direction: 'top', offset: [0, -4] }));
      }
    }
    const dugum = s.rota.dugumler[0];
    parcalar.push(
      L.polyline([[durum.bas.lat, durum.bas.lon], [ag.lat[dugum], ag.lon[dugum]]], { color: ROTA_RENGI, weight: 2, dashArray: '4 5', interactive: false }),
      L.polyline(cizgi, { color: '#fff', weight: 9, opacity: 0.95, interactive: false }),
      L.polyline(cizgi, { color: ROTA_RENGI, weight: 5, interactive: false }),
      L.circleMarker([s.rota.alan.lat, s.rota.alan.lon], { radius: 8, color: '#fff', weight: 2, fillColor: ALAN_RENGI, fillOpacity: 1 })
        .bindTooltip(kacis(alanAdi(s.rota.alan)), { permanent: true, direction: 'top', offset: [0, -6] }));
    katman = L.featureGroup(parcalar).addTo(h);
    if (ilkSigdirma) {
      ilkSigdirma = false;
      harita.sigdir(katman.getBounds().extend([durum.bas.lat, durum.bas.lon]).pad(0.25), 15);
    }
  }

  function isaretciKur() {
    if (isaretci) return;
    isaretci = L.marker([durum.bas.lat, durum.bas.lon], {
      draggable: true, autoPan: true, zIndexOffset: 1000, keyboard: true, title: T('Başlangıç: sürükle', 'Start: drag me'),
      icon: L.divIcon({ className: 'rota-baslangic', iconSize: [22, 22], iconAnchor: [11, 11] }),
    }).bindTooltip(T('Başlangıç — sürükle', 'Start — drag me'), { direction: 'top', offset: [0, -10] });
    isaretci.on('drag', () => {
      const { lat, lng } = isaretci.getLatLng();
      durum.bas = { lon: lng, lat };
      // sürüklerken her karede bir kez: veri bellekteyse rota anında yenilenir
      if (kare) return;
      kare = requestAnimationFrame(() => {
        kare = 0;
        const a = anahtar();
        const su = a ? suOnbellek.get(a) : null;
        if (!ag || (a && !su)) return;
        (su || Promise.resolve(null)).then((suVeri) => { hesapla(suVeri); haritayaCiz(); sonucCiz(); });
      });
    });
    isaretci.on('dragend', yenile);
  }

  function haritaTiklandi(olay) {
    durum.bas = { lon: olay.latlng.lng, lat: olay.latlng.lat };
    isaretci.setLatLng(olay.latlng);
    yenile();
  }

  function kapsamCiz() {
    if (kapsam || !ag) return;
    kapsam = L.geoJSON(kenarCizgileri({ features: [{ geometry: ag.kapsam }] }),
      { style: { color: ROTA_RENGI, weight: 1.5, dashArray: '6 6', opacity: 0.7 }, interactive: false }).addTo(harita.harita);
  }

  /** Kaydırıcı ve süre düğmeleri değişince yalnız değişen kısımlar yenilenir. */
  function secimleriCiz() {
    icerik.querySelector('[data-yer="yagis"]').textContent = durum.sira
      ? `${vitrin.yagis_mm[durum.sira - 1]} mm` : T('yağış yok', 'no rain');
    icerik.querySelector('[data-yer="sure"]').innerHTML = durum.sira
      ? secimHtml('saat', vitrin.sure_sa.map((saat) => [saat, `${saat} ${T('saat', 'h')}`]), durum.saat) : '';
    icerik.querySelector('[data-yer="olay"]').innerHTML = secimHtml('olay',
      vitrin.olay_senaryolari.map((s) => [s, senaryoAdi(s)]), anahtar() ?? '');
  }

  function ciz() {
    icerik.innerHTML = `
      <h2>${T('Tahliye rotası', 'Evacuation route')}</h2>
      <p>${T('Haritada bir yere tıkla ya da mor işaretçiyi sürükle. Rota, seçtiğin yağışta su basan yollardan kaçarak en yakın açık toplanma alanına gider ve her değişiklikte yeniden hesaplanır.',
             'Click anywhere on the map or drag the purple marker. The route avoids the roads flooded by the chosen rain, goes to the nearest open assembly area, and is recomputed on every change.')}</p>
      <label class="alan-baslik" for="rota-kaydir">${T('Yağış', 'Rainfall')}: <b data-yer="yagis"></b></label>
      <input type="range" id="rota-kaydir" min="0" max="${vitrin.yagis_mm.length}" step="1" value="${durum.sira}">
      <div class="olcek"><span>${T('yok', 'none')}</span><span>${vitrin.yagis_mm[vitrin.yagis_mm.length - 1]} mm</span></div>
      <div data-yer="sure" class="bosluk-ust"></div>
      <div class="alan-baslik">${T("2 Şubat 2021'e yakın yağışlar", 'Closest to 2 February 2021')}</div>
      <div data-yer="olay"></div>
      <div data-yer="sonuc"></div>
      <h3>${T('Rota nasıl hesaplanıyor?', 'How is the route computed?')}</h3>
      <ul>
        <li>${T("Bir noktası 30 cm'den derin suda kalan yol kapalı sayılır; başka yol yoksa yine geçilir ve söylenir.", 'A road with any point under more than 30 cm of water counts as closed; if there is no other way it is still used and reported.')}</li>
        <li>${T('Sığ sulu ya da düz ovadaki (derinliği bilinmeyen) yol 5 kat pahalı sayılır; yokuş da maliyeti artırır.', 'Roads with shallow water or on a flat plain (depth unknown) cost 5 times more; slopes add cost too.')}</li>
        <li>${T('Su altındaki ya da düz ovadaki toplanma alanı hedef seçilmez; kalanların hepsi arasından en ucuz yolla ulaşılanı seçilir.', 'Assembly areas under water or on a flat plain are never chosen; of the rest, the one reached at least cost wins.')}</li>
        <li>${T('Senaryoda alt geçitler doluysa alt geçitler de kapalıdır.', 'If the scenario floods the underpasses, they are closed too.')}</li>
      </ul>
      <div class="kutu not">${T('Sel anında resmi tavsiye çoğu zaman yola çıkmamak ve yüksekte kalmaktır. Bu rota bir "ne yapmalı" tavsiyesi değil; hangi yolların ve alanların kullanılamaz hale geldiğini gösteren bir planlama aracıdır.',
                                 'During a flood the official advice is usually to stay put on high ground. This route is not advice on what to do; it is a planning aid that shows which roads and areas become unusable.')}</div>
      <p class="kucuk">${T('Rota tarayıcında hesaplanır: merkezdeki 11 ilçenin OpenStreetMap araç yolu ağı (82 bin yol parçası, 873 toplanma alanı) ve her senaryoda yollara düşen su önceden dosyaya yazılmıştır; Dijkstra algoritması sunucudaki pgRouting sorgusuyla aynı maliyeti kullanır. Sunucu sürümündeki son 24 saatin depremleri ve trafik verisi burada yoktur.',
                           'The route is computed in your browser: the OpenStreetMap drive network of the 11 central districts (82k road segments, 873 assembly areas) and the water on each road in each scenario are precomputed; Dijkstra uses the same cost as the server-side pgRouting query. Live earthquakes and traffic from the server version are not included.')}</p>`;
    icerik.querySelector('#rota-kaydir').addEventListener('input', (olay) => {
      durum.sira = Number(olay.target.value);
      secimleriCiz();
      yenile();
    });
    secimleriCiz();
    sonucCiz();
  }

  return {
    id: 'rota',
    baslik: () => T('Rota', 'Route'),
    goster(yeniIcerik) {
      icerik = yeniIcerik;
      secimDinle(icerik, (grup, deger) => {
        if (grup === 'saat') durum.saat = Number(deger);
        if (grup === 'olay') {
          const [mm, saat] = deger.split('_').map(Number);
          durum.sira = vitrin.yagis_mm.indexOf(mm) + 1;
          durum.saat = saat;
          icerik.querySelector('#rota-kaydir').value = durum.sira;
        }
        secimleriCiz();
        yenile();
      });
      ilkSigdirma = true;
      ciz();
      isaretciKur();
      isaretci.addTo(harita.harita);
      harita.harita.on('click', haritaTiklandi);
      harita.harita.getContainer().classList.add('rota-secimi');
      // veri gelene kadar başlangıcın çevresi; rota gelince ona sığdırılır
      harita.sigdir(L.latLng(durum.bas.lat, durum.bas.lon).toBounds(3000), 15);
      yenile().then(kapsamCiz);
    },
    gizle() {
      istekNo++;
      if (katman) harita.harita.removeLayer(katman);
      if (kapsam) harita.harita.removeLayer(kapsam);
      if (isaretci) harita.harita.removeLayer(isaretci);
      katman = null; kapsam = null; icerik = null;
      harita.harita.off('click', haritaTiklandi);
      harita.harita.getContainer().classList.remove('rota-secimi');
      harita.suGoster(null);
    },
    ciz() { ciz(); haritayaCiz(); },     // dil değişince haritadaki etiketler de yenilenir
    lejant: () => lejantOgesi(ROTA_RENGI, T('rota', 'route'), 'cizgi')
      + (anahtar() ? lejantOgesi(KURU_RENGI, T('yağışsız günün rotası', 'dry-day route'), 'cizgi') : '')
      + lejantOgesi(ALAN_RENGI, T('toplanma alanı', 'assembly area'), 'daire')
      + (harita.suAcik() ? suLejanti(vitrin.siniflar) : ''),
  };
}
