# TASK_BOARD

> Единственный source of truth для статусов и списка задач проекта.
> Обновляется STRATEGY. Roo выполняет задачи через TASK PACK.

---

## Статусы задач

| Статус | Описание |
|--------|----------|
| TODO | Задача в бэклоге, ожидает реализации |
| IN_PROGRESS | Задача передана Roo, идёт работа |
| READY | Задача выполнена, готова к тестированию |
| TESTED | Задача протестирована, готова к merge |
| DONE | Задача закоммичена и запушена |

---

## Текущий приоритет

*(None - waiting for tasks)*

---

## EPIC 1 — WHALE COPY STRATEGY

| ID | Задача | Статус |
|----|--------|--------|
| W-001 | Whale Detection Pipeline | TODO |
| W-002 | Whale Tracking Database | TODO |
| W-003 | Strategy Metrics Engine | TODO |
| W-004 | Copy Trading Engine Integration | TODO |

---

## EPIC 2 — ARBITRAGE SYSTEM

| ID | Задача | Статус |
|----|--------|--------|
| A-101 | Cross-Exchange Arbitrage Detector | TODO |
| A-102 | Bybit Hedging Integration | TODO |
| A-103 | Order Book Inefficiency Scanner | TODO |

---

## EPIC 3 — SMART MONEY

| ID | Задача | Статус |
|----|--------|--------|
| S-201 | Kill Switch Mechanisms | TODO |
| S-202 | Position Limits & Drawdown Controls | TODO |
| S-203 | Commission & Fee Tracker | TODO |

---

## EPIC 4 — SYSTEM / INFRASTRUCTURE

| ID | Задача | Статус |
|----|--------|--------|
| SYS-301 | Docker Orchestration & Deployment | TODO |
| SYS-302 | Monitoring & Alerting System | TODO |
| SYS-304 | Add TASK_BOARD governance rules | DONE |
| SYS-305 | Generate docs/TASK_BOARD.html | DONE |
| SYS-306 | Persistent local web server for TASK_BOARD | DONE |
| SYS-309 | Daily Data Audit Snapshot | READY |

---

## Правила управления задачами

1. **Создание задач**: Только STRATEGY может добавлять новые задачи
2. **Изменение статусов**: Roo обновляет статус после подтверждения выполнения
3. **Переход к IN_PROGRESS**: Roo запрашивает подтверждение перед стартом
4. **Готовность к TESTING**: После завершения работы Roo помечает READY
5. **Merge в DONE**: После review и merge STRATEGY помечает DONE

---

## Workflow

```
STRATEGY → [TASK_PACK] → ROO → [выполнение] → STRATEGY → [review] → DONE
```

---

*Обновлено: 2026-03-09*
