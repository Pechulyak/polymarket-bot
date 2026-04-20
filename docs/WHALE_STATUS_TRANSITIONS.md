# Whale Status Transitions — Governance Spec

**Version:** 1.0 (draft)
**Approved by:** STRATEGY
**Approved at:** 2026-04-19
**Revision basis:** WHALE-STATUS-SPEC-DRAFT-v1

> Документ описывает алгоритм перевода китов между значениями `whales.copy_status`.
> Все изменения статусов в БД должны соответствовать этому документу.
> Обновляется STRATEGY.

---

## 1. Назначение

Документ описывает допустимые переходы между значениями `whales.copy_status` и обязательные действия при каждом переходе. Обновляется STRATEGY. Все изменения `copy_status` в БД должны соответствовать этому документу.

---

## 2. Состояния

| Status | Описание |
|--------|----------|
| `none` | Freshly discovered, no engagement. Default для новых китов. |
| `tracked` | Мониторинг P&L, без копирования трейдов. |
| `paper` | Активное paper-копирование. Требует `estimated_capital`. |
| `excluded` | Исключён из копирования и discovery (защищён BUG-607 guard). |
| `live` | Reserved, не используется. |

---

## 3. Переходы

### 3.1. none → tracked (promotion)

**Pre-actions:**
- Актуализировать tier через `_update_whale_activity`.
- Записать причину в `whale_comment`.

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'tracked',
    reviewed_at = NOW(),
    updated_at = NOW()
WHERE wallet_address = '<addr>' 
  AND copy_status = 'none';
```

---

### 3.2. tracked → paper (promotion)

**Pre-checks:**
- P&L Gate: WR ≥60%, N≥5 roundtrips, PnL > 0.
- Рассчитать `estimated_capital` по формуле:

```sql
SELECT MAX(daily_volume_usd) FROM (
    SELECT DATE(traded_at) AS d, SUM(size_usd) AS daily_volume_usd
    FROM whale_trades
    WHERE wallet_address = '<addr>'
      AND traded_at >= NOW() - INTERVAL '30 days'
    GROUP BY DATE(traded_at)
) t;
```

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'paper',
    estimated_capital = <computed_value>,
    capital_estimation_method = 'max_daily_volume_30d',
    reviewed_at = NOW(),
    updated_at = NOW()
WHERE wallet_address = '<addr>' 
  AND copy_status = 'tracked';
```

---

### 3.3. paper → tracked (downgrade, пауза)

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'tracked',
    reviewed_at = NOW(),
    updated_at = NOW()
WHERE wallet_address = '<addr>' 
  AND copy_status = 'paper';
```

**Note:** `estimated_capital` не очищается.

---

### 3.4. any → excluded (downgrade / exclusion)

**Pre-actions:**
- Заполнить `exclusion_reason`. Допустимые значения: `negative_pnl`, `auto_market_maker`, `edge_degraded`.
- Проверить открытые paper-позиции (они не закрываются автоматически, досыгрываются до settlement).

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'excluded',
    exclusion_reason = '<reason>',
    reviewed_at = NOW(),
    updated_at = NOW()
WHERE wallet_address = '<addr>';
```

---

### 3.5. excluded → tracked / paper (recovery)

Требует явного review STRATEGY. При восстановлении в `paper` — заново рассчитать `estimated_capital`.

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'tracked',  -- или 'paper' с estimated_capital
    exclusion_reason = NULL,
    reviewed_at = NOW(),
    updated_at = NOW()
WHERE wallet_address = '<addr>' 
  AND copy_status = 'excluded';
