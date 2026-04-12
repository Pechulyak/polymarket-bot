# FIX-002: Category Backfill Optimization — Report

**Date:** 2026-04-06  
**Status:** ✅ COMPLETED  
**Author:** Roo (Code Agent)

---

## Problem Statement

Category backfill запускался каждые **12 часов** — слишком редко для актуальных данных. При 4492 `unknown` записей (17% от общего числа) требовалось ускорить обновление.

---

## Changes Made

### 1. Code Change
**File:** `src/research/whale_detector.py` (line 381)

```python
# Before:
await asyncio.sleep(43200)  # 12 hours

# After:
await asyncio.sleep(7200)  # 2 hours
```

### 2. Container Rebuilt & Restarted
- Image rebuilt: `polymarket-bot-whale-detector:latest`
- Container restarted: `polymarket_whale_detector`

---

## Verification Results

### Before (Initial Snapshot)
```
 market_category |  cnt  | pct  
-----------------+-------+------
 Sports          | 15161 | 57.2
 unknown         |  4492 | 17.0
 Crypto          |  3057 | 11.5
 Politics        |  2945 | 11.1
 Other           |   568 |  2.1
 Weather         |   176 |  0.7
 Economics       |    87 |  0.3
```

### After (Final Snapshot)
```
 market_category |  cnt  | pct  
-----------------+-------+------
 Sports          | 15486 | 57.9
 unknown         |  4444 | 16.6
 Crypto          |  3062 | 11.4
 Politics        |  2946 | 11.0
 Other           |   568 |  2.1
 Weather         |   176 |  0.7
 Economics       |    87 |  0.3
```

### Delta
- **Sports:** +325 rows (15161 → 15486)
- **unknown:** -48 rows (4492 → 4444)
- **Total rows:** 26486

---

## Technical Details

### Backfill Loop Behavior
- **Interval:** 2 hours (changed from 12h)
- **Batch size:** 100 market_ids per iteration
- **Timeout per market:** 10 seconds
- **Rate limit:** 0.5s between API calls

### Logs Confirmed
- `backfill_market_category_updated` — rows successfully updated
- `market_category_cache_hit` — cached results used
- `backfill_market_category_timeout` — timeout warnings (normal for slow/removed markets)

---

## Next Scheduled Run

- **Next backfill:** ~09:20 UTC (2 hours after start at 07:20)
- **Subsequent:** Every 2 hours continuously

---

## Recommendation

Category backfill теперь работает в 6 раз чаще (12ч → 2ч). Это должно сократить `unknown` категорию до <10% в течение 24-48 часов.

**Commit pending approval before push.**