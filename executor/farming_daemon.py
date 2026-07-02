#!/usr/bin/env python3
"""
Liquidity Reward Farming Daemon for Polymarket (Account 2 / Justfuuun).

SEMANTICS DIFFER FROM copy-daemon:
  - autonomous (generates its own two-sided quotes at midpoint; NOT reactive to whale intents)
  - fill = FAILURE (adverse selection), not success
  - timeout / order resting = NORMAL (order accrues reward while unfilled)
  - fallback on drift = re-quote (cancel+replace as maker), NEVER taker (would pay entry fee)

STATUS: SKELETON. All live order placement is stubbed (DRY_RUN default True).
Reused primitives from live_executor_daemon.py are marked [REUSE].
New farming logic is marked [NEW]. Money-adjacent config marked # TODO CONFIRM.
"""
from py_clob_client_v2 import (
    ClobClient, OrderArgsV2, OrderType, PartialCreateOrderOptions, OrderPayload,
)
from py_clob_client_v2.order_builder.constants import BUY, SELL
import requests, os, sys, time, re
from datetime import datetime, timezone
from web3 import Web3

# ─────────────────────────── CONFIGURATION ───────────────────────────
# [REUSE] client/auth pattern from copy-daemon, but Account 2 funder.
ENV_PATH = "/opt/executor/app/accounts/account2.env"  # PRIVATE_KEY=0x... (chmod 600) — confirmed working acc2 creds
FUNDER   = "0x5F032FF0e9376538ac240417EA5863756e1f2634"  # acc2 funder (Justfuuun), on-chain confirmed 2026-06
SIG_TYPE = 3  # POLY_1271
HOST     = "https://clob.polymarket.com"
CHAIN_ID = 137

# ── ON-CHAIN INVENTORY READ (SDK get_balance_allowance() returns 0 — DEAD; read chain) ──
# CTF = Polymarket Conditional Tokens (ERC-1155), shares live here keyed by token_id.
#   Confirmed via PolygonScan label "Polymarket: Conditional Tokens", ERC-1155.
# pUSD = ERC-20 collateral (cash leg). Both read by balanceOf on FUNDER.
CTF_CONTRACT  = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"   # ERC-1155 balanceOf(addr,id)
PUSD_CONTRACT = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"   # ERC-20  balanceOf(addr)
SHARE_DECIMALS = 6                                             # CTF shares & pUSD both 1e6
RPC_URLS = [
    "https://polygon.drpc.org",
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
]
RPC_HEADERS = {"User-Agent": "Mozilla/5.0"}

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
LOG_FILE = "/opt/executor/logs/farming_daemon.log"

# ─────────────────────────── FARMING PARAMS ──────────────────────────
DRY_RUN = False                      # LIVE: D3 prototype run (farming, acc2)
POLL_INTERVAL   = 10                 # seconds between ticks
QUOTE_OFFSET    = 0.015              # CONFIRMED 2026-07-01: 1.5c/leg start (opt blocked until D3 fill-freq)
REQUOTE_FRAC    = 0.6                # [NEW] re-quote when drift >= REQUOTE_FRAC * BE_move

# Target markets (from Step A/B recon). size = shares per leg.
# TODO CONFIRM: sizing, market selection, whether Fed#2 included alongside US x Iran.
MARKETS = [
    {
        "name":  "US x Iran meeting",
        "token": "95676548525614691656970153001244738030704823210041753577158504248850005676647",
        "min_size": 200,             # shares per leg
        # max_spread / reward_daily filled at runtime from get_market()
    },
    # {"name": "Fed Pause x3 #2", "token": "9517687...", "min_size": 50},
]


# ─────────────────────────── UTIL [REUSE] ────────────────────────────
def log(msg):
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def notify(msg):
    log(msg)
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        log(f"Telegram error: {e}")


_throttle_state = {}  # key -> last-logged monotonic ts

