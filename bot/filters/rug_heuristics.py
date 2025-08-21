"""Rug pull detection heuristics."""

import structlog

from ..core.interfaces import Filter
from ..core.types import FilterDecision, TokenSnapshot

logger = structlog.get_logger(__name__)


class RugHeuristicsFilter(Filter):
    """Filter to detect potential rug pull tokens using heuristics."""

    def __init__(
        self,
        max_holder_concentration: float = 0.8,
        min_holders: int = 50,
        max_price_volatility: float = 100.0,  # Max 100% price change in 5m
    ) -> None:
        """Initialize rug heuristics filter."""
        self.max_holder_concentration = max_holder_concentration
        self.min_holders = min_holders
        self.max_price_volatility = max_price_volatility

    def evaluate(self, snap: TokenSnapshot) -> FilterDecision:
        """Evaluate token snapshot for rug pull indicators."""
        reasons = []
        score = 1.0

        # Check holder count
        if snap.holders is not None:
            if snap.holders < self.min_holders:
                reasons.append(f"Too few holders: {snap.holders} < {self.min_holders}")
                score -= 0.4
        else:
            reasons.append("Holder count unknown")
            score -= 0.2

        # Check price volatility
        if snap.pct_change_5m is not None:
            abs_change = abs(snap.pct_change_5m)
            if abs_change > self.max_price_volatility:
                reasons.append(
                    f"Price too volatile: {abs_change:.1f}% > {self.max_price_volatility}%"
                )
                score -= 0.3

        # Check for extreme price movements (potential pump and dump)
        if snap.pct_change_5m is not None and snap.pct_change_5m > 50:
            reasons.append(f"Potential pump: +{snap.pct_change_5m:.1f}% in 5m")
            score -= 0.2

        # Check liquidity (very low liquidity is suspicious)
        if snap.liq_usd < 1000:
            reasons.append(f"Very low liquidity: ${snap.liq_usd:.2f}")
            score -= 0.3

        accepted = score >= 0.5 and len(reasons) == 0

        if accepted:
            reasons.append("Passed rug heuristics")

        logger.debug(
            "Rug heuristics evaluation",
            token_mint=snap.token.mint,
            accepted=accepted,
            score=score,
            reasons=reasons,
        )

        return FilterDecision(accepted=accepted, score=score, reasons=reasons)
