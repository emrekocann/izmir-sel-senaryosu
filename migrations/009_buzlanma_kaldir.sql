-- Yol buzlanması özelliği kaldırıldı (İzmir'de anlamlı risk yok). 007'yi
-- uygulamış veritabanlarındaki kullanılmayan kolonlar silinir.
ALTER TABLE izmir_roads_noded DROP COLUMN IF EXISTS yukseklik,
                              DROP COLUMN IF EXISTS golgeli,
                              DROP COLUMN IF EXISTS kopru;
ALTER TABLE izmir_yaya_noded  DROP COLUMN IF EXISTS yukseklik,
                              DROP COLUMN IF EXISTS golgeli,
                              DROP COLUMN IF EXISTS kopru;
