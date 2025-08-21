"""Paper trading execution engine."""

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import structlog

from ..core.interfaces import ExecutionClient
from ..core.types import TokenId, TokenSnapshot

logger = structlog.get_logger(__name__)


class VirtualPosition:
    """Virtual position for paper trading."""

    def __init__(self, token_mint: str, avg_cost_usd: float, qty_base: float) -> None:
        """Initialize virtual position.

        Args:
            token_mint: Token mint address
            avg_cost_usd: Average cost per token in USD
            qty_base: Quantity of tokens held
        """
        self.token_mint = token_mint
        self.avg_cost_usd = avg_cost_usd
        self.qty_base = qty_base
        self.created_at = time.time()

    def add_position(self, cost_usd: float, qty_base: float) -> None:
        """Add to existing position.

        Args:
            cost_usd: Total cost in USD
            qty_base: Quantity to add
        """
        if qty_base <= 0:
            return

        # Calculate new average cost
        total_cost = self.avg_cost_usd * self.qty_base + cost_usd
        total_qty = self.qty_base + qty_base
        self.avg_cost_usd = total_cost / total_qty
        self.qty_base = total_qty

        logger.info(
            "Added to virtual position",
            token_mint=self.token_mint,
            new_qty=qty_base,
            new_avg_cost=self.avg_cost_usd,
            total_qty=self.qty_base,
        )

    def reduce_position(self, qty_base: float) -> float:
        """Reduce position and return cost basis.

        Args:
            qty_base: Quantity to sell

        Returns:
            Cost basis of sold quantity
        """
        if qty_base <= 0 or qty_base > self.qty_base:
            return 0.0

        cost_basis = self.avg_cost_usd * qty_base
        self.qty_base -= qty_base

        logger.info(
            "Reduced virtual position",
            token_mint=self.token_mint,
            sold_qty=qty_base,
            remaining_qty=self.qty_base,
            cost_basis=cost_basis,
        )

        return cost_basis

    def get_pnl(self, current_price_usd: float) -> float:
        """Calculate unrealized P&L.

        Args:
            current_price_usd: Current token price in USD

        Returns:
            Unrealized P&L in USD
        """
        if self.qty_base <= 0:
            return 0.0

        market_value = self.qty_base * current_price_usd
        cost_basis = self.qty_base * self.avg_cost_usd
        return market_value - cost_basis

    def get_pnl_percentage(self, current_price_usd: float) -> float:
        """Calculate unrealized P&L percentage.

        Args:
            current_price_usd: Current token price in USD

        Returns:
            Unrealized P&L percentage
        """
        if self.qty_base <= 0 or self.avg_cost_usd <= 0:
            return 0.0

        return ((current_price_usd - self.avg_cost_usd) / self.avg_cost_usd) * 100


