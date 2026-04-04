-- Phase 3.004: Settlement Functions for Resolved Positions
-- Creates functions to settle whale trade roundtrips based on market resolutions
-- Double logic winner determination: index-based (0/1) AND string match

-- Drop existing functions first (required to change return type)
DROP FUNCTION IF EXISTS settle_resolved_positions_dry_run();
DROP FUNCTION IF EXISTS settle_resolved_positions();

-- ============================================================
-- DRY-RUN FUNCTION: SELECT-only, shows expected settlements
-- ============================================================
CREATE OR REPLACE FUNCTION settle_resolved_positions_dry_run()
RETURNS TABLE(
    roundtrip_id UUID,
    market_id VARCHAR(255),
    wallet_address VARCHAR(255),
    outcome VARCHAR(50),
    open_price DECIMAL(20,8),
    open_size_usd DECIMAL(20,8),
    expected_close_type VARCHAR(30),
    expected_close_price DECIMAL(20,8),
    expected_net_pnl DECIMAL(20,8),
    winner_outcome VARCHAR(100),
    winner_index SMALLINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        rt.id as roundtrip_id,
        rt.market_id,
        rt.wallet_address,
        rt.outcome,
        rt.open_price,
        rt.open_size_usd,
        -- Winner determination (двойная логика)
        CASE 
            WHEN (
                -- Standard outcomes: Yes=0, No=1, Up=0, Down=1, Over=0, Under=1
                CASE LOWER(rt.outcome)
                    WHEN 'yes' THEN 0 WHEN 'up' THEN 0 WHEN 'over' THEN 0
                    WHEN 'no' THEN 1 WHEN 'down' THEN 1 WHEN 'under' THEN 1
                    ELSE NULL
                END = mr.winner_index
            ) THEN 'SETTLEMENT_WIN'::VARCHAR(30)
            -- Custom outcomes: string match
            WHEN UPPER(rt.outcome) = UPPER(mr.winner_outcome) THEN 'SETTLEMENT_WIN'::VARCHAR(30)
            ELSE 'SETTLEMENT_LOSS'::VARCHAR(30)
        END as expected_close_type,
        -- Close price: 1.0 for WIN, 0.0 for LOSS
        CASE 
            WHEN (
                CASE LOWER(rt.outcome)
                    WHEN 'yes' THEN 0 WHEN 'up' THEN 0 WHEN 'over' THEN 0
                    WHEN 'no' THEN 1 WHEN 'down' THEN 1 WHEN 'under' THEN 1
                    ELSE NULL
                END = mr.winner_index
            ) THEN 1.0::DECIMAL(20,8)
            WHEN UPPER(rt.outcome) = UPPER(mr.winner_outcome) THEN 1.0::DECIMAL(20,8)
            ELSE 0.0::DECIMAL(20,8)
        END as expected_close_price,
        -- PnL: (close_price - open_price) * open_size_usd
        CASE 
            WHEN (
                CASE LOWER(rt.outcome)
                    WHEN 'yes' THEN 0 WHEN 'up' THEN 0 WHEN 'over' THEN 0
                    WHEN 'no' THEN 1 WHEN 'down' THEN 1 WHEN 'under' THEN 1
                    ELSE NULL
                END = mr.winner_index
            ) THEN (1.0 - rt.open_price) * rt.open_size_usd
            WHEN UPPER(rt.outcome) = UPPER(mr.winner_outcome) THEN (1.0 - rt.open_price) * rt.open_size_usd
            ELSE (0.0 - rt.open_price) * rt.open_size_usd
        END as expected_net_pnl,
        mr.winner_outcome,
        mr.winner_index
    FROM whale_trade_roundtrips rt
    JOIN market_resolutions mr ON rt.market_id = mr.market_id
    WHERE rt.status = 'OPEN'
      AND mr.is_closed = TRUE
      AND mr.winner_outcome IS NOT NULL
      AND mr.winner_index IS NOT NULL;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- PRODUCTION FUNCTION: Updates roundtrips to CLOSED status
-- ============================================================
CREATE OR REPLACE FUNCTION settle_resolved_positions()
RETURNS TABLE(
    roundtrip_id UUID,
    market_id VARCHAR(255),
    wallet_address VARCHAR(255),
    outcome VARCHAR(50),
    open_price DECIMAL(20,8),
    open_size_usd DECIMAL(20,8),
    close_type VARCHAR(30),
    close_price DECIMAL(20,8),
    net_pnl DECIMAL(20,8),
    winner_outcome VARCHAR(100),
    winner_index SMALLINT
) AS $$
DECLARE
    r RECORD;
BEGIN
    -- Iterate through resolved positions and update them
    FOR r IN
        SELECT 
            rt.id as roundtrip_id,
            rt.market_id,
            rt.wallet_address,
            rt.outcome,
            rt.open_price,
            rt.open_size_usd,
            mr.winner_outcome,
            mr.winner_index
        FROM whale_trade_roundtrips rt
        JOIN market_resolutions mr ON rt.market_id = mr.market_id
        WHERE rt.status = 'OPEN'
          AND mr.is_closed = TRUE
          AND mr.winner_outcome IS NOT NULL
          AND mr.winner_index IS NOT NULL
    LOOP
        -- Determine close type and price based on winner logic
        DECLARE
            v_is_win BOOLEAN;
            v_close_price DECIMAL(20,8);
            v_close_type VARCHAR(30);
            v_net_pnl DECIMAL(20,8);
        BEGIN
            -- Double logic winner determination
            v_is_win := (
                -- Standard outcomes: Yes=0, No=1, Up=0, Down=1, Over=0, Under=1
                (
                    CASE LOWER(r.outcome)
                        WHEN 'yes' THEN 0 WHEN 'up' THEN 0 WHEN 'over' THEN 0
                        WHEN 'no' THEN 1 WHEN 'down' THEN 1 WHEN 'under' THEN 1
                        ELSE NULL
                    END = r.winner_index
                )
                OR
                -- Custom outcomes: string match
                (UPPER(r.outcome) = UPPER(r.winner_outcome))
            );

            -- Set close price and type
            IF v_is_win THEN
                v_close_price := 1.0::DECIMAL(20,8);
                v_close_type := 'SETTLEMENT_WIN'::VARCHAR(30);
            ELSE
                v_close_price := 0.0::DECIMAL(20,8);
                v_close_type := 'SETTLEMENT_LOSS'::VARCHAR(30);
            END IF;

            -- Calculate PnL
            v_net_pnl := (v_close_price - r.open_price) * r.open_size_usd;

            -- Update the roundtrip record
            UPDATE whale_trade_roundtrips
            SET 
                status = 'CLOSED',
                close_price = v_close_price,
                close_type = v_close_type,
                net_pnl_usd = v_net_pnl,
                closed_at = NOW()
            WHERE id = r.roundtrip_id;

            -- Return the updated row
            RETURN QUERY SELECT 
                r.roundtrip_id,
                r.market_id,
                r.wallet_address,
                r.outcome,
                r.open_price,
                r.open_size_usd,
                v_close_type,
                v_close_price,
                v_net_pnl,
                r.winner_outcome,
                r.winner_index;
        END;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Grant execute permissions (if needed)
-- GRANT EXECUTE ON FUNCTION settle_resolved_positions_dry_run() TO postgres;
-- GRANT EXECUTE ON FUNCTION settle_resolved_positions() TO postgres;