def throttled_log(key, msg, seconds=300):
    """Log at most once per `seconds` for the same key (in-memory).
    Used for high-frequency, low-signal lines (steady-state HOLD ticks,
    repeated identical errors). REQUOTE / fills / new errors bypass this and
    call log() directly. Never raises."""
    now = time.time()
    last = _throttle_state.get(key, 0)
    if now - last < seconds:
        return
    _throttle_state[key] = now
    log(msg)


def _load_signer_key() -> str:
    """Read PRIVATE_KEY from env-file. NEVER prints value."""
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
    """[REUSE] sig3/POLY_1271 init. Account 2 funder.
    DRY-only fallback: if DRY_RUN and the signer key is absent, return a
    read-only client (no L2 creds needed for get_order_book/get_market/
    get_midpoint/get_trades). Inventory is read ON-CHAIN (read_inventory),
    NOT via get_balance_allowance (dead SDK branch). Live path still REQUIRES
    the key — money-adjacent placement is unaffected."""
    if DRY_RUN and not os.path.exists(ENV_PATH):
        log(f"[DRY_RUN] env file absent ({ENV_PATH}) -> read-only client, no L2 creds")
        return ClobClient(HOST, CHAIN_ID)
    key = _load_signer_key()
    c = ClobClient(HOST, CHAIN_ID, key, signature_type=SIG_TYPE, funder=FUNDER)
    del key
    api_key = c.create_or_derive_api_key()
    c.set_api_creds(api_key)
    return c


# ─────────────────────── REWARD / MARKET READ [NEW] ──────────────────
def load_reward_params(c, mkt):
    """[NEW] Resolve condition_id from token book, read rewards + fee params.
    Returns dict augmenting mkt, or None on failure (caller skips market)."""
    token = mkt["token"]
    cid = c.get_order_book(token)["market"]
    m = c.get_market(cid)
    rw = m.get("rewards") or {}
    rates = rw.get("rates") or []
    reward_daily = float(rates[0]["rewards_daily_rate"]) if rates else 0.0
    return {
        "condition_id": cid,
        "reward_daily": reward_daily,
        "reward_min_size": rw.get("min_size"),
        "max_spread": float(rw.get("max_spread")) if rw.get("max_spread") is not None else None,
        "fee_bps": c.get_fee_rate_bps(token),
        "fee_exponent": c.get_fee_exponent(token),
        "neg_risk": m.get("neg_risk"),
        "tick_size": m.get("minimum_tick_size"),
    }


def compute_break_even(max_spread_cents, offset_dollars):
    """[NEW] CORRIDOR model (maker farming, fee=0 => fill has no cash loss;
    risk is managed by offset + cancel/replace, not a $-model).
    BE_margin_cents = how much extra drift the quote can absorb before the
    order leaves the reward corridor (where reward -> 0).
      spread_from_mid = offset_dollars * 100  (cents)
      BE_margin = max_spread_cents - spread_from_mid
    Returns dict: spread from mid, corridor margin, and whether offset fits.
    None-safe: returns None if max_spread unknown."""
    if max_spread_cents is None:
        return None
    spread_cents = float(offset_dollars) * 100.0
    margin = float(max_spread_cents) - spread_cents
    return {
        "spread_from_mid_cents": spread_cents,
        "max_spread_cents": float(max_spread_cents),
        "be_margin_cents": margin,      # >0 = inside corridor with room
        "fits_corridor": margin > 0,
    }


def read_midpoint(c, token):
    """[REUSE-ish] get_midpoint() → float mid."""
    return float(c.get_midpoint(token)["mid"])


def _reward_weight(size, spread_cents, max_spread_cents):
    """[NEW] Polymarket LP reward weight (Step A formula):
      w = size * (max_spread - spread)^2 / max_spread^2 ,  0 outside corridor."""
    if spread_cents > max_spread_cents:
        return 0.0
    return size * (max_spread_cents - spread_cents) ** 2 / (max_spread_cents ** 2)


