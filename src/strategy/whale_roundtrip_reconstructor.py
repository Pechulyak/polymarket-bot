# -*- coding: utf-8 -*-
"""Whale Roundtrip Reconstructor - Reconstruct whale positions from event-level whale_trades.

This module provides functionality to aggregate whale_trades (event log) into
whale_trade_roundtrips (position-level analytics).

Key concepts:
- whale_trades: Event log with individual BUY/SELL events
- whale_trade_roundtrips: Position-level view with open/close pairs

Task: TRD-412

Known limitations:
- market_category: Not available from Polymarket API (API doesn't provide groupItemTitle)
- settlement detection: Requires calling Polymarket Gamma API per market
- incremental updates: Run reconstruction periodically to capture new trades
"""

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.config.settings import settings

logger = structlog.get_logger(__name__)

# Polymarket APIs
CLOB_API = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


class CloseType(Enum):
    """Type of position close."""
    SELL = "SELL"
    SETTLEMENT_WIN = "SETTLEMENT_WIN"
    SETTLEMENT_LOSS = "SETTLEMENT_LOSS"
    FLIP = "FLIP"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class PositionStatus(Enum):
    """Position status."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PARTIAL = "PARTIAL"
    FLIPPED = "FLIPPED"
    UNRESOLVED = "UNRESOLVED"


class PnlStatus(Enum):
    """P&L confidence status."""
    CONFIRMED = "CONFIRMED"
    ESTIMATED = "ESTIMATED"
    UNAVAILABLE = "UNAVAILABLE"


class MatchingMethod(Enum):
    """Method used to match open/close."""
    DIRECT_SELL = "DIRECT_SELL"
    SETTLEMENT = "SETTLEMENT"
    FLIP = "FLIP"
    PARTIAL = "PARTIAL"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class MatchingConfidence(Enum):
    """Confidence level for matching."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class WhaleTradeEvent:
    """Single trade event from whale_trades table."""
    id: int
    whale_id: int
    wallet_address: str
    market_id: str
    side: str  # 'buy' or 'sell'
    size_usd: Decimal
    price: Decimal
    outcome: Optional[str]
    market_title: Optional[str]
    traded_at: datetime


