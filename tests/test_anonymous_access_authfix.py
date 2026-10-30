# tests/test_anonymous_access_authfix.py
"""Regression tests for the anonymous-access fixes on the hub support-ticket
routes and the simulation upload / asset-detail routes.

Before this change:

* ``GET``/``PATCH`` ``/api/v1/hub/tickets/{ticket_id}/status`` and
  ``GET``/``POST`` ``/api/v1/hub/tickets/{ticket_id}/messages`` performed no
  authentication check of any kind, so a logged-out caller could read another
  user's support conversation (including the base64 screenshot attached to a
  message) and reply to it.
* ``POST`` /api/simulation/upload-strategy`` and
  ``POST`` ``/api/simulation/asset-detail/{asset}`` performed no
  authentication check of any kind either.

These tests pin the fixed behaviour: 401 for an anonymous caller, and the
ticket owner (or an admin) for everybody else.
"""

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api import models
from api.depthsight_api import app
from api.hub_router import router as hub_router

pytestmark = pytest.mark.asyncio

SECRET_TICKET_TEXT = "SUPER_SECRET_TICKET_BODY_DO_NOT_LEAK"

# The four hub support-ticket routes that used to be reachable anonymously.
HUB_TICKET_ROUTES = [
    ("GET", "/api/v1/hub/tickets/{tid}/status", None),
    ("PATCH", "/api/v1/hub/tickets/{tid}/status", {"status": "CLOSED"}),
    ("GET", "/api/v1/hub/tickets/{tid}/messages", None),
    ("POST", "/api/v1/hub/tickets/{tid}/messages", {"text": "anonymous reply"}),
]

ASSET_DETAIL_BODY = {
    "strategy_json": {},
    "variants": [],
    "config": {},
}


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    """Mount the Federation Hub router on the test app if it is not mounted.

    IS_CENTRAL_HUB is false in the test environment, so the hub router is not
    included when the app module is imported. FastAPI 0.162 wraps included
    routers in an ``_IncludedRouter`` object that hides the individual paths
    from ``app.routes``, so "is it already mounted?" cannot be answered from
    ``app.routes``. An explicit marker on the app object is used instead, so
    the router is mounted exactly once per session even though more than one
    test module needs it.
    """
    if not getattr(app, "_depthsight_hub_router_mounted", False):
        app.include_router(hub_router)
        app._depthsight_hub_router_mounted = True


