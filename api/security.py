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
from cryptography.fernet import Fernet, MultiFernet
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

email_confirmation_serializer = URLSafeTimedSerializer(CONFIRMATION_SECRET_KEY)
password_reset_serializer = URLSafeTimedSerializer(
    CONFIRMATION_SECRET_KEY
)  # Using same for now


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
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return username


# --- Encryption for API Keys ---

# Load encryption key from environment variable
# Important: this key MUST be set in your runtime environment
env_path = Path(".") / ".env"
load_dotenv(dotenv_path=env_path)

# API_ENCRYPTION_KEY can now be a comma-separated list of keys
# The first key in the list is the active key used for encryption.
# Subsequent keys are fallback keys used for decrypting older data.
API_ENCRYPTION_KEYS_ENV = os.getenv("API_ENCRYPTION_KEY")

if not API_ENCRYPTION_KEYS_ENV:
    raise ValueError(
        "API_ENCRYPTION_KEY is not set in the environment. This is required for production."
    )

# Parse the keys
_encryption_keys = [k.strip() for k in API_ENCRYPTION_KEYS_ENV.split(",") if k.strip()]

if not _encryption_keys:
    raise ValueError(
        "API_ENCRYPTION_KEY is empty or invalid. Provide at least one valid Fernet key."
    )

# Create a Fernet instance using MultiFernet for automatic fallback decryption
# The first key in the list will be used for encryption (fernet_instances[0])
_fernet_instances = [Fernet(key.encode()) for key in _encryption_keys]
fernet = MultiFernet(_fernet_instances)

_security_logger = logging.getLogger(__name__)


def hash_data(data: str) -> str:
    """Creates a deterministic SHA-256 hash of a string for duplicate detection."""
    if not data:
        return ""
    return hashlib.sha256(data.encode()).hexdigest()


def encrypt_data(data: str) -> str:
    """Encrypts a string using Fernet."""
    if not data:
        return ""
    encrypted_data = fernet.encrypt(data.encode())
    return encrypted_data.decode()


def decrypt_data(encrypted_data: str) -> str:
    """Decrypts a string using Fernet."""
    if not encrypted_data:
        return ""
    try:
        decrypted_data = fernet.decrypt(encrypted_data.encode())
        return decrypted_data.decode()
    except Exception as e:
        _security_logger.error(
            f"SECURITY: Failed to decrypt data — possible key mismatch or data corruption: {e}"
        )
        raise ValueError(f"Decryption failed: {e}") from e
