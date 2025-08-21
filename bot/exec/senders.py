"""Transaction senders for Solana JSON-RPC operations."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)


def _is_retryable_error(exception) -> bool:
    """Check if an exception is retryable."""
    if isinstance(exception, httpx.TimeoutException):
        return True
    if isinstance(exception, httpx.ConnectError):
        return True
    if isinstance(exception, httpx.NetworkError):
        return True
    if isinstance(exception, SolanaRpcError):
        # Retry on server errors and some client errors
        retryable_codes = {
            -32603,  # Internal error
            -32005,  # Node is unhealthy
            -32004,  # Slot was skipped
            429,  # Too many requests
        }
        return exception.code in retryable_codes
    return False


class TxnSender(Protocol):
    """Protocol for transaction senders."""

    async def simulate(self, tx_base64: str) -> dict:
        """Simulate a transaction and return the result.

        Args:
            tx_base64: Base64-encoded transaction bytes

        Returns:
            Simulation result dictionary
        """
        ...

    async def send(self, tx_base64: str, skip_preflight: bool, max_retries: int) -> str:
        """Send a transaction and return the signature.

        Args:
            tx_base64: Base64-encoded transaction bytes
            skip_preflight: Whether to skip preflight checks
            max_retries: Maximum number of retries

        Returns:
            Transaction signature (transaction ID)
        """
        ...


class SolanaRpcError(Exception):
    """Exception for Solana RPC errors."""

    def __init__(self, code: int, message: str, data: dict | None = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"RPC Error {code}: {message}")


class RpcSender:
    """JSON-RPC sender for Solana transactions."""

    def __init__(
        self,
        rpc_url: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize RpcSender.

        Args:
            rpc_url: Solana RPC endpoint URL
            client: Optional httpx client (will create one if not provided)
            timeout: Request timeout in seconds
        """
        self.rpc_url = rpc_url
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self.timeout = timeout
        self._request_id = 0
        logger.info("RpcSender initialized", rpc_url=rpc_url, timeout=timeout)

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if hasattr(self, "client") and self.client:
            await self.client.aclose()

    def _get_request_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
    )
    async def _make_rpc_request(self, method: str, params: list[Any]) -> dict[str, Any]:
        """Make a JSON-RPC request with retries.

        Args:
            method: RPC method name
            params: Method parameters

        Returns:
            RPC response result

        Raises:
            SolanaRpcError: For RPC-specific errors
            httpx.HTTPError: For HTTP errors
        """
        request_id = self._get_request_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        start_time = time.time()
        try:
            logger.debug(
                "Making RPC request",
                method=method,
                request_id=request_id,
                url=self.rpc_url,
            )

            response = await self.client.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

            duration = time.time() - start_time
            logger.debug(
                "RPC request completed",
                method=method,
                request_id=request_id,
                duration=duration,
                status_code=response.status_code,
            )

            data = response.json()

            # Check for JSON-RPC error
            if "error" in data:
                error = data["error"]
                raise SolanaRpcError(
                    code=error.get("code", -1),
                    message=error.get("message", "Unknown RPC error"),
                    data=error.get("data"),
                )

            return data.get("result")

        except httpx.HTTPError as e:
            duration = time.time() - start_time
            logger.error(
                "RPC request failed",
                method=method,
                request_id=request_id,
                duration=duration,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                "RPC request failed with unexpected error",
                method=method,
                request_id=request_id,
                duration=duration,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    async def simulate(self, tx_base64: str) -> dict:
        """Simulate a transaction.

        Args:
            tx_base64: Base64-encoded transaction bytes

        Returns:
            Simulation result dictionary
        """
        try:
            logger.info("Simulating transaction", tx_length=len(tx_base64))

            params = [
                tx_base64,
                {
                    "encoding": "base64",
                    "commitment": "processed",
                    "sigVerify": True,
                    "replaceRecentBlockhash": True,
                },
            ]

            result = await self._make_rpc_request("simulateTransaction", params)

            # Check simulation result
            if (
                result
                and "err" in result["value"]
                and result["value"]["err"] is not None
            ):
                error_info = result["value"]["err"]
                logger.warning(
                    "Transaction simulation failed",
                    error=error_info,
                    logs=result["value"].get("logs", []),
                )
            else:
                logger.info(
                    "Transaction simulation successful",
                    compute_units=result["value"].get("unitsConsumed"),
                )

            return result

        except Exception as e:
            logger.error(
                "Transaction simulation failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    async def send(
        self, tx_base64: str, skip_preflight: bool = False, max_retries: int = 3
    ) -> str:
        """Send a transaction.

        Args:
            tx_base64: Base64-encoded transaction bytes
            skip_preflight: Whether to skip preflight checks
            max_retries: Maximum number of retries

        Returns:
            Transaction signature (transaction ID)
        """
        try:
            logger.info(
                "Sending transaction",
                tx_length=len(tx_base64),
                skip_preflight=skip_preflight,
                max_retries=max_retries,
            )

            params = [
                tx_base64,
                {
                    "encoding": "base64",
                    "skipPreflight": skip_preflight,
                    "maxRetries": max_retries,
                    "preflightCommitment": "processed",
                },
            ]

            signature = await self._make_rpc_request("sendTransaction", params)

            logger.info("Transaction sent successfully", signature=signature)
            return signature

        except Exception as e:
            logger.error(
                "Transaction send failed", error=str(e), error_type=type(e).__name__
            )
            raise

    async def confirm_signature(
        self,
        signature: str,
        commitment: str = "confirmed",
        timeout: float = 60.0,
        poll_interval: float = 2.0,
    ) -> dict[str, Any]:
        """Confirm a transaction signature.

        Args:
            signature: Transaction signature to confirm
            commitment: Commitment level for confirmation
            timeout: Maximum time to wait for confirmation
            poll_interval: Time between status checks

        Returns:
            Transaction status information

        Raises:
            TimeoutError: If confirmation times out
            SolanaRpcError: If transaction failed
        """
        start_time = datetime.now(timezone.utc)
        end_time = start_time.timestamp() + timeout

        logger.info(
            "Confirming transaction signature",
            signature=signature,
            commitment=commitment,
            timeout=timeout,
        )

        while datetime.now(timezone.utc).timestamp() < end_time:
            try:
                params = [[signature], {"searchTransactionHistory": True}]

                result = await self._make_rpc_request("getSignatureStatuses", params)

                if result and "value" in result and result["value"]:
                    status_info = result["value"][0]

                    if status_info is None:
                        # Transaction not found yet, continue polling
                        logger.debug(
                            "Transaction not found, continuing to poll",
                            signature=signature,
                        )
                    elif status_info.get("err") is not None:
                        # Transaction failed
                        error = status_info["err"]
                        logger.error(
                            "Transaction failed", signature=signature, error=error
                        )
                        raise SolanaRpcError(-1, f"Transaction failed: {error}")
                    elif (
                        status_info.get("confirmationStatus") == commitment
                        or commitment == "processed"
                    ):
                        # Transaction confirmed
                        logger.info(
                            "Transaction confirmed",
                            signature=signature,
                            confirmation_status=status_info.get("confirmationStatus"),
                            slot=status_info.get("slot"),
                        )
                        return status_info

                # Wait before next poll
                await asyncio.sleep(poll_interval)

            except SolanaRpcError:
                raise
            except Exception as e:
                logger.warning(
                    "Error checking signature status",
                    signature=signature,
                    error=str(e),
                )
                await asyncio.sleep(poll_interval)

        # Timeout reached
        duration = datetime.now(timezone.utc).timestamp() - start_time.timestamp()
        logger.error(
            "Transaction confirmation timeout",
            signature=signature,
            duration=duration,
            timeout=timeout,
        )
        raise TimeoutError(
            f"Transaction confirmation timeout after {timeout}s: {signature}"
        )

    async def get_latest_blockhash(
        self, commitment: str = "finalized"
    ) -> dict[str, Any]:
        """Get the latest blockhash.

        Args:
            commitment: Commitment level

        Returns:
            Latest blockhash information
        """
        try:
            params = [{"commitment": commitment}]
            result = await self._make_rpc_request("getLatestBlockhash", params)

            logger.debug(
                "Retrieved latest blockhash",
                blockhash=result["value"]["blockhash"][:8]
                + "...",  # Truncate for logging
                last_valid_block_height=result["value"]["lastValidBlockHeight"],
            )

            return result

        except Exception as e:
            logger.error("Failed to get latest blockhash", error=str(e))
            raise
