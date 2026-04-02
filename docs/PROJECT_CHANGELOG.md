# PROJECT CHANGELOG

Версия: v1.0  
Формат: краткий лог изменений (без технических деталей)

---

## ПРАВИЛА ВЕДЕНИЯ

1. Записываются ВСЕ задачи (TRD / SYS / STRAT и др.)
2. Только ключевая идея — без логов, SQL и кода
3. Максимум **15 строк на одну задачу**
4. Описывается результат, а не процесс
5. Один блок = одна задача

---

## ФОРМАТ ЗАПИСИ

### <TASK_ID> — <Краткое название>

**Дата:** YYYY-MM-DD  

**Описание:**  
<1–2 предложения, суть изменения или проблемы>

**До:**  
<что было неправильно / отсутствовало>

**После:**  
<что стало после выполнения задачи>

**Влияние:**  
<на какие части системы повлияло>

**Зависимости / риски (опционально):**  
<если есть важные последствия или ограничения>

---

## ПРИМЕР

### TRD-413 — Whale trades ingestion audit

**Дата:** 2026-03-23  

**Описание:**  
Выявлена критическая потеря данных при сборе whale_trades.

**До:**  
Использовался глобальный feed с лимитом 500 сделок, без per-wallet загрузки.

**После:**  
Определена необходимость перехода на targeted API fetch.

**Влияние:**  
Затронуты whale_tracker, whale_detector, логика квалификации китов.

**Зависимости / риски:**  
Требуется redesign ingestion pipeline.

---

### TRD-419 — Migration to activity-based whales schema

**Дата:** 2026-03-23  

**Описание:**  
Перевод логики китов с legacy полей на activity-based модель.

**До:**  
Использовались некорректные метрики (win_rate, total_profit_usd).

**После:**  
Введены поля activity: trades_count, days_active, volume.

**Влияние:**  
Обновлены whale_detector, whale_tracker и схема БД.

---

### PHASE1-001 — WhaleTradesRepo

**Дата:** 2026-04-02  

**Описание:**  
Создание единой точки записи whale_trades с валидацией и счётчиками.

**До:**  
Разные модули (whale_detector, whale_tracker) писали в БД напрямую, без централизованной валидации.

**После:**  
WhaleTradesRepo обеспечивает统一的 валидацию (side, size, price), дедупликацию по tx_hash, счётчики saved/rejected/duplicates.

**Влияние:**  
Новые модули: src/db/whale_trades_repo.py, src/db/__init__.py. Тесты: tests/test_whale_trades_repo.py (7/7 passed).

---

### PHASE1-002: whale_detector → WhaleTradesRepo

**Дата:** 2026-04-02  

**Описание:**  
Переключение whale_detector.save_trade_to_db() на WhaleTradesRepo.

**До:**  
save_trade_to_db() использовал async engine + save_whale_trade() напрямую.

**После:**  
Делегирует в WhaleTradesRepo: валидация (side, size, price), дедупликация, счётчики.

**Влияние:**  
 whale_detector.py — изменения в import, __init__, set_database, _ensure_database, save_trade_to_db, _paper_poll_loop. Логирование repo stats каждые 30 сек.

---

### PHASE1-003: whale_tracker → WhaleTradesRepo

**Дата:** 2026-04-02  

**Описание:**  
Переключение whale_tracker.save_whale_trade() на WhaleTradesRepo.

**До:**  
save_whale_trade() использовал async engine + save_whale_trade() из whale_trade_writer.

**После:**  
Делегирует в WhaleTradesRepo: валидация (side, size, price), дедупликация, счётчики.

**Влияние:**  
whale_tracker.py — изменения в import, __init__, set_database, _ensure_database, save_whale_trade. Старый код закомментирован (rollback-ready).

**Зависимости / риски:**  
whale_trade_writer.py → DEPRECATED, используется только в virtual_bankroll (Фаза 2+).

---

## ОГРАНИЧЕНИЯ

Запрещено в CHANGELOG:

- логи выполнения
- SQL-запросы
- куски кода
- длинные объяснения
- повторение TASK_BOARD
- метрики (они в snapshot)
- описание “как делали”

---

## ПРИНЦИП

CHANGELOG должен отвечать на вопрос:

> Что изменилось в системе и зачем это было сделано?

А не:

> Как именно мы это реализовывали.

---

## ИТОГ

CHANGELOG = краткая история решений, а не технический отчёт