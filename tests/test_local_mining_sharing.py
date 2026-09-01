import datetime
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from api import models


def _wallet_node_uuid(address: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"evm:{address}"))


@pytest.mark.asyncio
async def test_local_mining_sharing_endpoints(
    db_session: AsyncSession,
    authenticated_client_factory,
    free_user: models.User,
):
    # 1. Create an admin user and client
    admin_user = models.User(
        username="miningadmin",
        email="miningadmin@example.com",
        hashed_password="somehashpassword",
        is_active=True,
        role="admin",
    )
    db_session.add(admin_user)
    await db_session.commit()
    await db_session.refresh(admin_user)

    admin_client = await authenticated_client_factory(admin_user)
    user_client = await authenticated_client_factory(free_user)

    # 2. Test GET /mining/node-config (Admin only)
    resp = await user_client.get("/api/v1/mining/node-config")
    assert resp.status_code == 403

    resp = await admin_client.get("/api/v1/mining/node-config")
    assert resp.status_code == 200
    config_data = resp.json()["data"]
    assert config_data["isGlobalMiningEnabled"] is False
    # Safe default is 75% user share (not the dangerous 0.0 = 100% operator fee).
    assert config_data["userRewardSharePercent"] == 75.0

    # 3. Test PUT /mining/node-config (Admin only)
    payload = {
        "isGlobalMiningEnabled": True,
        "userRewardSharePercent": 40.0,
    }
    resp = await user_client.put("/api/v1/mining/node-config", json=payload)
    assert resp.status_code == 403

    resp = await admin_client.put("/api/v1/mining/node-config", json=payload)
    assert resp.status_code == 200
    config_data = resp.json()["data"]
    assert config_data["isGlobalMiningEnabled"] is True
    assert config_data["userRewardSharePercent"] == 40.0

    # 4. Check DB was updated
    result = await db_session.execute(
        select(models.NodeMiningConfig).where(models.NodeMiningConfig.id == 1)
    )
    db_cfg = result.scalar_one()
    assert db_cfg.user_reward_share_percent == 40.0

    # 5. Setup telemetry reports (the data source /mining/status actually reads)
    user2 = models.User(
        username="user2",
        email="user2@example.com",
        hashed_password="somehashpassword",
        is_active=True,
        role="user",
    )
    db_session.add(user2)
    await db_session.commit()
    await db_session.refresh(user2)

    today_noon = datetime.datetime.combine(
        datetime.date.today(),
        datetime.time(12, 0),
        tzinfo=datetime.timezone.utc,
    )
    free_user_node_uuid = _wallet_node_uuid(f"0x{free_user.id:040x}")
    user2_node_uuid = _wallet_node_uuid(f"0x{user2.id:040x}")
    report1 = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=100.0,
        exit_price=101.0,
        trade_mode="LIVE",
        node_uuid=free_user_node_uuid,
        trade_volume_usdt=1000.0,
        estimated_rebate_usdt=1.0,
        is_mining_eligible=True,
        created_at=today_noon,
    )
    report2 = models.HubTelemetryReport(
        symbol="ETHUSDT",
        direction="SHORT",
        entry_price=2000.0,
        exit_price=1980.0,
        trade_mode="LIVE",
        node_uuid=user2_node_uuid,
        trade_volume_usdt=3000.0,
        estimated_rebate_usdt=3.0,
        is_mining_eligible=True,
        created_at=today_noon,
    )
    db_session.add_all([report1, report2])

    # Bind wallet-derived mining node identity in user's AppConfig
    cfg1 = await db_session.get(models.AppConfig, free_user.id)
    if not cfg1:
        cfg1 = models.AppConfig(
            user_id=free_user.id,
            is_mining_enabled=True,
            risk_management={},
            notifications={},
            data_sources={},
        )
        db_session.add(cfg1)
    else:
        cfg1.is_mining_enabled = True
    cfg1.exchange_settings = {
        "weex": {
            "mining_node_uuid": free_user_node_uuid,
            "mining_node_secret": "test-mining-secret",
            "wallet_address": f"0x{free_user.id:040x}",
        }
    }

    await db_session.commit()

    # 6. Test GET /mining/status calculations
    resp = await user_client.get("/api/v1/mining/status")
    assert resp.status_code == 200
    status_data = resp.json()["data"]
    # Ratio = 1000 / (1000 + 3000) = 0.25 (25%)
    # userRewardSharePercent = 40%
    # user_estimated_rebate = estimated_rebate (1.0) * userRewardSharePercent (0.4) = 0.40
    assert status_data["userRewardSharePercent"] == 40.0
    assert status_data["userTradeVolume"] == 1000.0
    assert status_data["userEstimatedRebate"] == 0.40
    assert status_data["stats"]["userRatio"] == 0.25
