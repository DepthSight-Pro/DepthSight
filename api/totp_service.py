# api/totp_service.py
"""
Service for Two-Factor Authentication (2FA) using TOTP (RFC 6238).
Handles secret generation, QR code rendering, code verification with
replay protection, and backup recovery codes.
"""

import base64
import hashlib
import io
import logging
import secrets
import string
import time
from typing import Optional, Tuple, List

import pyotp
import qrcode

from . import security

logger = logging.getLogger(__name__)


def generate_totp_secret() -> str:
    """Generates a random Base32 secret for TOTP."""
    return pyotp.random_base32()


def get_totp_uri(username: str, secret: str, issuer: str = "DepthSight") -> str:
    """Generates the standard otpauth URI for authenticator apps."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def generate_qr_code_base64(totp_uri: str) -> str:
    """
    Generates a PNG QR code for the given TOTP URI
    and returns it as a data URL (data:image/png;base64,...).
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(totp_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64_encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64_encoded}"


def encrypt_totp_secret(secret: str) -> str:
    """Encrypts TOTP secret before persisting to database."""
    return security.encrypt_data(secret)


def decrypt_totp_secret(encrypted_secret: str) -> str:
    """Decrypts stored TOTP secret from database."""
    return security.decrypt_data(encrypted_secret)


def verify_totp_code(
    secret: str, code: str, last_step: Optional[int] = None
) -> Tuple[bool, Optional[int]]:
    """
    Verifies a 6-digit TOTP code against the given secret.
    Allows +-1 step (30 seconds) clock drift.
    Prevents replay attacks by ensuring the matched step is greater than last_step.

    Returns:
        (is_valid, matched_step)
    """
    if not code or not secret:
        return False, None

    cleaned_code = code.strip().replace(" ", "").replace("-", "")
    if not cleaned_code.isdigit() or len(cleaned_code) != 6:
        return False, None

    totp = pyotp.TOTP(secret, interval=30)
    current_time = time.time()
    current_step = int(current_time // 30)

    # Check across window: current step (0), previous (-1), next (+1)
    for step_offset in (0, -1, 1):
        step = current_step + step_offset
        step_time = step * 30
        expected_code = totp.at(step_time)
        if secrets.compare_digest(cleaned_code, expected_code):
            # Check against replay
            if last_step is not None and step <= last_step:
                logger.warning(
                    f"TOTP replay attempt detected: step {step} <= last_step {last_step}"
                )
                return False, None
            return True, step

    return False, None


def generate_backup_codes(
    count: int = 8, length: int = 10
) -> Tuple[List[str], List[str]]:
    """
    Generates a set of single-use backup recovery codes.
    Returns:
        (plain_codes, hashed_codes)
    """
    chars = string.ascii_uppercase + string.digits
    # Avoid visually ambiguous characters
    safe_chars = [c for c in chars if c not in ("0", "O", "1", "I", "L")]

    plain_codes = []
    hashed_codes = []

    for _ in range(count):
        raw_code = "".join(secrets.choice(safe_chars) for _ in range(length))
        # Format as XXXX-XXXX if length is 8 or more
        if length >= 8:
            formatted_code = f"{raw_code[: length // 2]}-{raw_code[length // 2 :]}"
        else:
            formatted_code = raw_code

        code_hash = hashlib.sha256(
            formatted_code.upper().replace("-", "").encode("utf-8")
        ).hexdigest()

        plain_codes.append(formatted_code)
        hashed_codes.append(code_hash)

    return plain_codes, hashed_codes


def verify_and_consume_backup_code(
    code: str, hashed_codes: Optional[List[str]]
) -> Tuple[bool, List[str]]:
    """
    Validates a backup code against stored hashes and consumes it (removes from list).
    Returns:
        (is_valid, remaining_hashed_codes)
    """
    if not code or not hashed_codes:
        return False, hashed_codes or []

    cleaned = code.strip().upper().replace("-", "").replace(" ", "")
    candidate_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()

    remaining = []
    found = False
    for h in hashed_codes:
        if not found and secrets.compare_digest(h, candidate_hash):
            found = True
        else:
            remaining.append(h)

    return found, remaining
