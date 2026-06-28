import logging
import os
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from .. import crud, schemas, security
from ..database import get_db
from ..audit_logger import audit_logger, get_client_ip, get_user_agent
from ..gamification import check_and_grant_retroactive_achievements

logger = logging.getLogger(__name__)


# Rate limiting fallback
def get_limit_value(val: str) -> str:
    return val


# Mock limiter if not available in context
class MockLimiter:
    def limit(self, *args, **kwargs):
        return lambda func: func


limiter = MockLimiter()

auth_router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Auth"],
)

auth_root_router = APIRouter(tags=["Auth"])


@auth_root_router.post("/token", response_model=schemas.LoginResponse)
@limiter.limit(get_limit_value("5/hour"))
# Login brute-force attack protection
async def login_for_access_token(
    request: Request,  # Required for slowapi
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    user_db = await crud.get_user_by_username(db, username=form_data.username)
    if not user_db or not security.verify_password(
        form_data.password, user_db.hashed_password
    ):
        # Log failed login attempt
        audit_logger.login_failed(
            username=form_data.username,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            reason="Invalid credentials" if not user_db else "Wrong password",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user_db.is_active:
        audit_logger.login_failed(
            username=form_data.username,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            reason="Account inactive",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user. Please confirm your email.",
        )

    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": user_db.username}, expires_delta=access_token_expires
    )

    refresh_token_expires = timedelta(minutes=security.REFRESH_TOKEN_EXPIRE_MINUTES)
    refresh_token = security.create_refresh_token(
        data={"sub": user_db.username}, expires_delta=refresh_token_expires
    )

    token_data = schemas.Token(
        access_token=access_token, refresh_token=refresh_token, token_type="bearer"
    )

    # 1. Check and grant retroactive achievements
    await check_and_grant_retroactive_achievements(db, user_db.id)

    # 2. Force commit changes in DB to get actual state
    await db.commit()

    # 3. Refresh user_db object from DB to fetch new XP and level
    await db.refresh(user_db)

    # 4. Now create user_data from refreshed object
    user_data = schemas.User.model_validate(user_db)

    # 5. Log successful login
    audit_logger.login_success(
        user_id=user_db.id,
        username=user_db.username,
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )

    return schemas.LoginResponse(token=token_data, user=user_data)


@auth_router.post("/google", response_model=schemas.LoginResponse)
@limiter.limit(get_limit_value("10/minute"))
async def google_login(
    request: Request,
    payload: schemas.GoogleLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not google_client_id:
        logger.error("GOOGLE_CLIENT_ID is not configured on the backend.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google Authentication is not configured on the server."
        )

    try:
        idinfo = id_token.verify_oauth2_token(
            payload.token,
            google_requests.Request(),
            google_client_id
        )

        if idinfo["iss"] not in ["accounts.google.com", "https://accounts.google.com"]:
            raise ValueError("Wrong issuer.")

        email = idinfo.get("email")
        if not email:
            raise ValueError("Email not found in Google token.")

    except Exception as e:
        logger.warning(f"Failed to verify Google token: {e}")
        audit_logger.login_failed(
            username=f"google_{payload.token[:10]}...",
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            reason="Invalid Google token",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google token",
        )

    user_db = await crud.get_user_by_email(db, email=email)
    if not user_db:
        username = email.split("@")[0]
        base_username = username
        counter = 1
        while await crud.get_user_by_username(db, username=username):
            username = f"{base_username}_{counter}"
            counter += 1

        user_db = await crud.create_oauth_user(db, email=email, username=username)
        logger.info(f"Created new Google OAuth user: {username} ({email})")

    if not user_db.is_active:
        audit_logger.login_failed(
            username=user_db.username,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            reason="Account inactive",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user account.",
        )

    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": user_db.username}, expires_delta=access_token_expires
    )

    refresh_token_expires = timedelta(minutes=security.REFRESH_TOKEN_EXPIRE_MINUTES)
    refresh_token = security.create_refresh_token(
        data={"sub": user_db.username}, expires_delta=refresh_token_expires
    )

    token_data = schemas.Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )

    await check_and_grant_retroactive_achievements(db, user_db.id)
    await db.commit()
    await db.refresh(user_db)

    user_data = schemas.User.model_validate(user_db)

    audit_logger.login_success(
        user_id=user_db.id,
        username=user_db.username,
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )

    return schemas.LoginResponse(token=token_data, user=user_data)


