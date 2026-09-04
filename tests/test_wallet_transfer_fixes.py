import pytest
from httpx import AsyncClient
from sqlalchemy import update

from api import models, security
from api.security import create_access_token
from api.routes.config import _ensure_node_secret


@pytest.mark.asyncio
async def test_disconnect_evm_wallet_cleans_all_keys(
    test_client: AsyncClient, test_user, db_session
):
    # Set up config with wallet data in multiple places
    settings = {
        "wallet_address": "0x1234567890123456789012345678901234567890",
        "wallet_configured": True,
        "mining_node_uuid": "some-uuid-1",
        "mining_node_secret": "some-secret-1",
        "weex": {
            "wallet_address": "0x1234567890123456789012345678901234567890",
            "wallet_configured": True,
            "mining_node_uuid": "some-uuid-1",
            "mining_node_secret": "some-secret-1",
        },
        "bybit": {
            "wallet_address": "0x1234567890123456789012345678901234567890",
            "wallet_configured": True,
        },
    }
    await db_session.execute(
        update(models.AppConfig)
        .where(models.AppConfig.user_id == test_user.id)
        .values(exchange_settings=settings, is_mining_enabled=True)
    )
    await db_session.commit()

    token = create_access_token(data={"sub": test_user.username})
    headers = {"Authorization": f"Bearer {token}"}

    # Call disconnect
    resp = await test_client.post("/api/v1/node/wallet/disconnect", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["success"] is True

    # Check status
    status_resp = await test_client.get("/api/v1/node/wallet/status", headers=headers)
    assert status_resp.status_code == 200
    status_data = status_resp.json()["data"]
    assert status_data["walletConfigured"] is False
    assert status_data["walletAddress"] is None


@pytest.mark.asyncio
async def test_ensure_node_secret_does_not_overwrite_existing(db_session, test_user):
    existing_secret_hash = "existing_authoritative_hash_123"
    node = models.HubNode(
        node_uuid="test-uuid-ensure",
        name="DepthSightNode-test",
        secret_hash=existing_secret_hash,
    )
    db_session.add(node)
    await db_session.commit()

    settings = {
        "weex": {
            "mining_node_secret": security.encrypt_node_secret("different_local_secret")
        }
    }

    # Calling _ensure_node_secret must NOT overwrite the existing secret_hash
    await _ensure_node_secret(
        db_session, test_user.id, settings, "test-uuid-ensure", node
    )
    assert node.secret_hash == existing_secret_hash


@pytest.mark.asyncio
async def test_wallet_nodes_excluded_from_active_servers_list(
    test_client: AsyncClient, db_session
):
    from datetime import datetime, timezone

    # 1. Physical server node (wallet_address is None)
    server_node = models.HubNode(
        node_uuid="server-node-1",
        name="DepthSightNode-server1",
        secret_hash="hash1",
        last_ping=datetime.now(timezone.utc),
        is_mining_server=True,
        wallet_address=None,
    )
    # 2. Personal wallet node (wallet_address is set)
    wallet_node = models.HubNode(
        node_uuid="wallet-node-1",
        name="DepthSightNode-wallet1",
        secret_hash="hash2",
        last_ping=datetime.now(timezone.utc),
        is_mining_server=False,
        wallet_address="0x1111111111111111111111111111111111111111",
    )
    db_session.add(server_node)
    db_session.add(wallet_node)
    await db_session.commit()

    resp = await test_client.get("/api/v1/hub/nodes")
    assert resp.status_code == 200
    nodes = resp.json()

    names = [n["name"] for n in nodes]
    assert "DepthSightNode-server1" in names
    # Wallet node MUST NOT be in the server federation list
    assert "DepthSightNode-wallet1" not in names
