SELECT *FROM whales WHERE id = 77194

WITH w AS (
    SELECT * FROM whales WHERE wallet_address = '0x31c1a77f809dd278c7c66a4941cad97072b87047'
),
wt_params AS (
    SELECT
        (SELECT estimated_capital FROM w) * 0.01 AS skip_threshold,
        to_timestamp((SELECT value::numeric FROM strategy_config WHERE key = 'bankroll_reset_at')) AS reset_ts
),
wt_agg AS (
    SELECT
        COUNT(*) FILTER (WHERE traded_at >= now() - interval '3 days') AS c_3d,
        COUNT(*) FILTER (WHERE traded_at >= now() - interval '7 days') AS c_7d,
        COUNT(*) FILTER (WHERE traded_at < (SELECT reset_ts FROM wt_params)) AS c_pre,
        COUNT(*) FILTER (WHERE traded_at >= (SELECT reset_ts FROM wt_params)) AS c_post,
        COUNT(*) FILTER (WHERE size_usd >= (SELECT skip_threshold FROM wt_params)) AS c_above,
        COUNT(*) FILTER (WHERE size_usd < (SELECT skip_threshold FROM wt_params)) AS c_below,
        COUNT(*) AS c_total
    FROM whale_trades
    WHERE wallet_address = (SELECT wallet_address FROM w)),
