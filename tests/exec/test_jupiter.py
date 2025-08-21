"""Tests for Jupiter execution engine."""

import base64
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import respx

from bot.core.types import TokenId, TokenSnapshot
from bot.exec.jupiter import (
    JupiterExecutor,
    build_quote_params,
    token_amount_to_usd,
    usd_to_token_amount,
)


class MockSigner:
    """Mock signer for testing."""

    def __init__(self, pubkey: str = "TestPubkey123"):
        self.pubkey = pubkey

    def pubkey_base58(self) -> str:
        """Get the public key in base58 format."""
        return self.pubkey

    def sign_transaction(self, txn_bytes: bytes) -> bytes:
        """Sign a transaction (mock implementation)."""
        # For testing, just prepend a fake signature
        fake_signature = b"fake_signature_12345"
        return fake_signature + txn_bytes


class MockSender:
    """Mock sender for testing."""

    def __init__(self):
        self.simulate_called = False
        self.send_called = False
        self.simulate_result = {"value": {"unitsConsumed": 5000}}
        self.send_result = "test_signature_67890"

    async def simulate(self, tx_base64: str) -> dict:
        """Simulate a transaction."""
        self.simulate_called = True
        return self.simulate_result

    async def send(self, tx_base64: str, skip_preflight: bool, max_retries: int) -> str:
        """Send a transaction."""
        self.send_called = True
        return self.send_result


class TestJupiterHelperFunctions:
    """Test helper functions."""

    def test_build_quote_params(self):
        """Test quote parameter building."""
        params = build_quote_params(
            input_mint="input_mint_123",
            output_mint="output_mint_456",
            amount=1000000,
            slippage_bps=100,
        )

        assert params["inputMint"] == "input_mint_123"
        assert params["outputMint"] == "output_mint_456"
        assert params["amount"] == "1000000"
        assert params["slippageBps"] == 100
        assert params["asLegacyTransaction"] is False

    def test_build_quote_params_with_options(self):
        """Test quote parameter building with optional parameters."""
        params = build_quote_params(
            input_mint="input_mint_123",
            output_mint="output_mint_456",
            amount=1000000,
            slippage_bps=100,
            only_direct_routes=True,
            as_legacy_transaction=True,
        )

        assert params["onlyDirectRoutes"] is True
        assert params["asLegacyTransaction"] is True

    def test_usd_to_token_amount(self):
        """Test USD to token amount conversion."""
        # Test with 9 decimals (most SPL tokens)
        result = usd_to_token_amount(100.0, 0.5, 9)
        assert result == 200_000_000_000  # 200 tokens * 10^9

        # Test with 6 decimals (USDC)
        result = usd_to_token_amount(50.0, 1.0, 6)
        assert result == 50_000_000  # 50 USDC * 10^6

    def test_usd_to_token_amount_invalid_price(self):
        """Test USD to token amount conversion with invalid price."""
        with pytest.raises(ValueError, match="Invalid token price"):
            usd_to_token_amount(100.0, 0.0, 9)

        with pytest.raises(ValueError, match="Invalid token price"):
            usd_to_token_amount(100.0, -1.0, 9)

    def test_token_amount_to_usd(self):
        """Test token amount to USD conversion."""
        # Test with 9 decimals
        result = token_amount_to_usd(200_000_000_000, 0.5, 9)
        assert result == 100.0

        # Test with 6 decimals
        result = token_amount_to_usd(50_000_000, 1.0, 6)
        assert result == 50.0

    def test_token_amount_to_usd_invalid_price(self):
        """Test token amount to USD conversion with invalid price."""
        with pytest.raises(ValueError, match="Invalid token price"):
            token_amount_to_usd(100_000_000, 0.0, 9)

        with pytest.raises(ValueError, match="Invalid token price"):
            token_amount_to_usd(100_000_000, -1.0, 9)


