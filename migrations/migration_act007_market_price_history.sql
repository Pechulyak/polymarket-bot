-- ACT-007: market_price_history — дневная история цен токенов (CLOB /prices-history)
-- Третий (последний по приоритету) источник mark_price в account_daily_position_ledger,
-- см. docs/tasks/ACT-006.md §5.5: account_positions_snapshot.cur_price > farming_daily_snapshot.mid
-- > market_price_history (этот бэкфилл — покрывает даты/рынки, для которых нет ни того, ни другого).

BEGIN;

CREATE TABLE IF NOT EXISTS market_price_history (
    asset       TEXT        NOT NULL,
    price_date  DATE        NOT NULL,
    price       NUMERIC(10, 6) NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (asset, price_date)
);

COMMENT ON TABLE market_price_history IS 'ACT-007: дневная цена токена из CLOB /prices-history (interval=max&fidelity=1440). При нескольких точках в один день берётся последняя по времени за сутки.';
COMMENT ON COLUMN market_price_history.asset IS 'token_id — то же, что account_activity.asset.';
COMMENT ON COLUMN market_price_history.price_date IS 'Календарная дата (UTC) точки истории.';
COMMENT ON COLUMN market_price_history.price IS 'Цена на конец точки (0..1, вероятностный токен).';

COMMIT;
