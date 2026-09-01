import re
import time
import uuid
import hashlib
import logging
from typing import Dict, Tuple, Optional
from eth_account import Account
from eth_account.messages import encode_defunct

logger = logging.getLogger(__name__)

# In-memory nonce cache: address.lower() -> (nonce, sign_message, timestamp)
_NONCE_CACHE: Dict[str, Tuple[str, str, float]] = {}
NONCE_EXPIRATION_SECONDS = 300  # 5 minutes

# Default TTL for ownership-authorization messages (self-verifying: no server
# state needed, safe across multiple uvicorn workers).
OWNERSHIP_AUTH_TTL_SECONDS = 300  # 5 minutes

OWNERSHIP_PURPOSE_BIND = "node-ownership"
OWNERSHIP_PURPOSE_REVOKE = "node-revoke"


def ownership_message_hash(message: str) -> str:
    """
    Returns the sha256 hex digest of the full ownership message text.

    Used as the single-use replay key: the same signed message can only be
    consumed once, even within its TTL window (see crud.claim_ownership_message).
    """
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def build_ownership_message(
    address: str,
    purpose: str = OWNERSHIP_PURPOSE_BIND,
    ttl_seconds: int = OWNERSHIP_AUTH_TTL_SECONDS,
) -> str:
    """
    Builds a self-verifying ownership-authorization message for an EVM address.

    The message embeds the wallet address, purpose, a unique nonce and an
    absolute expiry, so a signature over it can be verified by ANY service
    (local node and the hub) without shared nonce state. The per-message nonce
    lets one wallet hold several concurrently valid authorizations (e.g.
    binding servers A and B in the same second) while the message-hash replay
    registry blocks resubmission of an intercepted signature. Suitable for
    single-writer ops like binding a node, re-keying the telemetry secret,
    binding a referrer or revoking.
    """
    expires_at = int(time.time()) + ttl_seconds
    clean_addr = address.strip().lower()
    return (
        f"DepthSight Trade Mining — Node Ownership Authorization\n\n"
        f"Wallet Address: {clean_addr}\n"
        f"Purpose: {purpose}\n"
        f"Nonce: {uuid.uuid4().hex}\n"
        f"Expires At: {expires_at}"
    )


def verify_ownership_signature(
    address: str,
    signature: str,
    message: str,
    purpose: Optional[str] = None,
    max_age_seconds: int = OWNERSHIP_AUTH_TTL_SECONDS,
) -> bool:
    """
    Verifies a signature over a ``build_ownership_message`` message.

    Checks the embedded address/purpose match the expected ones and that the
    message has not expired. No server-side nonce state is required.
    """
    clean_addr = address.strip().lower()
    try:
        addr_match = re.search(r"Wallet Address:\s*(\S+)", message)
        purpose_match = re.search(r"Purpose:\s*(\S+)", message)
        expires_match = re.search(r"Expires At:\s*(\d+)", message)
        if not addr_match or not expires_match or not purpose_match:
            return False
        if addr_match.group(1).lower() != clean_addr:
            return False
        if purpose and purpose_match.group(1).strip() != purpose:
            return False
        expires_at = int(expires_match.group(1))
        now = time.time()
        if not (now <= expires_at <= now + max_age_seconds):
            return False
        encoded_msg = encode_defunct(text=message)
        recovered_address = Account.recover_message(encoded_msg, signature=signature)
        return recovered_address.lower() == clean_addr
    except Exception as e:
        logger.error(f"Error verifying ownership signature for {address}: {e}")
        return False


def generate_wallet_nonce(address: str) -> Tuple[str, str]:
    """
    Generates a secure random nonce and SIWE-style signable message for an EVM address.
    """
    clean_addr = address.strip().lower()
    nonce = f"depthsight-nonce-{uuid.uuid4().hex}"
    timestamp = time.time()

    sign_message = (
        f"DepthSight Trade Mining Authentication\n\n"
        f"Sign this message to verify ownership of your wallet for trade mining rewards.\n\n"
        f"Wallet Address: {address}\n"
        f"Nonce: {nonce}\n"
        f"Timestamp: {int(timestamp)}"
    )

    _NONCE_CACHE[clean_addr] = (nonce, sign_message, timestamp)

    # Cleanup expired nonces (> 10 mins old)
    now = time.time()
    expired = [k for k, v in _NONCE_CACHE.items() if now - v[2] > 600]
    for k in expired:
        _NONCE_CACHE.pop(k, None)

    return nonce, sign_message


def verify_wallet_signature(address: str, signature: str, nonce: str) -> bool:
    """
    Verifies that the given signature was produced by the EVM address for the expected nonce.
    """
    clean_addr = address.strip().lower()
    cached = _NONCE_CACHE.get(clean_addr)

    if not cached:
        logger.warning(f"No cached nonce found for address: {address}")
        return False

    cached_nonce, sign_message, timestamp = cached

    if cached_nonce != nonce:
        logger.warning(
            f"Nonce mismatch for {address}: expected {cached_nonce}, got {nonce}"
        )
        return False

    if time.time() - timestamp > NONCE_EXPIRATION_SECONDS:
        logger.warning(f"Expired nonce for address {address}")
        _NONCE_CACHE.pop(clean_addr, None)
        return False

    try:
        encoded_msg = encode_defunct(text=sign_message)
        recovered_address = Account.recover_message(encoded_msg, signature=signature)
        is_valid = recovered_address.lower() == clean_addr
        if is_valid:
            # Nonce used successfully -> consume it
            _NONCE_CACHE.pop(clean_addr, None)
        return is_valid
    except Exception as e:
        logger.error(f"Error verifying EVM signature for {address}: {e}")
        return False