rt_agg AS (
    SELECT
        COUNT(*) AS c_total,
        COUNT(*) FILTER (WHERE status = 'CLOSED') AS c_closed,
        COUNT(*) FILTER (WHERE status = 'OPEN') AS c_open,
        COUNT(*) FILTER (WHERE close_type = 'SETTLEMENT_WIN') AS c_win_ct,
        COUNT(*) FILTER (WHERE close_type = 'SETTLEMENT_LOSS') AS c_loss_ct,
        COUNT(*) FILTER (WHERE pnl_status = 'CONFIRMED' AND net_pnl_usd > 0) AS c_win_pnl,
        COUNT(*) FILTER (WHERE pnl_status = 'CONFIRMED' AND net_pnl_usd <= 0) AS c_loss_pnl,
        COUNT(*) FILTER (WHERE pnl_status = 'CONFIRMED') AS c_confirmed,
        SUM(net_pnl_usd) FILTER (WHERE pnl_status = 'CONFIRMED') AS sum_net_pnl,
        AVG(net_pnl_usd) FILTER (WHERE pnl_status = 'CONFIRMED') AS avg_net_pnl,
        MIN(net_pnl_usd) FILTER (WHERE pnl_status = 'CONFIRMED') AS min_net_pnl,
        MAX(net_pnl_usd) FILTER (WHERE pnl_status = 'CONFIRMED') AS max_net_pnl,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY net_pnl_usd) FILTER (WHERE pnl_status = 'CONFIRMED') AS med_net_pnl,
        SUM(gross_pnl_usd) FILTER (WHERE pnl_status = 'CONFIRMED') AS sum_gross_pnl,
        SUM(fees_usd) FILTER (WHERE pnl_status = 'CONFIRMED') AS sum_fees,
        MIN(opened_at) AS min_opened, MAX(opened_at) AS max_opened,
        MIN(closed_at) AS min_closed, MAX(closed_at) AS max_closed,
        MIN(open_size_usd) AS size_min,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY open_size_usd) AS size_p25,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY open_size_usd) AS size_p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY open_size_usd) AS size_p75,
        percentile_cont(0.90) WITHIN GROUP (ORDER BY open_size_usd) AS size_p90,
        percentile_cont(0.99) WITHIN GROUP (ORDER BY open_size_usd) AS size_p99,
        MAX(open_size_usd) AS size_max,
        AVG(open_size_usd) AS size_avg,
        SUM(open_size_usd) AS size_sum,
        AVG(open_price) AS avg_open_price
    FROM whale_trade_roundtrips
    WHERE wallet_address = (SELECT wallet_address FROM w)
),
rt_agg_post AS (
    SELECT
        COUNT(*) FILTER (WHERE opened_at >= (SELECT reset_ts FROM wt_params)) AS c_opened_post,
        COUNT(*) FILTER (WHERE opened_at <  (SELECT reset_ts FROM wt_params)) AS c_opened_pre,
        COUNT(*) FILTER (WHERE closed_at >= (SELECT reset_ts FROM wt_params)) AS c_closed_post,
        COUNT(*) FILTER (WHERE opened_at >= (SELECT reset_ts FROM wt_params) AND close_type = 'SETTLEMENT_WIN') AS c_win_ct_post,
        COUNT(*) FILTER (WHERE opened_at >= (SELECT reset_ts FROM wt_params) AND close_type = 'SETTLEMENT_LOSS') AS c_loss_ct_post,
        COUNT(*) FILTER (WHERE opened_at >= (SELECT reset_ts FROM wt_params) AND pnl_status = 'CONFIRMED' AND net_pnl_usd > 0) AS c_win_pnl_post,
        COUNT(*) FILTER (WHERE opened_at >= (SELECT reset_ts FROM wt_params) AND pnl_status = 'CONFIRMED' AND net_pnl_usd <= 0) AS c_loss_pnl_post,
        SUM(net_pnl_usd) FILTER (WHERE opened_at >= (SELECT reset_ts FROM wt_params) AND pnl_status = 'CONFIRMED') AS sum_net_pnl_post,
        AVG(net_pnl_usd) FILTER (WHERE opened_at >= (SELECT reset_ts FROM wt_params) AND pnl_status = 'CONFIRMED') AS avg_net_pnl_post
    FROM whale_trade_roundtrips
    WHERE wallet_address = (SELECT wallet_address FROM w)
),
pt_agg AS (
    SELECT
        COUNT(*) AS c_total,
        COUNT(DISTINCT market_id) AS c_markets,
        COUNT(DISTINCT tx_hash) AS c_tx,
        COUNT(*) FILTER (WHERE kelly_size < 1) AS c_kelly_below_1,
        COUNT(*) FILTER (WHERE kelly_size = 0) AS c_kelly_zero,
        COUNT(*) FILTER (WHERE price < 0 OR price > 1) AS c_price_oor,
        MIN(created_at) AS min_created, MAX(created_at) AS max_created,
        MIN(kelly_size) AS ks_min,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY kelly_size) AS ks_p25,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY kelly_size) AS ks_p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY kelly_size) AS ks_p75,
        percentile_cont(0.90) WITHIN GROUP (ORDER BY kelly_size) AS ks_p90,
        percentile_cont(0.99) WITHIN GROUP (ORDER BY kelly_size) AS ks_p99,
        MAX(kelly_size) AS ks_max, AVG(kelly_size) AS ks_avg, SUM(kelly_size) AS ks_sum,
        MIN(size_usd) AS su_min,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY size_usd) AS su_p25,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY size_usd) AS su_p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY size_usd) AS su_p75,
        percentile_cont(0.90) WITHIN GROUP (ORDER BY size_usd) AS su_p90,
        percentile_cont(0.99) WITHIN GROUP (ORDER BY size_usd) AS su_p99,
        MAX(size_usd) AS su_max, AVG(size_usd) AS su_avg,
        AVG(price) AS p_avg,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY price) AS p_med
    FROM paper_trades
    WHERE whale_address = (SELECT wallet_address FROM w)
),
pt_agg_ctx AS (
    SELECT
        COUNT(*) FILTER (WHERE created_at >= (SELECT reset_ts FROM wt_params)) AS c_post,
        COUNT(*) FILTER (WHERE created_at <  (SELECT reset_ts FROM wt_params)) AS c_pre,
        COUNT(*) FILTER (WHERE size_usd < (SELECT skip_threshold FROM wt_params)) AS c_below_skip,
        COUNT(*) FILTER (WHERE size_usd >= (SELECT skip_threshold FROM wt_params)) AS c_above_skip
    FROM paper_trades
    WHERE whale_address = (SELECT wallet_address FROM w)
),
psp_agg AS (
    SELECT
        COUNT(*) AS c_total,
        COUNT(*) FILTER (WHERE our_pnl_usd IS NULL) AS c_our_pnl_null,
        COUNT(*) FILTER (WHERE whale_pnl_usd IS NULL) AS c_whale_pnl_null,
        -- our WR via result
        COUNT(*) FILTER (WHERE result = 'WIN') AS c_result_win,
        COUNT(*) FILTER (WHERE result = 'LOSS') AS c_result_loss,
        -- our WR via close_type (whale's settlement)
        COUNT(*) FILTER (WHERE close_type = 'SETTLEMENT_WIN') AS c_ct_win,
        COUNT(*) FILTER (WHERE close_type = 'SETTLEMENT_LOSS') AS c_ct_loss,
        -- our PnL
        SUM(our_pnl_usd) AS our_pnl_sum,
        AVG(our_pnl_usd) AS our_pnl_avg,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY our_pnl_usd) AS our_pnl_med,
        MIN(our_pnl_usd) AS our_pnl_min,
        MAX(our_pnl_usd) AS our_pnl_max,
        SUM(our_pnl_usd) FILTER (WHERE result = 'WIN') AS our_pnl_sum_win,
        SUM(our_pnl_usd) FILTER (WHERE result = 'LOSS') AS our_pnl_sum_loss,
        AVG(our_pnl_usd) FILTER (WHERE result = 'WIN') AS our_pnl_avg_win,
        AVG(our_pnl_usd) FILTER (WHERE result = 'LOSS') AS our_pnl_avg_loss,
        -- whale PnL on matched roundtrips
        -- DISTINCT на уровне roundtrip: whale_pnl_usd дублируется для каждого paper_trade,
        -- относящегося к одному roundtrip (частичные входы). Считаем уникально.
        SUM(DISTINCT whale_pnl_usd) AS whale_pnl_sum_matched_naive,
        COUNT(DISTINCT whale_pnl_usd) AS whale_distinct_pnl_values
    FROM paper_simulation_pnl
    WHERE whale_address = (SELECT wallet_address FROM w)
)
-- ============ СЕКЦИЯ 1: whales ============
SELECT
    100 AS section_ord,
    ord,
    'whales' AS source_table,
    metric,
    value
