# bot_module/secrets_box.py
"""Fernet encryption box shared by the API layer and the bot runtime.

Lives in ``bot_module`` because the dependency direction between the two
layers is one-way: ``api -> bot_module`` is allowed, ``bot_module -> api`` is
forbidden (see tests/test_symbol_selection_contract.py). Both sides import
from here so there is exactly ONE source of truth for key parsing/rotation.
"""

import logging
import os

from cryptography.fernet import Fernet, MultiFernet

try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=os.path.join(".", ".env"))
except ImportError:  # pragma: no cover - dotenv is an API dependency anyway
    pass

logger = logging.getLogger(__name__)

# API_ENCRYPTION_KEY can be a comma-separated list of keys.
# The first key is the active key used for encryption;
# subsequent keys are fallbacks for decrypting older data.
_API_ENCRYPTION_KEYS_ENV = os.getenv("API_ENCRYPTION_KEY")

if not _API_ENCRYPTION_KEYS_ENV:
    raise ValueError(
        "API_ENCRYPTION_KEY is not set in the environment. This is required for production."
    )

_encryption_keys = [k.strip() for k in _API_ENCRYPTION_KEYS_ENV.split(",") if k.strip()]

if not _encryption_keys:
    raise ValueError(
        "API_ENCRYPTION_KEY is empty or invalid. Provide at least one valid Fernet key."
    )

fernet = MultiFernet([Fernet(key.encode()) for key in _encryption_keys])


def encrypt_data(data: str) -> str:
    """Encrypts a string using Fernet."""
    if not data:
        return ""
    return fernet.encrypt(data.encode()).decode()


def decrypt_data(encrypted_data: str) -> str:
    """Decrypts a string using Fernet. Raises ValueError on failure."""
    if not encrypted_data:
        return ""
    try:
        return fernet.decrypt(encrypted_data.encode()).decode()
    except Exception as e:
        logger.error(
            f"SECURITY: Failed to decrypt data — possible key mismatch or data corruption: {e}"
        )
        raise ValueError(f"Decryption failed: {e}") from e


def encrypt_node_secret(raw):
    """Encrypts a mining node secret for storage in AppConfig JSON."""
    if not raw:
        return raw
    return encrypt_data(raw)


def decrypt_node_secret(stored):
    """Reads a mining node secret, transparently supporting legacy plaintext.

    Fernet tokens always start with ``gAAA``; anything else is treated as
    plaintext left over from before encryption-at-rest was introduced."""
    if not stored:
        return stored
    try:
        return decrypt_data(stored)
    except ValueError:
        return stored
