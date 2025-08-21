"""DexScreener data source for coarse token lookups."""

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


class AsyncLRUCache:
    """Simple async LRU cache with TTL."""

    def __init__(self, maxsize: int = 1000, ttl: int = 300) -> None:
        """Initialize LRU cache.

        Args:
            maxsize: Maximum number of cached items
            ttl: Time to live in seconds
        """
        self.maxsize = maxsize
        self.ttl = ttl
        self.cache: dict[str, tuple[Any, float]] = {}
        self.access_order: list[str] = []

    def get(self, key: str) -> Any | None:
        """Get item from cache."""
        if key not in self.cache:
            return None

        value, timestamp = self.cache[key]

        # Check TTL
        if time.time() - timestamp > self.ttl:
            del self.cache[key]
            self.access_order.remove(key)
            return None

        # Update access order
        self.access_order.remove(key)
        self.access_order.append(key)

        return value

    def set(self, key: str, value: Any) -> None:
        """Set item in cache."""
        # Remove if already exists
        if key in self.cache:
            self.access_order.remove(key)

        # Evict oldest if at capacity
        if len(self.cache) >= self.maxsize and self.access_order:
            oldest_key = self.access_order.pop(0)
            del self.cache[oldest_key]

        # Add new item
        self.cache[key] = (value, time.time())
        self.access_order.append(key)


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


def map_dexscreener_token_to_snapshot(
    data: dict[str, Any], source: str = "dexscreener"
) -> TokenSnapshot:
    """Map DexScreener API response to TokenSnapshot.

    Args:
        data: Raw API response data
        source: Data source identifier

    Returns:
        TokenSnapshot with normalized data
    """
    # Extract token info
    address = data.get("address", "")

    # Extract market data from first pair (usually most liquid)
    pairs = data.get("pairs", [])
    if not pairs:
        # Return minimal snapshot if no pairs
        return TokenSnapshot(
            token=TokenId(mint=address),
            price_usd=0.0,
            liq_usd=0.0,
            vol_5m_usd=0.0,
            source=source,
            ts=datetime.now(UTC),
        )

    pair = pairs[0]  # Use first pair

    # Extract pool info
    pool = None
    if pair.get("pairAddress"):
        pool = PoolId(program=pair.get("dexId", "unknown"), address=pair["pairAddress"])

    # Extract price and volume data
    price_usd = float(pair.get("priceUsd", 0))
    volume_24h = float(pair.get("volume24h", 0))
    liquidity_usd = float(pair.get("liquidity", {}).get("usd", 0))

    # Normalize timestamp to UTC
    ts_str = pair.get("timestamp")
    if ts_str:
        try:
            ts = datetime.fromtimestamp(int(ts_str) / 1000, tz=UTC)
        except (ValueError, TypeError):
            ts = datetime.now(UTC)
    else:
        ts = datetime.now(UTC)

    return TokenSnapshot(
        token=TokenId(mint=address),
        pool=pool,
        price_usd=price_usd,
        liq_usd=liquidity_usd,
        vol_5m_usd=volume_24h / 288,  # Approximate 5-minute volume
        holders=None,  # DexScreener doesn't provide holder count
        age_seconds=None,  # DexScreener doesn't provide age
        pct_change_5m=float(pair.get("priceChange5m", 0)),
        source=source,
        ts=ts,
    )


class DexScreenerLookup(MarketDataSource):
    """DexScreener API data source for coarse token lookups."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        session: httpx.AsyncClient | None = None,
        cache_ttl: int = 300,
    ) -> None:
        """Initialize DexScreener lookup.

        Args:
            base_url: DexScreener API base URL
            api_key: Optional API key (not typically used)
            session: Optional httpx client session
            cache_ttl: Cache TTL in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session

        # Cache with 5-minute TTL
        self.cache = AsyncLRUCache(maxsize=1000, ttl=cache_ttl)

        # Rate limiting: 30 requests per minute (conservative)
        self.rate_limiter = TokenBucket(capacity=30, refill_rate=30 / 60)

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
            headers["Authorization"] = f"Bearer {self.api_key}"

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
                    "HTTP error in DexScreener request",
                    endpoint=endpoint,
                    status_code=e.response.status_code,
                    attempt=attempt.retry_state.attempt_number,
                )
                if e.response.status_code >= 500:
                    raise  # Retry on server errors
                raise  # Don't retry on client errors
            except (httpx.NetworkError, httpx.TimeoutException) as e:
                logger.warning(
                    "Network error in DexScreener request",
                    endpoint=endpoint,
                    error=str(e),
                    attempt=attempt.retry_state.attempt_number,
                )
                raise

    async def poll(self) -> list[TokenSnapshot]:
        """Poll for new market data snapshots.

        Note: DexScreener doesn't have a trending endpoint, so this returns empty.
        Use lookup() for specific token queries.

        Returns:
            Empty list (DexScreener is lookup-only)
        """
        logger.info("DexScreener poll called - this source is lookup-only")
        return []

    async def lookup(self, token: TokenId) -> TokenSnapshot | None:
        """Look up specific token snapshot.

        Args:
            token: Token identifier

        Returns:
            Token snapshot or None if not found
        """
        # Check cache first
        cache_key = f"token:{token.mint}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Cache hit for token", token_mint=token.mint)
            return cached_result

        try:
            # DexScreener endpoint for token details
            endpoint = f"latest/dex/tokens/{token.mint}"

            response_data = await self._make_request(endpoint)

            # DexScreener returns data in a specific format
            tokens = response_data.get("tokens", [])
            if not tokens:
                logger.info("Token not found", token_mint=token.mint)
                return None

            token_data = tokens[0]  # Use first token
            snapshot = map_dexscreener_token_to_snapshot(token_data)

            # Cache the result
            self.cache.set(cache_key, snapshot)

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