```

---

## 4. Запрещённые переходы

Следующие переходы не поддерживаются:

- `tracked → none`
- `paper → none`
- `excluded → none`
- Прямой `none → paper` без промежуточного `tracked` (discouraged, но технически возможен).

---

## 5. Инварианты

- Все переходы — ручной SQL, автоматических нет.
- `tier` (HOT/WARM/COLD) не зависит от `copy_status`. Определяется активностью через `_update_whale_activity`.
- `estimated_capital` не очищается при downgrade — сохраняется для потенциального recovery.
- DB trigger `trigger_copy_whale_trade` создаёт `paper_trades` только для `copy_status='paper'`. Смена статуса мгновенно включает/выключает копирование.
- `excluded` защищён от перезаписи discovery-пайплайном (BUG-607 fix: guard `WHERE copy_status != 'excluded'` в `whale_detector.py` и `whale_tracker.py`).

---

## 6. Open questions

Список вопросов, не решённых в v1:

1. Нужен ли периодический пересчёт `estimated_capital` для paper-китов (weekly/monthly)?
2. Нужно ли добавить поле `copy_status_updated_at` для аудита? (отдельный TRD-тикет)
3. Fallback метод расчёта `estimated_capital` для китов с <30 дней истории.
4. Retroactive применение `max_daily_volume_30d` к существующим paper-китам с `method='manual'`.

---

## Appendix A: Investigation data (2026-04-19)

*(Full forensic investigation and draft analysis preserved below for reference)*

---

# Whale Status Transitions — State Machine Specification

**Document Type:** Investigation / Governance
**Task ID:** WHALE-STATUS-TRANSITION-SPEC
**Status:** Superseded by Governance Spec v1.0
**Date:** 2026-04-19
**Investigated by:** Roo (read-only investigation)

---

## 1. Состояния

### `none`
**Описание:** Freshly discovered whale with no copy trading engagement.

**Условия попадания:**
- Automatically assigned when a new whale is detected by discovery pipeline (Polymarket Data API feed)
- Also the default value for all existing whales (9,357 records at time of investigation)

**Поведение пиплайнов:**
- `WhaleDetector._save_whale_to_db()` — INSERT с `source_new='auto_detected'`, no copy_status update (default 'none')
- `WhaleTracker.save_whale()` — same behavior
- Discovery пайплайн НЕ создаёт paper_trades для whales со status='none'
- Trades для whales в 'none' не копируются

**Связанные поля:**
| Поле | Описание |
|------|----------|
| `copy_status` | 'none' (default) |
| `qualification_status` | 'discovered' (default) |
| `tier` | HOT/WARM/COLD (activity-based, derived from last_seen_in_feed) |
| `source_new` | 'auto_detected' или 'discovery' |

---

### `tracked`
**Описание:** Whale is being monitored for P&L analysis. No trades are copied, but the system fetches their trade history for qualification assessment.

**Условия попадания:**
- Manually assigned by STRATEGY decision
- No automated transition exists in current codebase
- All updates are manual SQL UPDATE

**Поведение пиплайнов:**
- `WhaleDetector._fetch_tracked_whale_trades()` (line 1767) — fetches recent trades, NO paper_trades created (trigger only fires for 'paper')
- `WhaleDetector._fetch_paper_whale_trades()` (line 1632) — fetches trades only for 'paper' whales, not for 'tracked'
- `whale_pnl_summary` materialized view includes tracked whales (WHERE copy_status IN ('paper', 'tracked', 'excluded'))
- DB trigger `trigger_copy_whale_trade` checks for `copy_status = 'paper'` only — tracked whales do NOT trigger paper_trade creation

---

### `paper`
**Описание:** Active copy trading in paper mode. Trades are copied and recorded in paper_trades table via DB trigger. Virtual bankroll tracks positions.

**Условия попадания:**
- Manually assigned by STRATEGY decision
- Migration script `migration_add_copy_status.sql` set some whales to 'paper' initially

**Поведение пиплайнов:**
- DB trigger `trigger_copy_whale_trade` (scripts/create_copy_trigger.sql) creates paper_trades entries
- `WhaleDetector._fetch_paper_whale_trades()` fetches recent trades for these whales
- Copy trigger uses `estimated_capital` for proportional Kelly sizing (v_proportion = whale_trade / whale_capital)
- `whale_pnl_summary` materialized view includes paper whales

**Обязательные поля для корректной работы:**
| Поле | Описание | Что будет если пусто |
|------|----------|----------------------|
| `estimated_capital` | Whale's estimated total capital in USD | Trigger uses COALESCE(estimated_capital, 100000) — fallback to $100k |
| `capital_estimation_method` | How capital was estimated | Метод расчёта, см. раздел 12 |

**Текущее состояние в БД:**
- 2 whales in 'paper' status

---

### `excluded`
**Описание:** Whale explicitly excluded from all copy trading and discovery pipelines. Cannot be re-activated by auto-discovery.

**Условия попадания:**
- Manually assigned by STRATEGY decision

**Допустимые значения exclusion_reason:**
- `negative_pnl` — whale showed negative P&L over observed period
- `auto_market_maker` — whale identified as automated market maker
- `edge_degraded` — edge has degraded below usable threshold
- `manual` — STRATEGY decision without specific category

**Поведение пиплайнов:**
- **BUG-607 protection confirmed:** Both `WhaleDetector._save_whale_to_db()` (line 1032) and `WhaleTracker.save_whale()` (line 594) have `WHERE whales.copy_status != 'excluded'` guard
- This prevents re-discovery from overwriting excluded status
- `whale_pnl_summary` materialized view includes excluded whales
- No trades are copied for excluded whales (trigger checks copy_status = 'paper' only)

---

### `live` (defined but not used)
**Описание:** Defined in CHECK constraint but no active usage in current codebase.

**CHECK constraint** (from init_db.sql line 208):
```sql
CHECK (copy_status IN ('none', 'paper', 'live', 'tracked', 'excluded'))
```

**Current usage:** 0 whales with copy_status='live' in database.

**Status:** Reserved for future live trading mode, not implemented yet.

---

## 2. Связанные поля

Таблица всех полей в `whales`, связанных со status transitions:

| Поле | Тип | Описание | Автоматически? | Требуется для paper? |
|------|-----|----------|----------------|--------------------|
| `copy_status` | VARCHAR(10) | Primary status field | Partially (migration) | Да |
| `exclusion_reason` | VARCHAR(50) | Reason excluded | Нет | N/A |
| `reviewed_at` | TIMESTAMP | Status decision time | Нет | Рекомендуется |
| `estimated_capital` | DECIMAL(20,8) | Whale's capital USD | Нет | Да (для Kelly) |
| `capital_estimation_method` | VARCHAR(20) | How capital was estimated | Нет | Да (документация) |
| `updated_at` | TIMESTAMP | Last update | Да (auto) | Да (audit) |
| `tier` | VARCHAR(10) | HOT/WARM/COLD | Да (activity-based) | Нет |
| `qualification_status` | VARCHAR(20) | Pipeline stage | Да (auto) | Нет |
| `whale_comment` | TEXT | Analyst notes | Нет | Рекомендуется |
| `trades_count` | INTEGER | Trade counter | Частично | Нет |
| `whale_category` | VARCHAR(20) | Category | Нет | Нет |

**Отсутствующие поля (для аудита):**
- `copy_status_updated_at` — НЕ существует, планируется добавить (TRD-эпик)
- `paper_since` — НЕ существует, покрывается copy_status_updated_at + git log

---

## 3. Диаграмма переходов

```
                    ┌─────────────────────────────────────────────────────────────┐
                    │                    MANUAL TRANSITIONS                        │
                    │                   (STRATEGY decisions)                        │
                    └─────────────────────────────────────────────────────────────┘

  ┌─────────┐     tracked      ┌─────────┐     paper        ┌─────────┐    excluded    ┌──────────┐
  │  none   │ ───────────────► │ tracked │ ───────────────► │  paper  │ ─────────────► │ excluded │
  │ (9357)  │                 │   (6)   │                 │   (2)   │                │   (6)    │
  └─────────┘                  └─────────┘                  └─────────┘                └──────────┘
       ▲                            │
       │         ◄──────────────────┘
       │
       │         ◄──────────────────────────────────────────────────────────
       │         (any → excluded: STRATEGY decision)
       │
       └──────────────────────────────────────────────────────
       │
       │    Discovery auto-assigns 'none' to new whales
       │    Both WhaleDetector and WhaleTracker use INSERT ... ON CONFLICT
       │    with copy_status != 'excluded' guard (BUG-607)

  ┌──────────┐
  │   live   │  Reserved for future — no transitions in current codebase
  └──────────┘
