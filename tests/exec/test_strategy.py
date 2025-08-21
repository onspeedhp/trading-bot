"""Tests for trading strategy implementation."""

from datetime import datetime, timedelta

import pytest

from bot.core.interfaces import ExecutionClient, Persistence, RiskManager
from bot.core.types import TokenId, TokenSnapshot
from bot.exec.strategy import (
    PositionState,
    TradingStrategy,
    calculate_pnl_percentage,
    calculate_position_value,
    calculate_remaining_hold_time,
    calculate_take_profit_levels,
    calculate_trailing_stop_price,
)


class MockExecutionClient(ExecutionClient):
    """Mock execution client for testing."""

    def __init__(self):
        self.buy_count = 0
        self.sell_count = 0
        self.simulate_count = 0
        self.buy_results = []
        self.sell_results = []

    async def simulate(self, snapshot: TokenSnapshot, usd_amount: float) -> dict:
        """Mock simulation."""
        self.simulate_count += 1
        return {
            "qty_base": usd_amount / snapshot.price_usd,
            "price_exec": snapshot.price_usd,
            "cost_usd": usd_amount,
            "fee_usd": usd_amount * 0.001,
            "price_impact_pct": 0.1,
        }

    async def buy(self, snapshot: TokenSnapshot, usd_amount: float) -> dict:
        """Mock buy execution."""
        self.buy_count += 1
        result = {
            "qty_base": usd_amount / snapshot.price_usd,
            "price_exec": snapshot.price_usd,
            "cost_usd": usd_amount,
            "fee_usd": usd_amount * 0.001,
            "ts": datetime.now(),
        }
        self.buy_results.append(result)
        return result

    async def sell(self, token: TokenId, pct: float) -> dict:
        """Mock sell execution."""
        self.sell_count += 1
        result = {
            "qty_base": 100.0 * pct,  # Mock quantity
            "price_exec": 1.5,  # Mock sell price
            "cost_usd": 100.0 * pct * 1.5,
            "fee_usd": 100.0 * pct * 1.5 * 0.001,
            "ts": datetime.now(),
        }
        self.sell_results.append(result)
        return result


class MockRiskManager(RiskManager):
    """Mock risk manager for testing."""

    def __init__(self, allow_all: bool = True, position_size: float = 50.0):
        self.allow_all = allow_all
        self.position_size = position_size
        self.allow_buy_calls = 0
        self.size_usd_calls = 0
        self.after_fill_calls = 0

    def size_usd(self, snap: TokenSnapshot) -> float:
        """Mock position sizing."""
        self.size_usd_calls += 1
        return self.position_size

    def allow_buy(self, snap: TokenSnapshot) -> tuple[bool, list[str]]:
        """Mock buy permission."""
        self.allow_buy_calls += 1
        if self.allow_all:
            return True, []
        else:
            return False, ["Risk limit exceeded"]

    def after_fill(self, pnl_usd: float) -> None:
        """Mock after fill update."""
        self.after_fill_calls += 1


class MockStorage(Persistence):
    """Mock storage for testing."""

    def __init__(self):
        self.save_state_calls = 0
        self.load_state_calls = 0
        self.stored_data = {}

    async def upsert_position(
        self, token_mint: str, qty: float, avg_cost_usd: float
    ) -> None:
        """Mock position upsert."""
        pass

    async def record_trade(
        self, token_mint: str, side: str, qty: float, px: float, fee_usd: float
    ) -> None:
        """Mock trade recording."""
        pass

    async def load_positions(self) -> list[dict]:
        """Mock position loading."""
        return []

    async def load_state(self, key: str) -> str | None:
        """Mock state loading."""
        self.load_state_calls += 1
        return self.stored_data.get(key)

    async def save_state(self, key: str, value: str) -> None:
        """Mock state saving."""
        self.save_state_calls += 1
        self.stored_data[key] = value

    async def save_state_json(self, key: str, value: dict) -> None:
        """Mock JSON state saving."""
        self.save_state_calls += 1
        self.stored_data[key] = value

    async def load_state_json(self, key: str) -> dict | None:
        """Mock JSON state loading."""
        self.load_state_calls += 1
        return self.stored_data.get(key)


