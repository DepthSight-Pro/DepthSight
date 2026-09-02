from datetime import datetime, timedelta, timezone
from typing import Optional
import hashlib
import logging

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer
from fastapi import HTTPException
import os
from itsdangerous import URLSafeTimedSerializer
from dotenv import load_dotenv

from pathlib import Path


def get_boolean_env(key: str, default: bool = False) -> bool:
    """
    Retrieves a boolean value from an environment variable.
    Interprets 'true', '1', 't', 'y', 'yes' as True.
    """
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "t", "y", "yes")


# Will define these here for now, can be moved to config later
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise ValueError(
        "JWT_SECRET_KEY is not set in the environment. This is required for production."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30  # 30 minutes
REFRESH_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # 30 days

# --- Email Confirmation Settings ---
EMAIL_CONFIRMATION_ENABLED = get_boolean_env("EMAIL_CONFIRMATION_ENABLED", True)
CONFIRMATION_SECRET_KEY = os.getenv("CONFIRMATION_SECRET_KEY", SECRET_KEY)
if CONFIRMATION_SECRET_KEY == SECRET_KEY:
    logging.getLogger(__name__).warning(
        "SECURITY: CONFIRMATION_SECRET_KEY is not set — falling back to JWT_SECRET_KEY. "
        "Set a separate CONFIRMATION_SECRET_KEY in production for proper key separation."
    )
EMAIL_CONFIRMATION_SALT = "email-confirmation-salt"

# --- Password Reset Settings ---
PASSWORD_RESET_SALT = "password-reset-salt"
PASSWORD_RESET_TOKEN_MAX_AGE = 3600  # 1 hour

email_confirmation_serializer = URLSafeTimedSerializer(
    CONFIRMATION_SECRET_KEY, salt=EMAIL_CONFIRMATION_SALT
)
password_reset_serializer = URLSafeTimedSerializer(
    CONFIRMATION_SECRET_KEY, salt=PASSWORD_RESET_SALT
)


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=REFRESH_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def validate_token(token: str, credentials_exception: HTTPException) -> str:
    """Validates an access token and returns the ``sub`` (username).

    Requires the ``type`` claim to be ``"access"`` so that 30-day refresh tokens
    cannot be used to authenticate on access-token-protected endpoints.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None or payload.get("type") != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return username


# --- Two-Factor Authentication (2FA) Temporary Pre-Auth Tokens ---
TWO_FACTOR_TEMP_TOKEN_EXPIRE_MINUTES = 5


def create_temp_2fa_token(
    username: str, expires_delta: Optional[timedelta] = None
) -> str:
    """
    Creates a short-lived token (5 minutes) issued during login when 2FA is required.
    Allows access ONLY to the /2fa/verify-login endpoint.
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=TWO_FACTOR_TEMP_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {"sub": username, "exp": expire, "type": "2fa_pending"}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def validate_temp_2fa_token(token: str) -> str:
    """
    Validates a temporary 2FA token and returns the username.
    Raises HTTPException(401) if invalid or expired.
    """
    credentials_exception = HTTPException(
        status_code=401,
        detail="Invalid or expired 2FA session token. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None or payload.get("type") != "2fa_pending":
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return username


# --- Encryption for API Keys ---

# Load encryption key from environment variable
# Important: this key MUST be set in your runtime environment
env_path = Path(".") / ".env"
load_dotenv(dotenv_path=env_path)

# The Fernet box (key parsing, MultiFernet rotation, encrypt/decrypt and the
# mining-node-secret helpers) lives in bot_module.secrets_box — the shared,
# dependency-safe location. This module re-exports it for the API layer.
from bot_module.secrets_box import (  # noqa: E402
    decrypt_data as _sb_decrypt_data,
    decrypt_node_secret,  # noqa: F401  re-exported
    encrypt_data as _sb_encrypt_data,
    encrypt_node_secret,  # noqa: F401  re-exported
    fernet,  # noqa: F401  kept for backward compatibility with importers
)

_security_logger = logging.getLogger(__name__)


def hash_data(data: str) -> str:
    """Creates a deterministic SHA-256 hash of a string for duplicate detection."""
    if not data:
        return ""
    return hashlib.sha256(data.encode()).hexdigest()


def encrypt_data(data: str) -> str:
    """Encrypts a string using Fernet."""
    return _sb_encrypt_data(data)


def decrypt_data(encrypted_data: str) -> str:
    """Decrypts a string using Fernet."""
    return _sb_decrypt_data(encrypted_data)


# --- Mining node secret at rest -------------------------------------------
# encrypt_node_secret / decrypt_node_secret are re-exported above from
# bot_module.secrets_box (single implementation shared with the bot runtime;
# legacy plaintext values are accepted transparently on read).
