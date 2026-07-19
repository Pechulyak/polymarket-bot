-- ACT-006: панельные запросы поверх account_daily_position_ledger
-- Все три проверены на реальных данных (2026-07-19, 157 строк / 82 позиции).
-- Важно: economic_net — NULL, если позиция открыта (closing_balance != 0)
-- и mark_price для последней строки IS NULL (нет источника цены — ACT-007
-- ещё не сделан). НЕ заменять эту дыру на 0 в Grafana-панелях (unit override
-- на NULL, не COALESCE) — иначе повторится баг ACT-005/v_position_lifecycle.

-- ============================================================
-- 1. Таблица позиций (одна строка на account+condition_id+asset)
-- ============================================================
WITH agg AS (
    SELECT account, condition_id, asset,
           MAX(title) AS title,
           MIN(activity_date) AS first_date,
           MAX(activity_date) AS last_date,
           SUM(buy_usdc) AS total_buy_usdc,
           SUM(sell_usdc) AS total_sell_usdc,
           SUM(COALESCE(reward_usd, 0)) AS total_reward_usd,
           SUM(COALESCE(fees_usd, 0)) AS total_fees_usd
    FROM account_daily_position_ledger
    GROUP BY account, condition_id, asset
),
last_row AS (
    SELECT DISTINCT ON (account, condition_id, asset)
        account, condition_id, asset, status, avg_cost, mark_price, mark_source, closing_balance
    FROM account_daily_position_ledger
    ORDER BY account, condition_id, asset, activity_date DESC
)
SELECT
    a.account, a.title, a.condition_id, l.status,
    a.first_date, a.last_date,
    a.total_buy_usdc, a.total_sell_usdc, a.total_reward_usd, a.total_fees_usd,
    l.avg_cost, l.closing_balance, l.mark_price, l.mark_source,
    CASE
        WHEN ABS(l.closing_balance) < 0.0001
            THEN a.total_sell_usdc + a.total_reward_usd - a.total_fees_usd - a.total_buy_usdc
        WHEN l.mark_price IS NOT NULL
            THEN a.total_sell_usdc + a.total_reward_usd - a.total_fees_usd - a.total_buy_usdc
                 + (l.closing_balance * l.mark_price)
        ELSE NULL
    END AS economic_net
FROM agg a
JOIN last_row l USING (account, condition_id, asset)
ORDER BY a.last_date DESC;

-- ============================================================
-- 2. Scatter: economic_net vs дней удержания
-- ============================================================
WITH agg AS (
    SELECT account, condition_id, asset,
           MIN(activity_date) AS first_date, MAX(activity_date) AS last_date,
           SUM(buy_usdc) AS total_buy_usdc, SUM(sell_usdc) AS total_sell_usdc,
           SUM(COALESCE(reward_usd, 0)) AS total_reward_usd, SUM(COALESCE(fees_usd, 0)) AS total_fees_usd
    FROM account_daily_position_ledger GROUP BY account, condition_id, asset
),
last_row AS (
    SELECT DISTINCT ON (account, condition_id, asset)
        account, condition_id, asset, status, mark_price, closing_balance
    FROM account_daily_position_ledger ORDER BY account, condition_id, asset, activity_date DESC
),
combined AS (
    SELECT a.account, a.condition_id, a.first_date, a.last_date, l.status,
        CASE
            WHEN ABS(l.closing_balance) < 0.0001
                THEN a.total_sell_usdc + a.total_reward_usd - a.total_fees_usd - a.total_buy_usdc
            WHEN l.mark_price IS NOT NULL
                THEN a.total_sell_usdc + a.total_reward_usd - a.total_fees_usd - a.total_buy_usdc
                     + (l.closing_balance * l.mark_price)
            ELSE NULL
        END AS economic_net
    FROM agg a JOIN last_row l USING (account, condition_id, asset)
)
SELECT account, condition_id,
    CASE WHEN status = 'OPEN' THEN (CURRENT_DATE - first_date) ELSE (last_date - first_date) END AS days_held,
    economic_net, status
FROM combined
WHERE economic_net IS NOT NULL
ORDER BY days_held DESC;

-- ============================================================
-- 3. Дневная сводка по всем позициям (реализованный cash-flow за день,
--    БЕЗ mark-to-market остатков — отличается от economic_net в п.1-2)
-- ============================================================
SELECT activity_date AS time,
    SUM(buy_usdc) AS buy_usdc,
    SUM(sell_usdc) AS sell_usdc,
    SUM(COALESCE(reward_usd, 0)) AS reward_usd,
    SUM(COALESCE(fees_usd, 0)) AS fees_usd,
    SUM(sell_usdc) + SUM(COALESCE(reward_usd, 0)) - SUM(COALESCE(fees_usd, 0)) - SUM(buy_usdc) AS net_usd
FROM account_daily_position_ledger
GROUP BY activity_date
ORDER BY activity_date;
