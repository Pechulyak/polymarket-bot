# Migration Plan: TRD-418 Whales Schema Redesign

## Overview

Transform `whales` table from current schema to approved activity-based structure.

---

## Current Schema Analysis

### Columns in `whales` table (from init_db.sql, lines 156-192):

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | SERIAL | NOT NULL | PRIMARY KEY |
| wallet_address | VARCHAR(66) | NOT NULL | UNIQUE |
| first_seen_at | TIMESTAMP | NOT NULL | NOW() |
| total_trades | INTEGER | NOT NULL | 0 |
| win_rate | DECIMAL(5,4) | NOT NULL | 0 |
| total_profit_usd | DECIMAL(20,8) | NOT NULL | 0 |
| total_volume_usd | DECIMAL(20,8) | NOT NULL | 0 |
| avg_trade_size_usd | DECIMAL(20,8) | NOT NULL | 0 |
| last_active_at | TIMESTAMP | NOT NULL | NOW() |
| is_active | BOOLEAN | NOT NULL | TRUE |
| risk_score | INTEGER | NOT NULL | 5 |
| status | VARCHAR(20) | NOT NULL | 'discovered' |
| trades_last_3_days | INTEGER | NOT NULL | 0 |
| days_active | INTEGER | NOT NULL | 0 |
| last_qualified_at | TIMESTAMP | NULL | - |
| last_ranked_at | TIMESTAMP | NULL | - |
| source | VARCHAR(50) | NULL | - |
| notes | TEXT | NULL | - |
| created_at | TIMESTAMP | NOT NULL | NOW() |
| updated_at | TIMESTAMP | NOT NULL | NOW() |

### Code Dependencies Found:

**whale_detector.py** (INSERT - lines 858-884):
- Uses: `wallet_address, total_trades, win_rate, total_profit_usd, total_volume_usd, avg_trade_size_usd, risk_score, status, trades_last_3_days, trades_last_7_days, days_active, qualification_path, source, notes`
- Uses: `status` field
- Uses: `qualification_path` field
- Uses: `days_active` field
- Uses: `trades_last_7_days` field

**whale_detector.py** (UPDATE - lines 722-736):
- Updates: `qualification_path, trades_last_7_days, days_active, last_active_at, updated_at`

**whale_tracker.py** (INSERT - lines 556-572):
- Uses: `wallet_address, total_trades, win_rate, total_profit_usd, avg_trade_size_usd, last_active_at, risk_score`
- Uses: `win_rate`
- Uses: `total_profit_usd`

---

## Target Schema

See TASK_PACK for full specification. Key changes:

### Fields to RENAME:
| Current | Target | Notes |
|---------|--------|-------|
| first_seen_at | first_discovered_at | New name |
| total_trades | trades_count | New name |

### Fields to ADD:
- `qualification_status` (VARCHAR(20)) - status lifecycle
- `tier` (VARCHAR(10)) - HOT/WARM/COLD
- `last_seen_in_feed` (TIMESTAMP)
- `last_targeted_fetch_at` (TIMESTAMP)
- `trades_last_7_days` (INTEGER)
- `days_active_7d` (INTEGER)
- `days_active_30d` (INTEGER)
- `trades_per_day` (NUMERIC(20,8))

### Fields to REMOVE (LEGACY):
- `win_rate` - NOT in target schema
- `total_profit_usd` - NOT in target schema
- `is_active` - NOT in target schema
- `qualification_path` - NOT in target schema
- `status` - REPLACED by qualification_status
- `days_active` - REPLACED by days_active_7d/days_active_30d
- `last_ranked_at` - NOT in target schema
- `first_seen_at` - RENAMED to first_discovered_at

---

## Migration Strategy

### CRITICAL: Code Dependencies

**The code still references these legacy fields:**
- `status` - whale_detector.py line 860, 867, 877
- `qualification_path` - whale_detector.py line 723-724, 860, 868, 881
- `days_active` - whale_detector.py line 726, 734, 804, 862, 867
- `win_rate` - whale_detector.py line 860, 865, 872; whale_tracker.py line 558, 561, 566, 578
- `total_profit_usd` - whale_detector.py line 860, 865, 873; whale_tracker.py line 558, 561, 567, 579
- `trades_last_7_days` - whale_detector.py - used in updates

