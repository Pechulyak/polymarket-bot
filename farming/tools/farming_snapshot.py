#!/usr/bin/env python3
"""
Farming Daily Snapshot Tool

Collects daily snapshot of farming positions into farming_daily_snapshot table.
Intended for cron execution (12:30 UTC daily) on S2.

Usage:
    python farming_snapshot.py [YYYY-MM-DD]

    Date argument defaults to yesterday (UTC) if not provided.

Data sources per market:
    - reward_usd: c.get_earnings_for_user_for_day(date) API (dict by condition_id)
    - inv: On-chain ERC-1155 balanceOf(funder, token) via Polygon RPC
    - mid: CLOB c.get_midpoint(token)
    - capital_usd: inv * mid + notional of open BID orders
    - fees_usd: Sum of taker-fees from trades (TRD-448 formula if not in API)
    - legs_state/hours_both/legs_state_log: Reconstructed from fills + open orders + halted state

Idempotent: UPSERT by (snap_date, token).
Read-only: only INSERT/UPDATE into farming_daily_snapshot.

Dependencies (S2):
    - /opt/executor/app/accounts/account2.env (PRIVATE_KEY)
    - /opt/executor/app/farming_state.json
    - DATABASE_URL env or CREDENTIALS_DIRECTORY/database_url
    - PostgreSQL with farming_daily_snapshot table
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import psycopg2
import requests
from py_clob_client_v2 import ClobClient
from py_clob_client_v2.clob_types import TradeParams
from web3 import Web3

# ─── Configuration ─────────────────────────────────────────────────────────────
# Same as farming_daemon.py - immutable constants
ENV_PATH = "/opt/executor/app/accounts/account2.env"
FUNDER = "0x5F032FF0e9376538ac240417EA5863756e1f2634"
SIG_TYPE = 3  # POLY_1271
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

# Polygon RPC endpoints for on-chain reads
RPC_URLS = [
    "https://polygon.drpc.org",
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
]
RPC_HEADERS = {"User-Agent": "Mozilla/5.0"}

# ERC-1155 CTF contract for inventory reads
CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
SHARE_DECIMALS = 6

# Farming state file (on S2)
FARMING_STATE_FILE = "/opt/executor/app/farming_state.json"

# ─── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    """Log to stdout with timestamp."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def parse_date(date_str: Optional[str]) -> datetime:
    """Parse date string as UTC date, default to yesterday."""
    if date_str is None:
        return datetime.now(timezone.utc) - timedelta(days=1)
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _load_signer_key() -> str:
    """Read PRIVATE_KEY from env-file. Same pattern as farming_daemon.py."""
    if not os.path.exists(ENV_PATH):
        raise FileNotFoundError(f"env file not found at {ENV_PATH}")
    key = None
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("PRIVATE_KEY="):
                key = line.split("=", 1)[1].strip().strip(chr(34)).strip(chr(39))
                break
    if not key:
        raise ValueError(f"PRIVATE_KEY not found in {ENV_PATH}")
    return key


def build_client():
    """Build CLOB client with L2 auth. Same pattern as farming_daemon.py build_client()."""
    key = _load_signer_key()
    c = ClobClient(HOST, CHAIN_ID, key, signature_type=SIG_TYPE, funder=FUNDER)
    del key
    api_key = c.create_or_derive_api_key()
    c.set_api_creds(api_key)
    return c


def get_db_connection():
    """Create DB connection using S2 credentials pattern (same as live_executor_daemon.py)."""
    cred_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if cred_dir and os.path.exists(os.path.join(cred_dir, "database_url")):
        with open(os.path.join(cred_dir, "database_url")) as f:
            return psycopg2.connect(f.read().strip())
    
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)
    
    raise RuntimeError("No database credentials found (CREDENTIALS_DIRECTORY or DATABASE_URL)")


# ─── CLOB Read Functions ───────────────────────────────────────────────────────

def get_midpoint(c: ClobClient, token: str) -> Optional[float]:
    """Get current midpoint price for a token from CLOB."""
    try:
        data = c.get_midpoint(token)
        return float(data["mid"])
    except Exception as e:
        log(f"[WARN] get_midpoint({token[:20]}) failed: {e}")
        return None


def get_open_orders_for_token(c: ClobClient, token: str) -> list:
    """Get open orders for a specific token. Same pattern as farming_daemon.py."""
    try:
        all_orders = c.get_open_orders() or []
        return [o for o in all_orders if o.get("asset_id") == token]
    except Exception as e:
        log(f"[WARN] get_open_orders({token[:20]}) failed: {e}")
        return []


