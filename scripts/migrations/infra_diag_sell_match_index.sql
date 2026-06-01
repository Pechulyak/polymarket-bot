-- Migration: idx_whale_trades_sell_match
-- Task: INFRA-DIAG — fix close_sell Seq Scan degradation (1638s→92s)
-- Created: 2026-05-31
-- Source: diagnosed on live DB (index already present), now persisting to repo

-- Close-matching index: wallet_address + market_id + outcome + side + traded_at
-- Used by roundtrip_builder close path (_fetch_and_group_sell_trades, _close_roundtrips)
-- BEFORE: Seq Scan on whale_trades → 1638s close duration
-- AFTER: Index Only Scan → ~70-92s close duration

CREATE INDEX IF NOT EXISTS idx_whale_trades_sell_match
ON whale_trades (wallet_address, market_id, outcome, side, traded_at);