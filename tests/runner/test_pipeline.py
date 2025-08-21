"""Tests for the trading pipeline."""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from bot.config.settings import AppSettings
from bot.core.interfaces import (
    AlertSink,
    ExecutionClient,
    Filter,
    MarketDataSource,
    Persistence,
    RiskManager,
)
from bot.core.types import FilterDecision, TokenId, TokenSnapshot
from bot.runner.pipeline import NoopAlertSink, TradingPipeline


class MockDataSource(MarketDataSource):
    """Mock data source that emits deterministic snapshots."""

    def __init__(self, snapshots: list[TokenSnapshot]):
        self.snapshots = snapshots
        self.poll_count = 0

    async def poll(self) -> list[TokenSnapshot]:
        """Return snapshots and increment poll count."""
        self.poll_count += 1
        return self.snapshots.copy()

    async def lookup(self, token: TokenId) -> TokenSnapshot | None:
        """Look up a specific token."""
        for snapshot in self.snapshots:
            if snapshot.token.mint == token.mint:
                return snapshot
        return None


class MockFilter(Filter):
    """Mock filter that can be configured to accept or reject tokens."""

    def __init__(self, accept_all: bool = True, reject_tokens: set[str] = None):
        self.accept_all = accept_all
        self.reject_tokens = reject_tokens or set()
        self.evaluate_count = 0

    def evaluate(self, snap: TokenSnapshot) -> FilterDecision:
        """Evaluate token snapshot."""
        self.evaluate_count += 1

        if snap.token.mint in self.reject_tokens:
            return FilterDecision(accepted=False, score=0.0, reasons=["Mock rejection"])

        if self.accept_all:
            return FilterDecision(accepted=True, score=0.8, reasons=["Mock acceptance"])
        else:
            return FilterDecision(accepted=False, score=0.2, reasons=["Mock rejection"])


class MockRiskManager(RiskManager):
    """Mock risk manager for testing."""

    def __init__(self, allow_all: bool = True, position_size: float = 50.0):
        self.allow_all = allow_all
        self.position_size = position_size
        self.size_count = 0
        self.allow_count = 0
        self.after_fill_count = 0

    def size_usd(self, snap: TokenSnapshot) -> float:
        """Return configured position size."""
        self.size_count += 1
        return self.position_size

    def allow_buy(self, snap: TokenSnapshot) -> tuple[bool, list[str]]:
        """Allow or reject based on configuration."""
        self.allow_count += 1
        if self.allow_all:
            return True, ["Mock approval"]
        else:
            return False, ["Mock rejection"]

    def after_fill(self, pnl_usd: float) -> None:
        """Track after_fill calls."""
        self.after_fill_count += 1


class MockExecutionClient(ExecutionClient):
    """Mock execution client for testing."""

    def __init__(self):
        self.simulate_count = 0
        self.buy_count = 0
        self.sell_count = 0

    async def simulate(self, snap: TokenSnapshot, usd_amount: float) -> dict:
        """Mock simulation."""
        self.simulate_count += 1
        return {
            "qty_base": usd_amount / snap.price_usd,
            "price_impact_pct": 0.1,
            "ts": datetime.now(),
        }

    async def buy(self, snap: TokenSnapshot, usd_amount: float) -> dict:
        """Mock buy execution."""
        self.buy_count += 1
        qty_base = usd_amount / snap.price_usd
        return {
            "qty_base": qty_base,
            "price_exec": snap.price_usd,
            "cost_usd": usd_amount,
            "fee_usd": usd_amount * 0.001,  # 0.1% fee
            "ts": datetime.now(),
        }

    async def sell(self, token: TokenId, pct: float) -> dict:
        """Mock sell execution."""
        self.sell_count += 1
        return {
            "qty_base": 100.0 * (pct / 100.0),
            "price_exec": 1.5,
            "cost_usd": 150.0 * (pct / 100.0),
            "fee_usd": 0.15 * (pct / 100.0),
            "ts": datetime.now(),
        }


class MockAlertSink(AlertSink):
    """Mock alert sink for testing."""

    def __init__(self):
        self.messages = []
        self.push_count = 0

    async def push(self, message: str) -> None:
        """Store messages for testing."""
        self.push_count += 1
        self.messages.append(message)


class MockStorage(Persistence):
    """Mock storage for testing."""

    def __init__(self):
        self.record_trade_count = 0
        self.upsert_position_count = 0
        self.trade_id_counter = 1

    async def record_trade(
        self,
        token_mint: str,
        side: str,
        qty: float,
        px: float,
        fee_usd: float = 0.0,
        ts: float = None,
    ) -> int:
        """Mock trade recording."""
        self.record_trade_count += 1
        trade_id = self.trade_id_counter
        self.trade_id_counter += 1
        return trade_id

    async def upsert_position(
        self, token_mint: str, qty: float, avg_cost_usd: float, updated_ts: float = None
    ) -> None:
        """Mock position upsert."""
        self.upsert_position_count += 1

    async def close(self) -> None:
        """Mock close."""
        pass


