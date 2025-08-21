"""Tests for transaction signers."""

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
import pytest

from bot.exec.signers import (
    TxnSigner,
    KeypairSigner,
    ExternalSigner,
    load_base58_secret,
    load_base58_secret_from_string,
    load_json_keypair,
    SOLDERS_AVAILABLE,
    BASE58_AVAILABLE,
)


class TestTxnSignerProtocol:
    """Test the TxnSigner protocol compliance."""

    def test_protocol_definition(self):
        """Test that TxnSigner protocol is properly defined."""
        # This should not raise any errors
        assert hasattr(TxnSigner, "__call__")
        # Protocols don't have __annotations__ in the same way
        # Just verify the protocol exists
        assert TxnSigner is not None


class TestKeypairSigner:
    """Test KeypairSigner functionality."""

    def test_solders_not_available(self):
        """Test that KeypairSigner raises ImportError when solders is missing."""
        with patch("bot.exec.signers.SOLDERS_AVAILABLE", False):
            with pytest.raises(ImportError, match="solders package is required"):
                KeypairSigner()

    @pytest.mark.skipif(not SOLDERS_AVAILABLE, reason="solders not available")
    def test_keypair_initialization(self):
        """Test KeypairSigner initialization with mock keypair."""
        with patch("bot.exec.signers.solders_keypair") as mock_solders:
            # Mock keypair
            mock_keypair = Mock()
            mock_keypair.pubkey.return_value = "TestPubkey123"
            mock_solders.Keypair.from_bytes.return_value = mock_keypair

            # Mock the _load_keypair method to return our mock
            with patch.object(
                KeypairSigner, "_load_keypair", return_value=mock_keypair
            ):
                signer = KeypairSigner()

                assert signer.pubkey_base58() == "TestPubkey123"
                assert signer.keypair == mock_keypair

    @pytest.mark.skipif(not SOLDERS_AVAILABLE, reason="solders not available")
    def test_sign_transaction(self):
        """Test transaction signing."""
        with patch("bot.exec.signers.solders_keypair") as mock_solders:
            # Mock keypair and signature
            mock_keypair = Mock()
            mock_signature = Mock()
            mock_signature.__bytes__ = lambda: b"test_signature"
            mock_keypair.sign_message.return_value = mock_signature
            mock_solders.Keypair.from_bytes.return_value = mock_keypair

            with patch.object(
                KeypairSigner, "_load_keypair", return_value=mock_keypair
            ):
                signer = KeypairSigner()

                txn_bytes = b"test_transaction"
                signed = signer.sign_transaction(txn_bytes)

                assert signed == b"test_signature" + txn_bytes
                mock_keypair.sign_message.assert_called_once_with(txn_bytes)

    @pytest.mark.skipif(not SOLDERS_AVAILABLE, reason="solders not available")
    def test_load_keypair_no_sources(self):
        """Test that KeypairSigner raises error when no valid sources are provided."""
        with patch("bot.exec.signers.solders_keypair"):
            with patch.object(
                KeypairSigner,
                "_load_encrypted_keypair",
                side_effect=Exception("Failed"),
            ):
                with patch(
                    "bot.exec.signers.load_base58_secret",
                    side_effect=Exception("Failed"),
                ):
                    with patch(
                        "bot.exec.signers.load_json_keypair",
                        side_effect=Exception("Failed"),
                    ):
                        with pytest.raises(
                            ValueError, match="No valid keypair source found"
                        ):
                            KeypairSigner()


