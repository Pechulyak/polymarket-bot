-- ACT-002: account_activity table
-- Append-only event log for portfolio activity (TRADE/REDEEM/REWARD/SPLIT/MERGE/CONVERSION)

CREATE TABLE IF NOT EXISTS account_activity (
    id              BIGSERIAL PRIMARY KEY,
    account         TEXT        NOT NULL,  -- 'PechaArt' | 'Justfuuun'
    proxy_wallet    TEXT        NOT NULL,
    event_type      TEXT        NOT NULL,  -- TRADE | REDEEM | REWARD | SPLIT | MERGE | CONVERSION
    condition_id    TEXT        NOT NULL,
    asset           TEXT        NULL,       -- empty string stored as NULL for REDEEM/REWARD
    side            TEXT        NULL,       -- BUY | SELL | NULL for REDEEM/REWARD
    size            NUMERIC     NOT NULL,
    usdc_size       NUMERIC     NOT NULL,
    price           NUMERIC     NULL,
    outcome_index   INTEGER     NULL,       -- 999 for REDEEM/REWARD
    title           TEXT        NOT NULL,
    slug            TEXT        NOT NULL,
    event_ts        TIMESTAMPTZ NOT NULL,   -- from unix timestamp
    tx_hash         TEXT        NOT NULL,
    raw_json        JSONB       NOT NULL,   -- entire record as-is
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_activity_account_event_ts ON account_activity (account, event_ts);
CREATE INDEX idx_activity_condition_id      ON account_activity (condition_id);
CREATE INDEX idx_activity_event_type        ON account_activity (event_type);
CREATE INDEX idx_activity_tx_hash           ON account_activity (tx_hash);

-- Unique partial: non-REDEEM/REWARD (have side)
CREATE UNIQUE INDEX idx_activity_unique_trade
    ON account_activity (tx_hash, condition_id, event_type, side, size, price)
    WHERE side IS NOT NULL;

-- Unique partial: REDEEM/REWARD (no side)
CREATE UNIQUE INDEX idx_activity_unique_redeem
    ON account_activity (tx_hash, condition_id, event_type, size)
    WHERE side IS NULL;
