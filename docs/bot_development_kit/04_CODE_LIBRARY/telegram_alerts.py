"""
Telegram Alerts - Monitoring and Notification System

Real-time alerts for trade execution, errors, and daily summaries.

Sources:
- Multiple analyses (common alerting patterns)

Usage:
    from telegram_alerts import TelegramAlerter

    alerter = TelegramAlerter(
        bot_token="YOUR_BOT_TOKEN",
        chat_id="YOUR_CHAT_ID"
    )

    # Send trade alert
    await alerter.trade_executed(
        strategy="copy",
        market="Trump 2024",
        side="BUY",
        size=10.0,
        price=0.55
    )

    # Send error alert
    await alerter.error("WebSocket disconnected", priority="high")
"""

import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import aiohttp
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class Priority(Enum):
    """Alert priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AlertConfig:
    """Alert configuration"""
    enabled: bool = True
    min_priority: Priority = Priority.LOW
    rate_limit_seconds: int = 1
    daily_summary_hour: int = 0  # UTC hour for daily summary


class TelegramAlerter:
    """
    Telegram Alert System

    Sends real-time notifications for:
    - Trade executions
    - Errors and warnings
    - Kill switch triggers
    - Daily summaries
    - Position updates
    """

    TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

    # Priority emojis
    PRIORITY_EMOJI = {
        Priority.LOW: "",
        Priority.NORMAL: "",
        Priority.HIGH: "",
        Priority.CRITICAL: ""
    }

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        config: Optional[AlertConfig] = None
    ):
        """
        Initialize Telegram Alerter

        Args:
            bot_token: Telegram bot token from @BotFather
            chat_id: Target chat/channel ID
            config: Optional alert configuration
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.config = config or AlertConfig()

        # Rate limiting
        self._last_send_time: float = 0
        self._session: Optional[aiohttp.ClientSession] = None

        # Statistics
        self.stats = {
            "messages_sent": 0,
            "errors": 0,
            "rate_limited": 0
        }

        logger.info("TelegramAlerter initialized")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close the alerter session"""
        if self._session and not self._session.closed:
            await self._session.close()

    # ==================== Core Send Method ====================

    async def send(
        self,
        message: str,
        priority: Priority = Priority.NORMAL,
        parse_mode: str = "HTML"
    ) -> bool:
        """
        Send a message to Telegram

        Args:
            message: Message text (supports HTML)
            priority: Alert priority
            parse_mode: "HTML" or "Markdown"

        Returns:
            True if sent successfully
        """
        if not self.config.enabled:
            return False

        # Check minimum priority
        if priority.value < self.config.min_priority.value:
            return False

        # Rate limiting
        import time
        now = time.time()
        if now - self._last_send_time < self.config.rate_limit_seconds:
            self.stats["rate_limited"] += 1
            await asyncio.sleep(self.config.rate_limit_seconds)

        self._last_send_time = time.time()

        # Add priority emoji
        emoji = self.PRIORITY_EMOJI.get(priority, "")
        formatted_message = f"{emoji} {message}" if emoji else message

        # Send via API
        try:
            session = await self._get_session()
            url = self.TELEGRAM_API.format(
                token=self.bot_token,
                method="sendMessage"
            )

            payload = {
                "chat_id": self.chat_id,
                "text": formatted_message,
                "parse_mode": parse_mode
            }

            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    self.stats["messages_sent"] += 1
                    return True
                else:
                    error = await resp.text()
                    logger.error(f"Telegram API error: {error}")
                    self.stats["errors"] += 1
                    return False

        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            self.stats["errors"] += 1
            return False

    # ==================== Trade Alerts ====================

    async def trade_executed(
        self,
        strategy: str,
        market: str,
        side: str,
        size: float,
        price: float,
        pnl: Optional[float] = None,
        tx_hash: Optional[str] = None
    ):
        """
        Alert for trade execution

        Args:
            strategy: "copy" or "arbitrage"
            market: Market name/ID
            side: "BUY" or "SELL"
            size: Trade size in USD
            price: Execution price
            pnl: Optional realized PnL
            tx_hash: Optional transaction hash
        """
        strategy_emoji = "" if strategy == "copy" else ""
        side_emoji = "" if side == "BUY" else ""

        message = (
            f"<b>{strategy_emoji} TRADE EXECUTED</b>\n\n"
            f"Strategy: {strategy.upper()}\n"
            f"Market: {market[:40]}\n"
            f"Side: {side_emoji} {side}\n"
            f"Size: ${size:.2f}\n"
            f"Price: {price:.4f}"
        )

        if pnl is not None:
            pnl_emoji = "" if pnl >= 0 else ""
            message += f"\nPnL: {pnl_emoji} ${pnl:+.2f}"

        if tx_hash:
            short_hash = f"{tx_hash[:10]}...{tx_hash[-6:]}"
            message += f"\nTx: <code>{short_hash}</code>"

        await self.send(message, Priority.NORMAL)

    async def trade_failed(
        self,
        strategy: str,
        market: str,
        reason: str
    ):
        """Alert for failed trade"""
        message = (
            f"<b> TRADE FAILED</b>\n\n"
            f"Strategy: {strategy.upper()}\n"
            f"Market: {market[:40]}\n"
            f"Reason: {reason}"
        )

        await self.send(message, Priority.HIGH)

    # ==================== Position Alerts ====================

    async def position_opened(
        self,
        market: str,
        side: str,
        size: float,
        entry_price: float
    ):
        """Alert for new position"""
        message = (
            f"<b> POSITION OPENED</b>\n\n"
            f"Market: {market[:40]}\n"
            f"Side: {side}\n"
            f"Size: ${size:.2f}\n"
            f"Entry: {entry_price:.4f}"
        )

        await self.send(message, Priority.NORMAL)

    async def position_closed(
        self,
        market: str,
        pnl: float,
        hold_time_hours: float
    ):
        """Alert for closed position"""
        pnl_emoji = "" if pnl >= 0 else ""

        message = (
            f"<b> POSITION CLOSED</b>\n\n"
            f"Market: {market[:40]}\n"
            f"PnL: {pnl_emoji} ${pnl:+.2f}\n"
            f"Hold time: {hold_time_hours:.1f}h"
        )

        priority = Priority.NORMAL if pnl >= 0 else Priority.HIGH
        await self.send(message, priority)

    # ==================== Risk Alerts ====================

    async def kill_switch_triggered(self, reason: str):
        """Alert for kill switch activation"""
        message = (
            f"<b> KILL SWITCH TRIGGERED</b>\n\n"
            f"Reason: {reason}\n"
            f"Action: All trading STOPPED\n\n"
            f"<i>Manual intervention required</i>"
        )

        await self.send(message, Priority.CRITICAL)

    async def daily_loss_warning(
        self,
        strategy: str,
        current_loss: float,
        limit: float
    ):
        """Warning when approaching daily loss limit"""
        percent = (abs(current_loss) / limit) * 100

        message = (
            f"<b> LOSS WARNING</b>\n\n"
            f"Strategy: {strategy.upper()}\n"
            f"Current loss: ${abs(current_loss):.2f}\n"
            f"Limit: ${limit:.2f}\n"
            f"Usage: {percent:.0f}%"
        )

        await self.send(message, Priority.HIGH)

    # ==================== System Alerts ====================

    async def error(self, error_message: str, priority: Priority = Priority.HIGH):
        """Alert for system errors"""
        message = (
            f"<b> ERROR</b>\n\n"
            f"{error_message}"
        )

        await self.send(message, priority)

    async def warning(self, warning_message: str):
        """Alert for warnings"""
        message = (
            f"<b> WARNING</b>\n\n"
            f"{warning_message}"
        )

        await self.send(message, Priority.NORMAL)

    async def info(self, info_message: str):
        """Informational alert"""
        message = (
            f"<b> INFO</b>\n\n"
            f"{info_message}"
        )

        await self.send(message, Priority.LOW)

    async def bot_started(self, config_summary: str = ""):
        """Alert when bot starts"""
        message = (
            f"<b> BOT STARTED</b>\n\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        )

        if config_summary:
            message += f"\n{config_summary}"

        await self.send(message, Priority.NORMAL)

    async def bot_stopped(self, reason: str = "Manual shutdown"):
        """Alert when bot stops"""
        message = (
            f"<b> BOT STOPPED</b>\n\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Reason: {reason}"
        )

        await self.send(message, Priority.HIGH)

    # ==================== Summary Alerts ====================

    async def daily_summary(self, summary: Dict[str, Any]):
        """
        Send daily trading summary

        Args:
            summary: Dict with daily stats
        """
        copy_pnl = summary.get("copy", {}).get("pnl", 0)
        arb_pnl = summary.get("arbitrage", {}).get("pnl", 0)
        total_pnl = copy_pnl + arb_pnl

        pnl_emoji = "" if total_pnl >= 0 else ""

        message = (
            f"<b> DAILY SUMMARY</b>\n"
            f"<i>{summary.get('date', 'Today')}</i>\n\n"
            f"<b>Copy Trading:</b>\n"
            f"  Trades: {summary.get('copy', {}).get('trades', 0)}\n"
            f"  PnL: ${copy_pnl:+.2f}\n\n"
            f"<b>Arbitrage:</b>\n"
            f"  Trades: {summary.get('arbitrage', {}).get('trades', 0)}\n"
            f"  PnL: ${arb_pnl:+.2f}\n\n"
            f"<b>Total: {pnl_emoji} ${total_pnl:+.2f}</b>"
        )

        await self.send(message, Priority.NORMAL)

    async def weekly_summary(self, summary: Dict[str, Any]):
        """Send weekly trading summary"""
        message = (
            f"<b> WEEKLY SUMMARY</b>\n\n"
            f"Total Trades: {summary.get('total_trades', 0)}\n"
            f"Win Rate: {summary.get('win_rate', 0):.1f}%\n"
            f"Total PnL: ${summary.get('total_pnl', 0):+.2f}\n"
            f"Best Day: ${summary.get('best_day', 0):+.2f}\n"
            f"Worst Day: ${summary.get('worst_day', 0):+.2f}"
        )

        await self.send(message, Priority.NORMAL)

    # ==================== Arbitrage Specific ====================

    async def arbitrage_opportunity(
        self,
        pair_name: str,
        spread: float,
        expected_profit: float
    ):
        """Alert for detected arbitrage opportunity"""
        message = (
            f"<b> ARB OPPORTUNITY</b>\n\n"
            f"Pair: {pair_name}\n"
            f"Spread: {spread:.2%}\n"
            f"Expected: ${expected_profit:.2f}"
        )

        await self.send(message, Priority.NORMAL)

    # ==================== Utility Methods ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get alerter statistics"""
        return {
            **self.stats,
            "enabled": self.config.enabled
        }

    def set_enabled(self, enabled: bool):
        """Enable/disable alerts"""
        self.config.enabled = enabled

    def set_min_priority(self, priority: Priority):
        """Set minimum alert priority"""
        self.config.min_priority = priority


# ==================== Example Usage ====================

async def example():
    """Example usage of TelegramAlerter"""
    import os

    # Get credentials from environment
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
        return

    alerter = TelegramAlerter(bot_token, chat_id)

    try:
        # Test alerts
        await alerter.bot_started("Copy Trading: $70 | Arbitrage: $25")

        await alerter.trade_executed(
            strategy="copy",
            market="Trump wins 2024",
            side="BUY",
            size=10.0,
            price=0.55,
            pnl=0.50
        )

        await alerter.daily_summary({
            "date": "2024-01-15",
            "copy": {"trades": 5, "pnl": 2.50},
            "arbitrage": {"trades": 2, "pnl": 1.20}
        })

        print(f"Stats: {alerter.get_stats()}")

    finally:
        await alerter.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example())
