# tests/test_db_session_guard.py
# ruff: noqa: E402
"""The guard that stops the abandoned-session defect from coming back.

`api.database.get_db` is an async generator, and taking a session out of it
without closing the generator leaves the `async with AsyncSessionLocal()`
suspended at its `yield`: the session keeps its pooled connection checked
out and its transaction OPEN until the garbage collector finalises it. At
fleet scale that starves the pooler - upstream measured ~120 pinned server
connections at 660 controllers.

The rule lives in `tools/db_session_guard.py`. It matches the SHAPE of the
acquisition, not the NAME of the factory, so renaming `get_db_session` to
`_db_session` - or binding it to another name first - cannot hide a leak,
and it covers both acquisition forms (`async for` over the generator, and
`await anext(gen)`).

These tests check the rule itself against synthetic sources, so a rule that
silently stops matching is caught here rather than at the next incident.

The four gaps the review panel raised are covered by:

* GAP 1 (SCOPE)  - `test_the_guard_scans_every_python_file_in_the_repo` and
  `test_the_guard_scans_the_repo_root_the_api_package_and_the_tools`.
* GAP 2 (SHAPE)  - the `anext` and assign-then-iterate tests, plus
  `test_the_rule_flags_an_inline_anext_acquisition` and
  `test_the_rule_does_not_let_a_close_in_another_function_hide_a_leak`.
* GAP 3 (NAMES)  - `test_the_rule_flags_a_renamed_factory`,
  `test_the_rule_flags_an_aliased_factory`,
  `test_the_rule_flags_an_aliased_generator` and
  `test_the_rule_flags_a_leak_whose_body_calls_no_session_method`.
* GAP 4 (SWALLOW) - `test_the_session_release_never_swallows_a_failure`.
"""

import ast
import os
from pathlib import Path

os.environ.setdefault("POSTGRES_USER", "testuser")
os.environ.setdefault("POSTGRES_PASSWORD", "testpassword")
os.environ.setdefault("POSTGRES_DB", "testdb")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from tools.db_session_guard import (  # noqa: E402
    ALLOWED,
    REPO,
    SKIP_DIR_NAMES,
    find_offenders,
    find_offenders_in_source,
    find_parse_failures,
    scanned_files,
)

# A leak written the way the code used to write it.
LEAK_ASYNC_FOR = """
async def handler(self):
    async for db in self.get_db_session():
        config = await crud.get_config(db, user_id=self.user_id)
        await db.commit()
"""

# The SAME leak with the factory renamed. The rule must not depend on the
# name - this is the GAP 3 mutant.
LEAK_RENAMED_FACTORY = """
async def handler(self):
    async for db in self._db_session():
        config = await crud.get_config(db, user_id=self.user_id)
        await db.commit()
"""

# The factory ALIASED to another name first.
LEAK_ALIASED_FACTORY = """
async def handler(self):
    factory = self._db_session
    async for db in factory():
        config = await crud.get_config(db, user_id=self.user_id)
"""

# The generator ALIASED to another name first.
LEAK_ALIASED_GENERATOR = """
async def handler(self):
    gen = self.get_db_session()
    alias = gen
    async for db in alias:
        config = await crud.get_config(db, user_id=self.user_id)
"""

# The assign-then-iterate form: the factory call is not in the `async for`.
LEAK_ASSIGN_THEN_ITERATE = """
async def handler(self):
    sessions = self.get_db_session()
    async for db in sessions:
        config = await crud.get_config(db, user_id=self.user_id)
"""

# A leak whose body never calls a session method. The rule must not depend
# on a list of session-method NAMES either.
LEAK_NO_SESSION_METHOD = """
async def handler(self):
    async for db in self.get_db_session():
        config = await crud.get_config(db, user_id=self.user_id)
"""

# The `anext` acquisition form, never closed.
LEAK_UNCLOSED_ANEXT = """
async def handler(self):
    db_gen = get_db()
    db = await anext(db_gen)
    config = await crud.get_config(db, user_id=self.user_id)
"""

