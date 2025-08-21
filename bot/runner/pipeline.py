"""Main trading pipeline runner."""

import asyncio
import argparse
import signal
import sys
from typing import List
import structlog

from ..config.settings import Settings
from ..core.types import TradeSignal, OrderSide, OrderType
from ..data.helius import HeliusProvider
from ..data.birdeye import BirdeyeProvider
from ..data.dexscreener import DexScreenerProvider
from ..filters.basic import VolumeFilter, PriceChangeFilter, LiquidityFilter
from ..filters.rug_heuristics import (
    RugPullFilter,
    ContractVerificationFilter,
    HoneypotFilter,
)
from ..risk.manager import RiskManagerImpl
from ..exec.paper import PaperTradingEngine
from ..exec.jupiter import JupiterExecutionEngine
from ..alerts.telegram import TelegramAlertSystem
from ..persist.storage import FileStorage

logger = structlog.get_logger(__name__)


class TradingPipeline:
    """Main trading pipeline orchestrator."""

    def __init__(self, settings: Settings) -> None:
        """Initialize trading pipeline."""
        self.settings = settings
        self.running = False

        # Initialize components
        self.risk_manager = RiskManagerImpl(settings)
        self.alert_system = TelegramAlertSystem(settings)
        self.storage = FileStorage()

        # Initialize execution engine based on mode
        if settings.mode == "paper":
            self.execution_engine = PaperTradingEngine()
        else:
            self.execution_engine = JupiterExecutionEngine()

        # Initialize filters
        self.filters = [
            VolumeFilter(),
            PriceChangeFilter(),
            LiquidityFilter(),
            RugPullFilter(),
            ContractVerificationFilter(),
            HoneypotFilter(),
        ]

    async def start(self) -> None:
        """Start the trading pipeline."""
        logger.info("Starting trading pipeline", mode=self.settings.mode)
        self.running = True

        # Send startup alert
        await self.alert_system.send_alert(
            f"Trading bot started in {self.settings.mode} mode", level="info"
        )

        try:
            # Main trading loop
            while self.running:
                await self._trading_cycle()
                await asyncio.sleep(1)  # Cycle every second

        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.error("Pipeline error", error=str(e))
            await self.alert_system.send_alert(
                f"Trading pipeline error: {str(e)}", level="error"
            )
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the trading pipeline."""
        logger.info("Stopping trading pipeline")
        self.running = False

        # Send shutdown alert
        await self.alert_system.send_alert("Trading bot stopped", level="info")

    async def _trading_cycle(self) -> None:
        """Execute one trading cycle."""
        try:
            # Generate trading signals (placeholder)
            signals = await self._generate_signals()

            for signal in signals:
                # Apply filters
                filtered_signal = await self._apply_filters(signal)
                if not filtered_signal:
                    continue

                # Check risk limits
                if not await self.risk_manager.check_risk_limits(filtered_signal):
                    logger.warning(
                        "Signal rejected by risk manager", token=signal.token_address
                    )
                    continue

                # Calculate position size
                position_size = await self.risk_manager.calculate_position_size(
                    filtered_signal
                )
                if position_size <= 0:
                    continue

                # Update signal with calculated position size
                filtered_signal.quantity = position_size

                # Execute trade
                order = await self.execution_engine.place_order(filtered_signal)

                # Save order and signal
                await self.storage.save_order(order)
                await self.storage.save_signal(filtered_signal)

                # Send alerts
                await self.alert_system.send_trade_alert(order)

                logger.info(
                    "Trade executed", order_id=order.id, token=signal.token_address
                )

        except Exception as e:
            logger.error("Trading cycle error", error=str(e))

    async def _generate_signals(self) -> List[TradeSignal]:
        """Generate trading signals (placeholder implementation)."""
        # This would implement actual signal generation logic
        # For now, return empty list
        return []

    async def _apply_filters(self, signal: TradeSignal) -> TradeSignal | None:
        """Apply all filters to a trading signal."""
        for filter_obj in self.filters:
            filtered_signal = await filter_obj.filter_signal(signal)
            if not filtered_signal:
                logger.info(
                    "Signal filtered out",
                    token=signal.token_address,
                    filter=filter_obj.__class__.__name__,
                )
                return None
            signal = filtered_signal

        return signal


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Solana Trading Bot")
    parser.add_argument(
        "--mode", choices=["paper", "live"], default="paper", help="Trading mode"
    )
    parser.add_argument(
        "--config", default="configs/paper.yaml", help="Configuration file"
    )

    args = parser.parse_args()

    # Initialize settings
    settings = Settings(mode=args.mode)

    # Configure logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Create and run pipeline
    pipeline = TradingPipeline(settings)

    # Handle shutdown signals
    def signal_handler(signum, frame):
        logger.info("Received shutdown signal")
        asyncio.create_task(pipeline.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await pipeline.start()
    except Exception as e:
        logger.error("Fatal error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
