#!/usr/bin/env python3
"""
Live Executor Daemon for Polymarket
"""
from py_clob_client_v2 import (
    ClobClient, OrderArgsV2, MarketOrderArgsV2, OrderType,
    SignatureTypeV2, PartialCreateOrderOptions,
)
from py_clob_client_v2.order_builder.constants import BUY, SELL
from py_clob_client_v2.constants import POLYGON
import psycopg2, requests, os, sys, time, re
from datetime import datetime, timezone
from web3 import Web3
from psycopg2.extras import Json

# CONFIGURATION (hardcoded, no arguments)
KEY_PATH = "/opt/executor/secrets/.signer_key"
FUNDER = "0x3fC83D2b40F9f243Cbcd51a53cFdd7E9A6D366a1"
SIG_TYPE = 3  # POLY_1271
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
_cred_dir = os.environ.get("CREDENTIALS_DIRECTORY")
if _cred_dir and os.path.exists(os.path.join(_cred_dir, "database_url")):
    with open(os.path.join(_cred_dir, "database_url")) as _f:
        DB_URL = _f.read().strip()
else:
    DB_URL = os.environ.get("DATABASE_URL")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
POLL_INTERVAL = 10  # seconds
FILL_POLL_INTERVAL = 30  # seconds
MAKER_TIMEOUT_MINUTES = 15
LOG_FILE = "/opt/executor/logs/live_executor.log"
PUSD_CONTRACT = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
PUSD_DECIMALS = 6
RPC_URLS = [
    "https://polygon.drpc.org",
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
]
RPC_HEADERS = {"User-Agent": "Mozilla/5.0"}
FIXED_ORDER_USD = 1.0  # STAGE: фикс $1 на этапе обкатки live, kelly/size_usd вернуть при росте банкролла (LIVE-005)


def log(msg):
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


_throttle_state: dict = {}  # key -> last_logged timestamp

def throttled_log(key: str, msg: str, notify_too: bool = False, seconds: int = 300):
    """Log (and optionally notify) at most once per `seconds` for the same key."""
    now = time.time()
    last = _throttle_state.get(key, 0)
    if now - last < seconds:
        return
    _throttle_state[key] = now
    log(msg)
    if notify_too:
        notify(msg)


def notify(msg):
    """File log is mandatory (via log()); Telegram is best-effort on top."""
    log(msg)
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        log(f"Telegram error: {e}")


def mask_db_url(url):
    """Mask password in database URL for logging"""
    if not url:
        return "None"
    return re.sub(r'(://[^:]+:)[^@]+(@)', r'\1****\2', url)


def get_onchain_pusd_balance():
    """Read pUSD balance from on-chain ERC-20 contract via eth_call.
    
    Returns float balance in USD (human-readable), or raises Exception on RPC failure.
    Falls back through RPC_URLS list; fail-closed if all unresponsive.
    """
    last_error = None
    for rpc_url in RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"headers": RPC_HEADERS}))
            
            # ERC-20 balanceOf(address) function selector
            # keccak256("balanceOf(address)") = 0x70a08231
            owner_addr = FUNDER
            padded_addr = w3.to_bytes(hexstr=owner_addr).rjust(32, b'\x00')
            calldata = bytes.fromhex('70a08231') + padded_addr
            
            payload = {
                "to": PUSD_CONTRACT,
                "data": "0x" + calldata.hex(),
            }
            
            result = w3.eth.call(payload)
            raw_balance = int.from_bytes(result, 'big')
            
            balance_usd = raw_balance / (10 ** PUSD_DECIMALS)
            return balance_usd
        except Exception as e:
            last_error = e
            continue
    
    raise Exception(f"All RPCs failed, last error: {last_error}")


def build_client():
    with open(KEY_PATH, 'r') as f:
        key = f.read().strip()

    c = ClobClient(HOST, CHAIN_ID, key, signature_type=3, funder=FUNDER)

    api_key = c.derive_api_key()
    c.set_api_creds(api_key)

    del key

    return c


def get_db_conn():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn


def set_status(conn, live_order_id, status, error=None, extra_sql="", extra_params=()):
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE live_orders
        SET status=%s, error=%s{extra_sql}, updated_at=now()
        WHERE id=%s
        """,
        (status, error, *extra_params, live_order_id),
    )
    conn.commit()
    cur.close()


def claim_intent(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, token_id, condition_id, outcome, side, size_usd, idempotency_key
        FROM live_orders
        WHERE status='intent'
        ORDER BY created_at
        LIMIT 1
    """)
    row = cur.fetchone()
    if row is None:
        cur.close()
        return None

    order_id = row[0]
    cur.execute("""
        UPDATE live_orders
        SET status='claimed', claimed_at=now(), updated_at=now()
        WHERE id=%s AND status='intent'
        RETURNING id
    """, (order_id,))
    result = cur.fetchone()
    if result is None:
        conn.commit()
        cur.close()
        return None

    conn.commit()
    cur.close()

    return {
        'id': row[0],
        'token_id': row[1],
        'condition_id': row[2],
        'outcome': row[3],
        'side': row[4],
        'size_usd': float(row[5]),  # psycopg2 returns Decimal
        'idempotency_key': row[6],
    }


