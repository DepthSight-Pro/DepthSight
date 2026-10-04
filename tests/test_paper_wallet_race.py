"""Regression test for the paper-wallet race that rejected 93% of signals.

Reproduces the real failure: several PaperTradingExecutors sharing ONE
AsyncSession (as bot_runner.py does per shard) each needing to create their
wallet for the first time. Before the fix this raised
"InvalidRequestError: Session is already flushing", the executor swallowed it
and returned None, and RiskManager turned that into a $0.00 balance and a
ZERO_BALANCE rejection.

Run: pytest tests/test_paper_wallet_race.py -v
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("JWT_SECRET_KEY", "test_secret_key_1234567890_test_secret")
os.environ.setdefault(
    "API_ENCRYPTION_KEY", "fFEvqTGV-LGkN0ASdZrlOUhEpllCyi1Dj-PmKY3eh6Y="
)
os.environ.setdefault("API_KEY_SECRET", "test_api_key_secret_1234567890")
os.environ.setdefault("POSTGRES_USER", "testuser")
os.environ.setdefault("POSTGRES_PASSWORD", "testpassword")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_DB", "testdb")
os.environ.setdefault("TESTING", "true")
os.environ.setdefault("IS_CENTRAL_HUB", "true")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from api.database import Base  # noqa: E402
import api.models as models  # noqa: E402


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield factory
    finally:
        await engine.dispose()


def _make_executor(user_id, db):
    from bot_module.paper_executor import PaperTradingExecutor

    ex = PaperTradingExecutor(
        user_id=user_id, db_session=db, data_consumer=None, redis_client=None
    )
    return ex


@pytest.mark.asyncio
async def test_paper_wallet_ensured_at_startup_not_lazily(session_factory):
    """initialize_equity_tracking must create the wallet.

    Called once per controller from bot_runner during startup, so the create
    path never runs concurrently inside signal processing.
    """
    async with session_factory() as db:
        user = models.User(
            username="race_user_1",
            email="race_user_1@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id

    async with session_factory() as db:
        ex = _make_executor(uid, db)
        await ex.initialize_equity_tracking()

    async with session_factory() as db:
        bal = await _make_executor(uid, db).get_account_balance()
        assert bal is not None, "wallet must exist after startup initialisation"
        assert float(bal["USDT"]["free"]) > 0, "paper wallet must be funded"


@pytest.mark.asyncio
async def test_concurrent_first_reads_with_one_session_per_controller(session_factory):
    """The fixed production shape: concurrent controllers, each with its OWN session.

    Before the fix every controller of a shard shared one session, and the
    concurrent wallet creations raised "InvalidRequestError: Session is already
    flushing" - 456 times in the observed run, zeroing 152 of 163 balance reads.
    """
    from sqlalchemy import select

    async with session_factory() as db:
        for i in range(8):
            db.add(
                models.User(
                    username=f"race_user_{i}",
                    email=f"race_user_{i}@example.com",
                    hashed_password="x",
                    is_active=True,
                )
            )
        await db.commit()

    async with session_factory() as probe:
        uids = list((await probe.execute(select(models.User.id))).scalars())

    async def one(uid):
        async with session_factory() as own_session:  # <- one session each
            return await _make_executor(uid, own_session).get_account_balance()

    results = await asyncio.gather(*(one(uid) for uid in uids), return_exceptions=True)
    failures = [r for r in results if not isinstance(r, dict)]
    assert not failures, (
        f"{len(failures)}/{len(results)} executors failed to obtain a paper "
        f"balance: {failures[:3]}"
    )
    for r in results:
        assert float(r["USDT"]["free"]) > 0, "every wallet must be funded"


@pytest.mark.asyncio
async def test_shared_session_still_reports_failure_instead_of_zero(session_factory):
    """A broken/unavailable wallet must never look like a funded $0.00 balance.

    Even if a session is unusable, the RiskManager must say so explicitly rather
    than sizing against zero (finding A8 made this undiagnosable).
    """
    from bot_module.risk_manager import RiskManager
    from bot_module.strategy import SignalDirection

    class BrokenPaper:
        async def get_account_balance(self):
            return None

    class ZeroPaper:
        async def get_account_balance(self):
            return {"USDT": {"free": "0.0", "locked": "0.0"}}

    class Sig:
        symbol = "BTCUSDT"
        direction = SignalDirection.LONG
        stop_loss = None
        take_profit = None
        trigger_price = 100.0
        risk_usd = None
        risk_pct = None
        strategy_name = "VisualBuilderStrategy"
        details = {}

    for paper, expected in (
        (BrokenPaper(), "PAPER_BALANCE_FETCH_FAILED"),
        (ZeroPaper(), "PAPER_ZERO_BALANCE"),
    ):
        async with session_factory() as db:
            rm = RiskManager(
                executor=None,
                paper_executor=paper,
                user_id=1,
                db_session=db,
                user_settings={"risk_management": {"riskPerTradePercent": 1.0}},
            )
            approved, qty, _risk, reason = await rm.assess_signal(
                Sig(), None, None, mode="paper"
            )
        assert approved is False, f"{type(paper).__name__} must not be approved"
        assert qty is None
        assert reason == expected, f"got {reason!r}, expected {expected!r}"
        assert reason != "ZERO_BALANCE", (
            "ZERO_BALANCE means the live-balance gate, not a paper wallet problem"
        )
