"""
Copy Trading Engine - Whale Following Strategy

Monitors whale addresses and copies their trades with proportional sizing.

Sources:
- crypmancer/polymarket-arbitrage-copy-bot (block-based following)
- hodlwarden/polymarket-arbitrage-copy-bot (mempool monitoring)

Usage:
    from copy_trading_engine import CopyTradingEngine

    engine = CopyTradingEngine(
        config={
            "whale_addresses": ["0x123...", "0x456..."],
            "copy_capital": 70.0,
            "min_copy_size": 5.0,
            "max_copy_size": 20.0
        },
        risk_manager=risk_manager,
        executor=executor
    )

    # Process whale transaction
    result = await engine.process_transaction(tx_data)
"""

import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Set, Any, List
from web3 import Web3
import logging

logger = logging.getLogger(__name__)


@dataclass
class WhaleSignal:
    """Represents a detected whale trade signal"""
    address: str
    market_id: str
    side: str  # "BUY" or "SELL"
    amount: float
    price: float
    tx_hash: str
    block_number: int
    is_opening: bool  # True if opening position, False if closing


@dataclass
class CopyPosition:
    """Tracks a copied position"""
    market_id: str
    entry_price: float
    size: float
    whale_address: str
    entry_time: int
    pnl: float = 0.0