class TestJupiterExecutor:
    """Test Jupiter executor functionality."""

    @pytest.fixture
    def mock_session(self):
        """Create mock HTTP session."""
        return AsyncMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def mock_signer(self):
        """Create mock signer."""
        return MockSigner()

    @pytest.fixture
    def mock_sender(self):
        """Create mock sender."""
        return MockSender()

    @pytest.fixture
    def executor(self, mock_session, mock_signer, mock_sender):
        """Create Jupiter executor instance."""
        return JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=0,
            signer=mock_signer,
            sender=mock_sender,
            session=mock_session,
        )

    @pytest.fixture
    def executor_no_live(self, mock_session):
        """Create Jupiter executor without live trading."""
        return JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=0,
            session=mock_session,
        )

    @pytest.fixture
    def token_snapshot(self):
        """Create a test token snapshot."""
        return TokenSnapshot(
            token=TokenId(chain="sol", mint="TestToken123"),
            pool=None,
            price_usd=0.5,
            liq_usd=1000000.0,
            vol_5m_usd=50000.0,
            holders=1000,
            age_seconds=3600,
            pct_change_5m=5.0,
            source="test",
            ts=datetime.now(UTC),
        )

    def test_initialization(self, executor):
        """Test Jupiter executor initialization."""
        assert executor.base_url == "https://quote-api.jup.ag/v6"
        assert executor.rpc_url == "https://api.mainnet-beta.solana.com"
        assert executor.max_slippage_bps == 100
        assert executor.priority_fee_microlamports == 1000
        assert executor.compute_unit_limit == 120000
        assert executor.jito_tip_lamports == 0
        assert executor.signer is not None
        assert executor.sender is not None
        assert executor.enable_preflight is True

    def test_initialization_no_live_trading(self, executor_no_live):
        """Test Jupiter executor initialization without live trading."""
        assert executor_no_live.signer is None
        assert executor_no_live.sender is None
        assert executor_no_live._is_live_trading_enabled() is False

    def test_is_live_trading_enabled(self, executor, executor_no_live):
        """Test live trading enabled check."""
        assert executor._is_live_trading_enabled() is True
        assert executor_no_live._is_live_trading_enabled() is False

    @pytest.mark.asyncio
    async def test_make_request_get(self, executor):
        """Test HTTP GET request."""
        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {"test": "data"}
        mock_response.raise_for_status.return_value = None
        executor.session.get.return_value = mock_response

        result = await executor._make_request("quote", {"param": "value"})

        assert result == {"test": "data"}
        executor.session.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_make_request_post(self, executor):
        """Test HTTP POST request."""
        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {"test": "data"}
        mock_response.raise_for_status.return_value = None
        executor.session.post.return_value = mock_response

        result = await executor._make_request("swap", {"data": "value"}, method="POST")

        assert result == {"test": "data"}
        executor.session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_make_request_http_error(self, executor):
        """Test HTTP request with error."""
        # Mock HTTP error
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        http_error = httpx.HTTPStatusError(
            "400 Bad Request", request=Mock(), response=mock_response
        )
        executor.session.get.side_effect = http_error

        with pytest.raises(httpx.HTTPStatusError):
            await executor._make_request("quote", {"param": "value"})

    @pytest.mark.asyncio
    async def test_get_quote(self, executor):
        """Test quote retrieval."""
        # Mock quote response
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "1000000",
                    "outAmount": "2000000",
                    "priceImpactPct": 0.1,
                    "marketInfos": [],
                    "routePlan": [],
                }
            ],
            "quoteId": "quote_456",
        }

        # Mock the _make_request method directly
        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor, "_make_request", AsyncMock(return_value=quote_response))

            result = await executor._get_quote(
                input_mint="input_mint",
                output_mint="output_mint",
                amount=1000000,
                slippage_bps=100,
            )

            assert result == quote_response

    @pytest.mark.asyncio
    async def test_build_swap_transaction(self, executor):
        """Test swap transaction building."""
        # Mock quote response
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "1000000",
                    "outAmount": "2000000",
                    "priceImpactPct": 0.1,
                }
            ]
        }

        # Mock swap response
        swap_response = {
            "swapTransaction": base64.b64encode(b"test_transaction_bytes").decode(
                "utf-8"
            )
        }

        # Mock the _make_request method directly
        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor, "_make_request", AsyncMock(return_value=swap_response))

            result = await executor._build_swap_transaction(
                quote_response, "user_pubkey"
            )

            assert result == swap_response

    @pytest.mark.asyncio
    async def test_build_swap_transaction_no_routes(self, executor):
        """Test swap transaction building with no routes."""
        quote_response = {"routes": []}

        with pytest.raises(ValueError, match="No routes available in quote response"):
            await executor._build_swap_transaction(quote_response, "user_pubkey")

    @pytest.mark.asyncio
    async def test_build_swap_transaction_json_body_defaults(self, executor):
        """Test swap transaction JSON body structure with default settings."""
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "1000000",
                    "outAmount": "2000000",
                    "priceImpactPct": 0.1,
                    "routePlan": [],
                }
            ]
        }

        # Capture the actual request body
        captured_request = None

        async def mock_make_request(endpoint, data, method="GET"):
            nonlocal captured_request
            captured_request = data
            return {"swapTransaction": "dGVzdA=="}

        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor, "_make_request", mock_make_request)

            await executor._build_swap_transaction(quote_response, "user_pubkey")

            # Verify the JSON body structure
            assert captured_request is not None
            assert captured_request["route"] == quote_response["routes"][0]
            assert captured_request["userPublicKey"] == "user_pubkey"
            assert captured_request["wrapUnwrapSOL"] is True
            assert captured_request["asLegacyTransaction"] is False

            # Default settings should be applied
            assert (
                captured_request["computeUnitPriceMicroLamports"] == 1000
            )  # from executor
            assert captured_request["computeUnitLimit"] == 120000  # from executor
            # jito_tip_lamports is 0 by default, so should not be present
            assert "prioritizationFeeLamports" not in captured_request

    @pytest.mark.asyncio
    async def test_build_swap_transaction_json_body_with_overrides(self, executor):
        """Test swap transaction JSON body structure with parameter overrides."""
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "1000000",
                    "outAmount": "2000000",
                    "priceImpactPct": 0.1,
                    "routePlan": [],
                }
            ]
        }

        # Capture the actual request body
        captured_request = None

        async def mock_make_request(endpoint, data, method="GET"):
            nonlocal captured_request
            captured_request = data
            return {"swapTransaction": "dGVzdA=="}

        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor, "_make_request", mock_make_request)

            await executor._build_swap_transaction(
                quote_response,
                "user_pubkey",
                priority_fee_micro=2000,
                compute_unit_limit=250000,
                jito_tip_lamports=50000,
            )

            # Verify the JSON body structure with overrides
            assert captured_request is not None
            assert captured_request["route"] == quote_response["routes"][0]
            assert captured_request["userPublicKey"] == "user_pubkey"
            assert captured_request["wrapUnwrapSOL"] is True
            assert captured_request["asLegacyTransaction"] is False

            # Override values should be used
            assert captured_request["computeUnitPriceMicroLamports"] == 2000
            assert captured_request["computeUnitLimit"] == 250000
            assert captured_request["prioritizationFeeLamports"] == 50000

    @pytest.mark.asyncio
    async def test_build_swap_transaction_json_body_zero_values(self, executor_no_live):
        """Test swap transaction JSON body structure with zero values."""
        # Create executor with zero values
        executor_no_live.priority_fee_microlamports = 0
        executor_no_live.compute_unit_limit = 0
        executor_no_live.jito_tip_lamports = 0

        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "1000000",
                    "outAmount": "2000000",
                    "priceImpactPct": 0.1,
                    "routePlan": [],
                }
            ]
        }

        # Capture the actual request body
        captured_request = None

        async def mock_make_request(endpoint, data, method="GET"):
            nonlocal captured_request
            captured_request = data
            return {"swapTransaction": "dGVzdA=="}

        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor_no_live, "_make_request", mock_make_request)

            await executor_no_live._build_swap_transaction(
                quote_response, "user_pubkey"
            )

            # Verify that zero values are omitted from the JSON body
            assert captured_request is not None
            assert captured_request["route"] == quote_response["routes"][0]
            assert captured_request["userPublicKey"] == "user_pubkey"
            assert captured_request["wrapUnwrapSOL"] is True
            assert captured_request["asLegacyTransaction"] is False

            # Zero values should not be present in the request
            assert "computeUnitPriceMicroLamports" not in captured_request
            assert "computeUnitLimit" not in captured_request
            assert "prioritizationFeeLamports" not in captured_request

    @pytest.mark.asyncio
    async def test_simulate(self, executor, token_snapshot):
        """Test trade simulation."""
        # Mock quote response
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "1000000",
                    "outAmount": "2000000",
                    "priceImpactPct": 0.1,
                    "marketInfos": [],
                    "routePlan": [],
                    "swapMode": "ExactIn",
                }
            ]
        }

        # Mock the _get_quote method directly
        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor, "_get_quote", AsyncMock(return_value=quote_response))

            result = await executor.simulate(token_snapshot, 100.0)

        assert (
            result["input_mint"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        )  # USDC
        assert result["output_mint"] == token_snapshot.token.mint
        assert result["input_amount"] == 100_000_000  # 100 USDC * 10^6
        assert result["output_amount"] == "2000000"
        assert result["price_impact_pct"] == 0.1

    @pytest.mark.asyncio
    async def test_simulate_no_routes(self, executor, token_snapshot):
        """Test simulation with no available routes."""
        quote_response = {"routes": []}

        # Mock the _get_quote method directly
        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor, "_get_quote", AsyncMock(return_value=quote_response))

            with pytest.raises(ValueError, match="No routes available for quote"):
                await executor.simulate(token_snapshot, 100.0)

    @pytest.mark.asyncio
    async def test_buy(self, executor, token_snapshot):
        """Test buy execution."""
        # Mock quote response
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "1000000",
                    "outAmount": "2000000",
                    "priceImpactPct": 0.1,
                    "routePlan": [],
                }
            ],
            "quoteId": "quote_456",
        }

        # Mock swap response
        swap_response = {
            "swapTransaction": base64.b64encode(b"test_transaction_bytes").decode(
                "utf-8"
            )
        }

        # Mock the _get_quote and _build_swap_transaction methods
        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor, "_get_quote", AsyncMock(return_value=quote_response))
            m.setattr(
                executor,
                "_build_swap_transaction",
                AsyncMock(return_value=swap_response),
            )

            result = await executor.buy(token_snapshot, 100.0)

        assert result["sig"] == "test_signature_67890"
        assert result["quote_id"] == "quote_456"
        assert result["operation"] == "buy"
        assert result["input_mint"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        assert result["output_mint"] == token_snapshot.token.mint
        assert result["input_amount"] == 100_000_000
        assert result["output_amount"] == "2000000"

        # Verify signer and sender were called
        assert executor.sender.simulate_called
        assert executor.sender.send_called

    @pytest.mark.asyncio
    async def test_buy_no_live_trading(self, executor_no_live, token_snapshot):
        """Test buy execution without live trading enabled."""
        with pytest.raises(NotImplementedError, match="Live trading is disabled"):
            await executor_no_live.buy(token_snapshot, 100.0)

    @pytest.mark.asyncio
    async def test_sell(self, executor):
        """Test sell execution."""
        token = TokenId(chain="sol", mint="TestToken123")

        # Mock quote response
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "500000000",  # 0.5 tokens
                    "outAmount": "250000",  # 0.25 USDC
                    "priceImpactPct": 0.1,
                    "routePlan": [],
                }
            ],
            "quoteId": "quote_789",
        }

        # Mock swap response
        swap_response = {
            "swapTransaction": base64.b64encode(b"test_transaction_bytes").decode(
                "utf-8"
            )
        }

        # Mock the _get_quote and _build_swap_transaction methods
        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor, "_get_quote", AsyncMock(return_value=quote_response))
            m.setattr(
                executor,
                "_build_swap_transaction",
                AsyncMock(return_value=swap_response),
            )

            result = await executor.sell(token, 50.0)  # Sell 50%

        assert result["sig"] == "test_signature_67890"
        assert result["quote_id"] == "quote_789"
        assert result["operation"] == "sell"
        assert result["input_mint"] == token.mint
        assert result["output_mint"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

        # Verify signer and sender were called
        assert executor.sender.simulate_called
        assert executor.sender.send_called

    @pytest.mark.asyncio
    async def test_sell_no_live_trading(self, executor_no_live):
        """Test sell execution without live trading enabled."""
        token = TokenId(chain="sol", mint="TestToken123")

        with pytest.raises(NotImplementedError, match="Live trading is disabled"):
            await executor_no_live.sell(token, 50.0)

    @pytest.mark.asyncio
    async def test_buy_with_parameter_overrides(self, executor, token_snapshot):
        """Test buy execution with parameter overrides."""
        # Mock quote and swap responses
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "100000000",
                    "outAmount": "2000000000",
                    "priceImpactPct": 0.1,
                    "routePlan": [],
                }
            ],
            "quoteId": "quote_456",
        }

        swap_response = {"swapTransaction": base64.b64encode(b"test_tx").decode("utf-8")}

        captured_swap_params = None

        async def mock_build_swap_transaction(quote_resp, pubkey, **kwargs):
            nonlocal captured_swap_params
            captured_swap_params = kwargs
            return swap_response

        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor, "_get_quote", AsyncMock(return_value=quote_response))
            m.setattr(executor, "_build_swap_transaction", mock_build_swap_transaction)

            result = await executor.buy(
                token_snapshot,
                100.0,
                priority_fee_micro=3000,
                compute_unit_limit=300000,
                jito_tip_lamports=75000,
            )

            # Verify that parameter overrides were passed through
            assert captured_swap_params is not None
            assert captured_swap_params["priority_fee_micro"] == 3000
            assert captured_swap_params["compute_unit_limit"] == 300000
            assert captured_swap_params["jito_tip_lamports"] == 75000

            # Verify the result structure
            assert result["sig"] == "test_signature_67890"
            assert result["operation"] == "buy"

    @pytest.mark.asyncio
    async def test_sell_with_parameter_overrides(self, executor):
        """Test sell execution with parameter overrides."""
        token = TokenId(chain="sol", mint="TestToken123")

        # Mock quote and swap responses
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "500000000",
                    "outAmount": "1000000",
                    "priceImpactPct": 0.1,
                    "routePlan": [],
                }
            ],
            "quoteId": "quote_456",
        }

        swap_response = {"swapTransaction": base64.b64encode(b"test_tx").decode("utf-8")}

        captured_swap_params = None

        async def mock_build_swap_transaction(quote_resp, pubkey, **kwargs):
            nonlocal captured_swap_params
            captured_swap_params = kwargs
            return swap_response

        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor, "_get_quote", AsyncMock(return_value=quote_response))
            m.setattr(executor, "_build_swap_transaction", mock_build_swap_transaction)

            result = await executor.sell(
                token,
                50.0,
                priority_fee_micro=4000,
                compute_unit_limit=400000,
                jito_tip_lamports=100000,
            )

            # Verify that parameter overrides were passed through
            assert captured_swap_params is not None
            assert captured_swap_params["priority_fee_micro"] == 4000
            assert captured_swap_params["compute_unit_limit"] == 400000
            assert captured_swap_params["jito_tip_lamports"] == 100000

            # Verify the result structure
            assert result["sig"] == "test_signature_67890"
            assert result["operation"] == "sell"

    @pytest.mark.asyncio
    async def test_execute_trade_no_swap_transaction(self, executor):
        """Test trade execution with missing swap transaction."""
        # Mock quote response
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "1000000",
                    "outAmount": "2000000",
                    "priceImpactPct": 0.1,
                }
            ],
            "quoteId": "quote_456",
        }

        # Mock swap response without transaction
        swap_response = {}

        # Mock the _get_quote and _build_swap_transaction methods
        with pytest.MonkeyPatch().context() as m:
            m.setattr(executor, "_get_quote", AsyncMock(return_value=quote_response))
            m.setattr(
                executor,
                "_build_swap_transaction",
                AsyncMock(return_value=swap_response),
            )

            with pytest.raises(ValueError, match="No swap transaction in response"):
                await executor.buy(
                    TokenSnapshot(
                        token=TokenId(chain="sol", mint="TestToken123"),
                        pool=None,
                        price_usd=0.5,
                        liq_usd=1000000.0,
                        vol_5m_usd=50000.0,
                        holders=1000,
                        age_seconds=3600,
                        pct_change_5m=5.0,
                        source="test",
                        ts=datetime.now(UTC),
                    ),
                    100.0,
                )

    def test_get_config_summary(self, executor):
        """Test configuration summary."""
        summary = executor.get_config_summary()

        assert summary["base_url"] == "https://quote-api.jup.ag/v6"
        assert summary["rpc_url"] == "https://api.mainnet-beta.solana.com"
        assert summary["max_slippage_bps"] == 100
        assert summary["priority_fee_microlamports"] == 1000
        assert summary["compute_unit_limit"] == 120000
        assert summary["jito_tip_lamports"] == 0
        assert summary["live_trading_enabled"] is True
        assert summary["signer_configured"] is True
        assert summary["sender_configured"] is True
        assert summary["enable_preflight"] is True


