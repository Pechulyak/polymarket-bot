-- Function to copy whale trades to paper_trades table
-- FIX: Include whales with recent trades (last 24h) OR qualified whales
-- ADDED: market_title column, tx_hash column for dedup
-- BUG-505: Added tx_hash for reliable deduplication
CREATE OR REPLACE FUNCTION copy_whale_trade_to_paper()
RETURNS TRIGGER AS $$
DECLARE
    v_whale_address TEXT;
    v_kelly_fraction NUMERIC(10,8) := 0.25;
    v_bankroll NUMERIC(20,8) := 100.00;
    v_max_position NUMERIC(20,8);
    v_kelly_size NUMERIC(20,8);
    v_is_top_whale BOOLEAN := FALSE;
    v_source VARCHAR(20) := 'unknown';
BEGIN
    -- Get whale wallet address
    SELECT w.wallet_address INTO v_whale_address
    FROM whales w
    WHERE w.id = NEW.whale_id;

    -- Get source from whale_trades (default to 'unknown' if not set)
    v_source := COALESCE(NEW.source, 'unknown');

    -- STRAT-701: Check if whale has copy_status = 'paper'
    -- Simple filter: only copy trades from whales marked for paper trading
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
            -- Skip duplicate by tx_hash
            RETURN NEW;
        END IF;
    END IF;

    IF v_is_top_whale AND v_whale_address IS NOT NULL THEN
        -- Check for duplicate signal: skip if similar paper_trade exists within 5 minutes
        -- This prevents duplicate paper trades from whale_trades duplicates
        IF EXISTS (
            SELECT 1 FROM paper_trades
            WHERE whale_address = v_whale_address
              AND market_id = NEW.market_id
              AND side = NEW.side
              AND created_at >= NOW() - INTERVAL '5 minutes'
        ) THEN
            -- Skip duplicate signal
            RETURN NEW;
        END IF;

        -- Calculate Kelly size: bankroll * kelly_fraction (25% of full Kelly)
        v_max_position := v_bankroll * 0.02;
        v_kelly_size := v_bankroll * v_kelly_fraction;
        
        -- Cap at max position
        IF v_kelly_size > v_max_position THEN
            v_kelly_size := v_max_position;
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