```

---

## 4. Детализация переходов

### 4.1 none → tracked

**Триггер:** STRATEGY manual decision

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'tracked',
    reviewed_at = NOW(),
    whale_comment = COALESCE(whale_comment, '') || ' Promotion reason: <reason>. ',
    updated_at = NOW()
WHERE wallet_address = '<address>' 
  AND copy_status = 'none';
```

**Side effects:** Whale eligible for tracked polling, appears in whale_pnl_summary

**Guards:** None in code — STRATEGY must ensure whale exists and is in 'none' state

---

### 4.2 tracked → paper

**Триггер:** STRATEGY manual decision (after P&L Gate verification)

**Required fields:** `estimated_capital` MUST be set before this transition

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'paper',
    estimated_capital = <calculated_value>,
    capital_estimation_method = '<method>',
    reviewed_at = NOW(),
    whale_comment = COALESCE(whale_comment, '') || ' Promotion to paper. capital_estimation_method=<method>, estimated_capital=<value>. ',
    updated_at = NOW()
WHERE wallet_address = '<address>' 
  AND copy_status = 'tracked';
```

**Side effects:**
- DB trigger starts creating paper_trades
- `WhaleDetector._fetch_paper_whale_trades()` starts polling

**Guards:** estimated_capital must be non-NULL

---

### 4.3 paper → tracked

**Триггер:** STRATEGY manual decision (pause paper, continue monitoring)

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'tracked',
    reviewed_at = NOW(),
    whale_comment = COALESCE(whale_comment, '') || ' Paused paper trading. ',
    updated_at = NOW()
WHERE wallet_address = '<address>' 
  AND copy_status = 'paper';
```

