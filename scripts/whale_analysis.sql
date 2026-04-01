-- Whale Analysis SQL Script
-- ANALYTICS-001: Создать SQL-скрипт анализа китов
-- Запуск: cat scripts/whale_analysis.sql | docker compose exec -T postgres psql -U postgres -d polymarket

\echo '================================================'
\echo 'БЛОК 1: Общая сводка по китам с roundtrips'
\echo '================================================'

SELECT 
    SUBSTRING(w.wallet_address FROM 1 FOR 10) AS wallet,
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

SELECT 
    SUBSTRING(w.wallet_address FROM 1 FOR 10) AS wallet,
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
    COUNT(DISTINCT rt.market_id) AS unique_markets,
    MIN(rt.opened_at) AS first_trade,
    MAX(rt.closed_at) AS last_trade,
    COALESCE(AVG(t.size_usd), 0)::numeric(20,2) AS avg_size_usd_from_trades,
    -- Dominant outcome
    (SELECT outcome 
     FROM whale_trade_roundtrips 
     WHERE whale_id = w.id AND outcome IS NOT NULL 
     GROUP BY outcome 
     ORDER BY COUNT(*) DESC 
     LIMIT 1) AS dominant_outcome,
    -- Dominant side
    (SELECT open_side 
     FROM whale_trade_roundtrips 
     WHERE whale_id = w.id AND open_side IS NOT NULL 
     GROUP BY open_side 
     ORDER BY COUNT(*) DESC 
     LIMIT 1) AS dominant_side
FROM whales w
LEFT JOIN whale_trade_roundtrips rt ON rt.whale_id = w.id
LEFT JOIN whale_trades t ON t.whale_id = w.id
WHERE w.copy_status IN ('tracked', 'paper')
    AND w.total_roundtrips > 0
GROUP BY w.id, w.wallet_address, w.copy_status, w.tier, w.total_trades
ORDER BY total_pnl DESC NULLS LAST;

\echo ''
\echo '================================================'
\echo 'БЛОК 3a: Концентрация сделок по рынкам (топ-5 для каждого кита)'
\echo '================================================'

WITH whale_market_stats AS (
    SELECT 
        w.id AS whale_id,
        SUBSTRING(w.wallet_address FROM 1 FOR 10) AS whale,
        rt.market_id,
        MAX(rt.market_title) AS market_title,
        COUNT(DISTINCT t.id) AS trades_count,
        COUNT(DISTINCT rt.id) AS roundtrips_count,
        SUM(t.size_usd) AS total_volume,
        AVG(t.price) AS avg_price,
        COUNT(t.id) FILTER (WHERE t.side = 'buy') AS buy_trades,
        COUNT(t.id) FILTER (WHERE t.side = 'sell') AS sell_trades
    FROM whales w
    JOIN whale_trades t ON t.whale_id = w.id
    JOIN whale_trade_roundtrips rt ON rt.whale_id = w.id AND rt.market_id = t.market_id
    WHERE w.copy_status IN ('tracked', 'paper')
    GROUP BY w.id, w.wallet_address, rt.market_id
)
SELECT 
    whale,
    market_id,
    market_title,
    trades_count,
    roundtrips_count,
    total_volume::numeric(20,2) AS total_volume,
    ROUND(avg_price::numeric(20,4), 4) AS avg_price,
    CONCAT(buy_trades, '/', sell_trades) AS buy_sell
FROM whale_market_stats
ORDER BY whale, trades_count DESC;

\echo ''
\echo '================================================'
\echo 'БЛОК 3b: Ratio trades/roundtrips per market'
\echo '================================================'

WITH market_trades AS (
    SELECT 
        t.whale_id,
        rt.market_id,
        COUNT(DISTINCT t.id) AS trades_count,
        COUNT(DISTINCT rt.id) AS roundtrips_count
    FROM whale_trades t
    JOIN whale_trade_roundtrips rt ON rt.whale_id = t.whale_id AND rt.market_id = t.market_id
    GROUP BY t.whale_id, rt.market_id
)
SELECT 
    SUBSTRING(w.wallet_address FROM 1 FOR 10) AS whale,
    ROUND(AVG(mt.trades_count::numeric / NULLIF(mt.roundtrips_count, 0)), 2) AS avg_trades_per_roundtrip,
    MAX(mt.trades_count) AS max_trades_per_market,
    COUNT(mt.market_id) FILTER (WHERE mt.trades_count >= 10) AS markets_with_10plus_trades
FROM whales w
JOIN market_trades mt ON mt.whale_id = w.id
WHERE w.copy_status IN ('tracked', 'paper')
GROUP BY w.id, w.wallet_address
ORDER BY avg_trades_per_roundtrip DESC;

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
    SUBSTRING(w.wallet_address FROM 1 FOR 10) AS whale,
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
\echo 'БЛОК 4: Кандидаты на исключение'
\echo '================================================'

