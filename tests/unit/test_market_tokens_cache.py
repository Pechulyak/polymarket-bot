# -*- coding: utf-8 -*-
"""Unit tests for market_tokens_cache.

Verifies outcome index is resolved from cached CLOB tokens[] order,
not trusted blindly, and that results are cached per market_id.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.data.storage import market_tokens_cache


CLOB_MARKET = {
    "condition_id": "0xmarket1",
    "tokens": [
        {"token_id": "TOKEN_A", "outcome": "PortlandFire"},
        {"token_id": "TOKEN_B", "outcome": "Washington Mystics"},
    ],
}


@pytest.fixture(autouse=True)
def clear_cache():
    market_tokens_cache._cache.clear()
    market_tokens_cache._client = None
    yield
    market_tokens_cache._cache.clear()
    market_tokens_cache._client = None


@pytest.mark.asyncio
async def test_resolves_index_from_token_position():
    mock_client = AsyncMock()
    mock_client.get_market.return_value = CLOB_MARKET

    with patch.object(market_tokens_cache, "_get_client", return_value=mock_client):
        assert await market_tokens_cache.get_token_outcome_index("0xmarket1", "TOKEN_A") == 0
        assert await market_tokens_cache.get_token_outcome_index("0xmarket1", "TOKEN_B") == 1


@pytest.mark.asyncio
async def test_same_token_id_always_yields_same_index():
    """Regression: identical token_id must never resolve to two different indexes."""
    mock_client = AsyncMock()
    mock_client.get_market.return_value = CLOB_MARKET

    with patch.object(market_tokens_cache, "_get_client", return_value=mock_client):
        results = [
            await market_tokens_cache.get_token_outcome_index("0xmarket1", "TOKEN_A")
            for _ in range(5)
        ]
    assert results == [0] * 5


@pytest.mark.asyncio
async def test_caches_market_lookup_across_calls():
    mock_client = AsyncMock()
    mock_client.get_market.return_value = CLOB_MARKET

    with patch.object(market_tokens_cache, "_get_client", return_value=mock_client):
        await market_tokens_cache.get_token_outcome_index("0xmarket1", "TOKEN_A")
        await market_tokens_cache.get_token_outcome_index("0xmarket1", "TOKEN_B")

    mock_client.get_market.assert_awaited_once_with("0xmarket1")


@pytest.mark.asyncio
async def test_unknown_token_returns_none():
    mock_client = AsyncMock()
    mock_client.get_market.return_value = CLOB_MARKET

    with patch.object(market_tokens_cache, "_get_client", return_value=mock_client):
        result = await market_tokens_cache.get_token_outcome_index("0xmarket1", "TOKEN_UNKNOWN")
    assert result is None


@pytest.mark.asyncio
async def test_missing_market_id_or_token_id_returns_none():
    assert await market_tokens_cache.get_token_outcome_index("", "TOKEN_A") is None
    assert await market_tokens_cache.get_token_outcome_index("0xmarket1", "") is None


@pytest.mark.asyncio
async def test_client_error_returns_none_and_does_not_raise():
    mock_client = AsyncMock()
    mock_client.get_market.side_effect = RuntimeError("api down")

    with patch.object(market_tokens_cache, "_get_client", return_value=mock_client):
        result = await market_tokens_cache.get_token_outcome_index("0xmarket1", "TOKEN_A")
    assert result is None