class PaperExecutor(ExecutionClient):
    """Paper trading execution engine."""

    def __init__(
        self,
        slippage_bps: int = 100,
        fee_bps: int = 50,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        """Initialize paper executor.

        Args:
            slippage_bps: Slippage in basis points (default 100 = 1%)
            fee_bps: Fee in basis points (default 50 = 0.5%)
            now_fn: Optional function to get current timestamp (for testing)
        """
        self.slippage_bps = slippage_bps
        self.fee_bps = fee_bps
        self._now_fn = now_fn or time.time

        # Virtual positions tracking
        self._positions: dict[str, VirtualPosition] = {}
        self._trade_history: list[dict[str, Any]] = []

    def _calculate_execution_price(self, base_price_usd: float, is_buy: bool) -> float:
        """Calculate execution price with slippage.

        Args:
            base_price_usd: Base price in USD
            is_buy: True for buy, False for sell

        Returns:
            Execution price with slippage
        """
        slippage_multiplier = self.slippage_bps / 10000.0

        if is_buy:
            # Buy: pay more due to slippage
            return base_price_usd * (1 + slippage_multiplier)
        else:
            # Sell: receive less due to slippage
            return base_price_usd * (1 - slippage_multiplier)

    def _calculate_fee(self, cost_usd: float) -> float:
        """Calculate trading fee.

        Args:
            cost_usd: Trade cost in USD

        Returns:
            Fee amount in USD
        """
        return cost_usd * (self.fee_bps / 10000.0)

    def _execute_trade(
        self,
        snap: TokenSnapshot,
        usd_amount: float,
        is_buy: bool,
        pct: float | None = None,
    ) -> dict[str, Any]:
        """Execute a trade with slippage and fees.

        Args:
            snap: Token snapshot with market data
            usd_amount: Amount in USD to trade
            is_buy: True for buy, False for sell
            pct: For sells, percentage of position to sell (0-100)

        Returns:
            Trade execution result
        """
        base_price = snap.price_usd
        exec_price = self._calculate_execution_price(base_price, is_buy)

        if is_buy:
            # Buy: calculate quantity from USD amount
            qty_base = usd_amount / exec_price
            cost_usd = usd_amount
        else:
            # Sell: calculate quantity from percentage or USD amount
            token_mint = snap.token.mint
            position = self._positions.get(token_mint)

            if not position or position.qty_base <= 0:
                raise ValueError(f"No position to sell for token {token_mint}")

            if pct is not None:
                # Sell by percentage
                qty_base = position.qty_base * (pct / 100.0)
            else:
                # Sell by USD amount
                qty_base = usd_amount / exec_price

            # Cap by available position
            qty_base = min(qty_base, position.qty_base)
            cost_usd = qty_base * exec_price

        # Calculate fees
        fee_usd = self._calculate_fee(cost_usd)

        # Create execution result
        result = {
            "price_exec": exec_price,
            "qty_base": qty_base,
            "cost_usd": cost_usd,
            "fee_usd": fee_usd,
            "ts": datetime.fromtimestamp(self._now_fn()),
            "token_mint": snap.token.mint,
            "is_buy": is_buy,
            "base_price": base_price,
            "slippage_bps": self.slippage_bps,
        }

        logger.info(
            "Paper trade executed",
            token_mint=snap.token.mint,
            is_buy=is_buy,
            qty_base=qty_base,
            cost_usd=cost_usd,
            fee_usd=fee_usd,
            exec_price=exec_price,
            base_price=base_price,
            slippage_bps=self.slippage_bps,
        )

        return result

    async def simulate(self, snap: TokenSnapshot, usd_amount: float) -> dict[str, Any]:
        """Simulate a trade without executing.

        Args:
            snap: Token snapshot with market data
            usd_amount: Amount in USD to trade

        Returns:
            Simulated trade result
        """
        logger.info(
            "Simulating trade",
            token_mint=snap.token.mint,
            usd_amount=usd_amount,
            base_price=snap.price_usd,
        )

        return self._execute_trade(snap, usd_amount, is_buy=True)

    async def buy(self, snap: TokenSnapshot, usd_amount: float) -> dict[str, Any]:
        """Execute a buy trade and record virtual position.

        Args:
            snap: Token snapshot with market data
            usd_amount: Amount in USD to buy

        Returns:
            Trade execution result
        """
        result = self._execute_trade(snap, usd_amount, is_buy=True)

        # Record virtual position
        token_mint = snap.token.mint
        cost_usd = result["cost_usd"] + result["fee_usd"]  # Include fees in cost basis
        qty_base = result["qty_base"]

        if token_mint not in self._positions:
            # New position
            self._positions[token_mint] = VirtualPosition(
                token_mint=token_mint,
                avg_cost_usd=cost_usd / qty_base,
                qty_base=qty_base,
            )
        else:
            # Add to existing position
            self._positions[token_mint].add_position(cost_usd, qty_base)

        # Record trade
        self._trade_history.append(result)

        logger.info(
            "Buy trade recorded",
            token_mint=token_mint,
            total_positions=len(self._positions),
            position_qty=self._positions[token_mint].qty_base,
        )

        return result

    async def sell(self, token: TokenId, pct: float) -> dict[str, Any]:
        """Execute a sell trade and update virtual position.

        Args:
            token: Token identifier
            pct: Percentage of position to sell (0-100)

        Returns:
            Trade execution result
        """
        token_mint = token.mint
        position = self._positions.get(token_mint)

        if not position or position.qty_base <= 0:
            raise ValueError(f"No position to sell for token {token_mint}")

        # Create mock snapshot for current price (in real implementation, would get from data source)
        # For now, use a placeholder price - this would be improved in production
        mock_snap = TokenSnapshot(
            token=token,
            price_usd=position.avg_cost_usd,  # Use average cost as placeholder
            liq_usd=10000.0,
            vol_5m_usd=1000.0,
            source="paper_exec",
            ts=datetime.fromtimestamp(self._now_fn()),
        )

        # Calculate USD amount for the percentage
        usd_amount = position.qty_base * mock_snap.price_usd * (pct / 100.0)

        result = self._execute_trade(mock_snap, usd_amount, is_buy=False, pct=pct)

        # Update virtual position
        cost_basis = position.reduce_position(result["qty_base"])
        result["cost_basis"] = cost_basis
        result["realized_pnl"] = result["cost_usd"] - cost_basis

        # Remove position if fully sold
        if position.qty_base <= 0:
            del self._positions[token_mint]
            logger.info("Position fully closed", token_mint=token_mint)

        # Record trade
        self._trade_history.append(result)

        logger.info(
            "Sell trade recorded",
            token_mint=token_mint,
            sold_pct=pct,
            realized_pnl=result["realized_pnl"],
            remaining_positions=len(self._positions),
        )

        return result

    def get_position(self, token_mint: str) -> VirtualPosition | None:
        """Get virtual position for a token.

        Args:
            token_mint: Token mint address

        Returns:
            Virtual position or None if not found
        """
        return self._positions.get(token_mint)

    def get_all_positions(self) -> dict[str, VirtualPosition]:
        """Get all virtual positions.

        Returns:
            Dictionary of all positions
        """
        return self._positions.copy()

    def calculate_total_pnl(self, current_prices: dict[str, float]) -> float:
        """Calculate total unrealized P&L across all positions.

        Args:
            current_prices: Dictionary of token_mint -> current_price_usd

        Returns:
            Total unrealized P&L in USD
        """
        total_pnl = 0.0

        for token_mint, position in self._positions.items():
            current_price = current_prices.get(token_mint, position.avg_cost_usd)
            pnl = position.get_pnl(current_price)
            total_pnl += pnl

            logger.debug(
                "Position P&L",
                token_mint=token_mint,
                qty=position.qty_base,
                avg_cost=position.avg_cost_usd,
                current_price=current_price,
                pnl=pnl,
            )

        return total_pnl

    def get_portfolio_summary(self, current_prices: dict[str, float]) -> dict[str, Any]:
        """Get portfolio summary with P&L.

        Args:
            current_prices: Dictionary of token_mint -> current_price_usd

        Returns:
            Portfolio summary
        """
        total_cost_basis = 0.0
        total_market_value = 0.0
        total_pnl = 0.0
        position_details = []

        for token_mint, position in self._positions.items():
            current_price = current_prices.get(token_mint, position.avg_cost_usd)
            cost_basis = position.qty_base * position.avg_cost_usd
            market_value = position.qty_base * current_price
            pnl = position.get_pnl(current_price)

            total_cost_basis += cost_basis
            total_market_value += market_value
            total_pnl += pnl

            position_details.append(
                {
                    "token_mint": token_mint,
                    "qty_base": position.qty_base,
                    "avg_cost_usd": position.avg_cost_usd,
                    "current_price_usd": current_price,
                    "cost_basis_usd": cost_basis,
                    "market_value_usd": market_value,
                    "unrealized_pnl_usd": pnl,
                    "pnl_percentage": position.get_pnl_percentage(current_price),
                }
            )

        return {
            "total_positions": len(self._positions),
            "total_cost_basis_usd": total_cost_basis,
            "total_market_value_usd": total_market_value,
            "total_unrealized_pnl_usd": total_pnl,
            "total_pnl_percentage": (total_pnl / total_cost_basis * 100)
            if total_cost_basis > 0
            else 0.0,
            "positions": position_details,
            "trade_count": len(self._trade_history),
        }

    def get_trade_history(self) -> list[dict[str, Any]]:
        """Get trade history.

        Returns:
            List of trade records
        """
        return self._trade_history.copy()
