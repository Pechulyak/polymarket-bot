"""
Arbitrage Detector - Cross-Platform Opportunity Scanner

Detects price discrepancies between Polymarket and Manifold.

Sources:
- realfishsam/prediction-market-arbitrage-bot (cross-platform logic)
- CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot (exchange interface)

Usage:
    from arbitrage_detector import ArbitrageDetector

    detector = ArbitrageDetector(
        market_pairs=[
            {"name": "Trump 2024", "poly_id": "0x...", "manifold_id": "trump-2024"}
        ],
        min_spread=0.03  # 3% minimum
    )

    # Update prices from feeds
    detector.update_poly_price("0x...", 0.55, 0.56)
    detector.update_manifold_price("trump-2024", 0.60)

    # Scan for opportunities
    opportunities = detector.scan()
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ArbOpportunity:
    """Represents an arbitrage opportunity"""
    pair_name: str
    direction: str  # "BUY_POLY_SELL_MANIFOLD" or "BUY_MANIFOLD_SELL_POLY"
    poly_market_id: str
    manifold_market_id: str
    poly_price: float
    manifold_price: float
    spread: float
    net_spread: float  # After fees
    recommended_size: float
    expected_profit: float
    timestamp: int = field(default_factory=lambda: int(time.time()))

    @property
    def is_profitable(self) -> bool:
        return self.net_spread > 0

    def __repr__(self):
        return (
            f"ArbOpportunity({self.pair_name}: {self.direction}, "
            f"spread={self.net_spread:.2%}, profit=${self.expected_profit:.2f})"
        )


@dataclass
class MarketPair:
    """Configuration for a cross-platform market pair"""
    name: str
    poly_id: str
    manifold_id: str
    category: str = "general"
    active: bool = True


@dataclass
class PriceState:
    """Current price state for a market"""
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    timestamp: int = 0

    @property
    def is_fresh(self) -> bool:
        """Check if price is less than 10 seconds old"""
        return time.time() - self.timestamp < 10


class ArbitrageDetector:
    """
    Cross-Platform Arbitrage Detector

    Monitors price differences between Polymarket and Manifold
    to identify profitable arbitrage opportunities.
    """

    # Fee estimates
    POLY_MAKER_FEE = 0.02  # ~2%
    POLY_TAKER_FEE = 0.02  # ~2%
    MANIFOLD_FEE = 0.00    # Usually 0%

    def __init__(
        self,
        market_pairs: List[Dict[str, str]],
        min_spread: float = 0.03,
        max_trade_size: float = 5.0,
        capital: float = 25.0
    ):
        """
        Initialize Arbitrage Detector

        Args:
            market_pairs: List of market pair configs
            min_spread: Minimum spread to consider (after fees)
            max_trade_size: Maximum trade size per opportunity
            capital: Total capital allocated for arbitrage
        """
        self.min_spread = min_spread
        self.max_trade_size = max_trade_size
        self.capital = capital

        # Parse market pairs
        self.pairs: Dict[str, MarketPair] = {}
        for pair in market_pairs:
            mp = MarketPair(
                name=pair["name"],
                poly_id=pair["poly_id"],
                manifold_id=pair["manifold_id"],
                category=pair.get("category", "general")
            )
            self.pairs[pair["name"]] = mp

        # Price state tracking
        self.poly_prices: Dict[str, PriceState] = {}
        self.manifold_prices: Dict[str, PriceState] = {}

        # Statistics
        self.opportunities_found = 0
        self.last_scan_time = 0

        logger.info(f"ArbitrageDetector initialized with {len(self.pairs)} pairs")

    # ==================== Price Updates ====================

    def update_poly_price(
        self,
        market_id: str,
        bid: Optional[float],
        ask: Optional[float]
    ):
        """
        Update Polymarket price from orderbook

        Args:
            market_id: Token ID
            bid: Best bid price
            ask: Best ask price
        """
        mid = (bid + ask) / 2 if bid and ask else None
        self.poly_prices[market_id] = PriceState(
            bid=bid,
            ask=ask,
            mid=mid,
            timestamp=int(time.time())
        )

    def update_manifold_price(self, market_id: str, probability: float):
        """
        Update Manifold price from API

        Args:
            market_id: Manifold market slug
            probability: Current probability (0-1)
        """
        # Manifold uses AMM, so bid/ask = probability (no spread)
        self.manifold_prices[market_id] = PriceState(
            bid=probability,
            ask=probability,
            mid=probability,
            timestamp=int(time.time())
        )

    def update_from_orderbook(self, market_id: str, orderbook: Dict):
        """
        Update from orderbook data structure

        Args:
            market_id: Token ID
            orderbook: Dict with "bids" and "asks" lists
        """
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        best_bid = bids[0]["price"] if bids else None
        best_ask = asks[0]["price"] if asks else None

        self.update_poly_price(market_id, best_bid, best_ask)

    # ==================== Opportunity Detection ====================

    def scan(self) -> List[ArbOpportunity]:
        """
        Scan all pairs for arbitrage opportunities

        Returns:
            List of opportunities sorted by expected profit
        """
        opportunities = []
        self.last_scan_time = time.time()

        for name, pair in self.pairs.items():
            if not pair.active:
                continue

            opp = self._check_pair(pair)
            if opp and opp.is_profitable:
                opportunities.append(opp)

        # Sort by expected profit (descending)
        opportunities.sort(key=lambda x: -x.expected_profit)

        if opportunities:
            self.opportunities_found += len(opportunities)
            logger.info(f"Found {len(opportunities)} arbitrage opportunities")

        return opportunities

    def _check_pair(self, pair: MarketPair) -> Optional[ArbOpportunity]:
        """
        Check single pair for arbitrage

        Args:
            pair: MarketPair to check

        Returns:
            ArbOpportunity if found, None otherwise
        """
        poly_state = self.poly_prices.get(pair.poly_id)
        manifold_state = self.manifold_prices.get(pair.manifold_id)

        # Check we have fresh prices
        if not poly_state or not poly_state.is_fresh:
            return None
        if not manifold_state or not manifold_state.is_fresh:
            return None

        # Check we have valid prices
        if poly_state.ask is None or poly_state.bid is None:
            return None
        if manifold_state.mid is None:
            return None

        # Direction A: Buy on Poly (at ask), Sell on Manifold (at bid)
        gross_spread_a = manifold_state.mid - poly_state.ask
        fees_a = self._estimate_fees(poly_state.ask, manifold_state.mid)
        net_spread_a = gross_spread_a - fees_a

        # Direction B: Buy on Manifold (at ask), Sell on Poly (at bid)
        gross_spread_b = poly_state.bid - manifold_state.mid
        fees_b = self._estimate_fees(poly_state.bid, manifold_state.mid)
        net_spread_b = gross_spread_b - fees_b

        # Check Direction A
        if net_spread_a > self.min_spread:
            size = self._calculate_size(net_spread_a)
            return ArbOpportunity(
                pair_name=pair.name,
                direction="BUY_POLY_SELL_MANIFOLD",
                poly_market_id=pair.poly_id,
                manifold_market_id=pair.manifold_id,
                poly_price=poly_state.ask,
                manifold_price=manifold_state.mid,
                spread=gross_spread_a,
                net_spread=net_spread_a,
                recommended_size=size,
                expected_profit=net_spread_a * size
            )

        # Check Direction B
        if net_spread_b > self.min_spread:
            size = self._calculate_size(net_spread_b)
            return ArbOpportunity(
                pair_name=pair.name,
                direction="BUY_MANIFOLD_SELL_POLY",
                poly_market_id=pair.poly_id,
                manifold_market_id=pair.manifold_id,
                poly_price=poly_state.bid,
                manifold_price=manifold_state.mid,
                spread=gross_spread_b,
                net_spread=net_spread_b,
                recommended_size=size,
                expected_profit=net_spread_b * size
            )

        return None

    def _estimate_fees(self, poly_price: float, manifold_price: float) -> float:
        """
        Estimate total fees for both legs

        Args:
            poly_price: Polymarket price
            manifold_price: Manifold price

        Returns:
            Total fee estimate as decimal
        """
        poly_fee = poly_price * self.POLY_TAKER_FEE
        manifold_fee = manifold_price * self.MANIFOLD_FEE
        return poly_fee + manifold_fee

    def _calculate_size(self, spread: float) -> float:
        """
        Calculate recommended trade size based on spread

        Larger spreads = more confidence = larger size
        """
        # Base size: 10% of capital
        base = self.capital * 0.10

        # Increase with spread (up to 20% of capital)
        if spread > 0.10:  # >10% spread
            size = self.capital * 0.20
        elif spread > 0.07:  # >7% spread
            size = self.capital * 0.15
        else:
            size = base

        return min(size, self.max_trade_size)

    # ==================== Pair Management ====================

    def add_pair(
        self,
        name: str,
        poly_id: str,
        manifold_id: str,
        category: str = "general"
    ):
        """Add a new market pair to track"""
        self.pairs[name] = MarketPair(
            name=name,
            poly_id=poly_id,
            manifold_id=manifold_id,
            category=category
        )
        logger.info(f"Added market pair: {name}")

    def remove_pair(self, name: str):
        """Remove a market pair"""
        if name in self.pairs:
            del self.pairs[name]
            logger.info(f"Removed market pair: {name}")

    def set_pair_active(self, name: str, active: bool):
        """Enable/disable a market pair"""
        if name in self.pairs:
            self.pairs[name].active = active

    def get_pairs(self) -> List[str]:
        """Get list of tracked pair names"""
        return list(self.pairs.keys())

    # ==================== Statistics ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get detector statistics"""
        active_pairs = sum(1 for p in self.pairs.values() if p.active)
        fresh_poly = sum(1 for p in self.poly_prices.values() if p.is_fresh)
        fresh_manifold = sum(1 for p in self.manifold_prices.values() if p.is_fresh)

        return {
            "total_pairs": len(self.pairs),
            "active_pairs": active_pairs,
            "fresh_poly_prices": fresh_poly,
            "fresh_manifold_prices": fresh_manifold,
            "opportunities_found": self.opportunities_found,
            "last_scan_time": self.last_scan_time,
            "min_spread": self.min_spread,
            "capital": self.capital
        }

    def get_current_spreads(self) -> Dict[str, Optional[float]]:
        """Get current spreads for all pairs"""
        spreads = {}
        for name, pair in self.pairs.items():
            poly = self.poly_prices.get(pair.poly_id)
            manifold = self.manifold_prices.get(pair.manifold_id)

            if poly and poly.mid and manifold and manifold.mid:
                spreads[name] = abs(poly.mid - manifold.mid)
            else:
                spreads[name] = None

        return spreads


# ==================== Example Usage ====================

def example():
    """Example usage of ArbitrageDetector"""

    # Configure market pairs
    pairs = [
        {
            "name": "Trump 2024",
            "poly_id": "0x123abc...",
            "manifold_id": "trump-wins-2024"
        },
        {
            "name": "BTC 100k",
            "poly_id": "0x456def...",
            "manifold_id": "bitcoin-100k-2024"
        }
    ]

    detector = ArbitrageDetector(
        market_pairs=pairs,
        min_spread=0.03,
        capital=25.0
    )

    # Simulate price updates
    detector.update_poly_price("0x123abc...", bid=0.54, ask=0.56)
    detector.update_manifold_price("trump-wins-2024", probability=0.62)

    detector.update_poly_price("0x456def...", bid=0.40, ask=0.42)
    detector.update_manifold_price("bitcoin-100k-2024", probability=0.41)

    # Scan for opportunities
    opportunities = detector.scan()

    print(f"\nFound {len(opportunities)} opportunities:")
    for opp in opportunities:
        print(f"  {opp}")

    print(f"\nStats: {detector.get_stats()}")
    print(f"Current spreads: {detector.get_current_spreads()}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    example()
