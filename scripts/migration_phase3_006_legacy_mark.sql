-- TRD-443 / TASK 1.5: Mark 530 legacy CLOSED+SELL roundtrips
-- Created: 2026-05-17
-- Apply: staging in TASK 3, production in TASK 4
-- Rollback: scripts/rollback_phase3_006_legacy_mark.sql

BEGIN;

-- 1. DDL: add is_legacy_close column (idempotent)
ALTER TABLE whale_trade_roundtrips
    ADD COLUMN IF NOT EXISTS is_legacy_close BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Sanity-check: ровно 530 кандидатов до UPDATE
DO $$
DECLARE
    candidate_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO candidate_count
    FROM whale_trade_roundtrips
    WHERE matching_method = 'FLIP'
      AND matching_confidence = 'MEDIUM'
      AND close_type = 'SELL';

    IF candidate_count <> 530 THEN
        RAISE EXCEPTION 'TRD-443 T1.5: expected 530 legacy candidates, got %', candidate_count;
    END IF;
END $$;

-- 3. Mark all 530 as legacy
UPDATE whale_trade_roundtrips
SET is_legacy_close = TRUE
WHERE matching_method = 'FLIP'
  AND matching_confidence = 'MEDIUM'
  AND close_type = 'SELL';

-- 4. Sanity-check: ровно 530 после UPDATE
DO $$
DECLARE
    marked_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO marked_count
    FROM whale_trade_roundtrips
    WHERE is_legacy_close = TRUE;

    IF marked_count <> 530 THEN
        RAISE EXCEPTION 'TRD-443 T1.5: expected 530 marked rows, got %', marked_count;
    END IF;
END $$;

-- 5. Mark 75 broken rows as LEGACY_INVALID
-- TO BE FILLED IN T1.5-B (etap B):
--   - 16 orphaned: WHERE id IN (<list from CSV>)
--   - 59 sell_before_open: WHERE id IN (<list from CSV>)

-- 16 orphaned legacy roundtrips (no matching SELL trade)
UPDATE whale_trade_roundtrips
SET pnl_status = 'LEGACY_INVALID'
WHERE is_legacy_close = TRUE
  AND id IN (
    '043f9274-e5f6-44ab-ab69-c9b66cbede50',
    '68dc71a3-e610-42cb-a943-3a3a62c8a897',
    'bafc2d59-ccc9-41f0-8263-34c6404cb1b2',
    '856e92d1-ebb3-4f92-9a81-00daf6c61b3b',
    '0f76232b-edcf-4cbc-b03b-5eaf83279a28',
    '9a9a8761-bb5c-4d75-b57e-7ca55e2663f4',
    'a84d9d20-18d2-4835-821f-a28db1f7df79',
    'ba732fcb-2542-4926-8715-3569112f9f91',
    'fc655490-c9a8-419c-837d-2c96bb20483d',
    '9a76e2e5-6a46-4ab4-bdc5-397a6b8c5438',
    '62549d96-2ece-4baa-8c06-2627315ae3d5',
    'dbbdf962-8562-4d45-a15a-3c329bb0b03b',
    '37cfd8e2-1d70-4b27-b382-b9552b310ec5',
    'f425966f-7a4b-4bee-a319-e9563ab5ce8f',
    '47bb3b9f-0bc9-498c-8528-6cb1bb9472af',
    '64c1f188-ee08-4f43-9ef6-8887e56573ac'
  );

-- Sanity-check: ровно 16 строк помечены как LEGACY_INVALID (orphaned)
DO $$
DECLARE
    orphaned_marked INTEGER;
BEGIN
    SELECT COUNT(*) INTO orphaned_marked
    FROM whale_trade_roundtrips
    WHERE is_legacy_close = TRUE
      AND pnl_status = 'LEGACY_INVALID'
      AND id IN (
    '043f9274-e5f6-44ab-ab69-c9b66cbede50',
    '68dc71a3-e610-42cb-a943-3a3a62c8a897',
    'bafc2d59-ccc9-41f0-8263-34c6404cb1b2',
    '856e92d1-ebb3-4f92-9a81-00daf6c61b3b',
    '0f76232b-edcf-4cbc-b03b-5eaf83279a28',
    '9a9a8761-bb5c-4d75-b57e-7ca55e2663f4',
    'a84d9d20-18d2-4835-821f-a28db1f7df79',
    'ba732fcb-2542-4926-8715-3569112f9f91',
    'fc655490-c9a8-419c-837d-2c96bb20483d',
    '9a76e2e5-6a46-4ab4-bdc5-397a6b8c5438',
    '62549d96-2ece-4baa-8c06-2627315ae3d5',
    'dbbdf962-8562-4d45-a15a-3c329bb0b03b',
    '37cfd8e2-1d70-4b27-b382-b9552b310ec5',
    'f425966f-7a4b-4bee-a319-e9563ab5ce8f',
    '47bb3b9f-0bc9-498c-8528-6cb1bb9472af',
    '64c1f188-ee08-4f43-9ef6-8887e56573ac'
      );

    IF orphaned_marked <> 16 THEN
        RAISE EXCEPTION 'TRD-443 T1.5: expected 16 orphaned marked, got %', orphaned_marked;
    END IF;
END $$;

