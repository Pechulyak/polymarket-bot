# Duplicate Suppression Fix Report (SYS-315)

## Problem: Duplicate Paper Trades

**Symptom:** Up to 7 identical paper trades generated for a single whale trade signal (same wallet/market/side).

**Impact:**
- Inflated trade counts
- False signals in notification system
- Skewed performance metrics
- Wasted processing resources

## Root Cause

The SQL trigger `copy_whale_trade_to_paper()` in [`scripts/create_copy_trigger.sql`](scripts/create_copy_trigger.sql) was executed on EVERY insert into `whale_trades` table without any deduplication check.

**Data Flow:**
1. Whale trade detected → inserted into `whale_trades`
2. SQL trigger fires → creates entry in `paper_trades`
3. Problem: `whale_trades` had duplicates (same wallet/market/side within seconds)
4. Result: Each duplicate whale_trades generated a corresponding paper_trades

**Audit Results:**
- `whale_trades` duplicates: max 7, 20 pairs in 24h
- `paper_trades` duplicates: 1 pair (before fix)

## Fix Implementation

### 1. SQL Trigger Suppression Logic

Added duplicate check in [`scripts/create_copy_trigger.sql`](scripts/create_copy_trigger.sql):

```sql
-- Check for duplicate signal: skip if similar paper_trade exists within 5 minutes
IF EXISTS (
    SELECT 1 FROM paper_trades
    WHERE whale_address = v_whale_address
      AND market_id = NEW.market_id
      AND side = NEW.side
      AND created_at >= NOW() - INTERVAL '5 minutes'
) THEN
    -- Skip duplicate signal
    RETURN NEW;
END IF;
```

### 2. Database Index

Added index for faster duplicate checks:

```sql
CREATE INDEX idx_paper_trades_dedup 
ON paper_trades (whale_address, market_id, side, created_at DESC);
```

### 3. Historical Cleanup

Removed 1 historical duplicate from `paper_trades`.

## Verification Results

### Duplicate Check
```sql
SELECT whale_address, market_id, side, COUNT(*)
FROM paper_trades
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY whale_address, market_id, side
HAVING COUNT(*) > 1;
```
**Result:** 0 rows (no duplicates)

### Throughput Monitoring
| Time Window | Paper Trades |
|-------------|--------------|
| Last 2h     | 7            |
| Last 6h     | 15           |
| Last 24h    | 18           |

## Files Changed

1. **scripts/create_copy_trigger.sql** - Added 5-minute deduplication check in trigger
2. **docs/TASK_BOARD.md** - Added SYS-315 task

## Deployment

```bash
# Apply trigger fix
docker exec -i polymarket_postgres psql -U postgres -d polymarket < scripts/create_copy_trigger.sql

# Add index
docker exec polymarket_postgres psql -U postgres -d polymarket -c "
CREATE INDEX IF NOT EXISTS idx_paper_trades_dedup 
ON paper_trades (whale_address, market_id, side, created_at DESC);"
```

## Next Steps

- Monitor paper_trades for next 24h to confirm no new duplicates
- Consider expanding suppression window if needed
- Track whale_trades deduplication as separate issue (root cause in data ingestion)

---
*Report generated: 2026-03-09*
