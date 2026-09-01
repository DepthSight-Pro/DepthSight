# tests/test_hub_node_ownership.py
"""
Tests for wallet-ownership enforcement on hub node registration.

For wallet-bound nodes the EVM wallet is the ownership credential: creating a
wallet node, rotating its telemetry secret, binding a referrer and flagging it as
a mining server all require a valid wallet ownership signature. The node secret is
only a write-only telemetry credential and cannot rotate without the wallet.
"""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy.future import select

from api import models
from api.depthsight_api import app
from api.hub_router import router as hub_router
from api.wallet_auth import (
    OWNERSHIP_PURPOSE_BIND,
    OWNERSHIP_PURPOSE_REVOKE,
    build_ownership_message,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    has_hub = any(
        getattr(route, "path", "").startswith("/api/v1/hub") for route in app.routes
    )
    if not has_hub:
        app.include_router(hub_router)


def _sign_ownership(acct: Account, purpose: str = OWNERSHIP_PURPOSE_BIND):
    """Returns (message, signature) for the account over an ownership message."""
    message = build_ownership_message(acct.address, purpose=purpose)
    encoded = encode_defunct(text=message)
    sig = acct.sign_message(encoded)["signature"].hex()
    if not sig.startswith("0x"):
        sig = f"0x{sig}"
    return message, sig


async def _get_node(db_session, node_uuid: str):
    res = await db_session.execute(
        select(models.HubNode)
        .where(models.HubNode.node_uuid == node_uuid)
        .execution_options(populate_existing=True)
    )
    return res.scalars().first()


async def test_wallet_node_creation_requires_ownership(test_client, db_session):
    acct = Account.create()
    payload = {
        "node_uuid": f"wallet-node-{acct.address[-8:].lower()}",
        "name": "Wallet Node",
        "node_secret": "telemetry-secret-1",
        "wallet_address": acct.address,
        # No owner signature -> creation must be rejected
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=payload)
    assert resp.status_code == 403

    node = await _get_node(db_session, payload["node_uuid"])
    assert node is None


async def test_wallet_node_creation_with_ownership(test_client, db_session):
    acct = Account.create()
    node_uuid = f"wallet-node-{acct.address[-8:].lower()}"
    message, sig = _sign_ownership(acct)
    payload = {
        "node_uuid": node_uuid,
        "name": "Wallet Node",
        "node_secret": "telemetry-secret-1",
        "wallet_address": acct.address,
        "owner_signature": sig,
        "owner_message": message,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=payload)
    assert resp.status_code == 201

    node = await _get_node(db_session, node_uuid)
    assert node is not None
    assert node.wallet_address == acct.address.lower()
    assert node.secret_hash


async def test_wallet_node_secret_rotation_requires_ownership(test_client, db_session):
    acct = Account.create()
    node_uuid = f"wallet-node-{acct.address[-8:].lower()}"
    message, sig = _sign_ownership(acct)
    base = {
        "node_uuid": node_uuid,
        "name": "Wallet Node",
        "node_secret": "telemetry-secret-1",
        "wallet_address": acct.address,
        "owner_signature": sig,
        "owner_message": message,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=base)
    assert resp.status_code == 201
    node = await _get_node(db_session, node_uuid)
    original_hash = node.secret_hash

    # Re-register with a DIFFERENT secret and NO owner signature -> rejected.
    changed = dict(base)
    changed["node_secret"] = "telemetry-secret-2"
    changed.pop("owner_signature", None)
    changed.pop("owner_message", None)
    resp = await test_client.post("/api/v1/hub/nodes/register", json=changed)
    assert resp.status_code == 403

    node = await _get_node(db_session, node_uuid)
    assert node.secret_hash == original_hash

    # With a fresh owner signature the secret may rotate.
    message2, sig2 = _sign_ownership(acct)
    changed["owner_signature"] = sig2
    changed["owner_message"] = message2
    resp = await test_client.post("/api/v1/hub/nodes/register", json=changed)
    assert resp.status_code in (200, 201)

    node = await _get_node(db_session, node_uuid)
    assert node.secret_hash != original_hash


async def test_wallet_address_cannot_be_rebound(test_client, db_session):
    acct = Account.create()
    other = Account.create()
    node_uuid = f"wallet-node-{acct.address[-8:].lower()}"
    message, sig = _sign_ownership(acct)
    base = {
        "node_uuid": node_uuid,
        "name": "Wallet Node",
        "node_secret": "telemetry-secret-1",
        "wallet_address": acct.address,
        "owner_signature": sig,
        "owner_message": message,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=base)
    assert resp.status_code == 201

    # Attempt to bind to a different wallet with that wallet's signature.
    message2, sig2 = _sign_ownership(other)
    changed = dict(base)
    changed["wallet_address"] = other.address
    changed["owner_signature"] = sig2
    changed["owner_message"] = message2
    resp = await test_client.post("/api/v1/hub/nodes/register", json=changed)
    assert resp.status_code == 403

    node = await _get_node(db_session, node_uuid)
    assert node.wallet_address == acct.address.lower()


async def test_legacy_node_secret_mismatch_still_rejected(test_client, db_session):
    """Legacy (non-wallet) nodes keep secret-based ownership semantics."""
    payload = {
        "node_uuid": "legacy-node-0001",
        "name": "Legacy Node",
        "node_secret": "secret-A",
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=payload)
    assert resp.status_code == 201

    payload["node_secret"] = "secret-B"
    resp = await test_client.post("/api/v1/hub/nodes/register", json=payload)
    assert resp.status_code == 403


async def test_referrer_and_mining_flag_gated_for_wallet_node(test_client, db_session):
    acct = Account.create()
    node_uuid = f"wallet-node-{acct.address[-8:].lower()}"
    message, sig = _sign_ownership(acct)
    base = {
        "node_uuid": node_uuid,
        "name": "Wallet Node",
        "node_secret": "telemetry-secret-1",
        "wallet_address": acct.address,
        "owner_signature": sig,
        "owner_message": message,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=base)
    assert resp.status_code == 201

    # Re-register with the SAME secret, an is_mining_server flag and a referrer,
    # but NO owner signature -> sensitive changes must be ignored (metadata-only).
    changed = dict(base)
    changed["is_mining_server"] = True
    changed["referrer_code"] = "DSN-REF-ATTACK"
    changed.pop("owner_signature", None)
    changed.pop("owner_message", None)
    resp = await test_client.post("/api/v1/hub/nodes/register", json=changed)
    assert resp.status_code in (200, 201)

    node = await _get_node(db_session, node_uuid)
    assert node.is_mining_server is False
    assert node.referrer_node_uuid is None


async def test_telemetry_revoke_requires_ownership(test_client, db_session):
    acct = Account.create()
    node_uuid = f"wallet-node-{acct.address[-8:].lower()}"
    message, sig = _sign_ownership(acct)
    base = {
        "node_uuid": node_uuid,
        "name": "Wallet Node",
        "node_secret": "telemetry-secret-1",
        "wallet_address": acct.address,
        "owner_signature": sig,
        "owner_message": message,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=base)
    assert resp.status_code == 201

    # Revoke without a signature -> rejected.
    resp = await test_client.post(
        "/api/v1/hub/nodes/revoke-telemetry", json={"node_uuid": node_uuid}
    )
    assert resp.status_code == 403

    # Revoke with a valid REVOKE-purpose signature -> secret cleared.
    message_r, sig_r = _sign_ownership(acct, purpose=OWNERSHIP_PURPOSE_REVOKE)
    resp = await test_client.post(
        "/api/v1/hub/nodes/revoke-telemetry",
        json={
            "node_uuid": node_uuid,
            "owner_signature": sig_r,
            "owner_message": message_r,
        },
    )
    assert resp.status_code == 200
    node = await _get_node(db_session, node_uuid)
    assert node.secret_hash in (None, "")


async def test_revoke_rejected_for_legacy_node(test_client, db_session):
    resp = await test_client.post(
        "/api/v1/hub/nodes/revoke-telemetry",
        json={
            "node_uuid": "does-not-exist",
            "owner_signature": "x",
            "owner_message": "y",
        },
    )
    assert resp.status_code == 404


async def test_wallet_verify_message_based(
    authenticated_client_factory, current_user, monkeypatch
):
    """
    The /node/wallet/verify endpoint must accept a signature over the self-verifying
    ownership message (no shared nonce state), and bind the wallet-derived node.
    """
    import uuid

    # Treat this process as the central hub so the local->hub registration
    # forward (a real network call) is skipped; we only test message verification.
    monkeypatch.setenv("IS_CENTRAL_HUB", "true")

    client = await authenticated_client_factory(current_user)
    acct = Account.create()
    message = build_ownership_message(acct.address, purpose=OWNERSHIP_PURPOSE_BIND)
    encoded = encode_defunct(text=message)
    sig = acct.sign_message(encoded)["signature"].hex()
    if not sig.startswith("0x"):
        sig = f"0x{sig}"

    resp = await client.post(
        "/api/v1/node/wallet/verify",
        json={
            "address": acct.address,
            "signature": sig,
            "nonce": message,
            "message": message,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    expected_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"evm:{acct.address.lower()}"))
    assert data["nodeUuid"] == expected_uuid
    assert data["walletAddress"] == acct.address.lower()


async def test_wallet_verify_rejects_bad_signature(
    authenticated_client_factory, current_user, monkeypatch
):
    monkeypatch.setenv("IS_CENTRAL_HUB", "true")

    client = await authenticated_client_factory(current_user)
    acct = Account.create()
    other = Account.create()
    # Sign with a DIFFERENT wallet over the ownership message of acct.
    message = build_ownership_message(acct.address, purpose=OWNERSHIP_PURPOSE_BIND)
    encoded = encode_defunct(text=message)
    sig = other.sign_message(encoded)["signature"].hex()
    if not sig.startswith("0x"):
        sig = f"0x{sig}"

    resp = await client.post(
        "/api/v1/node/wallet/verify",
        json={
            "address": acct.address,
            "signature": sig,
            "nonce": message,
            "message": message,
        },
    )
    assert resp.status_code == 401


async def test_transfer_adopts_legacy_wallet_node(test_client, db_session):
    """
    A node bound to a wallet under a NON-deterministic uuid (older builds) must be
    adopted under the deterministic uuid when a transfer re-registers it, instead of
    creating a duplicate wallet node.
    """
    import uuid as _uuid

    acct = Account.create()
    deterministic_uuid = str(
        _uuid.uuid5(_uuid.NAMESPACE_DNS, f"evm:{acct.address.lower()}")
    )
    legacy_uuid = f"legacy-{acct.address[-8:].lower()}"

    # Seed a legacy node bound to this wallet with a random uuid.
    legacy = models.HubNode(
        node_uuid=legacy_uuid,
        name="Legacy Node",
        secret_hash="old-hash",
        node_referral_code="DSN-REF-LEGACY-1234",
        total_mined=0.0,
        has_welcome_bonus=False,
        wallet_address=acct.address.lower(),
    )
    db_session.add(legacy)
    await db_session.commit()

    # Server B transfers with the deterministic uuid + wallet ownership signature.
    message, sig = _sign_ownership(acct)
    resp = await test_client.post(
        "/api/v1/hub/nodes/register",
        json={
            "node_uuid": deterministic_uuid,
            "name": "DepthSightNode-Transfer",
            "node_secret": "telemetry-secret-transfer",
            "wallet_address": acct.address,
            "owner_signature": sig,
            "owner_message": message,
        },
    )
    assert resp.status_code == 201

    # The legacy node was adopted: no duplicate, deterministic uuid, secret rotated,
    # referral history preserved.
    res = await db_session.execute(
        select(models.HubNode)
        .where(models.HubNode.wallet_address == acct.address.lower())
        .execution_options(populate_existing=True)
    )
    nodes = res.scalars().all()
    assert len(nodes) == 1
    adopted = nodes[0]
    assert adopted.node_uuid == deterministic_uuid
    assert adopted.node_referral_code == "DSN-REF-LEGACY-1234"
    import hashlib

    assert (
        adopted.secret_hash == hashlib.sha256(b"telemetry-secret-transfer").hexdigest()
    )


async def _register_wallet_node(test_client, acct: Account, secret: str):
    node_uuid = f"wallet-node-{acct.address[-8:].lower()}"
    message, sig = _sign_ownership(acct)
    payload = {
        "node_uuid": node_uuid,
        "name": "Wallet Node",
        "node_secret": secret,
        "wallet_address": acct.address,
        "owner_signature": sig,
        "owner_message": message,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=payload)
    return node_uuid, resp


async def test_bind_signature_cannot_be_replayed(test_client, db_session):
    """A consumed ownership signature must not authorize a second rotation,
    even while still inside its TTL window (replay protection)."""
    import hashlib

    acct = Account.create()
    node_uuid = f"wallet-node-{acct.address[-8:].lower()}"
    message, sig = _sign_ownership(acct)
    base = {
        "node_uuid": node_uuid,
        "name": "Wallet Node",
        "node_secret": "telemetry-secret-1",
        "wallet_address": acct.address,
        "owner_signature": sig,
        "owner_message": message,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=base)
    assert resp.status_code == 201
    node = await _get_node(db_session, node_uuid)
    assert node.secret_hash == hashlib.sha256(b"telemetry-secret-1").hexdigest()

    # Replay the EXACT same signed message with a DIFFERENT secret: the
    # rotation must be rejected although the signature itself is still valid.
    replayed = dict(base)
    replayed["node_secret"] = "telemetry-secret-2"
    resp = await test_client.post("/api/v1/hub/nodes/register", json=replayed)
    assert resp.status_code == 403

    node = await _get_node(db_session, node_uuid)
    assert node.secret_hash == hashlib.sha256(b"telemetry-secret-1").hexdigest()


async def test_replayed_revoke_signature_rejected(test_client, db_session):
    """The second revoke with the SAME signed message must be rejected."""
    acct = Account.create()
    node_uuid, resp = await _register_wallet_node(
        test_client, acct, "telemetry-secret-1"
    )
    assert resp.status_code == 201

    message_r, sig_r = _sign_ownership(acct, purpose=OWNERSHIP_PURPOSE_REVOKE)
    revoke_payload = {
        "node_uuid": node_uuid,
        "owner_signature": sig_r,
        "owner_message": message_r,
    }
    resp = await test_client.post(
        "/api/v1/hub/nodes/revoke-telemetry", json=revoke_payload
    )
    assert resp.status_code == 200
    node = await _get_node(db_session, node_uuid)
    assert node.secret_hash in (None, "")

    # Replay the identical revoke request.
    resp = await test_client.post(
        "/api/v1/hub/nodes/revoke-telemetry", json=revoke_payload
    )
    assert resp.status_code == 403


async def test_revoked_node_cannot_be_hijacked_and_recovers(test_client, db_session):
    """P0 regression: after revocation the empty secret_hash must never be
    auto-assigned to an arbitrary caller-provided secret."""
    import hashlib

    acct = Account.create()
    node_uuid, resp = await _register_wallet_node(
        test_client, acct, "telemetry-secret-1"
    )
    assert resp.status_code == 201

    headers_old = {"X-Node-UUID": node_uuid, "X-Node-Secret": "telemetry-secret-1"}
    resp = await test_client.get("/api/v1/hub/mining/status", headers=headers_old)
    assert resp.status_code == 200

    # Owner revokes telemetry access.
    message_r, sig_r = _sign_ownership(acct, purpose=OWNERSHIP_PURPOSE_REVOKE)
    resp = await test_client.post(
        "/api/v1/hub/nodes/revoke-telemetry",
        json={
            "node_uuid": node_uuid,
            "owner_signature": sig_r,
            "owner_message": message_r,
        },
    )
    assert resp.status_code == 200

    # Old secret no longer works...
    resp = await test_client.get("/api/v1/hub/mining/status", headers=headers_old)
    assert resp.status_code == 403

    # ...and an ATTACKER-supplied arbitrary secret must NOT be adopted either.
    attacker_headers = {"X-Node-UUID": node_uuid, "X-Node-Secret": "attacker-secret"}
    resp = await test_client.get("/api/v1/hub/mining/status", headers=attacker_headers)
    assert resp.status_code == 403
    node = await _get_node(db_session, node_uuid)
    assert node.secret_hash in (None, "")

    # Recovery: the wallet owner re-registers with a FRESH bind signature.
    _, resp = await _register_wallet_node(test_client, acct, "telemetry-secret-2")
    assert resp.status_code in (200, 201)

    headers_new = {"X-Node-UUID": node_uuid, "X-Node-Secret": "telemetry-secret-2"}
    resp = await test_client.get("/api/v1/hub/mining/status", headers=headers_new)
    assert resp.status_code == 200

    node = await _get_node(db_session, node_uuid)
    assert node.secret_hash == hashlib.sha256(b"telemetry-secret-2").hexdigest()


async def test_referral_code_does_not_leak_node_secret_bits(
    authenticated_client_factory, current_user, monkeypatch, db_session
):
    """P0 regression: the publicly shared DSN-REF referral code must never
    contain fragments of the telemetry node secret."""
    from api import models as _models

    monkeypatch.setenv("IS_CENTRAL_HUB", "true")

    client = await authenticated_client_factory(current_user)
    acct = Account.create()
    message = build_ownership_message(acct.address, purpose=OWNERSHIP_PURPOSE_BIND)
    encoded = encode_defunct(text=message)
    sig = acct.sign_message(encoded)["signature"].hex()
    if not sig.startswith("0x"):
        sig = f"0x{sig}"

    resp = await client.post(
        "/api/v1/node/wallet/verify",
        json={
            "address": acct.address,
            "signature": sig,
            "nonce": message,
            "message": message,
        },
    )
    assert resp.status_code == 200

    # Drop the read snapshot opened by the current_user fixture so we observe
    # the state committed by the endpoint. Read everything through fresh
    # queries — the stale ORM instances must not be touched after rollback.
    user_id = current_user.id
    await db_session.rollback()

    res = await db_session.execute(
        select(_models.AppConfig).where(_models.AppConfig.user_id == user_id)
    )
    cfg = res.scalars().first()
    assert cfg is not None
    weex_settings = (cfg.exchange_settings or {}).get("weex") or {}
    from api.security import decrypt_node_secret

    node_secret = decrypt_node_secret(weex_settings.get("mining_node_secret"))
    assert node_secret

    user_res = await db_session.execute(
        select(_models.User).where(_models.User.id == user_id)
    )
    fresh_user = user_res.scalars().first()
    ref_code = fresh_user.referral_code
    assert ref_code and ref_code.startswith("DSN-REF-")

    # No fragment of the secret may appear in the public code.
    assert node_secret[:4].upper() not in ref_code
