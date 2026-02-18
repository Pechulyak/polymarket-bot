# Known Polymarket Whales

## Источник: PANews Analysis (January 2026)
## Статья: "In-depth analysis of 27,000 trades by Polymarket's top ten whales"

## Подтверждённые адреса (Ethereum/Polygon)

| # | Username | Wallet Address | Dec 2025 Profit | True Win Rate | Strategy |
|---|----------|---------------|-----------------|---------------|----------|
| 1 | DrPufferfish | `0xdB27Bf2Ac5D428a9c63dbc914611036855a6c56E` | $2.06M | ~50.9% | Diversified betting, low-prob → high-prob |
| 2 | 0xafEe | `0xee50a31c3f5a7c77824b12a941a54388a2827ed6` | $929k | ~69.5% | Low-frequency, pop culture predictions |
| 3 | gmanas | TBD (автозапуск) | $1.97M | ~51.8% | High-frequency automated |
| 4 | simonbanza | TBD (swing trader) | $1.04M | ~57.6% | Swing trading, probability fluctuations |
| 5 | gmpm | TBD | $2.93M (total) | ~56.16% | Asymmetric hedging |

## Топ-10 китов по версии PANews (декабрь 2025)

1. **SeriouslySirius** - $3.29M, 53.3% real WR (with zombie orders: 73.7%)
2. **DrPufferfish** - $2.06M, 50.9% real WR
3. **gmanas** - $1.97M, 51.8% real WR
4. **simonbanza** - $1.04M, 57.6% real WR (highest WR, swing trader)
5. **gmpm** - $2.93M total, 56.16% WR
6. **Swisstony** - $860k, high-frequency arbitrage (5527 trades)
7. **0xafEe** - $929k, 69.5% WR (low-frequency, pop culture)
8. **0x006cc** - $1.27M, 54% WR
9. **RN1** - NEGATIVE example (-$920k total), 42% WR
10. **Cavs2** - $630k, 50.43% WR

## Как получить адреса

Адреса можно получить через:
1. **Polymarket Data API**: `GET /trades?user=0xADDRESS`
2. **Polymarket Profile URL**: `polymarket.com/profile/0xADDRESS`
3. **Leaderboard**: `polymarket.com/leaderboard`

## Использование

Добавить в БД:
```python
from src.research.whale_tracker import WhaleTracker

whales = [
    WhaleStats(
        wallet_address="0xdB27Bf2Ac5D428a9c63dbc914611036855a6c56E",
        total_trades=5000,
        win_rate=Decimal("0.509"),
        total_profit_usd=Decimal("2060000"),
        avg_trade_size_usd=Decimal("500"),
        risk_score=5,
    ),
    # ...
]
```

## Важные замечания

1. **"Zombie orders"**: Многие киты имеют незакрытые ордера, которые маскируют реальный WR
2. **Real WR**: Истинный win rate значительно ниже исторического (на 20-30%)
3. **Hedging**: Большинство использует сложные hedging стратегии, а не простое YES+NO
4. **Liquidity**: Арбитраж часто ограничен ликвидностью
5. **Copy trading**: Не рекомендуется - те же проблемы с "zombie orders"

## Обновление данных

Запустить скрипт:
```bash
python -m src.research.whale_tracker --update-whales
```
