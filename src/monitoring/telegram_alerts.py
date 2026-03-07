# -*- coding: utf-8 -*-
"""Telegram alerts for trading bot monitoring."""

import os
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp
import structlog

logger = structlog.get_logger(__name__)


class TelegramAlerts:
    """Telegram bot alerts for trading bot.

    Sends alerts for:
    - Bot start/stop
    - Errors and exceptions
    - Trade execution (PnL)
    - Risk events
    - Daily summaries
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        """Initialize Telegram alerts.

        Args:
            bot_token: Telegram bot token (from BotFather)
            chat_id: Telegram chat ID for alerts
        """
        self.bot_token = (
            bot_token
            or os.getenv("TELEGRAM_BOT_TOKEN")
            or os.getenv("TELEGRAM_ALERT_BOT_TOKEN")
        )
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            logger.warning(
                "telegram_alerts_disabled", reason="missing_token_or_chat_id"
            )
        else:
            logger.info("telegram_alerts_enabled")

    async def _send_message(self, message: str, parse_mode: str = "Markdown") -> bool:
        """Send message to Telegram.

        Args:
            message: Message text
            parse_mode: Parse mode (Markdown or HTML)

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        logger.debug(
                            "telegram_message_sent", message_length=len(message)
                        )
                        return True
                    else:
                        logger.error("telegram_send_failed", status=resp.status)
                        return False
        except Exception as e:
            logger.error("telegram_send_error", error=str(e))
            return False

    async def send_start(self, mode: str = "paper", bankroll: float = 100.0) -> None:
        """Send bot start notification.

        Args:
            mode: Trading mode (paper or live)
            bankroll: Initial bankroll
        """
        emoji = "📝" if mode == "paper" else "🚀"
        message = f"""
{emoji} *Bot Started*

*Mode:* {mode.upper()}
*Bankroll:* ${bankroll:.2f}
*Time:* {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
"""
        await self._send_message(message)

    async def send_stop(self, reason: str = "manual") -> None:
        """Send bot stop notification.

        Args:
            reason: Stop reason
        """
        message = f"""
⏹️ *Bot Stopped*

*Reason:* {reason}
*Time:* {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
"""
        await self._send_message(message)

    async def send_error(
        self,
        error: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send error notification.

        Args:
            error: Error message
            context: Additional context
        """
        context_str = ""
        if context:
            context_str = "\n*Context:*\n" + "\n".join(
                f"- {k}: {v}" for k, v in context.items()
            )

        message = f"""
🚨 *Error*

```
{error}
```
{context_str}
*Time:* {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
"""
        await self._send_message(message)

    async def send_trade(
        self,
        side: str,
        size: float,
        price: float,
        market: str,
        pnl: Optional[float] = None,
        fees: Optional[float] = None,
    ) -> None:
        """Send trade notification.

        Args:
            side: Trade side (BUY or SELL)
            size: Trade size in USD
            price: Execution price
            market: Market ID
            pnl: Realized PnL (if closing)
            fees: Total fees
        """
        emoji = "🟢" if side.upper() == "BUY" else "🔴"
        pnl_str = f"\n*PnL:* ${pnl:.2f}" if pnl is not None else ""
        fees_str = f"\n*Fees:* ${fees:.2f}" if fees is not None else ""

        message = f"""
{emoji} *Trade Executed*

*Side:* {side.upper()}
*Size:* ${size:.2f}
*Price:* ${price:.4f}
*Market:* `{market[:20]}...`
{pnl_str}{fees_str}
*Time:* {datetime.utcnow().strftime("%H:%M:%S UTC")}
"""
        await self._send_message(message)

    async def send_pnl_update(
        self,
        total_pnl: float,
        daily_pnl: float,
        trades: int,
        wins: int,
        losses: int,
    ) -> None:
        """Send PnL update.

        Args:
            total_pnl: Total PnL
            daily_pnl: Daily PnL
            trades: Total trades
            wins: Win count
            losses: Loss count
        """
        win_rate = (wins / trades * 100) if trades > 0 else 0
        emoji = "📈" if daily_pnl >= 0 else "📉"

        message = f"""
{emoji} *PnL Update*

*Daily PnL:* ${daily_pnl:+.2f}
*Total PnL:* ${total_pnl:+.2f}
*Trades:* {trades} ({wins}W/{losses}L - {win_rate:.1f}%)
*Time:* {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
"""
        await self._send_message(message)

    async def send_risk_event(
        self,
        event_type: str,
        severity: str,
        description: str,
    ) -> None:
        """Send risk event notification.

        Args:
            event_type: Type of risk event
            severity: Severity level (low/medium/high/critical)
            description: Event description
        """
        severity_emoji = {
            "low": "⚠️",
            "medium": "🔶",
            "high": "🔴",
            "critical": "🚨",
        }.get(severity.lower(), "⚠️")

        message = f"""
{severity_emoji} *Risk Event*

*Type:* {event_type}
*Severity:* {severity.upper()}
*Description:* {description}
*Time:* {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
"""
        await self._send_message(message)

    async def send_kill_switch(self, reason: str) -> None:
        """Send kill switch activation notification.

        Args:
            reason: Reason for kill switch
        """
        message = f"""
🛑 *KILL SWITCH ACTIVATED*

*Reason:* {reason}
*Time:* {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}

*ALL TRADING HALTED*
"""
        await self._send_message(message)

    async def send_whale_signal(
        self,
        whale_address: str,
        whale_name: str,
        side: str,
        our_size: float,
        whale_size: float,
        price: float,
        market: str,
        trade_type: str = "virtual",
        status: str = "success",
        error: str = None,
    ) -> None:
        """Send whale trade signal notification.

        Args:
            whale_address: Whale wallet address
            whale_name: Whale name/username
            side: Trade side (buy/sell)
            our_size: Our trade size (after Kelly calculation)
            whale_size: Whale's original trade size
            price: Trade price
            market: Market ID/title
            trade_type: Type of trade (virtual/live)
            status: Trade status (success/error)
            error: Error message if failed
        """
        from datetime import timezone, timedelta

        # UTC+3 timezone
        utc_plus_3 = timezone(timedelta(hours=3))
        now_utc3 = datetime.now(utc_plus_3)

        if status == "success":
            message = f"""
🐋 *WHALE TRADE - {trade_type.upper()}*

*Whale:* {whale_name} (`{whale_address[:6]}...{whale_address[-4:]}`)
*Side:* {side.upper()}
*Our Size:* ${our_size:,.2f} (whale: ${whale_size:,.2f})
*Price:* {price:.4f}
*Market:* {market[:50]}...
*Time:* {now_utc3.strftime("%Y-%m-%d %H:%M:%S UTC+3")}
*Status:* ✅ {status}
"""
        else:
            message = f"""
🐋 *WHALE TRADE ERROR*

*Whale:* {whale_name} (`{whale_address[:6]}...{whale_address[-4:]}`)
*Side:* {side.upper()}
*Our Size:* ${our_size:,.2f}
*Market:* {market[:50]}...
*Time:* {now_utc3.strftime("%Y-%m-%d %H:%M:%S UTC+3")}
*Status:* ❌ {status}
*Error:* {error}
"""
        await self._send_message(message)

    async def send_paper_trade_notification(
        self,
        whale_address: str,
        market_id: str,
        side: str,
        price: float,
        size: float,
        size_usd: float,
        kelly_fraction: float,
        kelly_size: float,
        source: str,
        created_at: datetime,
        market_title: str = None,
    ) -> None:
        """Send paper trade created notification.

        Args:
            whale_address: Whale wallet address
            market_id: Market ID
            side: Trade side (buy/sell)
            price: Trade price
            size: Trade size
            size_usd: Trade size in USD
            kelly_fraction: Kelly fraction used
            kelly_size: Kelly-calculated position size
            source: Source (realtime/backfill)
            created_at: When trade was created
            market_title: Market title (optional, will fetch from DB if not provided)
        """
        from datetime import timezone, timedelta

        # UTC+3 timezone
        utc_plus_3 = timezone(timedelta(hours=3))

        # Handle timestamp conversion
        if created_at.tzinfo:
            created_utc3 = created_at.replace(tzinfo=timezone.utc).astimezone(utc_plus_3)
        else:
            # Assume UTC if no timezone info
            created_utc3 = created_at.replace(tzinfo=timezone.utc).astimezone(utc_plus_3)

        source_emoji = "⚡" if source == "realtime" else "📚"
        side_emoji = "🟢" if side.upper() == "BUY" else "🔴"

        # Try to get market_title from DB if not provided
        if not market_title:
            market_title = await self._fetch_market_title(market_id)

        # Use market_title if available, otherwise fallback to truncated market_id
        if market_title:
            market_display = market_title
        else:
            market_display = f"`{market_id[:12]}...{market_id[-8:]}`"

        message = f"""
{side_emoji} *PAPER TRADE CREATED*

*Source:* {source_emoji} {source.upper()}
*Whale:* `{whale_address[:6]}...{whale_address[-4:]}`
*Market:* {market_display}
*Side:* {side.upper()}
*Size:* ${size_usd:,.2f}
*Kelly:* {kelly_fraction*100:.1f}% → ${kelly_size:,.2f}
*Price:* {price:.4f}
*Time:* {created_utc3.strftime("%Y-%m-%d %H:%M:%S UTC+3")}
"""
        await self._send_message(message)

    async def _fetch_market_title(self, market_id: str) -> Optional[str]:
        """Fetch market_title from database.

        Args:
            market_id: Market ID to look up

        Returns:
            Market title if found, None otherwise
        """
        import os
        from sqlalchemy import create_engine, text

        try:
            database_url = os.getenv(
                "DATABASE_URL",
                "postgresql://postgres:password@postgres:5432/polymarket"
            )

            # Try to connect without SSL first (for local/Docker)
            engine = create_engine(
                database_url,
                connect_args={"options": "-c statement_timeout=5000"}
            )

            with engine.connect() as conn:
                # First try paper_trade_notifications table
                result = conn.execute(
                    text("""
                        SELECT market_title
                        FROM paper_trade_notifications
                        WHERE market_id = :market_id
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"market_id": market_id}
                )
                row = result.fetchone()
                if row and row[0]:
                    return row[0]

                # Fallback: try paper_trades table
                result = conn.execute(
                    text("""
                        SELECT market_title
                        FROM paper_trades
                        WHERE market_id = :market_id
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"market_id": market_id}
                )
                row = result.fetchone()
                if row and row[0]:
                    return row[0]

                # Fallback: try whale_trades table
                result = conn.execute(
                    text("""
                        SELECT market_title
                        FROM whale_trades
                        WHERE market_id = :market_id
                        ORDER BY traded_at DESC
                        LIMIT 1
                    """),
                    {"market_id": market_id}
                )
                row = result.fetchone()
                if row and row[0]:
                    return row[0]

            engine.dispose()
            return None

        except Exception as e:
            logger.warning("failed_to_fetch_market_title", market_id=market_id, error=str(e))
            return None

    async def send_daily_summary(
        self,
        date: str,
        trades: int,
        pnl: float,
        balance: float,
        win_rate: float,
    ) -> None:
        """Send daily summary.

        Args:
            date: Date string
            trades: Number of trades
            pnl: Daily PnL
            balance: Current balance
            win_rate: Win rate percentage
        """
        emoji = "📈" if pnl >= 0 else "📉"

        message = f"""
📊 *Daily Summary - {date}*

*Trades:* {trades}
*PnL:* {emoji} ${pnl:+.2f}
*Balance:* ${balance:.2f}
*Win Rate:* {win_rate:.1f}%
"""
        await self._send_message(message)


telegram_alerts = TelegramAlerts()
