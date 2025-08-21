"""Tests for core data types."""

import json
from datetime import datetime

from bot.core.types import FilterDecision, PoolId, PriceQuote, TokenId, TokenSnapshot


def test_token_id_creation() -> None:
    """Test TokenId creation and validation."""
    token = TokenId(mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

    assert token.chain == "sol"  # Default value
    assert token.mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    # Test with custom chain
    token_eth = TokenId(chain="eth", mint="0xA0b86a33E6441b8c4C8C8C8C8C8C8C8C8C8C8C8C8")
    assert token_eth.chain == "eth"
    assert token_eth.mint == "0xA0b86a33E6441b8c4C8C8C8C8C8C8C8C8C8C8C8C8"


def test_pool_id_creation() -> None:
    """Test PoolId creation and validation."""
    pool = PoolId(
        program="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        address="HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
    )

    assert pool.program == "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
    assert pool.address == "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ"


def test_price_quote_creation() -> None:
    """Test PriceQuote creation and validation."""
    base_token = TokenId(mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    quote_token = TokenId(mint="So11111111111111111111111111111111111111112")

    quote = PriceQuote(
        base=base_token,
        quote=quote_token,
        price=1.0,
        liq_usd=1000000.0,
        vol_5m_usd=50000.0,
        ts=datetime.utcnow(),
    )

    assert quote.base == base_token
    assert quote.quote == quote_token
    assert quote.price == 1.0
    assert quote.liq_usd == 1000000.0
    assert quote.vol_5m_usd == 50000.0
    assert isinstance(quote.ts, datetime)


def test_token_snapshot_creation() -> None:
    """Test TokenSnapshot creation and validation."""
    token = TokenId(mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    pool = PoolId(
        program="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        address="HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
    )

    snapshot = TokenSnapshot(
        token=token,
        pool=pool,
        price_usd=1.0,
        liq_usd=1000000.0,
        vol_5m_usd=50000.0,
        holders=1000,
        age_seconds=86400,
        pct_change_5m=2.5,
        source="jupiter",
        ts=datetime.utcnow(),
    )

    assert snapshot.token == token
    assert snapshot.pool == pool
    assert snapshot.price_usd == 1.0
    assert snapshot.liq_usd == 1000000.0
    assert snapshot.vol_5m_usd == 50000.0
    assert snapshot.holders == 1000
    assert snapshot.age_seconds == 86400
    assert snapshot.pct_change_5m == 2.5
    assert snapshot.source == "jupiter"
    assert isinstance(snapshot.ts, datetime)


def test_token_snapshot_optional_fields() -> None:
    """Test TokenSnapshot with optional fields set to None."""
    token = TokenId(mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

    snapshot = TokenSnapshot(
        token=token,
        price_usd=1.0,
        liq_usd=1000000.0,
        vol_5m_usd=50000.0,
        source="jupiter",
        ts=datetime.utcnow(),
    )

    assert snapshot.pool is None
    assert snapshot.holders is None
    assert snapshot.age_seconds is None
    assert snapshot.pct_change_5m is None


def test_filter_decision_creation() -> None:
    """Test FilterDecision creation and validation."""
    decision = FilterDecision(
        accepted=True,
        score=0.85,
        reasons=["High liquidity", "Good volume", "Stable price"],
    )

    assert decision.accepted is True
    assert decision.score == 0.85
    assert decision.reasons == ["High liquidity", "Good volume", "Stable price"]


def test_filter_decision_default_reasons() -> None:
    """Test FilterDecision with default empty reasons list."""
    decision = FilterDecision(accepted=False, score=0.2)

    assert decision.accepted is False
    assert decision.score == 0.2
    assert decision.reasons == []


def test_json_serialization_token_id() -> None:
    """Test JSON serialization roundtrip for TokenId."""
    token = TokenId(chain="sol", mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

    # Serialize to JSON
    json_str = token.model_dump_json()
    data = json.loads(json_str)

    # Deserialize from JSON
    token_roundtrip = TokenId.model_validate(data)

    assert token_roundtrip == token
    assert token_roundtrip.chain == "sol"
    assert token_roundtrip.mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def test_json_serialization_pool_id() -> None:
    """Test JSON serialization roundtrip for PoolId."""
    pool = PoolId(
        program="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        address="HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
    )

    # Serialize to JSON
    json_str = pool.model_dump_json()
    data = json.loads(json_str)

    # Deserialize from JSON
    pool_roundtrip = PoolId.model_validate(data)

    assert pool_roundtrip == pool


def test_json_serialization_price_quote() -> None:
    """Test JSON serialization roundtrip for PriceQuote."""
    base_token = TokenId(mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    quote_token = TokenId(mint="So11111111111111111111111111111111111111112")

    quote = PriceQuote(
        base=base_token,
        quote=quote_token,
        price=1.0,
        liq_usd=1000000.0,
        vol_5m_usd=50000.0,
        ts=datetime(2023, 1, 1, 12, 0, 0),
    )

    # Serialize to JSON
    json_str = quote.model_dump_json()
    data = json.loads(json_str)

    # Deserialize from JSON
    quote_roundtrip = PriceQuote.model_validate(data)

    assert quote_roundtrip.base == quote.base
    assert quote_roundtrip.quote == quote.quote
    assert quote_roundtrip.price == quote.price
    assert quote_roundtrip.liq_usd == quote.liq_usd
    assert quote_roundtrip.vol_5m_usd == quote.vol_5m_usd
    assert quote_roundtrip.ts == quote.ts


def test_json_serialization_token_snapshot() -> None:
    """Test JSON serialization roundtrip for TokenSnapshot."""
    token = TokenId(mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    pool = PoolId(
        program="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        address="HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
    )

    snapshot = TokenSnapshot(
        token=token,
        pool=pool,
        price_usd=1.0,
        liq_usd=1000000.0,
        vol_5m_usd=50000.0,
        holders=1000,
        age_seconds=86400,
        pct_change_5m=2.5,
        source="jupiter",
        ts=datetime(2023, 1, 1, 12, 0, 0),
    )

    # Serialize to JSON
    json_str = snapshot.model_dump_json()
    data = json.loads(json_str)

    # Deserialize from JSON
    snapshot_roundtrip = TokenSnapshot.model_validate(data)

    assert snapshot_roundtrip.token == snapshot.token
    assert snapshot_roundtrip.pool == snapshot.pool
    assert snapshot_roundtrip.price_usd == snapshot.price_usd
    assert snapshot_roundtrip.liq_usd == snapshot.liq_usd
    assert snapshot_roundtrip.vol_5m_usd == snapshot.vol_5m_usd
    assert snapshot_roundtrip.holders == snapshot.holders
    assert snapshot_roundtrip.age_seconds == snapshot.age_seconds
    assert snapshot_roundtrip.pct_change_5m == snapshot.pct_change_5m
    assert snapshot_roundtrip.source == snapshot.source
    assert snapshot_roundtrip.ts == snapshot.ts


def test_json_serialization_filter_decision() -> None:
    """Test JSON serialization roundtrip for FilterDecision."""
    decision = FilterDecision(
        accepted=True,
        score=0.85,
        reasons=["High liquidity", "Good volume", "Stable price"],
    )

    # Serialize to JSON
    json_str = decision.model_dump_json()
    data = json.loads(json_str)

    # Deserialize from JSON
    decision_roundtrip = FilterDecision.model_validate(data)

    assert decision_roundtrip == decision
    assert decision_roundtrip.accepted is True
    assert decision_roundtrip.score == 0.85
    assert decision_roundtrip.reasons == [
        "High liquidity",
        "Good volume",
        "Stable price",
    ]


def test_token_id_equality() -> None:
    """Test TokenId equality comparison."""
    token1 = TokenId(mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    token2 = TokenId(mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    token3 = TokenId(mint="So11111111111111111111111111111111111111112")

    assert token1 == token2
    assert token1 != token3


def test_pool_id_equality() -> None:
    """Test PoolId equality comparison."""
    pool1 = PoolId(
        program="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        address="HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
    )
    pool2 = PoolId(
        program="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        address="HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
    )
    pool3 = PoolId(
        program="different_program",
        address="HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
    )

    assert pool1 == pool2
    assert pool1 != pool3


def test_complex_nested_serialization() -> None:
    """Test serialization of complex nested structures."""
    # Create a complex structure with all types
    token = TokenId(mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    pool = PoolId(
        program="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        address="HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
    )

    snapshot = TokenSnapshot(
        token=token,
        pool=pool,
        price_usd=1.0,
        liq_usd=1000000.0,
        vol_5m_usd=50000.0,
        holders=1000,
        age_seconds=86400,
        pct_change_5m=2.5,
        source="jupiter",
        ts=datetime(2023, 1, 1, 12, 0, 0),
    )

    decision = FilterDecision(
        accepted=True,
        score=0.85,
        reasons=["High liquidity", "Good volume", "Stable price"],
    )

    # Test that we can serialize the snapshot and decision

    # Test that we can serialize the snapshot and decision
    snapshot_json = snapshot.model_dump_json()
    decision_json = decision.model_dump_json()

    # Verify they can be deserialized
    snapshot_roundtrip = TokenSnapshot.model_validate_json(snapshot_json)
    decision_roundtrip = FilterDecision.model_validate_json(decision_json)

    assert snapshot_roundtrip == snapshot
    assert decision_roundtrip == decision
