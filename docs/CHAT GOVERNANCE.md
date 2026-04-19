CHAT GOVERNANCE — Technical Version (готово для вставки в .md)
CHAT GOVERNANCE v1.0

Обновлено: 2026-03-01
Статус: ACTIVE

1. Управляющая модель
Проект использует централизованную архитектуру принятия решений.
Единственный оркестратор: STRATEGY
Все остальные чаты выполняют вспомогательные роли.

2. Роли и полномочия
🧠 STRATEGY (Master Orchestrator)
Полномочия:
Определяет roadmap
Принимает стратегические решения
Формирует ORCHESTRATOR TASK PACK
Передаёт задачи Roo
Одобряет / отклоняет research-гипотезы
Определяет переход paper → live
Обновляет стратегические параметры
Запрещено:
Вносить изменения в код напрямую
Исполнять задачи без Roo

🐋 WHALE OPTIMIZATION (Research Support)
Scope:
Qualification logic design
Performance model design
Statistical validation framework
Portfolio construction logic
Ограничения:
Не взаимодействует с Roo
Не меняет код
Работает только через Strategy

⚖️ ARBITRAGE RESEARCH
Scope:
Теоретический анализ арбитражных возможностей
Расчёт spread feasibility
ROI simulation
Frequency modelling
Запрещено:
Любая реализация
Любые технические изменения
Прямая постановка задач Roo

🧠 SMART MONEY RESEARCH

Scope:
Определение anomaly triggers
Event-based hypothesis
False positive modelling
Behavioural modelling
Запрещено:
Код
Execution
Задачи Roo

🔎 REVIEW

Scope:
Root cause analysis
Проверка архитектурной корректности
Минимальный фикс
Оценка рисков изменений
Не может:
Самостоятельно изменять архитектуру
Давать задачи Roo

🤖 ROO (Technical Executor)
Scope:
Реализация задач
Обновление changelog
Обновление errors-log
Выполнение TASK PACK
Обновление PROJECT_STATE
Запрещено:
Принимать стратегические решения
Изменять roadmap
Менять бизнес-логику без явного указания

3. Поток взаимодействия
Разрешённый поток:
Research → Strategy → Roo
Review → Strategy → Roo
Запрещённый поток:
Research → Roo
Review → Roo
Smart Money → Roo
Arbitrage → Roo

4. Приоритет стратегий
Primary Execution Lane:
Whale Copy
Secondary Research Lanes:
Arbitrage
Smart Money
Execution возможен только после approval Strategy.

5. Правило фокуса
В один момент времени Roo реализует только одну стратегическую линию.
Параллельная реализация нескольких стратегий запрещена.

6. Edge Governance
Live-режим может быть активирован только при выполнении:
ROI ≥ 25% (paper)
Winrate > 60%
Контролируемый drawdown
Статистически подтверждённый edge

---

## 7. TASK BOARD GOVERNANCE

**docs/TASK_BOARD.md** является каноническим источником списка задач проекта.

### Правила

1. Любые изменения TASK_BOARD выполняются только через Roo.
2. Strategy формирует изменение через ORCHESTRATOR TASK PACK.
3. Ручное редактирование TASK_BOARD.md запрещено.
4. Каждый commit изменения доски должен содержать:
   - TASK_ID
   - изменение статуса или структуры
5. TASK_BOARD.html является производным файлом и не редактируется вручную.

6. **Формат строки задачи** (строго):
   `| ID | Задача | Тег | Статус |`

   Четыре колонки обязательно. Тег — опциональный (пусто или `feature:xxx`).

7. **Название задачи**: краткое (3-8 слов), на русском языке, обязательно.
   Без описаний, goals, pre-conditions в названии.

8. **Inline-комментарии в TASK_BOARD запрещены**. Блоки `Description:`,
   `**Goals:**`, `**Pre-conditions:**`, `**Definition of Done:**` и аналогичные
   многострочные пояснения под строкой задачи в TASK_BOARD не включаются.
   Подробная спецификация задачи хранится:
   - в CHANGELOG (после выполнения) или
   - в отдельном документе задачи (`docs/tasks/TASK_ID.md`), если требуется
     развёрнутый спек.

9. **Префикс задачи = префикс эпика**. Задача принадлежит ровно одному эпику.
   Допустимые префиксы:
   - `PIPE-*` — Pipeline Refactoring
   - `TRD-*` — Trading Correctness
   - `DATA-*` — Data Integrity
   - `ANA-*` — Analytics
   - `SEC-*` — Security
   - `INFRA-*` — Infrastructure
   - `HYG-*` — System Hygiene
   - `DOC-*` — Documentation & Governance
   - `BUG-*` — Cross-cutting Bugs

   Связь между эпиками / фичами, затрагивающими несколько эпиков —
   через поле «Тег» в формате `feature:xxx`
   (например: `feature:live-execution`, `feature:paper-rotation`).

10. **Структура TASK_BOARD.md** фиксирована:
    - Шапка (статусы, приоритет, правила, workflow)
    - 3 LANE-блока (WHALE, ARB, SMART) — информационные, задач внутри нет
    - 9 EPIC-блоков с таблицами задач
    - Footer с датой обновления

    Добавление новых LANE или EPIC — отдельная задача уровня STRATEGY,
    требует обновления этого документа.

11. **Допустимые статусы задачи**:
    `TODO`, `IN_PROGRESS`, `READY`, `DONE`, `FROZEN`, `CANCELLED`, `BACKLOG`.

    В TASK_BOARD.html не включаются задачи со статусом `DONE` и `CANCELLED`
    (фильтр генератора).

---

## SECURITY POLICY — NETWORK EXPOSURE

External ports are strictly forbidden for the trading infrastructure.

Project directories must never be exposed via HTTP servers.

Forbidden examples:
- python3 -m http.server
- nginx serving project root
- any file server exposing /root/polymarket-bot
- any service exposing .env or configuration files

All services must bind to:
- 127.0.0.1

Firewall must block external access unless explicitly required.

If external access is ever required (rare cases):
- reverse proxy required
- authentication required
- directory access disabled
- .env must never be reachable
- service must not point to project root

Violation of this rule is considered a critical security failure.