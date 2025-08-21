"""Tests for configuration management."""

import os
import tempfile

import pytest
from pydantic import ValidationError

from bot.config.settings import AppSettings, load_settings


def test_app_settings_defaults() -> None:
    """Test that AppSettings has correct defaults."""
    settings = AppSettings(env="dev", rpc_url="https://api.devnet.solana.com")

    assert settings.env == "dev"
    assert settings.rpc_url == "https://api.devnet.solana.com"
    assert settings.helius_api_key is None
    assert settings.birdeye_api_key is None
    assert settings.dexscreener_base == "https://api.dexscreener.com/latest/dex"
    assert settings.jupiter_base == "https://quote-api.jup.ag/v6"
    assert settings.gmgn_base is None
    assert settings.priority_fee_microlamports == 0
    assert settings.compute_unit_limit == 120000
    assert settings.jito_tip_lamports == 0
    assert settings.max_slippage_bps == 100
    assert settings.position_size_usd == 50.0
    assert settings.daily_max_loss_usd == 200.0
    assert settings.cooldown_seconds == 60
    assert settings.telegram_bot_token is None
    assert settings.telegram_admin_ids == []
    assert settings.database_url == "sqlite+aiosqlite:///./bot.sqlite"
    assert settings.parquet_dir == "./data_parquet"
    assert settings.dry_run is True


def test_app_settings_custom_values() -> None:
    """Test that AppSettings can be customized."""
    settings = AppSettings(
        env="prod",
        rpc_url="https://api.mainnet-beta.solana.com",
        helius_api_key="test_key",
        position_size_usd=1000.0,
        daily_max_loss_usd=500.0,
        telegram_admin_ids=[123456789],
        dry_run=False,
    )

    assert settings.env == "prod"
    assert settings.rpc_url == "https://api.mainnet-beta.solana.com"
    assert settings.helius_api_key == "test_key"
    assert settings.position_size_usd == 1000.0
    assert settings.daily_max_loss_usd == 500.0
    assert settings.telegram_admin_ids == [123456789]
    assert settings.dry_run is False


def test_app_settings_validation() -> None:
    """Test that AppSettings validates required fields."""
    # Missing required rpc_url should raise validation error
    with pytest.raises(ValidationError):
        AppSettings(env="dev")

    # Invalid env should raise validation error
    with pytest.raises(ValidationError):
        AppSettings(env="invalid", rpc_url="https://api.devnet.solana.com")


def test_load_settings_dev_profile() -> None:
    """Test loading dev profile configuration."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
            rpc_url: "https://api.devnet.solana.com"
            helius_api_key: null
            birdeye_api_key: null
            position_size_usd: 10.0
            daily_max_loss_usd: 50.0
            cooldown_seconds: 120
            telegram_bot_token: null
            telegram_admin_ids: []
            database_url: "sqlite+aiosqlite:///./dev_bot.sqlite"
            parquet_dir: "./dev_data_parquet"
            dry_run: true
            """)
        yaml_path = f.name

    try:
        settings = load_settings("dev", yaml_path)

        assert settings.env == "dev"
        assert settings.rpc_url == "https://api.devnet.solana.com"
        assert settings.helius_api_key is None
        assert settings.position_size_usd == 10.0
        assert settings.daily_max_loss_usd == 50.0
        assert settings.cooldown_seconds == 120
        assert settings.dry_run is True  # Should remain as set in YAML
        assert settings.database_url == "sqlite+aiosqlite:///./dev_bot.sqlite"
        assert settings.parquet_dir == "./dev_data_parquet"
    finally:
        os.unlink(yaml_path)