def read_book_depth(c, token, mid, max_spread):
    """[NEW] Sum resting size on every book level inside the reward corridor and
    convert to reward-WEIGHT (Step A formula), separately per side.
    Others' resting size is treated as two-sided (conservative: our share is
    UNDER-stated). Returns dict with per-side competitor weight + raw depth."""
    ob = c.get_order_book(token)
    bids = ob.get("bids") or []
    asks = ob.get("asks") or []
    def side(levels):
        depth = 0.0; weight = 0.0
        for lv in levels:
            px = float(lv["price"]); sz = float(lv["size"])
            spread_c = abs(px - mid) * 100
            if spread_c <= max_spread:
                depth += sz
                weight += _reward_weight(sz, spread_c, max_spread)
        return depth, weight
    bid_depth, bid_w = side(bids)
    ask_depth, ask_w = side(asks)
    return {
        "mid": mid, "max_spread": max_spread,
        "bid_depth": bid_depth, "ask_depth": ask_depth,
        "competitor_weight_bid": bid_w, "competitor_weight_ask": ask_w,
    }


def estimate_share(depth, size, offset_cents, max_spread):
    """[NEW] Our reward share if we quote `size` per leg at `offset_cents` from mid.
    Competitor weight from read_book_depth already counts others two-sided, so we
    add our own weight to each side and take the ratio. Conservative (share low)."""
    our_w = _reward_weight(size, offset_cents, max_spread)  # per leg
    tot_bid = depth["competitor_weight_bid"] + our_w
    tot_ask = depth["competitor_weight_ask"] + our_w
    share_bid = our_w / tot_bid if tot_bid else 0.0
    share_ask = our_w / tot_ask if tot_ask else 0.0
    return {
        "offset_cents": offset_cents, "our_weight_per_leg": our_w,
        "share_bid": share_bid, "share_ask": share_ask,
        "share_avg": (share_bid + share_ask) / 2,
    }


