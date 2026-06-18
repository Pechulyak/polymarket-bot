-- Whale Analysis SQL Script
-- ANALYTICS-001: Создать SQL-скрипт анализа китов
-- Запуск: cat scripts/whale_analysis.sql | docker compose exec -T postgres psql -U postgres -d polymarket

\echo '================================================'
\echo 'БЛОК 1: Общая сводка по китам с roundtrips'
\echo '================================================'

SELECT 
    w.wallet_address AS wallet,
    w.copy_status,
    w.tier,
    w.total_trades AS total_whale_trades,
    COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED') AS closed_roundtrips,
    COUNT(rt.id) FILTER (WHERE rt.status = 'OPEN') AS open_roundtrips,
    ROUND(COALESCE(
        CASE 
            WHEN (COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED' AND rt.net_pnl_usd > 0) + COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED' AND rt.net_pnl_usd <= 0)) > 0
            THEN 100.0 * COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED' AND rt.net_pnl_usd > 0) / 
                 NULLIF(COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED'), 0)
            ELSE NULL
        END, 0
    ), 2) AS win_rate_pct,
    COALESCE(SUM(rt.net_pnl_usd) FILTER (WHERE rt.status = 'CLOSED'), 0)::numeric(20,2) AS total_pnl,
    COALESCE(AVG(rt.net_pnl_usd) FILTER (WHERE rt.status = 'CLOSED'), 0)::numeric(20,2) AS avg_pnl_per_roundtrip,
    COALESCE(AVG(rt.open_size_usd) FILTER (WHERE rt.status = 'CLOSED'), 0)::numeric(20,2) AS avg_entry_amount
FROM whales w
LEFT JOIN whale_trade_roundtrips rt ON rt.whale_id = w.id
WHERE w.total_roundtrips > 0
GROUP BY w.id, w.wallet_address, w.copy_status, w.tier, w.total_trades
ORDER BY total_pnl DESC NULLS LAST
LIMIT 50;

\echo ''
\echo '================================================'
\echo 'БЛОК 2: Детализация по китам tracked + paper'
\echo '================================================'

-- Упрощённый запрос: убраны correlated subqueries, убран LEFT JOIN whale_trades
SELECT 
    w.wallet_address AS wallet,
    w.copy_status,
    w.tier,
    w.total_trades AS total_whale_trades,
    COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED') AS closed_roundtrips,
    COUNT(rt.id) FILTER (WHERE rt.status = 'OPEN') AS open_roundtrips,
    ROUND(COALESCE(
        CASE 
            WHEN COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED') > 0
            THEN 100.0 * COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED' AND rt.net_pnl_usd > 0) / 
                 COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED')
            ELSE 0
        END, 0
    ), 2) AS win_rate_pct,
    COALESCE(SUM(rt.net_pnl_usd) FILTER (WHERE rt.status = 'CLOSED'), 0)::numeric(20,2) AS total_pnl,
    COALESCE(AVG(rt.net_pnl_usd) FILTER (WHERE rt.status = 'CLOSED'), 0)::numeric(20,2) AS avg_pnl_per_roundtrip,
    COUNT(DISTINCT rt.market_id) AS unique_markets,
    MIN(rt.opened_at) AS first_trade,
    MAX(rt.closed_at) FILTER (WHERE rt.status = 'CLOSED') AS last_trade,
    -- Dominant outcome (без correlated subquery)
    MODE() WITHIN GROUP (ORDER BY rt.outcome) FILTER (WHERE rt.outcome IS NOT NULL) AS dominant_outcome,
    -- Dominant side (без correlated subquery)
    MODE() WITHIN GROUP (ORDER BY rt.open_side) FILTER (WHERE rt.open_side IS NOT NULL) AS dominant_side
FROM whales w
LEFT JOIN whale_trade_roundtrips rt ON rt.whale_id = w.id
WHERE w.copy_status IN ('tracked', 'paper')
    AND w.total_roundtrips > 0
GROUP BY w.id, w.wallet_address, w.copy_status, w.tier, w.total_trades
ORDER BY total_pnl DESC NULLS LAST;

\echo ''
\echo '================================================'
\echo 'БЛОК 3a: Концентрация по рынкам (топ-5 на кита)'
\echo '================================================'

