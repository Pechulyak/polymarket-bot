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