# ─────────────────────── QUOTING CORE [NEW] ──────────────────────────
def place_two_sided(c, mkt, mid, plan=None, params=None):
    """[NEW] Place BID @ mid-offset and ASK @ mid+offset, both GTC maker.
    Returns (bid_order_id, ask_order_id). Uses OrderArgsV2 + post_order(GTC)
    like copy-daemon line 361-364, but TWO legs and anchored at mid, not best_bid.

    `plan` (from inventory_manage) drives asymmetric offsets/sizes when inventory
    is skewed; when None or skew='flat', symmetric QUOTE_OFFSET on both legs.
    `params` supplies neg_risk/tick_size directly (not read from mkt['params'],
    which may be stale/absent for a market whose load failed this tick).

    MONEY-ADJACENT: real placement guarded by DRY_RUN.
    """
    if DRY_RUN:
        # [NEW] validate against the LIVE book (LayerX lesson: never quote off bid-prices).
        ob = c.get_order_book(mkt["token"])
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        best_bid = max((float(b["price"]) for b in bids), default=None)
        best_ask = min((float(a["price"]) for a in asks), default=None)
        tick = float(ob.get("tick_size") or mkt.get("tick_size") or 0.01)
        # anchor on book midpoint, not the passed mid, and round to tick
        book_mid = (best_bid + best_ask) / 2 if (best_bid and best_ask) else mid
        def _round(x): return round(round(x / tick) * tick, 4)
        _plan = plan or {}
        bid_off = float(_plan.get("bid_offset", QUOTE_OFFSET))
        ask_off = float(_plan.get("ask_offset", QUOTE_OFFSET))
        bid_sz = float(_plan.get("bid_size", mkt["min_size"]))
        ask_sz = float(_plan.get("ask_size", mkt["min_size"]))
        our_bid = _round(book_mid - bid_off)
        our_ask = _round(book_mid + ask_off)
        ms = (params or {}).get("max_spread")
        if ms is None:
            ms = mkt.get("max_spread")
        bid_spread_c = (book_mid - our_bid) * 100
        ask_spread_c = (our_ask - book_mid) * 100
        crosses_bid = (best_ask is not None) and (our_bid >= best_ask)  # would take asks
        crosses_ask = (best_bid is not None) and (our_ask <= best_bid)  # would take bids
        in_corridor = (ms is None) or (bid_spread_c <= ms and ask_spread_c <= ms)
        log(f"[DRY_RUN] {mkt['name']} book_bid={best_bid} book_ask={best_ask} "
            f"book_mid={book_mid:.4f} tick={tick} skew={_plan.get('skew','flat')}")
        log(f"[DRY_RUN]   our BID @ {our_bid} ({bid_spread_c:.2f}c from mid) sz={bid_sz} | "
            f"our ASK @ {our_ask} ({ask_spread_c:.2f}c from mid) sz={ask_sz}")
        log(f"[DRY_RUN]   maker_safe: bid_no_cross={not crosses_bid} ask_no_cross={not crosses_ask} "
            f"in_corridor={in_corridor}")
        if crosses_bid or crosses_ask:
            log(f"[DRY_RUN]   WARN: quote would cross the book -> taker fill (fee). "
                f"Increase QUOTE_OFFSET or check tick alignment.")
        # mirror live return contract: suppressed leg -> None id
        return (("dry_bid" if bid_sz > 0 else None),
                ("dry_ask" if ask_sz > 0 else None))

    # ── LIVE PATH (money moves) ──────────────────────────────────────────
    # Symmetric maker two-sided quote anchored on the LIVE book midpoint.
    # Both legs GTC (rest passively -> maker -> entry fee = 0). Cross-guard:
    # if a leg would cross the book (would execute as taker and pay fee), that
    # leg is SKIPPED this tick, never repriced into a taker fill. The other leg
    # still posts. Returns (bid_id, ask_id); a skipped leg's id is None.
    token = mkt["token"]
    ob = c.get_order_book(token)
    bids = ob.get("bids") or []
    asks = ob.get("asks") or []
    best_bid = max((float(b["price"]) for b in bids), default=None)
    best_ask = min((float(a["price"]) for a in asks), default=None)
    # tick_size must be the STRING key ROUNDING_CONFIG expects ('0.01'), not float.
    # Prefer authoritative get_tick_size(); fall back to book/params only if it fails.
    try:
        tick_str = c.get_tick_size(token)
    except Exception:
        tick_str = str(ob.get("tick_size") or (params or {}).get("tick_size")
                       or mkt.get("tick_size") or "0.01")
    tick = float(tick_str)                               # float for offset arithmetic only
    book_mid = (best_bid + best_ask) / 2 if (best_bid and best_ask) else mid

    def _round(x):
        return round(round(x / tick) * tick, 4)

    # Plan-driven offsets/sizes (from inventory_manage). Default = symmetric.
    plan = plan or {}
    bid_off = float(plan.get("bid_offset", QUOTE_OFFSET))
    ask_off = float(plan.get("ask_offset", QUOTE_OFFSET))
    bid_size = float(plan.get("bid_size", mkt["min_size"]))
    ask_size = float(plan.get("ask_size", mkt["min_size"]))

    our_bid = _round(book_mid - bid_off)
    our_ask = _round(book_mid + ask_off)
    # neg_risk from params (authoritative), not stale mkt['params'].
    neg_risk = bool((params or mkt.get("params") or {}).get("neg_risk", False))
    opts = PartialCreateOrderOptions(tick_size=tick_str, neg_risk=neg_risk)

    crosses_bid = (best_ask is not None) and (our_bid >= best_ask)
    crosses_ask = (best_bid is not None) and (our_ask <= best_bid)

    # corridor guard: a leg outside max_spread earns 0 reward but still risks an
    # adverse fill. Skip it rather than rest a rewardless order.
    ms = (params or {}).get("max_spread")
    if ms is None:
        ms = mkt.get("max_spread")
    bid_spread_c = (book_mid - our_bid) * 100.0
    ask_spread_c = (our_ask - book_mid) * 100.0
    bid_out = (ms is not None) and (bid_spread_c > ms)
    ask_out = (ms is not None) and (ask_spread_c > ms)

    bid_id = ask_id = None

    # BID leg (BUY at our_bid) — skip if plan zeroed it, crosses, or leaves corridor.
    if bid_size <= 0:
        log(f"[place_two_sided] BID suppressed by plan (skew={plan.get('skew')})")
    elif crosses_bid:
        log(f"[place_two_sided] BID @ {our_bid} would cross best_ask={best_ask} "
            f"-> SKIP leg this tick (no taker fill)")
    elif bid_out:
        log(f"[place_two_sided] BID @ {our_bid} spread={bid_spread_c:.2f}c > max_spread={ms}c "
            f"-> SKIP leg (rewardless)")
    else:
        try:
            bid_args = OrderArgsV2(token_id=token, price=our_bid, size=bid_size, side=BUY)
            signed_bid = c.create_order(bid_args, opts)
            resp_bid = c.post_order(signed_bid, order_type=OrderType.GTC)
            bid_id = resp_bid.get("orderID") if isinstance(resp_bid, dict) else None
            log(f"[place_two_sided] BID posted @ {our_bid} size={bid_size} "
                f"id={bid_id} resp={resp_bid}")
        except Exception as e:
            log(f"[place_two_sided] BID post error (raw, not auto-fixed): {e}")

    # ASK leg (SELL at our_ask) — skip if plan zeroed it, crosses, or leaves corridor.
    if ask_size <= 0:
        log(f"[place_two_sided] ASK suppressed by plan (skew={plan.get('skew')})")
    elif crosses_ask:
        log(f"[place_two_sided] ASK @ {our_ask} would cross best_bid={best_bid} "
            f"-> SKIP leg this tick (no taker fill)")
    elif ask_out:
        log(f"[place_two_sided] ASK @ {our_ask} spread={ask_spread_c:.2f}c > max_spread={ms}c "
            f"-> SKIP leg (rewardless)")
    else:
        try:
            ask_args = OrderArgsV2(token_id=token, price=our_ask, size=ask_size, side=SELL)
            signed_ask = c.create_order(ask_args, opts)
            resp_ask = c.post_order(signed_ask, order_type=OrderType.GTC)
            ask_id = resp_ask.get("orderID") if isinstance(resp_ask, dict) else None
            log(f"[place_two_sided] ASK posted @ {our_ask} size={ask_size} "
                f"id={ask_id} resp={resp_ask}")
        except Exception as e:
            log(f"[place_two_sided] ASK post error (raw, not auto-fixed): {e}")

    return (bid_id, ask_id)


