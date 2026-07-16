#!/usr/bin/env python3
"""FARM tool: economics calculator — до какого размера выгодно вкладываться.

Usage:
    python3 calc_farm_economics.py <token_id> [--sizes 50,100,200,300,400,600,800]
                                              [--offset-cents X]
                                              [--our-bid P SIZE]
                                              [--our-ask P SIZE]

ЛОГИКА (upper-bound модель):
    score(order)  = size * ((max_spread - dist_cents) / max_spread)^2
    comp_pts      = min(bid_pts, ask_pts) + abs(bid_pts - ask_pts) / 3.0
                    (paired two-sided + excess/3 как upper bound)
    our_pts       = size * score_factor
    share         = our_pts / (comp_pts + our_pts)
    our_daily_usd = share * pool

    Размещение ноги по умолчанию: dist = min(spread/2, max_spread*0.9)
    (offset B'), переопределяется --offset-cents.

    --our-bid/--our-ask вычитают квадратичный score наших ордеров
    из соответствующей стороны книги ДО расчёта comp_pts.

Капитал: BID-нога = size*mid pUSD + ASK-нога = size шер (оценка size*mid).
Деградация: marginal $/day на каждый добавленный $100 капитала падает —
таблица показывает, где прирост перестаёт окупаться.

МОДЕЛЬ: upper-bound — uptime, PAUSE-эпизоды и внутридневной рост
конкуренции не учтены; факт исторически ~0.3–0.4 от прогноза.

Read-only, без SDK: raw urllib с User-Agent (паттерн S1).
"""
import json
import sys
import urllib.request

