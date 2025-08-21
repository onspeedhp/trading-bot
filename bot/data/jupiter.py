"""Jupiter data source for token price and market data (Token API V2 + optional Price V3)."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Optional

import httpx
import structlog

from ..core.interfaces import MarketDataSource
from ..core.types import TokenId, TokenSnapshot

logger = structlog.get_logger(__name__)

_STATS_KEY_BY_INTERVAL = {
    "5m": "stats5m",
    "1h": "stats1h",
    "6h": "stats6h",
    "24h": "stats24h",
}


class JupiterDataSource(MarketDataSource):
    """
    Fetch trending/new/verified tokens and their market fields from Jupiter Token API V2.
    Optionally enrich price via Price API V3.

    Docs:
      - Token API V2 base (lite): https://lite-api.jup.ag/tokens/v2
        categories: toporganicscore | toptraded | toptrending, intervals: 5m|1h|6h|24h
        search: /tokens/v2/search?query=...
      - Price API V3 base (lite): https://lite-api.jup.ag/price/v3?ids=... (<= 50 mints)
    """

    def __init__(
        self,
        *,
        base_url: str = "https://lite-api.jup.ag",
        category: str = "toptrending",
        interval: str = "5m",
        limit: int = 20,
        use_price_v3: bool = False,
        session: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.category = category  # toporganicscore | toptraded | toptrending
        self.interval = interval  # 5m | 1h | 6h | 24h
        self.limit = max(1, min(100, int(limit)))
        self.use_price_v3 = use_price_v3

        # Prefer an injected AsyncClient; fall back to own client if not provided.
        self._session = session or httpx.AsyncClient(
            timeout=20.0,
            http2=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._owns_session = session is None

    async def close(self) -> None:
        if self._owns_session:
            await self._session.aclose()

    # -------------------------
    # HTTP helpers
    # -------------------------
    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        r = await self._session.get(url, params=params)
        r.raise_for_status()
        return r.json()

    async def _price_v3(self, mints: list[str]) -> dict[str, Any]:
        """Call Price API V3 for up to 50 ids at once."""
        if not mints:
            return {}
        # limit per docs
        ids = ",".join(mints[:50])
        data = await self._get_json(f"/price/v3", {"ids": ids})
        # Response is a dict keyed by mint → {usdPrice, blockId, decimals, priceChange24h}
        return data if isinstance(data, dict) else {}

    # -------------------------
    # Mapping helpers
    # -------------------------
    @staticmethod
    def _parse_iso8601(ts: str | None) -> datetime | None:
        if not ts:
            return None
        try:
            # example: "2025-06-25T05:02:21.034234634Z"
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            return datetime.fromisoformat(ts).astimezone(UTC)
        except Exception:
            return None

    def _to_snapshot(
        self,
        item: dict[str, Any],
        stats_key: str,
        source: str,
        price_overlay: dict[str, Any] | None = None,
    ) -> TokenSnapshot | None:
        try:
            mint = item.get("id")
            if not isinstance(mint, str):
                return None

            # Prefer Token API V2 price; allow override by Price V3 if requested
            price_usd = float(item.get("usdPrice", 0.0))
            if price_overlay and mint in price_overlay:
                overlay = price_overlay[mint] or {}
                # docs: only usdPrice/decimals/priceChange24h/blockId
                oup = overlay.get("usdPrice")
                if isinstance(oup, (int, float)) and not math.isnan(float(oup)):
                    price_usd = float(oup)

            liq_usd = float(item.get("liquidity", 0.0))
            holders = item.get("holderCount")
            holders = int(holders) if isinstance(holders, (int, float)) else None

            stats = item.get(stats_key) or {}
            buy_v = (
                float(stats.get("buyVolume", 0.0)) if isinstance(stats, dict) else 0.0
            )
            sell_v = (
                float(stats.get("sellVolume", 0.0)) if isinstance(stats, dict) else 0.0
            )
            vol_5m_usd = buy_v + sell_v if stats_key == "stats5m" else 0.0

            pct_change_5m = (
                float(stats.get("priceChange", 0.0)) if stats_key == "stats5m" else None
            )

            first_pool = item.get("firstPool") or {}
            created_at = self._parse_iso8601(first_pool.get("createdAt"))
            age_seconds = (
                int((datetime.now(UTC) - created_at).total_seconds())
                if created_at
                else None
            )

            return TokenSnapshot(
                token=TokenId(mint=mint),
                pool=None,
                price_usd=price_usd,
                liq_usd=liq_usd,
                vol_5m_usd=vol_5m_usd,
                holders=holders,
                age_seconds=age_seconds,
                pct_change_5m=pct_change_5m,
                source=source,
                ts=datetime.now(UTC),
            )
        except Exception as e:
            logger.warning("Failed to map Jupiter item", error=str(e))
            return None

    # -------------------------
    # Public interface
    # -------------------------
    async def poll(self) -> list[TokenSnapshot]:
        """
        Fetch tokens from a Token API V2 category, map to TokenSnapshot.
        Default: toptrending/5m with limit.
        """
        stats_key = _STATS_KEY_BY_INTERVAL.get(self.interval, "stats5m")
        path = f"/tokens/v2/{self.category}/{self.interval}"
        params = {"limit": self.limit}

        try:
            items = await self._get_json(path, params)
        except Exception as e:
            logger.warning(
                "Jupiter category fetch failed; falling back to recent", error=str(e)
            )
            try:
                items = await self._get_json("/tokens/v2/recent", None)
            except Exception as ee:
                logger.error("Jupiter recent fallback failed", error=str(ee))
                return []

        if not isinstance(items, list):
            logger.warning("Unexpected Jupiter response (expected list)", path=path)
            return []

        # Optional: overlay with Price V3 for unified pricing
        overlay = {}
        if self.use_price_v3:
            try:
                overlay = await self._price_v3(
                    [x.get("id") for x in items if isinstance(x, dict) and x.get("id")]
                )
            except Exception as e:
                logger.warning("Price V3 overlay failed", error=str(e))

        snaps: list[TokenSnapshot] = []
        for it in items[: self.limit]:
            if not isinstance(it, dict):
                continue
            snap = self._to_snapshot(
                it,
                stats_key=stats_key,
                source=f"jupiter:{self.category}:{self.interval}",
                price_overlay=overlay,
            )
            if snap:
                snaps.append(snap)

        logger.info(
            "Polled Jupiter",
            category=self.category,
            interval=self.interval,
            count=len(snaps),
        )
        return snaps

    async def lookup(self, token: TokenId) -> TokenSnapshot | None:
        """
        Find a specific mint via Token API V2 search, then map fields.
        """
        try:
            data = await self._get_json("/tokens/v2/search", {"query": token.mint})
            if not isinstance(data, list) or not data:
                return None
            # pick exact id match if present
            item = next(
                (x for x in data if isinstance(x, dict) and x.get("id") == token.mint),
                data[0],
            )
            stats_key = "stats5m"
            overlay = {}
            if self.use_price_v3:
                try:
                    overlay = await self._price_v3([token.mint])
                except Exception as e:
                    logger.warning("Price V3 overlay (lookup) failed", error=str(e))
            snap = self._to_snapshot(
                item, stats_key, source="jupiter:lookup", price_overlay=overlay
            )
            return snap
        except Exception as e:
            logger.warning(
                "Failed to lookup token via Jupiter", mint=token.mint, error=str(e)
            )
            return None
