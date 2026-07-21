# -*- coding: utf-8 -*-
"""Тест env-флага WHALE_DISCOVERY_ENABLED: гейт широкого discovery в WhaleDetector.start()."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.research.whale_detector import WhaleDetector, DetectionConfig


def _make_detector():
    det = WhaleDetector.__new__(WhaleDetector)  # без __init__ (без БД/клиента)
    det._running = False
    det.polymarket_client = MagicMock()          # truthy — ветка discovery достижима
    det.database_url = None                       # отключает category_backfill_loop
    # заглушки корутин, вызываемых в start()
    det._cleanup_loop = AsyncMock()
    det._load_known_whales = AsyncMock()
    det._bootstrap_existing_whales = AsyncMock()
    det.start_polymarket_polling = AsyncMock()
    det._paper_poll_loop = AsyncMock()
    det._tracked_poll_loop = AsyncMock()
    return det


@pytest.mark.parametrize("flag,expect_called", [
    ("false", False),
    ("False", False),
    ("true", True),
    (None, True),          # дефолт — discovery включён
])
def test_discovery_flag_gates_polling(monkeypatch, flag, expect_called):
    if flag is None:
        monkeypatch.delenv("WHALE_DISCOVERY_ENABLED", raising=False)
    else:
        monkeypatch.setenv("WHALE_DISCOVERY_ENABLED", flag)

    det = _make_detector()
    asyncio.run(det.start())

    assert det.start_polymarket_polling.called is expect_called
    # таргетированные поллеры стартуют ВСЕГДА, независимо от флага
    assert det._paper_poll_loop.called
    assert det._tracked_poll_loop.called