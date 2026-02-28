# -*- coding: utf-8 -*-
"""Metrics Aggregator for Paper Trading.

Calculates and stores trading metrics from database history.
Handles 0-state properly and provides equity snapshots.

Usage:
    >>> from monitoring.metrics_aggregator import MetricsAggregator
    >>> from decimal import Decimal
    >>>
    >>> aggregator = MetricsAggregator(database_url="postgresql://...")
    >>> metrics = await aggregator.calculate_metrics()
    >>> print(metrics.win_rate)  # 0.0 if no trades
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = structlog.get_logger(__name__)


@dataclass
class TradingMetrics:
    """Aggregated trading metrics.

    Attributes:
        total_trades: Total number of executed trades
        winning_trades: Number of winning trades
        losing_trades: Number of losing trades
        win_rate: Win rate as decimal (0.0 to 1.0)
        roi: Return on investment as decimal
        expectancy: Average profit per trade
        max_drawdown: Maximum drawdown percentage
        realized_pnl: Total realized profit/loss
        unrealized_pnl: Unrealized profit/loss from open positions
        current_balance: Current virtual balance
        initial_balance: Starting balance
        last_update: Timestamp of last metrics calculation
    """

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = Decimal("0")
    roi: Decimal = Decimal("0")
    expectancy: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    current_balance: Decimal = Decimal("0")
    initial_balance: Decimal = Decimal("100.00")
    last_update: Optional[datetime] = None


@dataclass
class EquitySnapshot:
    """Equity snapshot for tracking balance over time.

    Attributes:
        timestamp: Snapshot timestamp
        balance: Balance at snapshot time
        realized_pnl: Realized PnL at snapshot
        unrealized_pnl: Unrealized PnL at snapshot
        trade_count: Number of trades at snapshot
    """

    timestamp: datetime
    balance: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    trade_count: int


class MetricsAggregator:
    """Metrics Aggregator for Paper Trading.

    Calculates trading metrics from database history.
    Handles 0-state properly (no trades = zero metrics, not errors).

    Attributes:
        database_url: PostgreSQL connection URL
        initial_balance: Starting balance for ROI calculation
    """

    def __init__(
        self,
        database_url: str,
        initial_balance: Decimal = Decimal("100.00"),
    ) -> None:
        """Initialize Metrics Aggregator.

        Args:
            database_url: PostgreSQL connection URL
            initial_balance: Starting balance for ROI calculation
        """
        self.database_url = database_url
        self.initial_balance = initial_balance
        self._engine = create_engine(database_url)
        self._Session = sessionmaker(bind=self._engine)

        logger.info(
            "metrics_aggregator_initialized",
            initial_balance=str(initial_balance),
        )

    async def calculate_metrics(self) -> TradingMetrics:
        """Calculate trading metrics from database.

        Returns:
            TradingMetrics with all calculated values (0-state safe)

        Note:
            Returns zero values for all metrics if no trades exist.
            This ensures graceful handling of 0-state.
        """
        session = self._Session()
        try:
            # Get all virtual trades
            trades_query = text("""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(CASE WHEN net_pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                    SUM(net_pnl) as realized_pnl,
                    MAX(executed_at) as last_trade_time
                FROM trades
                WHERE exchange = 'VIRTUAL'
            """)
            trades_result = session.execute(trades_query).fetchone()

            total_trades = trades_result[0] or 0
            winning_trades = trades_result[1] or 0
            losing_trades = trades_result[2] or 0
            realized_pnl = Decimal(str(trades_result[3] or 0))

            # Get open positions (unrealized PnL)
            open_positions_query = text("""
                SELECT
                    COUNT(*) as open_count,
                    SUM(size) as total_size,
                    AVG(price) as avg_price
                FROM trades
                WHERE exchange = 'VIRTUAL' AND status = 'open'
            """)
            open_result = session.execute(open_positions_query).fetchone()
            open_count = open_result[0] or 0

            # For unrealized PnL, we need current market prices
            # For now, set to 0 (no real-time price feed)
            unrealized_pnl = Decimal("0")

            # Calculate current balance
            current_balance = self.initial_balance + realized_pnl

            # Calculate win rate
            if total_trades > 0:
                win_rate = Decimal(winning_trades) / Decimal(total_trades)
            else:
                win_rate = Decimal("0")

            # Calculate ROI
            if self.initial_balance > 0:
                roi = (current_balance - self.initial_balance) / self.initial_balance
            else:
                roi = Decimal("0")

            # Calculate expectancy (average profit per trade)
            if total_trades > 0:
                expectancy = realized_pnl / Decimal(total_trades)
            else:
                expectancy = Decimal("0")

            # Calculate max drawdown from bankroll history
            max_drawdown = await self._calculate_max_drawdown(session)

            metrics = TradingMetrics(
                total_trades=total_trades,
                winning_trades=winning_trades,
                losing_trades=losing_trades,
                win_rate=win_rate,
                roi=roi,
                expectancy=expectancy,
                max_drawdown=max_drawdown,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                current_balance=current_balance,
                initial_balance=self.initial_balance,
                last_update=datetime.now(),
            )

            logger.info(
                "metrics_calculated",
                total_trades=total_trades,
                win_rate=str(win_rate),
                roi=str(roi),
                realized_pnl=str(realized_pnl),
            )

            return metrics

        except Exception as e:
            logger.error("metrics_calculation_failed", error=str(e))
            # Return zero-state metrics on error
            return TradingMetrics(
                initial_balance=self.initial_balance,
                last_update=datetime.now(),
            )
        finally:
            session.close()

    async def _calculate_max_drawdown(self, session) -> Decimal:
        """Calculate maximum drawdown from bankroll history.

        Args:
            session: Database session

        Returns:
            Maximum drawdown as decimal (0.0 to 1.0)
        """
        try:
            query = text("""
                SELECT timestamp, total_capital
                FROM bankroll
                ORDER BY timestamp ASC
            """)
            result = session.execute(query).fetchall()

            if not result:
                return Decimal("0")

            peak = Decimal("0")
            max_drawdown = Decimal("0")

            for row in result:
                capital = Decimal(str(row[1]))
                if capital > peak:
                    peak = capital

                if peak > 0:
                    drawdown = (peak - capital) / peak
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown

            return max_drawdown

        except Exception as e:
            logger.warning("max_drawdown_calculation_failed", error=str(e))
            return Decimal("0")

    async def save_equity_snapshot(
        self,
        balance: Decimal,
        realized_pnl: Decimal = Decimal("0"),
        unrealized_pnl: Decimal = Decimal("0"),
    ) -> None:
        """Save equity snapshot to database.

        Args:
            balance: Current balance
            realized_pnl: Realized PnL
            unrealized_pnl: Unrealized PnL
        """
        session = self._Session()
        try:
            # Get trade count
            count_query = text("""
                SELECT COUNT(*) FROM trades WHERE exchange = 'VIRTUAL'
            """)
            trade_count = session.execute(count_query).fetchone()[0] or 0

            # Insert into bankroll table as snapshot
            query = text("""
                INSERT INTO bankroll (
                    timestamp, total_capital, allocated, available,
                    daily_pnl, daily_drawdown, total_trades, win_count, loss_count
                ) VALUES (
                    NOW(), :balance, 0, :balance, :realized_pnl, 0, :trade_count, 0, 0
                )
            """)
            session.execute(
                query,
                {
                    "balance": float(balance),
                    "realized_pnl": float(realized_pnl),
                    "trade_count": trade_count,
                },
            )
            session.commit()

            logger.debug(
                "equity_snapshot_saved",
                balance=str(balance),
                trade_count=trade_count,
            )

        except Exception as e:
            logger.error("equity_snapshot_save_failed", error=str(e))
            session.rollback()
        finally:
            session.close()

    async def get_equity_history(
        self,
        days: int = 7,
    ) -> list[EquitySnapshot]:
        """Get equity history for specified number of days.

        Args:
            days: Number of days to look back

        Returns:
            List of EquitySnapshot objects
        """
        session = self._Session()
        try:
            query = text("""
                SELECT
                    timestamp,
                    total_capital,
                    daily_pnl,
                    total_trades
                FROM bankroll
                WHERE timestamp >= NOW() - INTERVAL ':days days'
                ORDER BY timestamp DESC
            """)
            result = session.execute(query, {"days": days}).fetchall()

            snapshots = []
            for row in result:
                snapshots.append(
                    EquitySnapshot(
                        timestamp=row[0],
                        balance=Decimal(str(row[1])),
                        realized_pnl=Decimal(str(row[2] or 0)),
                        unrealized_pnl=Decimal("0"),  # Not tracked in bankroll
                        trade_count=row[3] or 0,
                    )
                )

            return snapshots

        except Exception as e:
            logger.error("equity_history_fetch_failed", error=str(e))
            return []
        finally:
            session.close()

    async def get_daily_stats(self, days: int = 7) -> list[dict]:
        """Get daily trading statistics.

        Args:
            days: Number of days to look back

        Returns:
            List of daily stats dictionaries
        """
        session = self._Session()
        try:
            query = text("""
                SELECT
                    DATE(executed_at) as trade_date,
                    COUNT(*) as trade_count,
                    SUM(net_pnl) as daily_pnl,
                    SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN net_pnl < 0 THEN 1 ELSE 0 END) as losses
                FROM trades
                WHERE exchange = 'VIRTUAL'
                    AND executed_at >= NOW() - INTERVAL ':days days'
                GROUP BY DATE(executed_at)
                ORDER BY trade_date DESC
            """)
            result = session.execute(query, {"days": days}).fetchall()

            daily_stats = []
            for row in result:
                daily_stats.append({
                    "date": row[0],
                    "trade_count": row[1] or 0,
                    "daily_pnl": float(row[2] or 0),
                    "wins": row[3] or 0,
                    "losses": row[4] or 0,
                })

            return daily_stats

        except Exception as e:
            logger.error("daily_stats_fetch_failed", error=str(e))
            return []
        finally:
            session.close()