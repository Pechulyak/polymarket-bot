# -*- coding: utf-8 -*-
"""Background worker for processing paper trade notifications."""

import asyncio
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import create_engine, text

from src.monitoring.telegram_alerts import TelegramAlerts

logger = structlog.get_logger(__name__)


class NotificationWorker:
    """Background worker that polls notification queue and sends Telegram alerts."""

    def __init__(
        self,
        database_url: str,
        poll_interval: float = 2.0,
        batch_size: int = 10,
    ):
        """Initialize notification worker.

        Args:
            database_url: PostgreSQL connection URL
            poll_interval: How often to poll (seconds)
            batch_size: Number of notifications to process at once
        """
        self.database_url = database_url
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self._engine = create_engine(database_url)
        self._telegram = TelegramAlerts()
        self._running = False

    async def start(self) -> None:
        """Start the notification worker."""
        self._running = True
        logger.info("notification_worker_started", poll_interval=self.poll_interval)

        while self._running:
            try:
                await self._process_notifications()
            except Exception as e:
                logger.error("notification_worker_error", error=str(e))

            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        """Stop the notification worker."""
        self._running = False
        logger.info("notification_worker_stopped")

    async def _process_notifications(self) -> None:
        """Process pending notifications from the queue."""
        if not self._telegram.enabled:
            return

        with self._engine.connect() as conn:
            # Fetch pending notifications
            result = conn.execute(
                text("""
                    SELECT id, whale_address, market_id, side, price, size,
                           size_usd, kelly_fraction, kelly_size, source, created_at
                    FROM paper_trade_notifications
                    WHERE notified = FALSE
                    ORDER BY created_at ASC
                    LIMIT :batch_size
                """),
                {"batch_size": self.batch_size}
            )
            rows = result.fetchall()

            if not rows:
                return

            logger.debug("processing_notifications", count=len(rows))

            for row in rows:
                try:
                    await self._send_notification(row)
                    # Mark as notified
                    conn.execute(
                        text("UPDATE paper_trade_notifications SET notified = TRUE WHERE id = :id"),
                        {"id": row.id}
                    )
                    conn.commit()
                except Exception as e:
                    logger.error("notification_send_failed", notification_id=row.id, error=str(e))
                    conn.rollback()

    async def _send_notification(self, row) -> None:
        """Send a single notification to Telegram."""
        await self._telegram.send_paper_trade_notification(
            whale_address=row.whale_address,
            market_id=row.market_id,
            side=row.side,
            price=float(row.price) if row.price else 0.0,
            size=float(row.size) if row.size else 0.0,
            size_usd=float(row.size_usd) if row.size_usd else 0.0,
            kelly_fraction=float(row.kelly_fraction) if row.kelly_fraction else 0.25,
            kelly_size=float(row.kelly_size) if row.kelly_size else 0.0,
            source=row.source or "unknown",
            created_at=row.created_at,
        )
        logger.info(
            "notification_sent",
            whale_address=row.whale_address[:10] if row.whale_address else "unknown",
            market_id=row.market_id[:20] if row.market_id else "unknown",
            source=row.source,
        )


async def run_notification_worker(
    database_url: str,
    poll_interval: float = 2.0,
) -> None:
    """Run the notification worker.

    Args:
        database_url: PostgreSQL connection URL
        poll_interval: How often to poll (seconds)
    """
    worker = NotificationWorker(
        database_url=database_url,
        poll_interval=poll_interval,
    )
    await worker.start()