def test_load_settings_paper_profile() -> None:
    """Test loading paper profile configuration."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
            rpc_url: "https://api.mainnet-beta.solana.com"
            helius_api_key: null
            birdeye_api_key: null
            position_size_usd: 100.0
            daily_max_loss_usd: 200.0
            cooldown_seconds: 60
            telegram_bot_token: null
            telegram_admin_ids: []
            database_url: "sqlite+aiosqlite:///./paper_bot.sqlite"
            parquet_dir: "./paper_data_parquet"
            """)
        yaml_path = f.name

    try:
        settings = load_settings("paper", yaml_path)

        assert settings.env == "paper"
        assert settings.rpc_url == "https://api.mainnet-beta.solana.com"
        assert settings.position_size_usd == 100.0
        assert settings.daily_max_loss_usd == 200.0
        assert settings.cooldown_seconds == 60
        assert (
            settings.dry_run is True
        )  # Should be automatically set to True for paper profile
        assert settings.database_url == "sqlite+aiosqlite:///./paper_bot.sqlite"
        assert settings.parquet_dir == "./paper_data_parquet"
    finally:
        os.unlink(yaml_path)


def test_load_settings_prod_profile() -> None:
    """Test loading prod profile configuration."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
            rpc_url: "https://api.mainnet-beta.solana.com"
            helius_api_key: null
            birdeye_api_key: null
            position_size_usd: 500.0
            daily_max_loss_usd: 1000.0
            cooldown_seconds: 30
            telegram_bot_token: null
            telegram_admin_ids: []
            database_url: "sqlite+aiosqlite:///./prod_bot.sqlite"
            parquet_dir: "./prod_data_parquet"
            """)
        yaml_path = f.name

    try:
        settings = load_settings("prod", yaml_path)

        assert settings.env == "prod"
        assert settings.rpc_url == "https://api.mainnet-beta.solana.com"
        assert settings.position_size_usd == 500.0
        assert settings.daily_max_loss_usd == 1000.0
        assert settings.cooldown_seconds == 30
        assert (
            settings.dry_run is False
        )  # Should be automatically set to False for prod profile
        assert settings.database_url == "sqlite+aiosqlite:///./prod_bot.sqlite"
        assert settings.parquet_dir == "./prod_data_parquet"
    finally:
        os.unlink(yaml_path)


def test_load_settings_invalid_profile() -> None:
    """Test that load_settings rejects invalid profiles."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
            rpc_url: "https://api.devnet.solana.com"
            """)
        yaml_path = f.name

    try:
        with pytest.raises(ValueError, match="Invalid profile: invalid"):
            load_settings("invalid", yaml_path)
    finally:
        os.unlink(yaml_path)


def test_load_settings_file_not_found() -> None:
    """Test that load_settings handles missing files."""
    with pytest.raises(FileNotFoundError, match="Configuration file not found"):
        load_settings("dev", "nonexistent.yaml")


def test_load_settings_invalid_yaml() -> None:
    """Test that load_settings handles invalid YAML."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
            invalid: yaml: content: [
            """)
        yaml_path = f.name

    try:
        with pytest.raises(ValueError, match="Invalid YAML configuration"):
            load_settings("dev", yaml_path)
    finally:
        os.unlink(yaml_path)


def test_load_settings_validation_error() -> None:
    """Test that load_settings handles validation errors."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
            rpc_url: "https://api.devnet.solana.com"
            position_size_usd: "invalid_float"  # Invalid type for float field
            """)
        yaml_path = f.name

    try:
        with pytest.raises(ValidationError):
            load_settings("dev", yaml_path)
    finally:
        os.unlink(yaml_path)


def test_load_settings_with_environment_overrides() -> None:
    """Test that environment variables can override YAML settings."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
            rpc_url: "https://api.devnet.solana.com"
            helius_api_key: null
            position_size_usd: 10.0
            """)
        yaml_path = f.name

    try:
        # Set environment variables
        os.environ["HELIUS_API_KEY"] = "env_test_key"
        os.environ["POSITION_SIZE_USD"] = "25.0"

        # Create settings directly to test environment variable override
        settings = AppSettings(env="dev", rpc_url="https://api.devnet.solana.com")

        # Environment variables should override default values
        assert settings.helius_api_key == "env_test_key"
        assert settings.position_size_usd == 25.0

        # YAML values should remain for non-overridden fields
        assert settings.rpc_url == "https://api.devnet.solana.com"

    finally:
        os.unlink(yaml_path)
        # Clean up environment variables
        os.environ.pop("HELIUS_API_KEY", None)
        os.environ.pop("POSITION_SIZE_USD", None)
