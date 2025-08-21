"""Tests for data adapters."""

import pytest

from bot.data.birdeye import BirdeyeDataSource, map_birdeye_token_to_snapshot
from bot.data.dexscreener import DexScreenerLookup, map_dexscreener_token_to_snapshot
from bot.data.helius import HeliusDataSource, map_helius_token_to_snapshot


@pytest.fixture
def sample_helius_response():
    """Sample Helius API response."""
    return {
        "tokens": [
            {
                "token": {"mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
                "market": {
                    "price": 1.0,
                    "volume24h": 1000000.0,
                    "liquidity": 500000.0,
                    "priceChange5m": 0.5,
                    "pool": {
                        "program": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
                        "address": "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
                    },
                },
                "holders": 1000,
                "age_seconds": 86400,
                "timestamp": "2023-01-01T12:00:00Z",
            }
        ]
    }


@pytest.fixture
def sample_birdeye_response():
    """Sample Birdeye API response."""
    return {
        "data": [
            {
                "address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "price": 1.0,
                "volume24h": 1000000.0,
                "liquidity": 500000.0,
                "priceChange5m": 0.5,
                "poolAddress": "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
                "holders": 1000,
                "age": 86400,
                "timestamp": "2023-01-01T12:00:00Z",
            }
        ]
    }


@pytest.fixture
def sample_dexscreener_response():
    """Sample DexScreener API response."""
    return {
        "tokens": [
            {
                "address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "pairs": [
                    {
                        "pairAddress": "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
                        "dexId": "whirlpool",
                        "priceUsd": "1.0",
                        "volume24h": "1000000.0",
                        "liquidity": {"usd": "500000.0"},
                        "priceChange5m": "0.5",
                        "timestamp": "1640995200000",
                    }
                ],
            }
        ]
    }


class TestHeliusDataSource:
    """Test Helius data source."""

    def test_init(self):
        """Test HeliusDataSource initialization."""
        ds = HeliusDataSource(rpc_url="https://api.helius.xyz", api_key="test_key")

        assert ds.rpc_url == "https://api.helius.xyz"
        assert ds.api_key == "test_key"
        assert ds.rate_limiter.capacity == 100
        assert ds.rate_limiter.refill_rate == 100 / 60


class TestBirdeyeDataSource:
    """Test Birdeye data source."""

    def test_init(self):
        """Test BirdeyeDataSource initialization."""
        ds = BirdeyeDataSource(
            base_url="https://public-api.birdeye.so", api_key="test_key"
        )

        assert ds.base_url == "https://public-api.birdeye.so"
        assert ds.api_key == "test_key"
        assert ds.rate_limiter.capacity == 60
        assert ds.rate_limiter.refill_rate == 60 / 60


class TestDexScreenerLookup:
    """Test DexScreener lookup."""

    def test_init(self):
        """Test DexScreenerLookup initialization."""
        ds = DexScreenerLookup(base_url="https://api.dexscreener.com", cache_ttl=300)

        assert ds.base_url == "https://api.dexscreener.com"
        assert ds.cache.ttl == 300
        assert ds.rate_limiter.capacity == 30