# The `anext` acquisition form with the factory called inline. There is no
# name to close it by, so it is abandoned by construction.
LEAK_INLINE_ANEXT = """
async def handler(self):
    db = await anext(self.get_db_session())
    config = await crud.get_config(db, user_id=self.user_id)
"""

# The `anext` acquisition form, closed.
CLOSED_ANEXT = """
async def handler(self):
    db_gen = get_db()
    db = await anext(db_gen)
    try:
        config = await crud.get_config(db, user_id=self.user_id)
    finally:
        await db_gen.aclose()
"""

# A close in ANOTHER function must not hide a leak in this one. The module
# scope contains every function, so a whole-module search for `aclose()`
# masked the leak everywhere else in the file.
CLOSED_IN_ANOTHER_FUNCTION = """
async def helper(gen):
    await gen.aclose()

async def handler(self):
    db_gen = get_db()
    db = await anext(db_gen)
    config = await crud.get_config(db, user_id=self.user_id)
"""

# The correct shape.
OWNED_SESSION = """
async def handler(self):
    async with owned_session(self.get_db_session) as db:
        config = await crud.get_config(db, user_id=self.user_id)
"""

# The session method is called ON the loop variable (`await db.get(...)`),
# not passed to a call. The loop variable is the RECEIVER.
LEAK_RECEIVER_SESSION_METHOD = """
async def handler(self):
    async for db in self.get_db_session():
        row = await db.get(models.User, 1)
        break
"""

# `asend` hands the session out exactly like `anext` does.
LEAK_ASEND = """
async def handler(self):
    db_gen = get_db()
    db = await db_gen.asend(None)
    config = await crud.get_config(db, user_id=self.user_id)
"""

# The generator is held on the object, not on a local name.
LEAK_ATTRIBUTE_BOUND_GENERATOR = """
async def handler(self):
    self.db_gen = get_db()
    db = await self.db_gen.__anext__()
    config = await crud.get_config(db, user_id=self.user_id)
"""

# The walrus operator binds the generator.
LEAK_WALRUS = """
async def handler(self):
    if (db_gen := get_db()):
        db = await anext(db_gen)
        config = await crud.get_config(db, user_id=self.user_id)
"""

# The factory called WITH an argument. `self.get_db_session(user_id)` is
# still a session factory.
LEAK_FACTORY_WITH_ARGUMENT = """
async def handler(self, user_id):
    async for db in self.get_db_session(user_id):
        config = await crud.get_config(db, user_id=user_id)
"""

# A close that may never run closes nothing.
CLOSED_ONLY_CONDITIONALLY = """
async def handler(self):
    db_gen = get_db()
    db = await anext(db_gen)
    if ready:
        await db_gen.aclose()
    config = await crud.get_config(db, user_id=self.user_id)
"""

# The loop leaves early and never touches the session. The leak does not
# depend on the loop variable being used.
LEAK_EARLY_EXIT_UNUSED_VARIABLE = """
async def handler(self):
    async for db in self.get_db_session():
        break
"""

# The loop exhausts the generator: the generator resumes, its `async with`
# exits, and the connection goes back. Not a leak.
EXHAUSTS_THE_GENERATOR = """
async def handler(self):
    async for db in self.get_db_session():
        pass
"""

# The generator is held on the object and walked with `async for`.
LEAK_ATTRIBUTE_BOUND_ASYNC_FOR = """
async def handler(self):
    self.db_gen = get_db()
    async for db in self.db_gen:
        await crud.get_config(db, user_id=self.user_id)
"""

# A close in the body of a `try:` is skipped when the statement before it
# raises.
CLOSED_LATE_IN_A_TRY_BODY = """
async def handler(self):
    db_gen = get_db()
    db = await anext(db_gen)
    try:
        await something()
        await db_gen.aclose()
    except Exception:
        pass
"""

# A close BEFORE the acquisition closes nothing.
CLOSED_BEFORE_THE_ACQUISITION = """
async def handler(self):
    db_gen = get_db()
    await db_gen.aclose()
    db = await anext(db_gen)
    config = await crud.get_config(db, user_id=self.user_id)
"""

