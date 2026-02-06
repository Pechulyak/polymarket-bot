"""
Polymarket Hybrid Bot - Code Library

Ready-to-use Python modules for building a $100 capital trading bot.

Modules:
- polymarket_client: Polymarket CLOB API wrapper
- websocket_manager: Real-time data feeds
- copy_trading_engine: Whale following logic
- arbitrage_detector: Cross-platform opportunity detection
- risk_manager: Unified risk control
- order_executor: Trade execution (REST + Raw TX)
- telegram_alerts: Monitoring and alerting

Sources: Consolidated from 9 Level 2 repository analyses
- crypmancer/polymarket-arbitrage-copy-bot (beginner copy trading)
- hodlwarden/polymarket-arbitrage-copy-bot (advanced copy trading)
- realfishsam/prediction-market-arbitrage-bot (cross-platform arb)
- apemoonspin/polymarket-arbitrage-trading-bot (fee calculations)
- Others: cakaroni, CarlosIbCu, 0xRustElite1111, Jonmaa, coleschaffer
"""

__version__ = "1.0.0"
__author__ = "Polymarket Research Project"

from .polymarket_client import PolymarketClient
from .websocket_manager import WebSocketManager
from .copy_trading_engine import CopyTradingEngine
from .arbitrage_detector import ArbitrageDetector
from .risk_manager import RiskManager, RiskLimits
from .order_executor import OrderExecutor
from .telegram_alerts import TelegramAlerter

__all__ = [
    "PolymarketClient",
    "WebSocketManager",
    "CopyTradingEngine",
    "ArbitrageDetector",
    "RiskManager",
    "RiskLimits",
    "OrderExecutor",
    "TelegramAlerter",
]
