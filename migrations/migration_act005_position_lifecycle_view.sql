-- ACT-005: view v_position_lifecycle для дашборда Grafana "Position Lifecycle"
-- Грейн: (account, condition_id, asset) — одна строка на удерживаемый outcome-token
-- на аккаунт. Источники: account_activity (TRADE/REDEEM), account_positions_snapshot
-- (последний снапшот для текущего статуса/размера), farming_daily_snapshot (reward/fees
-- по фарм-рынкам — НЕ по всем позициям, см. примечание ниже).
--
-- Важные ограничения данных (проверено по живой БД 2026-07-19):
-- 1. REWARD/MAKER_REBATE в account_activity приходят с condition_id='' — Polymarket
--    не привязывает их к конкретному рынку в /activity. Поэтому reward/fees здесь
--    берутся из farming_daily_snapshot по condition_id, а НЕ из account_activity.
--    Это покрывает только фарм-рынки (13 из 81 traded condition_id на момент проверки);
--    для остальных позиций reward_usd/fees_usd будут NULL — это корректно, не баг.
-- 2. REDEEM-события несут condition_id, но НЕ несут asset (settlement на уровне рынка).
--    Если один аккаунт одновременно держит несколько исходов одного condition_id,
--    redeem_usdc будет приписан ко всем таким позициям (сейчас в данных такого нет).
-- 3. farming_daily_snapshot не хранит account — если когда-либо оба аккаунта будут
--    фармить один и тот же condition_id одновременно, reward_usd/fees_usd задвоятся
--    между их позициями (на момент миграции пересечений аккаунтов по condition_id нет).

BEGIN;

CREATE OR REPLACE VIEW v_position_lifecycle AS
WITH trades AS (
    SELECT
        account,
        condition_id,
        asset,
        max(title) AS title,
        min(event_ts) FILTER (WHERE side = 'BUY')  AS first_buy_ts,
        max(event_ts) FILTER (WHERE side = 'SELL') AS last_sell_ts,
        sum(size)      FILTER (WHERE side = 'BUY')  AS buy_size,
        sum(usdc_size) FILTER (WHERE side = 'BUY')  AS buy_usdc,
        sum(size)      FILTER (WHERE side = 'SELL') AS sell_size,
        sum(usdc_size) FILTER (WHERE side = 'SELL') AS sell_usdc
    FROM account_activity
    WHERE event_type = 'TRADE'
      AND condition_id != ''
      AND asset IS NOT NULL AND asset != ''
    GROUP BY account, condition_id, asset
),
redeems AS (
    SELECT
        account,
        condition_id,
        max(event_ts)  AS redeem_ts,
        sum(usdc_size) AS redeem_usdc
    FROM account_activity
    WHERE event_type = 'REDEEM' AND condition_id != ''
    GROUP BY account, condition_id
),
farming AS (
    SELECT
        condition_id,
        sum(reward_usd) AS reward_usd,
        sum(fees_usd)   AS fees_usd
    FROM farming_daily_snapshot
    GROUP BY condition_id
),
latest_snapshot AS (
    SELECT DISTINCT ON (account, condition_id, asset)
        account, condition_id, asset,
        snap_date AS last_snap_date,
        size      AS current_size,
        current_value, cash_pnl, realized_pnl, redeemable
    FROM account_positions_snapshot
    ORDER BY account, condition_id, asset, snap_date DESC
)
SELECT
    t.account,
    t.condition_id,
    t.asset,
    t.title,
    t.first_buy_ts,
    COALESCE(r.redeem_ts, t.last_sell_ts) AS exit_ts,
    CASE
        WHEN r.redeem_ts IS NOT NULL THEN 'REDEEMED'
        WHEN COALESCE(ls.current_size, 0) = 0 AND COALESCE(t.sell_size, 0) > 0 THEN 'CLOSED_SOLD'
        ELSE 'OPEN'
    END AS status,
    ROUND(
        EXTRACT(EPOCH FROM (COALESCE(r.redeem_ts, t.last_sell_ts, now()) - t.first_buy_ts)) / 86400.0
    , 2) AS days_held,
    ROUND(t.buy_usdc  / NULLIF(t.buy_size, 0),  4) AS avg_buy_price,
    ROUND(t.sell_usdc / NULLIF(t.sell_size, 0), 4) AS avg_sell_price,
    t.buy_size, t.buy_usdc,
    t.sell_size, t.sell_usdc,
    r.redeem_usdc,
    f.reward_usd,
    f.fees_usd,
    (COALESCE(t.sell_usdc, 0) + COALESCE(r.redeem_usdc, 0) - COALESCE(t.buy_usdc, 0)) AS trading_pnl_usd,
    (COALESCE(t.sell_usdc, 0) + COALESCE(r.redeem_usdc, 0) - COALESCE(t.buy_usdc, 0)
        + COALESCE(f.reward_usd, 0) - COALESCE(f.fees_usd, 0)) AS net_usd,
    ls.current_size, ls.current_value, ls.cash_pnl, ls.realized_pnl, ls.redeemable, ls.last_snap_date
FROM trades t
LEFT JOIN redeems r          ON r.account = t.account AND r.condition_id = t.condition_id
LEFT JOIN farming f          ON f.condition_id = t.condition_id
LEFT JOIN latest_snapshot ls ON ls.account = t.account AND ls.condition_id = t.condition_id AND ls.asset = t.asset;

COMMENT ON VIEW v_position_lifecycle IS 'ACT-005: жизненный цикл позиции (вход/выход, avg-цены, reward/fees из farming_daily_snapshot, net, статус) для Grafana-дашборда Position Lifecycle.';

COMMIT;
