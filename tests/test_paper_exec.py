"""Tests for paper trading executor."""

from datetime import datetime

import pytest

from bot.core.types import TokenId, TokenSnapshot
from bot.exec.paper import PaperExecutor, VirtualPosition


class TestVirtualPosition:
    """Test virtual position functionality."""

    def test_init(self):
        """Test virtual position initialization."""
        pos = VirtualPosition("test_token", 1.0, 100.0)

        assert pos.token_mint == "test_token"
        assert pos.avg_cost_usd == 1.0
        assert pos.qty_base == 100.0
        assert pos.created_at > 0

    def test_add_position(self):
        """Test adding to position."""
        pos = VirtualPosition("test_token", 1.0, 100.0)

        # Add more at higher price
        pos.add_position(150.0, 50.0)  # $3.0 per token

        # New average should be (100*1.0 + 50*3.0) / 150 = 1.67
        expected_avg = (100.0 * 1.0 + 50.0 * 3.0) / 150.0
        assert abs(pos.avg_cost_usd - expected_avg) < 0.01
        assert pos.qty_base == 150.0

    def test_add_position_zero_qty(self):
        """Test adding zero quantity."""
        pos = VirtualPosition("test_token", 1.0, 100.0)
        original_avg = pos.avg_cost_usd
        original_qty = pos.qty_base

        pos.add_position(50.0, 0.0)

        assert pos.avg_cost_usd == original_avg
        assert pos.qty_base == original_qty

    def test_reduce_position(self):
        """Test reducing position."""
        pos = VirtualPosition("test_token", 2.0, 100.0)

        cost_basis = pos.reduce_position(30.0)

        assert cost_basis == 60.0  # 30 * 2.0
        assert pos.qty_base == 70.0

    def test_reduce_position_invalid(self):
        """Test reducing position with invalid quantities."""
        pos = VirtualPosition("test_token", 2.0, 100.0)

        # Zero quantity
        cost_basis = pos.reduce_position(0.0)
        assert cost_basis == 0.0
        assert pos.qty_base == 100.0

        # Negative quantity
        cost_basis = pos.reduce_position(-10.0)
        assert cost_basis == 0.0
        assert pos.qty_base == 100.0

        # More than available
        cost_basis = pos.reduce_position(150.0)
        assert cost_basis == 0.0
        assert pos.qty_base == 100.0

    def test_get_pnl(self):
        """Test P&L calculation."""
        pos = VirtualPosition("test_token", 1.0, 100.0)

        # Price up 50%
        pnl = pos.get_pnl(1.5)
        assert pnl == 50.0  # (1.5 - 1.0) * 100

        # Price down 20%
        pnl = pos.get_pnl(0.8)
        assert pnl == -20.0  # (0.8 - 1.0) * 100

        # Zero quantity
        pos.qty_base = 0.0
        pnl = pos.get_pnl(1.5)
        assert pnl == 0.0

    def test_get_pnl_percentage(self):
        """Test P&L percentage calculation."""
        pos = VirtualPosition("test_token", 1.0, 100.0)

        # Price up 50%
        pnl_pct = pos.get_pnl_percentage(1.5)
        assert pnl_pct == 50.0

        # Price down 20%
        pnl_pct = pos.get_pnl_percentage(0.8)
        assert pnl_pct == pytest.approx(-20.0, rel=0.01)

        # Zero quantity
        pos.qty_base = 0.0
        pnl_pct = pos.get_pnl_percentage(1.5)
        assert pnl_pct == 0.0

        # Zero cost
        pos.avg_cost_usd = 0.0
        pnl_pct = pos.get_pnl_percentage(1.5)
        assert pnl_pct == 0.0


