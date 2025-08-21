"""Tests for transaction senders."""

import asyncio
import json
from unittest.mock import Mock, patch
import pytest
import httpx
import respx

from bot.exec.senders import TxnSender, RpcSender, SolanaRpcError, _is_retryable_error


class TestTxnSenderProtocol:
    """Test the TxnSender protocol compliance."""

    def test_protocol_definition(self):
        """Test that TxnSender protocol is properly defined."""
        # This should not raise any errors
        assert hasattr(TxnSender, "__call__")
        # Just verify the protocol exists
        assert TxnSender is not None


class TestSolanaRpcError:
    """Test SolanaRpcError exception."""

    def test_error_creation(self):
        """Test creating SolanaRpcError."""
        error = SolanaRpcError(
            code=-32603, message="Internal error", data={"details": "test"}
        )

        assert error.code == -32603
        assert error.message == "Internal error"
        assert error.data == {"details": "test"}
        assert str(error) == "RPC Error -32603: Internal error"

    def test_error_without_data(self):
        """Test creating SolanaRpcError without data."""
        error = SolanaRpcError(code=429, message="Too many requests")

        assert error.code == 429
        assert error.message == "Too many requests"
        assert error.data is None


class TestRpcSender:
    """Test RpcSender functionality."""

    @pytest.fixture
    def sender(self):
        """Create RpcSender instance for testing."""
        return RpcSender("https://api.mainnet-beta.solana.com")

    def test_initialization(self, sender):
        """Test RpcSender initialization."""
        assert sender.rpc_url == "https://api.mainnet-beta.solana.com"
        assert sender.timeout == 30.0
        assert sender._request_id == 0

    def test_initialization_with_client(self):
        """Test RpcSender initialization with custom client."""
        client = httpx.AsyncClient()
        sender = RpcSender("https://test.com", client=client, timeout=60.0)

        assert sender.client is client
        assert sender.timeout == 60.0

    def test_get_request_id(self, sender):
        """Test request ID generation."""
        id1 = sender._get_request_id()
        id2 = sender._get_request_id()

        assert id1 == 1
        assert id2 == 2
        assert id2 > id1

    def test_is_retryable_error(self, sender):
        """Test retryable error detection."""
        # Retryable errors
        assert _is_retryable_error(httpx.TimeoutException("timeout"))
        assert _is_retryable_error(httpx.ConnectError("connection failed"))
        assert _is_retryable_error(httpx.NetworkError("network error"))
        assert _is_retryable_error(SolanaRpcError(-32603, "Internal error"))
        assert _is_retryable_error(SolanaRpcError(429, "Too many requests"))

        # Non-retryable errors
        assert not _is_retryable_error(SolanaRpcError(-32602, "Invalid params"))
        assert not _is_retryable_error(ValueError("Invalid value"))
        assert not _is_retryable_error(Exception("Generic error"))

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test RpcSender as async context manager."""
        async with RpcSender("https://test.com") as sender:
            assert sender is not None
        # Context manager should close the client

    @pytest.mark.asyncio
    @respx.mock
    async def test_make_rpc_request_success(self, sender):
        """Test successful RPC request."""
        # Mock successful response
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": {"test": "success"}}
            )
        )

        result = await sender._make_rpc_request("testMethod", ["param1", "param2"])

        assert result == {"test": "success"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_make_rpc_request_rpc_error(self, sender):
        """Test RPC request with JSON-RPC error."""
        # Mock RPC error response
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {
                        "code": -32602,
                        "message": "Invalid params",
                        "data": {"details": "param error"},
                    },
                },
            )
        )

        with pytest.raises(SolanaRpcError) as exc_info:
            await sender._make_rpc_request("testMethod", ["invalid"])

        assert exc_info.value.code == -32602
        assert exc_info.value.message == "Invalid params"
        assert exc_info.value.data == {"details": "param error"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_make_rpc_request_http_error(self, sender):
        """Test RPC request with HTTP error."""
        # Mock HTTP error
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        with pytest.raises(httpx.HTTPStatusError):
            await sender._make_rpc_request("testMethod", [])

    @pytest.mark.asyncio
    @respx.mock
    async def test_simulate_success(self, sender):
        """Test successful transaction simulation."""
        # Mock successful simulation response
        simulation_result = {
            "value": {
                "err": None,
                "logs": ["Program log: success"],
                "unitsConsumed": 5000,
            }
        }

        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": simulation_result}
            )
        )

        tx_base64 = "test_transaction_base64"
        result = await sender.simulate(tx_base64)

        assert result == simulation_result

        # Verify request was made with correct parameters
        request = respx.calls.last.request
        payload = json.loads(request.content)
        assert payload["method"] == "simulateTransaction"
        assert payload["params"][0] == tx_base64
        assert payload["params"][1]["encoding"] == "base64"
        assert payload["params"][1]["commitment"] == "processed"

    @pytest.mark.asyncio
    @respx.mock
    async def test_simulate_with_error(self, sender):
        """Test transaction simulation with simulation error."""
        # Mock simulation with error
        simulation_result = {
            "value": {
                "err": {"InstructionError": [0, "InvalidAccountData"]},
                "logs": ["Program log: error"],
                "unitsConsumed": 0,
            }
        }

        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": simulation_result}
            )
        )

        result = await sender.simulate("test_transaction")

        # Should still return the result, not raise exception
        assert result == simulation_result

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_success(self, sender):
        """Test successful transaction send."""
        signature = "test_signature_12345"

        # Mock successful send response
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": signature}
            )
        )

        tx_base64 = "test_transaction_base64"
        result = await sender.send(tx_base64, skip_preflight=True, max_retries=5)

        assert result == signature

        # Verify request was made with correct parameters
        request = respx.calls.last.request
        payload = json.loads(request.content)
        assert payload["method"] == "sendTransaction"
        assert payload["params"][0] == tx_base64
        assert payload["params"][1]["encoding"] == "base64"
        assert payload["params"][1]["skipPreflight"] is True
        assert payload["params"][1]["maxRetries"] == 5

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_with_defaults(self, sender):
        """Test transaction send with default parameters."""
        signature = "test_signature_67890"

        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": signature}
            )
        )

        result = await sender.send("test_transaction")

        assert result == signature

        # Verify default parameters
        request = respx.calls.last.request
        payload = json.loads(request.content)
        assert payload["params"][1]["skipPreflight"] is False
        assert payload["params"][1]["maxRetries"] == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_confirm_signature_success(self, sender):
        """Test successful signature confirmation."""
        signature = "test_signature_confirm"

        # Mock successful confirmation response
        status_result = {
            "value": [
                {
                    "slot": 123456,
                    "confirmations": 10,
                    "err": None,
                    "confirmationStatus": "confirmed",
                }
            ]
        }

        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": status_result}
            )
        )

        result = await sender.confirm_signature(
            signature, commitment="confirmed", timeout=5.0
        )

        expected_status = status_result["value"][0]
        assert result == expected_status

        # Verify request was made with correct parameters
        request = respx.calls.last.request
        payload = json.loads(request.content)
        assert payload["method"] == "getSignatureStatuses"
        assert payload["params"][0] == [signature]

    @pytest.mark.asyncio
    @respx.mock
    async def test_confirm_signature_failed_transaction(self, sender):
        """Test confirmation of failed transaction."""
        signature = "test_signature_failed"

        # Mock failed transaction response
        status_result = {
            "value": [
                {
                    "slot": 123456,
                    "confirmations": None,
                    "err": {"InstructionError": [0, "InvalidAccountData"]},
                    "confirmationStatus": None,
                }
            ]
        }

        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": status_result}
            )
        )

        with pytest.raises(SolanaRpcError) as exc_info:
            await sender.confirm_signature(signature, timeout=5.0)

        assert "Transaction failed" in str(exc_info.value)

    @pytest.mark.asyncio
    @respx.mock
    async def test_confirm_signature_timeout(self, sender):
        """Test signature confirmation timeout."""
        signature = "test_signature_timeout"

        # Mock response where transaction is not found
        status_result = {"value": [None]}

        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": status_result}
            )
        )

        with pytest.raises(TimeoutError) as exc_info:
            await sender.confirm_signature(signature, timeout=1.0, poll_interval=0.5)

        assert "Transaction confirmation timeout" in str(exc_info.value)
        assert signature in str(exc_info.value)

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_latest_blockhash_success(self, sender):
        """Test getting latest blockhash."""
        blockhash_result = {
            "value": {
                "blockhash": "test_blockhash_12345",
                "lastValidBlockHeight": 123456789,
            }
        }

        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": blockhash_result}
            )
        )

        result = await sender.get_latest_blockhash(commitment="finalized")

        assert result == blockhash_result

        # Verify request parameters
        request = respx.calls.last.request
        payload = json.loads(request.content)
        assert payload["method"] == "getLatestBlockhash"
        assert payload["params"][0]["commitment"] == "finalized"

    @pytest.mark.asyncio
    @respx.mock
    async def test_retry_on_transient_error(self, sender):
        """Test retry behavior on transient errors."""
        signature = "test_signature_retry"

        # First request fails with retryable error, second succeeds
        respx.post("https://api.mainnet-beta.solana.com").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {"code": -32603, "message": "Internal error"},
                    },
                ),
                httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": 2, "result": signature}
                ),
            ]
        )

        result = await sender.send("test_transaction")

        assert result == signature
        # Verify it made 2 requests (first failed, second succeeded)
        assert len(respx.calls) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_retry_on_non_retryable_error(self, sender):
        """Test no retry on non-retryable errors."""
        # Mock non-retryable error (invalid params)
        respx.post("https://api.mainnet-beta.solana.com").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32602, "message": "Invalid params"},
                },
            )
        )

        with pytest.raises(SolanaRpcError) as exc_info:
            await sender.send("test_transaction")

        assert exc_info.value.code == -32602
        # Verify it only made 1 request (no retry)
        assert len(respx.calls) == 1


class TestIntegration:
    """Integration tests for senders."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_full_transaction_flow(self):
        """Test complete transaction flow: simulate -> send -> confirm."""
        sender = RpcSender("https://api.mainnet-beta.solana.com")
        tx_base64 = "test_transaction_base64"
        signature = "test_signature_flow"

        # Mock simulate response
        simulate_response = {
            "value": {
                "err": None,
                "logs": ["Program log: success"],
                "unitsConsumed": 5000,
            }
        }

        # Mock send response
        send_response = signature

        # Mock confirm response
        confirm_response = {
            "value": [
                {
                    "slot": 123456,
                    "confirmations": 10,
                    "err": None,
                    "confirmationStatus": "confirmed",
                }
            ]
        }

        # Set up respx mocks for different methods
        def route_request(request):
            payload = json.loads(request.content)
            method = payload["method"]

            if method == "simulateTransaction":
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": 1, "result": simulate_response}
                )
            elif method == "sendTransaction":
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": 2, "result": send_response}
                )
            elif method == "getSignatureStatuses":
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": 3, "result": confirm_response}
                )
            else:
                return httpx.Response(404, text="Method not found")

        respx.post("https://api.mainnet-beta.solana.com").mock(
            side_effect=route_request
        )

        # Execute full flow
        try:
            # 1. Simulate
            sim_result = await sender.simulate(tx_base64)
            assert sim_result["value"]["err"] is None

            # 2. Send
            tx_sig = await sender.send(tx_base64, skip_preflight=True)
            assert tx_sig == signature

            # 3. Confirm
            status = await sender.confirm_signature(signature, timeout=5.0)
            assert status["confirmationStatus"] == "confirmed"

        finally:
            await sender.client.aclose()
