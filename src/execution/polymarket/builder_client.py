# -*- coding: utf-8 -*-
"""Builder API Client for gasless Polymarket transactions.

Provides gasless order execution via Polymarket Builder API.
Uses py-builder-signing-sdk for authenticated headers.

Example:
    >>> from execution.polymarket.builder_client import BuilderClient
    >>> client = BuilderClient(
    ...     api_key="your-key",
    ...     api_secret="your-secret",
    ...     passphrase="your-pass",
    ...     private_key="0x..."
    ... )
    >>> result = await client.place_order(
    ...     token_id="0x123...",
    ...     side="BUY",
    ...     size=10.0,
    ...     price=0.55
    ... )
"""

import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

import aiohttp
import structlog

logger = structlog.get_logger(__name__)


class BuilderAPIError(Exception):
    """Exception for Builder API errors."""

    pass


@dataclass
class OrderResult:
    """Result of an order placement.

    Attributes:
        success: Whether order was placed successfully
        order_id: Polymarket order ID
        side: Order side (BUY/SELL)
        size: Order size in USD
        price: Order price
        filled: Whether order was immediately filled
        fill_price: Fill price if immediately filled
        error: Error message if failed
    """

    success: bool
    order_id: Optional[str] = None
    side: str = ""
    size: Decimal = Decimal("0")
    price: Decimal = Decimal("0")
    filled: bool = False
    fill_price: Optional[Decimal] = None
    error: Optional[str] = None


