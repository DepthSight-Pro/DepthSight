import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from api.wallet_auth import (
    OWNERSHIP_PURPOSE_BIND,
    OWNERSHIP_PURPOSE_REVOKE,
    build_ownership_message,
    generate_wallet_nonce,
    verify_ownership_signature,
    verify_wallet_signature,
)


@pytest.mark.asyncio
async def test_evm_siwe_nonce_and_signature_verification():
    # Generate random EVM test account
    acct = Account.create()
    address = acct.address

    # 1. Generate nonce
    nonce, sign_message = generate_wallet_nonce(address)
    assert nonce.startswith("depthsight-nonce-")
    assert address in sign_message

    # 2. Sign message using private key
    encoded_msg = encode_defunct(text=sign_message)
    signed = acct.sign_message(encoded_msg)
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = f"0x{signature}"

    # 3. Verify valid signature
    is_valid = verify_wallet_signature(address, signature, nonce)
    assert is_valid is True

    # 4. Attempt replay with consumed nonce -> should fail
    is_replay_valid = verify_wallet_signature(address, signature, nonce)
    assert is_replay_valid is False


@pytest.mark.asyncio
async def test_invalid_signature_rejection():
    acct1 = Account.create()
    acct2 = Account.create()

    nonce, sign_message = generate_wallet_nonce(acct1.address)

    # Sign with acct2 private key instead
    encoded_msg = encode_defunct(text=sign_message)
    signed = acct2.sign_message(encoded_msg)
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = f"0x{signature}"

    # Verification for acct1 should fail because it was signed by acct2
    is_valid = verify_wallet_signature(acct1.address, signature, nonce)
    assert is_valid is False


def _sign_message(acct: Account, message: str) -> str:
    encoded_msg = encode_defunct(text=message)
    sig = acct.sign_message(encoded_msg)["signature"].hex()
    if not sig.startswith("0x"):
        sig = f"0x{sig}"
    return sig


@pytest.mark.asyncio
async def test_ownership_signature_valid_bind_purpose():
    acct = Account.create()
    message = build_ownership_message(acct.address, purpose=OWNERSHIP_PURPOSE_BIND)
    sig = _sign_message(acct, message)

    assert (
        verify_ownership_signature(
            acct.address, sig, message, purpose=OWNERSHIP_PURPOSE_BIND
        )
        is True
    )


@pytest.mark.asyncio
async def test_ownership_signature_rejects_wrong_purpose():
    acct = Account.create()
    message = build_ownership_message(acct.address, purpose=OWNERSHIP_PURPOSE_BIND)
    sig = _sign_message(acct, message)

    assert (
        verify_ownership_signature(
            acct.address, sig, message, purpose=OWNERSHIP_PURPOSE_REVOKE
        )
        is False
    )


@pytest.mark.asyncio
async def test_ownership_signature_rejects_other_wallet():
    acct1 = Account.create()
    acct2 = Account.create()
    message = build_ownership_message(acct1.address, purpose=OWNERSHIP_PURPOSE_BIND)
    sig = _sign_message(acct2, message)

    assert (
        verify_ownership_signature(
            acct1.address, sig, message, purpose=OWNERSHIP_PURPOSE_BIND
        )
        is False
    )


@pytest.mark.asyncio
async def test_ownership_signature_rejects_tampered_address():
    acct = Account.create()
    message = build_ownership_message(acct.address, purpose=OWNERSHIP_PURPOSE_BIND)
    sig = _sign_message(acct, message)

    # Recover with a different (but valid-looking) address.
    tampered = message.replace(acct.address.lower(), "0x" + "1" * 40)
    assert (
        verify_ownership_signature(
            acct.address, sig, tampered, purpose=OWNERSHIP_PURPOSE_BIND
        )
        is False
    )


@pytest.mark.asyncio
async def test_ownership_signature_rejects_expired_message():
    import time

    acct = Account.create()
    # Build a message that already expired.
    message = (
        f"DepthSight Trade Mining — Node Ownership Authorization\n\n"
        f"Wallet Address: {acct.address.lower()}\n"
        f"Purpose: {OWNERSHIP_PURPOSE_BIND}\n"
        f"Expires At: {int(time.time()) - 60}"
    )
    sig = _sign_message(acct, message)

    assert (
        verify_ownership_signature(
            acct.address, sig, message, purpose=OWNERSHIP_PURPOSE_BIND
        )
        is False
    )


def test_ownership_message_includes_unique_nonce():
    """Every generated message carries a unique Nonce so a wallet can hold
    several concurrently valid authorizations (parallel server binds)."""
    acct = Account.create()
    m1 = build_ownership_message(acct.address, purpose=OWNERSHIP_PURPOSE_BIND)
    m2 = build_ownership_message(acct.address, purpose=OWNERSHIP_PURPOSE_BIND)

    assert "Nonce:" in m1
    assert "Nonce:" in m2
    assert m1 != m2


@pytest.mark.asyncio
async def test_verify_accepts_legacy_message_without_nonce():
    """Backward compatibility: messages issued before the nonce line was added
    (no `Nonce:` field) must still verify — replay protection relies on the
    message-hash registry, not on the nonce presence."""
    import time

    acct = Account.create()
    message = (
        f"DepthSight Trade Mining — Node Ownership Authorization\n\n"
        f"Wallet Address: {acct.address.lower()}\n"
        f"Purpose: {OWNERSHIP_PURPOSE_BIND}\n"
        f"Expires At: {int(time.time()) + 120}"
    )
    sig = _sign_message(acct, message)

    assert (
        verify_ownership_signature(
            acct.address, sig, message, purpose=OWNERSHIP_PURPOSE_BIND
        )
        is True
    )
