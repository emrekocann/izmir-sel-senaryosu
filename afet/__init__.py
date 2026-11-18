"""İzmir sel senaryosu ve tahliye rotası — sunucu ve ortak kod.

  afet.api          FastAPI uygulaması (sel senaryosu, günlük sel riski, rota)
  afet.veritabani   PostGIS bağlantısı, sorgular (pgRouting) ve kayıt şemaları
  afet.sel          önceden hesaplanmış ızgara katmanları: senaryo, günlük risk
  afet.canli_veri   rota maliyetine giren deprem / trafik verisinin toplanması
  afet.sinir, afet.izgara, afet.ag, afet.onbellek, afet.dosya, afet.yollar
                    ortak yardımcılar

Çevrimdışı hesaplar (model, yol ağı, yayın sitesi verisi) hesap/ altındadır.
"""
