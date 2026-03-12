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
| SYS-311 | Fix Whale Activity Counters | DONE |
| SYS-312 | Whale Universe Quality Analysis | DONE |
| SYS-313 | Hide DONE Tasks in HTML Task Board | DONE |
| SYS-314 | Paper Trade Trigger Pipeline Audit | DONE |
| SYS-315 | Fix Duplicate Suppression in Paper Trade Trigger | DONE |
| SYS-317 | Audit trades lifecycle for paper performance tracking | DONE |
| SYS-318 | Paper Position Settlement Engine | IN_PROGRESS |
| SYS-319 | Paper Execution Gap Audit | DONE |
| SYS-320 | Paper Trade Close Lifecycle Audit | DONE |
| SYS-321 | Подключение settlement engine для paper сделок | DONE |
| SYS-322 | Security Hardening: No Public Ports Policy | READY |

---

## EPIC 5 — STRATEGY / RESEARCH

| ID | Задача | Статус |
|----|--------|--------|
| SYS-325 | Paper Trade Quality Audit (High Price Entries) | READY |

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

*Обновлено: 2026-03-12*
