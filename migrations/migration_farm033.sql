-- FARM-025: Таблица daily snapshots для фарм-мониторинга
-- Ежедневные слепки состояния позиций: inv, mid, capital, fees, reward
-- PK: (snap_date, token) — один снапшот на токен на дату

BEGIN;

CREATE TABLE IF NOT EXISTS farming_daily_snapshot (
    snap_date       DATE            NOT NULL,
    token           TEXT            NOT NULL,

    -- Market identifiers
    gamma_id        BIGINT,
    condition_id    TEXT,

    -- Position state
    legs_state      TEXT,
    hours_both      NUMERIC(20, 8),

    -- Detailed state log
    legs_state_log  TEXT,

    -- Pricing & inventory
    inv             NUMERIC(20, 8),
    mid             NUMERIC(20, 8),

    -- Financials
    capital_usd     NUMERIC(20, 8),
    fees_usd        NUMERIC(20, 8),
    reward_usd      NUMERIC(20, 8),

    -- Audit
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    PRIMARY KEY (snap_date, token)
);

-- Index for date-based queries
CREATE INDEX IF NOT EXISTS idx_fds_snap_date ON farming_daily_snapshot(snap_date);
CREATE INDEX IF NOT EXISTS idx_fds_condition_id ON farming_daily_snapshot(condition_id);

-- Grant for order_executor role
GRANT INSERT, SELECT, UPDATE ON farming_daily_snapshot TO order_executor;

-- Row-level security (if enabled)
-- ALTER TABLE farming_daily_snapshot ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE farming_daily_snapshot IS 'Daily snapshots of farming positions: inv, mid, capital, fees, reward per token.';
COMMENT ON COLUMN farming_daily_snapshot.snap_date IS 'Дата снапшота (PK part 1).';
COMMENT ON COLUMN farming_daily_snapshot.token IS 'Токен маркета (PK part 2).';
COMMENT ON COLUMN farming_daily_snapshot.gamma_id IS 'Gamma market ID.';
COMMENT ON COLUMN farming_daily_snapshot.condition_id IS 'Polymarket condition ID.';
COMMENT ON COLUMN farming_daily_snapshot.legs_state IS 'Состояние ног позиции: OPEN/CLOSED/HEDGE.';
COMMENT ON COLUMN farming_daily_snapshot.hours_both IS 'Часы когда обе ноги были открыты.';
COMMENT ON COLUMN farming_daily_snapshot.legs_state_log IS 'JSON log всех изменений legs_state за день.';
COMMENT ON COLUMN farming_daily_snapshot.inv IS 'Inventory (суммарная позиция в шерах).';
COMMENT ON COLUMN farming_daily_snapshot.mid IS 'Mid price на момент снапшота.';
COMMENT ON COLUMN farming_daily_snapshot.capital_usd IS 'Задействованный капитал в USD.';
COMMENT ON COLUMN farming_daily_snapshot.fees_usd IS 'Trading fees за период в USD.';
COMMENT ON COLUMN farming_daily_snapshot.reward_usd IS 'Farming reward за период в USD.';

COMMIT;