# The name is rebound before the close, so the close refers to a DIFFERENT
# generator than the one that was acquired.
CLOSED_A_DIFFERENT_GENERATOR = """
async def handler(self):
    gen = get_db()
    db = await anext(gen)
    gen = something_else()
    await gen.aclose()
    config = await crud.get_config(db, user_id=self.user_id)
"""

# A loop that has nothing to do with the database.
NOT_A_SESSION = """
async def handler(websocket):
    async for message in websocket:
        await websocket.send_json(message)
"""

# A loop over a call that takes arguments and is not a session factory.
# `redis.scan_iter(match=..., count=...)` is the shape this must NOT flag.
NOT_A_SESSION_WITH_ARGUMENTS = """
async def handler(self):
    async for k in self.redis_client.scan_iter(match="running:*", count=100):
        keys.append(k)
"""


def test_the_guard_finds_no_unowned_db_sessions():
    """The whole repo: no acquisition outside the documented leftovers.

    The assertion is `== ALLOWED`, not `not in ALLOWED`: a new offender must
    fail the test, and an allowlist entry that stops matching (because it
    was fixed) must fail it too, so the entry cannot go stale.
    """
    offenders = find_offenders()
    assert offenders, "the guard found nothing at all - it is not running"
    allowed_hits = {_key(o) for o in offenders if _key(o) in ALLOWED}
    unexpected = [o for o in offenders if _key(o) not in ALLOWED]
    assert unexpected == [], f"unowned DB sessions: {unexpected}"
    assert allowed_hits == set(ALLOWED), (
        "the allowlist is stale: "
        f"expected {sorted(ALLOWED)}, the guard matched {sorted(allowed_hits)}"
    )


def test_the_guard_scans_every_python_file_in_the_repo():
    """GAP 1: the scope is the whole repo, not one package.

    A guard that only scanned `bot_module/` would have been blind to the
    command listener in `bot_runner.py` - one of the largest leaks this fix
    closed - and blind to `api/`, where the session factory is defined.

    The expected set is built here, independently of the scanner, so
    narrowing the scanner's scope fails this test.
    """
    expected = set()
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        for name in filenames:
            if name.endswith(".py"):
                expected.add(Path(dirpath, name).resolve())

    scanned = {p.resolve() for p in scanned_files()}

    assert expected, "the repo has no Python files at all"
    assert scanned == expected, (
        "the guard's scope is not the whole repo: "
        f"missing {sorted(str(p) for p in expected - scanned)[:10]}, "
        f"extra {sorted(str(p) for p in scanned - expected)[:10]}"
    )


def test_the_guard_scans_the_repo_root_the_api_package_and_the_tools():
    """GAP 1: the named places the guard must not be blind to."""
    files = {p.relative_to(REPO).as_posix() for p in scanned_files()}
    for required in (
        "bot_runner.py",  # the repo root: the command listener
        "market_data_service.py",  # the repo root: another root module
        "tasks.py",
        "api/database.py",  # where the session factory is defined
        "api/routes/admin.py",
        "bot_module/controller.py",
        "bot_module/telegram_notifier.py",
        "tools/db_session_guard.py",
    ):
        assert required in files, f"{required} is not scanned"


def test_the_allowed_leftover_is_a_real_site():
    """Each allowlist entry must still point at a real line of a real file."""
    for (path, line), reason in ALLOWED.items():
        target = REPO / path
        assert target.is_file(), f"{path} does not exist"
        assert reason.strip(), f"{path}:{line} has no documented reason"
        lines = target.read_text(encoding="utf-8").splitlines()
        assert line <= len(lines), f"{path}:{line} is past the end of the file"


def test_the_rule_flags_an_async_for_over_a_session_factory():
    assert find_offenders_in_source(LEAK_ASYNC_FOR), "the rule missed a leak"


def test_the_rule_flags_a_renamed_factory():
    """GAP 3: the rule must be about the shape, not the name."""
    assert find_offenders_in_source(LEAK_RENAMED_FACTORY), (
        "the rule missed a leak after the factory was renamed"
    )


