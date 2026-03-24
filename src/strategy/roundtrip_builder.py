# -*- coding: utf-8 -*-
"""Roundtrip Builder - Create OPEN roundtrips from whale BUY events with aggregation.

This module provides roundtrip creation logic with BUY event aggregation:
- Group all BUY events by position_key (wallet_address + market_id + outcome)
- Aggregate into single OPEN position per unique position_key
- Calculate weighted average price and total size
- Track first purchase timestamp as opened_at

Task: TRD-412 / ARC-502-A

Usage:
    # Normal run (skip duplicates, keep existing):
    python -m src.strategy.roundtrip_builder
    
    # Rebuild all OPEN positions from scratch:
    python -m src.strategy.roundtrip_builder --rebuild
"""

import os
import sys
import argparse
from decimal import Decimal
from typing import Dict, List, Tuple
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = print


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
                # Paper trade - not linked
                'paper_trade_id': None,
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
            # Find OPEN roundtrip for this position_key
            query = text("""
                SELECT 
                    id, whale_id, open_price, open_size_usd, status
                FROM whale_trade_roundtrips
                WHERE position_key = :position_key AND status = 'OPEN'
                LIMIT 1
            """)
            
            with self._engine.connect() as conn:
                result = conn.execute(query, {"position_key": position_key})
                row = result.fetchone()
            
            if not row:
                skipped_keys.append(position_key)
                skipped_count += 1
                continue
            
            roundtrip_id, whale_id, open_price, open_size_usd, status = row
            
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
                    matching_method = 'DIRECT_SELL',
                    matching_confidence = 'HIGH',
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
        
        # Log skipped keys
        if skipped_keys:
            logger(f"      Warning: {len(skipped_keys)} SELL events without matching OPEN roundtrip")
            for key in skipped_keys[:10]:  # Log first 10
                logger(f"        - {key}")
        
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
        
        # Group by whale_id
        whale_updates = {}
        for rt in closed_roundtrips:
            whale_id = rt['whale_id']
            if whale_id not in whale_updates:
                whale_updates[whale_id] = {
                    'whale_id': whale_id,
                    'wins': 0,
                    'losses': 0,
                    'roundtrips': 0,
                    'total_pnl': Decimal('0')
                }
            
            whale_updates[whale_id]['roundtrips'] += 1
            whale_updates[whale_id]['total_pnl'] += rt['net_pnl_usd']
            
            if rt['net_pnl_usd'] > 0:
                whale_updates[whale_id]['wins'] += 1
            else:
                whale_updates[whale_id]['losses'] += 1
        
        # Update each whale
        updated_count = 0
        for whale_id, data in whale_updates.items():
            # Calculate new values
            query = text("""
                SELECT 
                    win_count, 
                    loss_count, 
                    total_roundtrips, 
                    total_pnl_usd
                FROM whales
                WHERE id = :whale_id
            """)
            
            with self._engine.connect() as conn:
                result = conn.execute(query, {"whale_id": whale_id})
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
                WHERE id = :whale_id
            """)
            
            with self._engine.connect() as conn:
                result = conn.execute(update_query, {
                    'win_count': new_win_count,
                    'loss_count': new_loss_count,
                    'total_roundtrips': new_total_roundtrips,
                    'total_pnl_usd': new_total_pnl,
                    'avg_pnl_usd': new_avg_pnl,
                    'win_rate_confirmed': new_win_rate,
                    'whale_id': whale_id
                })
                conn.commit()
            
            if result.rowcount > 0:
                updated_count += 1
        
        return updated_count
    
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
    args = parser.parse_args()
    
    database_url = get_database_url()
    builder = RoundtripBuilder(database_url=database_url)
    
    if args.close:
        result = builder.run_close_positions()
    else:
        result = builder.run(rebuild=args.rebuild)
    
    return result


if __name__ == "__main__":
    main()