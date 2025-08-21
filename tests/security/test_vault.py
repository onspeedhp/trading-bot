"""Tests for secret vault functionality."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.secret_vault import (
    SecretVault,
    VaultError,
    load_key_from_env,
    mask_env_content,
)


class TestSecretVault:
    """Test SecretVault class functionality."""

    @pytest.fixture
    def test_key(self):
        """Fixed test key for deterministic testing."""
        return b"0123456789abcdef0123456789abcdef"  # 32 bytes

    @pytest.fixture
    def vault(self, test_key):
        """Create vault with test key."""
        return SecretVault(test_key)

    @pytest.fixture
    def test_data(self):
        """Test data for encryption/decryption."""
        return b"SECRET_API_KEY=abc123\nDB_PASSWORD=super_secret\n"

    def test_vault_initialization(self, test_key):
        """Test vault initialization."""
        vault = SecretVault(test_key)
        assert vault.aesgcm is not None

    def test_vault_initialization_invalid_key(self):
        """Test vault initialization with invalid key."""
        with pytest.raises(VaultError, match="Key must be exactly 32 bytes"):
            SecretVault(b"short_key")

    def test_derive_key_from_password(self):
        """Test key derivation from password."""
        password = "test_password"
        key1 = SecretVault.derive_key_from_password(password)
        key2 = SecretVault.derive_key_from_password(password)

        # Same password should generate same key
        assert key1 == key2
        assert len(key1) == 32

        # Different password should generate different key
        key3 = SecretVault.derive_key_from_password("different_password")
        assert key1 != key3

    def test_encrypt_decrypt_data(self, vault, test_data):
        """Test data encryption and decryption."""
        encrypted = vault.encrypt_data(test_data)
        decrypted = vault.decrypt_data(encrypted)

        assert decrypted == test_data
        assert encrypted != test_data
        assert len(encrypted) > len(test_data)  # Header + ciphertext

    def test_encrypt_decrypt_empty_data(self, vault):
        """Test encryption/decryption of empty data."""
        empty_data = b""
        encrypted = vault.encrypt_data(empty_data)
        decrypted = vault.decrypt_data(encrypted)

        assert decrypted == empty_data

    def test_decrypt_invalid_data(self, vault):
        """Test decryption of invalid data."""
        with pytest.raises(VaultError, match="Invalid encrypted data: too short"):
            vault.decrypt_data(b"short")

    def test_decrypt_wrong_version(self, vault, test_data):
        """Test decryption with wrong version."""
        encrypted = vault.encrypt_data(test_data)

        # Corrupt version in header
        corrupted = b"\x02\x00\x00\x00" + encrypted[4:]

        with pytest.raises(VaultError, match="Unsupported vault version: 2"):
            vault.decrypt_data(corrupted)

    def test_decrypt_corrupted_data(self, vault, test_data):
        """Test decryption of corrupted data."""
        encrypted = vault.encrypt_data(test_data)

        # Corrupt the ciphertext
        corrupted = encrypted[:-1] + b"\x00"

        with pytest.raises(VaultError, match="Decryption failed"):
            vault.decrypt_data(corrupted)

    def test_file_encryption_decryption(self, vault, test_data):
        """Test file encryption and decryption."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = Path(temp_dir) / "input.txt"
            encrypted_file = Path(temp_dir) / "encrypted.bin"
            output_file = Path(temp_dir) / "output.txt"

            # Write test data
            input_file.write_bytes(test_data)

            # Encrypt file
            vault.encrypt_file(input_file, encrypted_file)
            assert encrypted_file.exists()
            assert encrypted_file.read_bytes() != test_data

            # Decrypt file
            vault.decrypt_file(encrypted_file, output_file)
            assert output_file.exists()
            assert output_file.read_bytes() == test_data

    def test_file_encryption_missing_input(self, vault):
        """Test file encryption with missing input file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = Path(temp_dir) / "missing.txt"
            output_file = Path(temp_dir) / "output.bin"

            with pytest.raises(VaultError, match="Input file not found"):
                vault.encrypt_file(input_file, output_file)

    def test_file_encryption_existing_output(self, vault, test_data):
        """Test file encryption with existing output file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = Path(temp_dir) / "input.txt"
            output_file = Path(temp_dir) / "output.bin"

            input_file.write_bytes(test_data)
            output_file.write_bytes(b"existing")

            # Should fail without force
            with pytest.raises(VaultError, match="Output file exists"):
                vault.encrypt_file(input_file, output_file)

            # Should succeed with force
            vault.encrypt_file(input_file, output_file, force=True)
            assert output_file.exists()

    def test_file_decryption_return_data(self, vault, test_data):
        """Test file decryption returning data without writing file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = Path(temp_dir) / "input.txt"
            encrypted_file = Path(temp_dir) / "encrypted.bin"

            input_file.write_bytes(test_data)
            vault.encrypt_file(input_file, encrypted_file)

            # Decrypt without output file
            decrypted_data = vault.decrypt_file(encrypted_file)
            assert decrypted_data == test_data

    def test_different_keys_different_encryption(self, test_data):
        """Test that different keys produce different encryptions."""
        key1 = b"0123456789abcdef0123456789abcdef"
        key2 = b"fedcba9876543210fedcba9876543210"

        vault1 = SecretVault(key1)
        vault2 = SecretVault(key2)

        encrypted1 = vault1.encrypt_data(test_data)
        encrypted2 = vault2.encrypt_data(test_data)

        assert encrypted1 != encrypted2

        # Should not be able to decrypt with wrong key
        with pytest.raises(VaultError):
            vault2.decrypt_data(encrypted1)


class TestVaultUtilities:
    """Test vault utility functions."""

    def test_load_key_from_env_hex(self):
        """Test loading hex key from environment."""
        hex_key = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        with patch.dict(os.environ, {"TEST_KEY": hex_key}):
            key = load_key_from_env("TEST_KEY")
            assert key == bytes.fromhex(hex_key)
            assert len(key) == 32

    def test_load_key_from_env_password(self):
        """Test loading password-derived key from environment."""
        password = "test_password"

        with patch.dict(os.environ, {"TEST_KEY": password}):
            key = load_key_from_env("TEST_KEY")
            assert len(key) == 32
            assert key == SecretVault.derive_key_from_password(password)

    def test_load_key_from_env_missing(self):
        """Test loading key from missing environment variable."""
        with pytest.raises(
            VaultError, match="Environment variable MISSING_KEY not set"
        ):
            load_key_from_env("MISSING_KEY")

    def test_mask_env_content(self):
        """Test masking of environment file content."""
        content = """# Database settings
