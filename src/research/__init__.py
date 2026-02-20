# -*- coding: utf-8 -*-
"""Research module for strategy analysis."""

from .polymarket_data_client import (
    PolymarketDataClient,
    TradeWithAddress,
    AggregatedTraderStats,
    PolymarketDataError,
    create_polymarket_data_client,
)
from .whale_tracker import WhaleTracker, WhalePosition, WhaleTrade, WhaleStats
from .whale_detector import (
    WhaleDetector,
    DetectedWhale,
    DetectionConfig,
    TradeRecord,
)

__all__ = [
    "PolymarketDataClient",
    "TradeWithAddress",
    "AggregatedTraderStats",
    "PolymarketDataError",
    "create_polymarket_data_client",
    "WhaleTracker",
    "WhalePosition",
    "WhaleTrade",
    "WhaleStats",
    "WhaleDetector",
    "DetectedWhale",
    "DetectionConfig",
    "TradeRecord",
]
