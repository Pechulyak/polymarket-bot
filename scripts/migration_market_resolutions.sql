-- PHASE3-002: Market resolutions cache table
-- Populated by fetch_market_resolutions.py (CLOB API)
-- Consumed by settle_resolved_positions()

BEGIN;

CREATE TABLE IF NOT EXISTS market_resolutions (
    market_id VARCHAR(255) PRIMARY KEY,
    is_closed BOOLEAN NOT NULL DEFAULT FALSE,
    winner_outcome VARCHAR(100),
    tokens JSONB,
    resolution_source VARCHAR(20) NOT NULL DEFAULT 'CLOB',
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_market_resolutions_closed 
ON market_resolutions(is_closed) WHERE is_closed = TRUE;

COMMENT ON TABLE market_resolutions IS 
    'Cache of CLOB API market resolution data for SQL-based settlement';

COMMIT;