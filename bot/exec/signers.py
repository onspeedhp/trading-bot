"""Transaction signers for Solana trading operations."""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol, Optional, List, Union, TYPE_CHECKING
import structlog

logger = structlog.get_logger(__name__)

# Type checking imports
if TYPE_CHECKING:
    import solders.keypair as solders_keypair

# Runtime imports with fallbacks
try:
    import solders.keypair as solders_keypair

    SOLDERS_AVAILABLE = True
except ImportError:
    SOLDERS_AVAILABLE = False
    solders_keypair = None
    logger.warning("solders not available - KeypairSigner will not work")

try:
    import base58

    BASE58_AVAILABLE = True
except ImportError:
    BASE58_AVAILABLE = False
    base58 = None
    logger.warning("base58 not available - base58 secret key loading will not work")


class TxnSigner(Protocol):
    """Protocol for transaction signers."""

    def pubkey_base58(self) -> str:
        """Get the public key in base58 format."""
        ...

    def sign_transaction(self, txn_bytes: bytes) -> bytes:
        """Sign a transaction and return fully signed raw bytes.

        Args:
            txn_bytes: Raw transaction bytes to sign

        Returns:
            Fully signed transaction bytes ready for RPC submission
        """
        ...


class KeypairSigner:
    """Signer using a Solana keypair loaded from various sources."""

    def __init__(
        self,
        keypair_path_enc: Optional[str] = None,
        keypair_path_json: Optional[str] = None,
        secret_key_env: str = "SOLANA_SK_B58",
    ) -> None:
        """Initialize KeypairSigner with keypair loading options.

        Args:
            keypair_path_enc: Path to encrypted keypair file
            keypair_path_json: Path to JSON keypair file (Phantom/solana-keygen format)
            secret_key_env: Environment variable name for base58 secret key
        """
        if not SOLDERS_AVAILABLE:
            raise ImportError("solders package is required for KeypairSigner")

        self.keypair = self._load_keypair(
            keypair_path_enc, keypair_path_json, secret_key_env
        )
        logger.info("KeypairSigner initialized", pubkey=self.pubkey_base58())

    def pubkey_base58(self) -> str:
        """Get the public key in base58 format."""
        return str(self.keypair.pubkey())

    def sign_transaction(self, txn_bytes: bytes) -> bytes:
        """Sign a transaction and return fully signed raw bytes.

        Args:
            txn_bytes: Raw transaction bytes to sign

        Returns:
            Fully signed transaction bytes ready for RPC submission
        """
        signature = self.keypair.sign_message(txn_bytes)
        # For Solana transactions, we need to prepend the signature
        return bytes(signature) + txn_bytes

    def _load_keypair(
        self,
        keypair_path_enc: Optional[str],
        keypair_path_json: Optional[str],
        secret_key_env: str,
    ):
        """Load keypair from various sources in order of precedence."""

        # 1. Try encrypted file first
        if keypair_path_enc:
            try:
                secret_bytes = self._load_encrypted_keypair(keypair_path_enc)
                return solders_keypair.Keypair.from_bytes(secret_bytes)
            except Exception as e:
                logger.warning(
                    "Failed to load encrypted keypair",
                    path=keypair_path_enc,
                    error=str(e),
                )

        # 2. Try environment variable
        try:
            secret_bytes = load_base58_secret(secret_key_env)
            return solders_keypair.Keypair.from_bytes(secret_bytes)
        except Exception as e:
            logger.warning(
                "Failed to load secret from environment",
                env_var=secret_key_env,
                error=str(e),
            )

        # 3. Try JSON file
        if keypair_path_json:
            try:
                secret_bytes = load_json_keypair(keypair_path_json)
                return solders_keypair.Keypair.from_bytes(secret_bytes)
            except Exception as e:
                logger.warning(
                    "Failed to load JSON keypair", path=keypair_path_json, error=str(e)
                )

        raise ValueError(
            "No valid keypair source found. Please provide one of: encrypted file, environment variable, or JSON file"
        )

    def _load_encrypted_keypair(self, encrypted_path: str) -> bytes:
        """Load and decrypt keypair from encrypted file using secret vault."""
        try:
            # Import here to avoid circular imports
            from scripts.secret_vault import SecretVault, load_key_from_env

            # Load vault key from environment
            vault_key = load_key_from_env("VAULT_KEY")
            vault = SecretVault(vault_key)

            # Decrypt file in memory (no temp file)
            encrypted_data = Path(encrypted_path).read_bytes()
            decrypted_data = vault.decrypt_data(encrypted_data)

            # Parse as base58 secret key
            secret_str = decrypted_data.decode("utf-8").strip()
            return load_base58_secret_from_string(secret_str)

        except Exception as e:
            raise ValueError(
                f"Failed to load encrypted keypair from {encrypted_path}: {e}"
            )


