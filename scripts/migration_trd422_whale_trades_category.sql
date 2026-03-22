-- TRD-422: Add market_tags column to whale_trades
-- Source: CLOB API /markets/{conditionId} - NOT Gamma API
-- The 'tags' field is available in CLOB API, not in Gamma API /markets
-- Tag examples: Sports, Politics, Weather, Crypto, Economics
-- Tag mapping from API:
--   - Sports: ["Sports", "Soccer", "FIFA World Cup"]
--   - Weather: ["Weather", "Recurring", "Seoul", "Daily Temperature"]  
--   - Crypto: ["Crypto", "Bitcoin", "Up/Down"]
--   - Politics: ["Politics", "Elections", "2024"]
--   - Economics: ["Economics", "Fed", "Interest Rates"]

-- Add market_tags column to whale_trades
-- Store as TEXT - can be JSON array string or comma-separated values
ALTER TABLE whale_trades 
    ADD COLUMN IF NOT EXISTS market_tags TEXT;

-- Create index for tag queries
CREATE INDEX IF NOT EXISTS idx_whale_trades_tags 
    ON whale_trades(market_tags);

-- Add comment for documentation
COMMENT ON COLUMN whale_trades.market_tags IS 'Market tags from CLOB API (tags field) - e.g. Sports, Politics, Weather, Crypto';
