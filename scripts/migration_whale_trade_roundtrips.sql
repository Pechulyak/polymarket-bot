-- Migration: Create whale_trade_roundtrips table
-- Task: TRD-412 - Whale position reconstruction layer
-- Description: Analytical table to reconstruct whale positions from event-level whale_trades

-- Create whale_trade_roundtrips table
CREATE TABLE IF NOT EXISTS whale_trade_roundtrips (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Whale identification (nullable for orphaned trades)
    whale_id INTEGER REFERENCES whales(id),
    wallet_address VARCHAR(255),
    
    -- Position key (unique constraint for deduplication)
    position_key VARCHAR(255) UNIQUE NOT NULL,
    
    -- Market context
    market_id VARCHAR(255) NOT NULL,
    outcome VARCHAR(50),
    market_title TEXT,
    market_category VARCHAR(255),
    
    -- Open trade details
    open_trade_id INTEGER REFERENCES whale_trades(id),
    open_side VARCHAR(10) CHECK (open_side IN ('buy', 'sell')),
    open_price DECIMAL(20, 8),
    open_size_usd DECIMAL(20, 8),
    opened_at TIMESTAMP NOT NULL,
    
    -- Close trade details (nullable for open positions)
    close_trade_id INTEGER REFERENCES whale_trades(id),
    close_side VARCHAR(10) CHECK (close_side IN ('buy', 'sell')),
    close_price DECIMAL(20, 8),
    close_size_usd DECIMAL(20, 8),
    closed_at TIMESTAMP,
    
    -- Position status
    close_type VARCHAR(50) CHECK (
        close_type IN (
            'SELL', 
            'SETTLEMENT_WIN', 
            'SETTLEMENT_LOSS', 
            'FLIP', 
            'PARTIAL', 
            'UNKNOWN'
        )
    ),
    status VARCHAR(50) CHECK (
        status IN (
            'OPEN', 
            'CLOSED', 
            'PARTIAL', 
            'FLIPPED', 
            'UNRESOLVED'
        )
    ) NOT NULL DEFAULT 'OPEN',
    
    -- P&L calculations
    gross_pnl_usd DECIMAL(20, 8),
    fees_usd DECIMAL(20, 8) DEFAULT 0,
    net_pnl_usd DECIMAL(20, 8),
    pnl_status VARCHAR(50) CHECK (
        pnl_status IN ('CONFIRMED', 'ESTIMATED', 'UNAVAILABLE')
    ) DEFAULT 'UNAVAILABLE',
    
    -- Matching metadata
    matching_method VARCHAR(50) CHECK (
        matching_method IN (
            'DIRECT_SELL', 
            'SETTLEMENT', 
            'FLIP', 
            'PARTIAL', 
            'MANUAL_REVIEW'
        )
    ),
    matching_confidence VARCHAR(20) CHECK (
        matching_confidence IN ('HIGH', 'MEDIUM', 'LOW')
    ),
    
    -- Link to paper_trades (nullable - only if trade was actually copied)
    paper_trade_id UUID REFERENCES trades(trade_id),
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_roundtrips_wallet_address ON whale_trade_roundtrips(wallet_address);
CREATE INDEX IF NOT EXISTS idx_roundtrips_market_id ON whale_trade_roundtrips(market_id);
CREATE INDEX IF NOT EXISTS idx_roundtrips_status ON whale_trade_roundtrips(status);
CREATE INDEX IF NOT EXISTS idx_roundtrips_opened_at ON whale_trade_roundtrips(opened_at);
CREATE INDEX IF NOT EXISTS idx_roundtrips_closed_at ON whale_trade_roundtrips(closed_at);

-- Composite index for position reconstruction queries
CREATE INDEX IF NOT EXISTS idx_roundtrips_position_lookup 
    ON whale_trade_roundtrips(wallet_address, market_id, outcome, opened_at);

-- Index for paper_trade linking
CREATE INDEX IF NOT EXISTS idx_roundtrips_paper_trade_id 
    ON whale_trade_roundtrips(paper_trade_id) 
    WHERE paper_trade_id IS NOT NULL;

-- Index for whale_id lookup
CREATE INDEX IF NOT EXISTS idx_roundtrips_whale_id ON whale_trade_roundtrips(whale_id);

-- Comments for documentation
COMMENT ON TABLE whale_trade_roundtrips IS 'Whale position reconstruction table - aggregates whale_trades events into roundtrip positions';
COMMENT ON COLUMN whale_trade_roundtrips.position_key IS 'Deterministic key: hash(wallet_address + market_id + outcome + open_trade_id)';
COMMENT ON COLUMN whale_trade_roundtrips.close_type IS 'Type of close: SELL (direct), SETTLEMENT_WIN/LOSS, FLIP (Yes/No switch), PARTIAL (partial close)';
COMMENT ON COLUMN whale_trade_roundtrips.status IS 'Position status: OPEN (no close yet), CLOSED (full close), PARTIAL, FLIPPED, UNRESOLVED';
COMMENT ON COLUMN whale_trade_roundtrips.pnl_status IS 'P&L confidence: CONFIRMED (full data), ESTIMATE (partial), UNAVAILABLE';
