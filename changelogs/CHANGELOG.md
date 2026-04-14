# CHANGELOG

## 2026-04-14 — smoke_test.sh freshness check (SYS-335)

- **Check A fixed**: market_resolutions freshness now uses `COUNT(*) WHERE fetched_at < NOW() - INTERVAL '3 hours'` instead of flawed `MAX(fetched_at)` approach
- **Check B removed**: coverage gap LEFT JOIN check removed (false positives for active markets)
- **Final result**: 24/24 PASS, 0 FAIL

Commit: `task: SYS-335 smoke_test freshness check — 24 checks total`

- **SSH hardening**: PasswordAuthentication yes → no
- **SSH hardening**: PermitRootLogin yes → prohibit-password
- **fail2ban**: installed, SSH jail active
- **ignoreip**: 127.0.0.1/8, 62.60.233.100, 83.139.133.100
- **incident 006.1**: checked auth.log 08:51–09:11 UTC — no suspicious activity

Commit: `sec: SEC-501 SSH hardening complete, fail2ban active`

---

## 2026-03-31 — Pipeline End-to-End Fix

- **BUG-602**: Bankroll restore from DB on restart (no more $100 hardcode reset)
- **BUG-603**: Dedup filter switched to opportunity_id (paper_trades.id)
- **BUG-601-FIX**: Settlement switched from Gamma API to CLOB API (459 trades closed)
- **BUG-604**: Bankroll reconciliation from trades table (source of truth)
- **TRD-430**: Pipeline audit completed (timezone hypothesis rejected)

Commit: `docs: DOC-602 close BUG-601/602/603/604, TRD-430 — pipeline e2e fixed`

---

## 2026-03-30

### Fixed
- **TRD-408**: traded_at now uses API timestamp instead of DB insert time. Removed get_market_category() HTTP call from hot path in whale_detector.py, whale_tracker.py, virtual_bankroll.py. Commits: cefb92a, dbe310f.
- **BUG-502**: Verified real-time whale trade ingestion. Paper poll (30s) and tracked poll (5min) loops working independently. Confirmed on 0x2652dd (paper) and 0x32ed (paper).
- **BUG-504**: Fixed false new_trades=50 log. save_whale_trade() now returns bool based on INSERT rowcount. Duplicates correctly counted.

### Changed
- 0x2652dd (WR 100%, +$2917) moved from tracked → paper copy_status.
- Paper whales count: 2 (0x32ed + 0x2652dd).

---

## 2026-03

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-03-29 | STRAT-701 | Whale copy selection: добавлен copy_status column, trigger фильтрует по 'paper', pipeline unfrozen, bankroll reset to $100 |
| 2026-03-27 | ARC-503 | Remove legacy fields is_winner and profit_usd from whale_trades (код + БД) |
| 2026-03-26 | TRD-427b | Fix: Исправлен баг TypeError в _update_whales_pnl() — print() аргумент был строкой вместо списка, пересобран Docker образ |
| 2026-03-26 | TRD-427 | Fix: roundtrip_builder теперь запускает --settle автоматически каждые 2 часа (757 OPEN roundtrips теперь будут обновляться при закрытии рынков) |
| 2026-03-26 | TRD-426 | Fix: исправлены tier пороги (HOT: 1d, WARM: 7d), пересчитаны тиры (HOT: 40.7%, WARM: 59%, COLD: 0.3%) |
| 2026-03-26 | SYS-601-FIX | Fix: устранено дублирование roundtrip jobs (main.py → container), увеличен интервал 30min → 2h, отключен broken paper_settlement сервис |
| 2026-03-26 | ARC-502-D | Fix: обновление P&L китов через `wallet_address` вместо `whale_id` (+461 whales, +2266 roundtrips) |
| 2026-03-26 | ARC-502-C | Roundtrip Builder: settlement через CLOB API (+2039 CLOSED, +$680K P&L) |
| 2026-03-25 | ARC-502-B | Fix: fuzzy matching close для short selling (+27 CLOSED) |
| 2026-03-22 | TRD-422 | Добавлен market_category в whale_trades, унифицирован INSERT |
| 2026-03-22 | TRD-423 | Fix whale_trades ingestion: _database_url → database_url |
| 2026-03-22 | ARC-501 | Миграция whales: удалены 8 legacy полей, добавлены 7 P&L полей |
| 2026-03-22 | ARC-502-A | Roundtrip Builder: создание OPEN roundtrips из BUY событий |