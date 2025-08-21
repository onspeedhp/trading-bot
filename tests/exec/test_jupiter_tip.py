"""Unit tests for Jupiter tip instruction functionality."""

import pytest
from unittest.mock import MagicMock

from bot.exec.jupiter import JupiterExecutor


class TestJupiterTipInstruction:
    """Test Jupiter tip instruction functionality."""

    def test_should_add_tip_instruction_when_configured(self):
        """Test that tip instruction is enabled when properly configured."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=50000,
            tip_account_b58="J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
            signer=MagicMock(),
            sender=MagicMock(),
        )

        assert executor._should_add_tip_instruction() is True

    def test_should_not_add_tip_instruction_when_tip_zero(self):
        """Test that tip instruction is disabled when tip amount is zero."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=0,  # Zero tip
            tip_account_b58="J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
            signer=MagicMock(),
            sender=MagicMock(),
        )

        assert executor._should_add_tip_instruction() is False

    def test_should_not_add_tip_instruction_when_no_account(self):
        """Test that tip instruction is disabled when tip account is not provided."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=50000,
            tip_account_b58=None,  # No tip account
            signer=MagicMock(),
            sender=MagicMock(),
        )

        assert executor._should_add_tip_instruction() is False

    def test_should_not_add_tip_instruction_when_empty_account(self):
        """Test that tip instruction is disabled when tip account is empty string."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=50000,
            tip_account_b58="",  # Empty tip account
            signer=MagicMock(),
            sender=MagicMock(),
        )

        assert executor._should_add_tip_instruction() is False

    def test_should_not_add_tip_instruction_when_whitespace_account(self):
        """Test that tip instruction is disabled when tip account is whitespace."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=50000,
            tip_account_b58="   ",  # Whitespace tip account
            signer=MagicMock(),
            sender=MagicMock(),
        )

        assert executor._should_add_tip_instruction() is False

    def test_add_tip_instruction_when_not_configured(self):
        """Test that add_tip_instruction returns original transaction when not configured."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=0,  # Not configured
            tip_account_b58=None,
            signer=MagicMock(),
            sender=MagicMock(),
        )

        original_tx = b"fake_transaction_bytes"
        result = executor._add_tip_instruction(original_tx)

        assert result == original_tx

    def test_add_tip_instruction_when_configured(self):
        """Test that add_tip_instruction logs intention when configured."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=50000,
            tip_account_b58="J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
            signer=MagicMock(),
            sender=MagicMock(),
        )

        original_tx = b"fake_transaction_bytes"
        result = executor._add_tip_instruction(original_tx)

        # Currently returns original transaction (placeholder implementation)
        assert result == original_tx

    def test_constructor_with_tip_account(self):
        """Test that constructor properly stores tip account."""
        tip_account = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"

        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=50000,
            tip_account_b58=tip_account,
            signer=MagicMock(),
            sender=MagicMock(),
        )

        assert executor.tip_account_b58 == tip_account
        assert executor.jito_tip_lamports == 50000

    def test_constructor_without_tip_account(self):
        """Test that constructor works without tip account."""
        executor = JupiterExecutor(
            base_url="https://quote-api.jup.ag/v6",
            rpc_url="https://api.mainnet-beta.solana.com",
            max_slippage_bps=100,
            priority_fee_microlamports=1000,
            compute_unit_limit=120000,
            jito_tip_lamports=0,
            tip_account_b58=None,
            signer=MagicMock(),
            sender=MagicMock(),
        )

        assert executor.tip_account_b58 is None
        assert executor.jito_tip_lamports == 0
