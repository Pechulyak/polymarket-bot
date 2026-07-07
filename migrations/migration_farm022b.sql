-- FARM-022 К2: Таблица активных фарм-рынков
-- Источник seed: MARKETS из executor/farming_daemon.py
-- Pool/max_spread/baseline из CLOB /markets/{condition_id}
-- feesEnabled/negRisk из Gamma /markets/{gamma_id}

BEGIN;

CREATE TABLE IF NOT EXISTS farming_active_markets (
    id              SERIAL PRIMARY KEY,
    token_id        VARCHAR(255) NOT NULL,
    condition_id    VARCHAR(255) NOT NULL,
    gamma_id        INTEGER,
    name            VARCHAR(255) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'paused', 'removed')),

    -- Baseline values (на момент добавления в мониторинг)
    pool_baseline       NUMERIC(20, 8) NOT NULL,
    max_spread_baseline NUMERIC(10, 4) NOT NULL,
    fees_enabled_baseline BOOLEAN NOT NULL DEFAULT FALSE,
    neg_risk_baseline    BOOLEAN NOT NULL DEFAULT FALSE,
    end_date_baseline    TIMESTAMP WITH TIME ZONE,

    -- Timestamps
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Unique constraints
    UNIQUE (token_id),
    UNIQUE (condition_id),
    UNIQUE (gamma_id)
);

-- Index for status filtering
CREATE INDEX IF NOT EXISTS idx_fam_status ON farming_active_markets(status);

-- Seed: 2 рынка из MARKETS (executor/farming_daemon.py, 2026-07-07)
INSERT INTO farming_active_markets
    (token_id, condition_id, gamma_id, name, status,
     pool_baseline, max_spread_baseline, fees_enabled_baseline, neg_risk_baseline, end_date_baseline)
VALUES
    -- Market 1: New People 2nd seats
    (
        '16812776081734673413618925676070790303458587814000834940389189903201996256784',
        '0x65d9ff5dd4b1cd8974f14335c2bd1fc5f133c1228aeb6e5d83c80f7432a120f0',
        2046126,
        'New People 2nd seats',
        'active',
        18.0,
        4.5,
        TRUE,
        TRUE,
        '2026-09-20T00:00:00Z'
    ),
    -- Market 2: AI 1530 Arena by Sep30
    (
        '54893086053865884845869248787484771799795088600261085229269223835220342300136',
        '0x0ab703c5bc04b87984cc9355d28a2de699d396b71a86a29991fa42bf9c96e798',
        1831353,
        'AI 1530 Arena by Sep30',
        'active',
        20.0,
        4.5,
        TRUE,
        FALSE,
        '2026-09-30T00:00:00Z'
    )
ON CONFLICT (token_id) DO NOTHING;

COMMIT;
