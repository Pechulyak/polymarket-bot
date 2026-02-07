# -*- coding: utf-8 -*-
"""Data ingestion package."""

from .websocket_client import (
    PolymarketWebSocket,
    WebSocketMessage,
    WebSocketConnectionError,
)

__all__ = ["PolymarketWebSocket", "WebSocketMessage", "WebSocketConnectionError"]