def test_the_rule_flags_an_aliased_factory():
    """GAP 3: a factory bound to another name is still the same shape."""
    assert find_offenders_in_source(LEAK_ALIASED_FACTORY), (
        "the rule missed a leak after the factory was aliased"
    )


def test_the_rule_flags_an_aliased_generator():
    """GAP 3: the generator bound to another name is still the same shape."""
    assert find_offenders_in_source(LEAK_ALIASED_GENERATOR), (
        "the rule missed a leak after the generator was aliased"
    )


def test_the_rule_flags_a_leak_whose_body_calls_no_session_method():
    """GAP 3: the rule must not depend on a list of session-method names.

    `await crud.get_config(db, ...)` alone is enough to make the loop
    variable a session. A rule that only knew `commit`/`execute`/`flush`
    would miss this leak.
    """
    assert find_offenders_in_source(LEAK_NO_SESSION_METHOD), (
        "the rule missed a leak whose body calls no session method"
    )


def test_the_rule_flags_the_assign_then_iterate_form():
    """GAP 2: the factory call is not in the `async for`."""
    assert find_offenders_in_source(LEAK_ASSIGN_THEN_ITERATE), (
        "the rule missed the assign-then-iterate form"
    )


def test_the_rule_flags_an_unclosed_anext_acquisition():
    """GAP 2: the `await anext(gen)` acquisition form."""
    assert find_offenders_in_source(LEAK_UNCLOSED_ANEXT), (
        "the rule missed an unclosed anext acquisition"
    )


def test_the_rule_flags_an_inline_anext_acquisition():
    """GAP 2: `await anext(factory())` has no name to close it by."""
    assert find_offenders_in_source(LEAK_INLINE_ANEXT), (
        "the rule missed an inline anext acquisition"
    )


def test_the_rule_does_not_let_a_close_in_another_function_hide_a_leak():
    """GAP 2: the close must be in the SAME function as the acquisition.

    The module scope contains every function in the file, so a whole-file
    search for `aclose()` used to mask an unclosed generator in a different
    function of the same file.
    """
    offenders = find_offenders_in_source(CLOSED_IN_ANOTHER_FUNCTION)
    assert len(offenders) == 1, offenders
    assert offenders[0].endswith(":7"), offenders


def test_the_rule_does_not_flag_a_closed_anext_acquisition():
    assert not find_offenders_in_source(CLOSED_ANEXT), (
        "the rule flagged a generator that IS closed"
    )


def test_the_rule_does_not_flag_an_owned_session():
    assert not find_offenders_in_source(OWNED_SESSION), (
        "the rule flagged the correct `owned_session` shape"
    )


def test_the_rule_does_not_flag_a_loop_that_is_not_a_session():
    assert not find_offenders_in_source(NOT_A_SESSION), (
        "the rule flagged a websocket loop"
    )


def test_the_rule_does_not_flag_a_loop_over_a_call_with_arguments():
    """`redis.scan_iter(match=..., count=...)` is not a session factory."""
    assert not find_offenders_in_source(NOT_A_SESSION_WITH_ARGUMENTS), (
        "the rule flagged a redis scan loop"
    )


def test_the_rule_flags_a_session_method_called_on_the_loop_variable():
    """`await db.get(...)` - the loop variable is the RECEIVER."""
    assert find_offenders_in_source(LEAK_RECEIVER_SESSION_METHOD), (
        "the rule missed a leak whose only session use is a method call"
    )


def test_the_rule_flags_an_asend_acquisition():
    """`asend` hands the session out exactly like `anext`."""
    assert find_offenders_in_source(LEAK_ASEND), (
        "the rule missed an unclosed asend acquisition"
    )


def test_the_rule_flags_an_attribute_bound_generator():
    """`await self.db_gen.__anext__()` - the generator is on the object."""
    assert find_offenders_in_source(LEAK_ATTRIBUTE_BOUND_GENERATOR), (
        "the rule missed an unclosed attribute-bound generator"
    )


def test_the_rule_flags_a_walrus_bound_generator():
    """`if (db_gen := get_db()):` binds the generator."""
    assert find_offenders_in_source(LEAK_WALRUS), (
        "the rule missed an unclosed walrus-bound generator"
    )


