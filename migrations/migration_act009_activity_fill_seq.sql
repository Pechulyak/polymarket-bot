-- ACT-009: фикс дедуп-индекса account_activity, теряющего реальные сделки
-- Причина: unique index (tx_hash, condition_id, event_type, side, size, price)
-- не различает ДВА РАЗНЫХ ордера (разный orderHash on-chain) с одинаковым
-- размером/ценой в одной транзакции — второй молча не пишется (ON CONFLICT
-- DO NOTHING в scripts/fetch_account_activity.py). Data-API сам не отдаёт
-- order-level ID (raw_json идентичен для обоих филлов), поэтому естественного
-- дискриминатора нет — вводим искусственный (fill_seq).
-- Подтверждено on-chain (Polygon RPC) на 3 случаях, см. docs/tasks/ACT-006.md §8.

BEGIN;

ALTER TABLE account_activity ADD COLUMN IF NOT EXISTS fill_seq INTEGER NOT NULL DEFAULT 0;
COMMENT ON COLUMN account_activity.fill_seq IS 'ACT-009: дискриминатор для двух разных on-chain ордеров с одинаковым (tx_hash,size,price) в одной транзакции. 0 = первая/единственная запись, ингестируемая обычным потоком; 1+ = дозаписанные бэкфиллом пропущенные филлы.';

DROP INDEX IF EXISTS idx_activity_unique_trade;
CREATE UNIQUE INDEX idx_activity_unique_trade
    ON account_activity (tx_hash, condition_id, event_type, side, size, price, fill_seq)
    WHERE side IS NOT NULL;

DROP INDEX IF EXISTS idx_activity_unique_redeem;
CREATE UNIQUE INDEX idx_activity_unique_redeem
    ON account_activity (tx_hash, condition_id, event_type, size, fill_seq)
    WHERE side IS NULL;

COMMIT;
