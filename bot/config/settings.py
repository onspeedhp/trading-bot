"""Application settings and configuration management."""

from pathlib import Path
from typing import Literal

import structlog
import yaml
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings

logger = structlog.get_logger(__name__)


class AppSettings(BaseSettings):
    """Application settings with environment variable support."""

    # Environment and mode
    env: Literal["dev", "paper", "prod"] = Field(
        description="Environment: dev, paper, prod"
    )

    # RPC and API endpoints
    rpc_url: str = Field(description="Solana RPC URL")
    helius_api_key: str | None = Field(default=None, description="Helius API key")
    birdeye_api_key: str | None = Field(default=None, description="Birdeye API key")
    dexscreener_base: str = Field(
        default="https://api.dexscreener.com/latest/dex",
        description="DexScreener API base URL",
    )
    jupiter_base: str = Field(
        default="https://quote-api.jup.ag/v6", description="Jupiter API base URL"
    )
    gmgn_base: str | None = Field(default=None, description="GMGN API base URL")

    # Transaction settings
    priority_fee_microlamports: int = Field(
        default=0, description="Priority fee in microlamports"
    )
    compute_unit_limit: int = Field(
        default=120000, description="Compute unit limit for transactions"
    )
    jito_tip_lamports: int = Field(default=0, description="Jito tip in lamports")
    max_slippage_bps: int = Field(
        default=100, description="Maximum slippage in basis points"
    )

    # Risk management
    position_size_usd: float = Field(default=50.0, description="Position size in USD")
    daily_max_loss_usd: float = Field(
        default=200.0, description="Daily maximum loss in USD"
    )
    cooldown_seconds: int = Field(
        default=60, description="Cooldown between trades in seconds"
    )

    # Notifications
    telegram_bot_token: str | None = Field(
        default=None, description="Telegram bot token"
    )
    telegram_admin_ids: list[int] = Field(
        default_factory=list, description="Telegram admin user IDs"
    )

    # Data storage
    database_url: str = Field(
        default="sqlite+aiosqlite:///./bot.sqlite",
        description="Database connection URL",
    )
    parquet_dir: str = Field(
        default="./data_parquet", description="Directory for Parquet data files"
    )

    # Execution mode
    dry_run: bool = Field(default=True, description="Dry run mode (no real trades)")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


def load_settings(profile: str, yaml_path: str) -> AppSettings:
    """Load settings from YAML file and environment variables.

    Args:
        profile: Configuration profile name (dev, paper, prod)
        yaml_path: Path to YAML configuration file

    Returns:
        AppSettings instance with loaded configuration

    Raises:
        FileNotFoundError: If YAML file doesn't exist
        ValidationError: If configuration is invalid
        ValueError: If profile is invalid
    """
    if profile not in ["dev", "paper", "prod"]:
        raise ValueError(
            f"Invalid profile: {profile}. Must be one of: dev, paper, prod"
        )

    yaml_file = Path(yaml_path)
    if not yaml_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {yaml_path}")

    try:
        # Load YAML configuration
        with open(yaml_file, encoding="utf-8") as f:
            yaml_config = yaml.safe_load(f)

        # Set environment from profile
        yaml_config["env"] = profile

        # Set dry_run based on profile
        if profile == "paper":
            yaml_config["dry_run"] = True
        elif profile == "prod":
            yaml_config["dry_run"] = False
        # dev profile dry_run is set in YAML

        logger.info("Loading configuration", profile=profile, yaml_path=yaml_path)

        # Create settings with YAML config and environment variable overlay
        settings = AppSettings(**yaml_config)

        logger.info(
            "Configuration loaded successfully",
            profile=profile,
            dry_run=settings.dry_run,
            rpc_url=settings.rpc_url[:50] + "..."
            if len(settings.rpc_url) > 50
            else settings.rpc_url,
        )

        return settings

    except yaml.YAMLError as e:
        logger.error("Failed to parse YAML configuration", error=str(e))
        raise ValueError(f"Invalid YAML configuration: {e}") from e
    except ValidationError as e:
        logger.error("Configuration validation failed", error=str(e))
        raise
    except Exception as e:
        logger.error("Unexpected error loading configuration", error=str(e))
        raise
