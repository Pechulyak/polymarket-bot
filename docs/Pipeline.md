DISCOVERY (whale-detector) — ⛔ ОСТАНОВЛЕН (MIG-001, 2026-07-21)
│
│ Отключён флагом WHALE_DISCOVERY_ENABLED=false (обратимо).
│ Не работают: WebSocket-monitor (все рынки) + _polymarket_poll_loop.
│ Ранее: Polymarket Data API → новые адреса; INSERT INTO whales;
│        INSERT INTO whale_trades (source=POLLER).
│ Сейчас whale_trades пополняется ТОЛЬКО таргетированными поллерами
│ paper/tracked/live (см. блок PAPER/TRACKED POLLING ниже).
│
↓
TIER MANAGEMENT (whale-detector) — ⛔ ОСТАНОВЛЕН (MIG-001, 2026-07-21)
│
│ HOT/WARM/tier-downgrade живут внутри RealTimeWhaleMonitor.start(),
│ который MIG-001 не запускает (WHALE_DISCOVERY_ENABLED=false) → остановлены.
│ Ранее: HOT polling → 4ч; WARM polling → 24ч; Ranking update → 1ч.
│ Обслуживали тир-ранжирование discovered-китов, копированию не нужны.
│ Включить: WHALE_DISCOVERY_ENABLED=true + пересборка whale-detector.
│
↓
ROUNDTRIP BUILDER (standalone container, каждые 2ч)
│
│ BUY events → CREATE OPEN roundtrips
│ SELL events → CLOSE roundtrips + calc P&L
│ Gamma/CLOB API → SETTLE resolved markets
│ UPDATE whales (win_count, total_pnl, win_rate)
│
↓
PAPER TRADING (bot container)
│
│ Main loop: каждые 5с — анализ сигналов
│ Paper settlement: каждые 10м — резолюция бумажных сделок
│ Metrics update: каждые 5м
│ Stats printer: каждые 24ч
│
↓
NOTIFICATIONS (bot container, каждые 2с)
│
│ Telegram уведомления