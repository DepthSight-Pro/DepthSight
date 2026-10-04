"""Regression: plans config must not hit DB/disk per strategy start (B15).

`load_from_db()` is called on every POST /api/v1/strategies. It used to cost
a SELECT plus a YAML re-parse and a file rewrite each time (~58 ms, API at
100% CPU on ramps, concurrent rewrites racing each other). Now the in-memory
copy is trusted for a TTL and the request path never writes the YAML file.
"""

import os

import pytest
from sqlalchemy import event

from api import models
from api.plans import plans_config
from tests.conftest import test_engine


def _seed_override(db_session, plans_payload):
    setting = models.SystemSetting(
        key="plans_config",
        value=plans_payload,
        description="test override",
    )
    return setting


@pytest.mark.asyncio
async def test_load_from_db_cached_within_ttl(db_session):
    db_session.add(
        _seed_override(db_session, {"plans": {"free": {"limits": {}}}}),
    )
    await db_session.commit()

    hits = []

    def count_system_settings(
        conn, cursor, statement, parameters, context, executemany
    ):
        # SELECTs only: the first load also backfills merged defaults via UPDATE.
        if "system_settings" in statement and statement.lstrip().upper().startswith(
            "SELECT"
        ):
            hits.append(1)

    event.listen(
        test_engine.sync_engine, "before_cursor_execute", count_system_settings
    )
    try:
        assert await plans_config.load_from_db(db_session) is True
        assert await plans_config.load_from_db(db_session) is True
        assert await plans_config.load_from_db(db_session) is True
    finally:
        event.remove(
            test_engine.sync_engine, "before_cursor_execute", count_system_settings
        )

    assert len(hits) == 1, f"expected 1 system_settings SELECT, got {len(hits)}"


@pytest.mark.asyncio
async def test_load_from_db_forced_refresh(db_session):
    db_session.add(
        _seed_override(db_session, {"plans": {"free": {"limits": {}}}}),
    )
    await db_session.commit()

    hits = []

    def count_system_settings(
        conn, cursor, statement, parameters, context, executemany
    ):
        # SELECTs only: the first load also backfills merged defaults via UPDATE.
        if "system_settings" in statement and statement.lstrip().upper().startswith(
            "SELECT"
        ):
            hits.append(1)

    event.listen(
        test_engine.sync_engine, "before_cursor_execute", count_system_settings
    )
    try:
        assert await plans_config.load_from_db(db_session) is True
        assert await plans_config.load_from_db(db_session, max_age_seconds=0) is True
    finally:
        event.remove(
            test_engine.sync_engine, "before_cursor_execute", count_system_settings
        )

    assert len(hits) == 2, f"expected 2 system_settings SELECTs, got {len(hits)}"


@pytest.mark.asyncio
async def test_load_from_db_does_not_rewrite_yaml(db_session):
    db_session.add(
        _seed_override(db_session, {"plans": {"free": {"limits": {}}}}),
    )
    await db_session.commit()

    mtime_before = os.stat(plans_config._config_path).st_mtime_ns
    assert await plans_config.load_from_db(db_session) is True
    mtime_after = os.stat(plans_config._config_path).st_mtime_ns
    assert mtime_before == mtime_after, "request-path load must not rewrite the YAML"