DB_HOST=localhost
DB_PASSWORD=super_secret_password_123
API_KEY=abc123def456

# Empty value
EMPTY_VAL=

# Short value
SHORT=ab"""

        masked = mask_env_content(content)

        lines = masked.split("\n")
        assert "# Database settings" in lines
        assert "DB_HOST=loca*host" in lines
        assert "DB_PASSWORD=supe*****************_123" in lines
        assert "API_KEY=abc1****f456" in lines
        assert "EMPTY_VAL=" in lines
        assert "SHORT=**" in lines


class TestVaultCLI:
    """Test CLI functionality."""

    @pytest.fixture
    def sample_env_file(self):
        """Create sample .env file for testing."""
        content = """SECRET_API_KEY=abc123def456ghi789
DB_PASSWORD=super_secret_password
TELEGRAM_TOKEN=bot123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write(content)
            f.flush()
            yield f.name

        # Cleanup
        Path(f.name).unlink(missing_ok=True)

    def test_cli_encrypt_decrypt(self, sample_env_file):
        """Test CLI encrypt and decrypt commands."""
        test_key = "test_vault_password"

        with tempfile.TemporaryDirectory() as temp_dir:
            encrypted_file = Path(temp_dir) / "secrets.enc"
            decrypted_file = Path(temp_dir) / "decrypted.env"

            # Test encrypt command
            result = subprocess.run(
                [
                    "python",
                    "scripts/secret_vault.py",
                    "encrypt",
                    "--in",
                    sample_env_file,
                    "--out",
                    str(encrypted_file),
                    "--key-from-env",
                    "VAULT_KEY",
                ],
                env={**os.environ, "VAULT_KEY": test_key},
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0
            assert "✅ Encrypted" in result.stdout
            assert encrypted_file.exists()

            # Test decrypt command
            result = subprocess.run(
                [
                    "python",
                    "scripts/secret_vault.py",
                    "decrypt",
                    "--in",
                    str(encrypted_file),
                    "--out",
                    str(decrypted_file),
                    "--key-from-env",
                    "VAULT_KEY",
                ],
                env={**os.environ, "VAULT_KEY": test_key},
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0
            assert "✅ Decrypted" in result.stdout
            assert decrypted_file.exists()

            # Verify content is same
            original_content = Path(sample_env_file).read_text()
            decrypted_content = decrypted_file.read_text()
            assert original_content == decrypted_content

    def test_cli_show_masked(self, sample_env_file):
        """Test CLI show command with masking."""
        test_key = "test_vault_password"

        with tempfile.TemporaryDirectory() as temp_dir:
            encrypted_file = Path(temp_dir) / "secrets.enc"

            # Encrypt first
            subprocess.run(
                [
                    "python",
                    "scripts/secret_vault.py",
                    "encrypt",
                    "--in",
                    sample_env_file,
                    "--out",
                    str(encrypted_file),
                    "--key-from-env",
                    "VAULT_KEY",
                ],
                env={**os.environ, "VAULT_KEY": test_key},
                capture_output=True,
            )

            # Test show command
            result = subprocess.run(
                [
                    "python",
                    "scripts/secret_vault.py",
                    "show",
                    "--in",
                    str(encrypted_file),
                    "--key-from-env",
                    "VAULT_KEY",
                ],
                env={**os.environ, "VAULT_KEY": test_key},
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0
            assert "📋 Masked secrets content:" in result.stdout
            assert "SECRET_API_KEY=abc1**********i789" in result.stdout
            assert "DB_PASSWORD=supe*************word" in result.stdout

    def test_cli_decrypt_without_output(self, sample_env_file):
        """Test CLI decrypt command without output file (should refuse)."""
        test_key = "test_vault_password"

        with tempfile.TemporaryDirectory() as temp_dir:
            encrypted_file = Path(temp_dir) / "secrets.enc"

            # Encrypt first
            subprocess.run(
                [
                    "python",
                    "scripts/secret_vault.py",
                    "encrypt",
                    "--in",
                    sample_env_file,
                    "--out",
                    str(encrypted_file),
                    "--key-from-env",
                    "VAULT_KEY",
                ],
                env={**os.environ, "VAULT_KEY": test_key},
                capture_output=True,
            )

            # Test decrypt without output
            result = subprocess.run(
                [
                    "python",
                    "scripts/secret_vault.py",
                    "decrypt",
                    "--in",
                    str(encrypted_file),
                    "--key-from-env",
                    "VAULT_KEY",
                ],
                env={**os.environ, "VAULT_KEY": test_key},
                capture_output=True,
                text=True,
            )

            assert result.returncode == 1
            assert (
                "Refusing to print plaintext without --out specified" in result.stderr
            )

    def test_cli_missing_env_var(self, sample_env_file):
        """Test CLI with missing environment variable."""
        with tempfile.TemporaryDirectory() as temp_dir:
            encrypted_file = Path(temp_dir) / "secrets.enc"

            # Test encrypt with missing env var
            result = subprocess.run(
                [
                    "python",
                    "scripts/secret_vault.py",
                    "encrypt",
                    "--in",
                    sample_env_file,
                    "--out",
                    str(encrypted_file),
                    "--key-from-env",
                    "MISSING_KEY",
                ],
                capture_output=True,
                text=True,
            )

            assert result.returncode == 1
            assert "Environment variable MISSING_KEY not set" in result.stderr

    def test_cli_force_overwrite(self, sample_env_file):
        """Test CLI force overwrite functionality."""
        test_key = "test_vault_password"

        with tempfile.TemporaryDirectory() as temp_dir:
            encrypted_file = Path(temp_dir) / "secrets.enc"

            # Create existing file
            encrypted_file.write_text("existing content")

            # Test encrypt without force (should fail)
            result = subprocess.run(
                [
                    "python",
                    "scripts/secret_vault.py",
                    "encrypt",
                    "--in",
                    sample_env_file,
                    "--out",
                    str(encrypted_file),
                    "--key-from-env",
                    "VAULT_KEY",
                ],
                env={**os.environ, "VAULT_KEY": test_key},
                capture_output=True,
                text=True,
            )

            assert result.returncode == 1
            assert "Output file exists" in result.stderr

            # Test encrypt with force (should succeed)
            result = subprocess.run(
                [
                    "python",
                    "scripts/secret_vault.py",
                    "encrypt",
                    "--in",
                    sample_env_file,
                    "--out",
                    str(encrypted_file),
                    "--key-from-env",
                    "VAULT_KEY",
                    "--force",
                ],
                env={**os.environ, "VAULT_KEY": test_key},
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0
            assert "✅ Encrypted" in result.stdout

    def test_cli_help(self):
        """Test CLI help functionality."""
        result = subprocess.run(
            ["python", "scripts/secret_vault.py", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert (
            "Secret vault for managing encrypted configuration files" in result.stdout
        )
        assert "encrypt" in result.stdout
        assert "decrypt" in result.stdout
        assert "show" in result.stdout

    def test_cli_no_command(self):
        """Test CLI with no command."""
        result = subprocess.run(
            ["python", "scripts/secret_vault.py"], capture_output=True, text=True
        )

        assert result.returncode == 1
        assert "usage:" in result.stdout or result.stderr


class TestVaultSecurity:
    """Test security properties of the vault."""

    def test_nonce_uniqueness(self, test_data=b"test"):
        """Test that nonces are unique for each encryption."""
        vault = SecretVault(b"0123456789abcdef0123456789abcdef")

        # Encrypt same data multiple times
        encryptions = [vault.encrypt_data(test_data) for _ in range(10)]

        # Extract nonces (bytes 4-16 of each encryption)
        nonces = [enc[4:16] for enc in encryptions]

        # All nonces should be unique
        assert len(set(nonces)) == len(nonces)

    def test_ciphertext_integrity(self):
        """Test that tampering with ciphertext fails authentication."""
        vault = SecretVault(b"0123456789abcdef0123456789abcdef")
        plaintext = b"sensitive data"

        encrypted = vault.encrypt_data(plaintext)

        # Tamper with last byte of ciphertext
        tampered = encrypted[:-1] + bytes([encrypted[-1] ^ 1])

        with pytest.raises(VaultError, match="Decryption failed"):
            vault.decrypt_data(tampered)

    def test_header_integrity(self):
        """Test that tampering with header fails."""
        vault = SecretVault(b"0123456789abcdef0123456789abcdef")
        plaintext = b"sensitive data"

        encrypted = vault.encrypt_data(plaintext)

        # Tamper with nonce in header
        tampered = encrypted[:5] + bytes([encrypted[5] ^ 1]) + encrypted[6:]

        with pytest.raises(VaultError, match="Decryption failed"):
            vault.decrypt_data(tampered)

    def test_key_sensitivity(self):
        """Test that small key changes completely change output."""
        plaintext = b"test data"

        key1 = b"0123456789abcdef0123456789abcdef"
        key2 = b"0123456789abcdef0123456789abcdee"  # Last byte different

        vault1 = SecretVault(key1)
        vault2 = SecretVault(key2)

        # Encrypt with both keys
        enc1 = vault1.encrypt_data(plaintext)
        enc2 = vault2.encrypt_data(plaintext)

        # Should be completely different (except header version)
        assert enc1[0:4] == enc2[0:4]  # Same version
        # The rest should be different due to different keys and nonces
        assert enc1[4:] != enc2[4:]
