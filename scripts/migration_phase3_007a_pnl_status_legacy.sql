-- TRD-443 Phase 3 / Migration 007a: Extend pnl_status whitelist with LEGACY_INVALID
--
-- Discovered during TASK 3-A staging dry-run: migration 006 writes 'LEGACY_INVALID'
-- to pnl_status, but migration 007 (extend checks) didn't include it in whitelist.
--
-- Apply order: 007 → 007a → 006
-- (Migration 007 already applied to both prod and staging snapshot)
--
-- Safety: only ADDS value to whitelist. No removal. Existing rows remain valid.
-- Sanity DO-блок verifies no existing rows violate the new constraint.

BEGIN;

-- pnl_status: add 'LEGACY_INVALID'
ALTER TABLE whale_trade_roundtrips
    DROP CONSTRAINT IF EXISTS whale_trade_roundtrips_pnl_status_check;

ALTER TABLE whale_trade_roundtrips
    ADD CONSTRAINT whale_trade_roundtrips_pnl_status_check
    CHECK (pnl_status IS NULL OR pnl_status IN (
        'CONFIRMED',
        'ESTIMATED',
        'UNAVAILABLE',
        'EXACT',
        'LEGACY_INVALID'
    ));

-- Sanity: confirm no rows violate the new constraint
DO $$
DECLARE
    bad_status_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO bad_status_count
    FROM whale_trade_roundtrips
    WHERE pnl_status IS NOT NULL
      AND pnl_status NOT IN ('CONFIRMED', 'ESTIMATED', 'UNAVAILABLE', 'EXACT', 'LEGACY_INVALID');
    
    IF bad_status_count > 0 THEN
        RAISE EXCEPTION 'TRD-443/007a: unexpected pnl_status values exist: count=%', bad_status_count;
    END IF;

    RAISE NOTICE 'TRD-443/007a: pnl_status extended with LEGACY_INVALID';
END $$;

COMMIT;