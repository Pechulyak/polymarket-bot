-- ARC-501: Whales schema cleanup + P&L fields
-- Date: 2026-03-22
-- Backup required before execution: backups/whales_pre_arc501_20260322_190604.sql

BEGIN;

-- =====================
-- STEP 1: Remove redundant/dead columns
-- =====================

-- total_profit_usd: always 0, API doesn't provide
ALTER TABLE whales DROP COLUMN IF EXISTS total_profit_usd;

-- is_active: replaced by qualification_status
ALTER TABLE whales DROP COLUMN IF EXISTS is_active;

-- status: replaced by qualification_status
ALTER TABLE whales DROP COLUMN IF EXISTS status;

-- qualification_path: redundant
ALTER TABLE whales DROP COLUMN IF EXISTS qualification_path;

-- source: duplicate of source_new
ALTER TABLE whales DROP COLUMN IF EXISTS source;

-- trades_count: duplicate of total_trades
ALTER TABLE whales DROP COLUMN IF EXISTS trades_count;

-- days_active: replaced by days_active_7d
ALTER TABLE whales DROP COLUMN IF EXISTS days_active;

-- first_discovered_at: duplicate of first_seen_at
ALTER TABLE whales DROP COLUMN IF EXISTS first_discovered_at;

-- =====================
-- STEP 2: Add P&L fields
-- =====================

-- Confirmed closed positions count (win)
ALTER TABLE whales ADD COLUMN IF NOT EXISTS 
    win_count INTEGER NOT NULL DEFAULT 0;

-- Confirmed closed positions count (loss)
ALTER TABLE whales ADD COLUMN IF NOT EXISTS 
    loss_count INTEGER NOT NULL DEFAULT 0;

-- Total confirmed closed positions
ALTER TABLE whales ADD COLUMN IF NOT EXISTS 
    total_roundtrips INTEGER NOT NULL DEFAULT 0;

-- Total realized P&L from confirmed closed positions
ALTER TABLE whales ADD COLUMN IF NOT EXISTS 
    total_pnl_usd DECIMAL(20,8) NOT NULL DEFAULT 0;

-- Average P&L per closed position
ALTER TABLE whales ADD COLUMN IF NOT EXISTS 
    avg_pnl_usd DECIMAL(20,8) NOT NULL DEFAULT 0;

-- Win rate from confirmed closed positions only
-- (NOT from API - calculated from actual roundtrips)
ALTER TABLE whales ADD COLUMN IF NOT EXISTS 
    win_rate_confirmed DECIMAL(5,4) NOT NULL DEFAULT 0;

-- Last time P&L was updated
ALTER TABLE whales ADD COLUMN IF NOT EXISTS 
    last_pnl_updated TIMESTAMP NULL;

COMMIT;