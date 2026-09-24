# tests/test_promo_campaign.py
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from api import models


@pytest.mark.asyncio
async def test_promo_status_is_per_user_not_per_node(
    db_session: AsyncSession,
    authenticated_client_factory,
    sample_campaign: models.PromoCampaign,
):
    """Regression: user B must NOT see user A's volume/keys even when
    explicitly passing user A's node_uuid (чужой node ignored).

    Linkage is MetaMask-based (referral_code + node wallet + UID);
    the affiliate payout_address is intentionally NOT used.
    """
    wallet_a = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    wallet_b = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    user_a = models.User(
        username="promo_user_a",
        email="promo_user_a@example.com",
        hashed_password="somehashedpassword",
        is_active=True,
        role="user",
        referral_code="REF-PROMO-A",
    )
    user_b = models.User(
        username="promo_user_b",
        email="promo_user_b@example.com",
        hashed_password="somehashedpassword",
        is_active=True,
        role="user",
        referral_code="REF-PROMO-B",
    )
    db_session.add_all([user_a, user_b])
    await db_session.commit()
    await db_session.refresh(user_a)
    await db_session.refresh(user_b)

    # Public mode so non-admin users can see the campaign.
    sample_campaign.admin_only = False
    await db_session.commit()

    db_session.add(
        models.ApiKey(
            user_id=user_a.id,
            name="UserA Bitget Key",
            encrypted_api_key="enc_key",
            encrypted_api_secret="enc_secret",
            key_prefix="bg...aaaa",
            exchange="bitget",
            is_active=True,
        )
    )
    db_session.add(
        models.HubNode(
            node_uuid="user-a-promo-node",
            name="UserANode",
            secret_hash="secret",
            bitget_uid="uid_user_a",
            wallet_address=wallet_a,
            node_referral_code="REF-PROMO-A",
            total_mined=0.0,
        )
    )
    # User B owns an empty node (no UID, no volume) — own identity exists,
    # so a чужой X-Node-UUID must be ignored for personal data.
    db_session.add(
        models.HubNode(
            node_uuid="user-b-promo-node",
            name="UserBNode",
            secret_hash="secret",
            wallet_address=wallet_b,
            node_referral_code="REF-PROMO-B",
            total_mined=0.0,
        )
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=50000.0,
            exit_price=51000.0,
            trade_mode="live",
            trade_volume_usdt=1500.0,
            exchange_id="bitget_futures",
            node_uuid="user-a-promo-node",
            verification_status="VERIFIED",
            is_verified=True,
        )
    )
    await db_session.commit()

    client_a: AsyncClient = await authenticated_client_factory(user_a)
    client_b: AsyncClient = await authenticated_client_factory(user_b)

    # User A sees own aggregated data without passing any node header.
    res_a = await client_a.get("/api/v1/hub/promo/status")
    assert res_a.status_code == 200
    quest_a = next(q for q in res_a.json()["quests"] if q["questType"] == "api_volume")
    assert quest_a["requirements"]["totalVolume"] == 1500.0
    assert quest_a["requirements"]["verifiedVolume"] == 1500.0
    assert quest_a["requirements"]["hasExchangeKey"] is True
    assert quest_a["requirements"]["exchangeUid"] == "uid_user_a"
    assert quest_a["requirements"]["hasWallet"] is True

    # No physical node -> quest 2 card shows its own (empty) physical context.
    quest_a2 = next(
        q for q in res_a.json()["quests"] if q["questType"] == "node_runner"
    )
    assert quest_a2["requirements"]["totalVolume"] == 0.0
    assert quest_a2["requirements"]["isPhysicalNode"] is False
    assert quest_a2["allRequirementsMet"] is False

    # User B passes user A's node explicitly -> still sees only own (empty) data.
    res_b = await client_b.get(
        "/api/v1/hub/promo/status",
        headers={"X-Node-UUID": "user-a-promo-node"},
    )
    assert res_b.status_code == 200
    quest_b = next(q for q in res_b.json()["quests"] if q["questType"] == "api_volume")
    assert quest_b["requirements"]["totalVolume"] == 0.0
    assert quest_b["requirements"]["verifiedVolume"] == 0.0
    assert quest_b["requirements"]["hasExchangeKey"] is False
    assert quest_b["requirements"]["exchangeUid"] is None
    assert quest_b["isClaimed"] is False

    # User B cannot claim on top of user A's volume either (rejected: no own
    # UID/volume — чужой node context is ignored for identified users).
    res_claim = await client_b.post(
        "/api/v1/hub/promo/claim",
        json={"campaign_id": sample_campaign.id, "quest_type": "api_volume"},
        headers={"X-Node-UUID": "user-a-promo-node"},
    )
    assert res_claim.status_code == 400
    detail = res_claim.json()["detail"].lower()
    assert ("volume requirement not met" in detail) or ("uid" in detail)


