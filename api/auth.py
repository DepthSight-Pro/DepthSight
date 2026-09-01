import hmac
import logging
import os
import re

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request, status
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from . import crud, models  # Assuming these exist or will be created
from .database import get_db  # Assuming this exists
from .security import oauth2_scheme, validate_token

logger = logging.getLogger(__name__)

# Load variables from .env file (good practice)
load_dotenv()

# Read the key from environment variables.
# Name the backend variable differently to avoid confusion, e.g., API_KEY_SECRET
VALID_API_KEY = os.getenv("API_KEY_SECRET")
if not VALID_API_KEY:
    # If the variable is not set in .env, the application will not start. This prevents errors.
    raise ValueError("API_KEY_SECRET is not set in the environment variables!")

API_KEY_NAME = "X-API-KEY"
api_key_header_auth = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


async def get_api_key(api_key_header: str = Depends(api_key_header_auth)):
    # Now the comparison is made against the key loaded from .env
    if not api_key_header or not hmac.compare_digest(api_key_header, VALID_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key"
        )
    return api_key_header


# --- Trusted service (Slack agent) authentication ---------------------------
#
# The Slack bot authenticates on behalf of an existing user via the shared
# ``X-Slack-Secret`` / ``X-User-Email`` headers. Because that secret is a
# static value shared with an external process, a leak must not compromise
# every endpoint. The service path is therefore honored ONLY for the explicit
# allowlist of method + path combinations the Slack integration consumes;
# every other route requires a normal JWT bearer token.
_SERVICE_AUTH_ALLOWED: list[tuple[str, str]] = [
    ("POST", r"^/api/v1/ai/chat$"),
    ("DELETE", r"^/api/v1/ai/chat/history/[^/]+$"),
    ("POST", r"^/api/v1/strategies/config$"),
    ("GET", r"^/api/v1/strategies/config/[^/]+$"),
    ("POST", r"^/api/v1/backtests/?$"),
    ("GET", r"^/api/v1/backtests/?$"),
    ("GET", r"^/api/v1/backtests/[^/]+$"),
    ("GET", r"^/api/v1/portfolio/portfolio$"),
    ("GET", r"^/api/v1/users/me$"),
]


def _is_service_auth_allowed(request: Request) -> bool:
    """True if this method+path may use trusted service-header auth."""
    path = request.url.path
    return any(
        request.method == method and re.match(pattern, path)
        for method, pattern in _SERVICE_AUTH_ALLOWED
    )


def _service_headers_valid(request: Request) -> bool:
    """Constant-time check of the shared service secret."""
    slack_secret = request.headers.get("X-Slack-Secret") or ""
    user_email = request.headers.get("X-User-Email")
    if not user_email or not slack_secret or not VALID_API_KEY:
        return False
    return hmac.compare_digest(slack_secret.encode(), VALID_API_KEY.encode())


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Trusted Slack Bot auth by email for existing users only (no auto-registration).
    # Restricted to the integration allowlist so a leaked API_KEY_SECRET cannot
    # be used to impersonate users on arbitrary endpoints.
    if _is_service_auth_allowed(request) and _service_headers_valid(request):
        user_email = request.headers.get("X-User-Email")
        user = await crud.get_user_by_email(db, email=user_email)
        if not user:
            raise credentials_exception
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )
        logger.info(
            "Service-header auth accepted for user %s on %s %s",
            user.id,
            request.method,
            request.url.path,
        )
        return user

    username = validate_token(token, credentials_exception)
    user = await crud.get_user_by_username(db, username=username)
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        )

    return user


async def get_current_user_from_token(
    token: str, db: AsyncSession
) -> models.User | None:
    """
    Helper function to resolve a User model directly from a JWT Bearer token string.
    """
    try:
        from .security import validate_token

        username = validate_token(token, None)
        if username:
            return await crud.get_user_by_username(db, username=username)
    except Exception as e:
        logger.error(f"Error decoding user from token: {e}")
    return None
