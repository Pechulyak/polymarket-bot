-- TRD-420: Whale Discovery Refactoring - Initial History Fields
-- Добавляем поля для хранения результатов initial history fetch

ALTER TABLE whales 
    ADD COLUMN IF NOT EXISTS initial_history_fetched BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS history_trade_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS history_volume_usd DECIMAL(20,8) DEFAULT 0;

-- Индекс для эффективного tiered polling
CREATE INDEX IF NOT EXISTS idx_whales_tier_fetch 
    ON whales(tier, last_targeted_fetch_at);

-- Проверка:
-- SELECT column_name, data_type, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'whales' 
--   AND column_name IN (
--     'tier', 'last_targeted_fetch_at', 'initial_history_fetched',
--     'history_trade_count', 'history_volume_usd'
--   );
