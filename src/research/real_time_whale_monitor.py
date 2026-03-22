# -*- coding: utf-8 -*-
"""Real-time Whale Monitor using WebSocket.

Monitors Polymarket WebSocket for whale trades and forwards
signals to copy trading engine with delay tracking.

Example:
    >>> from research.real_time_whale_monitor import RealTimeWhaleMonitor
    >>>
    >>> async def on_whale(signal):
    ...     print(f"Whale trade: {signal}")
    ...
    >>> monitor = RealTimeWhaleMonitor(
    ...     min_trade_size=Decimal("100"),
    ...     on_whale_signal=on_whale,
    ...     database_url="postgresql://..."
    ... )
    >>> await monitor.start()
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

import asyncpg
import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from src.data.ingestion.websocket_client import PolymarketWebSocket, WebSocketMessage
from src.research.whale_tracker import WhaleTracker
from src.research.whale_poller import WhalePoller
from src.data.storage.market_title_cache import get_market_title
from src.data.storage.market_category_cache import get_market_category
from src.config.settings import settings
from src.research.polymarket_data_client import PolymarketDataClient
from src.research.whale_trade_writer import save_whale_trade

logger = structlog.get_logger(__name__)


@dataclass
class WhaleTradeSignal:
    """Represents a detected whale trade from WebSocket.

    Attributes:
        signal_id: Unique signal identifier
        market_id: Market/token identifier
        side: Trade side ("buy" or "sell")
        size_usd: Trade size in USD
        price: Execution price
        trader_address: Trader wallet address
        timestamp: When trade was detected
        delay_ms: Delay from trade to detection (milliseconds)
    """

    signal_id: str
    market_id: str
    side: str
    size_usd: Decimal
    price: Decimal
    trader_address: str
    timestamp: float = field(default_factory=time.time)
    delay_ms: float = 0.0


@dataclass
class MonitorStats:
    """Statistics for whale monitor.

    Attributes:
        trades_detected: Total whale trades detected
        signals_sent: Signals sent to copy engine
        avg_delay_ms: Average detection delay
        max_delay_ms: Maximum detection delay
        alerts_triggered: Number of delay alerts
    """

    trades_detected: int = 0
    signals_sent: int = 0
    avg_delay_ms: float = 0.0
    max_delay_ms: float = 0.0
    alerts_triggered: int = 0


class RealTimeWhaleMonitor:
    """Real-time Whale Monitor using Polymarket WebSocket.

    Monitors WebSocket for large trades and forwards signals
    to copy trading engine with delay tracking.

    Attributes:
        WS_URL: Polymarket WebSocket endpoint
        MAX_ACCEPTABLE_DELAY_MS: Maximum acceptable delay (10 seconds)
    """

    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    MAX_ACCEPTABLE_DELAY_MS = 10000

    def __init__(
        self,
        min_trade_size: Decimal = Decimal("100"),
        on_whale_signal: Optional[Callable[[WhaleTradeSignal], Any]] = None,
        database_url: Optional[str] = None,
        whale_tracker: Optional[WhaleTracker] = None,
        tracked_whales: Optional[Set[str]] = None,
        api_key: Optional[str] = None,
    ) -> None:
        """Initialize Real-time Whale Monitor.

        Args:
            min_trade_size: Minimum trade size to trigger signal (default: $100)
            on_whale_signal: Callback for whale trade signals
            database_url: PostgreSQL connection URL
            whale_tracker: WhaleTracker instance for whale filtering
            tracked_whales: Set of whale addresses to monitor
            api_key: Optional API key for authenticated requests
        """
        self.min_trade_size = min_trade_size
        self.on_whale_signal = on_whale_signal
        self.database_url = database_url
        self.whale_tracker = whale_tracker
        self.tracked_whales = tracked_whales or set()
        self.api_key = api_key

        # Whale poller dependencies
        self._db_pool: Optional[asyncpg.Pool] = None
        self._polymarket_client: Optional[PolymarketDataClient] = None
        self.config: dict = {}
        self.whale_poller: Optional[WhalePoller] = None

        self._ws: Optional[PolymarketWebSocket] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._engine = None
        self._Session = None
        self._delays: List[float] = []
        self._lock = asyncio.Lock()

        self.stats = MonitorStats()

        logger.info(
            "whale_monitor_initialized",
            min_trade_size=str(min_trade_size),
            tracked_whales=len(self.tracked_whales),
        )

    def set_database(self, database_url: str) -> None:
        """Set database URL and initialize connection."""
        self.database_url = database_url
        self._engine = create_engine(database_url)
        self._Session = sessionmaker(bind=self._engine)
        logger.info("whale_monitor_database_configured")

    async def _init_whale_poller(self) -> None:
        """Инициализировать whale poller."""
        if self.whale_poller is not None:
            logger.debug("whale_poller_already_initialized")
            return

        # Initialize asyncpg pool from database_url
        if self._db_pool is None and self.database_url:
            # Convert SQLAlchemy URL to asyncpg format
            # postgresql://user:pass@host:port/db -> user:pass@host:port/db
            db_url = self.database_url.replace("postgresql+psycopg2://", "postgresql://")
            db_url = db_url.replace("postgresql://", "")

            # Parse components
            if "@" in db_url:
                auth, host_db = db_url.split("@")
                user, password = auth.split(":")
                if "/" in host_db:
                    host, db = host_db.split("/")
                    port = 5432
                    if ":" in host:
                        host, port = host.split(":")
                else:
                    host = host_db
                    db = "postgres"
                    port = 5432
            else:
                # Default fallback
                user = "postgres"
                password = "password"
                host = "localhost"
                port = 5433
                db = "postgres"

            try:
                self._db_pool = await asyncpg.create_pool(
                    host=host,
                    port=int(port),
                    user=user,
                    password=password,
                    database=db,
                    min_size=2,
                    max_size=10,
                )
                logger.info("whale_poller_db_pool_created")
            except Exception as e:
                logger.error("whale_poller_db_pool_failed", error=str(e))
                return

        # Initialize Polymarket Data client
        if self._polymarket_client is None:
            self._polymarket_client = PolymarketDataClient(
                api_key=settings.polymarket_api_key
            )
            logger.info("whale_poller_polymarket_client_created")

        # Initialize WhaleTracker
        whale_tracker = WhaleTracker()

        # Create WhalePoller
        self.whale_poller = WhalePoller(
            db_pool=self._db_pool,
            polymarket_client=self._polymarket_client,
            whale_tracker=whale_tracker,
            config=self.config,
        )
        logger.info("whale_poller_initialized")

    def add_tracked_whale(self, address: str) -> None:
        """Add whale address to track."""
        self.tracked_whales.add(address.lower())
        logger.info("whale_added_to_monitor", address=address[:10])

    def remove_tracked_whale(self, address: str) -> None:
        """Remove whale address from tracking."""
        self.tracked_whales.discard(address.lower())
        logger.info("whale_removed_from_monitor", address=address[:10])

    async def _ensure_database(self) -> None:
        """Ensure database connection is available."""
        if not self.database_url:
            return
        if not self._engine:
            self._engine = create_engine(self.database_url)
            self._Session = sessionmaker(bind=self._engine)

    async def start(self, token_ids: Optional[List[str]] = None) -> None:
        """Start monitoring whale trades.

        Args:
            token_ids: Optional list of token IDs to subscribe to
        """
        if self._running:
            logger.warning("whale_monitor_already_running")
            return

        self._running = True
        self._ws = PolymarketWebSocket(
            api_key=self.api_key,
            on_message=self._handle_message,
        )

        try:
            await self._ws.connect()
            logger.info("whale_monitor_connected")

            if token_ids:
                await self._ws.subscribe_tokens(token_ids)

            self._task = asyncio.create_task(self._ws.start_listening())

            # Инициализировать и запустить whale poller
            await self._init_whale_poller()
            if self.whale_poller:
                asyncio.create_task(self.whale_poller.run_hot_polling())
                asyncio.create_task(self.whale_poller.run_warm_polling())
                asyncio.create_task(self.whale_poller.run_tier_downgrade_check())
                logger.info("whale_poller_tasks_started")

        except Exception as e:
            logger.error("whale_monitor_start_failed", error=str(e))
            self._running = False
            raise

    async def stop(self) -> None:
        """Stop monitoring."""
        self._running = False

        # Stop whale poller
        if self.whale_poller:
            logger.info("whale_poller_stopping")
            self.whale_poller = None

        # Close asyncpg pool
        if self._db_pool:
            await self._db_pool.close()
            self._db_pool = None
            logger.info("whale_poller_db_pool_closed")

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.disconnect()

        logger.info("whale_monitor_stopped", stats=self._get_stats())

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("monitor_loop_error", error=str(e))
                await asyncio.sleep(1)

    def _handle_message(self, msg: WebSocketMessage) -> None:
        """Handle incoming WebSocket message."""
        if not self._running:
            return

        data = msg.data
        if not data:
            return

        if isinstance(data, list):
            for item in data:
                self._process_single_message(item, msg.timestamp)
            return

        try:
            self._process_single_message(data, msg.timestamp)
        except Exception as e:
            logger.debug("message_handling_error", error=str(e))

    def _process_single_message(self, data: Dict[str, Any], received_at: float) -> None:
        """Process a single message item."""
        try:
            event_type = data.get("event_type", "")

            if event_type == "trade":
                self._process_ws_trade(data, received_at)
            elif event_type == "order" or "bids" in data or "asks" in data:
                self._process_orderbook_update(data, received_at)
            elif "price_changes" in data:
                pass  # Price updates, not trades
            elif "last_trade_price" in data:
                pass  # Orderbook snapshot, not trade
        except Exception as e:
            logger.debug("item_handling_error", error=str(e))

    def _process_ws_trade(self, data: Dict[str, Any], received_at: float) -> None:
        """Process trade from WebSocket message."""
        asset_id = data.get("asset_id", "")
        price = Decimal(str(data.get("price", 0)))
        size = Decimal(str(data.get("size", 0)))
        side = data.get("side", "buy").lower()

        if size * price < self.min_trade_size:
            return

        timestamp = data.get("timestamp", received_at)

        signal = WhaleTradeSignal(
            signal_id=str(uuid4()),
            market_id=data.get("market", asset_id),
            side=side,
            size_usd=size * price,
            price=price,
            trader_address=data.get("address", data.get("owner", "unknown")),
            timestamp=timestamp,
            delay_ms=(received_at - timestamp) * 1000 if timestamp else 0,
        )

        asyncio.create_task(self._handle_whale_signal(signal))

    def _process_trade_data(self, data: Dict[str, Any], received_at: float) -> None:
        """Process trade data from WebSocket message.

        Args:
            data: Trade data from message
            received_at: Timestamp when message was received
        """
        trades = data.get("trades", [])
        if not trades:
            return

        for trade in trades:
            size_usd = Decimal(str(trade.get("size", 0)))
            price = Decimal(str(trade.get("price", 0)))

            if size_usd < self.min_trade_size:
                continue

            trader = trade.get("address", "").lower()
            if self.tracked_whales and trader not in self.tracked_whales:
                continue

            if self.whale_tracker:
                if not self.whale_tracker.is_quality_whale(
                    self.whale_tracker.whale_stats.get(trader)
                ):
                    continue

            trade_time = trade.get("timestamp", received_at)
            delay_ms = (received_at - trade_time) * 1000

            signal = WhaleTradeSignal(
                signal_id=str(uuid4()),
                market_id=trade.get("conditionId", trade.get("tokenId", "")),
                side=trade.get("side", "buy").lower(),
                size_usd=size_usd,
                price=price,
                trader_address=trader,
                timestamp=trade_time,
                delay_ms=delay_ms,
            )

            asyncio.create_task(self._handle_whale_signal(signal))

    def _process_orderbook_update(
        self, data: Dict[str, Any], received_at: float
    ) -> None:
        """Process orderbook update for large orders."""
        size = Decimal(str(data.get("size", 0)))
        if size < self.min_trade_size:
            return

        price = Decimal(str(data.get("price", 0)))
        side = data.get("side", "buy").lower()

        signal = WhaleTradeSignal(
            signal_id=str(uuid4()),
            market_id=data.get("conditionId", data.get("tokenId", "")),
            side=side,
            size_usd=size,
            price=price,
            trader_address=data.get("address", "unknown"),
            timestamp=received_at,
            delay_ms=0.0,
        )

        asyncio.create_task(self._handle_whale_signal(signal))

    async def _handle_whale_signal(self, signal: WhaleTradeSignal) -> None:
        """Handle detected whale trade signal."""
        async with self._lock:
            self.stats.trades_detected += 1
            self._delays.append(signal.delay_ms)

            if len(self._delays) > 1000:
                self._delays = self._delays[-1000:]

            self.stats.avg_delay_ms = sum(self._delays) / len(self._delays)
            self.stats.max_delay_ms = max(self._delays)

        if signal.delay_ms > self.MAX_ACCEPTABLE_DELAY_MS:
            self.stats.alerts_triggered += 1
            logger.warning(
                "whale_signal_delay_high",
                signal_id=signal.signal_id[:8],
                delay_ms=signal.delay_ms,
                max_acceptable=self.MAX_ACCEPTABLE_DELAY_MS,
            )

        market_title = await get_market_title(signal.market_id)
        
        # Calculate outcome based on price and side (Polymarket binary convention)
        outcome = "Yes" if (signal.side == "buy" and signal.price < 0.5) or (signal.side == "sell" and signal.price >= 0.5) else "No"
        
        await self._save_whale_signal_to_db(signal, market_title=market_title, outcome=outcome)

        if self.on_whale_signal:
            try:
                await self.on_whale_signal(signal)
                self.stats.signals_sent += 1
            except Exception as e:
                logger.error("whale_signal_callback_failed", error=str(e))

        logger.info(
            "whale_trade_detected",
            signal_id=signal.signal_id[:8],
            market=signal.market_id[:20],
            side=signal.side,
            size=str(signal.size_usd),
            price=str(signal.price),
            delay_ms=signal.delay_ms,
        )

    async def _save_whale_signal_to_db(self, signal: WhaleTradeSignal, market_title: Optional[str] = None, outcome: Optional[str] = None) -> None:
        """Save whale signal to database using unified save_whale_trade method.

        Args:
            signal: The whale trade signal
            market_title: Market question/title from Polymarket API (optional)
            outcome: Trade outcome (Yes/No). If API returns Up/Down, convert using: outcomeIndex 0 = Yes, 1 = No
        """
        # Ensure async engine exists
        if not hasattr(self, '_async_engine') or self._async_engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine
            # Convert postgresql+psycopg2:// to postgresql+asyncpg://
            async_db_url = self.database_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
            self._async_engine = create_async_engine(async_db_url, pool_pre_ping=True)

        # Get market category
        market_category = await get_market_category(signal.market_id)

        # Create async session
        from sqlalchemy.ext.asyncio import AsyncSession
        async_session_maker = sessionmaker(
            self._async_engine, class_=AsyncSession, expire_on_commit=False
        )

        async with async_session_maker() as session:
            try:
                await save_whale_trade(
                    session=session,
                    wallet_address=signal.trader_address,
                    market_id=signal.market_id,
                    side=signal.side,
                    size_usd=signal.size_usd,
                    price=signal.price,
                    outcome=outcome,
                    market_title=market_title,
                    market_category=market_category,
                    source="REALTIME",
                )
            except Exception as e:
                logger.debug("whale_signal_save_failed", error=str(e))

    def _get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics."""
        return {
            "trades_detected": self.stats.trades_detected,
            "signals_sent": self.stats.signals_sent,
            "avg_delay_ms": self.stats.avg_delay_ms,
            "max_delay_ms": self.stats.max_delay_ms,
            "alerts_triggered": self.stats.alerts_triggered,
        }

    def get_stats(self) -> MonitorStats:
        """Get monitoring statistics."""
        return self.stats

    def is_running(self) -> bool:
        """Check if monitor is running."""
        return self._running

    async def subscribe_to_markets(self, token_ids: List[str]) -> None:
        """Subscribe to additional markets.

        Args:
            token_ids: List of token IDs to subscribe to
        """
        if self._ws:
            await self._ws.subscribe_tokens(token_ids)
            logger.info("subscribed_to_markets", count=len(token_ids))


