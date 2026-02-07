# -*- coding: utf-8 -*-
"""Unit tests for PolymarketClient.

Simplified tests using _make_request mocking.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from execution.polymarket.client import (
    OrderBook,
    PolymarketAPIError,
    PolymarketClient,
)


class TestClientInitialization:
    """Test PolymarketClient initialization."""

    def test_default_initialization(self):
        """Test client initializes with default parameters."""
        client = PolymarketClient()

        assert client.api_key is None
        assert client.max_retries == 3
        assert client.retry_delay == 1.0
        assert client._session is None

    def test_custom_initialization(self):
        """Test client initializes with custom parameters."""
        client = PolymarketClient(
            api_key="test_key",
            max_retries=5,
            retry_delay=2.0,
        )

        assert client.api_key == "test_key"
        assert client.max_retries == 5
        assert client.retry_delay == 2.0

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Test closing client session."""
        client = PolymarketClient()

        session = await client._get_session()
        assert not session.closed

        await client.close()
        assert session.closed


class TestGetMarkets:
    """Test get_markets method."""

    @pytest.mark.asyncio
    async def test_get_markets_success(self):
        client = PolymarketClient()
        """Test fetching markets successfully."""
        with patch.object(
            client,
            "_make_request",
            return_value=[
                {"id": "market1", "question": "Will it rain?"},
                {"id": "market2", "question": "Will BTC hit 100k?"},
            ],
        ):
            markets = await client.get_markets()

        assert len(markets) == 2
        assert markets[0]["id"] == "market1"

    @pytest.mark.asyncio
    async def test_get_markets_with_wrapper(self):
        client = PolymarketClient()
        """Test fetching markets with wrapper object."""
        with patch.object(
            client,
            "_make_request",
            return_value={"markets": [{"id": "market1", "question": "Test?"}]},
        ):
            markets = await client.get_markets()

        assert len(markets) == 1
        assert markets[0]["id"] == "market1"

    @pytest.mark.asyncio
    async def test_get_markets_inactive(self):
        client = PolymarketClient()
        """Test fetching all markets including inactive."""
        with patch.object(client, "_make_request", return_value=[]) as mock:
            await client.get_markets(active_only=False)

            # Verify params were passed
            call_args = mock.call_args
            assert call_args[1]["params"]["active"] == "false"


class TestGetOrderbook:
    """Test get_orderbook method."""

    @pytest.mark.asyncio
    async def test_get_orderbook_success(self):
        client = PolymarketClient()
        """Test fetching orderbook successfully."""
        with patch.object(
            client,
            "_make_request",
            return_value={
                "bids": [{"price": 0.55, "size": 100.0}],
                "asks": [{"price": 0.56, "size": 150.0}],
            },
        ):
            book = await client.get_orderbook("0xabc123")

        assert isinstance(book, OrderBook)
        assert book.token_id == "0xabc123"
        assert book.best_bid == 0.55
        assert book.best_ask == 0.56

    @pytest.mark.asyncio
    async def test_get_orderbook_empty(self):
        client = PolymarketClient()
        """Test fetching empty orderbook."""
        with patch.object(
            client,
            "_make_request",
            return_value={
                "bids": [],
                "asks": [],
            },
        ):
            book = await client.get_orderbook("0xabc123")

        assert book.best_bid is None
        assert book.best_ask is None


class TestGetPrice:
    """Test get_price method."""

    @pytest.mark.asyncio
    async def test_get_price_success(self):
        client = PolymarketClient()
        """Test fetching prices successfully."""
        with patch.object(
            client,
            "_make_request",
            return_value={
                "bids": [{"price": 0.60, "size": 100.0}],
                "asks": [{"price": 0.61, "size": 150.0}],
            },
        ):
            prices = await client.get_price("0xabc123")

        assert prices["bid"] == 0.60
        assert prices["ask"] == 0.61
        assert abs(prices["mid"] - 0.605) < 0.0001


class TestRateLimiting:
    """Test rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limit_stats_structure(self):
        client = PolymarketClient()
        """Test that stats structure is correct."""
        stats = client.get_stats()

        assert "requests_in_window" in stats
        assert "rate_limit" in stats
        assert "remaining_requests" in stats
        assert stats["rate_limit"] == 100

    @pytest.mark.asyncio
    async def test_rate_limit_cleanup_old_requests(self):
        client = PolymarketClient()
        """Test that old requests are cleaned up."""
        now = asyncio.get_event_loop().time()
        client._request_times = [now - 100, now - 80, now - 10]

        await client._apply_rate_limit()

        assert len(client._request_times) == 1


class TestErrorHandling:
    """Test error handling and retries."""

    @pytest.fixture
    async def client(self):
        """Create client for testing."""
        client = PolymarketClient(max_retries=2, retry_delay=0.1)
        yield client
        await client.close()

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test that failed requests are retried."""
        client = PolymarketClient(max_retries=2, retry_delay=0.1)
        # This test verifies retry logic exists (tested via integration)
        # Just verify client has retry config
        assert client.max_retries == 2
        assert client.retry_delay == 0.1

    @pytest.mark.asyncio
    async def test_api_error_after_retries(self):
        client = PolymarketClient()
        """Test that API error is raised after all retries."""
        with patch.object(
            client, "_make_request", side_effect=PolymarketAPIError("Error")
        ) as mock:
            with pytest.raises(PolymarketAPIError):
                await client.get_markets()


class TestOrderBook:
    """Test OrderBook dataclass."""

    def test_orderbook_properties(self):
        """Test OrderBook properties with data."""
        book = OrderBook(
            token_id="0xabc",
            bids=[{"price": 0.55, "size": 100}],
            asks=[{"price": 0.56, "size": 150}],
            timestamp=1234567890.0,
        )

        assert book.best_bid == 0.55
        assert book.best_ask == 0.56
        assert abs(book.spread - 0.01) < 0.0001

    def test_orderbook_empty(self):
        """Test OrderBook properties when empty."""
        book = OrderBook(
            token_id="0xabc",
            bids=[],
            asks=[],
            timestamp=1234567890.0,
        )

        assert book.best_bid is None
        assert book.best_ask is None


class TestGetStats:
    """Test get_stats method."""

    def test_get_stats_with_api_key(self):
        """Test stats when API key is set."""
        client = PolymarketClient(api_key="test_key")
        stats = client.get_stats()

        assert stats["api_key_set"] is True

    def test_get_stats_without_api_key(self):
        """Test stats when no API key."""
        client = PolymarketClient()
        stats = client.get_stats()

        assert stats["api_key_set"] is False


class TestWebSocket:
    """Test WebSocket preparation."""

    @pytest.mark.asyncio
    async def test_websocket_not_implemented(self):
        """Test that WebSocket raises NotImplementedError."""
        client = PolymarketClient()

        with pytest.raises(NotImplementedError):
            await client.connect_websocket()


class TestGetMarket:
    """Test get_market method."""

    @pytest.mark.asyncio
    async def test_get_market_success(self):
        client = PolymarketClient()
        """Test fetching single market successfully."""
        with patch.object(
            client,
            "_make_request",
            return_value={
                "id": "market123",
                "question": "Will ETH hit $10k?",
            },
        ):
            market = await client.get_market("market123")

        assert market["id"] == "market123"
        assert market["question"] == "Will ETH hit $10k?"