class TestExternalSigner:
    """Test ExternalSigner functionality."""

    def test_external_signer_initialization(self):
        """Test ExternalSigner initialization."""
        with patch.object(ExternalSigner, "_get_pubkey", return_value="TestPubkey456"):
            signer = ExternalSigner("test_command", ["--arg1", "--arg2"], timeout=60)

            assert signer.command == "test_command"
            assert signer.args == ["--arg1", "--arg2"]
            assert signer.timeout == 60
            assert signer.pubkey == "TestPubkey456"

    def test_pubkey_base58(self):
        """Test pubkey_base58 method."""
        signer = ExternalSigner("test_command")
        signer.pubkey = "TestPubkey789"

        assert signer.pubkey_base58() == "TestPubkey789"

    def test_sign_transaction_success(self):
        """Test successful transaction signing."""
        with patch("subprocess.run") as mock_run:
            # Mock successful subprocess execution
            mock_result = Mock()
            # Use a valid base64 string
            mock_result.stdout = (
                base64.b64encode(b"test_signed_data").decode("utf-8") + "\n"
            )
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            # Create signer without calling _get_pubkey during init
            signer = ExternalSigner.__new__(ExternalSigner)
            signer.command = "test_command"
            signer.args = []
            signer.timeout = 30
            signer.pubkey = (
                "TestPubkey123"  # Set pubkey directly to avoid _get_pubkey call
            )

            txn_bytes = b"test_transaction"
            signed = signer.sign_transaction(txn_bytes)

            # Verify command was called correctly
            expected_cmd = ["test_command", base64.b64encode(txn_bytes).decode("utf-8")]
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == expected_cmd

            # Verify subprocess parameters
            assert call_args[1]["capture_output"] is True
            assert call_args[1]["text"] is True
            assert call_args[1]["timeout"] == 30
            assert call_args[1]["check"] is True

            # Verify result
            assert signed == b"test_signed_data"

    def test_sign_transaction_timeout(self):
        """Test transaction signing timeout."""
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("test_command", 30)
        ):
            signer = ExternalSigner("test_command")

            with pytest.raises(
                TimeoutError, match="External signing command timed out"
            ):
                signer.sign_transaction(b"test_transaction")

    def test_sign_transaction_command_failure(self):
        """Test transaction signing when command fails."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1, "test_command", stderr="Error"
            ),
        ):
            signer = ExternalSigner("test_command")

            with pytest.raises(RuntimeError, match="External signing command failed"):
                signer.sign_transaction(b"test_transaction")

    def test_sign_transaction_empty_output(self):
        """Test transaction signing with empty output."""
        with patch("subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.stdout = ""
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            # Create signer without calling _get_pubkey during init
            signer = ExternalSigner.__new__(ExternalSigner)
            signer.command = "test_command"
            signer.args = []
            signer.timeout = 30
            signer.pubkey = (
                "TestPubkey123"  # Set pubkey directly to avoid _get_pubkey call
            )

            with pytest.raises(
                RuntimeError, match="Failed to execute external signing command: External command returned empty output"
            ):
                signer.sign_transaction(b"test_transaction")

    def test_get_pubkey_success(self):
        """Test successful public key retrieval."""
        with patch("subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.stdout = "TestPubkey123\n"
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            # Create signer without calling _get_pubkey during init
            signer = ExternalSigner.__new__(ExternalSigner)
            signer.command = "test_command"
            signer.args = []
            signer.timeout = 30

            pubkey = signer._get_pubkey()

            assert pubkey == "TestPubkey123"
            mock_run.assert_called_once_with(
                ["test_command", "--pubkey"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

    def test_get_pubkey_failure(self):
        """Test public key retrieval failure."""
        with patch("subprocess.run", side_effect=Exception("Command failed")):
            # Create signer without calling _get_pubkey during init
            signer = ExternalSigner.__new__(ExternalSigner)
            signer.command = "test_command"
            signer.args = []
            signer.timeout = 30
            
            pubkey = signer._get_pubkey()

            assert pubkey == "unknown"


class TestHelperFunctions:
    """Test helper functions for loading secrets."""

    def test_load_base58_secret_env_not_set(self):
        """Test load_base58_secret when environment variable is not set."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(
                ValueError, match="Environment variable TEST_ENV not set"
            ):
                load_base58_secret("TEST_ENV")

    @pytest.mark.skipif(not BASE58_AVAILABLE, reason="base58 not available")
    def test_load_base58_secret_from_string_valid(self):
        """Test loading valid base58 secret key."""
        # Create a valid 64-byte secret key
        valid_secret = "1" * 88  # base58 encoding of 64 bytes of 1s
        result = load_base58_secret_from_string(valid_secret)

        assert len(result) == 64

    @pytest.mark.skipif(not BASE58_AVAILABLE, reason="base58 not available")
    def test_load_base58_secret_from_string_invalid_length(self):
        """Test loading base58 secret key with invalid length."""
        # Create an invalid length secret key
        invalid_secret = "1" * 50  # Too short
        with pytest.raises(ValueError, match="Invalid secret key length"):
            load_base58_secret_from_string(invalid_secret)

    @pytest.mark.skipif(not BASE58_AVAILABLE, reason="base58 not available")
    def test_load_base58_secret_from_string_invalid_base58(self):
        """Test loading invalid base58 string."""
        with pytest.raises(ValueError, match="Invalid base58 secret key"):
            load_base58_secret_from_string("invalid_base58!")

    def test_load_json_keypair_array_format(self):
        """Test loading JSON keypair in array format."""
        # Create a valid 64-byte array
        keypair_data = [1] * 64

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(keypair_data, f)
            temp_path = f.name

        try:
            result = load_json_keypair(temp_path)
            assert len(result) == 64
            assert all(b == 1 for b in result)
        finally:
            os.unlink(temp_path)

    def test_load_json_keypair_dict_format(self):
        """Test loading JSON keypair in dictionary format."""
        # Create a valid dictionary format
        keypair_data = {"secretKey": [1] * 64}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(keypair_data, f)
            temp_path = f.name

        try:
            result = load_json_keypair(temp_path)
            assert len(result) == 64
            assert all(b == 1 for b in result)
        finally:
            os.unlink(temp_path)

    def test_load_json_keypair_dict_format_base58(self):
        """Test loading JSON keypair in dictionary format with base58 string."""
        # Create a valid dictionary format with base58 string
        keypair_data = {"secretKey": "1" * 88}  # base58 encoding of 64 bytes

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(keypair_data, f)
            temp_path = f.name

        try:
            if BASE58_AVAILABLE:
                result = load_json_keypair(temp_path)
                assert len(result) == 64
            else:
                with pytest.raises(ValueError, match="base58 package is required"):
                    load_json_keypair(temp_path)
        finally:
            os.unlink(temp_path)

    def test_load_json_keypair_invalid_format(self):
        """Test loading JSON keypair with invalid format."""
        # Create an invalid format
        keypair_data = {"invalid": "format"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(keypair_data, f)
            temp_path = f.name

        try:
            with pytest.raises(
                ValueError,
                match="JSON keypair file does not contain valid secretKey field",
            ):
                load_json_keypair(temp_path)
        finally:
            os.unlink(temp_path)

    def test_load_json_keypair_invalid_length(self):
        """Test loading JSON keypair with invalid array length."""
        # Create an array with wrong length
        keypair_data = [1] * 50  # Too short

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(keypair_data, f)
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="Invalid keypair array length"):
                load_json_keypair(temp_path)
        finally:
            os.unlink(temp_path)

    def test_load_json_keypair_file_not_found(self):
        """Test loading JSON keypair from non-existent file."""
        with pytest.raises(ValueError, match="Failed to load JSON keypair"):
            load_json_keypair("/nonexistent/file.json")


