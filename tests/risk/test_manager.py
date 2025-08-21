"""Tests for risk manager."""

import time
from datetime import datetime

from bot.core.types import TokenId, TokenSnapshot
from bot.risk.manager import RiskManagerImpl


class TestRiskManagerImpl:
    """Test risk manager implementation."""

    def test_init(self):
        """Test risk manager initialization."""
        rm = RiskManagerImpl(
            position_size_usd=100.0,
            daily_max_loss_usd=500.0,
            cooldown_seconds=60,
            max_concurrent_positions=5,
        )

        assert rm.position_size_usd == 100.0
        assert rm.daily_max_loss_usd == 500.0
        assert rm.cooldown_seconds == 60
        assert rm.max_concurrent_positions == 5
        assert rm.daily_pnl == 0.0
        assert rm.remaining_daily_budget == 500.0

    def test_size_usd_basic(self):
        """Test basic position sizing."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        size = rm.size_usd(snap)
        assert size == 100.0

    def test_size_usd_capped_by_daily_budget(self):
        """Test position size capped by daily budget."""
        rm = RiskManagerImpl(
            position_size_usd=100.0,
            daily_max_loss_usd=50.0,  # Small daily budget
            cooldown_seconds=60,
        )

        # Add some losses to reduce remaining budget
        rm.after_fill(-30.0)  # -$30 loss

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        size = rm.size_usd(snap)
        # Should be capped by remaining budget (50 - 30 = 20)
        assert size == 20.0

    def test_size_usd_zero_when_budget_exhausted(self):
        """Test position size is zero when daily budget exhausted."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=50.0, cooldown_seconds=60
        )

        # Exhaust daily budget
        rm.after_fill(-50.0)

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        size = rm.size_usd(snap)
        assert size == 0.0

    def test_size_usd_capped_by_liquidity(self):
        """Test position size capped by liquidity."""
        rm = RiskManagerImpl(
            position_size_usd=1000.0,  # Large position size
            daily_max_loss_usd=5000.0,
            cooldown_seconds=60,
        )

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=5000.0,  # Low liquidity
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        size = rm.size_usd(snap)
        # Should be capped by liquidity (5000 / 10 = 500)
        assert size == 500.0

    def test_allow_buy_basic(self):
        """Test basic buy permission."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        allowed, reasons = rm.allow_buy(snap)
        assert allowed is True
        assert reasons == []

    def test_allow_buy_daily_loss_exceeded(self):
        """Test buy denied when daily loss exceeded."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=50.0, cooldown_seconds=60
        )

        # Exhaust daily budget
        rm.after_fill(-50.0)

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        allowed, reasons = rm.allow_buy(snap)
        assert allowed is False
        assert "Daily loss limit exceeded" in reasons

    def test_allow_buy_cooldown(self):
        """Test buy denied during cooldown."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        # Set cooldown
        rm.set_cooldown("test_token")

        allowed, reasons = rm.allow_buy(snap)
        assert allowed is False
        assert any("cooldown" in reason.lower() for reason in reasons)

    def test_allow_buy_max_concurrent_positions(self):
        """Test buy denied when max concurrent positions reached."""
        rm = RiskManagerImpl(
            position_size_usd=100.0,
            daily_max_loss_usd=500.0,
            cooldown_seconds=60,
            max_concurrent_positions=2,
        )

        # Add maximum positions
        rm.record_position("token1", 50.0)
        rm.record_position("token2", 50.0)

        snap = TokenSnapshot(
            token=TokenId(mint="token3"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        allowed, reasons = rm.allow_buy(snap)
        assert allowed is False
        assert "Maximum concurrent positions reached" in reasons

    def test_allow_buy_already_has_position(self):
        """Test buy denied when already have position in token."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        # Add position
        rm.record_position("test_token", 50.0)

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        allowed, reasons = rm.allow_buy(snap)
        assert allowed is False
        assert "Already have position in this token" in reasons

    def test_allow_buy_insufficient_liquidity(self):
        """Test buy denied for insufficient liquidity."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=500.0,  # Below minimum 1000
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        allowed, reasons = rm.allow_buy(snap)
        assert allowed is False
        assert "Insufficient liquidity" in reasons

    def test_allow_buy_insufficient_volume(self):
        """Test buy denied for insufficient volume."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=50.0,  # Below minimum 100
            source="test",
            ts=datetime.now(),
        )

        allowed, reasons = rm.allow_buy(snap)
        assert allowed is False
        assert "Insufficient trading volume" in reasons

    def test_allow_buy_invalid_price(self):
        """Test buy denied for invalid price."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=0.0,  # Invalid price
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        allowed, reasons = rm.allow_buy(snap)
        assert allowed is False
        assert "Invalid price" in reasons

    def test_after_fill_profit(self):
        """Test after_fill with profit."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        initial_pnl = rm.daily_pnl
        rm.after_fill(25.0)  # $25 profit

        assert rm.daily_pnl == initial_pnl + 25.0
        assert rm.remaining_daily_budget == 500.0 + (initial_pnl + 25.0)

    def test_after_fill_loss(self):
        """Test after_fill with loss."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        initial_pnl = rm.daily_pnl
        rm.after_fill(-30.0)  # $30 loss

        assert rm.daily_pnl == initial_pnl - 30.0
        assert rm.remaining_daily_budget == 500.0 + (initial_pnl - 30.0)

    def test_record_and_close_position(self):
        """Test recording and closing positions."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        # Record position
        rm.record_position("test_token", 50.0)
        assert len(rm._active_positions) == 1
        assert "test_token" in rm._active_positions
        assert rm._position_sizes["test_token"] == 50.0

        # Get position info
        info = rm.get_position_info("test_token")
        assert info is not None
        assert info["token_mint"] == "test_token"
        assert info["size_usd"] == 50.0

        # Close position
        rm.close_position("test_token")
        assert len(rm._active_positions) == 0
        assert "test_token" not in rm._active_positions
        assert "test_token" not in rm._position_sizes

    def test_get_state_summary(self):
        """Test getting state summary."""
        rm = RiskManagerImpl(
            position_size_usd=100.0,
            daily_max_loss_usd=500.0,
            cooldown_seconds=60,
            max_concurrent_positions=5,
        )

        # Add some activity
        rm.after_fill(-25.0)
        rm.record_position("token1", 50.0)

        summary = rm.get_state_summary()

        assert summary["daily_pnl"] == -25.0
        assert summary["remaining_daily_budget"] == 475.0  # 500 + (-25)
        assert summary["active_positions"] == 1
        assert summary["max_concurrent_positions"] == 5
        assert summary["position_size_usd"] == 100.0
        assert summary["daily_max_loss_usd"] == 500.0
        assert summary["cooldown_seconds"] == 60
        assert "day_start" in summary