def cancel_quotes(c, order_ids):
    """[REUSE] cancel_order() from copy-daemon line 383, applied to both legs."""
    if DRY_RUN:
        log(f"[DRY_RUN] would cancel {order_ids}")
        return
    # ── LIVE PATH ──: cancel each leg by id. None-id legs (skipped/unposted) ignored.
    for oid in (order_ids or ()):
        if not oid or (isinstance(oid, str) and oid.startswith("dry_")):
            continue
        try:
            resp = c.cancel_order(OrderPayload(orderID=oid))
            log(f"[cancel_quotes] cancelled {oid} resp={resp}")
        except Exception as e:
            log(f"[cancel_quotes] cancel {oid} error (raw, not auto-fixed): {e}")


def check_fills(c, condition_id, funder, after_ts):
    """[NEW] Detect adverse fills via get_trades() (NOT get_order — empty docstr).
    Fill = adverse selection event, NOT success. Filters our maker trades on this
    market since after_ts. Returns (list_of_trades, newest_ts) where each trade is
    the RAW dict (fields logged on first real fill; sample only available on D3 /
    INFRA-049). Defensive .get() over candidate keys — schema unconfirmed on live.
    Read-only by effect: no order placement/cancel."""
    from py_clob_client_v2.clob_types import TradeParams
    params = TradeParams(market=condition_id, maker_address=funder, after=after_ts)
    try:
        trades = c.get_trades(params) or []
    except Exception as e:
        throttled_log(f"check_fills_err:{e}",
                      f"[check_fills] get_trades error (raw, not auto-fixed): {e}",
                      seconds=300)
        return [], after_ts
    if not trades:
        return [], after_ts
    # first real fill: dump raw element ONCE so we can confirm schema on D3.
    log(f"[check_fills] RAW first trade element: {trades[0]}")
    newest = after_ts
    max_ts = after_ts
    for tr in trades:
        ts = tr.get("match_time") or tr.get("timestamp") or tr.get("created_at")
        try:
            ts = int(ts)
            if ts > max_ts:
                max_ts = ts
        except (TypeError, ValueError):
            pass
    # Advance cursor strictly PAST the newest trade. Many trade APIs treat `after`
    # as inclusive (>=), which would re-return the same fills every tick and make
    # the daemon re-quote forever on one stale fill. +1s guarantees progress.
    newest = max_ts + 1 if max_ts > after_ts else after_ts
    return trades, newest