class ExternalSigner:
    """Signer using external command (e.g., hardware wallet bridge)."""

    def __init__(
        self, command: str, args: Optional[List[str]] = None, timeout: int = 30
    ) -> None:
        """Initialize ExternalSigner with command configuration.

        Args:
            command: Path to external signing command
            args: Additional arguments for the command
            timeout: Timeout in seconds for command execution
        """
        self.command = command
        self.args = args or []
        self.timeout = timeout
        self.pubkey = self._get_pubkey()
        logger.info("ExternalSigner initialized", command=command, pubkey=self.pubkey)

    def pubkey_base58(self) -> str:
        """Get the public key in base58 format."""
        return self.pubkey

    def sign_transaction(self, txn_bytes: bytes) -> bytes:
        """Sign a transaction using external command.

        Args:
            txn_bytes: Raw transaction bytes to sign

        Returns:
            Fully signed transaction bytes ready for RPC submission
        """
        # Encode transaction as base64
        txn_b64 = base64.b64encode(txn_bytes).decode("utf-8")

        # Prepare command
        cmd = [self.command] + self.args + [txn_b64]

        try:
            # Execute command
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout, check=True
            )

            # Parse signed transaction from output
            signed_b64 = result.stdout.strip()
            if not signed_b64:
                raise ValueError("External command returned empty output")

            signed_bytes = base64.b64decode(signed_b64)
            return signed_bytes

        except subprocess.TimeoutExpired:
            raise TimeoutError(
                f"External signing command timed out after {self.timeout} seconds"
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"External signing command failed: {e.stderr}")
        except Exception as e:
            raise RuntimeError(f"Failed to execute external signing command: {e}")

    def _get_pubkey(self) -> str:
        """Get public key from external command."""
        # This is a simplified implementation - in practice, the external command
        # might have a separate way to get the public key
        cmd = [self.command] + self.args + ["--pubkey"]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout, check=True
            )
            return result.stdout.strip()
        except Exception as e:
            logger.warning(
                "Failed to get public key from external command", error=str(e)
            )
            return "unknown"


def load_base58_secret(env_var: str) -> bytes:
    """Load base58-encoded secret key from environment variable.

    Args:
        env_var: Environment variable name containing base58 secret key

    Returns:
        64-byte secret key
    """
    secret_str = os.getenv(env_var)
    if not secret_str:
        raise ValueError(f"Environment variable {env_var} not set")

    return load_base58_secret_from_string(secret_str)


def load_base58_secret_from_string(secret_str: str) -> bytes:
    """Load base58-encoded secret key from string.

    Args:
        secret_str: Base58-encoded secret key string

    Returns:
        64-byte secret key
    """
    if not BASE58_AVAILABLE:
        raise ImportError("base58 package is required for base58 secret key loading")

    try:
        # Decode base58
        secret_bytes = base58.b58decode(secret_str)

        # Validate length (Solana keypairs are 64 bytes)
        if len(secret_bytes) != 64:
            raise ValueError(
                f"Invalid secret key length: {len(secret_bytes)} bytes (expected 64)"
            )

        return secret_bytes

    except Exception as e:
        raise ValueError(f"Invalid base58 secret key: {e}")


def load_json_keypair(json_path: str) -> bytes:
    """Load secret key from JSON keypair file (Phantom/solana-keygen format).

    Args:
        json_path: Path to JSON keypair file

    Returns:
        64-byte secret key
    """
    try:
        with open(json_path, "r") as f:
            data = json.load(f)

        # Handle different JSON formats
        if isinstance(data, list):
            # Phantom/solana-keygen format: array of numbers
            if len(data) != 64:
                raise ValueError(
                    f"Invalid keypair array length: {len(data)} (expected 64)"
                )
            return bytes(data)
        elif isinstance(data, dict):
            # Alternative format with secret key field
            if "secretKey" in data:
                secret_data = data["secretKey"]
                if isinstance(secret_data, list):
                    return bytes(secret_data)
                elif isinstance(secret_data, str):
                    return load_base58_secret_from_string(secret_data)
            raise ValueError("JSON keypair file does not contain valid secretKey field")
        else:
            raise ValueError("Invalid JSON keypair format")

    except Exception as e:
        raise ValueError(f"Failed to load JSON keypair from {json_path}: {e}")