def create_snapshot(token_mint: str, price_usd: float, **kwargs) -> TokenSnapshot:
    """Create a test token snapshot."""
    return TokenSnapshot(
        token=TokenId(mint=token_mint),
        price_usd=price_usd,
        liq_usd=kwargs.get("liq_usd", 100000.0),
        vol_5m_usd=kwargs.get("vol_5m_usd", 50000.0),
        holders=kwargs.get("holders", 1000),
        age_seconds=kwargs.get("age_seconds", 3600),
        pct_change_5m=kwargs.get("pct_change_5m", 5.0),
        source="test",
        ts=kwargs.get("ts", datetime.now()),
    )


class TestPositionState:
    """Test PositionState class."""

    def test_position_state_creation(self):
        """Test position state creation."""
        entry_time = datetime.now()
        position = PositionState(
            token_mint="TestToken123",
            entry_price_usd=1.0,
            quantity=100.0,
            entry_time=entry_time,
            high_water_mark=1.2,
            trailing_stop_price=0.9,
        )

        assert position.token_mint == "TestToken123"
        assert position.entry_price_usd == 1.0
        assert position.quantity == 100.0
        assert position.entry_time == entry_time
        assert position.high_water_mark == 1.2
        assert position.trailing_stop_price == 0.9
        assert position.partial_sells == []

    def test_position_state_serialization(self):
        """Test position state serialization/deserialization."""
        entry_time = datetime.now()
        position = PositionState(
            token_mint="TestToken123",
            entry_price_usd=1.0,
            quantity=100.0,
            entry_time=entry_time,
            high_water_mark=1.2,
            trailing_stop_price=0.9,
            partial_sells=[{"timestamp": "2024-01-01T00:00:00", "quantity": 25.0}],
        )

        # Convert to dict and back
        data = position.to_dict()
        restored = PositionState.from_dict(data)

        assert restored.token_mint == position.token_mint
        assert restored.entry_price_usd == position.entry_price_usd
        assert restored.quantity == position.quantity
        assert restored.high_water_mark == position.high_water_mark
        assert restored.trailing_stop_price == position.trailing_stop_price
        assert len(restored.partial_sells) == len(position.partial_sells)


