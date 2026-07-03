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
    OrderScoringParams,  # [FARM-004] is_order_scoring(OrderScoringParams(orderId=))
)
from py_clob_client_v2.order_builder.constants import BUY, SELL
import requests, os, sys, time, re, json
from decimal import Decimal, ROUND_CEILING
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
DRY_RUN = False                       # FARM-003: post-incident default. LIVE flip = separate confirmed step.
POLL_INTERVAL   = 10                 # seconds between ticks
QUOTE_OFFSET    = 0.02               # FARM-003 F2: offset MUST exceed requote threshold (incident root #1)
REQUOTE_FRAC    = 0.4                # FARM-003 F2: threshold = 0.4 * be_margin(2.5c) = 1.0c < 2.0c offset
STATE_FILE      = "/opt/executor/app/farming_state.json"  # FARM-003: last_ts persistence across restarts

# Target markets (from Step A/B recon). size = shares per leg.
# TODO CONFIRM: sizing, market selection, whether Fed#2 included alongside US x Iran.
MARKETS = [
    {
        "name":  "US x Iran meeting",
        "token": "95676548525614691656970153001244738030704823210041753577158504248850005676647",
        "min_size": 200,             # shares per leg
        "inv_center": 200,           # FARM-003 F4: target seed inventory backing the ASK leg
                                     #   inventory deviation is measured from HERE, not from 0
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


# [FARM-004] Edge-triggered operator alerts. State is per-alert-key bool:
#   None = unknown (startup), True = bad, False = ok.
# notify() fires on: bad->ok (recovery, always), ok->bad / None->bad (onset),
#   and bad->bad only past `cooldown` (re-nudge for a persistent problem).
# ok->ok is silent. Liveness rule: never raises (an alert bug must not kill
# the loop). DRY: callers gate on `not DRY_RUN`, so all three are no-op in DRY.
_alert_state = {}          # key -> last bool (None until first observation)
_alert_last_bad = {}       # key -> monotonic ts of last bad-notify (cooldown)

def edge_notify(key, is_bad, msg_bad, msg_ok, cooldown=1800):
    """[FARM-004e] Fire notify() only on state transitions (onset + recovery).
    Re-nudge (bad→bad after cooldown) removed. cooldown param kept for call-site compat.
    Returns None. Never raises."""
    try:
        prev = _alert_state.get(key)          # None / False / True
        if is_bad:
            if prev is not True:
                # onset (None->bad or ok->bad): always notify
                notify(msg_bad)
                _alert_last_bad[key] = time.time()
        else:
            if prev is True:
                # recovery bad->ok: always notify. None->ok stays silent.
                notify(msg_ok)
        _alert_state[key] = is_bad
    except Exception as e:
        log(f"[edge_notify] raw (not auto-fixed): {e}")


def load_state_file():
    """[FARM-003] last_ts persistence: restart must NOT re-read history as fresh
    fills (bootstrap-as-fill bug, FARM-001 debt). Also restores alert latch state.
    Returns {} on any failure."""
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        # Restore persisted alert latch state
        alerts = data.get("_alerts", {})
        global _alert_state
        _alert_state = {k: bool(v) for k, v in alerts.items()}
        return data
    except Exception:
        return {}


def save_state_file(state):
    """[FARM-003] Atomic write (tmp+replace) of per-token cursors + alert latch.
    Never raises."""
    try:
        # Token cursors
        token_data = {tok: {"last_ts": st.get("last_ts", 0)} for tok, st in state.items()}
        # Alert latch: only the bool state (not _alert_last_bad timestamps)
        alert_data = {"_alerts": dict(_alert_state)}
        data = {**token_data, **alert_data}
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        throttled_log("state_save_err", f"[state] save failed (raw): {e}", 300)


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
def place_two_sided(c, mkt, mid, plan=None, params=None, inv=None):
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

    # FARM-003 F3: never post an ASK the on-chain inventory can't back.
    # Incident: ASK 200 posted at inv=0.03 -> API 400 swallowed -> phantom
    # 'two-sided' state. Rule: cap ask_size by inventory; below reward min_size
    # the leg earns nothing -> conscious one-sided mode instead of 400-spam.
    if ask_size > 0 and inv is not None:
        backable = max(0.0, float(inv))
        if backable < ask_size:
            if backable >= float(mkt["min_size"]):
                log(f"[place_two_sided] ASK size capped by inventory: "
                    f"{ask_size} -> {backable:.2f}")
                ask_size = float(int(backable))  # whole shares, stay under balance
            else:
                log(f"[place_two_sided] ASK skipped: inventory {backable:.2f} < min_size "
                    f"{mkt['min_size']} -> ONE-SIDED mode (1/3 score) on {mkt['name']}")
                ask_size = 0.0

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

    # [FARM-004] C: dynamic BID cap — free cash (pUSD balanceOf FUNDER) limits bid_size.
    # mirrors F3 ASK cap (line 402) but for the cash leg: BID size costs our_bid * size pUSD.
    # buffer 3% (1.03) covers fee / price drift so cap is not immediately stale.
    if bid_size > 0:
        free_cash = read_cash_balance()
        if free_cash is not None:
            # affordable = floor(free_cash / (price * size)) -> solve for size
            # size <= free_cash / (our_bid * 1.03)
            affordable_cap = free_cash / (our_bid * 1.03) if our_bid > 0 else 0.0
            affordable_cap = float(int(affordable_cap))  # whole shares
            if affordable_cap < float(mkt["min_size"]):
                log(f"[place_two_sided] BID skipped: free_cash ${free_cash:.2f} < "
                    f"${free_cash:.2f} / ({our_bid:.4f} * 1.03) = affordable ${affordable_cap:.2f} "
                    f"< min_size ${mkt['min_size']} -> conscious one-sided BID skip")
                bid_size = 0.0
            elif affordable_cap < bid_size:
                log(f"[place_two_sided] BID size capped by cash: {bid_size} -> {affordable_cap:.0f} "
                    f"(free=${free_cash:.2f})")
                bid_size = affordable_cap

    # [FARM-004d rev.5] Fix 2: inv+bid_size overshoot gate.
    # Active only when skew == 'reseed_buy' (deficit repurchase mode).
    # In flat/sell modes, gate is bypassed (pre-004d behavior).
    # Formula: if inv + bid_size > center + dead -> skip BID (overshoot).
    if bid_size > 0 and inv is not None and plan.get('skew') == 'reseed_buy':
        min_sz = float(mkt.get("min_size") or 0)
        center = float(mkt.get("inv_center") or 0)
        dead = float(mkt.get("inv_deadband") or (min_sz * 0.5))
        threshold = center + dead
        if inv + bid_size > threshold:
            log(f"[place_two_sided] BID skipped: inv={inv:.0f} + bid_size={bid_size:.0f} = "
                f"{inv + bid_size:.0f} > threshold={threshold:.0f} (center={center:.0f} + dead={dead:.0f}) "
                f"skew={plan.get('skew')} -> inv overshoot gate (FARM-004d Fix 2)")
            bid_size = 0.0

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
            # Recovery after balance rejection: next successful BID clears the latch
            edge_notify(f"balance_reject:{token}", False,
                        "", "", cooldown=0)
        except Exception as e:
            # Check for balance rejection: extract available/needed from error message
            err_str = str(e)
            if "not enough balance" in err_str.lower() or "insufficient" in err_str.lower():
                # Parse free/need from actual API error fields (microUSD -> divide by 1e6):
                # "balance: 171673465, sum of active orders: 124000000, order amount (inc. fees): 124000000"
                free = need = None
                try:
                    import re
                    m_bal = re.search(r'balance:\s*([0-9]+)', err_str)
                    m_amt = re.search(r'order amount[^:]*:\s*([0-9]+)', err_str)
                    if m_bal:
                        free = float(m_bal.group(1)) / 1e6
                    if m_amt:
                        need = float(m_amt.group(1)) / 1e6
                except Exception:
                    pass
                edge_notify(
                    f"balance_reject:{token}", True,
                    f"🟠 BID урезан/пропущен ({mkt['name']}): "
                    f"свободно ${free} < нужно ${need}",
                    f"🟢 Заявка принята ({mkt['name']})",
                    cooldown=0)
            else:
                notify(f"[farm] BID post FAILED on {mkt['name']} (raw, not auto-fixed): {e}")

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
            notify(f"[farm] ASK post FAILED on {mkt['name']} (raw, not auto-fixed): {e}")

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


def reconcile_orders(c, token, st, min_size, mid=None):
    """[FARM-003 F1+F5] The BOOK is the source of truth, not in-memory st['ids'].
    Incident 2026-07-02: restart lost st['ids'] -> orphan BUY@0.60 rested 8h;
    rejected ASK left daemon 'two-sided' in its head, one-sided in the book.

    Per tick (live only):
      - ORPHANS: live orders on this token NOT tracked in st['ids'] -> cancel
        (restart survivors / lost-cancel leftovers). Forces requote.
      - MISSING: tracked ids gone from the book (filled or rejected) -> forces
        requote so the eaten/failed leg is restored immediately.
      - F5: a tracked leg whose remaining size < reward min_size earns ZERO
        reward while still fill-exposed -> forces requote (cancel+replace full).
        Exception (FARM-004d): BUY leg with size_matched > 0 (partially filled)
        is kept in book if drift from mid is within REQUOTE_FRAC*QUOTE_OFFSET —
        only requote if mid has genuinely drifted away from the order.
      - ONE-SIDED: <2 sides live while quotes expected -> flagged (1/3 score);
        NOT a requote trigger by itself (deliberate skip when inventory short —
        requoting every tick would burn accrued score).
    Returns {'one_sided': bool, 'force_requote': bool}. Read-only except
    orphan cancellation. Never raises."""
    out = {"one_sided": False, "force_requote": False}
    if DRY_RUN or st["ids"] is None:
        return out
    try:
        live = [o for o in (c.get_open_orders() or [])
                if o.get("asset_id") == token]
    except Exception as e:
        throttled_log(f"reconcile_err:{token}",
                      f"[reconcile] get_open_orders error (raw, not auto-fixed): {e}",
                      seconds=300)
        return out
    tracked = set(x for x in (st["ids"] or ()) if x and not str(x).startswith("dry_"))
    # [FARM-004g B1] also track auto_unload order so it's not cancelled as orphan
    unload_id = st.get("unload_id")
    if unload_id and not str(unload_id).startswith("dry_"):
        tracked.add(unload_id)
    live_ids, sides = set(), set()
    for o in live:
        oid = o.get("id") or o.get("order_id")
        live_ids.add(oid)
        if oid not in tracked:
            log(f"[reconcile] ORPHAN {o.get('side')} @ {o.get('price')} id={oid} -> cancel")
            cancel_quotes(c, (oid,))
            out["force_requote"] = True
            continue
        sides.add(o.get("side"))
        try:
            rem = float(o.get("original_size", 0)) - float(o.get("size_matched", 0))
            size_matched = float(o.get("size_matched", 0))
        except (TypeError, ValueError):
            rem = None
            size_matched = 0.0
        if rem is not None and rem < float(min_size):
            # [FARM-004d] Fix 1: BUY partially filled -> keep in book if drift is small
            side = o.get("side")
            order_price = float(o.get("price"))
            skip_requote = False
            if side == "BUY" and size_matched > 0 and mid is not None:
                # drift from mid in cents
                drift_c = abs(mid - order_price) * 100.0
                threshold_c = REQUOTE_FRAC * QUOTE_OFFSET * 100.0
                if drift_c <= threshold_c:
                    skip_requote = True
                    throttled_log(
                        f"buy_partial_fill_keep:{token}",
                        f"[reconcile] BUY partially filled (matched={size_matched:.0f}, "
                        f"remaining={rem:.0f}), drift={drift_c:.2f}c <= threshold={threshold_c:.2f}c "
                        f"-> keep in book (FARM-004d Fix 1)",
                        seconds=300)
            if skip_requote:
                pass  # don't force requote, keep BUY in book
            else:
                log(f"[reconcile] leg {side} remaining={rem} < min_size={min_size} "
                    f"-> rewardless but fill-exposed, force requote (F5)")
                out["force_requote"] = True
    if tracked - live_ids:
        missing = tracked - live_ids
        # [FARM-004g B1] if auto_unload order disappeared -> it was filled/cancelled;
        # clear st["unload_id"] and fire recovery latch, NO requote for that
        if unload_id and unload_id in missing:
            log(f"[reconcile] auto_unload id={unload_id} missing from book "
                f"(filled/cancelled) -> clear st['unload_id'], recovery latch")
            st["unload_id"] = None
            edge_notify(
                f"auto_unload:{token}", False,
                f"[auto_unload] pending on {token}",
                f"[OK] auto_unload resolved on {token} (order disappeared from book)",
                cooldown=0)
        rest = missing - {unload_id}
        if rest:
            log(f"[reconcile] tracked leg(s) missing from book (filled/rejected): "
                f"{sorted(rest)} -> force requote")
            out["force_requote"] = True
    if len(sides) < 2:
        out["one_sided"] = True
    return out


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
    # raw element for schema audit — throttled (was: logged on EVERY non-empty batch)
    throttled_log(f"raw_trade:{condition_id}",
                  f"[check_fills] RAW first trade element: {trades[0]}", seconds=3600)
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


def read_cash_balance():
    """[NEW] Read pUSD (ERC-20) cash balance for FUNDER on-chain.

    Uses the same RPC pattern as read_inventory:
      selector keccak256("balanceOf(address)") = 0x70a08231
      args: address left-padded to 32B.
    Falls back through RPC_URLS. Returns float pUSD (raw / 1e6), or None on
    total RPC failure. Read-only.
    """
    selector = bytes.fromhex("70a08231")
    last_error = None
    for rpc_url in RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"headers": RPC_HEADERS}))
            padded_addr = w3.to_bytes(hexstr=FUNDER).rjust(32, b"\x00")
            calldata = selector + padded_addr
            result = w3.eth.call({"to": PUSD_CONTRACT, "data": "0x" + calldata.hex()})
            raw = int.from_bytes(result, "big")
            return raw / (10 ** SHARE_DECIMALS)
        except Exception as e:
            last_error = e
            continue
    log(f"[read_cash_balance] all RPCs failed (raw, not auto-fixed): {last_error}")
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
    # FARM-003 F4 (incident root #5): a two-sided farm on a binary token NEEDS
    # shares to back the ASK, so the equilibrium inventory is the SEED
    # (inv_center ~= min_size), NOT zero. Old model (center=0, dead=1.5*min_size)
    # made the 236->0 drain invisible: skew never fired, ASK sold to depletion.
    # Deviation is measured from inv_center; deadband 0.5*min_size.
    center = float(mkt.get("inv_center") or 0)
    dead = float(mkt.get("inv_deadband") or (min_sz * 0.5))
    off = float(QUOTE_OFFSET)
    ms = params.get("max_spread")
    plan = {"bid_offset": off, "ask_offset": off,
            "bid_size": min_sz, "ask_size": min_sz, "skew": "flat"}
    if inv_shares is None:
        throttled_log(f"invmgr_unknown:{mkt['token']}",
                      "[inventory_manage] inventory unknown -> hold symmetric (no skew)",
                      seconds=300)
        return plan
    delta = inv_shares - center
    if delta > dead:
        # ABOVE seed (adverse BID fills accumulated): pull ASK toward mid to
        # unload the excess, suppress BID (stop accumulating).
        tighter = max(off / 2.0, 0.005)
        plan.update(ask_offset=tighter, bid_size=0.0, skew="long_unload")
    elif delta < -dead:
        # BELOW seed (ASK drained): pull BID toward mid to REBUY the seed,
        # ASK sizing handled by F3 cap (posts only what inventory can back).
        tighter = max(off / 2.0, 0.005)
        plan.update(bid_offset=tighter, skew="reseed_buy")
    # corridor guard: never propose an offset outside max_spread
    if ms is not None:
        cap = (ms / 100.0)
        plan["bid_offset"] = min(plan["bid_offset"], cap)
        plan["ask_offset"] = min(plan["ask_offset"], cap)
    # skew changes surface immediately (key includes skew); flat steady-state throttled
    throttled_log(f"invmgr:{mkt['token']}:{plan['skew']}",
                  f"[inventory_manage] inv={inv_shares:.2f} center={center} dead=+/-{dead} "
                  f"delta={delta:.2f} -> skew={plan['skew']} "
                  f"bid_off={plan['bid_offset']} ask_off={plan['ask_offset']} "
                  f"bid_sz={plan['bid_size']} ask_sz={plan['ask_size']}", seconds=300)
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
    # [FARM-004] Catches "came back up" after crash/restart. The inverse ("went
    # down") cannot be self-reported by a dead process -> external watcher, FARM-005.
    notify(f"🟢 Демон поднялся · LIVE (DRY_RUN={DRY_RUN})")
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
    persisted = load_state_file()   # FARM-003: survive restarts (bootstrap-as-fill fix)
    state = {m["token"]: {"center": None, "ids": None, "be": None,
                          "params": None, "inv": 0.0,
                          "last_ts": int((persisted.get(m["token"]) or {}).get("last_ts", 0))}
             for m in MARKETS}
    if persisted:
        log(f"[state] restored cursors: "
            f"{ {t: s['last_ts'] for t, s in state.items()} }")
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
                    # FARM-003 F2 invariant (incident root #1): the requote
                    # threshold must sit STRICTLY BELOW the quote offset,
                    # otherwise mid can drift through a leg before we reposition.
                    if st["be"] is not None:
                        thr = REQUOTE_FRAC * st["be"]["be_margin_cents"]
                        if thr >= QUOTE_OFFSET * 100.0:
                            notify(f"[farm] F2 INVARIANT VIOLATED on {mkt['name']}: "
                                   f"requote_threshold={thr:.2f}c >= offset="
                                   f"{QUOTE_OFFSET*100:.2f}c — legs can be drifted "
                                   f"through before requote. Fix params.")
                params = st["params"]

                # 2. midpoint                                                    [NEW]
                mid = read_midpoint(c, token)

                # 3. adverse-fill FIRST (fill = failure), then reconcile inventory[NEW]
                fills, st["last_ts"] = check_fills(
                    c, params["condition_id"], FUNDER, st["last_ts"])
                st["inv"] = read_inventory(c, token)
                if fills:
                    # fill = adverse selection event; operator must hear about it
                    # from the daemon, not from a CSV export the next morning.
                    notify(f"[farm] fill(s) detected on {mkt['name']}: "
                           f"n={len(fills)} inv_now={st['inv']}")
                    # [FARM-004d] Fix 3: auto-unload excess inventory after fill.
                    # If inv > center + dead and excess > 20 shares, place one
                    # maker SELL GTC at mid to unload the excess.
                    inv_now = st["inv"]
                    if inv_now is not None:
                        min_sz = float(mkt.get("min_size") or 0)
                        center = float(mkt.get("inv_center") or 0)
                        dead = float(mkt.get("inv_deadband") or (min_sz * 0.5))
                        threshold = center + dead
                        excess = inv_now - center
                        if inv_now > threshold and excess > 20 and not DRY_RUN:
                            # Place auto-unload SELL at mid for excess shares
                            # [FARM-004d rev.2 Правка B] round price UP to nearest tick
                            # (safe for SELL: price must be > mid to not cross the book)
                            try:
                                tick_str = str(params.get("tick_size")
                                              or mkt.get("tick_size") or "0.01")
                                tick = float(tick_str)
                                # [FARM-004d rev.3] Decimal-safe rounding UP to nearest tick
                                ticks = int((Decimal(str(mid)) / Decimal(str(tick))).to_integral_value(rounding=ROUND_CEILING))
                                sell_price = float(ticks * Decimal(str(tick)))
                                neg_risk = bool(params.get("neg_risk", False))
                                unload_opts = PartialCreateOrderOptions(
                                    tick_size=tick_str, neg_risk=neg_risk)
                                unload_args = OrderArgsV2(
                                    token_id=token, price=sell_price,
                                    size=float(int(excess)), side=SELL)
                                signed_unload = c.create_order(unload_args, unload_opts)
                                resp_unload = c.post_order(
                                    signed_unload, order_type=OrderType.GTC)
                                unload_id = resp_unload.get("orderID") if isinstance(
                                    resp_unload, dict) else None
                                log(f"[FARM-004d Fix 3] auto-unload SELL posted @ {sell_price:.4f} "
                                    f"(mid={mid:.4f}, tick={tick}) size={excess:.0f} "
                                    f"id={unload_id} resp={resp_unload}")
                                st["unload_id"] = unload_id   # [FARM-004g B1]
                                # One-time TG alert via latch (edge_notify)
                                edge_notify(
                                    f"auto_unload:{token}", True,
                                    f"🟠 Авторазгрузка ({mkt['name']}): "
                                    f"BID fill → inv={inv_now:.0f}, "
                                    f"выгружено {excess:.0f} шер @ {sell_price:.4f}",
                                    f"[OK] auto-unload resolved on {mkt['name']}",
                                    cooldown=0)
                            except Exception as e:
                                log(f"[FARM-004d Fix 3] auto-unload failed: {e}")
                # plan is cheap and read-only -> compute whenever inventory known
                plan = inventory_manage(c, mkt, st["inv"], mid, params) \
                    if st["inv"] is not None else None

                # [FARM-004f] Reseed: on first tick after restart st["ids"] is None
                # (only last_ts is persisted). reconcile_orders exits early for
                # st["ids"]=None, so orphan orders from the dead process never get
                # detected. Fix: fetch live orders, adopt ONE per side (closest to
                # target), cancel all other legs even if within threshold.
                if st["ids"] is None and not DRY_RUN and mid is not None:
                    bid_target = mid - float(QUOTE_OFFSET)
                    ask_target = mid + float(QUOTE_OFFSET)
                    requote_thr = REQUOTE_FRAC * float(QUOTE_OFFSET)
                    adopted_ids = []
                    try:
                        live = [o for o in (c.get_open_orders() or [])
                                if o.get("asset_id") == token]
                    except Exception as e:
                        throttled_log(f"reseed_err:{token}",
                                       f"[FARM-004f] get_open_orders failed: {e}", seconds=60)
                        live = []
                    # Find best (min drift) order per side
                    best_buy = None   # (drift, oid, price)
                    best_sell = None  # (drift, oid, price)
                    for o in live:
                        oid = o.get("id") or o.get("order_id")
                        side = o.get("side")
                        price = float(o.get("price"))
                        if side == "BUY":
                            drift = abs(price - bid_target)
                            label = f"BUY@{price:.4f} vs target={bid_target:.4f}"
                        else:
                            drift = abs(price - ask_target)
                            label = f"SELL@{price:.4f} vs target={ask_target:.4f}"
                        if drift <= requote_thr:
                            if side == "BUY":
                                if best_buy is None or drift < best_buy[0]:
                                    best_buy = (drift, oid, price)
                            else:
                                if best_sell is None or drift < best_sell[0]:
                                    best_sell = (drift, oid, price)
                        else:
                            log(f"[FARM-004f] cancel (out of threshold) {label} "
                                f"drift={drift:.4f} > thr={requote_thr:.4f} id={oid}")
                            cancel_quotes(c, (oid,))
                    # Cancel ALL other orders per side (even within threshold),
                    # keep only the closest one per side
                    for o in live:
                        oid = o.get("id") or o.get("order_id")
                        side = o.get("side")
                        price = float(o.get("price"))
                        is_adopted = False
                        if side == "BUY" and best_buy is not None:
                            if oid == best_buy[1]:
                                adopted_ids.append(oid)
                                log(f"[FARM-004f] adopted BUY@{price:.4f} "
                                    f"(best drift={best_buy[0]:.4f}) id={oid}")
                                is_adopted = True
                        elif side == "SELL" and best_sell is not None:
                            if oid == best_sell[1]:
                                adopted_ids.append(oid)
                                log(f"[FARM-004f] adopted SELL@{price:.4f} "
                                    f"(best drift={best_sell[0]:.4f}) id={oid}")
                                is_adopted = True
                        if not is_adopted and oid:
                            log(f"[FARM-004f] cancel (not best) id={oid} side={side} "
                                f"price={price:.4f}")
                            cancel_quotes(c, (oid,))
                    if adopted_ids:
                        st["ids"] = adopted_ids
                        st["center"] = mid   # [FARM-004g B2] prevent immediate requote
                        log(f"[FARM-004f] reseed adopted {len(adopted_ids)} leg(s): {adopted_ids})")
                    else:
                        log(f"[FARM-004f] no legs within threshold — cancel-all, "
                            f" штатная постановка с нуля")
                        # st["ids"] stays None → place_two_sided will post fresh

                # 3a. reconcile book vs memory (F1/F5): orphans, missing legs,
                #     undersized legs, one-sided state.                    [FARM-003]
                rec = reconcile_orders(c, token, st, float(mkt["min_size"]), mid)
                if rec["one_sided"]:
                    log(f"[reconcile] ONE-SIDED quoting on {mkt['name']} "
                        f"(1/3 reward score), inv={st['inv']}")

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
                # [FARM-004] drift_c hoisted out of the requote branch below: the
                # HARD-DRIFT alert needs it every tick, not only when be_margin
                # gates a requote. None when no center yet (first tick).
                drift_c = (abs(mid - st["center"]) * 100.0
                           if st["center"] is not None else None)
                need_requote = False
                if st["center"] is None:
                    need_requote = True
                elif fills or rec["force_requote"]:
                    need_requote = True     # eaten/failed/orphan/undersized leg -> restore now
                elif plan is not None and plan.get("skew") != st.get("last_skew", "flat"):
                    need_requote = True     # skew CHANGED -> reposition once
                    # (steady skew must NOT requote every tick — cancel/replace
                    #  each 10s burns the accrued per-minute epoch score)
                elif be_margin is not None and drift_c is not None:
                    if drift_c >= REQUOTE_FRAC * be_margin:
                        need_requote = True

                if need_requote:
                    if st["ids"] is not None:
                        cancel_quotes(c, st["ids"])
                    st["ids"] = place_two_sided(c, mkt, mid, plan=plan, params=params,
                                                inv=st["inv"])
                    st["center"] = mid
                    action = f"REQUOTE (skew={plan.get('skew') if plan else 'flat'})"
                else:
                    action = "HOLD (resting, accruing reward)"
                st["last_skew"] = plan.get("skew") if plan else "flat"

                # ─── [FARM-004] operator edge-alerts (live only; no-op in DRY) ───
                if not DRY_RUN and st["ids"] is not None:
                    # A. ONE-SIDED: onset/recovery with Russian texts (#1/#6), latch persisted.
                    # Guard: don't fire (or overwrite latch) until daemon has placed legs this run.
                    mkt_min_sz = float(mkt.get("min_size", 0))
                    inv_val = st.get("inv")
                    inv_txt = f"{inv_val:.2f}" if inv_val is not None else "n/a"
                    edge_notify(
                        f"one_sided:{token}", rec["one_sided"],
                        f"🟡 Одна сторона ({mkt['name']}) / Котирую только BID. "
                        f"Reward ⅓. / Inventory: {inv_txt} / {mkt_min_sz:.0f} YES",
                        f"🟢 Обе стороны ({mkt['name']}) / BID + ASK активны. Полный reward.",
                        cooldown=1800)

                    # B. SCORING-LOST: legs alive but outside reward corridor (#2), cooldown=0.
                    #    Only checked on a settled book (both legs tracked, no requote this tick).
                    _legs = [x for x in (st["ids"] or ())
                             if x and not str(x).startswith("dry_")]
                    if not need_requote and len(_legs) == 2:
                        try:
                            results = [c.is_order_scoring(OrderScoringParams(orderId=oid))
                                       for oid in _legs]
                            bid_scoring = (results[0].get("scoring", False)
                                          if results and len(results) > 0 else False)
                            ask_scoring = (results[1].get("scoring", False)
                                          if results and len(results) > 1 else False)
                            not_scoring = not (bid_scoring and ask_scoring)
                            edge_notify(
                                f"scoring:{token}", not_scoring,
                                f"🔴 Скоринг потерян ({mkt['name']}) / "
                                f"Ордера в книге, вне reward-зоны. / "
                                f"BID: {'✓' if bid_scoring else '✗'} · ASK: {'✓' if ask_scoring else '✗'}",
                                f"[OK] scoring restored on {mkt['name']}",
                                cooldown=0)
                        except Exception as e:
                            throttled_log(f"scoring_chk_err:{token}",
                                          f"[scoring-alert] check failed (raw): {e}",
                                          seconds=600)

                    # C. HARD-DRIFT: mid this far from center (#3), cooldown=0.
                    if drift_c is not None:
                        edge_notify(
                            f"drift:{token}", drift_c >= 3.0,
                            f"⚠️ Ордер оторвался от цены ({mkt['name']}) / "
                            f"Сдвиг {drift_c:.1f}c, requote не сработал.",
                            f"[OK] drift settled on {mkt['name']} ({drift_c:.1f}c)",
                            cooldown=0)

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

            save_state_file(state)           # [FARM-003] persist cursors (atomic)
            heartbeat(ready=(tick_n == 1))   # [NEW] systemd watchdog ping (variant B)
            time.sleep(POLL_INTERVAL)

        except Exception as e:
            log(f"ERROR (raw, not auto-fixed): {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
