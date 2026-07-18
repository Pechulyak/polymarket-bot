#!/usr/bin/env python3
"""
copy_paper_to_live.py — LIVE-004 Daemon

Listens for pg_notify('live_copy', paper_trade_id) and copies paper_trades rows
to live_orders as intent records, ready for S2 live_executor_daemon to pick up.

Kill-switch: reads strategy_config.live_whale_copy on every trade (no caching).
If live_whale_copy != 1 — returns early, no intent created.

Modes:
  (no args)          — LISTEN mode (primary daemon)
  --sweep            — sweep mode (cron fallback, at-most-once gap-fill)

Channel:   live_copy
Heartbeat: live_copy_daemon (LISTEN mode), live_copy_sweep (sweep mode)
Sweep window: 6 hours (configurable SWEEP_WINDOW_HOURS)

Exit codes:
  0  — clean exit (sweep mode)
  1  — LISTEN mode error (reconnect and retry)
  2  — configuration/system error (non-recoverable)
"""

import argparse
import os
import select
import signal
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# =============================================================================
# Configuration
# =============================================================================

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5433/polymarket"
)

# Channel name (matches pg_notify in trigger_notify_paper_trade_to_live)
NOTIFY_CHANNEL = "live_copy"

# Heartbeat component names
HEARTBEAT_COMPONENT_LISTEN = "live_copy_daemon"
HEARTBEAT_COMPONENT_SWEEP = "live_copy_sweep"

# Heartbeat interval (seconds) — LISTEN mode only
HEARTBEAT_INTERVAL_SECONDS = 60

# Sweep window (hours) — look back this far for missed notifications
SWEEP_WINDOW_HOURS = 6

# Position dedup window (hours) — trades matching an already-covered position
# (whale+market+outcome+side+price) within this window are skipped. Bounded,
# not permanent: a genuinely fresh re-entry days later at the same price
# should still get a live order.
LIVE_ORDER_DEDUP_WINDOW_HOURS = 6

# Logging
LOGS_DIR = Path("/root/polymarket-bot/logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "copy_paper_to_live.log"


# =============================================================================
# Logging
# =============================================================================

def log(msg: str, level: str = "INFO") -> None:
    ts = datetime.utcnow().isoformat(timespec="seconds")
    line = f"{ts} [{level}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# =============================================================================
# Database helpers
# =============================================================================

def get_db_connection():
    """Create a new psycopg2 connection."""
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)


def upsert_heartbeat(conn, component: str) -> None:
    """UPSERT heartbeat row in system_state (single-row pattern, INFRA-045)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO system_state (component, heartbeat_at, updated_at)
            VALUES (%s, NOW(), NOW())
            ON CONFLICT (component) DO UPDATE
                SET heartbeat_at = EXCLUDED.heartbeat_at,
                    updated_at = EXCLUDED.updated_at
            """,
            (component,)
        )
    conn.commit()


