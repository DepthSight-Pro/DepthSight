import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from api import models, security
from api.routes.config import auto_resolve_bitget_uid


@pytest.mark.asyncio
async def test_auto_resolve_bitget_uid_no_keys(
    db_session: AsyncSession, free_user: models.User
):
    uid = await auto_resolve_bitget_uid(db_session, free_user.id)
    assert uid is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
@patch("aiohttp.ClientSession.post")
async def test_bitget_uid_sync_behavior(
    mock_aiohttp_post,
    mock_httpx_get,
    db_session: AsyncSession,
    free_user: models.User,
    monkeypatch,
):
    monkeypatch.setenv("IS_CENTRAL_HUB", "false")

    encrypted_key = security.encrypt_data("test-bitget-key")
    packed_secret = json.dumps(
        {"secret": "test-bitget-secret", "password": "test-passphrase"}
    )
    encrypted_secret = security.encrypt_data(packed_secret)

    api_key_obj = models.ApiKey(
        user_id=free_user.id,
        exchange="bitget",
        name="Bitget Test Key",
        encrypted_api_key=encrypted_key,
        encrypted_api_secret=encrypted_secret,
        key_prefix="test...1234",
        status="valid",
        is_active=True,
    )
    db_session.add(api_key_obj)

    cfg_stmt = select(models.AppConfig).where(models.AppConfig.user_id == free_user.id)
    cfg_res = await db_session.execute(cfg_stmt)
    cfg = cfg_res.scalar_one()
    cfg.is_mining_enabled = True
    cfg.exchange_settings = {
        "bitget": {
            "mining_node_uuid": "test-node-uuid-bitget",
            "mining_node_secret": security.encrypt_node_secret("secret123"),
        }
    }
    await db_session.commit()
    await db_session.refresh(cfg)

    # Mock HubNode in database
    hub_node = models.HubNode(
        node_uuid="test-node-uuid-bitget",
        name="TestNode",
        secret_hash="hash123",
        node_referral_code="REF-BITGET-TEST",
    )
    db_session.add(hub_node)
    await db_session.commit()

    # Mock Bitget API response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "code": "00000",
        "msg": "success",
        "data": {"userId": "88776655"},
    }
    mock_httpx_get.return_value = mock_resp

    mock_hub_resp = AsyncMock()
    mock_hub_resp.status = 200
    mock_hub_resp.text.return_value = "OK"
    mock_aiohttp_post.return_value.__aenter__.return_value = mock_hub_resp

    uid = await auto_resolve_bitget_uid(db_session, free_user.id)
    assert uid == "88776655"

    # Verify AppConfig exchange_settings updated
    await db_session.refresh(cfg)
    assert cfg.exchange_settings["bitget"]["bitget_uid"] == "88776655"
    assert cfg.exchange_settings["bitget"]["uid"] == "88776655"

    # Verify HubNode updated directly in db
    await db_session.refresh(hub_node)
    assert hub_node.bitget_uid == "88776655"