def read_inventory(c, token):
    """[NEW] Actual CONDITIONAL (YES-share) balance for token, read ON-CHAIN.

    WHY not SDK: get_balance_allowance() is a DEAD branch — returns 0 even with
    real balances (documented Account1/Account2, POLYMARKET_V2_CONNECTION.md).
    Trust only on-chain, same as pUSD cash reads in copy-daemon.

    Reads ERC-1155 balanceOf(FUNDER, token_id) on the CTF contract.
      selector keccak256("balanceOf(address,uint256)") = 0x00fdd58e
      args: address left-padded to 32B, then uint256 token_id (32B).
    Falls back through RPC_URLS. Returns float shares (raw / 1e6), or None on
    total RPC failure (caller must NOT assume 0 — None = unknown, hold symmetric).
    `c` unused (kept for signature parity with the call site). Read-only.
    """
    try:
        token_int = int(token)
    except (TypeError, ValueError) as e:
        log(f"[read_inventory] bad token_id (raw): {e}")
        return None
    selector = bytes.fromhex("00fdd58e")
    last_error = None
    for rpc_url in RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"headers": RPC_HEADERS}))
            padded_addr = w3.to_bytes(hexstr=FUNDER).rjust(32, b"\x00")
            padded_id = token_int.to_bytes(32, "big")
            calldata = selector + padded_addr + padded_id
            result = w3.eth.call({"to": CTF_CONTRACT, "data": "0x" + calldata.hex()})
            raw = int.from_bytes(result, "big")
            return raw / (10 ** SHARE_DECIMALS)
        except Exception as e:
            last_error = e
            continue
    log(f"[read_inventory] all RPCs failed (raw, not auto-fixed): {last_error}")
    return None


def inventory_manage(c, mkt, inv_shares, mid, params):
    """[NEW] After adverse-fill: compute an ASYMMETRIC re-quote that discharges
    inventory WHILE still farming. NOT a market-sell (that would pay taker fee).

    Model (maker fee=0 on this market):
      - target inventory = 0 (flat market-maker).
      - if long  (inv > +min_size/2): skew ASK toward mid (unload faster),
                                       widen/suppress BID (stop accumulating).
      - if short (inv < -min_size/2): mirror.
      - within dead-band: keep SYMMETRIC quotes (min(Q_one,Q_two) rule — the
        two-sided reward is capped by the WEAKER leg, so symmetry maximizes score).

    Returns a quote plan dict for place_two_sided to consume. DOES NOT place
    orders itself (money-adjacent placement stays behind DRY_RUN + TODO CONFIRM).
    Read-only by effect.
    """
    min_sz = float(mkt.get("min_size") or 0)
    # Deadband set to 1.5x min_size: the bootstrap ASK-leg inventory (~min_size shares,
    # intentionally bought to seed the two-sided quote) must NOT be treated as an adverse
    # imbalance. Only inventory that grows BEYOND the seeded leg (real adverse fills) skews.
    dead = float(mkt.get("inv_deadband") or (min_sz * 1.5))
    off = float(QUOTE_OFFSET)
    ms = params.get("max_spread")
    plan = {"bid_offset": off, "ask_offset": off,
            "bid_size": min_sz, "ask_size": min_sz, "skew": "flat"}
    if inv_shares is None:
        log("[inventory_manage] inventory unknown -> hold symmetric (no skew)")
        return plan
    if inv_shares > dead:
        # LONG: pull ASK closer to mid to sell, suppress BID
        tighter = max(off / 2.0, 0.005)
        plan.update(ask_offset=tighter, bid_size=0.0, skew="long_unload")
    elif inv_shares < -dead:
        # SHORT: pull BID closer to mid to buy back, suppress ASK
        tighter = max(off / 2.0, 0.005)
        plan.update(bid_offset=tighter, ask_size=0.0, skew="short_cover")
    # corridor guard: never propose an offset outside max_spread
    if ms is not None:
        cap = (ms / 100.0)
        plan["bid_offset"] = min(plan["bid_offset"], cap)
        plan["ask_offset"] = min(plan["ask_offset"], cap)
    log(f"[inventory_manage] inv={inv_shares:.2f} dead=+/-{dead} -> skew={plan['skew']} "
        f"bid_off={plan['bid_offset']} ask_off={plan['ask_offset']} "
        f"bid_sz={plan['bid_size']} ask_sz={plan['ask_size']}")
    return plan


