"""
Polymarket CLOB API Client

Async wrapper for Polymarket's Central Limit Order Book API.
Supports both REST and WebSocket operations.

Sources:
- realfishsam/prediction-market-arbitrage-bot (WebSocket patterns)
- hodlwarden/polymarket-arbitrage-copy-bot (raw tx signing)

Usage:
    from polymarket_client import PolymarketClient

    client = PolymarketClient(
        private_key="0x...",
        rpc_url="https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY"
    )

    # Get orderbook
    book = await client.get_orderbook("MARKET_ID")

    # Place order
    result = await client.place_order(
        market_id="MARKET_ID",
        side="BUY",
        price=0.55,
        size=10.0
    )
"""

import asyncio
import json
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import aiohttp
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_typed_data
import logging

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """Represents a Polymarket order"""
    order_id: str
    market_id: str
    side: str
    price: float
    size: float
    filled: float
    status: str
    timestamp: int


@dataclass
class OrderBook:
    """Local orderbook representation"""
    market_id: str
    bids: List[Dict[str, float]]  # [{"price": 0.55, "size": 100}, ...]
    asks: List[Dict[str, float]]
    timestamp: int

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0]["price"] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0]["price"] if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None


class PolymarketClient:
    """
    Polymarket CLOB API Client

    Handles authentication, order signing, and API communication.
    """

    # API endpoints
    CLOB_API = "https://clob.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws"

    # Contract addresses (Polygon mainnet)
    EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
    USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

    def __init__(
        self,
        private_key: str,
        rpc_url: str,
        api_key: Optional[str] = None
    ):
        """
        Initialize client

        Args:
            private_key: Ethereum private key (0x...)
            rpc_url: Polygon RPC URL
            api_key: Optional API key for higher rate limits
        """
        self.private_key = private_key
        self.rpc_url = rpc_url
        self.api_key = api_key

        # Web3 setup
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.account = Account.from_key(private_key)
        self.address = self.account.address

        # Session management
        self._session: Optional[aiohttp.ClientSession] = None

        logger.info(f"PolymarketClient initialized for {self.address[:10]}...")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close the client session"""
        if self._session and not self._session.closed:
            await self._session.close()

    # ==================== Market Data ====================

    async def get_markets(self, active_only: bool = True) -> List[Dict]:
        """
        Get list of available markets

        Returns:
            List of market dictionaries with id, question, outcomes, etc.
        """
        session = await self._get_session()
        params = {"active": str(active_only).lower()}

        async with session.get(
            f"{self.GAMMA_API}/markets",
            params=params
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                raise Exception(f"Failed to get markets: {resp.status}")

    async def get_market(self, market_id: str) -> Dict:
        """Get single market details"""
        session = await self._get_session()

        async with session.get(
            f"{self.GAMMA_API}/markets/{market_id}"
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                raise Exception(f"Market not found: {market_id}")

    async def get_orderbook(self, token_id: str) -> OrderBook:
        """
        Get current orderbook for a token

        Args:
            token_id: The condition token ID (YES or NO)

        Returns:
            OrderBook with bids and asks
        """
        session = await self._get_session()

        async with session.get(
            f"{self.CLOB_API}/book",
            params={"token_id": token_id}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return OrderBook(
                    market_id=token_id,
                    bids=data.get("bids", []),
                    asks=data.get("asks", []),
                    timestamp=int(time.time())
                )
            else:
                raise Exception(f"Failed to get orderbook: {resp.status}")

    async def get_price(self, token_id: str) -> Dict[str, float]:
        """
        Get current best prices for a token

        Returns:
            {"bid": 0.55, "ask": 0.56, "mid": 0.555}
        """
        book = await self.get_orderbook(token_id)
        return {
            "bid": book.best_bid,
            "ask": book.best_ask,
            "mid": (book.best_bid + book.best_ask) / 2 if book.spread else None
        }

    # ==================== Order Management ====================

    async def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "GTC"
    ) -> Dict:
        """
        Place a limit order

        Args:
            token_id: Condition token ID
            side: "BUY" or "SELL"
            price: Limit price (0-1)
            size: Order size in USDC
            order_type: "GTC" (Good Till Cancel) or "FOK" (Fill or Kill)

        Returns:
            Order result with order_id, status, etc.
        """
        # Build order payload
        order = self._build_order(token_id, side, price, size, order_type)

        # Sign order
        signature = self._sign_order(order)

        # Submit
        session = await self._get_session()
        async with session.post(
            f"{self.CLOB_API}/order",
            json={**order, "signature": signature},
            headers=self._get_headers()
        ) as resp:
            if resp.status in [200, 201]:
                return await resp.json()
            else:
                error = await resp.text()
                raise Exception(f"Order failed: {error}")

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order"""
        session = await self._get_session()

        async with session.delete(
            f"{self.CLOB_API}/order/{order_id}",
            headers=self._get_headers()
        ) as resp:
            return resp.status == 200

    async def cancel_all_orders(self, market_id: Optional[str] = None) -> int:
        """
        Cancel all open orders

        Args:
            market_id: Optional - cancel only for specific market

        Returns:
            Number of orders cancelled
        """
        session = await self._get_session()
        params = {}
        if market_id:
            params["market"] = market_id

        async with session.delete(
            f"{self.CLOB_API}/orders",
            params=params,
            headers=self._get_headers()
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("cancelled", 0)
            return 0

    async def get_open_orders(self) -> List[Order]:
        """Get all open orders for this account"""
        session = await self._get_session()

        async with session.get(
            f"{self.CLOB_API}/orders",
            params={"maker": self.address},
            headers=self._get_headers()
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return [self._parse_order(o) for o in data]
            return []

    # ==================== Account ====================

    async def get_balance(self) -> Dict[str, float]:
        """
        Get account balances

        Returns:
            {"usdc": 100.0, "positions": {...}}
        """
        session = await self._get_session()

        async with session.get(
            f"{self.CLOB_API}/balance",
            params={"address": self.address},
            headers=self._get_headers()
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            return {"usdc": 0, "positions": {}}

    async def get_positions(self) -> List[Dict]:
        """Get current token positions"""
        session = await self._get_session()

        async with session.get(
            f"{self.GAMMA_API}/positions",
            params={"user": self.address}
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            return []

    # ==================== Internal Methods ====================

    def _build_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        order_type: str
    ) -> Dict:
        """Build order payload"""
        # Convert to contract format
        side_int = 0 if side.upper() == "BUY" else 1
        price_int = int(price * 1e6)  # 6 decimals
        size_int = int(size * 1e6)

        return {
            "tokenID": token_id,
            "price": str(price_int),
            "size": str(size_int),
            "side": side_int,
            "feeRateBps": "0",
            "nonce": str(int(time.time() * 1000)),
            "expiration": "0",  # No expiration
            "taker": "0x0000000000000000000000000000000000000000",
            "maker": self.address,
            "signatureType": 0
        }

    def _sign_order(self, order: Dict) -> str:
        """Sign order using EIP-712 typed data"""
        # EIP-712 domain
        domain = {
            "name": "Polymarket CTF Exchange",
            "version": "1",
            "chainId": 137,  # Polygon
            "verifyingContract": self.EXCHANGE_ADDRESS
        }

        # Order type
        types = {
            "Order": [
                {"name": "salt", "type": "uint256"},
                {"name": "maker", "type": "address"},
                {"name": "signer", "type": "address"},
                {"name": "taker", "type": "address"},
                {"name": "tokenId", "type": "uint256"},
                {"name": "makerAmount", "type": "uint256"},
                {"name": "takerAmount", "type": "uint256"},
                {"name": "expiration", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "feeRateBps", "type": "uint256"},
                {"name": "side", "type": "uint8"},
                {"name": "signatureType", "type": "uint8"},
            ]
        }

        # Build message (simplified - actual implementation more complex)
        message = {
            "salt": int(order["nonce"]),
            "maker": order["maker"],
            "signer": self.address,
            "taker": order["taker"],
            "tokenId": int(order["tokenID"]),
            "makerAmount": int(order["size"]),
            "takerAmount": int(float(order["price"]) * float(order["size"]) / 1e6),
            "expiration": int(order["expiration"]),
            "nonce": int(order["nonce"]),
            "feeRateBps": int(order["feeRateBps"]),
            "side": order["side"],
            "signatureType": order["signatureType"]
        }

        # Sign
        signable = encode_typed_data(domain, types, message)
        signed = self.account.sign_message(signable)

        return signed.signature.hex()

    def _get_headers(self) -> Dict[str, str]:
        """Get API headers"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _parse_order(self, data: Dict) -> Order:
        """Parse API response to Order object"""
        return Order(
            order_id=data.get("id", ""),
            market_id=data.get("tokenId", ""),
            side="BUY" if data.get("side") == 0 else "SELL",
            price=float(data.get("price", 0)) / 1e6,
            size=float(data.get("size", 0)) / 1e6,
            filled=float(data.get("sizeFilled", 0)) / 1e6,
            status=data.get("status", "unknown"),
            timestamp=data.get("timestamp", 0)
        )


# ==================== Example Usage ====================

async def example():
    """Example usage of PolymarketClient"""
    import os

    client = PolymarketClient(
        private_key=os.environ["PRIVATE_KEY"],
        rpc_url=os.environ["RPC_URL"]
    )

    try:
        # Get markets
        markets = await client.get_markets()
        print(f"Found {len(markets)} active markets")

        # Get orderbook for first market
        if markets:
            token_id = markets[0]["tokens"][0]["token_id"]
            book = await client.get_orderbook(token_id)
            print(f"Best bid: {book.best_bid}, Best ask: {book.best_ask}")

        # Get balance
        balance = await client.get_balance()
        print(f"USDC Balance: ${balance.get('usdc', 0):.2f}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(example())
