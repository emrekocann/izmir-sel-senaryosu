-- Sel / su baskını arazi duyarlılığı (hesap/sel_duyarlilik_hesapla.py doldurur).
-- sel_duyarlilik: 0–1, kenar boyunca ~25 m'de bir örneklenen SRTM tabanlı
--   duyarlılığın ORTALAMASI (rota cezası maruz kalınan uzunlukla orantılı olsun;
--   dere yatağına göre yükseklik + çukur derinliği; köprüler hariç).
-- sel_riskli_oran: kenarın duyarlılığı ≥0.6 olan kısmının oranı (rapor için).
-- alt_gecit: OSM'de kısa tünel (<400 m) — kentte su biriken alt geçit.
-- Değer NULL ise rota sel cezası uygulamaz.
ALTER TABLE izmir_roads_noded ADD COLUMN IF NOT EXISTS sel_duyarlilik real;
ALTER TABLE izmir_roads_noded ADD COLUMN IF NOT EXISTS alt_gecit boolean;
ALTER TABLE izmir_roads_noded ADD COLUMN IF NOT EXISTS sel_riskli_oran real;
ALTER TABLE izmir_yaya_noded  ADD COLUMN IF NOT EXISTS sel_duyarlilik real;
ALTER TABLE izmir_yaya_noded  ADD COLUMN IF NOT EXISTS alt_gecit boolean;
ALTER TABLE izmir_yaya_noded  ADD COLUMN IF NOT EXISTS sel_riskli_oran real;
