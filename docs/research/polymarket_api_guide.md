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
