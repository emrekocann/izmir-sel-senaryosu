// Uygulamanın girişi: veriyi yükler, haritayı kurar, sekmeleri yönetir.
//
// Yeni bir sekme eklemek için: js/sekmeler/ altına bir modül yaz (aşağıdaki
// arayüzle) ve SEKMELER listesine ekle. Başka dosyaya dokunmak gerekmez.
//
//   sekme = { id, baslik(), goster(icerikOgesi), gizle(), ciz(), lejant() }
//     goster  sekme açılınca: paneli doldurur, katmanlarını haritaya ekler
//     gizle   sekmeden çıkılınca: katmanlarını kaldırır
//     ciz     dil değişince: panel metnini yeniden üretir
//     lejant  haritanın lejantı (HTML)
import { ilkDil, dilAyarla, aktifDil, dilDegisince, T } from './cekirdek/dil.js';
import { veriYukle } from './cekirdek/veri.js';
import { haritaKur } from './cekirdek/harita.js';
import { hakkindaKur } from './hakkinda.js';
import { senaryoSekmesi } from './sekmeler/senaryo.js';
import { olaySekmesi } from './sekmeler/olay.js';
import { rotaSekmesi } from './sekmeler/rota.js';
import { denetimSekmesi } from './sekmeler/denetim.js';

const SEKMELER = [senaryoSekmesi, olaySekmesi, rotaSekmesi, denetimSekmesi];

const oge = (kimlik) => document.getElementById(kimlik);

async function baslat() {
  ilkDil();
  const panel = oge('panel'), govde = oge('panel-govde'), lejant = oge('lejant'), sekmeCubugu = oge('sekmeler');

  let veri;
  try {
    veri = await veriYukle();
  } catch (hata) {
    console.error(hata);
    govde.innerHTML = '<p class="kutu kotu">Veri yüklenemedi / Data failed to load.</p>';
    return;
  }

  const harita = haritaKur(oge('harita'), panel, veri.vitrin);
  const hakkinda = hakkindaKur(oge('hakkinda'), veri);
  const sekmeler = SEKMELER.map((kur) => kur({ ...veri, harita }));
  let aktif = null;

  // Lejant dar ekranda kapalı başlar: açıkken haritanın çoğunu örter
  // (rota sekmesinde işaretçi ve rota altında kalıyordu). Başlığa tıklayınca açılır.
  let lejantAcik = !matchMedia('(max-width: 720px)').matches;
  const lejantCiz = () => {
    const ic = aktif ? aktif.lejant() : '';
    lejant.classList.toggle('kapali', !lejantAcik);
    lejant.innerHTML = ic && `<button type="button" class="lejant-dugme" aria-expanded="${lejantAcik}">${T('Lejant', 'Legend')}</button><div class="lejant-ic">${ic}</div>`;
  };
  lejant.addEventListener('click', (olay) => {
    if (!olay.target.closest('.lejant-dugme')) return;
    lejantAcik = !lejantAcik;
    lejantCiz();
  });

  function sekmeDugmeleri() {
    sekmeCubugu.innerHTML = sekmeler.map((s) =>
      `<button type="button" role="tab" data-sekme="${s.id}" aria-selected="${s === aktif}">${s.baslik()}</button>`).join('');
  }

  function ac(kimlik) {
    const yeni = sekmeler.find((s) => s.id === kimlik) || sekmeler[0];
    if (yeni === aktif) return;
    if (aktif) aktif.gizle();
    aktif = yeni;
    // her açılışta taze bir kapsayıcı: önceki sekmenin dinleyicileri onunla birlikte gider
    const icerik = document.createElement('div');
    govde.replaceChildren(icerik);
    govde.scrollTop = 0;
    panel.classList.remove('kapali');
    aktif.goster(icerik);
    sekmeDugmeleri();
    lejantCiz();
    history.replaceState(null, '', `#${aktif.id}`);
  }

  sekmeCubugu.addEventListener('click', (olay) => {
    const dugme = olay.target.closest('[data-sekme]');
    if (dugme) ac(dugme.dataset.sekme);
  });
  window.addEventListener('hashchange', () => ac(location.hash.slice(1)));
  // paneldeki bir seçim lejantı değiştirebilir (ör. rota: yağış yok → su katmanı yok)
  govde.addEventListener('click', () => queueMicrotask(lejantCiz));
  govde.addEventListener('input', () => queueMicrotask(lejantCiz));

  oge('panel-kapat').addEventListener('click', () => panel.classList.toggle('kapali'));
  oge('dil').addEventListener('click', () => dilAyarla(aktifDil() === 'tr' ? 'en' : 'tr'));
  document.addEventListener('click', (olay) => {
    const dugme = olay.target.closest('[data-hakkinda]');
    if (dugme) hakkinda.ac(dugme.dataset.hakkinda);
  });

  const dilUygula = () => {
    oge('dil').textContent = aktifDil() === 'tr' ? 'EN' : 'TR';
    document.title = T('İzmir sel senaryosu — 2 Şubat 2021 yeniden yaşansa', 'İzmir flood scenario — what if 2 February 2021 happened again');
    sekmeDugmeleri();
    hakkinda.doldur();
    if (aktif) { aktif.ciz(); lejantCiz(); }
  };
  dilDegisince(dilUygula);
  dilUygula();

  const dogrudanSekme = location.hash.length > 1;      // bağlantı belirli bir sekmeye mi
  ac(location.hash.slice(1));
  // ilk ziyarette çalışmanın ne olduğu ve sınırı görünsün
  let gorulmus = false;
  try {
    gorulmus = localStorage.getItem('hakkinda-goruldu') === '1';
    localStorage.setItem('hakkinda-goruldu', '1');
  } catch (hata) { /* gizli pencere: yok say */ }
  if (!gorulmus && !dogrudanSekme) hakkinda.ac();
}

baslat();