@pytest.mark.asyncio
async def test_promo_affiliate_payout_alone_grants_nothing(
    db_session: AsyncSession,
    authenticated_client_factory,
    sample_campaign: models.PromoCampaign,
):
    """Affiliate User.payout_address is unrelated to mining/promo:
    without a MetaMask-bound wallet it must not satisfy hasWallet,
    must not resolve volume, and must not allow claims."""
    user = models.User(
        username="promo_affiliate_only",
        email="promo_affiliate_only@example.com",
        hashed_password="somehashedpassword",
        is_active=True,
        role="user",
        payout_address="0xdddddddddddddddddddddddddddddddddddddddd",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    sample_campaign.admin_only = False
    await db_session.commit()

    client: AsyncClient = await authenticated_client_factory(user)
    res = await client.get("/api/v1/hub/promo/status")
    assert res.status_code == 200
    quest = next(q for q in res.json()["quests"] if q["questType"] == "api_volume")
    assert quest["requirements"]["hasWallet"] is False
    assert quest["requirements"]["totalVolume"] == 0.0
    assert quest["allRequirementsMet"] is False

    res_claim = await client.post(
        "/api/v1/hub/promo/claim",
        json={"campaign_id": sample_campaign.id, "quest_type": "api_volume"},
    )
    assert res_claim.status_code == 400


@pytest.mark.asyncio
async def test_promo_volume_split_central_vs_physical(
    db_session: AsyncSession,
    authenticated_client_factory,
    sample_campaign: models.PromoCampaign,
):
    """Volume is split by context: non-physical (central) nodes feed quest 1,
    physical server nodes feed quest 2. Each quest is claimed from its own
    volume and the reward lands on the node of that context."""
    wallet = "0xcccccccccccccccccccccccccccccccccccccccc"
    user = models.User(
        username="promo_multi_node",
        email="promo_multi_node@example.com",
        hashed_password="somehashedpassword",
        is_active=True,
        role="user",
        referral_code="REF-MULTI-001",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Public mode so non-admin users can see the campaign.
    sample_campaign.admin_only = False
    await db_session.commit()

    db_session.add(
        models.ApiKey(
            user_id=user.id,
            name="Multi Bitget Key",
            encrypted_api_key="enc_key",
            encrypted_api_secret="enc_secret",
            key_prefix="bg...cccc",
            exchange="bitget",
            is_active=True,
        )
    )
    # NOTE: HubNode.wallet_address is unique, so the second (server) node
    # links via referral_code + exchange UID instead of duplicating wallet.
    now = datetime.now(timezone.utc)
    db_session.add(
        models.HubNode(
            node_uuid="multi-node-central",
            name="MultiNodeCentral",
            secret_hash="secret",
            bitget_uid="uid_multi",
            wallet_address=wallet,
            total_mined=0.0,
        )
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=50000.0,
            exit_price=51000.0,
            trade_mode="live",
            trade_volume_usdt=1200.0,
            exchange_id="bitget_futures",
            node_uuid="multi-node-central",
            verification_status="VERIFIED",
            is_verified=True,
        )
    )
    db_session.add(
        models.HubNode(
            node_uuid="multi-node-server",
            name="MultiNodeServer",
            secret_hash="secret",
            bitget_uid="uid_multi",
            node_referral_code="REF-MULTI-001",
            ip_address="198.51.100.77",
            last_ping=now,
            created_at=now - timedelta(days=20),
            total_mined=0.0,
        )
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=50000.0,
            exit_price=51000.0,
            trade_mode="live",
            trade_volume_usdt=1500.0,
            exchange_id="bitget_futures",
            node_uuid="multi-node-server",
            verification_status="VERIFIED",
            is_verified=True,
            created_at=now - timedelta(days=1),
        )
    )
    await db_session.commit()

    client: AsyncClient = await authenticated_client_factory(user)
    res = await client.get("/api/v1/hub/promo/status")
    assert res.status_code == 200
    data = res.json()

    quest1 = next(q for q in data["quests"] if q["questType"] == "api_volume")
    assert quest1["requirements"]["totalVolume"] == 1200.0
    assert quest1["requirements"]["verifiedVolume"] == 1200.0
    assert quest1["requirements"]["volumeContext"] == "central"
    assert quest1["allRequirementsMet"] is True

    quest2 = next(q for q in data["quests"] if q["questType"] == "node_runner")
    assert quest2["requirements"]["totalVolume"] == 1500.0
    assert quest2["requirements"]["verifiedVolume"] == 1500.0
    assert quest2["requirements"]["volumeContext"] == "physical"
    assert quest2["requirements"]["isPhysicalNode"] is True
    assert quest2["requirements"]["nodeAgeDays"] == 20
    assert quest2["requirements"]["hasActiveMining"] is True
    assert quest2["allRequirementsMet"] is True

    # Claim quest 1 -> reward lands on the central node.
    res_c1 = await client.post(
        "/api/v1/hub/promo/claim",
        json={"campaign_id": sample_campaign.id, "quest_type": "api_volume"},
    )
    assert res_c1.status_code == 200

    # Claim quest 2 (same UID/wallet, different quest_type is allowed) ->
    # reward lands on the physical server node.
    res_c2 = await client.post(
        "/api/v1/hub/promo/claim",
        json={"campaign_id": sample_campaign.id, "quest_type": "node_runner"},
    )
    assert res_c2.status_code == 200

    db_session.expire_all()
    central_node = (
        (
            await db_session.execute(
                select(models.HubNode).where(
                    models.HubNode.node_uuid == "multi-node-central"
                )
            )
        )
        .scalars()
        .first()
    )
    server_node = (
        (
            await db_session.execute(
                select(models.HubNode).where(
                    models.HubNode.node_uuid == "multi-node-server"
                )
            )
        )
        .scalars()
        .first()
    )
    assert central_node.total_mined == 5000.0
    assert server_node.total_mined == 25000.0


