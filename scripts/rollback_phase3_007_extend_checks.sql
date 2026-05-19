-- TRD-443 Phase 3 / Rollback 007: Revert CHECK constraint extensions
--
-- Restores the original CHECK whitelists.
--
-- WARNING: If any rows with matching_method='FUZZY_FLIP' or pnl_status='EXACT'
-- exist at rollback time, this will FAIL. Either delete those rows first,
-- or update them to allowed values, before running rollback.

BEGIN;

-- Sanity check: refuse rollback if forbidden values are present
DO $$
DECLARE
    fuzzy_flip_count INTEGER;
    exact_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO fuzzy_flip_count
    FROM whale_trade_roundtrips
    WHERE matching_method = 'FUZZY_FLIP';

    SELECT COUNT(*) INTO exact_count
    FROM whale_trade_roundtrips
    WHERE pnl_status = 'EXACT';

    IF fuzzy_flip_count > 0 THEN
        RAISE EXCEPTION 'TRD-443/007-rollback: % rows with matching_method=FUZZY_FLIP exist; clean them up first', fuzzy_flip_count;
    END IF;

    IF exact_count > 0 THEN
        RAISE EXCEPTION 'TRD-443/007-rollback: % rows with pnl_status=EXACT exist; clean them up first', exact_count;
    END IF;
END $$;

-- Restore original constraints
ALTER TABLE whale_trade_roundtrips
    DROP CONSTRAINT IF EXISTS whale_trade_roundtrips_matching_method_check;

ALTER TABLE whale_trade_roundtrips
    ADD CONSTRAINT whale_trade_roundtrips_matching_method_check
    CHECK (matching_method IS NULL OR matching_method IN (
        'DIRECT_SELL',
        'SETTLEMENT',
        'FLIP',
        'PARTIAL',
        'MANUAL_REVIEW'
    ));

ALTER TABLE whale_trade_roundtrips
    DROP CONSTRAINT IF EXISTS whale_trade_roundtrips_pnl_status_check;

ALTER TABLE whale_trade_roundtrips
    ADD CONSTRAINT whale_trade_roundtrips_pnl_status_check
    CHECK (pnl_status IS NULL OR pnl_status IN (
        'CONFIRMED',
        'ESTIMATED',
        'UNAVAILABLE'
    ));

COMMIT;