_NOTIFY_SOCK = None
def _get_notify_socket():
    """Lazy-open datagram socket to systemd $NOTIFY_SOCKET (stdlib only).
    Returns (sock, addr) or (None, None) if not run under Type=notify."""
    global _NOTIFY_SOCK
    if _NOTIFY_SOCK is not None:
        return _NOTIFY_SOCK
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        _NOTIFY_SOCK = (None, None)
        return _NOTIFY_SOCK
    # abstract namespace socket starts with '@' -> replace with NUL
    path = "\0" + addr[1:] if addr.startswith("@") else addr
    try:
        import socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
        _NOTIFY_SOCK = (s, path)
    except Exception as e:
        log(f"[heartbeat] notify socket open failed (raw): {e}")
        _NOTIFY_SOCK = (None, None)
    return _NOTIFY_SOCK


def heartbeat(ready=False):
    """[NEW] systemd watchdog ping via $NOTIFY_SOCKET (Type=notify + WatchdogSec).
    S2-autonomous liveness (variant B): NO S1 DB write, no grants needed.
    Sends WATCHDOG=1 each tick; READY=1 once on first call. No-op if not under
    systemd notify. Never raises (liveness must not crash the loop)."""
    sock, path = _get_notify_socket()
    if sock is None:
        return
    try:
        msg = b"READY=1\nWATCHDOG=1" if ready else b"WATCHDOG=1"
        sock.sendto(msg, path)
    except Exception as e:
        log(f"[heartbeat] notify send failed (raw, not auto-fixed): {e}")


