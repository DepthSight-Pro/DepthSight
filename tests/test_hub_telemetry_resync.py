import pytest
from httpx import Response
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import models, crud
from telemetry_sync import resync_pending_telemetry_reports

pytestmark = pytest.mark.asyncio


async def test_crud_telemetry_status_helpers(monkeypatch, db_session: AsyncSession):
    """
    Test save_hub_telemetry_report returns report object and update_hub_telemetry_status updates status.
    """
    monkeypatch.setenv("IS_CENTRAL_HUB", "false")
    payload = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 60000.0,
        "exit_price": 61000.0,
        "pnl_percent": 1.66,
        "trade_duration_sec": 1200,
        "exit_reason": "take_profit",
        "trade_mode": "LIVE",
        "exchange_id": "bybit",
        "market_type": "futures",
        "broker_trade_id": "resync-test-order-1",
        "trade_volume_usdt": 5000.0,
    }

    report = await crud.save_hub_telemetry_report(
        db_session,
        payload=payload,
        attribution_node_uuid="node-resync-1",
    )

    assert report is not None
    assert report.id is not None
    assert report.verification_status == "LOCAL_ONLY"

    # Test get_pending_local_telemetry_reports
    pending = await crud.get_pending_local_telemetry_reports(db_session, limit=10)
    assert any(r.id == report.id for r in pending)

    # Test update_hub_telemetry_status to SENT
    updated = await crud.update_hub_telemetry_status(
        db_session, report.id, status="SENT"
    )
    assert updated is not None
    assert updated.verification_status == "SENT"

    # Should no longer be pending
    pending_after = await crud.get_pending_local_telemetry_reports(db_session, limit=10)
    assert not any(r.id == report.id for r in pending_after)


async def test_resync_pending_telemetry_is_central_hub(
    monkeypatch, db_session: AsyncSession
):
    """
    Test that resync skips execution when IS_CENTRAL_HUB=true.
    """
    monkeypatch.setenv("IS_CENTRAL_HUB", "true")
    res = await resync_pending_telemetry_reports(db=db_session)
    assert res["reason"] == "is_central_hub"
    assert res["synced"] == 0


async def test_resync_pending_telemetry_success(
    monkeypatch, db_session: AsyncSession, mocker
):
    """
    Test that resync_pending_telemetry_reports uploads LOCAL_ONLY reports and marks them as SENT.
    """
    monkeypatch.setenv("IS_CENTRAL_HUB", "false")
    monkeypatch.setenv("HUB_NODE_UUID", "test-node-uuid")
    monkeypatch.setenv("HUB_NODE_SECRET", "test-node-secret")
    monkeypatch.setenv("FEDERATION_HUB_URL", "https://mock-hub.test")

    payload = {
        "symbol": "ETHUSDT",
        "direction": "SHORT",
        "entry_price": 3000.0,
        "exit_price": 2900.0,
        "pnl_percent": 3.33,
        "trade_duration_sec": 1800,
        "exit_reason": "take_profit",
        "trade_mode": "LIVE",
        "exchange_id": "weex",
        "market_type": "futures",
        "broker_trade_id": "resync-test-order-2",
        "trade_volume_usdt": 10000.0,
    }

    report = await crud.save_hub_telemetry_report(
        db_session,
        payload=payload,
        attribution_node_uuid="test-node-uuid",
    )
    assert report.verification_status == "LOCAL_ONLY"

    # Mock HTTP response from Hub using mocker
    mock_post = mocker.patch("httpx.AsyncClient.post")
    mock_post.return_value = Response(201, json={"status": "accepted"})

    res = await resync_pending_telemetry_reports(db=db_session)
    assert res["synced"] >= 1

    # Verify report status is now SENT in DB
    refreshed_stmt = select(models.HubTelemetryReport).where(
        models.HubTelemetryReport.id == report.id
    )
    refreshed_res = await db_session.execute(refreshed_stmt)
    refreshed_report = refreshed_res.scalar_one()
    assert refreshed_report.verification_status == "SENT"


async def test_resync_pending_telemetry_hub_offline(
    monkeypatch, db_session: AsyncSession, mocker
):
    """
    Test that when hub returns server error, reports remain LOCAL_ONLY for future retry.
    """
    monkeypatch.setenv("IS_CENTRAL_HUB", "false")
    monkeypatch.setenv("HUB_NODE_UUID", "test-node-uuid")
    monkeypatch.setenv("HUB_NODE_SECRET", "test-node-secret")
    monkeypatch.setenv("FEDERATION_HUB_URL", "https://mock-hub-offline.test")

    payload = {
        "symbol": "SOLUSDT",
        "direction": "LONG",
        "entry_price": 140.0,
        "exit_price": 145.0,
        "pnl_percent": 3.5,
        "trade_duration_sec": 600,
        "exit_reason": "take_profit",
        "trade_mode": "LIVE",
        "exchange_id": "bybit",
        "market_type": "futures",
        "broker_trade_id": "resync-test-order-3",
        "trade_volume_usdt": 2000.0,
    }

    report = await crud.save_hub_telemetry_report(
        db_session,
        payload=payload,
        attribution_node_uuid="test-node-uuid",
    )

    # Mock HTTP error (503 Service Unavailable)
    mock_post = mocker.patch("httpx.AsyncClient.post")
    mock_post.return_value = Response(503, text="Service Unavailable")

    res = await resync_pending_telemetry_reports(db=db_session)
    assert res["synced"] == 0

    # Verify report status remains LOCAL_ONLY
    refreshed_stmt = select(models.HubTelemetryReport).where(
        models.HubTelemetryReport.id == report.id
    )
    refreshed_res = await db_session.execute(refreshed_stmt)
    refreshed_report = refreshed_res.scalar_one()
    assert refreshed_report.verification_status == "LOCAL_ONLY"