@pytest.mark.asyncio
async def test_promo_claim_reward_never_lands_on_foreign_node(
    db_session: AsyncSession,
    authenticated_client_factory,
    sample_campaign: models.PromoCampaign,
):
    """Identified user claiming with a чужой X-Node-UUID: volume is own,
    and the reward is credited to the OWN node, never the чужой one."""
    wallet_own = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    wallet_other = "0xffffffffffffffffffffffffffffffffffffffff"
    user = models.User(
        username="promo_target_check",
        email="promo_target_check@example.com",
        hashed_password="somehashedpassword",
        is_active=True,
        role="user",
        referral_code="REF-TARGET-001",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    sample_campaign.admin_only = False
    await db_session.commit()

    db_session.add(
        models.ApiKey(
            user_id=user.id,
            name="Target Bitget Key",
            encrypted_api_key="enc_key",
            encrypted_api_secret="enc_secret",
            key_prefix="bg...eeee",
            exchange="bitget",
            is_active=True,
        )
    )
    db_session.add(
        models.HubNode(
            node_uuid="own-central-node",
            name="OwnCentral",
            secret_hash="secret",
            bitget_uid="uid_target",
            wallet_address=wallet_own,
            node_referral_code="REF-TARGET-001",
            total_mined=0.0,
        )
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=50000.0,
            exit_price=51000.0,
            trade_mode="live",
            trade_volume_usdt=1500.0,
            exchange_id="bitget_futures",
            node_uuid="own-central-node",
            verification_status="VERIFIED",
            is_verified=True,
        )
    )
    db_session.add(
        models.HubNode(
            node_uuid="foreign-node",
            name="Foreign",
            secret_hash="secret",
            bitget_uid="uid_foreign",
            wallet_address=wallet_other,
            total_mined=0.0,
        )
    )
    await db_session.commit()

    client: AsyncClient = await authenticated_client_factory(user)
    res_claim = await client.post(
        "/api/v1/hub/promo/claim",
        json={"campaign_id": sample_campaign.id, "quest_type": "api_volume"},
        headers={"X-Node-UUID": "foreign-node"},
    )
    assert res_claim.status_code == 200

    campaign_id = sample_campaign.id
    db_session.expire_all()
    own_node = (
        (
            await db_session.execute(
                select(models.HubNode).where(
                    models.HubNode.node_uuid == "own-central-node"
                )
            )
        )
        .scalars()
        .first()
    )
    foreign_node = (
        (
            await db_session.execute(
                select(models.HubNode).where(models.HubNode.node_uuid == "foreign-node")
            )
        )
        .scalars()
        .first()
    )
    assert own_node.total_mined == 5000.0
    assert foreign_node.total_mined == 0.0
    claim = (
        (
            await db_session.execute(
                select(models.PromoClaim).where(
                    models.PromoClaim.campaign_id == campaign_id,
                    models.PromoClaim.quest_type == "api_volume",
                )
            )
        )
        .scalars()
        .first()
    )
    assert claim.node_uuid == "own-central-node"
    assert claim.exchange_uid == "uid_target"