-- Упрощённый: только whale_trade_roundtrips, без JOIN с whale_trades
WITH ranked_markets AS (
    SELECT 
        w.id AS whale_id,
        w.wallet_address AS whale,
        rt.market_id,
        MAX(rt.market_title) AS market_title,
        COUNT(rt.id) AS roundtrips_count,
        COUNT(DISTINCT rt.market_id) AS unique_markets,
        SUM(rt.open_size_usd) AS total_volume,
        AVG(rt.open_price) AS avg_price,
        ROW_NUMBER() OVER (PARTITION BY w.id ORDER BY COUNT(rt.id) DESC) AS rn
    FROM whales w
    JOIN whale_trade_roundtrips rt ON rt.whale_id = w.id
    WHERE w.copy_status IN ('tracked', 'paper')
    GROUP BY w.id, w.wallet_address, rt.market_id
)
SELECT 
    whale,
    market_id,
    market_title,
    roundtrips_count AS trades_count,
    total_volume::numeric(20,2) AS total_volume,
    ROUND(avg_price::numeric(20,4), 4) AS avg_price
FROM ranked_markets
WHERE rn <= 5
ORDER BY whale, roundtrips_count DESC;

\echo ''
\echo '================================================'
\echo 'БЛОК 3b: Ratio trades/roundtrips per market'
\echo '================================================'

-- Упрощённый: считаем только roundtrips, без JOIN с whale_trades
SELECT 
    w.wallet_address AS whale,
    ROUND(AVG(cnt)::numeric, 2) AS avg_roundtrips_per_market,
    MAX(cnt) AS max_roundtrips_per_market,
    COUNT(*) FILTER (WHERE cnt >= 10) AS markets_with_10plus_trades
FROM (
    SELECT 
        whale_id,
        market_id,
        COUNT(*) AS cnt
    FROM whale_trade_roundtrips
    GROUP BY whale_id, market_id
) rt_cnt
JOIN whales w ON w.id = rt_cnt.whale_id
WHERE w.copy_status IN ('tracked', 'paper')
GROUP BY w.id, w.wallet_address
ORDER BY avg_roundtrips_per_market DESC;

\echo ''
\echo '================================================'
\echo 'БЛОК 3c: Временные паттерны'
\echo '================================================'

WITH daily_trades_calc AS (
    SELECT 
        whale_id,
        DATE(traded_at) AS trade_date,
        COUNT(*) AS daily_count
    FROM whale_trades
    GROUP BY whale_id, DATE(traded_at)
),
first_hour_trades AS (
    SELECT 
        whale_id,
        COUNT(*) AS first_hour_count
    FROM whale_trades
    WHERE EXTRACT(HOUR FROM traded_at) < 1
    GROUP BY whale_id
)
SELECT 
    w.wallet_address AS whale,
    ROUND(AVG(dtc.daily_count), 2) AS avg_trades_per_day,
    COUNT(dtc.trade_date) AS active_days,
    ROUND(
        100.0 * COALESCE(fht.first_hour_count, 0) / NULLIF(COUNT(dtc.daily_count), 0)
    , 1) AS trades_in_first_hour_pct
FROM whales w
LEFT JOIN daily_trades_calc dtc ON dtc.whale_id = w.id
LEFT JOIN first_hour_trades fht ON fht.whale_id = w.id
WHERE w.copy_status IN ('tracked', 'paper')
GROUP BY w.id, w.wallet_address, fht.first_hour_count
ORDER BY avg_trades_per_day DESC;

\echo ''
\echo '================================================'
\echo 'БЛОК 4: Кандидаты на исключение (топ-50)'
\echo '================================================'

-- Упрощённый: убран JOIN с whale_trades, убрана сложная subquery
SELECT 
    w.wallet_address AS whale,
    w.copy_status,
    CASE 
        WHEN ws.win_rate_pct < 45 AND ws.closed_roundtrips >= 5 THEN 'low_win_rate'
        WHEN ws.roundtrips_per_market > 20 THEN 'mm_pattern'
        WHEN ws.total_pnl < 0 AND ws.closed_roundtrips >= 10 THEN 'consistent_loser'
        WHEN w.avg_trade_size_usd < 100 AND w.total_trades > 500 THEN 'micro_scalper'
    END AS reason,
    CASE 
        WHEN ws.win_rate_pct < 45 AND ws.closed_roundtrips >= 5 THEN CONCAT('win_rate: ', ws.win_rate_pct, '%, closed_rt: ', ws.closed_roundtrips)
        WHEN ws.roundtrips_per_market > 20 THEN 'roundtrips_per_market > 20'
        WHEN ws.total_pnl < 0 AND ws.closed_roundtrips >= 10 THEN CONCAT('total_pnl: $', ws.total_pnl)
        WHEN w.avg_trade_size_usd < 100 AND w.total_trades > 500 THEN CONCAT('avg_trade: $', w.avg_trade_size_usd, ', total_trades: ', w.total_trades)
    END AS details,
    CASE 
        WHEN ws.win_rate_pct < 45 AND ws.closed_roundtrips >= 5 THEN 'EXCLUDE: low win rate'
        WHEN ws.roundtrips_per_market > 20 THEN 'EXCLUDE: likely market maker'
        WHEN ws.total_pnl < 0 AND ws.closed_roundtrips >= 10 THEN 'EXCLUDE: consistently unprofitable'
        WHEN w.avg_trade_size_usd < 100 AND w.total_trades > 500 THEN 'EXCLUDE: micro scalper'
    END AS recommendation
