# -*- coding: utf-8 -*-
"""Research module for strategy analysis."""

from .scrapers.github import GitHubScraper
from .scrapers.twitter import TwitterScraper
from .signal_processor import SignalProcessor
from .whale_tracker import WhaleTracker, WhalePosition, WhaleTrade, WhaleStats

__all__ = [
    "GitHubScraper",
    "TwitterScraper",
    "SignalProcessor",
    "WhaleTracker",
    "WhalePosition",
    "WhaleTrade",
    "WhaleStats",
]