class TestTradingStrategy:
    """Test TradingStrategy class."""

    @pytest.fixture
    def strategy(self):
        """Create a test strategy instance."""
        exec_client = MockExecutionClient()
        risk_manager = MockRiskManager()
        storage = MockStorage()

        return TradingStrategy(
            exec_client=exec_client,
            risk_manager=risk_manager,
            storage=storage,
            take_profit_levels=[(2.0, 0.25), (3.0, 0.25)],
            trailing_stop_pct=0.15,
            max_hold_time_hours=24.0,
        )

    @pytest.mark.asyncio
    async def test_strategy_initialization(self, strategy):
        """Test strategy initialization."""
        assert strategy.take_profit_levels == [(2.0, 0.25), (3.0, 0.25)]
        assert strategy.trailing_stop_pct == 0.15
        assert strategy.max_hold_time_hours == 24.0
        assert len(strategy.get_active_positions()) == 0

    @pytest.mark.asyncio
    async def test_on_signal_success(self, strategy):
        """Test successful signal processing."""
        snapshot = create_snapshot("TestToken123", 1.0)

        result = await strategy.on_signal(snapshot)

        assert result is not None
        assert strategy.exec_client.buy_count == 1
        assert strategy.risk_manager.allow_buy_calls == 1
        assert strategy.risk_manager.size_usd_calls == 1
        assert strategy.risk_manager.after_fill_calls == 1

        # Check position was created
        positions = strategy.get_active_positions()
        assert "TestToken123" in positions
        position = positions["TestToken123"]
        assert position.entry_price_usd == 1.0
        assert position.quantity == 50.0  # position_size / price
        assert position.high_water_mark == 1.0
        assert position.trailing_stop_price == 0.85  # 1.0 * (1 - 0.15)

    @pytest.mark.asyncio
    async def test_on_signal_risk_rejection(self, strategy):
        """Test signal rejection by risk manager."""
        strategy.risk_manager.allow_all = False
        snapshot = create_snapshot("TestToken123", 1.0)

        result = await strategy.on_signal(snapshot)

        assert result is None
        assert strategy.exec_client.buy_count == 0
        assert strategy.risk_manager.allow_buy_calls == 1
        assert len(strategy.get_active_positions()) == 0

    @pytest.mark.asyncio
    async def test_on_signal_zero_position_size(self, strategy):
        """Test signal rejection due to zero position size."""
        strategy.risk_manager.position_size = 0.0
        snapshot = create_snapshot("TestToken123", 1.0)

        result = await strategy.on_signal(snapshot)

        assert result is None
        assert strategy.exec_client.buy_count == 0
        assert len(strategy.get_active_positions()) == 0

    @pytest.mark.asyncio
    async def test_on_signal_existing_position(self, strategy):
        """Test signal rejection when position already exists."""
        snapshot = create_snapshot("TestToken123", 1.0)

        # Create initial position
        await strategy.on_signal(snapshot)
        initial_buy_count = strategy.exec_client.buy_count

        # Try to create another position
        result = await strategy.on_signal(snapshot)

        assert result is None
        assert strategy.exec_client.buy_count == initial_buy_count  # No additional buy

    @pytest.mark.asyncio
    async def test_take_profits_2x_level(self, strategy):
        """Test take profit at 2x level."""
        # Create position at $1.00
        snapshot = create_snapshot("TestToken123", 1.0)
        await strategy.on_signal(snapshot)

        # Price moves to $2.00 (2x)
        snapshot_2x = create_snapshot("TestToken123", 2.0)
        result = await strategy.take_profits(snapshot_2x)

        assert result is not None
        assert strategy.exec_client.sell_count == 1

        # Check position was partially sold
        position = strategy.get_position("TestToken123")
        assert position is not None
        assert position.quantity == 37.5  # 50 - (50 * 0.25)
        assert len(position.partial_sells) == 1
        assert position.partial_sells[0]["level"] == 2.0
        assert position.partial_sells[0]["reason"] == "take_profit"

    @pytest.mark.asyncio
    async def test_take_profits_3x_level(self, strategy):
        """Test take profit at 3x level."""
        # Create position at $1.00
        snapshot = create_snapshot("TestToken123", 1.0)
        await strategy.on_signal(snapshot)

        # First trigger 2x level
        snapshot_2x = create_snapshot("TestToken123", 2.0)
        result = await strategy.take_profits(snapshot_2x)
        assert result is not None
        assert strategy.exec_client.sell_count == 1

        # Then trigger 3x level
        snapshot_3x = create_snapshot("TestToken123", 3.0)
        result = await strategy.take_profits(snapshot_3x)

        assert result is not None
        assert strategy.exec_client.sell_count == 2

        # Check position was partially sold
        position = strategy.get_position("TestToken123")
        assert position is not None
        assert position.quantity == 28.125  # 50 - (50 * 0.25) - (37.5 * 0.25)
        assert len(position.partial_sells) == 2
        assert position.partial_sells[0]["level"] == 2.0
        assert position.partial_sells[1]["level"] == 3.0

    @pytest.mark.asyncio
    async def test_take_profits_no_position(self, strategy):
        """Test take profits with no position."""
        snapshot = create_snapshot("TestToken123", 2.0)
        result = await strategy.take_profits(snapshot)

        assert result is None
        assert strategy.exec_client.sell_count == 0

    @pytest.mark.asyncio
    async def test_take_profits_already_sold(self, strategy):
        """Test take profits when already sold at level."""
        # Create position at $1.00
        snapshot = create_snapshot("TestToken123", 1.0)
        await strategy.on_signal(snapshot)

        # Sell at 2x
        snapshot_2x = create_snapshot("TestToken123", 2.0)
        await strategy.take_profits(snapshot_2x)
        initial_sell_count = strategy.exec_client.sell_count

        # Try to sell again at 2x
        result = await strategy.take_profits(snapshot_2x)

        assert result is None
        assert (
            strategy.exec_client.sell_count == initial_sell_count
        )  # No additional sell

    @pytest.mark.asyncio
    async def test_trailing_stop_update(self, strategy):
        """Test trailing stop price updates."""
        # Create position at $1.00
        snapshot = create_snapshot("TestToken123", 1.0)
        await strategy.on_signal(snapshot)

        # Price moves up to $1.50
        snapshot_up = create_snapshot("TestToken123", 1.5)
        result = await strategy.trailing_stop(snapshot_up)

        assert result is None  # No stop triggered
        position = strategy.get_position("TestToken123")
        assert position.high_water_mark == 1.5
        assert position.trailing_stop_price == 1.275  # 1.5 * (1 - 0.15)

    @pytest.mark.asyncio
    async def test_trailing_stop_triggered(self, strategy):
        """Test trailing stop being triggered."""
        # Create position at $1.00
        snapshot = create_snapshot("TestToken123", 1.0)
        await strategy.on_signal(snapshot)

        # Price moves up to $1.50 (updates stop to 1.275)
        snapshot_up = create_snapshot("TestToken123", 1.5)
        await strategy.trailing_stop(snapshot_up)

        # Price drops to $1.20 (below stop)
        snapshot_down = create_snapshot("TestToken123", 1.20)
        result = await strategy.trailing_stop(snapshot_down)

        assert result is not None
        assert strategy.exec_client.sell_count == 1

        # Position should be closed
        assert strategy.get_position("TestToken123") is None

    @pytest.mark.asyncio
    async def test_time_stop_triggered(self, strategy):
        """Test time-based stop being triggered."""
        # Create position with old entry time
        old_time = datetime.now() - timedelta(hours=25)  # Exceeds 24 hours
        snapshot = create_snapshot("TestToken123", 1.0)

        # Manually create position with old time
        position = PositionState(
            token_mint="TestToken123",
            entry_price_usd=1.0,
            quantity=50.0,
            entry_time=old_time,
        )
        strategy._positions["TestToken123"] = position

        # Check time stop
        result = await strategy.time_stop(snapshot)

        assert result is not None
        assert strategy.exec_client.sell_count == 1

        # Position should be closed
        assert strategy.get_position("TestToken123") is None

    @pytest.mark.asyncio
    async def test_time_stop_not_triggered(self, strategy):
        """Test time-based stop not triggered."""
        # Create position with recent entry time
        recent_time = datetime.now() - timedelta(hours=12)  # Within 24 hours
        snapshot = create_snapshot("TestToken123", 1.0)

        # Manually create position with recent time
        position = PositionState(
            token_mint="TestToken123",
            entry_price_usd=1.0,
            quantity=50.0,
            entry_time=recent_time,
        )
        strategy._positions["TestToken123"] = position

        # Check time stop
        result = await strategy.time_stop(snapshot)

        assert result is None
        assert strategy.exec_client.sell_count == 0

        # Position should still exist
        assert strategy.get_position("TestToken123") is not None

    @pytest.mark.asyncio
    async def test_full_position_lifecycle(self, strategy):
        """Test complete position lifecycle with synthetic price path."""
        # Synthetic price path: 1.0 -> 2.5 -> 1.8 -> 0.8
        prices = [1.0, 2.5, 1.8, 0.8]

        # Step 1: Enter position at $1.00
        snapshot = create_snapshot("TestToken123", prices[0])
        result = await strategy.on_signal(snapshot)
        assert result is not None
        assert strategy.exec_client.buy_count == 1

        # Step 2: Price moves to $2.50 (2.5x - should trigger 2x take profit)
        snapshot = create_snapshot("TestToken123", prices[1])
        result = await strategy.take_profits(snapshot)
        assert result is not None
        assert strategy.exec_client.sell_count == 1

        # Check position state
        position = strategy.get_position("TestToken123")
        assert position.quantity == 37.5  # 50 - (50 * 0.25)
        assert position.high_water_mark == 2.5  # Updated during take_profits call
        assert (
            position.trailing_stop_price == 0.85
        )  # Still at entry level since trailing_stop wasn't called

        # Update trailing stop to 2.5 level first (use higher price to trigger update)
        snapshot_higher = create_snapshot("TestToken123", 2.6)
        await strategy.trailing_stop(snapshot_higher)

        # Step 3: Price drops to $1.80 (below trailing stop)
        snapshot = create_snapshot("TestToken123", prices[2])
        result = await strategy.trailing_stop(snapshot)
        assert result is not None
        assert strategy.exec_client.sell_count == 2

        # Position should be closed
        assert strategy.get_position("TestToken123") is None

        # Verify final state
        assert strategy.exec_client.buy_count == 1
        assert strategy.exec_client.sell_count == 2


