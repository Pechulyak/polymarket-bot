#!/usr/bin/env python3
"""
Farming market screener v4 (S1 analytics tool, NOT the daemon — LIVE-006 N/A).
Реализует воронку FARMING_MARKET_CRITERIA.md Слой 0-3.

v4 изменения против v3 (пересмотр целевой функции + Gamma Phase A):
  - [МЕТРИКА] Сортировка по our_daily (доход НАШИХ our_size шер), НЕ по
    usd_per_kpts (средняя доходность книги). Дефект 1: средняя завышает толстые
    книги, где наша предельная доля -> 0 (Bardella-ловушка). our_share =
    our_pts/(book_pts+our_pts), our_daily = our_share × pool.
  - [OFFSET B] our_pts считается при ноге у best_bid/best_ask (s=spread/2),
    не у mid — честная достижимая позиция, не идеальная.
  - [Phase A = Gamma] /sampling-markets + /book->cid->/markets цепочка заменена
    ОДНИМ Gamma-вызовом /markets. Reward-поля (clobRewards[], rewardsMinSize,
    rewardsMaxSpread, mid, neg_risk, end) приходят пачкой. Верифицировано
    разведкой 05.07: clobRewards[].rewardsDailyRate == веб-REWARD ($21 Netanyahu).
  - [POOL fix] pool = sum(clobRewards[].rewardsDailyRate) — массив, не rates[0].
    Закрыт хвост sum vs rates[0] (v3 market_meta брал rates[0], Phase A — sum;
    расхождение устранено, везде sum).
  - [POOL_MIN 30->15] our_daily теперь сам фильтрует мелочь по нашей доле,
    grubый pool-порог больше не нужен (Дефект 2: pool ≠ farmability).
  - [ФИЛЬТР] клоб-рынки берутся по clobRewards active, НЕ сортируются по volume
    (volume тянет наверх WC/US×Iran-класс = adverse-selection ловушка, Дефект 3).

  usd_per_kpts сохранён в выводе как справочная колонка (диагностика толщины).
Вывод НЕ выносит вердиктов — сырые метрики + флаги. Отбор за оператором.
READ-ONLY: только GET-запросы (Gamma + публичный CLOB). Ордеров/записи нет.
"""
import json, time, urllib.request, urllib.error, urllib.parse, re, sys
from datetime import datetime, timezone, timedelta

CLOB  = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
UA = {"User-Agent": "Mozilla/5.0"}

# ── пороги воронки (константы вверху — менять без правки логики) ──
POOL_MIN        = 5            # our_daily фильтрует сам; впускаем микропулы (мем-рынки)
MID_LO, MID_HI  = 0.10, 0.90   # Слой1 гейт7: хвосты отсечь
MIN_DAYS        = 30           # Слой0 гейт3: end > now + этого
TOP_N_BY_POOL   = 40           # phase A: топ по пулу под live-book scoring
TICK_REQUIRED   = "0.01"       # Слой0 гейт2: только 1¢, 0.1¢ = пенни-война
MAXSPREAD_MIN   = 3.0          # Слой1 гейт5: max_spread ниже -> нога без запаса
DOLLAR_PER_DAY_MIN = 1.0       # Слой1 гейт6: reward ниже порога не платится
MV2C_MAX        = 8            # Слой3: >N движений≥2¢/нед = волатилен -> вон (adverse)
PTS_K_MIN       = 0.5          # Слой3: книга тоньше = мёртвый рынок -> вон (не флаг)
OUR_SIZE        = int(sys.argv[1]) if len(sys.argv) > 1 else 300  # нога: argv[1] или 300
GAMMA_PAGE      = 100          # Gamma режет страницу на 100 (не 500)
GAMMA_PAGES     = 5            # страниц на окно ликвидности (100×5=500 верх)
LIQ_WINDOWS     = [(0, 5000), (5000, 20000), (20000, 50000), (50000, None)]  # FARM-018: None = без верха
SHOW_N          = 30           # сколько строк вывести

def get(url, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=15).read())
        except Exception as e:
            last = e
            time.sleep(0.6)
    raise last


# ── underlying-группировка (гейт 15): один underlying = максимум один рынок ──
# Флаг для оператора, НЕ автоотсев. Ключевые слова -> группа.
GROUP_PATTERNS = [
    ("FED",     re.compile(r"\bfed\b|interest rate|rate hike|fomc", re.I)),
    ("IRAN",    re.compile(r"\biran\b|hormuz|tehran|nuclear deal", re.I)),
    ("FRANCE27",re.compile(r"french presidential|bardella|philippe|le pen", re.I)),
    ("BRAZIL26",re.compile(r"brazilian presidential|lula|bolsonaro", re.I)),
    ("NETANYAHU",re.compile(r"netanyahu|israel.*pm|next.*prime minister.*israel", re.I)),
]
def underlying_group(q):
    for name, pat in GROUP_PATTERNS:
        if pat.search(q):
            return name
    return ""


