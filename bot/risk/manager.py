"""Risk management implementation."""

import time
from collections.abc import Callable
from datetime import datetime

import structlog

from ..core.interfaces import RiskManager
from ..core.types import TokenSnapshot

logger = structlog.get_logger(__name__)


class RiskManagerImpl(RiskManager):
    """Risk manager implementation with in-memory state."""

    def __init__(
        self,
        position_size_usd: float,
        daily_max_loss_usd: float,
        cooldown_seconds: int,
        max_concurrent_positions: int = 10,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        """Initialize risk manager.

        Args:
            position_size_usd: Maximum position size in USD
            daily_max_loss_usd: Maximum daily loss in USD
            cooldown_seconds: Cooldown period between trades on same token
            max_concurrent_positions: Maximum number of concurrent positions
            now_fn: Optional function to get current timestamp (for testing)
        """
        self.position_size_usd = position_size_usd
        self.daily_max_loss_usd = daily_max_loss_usd
        self.cooldown_seconds = cooldown_seconds
        self.max_concurrent_positions = max_concurrent_positions

        # Use provided now function or default to time.time
        self._now_fn = now_fn or time.time

        # In-memory state
        self._daily_pnl = 0.0
        self._daily_start_time = self._get_day_start()
        self._token_cooldowns: dict[str, float] = {}
        self._active_positions: set[str] = set()
        self._position_sizes: dict[str, float] = {}

    def _get_day_start(self) -> float:
        """Get the start of the current day as timestamp."""
        now = datetime.fromtimestamp(self._now_fn())
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start.timestamp()

    def _reset_daily_if_needed(self) -> None:
        """Reset daily tracking if a new day has started."""
        current_day_start = self._get_day_start()
        if current_day_start > self._daily_start_time:
            logger.info(
                "New trading day started, resetting daily P&L",
                previous_pnl=self._daily_pnl,
                new_day_start=datetime.fromtimestamp(current_day_start).date(),
            )
            self._daily_pnl = 0.0
            self._daily_start_time = current_day_start
            # Also reset cooldowns for new day
            self._token_cooldowns.clear()

    @property
    def daily_pnl(self) -> float:
        """Get current daily P&L."""
        self._reset_daily_if_needed()
        return self._daily_pnl

    @property
    def remaining_daily_budget(self) -> float:
        """Get remaining daily loss budget."""
        return self.daily_max_loss_usd + self.daily_pnl

    def size_usd(self, snap: TokenSnapshot) -> float:
        """Calculate position size in USD for a token.

        Args:
            snap: Token snapshot with market data

        Returns:
            Position size in USD, capped by position_size_usd and daily budget
        """
        self._reset_daily_if_needed()

        # Base position size
        size = self.position_size_usd

        # Cap by remaining daily budget
        remaining_budget = self.remaining_daily_budget
        if remaining_budget <= 0:
            logger.warning(
                "Daily loss limit reached, no new positions allowed",
                daily_pnl=self._daily_pnl,
                daily_max_loss=self.daily_max_loss_usd,
            )
            return 0.0

        # Cap position size by remaining budget
        size = min(size, remaining_budget)

        # Additional risk checks based on token characteristics
        if snap.liq_usd < size * 10:  # Require 10x liquidity for position size
            size = min(size, snap.liq_usd / 10)
            logger.info(
                "Reduced position size due to low liquidity",
                token_mint=snap.token.mint,
                original_size=self.position_size_usd,
                adjusted_size=size,
                liquidity=snap.liq_usd,
            )

        return max(0.0, size)

    def allow_buy(self, snap: TokenSnapshot) -> tuple[bool, list[str]]:
        """Check if buying is allowed and return reasons.

        Args:
            snap: Token snapshot with market data

        Returns:
            Tuple of (allowed, list of reasons)
        """
        self._reset_daily_if_needed()

        reasons = []
        allowed = True

        # Check daily loss limit
        if self.remaining_daily_budget <= 0:
            reasons.append("Daily loss limit exceeded")
            allowed = False

        # Check cooldown
        token_mint = snap.token.mint
        current_time = self._now_fn()
        last_trade_time = self._token_cooldowns.get(token_mint, 0)

        if current_time - last_trade_time < self.cooldown_seconds:
            remaining_cooldown = self.cooldown_seconds - (
                current_time - last_trade_time
            )
            reasons.append(f"Token in cooldown ({remaining_cooldown:.1f}s remaining)")
            allowed = False

        # Check concurrent positions limit
        if len(self._active_positions) >= self.max_concurrent_positions:
            reasons.append("Maximum concurrent positions reached")
            allowed = False

        # Check if already have position in this token
        if token_mint in self._active_positions:
            reasons.append("Already have position in this token")
            allowed = False

        # Additional risk checks
        if snap.liq_usd < 1000:  # Minimum liquidity requirement
            reasons.append("Insufficient liquidity")
            allowed = False

        if snap.vol_5m_usd < 100:  # Minimum volume requirement
            reasons.append("Insufficient trading volume")
            allowed = False

        if snap.price_usd <= 0:
            reasons.append("Invalid price")
            allowed = False

        if not allowed:
            logger.info(
                "Buy request denied",
                token_mint=token_mint,
                reasons=reasons,
                daily_pnl=self._daily_pnl,
                active_positions=len(self._active_positions),
            )

        return allowed, reasons

    def after_fill(self, pnl_usd: float) -> None:
        """Update risk state after trade fill.

        Args:
            pnl_usd: P&L from the trade (positive for profit, negative for loss)
        """
        self._reset_daily_if_needed()

        old_pnl = self._daily_pnl
        self._daily_pnl += pnl_usd

        logger.info(
            "Updated daily P&L after trade",
            trade_pnl=pnl_usd,
            old_daily_pnl=old_pnl,
            new_daily_pnl=self._daily_pnl,
            remaining_budget=self.remaining_daily_budget,
        )

    def record_position(self, token_mint: str, size_usd: float) -> None:
        """Record a new position.

        Args:
            token_mint: Token mint address
            size_usd: Position size in USD
        """
        self._active_positions.add(token_mint)
        self._position_sizes[token_mint] = size_usd

        logger.info(
            "Recorded new position",
            token_mint=token_mint,
            size_usd=size_usd,
            active_positions=len(self._active_positions),
        )

    def set_cooldown(self, token_mint: str) -> None:
        """Set cooldown for a token.

        Args:
            token_mint: Token mint address
        """
        self._token_cooldowns[token_mint] = self._now_fn()
        logger.info("Set cooldown for token", token_mint=token_mint)

    def close_position(self, token_mint: str) -> None:
        """Close a position.

        Args:
            token_mint: Token mint address
        """
        if token_mint in self._active_positions:
            self._active_positions.remove(token_mint)
            self._position_sizes.pop(token_mint, None)

            logger.info(
                "Closed position",
                token_mint=token_mint,
                active_positions=len(self._active_positions),
            )

    def get_position_info(self, token_mint: str) -> dict | None:
        """Get information about a position.

        Args:
            token_mint: Token mint address

        Returns:
            Position info dict or None if not found
        """
        if token_mint not in self._active_positions:
            return None

        return {
            "token_mint": token_mint,
            "size_usd": self._position_sizes.get(token_mint, 0.0),
            "opened_at": self._token_cooldowns.get(token_mint, 0),
        }

    def get_state_summary(self) -> dict:
        """Get current risk manager state summary.

        Returns:
            Dictionary with current state information
        """
        self._reset_daily_if_needed()

        return {
            "daily_pnl": self._daily_pnl,
            "remaining_daily_budget": self.remaining_daily_budget,
            "active_positions": len(self._active_positions),
            "max_concurrent_positions": self.max_concurrent_positions,
            "position_size_usd": self.position_size_usd,
            "daily_max_loss_usd": self.daily_max_loss_usd,
            "cooldown_seconds": self.cooldown_seconds,
            "day_start": datetime.fromtimestamp(self._daily_start_time).isoformat(),
        }