@dataclass
class WhaleRoundtrip:
    """Reconstructed whale position (roundtrip)."""
    # Primary key
    id: uuid.UUID = field(default_factory=lambda: uuid.uuid4())
    
    # Whale identification
    whale_id: Optional[int] = None
    wallet_address: str = ""
    
    # Position key
    position_key: str = ""
    
    # Market context
    market_id: str = ""
    outcome: Optional[str] = None
    market_title: Optional[str] = None
    market_category: Optional[str] = None
    
    # Open details
    open_trade_id: Optional[int] = None
    open_side: Optional[str] = None
    open_price: Optional[Decimal] = None
    open_size_usd: Optional[Decimal] = None
    opened_at: Optional[datetime] = None
    
    # Close details
    close_trade_id: Optional[int] = None
    close_side: Optional[str] = None
    close_price: Optional[Decimal] = None
    close_size_usd: Optional[Decimal] = None
    closed_at: Optional[datetime] = None
    
    # Position status
    close_type: Optional[str] = None
    status: str = "OPEN"
    
    # P&L
    gross_pnl_usd: Optional[Decimal] = None
    fees_usd: Decimal = Decimal("0")
    net_pnl_usd: Optional[Decimal] = None
    pnl_status: str = "UNAVAILABLE"
    
    # Matching metadata
    matching_method: Optional[str] = None
    matching_confidence: Optional[str] = None
    
    # Paper trade link
    paper_trade_id: Optional[uuid.UUID] = None
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class WhaleRoundtripReconstructor:
    """Reconstruct whale positions from event-level whale_trades.
    
    This class handles the conversion from event log (whale_trades) to
    position-level analytics (whale_trade_roundtrips).
    
    The reconstruction logic:
    1. Group trades by (wallet_address, market_id, outcome)
    2. Identify open events (BUY) and close events (SELL)
    3. Match open/close pairs to create roundtrips
    4. Handle special cases: flip, partial, settlement
    """
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize the reconstructor.
        
        Args:
            database_url: PostgreSQL connection URL
        """
        self.database_url = database_url or settings.database_url
        self._engine = create_engine(self.database_url)
        self._Session = sessionmaker(bind=self._engine)
    
    def _generate_position_key(
        self,
        wallet_address: str,
        market_id: str,
        outcome: Optional[str],
        open_trade_id: int
    ) -> str:
        """Generate deterministic position key.
        
        Args:
            wallet_address: Whale wallet address
            market_id: Market identifier
            outcome: Outcome (Yes/No)
            open_trade_id: ID of opening trade
            
        Returns:
            Deterministic hash key
        """
        key_string = f"{wallet_address}:{market_id}:{outcome or 'unknown'}:{open_trade_id}"
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]
    
    def _fetch_whale_trades(self) -> List[WhaleTradeEvent]:
        """Fetch all whale trades from database.
        
        Returns:
            List of WhaleTradeEvent objects
        """
        query = text("""
            SELECT 
                wt.id,
                wt.whale_id,
                w.wallet_address,
                wt.market_id,
                wt.side,
                wt.size_usd,
                wt.price,
                wt.outcome,
                wt.market_title,
                wt.traded_at
            FROM whale_trades wt
            LEFT JOIN whales w ON LOWER(w.wallet_address) = LOWER(wt.wallet_address)
            ORDER BY wt.whale_id, wt.market_id, wt.traded_at
        """)
        
        with self._engine.connect() as conn:
            result = conn.execute(query)
            trades = []
            for row in result:
                trades.append(WhaleTradeEvent(
                    id=row[0],
                    whale_id=row[1],
                    wallet_address=row[2],
                    market_id=row[3],
                    side=row[4],
                    size_usd=Decimal(str(row[5])),
                    price=Decimal(str(row[6])),
                    outcome=row[7],
                    market_title=row[8],
                    traded_at=row[9]
                ))
        return trades
    
    def _group_trades_by_position(
        self,
        trades: List[WhaleTradeEvent]
    ) -> Dict[Tuple[str, str, Optional[str]], List[WhaleTradeEvent]]:
        """Group trades by position key.
        
        Groups by (wallet_address, market_id, outcome).
        
        Args:
            trades: List of all whale trades
            
        Returns:
            Dict mapping position key to list of trades
        """
        groups: Dict[Tuple[str, str, Optional[str]], List[WhaleTradeEvent]] = {}
        
        for trade in trades:
            key = (trade.wallet_address, trade.market_id, trade.outcome)
            if key not in groups:
                groups[key] = []
            groups[key].append(trade)
        
        # Sort each group by timestamp
        for key in groups:
            groups[key].sort(key=lambda t: t.traded_at)
        
        return groups
    
    def _reconstruct_roundtrips(
        self,
        trade_groups: Dict[Tuple[str, str, Optional[str]], List[WhaleTradeEvent]]
    ) -> List[WhaleRoundtrip]:
        """Reconstruct roundtrips from grouped trades.
        
        Args:
            trade_groups: Trades grouped by position
            
        Returns:
            List of reconstructed roundtrips
        """
        roundtrips = []
        
        for (wallet_address, market_id, outcome), trades in trade_groups.items():
            # Separate buy and sell events
            buy_events = [t for t in trades if t.side.lower() == 'buy']
            sell_events = [t for t in trades if t.side.lower() == 'sell']
            
            if not buy_events:
                # No open event - skip or mark as unresolved
                continue
            
            # Process buy events to create roundtrips
            for buy_event in buy_events:
                roundtrip = self._create_roundtrip_from_buy(
                    buy_event=buy_event,
                    all_sell_events=sell_events,
                    all_trades=trades
                )
                if roundtrip:
                    roundtrips.append(roundtrip)
        
        return roundtrips
    
    def _create_roundtrip_from_buy(
        self,
        buy_event: WhaleTradeEvent,
        all_sell_events: List[WhaleTradeEvent],
        all_trades: List[WhaleTradeEvent]
    ) -> Optional[WhaleRoundtrip]:
        """Create a roundtrip from a buy event.
        
        Args:
            buy_event: Opening buy event
            all_sell_events: All sell events for this position
            all_trades: All trades for this position
            
        Returns:
            WhaleRoundtrip or None
        """
        # Find matching sell event
        matching_sell = None
        for sell in all_sell_events:
            if sell.traded_at > buy_event.traded_at:
                if matching_sell is None or sell.traded_at < matching_sell.traded_at:
                    matching_sell = sell
        
        # Create roundtrip
        roundtrip = WhaleRoundtrip(
            whale_id=buy_event.whale_id,
            wallet_address=buy_event.wallet_address,
            market_id=buy_event.market_id,
            outcome=buy_event.outcome,
            market_title=buy_event.market_title,
            open_trade_id=buy_event.id,
            open_side=buy_event.side,
            open_price=buy_event.price,
            open_size_usd=buy_event.size_usd,
            opened_at=buy_event.traded_at,
        )
        
        # Generate position key
        roundtrip.position_key = self._generate_position_key(
            wallet_address=buy_event.wallet_address,
            market_id=buy_event.market_id,
            outcome=buy_event.outcome,
            open_trade_id=buy_event.id
        )
        
        if matching_sell:
            # Position is closed
            roundtrip.close_trade_id = matching_sell.id
            roundtrip.close_side = matching_sell.side
            roundtrip.close_price = matching_sell.price
            roundtrip.close_size_usd = matching_sell.size_usd
            roundtrip.closed_at = matching_sell.traded_at
            
            # Determine close type
            if roundtrip.close_size_usd and roundtrip.open_size_usd:
                if roundtrip.close_size_usd < roundtrip.open_size_usd:
                    roundtrip.close_type = CloseType.PARTIAL.value
                    roundtrip.status = PositionStatus.PARTIAL.value
                    roundtrip.matching_method = MatchingMethod.PARTIAL.value
                    roundtrip.matching_confidence = MatchingConfidence.MEDIUM.value
                else:
                    roundtrip.close_type = CloseType.SELL.value
                    roundtrip.status = PositionStatus.CLOSED.value
                    roundtrip.matching_method = MatchingMethod.DIRECT_SELL.value
                    roundtrip.matching_confidence = MatchingConfidence.HIGH.value
            else:
                roundtrip.close_type = CloseType.SELL.value
                roundtrip.status = PositionStatus.CLOSED.value
                roundtrip.matching_method = MatchingMethod.DIRECT_SELL.value
                roundtrip.matching_confidence = MatchingConfidence.HIGH.value
            
            # Calculate P&L
            roundtrip.gross_pnl_usd = self._calculate_gross_pnl(
                open_size=roundtrip.open_size_usd,
                open_price=roundtrip.open_price,
                close_size=roundtrip.close_size_usd,
                close_price=roundtrip.close_price
            )
            roundtrip.net_pnl_usd = roundtrip.gross_pnl_usd - roundtrip.fees_usd
            roundtrip.pnl_status = PnlStatus.CONFIRMED.value
            
        else:
            # Position is still open
            roundtrip.status = PositionStatus.OPEN.value
            roundtrip.close_type = CloseType.UNKNOWN.value
            roundtrip.matching_method = None
            roundtrip.matching_confidence = None
            roundtrip.pnl_status = PnlStatus.UNAVAILABLE.value
        
        return roundtrip
    
    def _calculate_gross_pnl(
        self,
        open_size: Optional[Decimal],
        open_price: Optional[Decimal],
        close_size: Optional[Decimal],
        close_price: Optional[Decimal]
    ) -> Optional[Decimal]:
        """Calculate gross P&L.
        
        Reuses algorithm from virtual_bankroll.py:
        gross_pnl = exit_value - entry_value
        
        Args:
            open_size: Opening position size in USD
            open_price: Opening price
            close_size: Closing position size in USD
            close_price: Closing price
            
        Returns:
            Gross P&L in USD
        """
        if not all([open_size, open_price, close_size, close_price]):
            return None
        
        entry_value = open_size * open_price
        exit_value = close_size * close_price
        
        return exit_value - entry_value
    
    def _save_roundtrips(self, roundtrips: List[WhaleRoundtrip]) -> int:
        """Save roundtrips to database.
        
        Args:
            roundtrips: List of roundtrips to save
            
        Returns:
            Number of roundtrips saved
        """
        query = text("""
            INSERT INTO whale_trade_roundtrips (
                id, whale_id, wallet_address, position_key,
                market_id, outcome, market_title, market_category,
                open_trade_id, open_side, open_price, open_size_usd, opened_at,
                close_trade_id, close_side, close_price, close_size_usd, closed_at,
                close_type, status,
                gross_pnl_usd, fees_usd, net_pnl_usd, pnl_status,
                matching_method, matching_confidence,
                paper_trade_id,
                created_at, updated_at
            ) VALUES (
                :id, :whale_id, :wallet_address, :position_key,
                :market_id, :outcome, :market_title, :market_category,
                :open_trade_id, :open_side, :open_price, :open_size_usd, :opened_at,
                :close_trade_id, :close_side, :close_price, :close_size_usd, :closed_at,
                :close_type, :status,
                :gross_pnl_usd, :fees_usd, :net_pnl_usd, :pnl_status,
                :matching_method, :matching_confidence,
                :paper_trade_id,
                :created_at, :updated_at
            )
            ON CONFLICT (position_key) DO UPDATE SET
                close_trade_id = EXCLUDED.close_trade_id,
                close_side = EXCLUDED.close_side,
                close_price = EXCLUDED.close_price,
                close_size_usd = EXCLUDED.close_size_usd,
                closed_at = EXCLUDED.closed_at,
                close_type = EXCLUDED.close_type,
                status = EXCLUDED.status,
                gross_pnl_usd = EXCLUDED.gross_pnl_usd,
                net_pnl_usd = EXCLUDED.net_pnl_usd,
                pnl_status = EXCLUDED.pnl_status,
                matching_method = EXCLUDED.matching_method,
                matching_confidence = EXCLUDED.matching_confidence,
                updated_at = EXCLUDED.updated_at
        """)
        
        with self._engine.connect() as conn:
            for rt in roundtrips:
                conn.execute(query, {
                    'id': rt.id,
                    'whale_id': rt.whale_id,
                    'wallet_address': rt.wallet_address,
                    'position_key': rt.position_key,
                    'market_id': rt.market_id,
                    'outcome': rt.outcome,
                    'market_title': rt.market_title,
                    'market_category': rt.market_category,
                    'open_trade_id': rt.open_trade_id,
                    'open_side': rt.open_side,
                    'open_price': float(rt.open_price) if rt.open_price else None,
                    'open_size_usd': float(rt.open_size_usd) if rt.open_size_usd else None,
                    'opened_at': rt.opened_at,
                    'close_trade_id': rt.close_trade_id,
                    'close_side': rt.close_side,
                    'close_price': float(rt.close_price) if rt.close_price else None,
                    'close_size_usd': float(rt.close_size_usd) if rt.close_size_usd else None,
                    'closed_at': rt.closed_at,
                    'close_type': rt.close_type,
                    'status': rt.status,
                    'gross_pnl_usd': float(rt.gross_pnl_usd) if rt.gross_pnl_usd else None,
                    'fees_usd': float(rt.fees_usd),
                    'net_pnl_usd': float(rt.net_pnl_usd) if rt.net_pnl_usd else None,
                    'pnl_status': rt.pnl_status,
                    'matching_method': rt.matching_method,
                    'matching_confidence': rt.matching_confidence,
                    'paper_trade_id': rt.paper_trade_id,
                    'created_at': rt.created_at,
                    'updated_at': rt.updated_at,
                })
            conn.commit()
        
        return len(roundtrips)
    
    def run_reconstruction(self) -> Dict[str, int]:
        """Run full reconstruction pipeline.
        
        Returns:
            Dict with reconstruction statistics
        """
        logger.info("whale_roundtrip_reconstruction_started")
        
        # Step 1: Fetch all whale trades
        trades = self._fetch_whale_trades()
        logger.info("whale_trades_fetched", count=len(trades))
        
        # Step 2: Group trades by position
        trade_groups = self._group_trades_by_position(trades)
        logger.info("trade_groups_created", groups=len(trade_groups))
        
        # Step 3: Reconstruct roundtrips
        roundtrips = self._reconstruct_roundtrips(trade_groups)
        logger.info("roundtrips_reconstructed", count=len(roundtrips))
        
        # Step 4: Save to database
        saved = self._save_roundtrips(roundtrips)
        logger.info("roundtrips_saved", count=saved)
        
        # Step 5: Get statistics
        stats = self._get_statistics()
        
        logger.info("whale_roundtrip_reconstruction_completed", stats=stats)
        
        return stats
    
    def _get_statistics(self) -> Dict[str, int]:
        """Get reconstruction statistics.
        
        Returns:
            Dict with status counts
        """
        query = text("""
            SELECT 
                status,
                COUNT(*) as count
            FROM whale_trade_roundtrips
            GROUP BY status
        """)
        
        with self._engine.connect() as conn:
            result = conn.execute(query)
            stats = {row[0]: row[1] for row in result}
        
        # Add total
        total_query = text("SELECT COUNT(*) FROM whale_trade_roundtrips")
        with self._engine.connect() as conn:
            result = conn.execute(total_query)
            stats['total'] = result.scalar()
        
        return stats


    async def check_market_resolution(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Check if market is resolved via Polymarket CLOB API.
        
        Args:
            market_id: Market identifier
            
        Returns:
            Dict with resolution data or None
        """
        try:
            async with aiohttp.ClientSession() as session:
                # Use CLOB API - it provides market resolution data
                url = f"{CLOB_API}/markets/{market_id}"
                
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    
                    market = await resp.json()
                    
                    closed = market.get("closed", False)
                    if not closed:
                        return None
                    
                    # Get tokens (contains winner and settlement prices)
                    tokens = market.get("tokens", [])
                    
                    # Determine winner from tokens
                    winner = None
                    settlement_prices = []
                    
                    for token in tokens:
                        outcome = token.get("outcome", "")
                        price = token.get("price", 0)
                        winner_flag = token.get("winner", False)
                        
                        if winner_flag:
                            winner = outcome
                        settlement_prices.append({"outcome": outcome, "price": price})
                    
                    return {
                        "closed": closed,
                        "winner": winner,
                        "settlement_prices": settlement_prices,
                        "market": market,
                    }
                    
        except Exception as e:
            logger.debug("market_resolution_check_error", market_id=market_id[:20], error=str(e))
            return None
    
    async def update_settled_positions(self, batch_size: int = 50) -> Dict[str, int]:
        """Update open positions with settlement data.
        
        For each open position, check if the market is resolved and update accordingly.
        
        Args:
            batch_size: Number of markets to check per run
            
        Returns:
            Dict with update statistics
        """
        logger.info("settlement_detection_started")
        
        # Get open positions with their markets
        query = text("""
            SELECT DISTINCT market_id, outcome, open_price, open_size_usd
            FROM whale_trade_roundtrips
            WHERE status = 'OPEN'
            LIMIT :batch_size
        """)
        
        with self._engine.connect() as conn:
            result = conn.execute(query, {"batch_size": batch_size})
            markets = list(result)
        
        if not markets:
            logger.info("no_open_positions_to_check")
            return {"checked": 0, "settled": 0}
        
        settled = 0
        for market_id, outcome, open_price, open_size_usd in markets:
            resolution = await self.check_market_resolution(market_id)
            
            if resolution and resolution.get("winner"):
                winner = resolution["winner"]
                settlement_prices = resolution.get("settlement_prices", [])
                
                # Determine if our position won
                # Winner "Yes" means YES outcome won
                won = (outcome and outcome.lower() == winner.lower())
                
                # Get settlement price
                settlement_price = None
                if settlement_prices and outcome:
                    # CLOB API returns list of dicts: [{"outcome": "Yes", "price": 0.5}, ...]
                    # Find price for our outcome
                    try:
                        for sp in settlement_prices:
                            if isinstance(sp, dict):
                                sp_outcome = sp.get("outcome", "")
                                if sp_outcome and sp_outcome.lower() == outcome.lower():
                                    settlement_price = Decimal(str(sp.get("price", 0)))
                                    break
                            elif isinstance(sp, (int, float)):
                                # Fallback for simple list
                                settlement_price = Decimal(str(sp))
                                break
                    except (ValueError, TypeError):
                        pass
                
                if settlement_price is None:
                    # Use first price as fallback (handle dict format from CLOB API)
                    if settlement_prices:
                        first = settlement_prices[0]
                        if isinstance(first, dict):
                            settlement_price = Decimal(str(first.get("price", 0)))
                        else:
                            settlement_price = Decimal(str(first))
                    else:
                        settlement_price = Decimal("0")
                
                # Calculate P&L
                if open_price and settlement_price and open_size_usd:
                    if won:
                        # Won: profit = size * (1 - entry_price) for Yes, or size * entry_price for No
                        if outcome and outcome.lower() == "yes":
                            gross_pnl = open_size_usd * (settlement_price - open_price)
                        else:
                            gross_pnl = open_size_usd * (Decimal("1") - open_price - (Decimal("1") - settlement_price))
                    else:
                        # Lost: lose the stake
                        if outcome and outcome.lower() == "yes":
                            gross_pnl = open_size_usd * (settlement_price - open_price)
                        else:
                            gross_pnl = open_size_usd * (Decimal("1") - open_price) - open_size_usd * (Decimal("1") - settlement_price)
                    
                    # Update position
                    update_query = text("""
                        UPDATE whale_trade_roundtrips
                        SET status = :status,
                            close_type = :close_type,
                            close_price = :close_price,
                            closed_at = NOW(),
                            gross_pnl_usd = :gross_pnl,
                            net_pnl_usd = :gross_pnl,
                            pnl_status = 'CONFIRMED',
                            matching_method = 'SETTLEMENT',
                            matching_confidence = 'MEDIUM',
                            updated_at = NOW()
                        WHERE market_id = :market_id
                        AND status = 'OPEN'
                    """)
                    
                    close_type = CloseType.SETTLEMENT_WIN.value if won else CloseType.SETTLEMENT_LOSS.value
                    
                    with self._engine.connect() as conn:
                        conn.execute(update_query, {
                            "status": PositionStatus.CLOSED.value,
                            "close_type": close_type,
                            "close_price": float(settlement_price),
                            "gross_pnl": float(gross_pnl),
                            "market_id": market_id,
                        })
                        conn.commit()
                    
                    settled += 1
                    logger.info("position_settled", market_id=market_id[:20], won=won, pnl=str(gross_pnl))
        
        logger.info("settlement_detection_completed", checked=len(markets), settled=settled)
        return {"checked": len(markets), "settled": settled}
    
    async def run_incremental_update(self) -> Dict[str, int]:
        """Run incremental update - process new trades and settlements.
        
        Returns:
            Dict with update statistics
        """
        logger.info("incremental_update_started")
        
        # Get last trade ID processed
        max_query = text("SELECT COALESCE(MAX(open_trade_id), 0) FROM whale_trade_roundtrips")
        with self._engine.connect() as conn:
            result = conn.execute(max_query)
            last_trade_id = result.scalar()
        
        # Fetch new trades
        new_trades_query = text("""
            SELECT 
                wt.id,
                wt.whale_id,
                w.wallet_address,
                wt.market_id,
                wt.side,
                wt.size_usd,
                wt.price,
                wt.outcome,
                wt.market_title,
                wt.traded_at
            FROM whale_trades wt
            LEFT JOIN whales w ON LOWER(w.wallet_address) = LOWER(wt.wallet_address)
            WHERE wt.id > :last_trade_id
            ORDER BY wt.id
        """)
        
        with self._engine.connect() as conn:
            result = conn.execute(new_trades_query, {"last_trade_id": last_trade_id})
            new_trades = []
            for row in result:
                new_trades.append(WhaleTradeEvent(
                    id=row[0],
                    whale_id=row[1],
                    wallet_address=row[2],
                    market_id=row[3],
                    side=row[4],
                    size_usd=Decimal(str(row[5])),
                    price=Decimal(str(row[6])),
                    outcome=row[7],
                    market_title=row[8],
                    traded_at=row[9]
                ))
        
        logger.info("new_trades_fetched", count=len(new_trades))
        
        # Process new trades
        if new_trades:
            trade_groups = self._group_trades_by_position(new_trades)
            new_roundtrips = self._reconstruct_roundtrips(trade_groups)
            saved = self._save_roundtrips(new_roundtrips)
            logger.info("new_roundtrips_saved", count=saved)
        else:
            saved = 0
        
        # Check settlements for open positions
        settlement_result = await self.update_settled_positions(batch_size=100)
        
        # Get final stats
        stats = self._get_statistics()
        stats['new_trades'] = len(new_trades)
        stats['new_roundtrips'] = saved
        
        logger.info("incremental_update_completed", stats=stats)
        
        return stats


async def run_whale_roundtrip_reconstruction():
    """Async wrapper for running reconstruction."""
    reconstructor = WhaleRoundtripReconstructor(database_url='postgresql://postgres:Artem15@localhost:5433/polymarket')
    return await reconstructor.run_incremental_update()


if __name__ == "__main__":
    import asyncio
    result = asyncio.run(run_whale_roundtrip_reconstruction())
    print(f"Reconstruction complete: {result}")
