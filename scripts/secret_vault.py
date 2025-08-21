#!/usr/bin/env python3
"""Secret vault for managing encrypted configuration."""

import argparse
import json
import os
import sys
from pathlib import Path
from cryptography.fernet import Fernet
import structlog

logger = structlog.get_logger(__name__)


class SecretVault:
    """Encrypted configuration vault."""

    def __init__(self, key_file: str = ".key", vault_file: str = "secrets.enc") -> None:
        """Initialize secret vault."""
        self.key_file = Path(key_file)
        self.vault_file = Path(vault_file)
        self.fernet = None

    def _load_or_generate_key(self) -> None:
        """Load existing key or generate new one."""
        if self.key_file.exists():
            key = self.key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            self.key_file.write_bytes(key)
            logger.info("Generated new encryption key", key_file=self.key_file)

        self.fernet = Fernet(key)

    def encrypt_secrets(self, secrets: dict) -> None:
        """Encrypt and save secrets."""
        self._load_or_generate_key()

        if not self.fernet:
            raise RuntimeError("Fernet not initialized")

        # Convert to JSON and encrypt
        json_data = json.dumps(secrets, indent=2)
        encrypted_data = self.fernet.encrypt(json_data.encode())

        # Save encrypted data
        self.vault_file.write_bytes(encrypted_data)
        logger.info("Secrets encrypted and saved", vault_file=self.vault_file)

    def decrypt_secrets(self) -> dict:
        """Decrypt and load secrets."""
        self._load_or_generate_key()

        if not self.fernet:
            raise RuntimeError("Fernet not initialized")

        if not self.vault_file.exists():
            logger.warning("Vault file not found", vault_file=self.vault_file)
            return {}

        # Read and decrypt data
        encrypted_data = self.vault_file.read_bytes()
        json_data = self.fernet.decrypt(encrypted_data)
        secrets = json.loads(json_data.decode())

        logger.info("Secrets decrypted and loaded", vault_file=self.vault_file)
        return secrets

    def update_secret(self, key: str, value: str) -> None:
        """Update a single secret."""
        secrets = self.decrypt_secrets()
        secrets[key] = value
        self.encrypt_secrets(secrets)
        logger.info("Secret updated", key=key)

    def get_secret(self, key: str) -> str | None:
        """Get a single secret."""
        secrets = self.decrypt_secrets()
        return secrets.get(key)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Secret Vault Manager")
    parser.add_argument(
        "action",
        choices=["encrypt", "decrypt", "update", "get"],
        help="Action to perform",
    )
    parser.add_argument("--key-file", default=".key", help="Encryption key file")
    parser.add_argument(
        "--vault-file", default="secrets.enc", help="Encrypted vault file"
    )
    parser.add_argument("--secret-key", help="Secret key for update/get operations")
    parser.add_argument("--secret-value", help="Secret value for update operation")
    parser.add_argument("--input-file", help="Input file for encrypt operation")

    args = parser.parse_args()

    vault = SecretVault(args.key_file, args.vault_file)

    try:
        if args.action == "encrypt":
            if args.input_file:
                with open(args.input_file, "r") as f:
                    secrets = json.load(f)
            else:
                # Default secrets template
                secrets = {
                    "helius_api_key": "your_helius_api_key_here",
                    "birdeye_api_key": "your_birdeye_api_key_here",
                    "dexscreener_api_key": "your_dexscreener_api_key_here",
                    "telegram_bot_token": "your_telegram_bot_token_here",
                    "telegram_chat_id": "your_telegram_chat_id_here",
                }

            vault.encrypt_secrets(secrets)
            print("Secrets encrypted successfully")

        elif args.action == "decrypt":
            secrets = vault.decrypt_secrets()
            print(json.dumps(secrets, indent=2))

        elif args.action == "update":
            if not args.secret_key or not args.secret_value:
                print("Error: --secret-key and --secret-value are required for update")
                sys.exit(1)

            vault.update_secret(args.secret_key, args.secret_value)
            print(f"Secret '{args.secret_key}' updated successfully")

        elif args.action == "get":
            if not args.secret_key:
                print("Error: --secret-key is required for get")
                sys.exit(1)

            value = vault.get_secret(args.secret_key)
            if value:
                print(value)
            else:
                print(f"Secret '{args.secret_key}' not found")
                sys.exit(1)

    except Exception as e:
        logger.error("Vault operation failed", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
