# -*- coding: utf-8 -*-
"""Polymarket WebSocket Client for real-time data.

Provides real-time connection to Polymarket CLOB WebSocket API
for orderbook updates and trade monitoring.

Based on official Polymarket documentation:
https://docs.polymarket.com/quickstart/websocket/WSS-Quickstart

Example:
    >>> from data.ingestion.websocket_client import PolymarketWebSocket
    >>> ws = PolymarketWebSocket()
    >>> await ws.connect()
    >>> await ws.subscribe_tokens(["TOKEN_ID_1", "TOKEN_ID_2"])
    >>>
    >>> # Process messages
    >>> async for msg in ws.listen():
    ...     print(msg)
    >>>
    >>> await ws.disconnect()
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

logger = structlog.get_logger(__name__)


@dataclass
class WebSocketMessage:
    """Represents a WebSocket message from Polymarket.

    Attributes:
        channel: Message channel (market, user)
        asset_id: Token/asset identifier
        data: Message payload
        timestamp: Unix timestamp when received
    """

    channel: str
    asset_id: str
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class PolymarketWebSocket:
    """Polymarket WebSocket Client for real-time data.

    Features:
    - Real-time market data updates
    - Auto-reconnect with exponential backoff
    - Heartbeat/ping-pong (10s interval)
    - Rate limiting
    - Graceful shutdown

    Attributes:
        WS_URL: Polymarket WebSocket endpoint
    """

    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        on_message: Optional[Callable[[WebSocketMessage], Any]] = None,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
    ) -> None:
        """Initialize WebSocket client.

        Args:
            api_key: Optional API key for authenticated access
            api_secret: Optional API secret
            api_passphrase: Optional API passphrase
            on_message: Callback for all messages
            reconnect_delay: Initial reconnect delay in seconds
            max_reconnect_delay: Maximum reconnect delay
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.on_message = on_message
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        # Connection state
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._running = False
        self._reconnect_count = 0
        self._last_message_time = 0.0

        # Subscriptions
        self._subscribed_tokens: List[str] = []

        # Message queue for graceful shutdown
        self._message_queue: asyncio.Queue[WebSocketMessage] = asyncio.Queue()

        # Ping task
        self._ping_task: Optional[asyncio.Task] = None
        self._listener_task: Optional[asyncio.Task] = None

        logger.info(
            "websocket_client_initialized",
            has_api_key=api_key is not None,
            reconnect_delay=reconnect_delay,
        )

    async def connect(self) -> bool:
        """Connect to Polymarket WebSocket.

        Returns:
            True if connected successfully
        """
        if self._connected:
            logger.warning("already_connected")
            return True

        self._running = True

        try:
            # Build auth headers if API key provided
            extra_headers = {}
            if self.api_key and self.api_secret and self.api_passphrase:
                extra_headers["POLYMARKET_API_KEY"] = self.api_key

            self._ws = await websockets.connect(
                self.WS_URL,
                extra_headers=extra_headers if extra_headers else None,
            )
            self._connected = True
            self._reconnect_count = 0

            logger.info("websocket_connected", url=self.WS_URL)

            # Send initial subscription message
            if self._subscribed_tokens:
                await self._send_initial_subscription()

            # Start listener and ping tasks
            self._listener_task = asyncio.create_task(self._listen())
            self._ping_task = asyncio.create_task(self._ping_loop())

            return True

        except Exception as e:
            logger.error("websocket_connection_failed", error=str(e))
            return False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket gracefully."""
        self._running = False

        # Cancel tasks
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass

        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        # Close connection
        if self._ws:
            try:
                await self._ws.close()
                logger.info("websocket_disconnected")
            except Exception as e:
                logger.error("websocket_disconnect_error", error=str(e))

        self._connected = False

    async def subscribe_tokens(self, token_ids: List[str]) -> bool:
        """Subscribe to market data for tokens.

        Args:
            token_ids: List of token/asset IDs to subscribe

        Returns:
            True if subscribed successfully
        """
        if not self._connected or not self._ws:
            # Queue for later
            self._subscribed_tokens.extend(token_ids)
            logger.info("tokens_queued_for_subscription", count=len(token_ids))
            return False

        # Format: {"assets_ids": ["..."], "operation": "subscribe"}
        message = {
            "assets_ids": token_ids,
            "operation": "subscribe",
        }

        try:
            await self._ws.send(json.dumps(message))
            self._subscribed_tokens.extend(token_ids)
            logger.info(
                "subscribed_tokens",
                count=len(token_ids),
                tokens=[t[:20] for t in token_ids],
            )
            return True
        except Exception as e:
            logger.error("subscription_failed", error=str(e))
            return False

    async def unsubscribe_tokens(self, token_ids: List[str]) -> bool:
        """Unsubscribe from tokens.

        Args:
            token_ids: List of token IDs to unsubscribe

        Returns:
            True if unsubscribed successfully
        """
        if not self._connected or not self._ws:
            return False

        message = {
            "assets_ids": token_ids,
            "operation": "unsubscribe",
        }

        try:
            await self._ws.send(json.dumps(message))
            for tid in token_ids:
                if tid in self._subscribed_tokens:
                    self._subscribed_tokens.remove(tid)
            logger.info("unsubscribed_tokens", count=len(token_ids))
            return True
        except Exception as e:
            logger.error("unsubscription_failed", error=str(e))
            return False

    async def _send_initial_subscription(self) -> None:
        """Send initial subscription after connect."""
        if not self._subscribed_tokens:
            return

        # Format for initial connection: {"assets_ids": [...], "type": "market"}
        message = {
            "assets_ids": self._subscribed_tokens,
            "type": "market",
        }

        try:
            await self._ws.send(json.dumps(message))
            logger.info("sent_initial_subscription", count=len(self._subscribed_tokens))
        except Exception as e:
            logger.error("initial_subscription_failed", error=str(e))

    async def _ping_loop(self) -> None:
        """Send PING every 10 seconds to keep connection alive."""
        while self._running and self._connected:
            try:
                if self._ws:
                    await self._ws.send("PING")
                    logger.debug("ping_sent")
                await asyncio.sleep(10)
            except Exception as e:
                logger.warning("ping_failed", error=str(e))
                break

    async def _listen(self) -> None:
        """Listen for incoming messages with auto-reconnect."""
        current_delay = self.reconnect_delay

        while self._running:
            try:
                if not self._connected or not self._ws:
                    # Try to connect
                    if not await self.connect():
                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * 2, self.max_reconnect_delay)
                        continue

                    # Reset delay on successful connection
                    current_delay = self.reconnect_delay

                # Message loop
                async for raw_message in self._ws:
                    self._last_message_time = time.time()

                    # Handle PONG response
                    if raw_message == "PONG":
                        logger.debug("pong_received")
                        continue

                    # Handle PING from server
                    if raw_message == "PING":
                        await self._ws.send("PONG")
                        logger.debug("pong_sent")
                        continue

                    try:
                        data = json.loads(raw_message)
                        await self._handle_message(data)
                    except json.JSONDecodeError as e:
                        logger.warning(
                            "invalid_json", error=str(e), message=raw_message[:100]
                        )

            except ConnectionClosed as e:
                logger.warning("connection_closed", code=e.code, reason=e.reason)
                self._connected = False
                self._reconnect_count += 1

            except Exception as e:
                logger.error("websocket_error", error=str(e))
                self._connected = False
                self._reconnect_count += 1

            if not self._running:
                break

            # Exponential backoff
            logger.info(
                "reconnecting", delay=current_delay, attempt=self._reconnect_count
            )
            await asyncio.sleep(current_delay)
            current_delay = min(current_delay * 2, self.max_reconnect_delay)

    async def _handle_message(self, data: Dict[str, Any]) -> None:
        """Handle incoming WebSocket message.

        Args:
            data: Parsed JSON message
        """
        # Extract asset_id from various possible fields
        asset_id = (
            data.get("asset_id")
            or data.get("token_id")
            or data.get("market", "unknown")
        )
        channel = data.get("channel", "market")

        message = WebSocketMessage(
            channel=channel,
            asset_id=str(asset_id),
            data=data,
        )

        # Add to queue
        await self._message_queue.put(message)

        # Call callback if provided
        if self.on_message:
            try:
                result = self.on_message(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("message_callback_error", error=str(e))

    async def listen(self):
        """Async generator for consuming messages.

        Yields:
            WebSocketMessage objects
        """
        while self._running:
            try:
                message = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield message
            except asyncio.TimeoutError:
                continue

    def is_connected(self) -> bool:
        """Check if WebSocket is connected.

        Returns:
            True if connected
        """
        return self._connected

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics.

        Returns:
            Dict with connection stats
        """
        return {
            "connected": self._connected,
            "reconnect_count": self._reconnect_count,
            "last_message_time": self._last_message_time,
            "subscribed_tokens": len(self._subscribed_tokens),
            "queue_size": self._message_queue.qsize(),
        }

    def get_subscribed_tokens(self) -> List[str]:
        """Get list of subscribed token IDs.

        Returns:
            List of token IDs
        """
        return self._subscribed_tokens.copy()


class WebSocketConnectionError(Exception):
    """Exception for WebSocket connection errors."""

    pass
