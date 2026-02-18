# -*- coding: utf-8 -*-
"""Research module for strategy analysis."""

from .whale_tracker import WhaleTracker, WhalePosition, WhaleTrade, WhaleStats

# Temporarily disabled due to import issues
# from .real_time_whale_monitor import (
#     RealTimeWhaleMonitor,
#     WhaleTradeSignal,
#     MonitorStats,
# )
# from .whale_detector import WhaleDetector, DetectedWhale, DetectionConfig

__all__ = [
    "WhaleTracker",
    "WhalePosition",
    "WhaleTrade",
    "WhaleStats",
    # "RealTimeWhaleMonitor",
    # "WhaleTradeSignal",
    # "MonitorStats",
    # "WhaleDetector",
    # "DetectedWhale",
    # "DetectionConfig",
]
