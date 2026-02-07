# -*- coding: utf-8 -*-
"""Unit tests for PolymarketWebSocket.

Tests cover:
    - Connection management
    - Token subscription
    - Message processing
    - Reconnect logic
    - Ping/pong heartbeat
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data.ingestion.websocket_client import (
    PolymarketWebSocket,
    WebSocketMessage,
)


class TestWebSocketInitialization:
    """Test WebSocket client initialization."""

    def test_default_initialization(self):
        """Test client initializes with default parameters."""
        ws = PolymarketWebSocket()

        assert ws.api_key is None
        assert ws.on_message is None
        assert ws.reconnect_delay == 1.0
        assert ws.max_reconnect_delay == 60.0
        assert ws._connected is False

    def test_custom_initialization(self):
        """Test client initializes with custom parameters."""
        callback = MagicMock()

        ws = PolymarketWebSocket(
            api_key="test_key",
            api_secret="test_secret",
            api_passphrase="test_pass",
            on_message=callback,
            reconnect_delay=2.0,
            max_reconnect_delay=30.0,
        )

        assert ws.api_key == "test_key"
        assert ws.on_message == callback
        assert ws.reconnect_delay == 2.0
        assert ws.max_reconnect_delay == 30.0


class TestConnection:
    """Test WebSocket connection management."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection."""
        ws = PolymarketWebSocket()

        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_ws = AsyncMock()
            mock_connect.return_value = mock_ws

            result = await ws.connect()

            assert result is True
            assert ws._connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test connection failure."""
        ws = PolymarketWebSocket()

        with patch("websockets.connect", side_effect=Exception("Connection failed")):
            result = await ws.connect()

            assert result is False
            assert ws._connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnection."""
        ws = PolymarketWebSocket()
        ws._connected = True
        ws._ws = AsyncMock()
        ws._running = True

        await ws.disconnect()

        assert ws._connected is False
        assert ws._running is False


class TestSubscriptions:
    """Test subscription management."""

    @pytest.mark.asyncio
    async def test_subscribe_tokens(self):
        """Test subscribing to tokens."""
        ws = PolymarketWebSocket()
        ws._connected = True
        ws._ws = AsyncMock()

        token_ids = ["token1", "token2", "token3"]
        result = await ws.subscribe_tokens(token_ids)

        assert result is True
        assert len(ws._subscribed_tokens) == 3
        ws._ws.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_when_not_connected(self):
        """Test subscription when not connected."""
        ws = PolymarketWebSocket()
        ws._connected = False

        token_ids = ["token1"]
        result = await ws.subscribe_tokens(token_ids)

        # Should queue tokens but return False
        assert result is False
        assert "token1" in ws._subscribed_tokens

    @pytest.mark.asyncio
    async def test_unsubscribe_tokens(self):
        """Test unsubscribing from tokens."""
        ws = PolymarketWebSocket()
        ws._connected = True
        ws._ws = AsyncMock()
        ws._subscribed_tokens = ["token1", "token2"]

        result = await ws.unsubscribe_tokens(["token1"])

        assert result is True
        assert "token1" not in ws._subscribed_tokens
        assert "token2" in ws._subscribed_tokens


class TestMessageHandling:
    """Test message processing."""

    @pytest.mark.asyncio
    async def test_handle_message(self):
        """Test handling incoming message."""
        callback = MagicMock()
        ws = PolymarketWebSocket(on_message=callback)

        message_data = {
            "asset_id": "token123",
            "price": 0.55,
            "side": "BUY",
            "size": 100,
        }

        await ws._handle_message(message_data)

        # Check callback was called
        assert callback.called
        call_args = callback.call_args[0][0]
        assert isinstance(call_args, WebSocketMessage)
        assert call_args.asset_id == "token123"

    @pytest.mark.asyncio
    async def test_handle_message_without_callback(self):
        """Test handling message without callback."""
        ws = PolymarketWebSocket()  # No callback

        message_data = {
            "asset_id": "token123",
            "price": 0.55,
        }

        # Should not raise
        await ws._handle_message(message_data)

        # Check message in queue
        assert ws._message_queue.qsize() == 1


class TestPingPong:
    """Test heartbeat ping/pong."""

    @pytest.mark.asyncio
    async def test_ping_sent(self):
        """Test that PING is sent."""
        ws = PolymarketWebSocket()
        ws._connected = True
        ws._running = True
        ws._ws = AsyncMock()

        # Run ping loop briefly
        task = asyncio.create_task(ws._ping_loop())
        await asyncio.sleep(0.1)
        task.cancel()

        # Check PING was sent
        calls = ws._ws.send.call_args_list
        assert any(call[0][0] == "PING" for call in calls)


class TestReconnectLogic:
    """Test reconnect functionality."""

    @pytest.mark.asyncio
    async def test_reconnect_count_tracked(self):
        """Test that reconnect count is tracked."""
        ws = PolymarketWebSocket()
        ws._reconnect_count = 3

        stats = ws.get_stats()
        assert stats["reconnect_count"] == 3

    @pytest.mark.asyncio
    async def test_initial_subscription_on_connect(self):
        """Test that queued subscriptions are sent on connect."""
        ws = PolymarketWebSocket()
        ws._subscribed_tokens = ["token1", "token2"]
        ws._connected = True
        ws._ws = AsyncMock()

        await ws._send_initial_subscription()

        # Check subscription was sent
        ws._ws.send.assert_called_once()
        call_args = ws._ws.send.call_args[0][0]
        data = json.loads(call_args)
        assert data["type"] == "market"
        assert "token1" in data["assets_ids"]


class TestStats:
    """Test statistics methods."""

    def test_get_stats(self):
        """Test getting connection stats."""
        ws = PolymarketWebSocket()
        ws._connected = True
        ws._reconnect_count = 2
        ws._subscribed_tokens = ["token1", "token2", "token3"]

        stats = ws.get_stats()

        assert stats["connected"] is True
        assert stats["reconnect_count"] == 2
        assert stats["subscribed_tokens"] == 3

    def test_get_subscribed_tokens(self):
        """Test getting subscribed tokens."""
        ws = PolymarketWebSocket()
        ws._subscribed_tokens = ["token1", "token2"]

        tokens = ws.get_subscribed_tokens()

        assert "token1" in tokens
        assert "token2" in tokens
        assert len(tokens) == 2


class TestWebSocketMessage:
    """Test WebSocketMessage dataclass."""

    def test_message_creation(self):
        """Test creating WebSocketMessage."""
        msg = WebSocketMessage(
            channel="market",
            asset_id="token123",
            data={"price": 0.55, "size": 100},
        )

        assert msg.channel == "market"
        assert msg.asset_id == "token123"
        assert msg.data["price"] == 0.55
        assert msg.timestamp > 0


class TestIntegration:
    """Integration-style tests."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Test full WebSocket lifecycle."""
        messages_received = []

        def on_msg(msg):
            messages_received.append(msg)

        ws = PolymarketWebSocket(on_message=on_msg)

        # Mock connection
        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_ws = AsyncMock()
            mock_ws.__aiter__ = MagicMock(return_value=iter([]))
            mock_connect.return_value = mock_ws

            # Connect
            await ws.connect()
            assert ws.is_connected()

            # Subscribe to tokens
            await ws.subscribe_tokens(["token1"])

            # Simulate receiving message
            test_msg = {
                "asset_id": "token1",
                "price": 0.55,
                "side": "BUY",
            }
            await ws._handle_message(test_msg)

            # Verify message received
            assert len(messages_received) == 1

            # Disconnect
            await ws.disconnect()
            assert not ws.is_connected()
