# -*- coding: utf-8 -*-
"""Market Category Cache - LRU cache for Polymarket market categories.

Fetches market categories from Polymarket CLOB API and caches them to avoid
repeated API calls for the same market_id.

Category is extracted from the `tags[0]` field in the CLOB API response.

Example:
    >>> from src.data.storage.market_category_cache import get_market_category
    >>> category = await get_market_category("0xabc123...")
    >>> print(category)
    "Crypto"
"""

from typing import Optional

import structlog

from src.execution.polymarket.client import PolymarketClient

logger = structlog.get_logger(__name__)

# Standardized category names
VALID_CATEGORIES = frozenset([
    "Sports",
    "Weather",
    "Crypto",
    "Politics",
    "Economics",
    "Other",
])

# Primary category mapping from API tags to standardized categories
# Based on docs/API_MARKET_TYPES_AUDIT.md - Section 2.2
PRIMARY_CATEGORY_MAPPING = {
    "Sports": "Sports",
    "Weather": "Weather",
    "Crypto": "Crypto",
    "Politics": "Politics",
    "Economics": "Economics",
    "Elections": "Politics",
    "Business": "Economics",
    "Science": "Other",
    "Entertainment": "Other",
    "Technology": "Other",
    "Health": "Other",
    "World": "Politics",
    "US Politics": "Politics",
    "World Politics": "Politics",
}

# Keyword-based fallback mapping for category detection
CATEGORY_KEYWORDS = {
    "sports": "Sports",
    "weather": "Weather",
    "crypto": "Crypto",
    "bitcoin": "Crypto",
    "ethereum": "Crypto",
    "solana": "Crypto",
    "up/down": "Crypto",
    "politics": "Politics",
    "election": "Politics",
    "governor": "Politics",
    "president": "Politics",
    "congress": "Politics",
    "senate": "Politics",
    "economics": "Economics",
    "fed": "Economics",
    "interest": "Economics",
    "gdp": "Economics",
    "inflation": "Economics",
    "unemployment": "Economics",
}

# Module-level client instance for reuse
_client: Optional[PolymarketClient] = None


def _get_client() -> PolymarketClient:
    """Get or create PolymarketClient instance."""
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client


def _normalize_category(tags: list) -> Optional[str]:
    """Normalize category from API tags to standardized category.
    
    Extracts the primary category from tags[0] and maps it to
    one of the standardized categories: Sports, Weather, Crypto,
    Politics, Economics, or Other.
    
    Args:
        tags: List of tags from CLOB API (e.g., ["Crypto", "Bitcoin", "Up/Down"])
    
    Returns:
        Normalized category name or None if cannot determine
    """
    if not tags or len(tags) == 0:
        return None
    
    primary_tag = tags[0]
    if not primary_tag:
        return None
    
    # First try direct mapping
    if primary_tag in PRIMARY_CATEGORY_MAPPING:
        return PRIMARY_CATEGORY_MAPPING[primary_tag]
    
    # Try case-insensitive direct match
    for key, category in PRIMARY_CATEGORY_MAPPING.items():
        if key.lower() == primary_tag.lower():
            return category
    
    # Fall back to keyword matching on all tags
    all_tags_lower = " ".join(tags).lower()
    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in all_tags_lower:
            return category
    
    # Default to Other if no match
    logger.warning(
        "category_unmapped",
        primary_tag=primary_tag,
        all_tags=tags,
    )
    return "Other"


async def get_market_category(market_id: str) -> Optional[str]:
    """Get market category from Polymarket CLOB API with caching.

    Fetches the market category from Polymarket's CLOB API
    and caches the result to avoid repeated API calls.

    The category is extracted from the `tags[0]` field in the API response,
    then normalized to one of: Sports, Weather, Crypto, Politics, Economics, Other.

    Args:
        market_id: The market identifier (condition ID or market address)

    Returns:
        Normalized category from Polymarket API, or None if not found
    """
    if not market_id:
        return None
    
    # Check cache first (using module-level dict for async-safe caching)
    if hasattr(get_market_category, '_cache'):
        cached = get_market_category._cache.get(market_id)
        if cached is not None:
            logger.debug("market_category_cache_hit", market_id=market_id[:20])
            return cached
    else:
        get_market_category._cache = {}
    
    try:
        client = _get_client()
        market_data = await client.get_market(market_id)
        
        # Extract tags field (this is where category lives)
        tags = market_data.get("tags") if market_data else None
        
        if tags:
            category = _normalize_category(tags)
            if category:
                get_market_category._cache[market_id] = category
                logger.info(
                    "market_category_fetched",
                    market_id=market_id[:20],
                    category=category,
                    raw_tags=tags[:3],  # Log first 3 tags only
                )
            else:
                logger.warning(
                    "market_category_normalization_failed",
                    market_id=market_id[:20],
                    tags=tags,
                )
                # Cache None as well to avoid repeated failed lookups
                get_market_category._cache[market_id] = None
        else:
            logger.warning(
                "market_category_tags_not_found",
                market_id=market_id[:20],
            )
            # Cache None as well to avoid repeated failed lookups
            get_market_category._cache[market_id] = None
        
        return get_market_category._cache.get(market_id)
        
    except Exception as e:
        logger.error(
            "market_category_fetch_failed",
            market_id=market_id[:20],
            error=str(e),
        )
        return None


async def get_market_category_with_title(
    market_id: str,
) -> tuple[Optional[str], Optional[str]]:
    """Get both market category and title in a single API call.

    This is more efficient than calling get_market_category and
    get_market_title separately when both are needed.

    Args:
        market_id: The market identifier

    Returns:
        Tuple of (category, title) or (None, None) if not found
    """
    if not market_id:
        return None, None
    
    try:
        client = _get_client()
        market_data = await client.get_market(market_id)
        
        if not market_data:
            return None, None
        
        # Get category
        tags = market_data.get("tags")
        category = _normalize_category(tags) if tags else None
        
        # Get title
        title = market_data.get("question")
        
        # Cache both results
        if not hasattr(get_market_category, '_cache'):
            get_market_category._cache = {}
        
        if category:
            get_market_category._cache[market_id] = category
        
        # Note: title caching would need separate cache dict
        # This function primarily optimizes API calls
        
        return category, title
        
    except Exception as e:
        logger.error(
            "market_category_with_title_fetch_failed",
            market_id=market_id[:20],
            error=str(e),
        )
        return None, None


async def clear_cache() -> None:
    """Clear the market category cache."""
    if hasattr(get_market_category, '_cache'):
        get_market_category._cache.clear()
        logger.info("market_category_cache_cleared")


def get_cache_size() -> int:
    """Get current cache size."""
    if hasattr(get_market_category, '_cache'):
        return len(get_market_category._cache)
    return 0
