# -*- coding: utf-8 -*-
"""Virtual Bankroll Tracker for Paper Trading.

Tracks virtual trades without executing real transactions.
Calculates PnL, fees, and maintains balance history for paper trading validation.

Example:
    >>> from strategy.virtual_bankroll import VirtualBankroll, VirtualTradeResult
    >>> from decimal import Decimal
    >>>
    >>> bankroll = VirtualBankroll(initial_balance=Decimal("100.00"))
    >>> result = await bankroll.execute_virtual_trade(
    ...     market_id="0xabc123",
    ...     side="buy",
    ...     size=Decimal("10.0"),
    ...     price=Decimal("0.55"),
    ...     strategy="copy",
    ...     fees=Decimal("0.11"),
    ...     gas=Decimal("1.50")
    ... )
    >>> print(result.pnl)
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional
from uuid import uuid4

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.data.storage.market_title_cache import get_market_title

logger = structlog.get_logger(__name__)


def _mask_database_url(url: str) -> str:
    """Mask password in database URL for safe logging."""
    if not url:
        return "None"
    # Replace password between : and @ with ****
    import re
    return re.sub(r':([^@]+)@', ':****@', url)


@dataclass
class VirtualTradeResult:
    """Result of a virtual trade execution.

    Attributes:
        trade_id: Unique identifier for this trade
        market_id: Market/token identifier
        side: Trade side ("buy" or "sell")
        size: Position size in USD
        price: Execution price
        commission: Trading commission paid
        gas_cost: Gas cost paid
        net_pnl: Net profit/loss (positive = profit, negative = loss)
        is_open: True if position is still open
        opened_at: Timestamp when position was opened
        closed_at: Timestamp when position was closed (None if open)
        strategy: Strategy that generated this trade
        whale_source: Source whale address (if copy trading)
    """

    trade_id: str
    market_id: str
    side: str
    size: Decimal
    price: Decimal
    commission: Decimal
    gas_cost: Decimal
    net_pnl: Decimal
    is_open: bool
    opened_at: datetime
    closed_at: Optional[datetime] = None
    strategy: str = "unknown"
    whale_source: str = ""


@dataclass
class VirtualPosition:
    """Tracks an open virtual position.

    Attributes:
        trade_id: Unique identifier for the opening trade
        market_id: Market identifier
        side: Position side ("buy" or "sell")
        size: Position size in USD
        entry_price: Entry price
        commission: Commission paid on entry
        gas_cost: Gas cost on entry
        opened_at: Timestamp when position was opened
        strategy: Strategy that opened this position
        whale_source: Source whale address (if copy trading)
    """

    trade_id: str
    market_id: str
    side: str
    size: Decimal
    entry_price: Decimal
    commission: Decimal
    gas_cost: Decimal
    opened_at: datetime
    strategy: str
    whale_source: str = ""


@dataclass
class BankrollStats:
    """Statistics for the virtual bankroll.

    Attributes:
        current_balance: Current virtual balance
        total_trades: Total number of trades executed
        open_positions: Number of currently open positions
        closed_trades: Number of closed positions
        winning_trades: Number of winning trades
        losing_trades: Number of losing trades
        win_rate: Win rate as decimal (0.0 to 1.0)
        total_pnl: Total profit/loss realized
        consecutive_losses: Current streak of consecutive losing trades
        max_consecutive_losses: Maximum consecutive losses seen
    """

    current_balance: Decimal
    total_trades: int
    open_positions: int
    closed_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    total_pnl: Decimal
    consecutive_losses: int
    max_consecutive_losses: int


class VirtualBankroll:
    """Virtual Bankroll Tracker for Paper Trading.

    Manages virtual currency for paper trading without executing real trades.
    All operations are simulated and logged to PostgreSQL for analysis.

    IMPORTANT: Bankroll changes (available/allocated) happen ONLY after creating
    trades record in database. The pipeline is:
    1. whale_trades → paper_trades
    2. paper_trades → check bankroll (available >= entry_cost)
    3. trades(status='open') created
    4. bankroll: available -= entry_cost, allocated += entry_cost
    5. paper_trade_notifications

    Attributes:
        initial_balance: Starting virtual balance (default: $100)
        database_url: PostgreSQL connection URL
    """

    def __init__(
        self,
        initial_balance: Decimal = Decimal("100.00"),
        database_url: Optional[str] = None,
    ) -> None:
        """Initialize Virtual Bankroll.

        Args:
            initial_balance: Starting virtual balance (default: $100)
            database_url: PostgreSQL connection URL (optional, can be set later)
        """
        # Core bankroll fields
        self.balance = initial_balance  # Total capital (available + allocated)
        self.available = initial_balance  # Capital available for new positions
        self.allocated = Decimal("0")  # Capital locked in open positions
        self.initial_balance = initial_balance
        
        self.database_url = database_url

        self._open_positions: Dict[str, VirtualPosition] = {}
        self._consecutive_losses: int = 0
        self._max_consecutive_losses: int = 0
        self._winning_trades: int = 0
        self._losing_trades: int = 0
        self._total_pnl: Decimal = Decimal("0")
        self._total_trades: int = 0
        self._engine = None
        self._Session = None

        logger.info(
            "virtual_bankroll_initialized",
            initial_balance=str(initial_balance),
            balance=str(self.balance),
            available=str(self.available),
            allocated=str(self.allocated),
        )

    def set_database(self, database_url: str) -> None:
        """Set database URL and initialize connection.

        Args:
            database_url: PostgreSQL connection URL
        """
        self.database_url = database_url
        self._engine = create_engine(database_url)
        self._Session = sessionmaker(bind=self._engine)
        logger.info(
            "virtual_bankroll_database_configured", database_url=_mask_database_url(database_url)
        )

    def get_allocated_capital(self) -> Decimal:
        """Get current allocated capital.
        
        Returns:
            Current allocated capital (capital locked in open positions)
        """
        return self.allocated

    def get_available_capital(self) -> Decimal:
        """Get current available capital.
        
        Returns:
            Available capital for new positions
        """
        return self.available

    def _allocate_capital(self, entry_cost: Decimal) -> None:
        """Allocate capital when opening a position.
        
        IMPORTANT: This must be called AFTER creating the trades record.
        
        Args:
            entry_cost: Cost to open the position (size * price)
        """
        self.available -= entry_cost
        self.allocated += entry_cost
        
        logger.debug(
            "capital_allocated",
            entry_cost=str(entry_cost),
            new_available=str(self.available),
            new_allocated=str(self.allocated),
        )

    def _release_capital(self, exit_value: Decimal) -> None:
        """Release capital when closing a position.
        
        IMPORTANT: This must be called AFTER creating the trades record.
        
        Args:
            exit_value: Value received from closing the position
        """
        self.allocated -= exit_value
        self.available += exit_value
        
        logger.debug(
            "capital_released",
            exit_value=str(exit_value),
            new_available=str(self.available),
            new_allocated=str(self.allocated),
        )

    async def _ensure_database(self) -> None:
        """Ensure database connection is available."""
        if not self.database_url:
            logger.warning("virtual_bankroll_no_database")
            return

        if not self._engine:
            self._engine = create_engine(self.database_url)
            self._Session = sessionmaker(bind=self._engine)

    async def _save_virtual_trade(
        self,
        trade_id: str,
        market_id: str,
        side: str,
        size: Decimal,
        price: Decimal,  # entry price (open_price)
        commission: Decimal,
        gas_cost: Decimal,
        net_pnl: Decimal,
        is_open: bool,
        opened_at: datetime,
        closed_at: Optional[datetime],
        strategy: str,
        gross_pnl: Decimal = Decimal("0"),
        total_fees: Decimal = Decimal("0"),
        fiat_fees: Decimal = Decimal("0"),
        opportunity_id: Optional[str] = None,
        whale_source: str = "",
        market_title: Optional[str] = None,
        gas_cost_eth: Decimal = Decimal("0"),
        close_price: Optional[Decimal] = None,  # exit/settlement price
        outcome: Optional[str] = None,  # YES/NO outcome from paper_trades
    ) -> None:
        """Save virtual trade to PostgreSQL.

        Args:
            trade_id: Unique trade identifier
            market_id: Market identifier
            side: Trade side
            size: Position size
            price: Execution price
            commission: Trading commission
            gas_cost: Gas cost
            net_pnl: Net profit/loss
            is_open: Whether position is open
            opened_at: Opening timestamp
            closed_at: Closing timestamp (None if open)
            strategy: Trading strategy
            gross_pnl: Gross profit/loss before fees
            total_fees: Total fees (commission + gas)
            fiat_fees: Fiat fees
            opportunity_id: Associated opportunity ID
            market_title: Market title/question
        """
        await self._ensure_database()

        if not self._Session:
            return

        # For Builder-based paper mode (gasless transactions), fees are 0
        # TODO: Add separate implementation for fee-enabled markets
        db_commission = Decimal("0")
        db_gas_cost_eth = Decimal("0")
        db_gas_cost_usd = Decimal("0")
        db_fiat_fees = Decimal("0")
        db_total_fees = Decimal("0")

        session = self._Session()
        try:
            query = text("""
                INSERT INTO trades (
                    trade_id, market_id, side, size, open_price, close_price, exchange,
                    commission, gas_cost_eth, gas_cost_usd, net_pnl,
                    status, executed_at, settled_at, opportunity_id,
                    fiat_fees, gross_pnl, total_fees, market_title, whale_source, outcome
                ) VALUES (
                    :trade_id, :market_id, :side, :size, :open_price, :close_price, :exchange,
                    :commission, :gas_cost_eth, :gas_cost_usd, :net_pnl,
                    :status, :executed_at, :settled_at, :opportunity_id,
                    :fiat_fees, :gross_pnl, :total_fees, :market_title, :whale_source, :outcome
                )
                ON CONFLICT (trade_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    settled_at = EXCLUDED.settled_at,
                    close_price = EXCLUDED.close_price,
                    gross_pnl = EXCLUDED.gross_pnl,
                    total_fees = EXCLUDED.total_fees,
                    net_pnl = EXCLUDED.net_pnl,
                    outcome = EXCLUDED.outcome
            """)
            session.execute(
                query,
                {
                    "trade_id": trade_id,
                    "market_id": market_id,
                    "side": side,
                    "size": float(size),
                    "open_price": float(price),  # entry price
                    "close_price": float(close_price) if close_price else None,
                    "exchange": "VIRTUAL",
                    "commission": float(db_commission),
                    "gas_cost_eth": float(db_gas_cost_eth),
                    "gas_cost_usd": float(db_gas_cost_usd),
                    "net_pnl": float(net_pnl),
                    "status": "open" if is_open else "closed",
                    "executed_at": opened_at,
                    "settled_at": closed_at,
                    "opportunity_id": opportunity_id,
                    "fiat_fees": float(db_fiat_fees),
                    "gross_pnl": float(gross_pnl) if gross_pnl else None,
                    "total_fees": float(db_total_fees),
                    "market_title": market_title,
                    "whale_source": whale_source,
                    "outcome": outcome,
                },
            )
            session.commit()
            logger.debug("virtual_trade_saved", trade_id=trade_id, status="open" if is_open else "closed")
        except Exception as e:
            logger.error("virtual_trade_save_failed", trade_id=trade_id, error=str(e))
            session.rollback()
        finally:
            session.close()

    async def _save_bankroll_history(
        self, balance: Decimal, trade_id: Optional[str], action: str
    ) -> None:
        """Save bankroll state change to history.

        Args:
            current_balance: Current balance
            trade_id: Associated trade ID (if any)
            action: Action that triggered the change
        """
        await self._ensure_database()

        if not self._Session:
            return

        session = self._Session()
        try:
            # Persist into existing 'bankroll' table with available/allocated fields
            query = text(
                """
                INSERT INTO bankroll (
                    timestamp, total_capital, allocated, available,
                    daily_pnl, daily_drawdown, total_trades, win_count, loss_count
                ) VALUES (
                    NOW(), :balance, :allocated, :available, 0, 0, :total_trades, :win_count, :loss_count
                )
                ON CONFLICT DO NOTHING
                """
            )
            session.execute(
                query,
                {
                    "balance": float(balance),
                    "allocated": float(self.allocated),
                    "available": float(self.available),
                    "total_trades": self._total_trades,
                    "win_count": self._winning_trades,
                    "loss_count": self._losing_trades,
                },
            )
            session.commit()
            
            logger.debug(
                "bankroll_history_saved",
                balance=str(balance),
                allocated=str(self.allocated),
                available=str(self.available),
                action=action,
            )
        except Exception as e:
            logger.error("bankroll_history_save_failed", error=str(e))
            session.rollback()
        finally:
            session.close()

    async def _save_whale_trade_record(
        self,
        whale_address: str,
        market_id: str,
        side: str,
        size_usd: Decimal,
        price: Decimal,
        market_title: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> None:
        """Save whale trade record for tracking copy trading source.

        Args:
            whale_address: Source whale wallet address
            market_id: Market identifier
            side: Trade side
            size_usd: Trade size in USD
            price: Execution price
            market_title: Market question/title (optional)
            outcome: Trade outcome (YES/NO) - optional
        """
        await self._ensure_database()

        if not self._Session or not whale_address:
            return

        session = self._Session()
        try:
            query = text("""
                SELECT id FROM whales WHERE wallet_address = :address
            """)
            result = session.execute(query, {"address": whale_address.lower()})
            row = result.fetchone()

            if not row:
                logger.debug("whale_not_in_database", address=whale_address[:10])
                return

            whale_id = row[0]

            insert_query = text("""
                INSERT INTO whale_trades (
                    whale_id, market_id, market_title, side, size_usd, price, outcome, traded_at, source
                ) VALUES (
                    :whale_id, :market_id, :market_title, :side, :size_usd, :price, :outcome, NOW(), :source
                )
            """)
            session.execute(
                insert_query,
                {
                    "whale_id": whale_id,
                    "market_id": market_id,
                    "market_title": market_title,
                    "side": side,
                    "size_usd": float(size_usd),
                    "price": float(price),
                    "outcome": outcome,
                    "source": "REALTIME",
                },
            )
            session.commit()
            logger.debug(
                "whale_trade_recorded", whale_id=whale_id, market=market_id[:20]
            )

        except Exception as e:
            logger.error("whale_trade_save_failed", error=str(e))
            session.rollback()
        finally:
            session.close()

    async def execute_virtual_trade(
        self,
        market_id: str,
        side: str,
        size: Decimal,
        price: Decimal,
        strategy: str,
        fees: Decimal = Decimal("0.00"),
        gas: Decimal = Decimal("0.00"),
        whale_source: str = "",
        opportunity_id: Optional[str] = None,
        market_title: Optional[str] = None,
        outcome: Optional[str] = None,  # YES/NO outcome from paper_trades
    ) -> VirtualTradeResult:
        """Execute a virtual trade (does NOT execute real trade).

        IMPORTANT: Order of operations is critical:
        1. Check available capital (before any changes)
        2. Create trades record (status='open' for BUY)
        3. Allocate capital (available -= entry_cost, allocated += entry_cost)
        
        This ensures trades table is the source of truth and bankroll changes
        happen only after the trade is recorded.

        Args:
            market_id: Market/token identifier
            side: Trade side ("buy" or "sell")
            size: Position size in USD
            price: Execution price
            strategy: Trading strategy name
            fees: Trading commission (default: $0)
            gas: Gas cost (default: $0)
            whale_source: Source whale address for copy trading tracking
            opportunity_id: Associated opportunity ID (optional)
            market_title: Market title/question (optional)

        Returns:
            VirtualTradeResult with trade details

        Raises:
            ValueError: If insufficient available balance for trade
        """
        trade_id = str(uuid4())
        now = datetime.now()

        entry_cost = size * price
        total_cost = entry_cost + fees + gas

        # Check available capital BEFORE any changes
        if total_cost >= self.available:
            raise ValueError(
                f"Insufficient available capital: required {total_cost}, available {self.available}"
            )

        self._total_trades += 1

        if side.lower() == "buy":
            position = VirtualPosition(
                trade_id=trade_id,
                market_id=market_id,
                side="buy",
                size=size,
                entry_price=price,
                commission=fees,
                gas_cost=gas,
                opened_at=now,
                strategy=strategy,
                whale_source=whale_source,
            )
            self._open_positions[market_id] = position
            net_pnl = Decimal("0")
            gross_pnl = Decimal("0")
            is_open = True

        elif side.lower() == "sell":
            if market_id in self._open_positions:
                position = self._open_positions[market_id]
                del self._open_positions[market_id]

                entry_value = position.size * position.entry_price
                exit_value = size * price
                gross_pnl = exit_value - entry_value
                net_pnl = (
                    gross_pnl - fees - gas - position.commission - position.gas_cost
                )

                # Update total balance
                self.balance += exit_value - fees - gas
                is_open = False
            else:
                raise ValueError(f"No open position for market {market_id}")
        else:
            raise ValueError(f"Invalid side: {side}")

        if not is_open:
            if net_pnl > 0:
                self._winning_trades += 1
                self._consecutive_losses = 0
            else:
                self._losing_trades += 1
                self._consecutive_losses += 1
                self._max_consecutive_losses = max(
                    self._max_consecutive_losses, self._consecutive_losses
                )

            self._total_pnl += net_pnl

        result = VirtualTradeResult(
            trade_id=trade_id,
            market_id=market_id,
            side=side.lower(),
            size=size,
            price=price,
            commission=fees,
            gas_cost=gas,
            net_pnl=net_pnl,
            is_open=is_open,
            opened_at=now,
            closed_at=now if not is_open else None,
            strategy=strategy,
            whale_source=whale_source,
        )

        total_fees_calc = (
            fees + gas + position.commission + position.gas_cost
            if side.lower() == "sell"
            else fees + gas
        )

        # STEP 1: Save trade to database FIRST (source of truth)
        await self._save_virtual_trade(
            trade_id=result.trade_id,
            market_id=result.market_id,
            side=result.side,
            size=result.size,
            price=result.price,  # entry price
            commission=result.commission,
            gas_cost=result.gas_cost,
            net_pnl=result.net_pnl,
            is_open=result.is_open,
            opened_at=result.opened_at,
            closed_at=result.closed_at,
            strategy=result.strategy,
            gross_pnl=gross_pnl,
            total_fees=total_fees_calc,
            whale_source=whale_source,
            opportunity_id=opportunity_id,
            market_title=market_title,
            gas_cost_eth=Decimal("0"),
            close_price=None,  # no close price for open positions
            outcome=outcome,
        )

        # STEP 2: THEN allocate capital (only for BUY/open positions)
        # Balance stays the same - only available/allocated change
        if side.lower() == "buy" and is_open:
            self._allocate_capital(entry_cost)

        if whale_source:
            market_title = await get_market_title(market_id)
            await self._save_whale_trade_record(
                whale_address=whale_source,
                market_id=market_id,
                side=side.lower(),
                size_usd=size,
                price=price,
                market_title=market_title,
            )

        # Save bankroll history
        await self._save_bankroll_history(
            balance=self.balance, trade_id=trade_id, action=f"trade_{side.lower()}"
        )

        logger.info(
            "virtual_trade_executed",
            trade_id=trade_id,
            side=side.lower(),
            size=str(size),
            price=str(price),
            entry_cost=str(entry_cost),
            new_balance=str(self.balance),
            new_available=str(self.available),
            new_allocated=str(self.allocated),
            is_open=is_open,
            strategy=strategy,
            whale_source=whale_source[:10] if whale_source else "",
        )

        return result

    async def close_virtual_position(
        self,
        market_id: str,
        close_price: Decimal,
        fees: Decimal = Decimal("0.00"),
        gas: Decimal = Decimal("0.00"),
        outcome: Optional[str] = None,  # YES/NO outcome
    ) -> VirtualTradeResult:
        """Close an open virtual position and calculate PnL.

        IMPORTANT: Order of operations is critical:
        1. Create trades record (status='closed')
        2. Release capital (allocated -= exit_value, available += exit_value)
        
        This ensures trades table is the source of truth and bankroll changes
        happen only after the trade is recorded.

        Args:
            market_id: Market identifier of position to close
            close_price: Price at which to close
            fees: Trading commission for closing (default: $0)
            gas: Gas cost for closing (default: $0)

        Returns:
            VirtualTradeResult with closing details

        Raises:
            ValueError: If no open position exists for market_id
        """
        if market_id not in self._open_positions:
            raise ValueError(f"No open position for market {market_id}")

        position = self._open_positions[market_id]
        
        entry_value = position.size * position.entry_price
        exit_value = position.size * close_price

        if position.side == "buy":
            gross_pnl = exit_value - entry_value
        else:
            gross_pnl = entry_value - exit_value

        total_fees_calc = fees + gas + position.commission + position.gas_cost
        net_pnl = gross_pnl - total_fees_calc

        self._total_trades += 1

        if net_pnl > 0:
            self._winning_trades += 1
            self._consecutive_losses = 0
        else:
            self._losing_trades += 1
            self._consecutive_losses += 1
            self._max_consecutive_losses = max(
                self._max_consecutive_losses, self._consecutive_losses
            )

        self._total_pnl += net_pnl
        now = datetime.now()

        # Remove position from tracking
        del self._open_positions[market_id]

        result = VirtualTradeResult(
            trade_id=position.trade_id,
            market_id=market_id,
            side=position.side,
            size=position.size,
            price=close_price,
            commission=fees + position.commission,
            gas_cost=gas + position.gas_cost,
            net_pnl=net_pnl,
            is_open=False,
            opened_at=position.opened_at,
            closed_at=now,
            strategy=position.strategy,
            whale_source=position.whale_source,
        )

        # STEP 1: Save trade to database FIRST (source of truth)
        await self._save_virtual_trade(
            trade_id=result.trade_id,
            market_id=result.market_id,
            side=result.side,
            size=result.size,
            price=position.entry_price,  # entry price - preserved!
            commission=result.commission,
            gas_cost=result.gas_cost,
            net_pnl=result.net_pnl,
            is_open=result.is_open,
            opened_at=result.opened_at,
            closed_at=result.closed_at,
            strategy=result.strategy,
            gross_pnl=gross_pnl,
            total_fees=total_fees_calc,
            whale_source=position.whale_source,
            gas_cost_eth=Decimal("0"),
            close_price=close_price,  # exit/settlement price
            outcome=outcome,
        )

        # STEP 2: Update total balance
        self.balance += exit_value - fees - gas

        # STEP 3: Release allocated capital (using original entry value)
        self._release_capital(entry_value)

        if position.whale_source:
            market_title = await get_market_title(market_id)
            await self._save_whale_trade_record(
                whale_address=position.whale_source,
                market_id=market_id,
                side="sell" if position.side == "buy" else "buy",
                size_usd=position.size,
                price=close_price,
                market_title=market_title,
            )

        await self._save_bankroll_history(
            balance=self.balance, trade_id=position.trade_id, action="position_close"
        )

        logger.info(
            "virtual_position_closed",
            trade_id=position.trade_id,
            market_id=market_id,
            entry_price=str(position.entry_price),
            close_price=str(close_price),
            entry_value=str(entry_value),
            exit_value=str(exit_value),
            pnl=str(net_pnl),
            new_balance=str(self.balance),
            new_available=str(self.available),
            new_allocated=str(self.allocated),
            whale_source=position.whale_source[:10] if position.whale_source else "",
        )

        return result

    def get_open_positions(self) -> Dict[str, VirtualPosition]:
        """Get all currently open positions.

        Returns:
            Dict mapping market_id to VirtualPosition
        """
        return self._open_positions.copy()

    def get_stats(self) -> BankrollStats:
        """Get current bankroll statistics.

        Returns:
            BankrollStats with all relevant metrics
        """
        closed_trades = self._winning_trades + self._losing_trades
        win_rate = Decimal("0")
        if closed_trades > 0:
            win_rate = Decimal(self._winning_trades) / Decimal(closed_trades)

        return BankrollStats(
            current_balance=self.balance,
            total_trades=self._total_trades,
            open_positions=len(self._open_positions),
            closed_trades=closed_trades,
            winning_trades=self._winning_trades,
            losing_trades=self._losing_trades,
            win_rate=win_rate,
            total_pnl=self._total_pnl,
            consecutive_losses=self._consecutive_losses,
            max_consecutive_losses=self._max_consecutive_losses,
        )

    def check_success_criteria(
        self,
        target_balance: Decimal = Decimal("125.00"),
        min_win_rate: Decimal = Decimal("0.60"),
        max_consecutive_losses: int = 3,
    ) -> Dict[str, bool]:
        """Check if success criteria are met.

        Args:
            target_balance: Target virtual balance (default: $125)
            min_win_rate: Minimum win rate (default: 60%)
            max_consecutive_losses: Maximum allowed consecutive losses

        Returns:
            Dict with status of each criterion
        """
        stats = self.get_stats()

        return {
            "balance_above_target": self.balance >= target_balance,
            "win_rate_above_min": stats.win_rate >= min_win_rate,
            "consecutive_losses_acceptable": self._consecutive_losses
            <= max_consecutive_losses,
            "all_criteria_met": (
                self.balance >= target_balance
                and stats.win_rate >= min_win_rate
                and self._consecutive_losses <= max_consecutive_losses
            ),
        }

    async def load_open_positions_from_db(self) -> int:
        """Load open positions from database into memory.

        Used for recovery after bot restart - loads all positions with
        status='open' from trades table.

        Returns:
            Number of positions loaded
        """
        await self._ensure_database()

        if not self._Session:
            logger.warning("load_open_positions_no_session")
            return 0

        session = self._Session()
        try:
            query = text("""
                SELECT
                    t.trade_id,
                    t.market_id,
                    t.side,
                    t.size,
                    t.open_price as entry_price,
                    t.executed_at,
                    t.commission,
                    t.gas_cost_eth,
                    t.whale_source
                FROM trades t
                WHERE t.exchange = 'VIRTUAL'
                  AND t.status = 'open'
            """)
            result = session.execute(query)
            loaded = 0
            for row in result:
                market_id = str(row[1])
                # Skip if already in memory
                if market_id in self._open_positions:
                    continue
                position = VirtualPosition(
                    trade_id=str(row[0]),
                    market_id=market_id,
                    side=str(row[2]),
                    size=Decimal(str(row[3])),
                    entry_price=Decimal(str(row[4])),
                    commission=Decimal(str(row[6])) if row[6] else Decimal("0"),
                    gas_cost=Decimal(str(row[7])) if row[7] else Decimal("0"),
                    opened_at=row[5],
                    strategy="copy_whale",  # Default strategy for loaded positions
                    whale_source=str(row[8]) if row[8] else "",
                )
                self._open_positions[market_id] = position
                # Track allocated capital (entry cost)
                entry_cost = position.size * position.entry_price
                self.allocated += entry_cost
                self.available -= entry_cost
                loaded += 1

            logger.info(
                "open_positions_loaded_from_db",
                count=loaded,
                allocated=str(self.allocated),
                available=str(self.available),
            )
            
            # Save bankroll state after loading positions
            if loaded > 0:
                await self._save_bankroll_history(
                    balance=self.balance,
                    trade_id=None,
                    action="load_positions_from_db"
                )
            
            return loaded
        except Exception as e:
            logger.error("load_open_positions_error", error=str(e))
            return 0
        finally:
            session.close()

    async def reset(self, new_balance: Optional[Decimal] = None) -> None:
        """Reset bankroll to initial state.

        Args:
            new_balance: New balance to set (default: initial balance)
        """
        new_val = new_balance if new_balance else self.initial_balance
        self.balance = new_val
        self.available = new_val
        self.allocated = Decimal("0")
        
        self._open_positions.clear()
        self._consecutive_losses = 0
        self._max_consecutive_losses = 0
        self._winning_trades = 0
        self._losing_trades = 0
        self._total_pnl = Decimal("0")
        self._total_trades = 0

        await self._save_bankroll_history(
            balance=self.balance, trade_id=None, action="reset"
        )

        logger.info(
            "virtual_bankroll_reset",
            new_balance=str(self.balance),
            available=str(self.available),
            allocated=str(self.allocated),
            initial_balance=str(self.initial_balance),
        )

    def get_roi_percent(self) -> Decimal:
        """Calculate return on investment as percentage.

        Returns:
            ROI percentage (e.g., 25.0 for 25% gain)
        """
        if self.initial_balance == Decimal("0"):
            return Decimal("0")
        return ((self.balance - self.initial_balance) / self.initial_balance) * Decimal(
            "100"
        )
