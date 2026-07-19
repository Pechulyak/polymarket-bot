-- ACT-005: панельные запросы для Grafana-дашбордов "Farming Daily" и "Position Lifecycle"
-- Data source: Postgres S1 (212.192.11.92:5433, база polymarket)
-- Переменные $__timeFrom()/$__timeTo() — стандартные Grafana time range макросы.
-- snap_date/event_ts фильтруются вручную (BETWEEN ::date), а не через $__timeFilter(),
-- т.к. snap_date — DATE, а $__timeFilter ожидает timestamptz-семантику.

-- ============================================================
-- DASHBOARD 1: Farming Daily (источник: farming_daily_snapshot)
-- ============================================================

-- 1.1 Reward / Fees / Net по дням + 7-дневная MA (time series)
WITH daily AS (
    SELECT
        snap_date,
        sum(reward_usd) AS reward_usd,
        sum(fees_usd)   AS fees_usd,
        sum(reward_usd) - sum(fees_usd) AS net_usd
    FROM farming_daily_snapshot
    WHERE snap_date BETWEEN $__timeFrom()::date AND $__timeTo()::date
    GROUP BY snap_date
)
SELECT
    snap_date AS time,
    reward_usd,
    fees_usd,
    net_usd,
    AVG(net_usd)    OVER (ORDER BY snap_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS net_usd_ma7,
    AVG(reward_usd) OVER (ORDER BY snap_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS reward_usd_ma7
FROM daily
ORDER BY snap_date;

-- 1.2 Capital по дням + net/capital % (time series, 2 оси: $ и %)
SELECT
    snap_date AS time,
    sum(capital_usd) AS capital_usd,
    sum(reward_usd) - sum(fees_usd) AS net_usd,
    ROUND(
        100.0 * (sum(reward_usd) - sum(fees_usd)) / NULLIF(sum(capital_usd), 0)
    , 4) AS net_pct_of_capital
FROM farming_daily_snapshot
WHERE snap_date BETWEEN $__timeFrom()::date AND $__timeTo()::date
GROUP BY snap_date
ORDER BY snap_date;

-- 1.3 Reward по рынкам, stacked (time series long-format: time, metric, value —
--     Grafana Postgres datasource автоматически строит серии по колонке "metric")
SELECT
    fds.snap_date AS time,
    COALESCE(fmc.slug, fds.condition_id, fds.token) AS metric,
    sum(fds.reward_usd) AS reward_usd
FROM farming_daily_snapshot fds
LEFT JOIN farming_market_candidates fmc ON fmc.condition_id = fds.condition_id
WHERE fds.snap_date BETWEEN $__timeFrom()::date AND $__timeTo()::date
GROUP BY fds.snap_date, COALESCE(fmc.slug, fds.condition_id, fds.token)
ORDER BY fds.snap_date;

-- ============================================================
-- DASHBOARD 2: Position Lifecycle (источник: view v_position_lifecycle,
-- см. migrations/migration_act005_position_lifecycle_view.sql)
-- ============================================================

-- 2.1 Таблица позиций (основная панель дашборда)
SELECT
    account,
    title,
    status,
    first_buy_ts,
    exit_ts,
    days_held,
    avg_buy_price,
    avg_sell_price,
    reward_usd,
    fees_usd,
    trading_pnl_usd,
    net_usd,
    current_size,
    redeemable,
    condition_id
FROM v_position_lifecycle
ORDER BY first_buy_ts DESC;

-- 2.2 Scatter: net позиции vs дней удержания
--     (в Grafana: панель "State timeline"/"XY chart" или "Scatter", X = days_held, Y = net_usd)
SELECT
    days_held,
    net_usd,
    status,
    title,
    account
FROM v_position_lifecycle
WHERE days_held IS NOT NULL
ORDER BY days_held;

-- 2.3 (справочно) Сводка по статусам — для stat/pie панели рядом со scatter
SELECT
    status,
    count(*)          AS n_positions,
    sum(net_usd)       AS total_net_usd,
    avg(days_held)     AS avg_days_held
FROM v_position_lifecycle
GROUP BY status
ORDER BY n_positions DESC;
