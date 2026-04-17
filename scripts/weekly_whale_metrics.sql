-- =============================================================================
-- weekly_whale_metrics.sql
-- =============================================================================
-- Финальные SQL-запросы для еженедельного AI-анализа китов.
-- ANA-502-SQL: SQL-слой для еженедельного AI-анализа
-- =============================================================================

-- =============================================================================
-- БЛОК 1: Метрики paper/tracked китов
-- =============================================================================
-- Возвращает по каждому киту со статусом paper или tracked:
-- - wallet_address, copy_status
-- - WR all-time (win_rate_confirmed из whales)
-- - WR за последние 14 дней (из whale_trade_roundtrips, pnl_status='CONFIRMED')
-- - total_pnl_usd, trades_last_7_days, avg_pnl_usd
-- - Количество CLOSED roundtrips (all-time) и OPEN позиций
-- - Weekly PnL за последние 4 недели (4 отдельных значения: неделя 1, 2, 3, 4 назад)
-- - Skip rate proxy: соотношение source='POLLER' к source='TRACKED' за 7 дней

WITH 
-- Weekly PnL for last 4 weeks (CONFIRMED only)
weekly_pnl AS (
    SELECT 
        wtr.wallet_address,
        EXTRACT(WEEK FROM NOW() - INTERVAL '1 week') - EXTRACT(WEEK FROM wtr.closed_at) AS weeks_ago,
        SUM(wtr.net_pnl_usd) AS weekly_net_pnl
    FROM whale_trade_roundtrips wtr
    WHERE wtr.pnl_status = 'CONFIRMED'
      AND wtr.closed_at >= NOW() - INTERVAL '28 days'
    GROUP BY wtr.wallet_address, EXTRACT(WEEK FROM NOW() - INTERVAL '1 week') - EXTRACT(WEEK FROM wtr.closed_at)
),
weekly_pnl_pivot AS (
    SELECT 
        wallet_address,
        COALESCE(SUM(CASE WHEN weeks_ago = 0 THEN weekly_net_pnl END), 0) AS pnl_week_1,
        COALESCE(SUM(CASE WHEN weeks_ago = 1 THEN weekly_net_pnl END), 0) AS pnl_week_2,
        COALESCE(SUM(CASE WHEN weeks_ago = 2 THEN weekly_net_pnl END), 0) AS pnl_week_3,
        COALESCE(SUM(CASE WHEN weeks_ago = 3 THEN weekly_net_pnl END), 0) AS pnl_week_4
    FROM weekly_pnl
    GROUP BY wallet_address
),
-- Skip rate proxy: POLLER vs TRACKED ratio in last 7 days
skip_rate AS (
    SELECT 
        wallet_address,
        COUNT(*) FILTER (WHERE source = 'POLLER') AS poller_count,
        COUNT(*) FILTER (WHERE source = 'TRACKED') AS tracked_count,
        ROUND(
            COUNT(*) FILTER (WHERE source = 'POLLER')::NUMERIC / 
            NULLIF(COUNT(*) FILTER (WHERE source = 'TRACKED'), 0)::NUMERIC, 
            2
        ) AS skip_ratio
    FROM whale_trades
    WHERE traded_at >= NOW() - INTERVAL '7 days'
    GROUP BY wallet_address
),
-- Roundtrip stats
roundtrip_stats AS (
    SELECT 
        wallet_address,
        COUNT(*) FILTER (WHERE pnl_status = 'CONFIRMED') AS confirmed_roundtrips,
        COUNT(*) FILTER (WHERE pnl_status = 'CONFIRMED' AND closed_at >= NOW() - INTERVAL '14 days') AS confirmed_last_14d,
        COUNT(*) FILTER (WHERE pnl_status = 'CONFIRMED' AND closed_at >= NOW() - INTERVAL '14 days' AND net_pnl_usd > 0) AS wins_14d,
        COUNT(*) FILTER (WHERE status = 'OPEN') AS open_positions
    FROM whale_trade_roundtrips
    GROUP BY wallet_address
)
SELECT 
    w.wallet_address,
    w.copy_status,
    ROUND(w.win_rate_confirmed::NUMERIC, 4) AS wr_alltime,
    ROUND(
        rs.wins_14d::NUMERIC / NULLIF(rs.confirmed_last_14d, 0),
        4
    ) AS wr_14d_direct,
    ROUND(w.total_pnl_usd::NUMERIC, 2) AS total_pnl_usd,
    COALESCE(w.trades_last_7_days, 0) AS trades_last_7_days,
    ROUND(COALESCE(w.avg_pnl_usd, 0)::NUMERIC, 4) AS avg_pnl_usd,
    rs.confirmed_roundtrips AS closed_roundtrips,
    rs.open_positions,
    ROUND(wp.pnl_week_1::NUMERIC, 2) AS pnl_week_1,
    ROUND(wp.pnl_week_2::NUMERIC, 2) AS pnl_week_2,
    ROUND(wp.pnl_week_3::NUMERIC, 2) AS pnl_week_3,
    ROUND(wp.pnl_week_4::NUMERIC, 2) AS pnl_week_4,
    COALESCE(sr.skip_ratio, 0) AS skip_ratio
