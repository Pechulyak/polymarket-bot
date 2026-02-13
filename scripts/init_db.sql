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
    opportunity_id UUID REFERENCES opportunities(opportunity_id),
    market_id VARCHAR(255) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    size DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
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

-- Whales tracking table
CREATE TABLE IF NOT EXISTS whales (
    id SERIAL PRIMARY KEY,
    wallet_address VARCHAR(66) NOT NULL UNIQUE,
    first_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    total_trades INTEGER NOT NULL DEFAULT 0,
    win_rate DECIMAL(5, 4) NOT NULL DEFAULT 0,
    total_profit_usd DECIMAL(20, 8) NOT NULL DEFAULT 0,
    avg_trade_size_usd DECIMAL(20, 8) NOT NULL DEFAULT 0,
    last_active_at TIMESTAMP NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    risk_score INTEGER NOT NULL DEFAULT 5 CHECK (risk_score >= 1 AND risk_score <= 10),
    
    -- Additional metadata
    source VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_whales_address ON whales(wallet_address);
CREATE INDEX IF NOT EXISTS idx_whales_winrate ON whales(win_rate DESC);
CREATE INDEX IF NOT EXISTS idx_whales_active ON whales(is_active, last_active_at);
CREATE INDEX IF NOT EXISTS idx_whales_risk ON whales(risk_score);

-- Whale trades history (for analysis)
CREATE TABLE IF NOT EXISTS whale_trades (
    id SERIAL PRIMARY KEY,
    whale_id INTEGER NOT NULL REFERENCES whales(id),
    market_id VARCHAR(255) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    size_usd DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    outcome VARCHAR(50),
    is_winner BOOLEAN,
    profit_usd DECIMAL(20, 8),
    traded_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_whale_trades_whale ON whale_trades(whale_id, traded_at);
CREATE INDEX IF NOT EXISTS idx_whale_trades_market ON whale_trades(market_id, traded_at);

-- Insert initial bankroll record
INSERT INTO bankroll (total_capital, allocated, available, daily_pnl, daily_drawdown)
VALUES (100.00, 0, 100.00, 0, 0);
