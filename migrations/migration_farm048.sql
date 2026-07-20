-- FARM-048: portfolio-level free cash (pUSD ERC-20 balanceOf FUNDER) daily snapshot.
--
-- Separate table (NOT a per-row column on farming_daily_snapshot) because:
--   1. free_cash is a portfolio/funder-level scalar, not per-token — duplicating
--      it across every token row is semantically wrong and risks intra-date drift.
--   2. On days with zero active positions farming_daily_snapshot has no rows, so a
--      per-row column could not record cash at all; this one-row-per-date table
--      always records it (needed for the future farming auto-audit).
--
-- NULL semantics: free_cash_pusd IS NULL  => on-chain RPC read failed (unknown).
--                 free_cash_pusd = 0      => wallet truly empty.
-- The two MUST stay distinct — sizing decisions depend on it. Never coerce NULL->0.

CREATE TABLE IF NOT EXISTS farming_daily_cash (
    snap_date       DATE            NOT NULL,
    free_cash_pusd  NUMERIC(20,8),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    PRIMARY KEY (snap_date)
);

GRANT INSERT, SELECT, UPDATE ON farming_daily_cash TO order_executor;
GRANT SELECT ON farming_daily_cash TO grafana_reader;

COMMENT ON TABLE farming_daily_cash IS 'Daily portfolio-level free cash (pUSD ERC-20 balanceOf FUNDER). One row per snap_date. FARM-048.';
COMMENT ON COLUMN farming_daily_cash.snap_date IS 'Дата снапшота (PK).';
COMMENT ON COLUMN farming_daily_cash.free_cash_pusd IS 'Free cash = pUSD balanceOf(FUNDER)/1e6. NULL=RPC-отказ (неизвестно), 0=пустой кошелёк. NULL != 0, различие критично для sizing.';