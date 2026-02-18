# -*- coding: utf-8 -*-
"""Polymarket WebSocket Client for real-time data.

Provides real-time connection to Polymarket CLOB WebSocket API
for orderbook updates and trade monitoring.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

logger = structlog.get_logger(__name__)


@dataclass
class WebSocketMessage:
    channel: str
    asset_id: str
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class PolymarketWebSocket:
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        on_message: Optional[Callable[[WebSocketMessage], Any]] = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.on_message = on_message

        self._ws = None
        self._running = False
        self._connected = False
        self._subscribed_tokens: List[str] = []
        self._message_queue: asyncio.Queue = asyncio.Queue()

    async def connect(self, retries: int = 3, delay: float = 2.0) -> bool:
        if self._connected:
            return True

        self._running = True

        for attempt in range(retries):
            try:
                self._ws = await asyncio.wait_for(
                    websockets.connect(self.WS_URL), timeout=15.0
                )
                self._connected = True
                logger.info("websocket_connected", url=self.WS_URL)
                return True

            except asyncio.TimeoutError:
                logger.warning(
                    "websocket_timeout", attempt=attempt + 1, retries=retries
                )
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
            except Exception as e:
                logger.error(
                    "websocket_connection_failed", error=str(e), attempt=attempt + 1
                )
                if attempt < retries - 1:
                    await asyncio.sleep(delay)

        return False

    async def disconnect(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
        self._connected = False

    async def subscribe_tokens(self, token_ids: List[str], retry: bool = True) -> bool:
        if not token_ids:
            return True

        if not self._connected or not self._ws:
            if retry:
                self._subscribed_tokens.extend(token_ids)
            return False

        new_tokens = [t for t in token_ids if t not in self._subscribed_tokens]
        if not new_tokens:
            return True

        message = {"assets_ids": new_tokens[:50], "type": "market"}

        logger.info("ws_subscribe", message=message)

        try:
            await self._ws.send(json.dumps(message))
            self._subscribed_tokens.extend(new_tokens[:50])
            logger.info(
                "subscribed_tokens",
                count=len(new_tokens[:50]),
                total=len(self._subscribed_tokens),
            )
            return True
        except Exception as e:
            logger.error("subscription_failed", error=str(e))
            return False
            self._subscribed_tokens.extend(new_tokens)
            logger.info(
                "subscribed_tokens",
                count=len(new_tokens),
                total=len(self._subscribed_tokens),
            )
            return True
        except Exception as e:
            logger.error("subscription_failed", error=str(e))
            return False

    async def _resubscribe_pending(self) -> None:
        """Re-subscribe to tokens that were queued before connection was ready."""
        if self._subscribed_tokens and self._connected and self._ws:
            unique_tokens = list(set(self._subscribed_tokens))
            if unique_tokens:
                message = {"assets_ids": unique_tokens, "type": "market"}
                try:
                    await self._ws.send(json.dumps(message))
                    logger.info("resubscribed_pending_tokens", count=len(unique_tokens))
                except Exception as e:
                    logger.error("resubscribe_failed", error=str(e))

    async def start_listening(self) -> None:
        """Start listening for messages in a simple loop."""
        if not self._connected:
            return

        last_ping = time.time()

        while self._running:
            try:
                async for raw_message in self._ws:
                    if not self._running:
                        break

                    self._last_message_time = time.time()

                    if raw_message == "PONG":
                        logger.debug("received_pong")
                        continue
                    if raw_message == "PING":
                        await self._ws.send("PONG")
                        logger.debug("sent_pong")
                        continue

                    if time.time() - last_ping > 5:
                        try:
                            await self._ws.send("PING")
                            last_ping = time.time()
                            logger.debug("sent_ping")
                        except Exception:
                            pass

                    try:
                        data = json.loads(raw_message)
                        logger.debug(
                            "ws_received",
                            data_type=type(data).__name__,
                            data_keys=list(data.keys())
                            if isinstance(data, dict)
                            else f"list_len_{len(data)}"
                            if isinstance(data, list)
                            else "unknown",
                            sample=str(data)[:200] if data else "empty",
                        )

                        if isinstance(data, list):
                            if len(data) == 0:
                                logger.debug(
                                    "ws_empty_response",
                                    tokens_subscribed=len(self._subscribed_tokens),
                                )
                            else:
                                logger.info("ws_received_list", count=len(data))
                            for item in data[:3]:
                                logger.debug(
                                    "ws_list_item",
                                    keys=list(item.keys())
                                    if isinstance(item, dict)
                                    else "not_dict",
                                )
                                asset_id = (
                                    item.get("asset_id")
                                    or item.get("token_id")
                                    or item.get("conditionId")
                                    or "unknown"
                                )
                                channel = item.get("channel", "market")
                                msg = WebSocketMessage(
                                    channel=channel,
                                    asset_id=str(asset_id),
                                    data=item,
                                )
                                if self.on_message:
                                    try:
                                        result = self.on_message(msg)
                                        if asyncio.iscoroutine(result):
                                            await result
                                    except Exception as e:
                                        logger.error(
                                            "message_callback_error", error=str(e)
                                        )
                            continue

                        if not isinstance(data, dict):
                            continue

                        asset_id = (
                            data.get("asset_id")
                            or data.get("token_id")
                            or data.get("conditionId")
                            or "unknown"
                        )
                        channel = data.get("channel", "market")

                        msg = WebSocketMessage(
                            channel=channel,
                            asset_id=str(asset_id),
                            data=data,
                        )

                        if self.on_message:
                            try:
                                result = self.on_message(msg)
                                if asyncio.iscoroutine(result):
                                    await result
                            except Exception as e:
                                logger.error("message_callback_error", error=str(e))

                    except json.JSONDecodeError:
                        pass

            except ConnectionClosed:
                logger.warning("connection_closed")
                self._connected = False
                break
            except Exception as e:
                logger.error("websocket_error", error=str(e))
                self._connected = False
                break

    def is_connected(self) -> bool:
        return self._connected
