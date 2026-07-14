-- ACT-002: account_positions_snapshot table
-- Daily P&L snapshot for portfolio positions

CREATE TABLE IF NOT EXISTS account_positions_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    snap_date       DATE        NOT NULL,
    account         TEXT        NOT NULL,
    condition_id    TEXT        NOT NULL,
    asset           TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    size            NUMERIC     NOT NULL,
    avg_price       NUMERIC     NULL,
    initial_value   NUMERIC     NULL,
    current_value   NUMERIC     NULL,
    cash_pnl        NUMERIC     NOT NULL,
    realized_pnl    NUMERIC     NOT NULL,
    cur_price       NUMERIC     NULL,
    redeemable      BOOLEAN     NOT NULL,
    end_date        DATE        NULL,
    raw_json        JSONB       NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (snap_date, account, condition_id, asset)
);

CREATE INDEX idx_positions_snapshot_account_date ON account_positions_snapshot (account, snap_date);
CREATE INDEX idx_positions_snapshot_condition_id ON account_positions_snapshot (condition_id);