FROM (
    SELECT  1 AS ord, 'wallet_address'                AS metric, wallet_address::text                             AS value FROM w
    UNION ALL
    SELECT  2,        'copy_status',                             copy_status::text                                         FROM w
    UNION ALL
    SELECT  3,        'tier',                                    tier::text                                                FROM w
    UNION ALL
    SELECT  4,        'capital_estimation_method',               capital_estimation_method::text                           FROM w
    UNION ALL
    SELECT  5,        'estimated_capital',                       estimated_capital::text                                   FROM w
    UNION ALL
    SELECT  6,        'first_seen_at',                           first_seen_at::text                                       FROM w
    UNION ALL
    SELECT  7,        'last_active_at (native)',                 last_active_at::text                                      FROM w
    UNION ALL
    SELECT  8,        'exclusion_reason',                        COALESCE(exclusion_reason::text, '(null)')                FROM w
    UNION ALL
    SELECT  9,        'reviewed_at',                             COALESCE(reviewed_at::text, '(null)')                     FROM w
    UNION ALL
    SELECT 10,        'total_roundtrips (native)',               total_roundtrips::text                                    FROM w
    UNION ALL
    SELECT 11,        'win_count (native)',                      win_count::text                                           FROM w
    UNION ALL
    SELECT 12,        'loss_count (native)',                     loss_count::text                                          FROM w
    UNION ALL
    SELECT 13,        'win_rate_confirmed (native)',             win_rate_confirmed::text                                  FROM w
    UNION ALL
    SELECT 14,        'total_pnl_usd (native)',                  total_pnl_usd::text                                       FROM w
    UNION ALL
    SELECT 15,        'avg_pnl_usd (native)',                    avg_pnl_usd::text                                         FROM w
    UNION ALL
    SELECT 16,        'trades_last_3_days (native)',             trades_last_3_days::text                                  FROM w
    UNION ALL
    SELECT 17,        'trades_last_7_days (native)',             trades_last_7_days::text                                  FROM w
) x1
UNION ALL
-- ============ СЕКЦИЯ 2: whale_trades (L1) ============
SELECT
    200 AS section_ord,
    ord,
    'whale_trades' AS source_table,
    metric,
    value