class TestNoopAlertSink:
    """Test NoopAlertSink."""

    @pytest.mark.asyncio
    async def test_noop_push(self):
        """Test that noop sink just logs messages."""
        sink = NoopAlertSink()
        await sink.push("Test message")
        # Should not raise any exceptions


class TestTradingPipeline:
    """Test trading pipeline functionality."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock(spec=AppSettings)
        settings.dry_run = True
        settings.rpc_url = "https://api.mainnet-beta.solana.com"
        settings.helius_api_key = None
        settings.birdeye_api_key = None
        settings.dexscreener_base = "https://api.dexscreener.com/latest/dex"
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
                source="mock",
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
                source="mock",
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
        pipeline.components["risk"] = MockRiskManager(
            allow_all=True, position_size=50.0
        )
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

        # Check data sources (should have DexScreener even without API keys)
        assert len(components["data_sources"]) == 1
        assert "DexScreenerLookup" in str(type(components["data_sources"][0]))

        # Check filters
        assert len(components["filters"]) == 2

        # Check risk manager
        assert isinstance(components["risk"], RiskManager)

        # Check execution client (should be paper in dry run)
        assert "PaperExecutor" in str(type(components["exec_client"]))

        # Check alert sink (should be noop without Telegram config)
        assert isinstance(components["alerts"], NoopAlertSink)

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
    async def test_run_once_with_rejecting_filter(
        self, mock_settings, sample_snapshots
    ):
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
    async def test_run_once_with_rejecting_risk_manager(
        self, mock_settings, sample_snapshots
    ):
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

    @pytest.mark.asyncio
    async def test_run_once_with_zero_position_size(
        self, mock_settings, sample_snapshots
    ):
        """Test run_once with zero position size."""
        pipeline = TradingPipeline(mock_settings)

        # Replace components with zero position size
        pipeline.components["data_sources"] = [MockDataSource(sample_snapshots)]
        pipeline.components["filters"] = [MockFilter(accept_all=True)]
        pipeline.components["risk"] = MockRiskManager(allow_all=True, position_size=0.0)
        pipeline.components["exec_client"] = MockExecutionClient()
        pipeline.components["alerts"] = MockAlertSink()
        pipeline.components["storage"] = MockStorage()

        # Run one cycle
        await pipeline.run_once()

        # Verify no trades were executed
        exec_client = pipeline.components["exec_client"]
        assert exec_client.buy_count == 0

    @pytest.mark.asyncio
    async def test_run_once_with_empty_data_sources(self, mock_settings):
        """Test run_once with no data from sources."""
        pipeline = TradingPipeline(mock_settings)

        # Replace components with empty data source
        pipeline.components["data_sources"] = [MockDataSource([])]
        pipeline.components["filters"] = [MockFilter(accept_all=True)]
        pipeline.components["risk"] = MockRiskManager(allow_all=True)
        pipeline.components["exec_client"] = MockExecutionClient()
        pipeline.components["alerts"] = MockAlertSink()
        pipeline.components["storage"] = MockStorage()

        # Run one cycle
        await pipeline.run_once()

        # Verify no processing occurred
        filter_obj = pipeline.components["filters"][0]
        assert filter_obj.evaluate_count == 0

        exec_client = pipeline.components["exec_client"]
        assert exec_client.buy_count == 0

    @pytest.mark.asyncio
    async def test_run_once_with_data_source_error(
        self, mock_settings, sample_snapshots
    ):
        """Test run_once with data source errors."""
        pipeline = TradingPipeline(mock_settings)

        # Create data source that raises an error
        error_data_source = MockDataSource(sample_snapshots)

        async def error_poll():
            raise Exception("Data source error")

        error_data_source.poll = error_poll

        # Replace components
        pipeline.components["data_sources"] = [error_data_source]
        pipeline.components["filters"] = [MockFilter(accept_all=True)]
        pipeline.components["risk"] = MockRiskManager(allow_all=True)
        pipeline.components["exec_client"] = MockExecutionClient()
        pipeline.components["alerts"] = MockAlertSink()
        pipeline.components["storage"] = MockStorage()

        # Run one cycle
        await pipeline.run_once()

        # Verify no processing occurred due to error
        filter_obj = pipeline.components["filters"][0]
        assert filter_obj.evaluate_count == 0

    @pytest.mark.asyncio
    async def test_run_forever_metrics(self, pipeline_with_mocks):
        """Test run_forever logs metrics."""
        pipeline = pipeline_with_mocks

        # Run for a short time
        task = asyncio.create_task(pipeline.run_forever())

        # Let it run for a few cycles
        await asyncio.sleep(0.1)

        # Stop the pipeline
        pipeline.running = False
        await asyncio.sleep(0.1)

        # Cancel the task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify some processing occurred
        data_source = pipeline.components["data_sources"][0]
        assert data_source.poll_count > 0

    @pytest.mark.asyncio
    async def test_pipeline_stop(self, pipeline_with_mocks):
        """Test pipeline stop functionality."""
        pipeline = pipeline_with_mocks

        # Start pipeline
        pipeline.running = True

        # Stop pipeline
        await pipeline.stop()

        # Verify stopped
        assert not pipeline.running

        # Verify shutdown alert was sent
        alerts = pipeline.components["alerts"]
        assert any("Trading bot stopped" in msg for msg in alerts.messages)

    @pytest.mark.asyncio
    async def test_process_token_error_handling(self, pipeline_with_mocks):
        """Test error handling in _process_token."""
        pipeline = pipeline_with_mocks

        # Create a snapshot that will cause an error in execution
        error_snapshot = TokenSnapshot(
            token=TokenId(mint="ErrorToken"),
            pool=None,
            price_usd=0.0,  # This will cause division by zero
            liq_usd=1000.0,
            vol_5m_usd=100.0,
            holders=100,
            age_seconds=1800,
            pct_change_5m=0.0,
            source="mock",
            ts=datetime.now(),
        )

        # Process the token
        await pipeline._process_token(error_snapshot)

        # Verify error was handled gracefully (no exception raised)
        # The error should be logged but not crash the pipeline


class TestPipelineIntegration:
    """Integration tests for the pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_cycle(self):
        """Test a complete pipeline cycle with accepting token."""
        # Create settings
        settings = MagicMock(spec=AppSettings)
        settings.dry_run = True
        settings.rpc_url = "https://api.mainnet-beta.solana.com"
        settings.helius_api_key = None
        settings.birdeye_api_key = None
        settings.dexscreener_base = "https://api.dexscreener.com/latest/dex"
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
        settings.cycle_sleep_seconds = 0.1  # Fast for testing

        # Create pipeline
        pipeline = TradingPipeline(settings)

        # Create sample snapshot
        snapshot = TokenSnapshot(
            token=TokenId(mint="TestToken123"),
            pool=None,
            price_usd=1.0,
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            holders=1000,
            age_seconds=3600,
            pct_change_5m=5.0,
            source="mock",
            ts=datetime.now(),
        )

        # Replace components with mocks
        pipeline.components["data_sources"] = [MockDataSource([snapshot])]
        pipeline.components["filters"] = [MockFilter(accept_all=True)]
        pipeline.components["risk"] = MockRiskManager(
            allow_all=True, position_size=50.0
        )
        pipeline.components["exec_client"] = MockExecutionClient()
        pipeline.components["alerts"] = MockAlertSink()
        pipeline.components["storage"] = MockStorage()

        # Run one cycle
        await pipeline.run_once()

        # Verify complete flow
        exec_client = pipeline.components["exec_client"]
        storage = pipeline.components["storage"]
        alerts = pipeline.components["alerts"]

        # Should have executed a trade
        assert exec_client.buy_count == 1
        assert storage.record_trade_count == 1
        assert storage.upsert_position_count == 1
        assert alerts.push_count == 1

        # Should have sent trade alert
        assert any("Trade Executed" in msg for msg in alerts.messages)

        # Check for token in alert message (first 8 chars)
        assert any(
            "TestToke" in msg for msg in alerts.messages
        )  # First 8 chars of token mint


