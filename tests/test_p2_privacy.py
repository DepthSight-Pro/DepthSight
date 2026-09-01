# tests/test_p2_privacy.py
"""
P2 privacy/transport fixes:

- get_federation_hub_url(): HTTPS enforced (localhost / ALLOW_INSECURE_HUB_URL
  are the only exceptions).
- Telemetry HMAC requests honour X-Timestamp freshness (5 min window);
  legacy clients without the header stay compatible.
- shareTelemetry: the silent "self-heal" is gone вЂ” an explicit opt-out sticks;
  turning it OFF while Trade Mining is active is rejected with 409.
- mining_node_secret at rest: Fernet-encrypted on write, transparent legacy
  plaintext fallback on read.
- Offline delivery: telemetry_sync falls back to the wallet identity stored in
  the DB, so LOCAL_ONLY reports still reach the hub after a re-key.
"""

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api import models
from api.depthsight_api import app
from api.federation import InsecureHubUrlError, get_federation_hub_url
from api.hub_router import router as hub_router
from api.security import decrypt_node_secret, encrypt_node_secret

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    has_hub = any(
        getattr(route, "path", "").startswith("/api/v1/hub") for route in app.routes
    )
    if not has_hub:
        app.include_router(hub_router)


# ---------------------------------------------------------------------------
# 2.3 Hub URL scheme validation
# ---------------------------------------------------------------------------


def test_hub_url_https_ok(monkeypatch):
    monkeypatch.setenv("FEDERATION_HUB_URL", "https://hub.example.com/api/v1/hub")
    assert get_federation_hub_url() == "https://hub.example.com/api/v1/hub"


def test_hub_url_http_localhost_allowed(monkeypatch):
    monkeypatch.setenv("FEDERATION_HUB_URL", "http://localhost:8000/api/v1/hub")
    assert get_federation_hub_url() == "http://localhost:8000/api/v1/hub"


def test_hub_url_http_external_rejected(monkeypatch):
    monkeypatch.setenv("FEDERATION_HUB_URL", "http://hub.example.com/api/v1/hub")
    monkeypatch.setenv("ALLOW_INSECURE_HUB_URL", "false")
    with pytest.raises(InsecureHubUrlError):
        get_federation_hub_url()


def test_hub_url_http_external_escape_hatch(monkeypatch):
    monkeypatch.setenv("FEDERATION_HUB_URL", "http://hub.example.com/api/v1/hub")
    monkeypatch.setenv("ALLOW_INSECURE_HUB_URL", "true")
    assert get_federation_hub_url() == "http://hub.example.com/api/v1/hub"


# ---------------------------------------------------------------------------
# 2.2 X-Timestamp freshness + telemetry posting helpers
# ---------------------------------------------------------------------------


def _telemetry_body(broker_trade_id: str) -> bytes:
    payload = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entryPrice": 62500.0,
        "exitPrice": 63750.0,
        "pnlPercent": 2.0,
        "tradeDurationSec": 3600,
        "exitReason": "take_profit",
        "tradeMode": "LIVE",
        "strategyBlocks": [{"type": "volume_filter", "params": {"multiplier": 2.0}}],
        "marketContext": {},
        "exchangeId": "weex",
        "marketType": "futures",
        "brokerTradeId": broker_trade_id,
        "tradeVolumeUsdt": 1000.0,
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


async def _post_telemetry(
    test_client, node_uuid: str, secret: str, body: bytes, ts_ms=None
):
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "X-Node-UUID": node_uuid,
        "X-Node-Secret": secret,
        "X-Node-Signature": signature,
        "Content-Type": "application/json",
    }
    if ts_ms is not None:
        headers["X-Timestamp"] = str(ts_ms)
    return await test_client.post(
        "/api/v1/hub/telemetry/report", content=body, headers=headers
    )


async def test_telemetry_fresh_timestamp_accepted(test_client, db_session):
    db_session.add(
        models.HubNode(
            node_uuid="ts-node",
            name="TS",
            secret_hash=hashlib.sha256(b"sec-ts").hexdigest(),
        )
    )
    await db_session.commit()

    resp = await _post_telemetry(
        test_client,
        "ts-node",
        "sec-ts",
        _telemetry_body("ts-trade-1"),
        ts_ms=int(time.time() * 1000),
    )
    assert resp.status_code == 201


async def test_telemetry_stale_timestamp_rejected(test_client, db_session):
    db_session.add(
        models.HubNode(
            node_uuid="ts-node2",
            name="TS2",
            secret_hash=hashlib.sha256(b"sec-ts").hexdigest(),
        )
    )
    await db_session.commit()

    stale = int(time.time() * 1000) - 10 * 60 * 1000  # 10 minutes ago
    resp = await _post_telemetry(
        test_client,
        "ts-node2",
        "sec-ts",
        _telemetry_body("ts-trade-2"),
        ts_ms=stale,
    )
    assert resp.status_code == 400
    assert "timestamp" in resp.json()["detail"].lower()


async def test_telemetry_without_timestamp_legacy_ok(test_client, db_session):
    db_session.add(
        models.HubNode(
            node_uuid="ts-node3",
            name="TS3",
            secret_hash=hashlib.sha256(b"sec-ts").hexdigest(),
        )
    )
    await db_session.commit()

    resp = await _post_telemetry(
        test_client, "ts-node3", "sec-ts", _telemetry_body("ts-trade-3")
    )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# 2.4 node_secret encryption at rest