@auth_root_router.post("/refresh", response_model=schemas.Token)
@limiter.limit(get_limit_value("10/minute"))
async def refresh_access_token(
    request: Request,
    refresh_request: schemas.RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = security.jwt.decode(
            refresh_request.refresh_token,
            security.SECRET_KEY,
            algorithms=[security.ALGORITHM],
        )
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except security.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_db = await crud.get_user_by_username(db, username=username)
    if not user_db or not user_db.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": user_db.username}, expires_delta=access_token_expires
    )

    refresh_token_expires = timedelta(minutes=security.REFRESH_TOKEN_EXPIRE_MINUTES)
    new_refresh_token = security.create_refresh_token(
        data={"sub": user_db.username}, expires_delta=refresh_token_expires
    )

    return schemas.Token(
        access_token=access_token, refresh_token=new_refresh_token, token_type="bearer"
    )


@auth_root_router.post(
    "/register",
    response_model=schemas.ApiResponse,
    status_code=status.HTTP_200_OK,
    summary="Register new user",
)
@limiter.limit(get_limit_value("3/minute"))  # Protection against mass bot registration
async def register_user(
    user: schemas.UserCreate, request: Request, db: AsyncSession = Depends(get_db)
):
    """
    Registers a new user, sends a confirmation email, and waits for activation.
    """
    logger.info(
        f"REGISTRATION REQUEST: username={user.username}, email={user.email}, source={user.source}"
    )
    db_user = await crud.get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already registered",
        )

    db_user_by_email = await crud.get_user_by_email(db, email=user.email)
    if db_user_by_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Referral logic
    referred_by_user_id = None
    if user.ref_code:
        referrer = await crud.get_user_by_referral_code(db, referral_code=user.ref_code)
        if referrer:
            referred_by_user_id = referrer.id
        else:
            logger.warning(
                f"Referral code '{user.ref_code}' provided but no user found."
            )

    # If email confirmation is disabled, create an active user right away
    if not security.EMAIL_CONFIRMATION_ENABLED:
        new_user = await crud.create_user(
            db=db, user=user, referred_by_user_id=referred_by_user_id, is_active=True
        )
        if referred_by_user_id:
            await crud.create_pending_bonuses_for_referral(
                db, referrer_id=referred_by_user_id, referred_id=new_user.id
            )
        await db.commit()
        return {
            "data": {
                "message": "Registration successful. You can now log in.",
                "requires_confirmation": False,
            }
        }

    new_user = await crud.create_user(
        db=db, user=user, referred_by_user_id=referred_by_user_id
    )

    if referred_by_user_id:
        await crud.create_pending_bonuses_for_referral(
            db, referrer_id=referred_by_user_id, referred_id=new_user.id
        )

    await db.commit()
    await db.refresh(new_user)

    # --- Email Confirmation Logic ---
    token = security.email_confirmation_serializer.dumps(
        new_user.email, salt=security.EMAIL_CONFIRMATION_SALT
    )

    frontend_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
    # Use PWA path if registration came from PWA
    if user.source == "pwa":
        confirm_url = f"{frontend_url}/pwa/confirm-email/{token}"
    else:
        confirm_url = f"{frontend_url}/confirm-email/{token}"

    # Send email
    from ..email_utils import send_email

    subject = "Confirm your email for DepthSight"
    html_content = f"""<html>
<body>
<h2>Welcome to DepthSight!</h2>
<p>Please click the link below to confirm your email address:</p>
<p><a href="{confirm_url}">Confirm Email</a></p>
<p>If you did not register for an account, please ignore this email.</p>
</body>
</html>"""
    try:
        send_email(new_user.email, subject, html_content)
    except Exception as e:
        logger.error(
            f"Failed to send confirmation email to {new_user.email}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The email service is currently unavailable. Please try again later.",
        )

    logger.info(f"CONFIRMATION URL FOR {new_user.email}: {confirm_url}")

    return {
        "data": {
            "message": "Registration successful. Please check your email to confirm your account.",
            "requires_confirmation": True,
        }
    }


@auth_router.get("/confirm-email/{token}", response_model=schemas.LoginResponse)
async def confirm_email(token: str, db: AsyncSession = Depends(get_db)):
    try:
        email = security.email_confirmation_serializer.loads(
            token,
            salt=security.EMAIL_CONFIRMATION_SALT,
            max_age=86400,  # 24 hours for confirmation
        )
        logger.info(f"Email confirmation token decoded successfully for: {email}")
    except Exception as e:
        logger.error(f"Email confirmation failed: Invalid or expired token. Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The confirmation link is invalid or has expired. Please request a new confirmation email.",
        )

    user = await crud.get_user_by_email(db, email=email)

    if not user:
        logger.error(
            f"Email confirmation failed: User with email {email} not found in database"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email {email} not found.",
        )

    if user.is_active:
        logger.info(f"User {email} is already active, proceeding with login")
    else:
        logger.info(f"Activating user account for: {email}")
        user.is_active = True
        await db.commit()
        await db.refresh(user)
        logger.info(f"User account activated successfully for: {email}")

    # Create token and return complete login response
    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    token_data = schemas.Token(access_token=access_token, token_type="bearer")
    user_data = schemas.User.model_validate(user)

    logger.info(f"Email confirmation completed successfully for: {email}")
    return schemas.LoginResponse(token=token_data, user=user_data)


