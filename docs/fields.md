Polymarket API (эндпоинт `/markets`) возвращает следующие поля для маркета:

## Статус маркета
- `active` - маркет активен
- `closed` - маркет закрыт  
- `archived` - маркет в архиве
- `accepting_orders` - принимаются ли ордера
- `accepting_order_timestamp` - когда начали приниматься ордера

## Лимиты торговли
- `minimum_order_size` - минимальный размер ордера
- `minimum_tick_size` - минимальный тик цены

## Идентификаторы
- `condition_id` - ID условия на блокчейне
- `question_id` - ID вопроса
- `market_slug` - URL-слаг маркета

## Контент
- `question` - вопрос маркета (заголовок)
- `description` - полное описание
- `icon` - URL иконки
- `image` - URL изображения

## Временные метки
- `end_date_iso` - дата окончания (ISO 8601)
- `game_start_time` - время начала события
- `seconds_delay` - задержка в секундах

## Комиссии
- `maker_base_fee` - базовая комиссия мейкера
- `taker_base_fee` - базовая комиссия тейкера
- `rewards` - объект с `rates`, `min_size`, `max_spread`

## Смарт-контракт
- `fpmm` - адрес FPMM (Fixed Product Market Maker) контракта

## Токены (массив outcomes)
- `token_id` - ID токена
- `outcome` - название исхода (Yes/No)
- `price` - текущая цена
- `winner` - является ли выигрышным

## Дополнительно
- `neg_risk` - Negative Risk маркет
- `neg_risk_market_id` - ID для neg risk
- `neg_risk_request_id` - request ID
- `is_50_50_outcome` - 50/50 маркет
- `tags` - теги
- `notifications_enabled` - включены ли уведомления
- `enable_order_book` - включен ли ордербук