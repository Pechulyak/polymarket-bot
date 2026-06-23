-- TRD-449: Price entry filter in copy_whale_trade_to_paper
-- Date: 2026-06-23
-- Purpose: Add max_entry_price threshold — whale trades with price > threshold are skipped.
--   Reason: at p>0.97, commission (3% of notional) exceeds payout (1-p), buy-and-hold is loss-making even on wins.
--   Threshold is strictly > (p=0.97 passes).

-- Step 1: Add strategy_config key (idempotent — ON CONFLICT DO NOTHING, already applied in Step C)
INSERT INTO strategy_config (key, value, description)
VALUES ('max_entry_price', 0.97, 'Max whale entry price — trades above this threshold are skipped')
ON CONFLICT (key) DO NOTHING;

-- Step 2: Replace trigger function with price filter
CREATE OR REPLACE FUNCTION public.copy_whale_trade_to_paper()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_whale_address TEXT;
    v_whale_capital NUMERIC(20,8);
    v_our_bankroll NUMERIC(20,8);
    v_kelly_fraction NUMERIC(10,8);
    v_max_position_pct NUMERIC(10,8);
    v_min_trade_size NUMERIC(20,8);
    v_min_whale_trade_pct NUMERIC(10,8);
    v_max_entry_price NUMERIC(10,8);
    v_proportion NUMERIC(20,8);
    v_our_size NUMERIC(20,8);
    v_kelly_size NUMERIC(20,8);
    v_whale_pct NUMERIC(20,8);
    v_is_top_whale BOOLEAN := FALSE;
    v_source VARCHAR(20) := 'unknown';
    v_kelly_bankroll_source NUMERIC(10,0);
BEGIN
    SELECT w.wallet_address, COALESCE(w.estimated_capital, 100000)
    INTO v_whale_address, v_whale_capital
    FROM whales w
    WHERE w.id = NEW.whale_id;

    v_source := COALESCE(NEW.source, 'unknown');

    v_kelly_bankroll_source := COALESCE(
        (SELECT value::NUMERIC FROM strategy_config WHERE key = 'kelly_bankroll_source'),
        0
    );

    IF v_kelly_bankroll_source = 1 THEN
        v_our_bankroll := COALESCE(
            (SELECT current_balance FROM paper_portfolio_state LIMIT 1),
            (SELECT value::NUMERIC FROM strategy_config WHERE key = 'our_bankroll'),
            1000.00
        );
    ELSE
        v_our_bankroll := COALESCE(
            (SELECT value::NUMERIC FROM strategy_config WHERE key = 'our_bankroll'),
            1000.00
        );
    END IF;

    v_kelly_fraction := COALESCE(
        (SELECT value::NUMERIC FROM strategy_config WHERE key = 'kelly_fraction'),
        0.25
    );
    v_max_position_pct := COALESCE(
        (SELECT value::NUMERIC FROM strategy_config WHERE key = 'max_position_pct'),
        0.05
    );
    v_min_trade_size := COALESCE(
        (SELECT value::NUMERIC FROM strategy_config WHERE key = 'min_trade_size_usd'),
        1.00
    );
    v_min_whale_trade_pct := COALESCE(
        (SELECT value::NUMERIC FROM strategy_config WHERE key = 'min_whale_trade_pct'),
        0.01
    );
    v_max_entry_price := COALESCE(
        (SELECT value::NUMERIC FROM strategy_config WHERE key = 'max_entry_price'),
        0.97
    );

    IF v_whale_address IS NOT NULL THEN
        SELECT EXISTS (
            SELECT 1 FROM whales
            WHERE wallet_address = v_whale_address
              AND copy_status = 'paper'
        ) INTO v_is_top_whale;
    END IF;

    IF v_is_top_whale AND v_whale_address IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM paper_trades
            WHERE tx_hash = NEW.tx_hash
              AND whale_address = v_whale_address
              AND created_at >= NOW() - INTERVAL '5 minutes'
        ) THEN
            RETURN NEW;
        END IF;

        v_whale_pct := NEW.size_usd / NULLIF(v_whale_capital, 0);

        IF v_whale_pct < v_min_whale_trade_pct THEN
            RETURN NEW;
        END IF;

        -- TRD-449: Skip if whale entry price above threshold
        IF NEW.price > v_max_entry_price THEN
            RETURN NEW;
        END IF;

        v_proportion := v_whale_pct;
        v_our_size := v_proportion * v_our_bankroll * v_kelly_fraction;
        v_kelly_size := GREATEST(v_min_trade_size, LEAST(v_our_size, v_our_bankroll * v_max_position_pct));

        INSERT INTO paper_trades (
            whale_address,
            market_id,
            market_title,
            side,
            outcome,
            price,
            size,
            size_usd,
            kelly_fraction,
            kelly_size,
            created_at,
            source,
            tx_hash
        ) VALUES (
            v_whale_address,
            NEW.market_id,
            NEW.market_title,
            NEW.side,
            NEW.outcome,
            NEW.price,
            NEW.size_usd / NULLIF(NEW.price, 0),
            NEW.size_usd,
            v_kelly_fraction,
            v_kelly_size,
            NEW.traded_at,
            v_source,
            NEW.tx_hash
        );
    END IF;

    RETURN NEW;
END;
$function$;