def get_trades_for_condition(
    c: ClobClient,
    condition_id: str,
    start_ts: int,
    end_ts: int
) -> list:
    """Get trades for a condition within a time range with strict time filtering.
    
    Returns list of trade dicts filtered to start_ts <= int(ts) <= end_ts.
    Trades without parsable timestamp are excluded.
    """
    try:
        params = TradeParams(market=condition_id, maker_address=FUNDER, after=start_ts)
        all_trades = c.get_trades(params) or []
    except Exception as e:
        log(f"[WARN] get_trades({condition_id[:20]}) failed: {e}")
        return []
    
    filtered = []
    for t in all_trades:
        ts = t.get("match_time") or t.get("timestamp") or t.get("created_at")
        if ts is None:
            trade_id = t.get("id") or t.get("trade_id") or "unknown"
            log(f"[WARN] trade without parsable ts skipped: {trade_id}")
            continue
        try:
            ts_int = int(ts)
            if start_ts <= ts_int <= end_ts:
                filtered.append(t)
        except (TypeError, ValueError):
            trade_id = t.get("id") or t.get("trade_id") or "unknown"
            log(f"[WARN] trade without parsable ts skipped: {trade_id}")
    
    return filtered


def get_earnings_map(c: ClobClient, date_str: str) -> dict:
    """Get all earnings for user on a specific date.
    
    Calls c.get_earnings_for_user_for_day(date_str) once and builds
    a dict {condition_id: earnings} for efficient lookup.
    """
    try:
        earnings_list = c.get_earnings_for_user_for_day(date_str) or []
        result = {}
        for item in earnings_list:
            cid = item.get("condition_id")
            earn = float(item.get("earnings", 0))
            if cid:
                result[cid] = earn
        return result
    except Exception as e:
        log(f"[WARN] get_earnings_for_user_for_day({date_str}) failed: {e}")
        return {}


# ─── On-chain Read Functions ──────────────────────────────────────────────────

def read_erc1155_balance(token: str) -> Optional[float]:
    """Read ERC-1155 conditional token balance for funder via on-chain call."""
    token_int = int(token)
    selector = bytes.fromhex("00fdd58e")
    
    for rpc_url in RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"headers": RPC_HEADERS}))
            padded_addr = w3.to_bytes(hexstr=FUNDER).rjust(32, b"\x00")
            padded_id = token_int.to_bytes(32, "big")
            calldata = selector + padded_addr + padded_id
            result = w3.eth.call({"to": CTF_CONTRACT, "data": "0x" + calldata.hex()})
            raw = int.from_bytes(result, "big")
            return raw / (10 ** SHARE_DECIMALS)
        except Exception:
            continue
    
    log(f"[WARN] read_erc1155_balance({token[:20]}) all RPCs failed")
    return None


# ─── Fee Calculation ───────────────────────────────────────────────────────────

def calc_taker_fee(price: float, size: float) -> float:
    """Calculate taker fee using TRD-448 formula.
    
    Formula: 0.03 * max(price, 1 - price) * (price * size)
    where price * size is the notional value.
    """
    notional = price * size
    fee_factor = max(price, 1 - price)
    return 0.03 * fee_factor * notional


# ─── State Reconstruction ──────────────────────────────────────────────────────

def load_farming_state() -> dict:
    """Load farming state from JSON file (halted status, etc)."""
    try:
        with open(FARMING_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def reconstruct_legs_state(
    token: str,
    state: dict,
    trades: list,
    open_orders: list
) -> tuple:
    """Reconstruct legs_state, hours_both, and legs_state_log.
    
    Returns: (legs_state, hours_both, legs_state_log)
    
    legs_state values:
        - 'both': both legs present (bids and asks, or both sides traded)
        - 'halted': market is halted in farming_state.json
        - 'none': no legs present
        - 'bid_only': only BID leg present
        - 'ask_only': only ASK leg present
    
    hours_both:
        - 24.0 if both legs present at snapshot time AND no trades for the day
        - NULL otherwise
    
    legs_state_log: JSON log with approx flag when determined from trade fills
    """
    log_entries = []
    is_approx = False
    
    # Check halted status from state file
    token_state = state.get(token, {})
    if token_state.get("halted"):
        log_entries.append({
            "ts": None,
            "event": "halted",
            "state": "halted"
        })
        return "halted", None, json.dumps({"events": log_entries})
    
    # Analyze open orders
    bids = [o for o in open_orders if o.get("side") == "BUY"]
    asks = [o for o in open_orders if o.get("side") == "SELL"]
    
    # Analyze trades to determine if legs were filled
    has_bid_fill = any(t.get("side") == "BUY" for t in trades)
    has_ask_fill = any(t.get("side") == "SELL" for t in trades)
    
    # Determine legs_state
    has_bid = bool(bids) or has_bid_fill
    has_ask = bool(asks) or has_ask_fill
    
    # approx flag: if determined from trade fills (has_bid_fill/has_ask_fill)
    if has_bid_fill or has_ask_fill:
        is_approx = True
    
    if has_bid and has_ask:
        legs_state = "both"
    elif has_bid:
        legs_state = "bid_only"
    elif has_ask:
        legs_state = "ask_only"
    else:
        legs_state = "none"
    
    # hours_both logic (M3)
    hours_both = None
    if bids and asks and not trades:
        # Both legs present at snapshot and no trades for the day
        hours_both = 24.0
        log_entries.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "hours_estimate",
            "hours": 24.0,
            "approx": True
        })
        is_approx = True
    
    log_entries.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "snapshot",
        "legs_state": legs_state,
        "bids": len(bids),
        "asks": len(asks),
        "trades": len(trades)
    })
    
    result = {
        "approx": is_approx,
        "events": log_entries
    }
    
    return legs_state, hours_both, json.dumps(result)


