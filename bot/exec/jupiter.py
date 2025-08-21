"""Jupiter execution engine for live Solana trading."""

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import httpx
import structlog

from ..core.interfaces import ExecutionClient
from ..core.types import TokenId, TokenSnapshot

logger = structlog.get_logger(__name__)


@runtime_checkable
class Signer(Protocol):
    """Protocol for transaction signing."""

    def sign_txn(self, message_bytes: bytes) -> bytes:
        """Sign a transaction message.

        Args:
            message_bytes: Raw transaction message bytes

        Returns:
            Signed transaction bytes
        """
        ...


@runtime_checkable
class Sender(Protocol):
    """Protocol for transaction sending."""

    def send_raw_txn(self, txn_bytes: bytes) -> str:
        """Send a raw transaction.

        Args:
            txn_bytes: Raw transaction bytes

        Returns:
            Transaction signature
        """
        ...


def build_quote_params(
    input_mint: str,
    output_mint: str,
    amount: int,
    slippage_bps: int,
    only_direct_routes: bool = False,
    as_legacy_transaction: bool = False,
) -> dict[str, Any]:
    """Build query parameters for Jupiter quote endpoint.

    Args:
        input_mint: Input token mint address
        output_mint: Output token mint address
        amount: Amount in smallest units (lamports for SOL, token decimals for others)
        slippage_bps: Slippage tolerance in basis points
        only_direct_routes: Whether to only return direct routes
        as_legacy_transaction: Whether to return legacy transaction format

    Returns:
        Dictionary of query parameters
    """
    return {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount),
        "slippageBps": slippage_bps,
        "onlyDirectRoutes": only_direct_routes,
        "asLegacyTransaction": as_legacy_transaction,
    }


