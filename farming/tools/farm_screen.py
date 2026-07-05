import json, time, urllib.request

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read())

markets, cursor = [], ""
while True:
    url = "https://clob.polymarket.com/sampling-markets"
    if cursor: url += f"?next_cursor={cursor}"
    d = get(url)
    markets += d.get("data", [])
    cursor = d.get("next_cursor", "LTE=")
    if cursor in ("LTE=", "", None): break
print(f"total sampling markets: {len(markets)}")

cand = []
for m in markets:
    r = m.get("rewards") or {}
    rates = r.get("rates") or []
    pool = sum(x.get("rewards_daily_rate", 0) for x in rates)
    toks = m.get("tokens") or []
    if pool < 30 or not toks: continue
    p = toks[0].get("price") or 0
    if not (0.10 <= p <= 0.90): continue
    end = m.get("end_date_iso") or ""
    if end and end < "2026-08-04": continue
    cand.append({"q": m.get("question","")[:60], "token": toks[0]["token_id"],
                 "pool": pool, "mid_snap": p, "max_spread": r.get("max_spread", 3.5),
                 "min_size": r.get("min_size", 0), "tick": m.get("minimum_tick_size"),
                 "end": end[:10]})
cand.sort(key=lambda x: -x["pool"])
cand = cand[:40]
print(f"phase A candidates: {len(cand)}")

for c in cand:
    try:
        b = get(f"https://clob.polymarket.com/book?token_id={c['token']}")
        mid = float(get(f"https://clob.polymarket.com/midpoint?token_id={c['token']}")["mid"])
        ms = float(c["max_spread"]) / 100.0
        pts = 0.0
        for side in ("bids", "asks"):
            for lvl in b.get(side, []):
                s = abs(float(lvl["price"]) - mid)
                if s < ms:
                    pts += ((ms - s) / ms) ** 2 * float(lvl["size"])
        c["mid"] = round(mid, 3)
        c["pts_k"] = round(pts / 1000, 1)
        c["usd_per_kpts"] = round(c["pool"] / (pts / 1000), 2) if pts > 0 else None
    except Exception as e:
        c["usd_per_kpts"] = None
        c["err"] = str(e)[:40]
    time.sleep(0.4)

cand = [c for c in cand if c.get("usd_per_kpts")]
cand.sort(key=lambda x: -x["usd_per_kpts"])
print(f"\n{'$/1kpts':>8} {'pool':>6} {'pts(k)':>8} {'mid':>6} {'tick':>6} {'min':>4} {'end':>11}  question")
for c in cand[:25]:
    print(f"{c['usd_per_kpts']:>8} {c['pool']:>6.0f} {c['pts_k']:>8} {c['mid']:>6} "
          f"{str(c['tick']):>6} {c['min_size']:>4} {c['end']:>11}  {c['q']}")
json.dump(cand, open("/tmp/farm_screen_result.json","w"))
print("\nsaved: /tmp/farm_screen_result.json")
