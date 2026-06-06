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
    
    
"""

import os
import sys
import argparse

from decimal import Decimal
from typing import Dict, List, Optional, Tuple
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
            LEFT JOIN whales w ON w.wallet_address = wt.wallet_address
            WHERE wt.side = 'buy'
              AND wt.traded_at > NOW() - INTERVAL '30 days'
              AND (w.copy_status IS NULL OR w.copy_status != 'excluded')
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
            LEFT JOIN whales w ON w.wallet_address = wt.wallet_address
            WHERE wt.side = 'sell'
              AND wt.traded_at > NOW() - INTERVAL '30 days'
              AND (w.copy_status IS NULL OR w.copy_status != 'excluded')
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
                    'wallet_address': row[0],
                    'position_key': position_key,
                    'market_id': row[1],
                    'outcome': row[2],
                }
        
        return grouped
    
    def _close_roundtrips(self, grouped_sells: Dict[str, Dict], sentinel_method: str | None = None) -> Tuple[List[Dict], int, int, int]:
        """Close OPEN roundtrips based on SELL events.
        
        Args:
            grouped_sells: Dict of aggregated SELL data by position_key
            sentinel_method: Override matching_method for dry-run sentinel mode
        
        Returns:
            Tuple of (closed_roundtrips list, direct_count, fuzzy_count, skipped_count)
        """
        closed_roundtrips = []
        direct_count = 0
        fuzzy_count = 0
        skipped_count = 0
        
        # RF-003: Use CTE with ROW_NUMBER() for temporal ordering instead of MAX(wt.id)
        # RF-001: Add temporal filter wt.traded_at > rt.opened_at
        for position_key, close_data in grouped_sells.items():
            # Find OPEN roundtrips for this position_key using ROW_NUMBER() for exact match
            # Query consolidation: all 9 fields in single CTE, no separate rt_query/rt_pnl_query
            ranked_query = text("""
                WITH ranked_sells AS (
                    SELECT 
                        rt.id              AS roundtrip_id,
                        rt.whale_id        AS whale_id,
                        rt.outcome         AS open_outcome,
                        rt.open_price      AS open_price,
                        rt.open_size_usd   AS open_size_usd,
                        wt.id              AS sell_trade_id,
                        wt.traded_at       AS sell_traded_at,
                        wt.price           AS sell_price,
                        wt.size_usd        AS sell_size_usd,
                        ROW_NUMBER() OVER (
                            PARTITION BY rt.id 
                            ORDER BY wt.traded_at DESC, wt.id DESC
                        ) AS rn
                    FROM whale_trade_roundtrips rt
                    JOIN whale_trades wt 
                        ON wt.market_id      = rt.market_id
                       AND wt.outcome        = rt.outcome
                       AND wt.wallet_address = rt.wallet_address
                       AND wt.side           = 'sell'
                       AND wt.traded_at      > rt.opened_at
                    WHERE rt.position_key = :position_key
                      AND rt.close_type IS NULL
                      AND rt.opened_at IS NOT NULL
                )
                SELECT 
                    roundtrip_id, whale_id, open_outcome, open_price, open_size_usd,
                    sell_trade_id, sell_traded_at, sell_price, sell_size_usd
                FROM ranked_sells 
                WHERE rn = 1
            """)
            
            with self._engine.connect() as conn:
                result = conn.execute(ranked_query, {"position_key": position_key})
                row = result.fetchone()
            
            # RF-012: Fuzzy fallback per §16.2 C2.b
            if row is None:
                fuzzy_query = text("""
                    WITH ranked_fuzzy_sells AS (
                        SELECT 
                            rt.id              AS roundtrip_id,
                            rt.whale_id        AS whale_id,
                            rt.outcome         AS open_outcome,
                            rt.open_price      AS open_price,
                            rt.open_size_usd   AS open_size_usd,
                            wt.id              AS sell_trade_id,
                            wt.traded_at       AS sell_traded_at,
                            wt.price           AS sell_price,
                            wt.size_usd        AS sell_size_usd,
                            ROW_NUMBER() OVER (
                                PARTITION BY rt.id 
                                ORDER BY wt.traded_at DESC, wt.id DESC
                            ) AS rn
                        FROM whale_trade_roundtrips rt
                        JOIN whale_trades wt 
                            ON wt.market_id      = rt.market_id
                           AND wt.outcome        = rt.outcome
                           AND wt.wallet_address = rt.wallet_address
                           AND wt.side           = 'sell'
                           AND wt.traded_at      > rt.opened_at
                        WHERE rt.wallet_address = :wallet_address
                          AND rt.market_id      = :market_id
                          AND rt.outcome        = :outcome
                          AND rt.close_type IS NULL
                          AND rt.opened_at IS NOT NULL
                    )
                    SELECT 
                        roundtrip_id, whale_id, open_outcome, open_price, open_size_usd,
                        sell_trade_id, sell_traded_at, sell_price, sell_size_usd
                    FROM ranked_fuzzy_sells
                    ORDER BY sell_traded_at DESC
                    LIMIT 1
                """)
                with self._engine.connect() as conn:
                    fuzzy_result = conn.execute(fuzzy_query, {
                        "wallet_address": close_data['wallet_address'],
                        "market_id": close_data['market_id'],
                        "outcome": close_data['outcome'],
                    })
                    row = fuzzy_result.fetchone()
                matched_via_fuzzy = (row is not None)
            else:
                matched_via_fuzzy = False
            
            if row is None:
                # No matching OPEN roundtrip
                logger(f"INFO: close_match_skipped: position_key={position_key} reason='no matching OPEN roundtrip'")
                skipped_count += 1
                continue
            
            # All 9 fields from consolidated query
            (roundtrip_id, whale_id, open_outcome, open_price, open_size_usd,
             close_trade_id, closed_at, close_price, close_size) = row
            
            if matched_via_fuzzy:
                fuzzy_count += 1
                logger(f"WARNING: close_match_fuzzy: position_key={position_key} roundtrip_id={roundtrip_id} sell_trade_id={close_trade_id} reason='exact match failed'")
            else:
                direct_count += 1
                logger(f"INFO: close_match_direct: position_key={position_key} roundtrip_id={roundtrip_id} sell_trade_id={close_trade_id}")
            
            # Calculate P&L
            # gross_pnl = (close_price - open_price) * close_size
            # Note: prices are in 0-1 range (e.g., 0.65 for 65%)
            if open_price is not None and open_size_usd is not None:
                gross_pnl = (float(close_price) - float(open_price)) * float(close_size)
            else:
                gross_pnl = 0
            fees_usd = 0  # No fee data available
            net_pnl = gross_pnl - fees_usd
            
            # RF-012: Ternary labels per spec
            # sentinel_method overrides the default DIRECT_SELL/FUZZY_FLIP literals for dry-run
            matching_method = sentinel_method if sentinel_method else ('FUZZY_FLIP' if matched_via_fuzzy else 'DIRECT_SELL')
            matching_confidence = 'LOW' if matched_via_fuzzy else 'HIGH'
            pnl_status = 'ESTIMATED' if matched_via_fuzzy else 'EXACT'
            
            # Update roundtrip - RF-004: Fill close_trade_id, close_side, close_size_usd, fees_usd
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
                    matching_method = :matching_method,
                    matching_confidence = :matching_confidence,
                    updated_at = NOW()
                WHERE id = :id
            """)
            
            with self._engine.connect() as conn:
                result = conn.execute(update_query, {
                    'close_trade_id': close_trade_id,
                    'close_price': close_price,
                    'close_size_usd': close_size,
                    'closed_at': closed_at,
                    'gross_pnl_usd': gross_pnl,
                    'fees_usd': fees_usd,
                    'net_pnl_usd': net_pnl,
                    'pnl_status': pnl_status,
                    'matching_method': matching_method,
                    'matching_confidence': matching_confidence,
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
        
        # RF-012: Summary logging
        logger(
            f"INFO: close_roundtrips_summary: "
            f"total_groups={len(grouped_sells)} "
            f"direct={direct_count} "
            f"fuzzy={fuzzy_count} "
            f"skipped={skipped_count}"
        )
        
        return closed_roundtrips, direct_count, fuzzy_count, skipped_count
    
    def run_close_positions(self, sentinel_method: str | None = None) -> Dict:
        """Run SELL → CLOSED pipeline.
        
        Processes SELL events to close OPEN roundtrips and update whale P&L.
        
        Args:
            sentinel_method: Override matching_method for dry-run sentinel mode.
                           If set, uses this value instead of 'DIRECT_SELL' or 'FUZZY_FLIP'.
        
        Returns:
            Dict with processing statistics
        """
        logger("=" * 60)
        logger("ROUNDTRIP BUILDER (ARC-502-B) - Closing Positions")
        logger("=" * 60)
        
        # Step 1: Fetch and group SELL events
        logger("[1/2] Fetching and grouping SELL events...")
        grouped_sells = self._fetch_and_group_sell_trades()
        logger(f"      Found {len(grouped_sells)} unique position groups with SELL events")
        
        # Step 2: Close OPEN roundtrips
        logger("[2/2] Closing OPEN roundtrips based on SELL events...")
        closed_roundtrips, direct_count, fuzzy_count, skipped_count = self._close_roundtrips(grouped_sells, sentinel_method=sentinel_method)
        logger(f"      Closed: {direct_count} (direct={direct_count}, fuzzy={fuzzy_count}), Skipped (no OPEN): {skipped_count}")
        
        # Get final statistics
        stats = self._get_statistics()
        
        logger("=" * 60)
        logger("ROUNDTRIP BUILDER (ARC-502-B) - Complete")
        logger("=" * 60)
        logger(f"Results:")
        logger(f"  - SELL groups processed: {len(grouped_sells)}")
        logger(f"  - Roundtrips CLOSED: {direct_count + fuzzy_count} (direct={direct_count}, fuzzy={fuzzy_count})")
        logger(f"  - Roundtrips skipped: {skipped_count}")
        logger(f"  - Database stats: {stats}")
        logger("=" * 60)
        
        return {
            'sell_groups': len(grouped_sells),
            'closed': direct_count + fuzzy_count,
            'closed_direct': direct_count,
            'closed_fuzzy': fuzzy_count,
            'skipped': skipped_count,
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
    parser.add_argument('--sentinel-method', type=str, default=None,
                        help='Force matching_method tag on closures (forensics/backfill only, e.g. MANUAL_RUN_TRD443). Production should not set this.')
    args = parser.parse_args()
    
    # Validate sentinel_method if provided
    if args.sentinel_method is not None and args.sentinel_method != 'MANUAL_RUN_TRD443':
        sys.exit(1)
    
    database_url = get_database_url()
    builder = RoundtripBuilder(database_url=database_url)
    
    if args.close:
        result = builder.run_close_positions(sentinel_method=args.sentinel_method)
    else:
        result = builder.run(rebuild=args.rebuild)
    
    return result


if __name__ == "__main__":
    main()