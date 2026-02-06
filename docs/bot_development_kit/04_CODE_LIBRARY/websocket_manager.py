"""
WebSocket Manager - Real-time data feeds

Multi-connection handler for Polymarket and Manifold data streams.
Includes auto-reconnect, heartbeat, and graceful shutdown.

Sources:
- realfishsam/prediction-market-arbitrage-bot (WebSocket patterns)
- hodlwarden/polymarket-arbitrage-copy-bot (mempool monitoring)

Usage:
    from websocket_manager import WebSocketManager

    ws_manager = WebSocketManager()

    # Subscribe to orderbook updates
    await ws_manager.connect_polymarket(
        market_ids=["TOKEN_ID_1", "TOKEN_ID_2"],
        on_message=handle_orderbook_update
    )

    # Subscribe to blockchain events (whale monitoring)
    await ws_manager.connect_polygon_ws(
        on_pending_tx=handle_pending_tx
    )
"""

import asyncio
import json
import time
from typing import Callable, Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
import websockets
from websockets.exceptions import ConnectionClosed
import logging

logger = logging.getLogger(__name__)


@dataclass
class ConnectionState:
    """Track state of a WebSocket connection"""
    name: str
    uri: str
    is_connected: bool = False
    reconnect_count: int = 0
    last_message_time: float = 0
    subscriptions: Set[str] = field(default_factory=set)