# ─────────────────────────── MAIN LOOP ────────────────────────────────
def main():
    if '--diag' in sys.argv:
        log(f"DRY_RUN={DRY_RUN}")
        try:
            c = build_client()
            log(f"Client address: {c.get_address()}  FUNDER: {FUNDER}")
            notify("FARMING DIAG OK")
            sys.exit(0)
        except Exception as e:
            log(f"Client diag error: {e}")
            sys.exit(1)

    log(f"Starting farming daemon (acc2), DRY_RUN={DRY_RUN})")
    c = build_client()
    if DRY_RUN and not os.path.exists(ENV_PATH):
        log("Client ready (read-only, no address — DRY_RUN no-key mode)")
    else:
        log(f"Client ready, address={c.get_address()}")

    # per-market runtime state.
    #   center     : mid at last (re)quote  |  ids: active leg order ids (dry_* in DRY_RUN)
    #   be         : corridor-margin dict from compute_break_even
    #   params     : cached reward params (refreshed each PARAM_REFRESH ticks)
    #   inv        : last-read inventory (YES shares)  |  last_ts: get_trades cursor
    state = {m["token"]: {"center": None, "ids": None, "be": None,
                          "params": None, "inv": 0.0, "last_ts": 0}
             for m in MARKETS}
    PARAM_REFRESH = 30          # re-read reward params every N ticks
    tick_n = 0

    while True:
        try:
            tick_n += 1
            for mkt in MARKETS:
                st = state[mkt["token"]]
                token = mkt["token"]

                # 1. reward params + corridor margin (refresh periodically)      [NEW]
                if st["params"] is None or tick_n % PARAM_REFRESH == 0:
                    p = load_reward_params(c, mkt)
                    if p is None:
                        # Lost params: cancel any resting legs so they don't sit
                        # unmanaged (adverse-fill risk) while we're blind. Then skip.
                        if st["ids"] is not None:
                            cancel_quotes(c, st["ids"])
                            st["ids"] = None
                            st["center"] = None
                        log(f"[SKIP] {mkt['name']} params unavailable this tick")
                        continue
                    st["params"] = p
                    mkt["params"] = p   # expose to place_two_sided live path (neg_risk, tick)
                    if mkt.get("max_spread") is None:
                        mkt["max_spread"] = p.get("max_spread")
                    st["be"] = compute_break_even(p.get("max_spread"), QUOTE_OFFSET)
                params = st["params"]

                # 2. midpoint                                                    [NEW]
                mid = read_midpoint(c, token)

                # 3. adverse-fill FIRST (fill = failure), then reconcile inventory[NEW]
                fills, st["last_ts"] = check_fills(
                    c, params["condition_id"], FUNDER, st["last_ts"])
                st["inv"] = read_inventory(c, token)
                plan = None
                if fills or (st["inv"] is not None and abs(st["inv"]) > (mkt.get("min_size") or 0)/2.0):
                    plan = inventory_manage(c, mkt, st["inv"], mid, params)

                # 3b. reward-score estimate (Step A). This is the daemon's PRIMARY
                #     metric — what fraction of the LP reward pool our quote earns.
                #     Computed every tick from the live book so D3 has a time series.
                score = None
                ms_now = params.get("max_spread")
                if ms_now is not None:
                    try:
                        depth = read_book_depth(c, token, mid, ms_now)
                        score = estimate_share(depth, float(mkt["min_size"]),
                                               QUOTE_OFFSET * 100.0, ms_now)
                    except Exception as e:
                        throttled_log(f"score_err:{token}",
                                      f"[score] estimate failed (raw): {e}", seconds=300)

                # 4. drift check -> re-quote (asymmetric if plan skewed).        [NEW]
                #    Requote ONLY past REQUOTE_FRAC*be_margin: epoch score is
                #    per-minute; aggressive cancel/replace burns accrued score.
                be_margin = (st["be"] or {}).get("be_margin_cents")
                need_requote = False
                if st["center"] is None:
                    need_requote = True
                elif plan is not None and plan.get("skew") != "flat":
                    need_requote = True     # inventory skew -> reposition
                elif be_margin is not None:
                    drift_c = abs(mid - st["center"]) * 100.0
                    if drift_c >= REQUOTE_FRAC * be_margin:
                        need_requote = True

                if need_requote:
                    if st["ids"] is not None:
                        cancel_quotes(c, st["ids"])
                    st["ids"] = place_two_sided(c, mkt, mid, plan=plan, params=params)
                    st["center"] = mid
                    action = f"REQUOTE (skew={plan.get('skew') if plan else 'flat'})"
                else:
                    action = "HOLD (resting, accruing reward)"

                share_txt = (f"share_avg={score['share_avg']:.4f}"
                             if score else "share_avg=n/a")
                tick_line = (f"[TICK {tick_n}] {mkt['name']} mid={mid:.4f} center={st['center']:.4f} "
                             f"be_margin={be_margin} inv={st['inv']} {share_txt} "
                             f"-> {action}")
                if action.startswith("HOLD"):
                    # steady state: collapse repeated HOLD ticks per market
                    throttled_log(f"tick_hold:{mkt['token']}", tick_line, seconds=300)
                else:
                    log(tick_line)   # REQUOTE / skew — always surface

            heartbeat(ready=(tick_n == 1))   # [NEW] systemd watchdog ping (variant B)
            time.sleep(POLL_INTERVAL)

        except Exception as e:
            log(f"ERROR (raw, not auto-fixed): {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
