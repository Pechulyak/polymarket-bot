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
            INNER JOIN whales w ON wt.whale_id = w.id
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
    args = parser.parse_args()
    
    database_url = get_database_url()
    builder = RoundtripBuilder(database_url=database_url)
    result = builder.run(rebuild=args.rebuild)
    return result


if __name__ == "__main__":
    main()