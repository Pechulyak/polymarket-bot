# -*- coding: utf-8 -*-
"""Polymarket CLOB API Client - Read-only data client.

Async client for fetching market data from Polymarket's CLOB API.
Supports rate limiting, retry logic, and WebSocket preparation.

Example:
    >>> from execution.polymarket.client import PolymarketClient
    >>> client = PolymarketClient()
    >>> markets = await client.get_markets()
    >>> book = await client.get_orderbook("0x...")
    >>> await client.close()
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class OrderBook:
    """Order book representation for a token.

    Attributes:
        token_id: Token identifier
        bids: List of bids [{"price": float, "size": float}, ...]
        asks: List of asks [{"price": float, "size": float}, ...]
        timestamp: Unix timestamp when fetched
    """

    token_id: str
    bids: List[Dict[str, float]]
    asks: List[Dict[str, float]]
    timestamp: float

    @property
    def best_bid(self) -> Optional[float]:
        """Get best (highest) bid price."""
        return self.bids[0]["price"] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        """Get best (lowest) ask price."""
        return self.asks[0]["price"] if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        """Calculate bid-ask spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def mid_price(self) -> Optional[float]:
        """Calculate mid price."""
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None


class PolymarketClient:
    """Polymarket CLOB API Client (Read-only).

    Fetches market data with rate limiting and retry logic.

    Attributes:
        CLOB_API: CLOB REST API endpoint
        GAMMA_API: Gamma API endpoint for market metadata
        WS_URL: WebSocket endpoint (for future use)
    """

    # API endpoints
    CLOB_API = "https://clob.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws"

    # Rate limiting
    MAX_REQUESTS_PER_MINUTE = 100
    REQUEST_WINDOW_SECONDS = 60

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        """Initialize Polymarket client.

        Args:
            api_key: Optional API key for higher rate limits
            max_retries: Maximum retry attempts for failed requests
            retry_delay: Delay between retries in seconds
        """
        self.api_key = api_key
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Session management
        self._session: Optional[aiohttp.ClientSession] = None

        # Rate limiting
        self._request_times: List[float] = []
        self._rate_limit_lock = asyncio.Lock()

        logger.info(
            "polymarket_client_initialized",
            api_key_set=api_key is not None,
            max_retries=max_retries,
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("polymarket_client_closed")

    async def _apply_rate_limit(self) -> None:
        """Apply rate limiting - wait if over 100 req/min.

        Uses sliding window to track requests.
        """
        async with self._rate_limit_lock:
            now = time.time()

            # Remove old requests outside window
            cutoff = now - self.REQUEST_WINDOW_SECONDS
            self._request_times = [t for t in self._request_times if t > cutoff]

            # Check if we're over the limit
            if len(self._request_times) >= self.MAX_REQUESTS_PER_MINUTE:
                # Wait until oldest request is outside window
                wait_time = self._request_times[0] + self.REQUEST_WINDOW_SECONDS - now
                if wait_time > 0:
                    logger.warning(
                        "rate_limit_hit",
                        wait_seconds=wait_time,
                        queued_requests=len(self._request_times),
                    )
                    await asyncio.sleep(wait_time)
                    # Recurse to check again after wait
                    return await self._apply_rate_limit()

            # Record this request
            self._request_times.append(now)

    async def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Make HTTP request with retry logic and rate limiting.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            params: Query parameters
            headers: Request headers

        Returns:
            JSON response as dict

        Raises:
            PolymarketAPIError: On API errors after retries
        """
        await self._apply_rate_limit()

        session = await self._get_session()

        # Default headers - disable brotli compression to avoid decoding errors
        request_headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",  # Explicitly exclude brotli
        }
        if headers:
            request_headers.update(headers)
        if self.api_key:
            request_headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                async with session.request(
                    method=method,
                    url=url,
                    params=params,
                    headers=request_headers,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        # Rate limited by server
                        retry_after = float(
                            resp.headers.get("Retry-After", self.retry_delay)
                        )
                        logger.warning(
                            "server_rate_limit",
                            retry_after=retry_after,
                            attempt=attempt + 1,
                        )
                        await asyncio.sleep(retry_after)
                    else:
                        error_text = await resp.text()
                        logger.error(
                            "api_error",
                            status=resp.status,
                            url=url,
                            error=error_text[:200],
                        )
                        raise PolymarketAPIError(
                            f"API error {resp.status}: {error_text[:200]}"
                        )

            except aiohttp.ClientError as e:
                last_error = e
                logger.warning(
                    "request_failed",
                    error=str(e),
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))

        # All retries exhausted
        raise PolymarketAPIError(
            f"Request failed after {self.max_retries} attempts: {last_error}"
        )

    async def get_markets(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get list of available markets.

        Args:
            active_only: Only return active markets

        Returns:
            List of market dictionaries with id, question, outcomes, etc.
        """
        url = f"{self.GAMMA_API}/markets"
        params = {"active": str(active_only).lower()}

        logger.debug("fetching_markets", active_only=active_only)

        data = await self._make_request("GET", url, params=params)

        markets = data if isinstance(data, list) else data.get("markets", [])

        logger.info("markets_fetched", count=len(markets), active_only=active_only)

        return markets

    async def get_market(self, market_id: str) -> Dict[str, Any]:
        """Get single market details.

        Args:
            market_id: Market identifier

        Returns:
            Market details dictionary
        """
        url = f"{self.GAMMA_API}/markets/{market_id}"

        logger.debug("fetching_market", market_id=market_id)

        data = await self._make_request("GET", url)

        logger.info("market_fetched", market_id=market_id)

        return data

    async def get_orderbook(self, token_id: str) -> OrderBook:
        """Get orderbook for a token.

        Args:
            token_id: Condition token ID (YES or NO token)

        Returns:
            OrderBook with bids and asks
        """
        url = f"{self.CLOB_API}/book"
        params = {"token_id": token_id}

        logger.debug("fetching_orderbook", token_id=token_id[:20])

        data = await self._make_request("GET", url, params=params)

        orderbook = OrderBook(
            token_id=token_id,
            bids=data.get("bids", []),
            asks=data.get("asks", []),
            timestamp=time.time(),
        )

        logger.info(
            "orderbook_fetched",
            token_id=token_id[:20],
            bid_count=len(orderbook.bids),
            ask_count=len(orderbook.asks),
            best_bid=orderbook.best_bid,
            best_ask=orderbook.best_ask,
        )

        return orderbook

    async def get_price(self, token_id: str) -> Dict[str, Optional[float]]:
        """Get current prices for a token.

        Args:
            token_id: Condition token ID

        Returns:
            Dict with bid, ask, mid prices
        """
        book = await self.get_orderbook(token_id)

        prices = {
            "bid": book.best_bid,
            "ask": book.best_ask,
            "mid": book.mid_price,
            "spread": book.spread,
        }

        logger.debug("prices_fetched", token_id=token_id[:20], prices=prices)

        return prices

    # ==================== WebSocket Preparation ====================

    async def connect_websocket(self) -> None:
        """Prepare WebSocket connection (for future implementation).

        Currently raises NotImplementedError. Will be implemented
        when real-time data streaming is needed.
        """
        raise NotImplementedError(
            "WebSocket support not yet implemented. Use REST API methods for now."
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics.

        Returns:
            Dict with request stats and rate limit info
        """
        now = time.time()
        cutoff = now - self.REQUEST_WINDOW_SECONDS
        recent_requests = len([t for t in self._request_times if t > cutoff])

        return {
            "requests_in_window": recent_requests,
            "rate_limit": self.MAX_REQUESTS_PER_MINUTE,
            "remaining_requests": self.MAX_REQUESTS_PER_MINUTE - recent_requests,
            "api_key_set": self.api_key is not None,
        }


class PolymarketAPIError(Exception):
    """Exception for Polymarket API errors."""

    pass