**Direct destructive ALTER/DROP safe = NO**
- Legacy fields cannot be dropped until code is updated

**Staging required = YES**

---

## Staged Migration Plan

### Phase 1: Add New Columns (Safe)
1. Add `qualification_status` VARCHAR(20) DEFAULT 'discovered'
2. Add `tier` VARCHAR(10) NULL
3. Add `last_seen_in_feed` TIMESTAMP NULL
4. Add `last_targeted_fetch_at` TIMESTAMP NULL
5. Add `trades_last_7_days` INTEGER DEFAULT 0
6. Add `days_active_7d` INTEGER DEFAULT 0
7. Add `days_active_30d` INTEGER DEFAULT 0
8. Add `trades_per_day` NUMERIC(20,8) DEFAULT 0
9. Add `trades_count` INTEGER (temporary, will replace total_trades)
10. Add `first_discovered_at` TIMESTAMP (temporary, will replace first_seen_at)

### Phase 2: Backfill Data
1. Copy `total_trades` to `trades_count`
2. Copy `first_seen_at` to `first_discovered_at`
3. Copy `status` to `qualification_status`
4. Set default `qualification_status` = 'discovered' for existing rows

### Phase 3: Code Updates (REQUIRED BEFORE DROP)
1. Update whale_detector.py to use new field names
2. Update whale_tracker.py to use new field names
3. Remove references to: status, qualification_path, days_active, win_rate, total_profit_usd

### Phase 4: Drop Legacy Columns (After Code Update)
- Drop `status`
- Drop `qualification_path`
- Drop `days_active`
- Drop `win_rate`
- Drop `total_profit_usd`
- Drop `is_active`
- Drop `last_ranked_at`
- Drop `total_trades` (after trades_count is populated)
- Drop `first_seen_at` (after first_discovered_at is populated)

### Phase 5: Add Constraints & Comments
- Add CHECK constraints for all enumerated types
- Add NOT NULL constraints where required
- Add SQL COMMENT ON COLUMN for all fields

### Phase 6: Add Indexes
- UNIQUE INDEX on wallet_address
- INDEX on qualification_status
- INDEX on tier
- INDEX on last_active_at
- INDEX on last_seen_in_feed
- INDEX on last_targeted_fetch_at

---

## Risk Assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| Code still uses legacy fields | HIGH | Staged migration with code update step |
| Data loss on rename | MEDIUM | Backfill before drop |
| Constraint violations | LOW | Add constraints after data is validated |

---

## Migration SQL Outline

```sql
-- Phase 1: Add new columns
ALTER TABLE whales ADD COLUMN IF NOT EXISTS qualification_status VARCHAR(20) NOT NULL DEFAULT 'discovered';
ALTER TABLE whales ADD COLUMN IF NOT EXISTS tier VARCHAR(10);
ALTER TABLE whales ADD COLUMN IF NOT EXISTS last_seen_in_feed TIMESTAMP;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS last_targeted_fetch_at TIMESTAMP;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS trades_last_7_days INTEGER NOT NULL DEFAULT 0;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS days_active_7d INTEGER NOT NULL DEFAULT 0;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS days_active_30d INTEGER NOT NULL DEFAULT 0;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS trades_per_day NUMERIC(20,8) NOT NULL DEFAULT 0;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS trades_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE whales ADD COLUMN IF NOT EXISTS first_discovered_at TIMESTAMP;

-- Phase 2: Backfill
UPDATE whales SET trades_count = total_trades;
UPDATE whales SET first_discovered_at = first_seen_at;
UPDATE whales SET qualification_status = status;

-- Phase 4: Drop legacy (after code update)
-- ALTER TABLE whales DROP COLUMN IF EXISTS status;
-- ... etc
```

---

## Definition of Done

- [x] TASK_BOARD updated with TRD-418
- [ ] Migration plan documented
- [ ] New columns added
- [ ] Data backfilled
- [ ] Code updated to use new fields
- [ ] Legacy columns dropped
- [ ] Constraints added
- [ ] Comments added
- [ ] Indexes created
- [ ] Schema validated
- [ ] Strategy approval received
- [ ] Commit and push completed