def test_the_rule_flags_a_factory_called_with_an_argument():
    """`self.get_db_session(user_id)` is still a session factory."""
    assert find_offenders_in_source(LEAK_FACTORY_WITH_ARGUMENT), (
        "the rule missed a leak from a factory called with an argument"
    )


def test_the_rule_does_not_let_a_conditional_close_hide_a_leak():
    """A close that may never run closes nothing.

    `if ready: await gen.aclose()` does not close the generator on the path
    that leaks, so the acquisition is still an acquisition with no release.
    """
    offenders = find_offenders_in_source(CLOSED_ONLY_CONDITIONALLY)
    assert len(offenders) == 1, offenders
    assert offenders[0].endswith(":4"), offenders


def test_the_rule_flags_a_loop_that_leaves_early():
    """The leak does not depend on the loop variable being used.

    `async for db in factory(): break` abandons the generator with `db`
    never touched.
    """
    assert find_offenders_in_source(LEAK_EARLY_EXIT_UNUSED_VARIABLE), (
        "the rule missed a loop that leaves early"
    )


def test_the_rule_does_not_flag_a_loop_that_exhausts_the_generator():
    """A body that exhausts the generator releases the connection."""
    assert not find_offenders_in_source(EXHAUSTS_THE_GENERATOR), (
        "the rule flagged a loop that exhausts the generator"
    )


def test_the_rule_flags_an_attribute_bound_generator_in_an_async_for():
    """`async for db in self.db_gen:` - the generator is on the object."""
    assert find_offenders_in_source(LEAK_ATTRIBUTE_BOUND_ASYNC_FOR), (
        "the rule missed an attribute-bound generator walked with async for"
    )


def test_the_rule_does_not_let_a_late_close_in_a_try_body_hide_a_leak():
    """A close in a try body is skipped when the statement before it raises."""
    offenders = find_offenders_in_source(CLOSED_LATE_IN_A_TRY_BODY)
    assert len(offenders) == 1, offenders


def test_the_rule_does_not_let_a_close_before_the_acquisition_hide_a_leak():
    """A close before the acquisition closes nothing."""
    offenders = find_offenders_in_source(CLOSED_BEFORE_THE_ACQUISITION)
    assert len(offenders) == 1, offenders


def test_the_rule_does_not_let_a_close_of_another_generator_hide_a_leak():
    """The name is rebound, so the close refers to a different generator."""
    offenders = find_offenders_in_source(CLOSED_A_DIFFERENT_GENERATOR)
    assert len(offenders) == 1, offenders


def test_the_guard_reports_files_it_cannot_parse(tmp_path):
    """A guard that silently skips a file it cannot read always reports OK."""
    broken = tmp_path / "broken.py"
    broken.write_text("def oops(:\n", encoding="utf-8")

    failures = find_parse_failures(tmp_path)
    assert len(failures) == 1, failures
    assert "broken.py" in failures[0], failures

    # And the repo itself must be fully readable.
    assert find_parse_failures() == [], (
        f"the guard could not read: {find_parse_failures()}"
    )


def test_the_session_release_never_swallows_a_failure():
    """GAP 4: a swallowed close failure is worse than no close attempt.

    `owned_session` closes the generator and the session in a `finally`.
    If either close raises and the failure is swallowed, the pooled
    connection stays checked out and NOTHING says so - which is the exact
    failure this whole change exists to prevent. So every handler in
    `bot_module/db_session.py` must log with `logger.exception`.
    """
    path = REPO / "bot_module" / "db_session.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "db_session.py has no exception handler at all"

    for handler in handlers:
        assert not (
            len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass)
        ), "a rollback/close failure is swallowed with `except ...: pass`"

    assert "except Exception: pass" not in source
    assert "logger.exception" in source, (
        "the rollback/close failure must be logged with logger.exception, "
        "not swallowed and not downgraded to a debug line"
    )


def _key(offender: str):
    path, _, line = offender.rpartition(":")
    return path, int(line)
