"""Regression: read paths must not pin pool connections (pool exhaustion).

One long-lived session per controller + reads that never commit = one pool
connection pinned per controller forever (~300 pinned of a 350 pool, then
QueuePool timeouts fleet-wide). Read paths must use short sessions that always
close; write paths commit (which also releases).
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from api import models
from api.database import Base
from bot_module.paper_executor import PaperTradingExecutor
from bot_module.risk_manager import RiskManager


@pytest_asyncio.fixture()
async def queue_engine(tmp_path):
    """Dedicated QueuePool engine (the test-suite engine is StaticPool,
    which cannot observe checkouts)."""
    path = tmp_path / "lifecycle.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        poolclass=AsyncAdaptedQueuePool,
        pool_size=5,
        max_overflow=0,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
def queue_factory(queue_engine):
    maker = async_sessionmaker(queue_engine, expire_on_commit=False)

    @asynccontextmanager
    async def _scope():
        async with maker() as session:
            try:
                yield session
            except Exception:
                try:
                    await session.rollback()
                except Exception:
                    pass
                raise

    return _scope


@pytest.mark.asyncio
async def test_balance_reads_do_not_pin_connections(queue_engine, queue_factory):
    consumer = AsyncMock()
    ex = PaperTradingExecutor(
        user_id=1,
        db_session=AsyncMock(),
        data_consumer=consumer,
        db_session_factory=queue_factory,
    )
    pool = queue_engine.pool
    for _ in range(20):
        bal = await ex.get_account_balance()
        assert bal is not None and float(bal["USDT"]["free"]) > 0
        assert pool.checkedout() == 0, "a read must not hold a pool connection"

    # Legacy path (no factory) keeps working on the passed session.
    ex_legacy = PaperTradingExecutor(
        user_id=1, db_session=AsyncMock(), data_consumer=consumer
    )
    assert ex_legacy._db_factory is None


@pytest.mark.asyncio
async def test_risk_reads_do_not_pin_connections(queue_engine, queue_factory):
    rm = RiskManager(
        executor=None,
        paper_executor=AsyncMock(),
        user_id=1,
        db_session=AsyncMock(),
        user_settings={"risk_management": {"riskPerTradePercent": 1.0}},
        db_session_factory=queue_factory,
    )
    pool = queue_engine.pool
    for _ in range(10):
        await rm._load_risk_config()
        await rm._load_performance_from_db()
        assert pool.checkedout() == 0, "reads must not hold pool connections"


@pytest.mark.asyncio
async def test_performance_save_persists(queue_engine, queue_factory):
    """_save_performance_to_db must actually commit (it never did)."""
    from collections import deque

    from sqlalchemy import select

    from bot_module.risk_manager import SymbolStrategyPerformanceStats

    rm = RiskManager(
        executor=None,
        paper_executor=AsyncMock(),
        user_id=1,
        db_session=AsyncMock(),
        user_settings={"risk_management": {"riskPerTradePercent": 1.0}},
        db_session_factory=queue_factory,
    )
    stats = SymbolStrategyPerformanceStats(
        trade_results_buffer=deque([(10.0, 100.0)], maxlen=5),
        current_risk_multiplier_index=1,
        last_penalty_timestamp=0.0,
        total_trades_for_assessment=1,
        total_pnl_usd=10.0,
    )
    await rm._save_performance_to_db("BTCUSDT", "TestStrat", stats)
    assert queue_engine.pool.checkedout() == 0

    # Fresh session sees it: the save really committed.
    maker = async_sessionmaker(queue_engine, expire_on_commit=False)
    async with maker() as fresh:
        res = await fresh.execute(
            select(models.SymbolStrategyPerformance).where(
                models.SymbolStrategyPerformance.user_id == 1,
                models.SymbolStrategyPerformance.symbol == "BTCUSDT",
            )
        )
        row = res.scalars().first()
    assert row is not None
    assert row.total_pnl_usd == 10.0