class WebSocketManager:
    """
    Manages multiple WebSocket connections with auto-reconnect.

    Features:
    - Automatic reconnection with exponential backoff
    - Heartbeat monitoring
    - Graceful shutdown
    - Message buffering during reconnect
    """

    # Polymarket WebSocket endpoint
    POLYMARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws"

    def __init__(
        self,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
        heartbeat_interval: float = 30.0
    ):
        """
        Initialize WebSocket manager

        Args:
            reconnect_delay: Initial reconnect delay in seconds
            max_reconnect_delay: Maximum reconnect delay
            heartbeat_interval: Ping interval for connection health
        """
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.heartbeat_interval = heartbeat_interval

        # Connection management
        self.connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        self.states: Dict[str, ConnectionState] = {}
        self.callbacks: Dict[str, Callable] = {}

        # Control flags
        self._running = False
        self._tasks: List[asyncio.Task] = []

    async def start(self):
        """Start the WebSocket manager"""
        self._running = True
        logger.info("WebSocket manager started")

    async def stop(self):
        """Stop all connections gracefully"""
        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Close all connections
        for name, ws in self.connections.items():
            try:
                await ws.close()
                logger.info(f"Closed connection: {name}")
            except Exception as e:
                logger.error(f"Error closing {name}: {e}")

        self.connections.clear()
        self.states.clear()
        logger.info("WebSocket manager stopped")

    # ==================== Polymarket Connection ====================

    async def connect_polymarket(
        self,
        market_ids: List[str],
        on_message: Callable[[Dict], Any]
    ):
        """
        Connect to Polymarket CLOB WebSocket

        Args:
            market_ids: List of token IDs to subscribe to
            on_message: Callback for orderbook updates
        """
        name = "polymarket"
        self.callbacks[name] = on_message
        self.states[name] = ConnectionState(
            name=name,
            uri=self.POLYMARKET_WS,
            subscriptions=set(market_ids)
        )

        task = asyncio.create_task(
            self._maintain_connection(name, self.POLYMARKET_WS, market_ids)
        )
        self._tasks.append(task)

    async def _maintain_connection(
        self,
        name: str,
        uri: str,
        subscriptions: List[str]
    ):
        """Maintain WebSocket connection with auto-reconnect"""
        current_delay = self.reconnect_delay

        while self._running:
            try:
                async with websockets.connect(
                    uri,
                    ping_interval=self.heartbeat_interval,
                    ping_timeout=10,
                    close_timeout=5
                ) as ws:
                    self.connections[name] = ws
                    self.states[name].is_connected = True
                    self.states[name].reconnect_count = 0
                    current_delay = self.reconnect_delay

                    logger.info(f"Connected to {name}")

                    # Subscribe to channels
                    await self._subscribe(ws, subscriptions)

                    # Message loop
                    async for message in ws:
                        self.states[name].last_message_time = time.time()

                        try:
                            data = json.loads(message)
                            callback = self.callbacks.get(name)
                            if callback:
                                await self._safe_callback(callback, data)
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid JSON from {name}: {message[:100]}")

            except ConnectionClosed as e:
                logger.warning(f"Connection {name} closed: {e.code} - {e.reason}")
            except Exception as e:
                logger.error(f"WebSocket error {name}: {e}")

            # Mark disconnected
            self.states[name].is_connected = False
            self.states[name].reconnect_count += 1

            if not self._running:
                break

            # Exponential backoff
            logger.info(f"Reconnecting to {name} in {current_delay:.1f}s...")
            await asyncio.sleep(current_delay)
            current_delay = min(current_delay * 2, self.max_reconnect_delay)

    async def _subscribe(self, ws: websockets.WebSocketClientProtocol, market_ids: List[str]):
        """Subscribe to market channels"""
        for market_id in market_ids:
            subscribe_msg = {
                "type": "subscribe",
                "channel": "book",
                "market": market_id
            }
            await ws.send(json.dumps(subscribe_msg))
            logger.debug(f"Subscribed to {market_id}")

    async def _safe_callback(self, callback: Callable, data: Dict):
        """Execute callback with error handling"""
        try:
            result = callback(data)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Callback error: {e}")

    # ==================== Polygon WebSocket (Mempool) ====================

    async def connect_polygon_ws(
        self,
        rpc_wss_url: str,
        on_pending_tx: Callable[[Dict], Any],
        filter_addresses: Optional[List[str]] = None
    ):
        """
        Connect to Polygon WSS for pending transaction monitoring

        Args:
            rpc_wss_url: Alchemy/Infura WSS endpoint
            on_pending_tx: Callback for pending transactions
            filter_addresses: Optional list of addresses to filter
        """
        name = "polygon"
        self.callbacks[name] = on_pending_tx
        self.states[name] = ConnectionState(name=name, uri=rpc_wss_url)

        task = asyncio.create_task(
            self._maintain_polygon_connection(rpc_wss_url, filter_addresses)
        )
        self._tasks.append(task)

    async def _maintain_polygon_connection(
        self,
        uri: str,
        filter_addresses: Optional[List[str]]
    ):
        """Maintain Polygon WebSocket for mempool monitoring"""
        name = "polygon"
        filter_set = set(a.lower() for a in (filter_addresses or []))

        while self._running:
            try:
                async with websockets.connect(uri) as ws:
                    self.connections[name] = ws
                    self.states[name].is_connected = True
                    logger.info(f"Connected to Polygon WSS")

                    # Subscribe to pending transactions
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_subscribe",
                        "params": ["newPendingTransactions"]
                    }))

                    async for message in ws:
                        try:
                            data = json.loads(message)

                            # Handle subscription confirmation
                            if "result" in data and isinstance(data["result"], str):
                                logger.debug(f"Subscription ID: {data['result']}")
                                continue

                            # Handle pending tx notification
                            if "params" in data:
                                tx_hash = data["params"].get("result")
                                if tx_hash:
                                    # Get full transaction (optional filtering)
                                    await self._process_pending_tx(
                                        ws, tx_hash, filter_set
                                    )

                        except json.JSONDecodeError:
                            pass

            except Exception as e:
                logger.error(f"Polygon WS error: {e}")

            self.states[name].is_connected = False
            if self._running:
                await asyncio.sleep(self.reconnect_delay)

    async def _process_pending_tx(
        self,
        ws: websockets.WebSocketClientProtocol,
        tx_hash: str,
        filter_addresses: Set[str]
    ):
        """Process a pending transaction"""
        # Get transaction details
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "eth_getTransactionByHash",
            "params": [tx_hash]
        }))

        response = await ws.recv()
        data = json.loads(response)
        tx = data.get("result")

        if not tx:
            return

        # Filter by address if specified
        if filter_addresses:
            sender = tx.get("from", "").lower()
            if sender not in filter_addresses:
                return

        # Call callback
        callback = self.callbacks.get("polygon")
        if callback:
            await self._safe_callback(callback, tx)

    # ==================== Utility Methods ====================

    def is_connected(self, name: str) -> bool:
        """Check if a connection is active"""
        state = self.states.get(name)
        return state.is_connected if state else False

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics"""
        return {
            name: {
                "connected": state.is_connected,
                "reconnects": state.reconnect_count,
                "last_message": state.last_message_time,
                "subscriptions": len(state.subscriptions)
            }
            for name, state in self.states.items()
        }

    async def add_subscription(self, name: str, market_id: str):
        """Add subscription to existing connection"""
        ws = self.connections.get(name)
        state = self.states.get(name)

        if ws and state and state.is_connected:
            await ws.send(json.dumps({
                "type": "subscribe",
                "channel": "book",
                "market": market_id
            }))
            state.subscriptions.add(market_id)
            logger.info(f"Added subscription: {market_id}")

    async def remove_subscription(self, name: str, market_id: str):
        """Remove subscription from existing connection"""
        ws = self.connections.get(name)
        state = self.states.get(name)

        if ws and state and state.is_connected:
            await ws.send(json.dumps({
                "type": "unsubscribe",
                "channel": "book",
                "market": market_id
            }))
            state.subscriptions.discard(market_id)
            logger.info(f"Removed subscription: {market_id}")


# ==================== Example Usage ====================

async def example():
    """Example usage of WebSocketManager"""

    def handle_orderbook(data: Dict):
        """Handle orderbook updates"""
        print(f"Orderbook update: {data.get('market', 'unknown')[:20]}...")

    async def handle_pending_tx(tx: Dict):
        """Handle pending transactions"""
        print(f"Pending TX from: {tx.get('from', 'unknown')[:20]}...")

    manager = WebSocketManager()
    await manager.start()

    try:
        # Connect to Polymarket
        await manager.connect_polymarket(
            market_ids=["0x123..."],  # Replace with real token IDs
            on_message=handle_orderbook
        )

        # Run for 60 seconds
        await asyncio.sleep(60)

    finally:
        await manager.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example())
