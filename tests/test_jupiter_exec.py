"""Tests for Jupiter execution engine."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from bot.core.types import TokenId, TokenSnapshot
from bot.exec.jupiter import (
    JupiterExecutor,
    Sender,
    Signer,
    build_quote_params,
)


def create_mock_response(data: dict) -> AsyncMock:
    """Create a properly configured mock response."""
    mock_response = AsyncMock()
    mock_response.json = MagicMock(return_value=data)
    mock_response.raise_for_status = MagicMock()
    return mock_response


class TestBuildQuoteParams:
    """Test quote parameter building."""

    def test_basic_params(self):
        """Test basic parameter building."""
        params = build_quote_params(
            input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            output_mint="So11111111111111111111111111111111111111112",  # SOL
            amount=1000000,  # 1 USDC
            slippage_bps=100,  # 1%
        )

        assert params["inputMint"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        assert params["outputMint"] == "So11111111111111111111111111111111111111112"
        assert params["amount"] == "1000000"
        assert params["slippageBps"] == 100
        assert params["onlyDirectRoutes"] is False
        assert params["asLegacyTransaction"] is False

    def test_optional_params(self):
        """Test optional parameters."""
        params = build_quote_params(
            input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            output_mint="So11111111111111111111111111111111111111112",
            amount=1000000,
            slippage_bps=100,
            only_direct_routes=True,
            as_legacy_transaction=True,
        )

        assert params["onlyDirectRoutes"] is True
        assert params["asLegacyTransaction"] is True

    def test_amount_as_string(self):
        """Test that amount is converted to string."""
        params = build_quote_params(
            input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            output_mint="So11111111111111111111111111111111111111112",
            amount=123456789,
            slippage_bps=50,
        )

        assert params["amount"] == "123456789"
        assert isinstance(params["amount"], str)


class TestJupiterExecutor:
    """Test Jupiter executor functionality."""

    def test_init_basic(self):
        """Test basic initialization."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
        )

        assert executor.base_url == "https://quote-api.jup.ag/v6"
        assert executor.rpc_url == "https://api.mainnet-beta.solana.com"
        assert executor.max_slippage_bps == 100
        assert executor.priority_fee_microlamports == 1000
        assert executor.compute_unit_limit == 120000
        assert executor.jito_tip_lamports == 10000
        assert executor.signer is None
        assert executor.sender is None
        assert executor.session is None

    def test_init_with_signer_sender(self):
        """Test initialization with signer and sender."""
        mock_signer = MagicMock(spec=Signer)
        mock_sender = MagicMock(spec=Sender)
        mock_session = AsyncMock(spec=httpx.AsyncClient)

        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
            signer=mock_signer,
            sender=mock_sender,
            session=mock_session,
        )

        assert executor.signer == mock_signer
        assert executor.sender == mock_sender
        assert executor.session == mock_session

    def test_url_normalization(self):
        """Test URL normalization."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6/",
            rpc_url="https://api.mainnet-beta.solana.com/",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
        )

        assert executor.base_url == "https://quote-api.jup.ag/v6"
        assert executor.rpc_url == "https://api.mainnet-beta.solana.com"

    def test_is_live_trading_enabled(self):
        """Test live trading enabled check."""
        # Without signer/sender
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
        )
        assert executor._is_live_trading_enabled() is False

        # With signer/sender
        mock_signer = MagicMock(spec=Signer)
        mock_sender = MagicMock(spec=Sender)

        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
            signer=mock_signer,
            sender=mock_sender,
        )
        assert executor._is_live_trading_enabled() is True

    @pytest.mark.asyncio
    async def test_make_request_no_session(self):
        """Test make_request without session."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
        )

        with pytest.raises(RuntimeError, match="HTTP session not configured"):
            await executor._make_request("quote")

    @pytest.mark.asyncio
    async def test_make_request_success(self):
        """Test successful HTTP request."""
        mock_session = AsyncMock(spec=httpx.AsyncClient)
        mock_response = create_mock_response({"routes": []})
        mock_session.get.return_value = mock_response

        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
            session=mock_session,
        )

        result = await executor._make_request("quote", {"test": "param"})

        assert result == {"routes": []}
        mock_session.get.assert_called_once_with(
            "https://quote-api.jup.ag/v6/quote", params={"test": "param"}, timeout=30.0
        )

    @pytest.mark.asyncio
    async def test_make_request_http_error(self):
        """Test HTTP error handling."""
        mock_session = AsyncMock(spec=httpx.AsyncClient)
        mock_response = AsyncMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        mock_session.get.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_response
        )

        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
            session=mock_session,
        )

        with pytest.raises(httpx.HTTPStatusError):
            await executor._make_request("quote")

    @pytest.mark.asyncio
    async def test_get_quote(self):
        """Test quote retrieval."""
        mock_session = AsyncMock(spec=httpx.AsyncClient)
        mock_response = create_mock_response(
            {
                "routes": [
                    {
                        "outAmount": "1000000",
                        "priceImpactPct": 0.1,
                        "marketInfos": [],
                        "routePlan": [],
                        "swapMode": "ExactIn",
                    }
                ]
            }
        )
        mock_session.get.return_value = mock_response

        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
            session=mock_session,
        )

        result = await executor._get_quote(
            input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            output_mint="So11111111111111111111111111111111111111112",
            amount=1000000,
        )

        assert result["routes"][0]["outAmount"] == "1000000"
        mock_session.get.assert_called_once()
        call_args = mock_session.get.call_args
        assert "quote" in call_args[0][0]
        assert (
            call_args[1]["params"]["inputMint"]
            == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        )

    @pytest.mark.asyncio
    async def test_simulate_success(self):
        """Test successful simulation."""
        mock_session = AsyncMock(spec=httpx.AsyncClient)
        mock_response = create_mock_response(
            {
                "routes": [
                    {
                        "outAmount": "1000000",
                        "priceImpactPct": 0.1,
                        "marketInfos": [{"label": "Raydium"}],
                        "routePlan": [{"swapInfo": {"amm": {"label": "Raydium"}}}],
                        "swapMode": "ExactIn",
                    }
                ]
            }
        )
        mock_session.get.return_value = mock_response

        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
            session=mock_session,
        )

        snap = TokenSnapshot(
            token=TokenId(mint="So11111111111111111111111111111111111111112"),
            price_usd=100.0,
            liq_usd=1000000.0,
            vol_5m_usd=100000.0,
            source="test",
            ts=datetime.now(),
        )

        result = await executor.simulate(snap, 100.0)

        assert result["input_mint"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        assert result["output_mint"] == "So11111111111111111111111111111111111111112"
        assert result["input_amount"] == 100_000_000  # 100 USDC
        assert result["output_amount"] == "1000000"
        assert result["price_impact_pct"] == 0.1
        assert result["slippage_bps"] == 100
        assert "ts" in result

    @pytest.mark.asyncio
    async def test_simulate_no_routes(self):
        """Test simulation with no available routes."""
        mock_session = AsyncMock(spec=httpx.AsyncClient)
        mock_response = create_mock_response({"routes": []})
        mock_session.get.return_value = mock_response

        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
            session=mock_session,
        )

        snap = TokenSnapshot(
            token=TokenId(mint="So11111111111111111111111111111111111111112"),
            price_usd=100.0,
            liq_usd=1000000.0,
            vol_5m_usd=100000.0,
            source="test",
            ts=datetime.now(),
        )

        with pytest.raises(ValueError, match="No routes available for quote"):
            await executor.simulate(snap, 100.0)

    @pytest.mark.asyncio
    async def test_buy_not_implemented(self):
        """Test that buy raises NotImplementedError."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
        )

        snap = TokenSnapshot(
            token=TokenId(mint="So11111111111111111111111111111111111111112"),
            price_usd=100.0,
            liq_usd=1000000.0,
            vol_5m_usd=100000.0,
            source="test",
            ts=datetime.now(),
        )

        with pytest.raises(
            NotImplementedError, match="Live trading is disabled in this build"
        ):
            await executor.buy(snap, 100.0)

    @pytest.mark.asyncio
    async def test_sell_not_implemented(self):
        """Test that sell raises NotImplementedError."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
        )

        with pytest.raises(
            NotImplementedError, match="Live trading is disabled in this build"
        ):
            await executor.sell(TokenId(mint="test_token"), 50.0)

    def test_get_config_summary(self):
        """Test configuration summary."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
        )

        summary = executor.get_config_summary()

        assert summary["base_url"] == "https://quote-api.jup.ag/v6"
        assert summary["rpc_url"] == "https://api.mainnet-beta.solana.com"
        assert summary["max_slippage_bps"] == 100
        assert summary["priority_fee_microlamports"] == 1000
        assert summary["compute_unit_limit"] == 120000
        assert summary["jito_tip_lamports"] == 10000
        assert summary["live_trading_enabled"] is False
        assert summary["signer_configured"] is False
        assert summary["sender_configured"] is False

    def test_get_config_summary_with_signer_sender(self):
        """Test configuration summary with signer and sender."""
        mock_signer = MagicMock(spec=Signer)
        mock_sender = MagicMock(spec=Sender)

        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=10000,
            signer=mock_signer,
            sender=mock_sender,
        )

        summary = executor.get_config_summary()

        assert summary["live_trading_enabled"] is True
        assert summary["signer_configured"] is True
        assert summary["sender_configured"] is True


class TestSignerSenderProtocols:
    """Test Signer and Sender protocols."""

    def test_signer_protocol(self):
        """Test Signer protocol compliance."""

        class MockSigner:
            def sign_txn(self, message_bytes: bytes) -> bytes:
                return b"signed_transaction"

        signer = MockSigner()
        assert isinstance(signer, Signer)
        assert signer.sign_txn(b"test") == b"signed_transaction"

    def test_sender_protocol(self):
        """Test Sender protocol compliance."""

        class MockSender:
            def send_raw_txn(self, txn_bytes: bytes) -> str:
                return "transaction_signature"

        sender = MockSender()
        assert isinstance(sender, Sender)
        assert sender.send_raw_txn(b"test") == "transaction_signature"
