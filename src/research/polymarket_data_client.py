# -*- coding: utf-8 -*-
"""Polymarket Data API Client - Real-time trades with addresses.

Fetches all trades from Polymarket Data API with trader addresses.
Free, real-time, includes proxyWallet addresses.

Example:
    >>> from research.polymarket_data_client import PolymarketDataClient, TradeWithAddress
    >>>
    >>> client = PolymarketDataClient()
    >>> trades = await client.fetch_recent_trades(limit=100)
    >>> for trade in trades:
    ...     print(f"{trade.trader}: ${trade.size_usd}")
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

import aiohttp
import structlog
from aiohttp import ClientTimeout

from src.config.settings import settings

logger = structlog.get_logger(__name__)

DATA_API_BASE = "https://data-api.polymarket.com"


@dataclass
class TradeWithAddress:
    """Single trade from Polymarket Data API.

    Attributes:
        trader: Trader wallet address (proxyWallet)
        tx_hash: Transaction hash
        asset: Token/asset ID
        condition_id: Market condition ID
        side: Trade side ("BUY" or "SELL")
        size: Trade size (number of tokens)
        price: Execution price
        size_usd: Trade size in USD
        timestamp: Trade timestamp
        market_title: Market question/title
        outcome: Outcome name (Yes/No)
    """

    trader: str
    tx_hash: str
    asset: str
    condition_id: str
    side: str
    size: Decimal
    price: Decimal
    size_usd: Decimal
    timestamp: int
    market_title: str
    outcome: str


@dataclass
class AggregatedTraderStats:
    """Aggregated stats for a trader address.

    Attributes:
        address: Wallet address
        total_trades: Total number of trades
        total_volume_usd: Total volume in USD
        avg_trade_size_usd: Average trade size in USD
        buy_count: Number of buy trades
        sell_count: Number of sell trades
        last_seen: Last trade timestamp
    """

    address: str
    total_trades: int = 0
    total_volume_usd: Decimal = Decimal("0")
    avg_trade_size_usd: Decimal = Decimal("0")
    buy_count: int = 0
    sell_count: int = 0
    last_seen: Optional[int] = None


class PolymarketDataError(Exception):
    """Error during Polymarket Data API operations."""

    pass


class PolymarketDataClient:
    """Client for Polymarket Data API to fetch trades with addresses.

    Provides real-time access to all trades with trader wallet addresses.
    Free to use, no API key required.

    Attributes:
        BASE_URL: Polymarket Data API base URL
        MAX_TRADES_PER_QUERY: Max trades per request
    """

    BASE_URL = DATA_API_BASE
    MAX_TRADES_PER_QUERY = 1000

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 30,
    ):
        """Initialize Polymarket Data client.

        Args:
            api_key: Polymarket API key (optional, uses settings if not provided)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key or settings.polymarket_api_key
        self.timeout = ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

        logger.info("polymarket_data_client_initialized")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_recent_trades(
        self,
        limit: int = 100,
        min_size_usd: Optional[Decimal] = None,
    ) -> List[TradeWithAddress]:
        """Fetch recent trades from Polymarket.

        Args:
            limit: Max number of trades to return (max 1000)
            min_size_usd: Minimum trade size in USD to filter

        Returns:
            List of TradeWithAddress objects

        Raises:
            PolymarketDataError: If API request fails
        """
        limit = min(limit, self.MAX_TRADES_PER_QUERY)

        url = f"{self.BASE_URL}/trades"
        params = {"limit": limit}

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        session = await self._get_session()
        try:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        "polymarket_api_error",
                        status=response.status,
                        error=error_text,
                    )
                    raise PolymarketDataError(f"API error: {response.status}")

                data = await response.json()

                if not isinstance(data, list):
                    data = [data]

                trades = self._parse_trades(data)

                if min_size_usd:
                    trades = [t for t in trades if t.size_usd >= min_size_usd]

                logger.info(
                    "polymarket_trades_fetched",
                    count=len(trades),
                    total_raw=len(data),
                )

                return trades

        except aiohttp.ClientError as e:
            logger.error("polymarket_request_failed", error=str(e))
            raise PolymarketDataError(f"Request failed: {e}") from e

    def _parse_trades(self, data: List[Dict[str, Any]]) -> List[TradeWithAddress]:
        """Parse trades from API response.

        Args:
            data: Raw API response

        Returns:
            List of TradeWithAddress objects
        """
        trades = []

        for item in data:
            try:
                trader = item.get("proxyWallet", "")
                if not trader:
                    continue

                size_str = str(item.get("size", 0))
                price_str = str(item.get("price", 0))

                size = Decimal(size_str) if size_str else Decimal("0")
                price = Decimal(price_str) if price_str else Decimal("0")
                size_usd = size * price

                trade = TradeWithAddress(
                    trader=trader.lower(),
                    tx_hash=item.get("transactionHash", ""),
                    asset=item.get("asset", ""),
                    condition_id=item.get("conditionId", ""),
                    side=item.get("side", "").upper(),
                    size=size,
                    price=price,
                    size_usd=size_usd,
                    timestamp=int(item.get("timestamp", 0)),
                    market_title=item.get("title", ""),
                    outcome=item.get("outcome", ""),
                )
                trades.append(trade)

            except Exception as e:
                logger.debug("polymarket_parse_trade_error", error=str(e))
                continue

        return trades

    async def fetch_trader_trades(
        self,
        trader_address: str,
        limit: int = 100,
    ) -> List[TradeWithAddress]:
        """Fetch trades for a specific trader.

        Args:
            trader_address: Trader wallet address
            limit: Max number of trades

        Returns:
            List of TradeWithAddress objects
        """
        url = f"{self.BASE_URL}/trades"
        params = {
            "user": trader_address.lower(),
            "limit": limit,
        }

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        session = await self._get_session()
        try:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status != 200:
                    raise PolymarketDataError(f"API error: {response.status}")

                data = await response.json()

                if not isinstance(data, list):
                    data = [data]

                trades = self._parse_trades(data)

                logger.info(
                    "polymarket_trader_trades_fetched",
                    trader=trader_address[:10],
                    count=len(trades),
                )

                return trades

        except aiohttp.ClientError as e:
            logger.error("polymarket_request_failed", error=str(e))
            raise PolymarketDataError(f"Request failed: {e}") from e

    async def aggregate_by_address(
        self,
        limit: int = 100,
        min_size_usd: Decimal = Decimal("1000"),
    ) -> Dict[str, AggregatedTraderStats]:
        """Aggregate trades by trader address.

        Args:
            limit: Number of recent trades to analyze
            min_size_usd: Minimum trade size to include

        Returns:
            Dict mapping address to aggregated stats
        """
        trades = await self.fetch_recent_trades(limit=limit, min_size_usd=min_size_usd)

        aggregated: Dict[str, AggregatedTraderStats] = {}

        for trade in trades:
            address = trade.trader
            if address not in aggregated:
                aggregated[address] = AggregatedTraderStats(address=address)

            stats = aggregated[address]
            stats.total_trades += 1
            stats.total_volume_usd += trade.size_usd

            if trade.side == "BUY":
                stats.buy_count += 1
            else:
                stats.sell_count += 1

            if stats.last_seen is None or trade.timestamp > stats.last_seen:
                stats.last_seen = trade.timestamp

        for stats in aggregated.values():
            if stats.total_trades > 0:
                stats.avg_trade_size_usd = stats.total_volume_usd / Decimal(
                    stats.total_trades
                )

        logger.info(
            "polymarket_aggregated",
            unique_traders=len(aggregated),
            total_trades=sum(s.total_trades for s in aggregated.values()),
        )

        return aggregated


async def create_polymarket_data_client() -> PolymarketDataClient:
    """Factory function to create Polymarket Data client.

    Returns:
        Configured PolymarketDataClient instance
    """
    return PolymarketDataClient(api_key=settings.polymarket_api_key)