class JupiterExecutor(ExecutionClient):
    """Jupiter execution engine for live Solana trading."""

    def __init__(
        self,
        base_url: str,
        rpc_url: str,
        max_slippage_bps: int,
        priority_fee_microlamports: int,
        compute_unit_limit: int,
        jito_tip_lamports: int,
        signer: Signer | None = None,
        sender: Sender | None = None,
        session: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize Jupiter executor.

        Args:
            base_url: Jupiter API base URL
            rpc_url: Solana RPC URL
            max_slippage_bps: Maximum slippage tolerance in basis points
            priority_fee_microlamports: Priority fee in microlamports
            compute_unit_limit: Compute unit limit for transactions
            jito_tip_lamports: Jito tip in lamports
            signer: Optional transaction signer
            sender: Optional transaction sender
            session: Optional HTTP session
        """
        self.base_url = base_url.rstrip("/")
        self.rpc_url = rpc_url.rstrip("/")
        self.max_slippage_bps = max_slippage_bps
        self.priority_fee_microlamports = priority_fee_microlamports
        self.compute_unit_limit = compute_unit_limit
        self.jito_tip_lamports = jito_tip_lamports
        self.signer = signer
        self.sender = sender
        self.session = session

        # Validate configuration
        if signer is None or sender is None:
            logger.warning(
                "Jupiter executor initialized without signer/sender - live trading disabled",
                base_url=base_url,
                rpc_url=rpc_url,
            )

    def _is_live_trading_enabled(self) -> bool:
        """Check if live trading is enabled.

        Returns:
            True if signer and sender are configured
        """
        return self.signer is not None and self.sender is not None

    async def _make_request(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make HTTP request to Jupiter API.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            API response data

        Raises:
            httpx.HTTPError: On HTTP errors
        """
        if self.session is None:
            raise RuntimeError("HTTP session not configured")

        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            response = await self.session.get(url, params=params, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "Jupiter API error",
                endpoint=endpoint,
                status_code=e.response.status_code,
                response_text=e.response.text,
            )
            raise
        except httpx.RequestError as e:
            logger.error("Jupiter API request failed", endpoint=endpoint, error=str(e))
            raise

    async def _get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int | None = None,
    ) -> dict[str, Any]:
        """Get quote from Jupiter.

        Args:
            input_mint: Input token mint address
            output_mint: Output token mint address
            amount: Amount in smallest units
            slippage_bps: Slippage tolerance (uses max_slippage_bps if None)

        Returns:
            Quote response from Jupiter
        """
        if slippage_bps is None:
            slippage_bps = self.max_slippage_bps

        params = build_quote_params(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
            slippage_bps=slippage_bps,
        )

        logger.info(
            "Requesting Jupiter quote",
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
            slippage_bps=slippage_bps,
        )

        return await self._make_request("quote", params)

    async def _build_swap_transaction(
        self,
        quote_response: dict[str, Any],
        user_public_key: str,
    ) -> dict[str, Any]:
        """Build swap transaction from quote.

        Args:
            quote_response: Response from quote endpoint
            user_public_key: User's public key

        Returns:
            Transaction response from Jupiter
        """
        # Extract route from quote response
        route = quote_response.get("routes", [{}])[0]

        swap_request = {
            "route": route,
            "userPublicKey": user_public_key,
            "wrapUnwrapSOL": True,
            "computeUnitPriceMicroLamports": self.priority_fee_microlamports,
            "asLegacyTransaction": False,
        }

        logger.info(
            "Building swap transaction",
            user_public_key=user_public_key,
            priority_fee=self.priority_fee_microlamports,
        )

        return await self._make_request("swap", swap_request)

    async def simulate(self, snap: TokenSnapshot, usd_amount: float) -> dict[str, Any]:
        """Simulate a trade using Jupiter quote.

        Args:
            snap: Token snapshot with market data
            usd_amount: Amount in USD to trade

        Returns:
            Simulation result with route details
        """
        # For simulation, we'll use a mock USDC mint as input
        # In a real implementation, this would be the user's USDC balance
        input_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
        output_mint = snap.token.mint

        # Convert USD amount to USDC amount (6 decimals)
        amount_usdc = int(usd_amount * 1_000_000)

        try:
            quote_response = await self._get_quote(
                input_mint=input_mint,
                output_mint=output_mint,
                amount=amount_usdc,
            )

            # Extract relevant information from quote
            routes = quote_response.get("routes", [])
            if not routes:
                raise ValueError("No routes available for quote")

            best_route = routes[0]  # Jupiter returns routes sorted by best price

            simulation_result = {
                "input_mint": input_mint,
                "output_mint": output_mint,
                "input_amount": amount_usdc,
                "output_amount": best_route.get("outAmount", 0),
                "price_impact_pct": best_route.get("priceImpactPct", 0),
                "market_infos": best_route.get("marketInfos", []),
                "route_plan": best_route.get("routePlan", []),
                "swap_mode": best_route.get("swapMode", "ExactIn"),
                "slippage_bps": self.max_slippage_bps,
                "ts": datetime.now(),
            }

            logger.info(
                "Jupiter simulation completed",
                token_mint=output_mint,
                input_amount=amount_usdc,
                output_amount=simulation_result["output_amount"],
                price_impact=simulation_result["price_impact_pct"],
            )

            return simulation_result

        except Exception as e:
            logger.error(
                "Jupiter simulation failed",
                token_mint=output_mint,
                usd_amount=usd_amount,
                error=str(e),
            )
            raise

    async def buy(self, snap: TokenSnapshot, usd_amount: float) -> dict[str, Any]:
        """Execute a buy trade using Jupiter.

        Args:
            snap: Token snapshot with market data
            usd_amount: Amount in USD to buy

        Returns:
            Trade execution result

        Raises:
            NotImplementedError: If live trading is not enabled
        """
        if not self._is_live_trading_enabled():
            raise NotImplementedError(
                "Live trading is disabled in this build. "
                "Provide signer/sender and enable in config."
            )

        # This would implement the full buy flow:
        # 1. Get quote
        # 2. Build swap transaction
        # 3. Sign transaction
        # 4. Send transaction
        # 5. Wait for confirmation

        raise NotImplementedError(
            "Live trading is disabled in this build. "
            "Provide signer/sender and enable in config."
        )

    async def sell(self, token: TokenId, pct: float) -> dict[str, Any]:
        """Execute a sell trade using Jupiter.

        Args:
            token: Token identifier
            pct: Percentage of position to sell (0-100)

        Returns:
            Trade execution result

        Raises:
            NotImplementedError: If live trading is not enabled
        """
        if not self._is_live_trading_enabled():
            raise NotImplementedError(
                "Live trading is disabled in this build. "
                "Provide signer/sender and enable in config."
            )

        # This would implement the full sell flow:
        # 1. Get current token balance
        # 2. Calculate sell amount based on percentage
        # 3. Get quote for token -> USDC
        # 4. Build swap transaction
        # 5. Sign transaction
        # 6. Send transaction
        # 7. Wait for confirmation

        raise NotImplementedError(
            "Live trading is disabled in this build. "
            "Provide signer/sender and enable in config."
        )

    def get_config_summary(self) -> dict[str, Any]:
        """Get configuration summary.

        Returns:
            Dictionary with configuration details
        """
        return {
            "base_url": self.base_url,
            "rpc_url": self.rpc_url,
            "max_slippage_bps": self.max_slippage_bps,
            "priority_fee_microlamports": self.priority_fee_microlamports,
            "compute_unit_limit": self.compute_unit_limit,
            "jito_tip_lamports": self.jito_tip_lamports,
            "live_trading_enabled": self._is_live_trading_enabled(),
            "signer_configured": self.signer is not None,
            "sender_configured": self.sender is not None,
        }
