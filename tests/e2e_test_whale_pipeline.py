# -*- coding: utf-8 -*-
"""E2E Test: Whale Signal → Paper Trade → DB

End-to-end test that verifies the complete pipeline:
1. Mock whale signal creation
2. Processing through CopyTradingEngine
3. Paper trade execution via VirtualBankroll
4. Database persistence
5. Metrics retrieval
"""
import asyncio
import os
import sys
from decimal import Decimal
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Настройка DB
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5433/postgres")


async def run_e2e_test():
    """Run E2E test for whale signal pipeline."""
    print("=== Starting E2E Test ===\n")

    # 1. Импорт модулей
    from execution.copy_trading_engine import CopyTradingEngine, WhaleSignal
    from strategy.virtual_bankroll import VirtualBankroll

    # 2. Инициализация Virtual Bankroll (начинаем с $100)
    virtual_bankroll = VirtualBankroll(initial_balance=Decimal("100.00"))
    virtual_bankroll.set_database(DATABASE_URL)

    # 3. Создать mock risk manager
    class MockRiskManager:
        def can_trade(self, size: float, market_id: str = None, strategy: str = None):
            return True, "allowed"

        def check_drawdown(self, current_pnl: float):
            return True

        def record_trade(self, strategy: str, pnl: float, market_id: str = None):
            pass

    # 4. Инициализация CopyTradingEngine в paper mode
    engine = CopyTradingEngine(
        config={
            "copy_capital": Decimal("70.0"),
            "whale_addresses": [],
            "whale_balances": {},
            "min_copy_size": Decimal("1.0"),
            "max_copy_size": Decimal("20.0"),
        },
        risk_manager=MockRiskManager(),
        executor=None,  # No real executor for paper
        mode="paper",
        virtual_bankroll=virtual_bankroll,
    )

    # 5. Добавить тестового кита в tracked whales
    test_whale_address = "0x" + "a" * 40  # 0xaaaaaaaaaaaaaaaa...
    engine.add_whale(test_whale_address, Decimal("100000"))  # $100k volume

    # Add whale stats for quality check
    from research.whale_tracker import WhaleStats
    engine.whale_stats[test_whale_address.lower()] = WhaleStats(
        wallet_address=test_whale_address.lower(),
        total_trades=150,
        win_rate=Decimal("0.65"),
        avg_trade_size_usd=Decimal("5000"),
        risk_score=3,
    )

    # Also add to config for proportional size calculation
    engine.config["whale_balances"][test_whale_address.lower()] = Decimal("100000")

    print(f"Whale added: {test_whale_address[:20]}...")
    print(f"Tracked whales: {engine.get_tracked_whales()}")
    print()

    # 6. Симулировать whale signal (используя WhaleSignal dataclass)
    signal = WhaleSignal(
        address=test_whale_address,
        market_id="0x1234567890abcdef1234567890abcdef",
        side="BUY",
        amount=Decimal("5000"),  # $5000 trade
        price=Decimal("0.55"),
        tx_hash="0x" + "b" * 64,
        block_number=12345678,
        is_opening=True,
    )

    print(f"Created whale signal:")
    print(f"  - Address: {signal.address[:20]}...")
    print(f"  - Market: {signal.market_id[:20]}...")
    print(f"  - Side: {signal.side}")
    print(f"  - Amount: ${signal.amount}")
    print(f"  - Price: {signal.price}")
    print()

    # 7. Запустить обработку сигнала через process_transaction
    # (process_whale_signal требует WhaleTradeSignal из real_time_whale_monitor)
    tx_data = {
        "from": test_whale_address,
        "to": CopyTradingEngine.CLOB_ADDRESS,
        "input": "0x",  # Skip decoding for this test
        "hash": signal.tx_hash,
        "blockNumber": signal.block_number,
    }

    # Process directly through paper trade execution
    # Since we can't decode tx without web3, we'll simulate the flow
    copy_size = engine._calculate_proportional_size(signal)
    print(f"Calculated copy size: ${copy_size}")

    # Execute paper trade directly
    result = await engine._execute_paper_trade(
        market_id=signal.market_id,
        side=signal.side,
        size=copy_size,
        price=signal.price,
        strategy="copy",
        whale_address=test_whale_address,
    )

    print(f"\n=== Execution Results ===")
    print(f"Success: {result.get('success', False)}")
    print(f"Trade ID: {result.get('trade_id', 'N/A')}")
    print(f"Fill Price: {result.get('fill_price', 'N/A')}")
    print(f"Size: {result.get('size', 'N/A')}")
    print(f"Mode: {result.get('mode', 'N/A')}")
    print()

    # 8. Проверить DB запись
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Проверить есть ли записи
    cur.execute("SELECT COUNT(*) FROM trades;")
    trade_count = cur.fetchone()[0]
    print(f"=== Database Check ===")
    print(f"Trades in DB: {trade_count}")

    # Проверить последнюю запись
    cur.execute("""
        SELECT id, market_id, side, size, price, exchange, status 
        FROM trades 
        ORDER BY id DESC LIMIT 1;
    """)
    last_trade = cur.fetchone()
    print(f"Last trade: {last_trade}")

    cur.close()
    conn.close()
    print()

    # 9. Проверить метрики из VirtualBankroll
    stats = virtual_bankroll.get_stats()
    print(f"=== Virtual Bankroll Metrics ===")
    print(f"Current balance: ${stats.current_balance}")
    print(f"Total trades: {stats.total_trades}")
    print(f"Open positions: {stats.open_positions}")
    print(f"Closed trades: {stats.closed_trades}")
    print(f"Winning trades: {stats.winning_trades}")
    print(f"Losing trades: {stats.losing_trades}")
    print(f"Win rate: {stats.win_rate}")
    print(f"Total PnL: ${stats.total_pnl}")
    print(f"Consecutive losses: {stats.consecutive_losses}")
    print()

    # 10. Engine stats
    engine_stats = engine.get_stats()
    print(f"=== Engine Stats ===")
    print(f"Tracked whales: {engine_stats['tracked_whales']}")
    print(f"Open positions: {engine_stats['open_positions']}")
    print(f"Signals processed: {engine_stats['signals_processed']}")
    print(f"Trades executed: {engine_stats['trades_executed']}")
    print()

    # Summary
    print("=== E2E Test Summary ===")
    success = (
        result.get("success", False) and
        trade_count >= 1 and
        stats.total_trades >= 1
    )
    print(f"Test PASSED: {success}")

    return {
        "success": success,
        "trade_count": trade_count,
        "stats": {
            "current_balance": str(stats.current_balance),
            "total_trades": stats.total_trades,
            "win_rate": str(stats.win_rate),
            "total_pnl": str(stats.total_pnl),
        },
        "last_trade": last_trade,
    }


if __name__ == "__main__":
    result = asyncio.run(run_e2e_test())
    print(f"\nFinal result: {result}")