**Side effects:**
- DB trigger stops creating paper_trades
- Existing paper_trades remain (not deleted)
- `WhaleDetector._fetch_tracked_whale_trades()` starts polling

**Note:** `estimated_capital` is NOT cleared (per design decision 13.1)

---

### 4.4 paper → excluded

**Триггер:** STRATEGY manual decision

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'excluded',
    exclusion_reason = '<reason>',
    reviewed_at = NOW(),
    whale_comment = COALESCE(whale_comment, '') || ' Exclusion: <reason>. ',
    updated_at = NOW()
WHERE wallet_address = '<address>' 
  AND copy_status = 'paper';
```

**Side effects:**
- DB trigger stops creating paper_trades
- Open paper_trades remain open until settlement (design decision 13.2)
- BUG-607 guard locks status

---

### 4.5 tracked → excluded

**Триггер:** STRATEGY manual decision

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'excluded',
    exclusion_reason = '<reason>',
    reviewed_at = NOW(),
    whale_comment = COALESCE(whale_comment, '') || ' Exclusion: <reason>. ',
    updated_at = NOW()
WHERE wallet_address = '<address>' 
  AND copy_status = 'tracked';
```

---

### 4.6 none → excluded

**Триггер:** STRATEGY manual decision (known bad actor)

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'excluded',
    exclusion_reason = '<reason>',
    reviewed_at = NOW(),
    updated_at = NOW()
WHERE wallet_address = '<address>' 
  AND copy_status = 'none';
```

---

### 4.7 excluded → tracked (recovery)

**Триггер:** STRATEGY manual decision

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'tracked',
    exclusion_reason = NULL,
    reviewed_at = NOW(),
    whale_comment = COALESCE(whale_comment, '') || ' Recovered from excluded. ',
    updated_at = NOW()
WHERE wallet_address = '<address>' 
  AND copy_status = 'excluded';
```

---

### 4.8 excluded → paper (recovery)

**Триггер:** STRATEGY manual decision — requires estimated_capital to be set

**SQL:**
```sql
UPDATE whales 
SET copy_status = 'paper',
    exclusion_reason = NULL,
    estimated_capital = <value>,  -- REQUIRED
    capital_estimation_method = '<method>',
    reviewed_at = NOW(),
    whale_comment = COALESCE(whale_comment, '') || ' Recovered to paper. ',
    updated_at = NOW()
WHERE wallet_address = '<address>' 
  AND copy_status = 'excluded';
```

---

## 5. Известные баги и их статус

### BUG-607: Discovery could overwrite excluded whales

**Статус:** ✅ CLOSED

**Симптом:** Discovery pipeline overwrote `copy_status` of excluded whales back to 'none'.

**Root cause:** `INSERT ... ON CONFLICT (wallet_address) DO UPDATE` had no `WHERE copy_status != 'excluded'` clause.

**Fix applied:**
- `whale_detector.py` line 1032: Added `WHERE whales.copy_status != 'excluded'`
- `whale_tracker.py` line 594: Same guard

**Guard код:**
```sql
-- whale_detector.py (BUG-607 fix)
INSERT INTO whales (...) VALUES (...)
ON CONFLICT (wallet_address) DO UPDATE SET ...
WHERE whales.copy_status != 'excluded'

-- whale_tracker.py (BUG-607 fix)
INSERT INTO whales (...) VALUES (...)
ON CONFLICT (wallet_address) DO UPDATE SET ...
WHERE whales.copy_status != 'excluded'
```

