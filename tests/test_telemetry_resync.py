"""Regression: telemetry resync must not stall on one bad report (B5),
and epoch finalization must be single-flight (B7)."""

from datetime import date

import pytest

import telemetry_sync
from api import models


def _make_report(node_uuid, broker_id):
    return models.HubTelemetryReport(
        node_uuid=node_uuid,
        source_node_uuid=node_uuid,
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=50500.0,
        pnl_percent=1.0,
        trade_duration_sec=60,
        exit_reason="TP_HIT",
        trade_mode="live",
        exchange_id="bitget",
        market_type="futures_usdtm",
        broker_trade_id=broker_id,
        trade_volume_usdt=1000.0,
        verification_status="LOCAL_ONLY",
    )


class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.text = "ok"


class _FlakyClient:
    """Fails the 2nd POST, succeeds the rest. instances track attempts."""

    attempts = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=None, headers=None):
        _FlakyClient.attempts.append(url)
        if len(_FlakyClient.attempts) == 2:
            raise ConnectionError("hub flaky")
        return _Resp(200)


@pytest.mark.asyncio
async def test_resync_continues_after_single_failure(db_session, monkeypatch):
    monkeypatch.setenv("HUB_NODE_UUID", "node-1")
    monkeypatch.setenv("HUB_NODE_SECRET", "secret-1")
    monkeypatch.setenv("IS_CENTRAL_HUB", "false")
    monkeypatch.setattr(telemetry_sync.httpx, "AsyncClient", _FlakyClient)
    _FlakyClient.attempts = []

    for i in range(3):
        db_session.add(_make_report("node-1", f"resync-test-{i}"))
    await db_session.commit()

    result = await telemetry_sync.resync_pending_telemetry_reports(db_session)

    assert result["total"] == 3
    assert result["synced"] == 2
    assert len(_FlakyClient.attempts) == 3, "every report must be attempted"

    from sqlalchemy import select

    rows = (
        (
            await db_session.execute(
                select(models.HubTelemetryReport).order_by(
                    models.HubTelemetryReport.broker_trade_id
                )
            )
        )
        .scalars()
        .all()
    )
    statuses = [r.verification_status for r in rows]
    assert statuses == ["SENT", "LOCAL_ONLY", "SENT"]


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeSession:
    def __init__(self, behavior):
        self._behavior = behavior

    async def execute(self, *args, **kwargs):
        if self._behavior == "raise":
            raise Exception("no such function: pg_try_advisory_lock")
        return _ScalarResult(self._behavior)


@pytest.mark.asyncio
async def test_epoch_lock_acquired():
    from tasks import _acquire_epoch_lock

    assert await _acquire_epoch_lock(_FakeSession(True), date(2026, 9, 29)) is True


@pytest.mark.asyncio
async def test_epoch_lock_contention_skips():
    from tasks import _acquire_epoch_lock

    assert await _acquire_epoch_lock(_FakeSession(False), date(2026, 9, 29)) is False


@pytest.mark.asyncio
async def test_epoch_lock_falls_back_without_pg():
    from tasks import _acquire_epoch_lock

    # SQLite (tests) has no pg_advisory_lock: proceed as before, don't break.
    assert await _acquire_epoch_lock(_FakeSession("raise"), date(2026, 9, 29)) is True


def _insight_report(pnl, blocks, exit_reason="TP_HIT"):
    import uuid

    r = _make_report("node-1", f"ins-{uuid.uuid4().hex[:8]}")
    r.pnl_percent = pnl
    r.exit_reason = exit_reason
    r.strategy_blocks = [{"type": b} for b in blocks]
    return r


@pytest.mark.asyncio
async def test_insights_bounded_and_correct(db_session):
    """B11: same output shape over a bounded recent slice (min 5 trades/combo)."""
    from api.hub_router import get_telemetry_insights

    for i in range(4):
        db_session.add(_insight_report(2.0, ["rsi", "atr"]))
    for i in range(2):
        db_session.add(_insight_report(-1.0, ["atr", "rsi"]))
    for i in range(2):  # below the min-5 threshold -> filtered out
        db_session.add(_insight_report(5.0, ["macd"]))
    await db_session.commit()

    insights = await get_telemetry_insights(symbol=None, days=30, db=db_session)

    assert len(insights) == 1
    item = insights[0]
    assert item.combo_key == "atr + rsi"
    assert item.total_trades == 6
    assert item.win_rate == round(4 / 6 * 100, 2)
    assert item.best_exit_reasons == ["TP_HIT"]
