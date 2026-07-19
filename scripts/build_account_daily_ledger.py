#!/usr/bin/env python3
"""
ACT-006: Full rebuild of account_daily_position_ledger.

Reads account_activity (TRADE events), reconstructs per-position running
balance / weighted avg cost (reset on each "epoch" — position fully closed
then reopened), aggregates to a sparse daily grain (row exists only if
buy/sell/reward != 0 that day), attaches farm reward/fees, mark price
(exchange snapshot > farm mid, else NULL), and status (closed-by-trade,
closed-by-resolution, won-unclaimed, or open). Truncates and reinserts the
whole table on every run — source is small and append-only, full rebuild
avoids incremental-state drift.

See docs/tasks/ACT-006.md for the full design writeup.
"""

import os
import sys
from collections import defaultdict
from datetime import date

import psycopg2
import psycopg2.extras

EPSILON = 0.05  # dust threshold; Polymarket minimum_order_size is ~5 shares,
# so residuals this small are float-accumulation dust from many fills, not
# a real open position (confirmed against live data - largest observed
# dust residual on a 98-trade position was 0.0015)
FEE_RATE = 0.03  # TRD-448 universal factor, confirmed non-category-dependent

DB_HOST = os.getenv("PGHOST", "localhost")
DB_PORT = os.getenv("PGPORT", "5433")
DB_NAME = os.getenv("PGDATABASE", "polymarket")
DB_USER = os.getenv("PGUSER", "postgres")
DB_PASS = os.getenv("PGPASSWORD", "")


def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )


def fee_for(price, notional):
    if price is None or notional is None:
        return None
    return FEE_RATE * max(price, 1 - price) * notional


