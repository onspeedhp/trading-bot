"""Telegram alert system for trading notifications."""

import json
from typing import Any, Protocol, runtime_checkable

import httpx
import structlog

from ..core.interfaces import AlertSink

logger = structlog.get_logger(__name__)


@runtime_checkable
class StatusProvider(Protocol):
    """Protocol for status callback provider."""

    def get_status(self) -> dict[str, Any]:
        """Get current system status."""
        ...


class TelegramAlertSink(AlertSink):
    """Telegram-based alert sink implementation."""

    def __init__(
        self,
        bot_token: str,
        admin_user_ids: list[int],
        session: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize Telegram alert sink.

        Args:
            bot_token: Telegram bot token
            admin_user_ids: List of admin user IDs to send alerts to
            session: Optional HTTP session for requests
        """
        self.bot_token = bot_token
        self.admin_user_ids = admin_user_ids
        self.session = session or httpx.AsyncClient()
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

        logger.info(
            "Telegram alert sink initialized",
            admin_count=len(admin_user_ids),
            base_url=self.base_url,
        )

    async def push(self, message: str) -> None:
        """Push alert message to all admin users.

        Args:
            message: Alert message to send
        """
        if not self.admin_user_ids:
            logger.warning("No admin users configured, skipping alert")
            return

        success_count = 0
        for user_id in self.admin_user_ids:
            try:
                await self._send_message(user_id, message)
                success_count += 1
                logger.debug("Alert sent to admin", user_id=user_id)
            except Exception as e:
                logger.error(
                    "Failed to send alert to admin", user_id=user_id, error=str(e)
                )

        logger.info(
            "Alert push completed",
            total_admins=len(self.admin_user_ids),
            success_count=success_count,
        )

    async def _send_message(self, chat_id: int, text: str) -> None:
        """Send message to specific chat ID.

        Args:
            chat_id: Telegram chat ID
            text: Message text
        """
        url = f"{self.base_url}/sendMessage"
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

        response = await self.session.post(url, json=data)
        response.raise_for_status()

        result = response.json()
        if not result.get("ok"):
            raise Exception(
                f"Telegram API error: {result.get('description', 'Unknown error')}"
            )

    async def handle_command(
        self,
        chat_id: int,
        command: str,
        status_provider: StatusProvider | None = None,
    ) -> str:
        """Handle incoming Telegram commands.

        Args:
            chat_id: Telegram chat ID
            command: Command text (e.g., "/status")
            status_provider: Optional status provider for /status command

        Returns:
            Response message
        """
        if not command.startswith("/"):
            return "Invalid command format"

        cmd_parts = command.split()
        cmd = cmd_parts[0].lower()

        if cmd == "/status":
            return await self._handle_status_command(status_provider)
        elif cmd == "/help":
            return self._handle_help_command()
        else:
            return f"Unknown command: {cmd}"

    async def _handle_status_command(
        self, status_provider: StatusProvider | None
    ) -> str:
        """Handle /status command.

        Args:
            status_provider: Status provider callback

        Returns:
            Status response message
        """
        if status_provider is None:
            return "⚠️ Status provider not available"

        try:
            status = status_provider.get_status()
            status_json = json.dumps(status, indent=2, default=str)

            # Telegram has a 4096 character limit for messages
            if len(status_json) > 4000:
                status_json = status_json[:4000] + "\n... (truncated)"

            return f"📊 <b>System Status</b>\n\n<pre>{status_json}</pre>"

        except Exception as e:
            logger.error("Failed to get status", error=str(e))
            return f"❌ Error getting status: {str(e)}"

    def _handle_help_command(self) -> str:
        """Handle /help command.

        Returns:
            Help message
        """
        return (
            "🤖 <b>Trading Bot Commands</b>\n\n"
            "<b>/status</b> - Get current system status\n"
            "<b>/help</b> - Show this help message\n\n"
            "All alerts will be sent automatically to configured admins."
        )

    async def close(self) -> None:
        """Close the alert sink and cleanup resources."""
        if self.session:
            await self.session.aclose()
        logger.info("Telegram alert sink closed")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


# Minimal command handler wiring (to be used in runner/pipeline.py)
class TelegramCommandHandler:
    """Minimal command handler for Telegram bot integration."""

    def __init__(self, alert_sink: TelegramAlertSink) -> None:
        """Initialize command handler.

        Args:
            alert_sink: Telegram alert sink instance
        """
        self.alert_sink = alert_sink
        self.status_provider: StatusProvider | None = None

        logger.info("Telegram command handler initialized")

    def set_status_provider(self, provider: StatusProvider) -> None:
        """Set status provider for /status command.

        Args:
            provider: Status provider instance
        """
        self.status_provider = provider
        logger.debug("Status provider set")

    async def handle_update(self, update: dict[str, Any]) -> None:
        """Handle incoming Telegram update.

        Args:
            update: Telegram update object
        """
        try:
            message = update.get("message", {})
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "")

            if not chat_id or not text:
                return

            # Check if sender is an admin
            user_id = message.get("from", {}).get("id")
            if user_id not in self.alert_sink.admin_user_ids:
                logger.warning("Unauthorized command attempt", user_id=user_id)
                return

            # Handle command
            response = await self.alert_sink.handle_command(
                chat_id, text, self.status_provider
            )

            # Send response
            await self.alert_sink._send_message(chat_id, response)

            logger.info("Command handled", command=text, user_id=user_id)

        except Exception as e:
            logger.error("Failed to handle update", error=str(e))
