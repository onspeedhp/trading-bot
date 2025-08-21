"""Tests for SQLite storage implementation."""

import json
import tempfile
import warnings
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio

from bot.persist.storage import SQLiteStorage


class TestSQLiteStorage:
    """Test SQLite storage functionality."""

    @pytest_asyncio.fixture
    async def storage(self):
        """Create a temporary SQLite storage."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            db_path = tmp.name

        storage = SQLiteStorage(db_path=db_path)
        await storage.initialize()

        yield storage

        await storage.close()
        # Clean up temp file
        Path(db_path).unlink(missing_ok=True)

    @pytest_asyncio.fixture
    async def storage_with_parquet(self):
        """Create a temporary SQLite storage with Parquet support."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "test.sqlite")
            parquet_dir = str(Path(tmp_dir) / "parquet")

            storage = SQLiteStorage(
                db_path=db_path,
                parquet_dir=parquet_dir,
                enable_parquet=True,  # Will be disabled if pyarrow not available
            )
            await storage.initialize()

            yield storage

            await storage.close()

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test storage initialization."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            db_path = tmp.name

        storage = SQLiteStorage(db_path=db_path)
        await storage.initialize()

        # Verify database file exists
        assert Path(db_path).exists()

        await storage.close()
        Path(db_path).unlink()

    @pytest.mark.asyncio
    async def test_upsert_position(self, storage):
        """Test position upsert functionality."""
        token_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

        # Insert new position
        await storage.upsert_position(token_mint, 100.0, 1.5, 1640995200.0)

        positions = await storage.load_positions()
        assert len(positions) == 1
        assert positions[0]["token_mint"] == token_mint
        assert positions[0]["qty"] == 100.0
        assert positions[0]["avg_cost_usd"] == 1.5
        assert positions[0]["updated_ts"] == 1640995200.0

        # Update existing position
        await storage.upsert_position(token_mint, 150.0, 1.75, 1640995300.0)

        positions = await storage.load_positions()
        assert len(positions) == 1  # Still only one position
        assert positions[0]["qty"] == 150.0
        assert positions[0]["avg_cost_usd"] == 1.75
        assert positions[0]["updated_ts"] == 1640995300.0

    @pytest.mark.asyncio
    async def test_upsert_position_default_timestamp(self, storage):
        """Test position upsert with default timestamp."""
        token_mint = "test_token"

        before_time = datetime.now().timestamp()
        await storage.upsert_position(token_mint, 50.0, 2.0)
        after_time = datetime.now().timestamp()

        positions = await storage.load_positions()
        assert len(positions) == 1
        assert before_time <= positions[0]["updated_ts"] <= after_time

    @pytest.mark.asyncio
    async def test_record_trade(self, storage):
        """Test trade recording."""
        token_mint = "test_token"

        # Record a buy trade
        trade_id = await storage.record_trade(
            token_mint, "buy", 100.0, 1.5, 0.75, 1640995200.0
        )

        assert isinstance(trade_id, int)
        assert trade_id > 0

    @pytest.mark.asyncio
    async def test_record_trade_default_timestamp(self, storage):
        """Test trade recording with default timestamp."""
        token_mint = "test_token"

        trade_id = await storage.record_trade(token_mint, "sell", 50.0, 1.6, 0.4)

        assert isinstance(trade_id, int)
        assert trade_id > 0

    @pytest.mark.asyncio
    async def test_load_positions_empty(self, storage):
        """Test loading positions when none exist."""
        positions = await storage.load_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_load_positions_multiple(self, storage):
        """Test loading multiple positions."""
        # Add multiple positions
        await storage.upsert_position("token1", 100.0, 1.0, 1640995200.0)
        await storage.upsert_position("token2", 200.0, 2.0, 1640995300.0)
        await storage.upsert_position("token3", 300.0, 3.0, 1640995100.0)

        positions = await storage.load_positions()
        assert len(positions) == 3

        # Should be ordered by updated_ts DESC
        assert positions[0]["token_mint"] == "token2"  # Most recent
        assert positions[1]["token_mint"] == "token1"
        assert positions[2]["token_mint"] == "token3"  # Oldest

    @pytest.mark.asyncio
    async def test_state_operations(self, storage):
        """Test state save and load operations."""
        # Test non-existent key
        value = await storage.load_state("non_existent")
        assert value is None

        # Save and load string value
        await storage.save_state("test_key", "test_value")
        value = await storage.load_state("test_key")
        assert value == "test_value"

        # Update existing key
        await storage.save_state("test_key", "updated_value")
        value = await storage.load_state("test_key")
        assert value == "updated_value"

        # Save complex string
        complex_value = json.dumps({"nested": {"data": [1, 2, 3]}})
        await storage.save_state("complex_key", complex_value)
        value = await storage.load_state("complex_key")
        assert value == complex_value
        assert json.loads(value) == {"nested": {"data": [1, 2, 3]}}

    @pytest.mark.asyncio
    async def test_parquet_warning_without_pyarrow(self):
        """Test that warning is issued when Parquet requested but pyarrow unavailable."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "test.sqlite")
            parquet_dir = str(Path(tmp_dir) / "parquet")

            # Mock PARQUET_AVAILABLE to False to simulate missing pyarrow
            import bot.persist.storage as storage_module

            original_value = storage_module.PARQUET_AVAILABLE
            storage_module.PARQUET_AVAILABLE = False

            try:
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")

                    storage = SQLiteStorage(
                        db_path=db_path, parquet_dir=parquet_dir, enable_parquet=True
                    )

                    # Should have issued a warning
                    assert len(w) == 1
                    assert issubclass(w[0].category, UserWarning)
                    assert "pyarrow not available" in str(w[0].message)

                    # Parquet should be disabled
                    assert storage.enable_parquet is False

            finally:
                # Restore original value
                storage_module.PARQUET_AVAILABLE = original_value

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager functionality."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            db_path = tmp.name

        async with SQLiteStorage(db_path=db_path) as storage:
            # Should be initialized
            await storage.upsert_position("test_token", 100.0, 1.0)

            positions = await storage.load_positions()
            assert len(positions) == 1

        # Cleanup
        Path(db_path).unlink()

    @pytest.mark.asyncio
    async def test_crud_roundtrip(self, storage):
        """Test complete CRUD roundtrip for positions and trades."""
        token_mint = "test_token_crud"

        # 1. Create position
        await storage.upsert_position(token_mint, 100.0, 1.5, 1640995200.0)

        # 2. Read position
        positions = await storage.load_positions()
        assert len(positions) == 1
        position = positions[0]
        assert position["token_mint"] == token_mint
        assert position["qty"] == 100.0
        assert position["avg_cost_usd"] == 1.5

        # 3. Update position
        await storage.upsert_position(token_mint, 150.0, 1.75, 1640995300.0)

        # 4. Verify update
        positions = await storage.load_positions()
        assert len(positions) == 1
        position = positions[0]
        assert position["qty"] == 150.0
        assert position["avg_cost_usd"] == 1.75

        # 5. Record trades
        trade_id1 = await storage.record_trade(
            token_mint, "buy", 100.0, 1.5, 0.75, 1640995200.0
        )
        trade_id2 = await storage.record_trade(
            token_mint, "buy", 50.0, 2.0, 0.5, 1640995250.0
        )
        trade_id3 = await storage.record_trade(
            token_mint, "sell", 25.0, 2.2, 0.55, 1640995300.0
        )

        assert all(
            isinstance(tid, int) and tid > 0
            for tid in [trade_id1, trade_id2, trade_id3]
        )

        # 6. Test state operations
        state_data = {
            "position": position,
            "trade_ids": [trade_id1, trade_id2, trade_id3],
            "metadata": {"version": "1.0"},
        }

        await storage.save_state("session_state", json.dumps(state_data))

        loaded_state = await storage.load_state("session_state")
        assert loaded_state is not None
        parsed_state = json.loads(loaded_state)
        assert parsed_state == state_data

    @pytest.mark.asyncio
    async def test_multiple_tokens(self, storage):
        """Test operations with multiple tokens."""
        tokens = ["token_a", "token_b", "token_c"]

        # Add positions for multiple tokens
        for i, token in enumerate(tokens, 1):
            await storage.upsert_position(
                token, float(i * 100), float(i), float(1640995200 + i * 100)
            )

        # Add trades for multiple tokens
        for i, token in enumerate(tokens, 1):
            await storage.record_trade(
                token,
                "buy",
                float(i * 50),
                float(i * 1.5),
                float(i * 0.25),
                float(1640995200 + i * 50),
            )
            await storage.record_trade(
                token,
                "sell",
                float(i * 25),
                float(i * 1.8),
                float(i * 0.3),
                float(1640995200 + i * 75),
            )

        # Verify all positions loaded
        positions = await storage.load_positions()
        assert len(positions) == 3

        # Verify positions are ordered by timestamp desc
        token_order = [pos["token_mint"] for pos in positions]
        assert token_order == ["token_c", "token_b", "token_a"]

    @pytest.mark.asyncio
    async def test_edge_cases(self, storage):
        """Test edge cases and boundary conditions."""
        # Test with zero values
        await storage.upsert_position("zero_token", 0.0, 0.0, 0.0)
        positions = await storage.load_positions()
        assert len(positions) == 1
        assert positions[0]["qty"] == 0.0
        assert positions[0]["avg_cost_usd"] == 0.0

        # Test with very large numbers
        large_num = 1e15
        await storage.upsert_position("large_token", large_num, large_num, large_num)
        await storage.record_trade(
            "large_token", "buy", large_num, large_num, large_num, large_num
        )

        positions = await storage.load_positions()
        large_position = next(p for p in positions if p["token_mint"] == "large_token")
        assert large_position["qty"] == large_num

        # Test with very long strings
        long_string = "x" * 1000
        await storage.save_state("long_key", long_string)
        loaded_value = await storage.load_state("long_key")
        assert loaded_value == long_string

        # Test with special characters in token mint
        special_token = "token-with_special.chars123!@#"
        await storage.upsert_position(special_token, 100.0, 1.0)
        positions = await storage.load_positions()
        special_position = next(
            p for p in positions if p["token_mint"] == special_token
        )
        assert special_position is not None
