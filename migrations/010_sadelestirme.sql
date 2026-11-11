-- Sadeleştirme: proje sel senaryosu + tahliye rotasına odaklandı. Yağış
-- istasyonu, hava durumu, hava kalitesi, ilçe sıcaklığı ve uydu ısı
-- anomalisi verisi artık toplanmıyor; tabloları silinir. Rota maliyetine
-- giren deprem ve trafik tabloları kalır. (Eski hâl: arsiv/tum-katmanlar dalı)
DROP TABLE IF EXISTS canli_yagis_verileri, canli_yangin_verileri, canli_hava_kalitesi,
                     canli_meteoroloji, canli_isi_anomalisi, canli_ilce_isi;