@pytest.fixture
async def promo_admin_user(db_session: AsyncSession) -> models.User:
    admin = models.User(
        username="promoadmin",
        email="promoadmin@example.com",
        hashed_password="somehashedpassword",
        is_active=True,
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


@pytest.fixture
async def sample_campaign(db_session: AsyncSession) -> models.PromoCampaign:
    campaign = models.PromoCampaign(
        id="bitget_launch_test",
        name="Bitget Launch Airdrop Test",
        description="Connect API keys & trade to earn tokens",
        exchange_id="bitget",
        total_pool=10_000_000.0,
        distributed=0.0,
        admin_only=True,
        is_active=True,
        quests=[
            {
                "quest_type": "api_volume",
                "title": "Bitget API Pioneer",
                "description": "Connect API key & trade $1,000",
                "reward": 5000.0,
                "total_slots": 2,
                "volume_threshold": 1000.0,
            },
            {
                "quest_type": "node_runner",
                "title": "Infrastructure Pioneer",
                "description": "Run node for 14+ days & trade $1,000",
                "reward": 25000.0,
                "total_slots": 2,
                "volume_threshold": 1000.0,
                "min_node_age_days": 14,
            },
        ],
        ui_config={"accent_color": "#00F0FF", "primary_color": "#1DA2B4"},
    )
    db_session.add(campaign)
    await db_session.commit()
    await db_session.refresh(campaign)
    return campaign


@pytest.mark.asyncio
async def test_admin_only_preview_visibility(
    db_session: AsyncSession,
    authenticated_client_factory,
    free_user: models.User,
    promo_admin_user: models.User,
    sample_campaign: models.PromoCampaign,
):
    """Verifies that while admin_only=True, regular users see no campaign, but admin sees preview."""
    user_client: AsyncClient = await authenticated_client_factory(free_user)
    admin_client: AsyncClient = await authenticated_client_factory(promo_admin_user)

    # Regular user check
    res = await user_client.get("/api/v1/hub/promo/status")
    assert res.status_code == 200
    data = res.json()
    assert data["hasActiveCampaign"] is False

    # Admin user check
    res_admin = await admin_client.get("/api/v1/hub/promo/status")
    assert res_admin.status_code == 200
    data_admin = res_admin.json()
    assert data_admin["hasActiveCampaign"] is True
    assert data_admin["isAdminPreview"] is True
    assert data_admin["campaignId"] == "bitget_launch_test"
    assert len(data_admin["quests"]) == 2


@pytest.mark.asyncio
async def test_campaign_admin_crud(
    db_session: AsyncSession,
    authenticated_client_factory,
    promo_admin_user: models.User,
    free_user: models.User,
    monkeypatch,
):
    """Verifies admin CRUD on promo campaigns and Central Hub enforcement."""
    admin_client: AsyncClient = await authenticated_client_factory(promo_admin_user)
    user_client: AsyncClient = await authenticated_client_factory(free_user)

    # 1. Non-central hub rejected
    monkeypatch.setenv("IS_CENTRAL_HUB", "false")
    res_fail = await admin_client.get("/api/v1/hub/promo/admin/campaigns")
    assert res_fail.status_code == 403

    # 2. Central hub allowed
    monkeypatch.setenv("IS_CENTRAL_HUB", "true")

    # Regular user rejected
    res_user = await user_client.get("/api/v1/hub/promo/admin/campaigns")
    assert res_user.status_code == 403

    # Admin creates campaign
    new_campaign_payload = {
        "id": "bybit_summer_promo",
        "name": "Bybit Summer Promo",
        "exchangeId": "bybit",
        "totalPool": 5000000.0,
        "adminOnly": False,
        "isActive": True,
        "quests": [
            {
                "quest_type": "api_volume",
                "title": "Bybit Trader",
                "reward": 2500.0,
                "total_slots": 500,
                "volume_threshold": 500.0,
            }
        ],
    }
    res_create = await admin_client.post(
        "/api/v1/hub/promo/admin/campaigns", json=new_campaign_payload
    )
    assert res_create.status_code == 200
    created = res_create.json()
    assert created["id"] == "bybit_summer_promo"
    assert created["exchangeId"] == "bybit"

    # List campaigns
    res_list = await admin_client.get("/api/v1/hub/promo/admin/campaigns")
    assert res_list.status_code == 200
    campaigns = res_list.json()
    assert any(c["id"] == "bybit_summer_promo" for c in campaigns)


@pytest.mark.asyncio
async def test_claim_api_volume_success(
    db_session: AsyncSession,
    authenticated_client_factory,
    promo_admin_user: models.User,
    sample_campaign: models.PromoCampaign,
):
    """Verifies node with verified Bitget volume claims API quest and receives DEPTH reward."""
    admin_client: AsyncClient = await authenticated_client_factory(promo_admin_user)

    node = models.HubNode(
        node_uuid="test-node-claim-1",
        name="ClaimerNode",
        secret_hash="secret",
        bitget_uid="123456789",
        wallet_address="0x1111111111111111111111111111111111111111",
        total_mined=0.0,
    )
    db_session.add(node)
    await db_session.commit()

    # Add verified telemetry trade volume
    report = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        timeframe="1m",
        entry_price=50000.0,
        exit_price=51000.0,
        trade_mode="live",
        trade_volume_usdt=1500.0,
        exchange_id="bitget_futures",
        node_uuid="test-node-claim-1",
        verification_status="VERIFIED",
        is_verified=True,
    )
    db_session.add(report)
    await db_session.commit()

    # Claim quest
    claim_payload = {
        "campaign_id": sample_campaign.id,
        "quest_type": "api_volume",
    }
    res = await admin_client.post(
        "/api/v1/hub/promo/claim",
        json=claim_payload,
        headers={"X-Node-UUID": "test-node-claim-1"},
    )
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["success"] is True
    assert res_data["rewardAmount"] == 5000.0

    # Verify node received tokens
    await db_session.refresh(node)
    assert node.total_mined == 5000.0

    # Verify campaign distributed tokens updated
    await db_session.refresh(sample_campaign)
    assert sample_campaign.distributed == 5000.0

    # Verify second claim by same UID is rejected (409 Conflict)
    res_duplicate = await admin_client.post(
        "/api/v1/hub/promo/claim",
        json=claim_payload,
        headers={"X-Node-UUID": "test-node-claim-1"},
    )
    assert res_duplicate.status_code == 409


