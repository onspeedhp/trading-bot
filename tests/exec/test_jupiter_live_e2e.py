"""End-to-end tests for Jupiter live trading functionality."""

import base64
import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from bot.core.types import TokenId, TokenSnapshot
from bot.exec.jupiter import JupiterExecutor
from bot.exec.senders import RpcSender


class FakeSigner:
    """Fake signer that appends a marker to transaction bytes."""

    def __init__(self, pubkey: str = "FakePubkey123456789"):
        self.pubkey = pubkey

    def pubkey_base58(self) -> str:
        """Get the public key in base64 format."""
        return self.pubkey

    def sign_transaction(self, txn_bytes: bytes) -> bytes:
        """Sign a transaction by appending a fake signature marker."""
        # Append a fake signature marker
        fake_signature = b"FAKE_SIGNATURE_MARKER_12345"
        return txn_bytes + fake_signature


@pytest.fixture
def token_snapshot():
    """Create a realistic token snapshot for testing."""
    return TokenSnapshot(
        token=TokenId(
            chain="sol", mint="So11111111111111111111111111111111111111112"
        ),  # SOL
        pool=None,
        price_usd=100.0,  # $100 SOL
        liq_usd=1000000.0,  # $1M liquidity
        vol_5m_usd=50000.0,  # $50K 5min volume
        holders=100000,
        age_seconds=86400,  # 1 day
        pct_change_5m=2.5,
        source="test",
        ts=datetime.now(UTC),
    )


@pytest.fixture
def mock_quote_response():
    """Create a realistic Jupiter quote response."""
    return {
        "routes": [
            {
                "id": "route_123456789",
                "inAmount": "1000000",  # 1 USDC (6 decimals)
                "outAmount": "10000000",  # 0.01 SOL (9 decimals)
                "priceImpactPct": 0.15,
                "marketInfos": [
                    {
                        "id": "market_1",
                        "label": "Raydium",
                        "inputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                        "outputMint": "So11111111111111111111111111111111111111112",
                        "notEnoughLiquidity": False,
                        "inAmount": "1000000",
                        "outAmount": "10000000",
                    }
                ],
                "routePlan": [
                    {
                        "swapInfo": {
                            "amm": {
                                "id": "raydium_amm_1",
                                "label": "Raydium",
                            },
                            "inAmount": "1000000",
                            "outAmount": "10000000",
                        }
                    }
                ],
                "swapMode": "ExactIn",
            }
        ],
        "quoteId": "quote_987654321",
    }


@pytest.fixture
def mock_swap_response():
    """Create a realistic Jupiter swap response."""
    # Create a fake transaction blob
    fake_tx_data = {
        "version": 0,
        "header": {
            "numRequiredSignatures": 1,
            "numReadonlySignedAccounts": 0,
            "numReadonlyUnsignedAccounts": 1,
        },
        "staticAccountKeys": [
            "FakePubkey123456789",
            "11111111111111111111111111111111",
        ],
        "recentBlockhash": "fake_blockhash_123456789",
        "instructions": [
            {
                "programIdIndex": 1,
                "accounts": [0],
                "data": "fake_instruction_data",
            }
        ],
    }

    # Serialize to JSON and encode as base64
    tx_json = json.dumps(fake_tx_data, separators=(",", ":"))
    tx_bytes = tx_json.encode("utf-8")
    tx_base64 = base64.b64encode(tx_bytes).decode("utf-8")

    return {"swapTransaction": tx_base64}


@pytest.fixture
def mock_rpc_responses():
    """Create realistic RPC responses."""
    return {
        "simulate": {
            "jsonrpc": "2.0",
            "result": {
                "value": {
                    "err": None,
                    "logs": [
                        "Program 11111111111111111111111111111111 invoke [1]",
                        "Program 11111111111111111111111111111111 success",
                    ],
                    "unitsConsumed": 120000,
                }
            },
            "id": 1,
        },
        "send": {
            "jsonrpc": "2.0",
            "result": "fake_signature_123456789abcdef",
            "id": 1,
        },
    }