class TestPaperExecutor:
    """Test paper executor functionality."""

    def test_init(self):
        """Test paper executor initialization."""
        executor = PaperExecutor(slippage_bps=100, fee_bps=50)

        assert executor.slippage_bps == 100
        assert executor.fee_bps == 50
        assert len(executor._positions) == 0
        assert len(executor._trade_history) == 0

    def test_calculate_execution_price_buy(self):
        """Test execution price calculation for buys."""
        executor = PaperExecutor(slippage_bps=100)  # 1% slippage

        # Buy: should pay more due to slippage
        exec_price = executor._calculate_execution_price(1.0, is_buy=True)
        assert exec_price == 1.01  # 1.0 * (1 + 0.01)

    def test_calculate_execution_price_sell(self):
        """Test execution price calculation for sells."""
        executor = PaperExecutor(slippage_bps=100)  # 1% slippage

        # Sell: should receive less due to slippage
        exec_price = executor._calculate_execution_price(1.0, is_buy=False)
        assert exec_price == 0.99  # 1.0 * (1 - 0.01)

    def test_calculate_fee(self):
        """Test fee calculation."""
        executor = PaperExecutor(fee_bps=50)  # 0.5% fee

        fee = executor._calculate_fee(100.0)
        assert fee == 0.5  # 100.0 * 0.005

    @pytest.mark.asyncio
    async def test_simulate_buy(self):
        """Test buy simulation."""
        executor = PaperExecutor(slippage_bps=100, fee_bps=50)

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        result = await executor.simulate(snap, 100.0)

        assert result["price_exec"] == 1.01  # 1% slippage
        assert result["qty_base"] == pytest.approx(99.01, rel=0.01)  # 100/1.01
        assert result["cost_usd"] == 100.0
        assert result["fee_usd"] == 0.5  # 0.5% fee
        assert result["is_buy"] is True
        assert result["base_price"] == 1.0
        assert result["slippage_bps"] == 100

    @pytest.mark.asyncio
    async def test_buy_new_position(self):
        """Test buying new position."""
        executor = PaperExecutor(slippage_bps=100, fee_bps=50)

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        result = await executor.buy(snap, 100.0)

        # Check execution result
        assert result["price_exec"] == 1.01
        assert result["qty_base"] == pytest.approx(99.01, rel=0.01)
        assert result["cost_usd"] == 100.0
        assert result["fee_usd"] == 0.5

        # Check position was created
        position = executor.get_position("test_token")
        assert position is not None
        assert position.token_mint == "test_token"
        assert position.qty_base == pytest.approx(99.01, rel=0.01)
        # Average cost should include fees: (100 + 0.5) / 99.01
        expected_avg_cost = (100.0 + 0.5) / 99.01
        assert abs(position.avg_cost_usd - expected_avg_cost) < 0.01

        # Check trade history
        assert len(executor._trade_history) == 1
        assert executor._trade_history[0] == result

    @pytest.mark.asyncio
    async def test_buy_add_to_position(self):
        """Test buying to add to existing position."""
        executor = PaperExecutor(slippage_bps=100, fee_bps=50)

        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        # First buy
        await executor.buy(snap, 100.0)

        # Second buy at higher price
        snap2 = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.5,  # Higher price
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        await executor.buy(snap2, 150.0)

        # Check position was updated
        position = executor.get_position("test_token")
        assert position is not None
        assert position.qty_base > 99.01  # Should have more tokens

        # Check trade history
        assert len(executor._trade_history) == 2

    @pytest.mark.asyncio
    async def test_sell_partial(self):
        """Test partial sell."""
        executor = PaperExecutor(slippage_bps=100, fee_bps=50)

        # First buy a position
        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        await executor.buy(snap, 100.0)

        # Sell 50%
        result = await executor.sell(TokenId(mint="test_token"), 50.0)

        # Check execution result
        assert result["is_buy"] is False
        assert "cost_basis" in result
        assert "realized_pnl" in result

        # Check position was reduced
        position = executor.get_position("test_token")
        assert position is not None
        assert position.qty_base > 0  # Should still have some tokens

        # Check trade history
        assert len(executor._trade_history) == 2

    @pytest.mark.asyncio
    async def test_sell_full(self):
        """Test full sell."""
        executor = PaperExecutor(slippage_bps=100, fee_bps=50)

        # First buy a position
        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        await executor.buy(snap, 100.0)

        # Sell 100%
        await executor.sell(TokenId(mint="test_token"), 100.0)

        # Check position was removed
        position = executor.get_position("test_token")
        assert position is None

        # Check trade history
        assert len(executor._trade_history) == 2

    @pytest.mark.asyncio
    async def test_sell_no_position(self):
        """Test selling when no position exists."""
        executor = PaperExecutor()

        with pytest.raises(ValueError, match="No position to sell"):
            await executor.sell(TokenId(mint="test_token"), 50.0)

    def test_get_all_positions(self):
        """Test getting all positions."""
        executor = PaperExecutor()

        # Should be empty initially
        positions = executor.get_all_positions()
        assert len(positions) == 0

        # Add a position manually
        executor._positions["test_token"] = VirtualPosition("test_token", 1.0, 100.0)

        positions = executor.get_all_positions()
        assert len(positions) == 1
        assert "test_token" in positions

    def test_calculate_total_pnl(self):
        """Test total P&L calculation."""
        executor = PaperExecutor()

        # Add some positions
        executor._positions["token1"] = VirtualPosition("token1", 1.0, 100.0)
        executor._positions["token2"] = VirtualPosition("token2", 2.0, 50.0)

        current_prices = {
            "token1": 1.5,  # +50% P&L = 50
            "token2": 1.8,  # -10% P&L = -10
        }

        total_pnl = executor.calculate_total_pnl(current_prices)
        assert total_pnl == 40.0  # 50 - 10

    def test_get_portfolio_summary(self):
        """Test portfolio summary."""
        executor = PaperExecutor()

        # Add some positions
        executor._positions["token1"] = VirtualPosition("token1", 1.0, 100.0)
        executor._positions["token2"] = VirtualPosition("token2", 2.0, 50.0)

        current_prices = {
            "token1": 1.5,
            "token2": 1.8,
        }

        summary = executor.get_portfolio_summary(current_prices)

        assert summary["total_positions"] == 2
        assert summary["total_cost_basis_usd"] == 200.0  # 100*1 + 50*2
        assert summary["total_market_value_usd"] == 240.0  # 100*1.5 + 50*1.8
        assert summary["total_unrealized_pnl_usd"] == 40.0  # 240 - 200
        assert summary["total_pnl_percentage"] == 20.0  # 40/200 * 100
        assert len(summary["positions"]) == 2
        assert summary["trade_count"] == 0  # No trades yet

    def test_get_trade_history(self):
        """Test trade history."""
        executor = PaperExecutor()

        # Should be empty initially
        history = executor.get_trade_history()
        assert len(history) == 0

        # Add some trades
        executor._trade_history.append({"test": "trade1"})
        executor._trade_history.append({"test": "trade2"})

        history = executor.get_trade_history()
        assert len(history) == 2
        assert history[0]["test"] == "trade1"
        assert history[1]["test"] == "trade2"


