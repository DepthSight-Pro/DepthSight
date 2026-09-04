import pytest
from datetime import date
from sqlalchemy import select
from api import models
from scripts.reset_mining import reset_mining


@pytest.mark.asyncio
async def test_reset_mining_dry_run(db_session, monkeypatch):
    """Dry run should inspect counts but not modify anything."""
    from api import database

    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: db_session)

    # Populate dummy data
    epoch = models.MiningEpoch(
        epoch_date=date(2026, 8, 1),
        daily_emission=100.0,
        total_rebate_pool=10.0,
        total_distributed=100.0,
        participating_nodes=1,
        status="finalized",
    )
    db_session.add(epoch)
    await db_session.commit()

    await reset_mining(dry_run=True)

    # Epoch should still exist
    res = await db_session.execute(select(models.MiningEpoch))
    assert res.scalars().first() is not None


@pytest.mark.asyncio
async def test_reset_mining_live_confirm(db_session, monkeypatch):
    """Confirm mode should clean epochs, ledgers, reports, and reset node total_mined."""
    from api import database

    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: db_session)

    # 1. Create dummy node, epoch, ledger, telemetry
    node = models.HubNode(
        node_uuid="test-miner-node-12345",
        name="TestMiner",
        secret_hash="dummyhash",
        total_mined=500.0,
        has_welcome_bonus=True,
        is_operator=False,
    )
    operator_node = models.HubNode(
        node_uuid="operator-node-root",
        name="OperatorRoot",
        secret_hash="dummyhash2",
        total_mined=1200.0,
        has_welcome_bonus=True,
        is_operator=True,
    )
    epoch = models.MiningEpoch(
        epoch_date=date(2026, 8, 1),
        daily_emission=100.0,
        total_rebate_pool=10.0,
        total_distributed=100.0,
        participating_nodes=2,
        status="finalized",
    )
    ledger = models.MiningLedger(
        node_uuid="test-miner-node-12345",
        epoch_date=date(2026, 8, 1),
        base_reward=50.0,
        total_reward=50.0,
    )
    cfg = models.MiningConfig(
        id=1,
        is_mining_enabled=True,
        daily_emission_base=1000.0,
        launch_date=date(2026, 1, 1),
        total_operator_fee_collected=45.0,
    )
    db_session.add_all([node, operator_node, epoch, ledger, cfg])
    await db_session.commit()

    # 2. Run reset with confirm (without wipe_nodes)
    today = date(2026, 9, 4)
    await reset_mining(
        dry_run=False,
        wipe_nodes=False,
        launch_date_val=today,
        daily_emission_base=547945.21,
    )

    # 3. Assertions
    epochs = (await db_session.execute(select(models.MiningEpoch))).scalars().all()
    assert len(epochs) == 0

    ledgers = (await db_session.execute(select(models.MiningLedger))).scalars().all()
    assert len(ledgers) == 0

    # Nodes still exist, but total_mined and has_welcome_bonus reset
    nodes = (await db_session.execute(select(models.HubNode))).scalars().all()
    assert len(nodes) == 2
    for n in nodes:
        assert n.total_mined == 0.0
        assert n.has_welcome_bonus is False

    # Config updated with new launch date and zero operator fee
    cfg_updated = (
        await db_session.execute(select(models.MiningConfig))
    ).scalars().first()
    assert cfg_updated.launch_date == today
    assert cfg_updated.daily_emission_base == 547945.21
    assert cfg_updated.total_operator_fee_collected == 0.0


@pytest.mark.asyncio
async def test_reset_mining_with_wipe_nodes(db_session, monkeypatch):
    """Confirm mode with --wipe-nodes should delete non-operator nodes."""
    from api import database

    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: db_session)

    node = models.HubNode(
        node_uuid="miner-to-delete",
        name="MinerToDelete",
        secret_hash="dummyhash",
        total_mined=100.0,
        has_welcome_bonus=True,
        is_operator=False,
    )
    operator_node = models.HubNode(
        node_uuid="operator-root-keep",
        name="OperatorRoot",
        secret_hash="dummyhash2",
        total_mined=300.0,
        has_welcome_bonus=True,
        is_operator=True,
    )
    db_session.add_all([node, operator_node])
    await db_session.commit()

    await reset_mining(dry_run=False, wipe_nodes=True)

    nodes = (await db_session.execute(select(models.HubNode))).scalars().all()
    assert len(nodes) == 1
    assert nodes[0].node_uuid == "operator-root-keep"
    assert nodes[0].total_mined == 0.0
    assert nodes[0].has_welcome_bonus is False
