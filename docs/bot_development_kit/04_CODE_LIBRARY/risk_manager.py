"""
Unified Risk Manager

Central risk control for both Copy Trading and Arbitrage strategies.
Includes kill switch, position limits, and gas management.

Sources:
- hodlwarden/polymarket-arbitrage-copy-bot (kill switch patterns)
- Various analyses (position sizing, gas optimization)

Usage:
    from risk_manager import RiskManager, RiskLimits

    limits = RiskLimits(
        max_daily_loss=10.0,
        copy_max_position=20.0,
        arb_max_position=5.0
    )

    risk_manager = RiskManager(limits)

    # Check if trade allowed
    can_trade, reason = risk_manager.can_trade(
        market_id="0x...",
        size=10.0,
        strategy="copy"
    )

    if can_trade:
        # Execute trade
        result = await execute(...)
        risk_manager.record_trade("copy", result["pnl"])
"""

import time
from dataclasses import dataclass, field
from typing import Tuple, Dict, Optional, Any, Callable
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class Strategy(Enum):
    """Trading strategies"""
    COPY = "copy"
    ARBITRAGE = "arbitrage"


@dataclass
class RiskLimits:
    """
    Risk limit configuration

    Default values tuned for $100 total capital:
    - Copy Trading: $70 (70%)
    - Arbitrage: $25 (25%)
    - Gas Reserve: $5 (5%)
    """
    # Global limits
    max_daily_loss: float = 10.0           # $10 total daily loss
    max_total_exposure: float = 80.0       # $80 max deployed
    max_gas_gwei: float = 50.0             # Pause if gas > 50 gwei

    # Copy Trading limits ($70 reserve)
    copy_capital: float = 70.0
    copy_max_position: float = 20.0        # $20 per market
    copy_max_exposure: float = 56.0        # $56 max (80% of $70)
    copy_max_daily_loss: float = 7.0       # $7 daily loss
    copy_max_consecutive_losses: int = 3

    # Arbitrage limits ($25 reserve)
    arb_capital: float = 25.0
    arb_max_position: float = 5.0          # $5 per trade
    arb_max_exposure: float = 15.0         # $15 max
    arb_max_daily_loss: float = 3.0        # $3 daily loss
    arb_max_failed_trades: int = 5

    # Gas reserve
    gas_reserve: float = 5.0               # $5 for gas


@dataclass
class Position:
    """Represents an open position"""
    market_id: str
    strategy: str
    size: float
    entry_price: float
    entry_time: int
    unrealized_pnl: float = 0.0