class TestMappingFunctions:
    """Test data mapping functions."""

    def test_map_helius_token_to_snapshot(self):
        """Test Helius token mapping."""
        data = {
            "token": {"mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
            "market": {
                "price": 1.0,
                "volume24h": 1000000.0,
                "liquidity": 500000.0,
                "priceChange5m": 0.5,
                "pool": {
                    "program": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
                    "address": "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
                },
            },
            "holders": 1000,
            "age_seconds": 86400,
            "timestamp": "2023-01-01T12:00:00Z",
        }

        snapshot = map_helius_token_to_snapshot(data)

        assert snapshot.token.mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        assert snapshot.price_usd == 1.0
        assert snapshot.liq_usd == 500000.0
        assert snapshot.vol_5m_usd == 1000000.0 / 288
        assert snapshot.holders == 1000
        assert snapshot.age_seconds == 86400
        assert snapshot.pct_change_5m == 0.5
        assert snapshot.source == "helius"
        assert snapshot.pool is not None
        assert snapshot.pool.program == "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"

    def test_map_birdeye_token_to_snapshot(self):
        """Test Birdeye token mapping."""
        data = {
            "address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "price": 1.0,
            "volume24h": 1000000.0,
            "liquidity": 500000.0,
            "priceChange5m": 0.5,
            "poolAddress": "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
            "holders": 1000,
            "age": 86400,
            "timestamp": "2023-01-01T12:00:00Z",
        }

        snapshot = map_birdeye_token_to_snapshot(data)

        assert snapshot.token.mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        assert snapshot.price_usd == 1.0
        assert snapshot.liq_usd == 500000.0
        assert snapshot.vol_5m_usd == 1000000.0 / 288
        assert snapshot.holders == 1000
        assert snapshot.age_seconds == 86400
        assert snapshot.pct_change_5m == 0.5
        assert snapshot.source == "birdeye"
        assert snapshot.pool is not None
        assert snapshot.pool.address == "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ"

    def test_map_dexscreener_token_to_snapshot(self):
        """Test DexScreener token mapping."""
        data = {
            "address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "pairs": [
                {
                    "pairAddress": "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
                    "dexId": "whirlpool",
                    "priceUsd": "1.0",
                    "volume24h": "1000000.0",
                    "liquidity": {"usd": "500000.0"},
                    "priceChange5m": "0.5",
                    "timestamp": "1640995200000",
                }
            ],
        }

        snapshot = map_dexscreener_token_to_snapshot(data)

        assert snapshot.token.mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        assert snapshot.price_usd == 1.0
        assert snapshot.liq_usd == 500000.0
        assert snapshot.vol_5m_usd == 1000000.0 / 288
        assert snapshot.pct_change_5m == 0.5
        assert snapshot.source == "dexscreener"
        assert snapshot.pool is not None
        assert snapshot.pool.program == "whirlpool"
        assert snapshot.pool.address == "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ"

    def test_map_dexscreener_token_no_pairs(self):
        """Test DexScreener token mapping with no pairs."""
        data = {"address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "pairs": []}

        snapshot = map_dexscreener_token_to_snapshot(data)

        assert snapshot.token.mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        assert snapshot.price_usd == 0.0
        assert snapshot.liq_usd == 0.0
        assert snapshot.vol_5m_usd == 0.0
        assert snapshot.pool is None


class TestRateLimiting:
    """Test rate limiting functionality."""

    def test_token_bucket_initialization(self):
        """Test token bucket initialization."""
        from bot.data.helius import TokenBucket

        bucket = TokenBucket(capacity=100, refill_rate=10)
        assert bucket.capacity == 100
        assert bucket.refill_rate == 10
        assert bucket.tokens == 100


class TestCache:
    """Test caching functionality."""

    def test_async_lru_cache_initialization(self):
        """Test async LRU cache initialization."""
        from bot.data.dexscreener import AsyncLRUCache

        cache = AsyncLRUCache(maxsize=1000, ttl=300)
        assert cache.maxsize == 1000
        assert cache.ttl == 300
        assert len(cache.cache) == 0

    def test_cache_set_and_get(self):
        """Test cache set and get operations."""
        from bot.data.dexscreener import AsyncLRUCache

        cache = AsyncLRUCache(maxsize=10, ttl=300)

        # Test set and get
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Test non-existent key
        assert cache.get("key2") is None

    def test_cache_ttl_expiration(self):
        """Test cache TTL expiration."""
        import time

        from bot.data.dexscreener import AsyncLRUCache

        cache = AsyncLRUCache(maxsize=10, ttl=0.1)  # Very short TTL

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Wait for TTL to expire
        time.sleep(0.2)
        assert cache.get("key1") is None

    def test_cache_lru_eviction(self):
        """Test cache LRU eviction."""
        from bot.data.dexscreener import AsyncLRUCache

        cache = AsyncLRUCache(maxsize=2, ttl=300)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")  # Should evict key1

        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