# ─── Fee Processing ─────────────────────────────────────────────────────────────

def process_trade_fee(t: dict, log_entries: list) -> float:
    """Process fee for a single trade, considering taker role.
    
    Returns fee amount. Adds events to log_entries when role is undeterminable.
    """
    price = float(t.get("price", 0))
    size = float(t.get("size", 0))
    
    # If fee field present in trade - use it
    fee = t.get("fee") or t.get("commission")
    if fee is not None:
        return float(fee)
    
    # Determine if we're taker
    trader_side = t.get("trader_side")
    maker_addr = t.get("maker_address") or ""
    taker_addr = t.get("taker_address") or ""
    
    # is_taker confirmed if: trader_side=="TAKER" or taker_addr matches FUNDER
    is_taker = (
        (trader_side == "TAKER") or
        (taker_addr != "" and taker_addr.lower() == FUNDER.lower())
    )
    
    if is_taker:
        # Confirmed taker without explicit fee → apply formula
        return calc_taker_fee(price, size)
    
    # We're not taker: no fee unless role was completely undeterminable
    # Role undeterminable only if: no trader_side AND no taker_addr
    if trader_side is None and taker_addr == "":
        trade_id = t.get("id") or t.get("trade_id") or "unknown"
        log_entries.append({
            "event": "fee_undetermined",
            "trade_id": trade_id,
            "approx": True
        })
    
    return 0.0


# ─── Main Snapshot Logic ────────────────────────────────────────────────────────

DB_QUERY = """
    SELECT token_id, condition_id, gamma_id, name
    FROM farming_active_markets
    WHERE status = 'active'
"""

DB_QUERY_TOKEN_BY_CONDITION = """
    SELECT token_id FROM farming_active_markets WHERE condition_id = %s
"""


