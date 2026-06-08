-- PIPE-044: DDL tables for leaderboard candidate funnel
-- Creates3 tables: leaderboard_candidates, leaderboard_candidate_trades, leaderboard_candidate_roundtrips

-- Таблица 1: реестр кандидатов
CREATE TABLE leaderboard_candidates (
    id                          SERIAL PRIMARY KEY,
    wallet_address              VARCHAR(66)   NOT NULL UNIQUE,
    username                    VARCHAR(128),
    leaderboard_period          VARCHAR(16),
    leaderboard_rank            INTEGER,
    leaderboard_pnl_usd         NUMERIC(20,2),

    -- Fetch state
    fetched_at                  TIMESTAMP,
    trades_fetched              INTEGER,
    date_first_trade            TIMESTAMP,
    date_last_trade             TIMESTAMP,
    active_days                 INTEGER,

    -- LP/HFT фильтры
    is_lp                       BOOLEAN,
    is_hft_burst                BOOLEAN,
    peak_trades_per_15min       INTEGER,
    top_market_trade_count      INTEGER,
    top_market_vol_pct          NUMERIC(5,2),
    filter_reason               VARCHAR(128),

    -- PnL scoring
    roundtrips_total            INTEGER,
    roundtrips_closed           INTEGER,
    roundtrips_open             INTEGER,
    wins                        INTEGER,
    losses                      INTEGER,
    win_rate                    NUMERIC(5,4),
    calc_pnl_usd                NUMERIC(20,2),
    pnl_calc_method             VARCHAR(32),

    -- Решение оператора
    is_copyable                 BOOLEAN,
    approved_for_tracking       BOOLEAN DEFAULT FALSE,
    reviewed_at                 TIMESTAMP,
    notes                       TEXT,

    created_at                  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lc_wallet    ON leaderboard_candidates(wallet_address);
CREATE INDEX idx_lc_copyable  ON leaderboard_candidates(is_copyable)
    WHERE is_copyable = TRUE;
CREATE INDEX idx_lc_approved  ON leaderboard_candidates(approved_for_tracking)
    WHERE approved_for_tracking = TRUE;

-- Таблица 2: сырые сделки кандидатов
CREATE TABLE leaderboard_candidate_trades (
    id              SERIAL PRIMARY KEY,
    wallet_address  VARCHAR(66)   NOT NULL,
    tx_hash         VARCHAR(128),
    market_id       VARCHAR(128)  NOT NULL,
    outcome         VARCHAR(128),
    side            VARCHAR(4)    NOT NULL,
    size_usd        NUMERIC(20,2) NOT NULL,
    price           NUMERIC(10,6) NOT NULL,
    traded_at       TIMESTAMP     NOT NULL,
    created_at      TIMESTAMP     NOT NULL DEFAULT NOW(),
    UNIQUE(tx_hash)
);

CREATE INDEX idx_lct_wallet          ON leaderboard_candidate_trades(wallet_address);
CREATE INDEX idx_lct_wallet_market   ON leaderboard_candidate_trades(wallet_address, market_id);
CREATE INDEX idx_lct_traded_at       ON leaderboard_candidate_trades(traded_at);

-- Таблица 3: roundtrips кандидатов
CREATE TABLE leaderboard_candidate_roundtrips (
    id              SERIAL PRIMARY KEY,
    wallet_address  VARCHAR(66)   NOT NULL,
    market_id       VARCHAR(128)  NOT NULL,
    outcome         VARCHAR(128),

    open_side       VARCHAR(4),
    open_size_usd   NUMERIC(20,2),
    open_price      NUMERIC(10,6),
    opened_at       TIMESTAMP,

    close_side      VARCHAR(4),
    close_size_usd  NUMERIC(20,2),
    close_price     NUMERIC(10,6),
    closed_at       TIMESTAMP,
    close_type      VARCHAR(32),

    gross_pnl_usd   NUMERIC(20,2),
    net_pnl_usd     NUMERIC(20,2),
    pnl_status      VARCHAR(16),

    status          VARCHAR(16)   NOT NULL DEFAULT 'OPEN',

    created_at      TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP     NOT NULL DEFAULT NOW(),

    UNIQUE(wallet_address, market_id, outcome)
);

CREATE INDEX idx_lcr_wallet        ON leaderboard_candidate_roundtrips(wallet_address);
CREATE INDEX idx_lcr_status        ON leaderboard_candidate_roundtrips(status);
CREATE INDEX idx_lcr_wallet_status ON leaderboard_candidate_roundtrips(wallet_address, status);
