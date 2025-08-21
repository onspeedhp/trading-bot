"""Jupiter execution engine for live Solana trading."""

import base64
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import httpx
import structlog

from ..core.interfaces import ExecutionClient
from ..core.types import TokenId, TokenSnapshot

logger = structlog.get_logger(__name__)


@runtime_checkable
class TxnSigner(Protocol):
    """Protocol for transaction signing."""

    def pubkey_base58(self) -> str:
        """Get the public key in base58 format."""
        ...

    def sign_transaction(self, txn_bytes: bytes) -> bytes:
        """Sign a transaction and return fully signed raw bytes.

        Args:
            txn_bytes: Raw transaction bytes to sign

        Returns:
            Fully signed transaction bytes ready for RPC submission
        """
        ...


@runtime_checkable
class TxnSender(Protocol):
    """Protocol for transaction sending."""

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


def usd_to_token_amount(
    usd_amount: float, token_price_usd: float, token_decimals: int = 9
) -> int:
    """Convert USD amount to token amount in smallest units.

    Args:
        usd_amount: Amount in USD
        token_price_usd: Token price in USD
        token_decimals: Token decimal places (default 9 for most SPL tokens)

    Returns:
        Token amount in smallest units (e.g., lamports for SOL)
    """
    if token_price_usd <= 0:
        raise ValueError(f"Invalid token price: {token_price_usd}")

    token_amount = usd_amount / token_price_usd
    return int(token_amount * (10**token_decimals))