-- 59 sell_before_open legacy roundtrips (SELL traded_at <= opened_at)
UPDATE whale_trade_roundtrips
SET pnl_status = 'LEGACY_INVALID'
WHERE is_legacy_close = TRUE
  AND id IN (
    'f6cda2fe-828f-49be-817c-ec057b5d9e53',
    '2efefb7a-9f9c-4a8b-b5e9-fc23c7db7c2e',
    '0734e9bb-e1dc-4e8c-b6be-20307bd69c79',
    '73f75829-34b1-4327-ac97-85dd90c062b3',
    '25250358-d32e-4508-8719-6e6c29815b8f',
    'a4534bed-8477-46d9-9ef7-cc9a8abb1a8f',
    '40c0c63c-1a3a-45e7-aa59-e7a96818eaed',
    '17d7e4b8-467d-4de1-8a8f-d625eb023294',
    'edb93409-fdb8-4554-8c05-cb3114ef8ab6',
    '0685107b-3019-48bf-b1ac-cd219ba660c2',
    '5d657f3f-b8ec-431a-997a-59bb06e50155',
    '85e6e7bd-ac8a-486e-8848-72ebfb9bf8b0',
    '6458c280-713e-4dcb-8766-30f8cfa7d226',
    'dedb5330-7eb9-41fa-b20a-b3933687ca8f',
    'ab8a473d-c39a-4c05-9b0e-f9fafb9a4da7',
    '81815ba9-e66b-4aab-886b-05ce18a0ba22',
    '57bc6f23-8e26-4b1e-8aec-3be6562adb3e',
    'b48d4c87-02d0-4f2c-af17-197eda7688ff',
    'f3537531-9fa0-44fe-8d61-24f64111fe45',
    'b2a03ba3-d668-40e7-bd97-6441f420c93d',
    'c6509300-242f-4ed2-bebb-ce0554b09318',
    '461c7d63-dc09-4ea7-96b5-d6284ff4502c',
    'b6e98b43-47f9-4026-adba-9c37465615be',
    'd3e9cdb4-0da4-4967-be30-184668fc0c39',
    '9707f3f4-29b1-475b-b010-0e0d39d3a80c',
    '5bac1fd6-031d-4779-af1b-b578c3f8e652',
    'd812f823-e4e3-4726-a4ec-a36933e60631',
    '2b367183-c175-4680-a5d4-243458f42b3d',
    '10c1cd9d-19a6-48b7-9729-85c4849efd82',
    '995b1773-2ec5-4814-a819-bd9a20e752e9',
    'e891b169-c738-42df-8a0a-de09ceea61e8',
    '93cc95d1-9330-4854-ace9-042ee1bf1f76',
    '81e0e1bb-a942-439d-a8a3-6c52ed3da00a',
    'cf8f46bb-ec7e-436b-bc5c-6f32d46ff624',
    'f096ff77-9b30-42d6-9e9f-4f2ce57a8007',
    '014934e1-2b0e-40f6-9e50-dfbd0d797aac',
    'c70a5a68-fd02-4edf-9d1d-f99591e0bfd3',
    'a5343f6e-d912-4ba0-aa98-f49922e06906',
    '24f19b8c-9c2b-4ecd-a9f0-a0defe38a862',
    '10104821-9500-4652-becc-cfa071e34a8c',
    'c4e55bc2-4928-4f24-93b5-a88081afd889',
    'fe03b417-17f0-49f1-af30-d406cca2717c',
    '3a9925c4-02eb-4a97-ad78-f7d02cba5e9f',
    'ea700ddf-c8ba-48bb-bc38-8214e6bcf79b',
    '4ca38d2a-fa22-46ba-8f63-6e1aebccf376',
    '74870bbe-fc48-454b-a671-155dd197d539',
    '1f639dc3-3df6-40aa-bb38-e4674562d673',
    '2fb3c285-e89c-4ce8-9446-28a50cb488a2',
    '17cd2d44-d281-41be-ad32-e19ef38f981d',
    'def6c8d2-68f4-4fec-aab8-50170538ad61',
    'e14fa621-aeb3-4775-b19d-cb8fff9b953d',
    'efedbc2c-b0ab-49af-bf56-91be55511de3',
    '2c2fbf63-3d2a-4195-ab19-a3c43d93fec6',
    'ddd9e8ef-5c79-4676-bd5e-f5a4fbadb2a3',
    'ce648c8e-dbc9-49b7-996b-6511e45ab0ab',
    '97478cc2-ce47-4347-8c8c-e674e8fc4289',
    '072cef72-b55d-42c1-847e-e6d15210897f',
    'dfce49fb-e010-43b8-9e3e-b12826940432',
    '8abb40c1-930a-4e39-a509-374b22bd867f'
  );

-- Sanity-check: ровно 75 строк помечены как LEGACY_INVALID
DO $$
DECLARE
    total_invalid INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_invalid
    FROM whale_trade_roundtrips
    WHERE is_legacy_close = TRUE
      AND pnl_status = 'LEGACY_INVALID';

    IF total_invalid <> 75 THEN
        RAISE EXCEPTION 'TRD-443 T1.5: expected 75 total LEGACY_INVALID, got %', total_invalid;
    END IF;
END $$;

COMMIT;
