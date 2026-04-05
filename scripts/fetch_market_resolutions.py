"""
PHASE3-003: Fetch market resolution data from CLOB API and write to market_resolutions table.
This is a data pipeline script - does NOT call settle_resolved_positions() or update whale_trade_roundtrips.
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

import psycopg2
import requests


# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# Configuration
CLOB_API_BASE_URL = "https://clob.polymarket.com/markets"
REQUEST_TIMEOUT = 10  # seconds
RATE_LIMIT_DELAY = 0.3  # seconds between requests


def get_db_connection() -> psycopg2.extensions.connection:
    """Get database connection from environment variables."""
    # Try DATABASE_URL first
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        return psycopg2.connect(db_url)
    
    # Fall back to individual connection parameters
    host = os.environ.get('POSTGRES_HOST', 'localhost')
    port = os.environ.get('POSTGRES_PORT', '5432')
    dbname = os.environ.get('POSTGRES_DB', 'polymarket')
    user = os.environ.get('POSTGRES_USER', 'postgres')
    password = os.environ.get('POSTGRES_PASSWORD', 'password')
    
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password
    )


def get_open_market_ids(conn: psycopg2.extensions.connection) -> list:
    """Get distinct open market_ids from whale_trade_roundtrips."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT market_id 
            FROM whale_trade_roundtrips 
            WHERE status = 'OPEN'
        """)
        return [row[0] for row in cur.fetchall()]


def fetch_market_from_clob(market_id: str) -> Tuple[Optional[dict], Optional[str]]:
    """
    Fetch market data from CLOB API.
    Returns: (response_data, error_message)
    """
    url = f"{CLOB_API_BASE_URL}/{market_id}"
    
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        
        if response.status_code >= 400:
            return None, f"HTTP {response.status_code}: {response.text[:200]}"
        
        return response.json(), None
        
    except requests.exceptions.Timeout:
        return None, f"Timeout after {REQUEST_TIMEOUT}s"
    except requests.exceptions.RequestException as e:
        return None, f"Request error: {str(e)[:100]}"
    except json.JSONDecodeError as e:
        return None, f"JSON decode error: {str(e)[:100]}"


def parse_market_response(data: dict) -> dict:
    """
    Parse CLOB API response.
    Returns dict with: is_closed, winner_outcome, winner_index, tokens
    """
    is_closed = data.get('closed', False)
    tokens = data.get('tokens', [])
    
    winner_outcome = None
    winner_index = None
    if is_closed and tokens:
        for i, token in enumerate(tokens):
            if token.get('winner') is True:
                winner_outcome = token.get('outcome')
                winner_index = i
                break
    
    return {
        'is_closed': is_closed,
        'winner_outcome': winner_outcome,
        'winner_index': winner_index,
        'tokens': tokens
    }


def upsert_market_resolution(
    conn: psycopg2.extensions.connection,
    market_id: str,
    is_closed: bool,
    winner_outcome: Optional[str],
    winner_index: Optional[int],
    tokens: list
) -> Tuple[bool, bool]:
    """
    Insert or update market_resolutions table.
    Returns: (was_inserted, was_already_resolved)
    
    - was_inserted: True if new row inserted
    - was_already_resolved: True if market was already resolved before this call
    """
    # Determine resolved_at
    resolved_at = None
    was_already_resolved = False
    
    # Check if market was already resolved
    with conn.cursor() as cur:
        cur.execute("""
            SELECT resolved_at FROM market_resolutions 
            WHERE market_id = %s AND resolved_at IS NOT NULL
        """, (market_id,))
        existing = cur.fetchone()
        if existing and existing[0]:
            was_already_resolved = True
            resolved_at = existing[0]  # Keep existing resolved_at
    
    # If closed AND has winner AND not already resolved, set resolved_at to NOW()
    if is_closed and winner_outcome and not was_already_resolved:
        resolved_at = datetime.now(timezone.utc)
    
    # Convert tokens to JSON string for JSONB column
    tokens_json = json.dumps(tokens)
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO market_resolutions 
                (market_id, is_closed, winner_outcome, winner_index, tokens, fetched_at, resolved_at)
            VALUES (%s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (market_id) DO UPDATE SET
                is_closed = EXCLUDED.is_closed,
                winner_outcome = EXCLUDED.winner_outcome,
                winner_index = EXCLUDED.winner_index,
                tokens = EXCLUDED.tokens,
                fetched_at = NOW(),
                resolved_at = COALESCE(EXCLUDED.resolved_at, market_resolutions.resolved_at)
        """, (market_id, is_closed, winner_outcome, winner_index, tokens_json, resolved_at))
    
    conn.commit()
    
    # Check if this was a new resolution (not previously resolved)
    is_new_resolution = is_closed and winner_outcome and not was_already_resolved
    
    return not was_already_resolved, is_new_resolution


def run():
    """Main execution function."""
    logger.info("[fetch_market_resolutions] Starting...")
    
    # Connect to database
    try:
        conn = get_db_connection()
    except Exception as e:
        logger.error(f"[fetch_market_resolutions] DB connection failed: {e}")
        sys.exit(1)
    
    # Get open markets
    try:
        open_markets = get_open_market_ids(conn)
    except Exception as e:
        logger.error(f"[fetch_market_resolutions] Failed to get open markets: {e}")
        conn.close()
        sys.exit(1)
    
    logger.info(f"[fetch_market_resolutions] Start: {len(open_markets)} open markets to check")
    
    # Stats counters
    stats = {
        'checked': 0,
        'resolved': 0,
        'already_resolved': 0,
        'errors': 0
    }
    
    # Process each market
    for market_id in open_markets:
        stats['checked'] += 1
        
        # Rate limiting
        if stats['checked'] > 1:
            time.sleep(RATE_LIMIT_DELAY)
        
        # Fetch from CLOB API
        data, error = fetch_market_from_clob(market_id)
        
        if error:
            logger.warning(f"[fetch_market_resolutions] Market {market_id}: {error}")
            stats['errors'] += 1
            continue
        
        # Parse response
        parsed = parse_market_response(data)
        
        # Write to DB
        try:
            was_already_resolved, is_new_resolution = upsert_market_resolution(
                conn,
                market_id,
                parsed['is_closed'],
                parsed['winner_outcome'],
                parsed['winner_index'],
                parsed['tokens']
            )
            
            if is_new_resolution:
                logger.info(f"[fetch_market_resolutions] Resolved: market_id={market_id} winner={parsed['winner_outcome']} winner_index={parsed['winner_index']}")
                stats['resolved'] += 1
            elif was_already_resolved:
                stats['already_resolved'] += 1
                
        except Exception as e:
            logger.error(f"[fetch_market_resolutions] DB error for {market_id}: {e}")
            stats['errors'] += 1
            continue
    
    # Close DB connection
    conn.close()
    
    # Final stats
    logger.info(
        f"[fetch_market_resolutions] Done: checked={stats['checked']}, "
        f"resolved={stats['resolved']}, already_resolved={stats['already_resolved']}, errors={stats['errors']}"
    )


if __name__ == "__main__":
    run()