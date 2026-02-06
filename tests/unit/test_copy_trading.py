# -*- coding: utf-8 -*-
"""Unit tests for CopyTradingEngine.

Tests cover:
    - Whale tracking and management
    - Position sizing calculations
    - Trade signal processing
    - Position opening and closing
    - Risk integration
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import asyncio

from execution.copy_trading_engine import (
    CopyTradingEngine,
    CopyPosition,
    WhaleSignal,
)


class TestWhaleSignal:
    """Test WhaleSignal dataclass."""

    def test_whale_signal_creation(self):
        """Test creating a WhaleSignal."""
        signal = WhaleSignal(
            address="0x1234567890abcdef",
            market_id="0xabc123",
            side="BUY",
            amount=Decimal("5000"),
            price=Decimal("0.55"),
            tx_hash="0xdeadbeef",
            block_number=12345678,
            is_opening=True,
        )

        assert signal.address == "0x1234567890abcdef"
        assert signal.market_id == "0xabc123"
        assert signal.side == "BUY"
        assert signal.amount == Decimal("5000")
        assert signal.price == Decimal("0.55")
        assert signal.is_opening is True


class TestCopyPosition:
    """Test CopyPosition dataclass."""

    def test_position_creation(self):
        """Test creating a CopyPosition."""
        position = CopyPosition(
            market_id="0xabc123",
            entry_price=Decimal("0.55"),
            size=Decimal("10.0"),
            whale_address="0x1234567890abcdef",
            entry_time=1234567890.0,
        )

        assert position.market_id == "0xabc123"
        assert position.entry_price == Decimal("0.55")
        assert position.size == Decimal("10.0")
        assert position.pnl == Decimal("0")
        assert position.exit_price is None


class TestCopyTradingEngineInitialization:
    """Test CopyTradingEngine initialization."""

    @pytest.fixture
    def mock_risk_manager(self):
        """Create a mock risk manager."""
        mock = MagicMock()
        mock.can_trade.return_value = (True, "OK")
        return mock

    @pytest.fixture
    def mock_executor(self):
        """Create a mock order executor."""
        return AsyncMock()

    @pytest.fixture
    def engine_config(self):
        """Create default engine configuration."""
        return {
            "whale_addresses": [
                "0x1234567890abcdef1234567890abcdef12345678",
                "0xabcdef1234567890abcdef1234567890abcdef12",
            ],
            "whale_balances": {
                "0x1234567890abcdef1234567890abcdef12345678": Decimal("100000"),
                "0xabcdef1234567890abcdef1234567890abcdef12": Decimal("50000"),
            },
            "copy_capital": Decimal("70.0"),
            "min_copy_size": Decimal("5.0"),
            "max_copy_size": Decimal("20.0"),
        }

    def test_initialization(self, engine_config, mock_risk_manager, mock_executor):
        """Test engine initialization."""
        engine = CopyTradingEngine(
            config=engine_config,
            risk_manager=mock_risk_manager,
            executor=mock_executor,
        )

        assert len(engine.get_tracked_whales()) == 2
        assert engine.config["copy_capital"] == Decimal("70.0")
        assert len(engine.positions) == 0

    def test_tracked_whales_lowercase(self, engine_config, mock_risk_manager, mock_executor):
        """Test that whale addresses are stored in lowercase."""
        engine = CopyTradingEngine(
            config=engine_config,
            risk_manager=mock_risk_manager,
            executor=mock_executor,
        )

        whales = engine.get_tracked_whales()
        assert all(w == w.lower() for w in whales)


class TestWhaleManagement:
    """Test whale tracking management."""

    @pytest.fixture
    def engine(self):
        """Create an engine for testing."""
        config = {
            "whale_addresses": [],
            "copy_capital": Decimal("70.0"),
            "min_copy_size": Decimal("5.0"),
            "max_copy_size": Decimal("20.0"),
        }
        mock_risk = MagicMock()
        mock_exec = AsyncMock()

        return CopyTradingEngine(
            config=config,
            risk_manager=mock_risk,
            executor=mock_exec,
        )

    def test_add_whale(self, engine):
        """Test adding a whale."""
        engine.add_whale("0xABC123", Decimal("150000"))

        assert "0xabc123" in engine.get_tracked_whales()
        assert engine.config["whale_balances"]["0xabc123"] == Decimal("150000")

    def test_remove_whale(self, engine):
        """Test removing a whale."""
        engine.add_whale("0xABC123")
        assert len(engine.get_tracked_whales()) == 1

        engine.remove_whale("0xABC123")
        assert len(engine.get_tracked_whales()) == 0

    def test_remove_whale_cleans_positions(self, engine):
        """Test that removing whale cleans up position tracking."""
        engine.add_whale("0xABC123")
        engine.whale_positions["0xabc123"] = {"market1": {"side": "BUY"}}

        engine.remove_whale("0xABC123")
        assert "0xabc123" not in engine.whale_positions


class TestPositionSizing:
    """Test position sizing calculations."""

    @pytest.fixture
    def engine(self):
        """Create engine with known configuration."""
        config = {
            "whale_addresses": ["0xwhale1"],
            "whale_balances": {"0xwhale1": Decimal("100000")},
            "copy_capital": Decimal("70.0"),
            "min_copy_size": Decimal("5.0"),
            "max_copy_size": Decimal("20.0"),
        }
        mock_risk = MagicMock()
        mock_exec = AsyncMock()

        return CopyTradingEngine(
            config=config,
            risk_manager=mock_risk,
            executor=mock_exec,
        )

    def test_calculate_copy_size_basic(self, engine):
        """Test basic position sizing.

        Whale: $100k balance, trades $5k (5% conviction)
        Us: $70 capital -> $3.50 copy size
        """
        signal = WhaleSignal(
            address="0xwhale1",
            market_id="0xmarket1",
            side="BUY",
            amount=Decimal("5000"),
            price=Decimal("0.55"),
            tx_hash="0xtx",
            block_number=100,
            is_opening=True,
        )

        size = engine._calculate_copy_size(signal)
        # 5% of $70 = $3.50, but min is $5, so return 0 (too small to copy)
        assert size == Decimal("0")

    def test_calculate_copy_size_respects_max(self, engine):
        """Test that copy size respects maximum limit."""
        signal = WhaleSignal(
            address="0xwhale1",
            market_id="0xmarket1",
            side="BUY",
            amount=Decimal("50000"),  # 50% of whale balance
            price=Decimal("0.55"),
            tx_hash="0xtx",
            block_number=100,
            is_opening=True,
        )

        size = engine._calculate_copy_size(signal)
        # 50% of $70 = $35, but max is $20
        assert size == Decimal("20.0")

    def test_calculate_copy_size_below_minimum(self, engine):
        """Test that small trades return 0."""
        signal = WhaleSignal(
            address="0xwhale1",
            market_id="0xmarket1",
            side="BUY",
            amount=Decimal("500"),  # 0.5% of whale balance
            price=Decimal("0.55"),
            tx_hash="0xtx",
            block_number=100,
            is_opening=True,
        )

        size = engine._calculate_copy_size(signal)
        # 0.5% of $70 = $0.35, below $5 minimum
        assert size == Decimal("0")


class TradeOpeningClosing:
    """Test trade opening and closing logic."""

    @pytest.fixture
    def engine(self):
        """Create engine with open position."""
        config = {
            "whale_addresses": ["0xwhale1"],
            "whale_balances": {"0xwhale1": Decimal("100000")},
            "copy_capital": Decimal("70.0"),
            "min_copy_size": Decimal("5.0"),
            "max_copy_size": Decimal("20.0"),
        }
        mock_risk = MagicMock()
        mock_risk.can_trade.return_value = (True, "OK")
        mock_exec = AsyncMock()
        mock_exec.execute.return_value = {
            "success": True,
            "fill_price": 0.55,
            "order_id": "order123",
        }

        engine = CopyTradingEngine(
            config=config,
            risk_manager=mock_risk,
            executor=mock_exec,
        )

        # Add existing position
        engine.positions["0xmarket1"] = CopyPosition(
            market_id="0xmarket1",
            entry_price=Decimal("0.50"),
            size=Decimal("10.0"),
            whale_address="0xwhale1",
            entry_time=1234567890.0,
        )

        # Track whale position
        engine.whale_positions["0xwhale1"] = {
            "0xmarket1": {"side": "BUY", "size": Decimal("10000")}
        }

        return engine

    def test_is_opening_trade_new_position(self, engine):
        """Test detection of new position opening."""
        signal = WhaleSignal(
            address="0xwhale1",
            market_id="0xnewmarket",  # New market
            side="BUY",
            amount=Decimal("5000"),
            price=Decimal("0.55"),
            tx_hash="0xtx",
            block_number=100,
            is_opening=True,
        )

        assert engine._is_opening_trade(signal) is True

    def test_is_opening_trade_same_side(self, engine):
        """Test detection of adding to existing position."""
        signal = WhaleSignal(
            address="0xwhale1",
            market_id="0xmarket1",
            side="BUY",  # Same side as existing
            amount=Decimal("5000"),
            price=Decimal("0.55"),
            tx_hash="0xtx",
            block_number=100,
            is_opening=True,
        )

        assert engine._is_opening_trade(signal) is True

    def test_is_opening_trade_opposite_side(self, engine):
        """Test detection of position closing."""
        signal = WhaleSignal(
            address="0xwhale1",
            market_id="0xmarket1",
            side="SELL",  # Opposite side - closing
            amount=Decimal("5000"),
            price=Decimal("0.55"),
            tx_hash="0xtx",
            block_number=100,
            is_opening=False,
        )

        assert engine._is_opening_trade(signal) is False

    @pytest.mark.asyncio
    async def test_handle_whale_exit_closes_position(self, engine):
        """Test that whale exit closes our position."""
        signal = WhaleSignal(
            address="0xwhale1",
            market_id="0xmarket1",
            side="SELL",  # Whale selling
            amount=Decimal("5000"),
            price=Decimal("0.60"),
            tx_hash="0xtx",
            block_number=100,
            is_opening=False,
        )

        result = await engine._handle_whale_exit(signal)

        assert result is not None
        assert "0xmarket1" not in engine.positions
        engine.executor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_whale_exit_different_whale(self, engine):
        """Test that we don't close if different whale exits."""
        signal = WhaleSignal(
            address="0xwhale2",  # Different whale
            market_id="0xmarket1",
            side="SELL",
            amount=Decimal("5000"),
            price=Decimal("0.60"),
            tx_hash="0xtx",
            block_number=100,
            is_opening=False,
        )

        result = await engine._handle_whale_exit(signal)

        assert result is None
        engine.executor.execute.assert_not_called()


