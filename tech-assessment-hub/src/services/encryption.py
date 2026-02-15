# encryption.py - Simple encryption for storing credentials

from cryptography.fernet import Fernet
from pathlib import Path
import os

# Key file location (outside of version control)
KEY_FILE = Path(__file__).parent.parent.parent / "data" / ".encryption_key"


def _get_or_create_key() -> bytes:
    """Get existing encryption key or create a new one"""
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    else:
        key = Fernet.generate_key()
        KEY_FILE.parent.mkdir(exist_ok=True)
        KEY_FILE.write_bytes(key)
        # Set restrictive permissions (owner only)
        os.chmod(KEY_FILE, 0o600)
        return key


def get_fernet() -> Fernet:
    """Get Fernet instance for encryption/decryption"""
    key = _get_or_create_key()
    return Fernet(key)


def encrypt_password(password: str) -> str:
    """Encrypt a password for storage"""
    f = get_fernet()
    encrypted = f.encrypt(password.encode())
    return encrypted.decode()


def decrypt_password(encrypted_password: str) -> str:
    """Decrypt a stored password"""
    f = get_fernet()
    decrypted = f.decrypt(encrypted_password.encode())
    return decrypted.decode()