FROM whales w
JOIN (
    SELECT 
        w.id AS whale_id,
        COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED') AS closed_roundtrips,
        COALESCE(SUM(rt.net_pnl_usd) FILTER (WHERE rt.status = 'CLOSED'), 0) AS total_pnl,
        ROUND(COALESCE(
            100.0 * COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED' AND rt.net_pnl_usd > 0) / 
            NULLIF(COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED'), 0), 0
        ), 2) AS win_rate_pct,
        ROUND(COUNT(rt.id)::numeric / NULLIF(COUNT(DISTINCT rt.market_id), 0), 2) AS roundtrips_per_market
    FROM whales w
    LEFT JOIN whale_trade_roundtrips rt ON rt.whale_id = w.id
    GROUP BY w.id
    HAVING COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED') >= 5
        OR w.total_trades > 500
) ws ON ws.whale_id = w.id
WHERE 
    (ws.win_rate_pct < 45 AND ws.closed_roundtrips >= 5)
    OR (ws.roundtrips_per_market > 20)
    OR (ws.total_pnl < 0 AND ws.closed_roundtrips >= 10)
    OR (w.avg_trade_size_usd < 100 AND w.total_trades > 500)
ORDER BY 
    CASE 
        WHEN ws.win_rate_pct < 45 AND ws.closed_roundtrips >= 5 THEN 1
        WHEN ws.roundtrips_per_market > 20 THEN 2
        WHEN ws.total_pnl < 0 AND ws.closed_roundtrips >= 10 THEN 3
        WHEN w.avg_trade_size_usd < 100 AND w.total_trades > 500 THEN 4
    END,
    ws.total_pnl ASC
LIMIT 50;

\echo ''
\echo '================================================'
\echo 'БЛОК 5: Кандидаты на повышение'
\echo '================================================'

-- Упрощённый: убран JOIN с whale_trades
SELECT 
    w.wallet_address AS whale,
    w.copy_status,
    w.tier,
    ws.win_rate_pct,
    ws.closed_roundtrips,
    ws.total_pnl::numeric(20,2) AS total_pnl,
    ws.roundtrips_per_market,
    CASE 
        WHEN w.copy_status = 'none' THEN 'PROMOTE to tracked'
        WHEN w.copy_status = 'tracked' THEN 'CONSIDER for paper/live'
    END AS recommendation
FROM whales w
JOIN (
    SELECT 
        w.id AS whale_id,
        ROUND(COALESCE(
            100.0 * COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED' AND rt.net_pnl_usd > 0) / 
            NULLIF(COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED'), 0), 0
        ), 2) AS win_rate_pct,
        COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED') AS closed_roundtrips,
        COALESCE(SUM(rt.net_pnl_usd) FILTER (WHERE rt.status = 'CLOSED'), 0) AS total_pnl,
        ROUND(COUNT(rt.id)::numeric / NULLIF(COUNT(DISTINCT rt.market_id), 0), 2) AS roundtrips_per_market
    FROM whales w
    LEFT JOIN whale_trade_roundtrips rt ON rt.whale_id = w.id
    WHERE w.copy_status IN ('none', 'tracked')
    GROUP BY w.id
    HAVING COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED') >= 5
) ws ON ws.whale_id = w.id
WHERE 
    ws.win_rate_pct >= 60
    AND ws.total_pnl > 0
    AND (ws.roundtrips_per_market < 10 OR ws.roundtrips_per_market IS NULL)
ORDER BY ws.win_rate_pct DESC, ws.total_pnl DESC
LIMIT 50;

\echo ''
\echo '================================================'
\echo 'Анализ завершён'
\echo '================================================'