def monitor_order(c, conn, order_id, live_order_id, submitted_at):
    while True:
        try:
            order = c.get_order(order_id)
            if order is None:
                # not yet indexed; keep waiting (respecting timeout below)
                elapsed = time.time() - submitted_at
                if elapsed > MAKER_TIMEOUT_MINUTES * 60:
                    return False
                time.sleep(FILL_POLL_INTERVAL)
                continue

            status = str(order.get('status', '')).lower()

            if status == 'matched':
                # TODO INFRA-048: filled_size для maker не пишется — структура get_order
                # неизвестна (нет боевого maker-fill). Снять поля с реального ответа get_order,
                # затем дописать filled_size по образцу submit_taker (takingAmount).
                set_status(conn, live_order_id, 'filled')
                notify(f"✅ LIVE ORDER FILLED (maker) order_id={order_id}")
                return True

            elapsed = time.time() - submitted_at
            if elapsed > MAKER_TIMEOUT_MINUTES * 60:
                return False

            time.sleep(FILL_POLL_INTERVAL)
        except Exception as e:
            throttled_log(f"monitor_error:{str(e)[:80]}", f"Monitor order error: {e}", notify_too=False, seconds=60)
            elapsed = time.time() - submitted_at
            if elapsed > MAKER_TIMEOUT_MINUTES * 60:
                return False
            time.sleep(FILL_POLL_INTERVAL)


def submit_taker(c, conn, live_order_id, token_id, size_usd, neg_risk, tag="taker"):
    """Market BUY via FOK. SDK computes size from dollar amount (correct rounding)."""
    try:
        tick = c.get_tick_size(token_id)
        args = MarketOrderArgsV2(token_id=token_id, amount=size_usd, side=BUY)
        opts = PartialCreateOrderOptions(tick_size=tick, neg_risk=neg_risk)
        signed = c.create_market_order(args, opts)
        resp = c.post_order(signed, order_type=OrderType.FOK)
        log(f"TAKER POST_ORDER resp={resp}")

        clob_order_id = resp.get('orderID') or resp.get('id')
        status = str(resp.get('status', '')).lower()

        if resp.get('success') and status == 'matched':
            taking = resp.get('takingAmount')
            filled_size = float(taking) if taking not in (None, '') else None
            set_status(conn, live_order_id, 'filled', error=None,
                       extra_sql=", clob_order_id=%s, route=%s, filled_size=%s",
                       extra_params=(clob_order_id, tag, filled_size))
            notify(f"✅ LIVE ORDER FILLED ({tag}) order_id={clob_order_id}")
            return True
        else:
            err = resp.get('errorMsg') or 'fok_not_matched'
            set_status(conn, live_order_id, 'failed', error=str(err)[:500],
                       extra_sql=", clob_order_id=%s", extra_params=(clob_order_id,))
            notify(f"❌ LIVE ORDER FAILED ({tag}): {err}")
            return False
    except Exception as e:
        log(f"Taker submit error: {e}")
        try:
            set_status(conn, live_order_id, 'failed', error=str(e)[:500])
        except Exception:
            pass
        return False


