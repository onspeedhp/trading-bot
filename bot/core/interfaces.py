"""Core interfaces for the trading bot."""

from typing import Protocol, runtime_checkable

from .types import FilterDecision, TokenId, TokenSnapshot


class MarketDataSource(Protocol):
    """Market data source protocol."""

    async def poll(self) -> list[TokenSnapshot]:
        """Poll for new market data snapshots."""
        ...

    async def lookup(self, token: TokenId) -> TokenSnapshot | None:
        """Look up specific token snapshot."""
        ...


class Filter(Protocol):
    """Token filter protocol."""

    def evaluate(self, snap: TokenSnapshot) -> FilterDecision:
        """Evaluate a token snapshot and return filter decision."""
        ...


@runtime_checkable
class RiskManager(Protocol):
    """Risk management protocol."""

    def size_usd(self, snap: TokenSnapshot) -> float:
        """Calculate position size in USD for a token."""
        ...

    def allow_buy(self, snap: TokenSnapshot) -> tuple[bool, list[str]]:
        """Check if buying is allowed and return reasons."""
        ...

    def after_fill(self, pnl_usd: float) -> None:
        """Update risk state after trade fill."""
        ...


class ExecutionClient(Protocol):
    """Execution client protocol."""

    async def buy(self, snap: TokenSnapshot, usd_amount: float) -> dict:
        """Execute buy order."""
        ...

    async def sell(self, token: TokenId, pct: float) -> dict:
        """Execute sell order for percentage of position."""
        ...

    async def simulate(self, snap: TokenSnapshot, usd_amount: float) -> dict:
        """Simulate trade execution."""
        ...


class AlertSink(Protocol):
    """Alert sink protocol."""

    async def push(self, message: str) -> None:
        """Push alert message."""
        ...


class Persistence(Protocol):
    """Data persistence protocol."""

    # Position management
    async def store_position(
        self, token: TokenId, usd_amount: float, price_usd: float
    ) -> None:
        """Store position data."""
        ...

    async def load_positions(self) -> list[dict]:
        """Load all positions."""
        ...

    async def update_position(self, token: TokenId, pnl_usd: float) -> None:
        """Update position P&L."""
        ...

    # Trade history
    async def store_trade(
        self, token: TokenId, side: str, usd_amount: float, price_usd: float
    ) -> None:
        """Store trade data."""
        ...

    async def load_trades(self, limit: int = 100) -> list[dict]:
        """Load recent trades."""
        ...

    # Market snapshots
    async def store_snapshot(self, snap: TokenSnapshot) -> None:
        """Store market snapshot."""
        ...

    async def load_snapshots(
        self, token: TokenId, limit: int = 100
    ) -> list[TokenSnapshot]:
        """Load recent snapshots for a token."""
        ...
