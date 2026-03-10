# Paper Execution Gap Audit (SYS-319)

**Date**: 2026-03-10  
**Auditor**: Roo (Code Agent)  
**Status**: ✅ COMPLETE

---

## Executive Summary

**Primary Gap Cause**: Balance Exhaustion - Virtual bankroll completely drained ($100 → $1.00)

The paper_trades table grows independently (whale detection pipeline), while the trades table is only populated when VirtualBankroll.execute_virtual_trade() successfully executes. Since the bankroll is exhausted, no new trades can be executed.

---

## Gap Measurements

| Window | paper_trades | trades(VIRTUAL) | Gap |
|--------|--------------|-----------------|-----|
| Total | 173 | 68 | **105** |
| 2h | 5 | 0 | **5** |
| 6h | 28 | 0 | **28** |
| 24h | 125 | 66 | **59** |

### Match Ratio Analysis

- Total paper_trades: 173
- Matched to trades: 8
- Unmatched: 165
- **Match ratio: 4.6%**

---

## Root Cause Analysis

### Execution Path

1. **paper_trades source**: Whale detection pipeline (separate process)
   - Trigger-based insertion from `whale_trades` events
   - Continues populating regardless of balance

2. **trades source**: VirtualBankroll.execute_virtual_trade() in main.py
   - Lines 102-111 in [`src/main.py`](src/main.py:102)
   - Function: [`execute_virtual_trade()`](src/strategy/virtual_bankroll.py:416)
   - Requires positive balance to execute

### Skip Conditions Identified

| Condition | Count | Impact |
|-----------|-------|--------|
| **Insufficient Balance** | **CRITICAL** | All trades since balance dropped to $1 |
| Duplicate trades | Low | Deduplication index exists |
| Invalid market_id | Low | Validation in place |

### Current Balance Status

```
Initial bankroll: $100.00
Current balance:  $1.00
Min balance:      $1.00
Max balance:     $100.00
Bankroll records: 69
```

Each trade requires ~$1.50 (size + fees + gas), so balance is completely exhausted.

---

## Evidence from Logs

```json
{"event": "Error executing paper trade: Insufficient balance: required 1.500, available 1.000", "level": "warning"}
```

**Frequency**: ~30 errors per second (continuous loop)

---

## Classification

**Category**: **A** - main.py executes but balance is exhausted

The execution path IS correctly integrated, but all new trades are rejected due to insufficient balance.

---

## Recommendations

### Immediate Fix Required

1. **Reset virtual bankroll** to initial balance ($100.00)
   - Option A: Call `virtual_bankroll.reset(Decimal("100.00"))`
   - Option B: Update bankroll table directly
   - Option C: Restart bot with fresh bankroll

2. **Adjust gas calculation**
   - Current: $1.50 fixed gas per trade
   - Consider: Dynamic gas based on trade size, or reduce fixed amount

### Long-term Improvements

1. **Auto-reset on exhaustion**: Add logic to reset bankroll when it drops below threshold
2. **Alerting**: Send notification when balance < $10
3. **Position sizing**: Use Kelly Criterion to size positions appropriately for $100 bankroll

---

## Files Analyzed

- [`src/main.py`](src/main.py) - Lines 102-111: execute_virtual_trade calls
- [`src/strategy/virtual_bankroll.py`](src/strategy/virtual_bankroll.py) - Lines 416-580: execute_virtual_trade()
- [`src/strategy/virtual_bankroll.py`](src/strategy/virtual_bankroll.py) - Lines 454-457: Balance check (raises ValueError)

---

## Conclusion

The gap between paper_trades (173) and trades (68) is **NOT** due to broken integration. The integration is working correctly. The gap exists because:

1. whale detection continues to populate paper_trades
2. VirtualBankroll cannot execute new trades due to exhausted balance ($1.00 remaining)
3. Each trade requires $1.50 minimum (size + fees + gas)

**Recommended Action**: Reset virtual bankroll to $100.00 to resume paper trading.
