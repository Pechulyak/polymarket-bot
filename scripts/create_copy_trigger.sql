-- Function to copy whale trades to paper_trades table
-- PHASE1.5-003: Proportional Kelly sizing
-- Uses whale's estimated_capital to calculate proportionate copy size
-- Formula: proportion = whale_trade / whale_capital
--          our_size = proportion * our_bankroll * kelly_fraction
--          capped at max_position_pct
CREATE OR REPLACE FUNCTION copy_whale_trade_to_paper()
RETURNS TRIGGER AS $$
DECLARE
    v_whale_address TEXT;
    v_whale_capital NUMERIC(20,8);
    v_our_bankroll NUMERIC(20,8);
    v_kelly_fraction NUMERIC(10,8);
    v_max_position_pct NUMERIC(10,8);
    v_min_trade_size NUMERIC(20,8);
    v_proportion NUMERIC(20,8);
    v_our_size NUMERIC(20,8);
    v_kelly_size NUMERIC(20,8);
    v_is_top_whale BOOLEAN := FALSE;
    v_source VARCHAR(20) := 'unknown';
BEGIN
    -- Get whale wallet address and estimated capital
    SELECT w.wallet_address, COALESCE(w.estimated_capital, 100000)
    INTO v_whale_address, v_whale_capital
    FROM whales w
    WHERE w.id = NEW.whale_id;

    -- Get source from whale_trades (default to 'unknown' if not set)
    v_source := COALESCE(NEW.source, 'unknown');

    -- Read strategy config
    v_our_bankroll := COALESCE(
        (SELECT value FROM strategy_config WHERE key = 'our_bankroll'),
        1000.00
    );
    v_kelly_fraction := COALESCE(
        (SELECT value FROM strategy_config WHERE key = 'kelly_fraction'),
        0.25
    );
    v_max_position_pct := COALESCE(
        (SELECT value FROM strategy_config WHERE key = 'max_position_pct'),
        0.05
    );
    v_min_trade_size := COALESCE(
        (SELECT value FROM strategy_config WHERE key = 'min_trade_size_usd'),
        1.00
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
        IF NEW.tx_hash IS NOT NULL AND EXISTS (
            SELECT 1 FROM paper_trades 
            WHERE tx_hash = NEW.tx_hash
        ) THEN
            RETURN NEW;
        END IF;
    END IF;

    IF v_is_top_whale AND v_whale_address IS NOT NULL THEN
        -- Check for duplicate signal: skip if similar paper_trade exists within 5 minutes
        IF EXISTS (
            SELECT 1 FROM paper_trades
            WHERE whale_address = v_whale_address
              AND market_id = NEW.market_id
              AND side = NEW.side
              AND created_at >= NOW() - INTERVAL '5 minutes'
        ) THEN
            RETURN NEW;
        END IF;

        -- PHASE1.5-003: Proportional Kelly sizing
        -- Calculate proportion of whale's trade relative to whale's capital
        v_proportion := NEW.size_usd / NULLIF(v_whale_capital, 0);
        
        -- Our size = proportion * our bankroll * kelly fraction
        v_our_size := v_proportion * v_our_bankroll * v_kelly_fraction;
        
        -- Cap at max position percentage
        v_kelly_size := LEAST(v_our_size, v_our_bankroll * v_max_position_pct);

        -- Skip if below min_trade_size
        IF v_kelly_size < v_min_trade_size THEN
            RETURN NEW;
        END IF;

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
$$ LANGUAGE plpgsql;

-- Trigger
DROP TRIGGER IF EXISTS trigger_copy_whale_trade ON whale_trades;
CREATE TRIGGER trigger_copy_whale_trade
AFTER INSERT ON whale_trades
FOR EACH ROW
EXECUTE FUNCTION copy_whale_trade_to_paper();
