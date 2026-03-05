-- Add source column to whale_trades for tracking realtime vs backfill
ALTER TABLE whale_trades ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'unknown' 
    CHECK (source IN ('realtime', 'backfill', 'unknown'));

-- Add source column to paper_trades
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'unknown'
    CHECK (source IN ('realtime', 'backfill', 'unknown'));

-- Create notification queue table for Telegram alerts
CREATE TABLE IF NOT EXISTS paper_trade_notifications (
    id SERIAL PRIMARY KEY,
    paper_trade_id INTEGER NOT NULL,
    whale_address TEXT NOT NULL,
    market_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price NUMERIC(20, 8) NOT NULL,
    size NUMERIC(20, 8) NOT NULL,
    size_usd NUMERIC(20, 8),
    kelly_fraction NUMERIC(10, 8),
    kelly_size NUMERIC(20, 8),
    source VARCHAR(20) DEFAULT 'unknown',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    notified BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_notifications_pending ON paper_trade_notifications(notified, created_at);

-- Update the trigger function to include source
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

        -- Insert into paper_trades with source
        INSERT INTO paper_trades (
            whale_address,
            market_id,
            side,
            price,
            size,
            size_usd,
            kelly_fraction,
            kelly_size,
            created_at,
            source
        ) VALUES (
            v_whale_address,
            NEW.market_id,
            NEW.side,
            NEW.price,
            NEW.size_usd / NULLIF(NEW.price, 0),
            NEW.size_usd,
            v_kelly_fraction,
            v_kelly_size,
            NEW.traded_at,
            v_source
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger function to insert notification after paper_trade is created
CREATE OR REPLACE FUNCTION notify_paper_trade()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO paper_trade_notifications (
        paper_trade_id,
        whale_address,
        market_id,
        side,
        price,
        size,
        size_usd,
        kelly_fraction,
        kelly_size,
        source,
        created_at
    ) VALUES (
        NEW.id,
        NEW.whale_address,
        NEW.market_id,
        NEW.side,
        NEW.price,
        NEW.size,
        NEW.size_usd,
        NEW.kelly_fraction,
        NEW.kelly_size,
        NEW.source,
        NEW.created_at
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop and recreate trigger on paper_trades
DROP TRIGGER IF EXISTS trigger_notify_paper_trade ON paper_trades;
CREATE TRIGGER trigger_notify_paper_trade
AFTER INSERT ON paper_trades
FOR EACH ROW
EXECUTE FUNCTION notify_paper_trade();
