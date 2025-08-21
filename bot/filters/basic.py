"""Basic trading filters."""

import structlog

from ..core.interfaces import Filter
from ..core.types import FilterDecision, TokenSnapshot

logger = structlog.get_logger(__name__)


class BasicFilter(Filter):
    """Basic filter that implements common trading criteria."""

    def __init__(
        self,
        min_volume_usd: float = 10000.0,
        min_liquidity_usd: float = 50000.0,
        min_holders: int = 100,
        min_age_seconds: int = 1800,  # 30 minutes
    ) -> None:
        """Initialize basic filter."""
        self.min_volume_usd = min_volume_usd
        self.min_liquidity_usd = min_liquidity_usd
        self.min_holders = min_holders
        self.min_age_seconds = min_age_seconds

    def evaluate(self, snap: TokenSnapshot) -> FilterDecision:
        """Evaluate token snapshot against basic criteria."""
        reasons = []
        score = 1.0

        # Check volume
        if snap.vol_5m_usd < self.min_volume_usd:
            reasons.append(
                f"Volume too low: ${snap.vol_5m_usd:.2f} < ${self.min_volume_usd:.2f}"
            )
            score -= 0.3

        # Check liquidity
        if snap.liq_usd < self.min_liquidity_usd:
            reasons.append(
                f"Liquidity too low: ${snap.liq_usd:.2f} < ${self.min_liquidity_usd:.2f}"
            )
            score -= 0.4

        # Check holders
        if snap.holders is not None and snap.holders < self.min_holders:
            reasons.append(f"Too few holders: {snap.holders} < {self.min_holders}")
            score -= 0.2

        # Check age
        if snap.age_seconds is not None and snap.age_seconds < self.min_age_seconds:
            reasons.append(
                f"Token too new: {snap.age_seconds}s < {self.min_age_seconds}s"
            )
            score -= 0.1

        accepted = score >= 0.5 and len(reasons) == 0

        if accepted:
            reasons.append("Passed basic criteria")

        logger.debug(
            "Basic filter evaluation",
            token_mint=snap.token.mint,
            accepted=accepted,
            score=score,
            reasons=reasons,
        )

        return FilterDecision(accepted=accepted, score=score, reasons=reasons)