# ---------------------------------------------------------------------------


def test_node_secret_roundtrip_and_legacy():
    raw = "super-secret-value"
    encrypted = encrypt_node_secret(raw)
    assert encrypted != raw
    assert encrypted.startswith("gAAA")
    assert decrypt_node_secret(encrypted) == raw

    # Legacy plaintext passes through untouched.
    assert decrypt_node_secret(raw) == raw
    assert decrypt_node_secret(None) is None
    assert decrypt_node_secret("") == ""


# ---------------------------------------------------------------------------
# 2.5 shareTelemetry consent integrity
# ---------------------------------------------------------------------------


async def _seed_active_miner(db_session: AsyncSession) -> models.AppConfig:
    """User #1 with mining enabled, wallet bound and telemetry OFF."""
    res = await db_session.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == 1)
    )
    cfg = res.scalars().first()
    if cfg is None:
        cfg = models.AppConfig(
            user_id=1, risk_management={}, notifications={}, data_sources={}
        )
        db_session.add(cfg)
    cfg.exchange_settings = {
        "weex": {
            "wallet_configured": True,
            "mining_node_uuid": "consent-node",
            "mining_node_secret": encrypt_node_secret("sec-consent"),
        }
    }
    cfg.notifications = {"shareTelemetry": False}
    cfg.is_mining_enabled = True
    await db_session.commit()
    return cfg


async def test_status_no_longer_self_heals_toggle(
    authenticated_client_factory, current_user, monkeypatch, db_session
):
    monkeypatch.setenv("IS_CENTRAL_HUB", "true")
    user_id = current_user.id
    await _seed_active_miner(db_session)
    client = await authenticated_client_factory(current_user)

    resp = await client.get("/api/v1/mining/status")
    assert resp.status_code == 200

    # Drop the pre-endpoint read snapshot; read through a fresh query only.
    await db_session.rollback()
    res = await db_session.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == user_id)
    )
    cfg = res.scalars().first()
    assert cfg.notifications.get("shareTelemetry") is False


async def test_cannot_disable_telemetry_while_mining_active(
    authenticated_client_factory, current_user, db_session
):
    await _seed_active_miner(db_session)
    client = await authenticated_client_factory(current_user)

    resp = await client.put(
        "/api/v1/config",
        json={
            "notifications": {
                "shareTelemetry": False,
                "emailEnabled": True,
                "telegramEnabled": True,
            }
        },
    )
    assert resp.status_code == 409


async def test_can_disable_telemetry_after_mining_deactivated(
    authenticated_client_factory, current_user, db_session
):
    cfg = await _seed_active_miner(db_session)
    cfg.is_mining_enabled = False
    await db_session.commit()

    client = await authenticated_client_factory(current_user)
    resp = await client.put(
        "/api/v1/config",
        json={
            "notifications": {
                "shareTelemetry": False,
                "emailEnabled": True,
                "telegramEnabled": True,
            }
        },
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Offline delivery: DB fallback for the node identity
# ---------------------------------------------------------------------------


class _FakeHubClient:
    posted = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=None, headers=None):
        _FakeHubClient.posted.append({"url": url, "headers": headers})
        from types import SimpleNamespace

        return SimpleNamespace(status_code=201, text="")


async def test_resync_uses_db_wallet_identity(monkeypatch, db_session):
    import telemetry_sync

    monkeypatch.setenv("IS_CENTRAL_HUB", "false")
    monkeypatch.setattr(telemetry_sync, "get_node_identity", lambda: (None, None))
    monkeypatch.setattr(telemetry_sync.httpx, "AsyncClient", _FakeHubClient)
    _FakeHubClient.posted = []

    # Wallet-bound identity in the DB (encrypted at rest since P2).
    res = await db_session.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == 1)
    )
    cfg = res.scalars().first()
    if cfg is None:
        cfg = models.AppConfig(
            user_id=1, risk_management={}, notifications={}, data_sources={}
        )
        db_session.add(cfg)
    cfg.exchange_settings = {
        "weex": {
            "wallet_configured": True,
            "mining_node_uuid": "db-identity-node",
            "mining_node_secret": encrypt_node_secret("db-secret"),
        }
    }
    cfg.notifications = {"shareTelemetry": True}
    await db_session.commit()

    # A trade that was closed while the hub was down.
    report = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=1.0,
        exit_price=2.0,
        trade_mode="LIVE",
        node_uuid="db-identity-node",
        exchange_id="weex",
        market_type="futures",
        broker_trade_id="offline-trade-1",
        verification_status="LOCAL_ONLY",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(report)
    await db_session.commit()

    result = await telemetry_sync.resync_pending_telemetry_reports(db=db_session)
    assert result["synced"] == 1
    assert len(_FakeHubClient.posted) == 1
    sent_headers = _FakeHubClient.posted[0]["headers"]
    # The DECRYPTED secret signed/authorised the request, not the ciphertext.
    assert sent_headers["X-Node-Secret"] == "db-secret"
    assert "X-Timestamp" in sent_headers

    await db_session.refresh(report)
    assert report.verification_status == "SENT"