class CopyTradingEngine:
    """
    Copy Trading Engine

    Monitors whale addresses and replicates their trades with
    proportional sizing based on conviction level.
    """

    # Polymarket CLOB contract (Polygon)
    CLOB_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

    def __init__(
        self,
        config: Dict[str, Any],
        risk_manager: Any,
        executor: Any,
        w3: Optional[Web3] = None
    ):
        """
        Initialize Copy Trading Engine

        Args:
            config: Configuration dictionary with:
                - whale_addresses: List of addresses to follow
                - whale_balances: Dict of estimated whale balances
                - copy_capital: Capital allocated for copy trading ($)
                - min_copy_size: Minimum trade size ($)
                - max_copy_size: Maximum trade size ($)
            risk_manager: RiskManager instance
            executor: OrderExecutor instance
            w3: Optional Web3 instance
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
        self.whale_positions: Dict[str, Dict[str, Dict]] = {}
        # Format: {whale_address: {market_id: {"side": "BUY", "size": 100}}}

        # Our positions (copied from whales)
        self.positions: Dict[str, CopyPosition] = {}

        # CLOB ABI (simplified - add full ABI in production)
        self.clob_abi = self._get_clob_abi()

        logger.info(f"CopyTradingEngine initialized, tracking {len(self.tracked_whales)} whales")

    async def process_transaction(self, tx: Dict) -> Optional[Dict]:
        """
        Process a blockchain transaction and decide whether to copy

        Args:
            tx: Transaction dict with 'from', 'to', 'input', etc.

        Returns:
            Trade result dict or None if not copied
        """
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
            logger.debug(f"Could not decode trade from {sender[:10]}...")
            return None

        logger.info(
            f"Whale signal: {signal.address[:10]}... {signal.side} "
            f"${signal.amount:.2f} @ {signal.price:.3f}"
        )

        # Determine if opening or closing
        signal.is_opening = self._is_opening_trade(signal)

        if not signal.is_opening:
            # Whale is closing - check if we should exit too
            return await self._handle_whale_exit(signal)

        # Calculate copy size
        copy_size = self._calculate_copy_size(signal)
        if copy_size == 0:
            logger.info(f"Trade too small to copy: ${signal.amount:.2f}")
            return None

        # Risk check
        can_trade, reason = self.risk_manager.can_trade(
            market_id=signal.market_id,
            size=copy_size,
            strategy="copy"
        )
        if not can_trade:
            logger.info(f"Risk check failed: {reason}")
            return None

        # Execute copy trade
        logger.info(f"Copying: {signal.side} ${copy_size:.2f} on {signal.market_id[:20]}...")

        result = await self.executor.execute(
            market_id=signal.market_id,
            side=signal.side,
            size=copy_size,
            price=signal.price,
            mode="rest"  # Copy trading uses REST (latency less critical)
        )

        if result.get("success"):
            # Track our position
            self.positions[signal.market_id] = CopyPosition(
                market_id=signal.market_id,
                entry_price=result.get("fill_price", signal.price),
                size=copy_size,
                whale_address=signal.address,
                entry_time=int(asyncio.get_event_loop().time())
            )

            # Update whale position tracking
            self._update_whale_position(signal)

            logger.info(f"Copy trade executed: {result}")

        return result

    def _decode_trade(self, tx: Dict, sender: str) -> Optional[WhaleSignal]:
        """
        Decode Polymarket CLOB transaction

        Args:
            tx: Transaction data
            sender: Whale address

        Returns:
            WhaleSignal or None if decode fails
        """
        if not self.w3:
            logger.warning("Web3 not configured, cannot decode transactions")
            return None

        try:
            tx_input = tx.get("input", "")
            if not tx_input or tx_input == "0x":
                return None

            # Decode function call
            contract = self.w3.eth.contract(
                address=self.CLOB_ADDRESS,
                abi=self.clob_abi
            )

            func, params = contract.decode_function_input(tx_input)
            func_name = func.fn_name

            # Parse based on function type
            if "createOrder" in func_name or "fillOrder" in func_name:
                return WhaleSignal(
                    address=sender,
                    market_id=str(params.get("tokenId", "")),
                    side="BUY" if params.get("side", 0) == 0 else "SELL",
                    amount=float(params.get("amount", 0)) / 1e6,
                    price=float(params.get("price", 0)) / 1e6,
                    tx_hash=tx.get("hash", ""),
                    block_number=tx.get("blockNumber", 0),
                    is_opening=True
                )

        except Exception as e:
            logger.debug(f"Decode error: {e}")

        return None

    def _is_opening_trade(self, signal: WhaleSignal) -> bool:
        """
        Determine if whale is opening or closing a position

        Returns True if:
        - Whale has no existing position in this market
        - Whale is adding to existing position (same side)

        Returns False if:
        - Whale is reducing/closing position (opposite side)
        """
        whale_pos = self.whale_positions.get(signal.address, {})
        existing = whale_pos.get(signal.market_id)

        if existing is None:
            return True  # New position

        if existing["side"] == signal.side:
            return True  # Adding to position

        return False  # Closing/reducing position

    def _calculate_copy_size(self, signal: WhaleSignal) -> float:
        """
        Calculate proportional copy size based on whale conviction

        Formula:
        conviction = whale_trade_size / whale_estimated_balance
        copy_size = my_balance * conviction

        Example:
        - Whale balance: $100,000, trades $5,000 (5% conviction)
        - My balance: $70 → copy $3.50 (5% conviction)
        """
        # Get whale's estimated balance
        whale_balances = self.config.get("whale_balances", {})
        whale_balance = whale_balances.get(
            signal.address,
            100000  # Default estimate if unknown
        )

        # Calculate conviction ratio
        conviction = signal.amount / whale_balance

        # Apply to our capital
        my_balance = self.config.get("copy_capital", 70.0)
        base_size = my_balance * conviction

        # Apply limits
        min_size = self.config.get("min_copy_size", 5.0)
        max_size = self.config.get("max_copy_size", 20.0)

        if base_size < min_size:
            return 0  # Too small

        return min(base_size, max_size)

    async def _handle_whale_exit(self, signal: WhaleSignal) -> Optional[Dict]:
        """
        Handle whale exiting a position - close our position too

        Args:
            signal: The whale's exit signal

        Returns:
            Exit trade result or None
        """
        our_position = self.positions.get(signal.market_id)
        if not our_position:
            return None  # We don't have this position

        # Only exit if we followed this whale
        if our_position.whale_address != signal.address:
            return None

        logger.info(f"Whale exiting, closing our position: {signal.market_id[:20]}...")

        # Opposite side to close
        exit_side = "SELL" if signal.side == "BUY" else "BUY"

        result = await self.executor.execute(
            market_id=signal.market_id,
            side=exit_side,
            size=our_position.size,
            price=signal.price,  # Use whale's exit price
            mode="rest"
        )

        if result.get("success"):
            # Calculate PnL
            entry = our_position.entry_price
            exit_price = result.get("fill_price", signal.price)

            if our_position.size > 0:  # Was long
                pnl = (exit_price - entry) * our_position.size
            else:
                pnl = (entry - exit_price) * abs(our_position.size)

            # Record and remove position
            self.risk_manager.record_trade("copy", pnl, signal.market_id)
            del self.positions[signal.market_id]

            logger.info(f"Position closed, PnL: ${pnl:.2f}")

        return result

    def _update_whale_position(self, signal: WhaleSignal):
        """Update our tracking of whale positions"""
        if signal.address not in self.whale_positions:
            self.whale_positions[signal.address] = {}

        self.whale_positions[signal.address][signal.market_id] = {
            "side": signal.side,
            "size": signal.amount,
            "price": signal.price
        }

    def add_whale(self, address: str, estimated_balance: float = 100000):
        """Add a whale to track"""
        addr_lower = address.lower()
        self.tracked_whales.add(addr_lower)
        self.config.setdefault("whale_balances", {})[addr_lower] = estimated_balance
        logger.info(f"Added whale: {address[:10]}... (est. ${estimated_balance:,.0f})")

    def remove_whale(self, address: str):
        """Stop tracking a whale"""
        addr_lower = address.lower()
        self.tracked_whales.discard(addr_lower)
        logger.info(f"Removed whale: {address[:10]}...")

    def get_tracked_whales(self) -> List[str]:
        """Get list of tracked whale addresses"""
        return list(self.tracked_whales)

    def get_positions(self) -> Dict[str, CopyPosition]:
        """Get current copy positions"""
        return self.positions.copy()

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics"""
        total_exposure = sum(p.size for p in self.positions.values())
        total_pnl = sum(p.pnl for p in self.positions.values())

        return {
            "tracked_whales": len(self.tracked_whales),
            "open_positions": len(self.positions),
            "total_exposure": total_exposure,
            "unrealized_pnl": total_pnl
        }

    def _get_clob_abi(self) -> List[Dict]:
        """Get simplified CLOB ABI for decoding"""
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


# ==================== Example Usage ====================

async def example():
    """Example usage of CopyTradingEngine"""
    from unittest.mock import MagicMock

    # Mock dependencies
    mock_risk = MagicMock()
    mock_risk.can_trade.return_value = (True, "OK")

    mock_executor = MagicMock()
    mock_executor.execute = MagicMock(return_value={"success": True, "fill_price": 0.55})

    config = {
        "whale_addresses": [
            "0x1234567890abcdef1234567890abcdef12345678",
            "0xabcdef1234567890abcdef1234567890abcdef12"
        ],
        "whale_balances": {
            "0x1234567890abcdef1234567890abcdef12345678": 100000,
            "0xabcdef1234567890abcdef1234567890abcdef12": 50000
        },
        "copy_capital": 70.0,
        "min_copy_size": 5.0,
        "max_copy_size": 20.0
    }

    engine = CopyTradingEngine(
        config=config,
        risk_manager=mock_risk,
        executor=mock_executor
    )

    print(f"Tracking {len(engine.get_tracked_whales())} whales")
    print(f"Stats: {engine.get_stats()}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example())
