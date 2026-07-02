#!/usr/bin/env python3
"""
check_scoring.py — read-only reward-scoring verifier for the farming daemon.

For every OPEN order on the target market (Account 2 / Justfuuun), report:
  - distance from mid (cents) and whether it sits inside the reward corridor
    (our local calc: dist <= max_spread), AND
  - Polymarket's OWN verdict via is_order_scoring() — the authoritative answer
    to "is this order currently earning liquidity rewards?".

READ-ONLY: places/cancels nothing, moves no money. Safe to run anytime,
including while the live daemon is resting.

Usage:
    cd /opt/executor/app && venv/bin/python3 check_scoring.py
"""
import farming_daemon as F
from farming_daemon import build_client, load_reward_params, read_midpoint, MARKETS
from py_clob_client_v2.clob_types import OrderScoringParams


def main():
    c = build_client()
    for m in MARKETS:
        mkt = dict(m)
        p = load_reward_params(c, mkt)
        if p is None:
            print(f"[{mkt['name']}] params unavailable — skip")
            continue
        mid = read_midpoint(c, mkt["token"])
        ms = p["max_spread"]  # reward corridor half-width, cents
        print(f"\n=== {mkt['name']} ===")
        print(f"mid={mid:.4f}  max_spread={ms}c  condition_id={p['condition_id'][:12]}...")
        print("-" * 66)

        orders = c.get_open_orders() or []
        mine = [o for o in orders
                if o.get("asset_id") == mkt["token"]
                or o.get("market") == p["condition_id"]]
        if not mine:
            print("NO open orders for this market.")
            continue

        for o in mine:
            side = o.get("side")
            price = float(o.get("price"))
            orig = o.get("original_size") or o.get("size")
            matched = o.get("size_matched", 0)
            oid = o.get("id") or o.get("order_id")
            dist_c = abs(price - mid) * 100
            in_corr = "IN " if dist_c <= ms else "OUT"
            try:
                scoring = c.is_order_scoring(OrderScoringParams(orderId=oid))
            except Exception as e:
                scoring = f"(check failed: {e})"
            print(f"{side:4} @ {price:.2f}  dist={dist_c:.2f}c  size={orig} matched={matched}")
            print(f"       corridor_calc={in_corr}  |  polymarket_scoring={scoring}")


if __name__ == "__main__":
    main()
