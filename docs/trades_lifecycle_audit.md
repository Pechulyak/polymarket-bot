# TRADES LIFECYCLE AUDIT
## SYS-317: Audit trades Table Lifecycle for Paper Performance Tracking

**Date**: 2026-03-09
**Author**: Roo (Orchestrator)
**Task**: Audit lifecycle of trades table

---

## 1. PURPOSE OF TRADES TABLE

The `trades` table is the **central execution log** for all trade records in the Polymarket bot. It serves as:

- **Trade execution log**: Records every trade (real or virtual)
- **PnL tracking**: Tracks gross_pnl, total_fees, and net_pnl
- **Settlement tracking**: Uses status ('open'/'closed') and settled_at timestamp
- **Exchange identification**: The `exchange` field distinguishes between 'VIRTUAL' (paper) and live exchanges

---

## 2. TABLE STRUCTURE

### Columns Verified

| Column | Type | Purpose |
|--------|------|---------|
| `trade_id` | UUID | Unique identifier |
| `opportunity_id` | UUID | Link to opportunities table |
| `market_id` | VARCHAR | Market identifier |
| `side` | VARCHAR | 'buy' or 'sell' |
| `size` | NUMERIC | Position size in USD |
| `price` | NUMERIC | Execution price |
| `exchange` | VARCHAR | 'VIRTUAL' for paper, exchange name for live |
| `commission` | NUMERIC | Trading commission |
| `gas_cost_eth` | NUMERIC | Gas cost in ETH |
| `gas_cost_usd` | NUMERIC | Gas cost in USD |
| `fiat_fees` | NUMERIC | Fiat fees |
| `gross_pnl` | NUMERIC | Gross P&L (before fees) |
| `total_fees` | NUMERIC | Total fees (commission + gas) |
| `net_pnl` | NUMERIC | Net P&L (after all fees) |
| `status` | VARCHAR | 'open' or 'closed' |
| `executed_at` | TIMESTAMP | Trade execution time |
| `settled_at` | TIMESTAMP | Settlement time (when position closed) |

---

## 3. CURRENT STATE

### Record Count
```
SELECT COUNT(*) FROM trades;  -- Result: 2
```

### Status Distribution
```
SELECT status, COUNT(*) FROM trades GROUP BY status;
-- Result: status='open', count=2
```

### Sample Data
| trade_id | market_id | side | size | price | exchange | status |
|----------|-----------|------|------|-------|----------|--------|
| e41eeed8-... | 0x1234... | buy | 0.0 | 0.55 | VIRTUAL | open |
| 039128f4-... | 0x1234... | buy | 3.5 | 0.55 | VIRTUAL | open |

**Key Finding**: Both trades are **VIRTUAL** (paper trading) with status='open'. No closed positions yet.

---

## 4. WRITE PIPELINE

### Source Code Location
**File**: [`src/strategy/virtual_bankroll.py`](src/strategy/virtual_bankroll.py)

### Functions

1. **`VirtualBankroll.execute_virtual_trade()`** (line 416)
   - Main entry point for executing virtual trades
   - Calculates costs, updates balance, records trade
   - Calls `_save_virtual_trade()` for DB persistence

2. **`VirtualBankroll._save_virtual_trade()`** (line 206)
   - Writes to `trades` table
   - Uses `ON CONFLICT (trade_id) DO UPDATE` for upserts
   - Sets `exchange='VIRTUAL'` for paper trades

3. **`VirtualBankroll.close_virtual_position()`** (line 582)
   - Closes existing open position
   - Calculates PnL on close
   - Updates status to 'closed', sets settled_at

### Call Flow
```
copy_trading_engine.py
  └─> _execute_paper_trade()
        └─> virtual_bankroll.execute_virtual_trade()
              └─> _save_virtual_trade() --> trades table
```

---

## 5. LIFECYCLE STATES

### Trade Lifecycle Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    TRADE LIFECYCLE                         │
└─────────────────────────────────────────────────────────────┘

   CREATED                     SETTLED
     │                           │
     ▼                           ▼
┌─────────┐                 ┌─────────┐
│ status │                 │ status  │
│ ='open'│ ──────────────►│='closed'│
└─────────┘                 └─────────┘
     │                           │
     │                           ▼
     │                    ┌─────────────┐
     │                    │ settled_at  │
     │                    │ = NOW()     │
     │                    └─────────────┘
     │                           │
     │                           ▼
     │                    ┌─────────────┐
     │                    │ net_pnl     │
     │                    │ calculated  │
     │                    └─────────────┘
     │
     ▼