class TestTransactionProcessing:
    """Test transaction processing flow."""

    @pytest.fixture
    def engine(self):
        """Create engine for transaction tests."""
        config = {
            "whale_addresses": ["0xwhale1"],
            "whale_balances": {"0xwhale1": Decimal("100000")},
            "copy_capital": Decimal("70.0"),
            "min_copy_size": Decimal("5.0"),
            "max_copy_size": Decimal("20.0"),
        }
        mock_risk = MagicMock()
        mock_risk.can_trade.return_value = (True, "OK")
        mock_exec = AsyncMock()

        return CopyTradingEngine(
            config=config,
            risk_manager=mock_risk,
            executor=mock_exec,
        )

    def test_process_untracked_transaction(self, engine):
        """Test that untracked transactions are ignored."""
        tx = {
            "from": "0xunknown",
            "to": engine.CLOB_ADDRESS,
            "input": "0x1234",
        }

        result = asyncio.run(engine.process_transaction(tx))
        assert result is None

    def test_process_non_clob_transaction(self, engine):
        """Test that non-CLOB transactions are ignored."""
        tx = {
            "from": "0xwhale1",
            "to": "0xothercontract",
            "input": "0x1234",
        }

        result = asyncio.run(engine.process_transaction(tx))
        assert result is None


