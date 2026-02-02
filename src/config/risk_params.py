# -*- coding: utf-8 -*-
"""Risk management parameters."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class RiskParams:
    """Risk management configuration."""
    
    max_single_trade_drawdown: Decimal = Decimal("0.05")  # 5%
    max_daily_drawdown: Decimal = Decimal("0.02")  # 2%
    max_position_size_pct: Decimal = Decimal("0.25")  # 25%
    max_concurrent_trades: int = 10
    min_edge_bps: Decimal = Decimal("0.001")  # 10 bps
    max_api_latency_ms: int = 5000
    failed_execution_threshold: int = 3
    failed_execution_window_minutes: int = 10
