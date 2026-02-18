# -*- coding: utf-8 -*-
"""Data ingestion package."""

from .websocket_client import (
    PolymarketWebSocket,
    WebSocketMessage,
)

__all__ = ["PolymarketWebSocket", "WebSocketMessage"]