@pytest.mark.asyncio
async def test_claim_node_runner_validation(
    db_session: AsyncSession,
    authenticated_client_factory,
    promo_admin_user: models.User,
    sample_campaign: models.PromoCampaign,
):
    """Verifies node runner quest enforces physical node, minimum age (14 days), linked wallet, and active trades."""
    admin_client: AsyncClient = await authenticated_client_factory(promo_admin_user)

    # 1. Virtual central hub node (no IP, no last_ping) -> rejected because it's not a physical node
    young_node = models.HubNode(
        node_uuid="young-node-uuid",
        name="YoungNode",
        secret_hash="secret",
        bitget_uid="99887766",
        wallet_address="0x2222222222222222222222222222222222222222",
        created_at=datetime.now(timezone.utc) - timedelta(days=20),
        total_mined=0.0,
    )
    db_session.add(young_node)

    # Add verified trade volume
    db_session.add(
        models.HubTelemetryReport(
            symbol="ETHUSDT",
            direction="LONG",
            entry_price=3000.0,
            exit_price=3100.0,
            trade_mode="live",
            trade_volume_usdt=2000.0,
            exchange_id="bitget",
            node_uuid="young-node-uuid",
            verification_status="VERIFIED",
            is_verified=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
    )
    await db_session.commit()

    claim_payload = {
        "campaign_id": sample_campaign.id,
        "quest_type": "node_runner",
    }
    res_virtual = await admin_client.post(
        "/api/v1/hub/promo/claim",
        json=claim_payload,
        headers={"X-Node-UUID": "young-node-uuid"},
    )
    assert res_virtual.status_code == 400
    assert "physical node requirement not met" in res_virtual.json()["detail"].lower()

    # 2. Make it a physical node but only 5 days old -> rejected for age
    young_node.ip_address = "198.51.100.42"
    young_node.last_ping = datetime.now(timezone.utc)
    young_node.created_at = datetime.now(timezone.utc) - timedelta(days=5)
    await db_session.commit()

    res_too_young = await admin_client.post(
        "/api/v1/hub/promo/claim",
        json=claim_payload,
        headers={"X-Node-UUID": "young-node-uuid"},
    )
    assert res_too_young.status_code == 400
    assert "node active for" in res_too_young.json()["detail"].lower()

    # 3. Update created_at to 20 days ago -> now eligible!
    young_node.created_at = datetime.now(timezone.utc) - timedelta(days=20)
    await db_session.commit()

    res_success = await admin_client.post(
        "/api/v1/hub/promo/claim",
        json=claim_payload,
        headers={"X-Node-UUID": "young-node-uuid"},
    )
    assert res_success.status_code == 200
    assert res_success.json()["rewardAmount"] == 25000.0


@pytest.mark.asyncio
async def test_anti_fraud_duplicate_wallet_rejected(
    db_session: AsyncSession,
    authenticated_client_factory,
    promo_admin_user: models.User,
    sample_campaign: models.PromoCampaign,
):
    """Verifies that if a user deletes their node identity and creates a new node

    with the same wallet address, the second claim is rejected because the wallet
    is permanently recorded in promo_claims.
    """
    admin_client: AsyncClient = await authenticated_client_factory(promo_admin_user)
    shared_wallet = "0x3333333333333333333333333333333333333333"

    # Node 1 is registered and trades
    node1 = models.HubNode(
        node_uuid="wallet-node-1",
        name="Node1",
        secret_hash="secret",
        bitget_uid="uid_111",
        wallet_address=shared_wallet,
        total_mined=0.0,
    )
    db_session.add(node1)
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=50000.0,
            exit_price=51000.0,
            trade_mode="live",
            trade_volume_usdt=1500.0,
            exchange_id="bitget_futures",
            node_uuid="wallet-node-1",
            verification_status="VERIFIED",
            is_verified=True,
        )
    )
    await db_session.commit()

    # Node 1 claims -> success!
    res1 = await admin_client.post(
        "/api/v1/hub/promo/claim",
        json={"campaign_id": sample_campaign.id, "quest_type": "api_volume"},
        headers={"X-Node-UUID": "wallet-node-1"},
    )
    assert res1.status_code == 200

    # User removes node 1 (e.g. deletes node_identity.json) and registers node 2 with same wallet
    node1.wallet_address = None
    node2 = models.HubNode(
        node_uuid="wallet-node-2",
        name="Node2",
        secret_hash="secret",
        bitget_uid="uid_222",
        wallet_address=shared_wallet,
        total_mined=0.0,
    )
    db_session.add(node2)
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=50000.0,
            exit_price=51000.0,
            trade_mode="live",
            trade_volume_usdt=1500.0,
            exchange_id="bitget_futures",
            node_uuid="wallet-node-2",
            verification_status="VERIFIED",
            is_verified=True,
        )
    )
    await db_session.commit()

    # Node 2 tries to claim with the same wallet -> 409 Conflict
    res2 = await admin_client.post(
        "/api/v1/hub/promo/claim",
        json={"campaign_id": sample_campaign.id, "quest_type": "api_volume"},
        headers={"X-Node-UUID": "wallet-node-2"},
    )
    assert res2.status_code == 409
    assert "already claimed" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_volume_threshold_rejected(
    db_session: AsyncSession,
    authenticated_client_factory,
    promo_admin_user: models.User,
    sample_campaign: models.PromoCampaign,
):
    """Verifies that a node with volume below threshold is rejected."""
    admin_client: AsyncClient = await authenticated_client_factory(promo_admin_user)

    low_vol_node = models.HubNode(
        node_uuid="low-vol-node",
        name="LowVolNode",
        secret_hash="secret",
        bitget_uid="uid_low",
        wallet_address="0x4444444444444444444444444444444444444444",
        total_mined=0.0,
    )
    db_session.add(low_vol_node)

    # Volume $500 < $1,000 threshold
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=50000.0,
            exit_price=51000.0,
            trade_mode="live",
            trade_volume_usdt=500.0,
            exchange_id="bitget",
            node_uuid="low-vol-node",
            verification_status="VERIFIED",
            is_verified=True,
        )
    )
    await db_session.commit()

    res = await admin_client.post(
        "/api/v1/hub/promo/claim",
        json={"campaign_id": sample_campaign.id, "quest_type": "api_volume"},
        headers={"X-Node-UUID": "low-vol-node"},
    )
    assert res.status_code == 400
    assert "volume requirement not met" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_promo_detects_preexisting_api_key_without_uid(
    db_session: AsyncSession,
    authenticated_client_factory,
    promo_admin_user: models.User,
    sample_campaign: models.PromoCampaign,
):
    """Verifies that promo status detects pre-existing Bitget API keys in api_keys table even if UID is not resolved yet."""
    admin_client: AsyncClient = await authenticated_client_factory(promo_admin_user)

    # Pre-existing API key connected before promo without exchange_settings UID
    api_key = models.ApiKey(
        user_id=promo_admin_user.id,
        name="Pre-existing Bitget Key",
        encrypted_api_key="enc_key",
        encrypted_api_secret="enc_secret",
        key_prefix="bg...1234",
        exchange="bitget",
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.commit()

    res = await admin_client.get("/api/v1/hub/promo/status")
    assert res.status_code == 200
    data = res.json()
    assert data["hasActiveCampaign"] is True
    assert len(data["quests"]) > 0
    # The first quest requirements should detect hasExchangeKey = True
    assert data["quests"][0]["requirements"]["hasExchangeKey"] is True


@pytest.mark.asyncio
async def test_unverified_pending_volume_cannot_be_claimed(
    db_session: AsyncSession,
    authenticated_client_factory,
    promo_admin_user: models.User,
    sample_campaign: models.PromoCampaign,
):
    """Verifies that pending (unverified) trades fill total_volume and trigger is_volume_verifying,
    but cannot be claimed until broker verification marks them VERIFIED."""
    admin_client: AsyncClient = await authenticated_client_factory(promo_admin_user)

    node = models.HubNode(
        node_uuid="pending-vol-node",
        name="PendingVolNode",
        secret_hash="secret",
        bitget_uid="uid_pending",
        wallet_address="0x5555555555555555555555555555555555555555",
        total_mined=0.0,
    )
    db_session.add(node)

    # Add a pending trade report of $1,200 (> $1,000 threshold, but unverified)
    trade = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=60000.0,
        exit_price=61200.0,
        trade_mode="live",
        trade_volume_usdt=1200.0,
        exchange_id="bitget_futures",
        node_uuid="pending-vol-node",
        verification_status="PENDING",
        is_verified=False,
    )
    db_session.add(trade)
    await db_session.commit()

    # Check promo status: total_volume is 1200, verified_volume is 0
    res_status = await admin_client.get(
        "/api/v1/hub/promo/status",
        headers={"X-Node-UUID": "pending-vol-node"},
    )
    assert res_status.status_code == 200
    data = res_status.json()
    api_quest = next(q for q in data["quests"] if q["questType"] == "api_volume")
    assert api_quest["requirements"]["totalVolume"] == 1200.0
    assert api_quest["requirements"]["verifiedVolume"] == 0.0
    assert api_quest["requirements"]["isVolumeVerifying"] is True
    assert api_quest["requirements"]["isVolumeVerified"] is False
    assert api_quest["allRequirementsMet"] is False

    # Attempting to claim must fail with 400 and state undergoing broker verification
    res_claim_fail = await admin_client.post(
        "/api/v1/hub/promo/claim",
        json={"campaign_id": sample_campaign.id, "quest_type": "api_volume"},
        headers={"X-Node-UUID": "pending-vol-node"},
    )
    assert res_claim_fail.status_code == 400
    assert "broker verification" in res_claim_fail.json()["detail"].lower()

    # Now simulate broker verification marking the trade as VERIFIED
    trade.verification_status = "VERIFIED"
    trade.is_verified = True
    await db_session.commit()

    # Re-check status: now verified_volume is 1200, isVolumeVerifying is False, isVolumeVerified is True
    res_status2 = await admin_client.get(
        "/api/v1/hub/promo/status",
        headers={"X-Node-UUID": "pending-vol-node"},
    )
    assert res_status2.status_code == 200
    data2 = res_status2.json()
    api_quest2 = next(q for q in data2["quests"] if q["questType"] == "api_volume")
    assert api_quest2["requirements"]["totalVolume"] == 1200.0
    assert api_quest2["requirements"]["verifiedVolume"] == 1200.0
    assert api_quest2["requirements"]["isVolumeVerifying"] is False
    assert api_quest2["requirements"]["isVolumeVerified"] is True
    assert api_quest2["allRequirementsMet"] is True

    # Claim now succeeds
    res_claim_success = await admin_client.post(
        "/api/v1/hub/promo/claim",
        json={"campaign_id": sample_campaign.id, "quest_type": "api_volume"},
        headers={"X-Node-UUID": "pending-vol-node"},
    )
    assert res_claim_success.status_code == 200
    assert res_claim_success.json()["success"] is True
