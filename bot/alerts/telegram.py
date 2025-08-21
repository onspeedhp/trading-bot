"""Telegram alert system for trading notifications."""

from typing import Optional
import structlog
from telegram import Bot
from telegram.error import TelegramError

from ..core.interfaces import AlertSystem
from ..core.types import Order
from ..config.settings import Settings

logger = structlog.get_logger(__name__)


class TelegramAlertSystem(AlertSystem):
    """Telegram-based alert system."""

    def __init__(self, settings: Settings) -> None:
        """Initialize Telegram alert system."""
        self.settings = settings
        self.bot: Optional[Bot] = None
        self.chat_id = settings.telegram_chat_id

        if settings.telegram_bot_token:
            self.bot = Bot(token=settings.telegram_bot_token)

    async def send_alert(self, message: str, level: str = "info") -> bool:
        """Send a general alert message."""
        if not self.bot or not self.chat_id:
            logger.warning("Telegram not configured, skipping alert")
            return False

        try:
            # Add level emoji
            emoji_map = {"info": "ℹ️", "warning": "⚠️", "error": "🚨", "success": "✅"}
            emoji = emoji_map.get(level, "ℹ️")

            formatted_message = f"{emoji} {message}"

            await self.bot.send_message(
                chat_id=self.chat_id, text=formatted_message, parse_mode="HTML"
            )

            logger.info("Telegram alert sent", level=level)
            return True

        except TelegramError as e:
            logger.error("Failed to send Telegram alert", error=str(e))
            return False
        except Exception as e:
            logger.error("Unexpected error sending Telegram alert", error=str(e))
            return False

    async def send_trade_alert(self, order: Order) -> bool:
        """Send a trade-specific alert."""
        if not self.bot or not self.chat_id:
            logger.warning("Telegram not configured, skipping trade alert")
            return False

        try:
            # Create trade alert message
            side_emoji = "🟢" if order.side.value == "buy" else "🔴"
            status_emoji = "✅" if order.status == "filled" else "⏳"

            message = (
                f"<b>Trade Alert</b>\n\n"
                f"{side_emoji} <b>{order.side.value.upper()}</b> {status_emoji}\n"
                f"Token: <code>{order.token_address[:8]}...</code>\n"
                f"Quantity: {order.quantity}\n"
                f"Price: ${order.average_price or order.price or 'N/A'}\n"
                f"Status: {order.status}\n"
                f"Time: {order.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            await self.bot.send_message(
                chat_id=self.chat_id, text=message, parse_mode="HTML"
            )

            logger.info("Trade alert sent", order_id=order.id)
            return True

        except TelegramError as e:
            logger.error("Failed to send trade alert", error=str(e))
            return False
        except Exception as e:
            logger.error("Unexpected error sending trade alert", error=str(e))
            return False
