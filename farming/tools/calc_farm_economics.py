#!/usr/bin/env python3
"""FARM tool: economics calculator — до какого размера выгодно вкладываться.

Usage:
    python3 calc_farm_economics.py <token_id> [--sizes 50,100,200,300,400,600,800]
                                              [--offset-cents X]
                                              [--our-bid P SIZE]
                                              [--our-ask P SIZE]
                                              [--compare-history]

    --compare-history: подтянуть реальный reward_usd из farming_daily_snapshot
    для этого token_id (если рынок уже трекался) и вывести рядом с моделью.
    Если рынок УЖЕ активно фармится тобой — resting-ордера уже сидят в книге
    и попадают в comp_pts как "конкурент". Передай --our-bid/--our-ask с
    реальными price/size своих ордеров, иначе цифры искажены.

ЛОГИКА (upper-bound модель):
    score(order)  = size * ((max_spread - dist_cents) / max_spread)^2
    comp_pts      = min(bid_pts, ask_pts) + abs(bid_pts - ask_pts) / 3.0
                    (paired two-sided + excess/3 как upper bound)
    our_pts       = size * score_factor
    share         = our_pts / (comp_pts + our_pts)
    our_daily_usd = share * pool

    Размещение ноги по умолчанию: dist = DEFAULT_DIST_CENTS = 2c — это реальный
    QUOTE_OFFSET демона (executor/farming_daemon.py:59, symmetric/flat-план в
    inventory_manage(), ~строка 1071), фиксированная константа независимо от
    max_spread конкретного рынка. НЕ оценка по текущему spread книги (была
    dist=min(spread/2, max_spread*0.9) до FARM-051 — модель предполагала, что
    демон подходит к миду почти вплотную, что для узких спредов сильно
    завышало score_factor и прогноз $/день). Переопределяется --offset-cents.
    Если override не передан и max_spread рынка < 4×DEFAULT_DIST_CENTS (узкий
    спред-режим наград) — скрипт печатает предупреждение: расхождение
    модель/реальность на таких рынках сильнее обычного.

    --our-bid/--our-ask вычитают квадратичный score наших ордеров
    из соответствующей стороны книги ДО расчёта comp_pts.

Капитал: BID-нога = size*mid pUSD + ASK-нога = size шер (оценка size*mid).
Деградация: marginal $/day на каждый добавленный $100 капитала падает —
таблица показывает, где прирост перестаёт окупаться.

МОДЕЛЬ: upper-bound на МОМЕНТ снятия снепшота книги — uptime, PAUSE-эпизоды
и внутридневной рост конкуренции не учтены. Калибровка по факту (2026-07-17,
6 рынков, только чистые both-дни): разброс факт/потолок 13%-65% — единого
коэффициента НЕ существует (конкурентная книга и pool меняются день ото дня).
На одном рынке (Raquel Lyra) факт даже ПРЕВЫСИЛ потолок на 16% после вычета
своих ордеров — модель может как переоценивать, так и недооценивать.
НЕ применяй фиксированный множитель к результату. Используй --compare-history
для факта по конкретному токену; без истории — это потолок, не прогноз.

Read-only, без SDK: raw urllib с User-Agent (паттерн S1).
"""
import json
import os
import sys
import urllib.request

CLOB = "https://clob.polymarket.com"
UA = {"User-Agent": "Mozilla/5.0 (farm-econ-calc)"}

DEFAULT_DIST_CENTS = 2.0  # = QUOTE_OFFSET демона в центах (farming_daemon.py:59,
                          # 0.02$ = 2c), symmetric/flat-план. Если QUOTE_OFFSET в
                          # демоне поменяется — обновить и здесь вручную (сознательно
                          # не импортируем демон-код в read-only калькулятор).


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


