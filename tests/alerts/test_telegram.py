"""Tests for Telegram alert system."""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from bot.alerts.telegram import (
    StatusProvider,
    TelegramAlertSink,
    TelegramCommandHandler,
)


class MockStatusProvider:
    """Mock status provider for testing."""

    def __init__(self, status_data: dict):
        self.status_data = status_data

    def get_status(self) -> dict:
        return self.status_data


class TestTelegramAlertSink:
    """Test Telegram alert sink functionality."""

    @pytest.fixture
    def alert_sink(self):
        """Create a test alert sink."""
        return TelegramAlertSink(
            bot_token="test_token_123",
            admin_user_ids=[12345, 67890],
            session=AsyncMock(spec=httpx.AsyncClient),
        )

    @pytest.mark.asyncio
    async def test_initialization(self, alert_sink):
        """Test alert sink initialization."""
        assert alert_sink.bot_token == "test_token_123"
        assert alert_sink.admin_user_ids == [12345, 67890]
        assert alert_sink.base_url == "https://api.telegram.org/bottest_token_123"

    @pytest.mark.asyncio
    async def test_push_message_success(self, alert_sink):
        """Test successful message push."""
        # Mock successful responses
        mock_response = AsyncMock()
        mock_response.json = MagicMock(
            return_value={"ok": True, "result": {"message_id": 123}}
        )
        mock_response.raise_for_status = MagicMock()

        alert_sink.session.post.return_value = mock_response

        await alert_sink.push("Test alert message")

        # Verify calls to both admin users
        assert alert_sink.session.post.call_count == 2

        # Check first call
        first_call = alert_sink.session.post.call_args_list[0]
        assert (
            first_call[0][0] == "https://api.telegram.org/bottest_token_123/sendMessage"
        )
        assert first_call[1]["json"]["chat_id"] == 12345
        assert first_call[1]["json"]["text"] == "Test alert message"
        assert first_call[1]["json"]["parse_mode"] == "HTML"

        # Check second call
        second_call = alert_sink.session.post.call_args_list[1]
        assert second_call[1]["json"]["chat_id"] == 67890

    @pytest.mark.asyncio
    async def test_push_message_no_admins(self):
        """Test push with no admin users."""
        alert_sink = TelegramAlertSink(
            bot_token="test_token",
            admin_user_ids=[],
            session=AsyncMock(spec=httpx.AsyncClient),
        )

        await alert_sink.push("Test message")

        # Should not make any HTTP calls
        alert_sink.session.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_push_message_partial_failure(self, alert_sink):
        """Test push with partial failures."""
        # Mock first call success, second call failure
        mock_success = AsyncMock()
        mock_success.json.return_value = {"ok": True}
        mock_success.raise_for_status.return_value = None

        mock_failure = AsyncMock()
        mock_failure.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Error", request=MagicMock(), response=MagicMock()
        )

        alert_sink.session.post.side_effect = [mock_success, mock_failure]

        await alert_sink.push("Test message")

        # Should still make both calls
        assert alert_sink.session.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_message_telegram_error(self, alert_sink):
        """Test handling of Telegram API errors."""
        mock_response = AsyncMock()
        mock_response.json = MagicMock(
            return_value={"ok": False, "description": "Bad Request"}
        )
        mock_response.raise_for_status = MagicMock()

        alert_sink.session.post.return_value = mock_response

        with pytest.raises(Exception, match="Telegram API error: Bad Request"):
            await alert_sink._send_message(12345, "Test message")

    @pytest.mark.asyncio
    async def test_handle_help_command(self, alert_sink):
        """Test help command handling."""
        response = alert_sink._handle_help_command()

        assert "🤖" in response
        assert "/status" in response
        assert "/help" in response
        assert "Trading Bot Commands" in response

    @pytest.mark.asyncio
    async def test_handle_status_command_with_provider(self, alert_sink):
        """Test status command with provider."""
        status_data = {
            "uptime": "2h 30m",
            "positions": 3,
            "total_pnl": 125.50,
            "last_trade": "2024-01-01T12:00:00Z",
        }
        provider = MockStatusProvider(status_data)

        response = await alert_sink._handle_status_command(provider)

        assert "📊" in response
        assert "System Status" in response
        assert "uptime" in response
        assert "2h 30m" in response

    @pytest.mark.asyncio
    async def test_handle_status_command_no_provider(self, alert_sink):
        """Test status command without provider."""
        response = await alert_sink._handle_status_command(None)

        assert "⚠️" in response
        assert "not available" in response

    @pytest.mark.asyncio
    async def test_handle_status_command_large_response(self, alert_sink):
        """Test status command with large response."""
        # Create a large status response
        large_data = {"data": "x" * 5000}
        provider = MockStatusProvider(large_data)

        response = await alert_sink._handle_status_command(provider)

        assert len(response) <= 4096  # Telegram limit
        assert "... (truncated)" in response

    @pytest.mark.asyncio
    async def test_handle_command_invalid_format(self, alert_sink):
        """Test command handling with invalid format."""
        response = await alert_sink.handle_command(12345, "not_a_command")

        assert response == "Invalid command format"

    @pytest.mark.asyncio
    async def test_handle_command_unknown(self, alert_sink):
        """Test handling of unknown commands."""
        response = await alert_sink.handle_command(12345, "/unknown")

        assert "Unknown command" in response

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        mock_session = AsyncMock(spec=httpx.AsyncClient)

        async with TelegramAlertSink("test_token", [12345], mock_session) as sink:
            assert isinstance(sink, TelegramAlertSink)

        # Should close session
        mock_session.aclose.assert_called_once()


