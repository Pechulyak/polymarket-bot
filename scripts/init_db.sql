-- Polymarket Trading Bot Database Schema
-- Run: psql -U postgres -d polymarket -f scripts/init_db.sql

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Market data cache
CREATE TABLE IF NOT EXISTS market_data (
    id SERIAL PRIMARY KEY,
    market_id VARCHAR(255) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    best_bid DECIMAL(20, 8) NOT NULL,
    best_ask DECIMAL(20, 8) NOT NULL,
    bid_volume DECIMAL(20, 8),
    ask_volume DECIMAL(20, 8),
    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_time ON market_data(market_id, timestamp);

-- Trading opportunities detected
CREATE TABLE IF NOT EXISTS opportunities (
    id SERIAL PRIMARY KEY,
    opportunity_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    market_id VARCHAR(255) NOT NULL,
    strategy VARCHAR(100) NOT NULL,
    polymarket_price DECIMAL(20, 8) NOT NULL,
    bybit_price DECIMAL(20, 8) NOT NULL,
    spread_bps DECIMAL(10, 4) NOT NULL,
    gross_edge DECIMAL(20, 8) NOT NULL,
    net_edge DECIMAL(20, 8) NOT NULL,
    kelly_fraction DECIMAL(10, 8) NOT NULL,
    recommended_size DECIMAL(20, 8) NOT NULL,
    detected_at TIMESTAMP NOT NULL DEFAULT NOW(),
    executed BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_detected ON opportunities(detected_at, executed);

-- Trade execution log
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    trade_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    opportunity_id VARCHAR(255),
    market_id VARCHAR(255) NOT NULL,
    whale_source VARCHAR(255),
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    size DECIMAL(20, 8) NOT NULL,
    open_price DECIMAL(20, 8),  -- Entry price (from paper_trades.price)
    close_price DECIMAL(20, 8), -- Exit/settlement price (1.0 for winner, 0.0 for loser)
    exchange VARCHAR(50) NOT NULL,
    
    -- Fee breakdown
    commission DECIMAL(20, 8) NOT NULL,
    gas_cost_eth DECIMAL(20, 18),
    gas_cost_usd DECIMAL(20, 8),
    fiat_fees DECIMAL(20, 8),
    
    -- PnL tracking
    gross_pnl DECIMAL(20, 8),
    total_fees DECIMAL(20, 8),
    net_pnl DECIMAL(20, 8),
    
    status VARCHAR(50) NOT NULL,
    executed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    settled_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id, executed_at);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);

-- Position tracking
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    position_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    market_id VARCHAR(255) NOT NULL,
    polymarket_size DECIMAL(20, 8) NOT NULL DEFAULT 0,
    bybit_size DECIMAL(20, 8) NOT NULL DEFAULT 0,
    net_exposure DECIMAL(20, 8) NOT NULL DEFAULT 0,
    avg_entry_price DECIMAL(20, 8),
    unrealized_pnl DECIMAL(20, 8) DEFAULT 0,
    realized_pnl DECIMAL(20, 8) DEFAULT 0,
    opened_at TIMESTAMP NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'open'
);

CREATE INDEX IF NOT EXISTS idx_positions_market ON positions(market_id, status);

