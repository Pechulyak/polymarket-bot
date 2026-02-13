# -*- coding: utf-8 -*-
"""Research module for strategy analysis."""

from .scrapers.github import GitHubScraper
from .scrapers.twitter import TwitterScraper
from .signal_processor import SignalProcessor
from .whale_tracker import WhaleTracker, WhalePosition, WhaleTrade, WhaleStats
from .real_time_whale_monitor import (
    RealTimeWhaleMonitor,
    WhaleTradeSignal,
    MonitorStats,
)

__all__ = [
    "GitHubScraper",
    "TwitterScraper",
    "SignalProcessor",
    "WhaleTracker",
    "WhalePosition",
    "WhaleTrade",
    "WhaleStats",
    "RealTimeWhaleMonitor",
    "WhaleTradeSignal",
    "MonitorStats",
]