---

## 6. Materialized Views и Copy Status

### whale_pnl_summary

**Definition:**
```sql
WHERE w.copy_status IN ('paper', 'tracked', 'excluded')
```

**Note:** 'none' whales are excluded. 'excluded' whales ARE included (design decision 13.4).

---

## 7. DB Triggers и Copy Status

### trigger_copy_whale_trade

**Table:** whale_trades (AFTER INSERT)
**Copy status check:** Only 'paper' whales trigger paper_trade creation

```sql
-- STRAT-701: Check if whale has copy_status = 'paper'
IF v_whale_address IS NOT NULL THEN
    SELECT EXISTS (
        SELECT 1 FROM whales 
        WHERE wallet_address = v_whale_address 
          AND copy_status = 'paper'
    ) INTO v_is_top_whale;
END IF;
```

**No triggers on whales table** — zero triggers found.

---

## 8. Открытые вопросы — STRATEGY Decisions

### Q1: Should estimated_capital be cleared on downgrade?

**Decision:** ❌ NO — do not clear.

`estimated_capital` is an external characteristic of the whale, not our parameter. It is preserved across all transitions. See Design Decision 13.1.

---

### Q2: Add copy_status_updated_at field?

**Decision:** ✅ YES — field will be added via separate TRD epic ticket.

Spec is written assuming this field exists. When added, it will be auto-updated on every copy_status change.

---

### Q3: Add paper_since field?

**Decision:** ❌ NO — not needed.

Covered by `copy_status_updated_at` + git log. If STRATEGY needs duration tracking, it can be derived later.

---

### Q4: Remove 'live' from CHECK constraint?

**Decision:** ❌ NO — keep 'live' in constraint.

Reserved for future live trading mode. Removal would require migration, cost nothing to keep.

---

### Q5: Formal downgrade to 'none' supported?

**Decision:** ❌ NO — not needed.

`tracked` and `excluded` cover all downgrade scenarios. Direct `none` downgrade (e.g., from `tracked`) is not a supported transition — if needed, STRATEGY should use `excluded` or manually set to `none`.

---

### Q6: Should tier be re-evaluated on promotion?

**Decision:** ❌ NO automatic re-evaluation.

`tier` is an objective characteristic (based on last_seen_in_feed timestamps). STRATEGY is **obligated** to run `_update_whale_activity` before promotion to ensure tier is current. Automated tier update on copy_status change is NOT implemented and NOT planned.

---

## 9. Summary Action Checklist (Updated)

**Before any transition — verify whale exists:**
```sql
SELECT wallet_address, copy_status, tier, estimated_capital, whale_comment 
FROM whales WHERE wallet_address = '<address>';
```

**All transitions update these fields:**
```sql
SET reviewed_at = NOW(),
    whale_comment = COALESCE(whale_comment, '') || '<action logged>',
    updated_at = NOW()
```

**For paper transitions — additional required fields:**
- `estimated_capital` — calculated via method in section 12
- `capital_estimation_method` — one of allowed values in section 12

**For excluded transitions — additional required field:**
- `exclusion_reason` — one of allowed values in section 1

**Note:** `copy_status_updated_at` will be added via TRD epic. Once added, it will be auto-populated on all transitions.

---

## 10. Statistics

**Database snapshot (2026-04-19):**
| copy_status | Count | With estimated_capital |
|-------------|-------|------------------------|
| none        | 9,357 | 0                      |
| tracked     | 6     | 1 (~$186k)             |
| paper       | 2     | 2 (~$361k total)       |
| excluded    | 6     | 0                      |
| live        | 0     | 0                      |

---

## 11. Чек-листы STRATEGY перед переходом

### 11.1 Перед promotion в tracked (из none или excluded)

**Obligatory steps:**

1. **Run tier refresh** — call `_update_whale_activity` or equivalent to ensure `tier` is current:
   ```sql
   -- Manual refresh via WhaleDetector (if running):
   -- await whale_detector._update_whale_activity(wallet_address)
   ```

2. **Verify tier:** `SELECT tier FROM whales WHERE wallet_address = '<address>';`
   - Tier should be HOT or WARM
   - If COLD — explicitly document reason in `whale_comment` before proceeding