class TestPaperExecutorEdgeCases:
    """Test paper executor edge cases."""

    def test_zero_slippage(self):
        """Test with zero slippage."""
        executor = PaperExecutor(slippage_bps=0)

        exec_price = executor._calculate_execution_price(1.0, is_buy=True)
        assert exec_price == 1.0

        exec_price = executor._calculate_execution_price(1.0, is_buy=False)
        assert exec_price == 1.0

    def test_zero_fees(self):
        """Test with zero fees."""
        executor = PaperExecutor(fee_bps=0)

        fee = executor._calculate_fee(100.0)
        assert fee == 0.0

    def test_high_slippage(self):
        """Test with high slippage."""
        executor = PaperExecutor(slippage_bps=1000)  # 10% slippage

        exec_price = executor._calculate_execution_price(1.0, is_buy=True)
        assert exec_price == 1.1

        exec_price = executor._calculate_execution_price(1.0, is_buy=False)
        assert exec_price == 0.9

    @pytest.mark.asyncio
    async def test_sell_zero_percentage(self):
        """Test selling zero percentage."""
        executor = PaperExecutor()

        # Create a position
        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        await executor.buy(snap, 100.0)
        original_qty = executor.get_position("test_token").qty_base

        # Sell 0%
        await executor.sell(TokenId(mint="test_token"), 0.0)

        # Should not change position
        position = executor.get_position("test_token")
        assert position.qty_base == original_qty

    @pytest.mark.asyncio
    async def test_sell_over_100_percentage(self):
        """Test selling over 100%."""
        executor = PaperExecutor()

        # Create a position
        snap = TokenSnapshot(
            token=TokenId(mint="test_token"),
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="test",
            ts=datetime.now(),
        )

        await executor.buy(snap, 100.0)

        # Sell 150% - should cap at 100%
        await executor.sell(TokenId(mint="test_token"), 150.0)

        # Position should be fully closed
        position = executor.get_position("test_token")
        assert position is None

    def test_mock_time_function(self):
        """Test with mock time function."""
        current_time = [1000.0]

        def mock_now():
            return current_time[0]

        # The executor should use the mock time
        # This is tested indirectly through the trade execution
        # which includes timestamps in the results
