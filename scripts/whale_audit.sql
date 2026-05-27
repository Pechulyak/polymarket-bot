

-- whale_audit.sql v1.1
WITH params AS (
  SELECT
    to_timestamp((SELECT value::numeric FROM strategy_config WHERE key = 'bankroll_reset_at')) AS reset_ts,
    15 AS min_rt_closed
),
rt AS (
  SELECT
    whale_id,
    COUNT(*) FILTER (WHERE status='CLOSED' AND pnl_status='CONFIRMED') AS rt_closed,
    COUNT(*) FILTER (WHERE status='OPEN') AS rt_open,
    -- WR + PF (ALL, by close_type)
    COUNT(*) FILTER (WHERE close_type='SETTLEMENT_WIN') AS wins,
    COUNT(*) FILTER (WHERE close_type='SETTLEMENT_LOSS') AS losses,
    SUM(net_pnl_usd) FILTER (WHERE pnl_status='CONFIRMED') AS net_pnl_total,
    SUM(net_pnl_usd) FILTER (WHERE pnl_status='CONFIRMED' AND net_pnl_usd > 0) AS gross_wins,
    -SUM(net_pnl_usd) FILTER (WHERE pnl_status='CONFIRMED' AND net_pnl_usd < 0) AS gross_losses,
    -- POST-RESET metrics
    COUNT(*) FILTER (WHERE opened_at >= (SELECT reset_ts FROM params)
                       AND status='CLOSED' AND pnl_status='CONFIRMED') AS rt_post,
    COUNT(*) FILTER (WHERE opened_at >= (SELECT reset_ts FROM params)
                       AND close_type='SETTLEMENT_WIN') AS wins_post,
    COUNT(*) FILTER (WHERE opened_at >= (SELECT reset_ts FROM params)
                       AND close_type='SETTLEMENT_LOSS') AS losses_post,
    SUM(net_pnl_usd) FILTER (WHERE opened_at >= (SELECT reset_ts FROM params)
                               AND pnl_status='CONFIRMED') AS net_pnl_post,
    -- NEW: distribution of post-reset PnL
    MAX(net_pnl_usd) FILTER (WHERE opened_at >= (SELECT reset_ts FROM params)
                               AND pnl_status='CONFIRMED') AS max_win_post,
    MIN(net_pnl_usd) FILTER (WHERE opened_at >= (SELECT reset_ts FROM params)
                               AND pnl_status='CONFIRMED') AS max_loss_post,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY net_pnl_usd)
      FILTER (WHERE opened_at >= (SELECT reset_ts FROM params)
                AND pnl_status='CONFIRMED') AS pnl_median_post,
    -- NEW: volume (for ROI calculation)
    SUM(open_size_usd) FILTER (WHERE opened_at >= (SELECT reset_ts FROM params)
                                 AND status='CLOSED' AND pnl_status='CONFIRMED') AS volume_post,
    -- Activity
    MAX(closed_at) AS last_closed_at,
    -- Size profile
    percentile_cont(0.5) WITHIN GROUP (ORDER BY open_size_usd)
      FILTER (WHERE opened_at >= (SELECT reset_ts FROM params)) AS size_median_post
  FROM whale_trade_roundtrips
  GROUP BY whale_id
)
SELECT
  w.id AS whale_id,
  w.wallet_address,
  w.copy_status,
  w.tier,
  rt.rt_closed,
  rt.rt_open,
  -- ALL
  ROUND(100.0 * rt.wins / NULLIF(rt.wins + rt.losses, 0), 2) AS wr_pct,
  ROUND(rt.net_pnl_total::numeric, 2) AS net_pnl_total,
  ROUND((rt.gross_wins / NULLIF(rt.gross_losses, 0))::numeric, 2) AS pf,
  -- POST-RESET (главное для решений)
  rt.rt_post,
  ROUND(100.0 * rt.wins_post / NULLIF(rt.wins_post + rt.losses_post, 0), 2) AS wr_post_pct,
  ROUND(rt.net_pnl_post::numeric, 2) AS net_pnl_post,
  -- NEW: distribution quality
  ROUND(rt.pnl_median_post::numeric, 2) AS pnl_median_post,
  ROUND(rt.max_win_post::numeric, 2) AS max_win_post,
  ROUND(rt.max_loss_post::numeric, 2) AS max_loss_post,
  -- concentration: доля max_win в total (1.0 = всё на одной сделке)
  ROUND((rt.max_win_post / NULLIF(rt.net_pnl_post, 0))::numeric, 2) AS max_win_share,
  -- NEW: edge per dollar (ROI на объём, заменяет отсутствующий estimated_capital)
  ROUND((100.0 * rt.net_pnl_post / NULLIF(rt.volume_post, 0))::numeric, 2) AS roi_on_volume_pct,
  ROUND(rt.volume_post::numeric, 0) AS volume_post,
  -- Activity
  rt.last_closed_at::date AS last_closed,
  EXTRACT(DAY FROM (now() - rt.last_closed_at))::int AS days_inactive,
  ROUND(rt.size_median_post::numeric, 2) AS size_median_post,
  -- Flags
  (rt.gross_losses IS NULL OR rt.gross_losses = 0) AS zero_losses_flag
FROM whales w
JOIN rt ON rt.whale_id = w.id
WHERE w.copy_status IN ('none', 'tracked')
  AND rt.rt_closed >= (SELECT min_rt_closed FROM params)
ORDER BY rt.net_pnl_post DESC NULLS LAST;