def main():
    if '--diag' in sys.argv:
        log(f"DB_URL: {mask_db_url(DB_URL)}")

        try:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM live_orders ORDER BY created_at DESC LIMIT 5")
            rows = cur.fetchall()
            for r in rows:
                log(f"  {r}")
            cur.close()
            conn.close()
        except Exception as e:
            log(f"DB diag error: {e}")

        try:
            c = build_client()
            addr = c.get_address()
            log(f"Client address: {addr}")
            log(f"FUNDER: {FUNDER}")
            notify("DIAG OK")
            sys.exit(0)
        except Exception as e:
            log(f"Client diag error: {e}")
            sys.exit(1)

    log(f"Starting live executor daemon, DB_URL={mask_db_url(DB_URL)}")
    c = build_client()
    log(f"Client ready, address={c.get_address()}")

    while True:
        conn = None
        try:
            conn = get_db_conn()

            # Heartbeat UPSERT
            try:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO system_state (component, heartbeat_at, detail)
                    VALUES ('live_executor', now(), %s)
                    ON CONFLICT (component) DO UPDATE
                    SET heartbeat_at = EXCLUDED.heartbeat_at,
                        detail = EXCLUDED.detail,
                        updated_at = now()
                """, (Json({'pid': os.getpid()}),))
                conn.commit()
                cur.close()
            except Exception as e:
                log(f"Heartbeat error: {e}")

            row = claim_intent(conn)
            if row is None:
                conn.close()
                time.sleep(POLL_INTERVAL)
                continue

            log(f"CLAIMED id={row['id']} market={row['condition_id']} "
                f"outcome={row['outcome']} side={row['side']} size={row['size_usd']}")

            token_id = row['token_id']
            # STAGE: фикс $1 — size_usd из БД не используется ни для суммы ордера, ни для routing
            # size_usd = row['size_usd']
            log(f"DEBUG token_id={token_id[:20]}...")

            try:
                book = c.get_order_book(token_id)
                log(f"DEBUG book keys={list(book.keys()) if book else 'None'}")
            except Exception as book_err:
                import traceback
                throttled_log(f"book_error:{str(book_err)[:80]}", f"BOOK ERROR: {book_err}", notify_too=False, seconds=300)
                set_status(conn, row['id'], 'failed', error=str(book_err)[:500])
                conn.close()
                continue

            bids = book.get('bids') or []
            if not bids:
                set_status(conn, row['id'], 'failed', error='empty_orderbook')
                conn.close()
                continue

            best_bid = max(float(b['price']) for b in bids)
            asks = book.get('asks') or []
            best_ask = min(float(a['price']) for a in asks) if asks else None

            if best_ask is not None and best_bid >= best_ask:
                log(f"CROSSED BOOK: best_bid={best_bid} >= best_ask={best_ask}")
                set_status(conn, row['id'], 'failed', error='crossed_book')
                conn.close()
                continue

            # neg_risk from book, NOT hardcoded
            neg_risk = bool(book.get('neg_risk', False))
            min_order_size = float(book.get('min_order_size', 0) or 0)
            shares_maker = float(FIXED_ORDER_USD) / best_bid

            log(f"BOOK: best_bid={best_bid} best_ask={best_ask} "
                f"neg_risk={neg_risk} min_size={min_order_size} shares_maker={shares_maker:.4f}")

            # ROUTING: maker if shares meet the limit-order minimum, else straight to taker
            
            # BALANCE GATE — check balance before any order submission
            try:
                onchain_balance = get_onchain_pusd_balance()
            except Exception as balance_err:
                throttled_log(f"balance_rpc:{str(balance_err)[:80]}", f"BALANCE GATE FAIL (RPC): {balance_err}", notify_too=True, seconds=300)
                set_status(conn, row['id'], 'failed', error=f"balance_rpc_error: {balance_err}")
                conn.close()
                continue
            
            required_amount = FIXED_ORDER_USD + 0.05  # 1.05
            if onchain_balance < required_amount:
                log(f"BALANCE GATE FAIL: balance={onchain_balance:.4f} < required={required_amount:.2f}")
                set_status(conn, row['id'], 'failed',
                           error=f"insufficient balance: {onchain_balance:.4f} < required {required_amount:.2f}")
                conn.close()
                continue
            
            log(f"BALANCE GATE OK: balance={onchain_balance:.4f} >= {required_amount:.2f}")
            
            if shares_maker >= min_order_size:
                tick = c.get_tick_size(token_id)
                shares = round(shares_maker, 6)
                side = BUY if row['side'].upper() == 'BUY' else SELL
                log(f"MAKER ORDER best_bid={best_bid} shares={shares} tick={tick}")
                try:
                    args = OrderArgsV2(token_id=token_id, price=best_bid, size=shares, side=side)
                    opts = PartialCreateOrderOptions(tick_size=tick, neg_risk=neg_risk)
                    signed = c.create_order(args, opts)
                    resp = c.post_order(signed, order_type=OrderType.GTC)
                    log(f"MAKER POST_ORDER resp={resp}")
                except Exception as maker_err:
                    log(f"Maker submit error: {maker_err}")
                    set_status(conn, row['id'], 'failed', error=str(maker_err)[:500])
                    conn.close()
                    continue

                clob_order_id = resp.get('orderID') or resp.get('id') or str(resp)
                set_status(conn, row['id'], 'submitted', error=None,
                           extra_sql=", clob_order_id=%s, limit_price=%s",
                           extra_params=(clob_order_id, best_bid))

                submitted_at = time.time()
                filled = monitor_order(c, conn, clob_order_id, row['id'], submitted_at)

                if not filled:
                    log("TIMEOUT 15min, cancelling maker, switching to taker fallback")
                    try:
                        c.cancel_order(clob_order_id)
                    except Exception as e:
                        log(f"Cancel error: {e}")
                    submit_taker(c, conn, row['id'], token_id, FIXED_ORDER_USD, neg_risk, tag="taker_fallback")
            else:
                # below limit-order minimum: straight to taker, no 15-min wait
                log(f"shares_maker={shares_maker:.4f} < min_order_size={min_order_size}, "
                    f"going straight to taker")
                submit_taker(c, conn, row['id'], token_id, FIXED_ORDER_USD, neg_risk, tag="taker_direct")

            conn.close()

        except Exception as e:
            throttled_log(f"main_error:{str(e)[:80]}", f"ERROR: {e}", notify_too=False, seconds=300)
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            time.sleep(30)


if __name__ == "__main__":
    main()