CLOB = "https://clob.polymarket.com"
UA = {"User-Agent": "Mozilla/5.0 (farm-econ-calc)"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def fetch_market_data(token_id):
    book = get(f"{CLOB}/book?token_id={token_id}")
    condition_id = book.get("market")
    if not condition_id:
        sys.exit("book без поля market (condition_id) — проверь token_id")
    m = get(f"{CLOB}/markets/{condition_id}")
    rewards = m.get("rewards") or {}
    rates = rewards.get("rates") or []
    pool = sum(float(r.get("rewards_daily_rate") or 0) for r in rates)
    max_spread = float(rewards.get("max_spread") or 0)
    mid = get(f"{CLOB}/midpoint?token_id={token_id}")
    mid = float(mid["mid"])
    return book, m, condition_id, pool, max_spread, mid


def side_pts(orders, mid, ms_cents, is_bid):
    """Суммарный quadratic score одной стороны книги в окне max_spread."""
    pts = 0.0
    depth_usd = 0.0
    for o in orders:
        p = float(o["price"])
        s = float(o["size"])
        dist = (mid - p) * 100.0 if is_bid else (p - mid) * 100.0
        if dist < 0 or dist > ms_cents:
            continue
        pts += s * ((ms_cents - dist) / ms_cents) ** 2
        depth_usd += p * s if is_bid else (1.0 - p) * s
    return pts, depth_usd


def our_order_score(price, size, mid, ms_cents, is_bid):
    """Quadratic score одного нашего ордера."""
    dist = (mid - price) * 100.0 if is_bid else (price - mid) * 100.0
    if dist < 0 or dist > ms_cents:
        return 0.0
    return size * ((ms_cents - dist) / ms_cents) ** 2


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    token_id = args[0]
    sizes = [50, 100, 150, 200, 300, 400, 600, 800, 1200]
    offset_override = None
    our_bid_price, our_bid_size = None, None
    our_ask_price, our_ask_size = None, None

    i = 1
    while i < len(args):
        if args[i] == "--sizes" and i + 1 < len(args):
            sizes = [int(x) for x in args[i + 1].split(",")]
            i += 2
        elif args[i] == "--offset-cents" and i + 1 < len(args):
            offset_override = float(args[i + 1])
            i += 2
        elif args[i] == "--our-bid" and i + 2 < len(args):
            our_bid_price = float(args[i + 1])
            our_bid_size = float(args[i + 2])
            i += 3
        elif args[i] == "--our-ask" and i + 2 < len(args):
            our_ask_price = float(args[i + 1])
            our_ask_size = float(args[i + 2])
            i += 3
        else:
            i += 1

    book, m, cid, pool, ms, mid = fetch_market_data(token_id)
    if pool <= 0 or ms <= 0:
        sys.exit(f"Рынок без reward-программы: pool={pool}, max_spread={ms}")

    bids = book.get("bids") or []
    asks = book.get("asks") or []
    bid_pts, bid_depth = side_pts(bids, mid, ms, is_bid=True)
    ask_pts, ask_depth = side_pts(asks, mid, ms, is_bid=False)

    # Вычитаем наши ордера из соответствующей стороны (не ниже 0)
    if our_bid_price is not None and our_bid_size is not None:
        our_bid_score = our_order_score(our_bid_price, our_bid_size, mid, ms, is_bid=True)
        bid_pts = max(0.0, bid_pts - our_bid_score)
        print(f"  [наш BID {our_bid_size}@{our_bid_price} вычтен: -{our_bid_score:.2f} pts]")

    if our_ask_price is not None and our_ask_size is not None:
        our_ask_score = our_order_score(our_ask_price, our_ask_size, mid, ms, is_bid=False)
        ask_pts = max(0.0, ask_pts - our_ask_score)
        print(f"  [наш ASK {our_ask_size}@{our_ask_price} вычтен: -{our_ask_score:.2f} pts]")

    # comp_pts = paired + excess/3 (upper bound)
    comp_pts = min(bid_pts, ask_pts) + abs(bid_pts - ask_pts) / 3.0

    # spread: best bid / best ask (asks приходят по убыванию — best = [-1])
    try:
        best_bid = max(float(o["price"]) for o in bids)
        best_ask = min(float(o["price"]) for o in asks)
        spread_c = (best_ask - best_bid) * 100.0
    except ValueError:
        spread_c = ms  # пустая сторона

    dist = offset_override if offset_override is not None \
        else min(spread_c / 2.0, ms * 0.9)
    dist = max(0.0, min(dist, ms))
    score_factor = ((ms - dist) / ms) ** 2

    q = m.get("question") or m.get("market_slug") or cid
    print(f"\nРынок: {q}")
    print(f"condition_id: {cid}")
    print(f"mid={mid:.4f}  spread={spread_c:.2f}c  max_spread={ms}c  "
          f"pool=${pool:.2f}/день")
    print(f"Книга в окне награды: bid_pts={bid_pts:.0f} (${bid_depth:.0f})  "
          f"ask_pts={ask_pts:.0f} (${ask_depth:.0f})  -> comp_pts={comp_pts:.0f}")
    print(f"Наша нога: dist={dist:.2f}c от мида, score_factor={score_factor:.3f}")
    if min(bid_depth, ask_depth) < 300:
        print("⚠ thin_book: слабая сторона < $300 — против FARM-023 фильтра")
    print()
    hdr = (f"{'шер/нога':>9} | {'капитал~$':>9} | {'$/день':>7} | "
           f"{'$/д на $100':>11} | {'marg $/д':>9} | {'%ср':>5}")
    print(hdr)
    print("-" * len(hdr))
    prev_daily, prev_cap = 0.0, 0.0
    degraded_flag = False
    for s in sizes:
        our_pts = s * score_factor          # min(bid,ask) при равных ногах
        share = our_pts / (comp_pts + our_pts) if (comp_pts + our_pts) > 0 else 0
        daily = share * pool
        cap = 2.0 * s * mid
        per100 = daily / cap * 100.0 if cap > 0 else 0
        marg_daily = daily - prev_daily
        marg_cap = cap - prev_cap
        marg_per100 = marg_daily / marg_cap * 100.0 if marg_cap > 0 else 0
        pct = marg_per100 / per100 * 100.0 if per100 > 0 else 0.0
        note = ""
        if prev_cap > 0 and marg_per100 < per100 * 0.7 and not degraded_flag:
            note = "  <- деградация прироста"
            degraded_flag = True
        print(f"{s:>9} | {cap:>9.0f} | {daily:>7.2f} | {per100:>11.3f} | "
              f"{marg_per100:>9.2f} | {pct:>4.0f}{note}")
        prev_daily, prev_cap = daily, cap
    print("\ncomp_pts = paired + excess/3; собственные ордера вычитайте через --our-bid/--our-ask.")


if __name__ == "__main__":
    main()
