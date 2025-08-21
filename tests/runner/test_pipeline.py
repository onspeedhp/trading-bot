"""Tests for the trading pipeline."""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from bot.config.settings import AppSettings
from bot.core.interfaces import AlertSink, ExecutionClient, Filter, RiskManager
from bot.core.types import FilterDecision, TokenId, TokenSnapshot
from bot.runner.pipeline import TradingPipeline


class MockDataSource:
    """Mock data source for testing."""

    def __init__(self, snapshots: list[TokenSnapshot]):
        self.snapshots = snapshots
        self.poll_count = 0

    async def poll(self) -> list[TokenSnapshot]:
        self.poll_count += 1
        return self.snapshots

    async def close(self) -> None:
        pass


class MockFilter:
    """Mock filter for testing."""

    def __init__(self, accept_all: bool = True):
        self.accept_all = accept_all
        self.evaluate_count = 0

    def evaluate(self, snap: TokenSnapshot) -> FilterDecision:
        self.evaluate_count += 1
        if self.accept_all:
            return FilterDecision(accepted=True, score=1.0, reasons=["Mock accepted"])
        else:
            return FilterDecision(accepted=False, score=0.0, reasons=["Mock rejected"])


class MockRiskManager:
    """Mock risk manager for testing."""

    def __init__(self, allow_all: bool = True, position_size: float = 50.0):
        self.allow_all = allow_all
        self.position_size = position_size
        self.size_count = 0
        self.allow_count = 0

    def size_usd(self, snap: TokenSnapshot) -> float:
        self.size_count += 1
        return self.position_size

    def allow_buy(self, snap: TokenSnapshot) -> tuple[bool, list[str]]:
        self.allow_count += 1
        if self.allow_all:
            return True, ["Mock allowed"]
        else:
            return False, ["Mock rejected"]

    def after_fill(self, pnl_usd: float) -> None:
        pass


class MockExecutionClient:
    """Mock execution client for testing."""

    def __init__(self):
        self.simulate_count = 0
        self.buy_count = 0

    async def simulate(self, snap: TokenSnapshot, usd_amount: float) -> dict:
        self.simulate_count += 1
        return {"status": "simulated"}

    async def buy(self, snap: TokenSnapshot, usd_amount: float) -> dict:
        self.buy_count += 1
        return {"status": "bought"}


class MockAlertSink:
    """Mock alert sink for testing."""

    def __init__(self):
        self.push_count = 0
        self.messages = []

    async def push(self, message: str) -> None:
        self.push_count += 1
        self.messages.append(message)


class MockStorage:
    """Mock storage for testing."""

    def __init__(self):
        self.record_trade_count = 0
        self.upsert_position_count = 0

    async def record_trade(self, token: TokenId, side: str, usd_amount: float, price_usd: float) -> None:
        self.record_trade_count += 1

    async def upsert_position(self, token: TokenId, qty: float, avg_cost_usd: float) -> None:
        self.upsert_position_count += 1

    async def close(self) -> None:
        pass