def token_amount_to_usd(
    token_amount: int, token_price_usd: float, token_decimals: int = 9
) -> float:
    """Convert token amount to USD value.

    Args:
        token_amount: Token amount in smallest units
        token_price_usd: Token price in USD
        token_decimals: Token decimal places (default 9 for most SPL tokens)

    Returns:
        USD value of the token amount
    """
    if token_price_usd <= 0:
        raise ValueError(f"Invalid token price: {token_price_usd}")

    token_units = token_amount / (10**token_decimals)
    return token_units * token_price_usd


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
        signer: TxnSigner | None = None,
        sender: TxnSender | None = None,
        session: httpx.AsyncClient | None = None,
        enable_preflight: bool = True,
        tip_account_b58: str | None = None,
    ) -> None:
        """Initialize Jupiter executor.

        Args:
            base_url: Jupiter API base URL
            rpc_url: Solana RPC URL
            max_slippage_bps: Maximum slippage tolerance in basis points
            priority_fee_microlamports: Priority fee in microlamports
            compute_unit_limit: Compute unit limit for transactions
            jito_tip_lamports: Jito tip in lamports
            signer: Transaction signer
            sender: Transaction sender
            session: Optional HTTP session
            enable_preflight: Whether to enable preflight simulation
        """
        self.base_url = base_url.rstrip("/")
        self.rpc_url = rpc_url.rstrip("/")
        self.max_slippage_bps = max_slippage_bps
        self.priority_fee_microlamports = priority_fee_microlamports
        self.compute_unit_limit = compute_unit_limit
        self.jito_tip_lamports = jito_tip_lamports
        self.tip_account_b58 = tip_account_b58
        self.signer = signer
        self.sender = sender
        self.session = session
        self.enable_preflight = enable_preflight

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

    def _should_add_tip_instruction(self) -> bool:
        """Check if tip instruction should be added.

        Returns:
            True if jito tip is configured and tip account is provided
        """
        return (
            self.jito_tip_lamports > 0
            and self.tip_account_b58 is not None
            and self.tip_account_b58.strip() != ""
        )

    def _add_tip_instruction(self, tx_bytes: bytes) -> bytes:
        """Add Jito tip instruction to transaction.

        Args:
            tx_bytes: Raw transaction bytes

        Returns:
            Transaction bytes with tip instruction added

        Note:
            This is a placeholder implementation. In a real implementation,
            you would decode the transaction, add the tip instruction,
            and re-encode it. For now, we just log the intention.
        """
        if not self._should_add_tip_instruction():
            return tx_bytes

        logger.info(
            "Adding Jito tip instruction",
            tip_lamports=self.jito_tip_lamports,
            tip_account=self.tip_account_b58,
            tx_length=len(tx_bytes),
        )

        # TODO: Implement actual tip instruction addition
        # This would involve:
        # 1. Decoding the transaction using solders
        # 2. Adding a tip instruction to the transaction
        # 3. Re-encoding the transaction
        # 4. For now, we just return the original transaction

        # TODO: Future enhancement - implement JitoBlockEngineSender
        # This would provide a cleaner interface for MEV bundle submission
        # and tip instruction handling

        return tx_bytes

    async def _make_request(
        self, endpoint: str, params: dict[str, Any] | None = None, method: str = "GET"
    ) -> dict[str, Any]:
        """Make HTTP request to Jupiter API.

        Args:
            endpoint: API endpoint path
            params: Query parameters or request body
            method: HTTP method (GET or POST)

        Returns:
            API response data

        Raises:
            httpx.HTTPError: On HTTP errors
        """
        if self.session is None:
            raise RuntimeError("HTTP session not configured")

        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            if method.upper() == "GET":
                response = await self.session.get(url, params=params, timeout=30.0)
            else:
                response = await self.session.post(url, json=params, timeout=30.0)

            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "Jupiter API error",
                endpoint=endpoint,
                method=method,
                status_code=e.response.status_code,
                response_text=e.response.text,
            )
            raise
        except httpx.RequestError as e:
            logger.error(
                "Jupiter API request failed",
                endpoint=endpoint,
                method=method,
                error=str(e),
            )
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
        priority_fee_micro: int | None = None,
        compute_unit_limit: int | None = None,
        jito_tip_lamports: int | None = None,
    ) -> dict[str, Any]:
        """Build swap transaction from quote.

        Args:
            quote_response: Response from quote endpoint
            user_public_key: User's public key
            priority_fee_micro: Override for priority fee (microlamports)
            compute_unit_limit: Override for compute unit limit
            jito_tip_lamports: Override for Jito tip (lamports)

        Returns:
            Transaction response from Jupiter
        """
        # Extract route from quote response
        routes = quote_response.get("routes", [])
        if not routes:
            raise ValueError("No routes available in quote response")

        route = routes[0]  # Use best route

        # Build base swap request
        swap_request = {
            "route": route,
            "userPublicKey": user_public_key,
            "wrapUnwrapSOL": True,
            "asLegacyTransaction": False,
        }

        # Add priority fee if specified
        priority_fee = (
            priority_fee_micro
            if priority_fee_micro is not None
            else self.priority_fee_microlamports
        )
        if priority_fee > 0:
            swap_request["computeUnitPriceMicroLamports"] = priority_fee

        # Add compute unit limit if specified
        compute_units = (
            compute_unit_limit
            if compute_unit_limit is not None
            else self.compute_unit_limit
        )
        if compute_units > 0:
            swap_request["computeUnitLimit"] = compute_units

        # Add Jito tip if specified
        jito_tip = (
            jito_tip_lamports
            if jito_tip_lamports is not None
            else self.jito_tip_lamports
        )
        if jito_tip > 0:
            swap_request["prioritizationFeeLamports"] = jito_tip

        logger.info(
            "Building swap transaction",
            user_public_key=user_public_key,
            priority_fee=priority_fee,
            compute_units=compute_units,
            jito_tip=jito_tip,
            route_id=route.get("id", "unknown"),
        )

        return await self._make_request("swap", swap_request, method="POST")

    async def _execute_trade(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int | None = None,
        is_buy: bool = True,
        priority_fee_micro: int | None = None,
        compute_unit_limit: int | None = None,
        jito_tip_lamports: int | None = None,
    ) -> dict[str, Any]:
        """Execute a trade (buy or sell) using Jupiter.

        Args:
            input_mint: Input token mint address
            output_mint: Output token mint address
            amount: Amount in smallest units
            slippage_bps: Slippage tolerance override
            is_buy: Whether this is a buy operation (for logging)
            priority_fee_micro: Override for priority fee (microlamports)
            compute_unit_limit: Override for compute unit limit
            jito_tip_lamports: Override for Jito tip (lamports)

        Returns:
            Trade execution result
        """
        if not self._is_live_trading_enabled():
            raise NotImplementedError(
                "Live trading is disabled. Provide signer and sender in constructor."
            )

        operation = "buy" if is_buy else "sell"
        logger.info(
            f"Executing Jupiter {operation}",
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
            slippage_bps=slippage_bps or self.max_slippage_bps,
        )

        # Step 1: Get quote
        quote_response = await self._get_quote(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
            slippage_bps=slippage_bps,
        )

        routes = quote_response.get("routes", [])
        if not routes:
            raise ValueError("No routes available for quote")

        best_route = routes[0]
        quote_id = quote_response.get("quoteId", "unknown")

        logger.info(
            f"Jupiter {operation} quote received",
            quote_id=quote_id,
            input_amount=best_route.get("inAmount"),
            output_amount=best_route.get("outAmount"),
            price_impact=best_route.get("priceImpactPct"),
            route_plan_length=len(best_route.get("routePlan", [])),
        )

        # Step 2: Build swap transaction
        user_public_key = self.signer.pubkey_base58()
        swap_response = await self._build_swap_transaction(
            quote_response,
            user_public_key,
            priority_fee_micro=priority_fee_micro,
            compute_unit_limit=compute_unit_limit,
            jito_tip_lamports=jito_tip_lamports,
        )

        # Extract serialized transaction
        serialized_tx = swap_response.get("swapTransaction")
        if not serialized_tx:
            raise ValueError("No swap transaction in response")

        logger.info(
            f"Jupiter {operation} transaction built",
            quote_id=quote_id,
            tx_length=len(serialized_tx),
        )

        # Step 3: Add tip instruction (if configured)
        tx_bytes = base64.b64decode(serialized_tx)
        tx_bytes = self._add_tip_instruction(tx_bytes)

        # Step 4: Sign transaction
        signed_tx_bytes = self.signer.sign_transaction(tx_bytes)
        signed_tx_base64 = base64.b64encode(signed_tx_bytes).decode("utf-8")

        logger.info(
            f"Jupiter {operation} transaction signed",
            quote_id=quote_id,
            signed_tx_length=len(signed_tx_bytes),
        )

        # Step 5: Simulate (optional)
        if self.enable_preflight:
            try:
                simulation_result = await self.sender.simulate(signed_tx_base64)
                logger.info(
                    f"Jupiter {operation} simulation successful",
                    quote_id=quote_id,
                    compute_units=simulation_result.get("value", {}).get(
                        "unitsConsumed"
                    ),
                )
            except Exception as e:
                logger.warning(
                    f"Jupiter {operation} simulation failed",
                    quote_id=quote_id,
                    error=str(e),
                )
                # Continue with execution even if simulation fails

        # Step 6: Send transaction
        signature = await self.sender.send(
            signed_tx_base64,
            skip_preflight=not self.enable_preflight,
            max_retries=3,
        )

        logger.info(
            f"Jupiter {operation} transaction sent",
            quote_id=quote_id,
            signature=signature,
        )

        # Step 6: Return result
        result = {
            "sig": signature,
            "route": best_route,
            "price_est": best_route.get("outAmount", 0),
            "ts": datetime.now(UTC),
            "quote_id": quote_id,
            "operation": operation,
            "input_mint": input_mint,
            "output_mint": output_mint,
            "input_amount": amount,
            "output_amount": best_route.get("outAmount", 0),
            "price_impact_pct": best_route.get("priceImpactPct", 0),
            "slippage_bps": slippage_bps or self.max_slippage_bps,
        }

        return result

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
                "ts": datetime.now(UTC),
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

    async def buy(
        self,
        snap: TokenSnapshot,
        usd_amount: float,
        priority_fee_micro: int | None = None,
        compute_unit_limit: int | None = None,
        jito_tip_lamports: int | None = None,
    ) -> dict[str, Any]:
        """Execute a buy trade using Jupiter.

        Args:
            snap: Token snapshot with market data
            usd_amount: Amount in USD to buy
            priority_fee_micro: Override for priority fee (microlamports)
            compute_unit_limit: Override for compute unit limit
            jito_tip_lamports: Override for Jito tip (lamports)

        Returns:
            Trade execution result

        Raises:
            NotImplementedError: If live trading is not enabled
        """
        # USDC mint address
        input_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        output_mint = snap.token.mint

        # Convert USD amount to USDC amount (6 decimals)
        amount_usdc = int(usd_amount * 1_000_000)

        return await self._execute_trade(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount_usdc,
            is_buy=True,
            priority_fee_micro=priority_fee_micro,
            compute_unit_limit=compute_unit_limit,
            jito_tip_lamports=jito_tip_lamports,
        )

    async def sell(
        self,
        token: TokenId,
        pct: float,
        priority_fee_micro: int | None = None,
        compute_unit_limit: int | None = None,
        jito_tip_lamports: int | None = None,
    ) -> dict[str, Any]:
        """Execute a sell trade using Jupiter.

        Args:
            token: Token identifier
            pct: Percentage of position to sell (0-100)
            priority_fee_micro: Override for priority fee (microlamports)
            compute_unit_limit: Override for compute unit limit
            jito_tip_lamports: Override for Jito tip (lamports)

        Returns:
            Trade execution result

        Raises:
            NotImplementedError: If live trading is not enabled
        """
        # For now, we'll need a way to get the current token balance
        # This is a simplified implementation - in practice you'd need to:
        # 1. Get current token balance from the wallet
        # 2. Calculate sell amount based on percentage
        # 3. Execute the trade

        # For this implementation, we'll assume we have a fixed amount to sell
        # In a real implementation, you'd query the wallet for the actual balance

        # USDC mint address for output
        output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        input_mint = token.mint

        # For demonstration, use a fixed amount (1 token)
        # In practice, this would be the actual wallet balance * pct / 100
        token_decimals = 9  # Default for most SPL tokens
        amount_tokens = int(1 * (10**token_decimals) * pct / 100)

        return await self._execute_trade(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount_tokens,
            is_buy=False,
            priority_fee_micro=priority_fee_micro,
            compute_unit_limit=compute_unit_limit,
            jito_tip_lamports=jito_tip_lamports,
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
            "enable_preflight": self.enable_preflight,
        }
