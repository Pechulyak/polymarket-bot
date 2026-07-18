# -*- coding: utf-8 -*-
"""Market Tokens Cache - token_id -> outcome_index mapping from CLOB markets.

The API's per-trade outcomeIndex field can disagree with token_id for the
same trade. Token order in CLOB /markets/{condition_id}.tokens[] is ground
truth and immutable per market, so it is cached and used instead of trusting
outcomeIndex per trade.
"""

from typing import Dict, Optional

import structlog

from src.execution.polymarket.client import PolymarketClient

logger = structlog.get_logger(__name__)

_client: Optional[PolymarketClient] = None
_cache: Dict[str, Dict[str, int]] = {}


def _get_client() -> PolymarketClient:
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client


async def get_token_outcome_index(market_id: str, token_id: str) -> Optional[int]:
    """Resolve a token's outcome index (0/1) via cached CLOB market tokens.

    Returns None if market_id/token_id is missing, the market lookup fails,
    or token_id is not found in the market's tokens — callers should fall
    back to the API's outcomeIndex field in that case.
    """
    if not market_id or not token_id:
        return None

    index_map = _cache.get(market_id)
    if index_map is None:
        try:
            client = _get_client()
            market_data = await client.get_market(market_id)
            index_map = {
                t["token_id"]: i
                for i, t in enumerate((market_data or {}).get("tokens", []))
                if t.get("token_id")
            }
        except Exception as e:
            logger.warning("market_tokens_fetch_failed", market_id=market_id[:20], error=str(e))
            index_map = {}
        _cache[market_id] = index_map

    return index_map.get(token_id)
