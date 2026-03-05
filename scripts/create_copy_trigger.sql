-- Function to copy whale trades to paper_trades table
-- FIX: Include whales with recent trades (last 24h) OR qualified whales
CREATE OR REPLACE FUNCTION copy_whale_trade_to_paper()
RETURNS TRIGGER AS $$
DECLARE
    v_whale_address TEXT;
    v_kelly_fraction NUMERIC(10,8) := 0.25;
    v_bankroll NUMERIC(20,8) := 100.00;
    v_max_position NUMERIC(20,8);
    v_kelly_size NUMERIC(20,8);
    v_is_top_whale BOOLEAN := FALSE;
BEGIN
    -- Get whale wallet address
    SELECT w.wallet_address INTO v_whale_address
    FROM whales w
    WHERE w.id = NEW.whale_id;

    -- Check if whale is in top 50:
    -- 1. Qualified whales (qualification_path IS NOT NULL)
    -- 2. OR whales with recent trades (traded in last 24h)
    IF v_whale_address IS NOT NULL THEN
        SELECT EXISTS (
            SELECT 1 FROM (
                SELECT wallet_address 
                FROM whales 
                WHERE (
                    -- Path 1: Qualified whales
                    qualification_path IS NOT NULL
                    -- OR Path 2: Whales with recent activity (traded in last 24h)
                    OR id IN (
                        SELECT DISTINCT whale_id 
                        FROM whale_trades 
                        WHERE whale_id IS NOT NULL 
                          AND traded_at >= NOW() - INTERVAL '24 hours'
                    )
                )
                ORDER BY total_volume_usd DESC 
                LIMIT 50
            ) top_whales
            WHERE wallet_address = v_whale_address
        ) INTO v_is_top_whale;
    END IF;

    IF v_is_top_whale AND v_whale_address IS NOT NULL THEN
        -- Calculate Kelly size: bankroll * kelly_fraction (25% of full Kelly)
        v_max_position := v_bankroll * 0.02;
        v_kelly_size := v_bankroll * v_kelly_fraction;
        
        -- Cap at max position
        IF v_kelly_size > v_max_position THEN
            v_kelly_size := v_max_position;
        END IF;

        -- Insert into paper_trades
        INSERT INTO paper_trades (
            whale_address,
            market_id,
            side,
            price,
            size,
            size_usd,
            kelly_fraction,
            kelly_size,
            created_at
        ) VALUES (
            v_whale_address,
            NEW.market_id,
            NEW.side,
            NEW.price,
            NEW.size_usd / NULLIF(NEW.price, 0),
            NEW.size_usd,
            v_kelly_fraction,
            v_kelly_size,
            NEW.traded_at
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
