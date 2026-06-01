# INFRA-030 — Retention whale_trades (архив + cron)

## Статус: TODO

## Цель

Ограничить рост горячей таблицы `whale_trades` без партиционирования.

## Обоснование отказа от партиционирования (INFRA-028)

- Rate ~20k/day (после DATA-411, новый baseline, не артефакт)
- При retention 90д горячая таблица стабилизируется ~1.8M строк
- Этот объём PostgreSQL обслуживает на одной таблице без партиций
- Партиционирование несло блокер: `ON CONFLICT (tx_hash) WHERE ...` несовместим с partition key `traded_at`
- Риск повтора INFRA-028 (phantom trigger, catalog corruption)

## Горизонт

**90 дней.** Текущие OPEN: 0 старше 90д (подтверждено INFRA-029-PREP-B).

## Механика (черновик, НЕ реализация)

### Таблица archive

```sql
CREATE TABLE whale_trades_archive (
    id SERIAL PRIMARY KEY,
    whale_id INTEGER,
    market_id VARCHAR(255) NOT NULL,
    side VARCHAR(10) NOT NULL,
    size_usd NUMERIC(20,8) NOT NULL,
    price NUMERIC(20,8) NOT NULL,
    outcome VARCHAR(50),
    traded_at TIMESTAMP NOT NULL,
    wallet_address VARCHAR(66),
    tx_hash VARCHAR(70),
    source VARCHAR(20),
    market_title TEXT,
    market_category VARCHAR(50),
    archived_at TIMESTAMP DEFAULT NOW()
);
-- pkey-индекс только (id). Нет tx_hash unique, нет sell_match, нет проверок side/check.
-- Это холодная таблица для read-only querying.
```

### Cron daily

```sql
-- Архивировать старые строки, не принадлежащие OPEN-позициям
INSERT INTO whale_trades_archive (...)
SELECT wt.*
FROM whale_trades wt
WHERE wt.traded_at < NOW() - INTERVAL '90 days'
  AND NOT EXISTS (
    -- КРИТИЧЕСКОЕ ОГРАНИЧЕНИЕ: не трогать OPEN-позиции
    SELECT 1 FROM whale_trade_roundtrips rt
    WHERE rt.wallet_address = wt.wallet_address
      AND rt.market_id = wt.market_id
      AND rt.outcome = wt.outcome
      AND rt.status = 'OPEN'
  );
-- Затем удалить из whale_trades
DELETE FROM whale_trades wt
WHERE wt.traded_at < NOW() - INTERVAL '90 days'
  AND NOT EXISTS (...same subquery...);
```

## Критическое ограничение (INFRA-029-PREP-B)

DELETE удаляет ТОЛЬКО строки, НЕ принадлежащие OPEN-позициям.

Условие: `NOT EXISTS (open roundtrip с тем же wallet_address+market_id+outcome)`.

**Причина:** `roundtrip_builder --rebuild` делает полный скан всех BUY из `whale_trades` (без курсора/фильтра по времени). Если OPEN-позиция имеет исторический BUY, удалённый из `whale_trades`, rebuild не восстановит этот roundtrip.

## Что НЕ затрагивается

- ON CONFLICT в `WhaleTradesRepo.save_trade()`
- Unique-стратегия на `whale_trades`
- `save_trade()` метод
- `trigger_copy_whale_trade`

## Обратимость

Да. Механика не меняет горячую таблицу структурно, только перемещает данные в archive.

## Не сделано в этом task

- Реализация DDL для archive
- Реализация cron-скрипта
- Расчёт размера archive и итогового объёма горячей таблицы