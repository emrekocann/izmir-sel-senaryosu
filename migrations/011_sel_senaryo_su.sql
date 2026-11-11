-- Yağış senaryosunda yollardaki ve toplanma alanlarındaki su
-- (sel_senaryo_yollar.py doldurur; sel_senaryo_hazirla.py sonunda kendisi çağırır).
-- katman: 'drive' (izmir_roads_noded.id), 'walk' (izmir_yaya_noded.id),
--         'toplanma' (toplanma_alanlari.id)
-- senaryo: '<yağış mm>_<süre sa>', ör. '50_1'
-- derinlik: kenar boyunca ~25 m'de bir örneklenen su derinliğinin EN BÜYÜĞÜ (m);
--   yolun tek bir noktası suyun altındaysa o yoldan geçilemez. Köprüler hariç.
-- belirsiz: düz ovada "su gelir, derinlik verilemez" (haritada gri).
-- Yalnız derinlik ≥ 0.1 m ya da belirsiz olan satırlar yazılır; satırı olmayan
-- yol o senaryoda kurudur.
CREATE TABLE IF NOT EXISTS sel_senaryo_su (
    katman   text    NOT NULL,
    senaryo  text    NOT NULL,
    kimlik   bigint  NOT NULL,
    derinlik real    NOT NULL,
    belirsiz boolean NOT NULL DEFAULT false,
    PRIMARY KEY (katman, senaryo, kimlik)
);

-- Katman başına son yazım: rota "senaryo verisi var mı" diye buna bakar
-- (kuru bir senaryoda hiç satır olmaması veri yokluğu sayılmasın).
CREATE TABLE IF NOT EXISTS sel_senaryo_yazim (
    katman     text PRIMARY KEY,
    yazildi    timestamptz NOT NULL DEFAULT now(),
    senaryo_sayisi int NOT NULL
);
