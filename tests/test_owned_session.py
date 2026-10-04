"""Regression: controller DB sessions must never leak (pool exhaustion).

`async for db in self.get_db_session()` abandoned the generator (and its
checked-out pool connection) whenever the body returned or raised. With ~300
controllers doing that every few seconds the pool drained to QueuePool timeout
even though it was sized correctly. `_owned_session` guarantees rollback and
close on every path.
"""

import pytest

from bot_module.controller import TradingController


class FakeSession:
    def __init__(self, tracker):
        self._tracker = tracker

    async def rollback(self):
        self._tracker["rollbacks"] += 1

    async def close(self):
        self._tracker["closes"] += 1


def _make_controller(factory):
    ctrl = TradingController.__new__(TradingController)
    ctrl.get_db_session = factory
    return ctrl


def _tracking_factory(tracker):
    async def factory():
        tracker["created"] += 1
        yield FakeSession(tracker)

    return factory


@pytest.mark.asyncio
async def test_owned_session_closed_on_normal_exit():
    tracker = {"created": 0, "rollbacks": 0, "closes": 0}
    ctrl = _make_controller(_tracking_factory(tracker))

    async with ctrl._owned_session() as db:
        assert isinstance(db, FakeSession)

    assert tracker == {"created": 1, "rollbacks": 0, "closes": 1}


@pytest.mark.asyncio
async def test_owned_session_rolled_back_and_closed_on_error():
    tracker = {"created": 0, "rollbacks": 0, "closes": 0}
    ctrl = _make_controller(_tracking_factory(tracker))

    with pytest.raises(ValueError, match="boom"):
        async with ctrl._owned_session():
            raise ValueError("boom")

    assert tracker == {"created": 1, "rollbacks": 1, "closes": 1}


@pytest.mark.asyncio
async def test_owned_session_empty_factory_raises():
    async def empty():
        if False:
            yield None

    ctrl = _make_controller(empty)
    with pytest.raises(RuntimeError, match="yielded nothing"):
        async with ctrl._owned_session():
            pass  # pragma: no cover