WITH whale_stats AS (
    SELECT 
        w.id AS whale_id,
        w.wallet_address,
        w.copy_status,
        w.total_trades,
        w.avg_trade_size_usd,
        COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED') AS closed_roundtrips,
        COALESCE(SUM(rt.net_pnl_usd) FILTER (WHERE rt.status = 'CLOSED'), 0) AS total_pnl,
        ROUND(COALESCE(
            100.0 * COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED' AND rt.net_pnl_usd > 0) / 
            NULLIF(COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED'), 0), 0
        ), 2) AS win_rate_pct
    FROM whales w
    LEFT JOIN whale_trade_roundtrips rt ON rt.whale_id = w.id
    GROUP BY w.id, w.wallet_address, w.copy_status, w.total_trades, w.avg_trade_size_usd
    HAVING COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED') >= 5
        OR w.total_trades > 500
),
trades_per_roundtrip AS (
    SELECT 
        t.whale_id,
        rt.market_id,
        COUNT(DISTINCT t.id)::numeric AS trades_per_roundtrip
    FROM whale_trades t
    JOIN whale_trade_roundtrips rt ON rt.whale_id = t.whale_id AND rt.market_id = t.market_id
    GROUP BY t.whale_id, rt.market_id
),
whale_exclusions AS (
    SELECT DISTINCT
        ws.whale_id,
        ws.wallet_address,
        ws.copy_status,
        ws.total_trades,
        ws.avg_trade_size_usd,
        ws.closed_roundtrips,
        ws.total_pnl,
        ws.win_rate_pct,
        CASE 
            WHEN ws.win_rate_pct < 45 AND ws.closed_roundtrips >= 5 THEN 'low_win_rate'
            WHEN tpr.trades_per_roundtrip > 20 THEN 'mm_pattern'
            WHEN ws.total_pnl < 0 AND ws.closed_roundtrips >= 10 THEN 'consistent_loser'
            WHEN ws.avg_trade_size_usd < 100 AND ws.total_trades > 500 THEN 'micro_scalper'
        END AS reason
    FROM whale_stats ws
    LEFT JOIN trades_per_roundtrip tpr ON tpr.whale_id = ws.whale_id
    WHERE 
        (ws.win_rate_pct < 45 AND ws.closed_roundtrips >= 5)
        OR (tpr.trades_per_roundtrip > 20)
        OR (ws.total_pnl < 0 AND ws.closed_roundtrips >= 10)
        OR (ws.avg_trade_size_usd < 100 AND ws.total_trades > 500)
)
SELECT 
    SUBSTRING(wallet_address FROM 1 FOR 10) AS whale,
    copy_status,
    reason,
    CASE 
        WHEN reason = 'low_win_rate' THEN CONCAT('win_rate: ', win_rate_pct, '%, closed_rt: ', closed_roundtrips)
        WHEN reason = 'mm_pattern' THEN 'trades/roundtrip > 20'
        WHEN reason = 'consistent_loser' THEN CONCAT('total_pnl: $', total_pnl)
        WHEN reason = 'micro_scalper' THEN CONCAT('avg_trade: $', avg_trade_size_usd, ', total_trades: ', total_trades)
    END AS details,
    CASE 
        WHEN reason = 'low_win_rate' THEN 'EXCLUDE: low win rate'
        WHEN reason = 'mm_pattern' THEN 'EXCLUDE: likely market maker'
        WHEN reason = 'consistent_loser' THEN 'EXCLUDE: consistently unprofitable'
        WHEN reason = 'micro_scalper' THEN 'EXCLUDE: micro scalper'
    END AS recommendation
FROM whale_exclusions
ORDER BY whale, reason;

\echo ''
\echo '================================================'
\echo 'БЛОК 5: Кандидаты на повышение'
\echo '================================================'

WITH whale_stats AS (
    SELECT 
        w.id AS whale_id,
        w.wallet_address,
        w.copy_status,
        w.tier,
        COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED') AS closed_roundtrips,
        COALESCE(SUM(rt.net_pnl_usd) FILTER (WHERE rt.status = 'CLOSED'), 0) AS total_pnl,
        ROUND(COALESCE(
            100.0 * COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED' AND rt.net_pnl_usd > 0) / 
            NULLIF(COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED'), 0), 0
        ), 2) AS win_rate_pct
    FROM whales w
    LEFT JOIN whale_trade_roundtrips rt ON rt.whale_id = w.id
    WHERE w.copy_status IN ('none', 'tracked')
    GROUP BY w.id, w.wallet_address, w.copy_status, w.tier
    HAVING COUNT(rt.id) FILTER (WHERE rt.status = 'CLOSED') >= 5
),
trades_per_roundtrip AS (
    SELECT 
        sub.whale_id,
        AVG(sub.trades_count::numeric) AS avg_trades_per_roundtrip
    FROM (
        SELECT 
            t.whale_id,
            rt.market_id,
            COUNT(DISTINCT t.id) AS trades_count
        FROM whale_trades t
        JOIN whale_trade_roundtrips rt ON rt.whale_id = t.whale_id AND rt.market_id = t.market_id
        GROUP BY t.whale_id, rt.market_id
    ) sub
    GROUP BY sub.whale_id
)
SELECT 
    SUBSTRING(ws.wallet_address FROM 1 FOR 10) AS whale,
    ws.copy_status,
    ws.tier,
    ROUND(ws.win_rate_pct, 2) AS win_rate_pct,
    ws.closed_roundtrips,
    ws.total_pnl::numeric(20,2) AS total_pnl,
    ROUND(COALESCE(tpr.avg_trades_per_roundtrip, 0), 2) AS avg_trades_per_roundtrip,
    CASE 
        WHEN ws.copy_status = 'none' THEN 'PROMOTE to tracked'
        WHEN ws.copy_status = 'tracked' THEN 'CONSIDER for paper/live'
    END AS recommendation
FROM whale_stats ws
LEFT JOIN trades_per_roundtrip tpr ON tpr.whale_id = ws.whale_id
WHERE 
    ws.win_rate_pct >= 60
    AND ws.total_pnl > 0
    AND (tpr.avg_trades_per_roundtrip < 10 OR tpr.avg_trades_per_roundtrip IS NULL)
ORDER BY ws.win_rate_pct DESC, ws.total_pnl DESC;

\echo ''
\echo '================================================'
\echo 'Анализ завершён'
\echo '================================================'
