-- Migration: Create market_resolutions table
-- PHASE3-003: Settlement engine using Gamma API
-- Run: psql -U postgres -d polymarket -f scripts/migration_market_resolutions.sql
-- Rollback: scripts/rollback_market_resolutions.sql

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Market resolutions cache
-- Stores resolved market data from Gamma API for settlement calculation
CREATE TABLE IF NOT EXISTS market_resolutions (
    id SERIAL PRIMARY KEY,
    resolution_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    market_id VARCHAR(255) NOT NULL UNIQUE,
    condition_id VARCHAR(255),
    
    -- Resolution state from Gamma API
    closed BOOLEAN DEFAULT FALSE,
    uma_resolution_status VARCHAR(50),  -- 'unresolved', 'resolved', 'failed'
    resolved_by VARCHAR(255),
    resolved_at TIMESTAMP,
    
    -- Outcomes from Gamma API
    outcomes JSONB,  -- e.g. ["Yes", "No"]
    outcome_prices JSONB,  -- e.g. ["1", "0"] after resolution
    
    -- Derived settlement values
    winning_outcome VARCHAR(100),
    settlement_price DECIMAL(20, 8),  -- 1.0 for winner, 0.0 for loser
    
    -- Metadata from API
    end_date TIMESTAMP,
    question_text TEXT,
    api_response JSONB,  -- Full API response for debugging
    
    -- Tracking
    first_seen TIMESTAMP NOT NULL DEFAULT NOW(),
    last_updated TIMESTAMP NOT NULL DEFAULT NOW(),
    resolution_checks INTEGER DEFAULT 0
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_resolution_market ON market_resolutions(market_id);
CREATE INDEX IF NOT EXISTS idx_resolution_condition ON market_resolutions(condition_id);
CREATE INDEX IF NOT EXISTS idx_resolution_status ON market_resolutions(uma_resolution_status);
CREATE INDEX IF NOT EXISTS idx_resolution_updated ON market_resolutions(last_updated);
CREATE INDEX IF NOT EXISTS idx_resolution_closed ON market_resolutions(closed, uma_resolution_status) 
    WHERE uma_resolution_status = 'resolved';

-- Comments for documentation
COMMENT ON TABLE market_resolutions IS 'Stores Polymarket resolution data from Gamma API for paper settlement';
COMMENT ON COLUMN market_resolutions.market_id IS 'Polymarket conditionId';
COMMENT ON COLUMN market_resolutions.condition_id IS 'UMA conditionId';
COMMENT ON COLUMN market_resolutions.closed IS 'Market closed in Gamma metadata';
COMMENT ON COLUMN market_resolutions.uma_resolution_status IS 'UMA resolution status: unresolved|resolved|failed';
COMMENT ON COLUMN market_resolutions.winning_outcome IS 'Derived winning outcome (e.g. Yes, No)';
COMMENT ON COLUMN market_resolutions.settlement_price IS 'Settlement price: 1.0 for winner, 0.0 for loser';