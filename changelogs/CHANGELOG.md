# CHANGELOG

## 2026-03

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-03-26 | TRD-426 | Fix: исправлены tier пороги (HOT: 1d, WARM: 7d), пересчитаны тиры (HOT: 40.7%, WARM: 59%, COLD: 0.3%) |
| 2026-03-26 | SYS-601-FIX | Fix: устранено дублирование roundtrip jobs (main.py → container), увеличен интервал 30min → 2h, отключен broken paper_settlement сервис |
| 2026-03-26 | ARC-502-D | Fix: обновление P&L китов через `wallet_address` вместо `whale_id` (+461 whales, +2266 roundtrips) |
| 2026-03-26 | ARC-502-C | Roundtrip Builder: settlement через CLOB API (+2039 CLOSED, +$680K P&L) |
| 2026-03-25 | ARC-502-B | Fix: fuzzy matching close для short selling (+27 CLOSED) |
| 2026-03-22 | TRD-422 | Добавлен market_category в whale_trades, унифицирован INSERT |
| 2026-03-22 | TRD-423 | Fix whale_trades ingestion: _database_url → database_url |
| 2026-03-22 | ARC-501 | Миграция whales: удалены 8 legacy полей, добавлены 7 P&L полей |
| 2026-03-22 | ARC-502-A | Roundtrip Builder: создание OPEN roundtrips из BUY событий |