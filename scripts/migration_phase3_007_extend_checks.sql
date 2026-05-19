-- TRD-443 Phase 3 / Migration 007: Extend CHECK constraints
--
-- Production code (_close_roundtrips after TRD-443 refactor) writes:
--   - matching_method = 'FUZZY_FLIP' (new value for fuzzy fallback with outcome match)
--   - matching_method = 'MANUAL_RUN_TRD443' (sentinel for TRD-443 dry-run, never written in cron mode)
--   - pnl_status = 'EXACT' (new value for direct SELL-close with precise P&L)
--
-- Existing CHECK constraints reject these. This migration extends both
-- whitelists. Apply order: 007 (this) → 006 (legacy mark).
--
-- Safety: only ADDS values to whitelists. No removal. Existing rows remain valid.
-- Sanity DO-блок at the end verifies post-state.

BEGIN;

-- matching_method: add 'FUZZY_FLIP' and 'MANUAL_RUN_TRD443'
ALTER TABLE whale_trade_roundtrips
    DROP CONSTRAINT IF EXISTS whale_trade_roundtrips_matching_method_check;

ALTER TABLE whale_trade_roundtrips
    ADD CONSTRAINT whale_trade_roundtrips_matching_method_check
    CHECK (matching_method IS NULL OR matching_method IN (
        'DIRECT_SELL',
        'SETTLEMENT',
        'FLIP',
        'PARTIAL',
        'MANUAL_REVIEW',
        'FUZZY_FLIP',
        'MANUAL_RUN_TRD443'
    ));

-- pnl_status: add 'EXACT'
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

-- Sanity: confirm no rows violate the new constraints (impossible by construction,
-- but explicit check guards against schema drift)
DO $$
DECLARE
    bad_method_count INTEGER;
    bad_status_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO bad_method_count
    FROM whale_trade_roundtrips
    WHERE matching_method IS NOT NULL
      AND matching_method NOT IN (
          'DIRECT_SELL', 'SETTLEMENT', 'FLIP', 'PARTIAL', 'MANUAL_REVIEW', 'FUZZY_FLIP', 'MANUAL_RUN_TRD443'
        );
    IF bad_method_count > 0 THEN
        RAISE EXCEPTION 'TRD-443/007: unexpected matching_method values exist: count=%', bad_method_count;
    END IF;

    SELECT COUNT(*) INTO bad_status_count
    FROM whale_trade_roundtrips
    WHERE pnl_status IS NOT NULL
      AND pnl_status NOT IN ('CONFIRMED', 'ESTIMATED', 'UNAVAILABLE', 'EXACT');
    IF bad_status_count > 0 THEN
        RAISE EXCEPTION 'TRD-443/007: unexpected pnl_status values exist: count=%', bad_status_count;
    END IF;

    RAISE NOTICE 'TRD-443/007: CHECK constraints extended successfully';
END $$;

COMMIT;