class RiskManager:
    """
    Unified Risk Manager

    Handles risk control for both Copy Trading and Arbitrage strategies.
    Features:
    - Kill switch (daily loss, consecutive losses)
    - Position limits (per-market, total exposure)
    - Gas management
    - Real-time PnL tracking
    """

    def __init__(
        self,
        limits: Optional[RiskLimits] = None,
        on_kill_switch: Optional[Callable[[str], None]] = None
    ):
        """
        Initialize Risk Manager

        Args:
            limits: RiskLimits configuration
            on_kill_switch: Callback when kill switch triggers
        """
        self.limits = limits or RiskLimits()
        self.on_kill_switch = on_kill_switch

        # State tracking
        self.positions: Dict[str, Position] = {}
        self.daily_pnl: Dict[str, float] = {
            "copy": 0.0,
            "arbitrage": 0.0
        }
        self.consecutive_losses: Dict[str, int] = {
            "copy": 0,
            "arbitrage": 0
        }
        self.trade_count: Dict[str, int] = {
            "copy": 0,
            "arbitrage": 0
        }
        self.failed_trades: Dict[str, int] = {
            "copy": 0,
            "arbitrage": 0
        }

        # Kill switch state
        self.is_active = True
        self.kill_reason: Optional[str] = None
        self.kill_time: Optional[int] = None

        # Daily reset tracking
        self.last_reset_day: int = self._get_current_day()

        logger.info("RiskManager initialized")

    # ==================== Trade Authorization ====================

    def can_trade(
        self,
        market_id: str,
        size: float,
        strategy: str,
        current_gas_gwei: float = 30.0
    ) -> Tuple[bool, str]:
        """
        Check if a trade is allowed by risk rules

        Args:
            market_id: Market/token ID
            size: Trade size in USD
            strategy: "copy" or "arbitrage"
            current_gas_gwei: Current gas price

        Returns:
            (can_trade, reason) tuple
        """
        # Check daily reset
        self._check_daily_reset()

        # Global kill switch
        if not self.is_active:
            return False, f"Kill switch active: {self.kill_reason}"

        # Gas check
        if current_gas_gwei > self.limits.max_gas_gwei:
            return False, f"Gas too high: {current_gas_gwei:.1f} gwei > {self.limits.max_gas_gwei}"

        # Strategy-specific checks
        if strategy == "copy":
            return self._check_copy_limits(market_id, size)
        elif strategy == "arbitrage":
            return self._check_arb_limits(market_id, size)

        return False, f"Unknown strategy: {strategy}"

    def _check_copy_limits(self, market_id: str, size: float) -> Tuple[bool, str]:
        """Check copy trading specific limits"""

        # Daily loss check
        if self.daily_pnl["copy"] < -self.limits.copy_max_daily_loss:
            return False, f"Copy daily loss limit: ${abs(self.daily_pnl['copy']):.2f}"

        # Consecutive loss check
        if self.consecutive_losses["copy"] >= self.limits.copy_max_consecutive_losses:
            return False, f"Copy consecutive losses: {self.consecutive_losses['copy']}"

        # Position limit check
        current_pos = self._get_position_size(market_id, "copy")
        if current_pos + size > self.limits.copy_max_position:
            return False, f"Copy position limit: ${current_pos + size:.2f} > ${self.limits.copy_max_position}"

        # Total exposure check
        copy_exposure = self._get_strategy_exposure("copy")
        if copy_exposure + size > self.limits.copy_max_exposure:
            return False, f"Copy exposure limit: ${copy_exposure + size:.2f} > ${self.limits.copy_max_exposure}"

        return True, "OK"

    def _check_arb_limits(self, market_id: str, size: float) -> Tuple[bool, str]:
        """Check arbitrage specific limits"""

        # Daily loss check
        if self.daily_pnl["arbitrage"] < -self.limits.arb_max_daily_loss:
            return False, f"Arb daily loss limit: ${abs(self.daily_pnl['arbitrage']):.2f}"

        # Failed trades check
        if self.failed_trades["arbitrage"] >= self.limits.arb_max_failed_trades:
            return False, f"Arb failed trades: {self.failed_trades['arbitrage']}"

        # Position limit check
        if size > self.limits.arb_max_position:
            return False, f"Arb position limit: ${size:.2f} > ${self.limits.arb_max_position}"

        # Total exposure check
        arb_exposure = self._get_strategy_exposure("arbitrage")
        if arb_exposure + size > self.limits.arb_max_exposure:
            return False, f"Arb exposure limit: ${arb_exposure + size:.2f} > ${self.limits.arb_max_exposure}"

        return True, "OK"

    # ==================== Trade Recording ====================

    def record_trade(
        self,
        strategy: str,
        pnl: float,
        market_id: Optional[str] = None,
        success: bool = True
    ):
        """
        Record a completed trade and update state

        Args:
            strategy: "copy" or "arbitrage"
            pnl: Profit/loss from trade
            market_id: Optional market ID for position tracking
            success: Whether trade executed successfully
        """
        # Update PnL
        self.daily_pnl[strategy] += pnl
        self.trade_count[strategy] += 1

        # Track consecutive losses
        if pnl < 0:
            self.consecutive_losses[strategy] += 1
        else:
            self.consecutive_losses[strategy] = 0

        # Track failed trades
        if not success:
            self.failed_trades[strategy] += 1
        else:
            self.failed_trades[strategy] = 0

        # Log trade
        logger.info(
            f"Trade recorded [{strategy}]: PnL=${pnl:.2f}, "
            f"Daily=${self.daily_pnl[strategy]:.2f}, "
            f"Consecutive losses={self.consecutive_losses[strategy]}"
        )

        # Check kill conditions
        self._check_kill_conditions(strategy)

    def _check_kill_conditions(self, strategy: str):
        """Check if kill switch should trigger"""

        # Total daily loss
        total_daily = sum(self.daily_pnl.values())
        if total_daily < -self.limits.max_daily_loss:
            self.trigger_kill_switch(f"Total daily loss: ${abs(total_daily):.2f}")
            return

        # Strategy-specific
        if strategy == "copy":
            if self.daily_pnl["copy"] < -self.limits.copy_max_daily_loss:
                self.trigger_kill_switch(f"Copy daily loss: ${abs(self.daily_pnl['copy']):.2f}")
            elif self.consecutive_losses["copy"] >= self.limits.copy_max_consecutive_losses:
                self.trigger_kill_switch(f"Copy {self.consecutive_losses['copy']} consecutive losses")

        elif strategy == "arbitrage":
            if self.daily_pnl["arbitrage"] < -self.limits.arb_max_daily_loss:
                self.trigger_kill_switch(f"Arb daily loss: ${abs(self.daily_pnl['arbitrage']):.2f}")
            elif self.failed_trades["arbitrage"] >= self.limits.arb_max_failed_trades:
                self.trigger_kill_switch(f"Arb {self.failed_trades['arbitrage']} failed trades")

    # ==================== Position Management ====================

    def add_position(
        self,
        market_id: str,
        strategy: str,
        size: float,
        entry_price: float
    ):
        """Add a new position"""
        key = f"{strategy}:{market_id}"
        self.positions[key] = Position(
            market_id=market_id,
            strategy=strategy,
            size=size,
            entry_price=entry_price,
            entry_time=int(time.time())
        )

    def remove_position(self, market_id: str, strategy: str):
        """Remove a position"""
        key = f"{strategy}:{market_id}"
        if key in self.positions:
            del self.positions[key]

    def update_position_pnl(self, market_id: str, strategy: str, current_price: float):
        """Update unrealized PnL for a position"""
        key = f"{strategy}:{market_id}"
        pos = self.positions.get(key)
        if pos:
            pos.unrealized_pnl = (current_price - pos.entry_price) * pos.size

    def _get_position_size(self, market_id: str, strategy: str) -> float:
        """Get current position size for a market"""
        key = f"{strategy}:{market_id}"
        pos = self.positions.get(key)
        return pos.size if pos else 0.0

    def _get_strategy_exposure(self, strategy: str) -> float:
        """Get total exposure for a strategy"""
        return sum(
            p.size for p in self.positions.values()
            if p.strategy == strategy
        )

    # ==================== Kill Switch ====================

    def trigger_kill_switch(self, reason: str):
        """
        Trigger the kill switch

        Args:
            reason: Reason for triggering
        """
        if not self.is_active:
            return  # Already triggered

        self.is_active = False
        self.kill_reason = reason
        self.kill_time = int(time.time())

        logger.warning(f"KILL SWITCH TRIGGERED: {reason}")

        # Call callback if set
        if self.on_kill_switch:
            try:
                self.on_kill_switch(reason)
            except Exception as e:
                logger.error(f"Kill switch callback error: {e}")

    def reset_kill_switch(self, force: bool = False):
        """
        Reset the kill switch

        Args:
            force: Force reset even if conditions not met
        """
        if force or self._can_auto_reset():
            self.is_active = True
            self.kill_reason = None
            self.kill_time = None
            logger.info("Kill switch reset")
        else:
            logger.warning("Cannot reset kill switch - conditions not met")

    def _can_auto_reset(self) -> bool:
        """Check if kill switch can auto-reset"""
        # Auto-reset on daily reset if reason was daily-related
        if self.kill_reason and "daily" in self.kill_reason.lower():
            return True
        return False

    # ==================== Daily Reset ====================

    def _check_daily_reset(self):
        """Check if daily counters should reset"""
        current_day = self._get_current_day()
        if current_day != self.last_reset_day:
            self._reset_daily()
            self.last_reset_day = current_day

    def _reset_daily(self):
        """Reset daily counters"""
        logger.info("Daily reset triggered")

        self.daily_pnl = {"copy": 0.0, "arbitrage": 0.0}
        self.consecutive_losses = {"copy": 0, "arbitrage": 0}
        self.failed_trades = {"copy": 0, "arbitrage": 0}
        self.trade_count = {"copy": 0, "arbitrage": 0}

        # Auto-reset kill switch if daily-related
        if self._can_auto_reset():
            self.reset_kill_switch()

    def _get_current_day(self) -> int:
        """Get current day as integer (for comparison)"""
        return int(time.time() // 86400)

    # ==================== Statistics ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get risk manager statistics"""
        return {
            "is_active": self.is_active,
            "kill_reason": self.kill_reason,
            "daily_pnl": self.daily_pnl.copy(),
            "trade_count": self.trade_count.copy(),
            "consecutive_losses": self.consecutive_losses.copy(),
            "positions": len(self.positions),
            "copy_exposure": self._get_strategy_exposure("copy"),
            "arb_exposure": self._get_strategy_exposure("arbitrage"),
            "total_exposure": sum(p.size for p in self.positions.values())
        }

    def get_positions(self) -> Dict[str, Position]:
        """Get all open positions"""
        return self.positions.copy()

    def get_daily_summary(self) -> Dict[str, Any]:
        """Get daily trading summary"""
        return {
            "date": time.strftime("%Y-%m-%d"),
            "copy": {
                "trades": self.trade_count["copy"],
                "pnl": self.daily_pnl["copy"],
                "exposure": self._get_strategy_exposure("copy")
            },
            "arbitrage": {
                "trades": self.trade_count["arbitrage"],
                "pnl": self.daily_pnl["arbitrage"],
                "exposure": self._get_strategy_exposure("arbitrage")
            },
            "total_pnl": sum(self.daily_pnl.values()),
            "kill_switch": not self.is_active
        }


# ==================== Example Usage ====================

def example():
    """Example usage of RiskManager"""

    def on_kill(reason):
        print(f"ALERT: Kill switch triggered - {reason}")

    limits = RiskLimits(
        max_daily_loss=10.0,
        copy_max_position=20.0,
        copy_max_daily_loss=7.0
    )

    risk = RiskManager(limits=limits, on_kill_switch=on_kill)

    # Test trade authorization
    can, reason = risk.can_trade("0x123", 10.0, "copy")
    print(f"Can trade: {can} ({reason})")

    # Simulate some trades
    risk.record_trade("copy", 0.50)   # Win
    risk.record_trade("copy", -0.30)  # Loss
    risk.record_trade("copy", 0.80)   # Win

    print(f"\nStats: {risk.get_stats()}")
    print(f"Daily summary: {risk.get_daily_summary()}")

    # Simulate consecutive losses
    print("\nSimulating consecutive losses...")
    for i in range(4):
        risk.record_trade("copy", -2.0)
        print(f"  Trade {i+1}: PnL=-$2, Kill active: {not risk.is_active}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    example()
