# -*- coding: utf-8 -*-
"""Copy Trading Engine - Whale Following Strategy.

Monitors whale addresses and copies their trades with proportional sizing
based on conviction level using Kelly Criterion principles.

Sources:
    - crypmancer/polymarket-arbitrage-copy-bot (block-based following)
    - hodlwarden/polymarket-arbitrage-copy-bot (mempool monitoring)

Example:
    >>> from execution.copy_trading_engine import CopyTradingEngine
    >>> from decimal import Decimal
    >>>
    >>> engine = CopyTradingEngine(
    ...     config={
    ...         "whale_addresses": ["0x123...", "0x456..."],
    ...         "copy_capital": Decimal("70.0"),
    ...         "min_copy_size": Decimal("5.0"),
    ...         "max_copy_size": Decimal("20.0")
    ...     },
    ...     risk_manager=risk_manager,
    ...     executor=executor
    ... )
    >>>
    >>> # Process whale transaction
    >>> result = await engine.process_transaction(tx_data)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Union

import structlog
from web3 import Web3

from research.whale_tracker import WhaleTracker, WhaleStats

logger = structlog.get_logger(__name__)


@dataclass
class WhaleSignal:
    """Represents a detected whale trade signal.

    Attributes:
        address: Whale wallet address
        market_id: Market/token identifier
        side: Trade side ("BUY" or "SELL")
        amount: Trade size in USD
        price: Trade price (0-1 for binary markets)
        tx_hash: Transaction hash
        block_number: Block number where tx was mined
        is_opening: True if opening position, False if closing
        timestamp: Unix timestamp of detection
    """

    address: str
    market_id: str
    side: str
    amount: Decimal
    price: Decimal
    tx_hash: str
    block_number: int
    is_opening: bool
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())


@dataclass
class CopyPosition:
    """Tracks a copied position from a whale.

    Attributes:
        market_id: Market identifier
        entry_price: Entry price
        size: Position size in USD
        whale_address: Address of whale being copied
        whale_risk_score: Risk score of whale (1-10)
        entry_time: Unix timestamp of entry
        pnl: Realized PnL (updated on exit)
        exit_price: Exit price (set on close)
        exit_time: Exit timestamp (set on close)
    """

    market_id: str
    entry_price: Decimal
    size: Decimal
    whale_address: str
    whale_risk_score: int = 5
    entry_time: float = field(default_factory=lambda: datetime.now().timestamp())
    pnl: Decimal = Decimal("0")
    exit_price: Optional[Decimal] = None
    exit_time: Optional[float] = None


class CopyTradingEngine:
    """Copy Trading Engine for following whale trades.

    Monitors whale addresses and replicates their trades with
    proportional sizing based on conviction level. Uses Kelly Criterion
    principles for position sizing.

    Attributes:
        CLOB_ADDRESS: Polymarket CLOB contract address (Polygon)
        mode: Trading mode ("paper" or "live")
    """

    CLOB_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4dE6Bd8B8982E"

    def __init__(
        self,
        config: Dict[str, Any],
        risk_manager: Any,
        executor: Any,
        w3: Optional[Web3] = None,
        mode: str = "paper",
        virtual_bankroll: Optional[Any] = None,
        whale_tracker: Optional[WhaleTracker] = None,
        builder_client: Optional[Any] = None,
    ) -> None:
        """Initialize Copy Trading Engine.

        Args:
            config: Configuration dictionary containing:
                - whale_addresses: List of addresses to follow
                - whale_balances: Dict of estimated whale balances
                - copy_capital: Capital allocated for copy trading ($)
                - min_copy_size: Minimum trade size ($)
                - max_copy_size: Maximum trade size ($)
            risk_manager: RiskManager instance for trade validation
            executor: OrderExecutor instance for trade execution
            w3: Optional Web3 instance for transaction decoding
            mode: Trading mode ("paper" or "live")
            virtual_bankroll: Optional VirtualBankroll instance for paper trading
            whale_tracker: Optional WhaleTracker instance for whale data
            builder_client: Optional BuilderClient for gasless execution
        """
        self.config = config
        self.risk_manager = risk_manager
        self.executor = executor
        self.w3 = w3
        self.mode = mode
        self.virtual_bankroll = virtual_bankroll
        self.whale_tracker = whale_tracker
        self.builder_client = builder_client
        self.use_builder = builder_client is not None

        self.tracked_whales: Set[str] = set(
            addr.lower() for addr in config.get("whale_addresses", [])
        )

        self.whale_stats: Dict[str, WhaleStats] = {}

        self.whale_positions: Dict[str, Dict[str, Dict[str, Any]]] = {}

        self.positions: Dict[str, CopyPosition] = {}

        self.stats: Dict[str, Union[int, Decimal]] = {
            "signals_processed": 0,
            "trades_executed": 0,
            "positions_closed": 0,
            "total_pnl": Decimal("0"),
        }

        self.clob_abi = self._get_clob_abi()

        logger.info(
            "copy_trading_engine_initialized",
        )

        # Whale position tracking (what whales currently hold)
        self.whale_positions: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # Format: {whale_address: {market_id: {"side": "BUY", "size": Decimal("100")}}}

        # Our positions (copied from whales)
        self.positions: Dict[str, CopyPosition] = {}

        # Statistics
        self.stats: Dict[str, Union[int, Decimal]] = {
            "signals_processed": 0,
            "trades_executed": 0,
            "positions_closed": 0,
            "total_pnl": Decimal("0"),
        }

        # CLOB ABI for transaction decoding
        self.clob_abi = self._get_clob_abi()

        logger.info(
            "copy_trading_engine_initialized",
        )

    async def process_transaction(self, tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a blockchain transaction and decide whether to copy.

        Analyzes incoming transactions from tracked whales and determines
        if the trade should be copied based on risk parameters and sizing.

        Args:
            tx: Transaction dict with 'from', 'to', 'input', 'hash', etc.

        Returns:
            Trade result dict if copied, None otherwise
        """
        self.stats["signals_processed"] += 1

        sender = tx.get("from", "").lower()
        if sender not in self.tracked_whales:
            return None

        if not self.is_quality_whale(sender):
            logger.debug(
                "whale_not_quality",
                whale=sender[:10],
                reason="below quality threshold",
            )
            return None

        to_addr = tx.get("to", "").lower()
        if to_addr != self.CLOB_ADDRESS.lower():
            return None

        signal = self._decode_trade(tx, sender)
        if not signal:
            logger.debug(
                "trade_decode_failed",
                sender=sender[:10],
                tx_hash=tx.get("hash", "")[:10],
            )
            return None

        logger.info(
            "whale_signal_detected",
            whale=signal.address[:10],
            side=signal.side,
            amount=str(signal.amount),
            price=str(signal.price),
            market=signal.market_id[:20],
        )

        signal.is_opening = self._is_opening_trade(signal)

        if not signal.is_opening:
            return await self._handle_whale_exit(signal)

        copy_size = self._calculate_copy_size(signal)
        if copy_size == Decimal("0"):
            logger.info(
                "trade_too_small",
                whale_amount=str(signal.amount),
                calculated_size=str(copy_size),
            )
            return None

        can_trade, reason = self.risk_manager.can_trade(
            market_id=signal.market_id, size=float(copy_size), strategy="copy"
        )
        if not can_trade:
            logger.info(
                "risk_check_failed",
                reason=reason,
                market=signal.market_id[:20],
            )
            return None

        logger.info(
            "executing_copy_trade",
            side=signal.side,
            size=str(copy_size),
            market=signal.market_id[:20],
            mode=self.mode,
        )

        if self.mode == "paper":
            result = await self._execute_paper_trade(
                market_id=signal.market_id,
                side=signal.side,
                size=copy_size,
                price=signal.price,
                strategy="copy",
                whale_address=sender,
            )
        else:
            result = await self._execute_live_trade(
                market_id=signal.market_id,
                side=signal.side,
                size=copy_size,
                price=signal.price,
            )

        if result.get("success"):
            self.stats["trades_executed"] += 1

            fill_price = Decimal(str(result.get("fill_price", signal.price)))
            whale_risk_score = self.get_whale_risk_score(sender)
            self.positions[signal.market_id] = CopyPosition(
                market_id=signal.market_id,
                entry_price=fill_price,
                size=copy_size,
                whale_address=sender,
                whale_risk_score=whale_risk_score,
                entry_time=asyncio.get_event_loop().time(),
            )

            self._update_whale_position(signal)

            logger.info(
                "copy_trade_executed",
                order_id=result.get("order_id"),
                fill_price=str(fill_price),
                size=str(copy_size),
                whale_risk_score=whale_risk_score,
            )

        return result

    async def _execute_paper_trade(
        self,
        market_id: str,
        side: str,
        size: Decimal,
        price: Decimal,
        strategy: str,
        whale_address: str = "",
    ) -> Dict[str, Any]:
        """Execute a virtual trade in paper mode.

        Does NOT execute real trades - updates virtual bankroll only.

        Args:
            market_id: Market identifier
            side: Trade side ("BUY" or "SELL")
            size: Position size in USD
            price: Execution price
            strategy: Trading strategy name
            whale_address: Source whale address for tracking

        Returns:
            Dict with success status and trade details
        """
        if not self.virtual_bankroll:
            logger.warning("virtual_bankroll_not_configured")
            return {"success": False, "error": "Virtual bankroll not configured"}

        try:
            fees = size * Decimal("0.002")
            gas = Decimal("1.50")

            result = await self.virtual_bankroll.execute_virtual_trade(
                market_id=market_id,
                side=side.lower(),
                size=size,
                price=price,
                strategy=strategy,
                fees=fees,
                gas=gas,
                whale_source=whale_address,
            )

            logger.info(
                "paper_trade_executed",
                trade_id=result.trade_id,
                market_id=market_id,
                side=side,
                size=str(size),
                price=str(price),
                new_balance=str(self.virtual_bankroll.balance),
                whale_address=whale_address[:10] if whale_address else "",
            )

            return {
                "success": True,
                "trade_id": result.trade_id,
                "fill_price": float(price),
                "size": float(size),
                "mode": "paper",
            }

        except ValueError as e:
            logger.warning("paper_trade_insufficient_balance", error=str(e))
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error("paper_trade_failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def _execute_paper_close(
        self, market_id: str, side: str, size: Decimal, price: Decimal
    ) -> Dict[str, Any]:
        """Close a virtual position in paper mode.

        Args:
            market_id: Market identifier
            side: Opposite side to close
            size: Position size
            price: Close price

        Returns:
            Dict with success status and trade details
        """
        if not self.virtual_bankroll:
            return {"success": False, "error": "Virtual bankroll not configured"}

        try:
            fees = size * Decimal("0.002")

            result = await self.virtual_bankroll.close_virtual_position(
                market_id=market_id, close_price=price, fees=fees
            )

            return {
                "success": True,
                "trade_id": result.trade_id,
                "fill_price": float(price),
                "pnl": float(result.net_pnl),
                "mode": "paper",
            }

        except ValueError as e:
            logger.warning("paper_close_failed", error=str(e))
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error("paper_close_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def _execute_live_trade(
        self,
        market_id: str,
        side: str,
        size: Decimal,
        price: Decimal,
    ) -> Dict[str, Any]:
        """Execute a live trade with Builder API if available.

        Uses BuilderClient for gasless execution when available,
        falls back to regular executor otherwise.

        Args:
            market_id: Market identifier
            side: Trade side ("BUY" or "SELL")
            size: Position size in USD
            price: Execution price

        Returns:
            Dict with success status and trade details
        """
        from execution.polymarket.builder_client import BuilderClient  # noqa: F401

        if self.use_builder and self.builder_client:
            try:
                result = await self.builder_client.place_order(
                    token_id=market_id,
                    side=side,
                    size=float(size),
                    price=float(price),
                )

                logger.info(
                    "live_trade_executed_via_builder",
                    mode="builder",
                    success=result.success,
                    order_id=result.order_id,
                    filled=result.filled,
                )

                return {
                    "success": result.success,
                    "order_id": result.order_id,
                    "fill_price": float(result.fill_price)
                    if result.fill_price
                    else float(price),
                    "size": float(size),
                    "mode": "builder",
                    "error": result.error,
                }
            except Exception as e:
                logger.error("builder_trade_failed_using_fallback", error=str(e))
                if self.executor:
                    return await self.executor.execute(
                        market_id=market_id,
                        side=side,
                        size=float(size),
                        price=float(price),
                        mode="rest",
                    )
                return {"success": False, "error": str(e)}
        else:
            if self.executor:
                return await self.executor.execute(
                    market_id=market_id,
                    side=side,
                    size=float(size),
                    price=float(price),
                    mode="rest",
                )
            return {"success": False, "error": "No executor configured"}

    def _decode_trade(self, tx: Dict[str, Any], sender: str) -> Optional[WhaleSignal]:
        """Decode Polymarket CLOB transaction.

        Extracts trade details from transaction input data using
        Web3 contract decoding.

        Args:
            tx: Transaction data from blockchain
            sender: Whale address (normalized to lowercase)

        Returns:
            WhaleSignal with trade details or None if decode fails
        """
        if not self.w3:
            logger.warning("web3_not_configured")
            return None

        try:
            tx_input = tx.get("input", "")
            if not tx_input or tx_input == "0x":
                return None

            # Decode function call
            contract = self.w3.eth.contract(
                address=self.CLOB_ADDRESS,
                abi=self.clob_abi,  # type: ignore
            )

            func, params = contract.decode_function_input(tx_input)
            func_name = func.fn_name

            # Parse based on function type
            if "createOrder" in func_name or "fillOrder" in func_name:
                return WhaleSignal(
                    address=sender,
                    market_id=str(params.get("tokenId", "")),
                    side="BUY" if params.get("side", 0) == 0 else "SELL",
                    amount=Decimal(str(params.get("amount", 0))) / Decimal("1e6"),
                    price=Decimal(str(params.get("price", 0))) / Decimal("1e6"),
                    tx_hash=tx.get("hash", ""),
                    block_number=tx.get("blockNumber", 0),
                    is_opening=True,
                )

        except Exception as e:
            logger.debug("decode_error", error=str(e))

        return None

    def _is_opening_trade(self, signal: WhaleSignal) -> bool:
        """Determine if whale is opening or closing a position.

        Returns True if:
            - Whale has no existing position in this market
            - Whale is adding to existing position (same side)

        Returns False if:
            - Whale is reducing/closing position (opposite side)

        Args:
            signal: The detected whale signal

        Returns:
            True if opening/adding, False if closing/reducing
        """
        whale_pos = self.whale_positions.get(signal.address, {})
        existing = whale_pos.get(signal.market_id)

        if existing is None:
            return True  # New position

        if existing["side"] == signal.side:
            return True  # Adding to position

        return False  # Closing/reducing position

    def _calculate_copy_size(self, signal: WhaleSignal) -> Decimal:
        """Calculate Kelly-based copy size using whale win rate.

        Formula: f* = (b * p - q) / b
        Where:
        - b = payout ratio (odds received)
        - p = probability of winning (whale's win rate)
        - q = probability of losing (1 - p)

        Applies quarter Kelly (0.25) for safety, with min/max limits:
        - Min position: 1% of bankroll
        - Max position: 5% of bankroll

        Args:
            signal: The whale trade signal

        Returns:
            Calculated copy size in USD, or 0 if below minimum
        """
        bankroll = Decimal(str(self.config.get("copy_capital", Decimal("70.0"))))

        whale_stats = self.whale_stats.get(signal.address.lower())
        if not whale_stats:
            logger.debug(
                "no_whale_stats_using_proportional",
                address=signal.address[:10],
            )
            return self._calculate_proportional_size(signal)

        win_probability = whale_stats.win_rate
        if win_probability <= Decimal("0"):
            logger.debug(
                "zero_win_probability",
                address=signal.address[:10],
            )
            return Decimal("0")

        payout_ratio = (
            Decimal("1") / signal.price if signal.price > Decimal("0") else Decimal("1")
        )
        p = win_probability
        q = Decimal("1") - p

        b = payout_ratio - Decimal("1")

        if b <= Decimal("0"):
            logger.debug(
                "negative_payout_using_proportional",
                address=signal.address[:10],
            )
            return self._calculate_proportional_size(signal)

        kelly_fraction = (b * p - q) / b

        if kelly_fraction <= Decimal("0"):
            logger.debug(
                "negative_kelly_no_edge",
                address=signal.address[:10],
                win_prob=str(win_probability),
                payout=str(payout_ratio),
            )
            return Decimal("0")

        quarter_kelly = kelly_fraction * Decimal("0.25")

        min_fraction = Decimal("0.01")
        max_fraction = Decimal("0.05")

        final_fraction = max(min_fraction, min(quarter_kelly, max_fraction))

        kelly_size = bankroll * final_fraction

        min_size = Decimal(
            str(self.config.get("min_copy_size", bankroll * min_fraction))
        )
        max_size = Decimal(
            str(self.config.get("max_copy_size", bankroll * max_fraction))
        )

        if kelly_size < min_size:
            logger.debug(
                "kelly_size_below_min",
                kelly_size=str(kelly_size),
                min_size=str(min_size),
            )
            return Decimal("0")

        result = min(kelly_size, max_size)

        logger.info(
            "kelly_size_calculated",
            whale=signal.address[:10],
            win_rate=str(win_probability),
            payout=str(payout_ratio),
            kelly_fraction=str(kelly_fraction),
            quarter_kelly=str(quarter_kelly),
            final_fraction=str(final_fraction),
            size=str(result),
            bankroll=str(bankroll),
        )

        return result

    def _calculate_proportional_size(self, signal: WhaleSignal) -> Decimal:
        """Calculate proportional copy size based on whale conviction.

        Fallback method when whale stats unavailable.

        Args:
            signal: The whale trade signal

        Returns:
            Calculated copy size in USD, or 0 if below minimum
        """
        whale_balances = self.config.get("whale_balances", {})
        whale_balance = Decimal(
            str(
                whale_balances.get(
                    signal.address,
                    100000,
                )
            )
        )

        conviction = signal.amount / whale_balance
        my_balance = Decimal(str(self.config.get("copy_capital", Decimal("70.0"))))
        base_size = my_balance * conviction

        min_size = Decimal(str(self.config.get("min_copy_size", Decimal("5.0"))))
        max_size = Decimal(str(self.config.get("max_copy_size", Decimal("20.0"))))

        if base_size < min_size:
            return Decimal("0")

        return min(base_size, max_size)

    async def _handle_whale_exit(self, signal: WhaleSignal) -> Optional[Dict[str, Any]]:
        """Handle whale exiting a position - close our position too.

        When a whale closes their position, we should also exit our
        copied position to follow their strategy.

        Args:
            signal: The whale's exit signal

        Returns:
            Exit trade result dict or None if no position to close
        """
        our_position = self.positions.get(signal.market_id)
        if not our_position:
            return None  # We don't have this position

        # Only exit if we followed this whale
        if our_position.whale_address != signal.address:
            logger.debug(
                "different_whale_position",
                our_whale=our_position.whale_address[:10],
                signal_whale=signal.address[:10],
            )
            return None

        logger.info(
            "whale_exiting_closing_position",
            market=signal.market_id[:20],
            position_size=str(our_position.size),
        )

        # Opposite side to close
        exit_side = "SELL" if signal.side == "BUY" else "BUY"

        if self.mode == "paper":
            result = await self._execute_paper_close(
                market_id=signal.market_id,
                side=exit_side,
                size=our_position.size,
                price=signal.price,
            )
        else:
            result = await self._execute_live_trade(
                market_id=signal.market_id,
                side=exit_side,
                size=our_position.size,
                price=signal.price,
            )

        if result.get("success"):
            self.stats["positions_closed"] += 1

            # Calculate PnL
            entry = our_position.entry_price
            exit_price = Decimal(str(result.get("fill_price", signal.price)))

            if our_position.size > 0:  # Was long
                pnl = (exit_price - entry) * our_position.size
            else:
                pnl = (entry - exit_price) * abs(our_position.size)

            # Update position
            our_position.pnl = pnl
            our_position.exit_price = exit_price
            our_position.exit_time = asyncio.get_event_loop().time()

            # Record and remove position
            self.risk_manager.record_trade("copy", float(pnl), signal.market_id)
            current_pnl = self.stats["total_pnl"]
            assert isinstance(current_pnl, Decimal)
            self.stats["total_pnl"] = current_pnl + pnl
            del self.positions[signal.market_id]

            logger.info(
                "position_closed",
                pnl=str(pnl),
                entry=str(entry),
                exit=str(exit_price),
                mode=self.mode,
            )

        return result

    def _update_whale_position(self, signal: WhaleSignal) -> None:
        """Update our tracking of whale positions.

        Maintains internal state of what positions each tracked
        whale currently holds.

        Args:
            signal: The whale trade signal to record
        """
        if signal.address not in self.whale_positions:
            self.whale_positions[signal.address] = {}

        self.whale_positions[signal.address][signal.market_id] = {
            "side": signal.side,
            "size": signal.amount,
            "price": signal.price,
            "timestamp": signal.timestamp,
        }

    def add_whale(
        self, address: str, estimated_balance: Decimal = Decimal("100000")
    ) -> None:
        """Add a whale to track.

        Args:
            address: Ethereum address of whale
            estimated_balance: Estimated balance in USD for sizing
        """
        addr_lower = address.lower()
        self.tracked_whales.add(addr_lower)

        # Store balance
        if "whale_balances" not in self.config:
            self.config["whale_balances"] = {}
        self.config["whale_balances"][addr_lower] = estimated_balance

        logger.info(
            "whale_added",
            address=addr_lower[:10],
            estimated_balance=str(estimated_balance),
        )

    def remove_whale(self, address: str) -> None:
        """Stop tracking a whale.

        Args:
            address: Ethereum address to remove
        """
        addr_lower = address.lower()
        self.tracked_whales.discard(addr_lower)

        # Clean up position tracking
        if addr_lower in self.whale_positions:
            del self.whale_positions[addr_lower]

        logger.info("whale_removed", address=addr_lower[:10])

    def get_tracked_whales(self) -> list[str]:
        """Get list of tracked whale addresses.

        Returns:
            List of lowercase whale addresses
        """
        return list(self.tracked_whales)

    async def load_whales_from_database(
        self,
        database_url: str,
        min_win_rate: Decimal = Decimal("0.60"),
        min_trades: int = 100,
        max_risk_score: int = 6,
    ) -> List[WhaleStats]:
        """Load quality whales from database.

        Args:
            database_url: PostgreSQL connection URL
            min_win_rate: Minimum win rate (default: 60%)
            min_trades: Minimum total trades (default: 100)
            max_risk_score: Maximum risk score (default: 6)

        Returns:
            List of qualified WhaleStats
        """
        if not self.whale_tracker:
            self.whale_tracker = WhaleTracker(database_url=database_url)

        whales = await self.whale_tracker.load_quality_whales(
            min_win_rate=min_win_rate,
            min_trades=min_trades,
            max_risk_score=max_risk_score,
        )

        self.whale_stats = {w.wallet_address.lower(): w for w in whales}
        self.tracked_whales = set(self.whale_stats.keys())

        logger.info(
            "whales_loaded_from_database",
            count=len(whales),
            min_win_rate=str(min_win_rate),
            min_trades=min_trades,
            max_risk_score=max_risk_score,
        )

        return whales

    async def refresh_whale_stats(self) -> None:
        """Refresh statistics for all tracked whales from API."""
        if not self.whale_tracker:
            logger.warning("whale_tracker_not_configured")
            return

        for address in list(self.tracked_whales):
            try:
                stats = await self.whale_tracker.calculate_stats(address)
                self.whale_stats[address.lower()] = stats

                await self.whale_tracker.save_whale(stats)

                logger.debug(
                    "whale_stats_refreshed",
                    address=address[:10],
                    win_rate=str(stats.win_rate),
                    risk_score=stats.risk_score,
                )

            except Exception as e:
                logger.error(
                    "whale_stats_refresh_failed",
                    address=address[:10],
                    error=str(e),
                )

            await asyncio.sleep(0.5)

    def get_whale_risk_score(self, address: str) -> int:
        """Get risk score for a whale.

        Args:
            address: Whale wallet address

        Returns:
            Risk score 1-10 (1 = best), default 5 if unknown
        """
        stats = self.whale_stats.get(address.lower())
        return stats.risk_score if stats else 5

    def is_quality_whale(self, address: str) -> bool:
        """Check if address is a quality whale.

        Args:
            address: Whale wallet address

        Returns:
            True if whale meets quality criteria
        """
        stats = self.whale_stats.get(address.lower())
        if not stats:
            return False

        if self.whale_tracker:
            return self.whale_tracker.is_quality_whale(stats)

        return stats.win_rate >= Decimal("0.60") and stats.total_trades >= 100

    async def get_whale_positions(self, address: str) -> List[Any]:
        """Fetch current positions for a whale.

        Args:
            address: Whale wallet address

        Returns:
            List of whale positions
        """
        if not self.whale_tracker:
            logger.warning("whale_tracker_not_configured")
            return []

        return await self.whale_tracker.fetch_whale_positions(address)

    async def process_whale_signal(
        self,
        signal: Any,
    ) -> Optional[Dict[str, Any]]:
        """Process whale trade signal from real-time monitor.

        Takes a WhaleTradeSignal from WebSocket monitor and executes
        a copy trade.

        Args:
            signal: WhaleTradeSignal from RealTimeWhaleMonitor

        Returns:
            Trade result dict if copied, None otherwise
        """
        from research.real_time_whale_monitor import WhaleTradeSignal

        if not isinstance(signal, WhaleTradeSignal):
            logger.warning("invalid_signal_type", type=type(signal))
            return None

        self.stats["signals_processed"] += 1

        trader = signal.trader_address.lower()
        if trader not in self.tracked_whales:
            return None

        if not self.is_quality_whale(trader):
            logger.debug(
                "whale_not_quality_skipping",
                whale=trader[:10],
                delay_ms=signal.delay_ms,
            )
            return None

        logger.info(
            "whale_signal_from_monitor",
            signal_id=signal.signal_id[:8]
            if hasattr(signal, "signal_id")
            else "unknown",
            whale=trader[:10],
            side=signal.side,
            size=str(signal.size_usd),
            price=str(signal.price),
            delay_ms=signal.delay_ms,
            market=signal.market_id[:20],
        )

        copy_size = self._calculate_copy_size_from_signal(signal)
        if copy_size == Decimal("0"):
            logger.info("signal_size_too_small", size=str(signal.size_usd))
            return None

        can_trade, reason = self.risk_manager.can_trade(
            market_id=signal.market_id, size=float(copy_size), strategy="copy"
        )
        if not can_trade:
            logger.info("risk_check_failed", reason=reason)
            return None

        logger.info(
            "executing_copy_trade_from_signal",
            side=signal.side,
            size=str(copy_size),
            market=signal.market_id[:20],
            mode=self.mode,
        )

        if self.mode == "paper":
            result = await self._execute_paper_trade(
                market_id=signal.market_id,
                side=signal.side,
                size=copy_size,
                price=signal.price,
                strategy="copy",
                whale_address=trader,
            )
        else:
            result = await self._execute_live_trade(
                market_id=signal.market_id,
                side=signal.side,
                size=copy_size,
                price=signal.price,
            )

        if result.get("success"):
            self.stats["trades_executed"] += 1

            fill_price = signal.price
            whale_risk_score = self.get_whale_risk_score(trader)
            self.positions[signal.market_id] = CopyPosition(
                market_id=signal.market_id,
                entry_price=fill_price,
                size=copy_size,
                whale_address=trader,
                whale_risk_score=whale_risk_score,
                entry_time=asyncio.get_event_loop().time(),
            )

            logger.info(
                "copy_trade_executed_from_signal",
                signal_id=signal.signal_id[:8]
                if hasattr(signal, "signal_id")
                else "unknown",
                fill_price=str(fill_price),
                size=str(copy_size),
                delay_ms=signal.delay_ms,
            )

        return result

    def _calculate_copy_size_from_signal(self, signal: Any) -> Decimal:
        """Calculate copy size from whale trade signal.

        Args:
            signal: WhaleTradeSignal

        Returns:
            Calculated copy size
        """
        from research.real_time_whale_monitor import WhaleTradeSignal

        if not isinstance(signal, WhaleTradeSignal):
            return Decimal("0")

        bankroll = Decimal(str(self.config.get("copy_capital", Decimal("70.0"))))

        whale_stats = self.whale_stats.get(signal.trader_address.lower())
        if not whale_stats:
            min_fraction = Decimal("0.01")
            max_fraction = Decimal("0.05")
            return bankroll * Decimal("0.02")

        win_probability = whale_stats.win_rate
        if win_probability <= Decimal("0"):
            return Decimal("0")

        payout_ratio = (
            Decimal("1") / signal.price if signal.price > Decimal("0") else Decimal("1")
        )
        p = win_probability
        q = Decimal("1") - p
        b = payout_ratio - Decimal("1")

        if b <= Decimal("0"):
            return bankroll * Decimal("0.02")

        kelly_fraction = (b * p - q) / b

        if kelly_fraction <= Decimal("0"):
            return Decimal("0")

        quarter_kelly = kelly_fraction * Decimal("0.25")

        min_fraction = Decimal("0.01")
        max_fraction = Decimal("0.05")

        final_fraction = max(min_fraction, min(quarter_kelly, max_fraction))

        kelly_size = bankroll * final_fraction

        max_size = bankroll * max_fraction

        return min(kelly_size, max_size)

    def get_positions(self) -> Dict[str, CopyPosition]:
        """Get current copy positions.

        Returns:
            Dict mapping market_id to CopyPosition
        """
        return self.positions.copy()

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics.

        Returns:
            Dict with engine statistics including:
                - tracked_whales: Count of tracked whales
                - open_positions: Count of open positions
                - total_exposure: Total USD exposure
                - unrealized_pnl: Unrealized PnL
                - total_pnl: Realized PnL
        """
        total_exposure = sum(p.size for p in self.positions.values())

        return {
            "tracked_whales": len(self.tracked_whales),
            "open_positions": len(self.positions),
            "total_exposure": str(total_exposure),
            "unrealized_pnl": str(sum(p.pnl for p in self.positions.values())),
            "total_pnl": str(self.stats["total_pnl"]),
            "signals_processed": self.stats["signals_processed"],
            "trades_executed": self.stats["trades_executed"],
            "positions_closed": self.stats["positions_closed"],
        }

    async def integrate_whale_detector(self, detector: Any) -> None:
        """Integrate with WhaleDetector for automatic whale detection.

        Args:
            detector: WhaleDetector instance
        """
        from research.whale_detector import WhaleDetector

        if not isinstance(detector, WhaleDetector):
            logger.warning("invalid_detector_type")
            return

        async def on_whale_detected(whale: Any) -> None:
            from research.whale_detector import DetectedWhale

            if isinstance(whale, DetectedWhale):
                address = whale.wallet_address.lower()
                self.tracked_whales.add(address)

                from research.whale_tracker import WhaleStats

                self.whale_stats[address] = WhaleStats(
                    wallet_address=address,
                    total_trades=whale.total_trades,
                    win_rate=whale.win_rate,
                    avg_trade_size_usd=whale.avg_trade_size,
                    risk_score=whale.risk_score,
                )

                logger.info(
                    "whale_detector_integrated",
                    address=address[:10],
                    risk_score=whale.risk_score,
                    is_quality=whale.is_quality,
                )

        detector.on_whale_detected = on_whale_detected
        logger.info("whale_detector_integration_complete")

    def get_quality_whale_addresses(self) -> List[str]:
        """Get addresses of quality whales currently tracked.

        Returns:
            List of quality whale addresses
        """
        quality_addresses = []
        for address in self.tracked_whales:
            if self.is_quality_whale(address):
                quality_addresses.append(address)
        return quality_addresses

    def _get_clob_abi(self) -> list[Dict[str, Any]]:
        """Get simplified CLOB ABI for transaction decoding.

        Returns:
            ABI fragment for createOrder and fillOrder functions
        """
        return [
            {
                "name": "createOrder",
                "type": "function",
                "inputs": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "side", "type": "uint8"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "price", "type": "uint256"},
                ],
            },
            {
                "name": "fillOrder",
                "type": "function",
                "inputs": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "side", "type": "uint8"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "price", "type": "uint256"},
                ],
            },
        ]
