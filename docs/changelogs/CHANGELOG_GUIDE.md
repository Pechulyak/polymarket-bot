# CHANGELOG SYSTEM - Master Chat Aggregation

## Обзор

Master Chat агрегирует изменения от всех специализированных чатов в единый CHANGELOG.md. Это позволяет отслеживать прогресс проекта и формировать milestone коммиты.

## Структура Changelog

```
docs/changelogs/
├── MASTER_CHANGELOG.md          # Общий changelog (агрегирует все)
├── development.md               # Изменения от Development чата
├── architecture.md             # Изменения от Architecture чата
├── research.md                 # Изменения от Research чата
├── testing.md                  # Изменения от Testing чата
├── devops.md                   # Изменения от DevOps чата
└── risk.md                     # Изменения от Risk чата
```

## Формат Changelog

### Для Специализированных Чатов

Каждый чат создает/обновляет свой файл в `docs/changelogs/[chat-name].md`:

```markdown
# Changelog - [Chat Name]

## [Date] - [Task Description]

### Added
- [новые файлы/функции]

### Changed
- [измененные файлы]

### Fixed
- [исправленные баги]

### Tests
- [добавленные тесты]

### Technical Details
- [важные технические детали]

### Breaking Changes
- [если есть]

### Performance Impact
- [влияние на производительность]
```

### Для Master Chat

Master Chat агрегирует все чат-логи в `docs/changelogs/MASTER_CHANGELOG.md`:

```markdown
# Master Changelog

## [MILESTONE] - [Version] - [Date]

### 🎯 Development
**From:** Development Chat  
**Summary:** [краткое описание]

- Added: [список]
- Changed: [список]
- Files: [список файлов]

### 🏗️ Architecture
**From:** Architecture Chat
...

### 📊 Research
...

### 🧪 Testing
...

### 🚀 DevOps
...

### 🛡️ Risk
...

---
**Total Changes:** [N] files  
**Breaking Changes:** [Y/N]  
**Ready for Release:** [Y/N]
```

## Workflow

### 1. Специализированный Чат Завершает Задачу

```
[ЧАТ] → [MASTER]

ЗАДАЧА ЗАВЕРШЕНА: [название]

CHANGELOG (добавить в docs/changelogs/[chat-name].md):

### [YYYY-MM-DD] - [Task Name]

#### Added
- src/module/file.py - [описание]

#### Changed
- src/module/other.py - [описание изменений]

#### Tests
- tests/unit/test_file.py - [описание тестов]

#### Technical Details
- [важные детали]

ФАЙЛЫ ИЗМЕНЕНЫ:
- src/... (N файлов)
- tests/... (M файлов)

ПОЛНЫЙ DIFF:
```diff
[diff или ссылка на коммит]
```
```

### 2. Master Chat Агрегирует

```
[MASTER] Читает все чат-логи → Создает MASTER_CHANGELOG.md → Milestone Commit
```

### 3. Milestone Commit

```bash
git add docs/changelogs/
git commit -m "milestone: [version] - [description]

Changes:
- Development: [summary]
- Architecture: [summary]
- [other chats]: [summary]

Total: [N] files changed
[breaking changes if any]"
```

## Правила Ведения Changelog

### Для Специализированных Чатов:

1. **Всегда создавайте changelog** при завершении задачи
2. **Используйте даты** в формате YYYY-MM-DD
3. **Будьте конкретны**: конкретные файлы, функции, строки
4. **Указывайте причину**: почему было сделано изменение
5. **Включайте тесты**: отдельный раздел для тестов
6. **Отмечайте breaking changes**: отдельным блоком
7. **Измеряйте impact**: performance, security, maintainability

### Для Master Chat:

1. **Агрегируйте регулярно**: после каждой крупной задачи
2. **Синхронизируйте с git**: changelog отражает git history
3. **Создавайте milestone коммиты**: только с обновленным changelog
4. **Архивируйте старые версии**: при выпуске новой milestone
5. **Связывайте с issues**: если используется GitHub Issues

## Шаблоны

### Шаблон для Development Chat

Сохранен в: `docs/changelogs/TEMPLATE_development.md`

### Шаблон для Master Chat

Сохранен в: `docs/changelogs/TEMPLATE_master.md`

## Автоматизация (будущее)

В идеале:
```bash
# Скрипт агрегации
python scripts/generate_changelog.py

# Создает MASTER_CHANGELOG.md из всех чат-логов
# Проверяет consistency с git log
# Готовит milestone commit message
```

## Примеры

### Пример: Development Chat

```markdown
# Changelog - Development

## 2026-02-06 - Implement CopyTradingEngine

### Added
- src/execution/copy_trading_engine.py
  - CopyTradingEngine class
  - Whale signal processing
  - Proportional position sizing
  - Position tracking
- tests/unit/test_copy_trading.py
  - Test signal decoding
  - Test position sizing
  - Test risk integration

### Changed
- src/execution/__init__.py
  - Added CopyTradingEngine export
- src/config/settings.py
  - Added COPY_TRADING_ settings

### Technical Details
- Uses Web3.py for transaction decoding
- Integrates with RiskManager for position limits
- Async/await throughout for performance
- Kelly Criterion for sizing (capped at 25%)

### Performance Impact
- Expected latency: 200-500ms per trade
- Memory usage: ~10MB for position tracking

### Breaking Changes
- None
```

### Пример: Master Chat Aggregation

```markdown
# Master Changelog

## [MILESTONE] v0.2.0 - 2026-02-06

### 🤖 Development
**Summary:** Implemented Copy Trading strategy

- Added: CopyTradingEngine, tests
- Changed: Execution module structure
- Files: 5 changed, 2 added

### 🏗️ Architecture
**Summary:** Updated execution architecture

- Added: Copy trading data flow
- Changed: Sequence diagrams
- Files: 2 docs updated

### 🧪 Testing
**Summary:** Unit tests for copy trading

- Added: 15 test cases
- Coverage: 87%
- All tests passing

---
**Total Changes:** 9 files  
**Breaking Changes:** No  
**Ready for Release:** Yes
```

## Проверка Changelog

### Перед отправкой в Master:

- [ ] Дата указана (YYYY-MM-DD)
- [ ] Все измененные файлы перечислены
- [ ] Тесты описаны отдельно
- [ ] Breaking changes отмечены
- [ ] Технические детали включены
- [ ] Diff приложен или доступен

### Перед Milestone Commit:

- [ ] Все чат-логи прочитаны
- [ ] MASTER_CHANGELOG.md обновлен
- [ ] Версия и дата указаны
- [ ] Breaking changes явно отмечены
- [ ] Готовность к релизу подтверждена