-- Bankroll tracking
CREATE TABLE IF NOT EXISTS bankroll (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    total_capital DECIMAL(20, 8) NOT NULL,
    allocated DECIMAL(20, 8) NOT NULL DEFAULT 0,
    available DECIMAL(20, 8) NOT NULL,
    daily_pnl DECIMAL(20, 8) DEFAULT 0,
    daily_drawdown DECIMAL(10, 4) DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_bankroll_time ON bankroll(timestamp);

-- Risk events log
CREATE TABLE IF NOT EXISTS risk_events (
    id SERIAL PRIMARY KEY,
    event_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    event_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    description TEXT NOT NULL,
    market_id VARCHAR(255),
    position_id UUID,
    triggered_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP,
    resolution_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_risk_triggered ON risk_events(triggered_at, severity);

-- Fee structure
CREATE TABLE IF NOT EXISTS fee_schedule (
    id SERIAL PRIMARY KEY,
    exchange VARCHAR(50) NOT NULL,
    fee_type VARCHAR(50) NOT NULL,
    fee_percentage DECIMAL(10, 6),
    fixed_fee DECIMAL(20, 8),
    currency VARCHAR(10),
    effective_from TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (exchange, fee_type, effective_from)
);

-- API latency monitoring
CREATE TABLE IF NOT EXISTS api_health (
    id SERIAL PRIMARY KEY,
    exchange VARCHAR(50) NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    latency_ms INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    checked_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_health ON api_health(checked_at, exchange);

-- Insert initial fee schedule
INSERT INTO fee_schedule (exchange, fee_type, fee_percentage, fixed_fee, currency) VALUES
('bybit', 'deposit_fiat', 0.001, 0, 'USD'),
('bybit', 'trading', 0.00055, 0, 'USD'),
('bybit', 'withdrawal', 0, 10, 'USD'),
('polymarket', 'trading', 0.002, 0, 'USD'),
('ethereum', 'gas', NULL, NULL, 'ETH')
ON CONFLICT DO NOTHING;

-- Whales tracking table (TRD-419: activity-based schema, ARC-501: P&L fields added)
CREATE TABLE IF NOT EXISTS whales (
    id SERIAL PRIMARY KEY,
    wallet_address VARCHAR(66) NOT NULL UNIQUE,
    first_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    total_trades INTEGER NOT NULL DEFAULT 0,
    -- total_profit_usd REMOVED - API does not provide, use total_pnl_usd
    total_volume_usd DECIMAL(20, 8) NOT NULL DEFAULT 0,
    avg_trade_size_usd DECIMAL(20, 8) NOT NULL DEFAULT 0,
    last_active_at TIMESTAMP NOT NULL DEFAULT NOW(),
    -- is_active REMOVED - use qualification_status
    risk_score INTEGER CHECK (risk_score >= 1 AND risk_score <= 10 OR risk_score IS NULL),
    
    -- status REMOVED - use qualification_status
    trades_last_3_days INTEGER NOT NULL DEFAULT 0,
    trades_last_7_days INTEGER NOT NULL DEFAULT 0,
    -- days_active REMOVED - use days_active_7d
    last_qualified_at TIMESTAMP,
    last_ranked_at TIMESTAMP,
    
    -- TRD-419: New activity-based schema
    qualification_status VARCHAR(20) NOT NULL DEFAULT 'discovered' CHECK (qualification_status IN ('discovered', 'candidate', 'tracked', 'qualified', 'ranked', 'cold')),
    source_new VARCHAR(32) NOT NULL DEFAULT 'discovery',
    tier VARCHAR(10) CHECK (tier IN ('HOT', 'WARM', 'COLD') OR tier IS NULL),
    -- first_discovered_at REMOVED - use first_seen_at
    last_seen_in_feed TIMESTAMP,
    last_targeted_fetch_at TIMESTAMP,
    -- trades_count REMOVED - use total_trades
    days_active_7d INTEGER NOT NULL DEFAULT 0,
    days_active_30d INTEGER NOT NULL DEFAULT 0,
    trades_per_day NUMERIC(20, 8) NOT NULL DEFAULT 0,
    
    -- qualification_path REMOVED - redundant
    -- source REMOVED - duplicate of source_new
    
    -- Additional metadata
    notes TEXT,
    
    -- ARC-501: P&L fields (calculated from whale_trade_roundtrips)
    win_count INTEGER NOT NULL DEFAULT 0,
    loss_count INTEGER NOT NULL DEFAULT 0,
    total_roundtrips INTEGER NOT NULL DEFAULT 0,
    total_pnl_usd DECIMAL(20, 8) NOT NULL DEFAULT 0,
    avg_pnl_usd DECIMAL(20, 8) NOT NULL DEFAULT 0,
    win_rate_confirmed DECIMAL(5, 4) NOT NULL DEFAULT 0,
    last_pnl_updated TIMESTAMP,
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- STRAT-701: Copy trading status with whale classification
    -- WHALE-701: Added 'excluded' for excluded whales
    copy_status VARCHAR(10) DEFAULT 'none' CHECK (copy_status IN ('none', 'paper', 'live', 'tracked', 'excluded')),
    
    -- WHALE-701: Whale classification fields
    whale_category VARCHAR(20),
    whale_comment TEXT,
    reviewed_at TIMESTAMP,
    exclusion_reason VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_whales_address ON whales(wallet_address);
-- idx_whales_active REMOVED - is_active column removed
-- idx_whales_status REMOVED - status column removed
CREATE INDEX IF NOT EXISTS idx_whales_risk ON whales(risk_score);
-- Legacy indexes (deprecated)
CREATE INDEX IF NOT EXISTS idx_whales_trades_3days ON whales(trades_last_3_days DESC);
CREATE INDEX IF NOT EXISTS idx_whales_trades_7days ON whales(trades_last_7_days DESC);
-- TRD-419: New activity-based indexes
CREATE INDEX IF NOT EXISTS idx_whales_qualification_status ON whales(qualification_status);
CREATE INDEX IF NOT EXISTS idx_whales_tier ON whales(tier);
CREATE INDEX IF NOT EXISTS idx_whales_last_active_at ON whales(last_active_at);
CREATE INDEX IF NOT EXISTS idx_whales_last_seen_in_feed ON whales(last_seen_in_feed);
CREATE INDEX IF NOT EXISTS idx_whales_last_targeted_fetch_at ON whales(last_targeted_fetch_at);

-- Whale trades history (for analysis) - ARC-503: removed is_winner, profit_usd
-- TRD-420-B: Added CHECK constraint for source with 'TRACKED' value
CREATE TABLE IF NOT EXISTS whale_trades (
    id SERIAL PRIMARY KEY,
    whale_id INTEGER REFERENCES whales(id),
    wallet_address VARCHAR(66) NOT NULL,
    market_id VARCHAR(255) NOT NULL,
    market_title VARCHAR(500),
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    size_usd DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    outcome VARCHAR(50),
    traded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    tx_hash VARCHAR(66),
    source VARCHAR(32) NOT NULL DEFAULT 'BACKFILL' CHECK (source IN ('realtime', 'backfill', 'unknown', 'BACKFILL', 'TRIGGER_TEST', 'POLLER', 'PAPER_TRACK', 'PAPER', 'TRACKED'))
);

CREATE INDEX IF NOT EXISTS idx_whale_trades_whale ON whale_trades(whale_id, traded_at);
CREATE INDEX IF NOT EXISTS idx_whale_trades_market ON whale_trades(market_id, traded_at);
CREATE INDEX IF NOT EXISTS idx_whale_trades_wallet ON whale_trades(wallet_address, traded_at);
CREATE INDEX IF NOT EXISTS idx_whale_trades_tx_hash ON whale_trades(tx_hash) WHERE tx_hash IS NOT NULL;

-- Insert initial bankroll record
INSERT INTO bankroll (total_capital, allocated, available, daily_pnl, daily_drawdown)
VALUES (100.00, 0, 100.00, 0, 0);

-- ARC-503: Remove legacy fields is_winner and profit_usd from whale_trades
-- These fields were removed because Polymarket Data API does not provide settlement outcomes
ALTER TABLE whale_trades DROP COLUMN IF EXISTS is_winner;
ALTER TABLE whale_trades DROP COLUMN IF EXISTS profit_usd;

-- BUG-505: paper_trades table with tx_hash for deduplication
-- Created by trigger_copy_whale_trade from whale_trades
CREATE TABLE IF NOT EXISTS paper_trades (
    id SERIAL PRIMARY KEY,
    trade_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    whale_address VARCHAR(66) NOT NULL,
    market_id VARCHAR(255) NOT NULL,
    market_title TEXT,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    outcome VARCHAR(50),
    price DECIMAL(20, 8) NOT NULL,
    size DECIMAL(20, 8) NOT NULL,  -- Calculated shares (size_usd / price)
    size_usd DECIMAL(20, 8) NOT NULL,
    kelly_fraction DECIMAL(10, 8) NOT NULL DEFAULT 0.25,
    kelly_size DECIMAL(20, 8) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'settled')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    settled_at TIMESTAMP,
    source VARCHAR(20) DEFAULT 'unknown' CHECK (source IN ('REALTIME', 'BACKFILL', 'TRIGGER_TEST', 'unknown', 'PAPER')),
    
    -- BUG-505: tx_hash for transaction-level deduplication
    tx_hash VARCHAR(70)
);

-- Indexes for paper_trades
CREATE INDEX IF NOT EXISTS idx_paper_trades_whale ON paper_trades(whale_address, created_at);
CREATE INDEX IF NOT EXISTS idx_paper_trades_market ON paper_trades(market_id, created_at);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);

-- BUG-505: Partial unique index to prevent duplicate tx_hash entries
-- Only enforces uniqueness for non-null tx_hash values
CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_trades_tx_hash_unique 
ON paper_trades(tx_hash) WHERE tx_hash IS NOT NULL;

-- =============================================================================
-- WHALE-701: Migration for whale classification fields
-- =============================================================================

-- Add classification fields to whales table
ALTER TABLE whales ADD COLUMN IF NOT EXISTS whale_category VARCHAR(20);
ALTER TABLE whales ADD COLUMN IF NOT EXISTS whale_comment TEXT;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS exclusion_reason VARCHAR(50);

-- Expand copy_status CHECK constraint to include 'excluded'
ALTER TABLE whales DROP CONSTRAINT IF EXISTS whales_copy_status_check;
ALTER TABLE whales ADD CONSTRAINT whales_copy_status_check 
    CHECK (copy_status IN ('none', 'paper', 'live', 'tracked', 'excluded'));
