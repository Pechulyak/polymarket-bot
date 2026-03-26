DISCOVERY (whale-detector, каждые 60с)
│
│ Polymarket Data API → новые адреса
│ INSERT INTO whales (qualification_status, tier)
│ INSERT INTO whale_trades (source=POLLER)
│
↓
TIER MANAGEMENT (whale-detector, каждый час)
│
│ HOT polling  → каждые 4ч  (whale_poller.py)
│ WARM polling → каждые 24ч (whale_poller.py)
│ Ranking update → каждый час
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