async def _create_user(
    db_session: AsyncSession, username: str, role: str = "user"
) -> models.User:
    user = models.User(
        username=username,
        email=f"{username}@example.com",
        hashed_password="fakehashpassword",
        role=role,
        plan="pro",
        is_active=True,
        xp=0,
        level=1,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def two_users(db_session, authenticated_client_factory):
    """Two different logged-in users, each with their own authenticated client."""
    owner = await _create_user(db_session, "hub_ticket_owner")
    other = await _create_user(db_session, "hub_ticket_someone_else")
    owner_client = await authenticated_client_factory(owner)
    other_client = await authenticated_client_factory(other)
    async with owner_client, other_client:
        yield owner, other, owner_client, other_client


@pytest.fixture
async def owned_ticket(two_users, db_session):
    """A support ticket owned by the first user, holding a secret message."""
    owner, _other, _owner_client, _other_client = two_users

    ticket = models.SupportTicket(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        subject="Private support issue",
        category="bug",
        description="Only the owner should ever read this.",
        status="OPEN",
    )
    db_session.add(ticket)
    await db_session.commit()

    message = models.SupportTicketMessage(
        ticket_id=ticket.id,
        sender_name="owner",
        text=SECRET_TICKET_TEXT,
        is_admin=False,
    )
    db_session.add(message)
    await db_session.commit()
    return ticket.id


async def _call(client: AsyncClient, method: str, url: str, payload):
    if method == "GET":
        return await client.get(url)
    if method == "PATCH":
        return await client.patch(url, json=payload)
    return await client.post(url, json=payload)


# --------------------------------------------------------------------------
# Defect 1 - anonymous support-ticket read AND write
# --------------------------------------------------------------------------


async def test_hub_ticket_routes_reject_anonymous_callers(test_client, owned_ticket):
    """An unauthenticated request must be rejected with 401, not 403."""
    for method, template, payload in HUB_TICKET_ROUTES:
        url = template.format(tid=owned_ticket)
        response = await _call(test_client, method, url, payload)
        assert response.status_code == 401, (
            f"{method} {url} returned {response.status_code}, expected 401"
        )
        assert SECRET_TICKET_TEXT not in response.text


async def test_hub_ticket_routes_allow_the_owner(two_users, owned_ticket):
    """The owner of a ticket keeps full access to their own ticket."""
    _owner, _other, owner_client, _other_client = two_users

    status = await owner_client.get(f"/api/v1/hub/tickets/{owned_ticket}/status")
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "OPEN"

    messages = await owner_client.get(f"/api/v1/hub/tickets/{owned_ticket}/messages")
    assert messages.status_code == 200, messages.text
    assert any(m["text"] == SECRET_TICKET_TEXT for m in messages.json())

    reply = await owner_client.post(
        f"/api/v1/hub/tickets/{owned_ticket}/messages", json={"text": "owner reply"}
    )
    assert reply.status_code == 201, reply.text

    closed = await owner_client.patch(
        f"/api/v1/hub/tickets/{owned_ticket}/status", json={"status": "CLOSED"}
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"


async def test_hub_ticket_routes_refuse_a_different_user(two_users, owned_ticket):
    """A ticket belonging to somebody else must not leak to another user."""
    _owner, _other, _owner_client, other_client = two_users

    for method, template, payload in HUB_TICKET_ROUTES:
        url = template.format(tid=owned_ticket)
        response = await _call(other_client, method, url, payload)
        assert response.status_code == 403, (
            f"{method} {url} returned {response.status_code}, expected 403"
        )
        assert SECRET_TICKET_TEXT not in response.text


async def test_hub_ticket_routes_allow_an_admin(
    db_session, authenticated_client_factory, owned_ticket
):
    """A privileged role may read any ticket."""
    admin = await _create_user(db_session, "hub_ticket_admin", role="admin")
    admin_client = await authenticated_client_factory(admin)
    async with admin_client:
        response = await admin_client.get(f"/api/v1/hub/tickets/{owned_ticket}/messages")
        assert response.status_code == 200, response.text
        assert any(m["text"] == SECRET_TICKET_TEXT for m in response.json())


async def test_hub_feedback_ticket_is_owned_by_the_authenticated_caller(
    two_users,
):
    """An authenticated feedback submitter gets a ticket they may read back.

    The feedback route stays open to anonymous callers. When the caller IS
    authenticated, the ticket is attributed to them, otherwise the ticket id
    we hand back would point at a ticket they are not allowed to read.
    """
    _owner, _other, owner_client, _other_client = two_users

    response = await owner_client.post(
        "/api/v1/hub/feedback",
        json={
            "category": "bug",
            "text": "Authenticated feedback.",
            "contact_email": "owner@example.com",
        },
    )
    assert response.status_code == 201, response.text
    ticket_id = response.json()["ticket_id"]
    assert ticket_id

    status = await owner_client.get(f"/api/v1/hub/tickets/{ticket_id}/status")
    assert status.status_code == 200, status.text


async def test_hub_feedback_route_is_still_open_to_anonymous_callers(test_client):
    """The feedback route itself must stay open - that is a community feature."""
    response = await test_client.post(
        "/api/v1/hub/feedback",
        json={"category": "bug", "text": "Anonymous feedback."},
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "success"


# --------------------------------------------------------------------------
# Defect 2 - anonymous file upload / asset detail
# --------------------------------------------------------------------------


async def test_upload_strategy_rejects_an_anonymous_caller(test_client):
    response = await test_client.post(
        "/api/simulation/upload-strategy",
        files={
            "file": ("strategy.json", b'{"strategy_name": "anon"}', "application/json")
        },
    )
    assert response.status_code == 401, response.text


async def test_upload_strategy_accepts_an_authenticated_caller(authenticated_client):
    response = await authenticated_client.post(
        "/api/simulation/upload-strategy",
        files={
            "file": ("strategy.json", b'{"strategy_name": "mine"}', "application/json")
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["valid"] is True
    assert response.json()["strategy"]["strategy_name"] == "mine"


async def test_upload_strategy_keeps_the_client_4xx_status(authenticated_client):
    """A body that is valid JSON but not an object stays a 400, not a 500."""
    response = await authenticated_client.post(
        "/api/simulation/upload-strategy",
        files={"file": ("strategy.json", b"[1, 2, 3]", "application/json")},
    )
    assert response.status_code == 400, response.text


async def test_upload_strategy_rejects_an_oversized_file(authenticated_client):
    payload = json.dumps({"padding": "x" * (6 * 1024 * 1024)}).encode()
    response = await authenticated_client.post(
        "/api/simulation/upload-strategy",
        files={"file": ("big.json", payload, "application/json")},
    )
    assert response.status_code == 413, response.text


async def test_upload_strategy_never_writes_the_file_to_disk(
    authenticated_client, tmp_path
):
    """The uploaded file is parsed and returned - it is never written to disk.

    This is why a client supplied filename cannot cause a path traversal: the
    filename is never used as a filesystem path.
    """
    repo_root = Path(__file__).resolve().parent.parent
    response = await authenticated_client.post(
        "/api/simulation/upload-strategy",
        files={
            "file": (
                "../../../../escaped_strategy.json",
                b'{"strategy_name": "escaped"}',
                "application/json",
            )
        },
    )
    assert response.status_code == 200, response.text
    assert not (repo_root / "escaped_strategy.json").exists()
    assert not (tmp_path / "escaped_strategy.json").exists()


async def test_asset_detail_rejects_an_anonymous_caller(test_client):
    response = await test_client.post(
        "/api/simulation/asset-detail/BTCUSDT", json=ASSET_DETAIL_BODY
    )
    assert response.status_code == 401, response.text


async def test_asset_detail_accepts_an_authenticated_caller(authenticated_client):
    """An authenticated caller is let through to the (existing) data checks."""
    response = await authenticated_client.post(
        "/api/simulation/asset-detail/BTCUSDT", json=ASSET_DETAIL_BODY
    )
    # The data root does not exist in the test environment, so the route
    # answers 404 (asset not found) - but it must NOT answer 401 any more.
    assert response.status_code != 401, response.text


async def test_asset_path_resolution_refuses_to_escape_the_data_root(
    monkeypatch, tmp_path
):
    """`asset` comes from the URL, so it must not be able to walk out of the root."""
    from api import simulation_router

    data_root = tmp_path / "data_root"
    data_root.mkdir()
    monkeypatch.setattr(simulation_router, "DATA_STORAGE_PATH", data_root)

    inside = simulation_router._resolve_asset_parquet_path("BTCUSDT")
    assert inside == (data_root / "BTCUSDT" / "kline_1m.parquet")

    # NOTE: a four-dot component ("....") is deliberately not in this list.
    # Windows strips trailing dots from a path component so "...." collapses to
    # the parent directory there, but on POSIX it is an ordinary directory name
    # that stays INSIDE the data root - asserting it is refused would fail on
    # Linux.
    for escaping in ("..", "../..", "a/../.."):
        with pytest.raises(HTTPException) as exc_info:
            simulation_router._resolve_asset_parquet_path(escaping)
        assert exc_info.value.status_code == 404


async def test_asset_detail_cannot_read_a_file_outside_the_data_root(
    authenticated_client, monkeypatch, tmp_path
):
    """A parquet file outside the data root must not be readable via `..`."""
    import pandas as pd

    from api import simulation_router

    data_root = tmp_path / "data_root"
    data_root.mkdir()
    monkeypatch.setattr(simulation_router, "DATA_STORAGE_PATH", data_root)

    # This file sits OUTSIDE the data root (it is the parent directory).
    pd.DataFrame({"time": [1], "open": [1.0], "high": [1.0], "low": [1.0],
                  "close": [1.0], "volume": [1.0]}).to_parquet(
        tmp_path / "kline_1m.parquet"
    )

    response = await authenticated_client.post(
        "/api/simulation/asset-detail/..", json=ASSET_DETAIL_BODY
    )
    assert response.status_code == 404, response.text
    assert "klines" not in response.text


# --------------------------------------------------------------------------
# Additional finding from the same audit: unauthenticated inspector reads
# --------------------------------------------------------------------------


async def test_inspector_status_rejects_an_anonymous_caller(test_client):
    response = await test_client.get("/api/simulation/inspector/status/some-task-id")
    assert response.status_code == 401, response.text


async def test_inspector_stream_rejects_an_anonymous_caller(test_client):
    """The inspector SSE stream must not serve an anonymous caller.

    The route is a long-lived SSE stream: when it is reachable anonymously
    the request never ends (the generator keeps sending heartbeats for a task
    that does not exist), so the call is bounded by a timeout. Reaching the
    timeout means the anonymous caller was served.
    """
    try:
        response = await asyncio.wait_for(
            test_client.get("/api/simulation/inspector/celery/stream/some-task-id"),
            timeout=10,
        )
    except (asyncio.TimeoutError, TimeoutError):
        pytest.fail(
            "the inspector stream served an anonymous caller (the stream never ended)"
        )
    assert response.status_code == 401, response.text