class TestMissingDependencies:
    """Test behavior when dependencies are missing."""

    def test_base58_not_available(self):
        """Test behavior when base58 is not available."""
        with patch("bot.exec.signers.BASE58_AVAILABLE", False):
            with pytest.raises(ImportError, match="base58 package is required"):
                load_base58_secret_from_string("test")

    def test_solders_not_available(self):
        """Test behavior when solders is not available."""
        with patch("bot.exec.signers.SOLDERS_AVAILABLE", False):
            with pytest.raises(ImportError, match="solders package is required"):
                KeypairSigner()


class TestIntegration:
    """Integration tests for signers."""

    def test_external_signer_with_fake_command(self):
        """Test ExternalSigner with a fake command that echoes back the input."""
        # Create a temporary script that echoes back base64 input
        script_content = """#!/usr/bin/env python3
import sys
import base64

if len(sys.argv) > 1 and sys.argv[1] != "--pubkey":
    # Echo back the input as "signed"
    input_b64 = sys.argv[1]
    print(input_b64)
else:
    print("TestPubkey123")
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script_content)
            temp_script = f.name

        try:
            # Make script executable
            os.chmod(temp_script, 0o755)

            signer = ExternalSigner(temp_script)

            # Test pubkey retrieval
            assert signer.pubkey_base58() == "TestPubkey123"

            # Test transaction signing
            txn_bytes = b"test_transaction_data"
            signed = signer.sign_transaction(txn_bytes)

            # Should echo back the original transaction
            expected_b64 = base64.b64encode(txn_bytes).decode("utf-8")
            assert signed == txn_bytes  # The fake script just echoes back

        finally:
            os.unlink(temp_script)
