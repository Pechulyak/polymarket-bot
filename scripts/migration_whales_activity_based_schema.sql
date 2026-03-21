-- Migration: TRD-418 Whales Schema Redesign (Staged Migration)
-- Phase 1: Add new columns (without dropping legacy)
-- Date: 2026-03-20

BEGIN;

-- ============================================================
-- PHASE 1: Add new columns for activity-based schema
-- ============================================================

-- Identification / registry
ALTER TABLE whales ADD COLUMN IF NOT EXISTS qualification_status VARCHAR(20) NOT NULL DEFAULT 'discovered';
ALTER TABLE whales ADD COLUMN IF NOT EXISTS source_new VARCHAR(32) NOT NULL DEFAULT 'discovery';

-- Lifecycle / observation state
ALTER TABLE whales ADD COLUMN IF NOT EXISTS tier VARCHAR(10);
ALTER TABLE whales ADD COLUMN IF NOT EXISTS first_discovered_at TIMESTAMP NOT NULL DEFAULT NOW();
ALTER TABLE whales ADD COLUMN IF NOT EXISTS last_seen_in_feed TIMESTAMP;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS last_targeted_fetch_at TIMESTAMP;

-- Activity metrics
ALTER TABLE whales ADD COLUMN IF NOT EXISTS trades_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS days_active_7d INTEGER NOT NULL DEFAULT 0;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS days_active_30d INTEGER NOT NULL DEFAULT 0;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS trades_per_day NUMERIC(20,8) NOT NULL DEFAULT 0;

-- ============================================================
-- PHASE 2: Backfill data from legacy columns
-- ============================================================

-- Copy trades_count from total_trades
UPDATE whales SET trades_count = total_trades WHERE trades_count = 0;

-- Copy first_discovered_at from first_seen_at
UPDATE whales SET first_discovered_at = first_seen_at WHERE first_discovered_at IS NULL;

-- Copy qualification_status from status
UPDATE whales SET qualification_status = status WHERE qualification_status = 'discovered';

-- Copy source from existing source column
UPDATE whales SET source_new = COALESCE(source, 'discovery') WHERE source_new IS NULL OR source_new = 'discovery';

COMMIT;

-- ============================================================
-- PHASE 3: Add CHECK constraints
-- ============================================================

-- qualification_status CHECK
ALTER TABLE whales DROP CONSTRAINT IF EXISTS whales_qualification_status_check;
ALTER TABLE whales ADD CONSTRAINT whales_qualification_status_check
    CHECK (qualification_status IN ('discovered','candidate','tracked','qualified','ranked','cold'));

-- Set activity values for manual whales to match auto_detected
UPDATE whales
SET trades_last_3_days = 0,
    days_active_7d = 0,
    days_active_30d = 0
WHERE source_new = 'manual';

-- Drop deprecated win_rate column
ALTER TABLE whales DROP COLUMN IF EXISTS win_rate;

-- tier CHECK
ALTER TABLE whales DROP CONSTRAINT IF EXISTS whales_tier_check;
ALTER TABLE whales ADD CONSTRAINT whales_tier_check 
    CHECK (tier IN ('HOT','WARM','COLD') OR tier IS NULL);

-- trades_count CHECK
ALTER TABLE whales DROP CONSTRAINT IF EXISTS whales_trades_count_check;
ALTER TABLE whales ADD CONSTRAINT whales_trades_count_check 
    CHECK (trades_count >= 0);

-- trades_last_3_days CHECK
ALTER TABLE whales DROP CONSTRAINT IF EXISTS whales_trades_last_3_days_check;
ALTER TABLE whales ADD CONSTRAINT whales_trades_last_3_days_check 
    CHECK (trades_last_3_days >= 0);

-- trades_last_7_days CHECK
ALTER TABLE whales DROP CONSTRAINT IF EXISTS whales_trades_last_7_days_check;
ALTER TABLE whales ADD CONSTRAINT whales_trades_last_7_days_check 
    CHECK (trades_last_7_days >= 0);

-- days_active_7d CHECK
ALTER TABLE whales DROP CONSTRAINT IF EXISTS whales_days_active_7d_check;
ALTER TABLE whales ADD CONSTRAINT whales_days_active_7d_check 
    CHECK (days_active_7d >= 0);

-- days_active_30d CHECK
ALTER TABLE whales DROP CONSTRAINT IF EXISTS whales_days_active_30d_check;
ALTER TABLE whales ADD CONSTRAINT whales_days_active_30d_check 
    CHECK (days_active_30d >= 0);

-- trades_per_day CHECK
ALTER TABLE whales DROP CONSTRAINT IF EXISTS whales_trades_per_day_check;
ALTER TABLE whales ADD CONSTRAINT whales_trades_per_day_check 
    CHECK (trades_per_day >= 0);

-- risk_score CHECK (update existing)
ALTER TABLE whales DROP CONSTRAINT IF EXISTS whales_risk_score_check;
ALTER TABLE whales ADD CONSTRAINT whales_risk_score_check 
    CHECK (risk_score >= 1 AND risk_score <= 10 OR risk_score IS NULL);

