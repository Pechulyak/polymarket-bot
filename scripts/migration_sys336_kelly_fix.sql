-- SYS-336: Fix Kelly sizing — min $1, max 5%, whale filter 1%, dynamic bankroll
-- Migration: replace copy_whale_trade_to_paper() trigger function

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
    v_proportion NUMERIC(20,8);
    v_our_size NUMERIC(20,8);
    v_kelly_size NUMERIC(20,8);
    v_whale_pct NUMERIC(20,8);
    v_is_top_whale BOOLEAN := FALSE;
    v_source VARCHAR(20) := 'unknown';
    v_kelly_bankroll_source NUMERIC(10,0);
BEGIN
    -- Get whale wallet address and estimated capital
    SELECT w.wallet_address, COALESCE(w.estimated_capital, 100000)
    INTO v_whale_address, v_whale_capital
    FROM whales w
    WHERE w.id = NEW.whale_id;

    -- Get source from whale_trades (default to 'unknown' if not set)
    v_source := COALESCE(NEW.source, 'unknown');

    -- PHASE4-006: Get kelly_bankroll_source config
    v_kelly_bankroll_source := COALESCE(
        (SELECT value::NUMERIC FROM strategy_config WHERE key = 'kelly_bankroll_source'),
        0
    );

    -- PHASE4-006: Dynamic Kelly bankroll selection
    IF v_kelly_bankroll_source = 1 THEN
        -- Dynamic: берём current_balance из view paper_portfolio_state
        v_our_bankroll := COALESCE(
            (SELECT current_balance FROM paper_portfolio_state LIMIT 1),
            (SELECT value::NUMERIC FROM strategy_config WHERE key = 'our_bankroll'),
            1000.00
        );
    ELSE
        -- Static: берём из strategy_config (поведение Фазы 1.5)
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

    -- STRAT-701: Check if whale has copy_status = 'paper'
    IF v_whale_address IS NOT NULL THEN
        SELECT EXISTS (
            SELECT 1 FROM whales
            WHERE wallet_address = v_whale_address
              AND copy_status = 'paper'
        ) INTO v_is_top_whale;
    END IF;

    -- BUG-505: Hard dedup by tx_hash - skip if tx_hash already exists in paper_trades
    IF v_is_top_whale AND v_whale_address IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM paper_trades
            WHERE tx_hash = NEW.tx_hash
              AND whale_address = v_whale_address
              AND created_at >= NOW() - INTERVAL '5 minutes'
        ) THEN
            RETURN NEW;
        END IF;

        -- SYS-336: Calculate whale trade percentage
        v_whale_pct := NEW.size_usd / NULLIF(v_whale_capital, 0);

        -- SYS-336: Filter - if whale trades < min_whale_trade_pct of their capital, skip
        IF v_whale_pct < v_min_whale_trade_pct THEN
            RETURN NEW;  -- пропускаем сделку кита
        END IF;

        -- PHASE1.5-003: Proportional Kelly sizing
        -- v_proportion already calculated as v_whale_pct
        v_proportion := v_whale_pct;

        -- Our size = proportion * our bankroll * kelly fraction
        v_our_size := v_proportion * v_our_bankroll * v_kelly_fraction;

        -- SYS-336: Minimum $1, Maximum 5% of bankroll using GREATEST/LEAST
        v_kelly_size := GREATEST(v_min_trade_size, LEAST(v_our_size, v_our_bankroll * v_max_position_pct));

        -- Insert into paper_trades with market_title, source, outcome and tx_hash
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