class TestStatistics:
    """Test engine statistics."""

    @pytest.fixture
    def engine(self):
        """Create engine with some activity."""
        config = {
            "whale_addresses": ["0xwhale1", "0xwhale2"],
            "copy_capital": Decimal("70.0"),
            "min_copy_size": Decimal("5.0"),
            "max_copy_size": Decimal("20.0"),
        }
        mock_risk = MagicMock()
        mock_exec = AsyncMock()

        engine = CopyTradingEngine(
            config=config,
            risk_manager=mock_risk,
            executor=mock_exec,
        )

        # Add some positions
        engine.positions["0xmarket1"] = CopyPosition(
            market_id="0xmarket1",
            entry_price=Decimal("0.50"),
            size=Decimal("10.0"),
            whale_address="0xwhale1",
            entry_time=1234567890.0,
        )
        engine.positions["0xmarket2"] = CopyPosition(
            market_id="0xmarket2",
            entry_price=Decimal("0.60"),
            size=Decimal("15.0"),
            whale_address="0xwhale2",
            entry_time=1234567890.0,
            pnl=Decimal("5.0"),
        )

        return engine

    def test_get_stats(self, engine):
        """Test statistics retrieval."""
        stats = engine.get_stats()

        assert stats["tracked_whales"] == 2
        assert stats["open_positions"] == 2
        assert stats["total_exposure"] == "25.0"  # 10 + 15
        assert stats["unrealized_pnl"] == "5.0"


