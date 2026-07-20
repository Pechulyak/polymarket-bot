-- Polymarket Trading Bot Database Schema
-- Run: psql -U postgres -d polymarket -f scripts/init_db.sql

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

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

CREATE UNIQUE INDEX IF NOT EXISTS idx_whale_trades_tx_hash ON whale_trades(tx_hash) WHERE tx_hash IS NOT NULL AND tx_hash <> '';
-- INFRA-DIAG: fix close_sell Seq Scan degradation (1638s→92s)
CREATE INDEX IF NOT EXISTS idx_whale_trades_sell_match ON whale_trades(wallet_address, market_id, outcome, side, traded_at);
-- INFRA-031: fix buy query 12.7s→4.0s
CREATE INDEX IF NOT EXISTS idx_whale_trades_buy_match ON whale_trades(wallet_address, market_id, outcome, traded_at) WHERE side = 'buy';
-- INFRA-034: fix sell query (removed LOWER, added partial index)
CREATE INDEX IF NOT EXISTS idx_whale_trades_sell_partial ON whale_trades(wallet_address, market_id, outcome, traded_at) WHERE side = 'sell';

-- INFRA-030 / A1b: retention indexes for whale_trade_roundtrips
-- Required by retention_whale_trades() procedure for NOT EXISTS lookups
CREATE INDEX IF NOT EXISTS idx_rt_open_trade_id ON whale_trade_roundtrips(open_trade_id);
CREATE INDEX IF NOT EXISTS idx_rt_close_trade_id ON whale_trade_roundtrips(close_trade_id) WHERE close_trade_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rt_open_position_lookup ON whale_trade_roundtrips(wallet_address, market_id, outcome) WHERE status = 'OPEN';

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

-- =============================================================================
-- PHASE1.5-002: Strategy config for proportional Kelly sizing
-- =============================================================================

-- Strategy configuration table for Kelly sizing parameters
CREATE TABLE IF NOT EXISTS strategy_config (
    key VARCHAR(100) PRIMARY KEY,
    value DECIMAL(20, 8) NOT NULL,
    description TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- PHASE1.5-002: Whale capital estimation columns
ALTER TABLE whales ADD COLUMN IF NOT EXISTS estimated_capital DECIMAL(20, 8);
ALTER TABLE whales ADD COLUMN IF NOT EXISTS capital_estimation_method VARCHAR(20) DEFAULT 'manual';

-- =============================================================================
-- INFRA-030 / A3: retention_whale_trades procedure
-- Call: CALL retention_whale_trades(30, 10000);
-- Variant A (asymmetric): BUY older than p_days deletable even at OPEN;
-- SELL protected while an OPEN roundtrip exists on same wallet+market+outcome.
-- PROCEDURE (not function) — needs COMMIT inside loop.
-- Live NOT EXISTS each batch (no snapshot) — safe against concurrent 3B/3C.
-- Indexes A1b cover all three NOT EXISTS (Index Only Scan).
-- =============================================================================

CREATE OR REPLACE PROCEDURE public.retention_whale_trades(
    IN p_days  integer DEFAULT 30,
    IN p_batch integer DEFAULT 10000
)
LANGUAGE plpgsql
AS $procedure$
DECLARE
    v_batch_num      INT := 0;
    v_deleted_total  BIGINT := 0;
    v_rowcount       INT := 1;
BEGIN
    IF p_days < 1 OR p_batch < 1 THEN
        RAISE NOTICE 'Invalid parameters: p_days=%, p_batch=%. Must be >= 1.', p_days, p_batch;
        RETURN;
    END IF;

    RAISE NOTICE 'Starting retention_whale_trades: p_days=%, p_batch=%', p_days, p_batch;

    WHILE v_rowcount > 0 LOOP
        v_batch_num := v_batch_num + 1;

        DELETE FROM whale_trades wt
        WHERE wt.id IN (
            SELECT wt2.id
            FROM whale_trades wt2
            WHERE wt2.traded_at < NOW() - make_interval(days => p_days)
              -- anchor BUY protected (FK open_trade_id)
              AND NOT EXISTS (
                  SELECT 1 FROM whale_trade_roundtrips rt
                  WHERE rt.open_trade_id = wt2.id
              )
              -- close-referenced protected (FK close_trade_id)
              AND NOT EXISTS (
                  SELECT 1 FROM whale_trade_roundtrips rt
                  WHERE rt.close_trade_id = wt2.id
              )
              -- Variant A asymmetry:
              -- BUY always deletable (no reader of old unreferenced BUY);
              -- SELL kept while OPEN exists (3C needs it to close the position).
              AND (
                  wt2.side = 'buy'
                  OR NOT EXISTS (
                      SELECT 1 FROM whale_trade_roundtrips rt
                      WHERE rt.wallet_address = wt2.wallet_address
                        AND rt.market_id      = wt2.market_id
                        AND (rt.outcome = wt2.outcome
                             OR (rt.outcome IS NULL AND wt2.outcome IS NULL))
                        AND rt.status = 'OPEN'
                  )
              )
            LIMIT p_batch
        );

        GET DIAGNOSTICS v_rowcount = ROW_COUNT;
        v_deleted_total := v_deleted_total + v_rowcount;

        RAISE NOTICE 'Batch %: deleted %, total %', v_batch_num, v_rowcount, v_deleted_total;

        COMMIT;
    END LOOP;

    RAISE NOTICE 'Retention complete. Batches: %, Total deleted: %', v_batch_num, v_deleted_total;
END;
$procedure$;