class TestPriceCalculationHelpers:
    """Test pure helper functions for price calculations."""

    def test_calculate_pnl_percentage(self):
        """Test P&L percentage calculation."""
        # Profit case
        assert calculate_pnl_percentage(100.0, 120.0) == 20.0
        assert calculate_pnl_percentage(100.0, 150.0) == 50.0

        # Loss case
        assert calculate_pnl_percentage(100.0, 80.0) == -20.0
        assert calculate_pnl_percentage(100.0, 50.0) == -50.0

        # Edge cases
        assert calculate_pnl_percentage(100.0, 100.0) == 0.0
        assert calculate_pnl_percentage(0.0, 100.0) == 0.0

    def test_calculate_trailing_stop_price(self):
        """Test trailing stop price calculation."""
        assert calculate_trailing_stop_price(100.0, 0.15) == 85.0
        assert calculate_trailing_stop_price(200.0, 0.10) == 180.0
        assert calculate_trailing_stop_price(50.0, 0.20) == 40.0

    def test_calculate_position_value(self):
        """Test position value calculation."""
        assert calculate_position_value(100.0, 1.5) == 150.0
        assert calculate_position_value(50.0, 2.0) == 100.0
        assert calculate_position_value(0.0, 10.0) == 0.0

    def test_calculate_remaining_hold_time(self):
        """Test remaining hold time calculation."""
        entry_time = datetime.now() - timedelta(hours=6)
        remaining = calculate_remaining_hold_time(entry_time, 24.0)
        assert 17.5 < remaining < 18.5  # Should be around 18 hours

        # Exceeded time
        old_time = datetime.now() - timedelta(hours=30)
        remaining = calculate_remaining_hold_time(old_time, 24.0)
        assert remaining < 0  # Should be negative

    def test_calculate_take_profit_levels(self):
        """Test take profit level calculation."""
        entry_price = 100.0
        levels = [(2.0, 0.25), (3.0, 0.25)]

        result = calculate_take_profit_levels(entry_price, levels)
        expected = [(200.0, 0.25), (300.0, 0.25)]

        assert result == expected


