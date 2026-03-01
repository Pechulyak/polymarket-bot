# Errors Log — что пошло не так и как решили

## Формат записи
### [ДАТА] Короткое название ошибки
- **Симптом:** что наблюдалось
- **Причина:** почему произошло
- **Решение:** что сделали
- **Правило:** как избежать в будущем

---

## Зафиксированные ошибки

### [2026-02-28] Киты не сохраняются в БД (ИСПРАВЛЕНО)

- **Симптом:** В памяти: 10-35 tracked whales, в БД: 0 записей. Логи показывают: `whale_save_failed error='column "total_volume_usd" of relation "whales" does not exist'`
- **Причина:** Таблица `whales` в БД не имела колонок, требуемых кодом `_save_whale_to_db()` в whale_detector.py:
  - total_volume_usd
  - avg_trade_size_usd
  - status
  - trades_last_3_days
  - days_active
- **Решение:** Добавлены колонки через ALTER TABLE:
  ```sql
  ALTER TABLE whales ADD COLUMN IF NOT EXISTS total_volume_usd DECIMAL(20, 8) NOT NULL DEFAULT 0;
  ALTER TABLE whales ADD COLUMN IF NOT EXISTS avg_trade_size_usd DECIMAL(20, 8) NOT NULL DEFAULT 0;
  ALTER TABLE whales ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'discovered';
  ALTER TABLE whales ADD COLUMN IF NOT EXISTS trades_last_3_days INTEGER NOT NULL DEFAULT 0;
  ALTER TABLE whales ADD COLUMN IF NOT EXISTS days_active INTEGER NOT NULL DEFAULT 0;
  ```
- **Проверка:** COUNT(*) FROM whales = 15+, киты сохраняются со статусом discovered
- **Правило:** Обновить scripts/init_db.sql чтобы схема соответствовала коду

### [2026-02-28] Stage 2 — киты не сохраняются в БД

- **Симптом:** В памяти 10 tracked whales, Quality=0, в БД 0 записей. Логи не показывают ошибок сохранения.
- **Причина:**
  1. `known_whales_loaded` показывало 10 whales — это из старой БД (кеш в памяти после перезапуска)
  2. WhaleDetector использует `database_url` из env, но в whale-detector контейнере был неправильный DATABASE_URL
  3. После исправления DATABASE_URL в docker-compose.yml — сохранение всё равно не работает
  4. Возможная причина: whales не проходят `daily_trade_threshold` (5 trades/day), поэтому не попадают в tracked list
- **Решение (в процессе):**
  - Исправлен DATABASE_URL в docker-compose.yml: `postgresql://postgres:156136ar@postgres:5432/polymarket`
  - Добавлены логи `save_whale_to_db` для диагностики
  - Изменена логика: теперь сохраняются ВСЕ discovered киты, не только quality
- **Правило:** Всегда проверять DATABASE_URL через `docker compose exec <service> env | grep DATABASE`

### [2026-02] PostgreSQL порт
- **Симптом:** подключение к БД падало
- **Причина:** стандартный порт 5432 вместо 5433
- **Решение:** исправить DATABASE_URL на порт 5433
- **Правило:** PostgreSQL всегда на 5433 в этом проекте

---

### [2026-02] WhaleDetector AttributeError — self.config не сохранялся
- **Симптом:** контейнер whale-detector падал сразу после запуска
- **Причина:** в whale_detector.py `__init__` принимал `config` но не делал `self.config = config`
- **Решение:** добавить `self.config = config` в `__init__` после строки 148
- **Правило:** при создании класса всегда проверять что все параметры `__init__` сохраняются в `self`

---

### [2026-03-01] E2E Test — fromisoformat error в whale_tracker.py

- **Симптом:** E2E тест падал с ошибкой `TypeError: fromisoformat() argument must be str, datetime or None`
- **Причина:** whale_tracker.py вызывал `datetime.fromisoformat()` без проверки типа данных, полученных из БД
- **Решение:** Добавлена проверка типа данных и преобразование через `ast.literal_eval()` для кортежей
- **Правило:** Всегда проверять тип данных полученных из БД перед вызовом методов datetime

### [2026-03-01] E2E Test — AttributeError в WhaleTracker

- **Симптом:** Ошибка `AttributeError: 'WhaleTracker' object has no attribute 'config'`
- **Причина:** WhaleTracker.__init__ не инициализировал self.config
- **Решение:** Добавлена инициализация self.config = config в WhaleTracker.__init__
- **Правило:** При создании класса всегда проверять что все параметры __init__ сохраняются в self

---

### [2026-02-28] Whale Stats Incorrect — win_rate и profit были некорректны

#### Проблема 1: Некорректный win_rate
- **Симптом:** win_rate показывал процент от всех сделок кита (buy сделки)
- **Причина:** Считалось что "buy" = "win", но это не так! Покупка "Yes" - это просто позиция, не выигрыш
- **Решение:**
  - Введён `stats_mode: REALIZED` - статистика основана на реальных результатах копирования
  - win_rate теперь вычисляется как: realized_pnl > 0 / total_copied_trades
  - Используется realized_pnl из скопированных сделок в БД
- **Правило:** Не путать buy сделку с выигрышем. Win = позиция закрылась с прибылью

#### Проблема 2: Некорректный profit
- **Симптом:** profit показывал volume, а не реальную прибыль
- **Причина:** API не предоставляет PnL, использовался volume как прокси
- **Решение:**
  - profit теперь = realized_pnl из скопированных сделок
  - Добавлено поле `data_capability: PARTIAL` в PROJECT_STATE
- **Правило:** Не использовать volume как замену profit

#### Проблема 3: Разные risk_score в detector и tracker
- **Симптом:** risk_score вычислялся в двух местах с разной логикой
- **Причина:** Не было единого source-of-truth
- **Решение:**
  - risk_score_source_of_truth: tracker
  - whale_detector использует risk_score из whale_tracker
  - Единая логика в QUALITY_WHALE_CRITERIA
- **Правило:** Всегда иметь единый source-of-truth для ключевых метрик

#### Проблема 4: API Capability
- **Симптом:** Ожидали от API данные, которых нет
- **Причина:** Polymarket Data API НЕ предоставляет: direct PnL, win/loss статус сделок
- **Решение:**
  - Добавлен аудит в docs/data_capability_audit.md
  - data_capability: PARTIAL
  - stats_mode: REALIZED (только при копировании получаем реальные результаты)
- **Правило:** Всегда проверять фактические возможности API перед использованием