3. **Log promotion reason in whale_comment:**
   ```sql
   UPDATE whales SET whale_comment = 'Promotion to tracked. Reason: <reason>. Tier: <tier>. ', 
   WHERE wallet_address = '<address>';
   ```

4. **For excluded → tracked:** clear exclusion_reason:
   ```sql
   UPDATE whales SET exclusion_reason = NULL WHERE wallet_address = '<address>';
   ```

---

### 11.2 Перед promotion в paper (из tracked или excluded)

**All steps from 11.1 plus:**

5. **P&L Gate verification:**
   - WR ≥ 60%
   - N ≥ 5 closed roundtrips
   - Net PnL > 0
   - Tier is HOT or WARM

   ```sql
   SELECT w.win_rate_confirmed, w.total_roundtrips, w.total_pnl_usd, w.tier
   FROM whales w WHERE w.wallet_address = '<address>';
   ```

6. **Calculate and set estimated_capital** (see Section 12):
   ```sql
   UPDATE whales 
   SET estimated_capital = <calculated_value>,
       capital_estimation_method = '<method>',
       ...
   WHERE wallet_address = '<address>';
   ```

7. **Document in whale_comment:**
   ```sql
   UPDATE whales 
   SET whale_comment = whale_comment || ' Promotion to paper. estimated_capital=<value> (<method>). P&L Gate: WR=<wr>, RT=<rt>, PnL=<pnl>. ',
   WHERE wallet_address = '<address>';
   ```

---

### 11.3 Перед переводом в excluded

**Obligatory steps:**

8. **Set exclusion_reason** (required):
   ```sql
   UPDATE whales 
   SET exclusion_reason = '<reason>',
       whale_comment = COALESCE(whale_comment, '') || ' Excluded: <reason>. ',
   WHERE wallet_address = '<address>';
   ```

9. **Check for open paper positions:**
   ```sql
   SELECT COUNT(*) FROM paper_trades 
   WHERE whale_address = '<address>' 
     AND (status = 'open' OR status IS NULL);
   ```
   - If open positions exist — STRATEGY confirms awareness that they remain open until settlement
   - This is expected behavior (Design Decision 13.2)

---

## 12. Логика расчёта estimated_capital

### 12.1 Forensic Analysis — Current Paper Whales

**Whale 0x32ed... (manual method):**
| Metric | Value |
|--------|-------|
| estimated_capital | $200,000.00 |
| capital_estimation_method | manual |
| total trades | 13,568 |
| total volume | $4,542,705.78 |
| max single trade | $9,979.00 |
| p99 trade size | $5,123.56 |
| max daily volume (30d) | $507,210.39 |

**Analysis:** $200,000 / max_trade ($9,979) = ~20x. Method is "manual" — no formula found.

---

**Whale 0x479e... (max_daily_volume_30d method):**
| Metric | Value |
|--------|-------|
| estimated_capital | $160,999.99989500 |
| capital_estimation_method | max_daily_volume_30d |
| total trades | 476 |
| total volume | $1,280,464.49 |
| max single trade | $9,989.96 |
| p99 trade size | $9,890.97 |
| Max daily volume (30d) | $160,999.99989500 |

**CRITICAL FINDING:** estimated_capital = MAX(daily volume) over last 30 days, exactly matching!

```
2026-03-28: $160,999.99989500 ← this is the estimated_capital value
```

**Formula discovered:** `estimated_capital = MAX(SUM(size_usd) OVER DATE) for 30-day window`

---

### 12.2 Code/Git History for estimated_capital

**Search results:** No automated formula found in Python code or migrations.

- `create_copy_trigger.sql` uses `COALESCE(w.estimated_capital, 100000)` — only reads, never writes
- `migration_phase4_006_dynamic_kelly.sql` — same usage pattern
- `migration_sys336_kelly_fix.sql` — same usage pattern
- PROJECT_CHANGELOG.md: "0x32ed: estimated_capital=$200,000 (manual)" — no formula specified

**Conclusion:** estimated_capital was always manual input until 0x479e... which used `max_daily_volume_30d` method (discovered from the field name).

---

### 12.3 Allowed capital_estimation_method values

Based on forensic analysis, the following methods are defined:

| Method | Formula | When to use | Notes |
|--------|---------|-------------|-------|
| `max_daily_volume_30d` | MAX(daily volume) over last 30 days | Default for active whales with ≥30d history | Derived from 0x479e analysis |
| `p99_trade_20x` | p99_trade_size × 20 | Short history (<30d), need conservative estimate | Fallback method |
| `peak_exposure_2x` | Peak concurrent open position × 2 | Whales with >100 roundtrips, complex positions | Requires roundtrip analysis |
| `manual` | STRATEGY sets directly | Edge cases, insider info, external sources | Use only when formula methods insufficient |

**Rejected methods:**
- `max_trade_10x` — too aggressive, outliers distort
- `avg_trade_*` — underestimates active traders

---

### 12.4 Recommended Default Method

**For new paper whales with ≥30d history:** `max_daily_volume_30d`

**SQL to calculate:**
```sql
SELECT 
    wallet_address,
    MAX(daily_vol) as estimated_capital
FROM (
    SELECT 
        wallet_address, 
        DATE(traded_at) as day, 
        SUM(size_usd) as daily_vol
    FROM whale_trades 
    WHERE wallet_address = '<address>'
      AND traded_at > NOW() - INTERVAL '30 days'
    GROUP BY wallet_address, DATE(traded_at)
) sub
GROUP BY wallet_address;
```

---

### 12.5 Retroactive Application Recommendation

**For current paper whale 0x32ed... (currently "manual", $200k):**
- max_daily_volume_30d = $507,210 (from 2026-04-08)
- Current value $200k vs calculated $507k — mismatch
- **Recommendation:** If this whale is to continue in paper mode, recalculate with `max_daily_volume_30d` → $507k
- This is a recommendation only — STRATEGY to decide whether to retroactively update

**For current paper whale 0x479e...:**
- Already using `max_daily_volume_30d` method
- Value $160,999.99989500 exactly matches max daily volume
- No change needed — method and value are consistent

---

## 13. Design Decisions

### 13.1 estimated_capital is NOT cleared on transitions

`estimated_capital` represents an external characteristic of the whale (its capital on Polymarket). It does not depend on our copy/no-copy decision. Therefore:
- Downgrade from paper → tracked does NOT clear estimated_capital
- Exclusion does NOT clear estimated_capital
- Recovery from excluded uses the preserved value (if still valid)

If STRATEGY determines the value is stale, manual update is required via promotion checklist.

---

### 13.2 Open paper positions are NOT closed on paper → excluded

Positions remain open until natural settlement (SELL event or SETTLEMENT_WIN/LOSS). This allows post-mortem analysis of the whale's final trades before exclusion.

If forced closure is needed in the future, it requires a separate procedure (out of scope for this spec).

---

### 13.3 tier is independent of copy_status

`tier` is calculated from `last_seen_in_feed` timestamps (HOT ≤1 day, WARM ≤7 days, COLD >7 days). It does NOT change when copy_status changes.

STRATEGY is obligated to run `_update_whale_activity` before promotion to ensure tier reflects current activity.

---

### 13.4 whale_pnl_summary includes excluded whales

This is intentional for historical analysis. If aggregated P&L is needed for active whales only, add `AND copy_status != 'excluded'` filter in queries.

---

### 13.5 BUG-607 guarantees excluded whales cannot be auto-restored

Once a whale is set to `excluded`, only STRATEGY manual UPDATE can restore it. Discovery pipelines have a `WHERE copy_status != 'excluded'` guard that prevents overwriting.

---

## 14. Таблица допустимых переходов

| From | To | Allowed | Notes |
|------|----|---------|-------|
| none | tracked | ✅ Yes | Standard promotion path |
| none | excluded | ✅ Yes | Direct exclusion (known bad actor) |
| none | paper | ⚠️ Discouraged | Bypass tracked — requires explicit STRATEGY justification in whale_comment |
| tracked | paper | ✅ Yes | Standard promotion (after P&L Gate) |
| tracked | excluded | ✅ Yes | Downgrade |
| tracked | none | ❌ No | Not supported — use excluded instead |
| paper | tracked | ✅ Yes | Pause copy, continue monitoring |
| paper | excluded | ✅ Yes | Downgrade with exclusion reason |
| paper | none | ❌ No | Not supported |
| excluded | tracked | ⚠️ Review | Recovery — clear exclusion_reason |
| excluded | paper | ⚠️ Review | Recovery — requires estimated_capital reset |
| excluded | none | ❌ No | Not supported |
| *(any) | live | ❌ No | Not implemented yet |

---

**Document status:** Superseded by Governance Spec v1.0 at top of file.