class TestLiveTradingSafety:
    """Tests for live trading safety validation."""

    def test_live_trading_localhost_rpc_raises_error(self):
        """Test that live trading with localhost RPC raises error."""
        settings = MagicMock(spec=AppSettings)
        settings.dry_run = False
        settings.rpc_url = "http://localhost:8899"
        settings.allow_devnet = False
        settings.position_size_usd = 50.0
        settings.daily_max_loss_usd = 200.0
        settings.max_slippage_bps = 100

        with pytest.raises(
            ValueError, match="Live trading on localhost/devnet is not allowed"
        ):
            TradingPipeline(settings)

    def test_live_trading_localhost_rpc_allowed_with_flag(self):
        """Test that localhost RPC is allowed with allow_devnet flag."""
        settings = MagicMock(spec=AppSettings)
        settings.dry_run = False
        settings.rpc_url = "http://localhost:8899"
        settings.allow_devnet = True
        settings.position_size_usd = 50.0
        settings.daily_max_loss_usd = 200.0
        settings.max_slippage_bps = 100
        settings.cooldown_seconds = 60
        settings.helius_api_key = None
        settings.birdeye_api_key = None
        settings.dexscreener_base = "https://api.dexscreener.com/latest/dex"
        settings.jupiter_base = "https://quote-api.jup.ag/v6"
        settings.priority_fee_microlamports = 0
        settings.compute_unit_limit = 120000
        settings.jito_tip_lamports = 0
        settings.telegram_bot_token = None
        settings.telegram_admin_ids = []
        settings.database_url = "sqlite+aiosqlite:///./test.sqlite"
        settings.parquet_dir = "./test_parquet"
        settings.preflight_simulate = True
        settings.max_retries_send = 3

        # Should raise error due to missing signer config, but not due to localhost
        with pytest.raises(ValueError, match="No valid signer configuration found"):
            TradingPipeline(settings)

    def test_live_trading_position_size_exceeds_daily_loss_raises_error(self):
        """Test that position size exceeding daily loss raises error."""
        settings = MagicMock(spec=AppSettings)
        settings.dry_run = False
        settings.rpc_url = "https://api.mainnet-beta.solana.com"
        settings.allow_devnet = False
        settings.position_size_usd = 300.0  # Exceeds daily max loss
        settings.daily_max_loss_usd = 200.0
        settings.max_slippage_bps = 100

        with pytest.raises(
            ValueError, match="Position size.*cannot exceed.*daily max loss"
        ):
            TradingPipeline(settings)

    def test_live_trading_high_slippage_raises_error(self):
        """Test that high slippage raises error without override."""
        settings = MagicMock(spec=AppSettings)
        settings.dry_run = False
        settings.rpc_url = "https://api.mainnet-beta.solana.com"
        settings.allow_devnet = False
        settings.position_size_usd = 50.0
        settings.daily_max_loss_usd = 200.0
        settings.max_slippage_bps = 1500  # 15% - exceeds 10% limit
        settings.unsafe_allow_high_slippage = False

        with pytest.raises(ValueError, match="Slippage.*exceeds 10% limit"):
            TradingPipeline(settings)

    def test_live_trading_high_slippage_allowed_with_flag(self):
        """Test that high slippage is allowed with override flag."""
        settings = MagicMock(spec=AppSettings)
        settings.dry_run = False
        settings.rpc_url = "https://api.mainnet-beta.solana.com"
        settings.allow_devnet = False
        settings.position_size_usd = 50.0
        settings.daily_max_loss_usd = 200.0
        settings.max_slippage_bps = 1500  # 15% - exceeds 10% limit
        settings.unsafe_allow_high_slippage = True
        settings.cooldown_seconds = 60
        settings.helius_api_key = None
        settings.birdeye_api_key = None
        settings.dexscreener_base = "https://api.dexscreener.com/latest/dex"
        settings.jupiter_base = "https://quote-api.jup.ag/v6"
        settings.priority_fee_microlamports = 0
        settings.compute_unit_limit = 120000
        settings.jito_tip_lamports = 0
        settings.telegram_bot_token = None
        settings.telegram_admin_ids = []
        settings.database_url = "sqlite+aiosqlite:///./test.sqlite"
        settings.parquet_dir = "./test_parquet"
        settings.preflight_simulate = True
        settings.max_retries_send = 3

        # Should raise error due to missing signer config, but not due to high slippage
        with pytest.raises(ValueError, match="No valid signer configuration found"):
            TradingPipeline(settings)

    def test_dry_run_bypasses_safety_checks(self):
        """Test that dry run mode bypasses safety checks."""
        settings = MagicMock(spec=AppSettings)
        settings.dry_run = True
        settings.rpc_url = "http://localhost:8899"  # Would fail in live mode
        settings.allow_devnet = False
        settings.position_size_usd = 300.0  # Would fail in live mode
        settings.daily_max_loss_usd = 200.0
        settings.max_slippage_bps = 1500  # Would fail in live mode
        settings.unsafe_allow_high_slippage = False
        settings.cooldown_seconds = 60
        settings.helius_api_key = None
        settings.birdeye_api_key = None
        settings.dexscreener_base = "https://api.dexscreener.com/latest/dex"
        settings.jupiter_base = "https://quote-api.jup.ag/v6"
        settings.priority_fee_microlamports = 0
        settings.compute_unit_limit = 120000
        settings.jito_tip_lamports = 0
        settings.telegram_bot_token = None
        settings.telegram_admin_ids = []
        settings.database_url = "sqlite+aiosqlite:///./test.sqlite"
        settings.parquet_dir = "./test_parquet"

        # Should not raise any safety validation errors in dry run mode
        pipeline = TradingPipeline(settings)
        assert pipeline.settings.dry_run is True
