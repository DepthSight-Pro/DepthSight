# tests/test_transfer_e2e.py
"""
Full cross-server transfer simulation.

Server A binds a wallet (hub node created). Server B binds the SAME wallet.
We mock the local server's outbound aiohttp forward to actually dispatch into
the hub router, so the whole verify -> forward -> hub register chain runs.
"""

import hashlib
import uuid

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient
from sqlalchemy.future import select

from api import models
from api.depthsight_api import app
from api.hub_router import router as hub_router
from api.wallet_auth import OWNERSHIP_PURPOSE_BIND, build_ownership_message

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    has_hub = any(
        getattr(route, "path", "").startswith("/api/v1/hub") for route in app.routes
    )
    if not has_hub:
        app.include_router(hub_router)


class FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status = status
        self._body = body

    async def text(self):
        return str(self._body)

    async def json(self):
        return self._body


def _sign_ownership(acct: Account):
    message = build_ownership_message(acct.address, purpose=OWNERSHIP_PURPOSE_BIND)
    encoded = encode_defunct(text=message)
    sig = acct.sign_message(encoded)["signature"].hex()
    if not sig.startswith("0x"):
        sig = f"0x{sig}"
    return message, sig


def _wallet_uuid(addr: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"evm:{addr.strip().lower()}"))


def _patch_aiohttp(mocker, captured):
    """Makes aiohttp.ClientSession.post dispatch into the in-process hub router."""

    class FakeResponse:
        def __init__(self, status, body):
            self.status = status
            self._body = body

        async def text(self):
            return str(self._body)

    class FakeRequest:
        def __init__(self, json):
            self._json = json

        async def __aenter__(self):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://hub"
            ) as client:
                resp = await client.post(
                    "/api/v1/hub/nodes/register", json=self._json or {}
                )
            return FakeResponse(resp.status_code, resp.json())

        async def __aexit__(self, *exc):
            return False

    class FakeSession:
        def __init__(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, url, json=None, timeout=None):
            captured.append(json)
            return FakeRequest(json)

    mocker.patch("aiohttp.ClientSession", FakeSession)


def _patch_aiohttp_stub(mocker, response_body, status=201):
    """Makes aiohttp.ClientSession.post return a canned response body."""

    class FakeResponse:
        def __init__(self, body):
            self.status = status
            self._body = body

        async def json(self):
            return self._body

        async def text(self):
            return str(self._body)

    class FakeRequest:
        def __init__(self, body):
            self._body = body

        async def __aenter__(self):
            return FakeResponse(self._body)

        async def __aexit__(self, *exc):
            return False

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, url, json=None, timeout=None):
            return FakeRequest(response_body)

    mocker.patch("aiohttp.ClientSession", FakeSession)


async def _get_node(db_session, node_uuid: str):
    res = await db_session.execute(
        select(models.HubNode)
        .where(models.HubNode.node_uuid == node_uuid)
        .execution_options(populate_existing=True)
    )
    return res.scalars().first()


async def test_bind_on_server_B_rekeys_not_creates(
    authenticated_client_factory, current_user, db_session, monkeypatch, mocker
):
    """
    Server A created the wallet node directly on the hub. Server B binds the same
    wallet -> the forward must re-key the existing node, leaving exactly one.
    """
    monkeypatch.setenv("IS_CENTRAL_HUB", "false")
    acct = Account.create()
    node_uuid = _wallet_uuid(acct.address)

    # Simulate server A: register the wallet node on the hub directly.
    message_a, sig_a = _sign_ownership(acct)
    hub_client = AsyncClient(transport=ASGITransport(app=app), base_url="http://hub")
    try:
        resp = await hub_client.post(
            "/api/v1/hub/nodes/register",
            json={
                "node_uuid": node_uuid,
                "name": "DepthSightNode-A",
                "node_secret": "secret-A",
                "wallet_address": acct.address,
                "owner_signature": sig_a,
                "owner_message": message_a,
            },
        )
    finally:
        await hub_client.aclose()
    assert resp.status_code == 201

    captured = []
    _patch_aiohttp(mocker, captured)

    # Server B: user binds the same wallet via /node/wallet/verify
    client = await authenticated_client_factory(current_user)
    message_b, sig_b = _sign_ownership(acct)
    resp = await client.post(
        "/api/v1/node/wallet/verify",
        json={
            "address": acct.address,
            "signature": sig_b,
            "nonce": message_b,
            "message": message_b,
        },
    )
    assert resp.status_code == 200

    # The forward must have been sent with the wallet + owner signature
    assert len(captured) == 1, f"expected 1 forwarded register, got {len(captured)}"
    payload = captured[0]
    assert payload["node_uuid"] == node_uuid
    assert payload["wallet_address"] == acct.address.lower()
    assert payload["node_secret"] != "secret-A"

    # Exactly ONE node for this wallet on the hub, re-keyed to secret-B
    res = await db_session.execute(
        select(models.HubNode)
        .where(models.HubNode.wallet_address == acct.address.lower())
        .execution_options(populate_existing=True)
    )
    nodes = res.scalars().all()
    assert len(nodes) == 1
    assert nodes[0].node_uuid == node_uuid
    assert (
        nodes[0].secret_hash
        == hashlib.sha256(payload["node_secret"].encode()).hexdigest()
    )


async def test_bind_on_server_B_adopts_hub_referral_code(
    authenticated_client_factory, current_user, db_session, monkeypatch, mocker
):
    """
    When the wallet is bound on a local node (server B), the referral code must
    come from the hub's registration response (the original node code), NOT from
    a freshly fabricated DSN-REF-* code. The local user and local HubNode mirror
    must then carry the hub's authoritative code so the mining UI shows it.
    """
    monkeypatch.setenv("IS_CENTRAL_HUB", "false")
    acct = Account.create()
    node_uuid = _wallet_uuid(acct.address)
    hub_ref = "DSN-REF-HUB-ABCD"

    _patch_aiohttp_stub(mocker, {"status": "success", "node_referral_code": hub_ref})

    client = await authenticated_client_factory(current_user)
    message, sig = _sign_ownership(acct)
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

    # The local user must carry the hub's authoritative referral code.
    res = await db_session.execute(
        select(models.User)
        .where(models.User.id == current_user.id)
        .execution_options(populate_existing=True)
    )
    user = res.scalars().first()
    assert user.referral_code == hub_ref

    # And the local HubNode mirror must carry it too.
    res = await db_session.execute(
        select(models.HubNode)
        .where(models.HubNode.node_uuid == node_uuid)
        .execution_options(populate_existing=True)
    )
    node = res.scalars().first()
    assert node is not None
    assert node.node_referral_code == hub_ref
