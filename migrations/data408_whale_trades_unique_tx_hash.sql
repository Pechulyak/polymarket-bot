-- DATA-408: partial UNIQUE INDEX на whale_trades.tx_hash
-- Выполнять ВНЕ транзакции (CONCURRENTLY несовместим с BEGIN).
-- Команда запуска: docker exec -i polymarket_postgres psql -U postgres -d polymarket < migrations/data408_whale_trades_unique_tx_hash.sql

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
    idx_whale_trades_tx_hash_unique
ON whale_trades (tx_hash)
WHERE tx_hash IS NOT NULL AND tx_hash <> '';