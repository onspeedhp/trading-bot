"""Persistence storage using SQLite and optional Parquet."""

import json
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from ..core.interfaces import Persistence

logger = structlog.get_logger(__name__)

# Try to import pyarrow for Parquet support
try:
    import pyarrow as pa
    import pyarrow.parquet as pq

    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False
    pa = None
    pq = None


class SQLiteStorage(Persistence):
    """SQLite-based storage implementation."""

    def __init__(
        self,
        db_path: str = "bot.sqlite",
        parquet_dir: str | None = None,
        enable_parquet: bool = False,
    ) -> None:
        """Initialize SQLite storage.

        Args:
            db_path: Path to SQLite database file
            parquet_dir: Directory for Parquet files (optional)
            enable_parquet: Whether to enable Parquet writing
        """
        self.db_path = db_path
        self.parquet_dir = Path(parquet_dir) if parquet_dir else None
        self.enable_parquet = enable_parquet and PARQUET_AVAILABLE

        if enable_parquet and not PARQUET_AVAILABLE:
            warnings.warn(
                "Parquet support requested but pyarrow not available. "
                "Install with: pip install pyarrow",
                UserWarning,
                stacklevel=2,
            )
            logger.warning(
                "Parquet support disabled - pyarrow not available",
                parquet_dir=parquet_dir,
            )

        if self.enable_parquet and self.parquet_dir:
            self.parquet_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Parquet support enabled", parquet_dir=str(self.parquet_dir))

        logger.info("SQLite storage initialized", db_path=db_path)

    async def initialize(self) -> None:
        """Initialize database tables."""
        async with aiosqlite.connect(self.db_path) as db:
            # Enable foreign keys
            await db.execute("PRAGMA foreign_keys = ON")

            # Create positions table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    token_mint TEXT PRIMARY KEY,
                    qty REAL NOT NULL,
                    avg_cost_usd REAL NOT NULL,
                    updated_ts REAL NOT NULL
                )
            """)

            # Create trades table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_mint TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    px REAL NOT NULL,
                    fee_usd REAL NOT NULL DEFAULT 0.0,
                    ts REAL NOT NULL
                )
            """)

            # Create index on trades for better query performance
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_token_mint
                ON trades(token_mint)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_ts
                ON trades(ts)
            """)

            # Create state table for key-value storage
            await db.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            await db.commit()

        logger.info("Database tables initialized")

    async def upsert_position(
        self,
        token_mint: str,
        qty: float,
        avg_cost_usd: float,
        updated_ts: float | None = None,
    ) -> None:
        """Insert or update a position.

        Args:
            token_mint: Token mint address
            qty: Position quantity
            avg_cost_usd: Average cost in USD
            updated_ts: Update timestamp (defaults to current time)
        """
        if updated_ts is None:
            updated_ts = datetime.now().timestamp()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO positions (token_mint, qty, avg_cost_usd, updated_ts)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(token_mint) DO UPDATE SET
                    qty = excluded.qty,
                    avg_cost_usd = excluded.avg_cost_usd,
                    updated_ts = excluded.updated_ts
            """,
                (token_mint, qty, avg_cost_usd, updated_ts),
            )

            await db.commit()

        logger.debug(
            "Position upserted",
            token_mint=token_mint,
            qty=qty,
            avg_cost_usd=avg_cost_usd,
        )

    async def record_trade(
        self,
        token_mint: str,
        side: str,
        qty: float,
        px: float,
        fee_usd: float = 0.0,
        ts: float | None = None,
    ) -> int:
        """Record a trade.

        Args:
            token_mint: Token mint address
            side: Trade side ('buy' or 'sell')
            qty: Trade quantity
            px: Trade price
            fee_usd: Trading fee in USD
            ts: Trade timestamp (defaults to current time)

        Returns:
            Trade ID
        """
        if ts is None:
            ts = datetime.now().timestamp()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO trades (token_mint, side, qty, px, fee_usd, ts)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (token_mint, side, qty, px, fee_usd, ts),
            )

            trade_id = cursor.lastrowid
            await db.commit()

        logger.debug(
            "Trade recorded",
            trade_id=trade_id,
            token_mint=token_mint,
            side=side,
            qty=qty,
            px=px,
            fee_usd=fee_usd,
        )

        # Write to Parquet if enabled
        if self.enable_parquet:
            await self._write_trade_to_parquet(
                trade_id, token_mint, side, qty, px, fee_usd, ts
            )

        return trade_id

    async def load_positions(self) -> list[dict[str, Any]]:
        """Load all positions.

        Returns:
            List of position dictionaries
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute("""
                SELECT token_mint, qty, avg_cost_usd, updated_ts
                FROM positions
                ORDER BY updated_ts DESC
            """) as cursor:
                rows = await cursor.fetchall()

        positions = [dict(row) for row in rows]

        logger.debug("Loaded positions", count=len(positions))
        return positions

    async def load_state(self, key: str) -> str | None:
        """Load state value by key.

        Args:
            key: State key

        Returns:
            State value or None if not found
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT value FROM state WHERE key = ?
            """,
                (key,),
            ) as cursor:
                row = await cursor.fetchone()

        if row:
            value = row[0]
            logger.debug("State loaded", key=key, value_length=len(value))
            return value

        logger.debug("State not found", key=key)
        return None

    async def save_state(self, key: str, value: str) -> None:
        """Save state value by key.

        Args:
            key: State key
            value: State value
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value
            """,
                (key, value),
            )

            await db.commit()

        logger.debug("State saved", key=key, value_length=len(value))

    async def save_state_json(self, key: str, data: Any) -> None:
        """Save JSON-serializable data as state.

        Args:
            key: State key
            data: JSON-serializable data
        """
        value = json.dumps(data)
        await self.save_state(key, value)

    async def load_state_json(self, key: str) -> Any | None:
        """Load and deserialize JSON state data.

        Args:
            key: State key

        Returns:
            Deserialized data or None if not found
        """
        value = await self.load_state(key)
        if value is None:
            return None

        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error("Failed to deserialize state JSON", key=key, error=str(e))
            return None

    async def _write_trade_to_parquet(
        self,
        trade_id: int,
        token_mint: str,
        side: str,
        qty: float,
        px: float,
        fee_usd: float,
        ts: float,
    ) -> None:
        """Write trade to Parquet file (if enabled)."""
        if not self.enable_parquet or not self.parquet_dir:
            return

        try:
            # Create trade data
            trade_data = {
                "id": [trade_id],
                "token_mint": [token_mint],
                "side": [side],
                "qty": [qty],
                "px": [px],
                "fee_usd": [fee_usd],
                "ts": [ts],
                "date": [datetime.fromtimestamp(ts).date().isoformat()],
            }

            # Create PyArrow table
            table = pa.table(trade_data)

            # Determine file path (partition by date)
            date_str = datetime.fromtimestamp(ts).date().isoformat()
            parquet_file = self.parquet_dir / f"trades_{date_str}.parquet"

            # Append to existing file or create new one
            if parquet_file.exists():
                # Read existing data and append
                existing_table = pq.read_table(str(parquet_file))
                combined_table = pa.concat_tables([existing_table, table])
                pq.write_table(combined_table, str(parquet_file))
            else:
                # Create new file
                pq.write_table(table, str(parquet_file))

            logger.debug(
                "Trade written to Parquet", trade_id=trade_id, file=str(parquet_file)
            )

        except Exception as e:
            logger.error(
                "Failed to write trade to Parquet", trade_id=trade_id, error=str(e)
            )

    async def close(self) -> None:
        """Close storage (cleanup if needed)."""
        logger.info("Storage closed")

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