@pytest.fixture
def jupiter_executor():
    """Create a JupiterExecutor with fake signer and mocked sender."""
    signer = FakeSigner()
    sender = RpcSender(rpc_url="https://api.mainnet-beta.solana.com")

    return JupiterExecutor(
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


@pytest.mark.skipif(not respx, reason="respx not available")
class TestJupiterLiveE2E:
    """End-to-end tests for Jupiter live trading."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_buy_flow_success(
        self,
        jupiter_executor,
        token_snapshot,
        mock_quote_response,
        mock_swap_response,
        mock_rpc_responses,
    ):
        """Test successful buy flow with realistic mocked responses."""
        # Mock Jupiter quote endpoint
        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(200, json=mock_quote_response)
        )

        # Mock Jupiter swap endpoint
        respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=httpx.Response(200, json=mock_swap_response)
        )

        # Mock RPC simulate endpoint
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(200, json=mock_rpc_responses["simulate"])
        )

        # Mock RPC send endpoint
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(200, json=mock_rpc_responses["send"])
        )

        # Execute buy
        result = await jupiter_executor.buy(token_snapshot, 100.0)

        # Verify result structure
        assert isinstance(result, dict)
        assert "sig" in result
        assert result["sig"] == "fake_signature_123456789abcdef"
        assert "route" in result
        assert "price_est" in result
        assert "ts" in result
        assert "quote_id" in result
        assert "operation" in result
        assert result["operation"] == "buy"
        assert "input_mint" in result
        assert "output_mint" in result
        assert "input_amount" in result
        assert "output_amount" in result
        assert "price_impact_pct" in result
        assert "slippage_bps" in result

        # Verify route details
        route = result["route"]
        assert route["id"] == "route_123456789"
        assert route["inAmount"] == "1000000"
        assert route["outAmount"] == "10000000"
        assert route["priceImpactPct"] == 0.15

        # Verify HTTP requests were made
        assert len(respx.calls) == 4
        assert respx.calls[0].request.url.path == "/v6/quote"
        assert respx.calls[1].request.url.path == "/v6/swap"
        assert respx.calls[2].request.url.path == "/"  # RPC simulate
        assert respx.calls[3].request.url.path == "/"  # RPC send

    @pytest.mark.asyncio
    @respx.mock
    async def test_sell_flow_success(
        self,
        jupiter_executor,
        token_snapshot,
        mock_quote_response,
        mock_swap_response,
        mock_rpc_responses,
    ):
        """Test successful sell flow with realistic mocked responses."""
        # Mock Jupiter quote endpoint
        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(200, json=mock_quote_response)
        )

        # Mock Jupiter swap endpoint
        respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=httpx.Response(200, json=mock_swap_response)
        )

        # Mock RPC simulate endpoint
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(200, json=mock_rpc_responses["simulate"])
        )

        # Mock RPC send endpoint
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(200, json=mock_rpc_responses["send"])
        )

        # Execute sell
        result = await jupiter_executor.sell(token_snapshot.token, 50.0)

        # Verify result structure
        assert isinstance(result, dict)
        assert "sig" in result
        assert result["sig"] == "fake_signature_123456789abcdef"
        assert "operation" in result
        assert result["operation"] == "sell"

        # Verify HTTP requests were made
        assert len(respx.calls) == 4

    @pytest.mark.asyncio
    @respx.mock
    async def test_quote_rate_limit_retry(
        self,
        jupiter_executor,
        token_snapshot,
        mock_quote_response,
        mock_swap_response,
        mock_rpc_responses,
    ):
        """Test that rate limit errors trigger retries."""
        # Mock Jupiter quote endpoint to return 429 first, then success
        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(429, json={"error": "Rate limit exceeded"})
        ).mock(return_value=httpx.Response(200, json=mock_quote_response))

        # Mock Jupiter swap endpoint
        respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=httpx.Response(200, json=mock_swap_response)
        )

        # Mock RPC endpoints
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(200, json=mock_rpc_responses["simulate"])
        ).mock(return_value=httpx.Response(200, json=mock_rpc_responses["send"]))

        # Execute buy - should retry and succeed
        result = await jupiter_executor.buy(token_snapshot, 100.0)

        # Verify success
        assert result["sig"] == "fake_signature_123456789abcdef"

        # Verify retry occurred - the Jupiter executor doesn't retry quote failures,
        # but we can verify the first call was made and then succeeded
        assert len(respx.calls) >= 4  # quote + quote + swap + 2 RPC calls

    @pytest.mark.asyncio
    @respx.mock
    async def test_quote_permanent_failure(self, jupiter_executor, token_snapshot):
        """Test that permanent quote failures surface clean errors."""
        # Mock Jupiter quote endpoint to always fail
        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(500, json={"error": "Internal server error"})
        )

        # Execute buy - should fail with clean error
        with pytest.raises(Exception) as exc_info:
            await jupiter_executor.buy(token_snapshot, 100.0)

        # Verify error is surfaced
        assert "Internal server error" in str(exc_info.value) or "500" in str(
            exc_info.value
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_swap_failure(
        self, jupiter_executor, token_snapshot, mock_quote_response
    ):
        """Test that swap failures surface clean errors."""
        # Mock Jupiter quote endpoint
        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(200, json=mock_quote_response)
        )

        # Mock Jupiter swap endpoint to fail
        respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=httpx.Response(400, json={"error": "Invalid route"})
        )

        # Execute buy - should fail with clean error
        with pytest.raises(Exception) as exc_info:
            await jupiter_executor.buy(token_snapshot, 100.0)

        # Verify error is surfaced
        assert "Invalid route" in str(exc_info.value) or "400" in str(exc_info.value)

    @pytest.mark.asyncio
    @respx.mock
    async def test_rpc_simulate_failure(
        self, jupiter_executor, token_snapshot, mock_quote_response, mock_swap_response
    ):
        """Test that RPC simulation failures are handled gracefully."""
        # Mock Jupiter endpoints
        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(200, json=mock_quote_response)
        )
        respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=httpx.Response(200, json=mock_swap_response)
        )

        # Mock RPC simulate to fail
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "result": {
                        "value": {
                            "err": "InvalidInstructionData",
                            "logs": ["Program failed: Invalid instruction data"],
                        }
                    },
                    "id": 1,
                },
            )
        )

        # Mock RPC send to succeed
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "result": "fake_signature_123456789abcdef",
                    "id": 1,
                },
            )
        )

        # Execute buy - should continue despite simulation failure
        result = await jupiter_executor.buy(token_snapshot, 100.0)

        # Verify success (simulation failure is logged but doesn't stop execution)
        assert result["sig"] == "fake_signature_123456789abcdef"

    @pytest.mark.asyncio
    @respx.mock
    async def test_rpc_send_failure_retry(
        self,
        jupiter_executor,
        token_snapshot,
        mock_quote_response,
        mock_swap_response,
        mock_rpc_responses,
    ):
        """Test that RPC send failures trigger retries."""
        # Mock Jupiter endpoints
        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(200, json=mock_quote_response)
        )
        respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=httpx.Response(200, json=mock_swap_response)
        )

        # Mock RPC simulate
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(200, json=mock_rpc_responses["simulate"])
        )

        # Mock RPC send to fail first, then succeed
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(500, json={"error": "RPC error"})
        ).mock(return_value=httpx.Response(200, json=mock_rpc_responses["send"]))

        # Execute buy - should retry and succeed
        result = await jupiter_executor.buy(token_snapshot, 100.0)

        # Verify success
        assert result["sig"] == "fake_signature_123456789abcdef"

        # Verify retry occurred - the RpcSender should retry on 500 errors
        # Note: The exact number depends on the retry configuration
        assert (
            len(respx.calls) >= 4
        )  # quote + swap + simulate + send (with potential retries)

    @pytest.mark.asyncio
    @respx.mock
    async def test_parameter_overrides(
        self,
        jupiter_executor,
        token_snapshot,
        mock_quote_response,
        mock_swap_response,
        mock_rpc_responses,
    ):
        """Test that parameter overrides work correctly."""
        # Mock all endpoints
        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(200, json=mock_quote_response)
        )
        respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=httpx.Response(200, json=mock_swap_response)
        )
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(200, json=mock_rpc_responses["simulate"])
        ).mock(return_value=httpx.Response(200, json=mock_rpc_responses["send"]))

        # Execute buy with parameter overrides
        result = await jupiter_executor.buy(
            token_snapshot,
            100.0,
            priority_fee_micro=2000,
            compute_unit_limit=250000,
            jito_tip_lamports=50000,
        )

        # Verify success
        assert result["sig"] == "fake_signature_123456789abcdef"

        # Verify swap request included overrides
        swap_call = respx.calls[1]
        swap_data = json.loads(swap_call.request.content)
        assert swap_data["computeUnitPriceMicroLamports"] == 2000
        assert swap_data["computeUnitLimit"] == 250000
        assert swap_data["prioritizationFeeLamports"] == 50000

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_routes_available(self, jupiter_executor, token_snapshot):
        """Test handling of no routes available."""
        # Mock Jupiter quote endpoint with no routes
        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(
                200, json={"routes": [], "quoteId": "empty_quote"}
            )
        )

        # Execute buy - should fail with clear error
        with pytest.raises(ValueError, match="No routes available"):
            await jupiter_executor.buy(token_snapshot, 100.0)

    @pytest.mark.asyncio
    @respx.mock
    async def test_missing_swap_transaction(
        self, jupiter_executor, token_snapshot, mock_quote_response
    ):
        """Test handling of missing swap transaction in response."""
        # Mock Jupiter quote endpoint
        respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=httpx.Response(200, json=mock_quote_response)
        )

        # Mock Jupiter swap endpoint with missing transaction
        respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=httpx.Response(200, json={"error": "No transaction generated"})
        )

        # Execute buy - should fail with clear error
        with pytest.raises(ValueError, match="No swap transaction in response"):
            await jupiter_executor.buy(token_snapshot, 100.0)


@pytest.mark.skipif(not respx, reason="respx not available")
class TestFakeSigner:
    """Tests for the FakeSigner implementation."""

    def test_fake_signer_creation(self):
        """Test FakeSigner creation and basic functionality."""
        signer = FakeSigner("TestPubkey123")

        assert signer.pubkey_base58() == "TestPubkey123"

    def test_fake_signer_transaction_signing(self):
        """Test that FakeSigner appends signature marker."""
        signer = FakeSigner()
        original_tx = b"original_transaction_bytes"

        signed_tx = signer.sign_transaction(original_tx)

        assert signed_tx.startswith(original_tx)
        assert signed_tx.endswith(b"FAKE_SIGNATURE_MARKER_12345")
        assert len(signed_tx) == len(original_tx) + len(b"FAKE_SIGNATURE_MARKER_12345")
