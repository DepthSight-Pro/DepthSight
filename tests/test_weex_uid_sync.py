import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from api import models, security
from api.routes.config import auto_resolve_weex_uid


@pytest.mark.asyncio
async def test_auto_resolve_weex_uid_no_keys(
    db_session: AsyncSession, free_user: models.User
):
    # If no keys exist, it should return None
    uid = await auto_resolve_weex_uid(db_session, free_user.id)
    assert uid is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
@patch("aiohttp.ClientSession.post")
async def test_weex_uid_sync_behavior(
    mock_aiohttp_post,
    mock_httpx_get,
    db_session: AsyncSession,
    free_user: models.User,
    monkeypatch,
):
    monkeypatch.setenv("IS_CENTRAL_HUB", "false")
    # 1. Add decrypted mock API keys for free_user
    encrypted_key = security.encrypt_data("test-api-key")
    encrypted_secret = security.encrypt_data("test-api-secret")

    api_key_obj = models.ApiKey(
        user_id=free_user.id,
        exchange="weex",
        name="Weex Test Key",
        encrypted_api_key=encrypted_key,
        encrypted_api_secret=encrypted_secret,
        key_prefix="test...1234",
        status="valid",
        is_active=True,
    )
    db_session.add(api_key_obj)

    # Retrieve existing AppConfig
    from sqlalchemy import select

    cfg_stmt = select(models.AppConfig).where(models.AppConfig.user_id == free_user.id)
    cfg_res = await db_session.execute(cfg_stmt)
    cfg = cfg_res.scalar_one()
    cfg.is_mining_enabled = False  # Mining is disabled initially
    cfg.exchange_settings = {}
    await db_session.commit()
    await db_session.refresh(cfg)

    # Mock Weex API response returning UID 999888
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_code = 200
    mock_resp.json.return_value = {"data": {"uid": 999888}}
    mock_httpx_get.return_value = mock_resp

    # Mock aiohttp Hub response
    mock_aiohttp_resp = MagicMock()
    mock_aiohttp_resp.status = 200
    mock_aiohttp_resp.text = AsyncMock(return_value="Success")

    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_aiohttp_resp)
    mock_context.__aexit__ = AsyncMock()
    mock_aiohttp_post.return_value = mock_context

    # 2. Resolve UID when mining is disabled (should NOT sync to Hub)
    uid = await auto_resolve_weex_uid(db_session, free_user.id)
    assert uid == "999888"
    mock_aiohttp_post.assert_not_called()

    # Verify UID was saved locally in AppConfig
    await db_session.refresh(cfg)
    assert cfg.exchange_settings["weex"]["weex_uid"] == "999888"

    # 3. Enable mining and resolve again (should trigger sync to Hub)
    cfg.is_mining_enabled = True
    # Configure mining node credentials
    cfg.exchange_settings = {
        "weex": {
            "weex_uid": "999888",
            "uid": "999888",
            "mining_node_uuid": "test-node-uuid",
            "mining_node_secret": "test-node-secret",
        }
    }
    await db_session.commit()

    uid = await auto_resolve_weex_uid(db_session, free_user.id)
    assert uid == "999888"
    mock_aiohttp_post.assert_called_once()
