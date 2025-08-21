#!/usr/bin/env python3
"""Secret vault for managing encrypted configuration files using AES-256-GCM."""

import argparse
import os
import struct
import sys
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class VaultError(Exception):
    """Base exception for vault operations."""
    pass


class SecretVault:
    """AES-256-GCM encrypted secret vault."""
    
    VAULT_VERSION = 1
    NONCE_SIZE = 12  # 96 bits for GCM
    KEY_SIZE = 32    # 256 bits for AES-256
    HEADER_SIZE = 16  # version (4) + nonce (12)
    
    def __init__(self, key: bytes) -> None:
        """Initialize vault with encryption key.
        
        Args:
            key: 32-byte encryption key for AES-256
        """
        if len(key) != self.KEY_SIZE:
            raise VaultError(f"Key must be exactly {self.KEY_SIZE} bytes, got {len(key)}")
        
        self.aesgcm = AESGCM(key)
    
    @classmethod
    def derive_key_from_password(cls, password: str, salt: bytes = b'vault_salt_2024') -> bytes:
        """Derive encryption key from password using PBKDF2.
        
        Args:
            password: Password string
            salt: Salt bytes for key derivation
            
        Returns:
            32-byte derived key
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=cls.KEY_SIZE,
            salt=salt,
            iterations=100000,  # NIST recommended minimum
        )
        return kdf.derive(password.encode('utf-8'))
    
    def encrypt_data(self, plaintext: bytes) -> bytes:
        """Encrypt data with AES-256-GCM.
        
        Args:
            plaintext: Data to encrypt
            
        Returns:
            Encrypted data with header (version + nonce + ciphertext)
        """
        # Generate random nonce
        nonce = os.urandom(self.NONCE_SIZE)
        
        # Encrypt data
        ciphertext = self.aesgcm.encrypt(nonce, plaintext, None)
        
        # Build header: version (4 bytes) + nonce (12 bytes)
        header = struct.pack('<I', self.VAULT_VERSION) + nonce
        
        return header + ciphertext
    
    def decrypt_data(self, encrypted_data: bytes) -> bytes:
        """Decrypt data with AES-256-GCM.
        
        Args:
            encrypted_data: Encrypted data with header
            
        Returns:
            Decrypted plaintext
        """
        if len(encrypted_data) < self.HEADER_SIZE:
            raise VaultError("Invalid encrypted data: too short")
        
        # Parse header
        header = encrypted_data[:self.HEADER_SIZE]
        ciphertext = encrypted_data[self.HEADER_SIZE:]
        
        version, = struct.unpack('<I', header[:4])
        if version != self.VAULT_VERSION:
            raise VaultError(f"Unsupported vault version: {version}")
        
        nonce = header[4:self.HEADER_SIZE]
        
        # Decrypt data
        try:
            plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext
        except Exception as e:
            raise VaultError(f"Decryption failed: {e}")
    
    def encrypt_file(self, input_path: Path, output_path: Path, force: bool = False) -> None:
        """Encrypt a file.
        
        Args:
            input_path: Path to input file
            output_path: Path to output encrypted file
            force: Whether to overwrite existing output file
        """
        if not input_path.exists():
            raise VaultError(f"Input file not found: {input_path}")
        
        if output_path.exists() and not force:
            raise VaultError(f"Output file exists (use --force to overwrite): {output_path}")
        
        # Read and encrypt file
        plaintext = input_path.read_bytes()
        encrypted_data = self.encrypt_data(plaintext)
        
        # Write encrypted file
        output_path.write_bytes(encrypted_data)
    
    def decrypt_file(self, input_path: Path, output_path: Optional[Path] = None, force: bool = False) -> bytes:
        """Decrypt a file.
        
        Args:
            input_path: Path to encrypted input file
            output_path: Path to output decrypted file (None to return data)
            force: Whether to overwrite existing output file
            
        Returns:
            Decrypted data if output_path is None
        """
        if not input_path.exists():
            raise VaultError(f"Input file not found: {input_path}")
        
        if output_path and output_path.exists() and not force:
            raise VaultError(f"Output file exists (use --force to overwrite): {output_path}")
        
        # Read and decrypt file
        encrypted_data = input_path.read_bytes()
        plaintext = self.decrypt_data(encrypted_data)
        
        if output_path:
            output_path.write_bytes(plaintext)
        
        return plaintext


def load_key_from_env(env_var: str) -> bytes:
    """Load encryption key from environment variable.
    
    Args:
        env_var: Name of environment variable containing key
        
    Returns:
        32-byte encryption key
    """
    key_value = os.getenv(env_var)
    if not key_value:
        raise VaultError(f"Environment variable {env_var} not set")
    
    # Try to decode as hex first, then derive from password
    try:
        if len(key_value) == 64:  # 32 bytes as hex
            return bytes.fromhex(key_value)
        else:
            # Derive key from password
            return SecretVault.derive_key_from_password(key_value)
    except ValueError:
        # Derive key from password
        return SecretVault.derive_key_from_password(key_value)


def mask_env_content(content: str) -> str:
    """Mask sensitive values in environment file content.
    
    Args:
        content: Environment file content
        
    Returns:
        Content with masked values
    """
    lines = []
    for line in content.split('\n'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            if value and len(value) > 8:
                # Show first 4 and last 4 characters, mask the middle
                masked_value = value[:4] + '*' * (len(value) - 8) + value[-4:]
            else:
                masked_value = '*' * len(value)
            lines.append(f"{key}={masked_value}")
        else:
            lines.append(line)
    
    return '\n'.join(lines)


def cmd_encrypt(args: argparse.Namespace) -> None:
    """Handle encrypt command."""
    try:
        key = load_key_from_env(args.key_from_env)
        vault = SecretVault(key)
        
        input_path = Path(args.input)
        output_path = Path(args.output)
        
        vault.encrypt_file(input_path, output_path, args.force)
        print(f"✅ Encrypted {input_path} -> {output_path}")
        
    except Exception as e:
        print(f"❌ Encryption failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_decrypt(args: argparse.Namespace) -> None:
    """Handle decrypt command."""
    try:
        key = load_key_from_env(args.key_from_env)
        vault = SecretVault(key)
        
        input_path = Path(args.input)
        
        if args.output:
            output_path = Path(args.output)
            vault.decrypt_file(input_path, output_path, args.force)
            print(f"✅ Decrypted {input_path} -> {output_path}")
        else:
            # Don't write plaintext to disk if --out omitted
            plaintext = vault.decrypt_file(input_path)
            print("❌ Refusing to print plaintext without --out specified", file=sys.stderr)
            print("Use --out to specify output file", file=sys.stderr)
            sys.exit(1)
        
    except Exception as e:
        print(f"❌ Decryption failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_show(args: argparse.Namespace) -> None:
    """Handle show command (prints masked content)."""
    try:
        key = load_key_from_env(args.key_from_env)
        vault = SecretVault(key)
        
        input_path = Path(args.input)
        plaintext = vault.decrypt_file(input_path)
        
        # Decode and mask content
        content = plaintext.decode('utf-8')
        masked_content = mask_env_content(content)
        
        print("📋 Masked secrets content:")
        print("=" * 40)
        print(masked_content)
        
    except Exception as e:
        print(f"❌ Show failed: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Secret vault for managing encrypted configuration files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Encrypt .env file
  export VAULT_KEY="my-secure-password"
  secret_vault.py encrypt --in .env --out secrets.enc --key-from-env VAULT_KEY
  
  # Decrypt secrets
  secret_vault.py decrypt --in secrets.enc --out .env.decrypted --key-from-env VAULT_KEY
  
  # Show masked secrets
  secret_vault.py show --in secrets.enc --key-from-env VAULT_KEY
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Encrypt command
    encrypt_parser = subparsers.add_parser('encrypt', help='Encrypt a file')
    encrypt_parser.add_argument('--in', dest='input', required=True, help='Input file path')
    encrypt_parser.add_argument('--out', dest='output', required=True, help='Output encrypted file path')
    encrypt_parser.add_argument('--key-from-env', required=True, help='Environment variable containing encryption key')
    encrypt_parser.add_argument('--force', action='store_true', help='Overwrite existing output file')
    
    # Decrypt command
    decrypt_parser = subparsers.add_parser('decrypt', help='Decrypt a file')
    decrypt_parser.add_argument('--in', dest='input', required=True, help='Input encrypted file path')
    decrypt_parser.add_argument('--out', dest='output', help='Output decrypted file path')
    decrypt_parser.add_argument('--key-from-env', required=True, help='Environment variable containing encryption key')
    decrypt_parser.add_argument('--force', action='store_true', help='Overwrite existing output file')
    
    # Show command
    show_parser = subparsers.add_parser('show', help='Show masked secrets content')
    show_parser.add_argument('--in', dest='input', required=True, help='Input encrypted file path')
    show_parser.add_argument('--key-from-env', required=True, help='Environment variable containing encryption key')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Dispatch to command handlers
    if args.command == 'encrypt':
        cmd_encrypt(args)
    elif args.command == 'decrypt':
        cmd_decrypt(args)
    elif args.command == 'show':
        cmd_show(args)


if __name__ == "__main__":
    main()