class WhaleSignalBuffer:
    """Buffer for managing whale signals with deduplication."""

    def __init__(self, dedup_window_seconds: float = 5.0) -> None:
        """Initialize signal buffer.

        Args:
            dedup_window_seconds: Time window for deduplication
        """
        self.dedup_window = dedup_window_seconds
        self._signals: Dict[str, WhaleTradeSignal] = {}
        self._lock = asyncio.Lock()

    async def add(self, signal: WhaleTradeSignal) -> bool:
        """Add signal to buffer if not duplicate.

        Args:
            signal: Signal to add

        Returns:
            True if added, False if duplicate
        """
        async with self._lock:
            key = f"{signal.market_id}:{signal.trader_address}:{signal.side}"

            for existing_key, existing_signal in list(self._signals.items()):
                if existing_key == key:
                    if signal.timestamp - existing_signal.timestamp < self.dedup_window:
                        return False
                    del self._signals[existing_key]

            self._signals[key] = signal
            return True

    async def get_recent(self, seconds: float = 60.0) -> List[WhaleTradeSignal]:
        """Get recent signals from buffer.

        Args:
            seconds: Time window in seconds

        Returns:
            List of recent signals
        """
        async with self._lock:
            now = time.time()
            return [s for s in self._signals.values() if now - s.timestamp < seconds]

    async def clear(self) -> None:
        """Clear the buffer."""
        async with self._lock:
            self._signals.clear()