def leg_dist_cents(ms, offset_override=None, default=DEFAULT_DIST_CENTS):
    """Дистанция нашей ноги от мида (центы) + флаг "узкий max_spread".

    По умолчанию — фиксированный default (реальный QUOTE_OFFSET демона), не
    оценка по текущему spread книги: демон не смотрит на spread при
    symmetric/flat-плане (farming_daemon.py:1071). narrow_warn=True, если
    override не передан и ms < 4*default — на таких рынках расхождение
    модель/реальность сильнее (см. docstring модуля).
    """
    dist = default if offset_override is None else offset_override
    dist = max(0.0, min(dist, ms))
    narrow_warn = offset_override is None and ms < 4 * default
    return dist, narrow_warn


def fetch_history(token_id):
    """Факт из farming_daily_snapshot для token_id (только both-дни).
    None при недоступности БД — не валит скрипт (сохраняет read-only-без-SDK дух)."""
    try:
        import psycopg2
    except ImportError:
        return None
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:password@localhost:5433/polymarket"
    )
    try:
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        cur.execute(
            "SELECT snap_date, inv, capital_usd, reward_usd FROM farming_daily_snapshot "
            "WHERE token = %s AND legs_state = %s ORDER BY snap_date DESC LIMIT 14",
            (token_id, "both")
        )
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"[fetch_history warning] БД недоступна или ошибка запроса: {e}", file=sys.stderr)
        return None


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    token_id = args[0]
    sizes = [50, 100, 150, 200, 300, 400, 600, 800, 1200]
    offset_override = None
    our_bid_price, our_bid_size = None, None
    our_ask_price, our_ask_size = None, None
    compare_history = False

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
        elif args[i] == "--compare-history":
            compare_history = True
            i += 1
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

    dist, narrow_warn = leg_dist_cents(ms, offset_override)
    score_factor = ((ms - dist) / ms) ** 2

    q = m.get("question") or m.get("market_slug") or cid
    print(f"\nРынок: {q}")
    print(f"condition_id: {cid}")
    print(f"mid={mid:.4f}  spread={spread_c:.2f}c  max_spread={ms}c  "
          f"pool=${pool:.2f}/день")
    print(f"Книга в окне награды: bid_pts={bid_pts:.0f} (${bid_depth:.0f})  "
          f"ask_pts={ask_pts:.0f} (${ask_depth:.0f})  -> comp_pts={comp_pts:.0f}")
    print(f"Наша нога: dist={dist:.2f}c от мида, score_factor={score_factor:.3f}")
    if narrow_warn:
        print(f"⚠ узкий max_spread={ms:.1f}c (< {4*DEFAULT_DIST_CENTS:.0f}c = "
              f"4×дефолтный offset={DEFAULT_DIST_CENTS:.0f}c) — модель может "
              f"разойтись с реальностью сильнее обычного, см. docstring")
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

    if compare_history:
        hist = fetch_history(token_id)
        print()
        if hist:
            print("История факта (farming_daily_snapshot, legs_state=both):")
            print("{:>12} | {:>8} | {:>8} | {:>10}".format("дата", "inv", "капитал", "reward_usd"))
            total = 0.0
            for snap_date, inv, cap, rew in hist:
                inv_v = float(inv) if inv is not None else 0.0
                cap_v = float(cap) if cap is not None else 0.0
                rew_v = float(rew) if rew is not None else 0.0
                print("{:>12} | {:>8.1f} | {:>8.1f} | {:>10.2f}".format(str(snap_date), inv_v, cap_v, rew_v))
                total += rew_v
            avg = total / len(hist)
            print("Среднее за {} дн.: ${:.2f}/день (сверь с близким по inv размером в таблице выше)".format(len(hist), avg))
        else:
            print("История в БД не найдена (рынок новый или БД недоступна) - "
                  "ориентируйся на диапазон 13-65% (медиана ~34%, см. МОДЕЛЬ в docstring), "
                  "с осторожностью: разброс большой, это не прогноз.")


if __name__ == "__main__":
    main()
