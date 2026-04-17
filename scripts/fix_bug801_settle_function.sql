-- BUG-801 Fix: Patch live settle_resolved_positions() function
-- Adds gross_pnl_usd and pnl_status to the UPDATE statement

DROP FUNCTION IF EXISTS settle_resolved_positions();

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

            -- BUG-801 FIX: Update with gross_pnl_usd and pnl_status
            UPDATE whale_trade_roundtrips
            SET 
                status = 'CLOSED',
                close_price = v_close_price,
                close_type = v_close_type,
                gross_pnl_usd = v_net_pnl,      -- BUG-801 FIX
                net_pnl_usd = v_net_pnl,
                pnl_status = 'CONFIRMED',         -- BUG-801 FIX
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