FROM (
    SELECT  1 AS ord, 'total_count' AS metric, COUNT(*)::text AS value
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT  2, 'distinct_markets',          COUNT(DISTINCT market_id)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT  3, 'distinct_tx_hashes',        COUNT(DISTINCT tx_hash)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT  4, 'duplicate_tx_hash_count',   (COUNT(*) - COUNT(DISTINCT tx_hash))::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT  5, 'distinct_sources',          COUNT(DISTINCT source)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT  6, 'distinct_market_categories', COUNT(DISTINCT market_category)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 10, 'first_trade_at',            MIN(traded_at)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 11, 'last_trade_at',             MAX(traded_at)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 20, 'size_min',                  MIN(size_usd)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 21, 'size_p10',                  percentile_cont(0.10) WITHIN GROUP (ORDER BY size_usd)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 22, 'size_p25',                  percentile_cont(0.25) WITHIN GROUP (ORDER BY size_usd)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 23, 'size_p50_median',           percentile_cont(0.50) WITHIN GROUP (ORDER BY size_usd)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 24, 'size_p75',                  percentile_cont(0.75) WITHIN GROUP (ORDER BY size_usd)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 25, 'size_p90',                  percentile_cont(0.90) WITHIN GROUP (ORDER BY size_usd)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 26, 'size_p99',                  percentile_cont(0.99) WITHIN GROUP (ORDER BY size_usd)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 27, 'size_max',                  MAX(size_usd)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 28, 'size_avg',                  AVG(size_usd)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 29, 'size_sum_total_volume',     SUM(size_usd)::text
    FROM whale_trades WHERE wallet_address = (SELECT wallet_address FROM w)
    UNION ALL
    SELECT 40, 'side_' || COALESCE(side, 'null') || '_count', COUNT(*)::text
    FROM whale_trades
    WHERE wallet_address = (SELECT wallet_address FROM w)
    GROUP BY side
    UNION ALL
    SELECT 50, 'source_' || COALESCE(source, 'null') || '_count', COUNT(*)::text
    FROM whale_trades
    WHERE wallet_address = (SELECT wallet_address FROM w)
    GROUP BY source
    UNION ALL
    SELECT 60, 'market_category_' || COALESCE(market_category, 'null') || '_count', COUNT(*)::text
    FROM whale_trades
    WHERE wallet_address = (SELECT wallet_address FROM w)
    GROUP BY market_category
) x2
UNION ALL SELECT 250 AS section_ord, ord, 'whale_trades_context' AS source_table, metric, value
FROM (
    SELECT 1 AS ord, 'param_skip_threshold' AS metric, (SELECT skip_threshold FROM wt_params)::text AS value
    UNION ALL SELECT 2, 'param_reset_ts', (SELECT reset_ts FROM wt_params)::text
    UNION ALL SELECT 3, 'param_now', now()::text
    UNION ALL SELECT 10, 'trades_last_3d', (SELECT c_3d FROM wt_agg)::text
    UNION ALL SELECT 11, 'trades_last_7d', (SELECT c_7d FROM wt_agg)::text
    UNION ALL SELECT 20, 'trades_pre_reset', (SELECT c_pre FROM wt_agg)::text
    UNION ALL SELECT 21, 'trades_post_reset', (SELECT c_post FROM wt_agg)::text
    UNION ALL SELECT 30, 'above_skip_threshold_count', (SELECT c_above FROM wt_agg)::text
    UNION ALL SELECT 31, 'below_skip_threshold_count', (SELECT c_below FROM wt_agg)::text
    UNION ALL SELECT 32, 'skip_rate_pct', ROUND(100.0 * (SELECT c_below FROM wt_agg) / NULLIF((SELECT c_total FROM wt_agg), 0), 2)::text
) x_ctx
UNION ALL SELECT 300 AS section_ord, ord, 'whale_trade_roundtrips' AS source_table, metric, value FROM (
    -- Counts
    SELECT 1 AS ord, 'total_count' AS metric, (SELECT c_total FROM rt_agg)::text AS value
    UNION ALL SELECT 2, 'status_CLOSED_count', (SELECT c_closed FROM rt_agg)::text
    UNION ALL SELECT 3, 'status_OPEN_count', (SELECT c_open FROM rt_agg)::text
    -- WR: version A (by close_type)
    UNION ALL SELECT 10, 'wr_A_win_count (SETTLEMENT_WIN)', (SELECT c_win_ct FROM rt_agg)::text
    UNION ALL SELECT 11, 'wr_A_loss_count (SETTLEMENT_LOSS)', (SELECT c_loss_ct FROM rt_agg)::text
    UNION ALL SELECT 12, 'wr_A_rate', ROUND(100.0 * (SELECT c_win_ct FROM rt_agg) / NULLIF((SELECT c_win_ct + c_loss_ct FROM rt_agg), 0), 4)::text
    -- WR: version B (by net_pnl sign, CONFIRMED only)
    UNION ALL SELECT 15, 'wr_B_win_count (net_pnl>0)', (SELECT c_win_pnl FROM rt_agg)::text
    UNION ALL SELECT 16, 'wr_B_loss_count (net_pnl<=0)', (SELECT c_loss_pnl FROM rt_agg)::text
    UNION ALL SELECT 17, 'wr_B_rate', ROUND(100.0 * (SELECT c_win_pnl FROM rt_agg) / NULLIF((SELECT c_win_pnl + c_loss_pnl FROM rt_agg), 0), 4)::text
    -- pnl_status
    UNION ALL SELECT 20, 'pnl_status_CONFIRMED_count', (SELECT c_confirmed FROM rt_agg)::text
    UNION ALL SELECT 21, 'pnl_status_NOT_CONFIRMED_count', ((SELECT c_total FROM rt_agg) - (SELECT c_confirmed FROM rt_agg))::text
    -- PnL (CONFIRMED only)
    UNION ALL SELECT 30, 'net_pnl_sum (CONFIRMED)', (SELECT sum_net_pnl FROM rt_agg)::text
    UNION ALL SELECT 31, 'net_pnl_avg (CONFIRMED)', (SELECT avg_net_pnl FROM rt_agg)::text
    UNION ALL SELECT 32, 'net_pnl_median (CONFIRMED)', (SELECT med_net_pnl FROM rt_agg)::text
    UNION ALL SELECT 33, 'net_pnl_min (CONFIRMED)', (SELECT min_net_pnl FROM rt_agg)::text
    UNION ALL SELECT 34, 'net_pnl_max (CONFIRMED)', (SELECT max_net_pnl FROM rt_agg)::text
    UNION ALL SELECT 35, 'gross_pnl_sum (CONFIRMED)', (SELECT sum_gross_pnl FROM rt_agg)::text
    UNION ALL SELECT 36, 'fees_sum (CONFIRMED)', (SELECT sum_fees FROM rt_agg)::text
    -- Time range
    UNION ALL SELECT 40, 'first_opened_at', (SELECT min_opened FROM rt_agg)::text
    UNION ALL SELECT 41, 'last_opened_at', (SELECT max_opened FROM rt_agg)::text
    UNION ALL SELECT 42, 'first_closed_at', (SELECT min_closed FROM rt_agg)::text
    UNION ALL SELECT 43, 'last_closed_at', (SELECT max_closed FROM rt_agg)::text
    -- open_size distribution
    UNION ALL SELECT 50, 'open_size_min', (SELECT size_min FROM rt_agg)::text
    UNION ALL SELECT 51, 'open_size_p25', (SELECT size_p25 FROM rt_agg)::text
    UNION ALL SELECT 52, 'open_size_p50_median', (SELECT size_p50 FROM rt_agg)::text
    UNION ALL SELECT 53, 'open_size_p75', (SELECT size_p75 FROM rt_agg)::text
    UNION ALL SELECT 54, 'open_size_p90', (SELECT size_p90 FROM rt_agg)::text
    UNION ALL SELECT 55, 'open_size_p99', (SELECT size_p99 FROM rt_agg)::text
    UNION ALL SELECT 56, 'open_size_max', (SELECT size_max FROM rt_agg)::text
    UNION ALL SELECT 57, 'open_size_avg', (SELECT size_avg FROM rt_agg)::text
    UNION ALL SELECT 58, 'open_size_sum_total_volume', (SELECT size_sum FROM rt_agg)::text
    -- Price
    UNION ALL SELECT 60, 'avg_open_price', (SELECT avg_open_price FROM rt_agg)::text
    -- close_type distribution (per-value)
    UNION ALL SELECT 70, 'close_type_' || COALESCE(close_type, 'null') || '_count', COUNT(*)::text FROM whale_trade_roundtrips WHERE wallet_address = (SELECT wallet_address FROM w) GROUP BY close_type
    -- open_side distribution (per-value)
    UNION ALL SELECT 80, 'open_side_' || COALESCE(open_side, 'null') || '_count', COUNT(*)::text FROM whale_trade_roundtrips WHERE wallet_address = (SELECT wallet_address FROM w) GROUP BY open_side
    -- close_side distribution
    UNION ALL SELECT 81, 'close_side_' || COALESCE(close_side, 'null') || '_count', COUNT(*)::text FROM whale_trade_roundtrips WHERE wallet_address = (SELECT wallet_address FROM w) GROUP BY close_side
    -- market_category distribution
    UNION ALL SELECT 90, 'market_category_' || COALESCE(market_category, 'null') || '_count', COUNT(*)::text FROM whale_trade_roundtrips WHERE wallet_address = (SELECT wallet_address FROM w) GROUP BY market_category
) x3
UNION ALL SELECT 350 AS section_ord, ord, 'whale_trade_roundtrips_context' AS source_table, metric, value FROM (
    SELECT 1 AS ord, 'param_reset_ts' AS metric, (SELECT reset_ts FROM wt_params)::text AS value
    UNION ALL SELECT 10, 'roundtrips_opened_pre_reset', (SELECT c_opened_pre FROM rt_agg_post)::text
    UNION ALL SELECT 11, 'roundtrips_opened_post_reset', (SELECT c_opened_post FROM rt_agg_post)::text
    UNION ALL SELECT 12, 'roundtrips_closed_post_reset', (SELECT c_closed_post FROM rt_agg_post)::text
    UNION ALL SELECT 20, 'post_reset_wr_A_win (SETTLEMENT_WIN)', (SELECT c_win_ct_post FROM rt_agg_post)::text
    UNION ALL SELECT 21, 'post_reset_wr_A_loss (SETTLEMENT_LOSS)', (SELECT c_loss_ct_post FROM rt_agg_post)::text
    UNION ALL SELECT 22, 'post_reset_wr_A_rate', ROUND(100.0 * (SELECT c_win_ct_post FROM rt_agg_post) / NULLIF((SELECT c_win_ct_post + c_loss_ct_post FROM rt_agg_post), 0), 4)::text
    UNION ALL SELECT 25, 'post_reset_wr_B_win (net_pnl>0)', (SELECT c_win_pnl_post FROM rt_agg_post)::text
    UNION ALL SELECT 26, 'post_reset_wr_B_loss (net_pnl<=0)', (SELECT c_loss_pnl_post FROM rt_agg_post)::text
    UNION ALL SELECT 27, 'post_reset_wr_B_rate', ROUND(100.0 * (SELECT c_win_pnl_post FROM rt_agg_post) / NULLIF((SELECT c_win_pnl_post + c_loss_pnl_post FROM rt_agg_post), 0), 4)::text
    UNION ALL SELECT 30, 'post_reset_net_pnl_sum (CONFIRMED)', (SELECT sum_net_pnl_post FROM rt_agg_post)::text
    UNION ALL SELECT 31, 'post_reset_net_pnl_avg (CONFIRMED)', (SELECT avg_net_pnl_post FROM rt_agg_post)::text
) x4
UNION ALL SELECT 400 AS section_ord, ord, 'paper_trades' AS source_table, metric, value FROM (
    SELECT 1 AS ord, 'total_count' AS metric, (SELECT c_total FROM pt_agg)::text AS value
    UNION ALL SELECT 2, 'distinct_markets', (SELECT c_markets FROM pt_agg)::text
    UNION ALL SELECT 3, 'distinct_tx_hashes', (SELECT c_tx FROM pt_agg)::text
    UNION ALL SELECT 4, 'duplicate_tx_hash_count', ((SELECT c_total FROM pt_agg) - (SELECT c_tx FROM pt_agg))::text
    -- Sanity
    UNION ALL SELECT 10, 'sanity_kelly_size_below_1_count', (SELECT c_kelly_below_1 FROM pt_agg)::text
    UNION ALL SELECT 11, 'sanity_kelly_size_zero_count', (SELECT c_kelly_zero FROM pt_agg)::text
    UNION ALL SELECT 12, 'sanity_price_out_of_range_count', (SELECT c_price_oor FROM pt_agg)::text
    -- Time range
    UNION ALL SELECT 20, 'first_created_at', (SELECT min_created FROM pt_agg)::text
    UNION ALL SELECT 21, 'last_created_at', (SELECT max_created FROM pt_agg)::text
    -- kelly_size distribution (наш реальный размер)
    UNION ALL SELECT 30, 'kelly_size_min', (SELECT ks_min FROM pt_agg)::text
    UNION ALL SELECT 31, 'kelly_size_p25', (SELECT ks_p25 FROM pt_agg)::text
    UNION ALL SELECT 32, 'kelly_size_p50_median', (SELECT ks_p50 FROM pt_agg)::text
    UNION ALL SELECT 33, 'kelly_size_p75', (SELECT ks_p75 FROM pt_agg)::text
    UNION ALL SELECT 34, 'kelly_size_p90', (SELECT ks_p90 FROM pt_agg)::text
    UNION ALL SELECT 35, 'kelly_size_p99', (SELECT ks_p99 FROM pt_agg)::text
    UNION ALL SELECT 36, 'kelly_size_max', (SELECT ks_max FROM pt_agg)::text
    UNION ALL SELECT 37, 'kelly_size_avg', (SELECT ks_avg FROM pt_agg)::text
    UNION ALL SELECT 38, 'kelly_size_sum', (SELECT ks_sum FROM pt_agg)::text
    -- size_usd distribution (имитация размера кита)
    UNION ALL SELECT 40, 'size_usd_min', (SELECT su_min FROM pt_agg)::text
    UNION ALL SELECT 41, 'size_usd_p25', (SELECT su_p25 FROM pt_agg)::text
    UNION ALL SELECT 42, 'size_usd_p50_median', (SELECT su_p50 FROM pt_agg)::text
    UNION ALL SELECT 43, 'size_usd_p75', (SELECT su_p75 FROM pt_agg)::text
    UNION ALL SELECT 44, 'size_usd_p90', (SELECT su_p90 FROM pt_agg)::text
    UNION ALL SELECT 45, 'size_usd_p99', (SELECT su_p99 FROM pt_agg)::text
    UNION ALL SELECT 46, 'size_usd_max', (SELECT su_max FROM pt_agg)::text
    UNION ALL SELECT 47, 'size_usd_avg', (SELECT su_avg FROM pt_agg)::text
    -- Price
    UNION ALL SELECT 50, 'price_avg', (SELECT p_avg FROM pt_agg)::text
    UNION ALL SELECT 51, 'price_median', (SELECT p_med FROM pt_agg)::text
    -- side distribution
    UNION ALL SELECT 60, 'side_' || COALESCE(side, 'null') || '_count', COUNT(*)::text FROM paper_trades WHERE whale_address = (SELECT wallet_address FROM w) GROUP BY side
    -- source distribution
    UNION ALL SELECT 70, 'source_' || COALESCE(source, 'null') || '_count', COUNT(*)::text FROM paper_trades WHERE whale_address = (SELECT wallet_address FROM w) GROUP BY source
    -- kelly_fraction distribution (per-value — смотрим, менялась ли)
    UNION ALL SELECT 80, 'kelly_fraction_' || COALESCE(kelly_fraction::text, 'null') || '_count', COUNT(*)::text FROM paper_trades WHERE whale_address = (SELECT wallet_address FROM w) GROUP BY kelly_fraction
) x5
UNION ALL SELECT 450 AS section_ord, ord, 'paper_trades_context' AS source_table, metric, value FROM (
    SELECT 1 AS ord, 'param_reset_ts' AS metric, (SELECT reset_ts FROM wt_params)::text AS value
    UNION ALL SELECT 2, 'param_skip_threshold', (SELECT skip_threshold FROM wt_params)::text
    UNION ALL SELECT 10, 'paper_trades_pre_reset', (SELECT c_pre FROM pt_agg_ctx)::text
    UNION ALL SELECT 11, 'paper_trades_post_reset', (SELECT c_post FROM pt_agg_ctx)::text
    UNION ALL SELECT 20, 'paper_trades_above_skip_threshold', (SELECT c_above_skip FROM pt_agg_ctx)::text
    UNION ALL SELECT 21, 'paper_trades_below_skip_threshold (should be 0)', (SELECT c_below_skip FROM pt_agg_ctx)::text
) x6
UNION ALL SELECT 500 AS section_ord, ord, 'paper_simulation_pnl' AS source_table, metric, value FROM (
    -- Counts
    SELECT 1 AS ord, 'total_count' AS metric, (SELECT c_total FROM psp_agg)::text AS value
    UNION ALL SELECT 2, 'sanity_our_pnl_null_count', (SELECT c_our_pnl_null FROM psp_agg)::text
    UNION ALL SELECT 3, 'sanity_whale_pnl_null_count', (SELECT c_whale_pnl_null FROM psp_agg)::text
    -- WR via result (наш результат)
    UNION ALL SELECT 10, 'our_wr_via_result_win', (SELECT c_result_win FROM psp_agg)::text
    UNION ALL SELECT 11, 'our_wr_via_result_loss', (SELECT c_result_loss FROM psp_agg)::text
    UNION ALL SELECT 12, 'our_wr_via_result_rate', ROUND(100.0 * (SELECT c_result_win FROM psp_agg) / NULLIF((SELECT c_result_win + c_result_loss FROM psp_agg), 0), 4)::text
    -- WR via close_type (результат кита = наш, при идеальной трансляции)
    UNION ALL SELECT 15, 'whale_wr_matched_via_close_type_win', (SELECT c_ct_win FROM psp_agg)::text
    UNION ALL SELECT 16, 'whale_wr_matched_via_close_type_loss', (SELECT c_ct_loss FROM psp_agg)::text
    UNION ALL SELECT 17, 'whale_wr_matched_rate', ROUND(100.0 * (SELECT c_ct_win FROM psp_agg) / NULLIF((SELECT c_ct_win + c_ct_loss FROM psp_agg), 0), 4)::text
    -- our PnL
    UNION ALL SELECT 20, 'our_pnl_sum', (SELECT our_pnl_sum FROM psp_agg)::text
    UNION ALL SELECT 21, 'our_pnl_avg', (SELECT our_pnl_avg FROM psp_agg)::text
    UNION ALL SELECT 22, 'our_pnl_median', (SELECT our_pnl_med FROM psp_agg)::text
    UNION ALL SELECT 23, 'our_pnl_min', (SELECT our_pnl_min FROM psp_agg)::text
    UNION ALL SELECT 24, 'our_pnl_max', (SELECT our_pnl_max FROM psp_agg)::text
    UNION ALL SELECT 25, 'our_pnl_sum_WIN', (SELECT our_pnl_sum_win FROM psp_agg)::text
    UNION ALL SELECT 26, 'our_pnl_sum_LOSS', (SELECT our_pnl_sum_loss FROM psp_agg)::text
    UNION ALL SELECT 27, 'our_pnl_avg_WIN', (SELECT our_pnl_avg_win FROM psp_agg)::text
    UNION ALL SELECT 28, 'our_pnl_avg_LOSS', (SELECT our_pnl_avg_loss FROM psp_agg)::text
    -- whale PnL matched
    UNION ALL SELECT 30, 'whale_pnl_sum_matched (distinct)', (SELECT whale_pnl_sum_matched_naive FROM psp_agg)::text
    UNION ALL SELECT 31, 'whale_distinct_pnl_values', (SELECT whale_distinct_pnl_values FROM psp_agg)::text
    -- Derived
    UNION ALL SELECT 40, 'pnl_transmission_ratio_pct', ROUND(100.0 * (SELECT our_pnl_sum FROM psp_agg) / NULLIF((SELECT whale_pnl_sum_matched_naive FROM psp_agg), 0), 4)::text
    -- per-value distributions
    UNION ALL SELECT 50, 'position_status_' || COALESCE(position_status, 'null') || '_count', COUNT(*)::text FROM paper_simulation_pnl WHERE whale_address = (SELECT wallet_address FROM w) GROUP BY position_status
    UNION ALL SELECT 60, 'close_type_' || COALESCE(close_type, 'null') || '_count', COUNT(*)::text FROM paper_simulation_pnl WHERE whale_address = (SELECT wallet_address FROM w) GROUP BY close_type
    UNION ALL SELECT 70, 'result_' || COALESCE(result, 'null') || '_count', COUNT(*)::text FROM paper_simulation_pnl WHERE whale_address = (SELECT wallet_address FROM w) GROUP BY result
) x7
ORDER BY section_ord, ord, metric;