-- ============================================================
-- PHASE 4: Add Comments (for DBeaver display)
-- ============================================================

-- Legacy columns
COMMENT ON COLUMN whales.id IS 'Уникальный идентификатор записи';
COMMENT ON COLUMN whales.wallet_address IS 'Адрес кошелька кита (уникальный идентификатор)';
COMMENT ON COLUMN whales.first_seen_at IS 'Время первого обнаружения адреса (legacy)';
COMMENT ON COLUMN whales.total_trades IS 'Общее количество сделок (legacy - использовать trades_count)';
COMMENT ON COLUMN whales.win_rate IS 'Процент выигрышных сделок (legacy)';
COMMENT ON COLUMN whales.total_profit_usd IS 'Общая прибыль в USD (legacy)';
COMMENT ON COLUMN whales.avg_trade_size_usd IS 'Средний размер сделки в USD';
COMMENT ON COLUMN whales.last_active_at IS 'Время последней активности';
COMMENT ON COLUMN whales.is_active IS 'Признак активности (legacy)';
COMMENT ON COLUMN whales.risk_score IS 'Оценка риска (1-10)';
COMMENT ON COLUMN whales.source IS 'Источник обнаружения (legacy)';
COMMENT ON COLUMN whales.notes IS 'Заметки по адресу';
COMMENT ON COLUMN whales.created_at IS 'Время создания записи';
COMMENT ON COLUMN whales.updated_at IS 'Время последнего обновления записи';
COMMENT ON COLUMN whales.total_volume_usd IS 'Общий объём торгов в USD';
COMMENT ON COLUMN whales.status IS 'Статус (legacy - использовать qualification_status)';
COMMENT ON COLUMN whales.trades_last_3_days IS 'Количество сделок за последние 3 дня';
COMMENT ON COLUMN whales.days_active IS 'Количество активных дней (legacy - использовать days_active_7d/30d)';
COMMENT ON COLUMN whales.qualification_path IS 'Путь квалификации (legacy)';
COMMENT ON COLUMN whales.trades_last_7_days IS 'Количество сделок за последние 7 дней';

-- New activity-based columns
COMMENT ON COLUMN whales.qualification_status IS 'Статус квалификации: discovered/candidate/tracked/qualified/cold';
COMMENT ON COLUMN whales.source_new IS 'Источник обнаружения: discovery/backfill/manual';
COMMENT ON COLUMN whales.tier IS 'Уровень наблюдения: HOT/WARM/COLD';
COMMENT ON COLUMN whales.first_discovered_at IS 'Время первого обнаружения адреса системой';
COMMENT ON COLUMN whales.last_seen_in_feed IS 'Последний момент, когда адрес был замечен в discovery feed';
COMMENT ON COLUMN whales.last_targeted_fetch_at IS 'Время последнего целевого запроса API по адресу';
COMMENT ON COLUMN whales.trades_count IS 'Общее количество сделок адреса в истории';
COMMENT ON COLUMN whales.days_active_7d IS 'Количество уникальных дней торгов за последние 7 дней';
COMMENT ON COLUMN whales.days_active_30d IS 'Количество уникальных дней торгов за последние 30 дней';
COMMENT ON COLUMN whales.trades_per_day IS 'Среднее число сделок в день';
COMMENT ON COLUMN whales.last_qualified_at IS 'Время последнего подтверждения статуса qualified';

-- ============================================================
-- PHASE 5: Add Indexes
-- ============================================================

-- Drop old indexes that may conflict
DROP INDEX IF EXISTS idx_whales_winrate;
DROP INDEX IF EXISTS idx_whales_qualified;
DROP INDEX IF EXISTS idx_whales_ranked;

-- Add new indexes
CREATE INDEX IF NOT EXISTS idx_whales_qualification_status ON whales(qualification_status);
CREATE INDEX IF NOT EXISTS idx_whales_tier ON whales(tier);
CREATE INDEX IF NOT EXISTS idx_whales_last_active_at ON whales(last_active_at);
CREATE INDEX IF NOT EXISTS idx_whales_last_seen_in_feed ON whales(last_seen_in_feed);
CREATE INDEX IF NOT EXISTS idx_whales_last_targeted_fetch_at ON whales(last_targeted_fetch_at);

-- Keep existing useful indexes
-- idx_whales_address (unique)
-- idx_whales_risk
-- idx_whales_active

-- ============================================================
-- PHASE 6: Data Validation
-- ============================================================

SELECT 'Rows in whales after migration:' as info, COUNT(*) as row_count FROM whales;
SELECT 'Check NULLs in qualification_status:' as info, COUNT(*) as null_count FROM whales WHERE qualification_status IS NULL;
SELECT 'Check NULLs in trades_count:' as info, COUNT(*) as null_count FROM whales WHERE trades_count IS NULL;
SELECT 'Check NULLs in first_discovered_at:' as info, COUNT(*) as null_count FROM whales WHERE first_discovered_at IS NULL;