def collect_snapshot(date_str: str) -> list:
    """Collect snapshot data for all active markets on given date."""
    date = parse_date(date_str)
    start_dt = date.replace(hour=0, minute=0, second=0)
    end_dt = date.replace(hour=23, minute=59, second=59)
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    
    log(f"Collecting snapshot for {date_str} (ts: {start_ts} - {end_ts})")
    
    # Load farming state
    state = load_farming_state()
    
    # Build CLOB client
    c = build_client()
    
    # Connect to DB
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Fetch active markets
    cur.execute(DB_QUERY)
    markets = cur.fetchall()
    log(f"Found {len(markets)} active markets")
    
    # [C1] Get all earnings for the date ONCE
    earnings_map = get_earnings_map(c, date_str)
    log(f"Earnings map has {len(earnings_map)} entries")
    
    # Track markets to process (active + ones with earnings but not in active list)
    markets_to_process = set()
    for row in markets:
        token_id = row[0]
        markets_to_process.add(token_id)
    
    # Add markets that have earnings but not in active list
    for cid in earnings_map.keys():
        # Check if this condition_id is in our active markets
        found = False
        for row in markets:
            if row[1] == cid:  # row[1] is condition_id
                found = True
                break
        if not found:
            # Need to find token_id for this condition_id
            cur.execute(DB_QUERY_TOKEN_BY_CONDITION, (cid,))
            result = cur.fetchone()
            if result:
                markets_to_process.add(result[0])
            else:
                # No token found - use condition_id as token
                markets_to_process.add(cid)
    
    results = []
    
    for token_id in markets_to_process:
        # Find condition_id and gamma_id for this token
        condition_id = None
        gamma_id = None
        name = None
        is_not_in_active = False
        
        for row in markets:
            if row[0] == token_id:
                condition_id = row[1]
                gamma_id = row[2]
                name = row[3]
                break
        
        if condition_id is None:
            # This is a market from earnings but not in active list
            condition_id = token_id
            is_not_in_active = True
        
        log(f"Processing market: {name or condition_id[:20]}... ({condition_id[:20]}...)")
        
        # Get current mid price
        mid = get_midpoint(c, token_id)
        log(f"  mid: {mid}")
        
        # Get inventory (on-chain ERC-1155 balance)
        inv = read_erc1155_balance(token_id)
        log(f"  inv: {inv}")
        
        # Get open orders
        open_orders = get_open_orders_for_token(c, token_id)
        bid_notional = 0.0
        for o in open_orders:
            if o.get("side") == "BUY":
                try:
                    price = float(o.get("price", 0))
                    size = float(o.get("original_size", 0)) - float(o.get("size_matched", 0))
                    bid_notional += price * size
                except (TypeError, ValueError):
                    pass
        
        # Calculate capital_usd
        capital_usd = None
        if inv is not None and mid is not None:
            capital_usd = inv * mid + bid_notional
        
        # Get trades for the day
        trades = get_trades_for_condition(c, condition_id, start_ts, end_ts)
        
        # [S2] Calculate fees_usd - only taker trades
        fees_usd = 0.0
        legs_state_log_entries = []
        for t in trades:
            fee = process_trade_fee(t, legs_state_log_entries)
            fees_usd += fee
        
        # [C1] Get rewards from earnings map
        reward_usd = earnings_map.get(condition_id, 0.0)
        log(f"  reward_usd: {reward_usd}")
        
        # Reconstruct legs state
        legs_state, hours_both, legs_state_log = reconstruct_legs_state(
            token_id, state, trades, open_orders
        )
        
        # Add fee events to legs_state_log if any
        if legs_state_log_entries:
            legs_state_data = json.loads(legs_state_log)
            legs_state_data["events"].extend(legs_state_log_entries)
            legs_state_log = json.dumps(legs_state_data)
        
        # [C1] Handle markets not in active list
        if is_not_in_active:
            legs_state = "none"
            legs_state_data = json.loads(legs_state_log)
            legs_state_data["events"].append({
                "event": "not_in_active_markets",
                "approx": True
            })
            legs_state_log = json.dumps(legs_state_data)
        
        results.append({
            "snap_date": date_str,
            "token": token_id,
            "gamma_id": gamma_id,
            "condition_id": condition_id,
            "legs_state": legs_state,
            "hours_both": hours_both,
            "legs_state_log": legs_state_log,
            "inv": inv,
            "mid": mid,
            "capital_usd": capital_usd,
            "fees_usd": fees_usd,
            "reward_usd": reward_usd,
        })
        
        log(f"  legs_state={legs_state}, hours_both={hours_both}, "
            f"capital_usd={capital_usd}, fees_usd={fees_usd:.4f}")
    
    cur.close()
    conn.close()
    
    return results


def upsert_snapshot(data: list) -> None:
    """UPSERT snapshot data into farming_daily_snapshot.
    
    Uses ON CONFLICT (snap_date, token) DO UPDATE.
    """
    if not data:
        log("No data to upsert")
        return
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    sql = """
        INSERT INTO farming_daily_snapshot (
            snap_date, token, gamma_id, condition_id,
            legs_state, hours_both, legs_state_log,
            inv, mid, capital_usd, fees_usd, reward_usd
        ) VALUES (
            %(snap_date)s, %(token)s, %(gamma_id)s, %(condition_id)s,
            %(legs_state)s, %(hours_both)s, %(legs_state_log)s,
            %(inv)s, %(mid)s, %(capital_usd)s, %(fees_usd)s, %(reward_usd)s
        )
        ON CONFLICT (snap_date, token) DO UPDATE SET
            gamma_id = EXCLUDED.gamma_id,
            condition_id = EXCLUDED.condition_id,
            legs_state = EXCLUDED.legs_state,
            hours_both = EXCLUDED.hours_both,
            legs_state_log = EXCLUDED.legs_state_log,
            inv = EXCLUDED.inv,
            mid = EXCLUDED.mid,
            capital_usd = EXCLUDED.capital_usd,
            fees_usd = EXCLUDED.fees_usd,
            reward_usd = EXCLUDED.reward_usd
    """
    
    for row in data:
        cur.execute(sql, row)
        log(f"Upserted: {row['token'][:20]}... on {row['snap_date']}")
    
    conn.commit()
    cur.close()
    conn.close()
    
    log(f"Successfully upserted {len(data)} rows")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Collect daily farming snapshot into farming_daily_snapshot"
    )
    parser.add_argument(
        "date",
        nargs="?",
        help="Date in YYYY-MM-DD format (default: yesterday UTC)"
    )
    
    args = parser.parse_args()
    date_str = args.date
    
    if date_str is None:
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")
    
    # Validate date format
    try:
        parse_date(date_str)
    except ValueError:
        log(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")
        sys.exit(1)
    
    log(f"Starting farming snapshot for {date_str}")
    
    # Collect snapshot data
    data = collect_snapshot(date_str)
    
    # Upsert to database
    upsert_snapshot(data)
    
    log(f"Farming snapshot completed for {date_str}")


if __name__ == "__main__":
    main()