class TestRiskManagerTimeBased:
    """Test risk manager with time-based functionality."""

    def test_daily_reset(self):
        """Test daily P&L reset on new day."""
        # Mock time function that advances to next day
        current_time = [time.time()]

        def mock_now():
            return current_time[0]

        rm = RiskManagerImpl(
            position_size_usd=100.0,
            daily_max_loss_usd=500.0,
            cooldown_seconds=60,
            now_fn=mock_now,
        )

        # Add some P&L
        rm.after_fill(-100.0)
        assert rm.daily_pnl == -100.0

        # Advance time to next day
        current_time[0] += 86400  # Add 24 hours

        # Access daily_pnl again (should trigger reset)
        pnl = rm.daily_pnl
        assert pnl == 0.0  # Should reset to 0 for new day

    def test_cooldown_expiration(self):
        """Test cooldown expiration."""
        current_time = [time.time()]

        def mock_now():
            return current_time[0]

        rm = RiskManagerImpl(
            position_size_usd=100.0,
            daily_max_loss_usd=500.0,
            cooldown_seconds=60,
            now_fn=mock_now,
        )

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        # Set cooldown
        rm.set_cooldown("test_token")

        # Should be in cooldown
        allowed, reasons = rm.allow_buy(snap)
        assert allowed is False
        assert any("cooldown" in reason.lower() for reason in reasons)

        # Advance time past cooldown
        current_time[0] += 61  # 61 seconds later

        # Should be allowed now
        allowed, reasons = rm.allow_buy(snap)
        assert allowed is True
        assert reasons == []

    def test_multiple_reasons(self):
        """Test multiple reasons for buy denial."""
        rm = RiskManagerImpl(
            position_size_usd=100.0,
            daily_max_loss_usd=50.0,  # Small budget
            cooldown_seconds=60,
            max_concurrent_positions=1,
        )

        # Exhaust daily budget
        rm.after_fill(-50.0)

        # Add a position to reach max concurrent
        rm.record_position("token1", 25.0)

        snap = TokenSnapshot(
            token=TokenId(mint="token2"),
            price_usd=0.0,  # Invalid price
            liq_usd=500.0,  # Low liquidity
            vol_5m_usd=50.0,  # Low volume
            source="test",
            ts=datetime.now(),
        )

        allowed, reasons = rm.allow_buy(snap)
        assert allowed is False
        assert len(reasons) >= 4  # Should have multiple reasons
        assert "Daily loss limit exceeded" in reasons
        assert "Maximum concurrent positions reached" in reasons
        assert "Invalid price" in reasons
        assert "Insufficient liquidity" in reasons
        assert "Insufficient trading volume" in reasons


class TestRiskManagerEdgeCases:
    """Test risk manager edge cases."""

    def test_zero_position_size(self):
        """Test with zero position size."""
        rm = RiskManagerImpl(
            position_size_usd=0.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        size = rm.size_usd(snap)
        assert size == 0.0

    def test_negative_daily_loss(self):
        """Test with negative daily loss limit."""
        rm = RiskManagerImpl(
            position_size_usd=100.0,
            daily_max_loss_usd=-100.0,  # Negative limit
            cooldown_seconds=60,
        )

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        # Should be denied since we start with negative budget
        allowed, reasons = rm.allow_buy(snap)
        assert allowed is False
        assert "Daily loss limit exceeded" in reasons

    def test_zero_cooldown(self):
        """Test with zero cooldown."""
        rm = RiskManagerImpl(
            position_size_usd=100.0,
            daily_max_loss_usd=500.0,
            cooldown_seconds=0,  # No cooldown
        )

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        # Record position
        rm.record_position("test_token", 50.0)

        # Should still be denied because we already have position
        allowed, reasons = rm.allow_buy(snap)
        assert allowed is False
        assert "Already have position in this token" in reasons

    def test_close_nonexistent_position(self):
        """Test closing a position that doesn't exist."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        # Should not raise an error
        rm.close_position("nonexistent_token")

        # State should remain unchanged
        assert len(rm._active_positions) == 0

    def test_get_nonexistent_position_info(self):
        """Test getting info for nonexistent position."""
        rm = RiskManagerImpl(
            position_size_usd=100.0, daily_max_loss_usd=500.0, cooldown_seconds=60
        )

        info = rm.get_position_info("nonexistent_token")
        assert info is None
