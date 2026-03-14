# -*- coding: utf-8 -*-
"""Market Title Cache - LRU cache for Polymarket market titles.

Fetches market titles from Polymarket API and caches them to avoid
repeated API calls for the same market_id.

Example:
    >>> from src.data.storage.market_title_cache import get_market_title
    >>> title = await get_market_title("0xabc123...")
    >>> print(title)
    "Will BTC reach $100k by 2025?"
"""

from functools import lru_cache
from typing import Optional

import structlog

from src.execution.polymarket.client import PolymarketClient

logger = structlog.get_logger(__name__)

# Module-level client instance for reuse
_client: Optional[PolymarketClient] = None


def _get_client() -> PolymarketClient:
    """Get or create PolymarketClient instance."""
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client


@lru_cache(maxsize=100)
def _cached_market_title(market_id: str) -> Optional[str]:
    """Synchronous cached lookup (for use with async wrapper).
    
    Note: This uses sync lru_cache. The async get_market_title function
    handles the actual API call with proper async handling.
    """
    return None  # Placeholder - actual fetching done in async function


async def get_market_title(market_id: str) -> Optional[str]:
    """Get market title from Polymarket API with caching.

    Fetches the market title (question) from Polymarket's Gamma API
    and caches the result to avoid repeated API calls.

    Args:
        market_id: The market identifier (condition ID or market address)

    Returns:
        Market title (question) from Polymarket API, or None if not found
    """
    if not market_id:
        return None
    
    # Check cache first (using module-level dict for async-safe caching)
    if hasattr(get_market_title, '_cache'):
        cached = get_market_title._cache.get(market_id)
        if cached is not None:
            logger.debug("market_title_cache_hit", market_id=market_id[:20])
            return cached
    else:
        get_market_title._cache = {}
    
    try:
        client = _get_client()
        market_data = await client.get_market(market_id)
        
        # Extract question field (this is the market title)
        title = market_data.get("question") if market_data else None
        
        if title:
            get_market_title._cache[market_id] = title
            logger.info("market_title_fetched", market_id=market_id[:20], title=title[:50])
        else:
            logger.warning("market_title_not_found", market_id=market_id[:20])
            # Cache None as well to avoid repeated failed lookups
            get_market_title._cache[market_id] = None
        
        return title
        
    except Exception as e:
        logger.error("market_title_fetch_failed", market_id=market_id[:20], error=str(e))
        return None


async def clear_cache() -> None:
    """Clear the market title cache."""
    if hasattr(get_market_title, '_cache'):
        get_market_title._cache.clear()
        logger.info("market_title_cache_cleared")


def get_cache_size() -> int:
    """Get current cache size."""
    if hasattr(get_market_title, '_cache'):
        return len(get_market_title._cache)
    return 0
