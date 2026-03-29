#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Intra-market Arbitrage Scanner for Polymarket.

Scans all active binary markets to find intra-market arbitrage opportunities.
An intra-market arbitrage exists when YES_ask + NO_ask < 1.0 (i.e., the total cost
to buy both sides is less than $1, creating a guaranteed profit).

Usage:
    python scripts/arb_scanner.py

Output:
    - Formatted table of arbitrage opportunities
    - JSON file with raw results: scripts/arb_scan_results.json
"""

import asyncio
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
import structlog

logger = structlog.get_logger(__name__)

# API Endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Trading fees (approximate)
FEE_PCT = 0.4  # 0.2% per side x 2


@dataclass
class MarketOpportunity:
    """Represents an arbitrage opportunity in a single market."""
    market_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    best_yes_ask: float
    best_no_ask: float
    yes_ask_size: float
    no_ask_size: float
    total_cost: float
    spread: float
    margin_pct: float
    net_margin_pct: float
    liquidity: float


class ArbitrageScanner:
    """Scans Polymarket for intra-market arbitrage opportunities."""

    def __init__(self, rate_limit_delay: float = 0.2):
        """Initialize scanner.

        Args:
            rate_limit_delay: Delay between API requests (seconds)
        """
        self.rate_limit_delay = rate_limit_delay
        self._session: Optional[aiohttp.ClientSession] = None
        self.results: List[MarketOpportunity] = []

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                }
            )
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _fetch_with_retry(
        self, url: str, params: Optional[Dict[str, Any]] = None, max_retries: int = 3
    ) -> Optional[Dict[str, Any]]:
        """Fetch URL with retry logic."""
        session = await self._get_session()

        for attempt in range(max_retries):
            try:
                await asyncio.sleep(self.rate_limit_delay)

                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        # Rate limited - wait and retry
                        wait_time = float(resp.headers.get("Retry-After", 2))
                        logger.warning("rate_limited", wait=wait_time)
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(
                            "http_error",
                            status=resp.status,
                            url=url,
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(1)
                            continue
                        return None

            except aiohttp.ClientError as e:
                logger.warning("request_error", error=str(e), attempt=attempt + 1)
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return None

        return None

    async def get_active_markets(self) -> List[Dict[str, Any]]:
        """Get all active markets from Gamma API.

        Returns:
            List of active market dictionaries
        """
        logger.info("fetching_active_markets")

        # Use markets endpoint with closed=false to get all non-closed markets
        url = f"{GAMMA_API}/markets"
        params = {"closed": "false"}

        data = await self._fetch_with_retry(url, params=params)

        if not data:
            logger.error("failed_to_fetch_markets")
            return []

        markets = data if isinstance(data, list) else data.get("markets", [])
        logger.info("markets_fetched", count=len(markets))

        return markets

    def _is_binary_market(self, market: Dict[str, Any]) -> bool:
        """Check if market is a binary (50/50) market with orderbook enabled.

        Args:
            market: Market dictionary

        Returns:
            True if binary market with orderbook access
        """
        # Must have orderbook enabled for arbitrage
        if market.get("enableOrderBook") != True:
            return False

        # Check outcomes field
        outcomes = market.get("outcomes")
        if outcomes:
            if isinstance(outcomes, str):
                import json
                outcomes = json.loads(outcomes)
            if isinstance(outcomes, list):
                outcomes_set = {str(o).lower() for o in outcomes}
                if outcomes_set == {"yes", "no"}:
                    return True

        # Check clobTokenIds - should have 2 tokens for binary
        clob_token_ids = market.get("clobTokenIds")
        if clob_token_ids:
            if isinstance(clob_token_ids, str):
                import json
                clob_token_ids = json.loads(clob_token_ids)
            if isinstance(clob_token_ids, list) and len(clob_token_ids) == 2:
                return True

        return False

    async def get_orderbook(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Get orderbook for a token.

        Args:
            token_id: Token ID

        Returns:
            Orderbook dict with bids/asks or None on error
        """
        url = f"{CLOB_API}/book"
        params = {"token_id": token_id}

        return await self._fetch_with_retry(url, params=params)

    async def scan_market(self, market: Dict[str, Any]) -> Optional[MarketOpportunity]:
        """Scan a single market for arbitrage opportunity.

        Args:
            market: Market dictionary with tokens

        Returns:
            MarketOpportunity if arbitrage found, None otherwise
        """
        question = market.get("question", "Unknown")
        market_id = market.get("id") or market.get("conditionId", "")

        if not market_id:
            return None

        # Get clobTokenIds (list of 2 token IDs: YES, NO)
        clob_token_ids = market.get("clobTokenIds")
        if not clob_token_ids:
            return None

        # Parse if string
        if isinstance(clob_token_ids, str):
            import json
            clob_token_ids = json.loads(clob_token_ids)

        if not isinstance(clob_token_ids, list) or len(clob_token_ids) != 2:
            return None

        # clobTokenIds[0] = YES, clobTokenIds[1] = NO
        yes_token_id = clob_token_ids[0]
        no_token_id = clob_token_ids[1]

        # Fetch orderbooks concurrently
        yes_book, no_book = await asyncio.gather(
            self.get_orderbook(yes_token_id),
            self.get_orderbook(no_token_id),
        )

        # Skip if either orderbook is empty
        if not yes_book or not no_book:
            return None

        yes_asks = yes_book.get("asks", [])
        no_asks = no_book.get("asks", [])

        if not yes_asks or not no_asks:
            return None

        # Get best ask prices (lowest ask = our buy price)
        # API returns strings, convert to float
        best_yes_ask = float(yes_asks[0].get("price", 0))
        best_no_ask = float(no_asks[0].get("price", 0))
        yes_ask_size = float(yes_asks[0].get("size", 0))
        no_ask_size = float(no_asks[0].get("size", 0))

        if best_yes_ask is None or best_no_ask is None:
            return None

        # Calculate arbitrage metrics
        total_cost = best_yes_ask + best_no_ask
        spread = 1.0 - total_cost  # Positive spread = profit opportunity

        # Skip if no positive spread (no arbitrage)
        if spread <= 0:
            return None

        margin_pct = (spread / total_cost) * 100
        net_margin_pct = margin_pct - FEE_PCT

        # Liquidity is the minimum size at best ask (both sides needed)
        liquidity = min(yes_ask_size, no_ask_size)

        return MarketOpportunity(
            market_id=market_id,
            question=question,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            best_yes_ask=best_yes_ask,
            best_no_ask=best_no_ask,
            yes_ask_size=yes_ask_size,
            no_ask_size=no_ask_size,
            total_cost=total_cost,
            spread=spread,
            margin_pct=margin_pct,
            net_margin_pct=net_margin_pct,
            liquidity=liquidity,
        )

    async def scan_all_markets(self) -> List[MarketOpportunity]:
        """Scan all active markets for arbitrage opportunities.

        Returns:
            List of arbitrage opportunities found
        """
        logger.info("starting_arbitrage_scan")

        markets = await self.get_active_markets()

        # Filter to binary markets
        binary_markets = [m for m in markets if self._is_binary_market(m)]
        logger.info("binary_markets_found", count=len(binary_markets))

        opportunities: List[MarketOpportunity] = []

        for i, market in enumerate(binary_markets):
            if i % 10 == 0:
                logger.info("scan_progress", processed=i, total=len(binary_markets))

            opportunity = await self.scan_market(market)
            if opportunity:
                opportunities.append(opportunity)
                logger.info(
                    "arbitrage_found",
                    market=opportunity.question[:50],
                    margin_pct=round(opportunity.margin_pct, 2),
                )

        # Sort by net margin (highest first)
        opportunities.sort(key=lambda x: x.net_margin_pct, reverse=True)

        self.results = opportunities
        logger.info("scan_complete", opportunities=len(opportunities))

        return opportunities

    def print_results(self) -> None:
        """Print formatted table of results."""
        # Always print summary of all scanned markets
        print("\n" + "=" * 120)
        print("INTRA-MARKET ARBITRAGE SCAN RESULTS")
        print("=" * 120)
        print()
        
        # If we have results, show them
        if self.results:
            # Header
            print(
                f"{'Market':<50} | {'YES':>6} | {'NO':>6} | {'Total':>7} | "
                f"{'Spread':>7} | {'Margin%':>8} | {'Net%':>7} | {'Liquidity':>10}"
            )
            print("-" * 120)

            # Data rows
            for opp in self.results:
                question = opp.question[:47] + "..." if len(opp.question) > 50 else opp.question

                print(
                    f"{question:<50} | "
                    f"{opp.best_yes_ask:>6.2f} | {opp.best_no_ask:>6.2f} | "
                    f"{opp.total_cost:>7.2f} | {opp.spread:>7.4f} | "
                    f"{opp.margin_pct:>7.2f}% | {opp.net_margin_pct:>6.2f}% | "
                    f"${opp.liquidity:>9.2f}"
                )

            print("-" * 120)
            print(f"Total opportunities with positive spread: {len(self.results)}")
            print()
        else:
            print("No arbitrage opportunities found (all markets have spread < 0)")
            print()
            print("Note: This is normal - Polymarket typically has efficient pricing.")
            print("The spread (YES_ask + NO_ask) is usually > $1.00, meaning no guaranteed profit.")
            print()

    def save_results(self, filename: str = "scripts/arb_scan_results.json") -> None:
        """Save results to JSON file.

        Args:
            filename: Output filename
        """
        data = {
            "scan_time": datetime.now().isoformat(),
            "opportunities_count": len(self.results),
            "opportunities": [asdict(opp) for opp in self.results],
        }

        with open(filename, "w") as f:
            json.dump(data, f, indent=2)

        logger.info("results_saved", filename=filename)


async def main():
    """Main entry point."""
    scanner = ArbitrageScanner(rate_limit_delay=0.2)

    try:
        opportunities = await scanner.scan_all_markets()

        scanner.print_results()
        scanner.save_results()

        if opportunities:
            logger.info(
                "scan_successful",
                opportunities=len(opportunities),
                best_margin=max(o.net_margin_pct for o in opportunities),
            )
        else:
            logger.info("no_opportunities")

    finally:
        await scanner.close()


if __name__ == "__main__":
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ]
    )

    asyncio.run(main())