def moves_and_range(token, ms_cents):
    """[Слой3] /prices-history 1w fidelity=60 -> (moves>=2c count, range7d cents).
    moves2c = число межточечных дельт >= 2c за окно (прокси волатильности/adverse).
    range7d = (max-min)*100 за окно. None-safe: (None,None) при сбое."""
    try:
        url = (f"{CLOB}/prices-history?market={token}"
               f"&interval=1w&fidelity=60")
        d = get(url)
        pts = d.get("history") or []
        prices = [float(p["p"]) for p in pts if "p" in p]
        if len(prices) < 2:
            return None, None
        moves2c = sum(1 for i in range(1, len(prices))
                      if abs(prices[i] - prices[i-1]) * 100.0 >= 2.0)
        rng = (max(prices) - min(prices)) * 100.0
        return moves2c, round(rng, 2)
    except Exception:
        return None, None


# ─────────────────────── PHASE A: Gamma /markets + hard-гейты ───────────────────────
# Один Gamma-вызов отдаёт reward-поля пачкой (clobRewards[], rewardsMinSize,
# rewardsMaxSpread, bestBid/bestAsk, negRisk, endDate). Заменяет цепочку
# /sampling-markets -> /book -> cid -> /markets. Верифицировано разведкой 05.07.
def gamma_markets():
    """Тянет reward-рынки диапазонами ликвидности (LIQ_WINDOWS), order=liquidityNum
    asc + пагинация — ловит ВЕСЬ диапазон, включая хвост 20-50k (Streeting liq=37k,
    терялся при кумулятивном max без сортировки). volume-order выкинут (топил
    толстые US-Iran). Дедуп по conditionId между окнами."""
    out, seen = [], set()
    for lo, hi in LIQ_WINDOWS:
        for page in range(GAMMA_PAGES):
            p = {"closed": "false", "limit": GAMMA_PAGE,
                 "offset": page * GAMMA_PAGE,
                 "liquidity_num_min": lo,
                 "order": "liquidityNum", "ascending": "true"}
            if hi is not None:                     # FARM-018: окно 50k+ без max
                p["liquidity_num_max"] = hi
            qs = urllib.parse.urlencode(p)
            d = get(f"{GAMMA}/markets?{qs}")
            if not d:
                break
            for m in d:
                cid = m.get("conditionId")
                if cid and cid not in seen:
                    seen.add(cid); out.append(m)
            if len(d) < GAMMA_PAGE:
                break
    return out

def pool_from_clobrewards(cr):
    """pool = sum(clobRewards[].rewardsDailyRate). Массив, не rates[0].
    Несколько reward-программ на рынке -> суммируются."""
    if not cr:
        return 0.0
    return sum(float(x.get("rewardsDailyRate", 0) or 0) for x in cr)

gm = gamma_markets()
print(f"total gamma markets pulled: {len(gm)}")

cutoff = (datetime.now(timezone.utc) + timedelta(days=MIN_DAYS)).strftime("%Y-%m-%d")
cand = []
skipped = {"no_reward": 0, "pool": 0, "no_book": 0, "mid": 0, "end_empty": 0,
           "end_soon": 0, "tick": 0, "maxspread": 0, "no_token": 0}
