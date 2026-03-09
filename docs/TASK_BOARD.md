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

**W-003 — Strategy Metrics Engine** (READY)

---

## EPIC 1 — WHALE COPY STRATEGY

| ID | Задача | Статус |
|----|--------|--------|
| W-001 | Whale Detection Pipeline | TODO |
| W-002 | Whale Tracking Database | TODO |
| W-003 | Strategy Metrics Engine | **READY** |
| W-004 | Copy Trading Engine Integration | TODO |

---

## EPIC 2 — ARBITRAGE SYSTEM

| ID | Задача | Статус |
|----|--------|--------|
| W-005 | Cross-Exchange Arbitrage Detector | TODO |
| W-006 | Bybit Hedging Integration | TODO |
| W-007 | Order Book Inefficiency Scanner | TODO |

---

## EPIC 3 — RISK MANAGEMENT

| ID | Задача | Статус |
|----|--------|--------|
| W-008 | Kill Switch Mechanisms | TODO |
| W-009 | Position Limits & Drawdown Controls | TODO |
| W-010 | Commission & Fee Tracker | TODO |

---

## EPIC 4 — SYSTEM / INFRASTRUCTURE

| ID | Задача | Статус |
|----|--------|--------|
| W-011 | Docker Orchestration & Deployment | TODO |
| W-012 | Monitoring & Alerting System | TODO |

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
