# -*- coding: utf-8 -*-
"""Metrics collection for Prometheus monitoring."""

import os
from decimal import Decimal
from typing import Dict, Optional

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = None


class Metrics:
    """Prometheus metrics for trading bot."""

    def __init__(self, enabled: bool = True, port: int = 9090):
        """Initialize metrics.

        Args:
            enabled: Whether to enable metrics collection
            port: Port to expose metrics on
        """
        self.enabled = (
            enabled and os.getenv("METRICS_ENABLED", "true").lower() == "true"
        )
        self.port = port

        if self.enabled:
            self._init_metrics()
            self._start_server()
        else:
            logger = self._get_logger()
            logger.info("metrics_disabled")

    def _get_logger(self):
        global logger
        if logger is None:
            import structlog

            logger = structlog.get_logger(__name__)
        return logger

    def _init_metrics(self):
        """Initialize Prometheus metrics."""
        self.balance = Gauge(
            "polymarket_balance",
            "Current account balance in USD",
        )

        self.total_trades = Counter(
            "polymarket_trades_total",
            "Total number of trades executed",
            ["side", "status"],
        )

        self.daily_pnl = Gauge(
            "polymarket_daily_pnl",
            "Daily profit/loss in USD",
        )

        self.total_pnl = Gauge(
            "polymarket_total_pnl",
            "Total profit/loss in USD",
        )

        self.win_rate = Gauge(
            "polymarket_win_rate",
            "Win rate as percentage",
        )

        self.errors = Counter(
            "polymarket_errors_total",
            "Total number of errors",
            ["type"],
        )

        self.whale_signals = Counter(
            "polymarket_whale_signals_total",
            "Total whale signals detected",
            ["quality"],
        )

        self.positions_open = Gauge(
            "polymarket_positions_open",
            "Number of currently open positions",
        )

        self.execution_time = Histogram(
            "polymarket_execution_time_seconds",
            "Trade execution time in seconds",
            ["side"],
        )

        self.api_latency = Histogram(
            "polymarket_api_latency_seconds",
            "API call latency in seconds",
            ["endpoint"],
        )

    def _start_server(self):
        """Start Prometheus metrics server."""
        try:
            start_http_server(self.port)
            self._get_logger().info("metrics_server_started", port=self.port)
        except Exception as e:
            self._get_logger().error("metrics_server_failed", error=str(e))

    def update_balance(self, balance: float) -> None:
        """Update balance metric."""
        if self.enabled:
            self.balance.set(balance)

    def record_trade(self, side: str, status: str = "success") -> None:
        """Record a trade."""
        if self.enabled:
            self.total_trades.labels(side=side, status=status).inc()

    def update_pnl(self, daily: float, total: float) -> None:
        """Update PnL metrics."""
        if self.enabled:
            self.daily_pnl.set(daily)
            self.total_pnl.set(total)

    def update_win_rate(self, win_rate: float) -> None:
        """Update win rate metric."""
        if self.enabled:
            self.win_rate.set(win_rate)

    def record_error(self, error_type: str) -> None:
        """Record an error."""
        if self.enabled:
            self.errors.labels(type=error_type).inc()

    def record_whale_signal(self, quality: str = "low") -> None:
        """Record a whale signal."""
        if self.enabled:
            self.whale_signals.labels(quality=quality).inc()

    def update_positions(self, count: int) -> None:
        """Update open positions count."""
        if self.enabled:
            self.positions_open.set(count)

    def record_execution_time(self, side: str, seconds: float) -> None:
        """Record trade execution time."""
        if self.enabled:
            self.execution_time.labels(side=side).observe(seconds)

    def record_api_latency(self, endpoint: str, seconds: float) -> None:
        """Record API call latency."""
        if self.enabled:
            self.api_latency.labels(endpoint=endpoint).observe(seconds)


metrics = Metrics()