for m in gm:
    cr = m.get("clobRewards") or []
    # [ФИЛЬТР] только рынки с активной reward-программой (не сорт по volume)
    if not cr:
        skipped["no_reward"] += 1; continue
    pool = pool_from_clobrewards(cr)
    if pool < POOL_MIN:
        skipped["pool"] += 1; continue
    if not (m.get("enableOrderBook") and m.get("acceptingOrders")):
        skipped["no_book"] += 1; continue
    bb, ba = m.get("bestBid"), m.get("bestAsk")
    if bb is None or ba is None:
        skipped["no_book"] += 1; continue
    mid = (float(bb) + float(ba)) / 2.0
    if not (MID_LO <= mid <= MID_HI):
        skipped["mid"] += 1; continue
    end = m.get("endDate") or ""
    if not end:
        skipped["end_empty"] += 1; continue
    if end[:10] < cutoff:
        skipped["end_soon"] += 1; continue
    # tick: Gamma orderPriceMinTickSize (fallback — пропустить гейт, live /book уточнит)
    tick = str(m.get("orderPriceMinTickSize") or TICK_REQUIRED)
    if tick != TICK_REQUIRED:
        skipped["tick"] += 1; continue
    ms = m.get("rewardsMaxSpread")
    if ms is not None and float(ms) < MAXSPREAD_MIN:
        skipped["maxspread"] += 1; continue
    # token_id: Gamma clobTokenIds — строка "[\"tok1\",\"tok2\"]" (YES первый)
    ctok = m.get("clobTokenIds")
    try:
        toks = json.loads(ctok) if isinstance(ctok, str) else (ctok or [])
    except Exception:
        toks = []
    if not toks:
        skipped["no_token"] += 1; continue
    cand.append({"q": (m.get("question") or "")[:60],
                 "token": toks[0],
                 "pool": pool, "mid_snap": round(mid, 3),
                 "max_spread": float(ms) if ms is not None else None,
                 "min_size": m.get("rewardsMinSize") or 0, "tick": tick,
                 "neg_risk": m.get("negRisk"),
                 "condition_id": m.get("conditionId"),
                 # [v4.9] rebate/holding: rebate только на feesEnabled-рынках
                 "fees_enabled": m.get("feesEnabled"),
                 "fee_type": m.get("feeType"),
                 "holding": m.get("holdingRewardsEnabled"),
                 "end": end[:10]})
print(f"phase A filter skips: {skipped}")
cand.sort(key=lambda x: -x["pool"])
cand = cand[:TOP_N_BY_POOL]
print(f"phase A candidates: {len(cand)}")

# ─────────────────── PHASE B: live-book our_share/our_daily + Слой3 ───────────────────
# book_pts = квадратичный score всей книги в reward-зоне.
# our_pts  = score НАШЕЙ ноги OUR_SIZE при offset B (s=spread/2, у best_bid/ask).
# our_share = our_pts/(book_pts+our_pts); our_daily = our_share × pool.
# usd_per_kpts (средняя книги) сохранён справочно — диагностика толщины.
for c in cand:
    try:
        b = get(f"{CLOB}/book?token_id={c['token']}")
        mid = float(get(f"{CLOB}/midpoint?token_id={c['token']}")["mid"])
        ms = float(c["max_spread"]) / 100.0            # max_spread в долях цены
        book_pts = 0.0
        for side in ("bids", "asks"):
            for lvl in b.get(side, []):
                s = abs(float(lvl["price"]) - mid)
                if s < ms:
                    book_pts += ((ms - s) / ms) ** 2 * float(lvl["size"])

        # [OFFSET B'] наша нога ВНУТРИ reward-зоны у её границы.
        # На тонкой книге spread > ms -> нога у best_bid падает ВНЕ зоны (our_pts=0).
        # Farm-механика: встать на min(spread/2, ms*0.9) от mid — максимально близко
        # к mid, что зона позволяет. book spread из /midpoint +/- half-spread недоступен;
        # берём best_bid/best_ask из /price (не bids[0] — то дно книги на тонких).
        try:
            bp = get(f"{CLOB}/price?token_id={c['token']}&side=buy")
            sp = get(f"{CLOB}/price?token_id={c['token']}&side=sell")
            best_bid = float(bp["price"]); best_ask = float(sp["price"])
            spr = abs(best_ask - best_bid)
        except Exception:
            spr = ms * 2  # fallback: считаем спред = ширине зоны
        s_our = min(spr / 2.0, ms * 0.9)   # внутри зоны, у границы если книга шире
        our_pts = ((ms - s_our) / ms) ** 2 * OUR_SIZE if s_our < ms else 0.0
        # [гейт пустой книги] book_pts=0 -> НЕ our_share=1.0 (ложный максимум).
        # Пустая книга = нет контрагентов = мёртвый рынок, а не монополия.
        # first taker метёт ногу, adverse >> pool. Флаг ☠, our_share=None (ранг вниз).
        if book_pts <= 0:
            our_share = None
            c["dead_book"] = True
        else:
            our_share = our_pts / (book_pts + our_pts)
            c["dead_book"] = False

        c["mid"] = round(mid, 3)
        c["pts_k"] = round(book_pts / 1000, 1)
        c["our_share"] = round(our_share, 6) if our_share is not None else None
        c["our_daily"] = round(our_share * c["pool"], 2) if our_share is not None else None
        c["usd_per_kpts"] = round(c["pool"] / (book_pts / 1000), 2) if book_pts > 0 else None
    except Exception as e:
        c["our_daily"] = None
        c["err"] = str(e)[:40]
    # [Слой3] волатильность (прокси adverse-selection)
    mv, rng = moves_and_range(c["token"], c["max_spread"])
    c["moves2c"] = mv
    c["range7d"] = rng
    # [гейт6] $1/д порог по НАШЕМУ доходу (не по среднему пулу)
    od = c.get("our_daily")
    c["below_1usd"] = (od is not None and od < DOLLAR_PER_DAY_MIN)
    # [гейт15] underlying-группа (флаг, не отсев)
    c["group"] = underlying_group(c["q"])
    time.sleep(0.4)

