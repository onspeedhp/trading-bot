"""Main trading pipeline runner."""

import argparse
import asyncio
import signal
import sys
from datetime import datetime
from typing import Any

import structlog

from ..alerts.telegram import TelegramAlertSink
from ..config.settings import AppSettings, load_settings
from ..core.interfaces import (
    AlertSink,
)
from ..core.types import TokenSnapshot
from ..data.birdeye import BirdeyeDataSource
from ..data.dexscreener import DexScreenerLookup
from ..data.helius import HeliusDataSource
from ..exec.jupiter import JupiterExecutor
from ..exec.paper import PaperExecutor
from ..exec.senders import RpcSender
from ..exec.signers import ExternalSigner, KeypairSigner
from ..filters.basic import BasicFilter
from ..filters.rug_heuristics import RugHeuristicsFilter
from ..persist.storage import SQLiteStorage
from ..risk.manager import RiskManagerImpl

logger = structlog.get_logger(__name__)


class NoopAlertSink(AlertSink):
    """No-operation alert sink for when Telegram is not configured."""

    async def push(self, message: str) -> None:
        """No-op push - just log the message."""
        logger.info("Alert (noop): %s", message)


class TradingPipeline:
    """Main trading pipeline orchestrator."""

    def __init__(self, settings: AppSettings) -> None:
        """Initialize trading pipeline with assembled components."""
        self.settings = settings
        self.running = False

        # Validate safety settings before assembly
        if not settings.dry_run:
            self._validate_live_trading_safety(settings)

        self.components = self._assemble(settings)

        logger.info(
            "Trading pipeline initialized",
            dry_run=settings.dry_run,
            data_sources=len(self.components["data_sources"]),
            filters=len(self.components["filters"]),
        )

    def _validate_live_trading_safety(self, settings: AppSettings) -> None:
        """Validate safety settings for live trading.

        Args:
            settings: Application settings

        Raises:
            ValueError: If safety checks fail
        """
        # Check for localhost/devnet RPC
        if "localhost" in settings.rpc_url or "127.0.0.1" in settings.rpc_url:
            if not settings.allow_devnet:
                raise ValueError(
                    f"Live trading on localhost/devnet is not allowed. "
                    f"RPC URL: {settings.rpc_url}. "
                    f"Set allow_devnet=true to override (UNSAFE)."
                )
            logger.warning("Live trading on localhost/devnet enabled (UNSAFE)")

        # Check position size vs daily loss limit
        if settings.position_size_usd > settings.daily_max_loss_usd:
            raise ValueError(
                f"Position size ({settings.position_size_usd}) cannot exceed "
                f"daily max loss ({settings.daily_max_loss_usd}). "
                f"This would allow losing more than the daily limit in a single trade."
            )

        # Check slippage limits
        if settings.max_slippage_bps > 1000:  # 10%
            if not settings.unsafe_allow_high_slippage:
                raise ValueError(
                    f"Slippage {settings.max_slippage_bps} bps ({settings.max_slippage_bps / 100}%) "
                    f"exceeds 10% limit. Set unsafe_allow_high_slippage=true to override (UNSAFE)."
                )
            logger.warning(
                f"High slippage {settings.max_slippage_bps} bps enabled (UNSAFE)"
            )

        # Log live trading banner
        logger.critical(
            "🚨 LIVE TRADING MODE ENABLED 🚨",
            rpc_url=settings.rpc_url,
            position_size_usd=settings.position_size_usd,
            daily_max_loss_usd=settings.daily_max_loss_usd,
            max_slippage_bps=settings.max_slippage_bps,
        )

    def _assemble(self, settings: AppSettings) -> dict[str, Any]:
        """Assemble all trading components from settings.

        Args:
            settings: Application settings

        Returns:
            Dictionary of assembled components
        """
        components = {}

        # Data sources
        data_sources = []

        if settings.helius_api_key:
            data_sources.append(
                HeliusDataSource(
                    rpc_url=settings.rpc_url, api_key=settings.helius_api_key
                )
            )
            logger.info("Added Helius data source")
        else:
            logger.warning("Helius API key not provided, skipping Helius data source")

        if settings.birdeye_api_key:
            data_sources.append(BirdeyeDataSource(api_key=settings.birdeye_api_key))
            logger.info("Added Birdeye data source")
        else:
            logger.warning("Birdeye API key not provided, skipping Birdeye data source")

        # Always add DexScreener as lookup source
        data_sources.append(DexScreenerLookup(base_url=settings.dexscreener_base))
        logger.info("Added DexScreener lookup source")

        components["data_sources"] = data_sources

        # Filters
        components["filters"] = [BasicFilter(), RugHeuristicsFilter()]
        logger.info("Added basic and rug heuristics filters")

        # Risk manager
        components["risk"] = RiskManagerImpl(
            position_size_usd=settings.position_size_usd,
            daily_max_loss_usd=settings.daily_max_loss_usd,
            cooldown_seconds=settings.cooldown_seconds,
        )
        logger.info("Initialized risk manager")

        # Execution client
        if settings.dry_run:
            components["exec_client"] = PaperExecutor(
                slippage_bps=settings.max_slippage_bps
            )
            logger.info("Using paper executor (dry run mode)")
        else:
            # Live trading - need signer and sender
            signer = self._create_signer(settings)
            sender = RpcSender(rpc_url=settings.rpc_url)

            components["exec_client"] = JupiterExecutor(
                base_url=settings.jupiter_base,
                rpc_url=settings.rpc_url,
                max_slippage_bps=settings.max_slippage_bps,
                priority_fee_microlamports=settings.priority_fee_microlamports,
                compute_unit_limit=settings.compute_unit_limit,
                jito_tip_lamports=settings.jito_tip_lamports,
                signer=signer,
                sender=sender,
                enable_preflight=settings.preflight_simulate,
                tip_account_b58=settings.tip_account_b58,
            )

            # Log public key for live trading
            pubkey = signer.pubkey_base58()
            logger.critical(
                "🔑 LIVE TRADING CONFIGURED 🔑",
                public_key=pubkey,
                rpc_url=settings.rpc_url,
                preflight_simulate=settings.preflight_simulate,
                max_retries=settings.max_retries_send,
            )
            logger.info("Using Jupiter executor (live mode)")

        # Alert sink
        if settings.telegram_bot_token and settings.telegram_admin_ids:
            components["alerts"] = TelegramAlertSink(
                bot_token=settings.telegram_bot_token,
                admin_user_ids=settings.telegram_admin_ids,
            )
            logger.info("Using Telegram alert sink")
        else:
            components["alerts"] = NoopAlertSink()
            logger.info("Using noop alert sink (no Telegram config)")

        # Storage
        components["storage"] = SQLiteStorage(
            db_path=settings.database_url.replace("sqlite+aiosqlite:///", ""),
            parquet_dir=settings.parquet_dir,
            enable_parquet=True,
        )
        logger.info("Initialized SQLite storage")

        return components

    def _create_signer(self, settings: AppSettings) -> KeypairSigner | ExternalSigner:
        """Create a transaction signer for live trading.

        Args:
            settings: Application settings

        Returns:
            Configured signer instance

        Raises:
            ValueError: If no valid signer configuration is found
        """
        # Try KeypairSigner first (preferred)
        try:
            # Check for encrypted keypair file
            if hasattr(settings, "keypair_path_enc") and settings.keypair_path_enc:
                return KeypairSigner.from_encrypted_file(settings.keypair_path_enc)

            # Check for base58 secret key in environment
            if hasattr(settings, "solana_sk_b58") and settings.solana_sk_b58:
                return KeypairSigner.from_base58_secret(settings.solana_sk_b58)

            # Check for JSON keypair file
            if hasattr(settings, "keypair_path_json") and settings.keypair_path_json:
                return KeypairSigner.from_json_file(settings.keypair_path_json)

        except Exception as e:
            logger.warning("Failed to create KeypairSigner", error=str(e))

        # Try ExternalSigner as fallback
        try:
            if (
                hasattr(settings, "external_signer_command")
                and settings.external_signer_command
            ):
                return ExternalSigner(
                    command=settings.external_signer_command,
                    timeout_seconds=getattr(settings, "external_signer_timeout", 30),
                )
        except Exception as e:
            logger.warning("Failed to create ExternalSigner", error=str(e))

        raise ValueError(
            "No valid signer configuration found for live trading. "
            "Configure one of: keypair_path_enc, solana_sk_b58, keypair_path_json, or external_signer_command"
        )

    async def run_once(self) -> None:
        """Execute one trading cycle."""
        try:
            # Poll all data sources
            all_snapshots = []
            for data_source in self.components["data_sources"]:
                try:
                    snapshots = await data_source.poll()
                    all_snapshots.extend(snapshots)
                    logger.debug(
                        "Polled data source",
                        source=type(data_source).__name__,
                        count=len(snapshots),
                    )
                except Exception as e:
                    logger.error(
                        "Failed to poll data source",
                        source=type(data_source).__name__,
                        error=str(e),
                    )

            if not all_snapshots:
                logger.debug("No snapshots received from data sources")
                return

            # Merge snapshots by token mint (keep latest for each token)
            token_snapshots = {}
            for snapshot in all_snapshots:
                token_mint = snapshot.token.mint
                if (
                    token_mint not in token_snapshots
                    or snapshot.ts > token_snapshots[token_mint].ts
                ):
                    token_snapshots[token_mint] = snapshot

            logger.debug("Merged snapshots", unique_tokens=len(token_snapshots))

            # Process each token
            for _token_mint, snapshot in token_snapshots.items():
                await self._process_token(snapshot)

        except Exception as e:
            logger.error("Error in trading cycle", error=str(e))
            await self.components["alerts"].push(f"🚨 Trading cycle error: {str(e)}")

    async def _process_token(self, snapshot: TokenSnapshot) -> None:
        """Process a single token snapshot through the pipeline.

        Args:
            snapshot: Token snapshot to process
        """
        try:
            # Apply filters
            for filter_obj in self.components["filters"]:
                decision = filter_obj.evaluate(snapshot)
                if not decision.accepted:
                    logger.debug(
                        "Token filtered out",
                        token_mint=snapshot.token.mint,
                        filter=type(filter_obj).__name__,
                        reasons=decision.reasons,
                    )
                    return

            logger.info(
                "Token passed all filters",
                token_mint=snapshot.token.mint,
                price_usd=snapshot.price_usd,
                liq_usd=snapshot.liq_usd,
            )

            # Check risk management
            risk_manager = self.components["risk"]
            allowed, reasons = risk_manager.allow_buy(snapshot)
            if not allowed:
                logger.info(
                    "Token rejected by risk manager",
                    token_mint=snapshot.token.mint,
                    reasons=reasons,
                )
                return

            # Calculate position size
            position_size = risk_manager.size_usd(snapshot)
            if position_size <= 0:
                logger.debug("Zero position size", token_mint=snapshot.token.mint)
                return

            logger.info(
                "Token approved for trading",
                token_mint=snapshot.token.mint,
                position_size_usd=position_size,
            )

            # Simulate trade first
            exec_client = self.components["exec_client"]
            simulation = await exec_client.simulate(snapshot, position_size)

            logger.info(
                "Trade simulation completed",
                token_mint=snapshot.token.mint,
                input_amount=position_size,
                output_amount=simulation.get("qty_base", 0),
                price_impact=simulation.get("price_impact_pct", 0),
            )

            # Execute trade
            trade_result = await exec_client.buy(snapshot, position_size)

            # Record trade
            storage = self.components["storage"]
            trade_id = await storage.record_trade(
                token_mint=snapshot.token.mint,
                side="buy",
                qty=trade_result["qty_base"],
                px=trade_result["price_exec"],
                fee_usd=trade_result["fee_usd"],
            )

            # Update position
            await storage.upsert_position(
                token_mint=snapshot.token.mint,
                qty=trade_result["qty_base"],
                avg_cost_usd=trade_result["price_exec"],
            )

            # Send alert
            alert_msg = (
                f"🟢 <b>Trade Executed</b>\n\n"
                f"Token: <code>{snapshot.token.mint[:8]}...</code>\n"
                f"Amount: ${position_size:.2f}\n"
                f"Quantity: {trade_result['qty_base']:.6f}\n"
                f"Price: ${trade_result['price_exec']:.6f}\n"
                f"Fee: ${trade_result['fee_usd']:.2f}\n"
                f"Trade ID: {trade_id}"
            )
            await self.components["alerts"].push(alert_msg)

            # Update risk state
            risk_manager.after_fill(0.0)  # PnL will be calculated later

            logger.info(
                "Trade completed successfully",
                token_mint=snapshot.token.mint,
                trade_id=trade_id,
            )

        except Exception as e:
            logger.error(
                "Error processing token", token_mint=snapshot.token.mint, error=str(e)
            )

    async def run_forever(self) -> None:
        """Run the trading pipeline forever with configurable sleep intervals."""
        logger.info("Starting trading pipeline", dry_run=self.settings.dry_run)
        self.running = True

        # Send startup alert
        startup_msg = f"🤖 Trading bot started in {'paper' if self.settings.dry_run else 'live'} mode"
        await self.components["alerts"].push(startup_msg)

        cycle_count = 0
        start_time = datetime.now()

        try:
            while self.running:
                await self.run_once()

                cycle_count += 1

                # Log metrics every 10 cycles
                if cycle_count % 10 == 0:
                    uptime = (datetime.now() - start_time).total_seconds()
                    logger.info(
                        "Pipeline metrics",
                        cycles=cycle_count,
                        uptime_seconds=uptime,
                        avg_cycle_duration=uptime / cycle_count,
                    )

                # Sleep between cycles (configurable)
                sleep_duration = getattr(self.settings, "cycle_sleep_seconds", 30)
                await asyncio.sleep(sleep_duration)

        except asyncio.CancelledError:
            logger.info("Pipeline cancelled")
        except Exception as e:
            logger.error("Pipeline error", error=str(e))
            await self.components["alerts"].push(f"🚨 Pipeline error: {str(e)}")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the trading pipeline."""
        logger.info("Stopping trading pipeline")
        self.running = False

        # Send shutdown alert
        await self.components["alerts"].push("🛑 Trading bot stopped")

        # Close storage
        if "storage" in self.components:
            await self.components["storage"].close()


async def main() -> None:
    """Main entry point for the trading bot."""
    parser = argparse.ArgumentParser(description="Solana Trading Bot")
    parser.add_argument(
        "--config", default="configs/paper.yaml", help="Configuration file path"
    )
    parser.add_argument(
        "--profile",
        default="paper",
        choices=["dev", "paper", "prod"],
        help="Configuration profile",
    )

    args = parser.parse_args()

    try:
        # Load settings
        settings = load_settings(args.profile, args.config)
        logger.info("Settings loaded", profile=args.profile, config=args.config)

        # Create pipeline
        pipeline = TradingPipeline(settings)

        # Handle shutdown signals
        def signal_handler(signum, frame):
            logger.info("Received shutdown signal")
            asyncio.create_task(pipeline.stop())

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Run pipeline
        await pipeline.run_forever()

    except Exception as e:
        logger.error("Fatal error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
