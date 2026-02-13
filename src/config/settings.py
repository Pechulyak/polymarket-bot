# -*- coding: utf-8 -*-
"""Configuration settings loaded from environment."""

try:
    from pydantic_settings import BaseSettings
except Exception:
    # Fallback for environments without pydantic_settings
    class BaseSettings:
        pass


from typing import Optional


class Settings(BaseSettings):
    """Application settings."""

    # API Keys
    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""
    polymarket_passphrase: str = ""
    polymarket_private_key: str = ""
    polymarket_funder_address: str = ""
    bybit_api_key: str = ""
    bybit_api_secret: str = ""

    # Web3
    metamask_private_key: str = ""
    ethereum_rpc_url: str = ""
    polygon_rpc_url: str = ""
    chain_id: int = 137

    # Database
    database_url: str = "sqlite:///:memory:"
    redis_url: str = "redis://localhost:6379/0"

    # Trading
    initial_bankroll: float = 100.0
    trading_mode: str = "paper"  # paper or live
    min_edge_bps: float = 10.0
    max_position_pct: float = 25.0

    # Risk
    risk_max_drawdown: float = 0.02
    risk_kill_switch_enabled: bool = True
    risk_max_concurrent_trades: int = 10

    # Monitoring
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    # Backwards-compatibility with legacy env vars used in tests
    polymarket_api_url: str = "https://api.polymarket.com"
    bybit_api_url: str = "https://api.bybit.com"
    bybit_testnet: bool = True
    risk_ban_detection: bool = False
    telegram_alert_bot_token: Optional[str] = None
    sentry_dsn: Optional[str] = None
    debug: bool = False
    environment: str = "development"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"


settings = Settings()