dead_ct = sum(1 for c in cand if c.get("dead_book"))
cand = [c for c in cand if c.get("our_daily") is not None]
# [Слой3 отсечка] волатильные (mv2c>MAX) и мёртво-тонкие (pts_k<MIN) — ВОН до сортировки.
# our_share растёт на тонкой книге ровно там, где adverse максимален -> отсекаем.
pre = len(cand)
vol_ct = sum(1 for c in cand if (c.get("moves2c") or 0) > MV2C_MAX)
thin_ct = sum(1 for c in cand if (c.get("pts_k") or 0) < PTS_K_MIN)
cand = [c for c in cand
        if (c.get("moves2c") or 0) <= MV2C_MAX and (c.get("pts_k") or 0) >= PTS_K_MIN]
cand.sort(key=lambda x: -x["our_daily"])

# ─────────────────────────────── ВЫВОД ───────────────────────────────
# Ведущая метрика: our_$/d (доход НАШИХ OUR_SIZE шер). share = наша доля книги.
# usd/kpts = средняя книги (справочно). pts_k≈0 = тонкая книга (⚠, гейт11).
# below $1/d (гейт6) по НАШЕМУ доходу -> флаг ✗.
hdr = (f"{'our$/d':>7} {'share':>6} {'pool':>6} {'usd/kp':>7} {'pts_k':>7} "
       f"{'mv2c':>5} {'rng7':>6} {'mid':>6} {'min':>4} {'ms':>4} {'nr':>3} {'fee':>4} {'hld':>4} "
       f"{'group':>9} {'end':>11}  question")
print("\n" + hdr)
print("-" * len(hdr))
for c in cand[:SHOW_N]:
    thin = "⚠" if (c.get("pts_k") or 0) < 0.5 else " "
    lowd = "✗" if c.get("below_1usd") else " "
    mv = c.get("moves2c");  mv_s = str(mv) if mv is not None else "n/a"
    rng = c.get("range7d"); rng_s = f"{rng:.1f}" if rng is not None else "n/a"
    nr = c.get("neg_risk"); nr_s = "Y" if nr is True else ("N" if nr is False else "?")
    upk = c.get("usd_per_kpts"); upk_s = f"{upk:.1f}" if upk is not None else "n/a"
    print(f"{c['our_daily']:>6.2f}{lowd}{c['our_share']:>8.5f} {c['pool']:>6.0f} "
          f"{upk_s:>7} {c['pts_k']:>7}{thin}{mv_s:>4} {rng_s:>6} {c['mid']:>6} "
          f"{c['min_size']:>4} {str(c['max_spread']):>4} {nr_s:>3} "
          f"{'Y' if c.get('fees_enabled') is True else ('N' if c.get('fees_enabled') is False else '?'):>4} "
          f"{'Y' if c.get('holding') is True else ('N' if c.get('holding') is False else '?'):>4} "
          f"{c.get('group',''):>9} {c['end']:>11}  {c['q']}")

# группы с >1 кандидатом (гейт15 напоминание оператору)
from collections import Counter
gc = Counter(c["group"] for c in cand[:SHOW_N] if c.get("group"))
multi = {g: n for g, n in gc.items() if n > 1}
if multi:
    print(f"\n[гейт15] underlying-группы с >1 рынком (взять МАКС один на группу): {multi}")

json.dump(cand, open("/tmp/farm_screen_result.json", "w"))
print(f"\nsaved: /tmp/farm_screen_result.json ({len(cand)} scored, "
      f"отсеяно: {vol_ct} volatile mv2c>{MV2C_MAX}, {thin_ct} thin pts_k<{PTS_K_MIN})")
print(f"[v4] сортировка по our_daily (нога {OUR_SIZE} шер, offset B'=внутри reward-зоны). "
      f"volatile+thin отсечены жёстко. mv2c/rng7 в выводе для доп-контроля.")
print("Слой3 (moves2c/range7d) в result.json. Вердикты — оператор/аналитик, не скринер.")