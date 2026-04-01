# -*- coding: utf-8 -*-
"""Roundtrip Builder - Create OPEN roundtrips from whale BUY events with aggregation.

This module provides roundtrip creation logic with BUY event aggregation:
- Group all BUY events by position_key (wallet_address + market_id + outcome)
- Aggregate into single OPEN position per unique position_key
- Calculate weighted average price and total size
- Track first purchase timestamp as opened_at

Task: TRD-412 / ARC-502-A, ARC-502-B, ARC-502-C

Usage:
    # Normal run (skip duplicates, keep existing):
    python -m src.strategy.roundtrip_builder
    
    # Rebuild all OPEN positions from scratch:
    python -m src.strategy.roundtrip_builder --rebuild
    
    # Close positions via SELL events:
    python -m src.strategy.roundtrip_builder --close
    
    # Settle positions via Gamma API (market resolution):
    python -m src.strategy.roundtrip_builder --settle
"""

import os
import sys
import argparse
import asyncio
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

import aiohttp
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = print

# Polymarket APIs
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


def get_database_url() -> str:
    """Get database URL from environment or default."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:password@localhost:5433/polymarket"
    )


class RoundtripBuilder:
    """Build OPEN roundtrips from whale BUY events with aggregation.
    
    Aggregates multiple BUY events for same position_key into single OPEN:
    - Groups by wallet_address + market_id + outcome
    - Sums size_usd for total open position
    - Calculates weighted average open price
    - Uses MIN(traded_at) as opened_at (first purchase, not last)
    """
    
    def __init__(self, database_url: str = None):
        """Initialize builder.
        
        Args:
            database_url: PostgreSQL connection URL
        """
        self.database_url = database_url or get_database_url()
        self._engine = create_engine(self.database_url)
        self._Session = sessionmaker(bind=self._engine)
    
    def _generate_position_key(self, wallet_address: str, market_id: str, outcome: str = None) -> str:
        """Generate position key for grouping.
        
        Args:
            wallet_address: Whale wallet address
            market_id: Market identifier
            outcome: Outcome (Yes/No)
            
        Returns:
            Position key string
        """
        return f"{wallet_address}:{market_id}:{outcome or 'unknown'}"
    
    def _fetch_and_group_buy_trades(self) -> Dict[str, Dict]:
        """Fetch all BUY events and group by position_key with aggregation.
        
        Groups all BUY trades by (wallet_address, market_id, outcome) and calculates:
        - open_size_usd = SUM(size_usd)
        - open_price = SUM(price * size_usd) / SUM(size_usd) -- weighted average
        - opened_at = MIN(traded_at) -- first purchase
        - open_trade_id = id of first trade (MIN traded_at)
        
        Returns:
            Dict mapping position_key to aggregated data
        """
        query = text("""
            SELECT 
                w.wallet_address,
                wt.market_id,
                wt.outcome,
                -- Aggregation
                SUM(wt.size_usd) as open_size_usd,
                SUM(wt.price * wt.size_usd) / NULLIF(SUM(wt.size_usd), 0) as open_price,
                MIN(wt.traded_at) as opened_at,
                MIN(wt.id) as open_trade_id,
                -- Get whale_id only from matched whale
                w.id as whale_id
            FROM whale_trades wt
            LEFT JOIN whales w ON LOWER(w.wallet_address) = LOWER(wt.wallet_address)
            WHERE wt.side = 'buy'
            GROUP BY w.wallet_address, wt.market_id, wt.outcome, w.id
            ORDER BY opened_at
        """)
        
        with self._engine.connect() as conn:
            result = conn.execute(query)
            grouped = {}
            for row in result:
                position_key = self._generate_position_key(
                    wallet_address=row[0],
                    market_id=row[1],
                    outcome=row[2]
                )
                # Row indices: 0=wallet_address, 1=market_id, 2=outcome, 
                # 3=open_size_usd, 4=open_price, 5=opened_at, 6=open_trade_id, 7=whale_id
                grouped[position_key] = {
                    'whale_id': row[7],  # This is w.id (whale's primary key)
                    'wallet_address': row[0],
                    'position_key': position_key,
                    'market_id': row[1],
                    'outcome': row[2],
                    'open_size_usd': row[3],
                    'open_price': row[4],
                    'opened_at': row[5],
                    'open_trade_id': row[6],  # This is MIN(wt.id) - the trade ID
                    'market_title': None,
                }
        
        return grouped
    
    def _get_existing_open_position_keys(self) -> set:
        """Get set of existing OPEN position keys for deduplication.
        
        Returns:
            Set of position_key strings
        """
        query = text("""
            SELECT position_key
            FROM whale_trade_roundtrips
            WHERE status = 'OPEN'
        """)
        
        with self._engine.connect() as conn:
            result = conn.execute(query)
            return {row[0] for row in result}
    
    def _clear_existing_open_roundtrips(self) -> int:
        """Delete all existing OPEN roundtrips.
        
        Returns:
            Number of deleted records
        """
        query = text("""
            DELETE FROM whale_trade_roundtrips
            WHERE status = 'OPEN'
        """)
        
        with self._engine.connect() as conn:
            result = conn.execute(query)
            conn.commit()
            return result.rowcount
    
    def _create_roundtrips(
        self,
        grouped_trades: Dict[str, Dict],
    ) -> Tuple[List[Dict], int]:
        """Create roundtrip records from aggregated BUY groups.
        
        Args:
            grouped_trades: Dict of aggregated trade data by position_key
            
        Returns:
            Tuple of (roundtrips list, created count)
        """
        roundtrips = []
        created = 0
        
        for position_key, trade_data in grouped_trades.items():
            # Create roundtrip record with aggregated data
            roundtrip = {
                'id': str(uuid4()),
                'whale_id': trade_data['whale_id'],
                'wallet_address': trade_data['wallet_address'],
                'position_key': position_key,
                'market_id': trade_data['market_id'],
                'outcome': trade_data['outcome'],
                'market_title': trade_data['market_title'],
                'market_category': None,
                'open_trade_id': trade_data['open_trade_id'],
                'open_side': 'buy',
                'open_price': trade_data['open_price'],
                'open_size_usd': trade_data['open_size_usd'],
                'opened_at': trade_data['opened_at'],
                # Close fields - null for OPEN positions
                'close_trade_id': None,
                'close_side': None,
                'close_price': None,
                'close_size_usd': None,
                'closed_at': None,
                'close_type': None,
                # Status
                'status': 'OPEN',
                # P&L - unavailable until close
                'gross_pnl_usd': None,
                'fees_usd': 0,
                'net_pnl_usd': None,
                'pnl_status': 'UNAVAILABLE',
                # Matching metadata
                'matching_method': None,
                'matching_confidence': None,
            }
            
            roundtrips.append(roundtrip)
            created += 1
        
        return roundtrips, created
    
    def _save_roundtrips(self, roundtrips: List[Dict]) -> int:
        """Save roundtrips to database.
        
        Args:
            roundtrips: List of roundtrip dictionaries
            
        Returns:
            Number of records inserted
        """
        if not roundtrips:
            return 0
        
        query = text("""
            INSERT INTO whale_trade_roundtrips (
                id, whale_id, wallet_address, position_key,
                market_id, outcome, market_title, market_category,
                open_trade_id, open_side, open_price, open_size_usd, opened_at,
                close_trade_id, close_side, close_price, close_size_usd, closed_at,
                close_type, status,
                gross_pnl_usd, fees_usd, net_pnl_usd, pnl_status,
                matching_method, matching_confidence,
                created_at, updated_at
            ) VALUES (
                :id, :whale_id, :wallet_address, :position_key,
                :market_id, :outcome, :market_title, :market_category,
                :open_trade_id, :open_side, :open_price, :open_size_usd, :opened_at,
                :close_trade_id, :close_side, :close_price, :close_size_usd, :closed_at,
                :close_type, :status,
                :gross_pnl_usd, :fees_usd, :net_pnl_usd, :pnl_status,
                :matching_method, :matching_confidence,
                NOW(), NOW()
            )
            ON CONFLICT (position_key) DO NOTHING
        """)
        
        with self._engine.connect() as conn:
            for rt in roundtrips:
                conn.execute(query, rt)
            conn.commit()
        
        return len(roundtrips)
    
    def _get_statistics(self) -> Dict:
        """Get roundtrips statistics.
        
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
        
        total_query = text("SELECT COUNT(*) FROM whale_trade_roundtrips")
        with self._engine.connect() as conn:
            result = conn.execute(total_query)
            stats['total'] = result.scalar()
        
        return stats
    
    def _fetch_and_group_sell_trades(self) -> Dict[str, Dict]:
        """Fetch all SELL events and group by position_key with aggregation.
        
        Groups all SELL trades by (wallet_address, market_id, outcome) and calculates:
        - close_size_usd = SUM(size_usd)
        - close_price = SUM(price * size_usd) / SUM(size_usd) -- weighted average
        - closed_at = MAX(traded_at) -- last sale
        - close_trade_id = id of last trade (MAX traded_at)
        
        Returns:
            Dict mapping position_key to aggregated close data
        """
        query = text("""
            SELECT 
                w.wallet_address,
                wt.market_id,
                wt.outcome,
                -- Aggregation
                SUM(wt.size_usd) as close_size_usd,
                SUM(wt.price * wt.size_usd) / NULLIF(SUM(wt.size_usd), 0) as close_price,
                MAX(wt.traded_at) as closed_at,
                MAX(wt.id) as close_trade_id,
                -- Get whale_id only from matched whale
                w.id as whale_id
            FROM whale_trades wt
            LEFT JOIN whales w ON LOWER(w.wallet_address) = LOWER(wt.wallet_address)
            WHERE wt.side = 'sell'
            GROUP BY w.wallet_address, wt.market_id, wt.outcome, w.id
            ORDER BY closed_at
        """)
        
        with self._engine.connect() as conn:
            result = conn.execute(query)
            grouped = {}
            for row in result:
                position_key = self._generate_position_key(
                    wallet_address=row[0],
                    market_id=row[1],
                    outcome=row[2]
                )
                # Row indices: 0=wallet_address, 1=market_id, 2=outcome, 
                # 3=close_size_usd, 4=close_price, 5=closed_at, 6=close_trade_id, 7=whale_id
                grouped[position_key] = {
                    'whale_id': row[7],
                    'wallet_address': row[0],
                    'position_key': position_key,
                    'market_id': row[1],
                    'outcome': row[2],
                    'close_size_usd': row[3],
                    'close_price': row[4],
                    'closed_at': row[5],
                    'close_trade_id': row[6],
                }
        
        return grouped
    
    def _close_roundtrips(self, grouped_sells: Dict[str, Dict]) -> Tuple[List[Dict], int, int]:
        """Close OPEN roundtrips based on SELL events.
        
        Args:
            grouped_sells: Dict of aggregated SELL data by position_key
            
        Returns:
            Tuple of (closed_roundtrips list, closed_count, skipped_count)
        """
        closed_roundtrips = []
        closed_count = 0
        skipped_count = 0
        skipped_keys = []
        
        for position_key, close_data in grouped_sells.items():
            # Find OPEN roundtrips for this position_key
            # First try exact match
            query = text("""
                SELECT 
                    id, whale_id, open_price, open_size_usd, status, outcome
                FROM whale_trade_roundtrips
                WHERE position_key = :position_key AND status = 'OPEN'
                LIMIT 1
            """)
            
            with self._engine.connect() as conn:
                result = conn.execute(query, {"position_key": position_key})
                row = result.fetchone()
            
            if not row:
                # No exact match - try fuzzy matching for short selling (sell before buy)
                # Look for any OPEN roundtrip for same wallet + market (different outcome)
                wallet_address = close_data['wallet_address']
                market_id = close_data['market_id']
                
                fuzzy_query = text("""
                    SELECT 
                        id, whale_id, open_price, open_size_usd, status, outcome
                    FROM whale_trade_roundtrips
                    WHERE wallet_address = :wallet_address 
                        AND market_id = :market_id 
                        AND status = 'OPEN'
                    ORDER BY opened_at DESC
                    LIMIT 1
                """)
                
                with self._engine.connect() as conn:
                    result = conn.execute(fuzzy_query, {
                        "wallet_address": wallet_address,
                        "market_id": market_id
                    })
                    row = result.fetchone()
            
            if not row:
                skipped_keys.append(position_key)
                skipped_count += 1
                continue
            
            roundtrip_id, whale_id, open_price, open_size_usd, status, open_outcome = row
            
            # Calculate P&L
            close_price = close_data['close_price']
            close_size = close_data['close_size_usd']
            
            # gross_pnl = (close_price - open_price) * close_size
            # Note: prices are in 0-1 range (e.g., 0.65 for 65%)
            gross_pnl = (close_price - open_price) * close_size
            fees_usd = 0  # No fee data available
            net_pnl = gross_pnl - fees_usd
            
            # Determine P&L status
            pnl_status = 'CONFIRMED'
            
            # Update roundtrip
            update_query = text("""
                UPDATE whale_trade_roundtrips SET
                    close_trade_id = :close_trade_id,
                    close_side = 'sell',
                    close_price = :close_price,
                    close_size_usd = :close_size_usd,
                    closed_at = :closed_at,
                    close_type = 'SELL',
                    status = 'CLOSED',
                    gross_pnl_usd = :gross_pnl_usd,
                    fees_usd = :fees_usd,
                    net_pnl_usd = :net_pnl_usd,
                    pnl_status = :pnl_status,
                    matching_method = 'FLIP',
                    matching_confidence = 'MEDIUM',
                    updated_at = NOW()
                WHERE id = :id AND status = 'OPEN'
            """)
            
            with self._engine.connect() as conn:
                result = conn.execute(update_query, {
                    'close_trade_id': close_data['close_trade_id'],
                    'close_price': close_price,
                    'close_size_usd': close_size,
                    'closed_at': close_data['closed_at'],
                    'gross_pnl_usd': gross_pnl,
                    'fees_usd': fees_usd,
                    'net_pnl_usd': net_pnl,
                    'pnl_status': pnl_status,
                    'id': roundtrip_id
                })
                conn.commit()
            
            if result.rowcount > 0:
                closed_roundtrips.append({
                    'id': roundtrip_id,
                    'whale_id': whale_id,
                    'wallet_address': close_data['wallet_address'],
                    'position_key': position_key,
                    'net_pnl_usd': net_pnl,
                })
                closed_count += 1
        
        return closed_roundtrips, closed_count, skipped_count
    
    def _update_whales_pnl(self, closed_roundtrips: List[Dict]) -> int:
        """Update whales P&L based on closed roundtrips.
        
        Args:
            closed_roundtrips: List of closed roundtrip records with P&L
            
        Returns:
            Number of whales updated
        """
        if not closed_roundtrips:
            return 0
        
        
        # Group by wallet_address instead of whale_id
        whale_updates = {}
        for rt in closed_roundtrips:
            wallet_address = rt['wallet_address']
            if wallet_address not in whale_updates:
                whale_updates[wallet_address] = {
                    'wallet_address': wallet_address,
                    'wins': 0,
                    'losses': 0,
                    'roundtrips': 0,
                    'total_pnl': Decimal('0')
                }
            
            whale_updates[wallet_address]['roundtrips'] += 1
            whale_updates[wallet_address]['total_pnl'] += rt['net_pnl_usd']
            
            if rt['net_pnl_usd'] > 0:
                whale_updates[wallet_address]['wins'] += 1
            else:
                whale_updates[wallet_address]['losses'] += 1
        
        # Update each whale
        updated_count = 0
        for wallet_address, data in whale_updates.items():
            # Calculate new values
            query = text("""
                SELECT 
                    win_count, 
                    loss_count, 
                    total_roundtrips, 
                    total_pnl_usd
                FROM whales
                WHERE LOWER(wallet_address) = LOWER(:wallet_address)
            """)
            
            with self._engine.connect() as conn:
                result = conn.execute(query, {"wallet_address": wallet_address})
                row = result.fetchone()
            
            if not row:
                continue
            
            current_win_count = row[0] or 0
            current_loss_count = row[1] or 0
            current_total_roundtrips = row[2] or 0
            current_total_pnl = row[3] or Decimal('0')
            
            new_win_count = current_win_count + data['wins']
            new_loss_count = current_loss_count + data['losses']
            new_total_roundtrips = current_total_roundtrips + data['roundtrips']
            new_total_pnl = current_total_pnl + data['total_pnl']
            
            # Calculate avg_pnl and win_rate
            if new_total_roundtrips > 0:
                new_avg_pnl = new_total_pnl / new_total_roundtrips
                new_win_rate = Decimal(str(new_win_count)) / Decimal(str(new_total_roundtrips))
            else:
                new_avg_pnl = Decimal('0')
                new_win_rate = Decimal('0')
            
            update_query = text("""
                UPDATE whales SET
                    win_count = :win_count,
                    loss_count = :loss_count,
                    total_roundtrips = :total_roundtrips,
                    total_pnl_usd = :total_pnl_usd,
                    avg_pnl_usd = :avg_pnl_usd,
                    win_rate_confirmed = :win_rate_confirmed,
                    last_pnl_updated = NOW(),
                    updated_at = NOW()
                WHERE LOWER(wallet_address) = LOWER(:wallet_address)
            """)
            
            with self._engine.connect() as conn:
                result = conn.execute(update_query, {
                    'win_count': new_win_count,
                    'loss_count': new_loss_count,
                    'total_roundtrips': new_total_roundtrips,
                    'total_pnl_usd': new_total_pnl,
                    'avg_pnl_usd': new_avg_pnl,
                    'win_rate_confirmed': new_win_rate,
                    'wallet_address': wallet_address
                })
                conn.commit()
            
            if result.rowcount > 0:
                updated_count += 1
        
        return updated_count
    
    def _get_outcome_index(self, outcome: str) -> Optional[int]:
        """Map outcome to index in outcome_prices array.
        
        Args:
            outcome: Outcome string (Yes/No/Up/Down/Over/Under or custom team names)
            
        Returns:
            Index in outcome_prices array, or None if unknown
        """
        if not outcome:
            return None
        
        outcome_lower = outcome.lower()
        
        # Standard binary outcomes
        if outcome_lower in ('yes', 'up', 'over'):
            return 0
        elif outcome_lower in ('no', 'down', 'under'):
            return 1
        
        # For non-standard outcomes (team names like "Lakers", "Xtreme Gaming")
        # These will be matched by looking up in outcomes array
        # Return None and handle in settlement logic
        return None
    
    async def _get_market_resolution(self, session: aiohttp.ClientSession, market_id: str) -> Optional[Dict]:
        """Get market resolution data from CLOB API.
        
        CLOB API works directly with conditionId (which is what we store in market_id).
        
        Args:
            session: aiohttp client session
            market_id: Market identifier (conditionId from whale_trades)
            
        Returns:
            Dict with market resolution data or None
        """
        try:
            # Use CLOB API: GET /markets/{conditionId}
            # This returns market data including tokens with winner status
            url = f"{CLOB_API}/markets/{market_id}"
            
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger(f"Warning: market_api_error for {market_id[:20]}, status={resp.status}")
                    return None
                
                market = await resp.json()
                
                # Extract resolution data
                closed = market.get("closed", False)
                resolved = market.get("resolved")
                
                # Get tokens array - contains outcome prices and winner status
                tokens = market.get("tokens", [])
                
                # Build outcome_prices and winner mapping from tokens
                outcome_prices = []
                winners = []
                outcomes = []
                
                for token in tokens:
                    outcome = token.get("outcome", "")
                    price = token.get("price", "0")
                    winner = token.get("winner", False)
                    
                    outcomes.append(outcome)
                    outcome_prices.append(float(price) if price else 0.0)
                    winners.append(winner)
                
                return {
                    "market_id": market_id,
                    "closed": closed,
                    "resolved": resolved,
                    "outcome_prices": outcome_prices,
                    "outcomes": outcomes,
                    "winners": winners,
                }
                
        except Exception as e:
            logger(f"Error: market_resolution_error for {market_id[:20]}: {e}")
            return None
    
    async def settle_roundtrips_via_gamma(self) -> Dict:
        """Settle OPEN roundtrips via Gamma API market resolution.
        
        Checks each OPEN roundtrip's market_id against Gamma API.
        If market is closed (resolved), calculates P&L based on settlement prices
        and updates the roundtrip status.
        
        Returns:
            Dict with settlement results
        """
        logger("=" * 60)
        logger("ROUNDTRIP SETTLER (ARC-502-C) - Gamma API Settlement")
        logger("=" * 60)
        
        # Step 1: Get all OPEN roundtrips with unique market_ids
        logger("[1/5] Fetching OPEN roundtrips...")
        
        query = text("""
            SELECT DISTINCT market_id, outcome, open_price, open_size_usd, id, wallet_address, whale_id
            FROM whale_trade_roundtrips
            WHERE status = 'OPEN'
        """)
        
        with self._engine.connect() as conn:
            result = conn.execute(query)
            open_roundtrips = []
            market_ids = set()
            for row in result:
                open_roundtrips.append({
                    'roundtrip_id': row[4],
                    'whale_id': row[6],
                    'wallet_address': row[5],
                    'market_id': row[0],
                    'outcome': row[1],
                    'open_price': row[2],
                    'open_size_usd': row[3],
                })
                market_ids.add(row[0])
        
        logger(f"      Found {len(open_roundtrips)} OPEN roundtrips across {len(market_ids)} markets")
        
        if not open_roundtrips:
            return {
                'checked': 0,
                'settled': 0,
                'closed_markets': 0,
                'open_markets': 0,
                'errors': 0,
            }
        
        # Step 2: Fetch resolution data for each unique market
        logger("[2/5] Fetching market resolutions from Gamma API...")
        
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        market_resolutions = {}
        
        try:
            for market_id in market_ids:
                resolution = await self._get_market_resolution(session, market_id)
                if resolution:
                    market_resolutions[market_id] = resolution
                # Rate limiting: pause between requests
                await asyncio.sleep(0.05)
        finally:
            await session.close()
        
        logger(f"      Fetched {len(market_resolutions)} market resolutions")
        
        # Step 3: Process each roundtrip for settlement
        logger("[3/5] Processing settlements...")
        
        settled_roundtrips = []
        closed_markets = 0
        open_markets = 0
        errors = 0
        skipped_unknown_outcome = 0
        
        for rt in open_roundtrips:
            market_id = rt['market_id']
            outcome = rt['outcome']
            open_price = rt['open_price']
            open_size_usd = rt['open_size_usd']
            
            # Skip if no resolution data
            if market_id not in market_resolutions:
                errors += 1
                continue
            
            resolution = market_resolutions[market_id]
            
            # Check if market is closed (CLOB returns closed=True for resolved markets)
            if not resolution['closed']:
                open_markets += 1
                continue
            
            closed_markets += 1
            
            # Determine outcome index and settlement price
            outcome_index = self._get_outcome_index(outcome)
            
            # If outcome_index is None (team names or custom outcomes), try to find by matching
            if outcome_index is None:
                # Try to find matching outcome in the tokens array
                outcomes = resolution.get('outcomes', [])
                matched_idx = None
                for idx, token_outcome in enumerate(outcomes):
                    if token_outcome.lower() == outcome.lower():
                        matched_idx = idx
                        break
                
                if matched_idx is not None:
                    outcome_index = matched_idx
                else:
                    # Unknown outcome - log warning and skip
                    logger(f"Warning: unknown_outcome_for_settlement: market={market_id[:20]}, outcome={outcome}")
                    skipped_unknown_outcome += 1
                    continue
            
            # Use winners array from CLOB API to determine if our outcome won
            winners = resolution.get('winners', [])
            outcome_prices = resolution.get('outcome_prices', [])
            
            if outcome_index >= len(winners) or outcome_index >= len(outcome_prices):
                logger(f"Warning: invalid_outcome_index for settlement: market={market_id[:20]}, index={outcome_index}")
                errors += 1
                continue
            
            # Check if this outcome is the winner
            is_winner = winners[outcome_index]
            settlement_price = outcome_prices[outcome_index]
            
            if is_winner:
                # Winner settles at 1.0
                close_price = Decimal('1.0')
                close_type = 'SETTLEMENT_WIN'
            elif settlement_price >= 0.99:
                # Price at 0.99+ but not winner - rare edge case, treat as loss
                close_price = Decimal('0.0')
                close_type = 'SETTLEMENT_LOSS'
            else:
                # Loser settles at 0.0
                close_price = Decimal('0.0')
                close_type = 'SETTLEMENT_LOSS'
            
            # Calculate P&L
            # gross_pnl = (close_price - open_price) * open_size_usd
            gross_pnl = (close_price - open_price) * open_size_usd
            fees_usd = Decimal('0')  # No fees for settlement
            net_pnl = gross_pnl - fees_usd
            
            # Update roundtrip in database
            update_query = text("""
                UPDATE whale_trade_roundtrips SET
                    close_price = :close_price,
                    close_size_usd = :close_size_usd,
                    closed_at = NOW(),
                    close_type = :close_type,
                    status = 'CLOSED',
                    gross_pnl_usd = :gross_pnl_usd,
                    fees_usd = :fees_usd,
                    net_pnl_usd = :net_pnl_usd,
                    pnl_status = 'CONFIRMED',
                    matching_method = 'SETTLEMENT',
                    matching_confidence = 'HIGH',
                    updated_at = NOW()
                WHERE id = :roundtrip_id AND status = 'OPEN'
            """)
            
            with self._engine.connect() as conn:
                result = conn.execute(update_query, {
                    'close_price': float(close_price),
                    'close_size_usd': float(open_size_usd),
                    'close_type': close_type,
                    'gross_pnl_usd': float(gross_pnl),
                    'fees_usd': float(fees_usd),
                    'net_pnl_usd': float(net_pnl),
                    'roundtrip_id': rt['roundtrip_id']
                })
                conn.commit()
            
            if result.rowcount > 0:
                settled_roundtrips.append({
                    'roundtrip_id': rt['roundtrip_id'],
                    'whale_id': rt['whale_id'],
                    'wallet_address': rt['wallet_address'],
                    'market_id': market_id,
                    'outcome': outcome,
                    'open_price': open_price,
                    'open_size_usd': open_size_usd,
                    'close_price': close_price,
                    'close_type': close_type,
                    'net_pnl_usd': net_pnl,
                })
        
        logger(f"      Settled: {len(settled_roundtrips)}, Closed markets: {closed_markets}")
        logger(f"      Open markets: {open_markets}, Errors: {errors}, Skipped (unknown outcome): {skipped_unknown_outcome}")
        
        # Step 4: Update whales P&L statistics
        logger("[4/5] Updating whales P&L statistics...")
        
        whales_updated = self._update_whales_pnl(settled_roundtrips)
        logger(f"      Whales updated: {whales_updated}")
        
        # Step 5: Get final statistics
        logger("[5/5] Getting final statistics...")
        
        stats = self._get_statistics()
        
        logger("=" * 60)
        logger("ROUNDTRIP SETTLER (ARC-502-C) - Complete")
        logger("=" * 60)
        logger(f"Results:")
        logger(f"  - OPEN roundtrips checked: {len(open_roundtrips)}")
        logger(f"  - Unique markets checked: {len(market_ids)}")
        logger(f"  - Markets resolved (closed): {closed_markets}")
        logger(f"  - Markets still open: {open_markets}")
        logger(f"  - Roundtrips settled: {len(settled_roundtrips)}")
        logger(f"  - Errors: {errors}")
        logger(f"  - Whales updated: {whales_updated}")
        logger(f"  - Database stats: {stats}")
        logger("=" * 60)
        
        return {
            'checked': len(open_roundtrips),
            'unique_markets': len(market_ids),
            'settled': len(settled_roundtrips),
            'closed_markets': closed_markets,
            'open_markets': open_markets,
            'errors': errors,
            'skipped_unknown_outcome': skipped_unknown_outcome,
            'whales_updated': whales_updated,
            'stats': stats
        }
    
    def run_close_positions(self) -> Dict:
        """Run SELL → CLOSED pipeline.
        
        Processes SELL events to close OPEN roundtrips and update whale P&L.
        
        Returns:
            Dict with processing statistics
        """
        logger("=" * 60)
        logger("ROUNDTRIP BUILDER (ARC-502-B) - Closing Positions")
        logger("=" * 60)
        
        # Step 1: Fetch and group SELL events
        logger("[1/3] Fetching and grouping SELL events from whale_trades...")
        grouped_sells = self._fetch_and_group_sell_trades()
        logger(f"      Found {len(grouped_sells)} unique position groups with SELL events")
        
        # Step 2: Close OPEN roundtrips
        logger("[2/3] Closing OPEN roundtrips based on SELL events...")
        closed_roundtrips, closed_count, skipped_count = self._close_roundtrips(grouped_sells)
        logger(f"      Closed: {closed_count}, Skipped (no OPEN): {skipped_count}")
        
        # Step 3: Update whales P&L
        logger("[3/3] Updating whales P&L statistics...")
        whales_updated = self._update_whales_pnl(closed_roundtrips)
        logger(f"      Whales updated: {whales_updated}")
        
        # Get final statistics
        stats = self._get_statistics()
        
        logger("=" * 60)
        logger("ROUNDTRIP BUILDER (ARC-502-B) - Complete")
        logger("=" * 60)
        logger(f"Results:")
        logger(f"  - SELL groups processed: {len(grouped_sells)}")
        logger(f"  - Roundtrips CLOSED: {closed_count}")
        logger(f"  - Roundtrips skipped: {skipped_count}")
        logger(f"  - Whales updated: {whales_updated}")
        logger(f"  - Database stats: {stats}")
        logger("=" * 60)
        
        return {
            'sell_groups': len(grouped_sells),
            'closed': closed_count,
            'skipped': skipped_count,
            'whales_updated': whales_updated,
            'stats': stats
        }
    
    def run(self, rebuild: bool = False) -> Dict:
        """Run full build pipeline.
        
        Args:
            rebuild: If True, delete existing OPEN roundtrips and recreate
            
        Returns:
            Dict with build statistics
        """
        logger("=" * 60)
        logger("ROUNDTRIP BUILDER (ARC-502-A) - Starting")
        logger("=" * 60)
        
        # Step 1: Fetch and group BUY events
        logger("[1/4] Fetching and grouping BUY events from whale_trades...")
        grouped_trades = self._fetch_and_group_buy_trades()
        logger(f"      Found {len(grouped_trades)} unique position groups")
        
        # Step 2: Handle existing OPEN roundtrips
        if rebuild:
            logger("[2/4] REBUILD MODE: Clearing existing OPEN roundtrips...")
            deleted = self._clear_existing_open_roundtrips()
            logger(f"      Deleted {deleted} existing OPEN roundtrips")
        else:
            logger("[2/4] Checking for existing OPEN roundtrips...")
            existing_keys = self._get_existing_open_position_keys()
            logger(f"      Found {len(existing_keys)} existing OPEN roundtrips")
        
        # Step 3: Create roundtrip records
        logger("[3/4] Creating OPEN roundtrips with aggregation...")
        roundtrips, created = self._create_roundtrips(grouped_trades)
        logger(f"      Will create: {created}")
        
        # Step 4: Save to database
        if roundtrips:
            logger("[4/4] Saving to database...")
            saved = self._save_roundtrips(roundtrips)
            logger(f"      Saved {saved} records")
        else:
            logger("[4/4] No records to save")
            saved = 0
        
        # Get final statistics
        stats = self._get_statistics()
        
        logger("=" * 60)
        logger("ROUNDTRIP BUILDER (ARC-502-A) - Complete")
        logger("=" * 60)
        logger(f"Results:")
        logger(f"  - Total BUY groups processed: {len(grouped_trades)}")
        logger(f"  - NEW roundtrips created: {created}")
        logger(f"  - Database stats: {stats}")
        logger("=" * 60)
        
        # Write heartbeat file for healthcheck
        try:
            from datetime import datetime
            with open("/tmp/heartbeat", "w") as f:
                f.write(datetime.now().isoformat())
        except Exception:
            pass  # Non-critical
        
        return {
            'buy_groups': len(grouped_trades),
            'created': created,
            'saved': saved,
            'stats': stats
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Roundtrip Builder')
    parser.add_argument('--rebuild', action='store_true', 
                        help='Clear existing OPEN roundtrips and rebuild from scratch')
    parser.add_argument('--close', action='store_true',
                        help='Process SELL events to close OPEN roundtrips')
    parser.add_argument('--settle', action='store_true',
                        help='Settle OPEN roundtrips via Gamma API market resolution')
    args = parser.parse_args()
    
    database_url = get_database_url()
    builder = RoundtripBuilder(database_url=database_url)
    
    if args.settle:
        result = asyncio.run(builder.settle_roundtrips_via_gamma())
    elif args.close:
        result = builder.run_close_positions()
    else:
        result = builder.run(rebuild=args.rebuild)
    
    return result


if __name__ == "__main__":
    main()