┌──────────────────────────────────────┐
│ Fields set on creation:              │
│ - trade_id (UUID)                    │
│ - market_id                          │
│ - side, size, price                  │
│ - exchange='VIRTUAL'                 │
│ - commission, gas_cost               │
│ - executed_at = NOW()                │
│ - status = 'open'                    │
│ - gross_pnl = 0, net_pnl = 0         │
└──────────────────────────────────────┘
```

### Status Transitions

| From | To | Trigger | Fields Updated |
|------|-----|---------|----------------|
| (new) | open | `execute_virtual_trade()` | All fields set |
| open | closed | `close_virtual_position()` or sell side | status, settled_at, gross_pnl, total_fees, net_pnl |

---

## 6. PnL CALCULATION

### Formula (from virtual_bankroll.py lines 485-490)

```python
# Entry
entry_value = position.size * position.entry_price

# Exit
exit_value = size * price

# Gross P&L
gross_pnl = exit_value - entry_value

# Total fees
total_fees = fees + gas + position.commission + position.gas_cost

# Net P&L
net_pnl = gross_pnl - total_fees
```

### Fields Used
- `gross_pnl`: Raw profit/loss before fees
- `total_fees`: commission + gas_cost_eth + gas_cost_usd
- `net_pnl`: gross_pnl - total_fees

### Fee Breakdown
The code calculates:
1. Entry fees: `fees + gas` (passed to execute_virtual_trade)
2. Exit fees: `fees + gas` (passed to close_virtual_position)
3. Position holding costs: `position.commission + position.gas_cost`

---

## 7. RELATIONSHIP TO PAPER TRADING

### Finding: YES - trades table IS used for paper performance tracking

**Evidence**:
1. Both existing trades have `exchange='VIRTUAL'`
2. Code in [`copy_trading_engine.py`](src/execution/copy_trading_engine.py:321) calls `virtual_bankroll.execute_virtual_trade()` in paper mode
3. VirtualBankroll sets `exchange='VIRTUAL'` when saving

### Additional Tables

| Table | Records | Purpose |
|-------|---------|---------|
| `trades` | 2 | Execution log with PnL |
| `paper_trades` | 55 | Whale signal tracking (pre-execution) |
| `paper_trade_notifications` | - | Telegram notifications |

### Relationship
- `paper_trades`: Whale signals BEFORE execution
- `trades`: Trade execution log WITH PnL
- No direct foreign key relationship between them

---

## 8. INTENDED ARCHITECTURE

### Current Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     CURRENT PIPELINE                            │
└──────────────────────────────────────────────────────────────────┘

  Whale Signal
       │
       ▼
┌─────────────────┐
│ paper_trades    │  ← whale signal storage (55 records)
│ (pre-execution)│
└─────────────────┘
       │
       ▼ (trigger detected)
┌─────────────────────────────┐
│ copy_trading_engine         │
│ (mode = "paper")            │
└─────────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ VirtualBankroll             │
│ .execute_virtual_trade()    │
└─────────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ trades table                │  ← execution log with PnL (2 records)
│ exchange='VIRTUAL'          │
│ status='open'/'closed'      │
└─────────────────────────────┘
```

### Missing Components

1. **No automatic position closing** - Positions remain 'open' until manually closed
2. **No settlement pipeline** - settled_at only set when close_virtual_position() called
3. **No market resolution** - No connection to Polymarket market resolution

---

## 9. RECOMMENDATION: REUSE FOR PAPER PERFORMANCE TRACKING

### Can trades table be reused for paper trade PnL tracking?

**YES** - The table already supports this:

✅ All required fields present:
- trade_id, market_id, side, size, price
- gross_pnl, total_fees, net_pnl
- status, executed_at, settled_at
- exchange='VIRTUAL' distinguishes paper from live

✅ Pipeline already implemented:
- VirtualBankroll writes to trades
- PnL calculation present
- Status lifecycle present

⚠️ Issues to Address:

1. **No automatic settlement**: Positions stay 'open' forever
   - Need: Market resolution listener or manual close trigger
   
2. **No historical PnL**: 2 trades, both 'open'
   - Need: Close positions to see PnL

3. **Missing whale source tracking in trades**:
   - `whale_source` field is passed but NOT saved to trades table
   - See virtual_bankroll.py line 549 - passed but not in INSERT

---

## 10. CONCLUSION

### Summary

| Question | Answer |
|----------|--------|
| Purpose of trades table | Central execution log with PnL |
| Pipeline populating it | VirtualBankroll.execute_virtual_trade() |
| PnL fields present | gross_pnl, total_fees, net_pnl ✓ |
| Can reuse for paper tracking | **YES** - already doing it |
| Current state | 2 VIRTUAL trades, both 'open' |

### Recommendation

**The trades table is suitable and already in use for paper trade performance tracking.** 

To fully enable paper PnL tracking:
1. Implement market resolution listener to auto-close positions
2. Ensure whale_source is saved to trades (currently passed but not inserted)
3. Add reporting queries for paper trading performance

---

*Generated: 2026-03-09*
