-- TRD-444: Forward fix — settle_resolved_positions() writes close_size_usd
-- Migration: phase3_004a (follows phase3_004 which created the function)
-- Semantics: close_size_usd = open_size_usd (Formula A, project convention)
-- Verified against existing 7,531 SETTLEMENT rows (100% Formula A match).
-- Does NOT change RETURNS TABLE signature (public API contract preserved).

CREATE OR REPLACE FUNCTION public.settle_resolved_positions()
 RETURNS TABLE(roundtrip_id uuid, market_id character varying, wallet_address character varying, outcome character varying, open_price numeric, open_size_usd numeric, close_type character varying, close_price numeric, net_pnl numeric, winner_outcome character varying, winner_index smallint)
 LANGUAGE plpgsql
AS $function$
DECLARE
    r RECORD;
BEGIN
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
        DECLARE
            v_is_win BOOLEAN;
            v_close_price DECIMAL(20,8);
            v_close_type VARCHAR(30);
            v_net_pnl DECIMAL(20,8);
        BEGIN
            v_is_win := (
                (
                    CASE LOWER(r.outcome)
                        WHEN 'yes' THEN 0 WHEN 'up' THEN 0 WHEN 'over' THEN 0
                        WHEN 'no' THEN 1 WHEN 'down' THEN 1 WHEN 'under' THEN 1
                        ELSE NULL
                    END = r.winner_index
                )
                OR
                (UPPER(r.outcome) = UPPER(r.winner_outcome))
            );
            IF v_is_win THEN
                v_close_price := 1.0::DECIMAL(20,8);
                v_close_type := 'SETTLEMENT_WIN'::VARCHAR(30);
            ELSE
                v_close_price := 0.0::DECIMAL(20,8);
                v_close_type := 'SETTLEMENT_LOSS'::VARCHAR(30);
            END IF;
            v_net_pnl := (v_close_price - r.open_price) * r.open_size_usd;
            UPDATE whale_trade_roundtrips
            SET 
                status = 'CLOSED',
                close_price = v_close_price,
                close_size_usd = r.open_size_usd,  -- TRD-444: Formula A
                close_type = v_close_type,
                gross_pnl_usd = v_net_pnl,
                net_pnl_usd = v_net_pnl,
                pnl_status = 'CONFIRMED',
                closed_at = NOW()
            WHERE id = r.roundtrip_id;
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
$function$;
