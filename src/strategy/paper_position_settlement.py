# -*- coding: utf-8 -*-
"""Paper Position Settlement Engine.

Settles paper positions when markets resolve on Polymarket.
Calculates PnL based on resolution prices and updates the trades table.

Usage:
    python -m src.strategy.paper_position_settlement
    # Or as part of scheduler
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = structlog.get_logger(__name__)


def get_database_url() -> str:
    """Get database URL from environment or config."""
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:password@localhost:5433/polymarket"
    )

logger = structlog.get_logger(__name__)


# Polymarket API endpoints
GAMMA_API = "https://gamma-api.polymarket.com"


@dataclass
class MarketResolution:
    """Market resolution data from Polymarket.

    Attributes:
        market_id: Market identifier
        closed: Whether market is closed/resolved
        end_date: End date timestamp
        outcome_prices: Final outcome prices
        winner: Winning outcome (if resolved)
    """

    market_id: str
    closed: bool
    end_date: Optional[str]
    outcome_prices: List[float]
    winner: Optional[str] = None


@dataclass
class SettledPosition:
    """A settled paper position with PnL.

    Attributes:
        trade_id: Trade identifier
        market_id: Market identifier
        side: Position side (buy/sell)
        size: Position size
        entry_price: Entry price
        close_price: Settlement price
        gross_pnl: Gross PnL before fees
        total_fees: Total fees paid
        net_pnl: Net PnL after fees
        settled_at: Settlement timestamp
    """

    trade_id: str
    market_id: str
    side: str
    size: Decimal
    entry_price: Decimal
    close_price: Decimal
    gross_pnl: Decimal
    total_fees: Decimal
    net_pnl: Decimal
    settled_at: datetime


class PaperPositionSettlementEngine:
    """Settlement Engine for Paper Positions.

    Monitors Polymarket for resolved markets and settles
    paper positions accordingly.

    Attributes:
        database_url: PostgreSQL connection URL
    """

    def __init__(self, database_url: str) -> None:
        """Initialize settlement engine.

        Args:
            database_url: PostgreSQL connection URL
        """
        self.database_url = database_url
        self._engine = create_engine(database_url)
        self._Session = sessionmaker(bind=self._engine)

        # Fee constants (Polymarket fees)
        self.trading_fee_rate = Decimal("0.02")  # 2% trading fee
        self.gas_cost = Decimal("1.50")  # Estimated gas cost

        logger.info("paper_position_settlement_engine_initialized")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session for API calls."""
        if not hasattr(self, "_http_session") or self._http_session is None:
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._http_session

    async def close(self) -> None:
        """Close HTTP session."""
        if hasattr(self, "_http_session") and self._http_session is not None:
            await self._http_session.close()

    async def get_market_resolution(
        self, market_id: str
    ) -> Optional[MarketResolution]:
        """Get market resolution data from Polymarket API.

        Uses Gamma API to fetch market status and resolution data.

        Args:
            market_id: Market identifier

        Returns:
            MarketResolution if market exists, None otherwise
        """
        try:
            session = await self._get_session()

            # Use Gamma API markets endpoint
            url = f"{GAMMA_API}/markets"
            params = {"id": market_id}

            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(
                        "market_api_error",
                        market_id=market_id[:20],
                        status=resp.status,
                    )
                    return None

                data = await resp.json()

                # Handle both single market and list response
                if isinstance(data, list):
                    if not data:
                        return None
                    market = data[0]
                else:
                    market = data

                # Extract resolution data
                closed = market.get("closed", False)
                end_date = market.get("endDate") or market.get("end_date")

                # Get outcome prices - this is the settlement price
                outcome_prices = []
                if "outcomePrices" in market:
                    try:
                        # outcomePrices is like ["0.65", "0.35"]
                        prices = market["outcomePrices"]
                        if isinstance(prices, str):
                            import json

                            prices = json.loads(prices)
                        outcome_prices = [float(p) for p in prices]
                    except (json.JSONDecodeError, ValueError, TypeError) as e:
                        logger.warning(
                            "outcome_prices_parse_error",
                            market_id=market_id[:20],
                            error=str(e),
                        )

                # Determine winner
                winner = None
                if closed and outcome_prices:
                    # Find the outcome with highest probability
                    max_idx = outcome_prices.index(max(outcome_prices))
                    # Get outcomes list
                    outcomes = market.get("outcomes", ["Yes", "No"])
                    if isinstance(outcomes, str):
                        import json

                        outcomes = json.loads(outcomes)
                    if max_idx < len(outcomes):
                        winner = outcomes[max_idx]

                return MarketResolution(
                    market_id=market_id,
                    closed=closed,
                    end_date=end_date,
                    outcome_prices=outcome_prices,
                    winner=winner,
                )

        except aiohttp.ClientError as e:
            logger.error(
                "market_resolution_api_error",
                market_id=market_id[:20],
                error=str(e),
            )
            return None
        except Exception as e:
            logger.error(
                "market_resolution_error",
                market_id=market_id[:20],
                error=str(e),
            )
            return None

    def get_open_paper_positions(self) -> List[Dict[str, Any]]:
        """Get all open paper positions from trades table.

        Returns:
            List of position dictionaries
        """
        session = self._Session()
        try:
            query = text("""
                SELECT
                    t.trade_id,
                    t.market_id,
                    t.side,
                    t.size,
                    t.open_price as entry_price,  -- Use open_price instead of price
                    t.executed_at,
                    t.commission,
                    t.gas_cost_eth
                FROM trades t
                WHERE t.exchange = 'VIRTUAL'
                  AND t.status = 'open'
                ORDER BY t.executed_at DESC
            """)
            result = session.execute(query)
            positions = []
            for row in result:
                positions.append({
                    "trade_id": str(row[0]),
                    "market_id": str(row[1]),
                    "side": str(row[2]),
                    "size": Decimal(str(row[3])),
                    "entry_price": Decimal(str(row[4])),
                    "executed_at": row[5],
                    "commission": Decimal(str(row[6])) if row[6] else Decimal("0"),
                    "gas_cost": Decimal(str(row[7])) if row[7] else Decimal("0"),
                })
            return positions
        except Exception as e:
            logger.error("get_open_positions_error", error=str(e))
            return []
        finally:
            session.close()

    def settle_position(
        self,
        trade_id: str,
        market_id: str,
        side: str,
        size: Decimal,
        entry_price: Decimal,
        close_price: Decimal,
        commission: Decimal,
        gas_cost: Decimal,
    ) -> bool:
        """Settle a single position with given close price.

        Args:
            trade_id: Trade identifier
            market_id: Market identifier
            side: Position side (buy/sell)
            size: Position size
            entry_price: Entry price
            close_price: Settlement/close price
            commission: Commission paid
            gas_cost: Gas cost paid

        Returns:
            True if settlement successful, False otherwise
        """
        session = self._Session()
        try:
            # Calculate PnL
            if side.lower() == "buy":
                # Long position: profit if close > entry
                gross_pnl = (close_price - entry_price) * size
            else:
                # Short position: profit if entry > close
                gross_pnl = (entry_price - close_price) * size

            total_fees = commission + gas_cost
            net_pnl = gross_pnl - total_fees

            # Update trade record - set close_price, preserve open_price
            query = text("""
                UPDATE trades
                SET status = 'closed',
                    settled_at = NOW(),
                    close_price = :close_price,
                    gross_pnl = :gross_pnl,
                    total_fees = :total_fees,
                    net_pnl = :net_pnl
                WHERE trade_id = :trade_id
            """)
            session.execute(
                query,
                {
                    "close_price": float(close_price),
                    "gross_pnl": float(gross_pnl),
                    "total_fees": float(total_fees),
                    "net_pnl": float(net_pnl),
                    "trade_id": trade_id,
                },
            )
            session.commit()

            logger.info(
                "position_settled",
                trade_id=trade_id,
                market_id=market_id[:20],
                side=side,
                entry_price=str(entry_price),
                close_price=str(close_price),
                gross_pnl=str(gross_pnl),
                net_pnl=str(net_pnl),
            )
            return True

        except Exception as e:
            logger.error(
                "settle_position_error",
                trade_id=trade_id,
                error=str(e),
            )
            session.rollback()
            return False
        finally:
            session.close()

    async def settle_resolved_paper_positions(self) -> Dict[str, Any]:
        """Main entry point: settle all resolved paper positions.

        Queries open paper positions, checks if their markets are
        resolved on Polymarket, and settles them with PnL calculation.

        Returns:
            Dict with settlement results
        """
        logger.info("starting_settlement_cycle")

        # Get open positions
        positions = self.get_open_paper_positions()

        if not positions:
            logger.info("no_open_positions_to_settle")
            return {
                "checked": 0,
                "settled": 0,
                "resolved": 0,
                "failed": 0,
                "markets_not_resolved": 0,
            }

        settled = 0
        resolved = 0
        failed = 0
        markets_not_resolved = 0
        resolution_errors = []

        # Group positions by market_id to minimize API calls
        market_positions: Dict[str, List[Dict]] = {}
        for pos in positions:
            mid = pos["market_id"]
            if mid not in market_positions:
                market_positions[mid] = []
            market_positions[mid].append(pos)

        # Check each unique market
        for market_id, market_positions_list in market_positions.items():
            # Get resolution data
            resolution = await self.get_market_resolution(market_id)

            if resolution is None:
                logger.warning(
                    "market_resolution_fetch_failed",
                    market_id=market_id[:20],
                )
                resolution_errors.append(market_id)
                failed += len(market_positions_list)
                continue

            if not resolution.closed:
                logger.debug(
                    "market_not_resolved",
                    market_id=market_id[:20],
                )
                markets_not_resolved += len(market_positions_list)
                continue

            # Market is resolved - get settlement price
            if not resolution.outcome_prices:
                logger.warning(
                    "no_outcome_prices",
                    market_id=market_id[:20],
                )
                failed += len(market_positions_list)
                continue

            resolved += len(market_positions_list)

            # Use the first outcome price as settlement price
            # (for binary markets, this is typically the YES token)
            settlement_price = Decimal(str(resolution.outcome_prices[0]))

            logger.info(
                "market_resolved",
                market_id=market_id[:20],
                settlement_price=str(settlement_price),
                winner=resolution.winner,
            )

            # Settle each position in this market
            for pos in market_positions_list:
                success = self.settle_position(
                    trade_id=pos["trade_id"],
                    market_id=pos["market_id"],
                    side=pos["side"],
                    size=pos["size"],
                    entry_price=pos["entry_price"],
                    close_price=settlement_price,
                    commission=pos["commission"],
                    gas_cost=pos["gas_cost"],
                )
                if success:
                    settled += 1
                else:
                    failed += 1

            # Rate limit: be nice to Polymarket API
            await asyncio.sleep(0.5)

        result = {
            "checked": len(positions),
            "settled": settled,
            "resolved": resolved,
            "failed": failed,
            "markets_not_resolved": markets_not_resolved,
            "resolution_errors": resolution_errors,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(
            "settlement_cycle_complete",
            **result,
        )

        return result


async def run_settlement_cycle(database_url: str) -> Dict[str, Any]:
    """Run a single settlement cycle.

    Args:
        database_url: PostgreSQL connection URL

    Returns:
        Settlement results dict
    """
    engine = PaperPositionSettlementEngine(database_url)
    try:
        return await engine.settle_resolved_paper_positions()
    finally:
        await engine.close()


async def run_settlement_loop(
    database_url: str, interval_seconds: int = 600
) -> None:
    """Run settlement engine in a loop.

    Args:
        database_url: PostgreSQL connection URL
        interval_seconds: Seconds between settlement checks (default: 600 = 10 min)
    """
    logger.info(
        "settlement_loop_started",
        interval_seconds=interval_seconds,
    )

    engine = PaperPositionSettlementEngine(database_url)

    try:
        while True:
            try:
                result = await engine.settle_resolved_paper_positions()
                logger.info("settlement_cycle_result", **result)
            except Exception as e:
                logger.error("settlement_cycle_error", error=str(e))

            await asyncio.sleep(interval_seconds)
    finally:
        await engine.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Paper Position Settlement Engine")
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="PostgreSQL connection URL",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=600,
        help="Settlement check interval in seconds (default: 600)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run only once instead of loop",
    )
    args = parser.parse_args()

    database_url = args.database_url or get_database_url()

    if args.once:
        result = asyncio.run(run_settlement_cycle(database_url))
        print(f"Settlement result: {result}")
    else:
        asyncio.run(run_settlement_loop(database_url, args.interval))
