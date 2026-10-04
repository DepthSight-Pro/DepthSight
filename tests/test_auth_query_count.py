"""Regression: auth must not fan out into per-relationship queries (B1).

`get_user_by_username` runs on every authenticated request. The User model used
to declare six relationships lazy="selectin", so one auth emitted 7 queries
for collections the caller usually never touches. This test pins the query
count of the bare auth lookup.
"""

import pytest
from sqlalchemy import event

from api import crud
from tests.conftest import test_engine


@pytest.mark.asyncio
async def test_get_user_by_username_emits_single_query(db_session, test_user):
    queries = []

    def count_before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        queries.append(statement.split()[0])

    event.listen(
        test_engine.sync_engine, "before_cursor_execute", count_before_cursor_execute
    )
    try:
        user = await crud.get_user_by_username(db_session, test_user.username)
    finally:
        event.remove(
            test_engine.sync_engine,
            "before_cursor_execute",
            count_before_cursor_execute,
        )

    assert user is not None
    assert user.id == test_user.id
    selects = [q for q in queries if q.upper() == "SELECT"]
    assert selects == ["SELECT"], (
        f"auth lookup must be a single SELECT, got {len(selects)}: {selects}"
    )
