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
from typing import Any, Dict, Optional, Set, Union

import structlog
from web3 import Web3

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
        entry_time: Unix timestamp of entry
        pnl: Realized PnL (updated on exit)
        exit_price: Exit price (set on close)
        exit_time: Exit timestamp (set on close)
    """
    market_id: str
    entry_price: Decimal
    size: Decimal
    whale_address: str
    entry_time: float
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
    """

    # Polymarket CLOB contract (Polygon mainnet)
    CLOB_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

    def __init__(
        self,
        config: Dict[str, Any],
        risk_manager: Any,
        executor: Any,
        w3: Optional[Web3] = None
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
        """
        self.config = config
        self.risk_manager = risk_manager
        self.executor = executor
        self.w3 = w3

        # Tracked whales (lowercase for comparison)
        self.tracked_whales: Set[str] = set(
            addr.lower() for addr in config.get("whale_addresses", [])
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
            tracked_whales=len(self.tracked_whales),
            copy_capital=str(config.get("copy_capital", Decimal("70.0"))),
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

        # Check if from tracked whale
        sender = tx.get("from", "").lower()
        if sender not in self.tracked_whales:
            return None

        # Check if to CLOB contract
        to_addr = tx.get("to", "").lower()
        if to_addr != self.CLOB_ADDRESS.lower():
            return None

        # Decode the trade
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

        # Determine if opening or closing
        signal.is_opening = self._is_opening_trade(signal)

        if not signal.is_opening:
            # Whale is closing - check if we should exit too
            return await self._handle_whale_exit(signal)

        # Calculate copy size
        copy_size = self._calculate_copy_size(signal)
        if copy_size == Decimal("0"):
            logger.info(
                "trade_too_small",
                whale_amount=str(signal.amount),
                calculated_size=str(copy_size),
            )
            return None

        # Risk check
        can_trade, reason = self.risk_manager.can_trade(
            market_id=signal.market_id,
            size=float(copy_size),
            strategy="copy"
        )
        if not can_trade:
            logger.info(
                "risk_check_failed",
                reason=reason,
                market=signal.market_id[:20],
            )
            return None

        # Execute copy trade
        logger.info(
            "executing_copy_trade",
            side=signal.side,
            size=str(copy_size),
            market=signal.market_id[:20],
        )

        result = await self.executor.execute(
            market_id=signal.market_id,
            side=signal.side,
            size=float(copy_size),
            price=float(signal.price),
            mode="rest"  # Copy trading uses REST (latency less critical)
        )

        if result.get("success"):
            self.stats["trades_executed"] += 1
            
            # Track our position
            fill_price = Decimal(str(result.get("fill_price", signal.price)))
            self.positions[signal.market_id] = CopyPosition(
                market_id=signal.market_id,
                entry_price=fill_price,
                size=copy_size,
                whale_address=signal.address,
                entry_time=asyncio.get_event_loop().time(),
            )

            # Update whale position tracking
            self._update_whale_position(signal)

            logger.info(
                "copy_trade_executed",
                order_id=result.get("order_id"),
                fill_price=str(fill_price),
                size=str(copy_size),
            )

        return result

    def _decode_trade(
        self,
        tx: Dict[str, Any],
        sender: str
    ) -> Optional[WhaleSignal]:
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
                abi=self.clob_abi  # type: ignore
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
                    is_opening=True
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
        """Calculate proportional copy size based on whale conviction.

        Uses proportional sizing formula:
            conviction = whale_trade_size / whale_estimated_balance
            copy_size = my_balance * conviction

        Example:
            - Whale balance: $100,000, trades $5,000 (5% conviction)
            - My balance: $70 → copy $3.50 (5% conviction)

        Args:
            signal: The whale trade signal

        Returns:
            Calculated copy size in USD, or 0 if below minimum
        """
        # Get whale's estimated balance
        whale_balances = self.config.get("whale_balances", {})
        whale_balance = Decimal(str(whale_balances.get(
            signal.address,
            100000  # Default estimate if unknown
        )))

        # Calculate conviction ratio
        conviction = signal.amount / whale_balance

        # Apply to our capital
        my_balance = Decimal(str(self.config.get("copy_capital", Decimal("70.0"))))
        base_size = my_balance * conviction

        # Apply limits
        min_size = Decimal(str(self.config.get("min_copy_size", Decimal("5.0"))))
        max_size = Decimal(str(self.config.get("max_copy_size", Decimal("20.0"))))

        if base_size < min_size:
            return Decimal("0")  # Too small

        return min(base_size, max_size)

    async def _handle_whale_exit(
        self,
        signal: WhaleSignal
    ) -> Optional[Dict[str, Any]]:
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

        result = await self.executor.execute(
            market_id=signal.market_id,
            side=exit_side,
            size=float(our_position.size),
            price=float(signal.price),
            mode="rest"
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

    def add_whale(self, address: str, estimated_balance: Decimal = Decimal("100000")) -> None:
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
                    {"name": "price", "type": "uint256"}
                ]
            },
            {
                "name": "fillOrder",
                "type": "function",
                "inputs": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "side", "type": "uint8"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "price", "type": "uint256"}
                ]
            }
        ]
