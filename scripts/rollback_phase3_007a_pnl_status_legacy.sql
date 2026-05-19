-- TRD-443 Phase 3 / Rollback Migration 007a
--
-- Reverses: migration_phase3_007a_pnl_status_legacy.sql
-- Removes LEGACY_INVALID from pnl_status whitelist
--
-- Warning: This rollback does NOT restore pnl_status values for rows
-- that were set to LEGACY_INVALID by migration 006.
-- Those values would need baseline snapshot restore to recover.

BEGIN;

-- pnl_status: remove 'LEGACY_INVALID' from whitelist
ALTER TABLE whale_trade_roundtrips
    DROP CONSTRAINT IF EXISTS whale_trade_roundtrips_pnl_status_check;

ALTER TABLE whale_trade_roundtrips
    ADD CONSTRAINT whale_trade_roundtrips_pnl_status_check
    CHECK (pnl_status IS NULL OR pnl_status IN (
        'CONFIRMED',
        'ESTIMATED',
        'UNAVAILABLE',
        'EXACT'
    ));

-- Sanity: confirm no LEGACY_INVALID rows exist after rollback
DO $$
DECLARE
    legacy_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO legacy_count
    FROM whale_trade_roundtrips
    WHERE pnl_status = 'LEGACY_INVALID';
    
    IF legacy_count > 0 THEN
        RAISE WARNING 'TRD-443/007a rollback: % rows still have LEGACY_INVALID pnl_status', legacy_count;
    END IF;

    RAISE NOTICE 'TRD-443/007a rollback: pnl_status restored to original whitelist';
END $$;

COMMIT;