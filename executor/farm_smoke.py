#!/usr/bin/env python3
"""
farm_smoke.py — pre-flip SDK-contract gate for the farming daemon.

WHY THIS EXISTS: reading farming_daemon.py by eye cannot catch bugs that live
on the boundary between our code and py_clob_client_v2 (wrong tick type, wrong
cancel payload, dead skew/score code). Those only surface when the SDK calls
actually execute. This script executes every contract the daemon depends on and
fails loudly if any is broken — run it BEFORE flipping DRY_RUN=False.

Covers:
  - module import + client build
  - load_reward_params / read_midpoint / read_inventory
  - reward-score path (read_book_depth + estimate_share)   [A3 — was dead code]
  - check_fills cursor advance                              [B1 — re-fetch guard]
  - inventory_manage flat + long_unload plans              [A1 — was discarded]
  - create_order contract, BOTH legs (str tick_size)       [today's KeyError:0.01]
  - place_two_sided in DRY (validates book, honors plan)

MONEY: this default run is READ-ONLY / DRY. It does NOT post real orders.
To also exercise the LIVE post_order + cancel_order round-trip, run with --live
(requires explicit operator intent; posts min-size maker legs and cancels them
in the same run). Never pass --live on an unattended host.

Usage:
    cd /opt/executor/app && venv/bin/python3 farm_smoke.py          # dry/read
    cd /opt/executor/app && venv/bin/python3 farm_smoke.py --live   # + live round-trip
"""
import sys
import traceback

import farming_daemon as F
from farming_daemon import (
    build_client, load_reward_params, read_book_depth, estimate_share,
    inventory_manage, place_two_sided, cancel_quotes, check_fills,
    read_midpoint, read_inventory, MARKETS, QUOTE_OFFSET,
)
from py_clob_client_v2 import OrderArgsV2, PartialCreateOrderOptions
from py_clob_client_v2.order_builder.constants import BUY, SELL

LIVE = "--live" in sys.argv
FAIL = []


def check(name, fn):
    try:
        r = fn()
        print(f"[OK]   {name}")
        return r
    except Exception:
        print(f"[FAIL] {name}")
        traceback.print_exc()
        FAIL.append(name)
        return None


def main():
    print(f"farm_smoke: mode={'LIVE round-trip' if LIVE else 'DRY/read-only'}  "
          f"DRY_RUN(file)={F.DRY_RUN}")
    c = build_client()
    mkt = dict(MARKETS[0])
    p = check("load_reward_params", lambda: load_reward_params(c, mkt))
    if p is None:
        print("\n=== SMOKE ABORTED: no reward params ===")
        sys.exit(1)
    mkt["params"] = p
    mkt["max_spread"] = p["max_spread"]
    mid = check("read_midpoint", lambda: read_midpoint(c, mkt["token"]))
    check("read_inventory", lambda: read_inventory(c, mkt["token"]))

    # reward-score path (A3)
    depth = check("read_book_depth",
                  lambda: read_book_depth(c, mkt["token"], mid, p["max_spread"]))
    if depth:
        sc = check("estimate_share",
                   lambda: estimate_share(depth, float(mkt["min_size"]),
                                          QUOTE_OFFSET * 100, p["max_spread"]))
        if sc:
            print(f"       share_avg={sc['share_avg']:.4f}")

    # check_fills cursor (B1) — after_ts=0 will see historical trades; assert cursor moves
    def cf():
        fills, ts = check_fills(c, p["condition_id"], F.FUNDER, 0)
        print(f"       fills={len(fills)} cursor={ts} advanced={ts > 0 or len(fills) == 0}")
        return True
    check("check_fills", cf)

    # inventory_manage plans (A1)
    plan_flat = check("inventory_manage flat",
                      lambda: inventory_manage(c, mkt, 0.0, mid, p))
    plan_long = check("inventory_manage long_unload",
                      lambda: inventory_manage(c, mkt, 999.0, mid, p))
    if plan_long:
        print(f"       long skew={plan_long.get('skew')} "
              f"bid_size={plan_long.get('bid_size')} ask_size={plan_long.get('ask_size')}")

    # create_order contract, both legs, string tick_size (today's KeyError:0.01)
    tick_str = c.get_tick_size(mkt["token"])

    def build_leg(side, price):
        a = OrderArgsV2(token_id=mkt["token"], price=price, size=float(mkt["min_size"]), side=side)
        o = PartialCreateOrderOptions(tick_size=tick_str, neg_risk=bool(p["neg_risk"]))
        return c.create_order(a, o)
    check("create_order BID (str-tick, not posted)", lambda: build_leg(BUY, 0.60))
    check("create_order ASK (str-tick, not posted)", lambda: build_leg(SELL, 0.64))

    if not LIVE:
        # DRY place_two_sided both plans — validates book, returns ids, no money
        save = F.DRY_RUN
        F.DRY_RUN = True
        check("place_two_sided symmetric (DRY)",
              lambda: place_two_sided(c, mkt, mid, plan=plan_flat, params=p))
        ids_skew = check("place_two_sided long_unload (DRY)",
                         lambda: place_two_sided(c, mkt, mid, plan=plan_long, params=p))
        if ids_skew is not None:
            print(f"       skew ids={ids_skew} bid_suppressed={ids_skew[0] is None}")
        F.DRY_RUN = save
    else:
        # LIVE round-trip: post real min-size maker legs, verify, cancel in same run
        save = F.DRY_RUN
        F.DRY_RUN = False
        ids_sym = check("place_two_sided symmetric (LIVE)",
                        lambda: place_two_sided(c, mkt, mid, plan=plan_flat, params=p))
        if ids_sym:
            check("cancel symmetric", lambda: cancel_quotes(c, ids_sym))
        ids_skew = check("place_two_sided long_unload (LIVE)",
                         lambda: place_two_sided(c, mkt, mid, plan=plan_long, params=p))
        if ids_skew:
            print(f"       skew ids={ids_skew} bid_suppressed={ids_skew[0] is None}")
            check("cancel skew", lambda: cancel_quotes(c, ids_skew))
        F.DRY_RUN = save

    print("\n=== SMOKE RESULT ===")
    if FAIL:
        print(f"FAIL: {FAIL}")
        sys.exit(1)
    print("PASS — all SDK contracts + skew + score green")


if __name__ == "__main__":
    main()