class TestTelegramCommandHandler:
    """Test Telegram command handler."""

    @pytest.fixture
    def alert_sink(self):
        """Create a test alert sink."""
        return TelegramAlertSink(
            bot_token="test_token",
            admin_user_ids=[12345],
            session=AsyncMock(spec=httpx.AsyncClient),
        )

    @pytest.fixture
    def command_handler(self, alert_sink):
        """Create a test command handler."""
        return TelegramCommandHandler(alert_sink)

    def test_initialization(self, command_handler):
        """Test command handler initialization."""
        assert command_handler.alert_sink is not None
        assert command_handler.status_provider is None

    def test_set_status_provider(self, command_handler):
        """Test setting status provider."""
        provider = MockStatusProvider({"test": "data"})
        command_handler.set_status_provider(provider)

        assert command_handler.status_provider == provider

    @pytest.mark.asyncio
    async def test_handle_update_valid_command(self, command_handler):
        """Test handling valid command update."""
        # Mock successful response
        mock_response = AsyncMock()
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()
        command_handler.alert_sink.session.post.return_value = mock_response

        update = {
            "message": {"chat": {"id": 12345}, "from": {"id": 12345}, "text": "/help"}
        }

        await command_handler.handle_update(update)

        # Should send response
        command_handler.alert_sink.session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_update_unauthorized_user(self, command_handler):
        """Test handling update from unauthorized user."""
        update = {
            "message": {
                "chat": {"id": 99999},
                "from": {"id": 99999},  # Not in admin list
                "text": "/help",
            }
        }

        await command_handler.handle_update(update)

        # Should not send any response
        command_handler.alert_sink.session.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_update_missing_fields(self, command_handler):
        """Test handling update with missing fields."""
        # Missing chat_id
        update1 = {"message": {"from": {"id": 12345}, "text": "/help"}}
        await command_handler.handle_update(update1)

        # Missing text
        update2 = {"message": {"chat": {"id": 12345}, "from": {"id": 12345}}}
        await command_handler.handle_update(update2)

        # Should not send any responses
        command_handler.alert_sink.session.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_update_status_command(self, command_handler):
        """Test handling status command."""
        # Set up status provider
        provider = MockStatusProvider({"uptime": "1h", "positions": 2})
        command_handler.set_status_provider(provider)

        # Mock successful response
        mock_response = AsyncMock()
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()
        command_handler.alert_sink.session.post.return_value = mock_response

        update = {
            "message": {"chat": {"id": 12345}, "from": {"id": 12345}, "text": "/status"}
        }

        await command_handler.handle_update(update)

        # Should send response with status
        call_args = command_handler.alert_sink.session.post.call_args
        response_text = call_args[1]["json"]["text"]
        assert "📊" in response_text
        assert "uptime" in response_text


class TestTelegramIntegration:
    """Integration tests with respx HTTP mocking."""

    @pytest.mark.asyncio
    async def test_telegram_api_integration(self):
        """Test integration with Telegram API using respx."""
        with respx.mock as respx_mock:
            # Mock successful sendMessage response
            respx_mock.post("https://api.telegram.org/bottest_token/sendMessage").mock(
                return_value=httpx.Response(
                    200, json={"ok": True, "result": {"message_id": 123}}
                )
            )

            alert_sink = TelegramAlertSink("test_token", [12345])

            await alert_sink.push("Integration test message")

            # Verify request was made
            assert respx_mock.calls.call_count == 1
            call = respx_mock.calls[0]
            assert (
                call.request.url == "https://api.telegram.org/bottest_token/sendMessage"
            )

            # Verify request data
            request_data = json.loads(call.request.content)
            assert request_data["chat_id"] == 12345
            assert request_data["text"] == "Integration test message"
            assert request_data["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_telegram_api_error_handling(self):
        """Test handling of Telegram API errors."""
        with respx.mock as respx_mock:
            # Mock error response (200 status but ok=False)
            respx_mock.post("https://api.telegram.org/bottest_token/sendMessage").mock(
                return_value=httpx.Response(
                    200, json={"ok": False, "description": "Bad Request"}
                )
            )

            alert_sink = TelegramAlertSink("test_token", [12345])

            with pytest.raises(Exception, match="Telegram API error: Bad Request"):
                await alert_sink._send_message(12345, "Test message")

    @pytest.mark.asyncio
    async def test_telegram_api_http_error(self):
        """Test handling of HTTP errors."""
        with respx.mock as respx_mock:
            # Mock HTTP error
            respx_mock.post("https://api.telegram.org/bottest_token/sendMessage").mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )

            alert_sink = TelegramAlertSink("test_token", [12345])

            with pytest.raises(httpx.HTTPStatusError):
                await alert_sink._send_message(12345, "Test message")


class TestStatusProviderProtocol:
    """Test StatusProvider protocol compliance."""

    def test_mock_status_provider_compliance(self):
        """Test that MockStatusProvider implements StatusProvider protocol."""
        provider = MockStatusProvider({"test": "data"})

        # Should be able to call get_status
        status = provider.get_status()
        assert isinstance(status, dict)
        assert status["test"] == "data"

        # Should be compatible with StatusProvider type
        assert isinstance(provider, StatusProvider)
