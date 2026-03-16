# Код изменения для open_price / close_price миграции

## SQL Migration (готов к выполнению)

```sql
-- scripts/migration_add_open_price.sql
ALTER TABLE trades ADD COLUMN IF NOT EXISTS open_price NUMERIC(20, 8);
UPDATE trades SET open_price = price WHERE status = 'open' AND open_price IS NULL;
ALTER TABLE trades RENAME COLUMN price TO close_price;
ALTER TABLE trades ALTER COLUMN close_price DROP NOT NULL;
```

---

## 1. src/strategy/virtual_bankroll.py

### Изменение #1: Сохранение entry price (строка ~560)
**Было:**
```python
entry_price=price,  # used directly
```

**Стало:**
```python
entry_price=price,  # сохраняем как open_price при записи в БД
```

### Изменение #2: INSERT в БД (строка ~620)
**Было:**
```python
"price": float(price),
```

**Стало:**
```python
"open_price": float(price),  # записываем цену входа
"close_price": None,         # пока null для открытых позиций
```

### Изменение #3: UPDATE при закрытии (строка ~755)
**Было:**
```python
price = :close_price,
```

**Стало:**
```python
close_price = :close_price,  # только close_price, НЕ open_price
```

---

## 2. src/strategy/paper_position_settlement.py

### Изменение #1: Чтение entry price (строка ~239)
**Было:**
```python
t.price as entry_price,
```

**Стало:**
```python
t.open_price as entry_price,  # используем правильное поле
```

### Изменение #2: UPDATE при settlement (строка ~310)
**Было:**
```python
UPDATE trades
SET status = 'closed',
    settled_at = NOW(),
    price = :close_price,  -- БАГ: перезаписывает entry price!
    gross_pnl = :gross_pnl,
    total_fees = :total_fees,
    net_pnl = :net_pnl
```

**Станет:**
```python
UPDATE trades
SET status = 'closed',
    settled_at = NOW(),
    close_price = :close_price,  -- только close_price
    gross_pnl = :gross_pnl,
    total_fees = :total_fees,
    net_pnl = :net_pnl
WHERE trade_id = :trade_id
-- open_price остаётся нетронутым!
```

---

## 3. src/main.py

### Изменение #1: Deduplication check (строка ~49)
**Было:**
```python
AND price = :price
```

**Станет:**
```python
AND open_price = :price  # проверяем по цене входа
```

---

## 4. src/execution/copy_trading_engine.py

### Изменение #1: Deduplication check (строка ~363)
**Было:**
```python
AND price = :price
```

**Станет:**
```python
AND open_price = :price  # проверяем по цене входа
```

---

## 5. src/monitoring/notification_worker.py

### Изменение #1: Чтение цены для уведомлений (строка ~101)
**Было:**
```python
price=float(row.price) if row.price else 0.0,
```

**Станет:**
```python
# Для открытых позиций - показываем entry price
# Для закрытых - показываем close price
price=float(row.close_price) if row.close_price else (float(row.open_price) if row.open_price else 0.0),
```

---

## PnL Calculation (формула)

После миграции PnL рассчитывается так:

```python
# Для LONG (buy) позиций:
gross_pnl = (close_price - open_price) * size

# Пример:
# open_price = 0.95, close_price = 1.0, size = 2.00
# gross_pnl = (1.0 - 0.95) * 2.00 = 0.10 USD
```

---

## Тестирование

После применения миграции и кода:

1. **Создать новую сделку** - проверить что `open_price` заполнен
2. **Settlement сделки** - проверить что `close_price` заполнен, `open_price` НЕ изменён
3. **Проверить PnL** - формула `(close_price - open_price) * size` работает корректно