class TestJupiterIntegration:
    """Integration tests for Jupiter executor."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_full_buy_flow(self):
        """Test complete buy flow with mocked HTTP responses."""
        # Create executor with mock signer and sender
        signer = MockSigner("TestPubkey123")
        sender = MockSender()

        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=0,
            signer=signer,
            sender=sender,
            session=httpx.AsyncClient(),
        )

        # Create token snapshot
        token_snapshot = TokenSnapshot(
            token=TokenId(chain="sol", mint="TestToken123"),
            pool=None,
            price_usd=0.5,
            liq_usd=1000000.0,
            vol_5m_usd=50000.0,
            holders=1000,
            age_seconds=3600,
            pct_change_5m=5.0,
            source="test",
            ts=datetime.now(UTC),
        )

        # Mock quote endpoint
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "1000000",
                    "outAmount": "2000000",
                    "priceImpactPct": 0.1,
                    "routePlan": [],
                }
            ],
            "quoteId": "quote_456",
        }

        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(200, json=quote_response)
        )

        # Mock swap endpoint
        swap_response = {
            "swapTransaction": base64.b64encode(b"test_transaction_bytes").decode(
                "utf-8"
            )
        }

        respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=httpx.Response(200, json=swap_response)
        )

        # Execute buy
        result = await executor.buy(token_snapshot, 100.0)

        # Verify result
        assert result["sig"] == "test_signature_67890"
        assert result["quote_id"] == "quote_456"
        assert result["operation"] == "buy"
        assert result["input_mint"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        assert result["output_mint"] == token_snapshot.token.mint
        assert result["input_amount"] == 100_000_000
        assert result["output_amount"] == "2000000"

        # Verify signer and sender were called
        assert sender.simulate_called
        assert sender.send_called

        # Verify HTTP requests were made
        assert len(respx.calls) == 2
        assert respx.calls[0].request.url.path == "/v6/quote"
        assert respx.calls[1].request.url.path == "/v6/swap"

    @pytest.mark.asyncio
    @respx.mock
    async def test_full_sell_flow(self):
        """Test complete sell flow with mocked HTTP responses."""
        # Create executor with mock signer and sender
        signer = MockSigner("TestPubkey123")
        sender = MockSender()

        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=0,
            signer=signer,
            sender=sender,
            session=httpx.AsyncClient(),
        )

        token = TokenId(chain="sol", mint="TestToken123")

        # Mock quote endpoint
        quote_response = {
            "routes": [
                {
                    "id": "route_123",
                    "inAmount": "500000000",  # 0.5 tokens
                    "outAmount": "250000",  # 0.25 USDC
                    "priceImpactPct": 0.1,
                    "routePlan": [],
                }
            ],
            "quoteId": "quote_789",
        }

        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(200, json=quote_response)
        )

        # Mock swap endpoint
        swap_response = {
            "swapTransaction": base64.b64encode(b"test_transaction_bytes").decode(
                "utf-8"
            )
        }

        respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=httpx.Response(200, json=swap_response)
        )

        # Execute sell
        result = await executor.sell(token, 50.0)  # Sell 50%

        # Verify result
        assert result["sig"] == "test_signature_67890"
        assert result["quote_id"] == "quote_789"
        assert result["operation"] == "sell"
        assert result["input_mint"] == token.mint
        assert result["output_mint"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

        # Verify signer and sender were called
        assert sender.simulate_called
        assert sender.send_called

        # Verify HTTP requests were made
        assert len(respx.calls) == 2
        assert respx.calls[0].request.url.path == "/v6/quote"
        assert respx.calls[1].request.url.path == "/v6/swap"
