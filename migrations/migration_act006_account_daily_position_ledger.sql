-- ACT-006: account_daily_position_ledger — mark-to-market витрина позиций по дням
-- Грейн: (account, condition_id, asset, activity_date), РАЗРЕЖЕННЫЙ — строка
-- существует только если buy_size!=0 OR sell_size!=0 OR reward_usd!=0 в этот день.
-- Полная пересборка при каждом запуске build_account_daily_ledger.py (не upsert):
-- источник (account_activity) append-only и мал по объёму, full rebuild исключает
-- дрейф инкрементального состояния. См. docs/tasks/ACT-006.md за полным дизайном.

BEGIN;

CREATE TABLE IF NOT EXISTS account_daily_position_ledger (
    account          TEXT            NOT NULL,
    condition_id     TEXT            NOT NULL,
    asset            TEXT            NOT NULL,
    activity_date    DATE            NOT NULL,
    title            TEXT,

    buy_size         NUMERIC(20, 8)  NOT NULL DEFAULT 0,
    buy_usdc         NUMERIC(20, 8)  NOT NULL DEFAULT 0,
    sell_size        NUMERIC(20, 8)  NOT NULL DEFAULT 0,
    sell_usdc        NUMERIC(20, 8)  NOT NULL DEFAULT 0,

    avg_cost         NUMERIC(20, 8),
    opening_balance  NUMERIC(20, 8)  NOT NULL,
    closing_balance  NUMERIC(20, 8)  NOT NULL,

    mark_price       NUMERIC(20, 8),
    mark_source      TEXT,

    buy_fee          NUMERIC(20, 8),
    sell_fee         NUMERIC(20, 8),
    fee_source       TEXT,

    reward_usd       NUMERIC(20, 8),
    fees_usd         NUMERIC(20, 8),

    status           TEXT            NOT NULL,

    built_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    PRIMARY KEY (account, condition_id, asset, activity_date)
);

CREATE INDEX IF NOT EXISTS idx_adpl_account_date ON account_daily_position_ledger (account, activity_date);
CREATE INDEX IF NOT EXISTS idx_adpl_condition_id ON account_daily_position_ledger (condition_id);
CREATE INDEX IF NOT EXISTS idx_adpl_status ON account_daily_position_ledger (status);

COMMENT ON TABLE account_daily_position_ledger IS 'ACT-006: mark-to-market дневная витрина позиций (account_activity + farming_daily_snapshot + account_positions_snapshot + market_resolutions). Полная пересборка скриптом scripts/build_account_daily_ledger.py, не upsert.';
COMMENT ON COLUMN account_daily_position_ledger.avg_cost IS 'Running weighted avg cost купленного в рамках текущей "эпохи" позиции (сбрасывается когда баланс уходит в ~0 и открывается заново).';
COMMENT ON COLUMN account_daily_position_ledger.mark_price IS 'Цена оценки остатка. NULL если позиция закрыта ИЛИ источник цены недоступен (НИКОГДА не COALESCE до 0/avg_cost).';
COMMENT ON COLUMN account_daily_position_ledger.mark_source IS 'exchange_snapshot | farm_mid | NULL (clob_history — ACT-007, ещё не реализовано).';
COMMENT ON COLUMN account_daily_position_ledger.buy_fee IS 'Справочная оценка комиссии (TRD-448 formula, универсальная ставка). НЕ вычитать повторно из usdc_size — комиссия иногда уже включена в него.';
COMMENT ON COLUMN account_daily_position_ledger.status IS 'OPEN | CLOSED_TRADED | CLOSED_RESOLVED_WIN | CLOSED_RESOLVED_LOSS | WON_UNCLAIMED.';

COMMIT;
