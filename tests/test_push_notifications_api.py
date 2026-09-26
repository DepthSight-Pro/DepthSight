# tests/test_push_notifications_api.py
"""Tests for POST /api/v1/notifications/push-test."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud, models


@pytest.mark.asyncio
async def test_push_test_no_subscription(
    pro_user_client: AsyncClient,
    db_session: AsyncSession,
    pro_user: models.User,
):
    await crud.delete_user_push_subscription(db_session, user_id=pro_user.id)
    await db_session.commit()
    response = await pro_user_client.post("/api/v1/notifications/push-test")
    assert response.status_code == 200
    assert response.json() == {"status": "no_subscription"}


@pytest.mark.asyncio
async def test_push_test_sent(
    pro_user_client: AsyncClient,
    db_session: AsyncSession,
    pro_user: models.User,
    monkeypatch,
):
    await crud.update_user_push_subscription(
        db_session,
        user_id=pro_user.id,
        subscription={"endpoint": "https://push.example/x"},
    )
    await db_session.commit()

    import api.routes.notifications as notifications_route

    monkeypatch.setattr(
        notifications_route, "send_push_notification", lambda *a, **k: "sent"
    )
    response = await pro_user_client.post("/api/v1/notifications/push-test")
    assert response.status_code == 200
    assert response.json() == {"status": "sent"}


@pytest.mark.asyncio
async def test_push_test_expired_clears_subscription(
    pro_user_client: AsyncClient,
    db_session: AsyncSession,
    pro_user: models.User,
    monkeypatch,
):
    await crud.update_user_push_subscription(
        db_session,
        user_id=pro_user.id,
        subscription={"endpoint": "https://push.example/x"},
    )
    await db_session.commit()

    import api.routes.notifications as notifications_route

    monkeypatch.setattr(
        notifications_route, "send_push_notification", lambda *a, **k: "expired"
    )
    response = await pro_user_client.post("/api/v1/notifications/push-test")
    assert response.status_code == 200
    assert response.json() == {"status": "expired"}

    await db_session.refresh(pro_user)
    assert pro_user.push_subscription is None
