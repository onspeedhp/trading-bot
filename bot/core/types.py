"""Core data types for the trading bot."""

from datetime import datetime

from pydantic import BaseModel, Field


class TokenId(BaseModel):
    """Token identifier with chain and mint address."""

    chain: str = Field(default="sol", description="Blockchain chain identifier")
    mint: str = Field(description="Token mint address")


class PoolId(BaseModel):
    """Pool identifier with program and address."""

    program: str = Field(description="DEX program identifier")
    address: str = Field(description="Pool address")


class PriceQuote(BaseModel):
    """Price quote for a token pair."""

    base: TokenId = Field(description="Base token")
    quote: TokenId = Field(description="Quote token")
    price: float = Field(description="Price in quote currency")
    liq_usd: float = Field(description="Liquidity in USD")
    vol_5m_usd: float = Field(description="5-minute volume in USD")
    ts: datetime = Field(description="Timestamp")


class TokenSnapshot(BaseModel):
    """Token market snapshot with comprehensive data."""

    token: TokenId = Field(description="Token identifier")
    pool: PoolId | None = Field(default=None, description="Associated pool")
    price_usd: float = Field(description="Price in USD")
    liq_usd: float = Field(description="Liquidity in USD")
    vol_5m_usd: float = Field(description="5-minute volume in USD")
    holders: int | None = Field(default=None, description="Number of holders")
    age_seconds: int | None = Field(default=None, description="Token age in seconds")
    pct_change_5m: float | None = Field(
        default=None, description="5-minute price change percentage"
    )
    source: str = Field(description="Data source identifier")
    ts: datetime = Field(description="Snapshot timestamp")


class FilterDecision(BaseModel):
    """Filter evaluation decision."""

    accepted: bool = Field(description="Whether the token passed the filter")
    score: float = Field(description="Filter score (0-1)")
    reasons: list[str] = Field(default_factory=list, description="Reasons for decision")