def fetch_trades(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT account, condition_id, asset, event_ts, event_ts::date AS event_date,
                   side, size, usdc_size, price, title
            FROM account_activity
            WHERE event_type = 'TRADE' AND condition_id != ''
              AND asset IS NOT NULL AND asset != ''
            ORDER BY account, condition_id, asset, event_ts
            """
        )
        return cur.fetchall()


def fetch_redeem_events(conn):
    """(account, condition_id) -> list of {event_ts, event_date, size, usdc_size}.

    REDEEM rows carry no `asset` (settlement is at the condition level, see
    ACT-005 finding) - caller attaches each to whichever single asset that
    account traded under that condition_id. Also used as the (account,
    condition_id) -> "was ever redeemed" set for the WON_UNCLAIMED check.
    """
    out = defaultdict(list)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT account, condition_id, event_ts, event_ts::date AS event_date, size, usdc_size "
            "FROM account_activity WHERE event_type = 'REDEEM' AND condition_id != '' "
            "ORDER BY account, condition_id, event_ts"
        )
        for row in cur.fetchall():
            out[(row["account"], row["condition_id"])].append(row)
    return out


def fetch_farming_daily(conn):
    """condition_id -> {date: (reward_usd, fees_usd, mid)}"""
    out = defaultdict(dict)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT condition_id, snap_date, reward_usd, fees_usd, mid "
            "FROM farming_daily_snapshot WHERE condition_id IS NOT NULL"
        )
        for condition_id, snap_date, reward_usd, fees_usd, mid in cur.fetchall():
            out[condition_id][snap_date] = (
                float(reward_usd or 0),
                float(fees_usd or 0),
                float(mid) if mid is not None else None,
            )
    return out


def fetch_exchange_snapshots(conn):
    """(account, condition_id, asset) -> {date: cur_price}"""
    out = defaultdict(dict)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT account, condition_id, asset, snap_date, cur_price "
            "FROM account_positions_snapshot WHERE cur_price IS NOT NULL"
        )
        for account, condition_id, asset, snap_date, cur_price in cur.fetchall():
            out[(account, condition_id, asset)][snap_date] = float(cur_price)
    return out


def fetch_market_resolutions(conn):
    """condition_id -> (is_closed, winner_index, tokens)"""
    out = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT market_id, is_closed, winner_index, tokens FROM market_resolutions"
        )
        for market_id, is_closed, winner_index, tokens in cur.fetchall():
            out[market_id] = (is_closed, winner_index, tokens)
    return out


def process_position(trades, farming_by_condition, snapshots_by_key, redeems, resolutions):
    """trades: list of dicts for one (account, condition_id, asset), time-ordered."""
    account = trades[0]["account"]
    condition_id = trades[0]["condition_id"]
    asset = trades[0]["asset"]
    title = trades[0]["title"]

    balance = 0.0
    epoch_buy_usdc = 0.0
    epoch_buy_size = 0.0

    # per-day aggregation, in trade order
    daily = {}  # date -> dict

    def day_bucket(d):
        if d not in daily:
            daily[d] = {
                "buy_size": 0.0, "buy_usdc": 0.0,
                "sell_size": 0.0, "sell_usdc": 0.0,
                "buy_notional_for_fee": 0.0, "sell_notional_for_fee": 0.0,
                "buy_price_weighted_sum": 0.0, "sell_price_weighted_sum": 0.0,
            }
        return daily[d]

    # last-known state carried forward per shown day (closing balance / avg cost as of that day)
    day_end_state = {}  # date -> (closing_balance, avg_cost or None)

    for t in trades:
        d = t["event_date"]
        b = day_bucket(d)
        price = float(t["price"]) if t["price"] is not None else None
        size = float(t["size"])
        usdc = float(t["usdc_size"])

        if t["side"] == "BUY":
            if abs(balance) < EPSILON:
                epoch_buy_usdc = 0.0
                epoch_buy_size = 0.0
            epoch_buy_usdc += usdc
            epoch_buy_size += size
            balance += size
            b["buy_size"] += size
            b["buy_usdc"] += usdc
            if price is not None:
                b["buy_price_weighted_sum"] += price * size
        else:  # SELL
            balance -= size
            b["sell_size"] += size
            b["sell_usdc"] += usdc
            if price is not None:
                b["sell_price_weighted_sum"] += price * size

        avg_cost = (epoch_buy_usdc / epoch_buy_size) if epoch_buy_size > EPSILON else None
        day_end_state[d] = (balance, avg_cost)

    trade_days = sorted(daily.keys())
    first_day = trade_days[0]
    # Closed means the position's FINAL known balance (after the very last trade,
    # chronologically) is ~0 - not merely "touched 0 at some point in the past".
    # A position that closed and reopened and is still open must NOT be truncated
    # at that earlier, now-stale zero-crossing.
    final_balance = day_end_state[trade_days[-1]][0]
    closed_day = trade_days[-1] if abs(final_balance) < EPSILON else None

    # reward/fee days from farming_daily_snapshot within [first_day, last relevant day]
    farm_dates = farming_by_condition.get(condition_id, {})
    last_day_cap = closed_day if closed_day is not None else date.max
    reward_days = {
        d for d in farm_dates
        if d >= first_day and d <= last_day_cap
        and (farm_dates[d][0] != 0 or farm_dates[d][1] != 0)
    }

    all_days = sorted(set(trade_days) | reward_days)
    if closed_day is not None:
        all_days = [d for d in all_days if d <= closed_day]

    rows = []
    prev_closing_balance = 0.0
    prev_avg_cost = None
    last_seen_balance = 0.0
    last_seen_avg_cost = None

    for d in all_days:
        opening_balance = prev_closing_balance

        if d in day_end_state:
            closing_balance, avg_cost = day_end_state[d]
            last_seen_balance, last_seen_avg_cost = closing_balance, avg_cost
        else:
            closing_balance, avg_cost = last_seen_balance, last_seen_avg_cost

        b = daily.get(d, {
            "buy_size": 0.0, "buy_usdc": 0.0, "sell_size": 0.0, "sell_usdc": 0.0,
            "buy_price_weighted_sum": 0.0, "sell_price_weighted_sum": 0.0,
        })

        reward_usd, fees_usd = None, None
        if d in farm_dates:
            reward_usd, fees_usd, _ = farm_dates[d]

        # skip row if genuinely nothing happened (sparse-grain rule)
        if b["buy_size"] == 0 and b["sell_size"] == 0 and not reward_usd:
            continue

        is_open = abs(closing_balance) >= EPSILON

        mark_price, mark_source = None, None
        if is_open:
            snap = snapshots_by_key.get((account, condition_id, asset), {}).get(d)
            if snap is not None:
                mark_price, mark_source = snap, "exchange_snapshot"
            elif d in farm_dates and farm_dates[d][2] is not None:
                mark_price, mark_source = farm_dates[d][2], "farm_mid"

        buy_fee = sell_fee = None
        fee_source = None
        if b["buy_size"] > 0:
            avg_buy_price = b["buy_price_weighted_sum"] / b["buy_size"] if b["buy_size"] else None
            buy_fee = fee_for(avg_buy_price, b["buy_usdc"])
            fee_source = "estimated_universal_rate"
        if b["sell_size"] > 0:
            avg_sell_price = b["sell_price_weighted_sum"] / b["sell_size"] if b["sell_size"] else None
            sell_fee = fee_for(avg_sell_price, b["sell_usdc"])
            fee_source = "estimated_universal_rate"

        status = "OPEN"
        if not is_open:
            status = "CLOSED_TRADED"
        elif d == all_days[-1]:
            is_closed, winner_index, tokens = resolutions.get(condition_id, (None, None, None))
            if is_closed:
                won = False
                if tokens:
                    for tok in tokens:
                        if tok.get("token_id") == asset and tok.get("winner"):
                            won = True
                if won:
                    status = "WON_UNCLAIMED" if (account, condition_id) not in redeems else "CLOSED_RESOLVED_WIN"
                else:
                    status = "CLOSED_RESOLVED_LOSS"
                    mark_price, mark_source = 0.0, "resolved_loss"

        rows.append({
            "account": account, "condition_id": condition_id, "asset": asset,
            "activity_date": d, "title": title,
            "buy_size": b["buy_size"], "buy_usdc": b["buy_usdc"],
            "sell_size": b["sell_size"], "sell_usdc": b["sell_usdc"],
            "avg_cost": avg_cost,
            "opening_balance": opening_balance, "closing_balance": closing_balance,
            "mark_price": mark_price, "mark_source": mark_source,
            "buy_fee": buy_fee, "sell_fee": sell_fee, "fee_source": fee_source,
            "reward_usd": reward_usd, "fees_usd": fees_usd,
            "status": status,
        })
        prev_closing_balance = closing_balance

    return rows


def build(conn):
    trades = fetch_trades(conn)
    farming_by_condition = fetch_farming_daily(conn)
    snapshots_by_key = fetch_exchange_snapshots(conn)
    redeem_events = fetch_redeem_events(conn)
    resolutions = fetch_market_resolutions(conn)
    redeems = set(redeem_events.keys())

    groups = defaultdict(list)
    for t in trades:
        groups[(t["account"], t["condition_id"], t["asset"])].append(t)

    # REDEEM rows carry no `asset` - attach each to the single asset that
    # account traded under that condition_id (settlement is condition-level).
    # If more than one asset was traded under the same condition_id by the
    # same account, attribution is ambiguous - skip and warn rather than guess.
    for (account, condition_id), events in redeem_events.items():
        matching_assets = [
            key for key in groups if key[0] == account and key[1] == condition_id
        ]
        if len(matching_assets) != 1:
            print(
                f"[WARN] REDEEM attribution ambiguous for {account}/{condition_id}: "
                f"{len(matching_assets)} candidate assets, skipping redeem inclusion",
                file=sys.stderr,
            )
            continue
        key = matching_assets[0]
        title = groups[key][0]["title"]
        for ev in events:
            groups[key].append({
                "account": account, "condition_id": condition_id, "asset": key[2],
                "event_ts": ev["event_ts"], "event_date": ev["event_date"],
                "side": "SELL", "size": float(ev["size"]), "usdc_size": float(ev["usdc_size"]),
                "price": None, "title": title,
            })
        groups[key].sort(key=lambda t: t["event_ts"])

    all_rows = []
    for key, group_trades in groups.items():
        all_rows.extend(
            process_position(group_trades, farming_by_condition, snapshots_by_key, redeems, resolutions)
        )
    return all_rows


def write_rows(conn, rows):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE account_daily_position_ledger")
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO account_daily_position_ledger (
                account, condition_id, asset, activity_date, title,
                buy_size, buy_usdc, sell_size, sell_usdc,
                avg_cost, opening_balance, closing_balance,
                mark_price, mark_source, buy_fee, sell_fee, fee_source,
                reward_usd, fees_usd, status
            ) VALUES %s
            """,
            [
                (
                    r["account"], r["condition_id"], r["asset"], r["activity_date"], r["title"],
                    r["buy_size"], r["buy_usdc"], r["sell_size"], r["sell_usdc"],
                    r["avg_cost"], r["opening_balance"], r["closing_balance"],
                    r["mark_price"], r["mark_source"], r["buy_fee"], r["sell_fee"], r["fee_source"],
                    r["reward_usd"], r["fees_usd"], r["status"],
                )
                for r in rows
            ],
        )
    conn.commit()


def main():
    dry_run = "--dry-run" in sys.argv
    conn = get_conn()
    try:
        rows = build(conn)
        print(f"built {len(rows)} rows", file=sys.stderr)
        if dry_run:
            filt = None
            for arg in sys.argv:
                if arg.startswith("--condition-id="):
                    filt = arg.split("=", 1)[1]
            for r in rows:
                if filt and r["condition_id"] != filt:
                    continue
                print(r)
        else:
            write_rows(conn, rows)
            print("wrote rows to account_daily_position_ledger", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
