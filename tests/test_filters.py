"""Tests for trading filters."""

import pytest
from decimal import Decimal
from datetime import datetime

from bot.core.types import TradeSignal, OrderSide, OrderType
from bot.filters.basic import VolumeFilter, PriceChangeFilter, LiquidityFilter
from bot.filters.rug_heuristics import (
    RugPullFilter,
    ContractVerificationFilter,
    HoneypotFilter,
)


@pytest.fixture
def sample_signal() -> TradeSignal:
    """Create a sample trade signal for testing."""
    return TradeSignal(
        token_address="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        price=Decimal("1.00"),
        confidence=0.8,
        timestamp=datetime.utcnow(),
    )


@pytest.mark.asyncio
async def test_volume_filter_should_trade(sample_signal: TradeSignal) -> None:
    """Test volume filter should_trade method."""
    filter_obj = VolumeFilter(min_volume_usd=Decimal("10000"))
    result = await filter_obj.should_trade(sample_signal)
    assert result is True


@pytest.mark.asyncio
async def test_volume_filter_filter_signal(sample_signal: TradeSignal) -> None:
    """Test volume filter filter_signal method."""
    filter_obj = VolumeFilter(min_volume_usd=Decimal("10000"))
    result = await filter_obj.filter_signal(sample_signal)
    assert result == sample_signal


@pytest.mark.asyncio
async def test_price_change_filter_should_trade(sample_signal: TradeSignal) -> None:
    """Test price change filter should_trade method."""
    filter_obj = PriceChangeFilter(max_change_percent=50.0)
    result = await filter_obj.should_trade(sample_signal)
    assert result is True


@pytest.mark.asyncio
async def test_price_change_filter_filter_signal(sample_signal: TradeSignal) -> None:
    """Test price change filter filter_signal method."""
    filter_obj = PriceChangeFilter(max_change_percent=50.0)
    result = await filter_obj.filter_signal(sample_signal)
    assert result == sample_signal


@pytest.mark.asyncio
async def test_liquidity_filter_should_trade(sample_signal: TradeSignal) -> None:
    """Test liquidity filter should_trade method."""
    filter_obj = LiquidityFilter(min_liquidity_usd=Decimal("50000"))
    result = await filter_obj.should_trade(sample_signal)
    assert result is True


@pytest.mark.asyncio
async def test_liquidity_filter_filter_signal(sample_signal: TradeSignal) -> None:
    """Test liquidity filter filter_signal method."""
    filter_obj = LiquidityFilter(min_liquidity_usd=Decimal("50000"))
    result = await filter_obj.filter_signal(sample_signal)
    assert result == sample_signal


@pytest.mark.asyncio
async def test_rug_pull_filter_should_trade(sample_signal: TradeSignal) -> None:
    """Test rug pull filter should_trade method."""
    filter_obj = RugPullFilter(max_holder_concentration=0.8)
    result = await filter_obj.should_trade(sample_signal)
    assert result is True


@pytest.mark.asyncio
async def test_rug_pull_filter_filter_signal(sample_signal: TradeSignal) -> None:
    """Test rug pull filter filter_signal method."""
    filter_obj = RugPullFilter(max_holder_concentration=0.8)
    result = await filter_obj.filter_signal(sample_signal)
    assert result == sample_signal


@pytest.mark.asyncio
async def test_contract_verification_filter_should_trade(
    sample_signal: TradeSignal,
) -> None:
    """Test contract verification filter should_trade method."""
    filter_obj = ContractVerificationFilter(require_verified=True)
    result = await filter_obj.should_trade(sample_signal)
    assert result is True


@pytest.mark.asyncio
async def test_contract_verification_filter_filter_signal(
    sample_signal: TradeSignal,
) -> None:
    """Test contract verification filter filter_signal method."""
    filter_obj = ContractVerificationFilter(require_verified=True)
    result = await filter_obj.filter_signal(sample_signal)
    assert result == sample_signal


@pytest.mark.asyncio
async def test_honeypot_filter_should_trade(sample_signal: TradeSignal) -> None:
    """Test honeypot filter should_trade method."""
    filter_obj = HoneypotFilter()
    result = await filter_obj.should_trade(sample_signal)
    assert result is True


@pytest.mark.asyncio
async def test_honeypot_filter_filter_signal(sample_signal: TradeSignal) -> None:
    """Test honeypot filter filter_signal method."""
    filter_obj = HoneypotFilter()
    result = await filter_obj.filter_signal(sample_signal)
    assert result == sample_signal
