"""Birdeye data source for Solana market data."""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..core.interfaces import MarketDataSource
from ..core.types import PoolId, TokenId, TokenSnapshot

logger = structlog.get_logger(__name__)


class TokenBucket:
    """Simple in-memory token bucket rate limiter."""

    def __init__(self, capacity: int, refill_rate: float) -> None:
        """Initialize token bucket.

        Args:
            capacity: Maximum tokens in bucket
            refill_rate: Tokens per second refill rate
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()

    async def acquire(self) -> bool:
        """Try to acquire a token, return True if successful."""
        now = time.time()
        time_passed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + time_passed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


def map_birdeye_token_to_snapshot(
    data: dict[str, Any], source: str = "birdeye"
) -> TokenSnapshot:
    """Map Birdeye API response to TokenSnapshot.

    Args:
        data: Raw API response data
        source: Data source identifier

    Returns:
        TokenSnapshot with normalized data
    """
    # Extract token info
    address = data.get("address", "")

    # Extract market data
    price_usd = data.get("price", 0.0)
    volume_24h = data.get("volume24h", 0.0)
    liquidity = data.get("liquidity", 0.0)

    # Extract pool info if available
    pool = None
    pool_address = data.get("poolAddress")
    if pool_address:
        pool = PoolId(
            program="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",  # Default to Whirlpool
            address=pool_address,
        )

    # Normalize timestamp to UTC
    ts_str = data.get("timestamp", "")
    if ts_str:
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            ts = datetime.now(UTC)
    else:
        ts = datetime.now(UTC)

    return TokenSnapshot(
        token=TokenId(mint=address),
        pool=pool,
        price_usd=price_usd,
        liq_usd=liquidity,
        vol_5m_usd=volume_24h / 288,  # Approximate 5-minute volume
        holders=data.get("holders"),
        age_seconds=data.get("age"),
        pct_change_5m=data.get("priceChange5m", 0.0),
        source=source,
        ts=ts,
    )


class BirdeyeDataSource(MarketDataSource):
    """Birdeye API data source for Solana market data."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        session: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize Birdeye data source.

        Args:
            base_url: Birdeye API base URL
            api_key: Optional API key for enhanced endpoints
            session: Optional httpx client session
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session

        # Rate limiting: 60 requests per minute (more conservative)
        self.rate_limiter = TokenBucket(capacity=60, refill_rate=60 / 60)

        # Retry configuration
        self.retry_config = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((httpx.NetworkError, httpx.TimeoutException)),
            reraise=True,
        )

    async def _make_request(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make HTTP request with rate limiting and retries.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            API response data

        Raises:
            httpx.HTTPError: On HTTP errors
            RetryError: When all retries are exhausted
        """
        # Wait for rate limit
        while not await self.rate_limiter.acquire():
            await asyncio.sleep(0.1)

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {}

        if self.api_key:
            headers["X-API-KEY"] = self.api_key

        async for attempt in self.retry_config:
            try:
                with attempt:
                    response = await self.session.get(
                        url, params=params, headers=headers, timeout=30.0
                    )
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "HTTP error in Birdeye request",
                    endpoint=endpoint,
                    status_code=e.response.status_code,
                    attempt=attempt.retry_state.attempt_number,
                )
                if e.response.status_code >= 500:
                    raise  # Retry on server errors
                raise  # Don't retry on client errors
            except (httpx.NetworkError, httpx.TimeoutException) as e:
                logger.warning(
                    "Network error in Birdeye request",
                    endpoint=endpoint,
                    error=str(e),
                    attempt=attempt.retry_state.attempt_number,
                )
                raise

    async def poll(self) -> list[TokenSnapshot]:
        """Poll for new market data snapshots.

        Returns:
            List of token snapshots
        """
        try:
            # Mock endpoint for trending tokens
            endpoint = "public/trending"
            params = {"limit": 50}

            response_data = await self._make_request(endpoint, params)

            snapshots = []
            for token_data in response_data.get("data", []):
                try:
                    snapshot = map_birdeye_token_to_snapshot(token_data)
                    snapshots.append(snapshot)
                except Exception as e:
                    logger.warning(
                        "Failed to map token data",
                        token_address=token_data.get("address"),
                        error=str(e),
                    )
                    continue

            logger.info("Polled Birdeye data", count=len(snapshots))
            return snapshots

        except Exception as e:
            logger.error("Failed to poll Birdeye data", error=str(e))
            return []

    async def lookup(self, token: TokenId) -> TokenSnapshot | None:
        """Look up specific token snapshot.

        Args:
            token: Token identifier

        Returns:
            Token snapshot or None if not found
        """
        try:
            # Mock endpoint for token details
            endpoint = f"public/token/{token.mint}"

            response_data = await self._make_request(endpoint)

            snapshot = map_birdeye_token_to_snapshot(response_data.get("data", {}))
            logger.info("Looked up token", token_mint=token.mint)
            return snapshot

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info("Token not found", token_mint=token.mint)
                return None
            logger.error(
                "HTTP error in token lookup", token_mint=token.mint, error=str(e)
            )
            return None
        except Exception as e:
            logger.error("Failed to lookup token", token_mint=token.mint, error=str(e))
            return None
