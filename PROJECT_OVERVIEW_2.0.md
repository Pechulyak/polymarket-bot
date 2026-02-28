# POLYMARKET BOT — PROJECT OVERVIEW 2.0
Версия: 2026-02
Статус: Architecture Ready | Paper Phase Initialization

---

# 1. ТЕКУЩИЙ СТАТУС

Архитектура реализована.
Docker-инфраструктура готова.
Whale detection интегрирован.
Builder API подключен.
Risk management (Kelly) внедрен.
Paper trading доступен.
Live trading выключен.

Метрики пока не зафиксированы (приоритет Недели 1).

---

# 2. ЦЕЛЬ ДО 31.03.2026

Запуск контролируемого live-режима с подтвержденным статистическим edge.

Edge определяется через:
- положительное expectancy
- winrate > 60%
- ROI +25% на виртуальном банкролле
- управляемый drawdown

Live запрещен без подтверждения.

---

# 3. СТРАТЕГИЯ НА ДАННЫЙ МОМЕНТ

Primary:
- Whale Copy (адаптивный Kelly sizing)

Secondary (тестируются параллельно):
- Cross-platform arbitrage
- Market inefficiency detection
- Аномалии потока сделок

Стратегии тестируются изолированно.
Никакой гибрид в прод до подтверждения edge каждой из них.

---

# 4. ФАЗЫ ДО ПРОДАКШЕНА

## Неделя 1 — Системная стабилизация
- Настройка взаимодействия ChatGPT ↔ Roo
- Введение PROJECT_STATE.md
- Метрики paper trading
- Проверка устойчивости

Критерий: стабильный pipeline + измеряемость.

---

## Недели 2–3 — Paper Optimization
- Whale quality filtering
- ROI измерения
- Drawdown контроль
- Research-driven improvements

KPI:
- ROI +25%
- WR >60%
- Discrete loss clusters отсутствуют

---

## Неделя 4 — Controlled Live
- Минимальный капитал
- Ограниченный риск
- Активация только после статистического подтверждения

---

# 5. УПРАВЛЕНИЕ

ChatGPT (Project):
- Strategy (оркестратор)
- Research (анализ)

Roo:
- реализация
- changelog
- errors-log

GitHub:
- источник правды по коду

ChatGPT получает snapshot состояния через PROJECT_STATE.md.

---

# 6. РИСК-ПРИНЦИПЫ

- Kelly-based sizing
- Никакого live без edge
- Любая ошибка фиксируется
- Drawdown контролируется

---

# 7. ЧТО МЫ НЕ ДЕЛАЕМ

- Не предполагаем доходность без данных
- Не доверяем optimistic ROI
- Не масштабируем до доказательства edge
- Не включаем live по ощущению

---

# 8. ГЛАВНЫЙ KPI

Не “заработать быстро”.
А построить устойчивую управляемую торговую систему.

---

Последнее обновление: 2026-02