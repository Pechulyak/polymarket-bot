-- INFRA-043: live_orders schema + order_executor grant
-- Purpose: queue of intent orders for live execution (pull-model)
-- Executor: order_executor (role already exists with pg_hba line 34 for 62.60.233.100)
-- Rollback: DROP TABLE IF EXISTS live_orders; (role order_executor not touched)

BEGIN;

CREATE TABLE live_orders (
    id              BIGSERIAL PRIMARY KEY,
    token_id        TEXT          NOT NULL,   -- CLOB token for specific outcome (resolve via Gamma, NOT condition_id)
    condition_id    TEXT          NOT NULL,   -- = market_id of the market
    market_title    TEXT,                     -- human-readable, for operator verification
    outcome         TEXT,                     -- Yes/No (for cross-check with token_id)
    side            TEXT          NOT NULL CHECK (side IN ('BUY','SELL')),
    size_usd        NUMERIC(20,8) NOT NULL CHECK (size_usd > 0),
    limit_price     NUMERIC(20,8) CHECK (limit_price > 0 AND limit_price < 1),
    status          TEXT          NOT NULL DEFAULT 'intent'
                    CHECK (status IN ('intent','claimed','submitted','filled','partial','rejected','failed')),
    idempotency_key TEXT          NOT NULL UNIQUE,
    clob_order_id   TEXT,
    filled_size     NUMERIC(20,8),
    error           TEXT,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ,
    claimed_at      TIMESTAMPTZ
);

-- Partial index: fast lookup of intent orders without full table scan
-- Used by pull-poll executor to find pending work
CREATE INDEX idx_live_orders_intent ON live_orders (status) WHERE status = 'intent';

-- Permissions: executor reads intent and writes result back
-- INSERT/DELETE not granted: only the operator (via API/gov channel) creates rows
-- executor cannot spawn orders on its own
GRANT SELECT, UPDATE ON live_orders TO order_executor;

COMMIT;