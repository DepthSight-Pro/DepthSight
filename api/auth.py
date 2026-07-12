from fastapi import Depends, HTTPException, status, Request
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from . import models, crud  # Assuming these exist or will be created
from .database import get_db  # Assuming this exists
from .security import validate_token, oauth2_scheme

import os
from dotenv import load_dotenv

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
    if not api_key_header or api_key_header != VALID_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key"
        )
    return api_key_header


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> models.User:
    # Check for trusted Slack Bot bypass header
    slack_secret = request.headers.get("X-Slack-Secret")
    user_email = request.headers.get("X-User-Email")
    if slack_secret and slack_secret == VALID_API_KEY and user_email:
        user = await crud.get_user_by_email(db, email=user_email)
        if user:
            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User account is inactive",
                )
            return user

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    username = validate_token(token, credentials_exception)
    user = await crud.get_user_by_username(db, username=username)
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        )

    return user