class BuilderClient:
    """Builder API Client for gasless transactions.

    Uses Builder API credentials to create authenticated headers
    for gasless order execution on Polymarket.

    Attributes:
        CLOB_API: CLOB API endpoint
        MAX_ORDERS_PER_DAY: Rate limit for unverified tier (100/day)
    """

    CLOB_API = "https://clob.polymarket.com"
    MAX_ORDERS_PER_DAY = 100

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        private_key: str,
        chain_id: int = 137,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        """Initialize Builder API client.

        Args:
            api_key: Builder API key
            api_secret: Builder API secret
            passphrase: Builder API passphrase
            private_key: Wallet private key for signing
            chain_id: Polygon chain ID (default 137)
            max_retries: Maximum retry attempts
            retry_delay: Base delay between retries
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.private_key = private_key
        self.chain_id = chain_id
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._session: Optional[aiohttp.ClientSession] = None
        self._order_count_today = 0
        self._order_count_reset = 0.0
        self._builder_headers: Optional[Dict[str, str]] = None
        self._headers_lock = asyncio.Lock()

        self._try_import_builder_sdk()

        logger.info(
            "builder_client_initialized",
            api_key_set=bool(api_key),
            private_key_set=bool(private_key),
            chain_id=chain_id,
        )

    def _try_import_builder_sdk(self) -> None:
        """Try to import Builder SDK, fall back to manual headers."""
        try:
            from py_builder_signing_sdk import BuilderApiKeyCreds, BuilderConfig

            self._builder_config = BuilderConfig(
                local_builder_creds=BuilderApiKeyCreds(
                    key=self.api_key,
                    secret=self.api_secret,
                    passphrase=self.passphrase,
                )
            )
            self._use_sdk = True
            logger.info("builder_sdk_loaded", method="py_builder_signing_sdk")
        except ImportError:
            self._builder_config = None
            self._use_sdk = False
            logger.warning(
                "builder_sdk_not_available",
                message="Will use manual HMAC signing",
            )

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("builder_client_closed")

    async def _generate_builder_headers(
        self,
        method: str,
        path: str,
        body: str = "",
    ) -> Dict[str, str]:
        """Generate Builder API authentication headers.

        Args:
            method: HTTP method
            path: API path
            body: Request body

        Returns:
            Dict of authentication headers
        """
        async with self._headers_lock:
            if self._use_sdk and self._builder_config:
                headers = self._builder_config.generate_builder_headers(
                    method=method,
                    path=path,
                    body=body,
                )
                return headers
            return self._generate_manual_headers(method, path, body)

    def _generate_manual_headers(
        self,
        method: str,
        path: str,
        body: str = "",
    ) -> Dict[str, str]:
        """Generate Builder headers manually using HMAC-SHA256.

        Fallback when py-builder-signing-sdk is not available.

        Args:
            method: HTTP method
            path: API path
            body: Request body

        Returns:
            Dict of authentication headers
        """
        import base64
        import hmac

        timestamp = str(int(time.time()))
        message = timestamp + method + path + body
        secret_bytes = self.api_secret.encode("utf-8")
        if len(secret_bytes) >= 32:
            secret_bytes = secret_bytes[:32]
        else:
            secret_bytes = secret_bytes + b"\0" * (32 - len(secret_bytes))
        signature = hmac.new(secret_bytes, message.encode("utf-8"), "sha256")
        signature_b64 = base64.b64encode(signature.digest()).decode("utf-8")

        return {
            "POLY-BUILDER-KEY": self.api_key,
            "POLY-BUILDER-SIGNATURE": signature_b64,
            "POLY-BUILDER-TIMESTAMP": timestamp,
            "POLY-BUILDER-PASSPHRASE": self.passphrase,
        }

    def _check_rate_limit(self) -> None:
        """Check and update daily order rate limit."""
        now = time.time()
        if now - self._order_count_reset > 86400:
            self._order_count_today = 0
            self._order_count_reset = now

        if self._order_count_today >= self.MAX_ORDERS_PER_DAY:
            raise BuilderAPIError(
                f"Daily order limit reached: {self.MAX_ORDERS_PER_DAY}/day"
            )

    async def _make_request(
        self,
        method: str,
        path: str,
        body: str = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make authenticated request to Builder API.

        Args:
            method: HTTP method
            path: API path
            body: Request body
            params: Query parameters

        Returns:
            JSON response as dict

        Raises:
            BuilderAPIError: On API errors after retries
        """
        self._check_rate_limit()

        url = f"{self.CLOB_API}{path}"
        headers = await self._generate_builder_headers(method, path, body)

        session = await self._get_session()

        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **headers,
        }

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                async with session.request(
                    method=method,
                    url=url,
                    params=params,
                    headers=request_headers,
                    data=body if body else None,
                ) as resp:
                    if resp.status in (200, 201):
                        self._order_count_today += 1
                        return await resp.json()
                    elif resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", "5"))
                        logger.warning(
                            "builder_rate_limit",
                            retry_after=retry_after,
                            attempt=attempt + 1,
                        )
                        await asyncio.sleep(retry_after)
                    elif resp.status == 400:
                        error_text = await resp.text()
                        logger.error(
                            "builder_bad_request",
                            status=resp.status,
                            error=error_text[:200],
                        )
                        raise BuilderAPIError(f"Bad request: {error_text[:200]}")
                    else:
                        error_text = await resp.text()
                        logger.error(
                            "builder_api_error",
                            status=resp.status,
                            error=error_text[:200],
                        )
                        raise BuilderAPIError(
                            f"API error {resp.status}: {error_text[:200]}"
                        )

            except aiohttp.ClientError as e:
                last_error = e
                logger.warning(
                    "builder_request_failed",
                    error=str(e),
                    attempt=attempt + 1,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))

        raise BuilderAPIError(
            f"Request failed after {self.max_retries} attempts: {last_error}"
        )

    async def place_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
    ) -> OrderResult:
        """Place an order with Builder API (gasless).

        Args:
            token_id: Condition token ID
            side: "BUY" or "SELL"
            size: Order size in USD
            price: Order price (0-1)

        Returns:
            OrderResult with success status and details
        """
        try:
            size_raw = int(size * 1e6)
            price_raw = int(price * 1e6)
            side_int = 0 if side.upper() == "BUY" else 1

            order_data = {
                "tokenId": token_id,
                "side": side_int,
                "amount": str(size_raw),
                "price": str(price_raw),
            }

            body = ""
            logger.info(
                "placing_builder_order",
                token_id=token_id[:20],
                side=side,
                size=size,
                price=price,
            )

            response = await self._make_request(
                method="POST",
                path="/order",
                body=body,
                params=order_data,
            )

            order_id = response.get("orderID") or response.get("order_id")
            filled = response.get("filled", False)
            fill_price = response.get("fillPrice")

            logger.info(
                "builder_order_placed",
                order_id=order_id,
                filled=filled,
                fill_price=fill_price,
            )

            return OrderResult(
                success=True,
                order_id=order_id,
                side=side,
                size=Decimal(str(size)),
                price=Decimal(str(price)),
                filled=filled,
                fill_price=(Decimal(str(fill_price)) if fill_price else None),
            )

        except BuilderAPIError as e:
            logger.error("builder_order_failed", error=str(e))
            return OrderResult(
                success=False,
                side=side,
                size=Decimal(str(size)),
                price=Decimal(str(price)),
                error=str(e),
            )
        except Exception as e:
            logger.error("builder_order_error", error=str(e))
            return OrderResult(
                success=False,
                side=side,
                size=Decimal(str(size)),
                price=Decimal(str(price)),
                error=str(e),
            )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if cancelled successfully
        """
        try:
            await self._make_request(
                method="DELETE",
                path=f"/order/{order_id}",
            )
            logger.info("builder_order_cancelled", order_id=order_id)
            return True
        except BuilderAPIError as e:
            logger.error("builder_cancel_failed", order_id=order_id, error=str(e))
            return False

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order details.

        Args:
            order_id: Order ID

        Returns:
            Order details dict or None if not found
        """
        try:
            response = await self._make_request(
                method="GET",
                path=f"/order/{order_id}",
            )
            return response
        except BuilderAPIError:
            return None

    async def get_orders(
        self,
        market_id: Optional[str] = None,
        status: str = "open",
    ) -> List[Dict[str, Any]]:
        """Get orders for the account.

        Args:
            market_id: Optional market filter
            status: Order status filter ("open", "filled", "cancelled")

        Returns:
            List of order dicts
        """
        params: Dict[str, Any] = {"status": status}
        if market_id:
            params["market"] = market_id

        try:
            response = await self._make_request(
                method="GET",
                path="/orders",
                params=params,
            )
            return response.get("orders", [])
        except BuilderAPIError as e:
            logger.error("builder_get_orders_failed", error=str(e))
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics.

        Returns:
            Dict with order stats and rate limit info
        """
        return {
            "orders_today": self._order_count_today,
            "max_orders_per_day": self.MAX_ORDERS_PER_DAY,
            "orders_remaining": self.MAX_ORDERS_PER_DAY - self._order_count_today,
            "sdk_available": self._use_sdk,
        }


class BuilderClientWrapper:
    """Wrapper that provides fallback to regular execution.

    Uses Builder API when available, falls back to regular
    execution when Builder is unavailable or rate-limited.
    """

    def __init__(
        self,
        builder_client: Optional[BuilderClient] = None,
        fallback_executor: Any = None,
    ) -> None:
        """Initialize wrapper.

        Args:
            builder_client: Optional BuilderClient instance
            fallback_executor: Fallback executor when Builder unavailable
        """
        self.builder_client = builder_client
        self.fallback_executor = fallback_executor
        self.use_builder = builder_client is not None

    async def execute(
        self,
        market_id: str,
        side: str,
        size: float,
        price: float,
    ) -> Dict[str, Any]:
        """Execute order with Builder API or fallback.

        Args:
            market_id: Market/token identifier
            side: "BUY" or "SELL"
            size: Order size in USD
            price: Order price

        Returns:
            Result dict with success status
        """
        if not self.use_builder or not self.builder_client:
            if self.fallback_executor:
                return await self.fallback_executor.execute(
                    market_id=market_id,
                    side=side,
                    size=size,
                    price=price,
                    mode="rest",
                )
            return {
                "success": False,
                "error": "No executor configured",
            }

        try:
            result = await self.builder_client.place_order(
                token_id=market_id,
                side=side,
                size=size,
                price=price,
            )

            return {
                "success": result.success,
                "order_id": result.order_id,
                "filled": result.filled,
                "fill_price": float(result.fill_price) if result.fill_price else None,
                "size": float(result.size),
                "error": result.error,
                "mode": "builder",
            }

        except BuilderAPIError as e:
            logger.warning(
                "builder_unavailable_using_fallback",
                error=str(e),
            )
            if self.fallback_executor:
                return await self.fallback_executor.execute(
                    market_id=market_id,
                    side=side,
                    size=size,
                    price=price,
                    mode="rest",
                )
            return {
                "success": False,
                "error": f"Builder failed: {e}",
            }

    def get_builder_stats(self) -> Optional[Dict[str, Any]]:
        """Get Builder API statistics.

        Returns:
            Stats dict or None if Builder not available
        """
        if self.builder_client:
            return self.builder_client.get_stats()
        return None


def create_builder_client_from_settings(
    settings_module: Any = None,
) -> Optional[BuilderClient]:
    """Create BuilderClient from settings.

    Reads BUILDER_API_KEY, BUILDER_API_SECRET, BUILDER_PASSPHRASE
    from settings and POLYMARKET_PRIVATE_KEY for signing.

    Args:
        settings_module: Module with settings (defaults to src.config.settings)

    Returns:
        BuilderClient instance or None if credentials not configured
    """
    if settings_module is None:
        try:
            from src.config import settings
        except ImportError:
            try:
                from config import settings
            except ImportError:
                logger.warning("settings_module_not_provided")
                return None
    else:
        settings = settings_module

    api_key = getattr(settings, "builder_api_key", None) or getattr(
        settings, "BUILDER_API_KEY", None
    )
    api_secret = getattr(settings, "builder_api_secret", None) or getattr(
        settings, "BUILDER_API_SECRET", None
    )
    passphrase = getattr(settings, "builder_api_passphrase", None) or getattr(
        settings, "BUILDER_PASSPHRASE", None
    )
    private_key = getattr(settings, "polymarket_private_key", None) or getattr(
        settings, "POLYMARKET_PRIVATE_KEY", None
    )

    if not api_key or not api_secret or not passphrase:
        logger.warning(
            "builder_credentials_missing",
            has_api_key=bool(api_key),
            has_api_secret=bool(api_secret),
            has_passphrase=bool(passphrase),
        )
        return None

    if not private_key:
        logger.warning("private_key_missing_for_builder")
        return None

    logger.info(
        "creating_builder_client",
        api_key_prefix=api_key[:8] + "..." if len(api_key) > 8 else api_key,
    )

    return BuilderClient(
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
        private_key=private_key,
    )