FROM whales w
LEFT JOIN roundtrip_stats rs ON rs.wallet_address = w.wallet_address
LEFT JOIN weekly_pnl_pivot wp ON wp.wallet_address = w.wallet_address
LEFT JOIN skip_rate sr ON sr.wallet_address = w.wallet_address
WHERE w.copy_status IN ('paper', 'tracked')
ORDER BY w.total_pnl_usd DESC NULLS LAST
LIMIT 20;

-- =============================================================================
-- БЛОК 2: Кандидаты из none
-- =============================================================================
-- Топ-5 китов из whales где copy_status = 'none':
-- - Минимум 30 CONFIRMED roundtrips в whale_trade_roundtrips
-- - Сортировка по total_pnl_usd DESC
-- - Поля: wallet_address, total_pnl_usd, win_rate_confirmed, trades_last_7_days,
--         days_active_7d, whale_category, доминирующая market_category из whale_trades

WITH 
-- Count CONFIRMED roundtrips per whale
confirmed_counts AS (
    SELECT 
        wallet_address,
        COUNT(*) FILTER (WHERE pnl_status = 'CONFIRMED') AS confirmed_roundtrips
    FROM whale_trade_roundtrips
    GROUP BY wallet_address
),
-- Dominant market_category per whale (from whale_trades)
dominant_category AS (
    SELECT 
        wallet_address,
        market_category,
        trade_count,
        ROW_NUMBER() OVER (PARTITION BY wallet_address ORDER BY trade_count DESC) AS rn
    FROM (
        SELECT 
            wallet_address,
            market_category,
            COUNT(*) AS trade_count
        FROM whale_trades
        WHERE market_category IS NOT NULL
        GROUP BY wallet_address, market_category
    ) sub
)
SELECT 
    w.wallet_address,
    ROUND(w.total_pnl_usd::NUMERIC, 2) AS total_pnl_usd,
    ROUND(w.win_rate_confirmed::NUMERIC, 4) AS win_rate_confirmed,
    COALESCE(w.trades_last_7_days, 0) AS trades_last_7_days,
    w.days_active_7d,
    w.whale_category,
    dc.market_category AS dominant_category
FROM whales w
JOIN confirmed_counts cc ON cc.wallet_address = w.wallet_address
LEFT JOIN dominant_category dc ON dc.wallet_address = w.wallet_address AND dc.rn = 1
WHERE w.copy_status = 'none'
  AND cc.confirmed_roundtrips >= 30
ORDER BY w.total_pnl_usd DESC NULLS LAST
LIMIT 5;

-- =============================================================================
-- БЛОК 3: Системный edge по категориям
-- =============================================================================
-- Агрегация по market_category из whale_trade_roundtrips где pnl_status = 'CONFIRMED':
-- - confirmed_count, avg_net_pnl, total_net_pnl, win_rate по категории
-- - Топ-кит (по total_pnl_usd) в каждой категории
-- - Сортировка по total_net_pnl DESC

WITH 
category_stats AS (
    SELECT 
        market_category,
        COUNT(*) AS confirmed_count,
        AVG(net_pnl_usd) AS avg_net_pnl,
        SUM(net_pnl_usd) AS total_net_pnl,
        COUNT(*) FILTER (WHERE net_pnl_usd > 0) AS wins,
        COUNT(*) FILTER (WHERE net_pnl_usd <= 0) AS losses
    FROM whale_trade_roundtrips
    WHERE pnl_status = 'CONFIRMED'
      AND market_category IS NOT NULL
    GROUP BY market_category
),
top_whale_per_category AS (
    SELECT 
        wtr.market_category,
        wtr.wallet_address,
        SUM(wtr.net_pnl_usd) AS whale_total_pnl,
        ROW_NUMBER() OVER (PARTITION BY wtr.market_category ORDER BY SUM(wtr.net_pnl_usd) DESC) AS rn
    FROM whale_trade_roundtrips wtr
    WHERE wtr.pnl_status = 'CONFIRMED'
    GROUP BY wtr.market_category, wtr.wallet_address
)
SELECT 
    cs.market_category,
    cs.confirmed_count,
    ROUND(cs.avg_net_pnl::NUMERIC, 2) AS avg_net_pnl,
    ROUND(cs.total_net_pnl::NUMERIC, 2) AS total_net_pnl,
    ROUND(
        cs.wins::NUMERIC / NULLIF(cs.confirmed_count, 0),
        4
    ) AS win_rate,
    tw.wallet_address AS top_whale_address,
    ROUND(tw.whale_total_pnl::NUMERIC, 2) AS top_whale_pnl
FROM category_stats cs
LEFT JOIN top_whale_per_category tw ON tw.market_category = cs.market_category AND tw.rn = 1
ORDER BY cs.total_net_pnl DESC NULLS LAST;
