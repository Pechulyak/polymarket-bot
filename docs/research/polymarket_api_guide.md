# Polymarket API Guide

## Статус: АКТУАЛЬНО (февраль 2026)

## Executive Summary

API ключ получен и работает. Баланс отображается корректно (~9.93 USDCe). Все тесты пройдены успешно.

### Полученные данные:
- API Key: a6c43dd7-352c-6f39-0ea9-c70556b5b4b4
- Funder Address: 0xdcff4B12d198E22fb581aaC4B8d6504135Fe1fEa
- Баланс: 9925021 (9.93 USDCe)
- Доступно маркетов: 269

### Rate Limits:
- General: 15000/10s
- CLOB: 9000/10s
- Trading: 3500/10s (burst)
- Статус: Unverified (100/день)

---

## Builder API (Gasless Transactions)

### Что даёт Builder API:
- **Gasless transactions** - Polymarket оплачивает gas за пользователей
- **Order attribution** - ордера атрибутируются к вашему builder
- **Fee share** - получаете долю от комиссий
- **Safe/Proxy wallets** - автоматическое развертывание кошельков

### Builder Tiers (Лимиты)

| Tier | Daily Relayer Txn | API Rate Limits | Requirements |
|------|-------------------|-----------------|--------------|
| Unverified | 100/day | Standard | None (permissionless) |
| Verified | 3,000/day | Higher | Application approval |
| Partner | Unlimited | Highest | Partnership agreement |

### Как получить Builder API Key

**Шаг 1: Доступ к Builder Profile**
- Перейти: https://polymarket.com/settings?tab=builder
- Или: Профиль → Builders

**Шаг 2: Создание API Keys**
1. В разделе **Builder Keys** нажать "Create Key"
2. Ключ генерируется автоматически
3. Получаете: `key`, `secret`, `passphrase`

**Шаг 3: Настройка SDK**
```typescript
import { BuilderConfig, BuilderApiKeyCreds } from "@polymarket/builder-signing-sdk";

const builderConfig = new BuilderConfig({
  localBuilderCreds: new BuilderApiKeyCreds({
    key: process.env.BUILDER_API_KEY,
    secret: process.env.BUILDER_SECRET,
    passphrase: process.env.BUILDER_PASSPHRASE
  })
});
```

### Использование Relayer Client

```typescript
import { ClobClient } from "@polymarket/clob-client";
import { RelayerClient } from "@polymarket/relayer-client";

const relayer = new RelayerClient(
  "https://relayer.polymarket.com",
  builderConfig
);

// Gasless order placement
const order = await clob.createOrder({
  tokenId: "...",
  price: 0.75,
  size: 100,
  side: "BUY"
});

const result = await relayer.executeOrder(order);
```

### Альтернативы если Builder API недоступен

**1. Safe Wallet (Gnosis Safe)**
- Multi-sig кошелёк
- Требует: 2/3 ключей для подписи
- Минус: не gasless, нужно платить за деплой

**2. Direct Private Key**
- Подписание напрямую через EOA
- Минус: менее безопасно, не рекомендуется для production
- Пример: `py-clob-client` с `PrivateKeySigner`

**3. Relayer Service (Custom)**
- Свой relayer сервер
- Требует: отдельная инфраструктура
- SDK: `@polymarket/builder-signing-server`

### Ресурсы
- Builder Program: docs.polymarket.com/developers/builders/builder-intro
- Builder Tiers: docs.polymarket.com/developers/builders/builder-tiers
- Builder Keys: docs.polymarket.com/developers/builders/builder-profile
- SDK: github.com/Polymarket/builder-signing-sdk

---

## Тесты

Все тесты прошли успешно:
1. test_one_price.py - цены получены ($0.49/$0.51)
2. test_orderbook.py - orderbook получен (16 bids/asks)
3. test_balance.py - баланс отображается ($9.93)
4. list_all_markets.py - найдено 269 маркетов

## Источники
- docs.polymarket.com
- github.com/Polymarket/py-clob-client
- Получено февраль 2026
