# -*- coding: utf-8 -*-
"""Background worker for processing paper trade notifications."""

import asyncio
from datetime import datetime
from typing import Optional, Tuple

import aiohttp
import structlog
from sqlalchemy import create_engine, text

from src.monitoring.telegram_alerts import TelegramAlerts

logger = structlog.get_logger(__name__)

ENRICH_MAX_ATTEMPTS = 3
SEND_MAX_ATTEMPTS = 5


async def resolve_market_url(market_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Resolve market URL and group_item_title from market_id.

    Returns:
        Tuple of (url, group_item_title, error_message).
        On success: (url, group_item_title, None).
        On failure: (None, None, error_description).
    """
    import os

    clob_url = f"https://clob.polymarket.com/markets/{market_id}"
    timeout = aiohttp.ClientTimeout(total=5)

    # Step 1: CLOB — get market_slug
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                clob_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    return None, None, f"CLOB returned {resp.status}"
                clob_data = await resp.json()
                market_slug = clob_data.get("market_slug")
                if not market_slug:
                    return None, None, "CLOB: no market_slug found"
    except asyncio.TimeoutError:
        return None, None, "CLOB timeout"
    except Exception as e:
        return None, None, f"CLOB error: {str(e)}"

    # Step 2: Gamma — get events[0].slug and groupItemTitle
    gamma_url = f"https://gamma-api.polymarket.com/markets/slug/{market_slug}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                gamma_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    return None, None, f"Gamma returned {resp.status}"
                gamma_data = await resp.json()
                if not gamma_data:
                    return None, None, "Gamma: empty response"
                events = gamma_data.get("events", [])
                if not events or len(events) == 0:
                    return None, None, "Gamma: no events array or empty"
                event_slug = events[0].get("slug")
                if not event_slug:
                    return None, None, "Gamma: events[0].slug missing"
                group_item_title = gamma_data.get("groupItemTitle")
                url = f"https://polymarket.com/event/{event_slug}"
                return url, group_item_title, None
    except asyncio.TimeoutError:
        return None, None, "Gamma timeout"
    except Exception as e:
        return None, None, f"Gamma error: {str(e)}"


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
            # Fetch notifications ready for sending
            result = conn.execute(
                text("""
                    SELECT id, whale_address, market_id, side, price, size,
                           size_usd, kelly_fraction, kelly_size, source,
                           created_at, outcome, market_title, attempt_count, status
                    FROM paper_trade_notifications
                    WHERE status = 'PENDING'
                       OR (status IN ('ENRICH_FAILED', 'SEND_FAILED')
                           AND next_retry_at IS NOT NULL
                           AND next_retry_at <= NOW())
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
                await self._process_single_notification(conn, row)

    async def _process_single_notification(self, conn, row) -> None:
        """Process a single notification with status machine."""
        row_id = row.id
        attempt_count = row.attempt_count or 0
        whale_address = row.whale_address

        # Step 1: Enrich — resolve market URL
        url, group_item_title, enrich_error = await resolve_market_url(row.market_id)

        if enrich_error:
            attempt_count += 1
            if attempt_count >= ENRICH_MAX_ATTEMPTS:
                # Freeze: ENRICH_FAILED with no retry
                conn.execute(
                    text("""
                        UPDATE paper_trade_notifications
                        SET status = 'ENRICH_FAILED',
                            attempt_count = :attempt_count,
                            next_retry_at = NULL
                        WHERE id = :id
                    """),
                    {"id": row_id, "attempt_count": attempt_count}
                )
                conn.commit()
                await self._telegram.send_error(
                    error=f"Cannot build URL for market_id {row.market_id}: {enrich_error}. Frozen after {attempt_count} attempts.",
                    context={"notification_id": row_id, "whale_address": whale_address}
                )
                logger.error(
                    "enrich_failed_frozen",
                    notification_id=row_id,
                    market_id=row.market_id,
                    error=enrich_error,
                    attempts=attempt_count,
                )
            else:
                # Retry later with backoff calculated in SQL
                conn.execute(
                    text("""
                        UPDATE paper_trade_notifications
                        SET status = 'ENRICH_FAILED',
                            attempt_count = :attempt_count,
                            next_retry_at = NOW() + (LEAST(POWER(2, :attempt_count), 300) * INTERVAL '1 second')
                        WHERE id = :id
                    """),
                    {"id": row_id, "attempt_count": attempt_count}
                )
                conn.commit()
                logger.warning(
                    "enrich_failed_retry",
                    notification_id=row_id,
                    market_id=row.market_id,
                    error=enrich_error,
                    attempts=attempt_count,
                )
            return

        # Enrich succeeded — now get whale name
        whale_name = None
        try:
            with self._engine.connect() as name_conn:
                name_result = name_conn.execute(
                    text("SELECT notes FROM whales WHERE wallet_address = :addr LIMIT 1"),
                    {"addr": whale_address}
                )
                name_row = name_result.fetchone()
                if name_row and name_row[0]:
                    whale_name = name_row[0]
        except Exception as e:
            logger.warning("whale_name_lookup_failed", whale_address=whale_address, error=str(e))

        # Step 2: Send notification
        send_ok = await self._telegram.send_paper_trade_notification(
            whale_address=whale_address,
            market_id=row.market_id,
            side=row.side,
            price=float(row.price) if row.price else 0.0,
            size=float(row.size) if row.size else 0.0,
            size_usd=float(row.size_usd) if row.size_usd else 0.0,
            kelly_fraction=float(row.kelly_fraction) if row.kelly_fraction else 0.0,
            kelly_size=float(row.kelly_size) if row.kelly_size else 0.0,
            source=row.source or "unknown",
            created_at=row.created_at,
            outcome=row.outcome,
            whale_name=whale_name,
            url=url,
            group_item_title=group_item_title,
        )

        if send_ok:
            conn.execute(
                text("UPDATE paper_trade_notifications SET status = 'SENT' WHERE id = :id"),
                {"id": row_id}
            )
            conn.commit()
            logger.info(
                "notification_sent",
                notification_id=row_id,
                whale_address=whale_address[:10] if whale_address else "unknown",
                market_id=row.market_id[:20] if row.market_id else "unknown",
                source=row.source,
            )
        else:
            # _send_message returned False — treat as send failure with backoff
            attempt_count += 1
            if attempt_count >= SEND_MAX_ATTEMPTS:
                conn.execute(
                    text("""
                        UPDATE paper_trade_notifications
                        SET status = 'SEND_FAILED',
                            attempt_count = :attempt_count,
                            next_retry_at = NULL
                        WHERE id = :id
                    """),
                    {"id": row_id, "attempt_count": attempt_count}
                )
                conn.commit()
                await self._telegram.send_error(
                    error=f"Cannot send Telegram alert (API returned False). Frozen after {attempt_count} attempts.",
                    context={"notification_id": row_id, "whale_address": whale_address}
                )
                logger.error(
                    "send_failed_frozen",
                    notification_id=row_id,
                    attempts=attempt_count,
                )
            else:
                conn.execute(
                    text("""
                        UPDATE paper_trade_notifications
                        SET status = 'SEND_FAILED',
                            attempt_count = :attempt_count,
                            next_retry_at = NOW() + (LEAST(POWER(2, :attempt_count), 300) * INTERVAL '1 second')
                        WHERE id = :id
                    """),
                    {"id": row_id, "attempt_count": attempt_count}
                )
                conn.commit()
                logger.warning(
                    "send_failed_retry",
                    notification_id=row_id,
                    attempts=attempt_count,
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