class TestSyntheticPricePaths:
    """Test strategy behavior with various synthetic price paths."""

    @pytest.fixture
    def strategy(self):
        """Create strategy with custom settings."""
        exec_client = MockExecutionClient()
        risk_manager = MockRiskManager()
        storage = MockStorage()

        return TradingStrategy(
            exec_client=exec_client,
            risk_manager=risk_manager,
            storage=storage,
            take_profit_levels=[(1.5, 0.33), (2.0, 0.33)],  # More aggressive
            trailing_stop_pct=0.10,  # Tighter stop
            max_hold_time_hours=12.0,  # Shorter hold time
        )

    @pytest.mark.asyncio
    async def test_bull_run_scenario(self, strategy):
        """Test strategy in a strong bull run scenario."""
        # Price path: 1.0 -> 1.6 -> 2.2 -> 3.0 -> 2.5
        prices = [1.0, 1.6, 2.2, 3.0, 2.5]

        # Enter position
        snapshot = create_snapshot("TestToken123", prices[0])
        await strategy.on_signal(snapshot)

        # Price to 1.6 (1.6x - should trigger 1.5x take profit)
        snapshot = create_snapshot("TestToken123", prices[1])
        result = await strategy.take_profits(snapshot)
        assert result is not None

        # Price to 2.2 (2.2x - should trigger 2.0x take profit)
        snapshot = create_snapshot("TestToken123", prices[2])
        result = await strategy.take_profits(snapshot)
        assert result is not None

        # Price to 3.0 (3.0x - no more take profits configured)
        snapshot = create_snapshot("TestToken123", prices[3])
        result = await strategy.take_profits(snapshot)
        assert result is None

        # Update trailing stop to 3.0 level (use higher price to trigger update)
        snapshot_higher = create_snapshot("TestToken123", 3.1)
        await strategy.trailing_stop(snapshot_higher)

        # Price drops to 2.4 (should trigger trailing stop)
        snapshot = create_snapshot("TestToken123", 2.4)
        result = await strategy.trailing_stop(snapshot)
        assert result is not None

        # Verify all sells executed
        assert strategy.exec_client.sell_count == 3  # 2 partial + 1 full

    @pytest.mark.asyncio
    async def test_volatile_scenario(self, strategy):
        """Test strategy in a volatile scenario."""
        # Price path: 1.0 -> 1.8 -> 1.2 -> 2.1 -> 0.9
        prices = [1.0, 1.8, 1.2, 2.1, 0.9]

        # Enter position
        snapshot = create_snapshot("TestToken123", prices[0])
        await strategy.on_signal(snapshot)

        # Price to 1.8 (1.8x - should trigger 1.5x take profit)
        snapshot = create_snapshot("TestToken123", prices[1])
        result = await strategy.take_profits(snapshot)
        assert result is not None

        # Price drops to 1.2 (should update trailing stop)
        snapshot = create_snapshot("TestToken123", prices[2])
        result = await strategy.trailing_stop(snapshot)
        assert result is None  # No stop triggered

        # Price to 2.1 (should trigger 2.0x take profit)
        snapshot = create_snapshot("TestToken123", prices[3])
        result = await strategy.take_profits(snapshot)
        assert result is not None  # Should trigger 2.0x level

        # Price drops to 0.9 (should trigger trailing stop)
        snapshot = create_snapshot("TestToken123", prices[4])
        result = await strategy.trailing_stop(snapshot)
        assert result is not None

        # Verify sells executed
        assert strategy.exec_client.sell_count == 3  # 2 partial + 1 full

    @pytest.mark.asyncio
    async def test_sideways_scenario(self, strategy):
        """Test strategy in a sideways market scenario."""
        # Price path: 1.0 -> 1.1 -> 0.95 -> 1.05 -> 0.9
        prices = [1.0, 1.1, 0.95, 1.05, 0.9]

        # Enter position
        snapshot = create_snapshot("TestToken123", prices[0])
        await strategy.on_signal(snapshot)

        # No take profits should trigger
        for price in prices[1:4]:
            snapshot = create_snapshot("TestToken123", price)
            result = await strategy.take_profits(snapshot)
            assert result is None

        # Price drops to 0.9 (should trigger trailing stop)
        snapshot = create_snapshot("TestToken123", prices[4])
        result = await strategy.trailing_stop(snapshot)
        assert result is not None

        # Verify only one sell (trailing stop)
        assert strategy.exec_client.sell_count == 1

    @pytest.mark.asyncio
    async def test_time_expiry_scenario(self, strategy):
        """Test strategy with time-based expiry."""
        # Create position with old entry time
        old_time = datetime.now() - timedelta(hours=13)  # Exceeds 12 hours
        snapshot = create_snapshot("TestToken123", 1.0)

        position = PositionState(
            token_mint="TestToken123",
            entry_price_usd=1.0,
            quantity=50.0,
            entry_time=old_time,
        )
        strategy._positions["TestToken123"] = position

        # Time stop should trigger
        result = await strategy.time_stop(snapshot)
        assert result is not None
        assert strategy.exec_client.sell_count == 1

        # Position should be closed
        assert strategy.get_position("TestToken123") is None
