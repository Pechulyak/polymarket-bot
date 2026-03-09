# Paper Trade Trigger Pipeline Audit

## Executive Summary
Audit completed: 2026-03-09
Focus: whale_trades → paper_trades → notifications pipeline

## 1. Throughput - whale_trades

| Window | Count |
|--------|-------|
| 2 hours | 62 |
| 6 hours | 191 |
| 24 hours | 860 |

Unique whale traders (24h): 662

## 2. Throughput - paper_trades

| Window | Count |
|--------|-------|
| 2 hours | 7 |
| 6 hours | 13 |
| 24 hours | 17 |

## 3. Throughput - notifications

| Window | Count |
|--------|-------|
| 6 hours | 13 |
| 24 hours | 17 |

Status: ✅ 100% delivery rate

## 4. Conversion Ratio

| Window | Whale Trades | Paper Trades | Conversion |
|--------|--------------|--------------|------------|
| 2h | 62 | 7 | 11.3% |
| 6h | 191 | 13 | 6.8% |
| 24h | 860 | 17 | 2.0% |

## 5. Whales Eligibility Analysis

Trades from active whales (≥3 trades_last_3_days): 169

Activity breakdown (24h):
- Active (≥3 trades): 169 trades
- Recent (1-2 trades): 246 trades
- Total matched to whales: 415

## 6. Duplicate Trade Analysis

⚠️ **Issue Found**: 20 duplicate groups detected

Top duplicates:
- Max 7 duplicates for single wallet/market/side
- This indicates duplicate suppression is NOT working properly

## 7. Pipeline Latency

| Metric | Value |
|--------|-------|
| Avg Latency | 12 min 2 sec |
| Min Latency | -6 sec (negative!) |
| Max Latency | 4 hours 48 sec |
| Matched Trades | 20 |

⚠️ **Issues**:
- Only 20 matched trades found (very low vs 415 eligible)
- Negative latency suggests timing issues

## 8. Pipeline Bottleneck Analysis

### Identified Issues:

1. **CRITICAL: Low conversion rate (2% overall)**
   - 860 whale trades → only 17 paper trades
   - Primary bottleneck: filter stages between whale_trades and paper_trades

2. **Duplicate suppression not working**
   - 20 duplicate groups with up to 7 repeats
   - Expected behavior: duplicates should be suppressed

3. **Low matched trades in latency query**
   - Only 20 matches despite 415 whale trades with known whales
   - Suggests trigger condition mismatch or timing issues

4. **High latency variance**
   - Avg 12 min, but up to 4.8 hours
   - Indicates possible queue delays or stale data

### Pipeline Flow:

```
whale_trades (860/24h)
  ↓ [filter: active whales only]
  ↓ ~48% pass (415 trades)
  ↓ [filter: duplicate suppression - NOT WORKING]
  ↓ [filter: unknown]
  ↓
paper_trades (17/24h) ← BOTTLENECK HERE
  ↓
notifications (17/24h) ← 100% delivery
```

## Recommendations

1. Investigate why only 17/415 eligible whale trades become paper_trades
2. Fix duplicate suppression mechanism
3. Review trigger conditions for copy trading
4. Check for timing/synchronization issues
