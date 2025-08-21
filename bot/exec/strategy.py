"""Trading strategy implementation with position lifecycle management."""

from datetime import datetime, timedelta
from typing import Any

import structlog

from ..core.interfaces import ExecutionClient, Persistence, RiskManager
from ..core.types import TokenSnapshot

logger = structlog.get_logger(__name__)


class PositionState:
    """Represents the current state of a trading position."""

    def __init__(
        self,
        token_mint: str,
        entry_price_usd: float,
        quantity: float,
        entry_time: datetime,
        high_water_mark: float = 0.0,
        trailing_stop_price: float = 0.0,
        partial_sells: list[dict[str, Any]] = None,
    ) -> None:
        """Initialize position state.

        Args:
            token_mint: Token mint address
            entry_price_usd: Entry price in USD
            quantity: Position quantity
            entry_time: Entry timestamp
            high_water_mark: Highest price reached (for trailing stop)
            trailing_stop_price: Current trailing stop price
            partial_sells: List of partial sell transactions
        """
        self.token_mint = token_mint
        self.entry_price_usd = entry_price_usd
        self.quantity = quantity
        self.entry_time = entry_time
        self.high_water_mark = high_water_mark
        self.trailing_stop_price = trailing_stop_price
        self.partial_sells = partial_sells or []

    def to_dict(self) -> dict[str, Any]:
        """Convert position state to dictionary for storage."""
        return {
            "token_mint": self.token_mint,
            "entry_price_usd": self.entry_price_usd,
            "quantity": self.quantity,
            "entry_time": self.entry_time.isoformat(),
            "high_water_mark": self.high_water_mark,
            "trailing_stop_price": self.trailing_stop_price,
            "partial_sells": self.partial_sells,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PositionState":
        """Create position state from dictionary."""
        return cls(
            token_mint=data["token_mint"],
            entry_price_usd=data["entry_price_usd"],
            quantity=data["quantity"],
            entry_time=datetime.fromisoformat(data["entry_time"]),
            high_water_mark=data.get("high_water_mark", 0.0),
            trailing_stop_price=data.get("trailing_stop_price", 0.0),
            partial_sells=data.get("partial_sells", []),
        )


class TradingStrategy:
    """Trading strategy with position lifecycle management."""

    def __init__(
        self,
        exec_client: ExecutionClient,
        risk_manager: RiskManager,
        storage: Persistence,
        take_profit_levels: list[tuple[float, float]] = None,  # (multiplier, fraction)
        trailing_stop_pct: float = 0.15,  # 15% trailing stop
        max_hold_time_hours: float = 24.0,  # 24 hours max hold
        partial_sell_fraction: float = 0.25,  # Sell 25% at each profit level
    ) -> None:
        """Initialize trading strategy.

        Args:
            exec_client: Execution client for trades
            risk_manager: Risk manager for position sizing
            storage: Storage for position state
            take_profit_levels: List of (multiplier, fraction) for profit taking
            trailing_stop_pct: Trailing stop percentage
            max_hold_time_hours: Maximum position hold time in hours
            partial_sell_fraction: Fraction to sell at each profit level
        """
        self.exec_client = exec_client
        self.risk_manager = risk_manager
        self.storage = storage

        # Default take profit levels: (multiplier, fraction)
        self.take_profit_levels = take_profit_levels or [
            (2.0, 0.25),  # Sell 25% at 2x
            (3.0, 0.25),  # Sell 25% at 3x
        ]

        self.trailing_stop_pct = trailing_stop_pct
        self.max_hold_time_hours = max_hold_time_hours
        self.partial_sell_fraction = partial_sell_fraction

        # Active positions cache
        self._positions: dict[str, PositionState] = {}

        logger.info(
            "Trading strategy initialized",
            take_profit_levels=self.take_profit_levels,
            trailing_stop_pct=self.trailing_stop_pct,
            max_hold_time_hours=self.max_hold_time_hours,
        )

    async def on_signal(self, snapshot: TokenSnapshot) -> dict[str, Any] | None:
        """Process a trading signal.

        Args:
            snapshot: Token snapshot with current market data

        Returns:
            Trade result if position opened, None otherwise
        """
        token_mint = snapshot.token.mint

        # Check if we already have a position
        if token_mint in self._positions:
            logger.debug("Already have position", token_mint=token_mint)
            return None

        # Check risk management
        can_buy, reasons = self.risk_manager.allow_buy(snapshot)
        if not can_buy:
            logger.debug(
                "Risk manager rejected signal",
                token_mint=token_mint,
                reasons=reasons,
            )
            return None

        # Calculate position size
        position_size_usd = self.risk_manager.size_usd(snapshot)
        if position_size_usd <= 0:
            logger.debug("Zero position size", token_mint=token_mint)
            return None

        logger.info(
            "Processing trading signal",
            token_mint=token_mint,
            price_usd=snapshot.price_usd,
            position_size_usd=position_size_usd,
        )

        try:
            # Execute trade
            trade_result = await self.exec_client.buy(snapshot, position_size_usd)

            # Create position state
            position = PositionState(
                token_mint=token_mint,
                entry_price_usd=trade_result["price_exec"],
                quantity=trade_result["qty_base"],
                entry_time=datetime.now(),
                high_water_mark=trade_result["price_exec"],
                trailing_stop_price=trade_result["price_exec"]
                * (1 - self.trailing_stop_pct),
            )

            # Store position
            self._positions[token_mint] = position
            await self._save_position_state(position)

            # Update risk manager
            self.risk_manager.after_fill(0.0)

            logger.info(
                "Position opened successfully",
                token_mint=token_mint,
                entry_price=trade_result["price_exec"],
                quantity=trade_result["qty_base"],
                cost_usd=trade_result["cost_usd"],
            )

            return trade_result

        except Exception as e:
            logger.error(
                "Failed to execute signal",
                token_mint=token_mint,
                error=str(e),
            )
            return None

    async def take_profits(self, snapshot: TokenSnapshot) -> dict[str, Any] | None:
        """Check and execute take profit orders.

        Args:
            snapshot: Current token snapshot

        Returns:
            Sell result if profit taken, None otherwise
        """
        token_mint = snapshot.token.mint
        position = self._positions.get(token_mint)

        if not position:
            return None

        current_price = snapshot.price_usd
        price_multiplier = current_price / position.entry_price_usd

        # Update high water mark first
        if current_price > position.high_water_mark:
            position.high_water_mark = current_price

        # Check each take profit level
        for multiplier, fraction in self.take_profit_levels:
            if price_multiplier >= multiplier:
                # Check if we already sold at this level
                already_sold = any(
                    sell.get("level") == multiplier for sell in position.partial_sells
                )

                if not already_sold:
                    return await self._execute_partial_sell(
                        position, snapshot, fraction, multiplier
                    )

        return None

    async def trailing_stop(self, snapshot: TokenSnapshot) -> dict[str, Any] | None:
        """Check and execute trailing stop orders.

        Args:
            snapshot: Current token snapshot

        Returns:
            Sell result if stop triggered, None otherwise
        """
        token_mint = snapshot.token.mint
        position = self._positions.get(token_mint)

        if not position:
            return None

        current_price = snapshot.price_usd

        # Update high water mark
        if current_price > position.high_water_mark:
            position.high_water_mark = current_price
            new_stop_price = current_price * (1 - self.trailing_stop_pct)

            # Only move stop up, never down
            if new_stop_price > position.trailing_stop_price:
                position.trailing_stop_price = new_stop_price
                await self._save_position_state(position)

                logger.debug(
                    "Updated trailing stop",
                    token_mint=token_mint,
                    high_water_mark=position.high_water_mark,
                    trailing_stop=position.trailing_stop_price,
                )

        # Check if stop is triggered
        if current_price <= position.trailing_stop_price:
            logger.info(
                "Trailing stop triggered",
                token_mint=token_mint,
                current_price=current_price,
                stop_price=position.trailing_stop_price,
            )

            return await self._execute_full_sell(position, snapshot, "trailing_stop")

        return None

    async def time_stop(self, snapshot: TokenSnapshot) -> dict[str, Any] | None:
        """Check and execute time-based exits.

        Args:
            snapshot: Current token snapshot

        Returns:
            Sell result if time stop triggered, None otherwise
        """
        token_mint = snapshot.token.mint
        position = self._positions.get(token_mint)

        if not position:
            return None

        current_time = datetime.now()
        hold_time = current_time - position.entry_time
        max_hold_time = timedelta(hours=self.max_hold_time_hours)

        if hold_time >= max_hold_time:
            logger.info(
                "Time stop triggered",
                token_mint=token_mint,
                hold_time_hours=hold_time.total_seconds() / 3600,
                max_hold_time_hours=self.max_hold_time_hours,
            )

            return await self._execute_full_sell(position, snapshot, "time_stop")

        return None

    async def _execute_partial_sell(
        self,
        position: PositionState,
        snapshot: TokenSnapshot,
        fraction: float,
        level: float,
    ) -> dict[str, Any]:
        """Execute a partial sell order.

        Args:
            position: Position to sell from
            snapshot: Current market snapshot
            fraction: Fraction of position to sell
            level: Take profit level (for tracking)

        Returns:
            Sell result
        """
        sell_quantity = position.quantity * fraction

        logger.info(
            "Executing partial sell",
            token_mint=position.token_mint,
            quantity=sell_quantity,
            fraction=fraction,
            level=level,
        )

        # Execute sell
        sell_result = await self.exec_client.sell(
            snapshot.token,
            sell_quantity / position.quantity,  # Convert to percentage
        )

        # Update position
        position.quantity -= sell_quantity
        position.partial_sells.append(
            {
                "timestamp": datetime.now().isoformat(),
                "quantity": sell_quantity,
                "price": sell_result["price_exec"],
                "level": level,
                "reason": "take_profit",
            }
        )

        # Save updated position
        await self._save_position_state(position)

        # If position is fully closed, remove from active positions
        if position.quantity <= 0:
            del self._positions[position.token_mint]
            logger.info(
                "Position fully closed via partial sells",
                token_mint=position.token_mint,
            )

        return sell_result

    async def _execute_full_sell(
        self, position: PositionState, snapshot: TokenSnapshot, reason: str
    ) -> dict[str, Any]:
        """Execute a full position sell.

        Args:
            position: Position to sell
            snapshot: Current market snapshot
            reason: Reason for selling

        Returns:
            Sell result
        """
        logger.info(
            "Executing full sell",
            token_mint=position.token_mint,
            quantity=position.quantity,
            reason=reason,
        )

        # Execute sell
        sell_result = await self.exec_client.sell(
            snapshot.token,
            1.0,  # Sell 100%
        )

        # Record final sell
        position.partial_sells.append(
            {
                "timestamp": datetime.now().isoformat(),
                "quantity": position.quantity,
                "price": sell_result["price_exec"],
                "reason": reason,
            }
        )

        # Remove from active positions
        del self._positions[position.token_mint]

        # Save final position state
        await self._save_position_state(position)

        return sell_result

    async def _save_position_state(self, position: PositionState) -> None:
        """Save position state to storage."""
        try:
            await self.storage.save_state_json(
                f"position_{position.token_mint}", position.to_dict()
            )
        except Exception as e:
            logger.error(
                "Failed to save position state",
                token_mint=position.token_mint,
                error=str(e),
            )

    async def load_positions(self) -> None:
        """Load active positions from storage."""
        try:
            # Load all position states from storage
            # This is a simplified implementation - in practice you'd want
            # to scan for position_* keys or maintain a position index
            logger.info("Loading positions from storage")

            # For now, we'll assume positions are loaded elsewhere
            # In a real implementation, you'd scan storage for position keys
            # and reconstruct PositionState objects

        except Exception as e:
            logger.error("Failed to load positions", error=str(e))

    def get_active_positions(self) -> dict[str, PositionState]:
        """Get all active positions."""
        return self._positions.copy()

    def get_position(self, token_mint: str) -> PositionState | None:
        """Get a specific position."""
        return self._positions.get(token_mint)


# Pure helper functions for price calculations


def calculate_pnl_percentage(entry_price: float, current_price: float) -> float:
    """Calculate percentage P&L.

    Args:
        entry_price: Entry price
        current_price: Current price

    Returns:
        P&L percentage (positive for profit, negative for loss)
    """
    if entry_price == 0:
        return 0.0
    return ((current_price - entry_price) / entry_price) * 100.0


def calculate_trailing_stop_price(
    high_water_mark: float, stop_percentage: float
) -> float:
    """Calculate trailing stop price.

    Args:
        high_water_mark: Highest price reached
        stop_percentage: Stop percentage (e.g., 0.15 for 15%)

    Returns:
        Trailing stop price
    """
    return high_water_mark * (1 - stop_percentage)


def calculate_position_value(quantity: float, price: float) -> float:
    """Calculate current position value.

    Args:
        quantity: Position quantity
        price: Current price

    Returns:
        Position value in USD
    """
    return quantity * price


def calculate_remaining_hold_time(entry_time: datetime, max_hours: float) -> float:
    """Calculate remaining hold time.

    Args:
        entry_time: Position entry time
        max_hours: Maximum hold time in hours

    Returns:
        Remaining time in hours (negative if exceeded)
    """
    elapsed = datetime.now() - entry_time
    elapsed_hours = elapsed.total_seconds() / 3600
    return max_hours - elapsed_hours


def calculate_take_profit_levels(
    entry_price: float, levels: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Calculate take profit price levels.

    Args:
        entry_price: Entry price
        levels: List of (multiplier, fraction) tuples

    Returns:
        List of (price, fraction) tuples
    """
    return [(entry_price * multiplier, fraction) for multiplier, fraction in levels]