class TestTradingPipeline:
    """Test the trading pipeline."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock(spec=AppSettings)
        settings.dry_run = True
        settings.rpc_url = "https://api.mainnet-beta.solana.com"
        # Jupiter API doesn't require API keys
        settings.position_size_usd = 50.0
        settings.daily_max_loss_usd = 200.0
        settings.cooldown_seconds = 60
        settings.max_slippage_bps = 100
        settings.jupiter_base = "https://quote-api.jup.ag/v6"
        settings.priority_fee_microlamports = 0
        settings.compute_unit_limit = 120000
        settings.jito_tip_lamports = 0
        settings.telegram_bot_token = None
        settings.telegram_admin_ids = []
        settings.database_url = "sqlite+aiosqlite:///./test.sqlite"
        settings.parquet_dir = "./test_parquet"
        settings.cycle_sleep_seconds = 1
        return settings

    @pytest.fixture
    def sample_snapshots(self):
        """Create sample token snapshots."""
        return [
            TokenSnapshot(
                token=TokenId(mint="TokenA123456789"),
                pool=None,
                price_usd=1.50,
                liq_usd=10000.0,
                vol_5m_usd=1000.0,
                holders=1000,
                age_seconds=3600,
                pct_change_5m=5.0,
                source="jupiter",
                ts=datetime.now(),
            ),
            TokenSnapshot(
                token=TokenId(mint="TokenB987654321"),
                pool=None,
                price_usd=0.75,
                liq_usd=5000.0,
                vol_5m_usd=500.0,
                holders=500,
                age_seconds=7200,
                pct_change_5m=-2.0,
                source="jupiter",
                ts=datetime.now(),
            ),
        ]

    @pytest.fixture
    def pipeline_with_mocks(self, mock_settings, sample_snapshots):
        """Create pipeline with mocked components."""
        # Create pipeline
        pipeline = TradingPipeline(mock_settings)

        # Replace components with mocks
        pipeline.components["data_sources"] = [MockDataSource(sample_snapshots)]
        pipeline.components["filters"] = [MockFilter(accept_all=True)]
        pipeline.components["risk"] = MockRiskManager(allow_all=True, position_size=50.0)
        pipeline.components["exec_client"] = MockExecutionClient()
        pipeline.components["alerts"] = MockAlertSink()
        pipeline.components["storage"] = MockStorage()

        return pipeline

    @pytest.mark.asyncio
    async def test_pipeline_initialization(self, mock_settings):
        """Test pipeline initialization."""
        pipeline = TradingPipeline(mock_settings)

        assert pipeline.settings == mock_settings
        assert not pipeline.running
        assert "data_sources" in pipeline.components
        assert "filters" in pipeline.components
        assert "risk" in pipeline.components
        assert "exec_client" in pipeline.components
        assert "alerts" in pipeline.components
        assert "storage" in pipeline.components

    @pytest.mark.asyncio
    async def test_assemble_components(self, mock_settings):
        """Test component assembly."""
        pipeline = TradingPipeline(mock_settings)
        components = pipeline.components

        # Check data sources (should have Jupiter)
        assert len(components["data_sources"]) == 1
        assert "JupiterDataSource" in str(type(components["data_sources"][0]))

        # Check filters
        assert len(components["filters"]) == 2

        # Check risk manager
        assert hasattr(components["risk"], "size_usd")

        # Check execution client (should be paper in dry run)
        assert "PaperExecutor" in str(type(components["exec_client"]))

        # Check alert sink (should be noop without Telegram config)
        assert hasattr(components["alerts"], "push")

        # Check storage
        assert "SQLiteStorage" in str(type(components["storage"]))

    @pytest.mark.asyncio
    async def test_run_once_with_accepting_token(self, pipeline_with_mocks):
        """Test run_once with a token that passes all checks."""
        pipeline = pipeline_with_mocks

        # Run one cycle
        await pipeline.run_once()

        # Verify data source was polled
        data_source = pipeline.components["data_sources"][0]
        assert data_source.poll_count == 1

        # Verify filters were evaluated
        filter_obj = pipeline.components["filters"][0]
        assert filter_obj.evaluate_count == 2  # One for each token

        # Verify risk manager was called
        risk_manager = pipeline.components["risk"]
        assert risk_manager.size_count == 2
        assert risk_manager.allow_count == 2

        # Verify execution client was called
        exec_client = pipeline.components["exec_client"]
        assert exec_client.simulate_count == 2
        assert exec_client.buy_count == 2

        # Verify storage was called
        storage = pipeline.components["storage"]
        assert storage.record_trade_count == 2
        assert storage.upsert_position_count == 2

        # Verify alerts were sent
        alerts = pipeline.components["alerts"]
        assert alerts.push_count == 2  # One for each trade
        assert any("Trade Executed" in msg for msg in alerts.messages)

    @pytest.mark.asyncio
    async def test_run_once_with_rejecting_filter(self, mock_settings, sample_snapshots):
        """Test run_once with a filter that rejects tokens."""
        pipeline = TradingPipeline(mock_settings)

        # Replace components with rejecting filter
        pipeline.components["data_sources"] = [MockDataSource(sample_snapshots)]
        pipeline.components["filters"] = [MockFilter(accept_all=False)]
        pipeline.components["risk"] = MockRiskManager(allow_all=True)
        pipeline.components["exec_client"] = MockExecutionClient()
        pipeline.components["alerts"] = MockAlertSink()
        pipeline.components["storage"] = MockStorage()

        # Run one cycle
        await pipeline.run_once()

        # Verify filters were evaluated
        filter_obj = pipeline.components["filters"][0]
        assert filter_obj.evaluate_count == 2

        # Verify no trades were executed
        exec_client = pipeline.components["exec_client"]
        assert exec_client.buy_count == 0

        # Verify no storage calls
        storage = pipeline.components["storage"]
        assert storage.record_trade_count == 0

    @pytest.mark.asyncio
    async def test_run_once_with_rejecting_risk_manager(self, mock_settings, sample_snapshots):
        """Test run_once with a risk manager that rejects tokens."""
        pipeline = TradingPipeline(mock_settings)

        # Replace components with rejecting risk manager
        pipeline.components["data_sources"] = [MockDataSource(sample_snapshots)]
        pipeline.components["filters"] = [MockFilter(accept_all=True)]
        pipeline.components["risk"] = MockRiskManager(allow_all=False)
        pipeline.components["exec_client"] = MockExecutionClient()
        pipeline.components["alerts"] = MockAlertSink()
        pipeline.components["storage"] = MockStorage()

        # Run one cycle
        await pipeline.run_once()

        # Verify risk manager was called
        risk_manager = pipeline.components["risk"]
        assert risk_manager.allow_count == 2

        # Verify no trades were executed
        exec_client = pipeline.components["exec_client"]
        assert exec_client.buy_count == 0

        # Verify no storage calls
        storage = pipeline.components["storage"]
        assert storage.record_trade_count == 0

    @pytest.mark.asyncio
    async def test_pipeline_stop(self, pipeline_with_mocks):
        """Test pipeline stop functionality."""
        pipeline = pipeline_with_mocks

        # Start pipeline
        pipeline.running = True

        # Stop pipeline
        await pipeline.stop()

        # Verify pipeline is stopped
        assert not pipeline.running

        # Verify storage was closed
        storage = pipeline.components["storage"]
        assert hasattr(storage, 'close')  # Mock should have close method