class TestKellyCriterionIntegration:
    """Test Kelly Criterion integration in sizing."""

    def test_proportional_sizing_follows_kelly_principle(self):
        """Test that sizing follows Kelly principle (proportional to edge)."""
        config = {
            "whale_addresses": ["0xwhale1"],
            "whale_balances": {"0xwhale1": Decimal("100000")},
            "copy_capital": Decimal("100.0"),  # $100 bankroll
            "min_copy_size": Decimal("1.0"),
            "max_copy_size": Decimal("50.0"),
        }
        mock_risk = MagicMock()
        mock_exec = AsyncMock()

        engine = CopyTradingEngine(
            config=config,
            risk_manager=mock_risk,
            executor=mock_exec,
        )

        # Test conviction levels
        test_cases = [
            # (whale_trade, whale_balance, expected_conviction)
            (Decimal("1000"), Decimal("100000"), Decimal("0.01")),   # 1%
            (Decimal("5000"), Decimal("100000"), Decimal("0.05")),   # 5%
            (Decimal("10000"), Decimal("100000"), Decimal("0.10")),  # 10%
            (Decimal("20000"), Decimal("100000"), Decimal("0.20")),  # 20%
        ]

        for trade_size, whale_balance, expected_conviction in test_cases:
            signal = WhaleSignal(
                address="0xwhale1",
                market_id="0xmarket",
                side="BUY",
                amount=trade_size,
                price=Decimal("0.55"),
                tx_hash="0xtx",
                block_number=100,
                is_opening=True,
            )

            # Update whale balance
            engine.config["whale_balances"]["0xwhale1"] = whale_balance

            size = engine._calculate_copy_size(signal)
            expected_size = Decimal("100") * expected_conviction

            assert size == expected_size, (
                f"Trade size {trade_size}, balance {whale_balance}: "
                f"expected {expected_size}, got {size}"
            )


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_missing_whale_balances_use_default(self):
        """Test that missing whale balances use default value."""
        config = {
            "whale_addresses": ["0xwhale1"],
            # No whale_balances specified
            "copy_capital": Decimal("70.0"),
            "min_copy_size": Decimal("5.0"),
            "max_copy_size": Decimal("20.0"),
        }
        mock_risk = MagicMock()
        mock_exec = AsyncMock()

        engine = CopyTradingEngine(
            config=config,
            risk_manager=mock_risk,
            executor=mock_exec,
        )

        signal = WhaleSignal(
            address="0xwhale1",
            market_id="0xmarket1",
            side="BUY",
            amount=Decimal("5000"),
            price=Decimal("0.55"),
            tx_hash="0xtx",
            block_number=100,
            is_opening=True,
        )

        size = engine._calculate_copy_size(signal)
        # 5% of $70 = $3.5, below min $5, so return 0
        assert size == Decimal("0")

    @pytest.mark.asyncio
    async def test_risk_manager_rejection(self):
        """Test that rejected trades are not executed."""
        config = {
            "whale_addresses": ["0xwhale1"],
            "whale_balances": {"0xwhale1": Decimal("100000")},
            "copy_capital": Decimal("70.0"),
            "min_copy_size": Decimal("5.0"),
            "max_copy_size": Decimal("20.0"),
        }
        mock_risk = MagicMock()
        mock_risk.can_trade.return_value = (False, "Daily loss limit")
        mock_exec = AsyncMock()

        engine = CopyTradingEngine(
            config=config,
            risk_manager=mock_risk,
            executor=mock_exec,
        )

        # Mock decode_trade to return a valid signal
        signal = WhaleSignal(
            address="0xwhale1",
            market_id="0xmarket1",
            side="BUY",
            amount=Decimal("10000"),
            price=Decimal("0.55"),
            tx_hash="0xtx",
            block_number=100,
            is_opening=True,
        )
        engine._decode_trade = MagicMock(return_value=signal)

        tx = {
            "from": "0xwhale1",
            "to": engine.CLOB_ADDRESS,
            "input": "0x1234",
        }

        result = await engine.process_transaction(tx)

        assert result is None
        mock_exec.execute.assert_not_called()