def get_kill_switch(conn) -> bool:
    """Read live_whale_copy from strategy_config. Returns True if enabled."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value FROM strategy_config WHERE key = 'live_whale_copy'"
        )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        return False
    return float(row[0]) == 1.0


def get_paper_trade(conn, trade_id: int) -> dict | None:
    """Fetch a single paper_trades row by id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                pt.id,
                pt.whale_address,
                pt.market_id,
                pt.market_title,
                pt.outcome,
                pt.side,
                pt.kelly_size,
                pt.price,
                pt.tx_hash,
                pt.created_at,
                pt.token_id,
                w.copy_status
            FROM paper_trades pt
            JOIN whales w ON w.wallet_address = pt.whale_address
            WHERE pt.id = %s
            """,
            (trade_id,)
        )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        return None
    return {
        "id": row[0],
        "whale_address": row[1],
        "market_id": row[2],
        "market_title": row[3],
        "outcome": row[4],
        "side": row[5],
        "kelly_size": row[6],
        "price": row[7],
        "tx_hash": row[8],
        "created_at": row[9],
        "token_id": row[10],
        "copy_status": row[11],
    }


def has_live_intent_for_position(conn, trade: dict) -> bool:
    """
    Check whether another paper_trades row for the same position
    (whale_address, market_id, outcome, side, price), within the dedup
    window, already has a non-failed live_orders intent.

    paper_trades intentionally keeps every individual whale trade — a whale
    building one position via many small trades produces many paper_trades
    rows. Without this check, each row would get its own live order.
    'failed'/'rejected' intents don't count: a failed attempt shouldn't
    permanently block retrying the same signal.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM paper_trades pt2
                JOIN live_orders lo ON lo.idempotency_key = ('pt_' || pt2.id)
                WHERE pt2.whale_address = %(whale_address)s
                  AND pt2.market_id = %(market_id)s
                  AND pt2.outcome = %(outcome)s
                  AND pt2.side = %(side)s
                  AND pt2.price = %(price)s
                  AND pt2.id != %(trade_id)s
                  AND pt2.created_at BETWEEN %(created_at)s - (%(window_hours)s || ' hours')::interval
                                          AND %(created_at)s + (%(window_hours)s || ' hours')::interval
                  AND lo.status NOT IN ('failed', 'rejected')
            )
            """,
            {
                "whale_address": trade["whale_address"],
                "market_id": trade["market_id"],
                "outcome": trade["outcome"],
                "side": trade["side"],
                "price": trade["price"],
                "trade_id": trade["id"],
                "created_at": trade["created_at"],
                "window_hours": LIVE_ORDER_DEDUP_WINDOW_HOURS,
            }
        )
        (exists,) = cur.fetchone()
    conn.commit()
    return bool(exists)


def insert_live_order(conn, trade: dict, token_id: str) -> bool:
    """
    INSERT a row into live_orders with status='intent'.

    idemponent_key = 'pt_' || paper_trade_id
    ON CONFLICT (idempotency_key) DO NOTHING — safe for retries/sweep duplicates.

    Returns True if inserted, False if skipped/conflicted.
    """
    side_upper = trade["side"].upper()  # paper_trades uses lowercase; live_orders requires BUY/SELL
    idempotency_key = f"pt_{trade['id']}"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO live_orders (
                token_id,
                condition_id,
                market_title,
                outcome,
                side,
                size_usd,
                idempotency_key,
                status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'intent')
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                token_id,
                trade["market_id"],
                trade.get("market_title"),
                trade["outcome"],
                side_upper,
                trade["kelly_size"],
                idempotency_key,
            )
        )
        inserted = cur.rowcount > 0
    conn.commit()
    return inserted


# =============================================================================
# process_one — core logic for a single paper_trade row
# =============================================================================

def process_one(conn, trade_id: int) -> None:
    """
    Process a single paper_trades row: kill-switch gate → whale gate → resolve → insert.

    On any error (network, parse, DB) — logs raw info and returns.
    Does NOT raise; does NOT create partial intents.
    """
    # Gate 1: kill-switch (fresh read, no caching)
    if not get_kill_switch(conn):
        log(f"trade_id={trade_id}: kill-switch off, skipped")
        return

    # Fetch row with whale copy_status
    trade = get_paper_trade(conn, trade_id)
    if trade is None:
        log(f"trade_id={trade_id}: row not found in paper_trades", "WARN")
        return

    # Gate 2: whale must be live (safety belt against paper whales and race conditions)
    if trade["copy_status"] != "live":
        log(f"trade_id={trade_id}: whale {trade['whale_address']} copy_status={trade['copy_status']}, expected live — skipped")
        return

    # Gate 3: must have kelly_size > 0
    if not trade["kelly_size"] or float(trade["kelly_size"]) <= 0:
        log(f"trade_id={trade_id}: kelly_size={trade['kelly_size']} <= 0, skipped")
        return

    # Gate 4: token_id must be present (fail-closed for historical/categorical trades without asset)
    token_id = trade.get("token_id")
    if not token_id:
        log(f"trade_id={trade_id}: token_id is NULL/empty — intent NOT created (historical/categorical trade)", "ERROR")
        return

    # Gate 5: same position (whale+market+outcome+side+price) already has a
    # live intent within the dedup window — skip, one order per position
    if has_live_intent_for_position(conn, trade):
        log(f"trade_id={trade_id}: duplicate position (whale={trade['whale_address']}, "
            f"market={trade['market_id']}, outcome={trade['outcome']}, side={trade['side']}, "
            f"price={trade['price']}) already has a live intent — skipped")
        return

    # Insert intent into live_orders
    inserted = insert_live_order(conn, trade, token_id)
    if inserted:
        log(f"trade_id={trade_id}: intent created token_id={token_id}")
    else:
        log(f"trade_id={trade_id}: intent already exists (idempotency_key=pt_{trade_id})")


# =============================================================================
# LISTEN mode — primary daemon
# =============================================================================

def listen_mode() -> None:
    """
    Long-running daemon: LISTEN live_copy + heartbeat timer.
    Self-pipe pattern: os.pipe() + signal.set_wakeup_fd() for reliable signal handling.
    Shutdown is instantaneous regardless of select() blocking.
    """
    log("Starting LISTEN mode daemon")

    # Self-pipe for signal handling (instant wakeup from select)
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)  # non-blocking write end
    old_wakeup_fd = signal.set_wakeup_fd(write_fd)  # Python writes byte on any signal

    conn = get_db_connection()
    conn.autocommit = True  # autocommit for LISTEN (psycopg2 convention)

    # Register LISTEN
    with conn.cursor() as cur:
        cur.execute(f"LISTEN {NOTIFY_CHANNEL}")
    log(f"Listening on channel: {NOTIFY_CHANNEL}")

    # Graceful shutdown
    shutdown = False
    last_heartbeat = time.monotonic()

    def signal_handler(signum, frame):
        nonlocal shutdown
        log(f"Received signal {signum}, shutting down gracefully")
        shutdown = True

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    while not shutdown:
        try:
            # Wait for notifications OR shutdown signal
            ready, _, _ = select.select([conn, read_fd], [], [], HEARTBEAT_INTERVAL_SECONDS)

            # Shutdown signal received — exit immediately
            if shutdown:
                break

            # Drain the wakeup pipe if it has data
            if read_fd in ready:
                os.read(read_fd, 1024)  # discard buffered signal bytes

            # Heartbeat: write if enough time has passed (independent of select timeout)
            now = time.monotonic()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                try:
                    hb_conn = get_db_connection()
                    upsert_heartbeat(hb_conn, HEARTBEAT_COMPONENT_LISTEN)
                    hb_conn.close()
                    last_heartbeat = now
                except Exception as e:
                    log(f"Heartbeat update failed: {e}", "ERROR")

            # Notifications available — consume them
            conn.poll()
            while conn.notifies:
                notify = conn.notifies.pop(0)
                payload = notify.payload
                log(f"Received NOTIFY: channel={notify.channel}, pid={notify.pid}, payload={payload}")
                try:
                    trade_id = int(payload)
                except ValueError:
                    log(f"Invalid notify payload (not an int): {payload}", "WARN")
                    continue

                # Process in a fresh connection (LISTEN connection is in autocommit)
                try:
                    proc_conn = get_db_connection()
                    process_one(proc_conn, trade_id)
                    proc_conn.close()
                except Exception as e:
                    log(f"process_one({trade_id}) raised: {type(e).__name__}: {e}", "ERROR")

        except psycopg2.OperationalError as e:
            log(f"Connection error, reconnecting: {e}", "ERROR")
            time.sleep(5)
            try:
                conn = get_db_connection()
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(f"LISTEN {NOTIFY_CHANNEL}")
            except Exception as re:
                log(f"Reconnect failed: {re}", "CRITICAL")
                sys.exit(1)

    # Cleanup: restore wakeup fd, close pipe, close conn
    signal.set_wakeup_fd(old_wakeup_fd)
    os.close(read_fd)
    os.close(write_fd)
    conn.close()
    log("LISTEN mode daemon stopped")


# =============================================================================
# SWEEP mode — cron fallback
# =============================================================================

def sweep_mode() -> None:
    """
    Sweep: find paper_trades rows where whale is 'live' but no live_orders intent exists,
    for trades within the sweep window. Process each one via process_one().

    Idempotent: process_one uses ON CONFLICT DO NOTHING on idempotency_key.
    Designed to be safe to run overlapping with LISTEN daemon.
    """
    log(f"Starting SWEEP mode (window={SWEEP_WINDOW_HOURS}h)")

    try:
        conn = get_db_connection()
    except Exception as e:
        log(f"Database connection failed in sweep: {e}", "ERROR")
        sys.exit(1)

    # Kill-switch at top of sweep: exit early if disabled
    if not get_kill_switch(conn):
        log("Kill-switch off — sweep skipped")
        conn.close()
        sys.exit(0)

    # UPSERT sweep heartbeat
    try:
        upsert_heartbeat(conn, HEARTBEAT_COMPONENT_SWEEP)
    except Exception as e:
        log(f"Sweep heartbeat failed: {e}", "ERROR")

    cutoff = datetime.utcnow() - timedelta(hours=SWEEP_WINDOW_HOURS)

    # Find rows: live whale + has kelly_size + token_id + no existing intent
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pt.id
            FROM paper_trades pt
            JOIN whales w ON w.wallet_address = pt.whale_address
            LEFT JOIN live_orders lo
                ON lo.idempotency_key = ('pt_' || pt.id)
            WHERE w.copy_status = 'live'
              AND pt.kelly_size > 0
              AND pt.token_id IS NOT NULL
              AND pt.created_at >= %s
              AND lo.id IS NULL
            ORDER BY pt.created_at ASC
            """,
            (cutoff,)
        )
        rows = cur.fetchall()
    conn.commit()
    conn.close()

    log(f"Sweep found {len(rows)} candidate rows")

    if not rows:
        log("Sweep complete, no rows to process")
        sys.exit(0)

    proc_conn = get_db_connection()
    for (trade_id,) in rows:
        log(f"Sweep processing trade_id={trade_id}")
        try:
            process_one(proc_conn, trade_id)
        except Exception as e:
            log(f"process_one({trade_id}) in sweep raised: {type(e).__name__}: {e}", "ERROR")
    proc_conn.close()

    log("Sweep complete")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="copy_paper_to_live — LIVE-004 daemon")
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Run in sweep mode (one-shot, for cron)"
    )
    args = parser.parse_args()

    if args.sweep:
        sweep_mode()
    else:
        listen_mode()