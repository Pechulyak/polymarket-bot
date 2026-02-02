# -*- coding: utf-8 -*-
"""Research module for strategy analysis."""

from .scrapers.github import GitHubScraper
from .scrapers.twitter import TwitterScraper
from .signal_processor import SignalProcessor

__all__ = ["GitHubScraper", "TwitterScraper", "SignalProcessor"]