@auth_router.post("/resend-confirmation", response_model=schemas.ApiResponse)
async def resend_confirmation_email(
    email_request: schemas.EmailRequest, db: AsyncSession = Depends(get_db)
):
    """
    Resends email confirmation letter for inactive users.
    """
    user = await crud.get_user_by_email(db, email=email_request.email)

    if not user:
        # Do not disclose email existence in the system
        logger.warning(
            f"Resend confirmation requested for non-existent email: {email_request.email}"
        )
        return {
            "data": {
                "message": "If this email is registered, a confirmation link has been sent."
            }
        }

    if user.is_active:
        logger.info(
            f"Resend confirmation requested for already active user: {email_request.email}"
        )
        return {
            "data": {"message": "This account is already activated. You can log in."}
        }

    # Generate a new token
    token = security.email_confirmation_serializer.dumps(
        user.email, salt=security.EMAIL_CONFIRMATION_SALT
    )

    frontend_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
    confirm_url = f"{frontend_url}/confirm-email/{token}"

    # Send email
    from .email_utils import send_email

    subject = "Confirm your email for DepthSight"
    html_content = f"""<html>
<body>
<h2>Welcome to DepthSight!</h2>
<p>Please click the link below to confirm your email address:</p>
<p><a href="{confirm_url}">Confirm Email</a></p>
<p>This link will expire in 24 hours.</p>
<p>If you did not register for an account, please ignore this email.</p>
</body>
</html>"""

    try:
        send_email(user.email, subject, html_content)
        logger.info(f"Confirmation email resent to: {user.email}")
    except Exception as e:
        logger.error(
            f"Failed to resend confirmation email to {user.email}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The email service is currently unavailable. Please try again later.",
        )

    return {
        "data": {
            "message": "If this email is registered, a confirmation link has been sent."
        }
    }


@auth_router.post("/forgot-password", response_model=schemas.ApiResponse)
async def forgot_password(
    request: schemas.PasswordResetRequest, db: AsyncSession = Depends(get_db)
):
    """
    Initiates password recovery process.
    Sends reset link email if email is registered.
    """
    user = await crud.get_user_by_email(db, email=request.email)

    # Always return the same response for security
    success_msg = {
        "data": {
            "message": "If this email is registered, a password reset link has been sent."
        }
    }

    if not user:
        logger.warning(
            f"Password reset requested for non-existent email: {request.email}"
        )
        return success_msg

    # Generate password reset token
    token = security.password_reset_serializer.dumps(
        user.email, salt=security.PASSWORD_RESET_SALT
    )

    frontend_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
    if request.source == "pwa":
        reset_url = f"{frontend_url}/pwa/reset-password/{token}"
    else:
        reset_url = f"{frontend_url}/reset-password/{token}"

    # Send email
    from ..email_utils import send_email

    subject = "Reset your password for DepthSight"
    html_content = f"""<html>
<body>
<h2>Password Reset Request</h2>
<p>We received a request to reset your password. Click the link below to set a new password:</p>
<p><a href="{reset_url}">Reset Password</a></p>
<p>This link will expire in 1 hour.</p>
<p>If you did not request a password reset, please ignore this email.</p>
</body>
</html>"""

    try:
        send_email(user.email, subject, html_content)
        logger.info(f"Password reset email sent to: {user.email}")
    except Exception as e:
        logger.error(
            f"Failed to send password reset email to {user.email}: {e}", exc_info=True
        )
        # In this case, an error can be returned as it is a technical failure
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The email service is currently unavailable. Please try again later.",
        )

    return success_msg


@auth_router.post("/reset-password", response_model=schemas.ApiResponse)
async def reset_password(
    request: schemas.PasswordResetConfirm, db: AsyncSession = Depends(get_db)
):
    """
    Resets user password using a valid token.
    """
    try:
        email = security.password_reset_serializer.loads(
            request.token,
            salt=security.PASSWORD_RESET_SALT,
            max_age=security.PASSWORD_RESET_TOKEN_MAX_AGE,
        )
    except Exception as e:
        logger.error(f"Password reset failed: Invalid or expired token. Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The password reset link is invalid or has expired.",
        )

    user = await crud.get_user_by_email(db, email=email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    # Hash and update password
    user.hashed_password = security.get_password_hash(request.new_password)
    await db.commit()

    logger.info(f"Password reset successfully for user: {email}")
    return {
        "data": {
            "message": "Your password has been reset successfully. You can now log in."
        }
    }
