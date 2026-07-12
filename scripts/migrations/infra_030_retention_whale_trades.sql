-- INFRA-030 / A3 — retention_whale_trades
-- Variant A (asymmetric): BUY older than p_days deletable even at OPEN;
-- SELL protected while an OPEN roundtrip exists on same wallet+market+outcome.
-- PROCEDURE (not function) — needs COMMIT inside loop.
-- Live NOT EXISTS each batch (no snapshot) — safe against concurrent 3B/3C.
-- Indexes A1b cover all three NOT EXISTS (Index Only Scan).

CREATE OR REPLACE PROCEDURE public.retention_whale_trades(
    IN p_days  integer DEFAULT 30,
    IN p_batch integer DEFAULT 10000
)
LANGUAGE plpgsql
AS $procedure$
DECLARE
    v_batch_num      INT := 0;
    v_deleted_total  BIGINT := 0;
    v_rowcount       INT := 1;
BEGIN
    IF p_days < 1 OR p_batch < 1 THEN
        RAISE NOTICE 'Invalid parameters: p_days=%, p_batch=%. Must be >= 1.', p_days, p_batch;
        RETURN;
    END IF;

    RAISE NOTICE 'Starting retention_whale_trades: p_days=%, p_batch=%', p_days, p_batch;

    WHILE v_rowcount > 0 LOOP
        v_batch_num := v_batch_num + 1;

        DELETE FROM whale_trades wt
        WHERE wt.id IN (
            SELECT wt2.id
            FROM whale_trades wt2
            WHERE wt2.traded_at < NOW() - make_interval(days => p_days)
              -- anchor BUY protected (FK open_trade_id)
              AND NOT EXISTS (
                  SELECT 1 FROM whale_trade_roundtrips rt
                  WHERE rt.open_trade_id = wt2.id
              )
              -- close-referenced protected (FK close_trade_id)
              AND NOT EXISTS (
                  SELECT 1 FROM whale_trade_roundtrips rt
                  WHERE rt.close_trade_id = wt2.id
              )
              -- Variant A asymmetry:
              -- BUY always deletable (no reader of old unreferenced BUY);
              -- SELL kept while OPEN exists (3C needs it to close the position).
              AND (
                  wt2.side = 'buy'
                  OR NOT EXISTS (
                      SELECT 1 FROM whale_trade_roundtrips rt
                      WHERE rt.wallet_address = wt2.wallet_address
                        AND rt.market_id      = wt2.market_id
                        AND (rt.outcome = wt2.outcome
                             OR (rt.outcome IS NULL AND wt2.outcome IS NULL))
                        AND rt.status = 'OPEN'
                  )
              )
            LIMIT p_batch
        );

        GET DIAGNOSTICS v_rowcount = ROW_COUNT;
        v_deleted_total := v_deleted_total + v_rowcount;

        RAISE NOTICE 'Batch %: deleted %, total %', v_batch_num, v_rowcount, v_deleted_total;

        COMMIT;
    END LOOP;

    RAISE NOTICE 'Retention complete. Batches: %, Total deleted: %', v_batch_num, v_deleted_total;
END;
$procedure$;