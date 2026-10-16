from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import json

import pytest

import bot_runner


def test_plan_allows_live_trading_matches_plan_config():
    assert bot_runner._plan_allows_live_trading("standard") is True
    assert bot_runner._plan_allows_live_trading("pro") is True
    assert bot_runner._plan_allows_live_trading("free") is False
    assert bot_runner._plan_allows_live_trading("researcher") is False


def test_api_key_is_sharded_by_api_key_id():
    user_id = 42

    assert user_id % 2 == 0
    assert bot_runner._api_key_belongs_to_shard(1, shard_id=1, num_workers=2) is True
    assert bot_runner._api_key_belongs_to_shard(2, shard_id=1, num_workers=2) is False


@pytest.mark.asyncio
async def test_initialize_user_controllers_uses_api_key_sharding(mocker):
    user = SimpleNamespace(id=42, username="live_user", plan="standard")
    active_keys = [
        SimpleNamespace(id=1, name="key-1"),
        SimpleNamespace(id=2, name="key-2"),
        SimpleNamespace(id=3, name="key-3"),
    ]

    mocker.patch.object(
        bot_runner.crud,
        "get_active_api_keys_for_user",
        AsyncMock(return_value=active_keys),
    )
    initialize_controller = mocker.patch.object(
        bot_runner, "_initialize_controller_for_key", AsyncMock()
    )

    await bot_runner._initialize_user_controllers(
        user,
        db=MagicMock(),
        session=object(),
        redis_client=object(),
        telegram_notifier_instance=None,
        shard_id=1,
        num_workers=2,
    )

    initialized_api_key_ids = [
        call.args[1].id for call in initialize_controller.await_args_list
    ]
    assert initialized_api_key_ids == [1, 3]


@pytest.mark.asyncio
async def test_initialize_user_controllers_skips_non_live_plans(mocker):
    user = SimpleNamespace(id=7, username="research_only", plan="researcher")

    get_active_keys = mocker.patch.object(
        bot_runner.crud, "get_active_api_keys_for_user", AsyncMock()
    )
    initialize_controller = mocker.patch.object(
        bot_runner, "_initialize_controller_for_key", AsyncMock()
    )

    await bot_runner._initialize_user_controllers(
        user,
        db=MagicMock(),
        session=object(),
        redis_client=object(),
        telegram_notifier_instance=None,
        shard_id=0,
        num_workers=4,
    )

    get_active_keys.assert_not_awaited()
    initialize_controller.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_strategy_runtime_state_publishes_empty_snapshot():
    redis_client = AsyncMock()

    await bot_runner._clear_strategy_runtime_state(
        redis_client, user_id=15, api_key_id=4
    )

    redis_client.set.assert_awaited_once_with(
        "depthsight:state:strategies:15:4",
        "[]",
    )
    redis_client.publish.assert_awaited_once_with(
        "depthsight:events:strategies:15",
        json.dumps({"user_id": 15}),
    )


def test_notification_channel_matches_bot_command_channel():
    """API must publish to the channel the bot subscribes to.

    Regression: notifications.py/users.py used a hardcoded "bot_commands"
    default while the bot listens on bot_module.config.REDIS_COMMAND_CHANNEL
    ("depthsight:commands"), silently dropping TEST_NOTIFICATION/RELOAD_CONFIG.
    """
    from bot_module import config as bot_config
    from api.routes import notifications as notifications_route
    from api.routes import users as users_route

    assert notifications_route.REDIS_COMMAND_CHANNEL == bot_config.REDIS_COMMAND_CHANNEL
    assert users_route.REDIS_COMMAND_CHANNEL == bot_config.REDIS_COMMAND_CHANNEL


def _make_command_pubsub(messages):
    """Fake redis pubsub yielding `messages`, then ending the listener loop."""
    import asyncio

    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.get_message = AsyncMock(side_effect=[*messages, asyncio.CancelledError()])
    redis_client = MagicMock()
    redis_client.pubsub.return_value = pubsub
    return redis_client


def _test_notification_message(user_id=7, chat_id="12345"):
    return {
        "type": "message",
        "data": json.dumps(
            {
                "command": "TEST_NOTIFICATION",
                "payload": {"user_id": user_id, "chat_id": chat_id},
            }
        ),
    }


@pytest.mark.asyncio
async def test_command_listener_sends_test_notification_once_on_shard_0():
    import asyncio

    notifier = MagicMock()
    notifier.send_test_message = AsyncMock()
    redis_client = _make_command_pubsub([_test_notification_message()])

    await bot_runner._run_command_listener(
        MagicMock(),
        object(),
        redis_client,
        telegram_notifier_instance=notifier,
        shard_id=0,
        num_workers=1,
    )
    await asyncio.sleep(0.05)

    notifier.send_test_message.assert_awaited_once_with(chat_id="12345")


@pytest.mark.asyncio
async def test_command_listener_skips_test_notification_on_other_shards():
    import asyncio

    notifier = MagicMock()
    notifier.send_test_message = AsyncMock()
    redis_client = _make_command_pubsub([_test_notification_message()])

    await bot_runner._run_command_listener(
        MagicMock(),
        object(),
        redis_client,
        telegram_notifier_instance=notifier,
        shard_id=1,
        num_workers=2,
    )
    await asyncio.sleep(0.05)

    notifier.send_test_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_command_listener_test_notification_without_notifier_does_not_raise():
    redis_client = _make_command_pubsub([_test_notification_message()])

    await bot_runner._run_command_listener(
        MagicMock(),
        object(),
        redis_client,
        telegram_notifier_instance=None,
        shard_id=0,
        num_workers=1,
    )


@pytest.mark.asyncio
async def test_command_listener_test_notification_send_failure_does_not_raise():
    """A Telegram send failure must be logged, not crash the listener loop."""
    import asyncio

    notifier = MagicMock()
    notifier.send_test_message = AsyncMock(side_effect=Exception("tg down"))
    redis_client = _make_command_pubsub([_test_notification_message()])

    await bot_runner._run_command_listener(
        MagicMock(),
        object(),
        redis_client,
        telegram_notifier_instance=notifier,
        shard_id=0,
        num_workers=1,
    )
    await asyncio.sleep(0.05)

    notifier.send_test_message.assert_awaited_once_with(chat_id="12345")


@pytest.mark.asyncio
async def test_every_controller_receives_its_own_non_null_db_session(mocker):
    """Regression: one session was shared by every controller on a shard.

    Concurrent controllers on one AsyncSession raised "Session is already
    flushing", which silently zeroed paper balances and rejected every signal.
    Each controller must now be built on a distinct, non-None session, and the
    backing generators must be retained so the session is not closed under the
    running bot.
    """
    sessions = []

    async def fake_get_db():
        # get_db is a plain async generator function (not @asynccontextmanager),
        # so bot_runner drives it with anext() and keeps the generator alive.
        session = SimpleNamespace(tag=len(sessions))
        sessions.append(session)
        yield session

    mocker.patch.object(bot_runner, "get_db", fake_get_db)
    init_controller = mocker.patch.object(
        bot_runner, "_initialize_controller_for_key", AsyncMock(return_value=True)
    )

    bot_runner._controller_session_gens.clear()
    user = SimpleNamespace(id=42, username="u", plan="standard")
    for key_id in (1, 2, 3):
        await bot_runner._init_controller_with_own_session(
            user,
            SimpleNamespace(id=key_id),
            object(),
            object(),
            None,
        )

    handed_out = [call.args[2] for call in init_controller.await_args_list]
    assert len(handed_out) == 3
    assert all(s is not None for s in handed_out)
    assert len({id(s) for s in handed_out}) == 3, "sessions must not be shared"
    assert len(bot_runner._controller_session_gens) == 3, (
        "generators must be retained for the process lifetime"
    )
    bot_runner._controller_session_gens.clear()


@pytest.mark.asyncio
async def test_command_listener_activate_api_key_uses_its_db_session(mocker):
    """ACTIVATE_API_KEY must dereference a real session, not None.

    Regression: the session variable was renamed during the per-controller session
    refactor, which left the command listener being handed a stale None. Because
    the listener swallows per-command exceptions, every dynamic key activation
    would have failed silently on db.expire_all().
    """
    import asyncio

    db_session = MagicMock()
    db_session.expire_all = MagicMock()

    message = {
        "type": "message",
        "data": json.dumps(
            {
                "command": "ACTIVATE_API_KEY",
                "payload": {"user_id": 7, "api_key_id": 4},
            }
        ),
    }
    redis_client = _make_command_pubsub([message])

    mocker.patch.object(bot_runner.crud, "get_user_by_id", AsyncMock(return_value=None))

    await bot_runner._run_command_listener(
        db_session,
        object(),
        redis_client,
        telegram_notifier_instance=None,
        shard_id=0,
        num_workers=1,
    )
    await asyncio.sleep(0.05)

    db_session.expire_all.assert_called_once_with()
    bot_runner.crud.get_user_by_id.assert_awaited_once_with(db_session, user_id=7)


@pytest.mark.asyncio
async def test_pool_telemetry_once_logs_pool_state():
    """Single telemetry sample must emit pool counters without a DB roundtrip."""
    import logging

    messages = []

    class _Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    handler = _Capture()
    bot_runner.logger.addHandler(handler)
    try:
        await bot_runner._log_pool_telemetry_once(shard_id=0)
    finally:
        bot_runner.logger.removeHandler(handler)
    assert any(
        "[PoolTelemetry]" in m
        and "checkedout=" in m
        and "controllers=" in m
        and "tasks_top=" in m
        for m in messages
    )


@pytest.mark.asyncio
async def test_initialize_controller_releases_bootstrap_pin(mocker):
    """Regression (A14): the first read on a controller session checks out a
    pool connection that reads never return, pinning ~1 conn per controller
    until the fleet silently exhausts the pool (~340 controllers on 350).
    Successful init must end with a release commit on that session."""
    mocker.patch.object(
        bot_runner.security, "decrypt_data", MagicMock(return_value="x")
    )
    mocker.patch.object(
        bot_runner, "create_exchange_executor", MagicMock(return_value=MagicMock())
    )
    mocker.patch.object(bot_runner, "DataConsumer", MagicMock(return_value=MagicMock()))
    paper = MagicMock()
    paper.initialize_equity_tracking = AsyncMock()
    mocker.patch.object(
        bot_runner, "PaperTradingExecutor", MagicMock(return_value=paper)
    )
    cfg = MagicMock()
    cfg.model_dump = MagicMock(return_value={})
    mocker.patch.object(bot_runner.crud, "get_config", AsyncMock(return_value=cfg))
    rm = MagicMock()
    rm.initialize = AsyncMock()
    mocker.patch.object(bot_runner, "RiskManager", MagicMock(return_value=rm))
    started_controller = MagicMock()
    started_controller.start = AsyncMock()
    mocker.patch.object(
        bot_runner, "TradingController", MagicMock(return_value=started_controller)
    )
    mocker.patch.object(bot_runner, "user_controllers", {})

    db = AsyncMock()
    user = SimpleNamespace(id=7, username="pin_user")
    key = SimpleNamespace(
        id=9,
        name="k",
        exchange="binance",
        encrypted_api_key="ek",
        encrypted_api_secret="es",
    )
    ok = await bot_runner._initialize_controller_for_key(
        user, key, db, object(), object(), None
    )
    assert ok is True
    db.commit.assert_awaited_once()


def test_worker_main_installs_loadtest_shim(mocker):
    """Spawned workers start a fresh interpreter without the parent's patches.

    Without per-worker shim install, no worker (including shard 0's, since the
    parent only spawns and waits) would have the synthetic live balance and
    every signal would be rejected with RISK_BLOCK.
    """
    installed = []
    fake_shim = SimpleNamespace(install=lambda: installed.append(True))
    mocker.patch.dict("sys.modules", {"loadtest_live_balance_shim": fake_shim})
    mocker.patch.object(bot_runner.asyncio, "run", MagicMock())
    bot_runner.worker_main(2, 4)
    assert installed == [True]
    bot_runner.asyncio.run.assert_called_once()


def _dead_worker(pid):
    p = MagicMock()
    p.is_alive = MagicMock(return_value=False)
    p.exitcode = 1
    p.pid = pid
    return p


def test_run_multi_process_exits_nonzero_when_all_dead(mocker):
    """A master that outlives all children must fail loudly (Exited 1), not
    idle as a look-healthy container with zero output."""
    mocker.patch.object(
        bot_runner.multiprocessing,
        "Process",
        MagicMock(side_effect=[_dead_worker(101), _dead_worker(102)]),
    )
    mocker.patch.object(bot_runner.multiprocessing, "set_start_method", MagicMock())
    mocker.patch.object(
        bot_runner,
        "shutdown_event",
        SimpleNamespace(is_set=MagicMock(return_value=False)),
    )
    mocker.patch("time.sleep", MagicMock())
    assert bot_runner._run_multi_process(2) == 1


def test_run_multi_process_zero_on_clean_shutdown(mocker):
    alive = MagicMock()
    alive.is_alive = MagicMock(return_value=True)
    alive.exitcode = None
    alive.pid = 1111
    mocker.patch.object(
        bot_runner.multiprocessing, "Process", MagicMock(return_value=alive)
    )
    mocker.patch.object(bot_runner.multiprocessing, "set_start_method", MagicMock())
    state = {"stop": False}

    def _is_set():
        if state["stop"]:
            return True
        state["stop"] = True
        return False

    mocker.patch.object(
        bot_runner,
        "shutdown_event",
        SimpleNamespace(is_set=MagicMock(side_effect=_is_set)),
    )
    mocker.patch("time.sleep", MagicMock())
    assert bot_runner._run_multi_process(1) == 0


@pytest.mark.asyncio
async def test_pool_telemetry_appends_csv_when_configured(tmp_path, monkeypatch):
    """POOL_TELEMETRY_PATH must receive one CSV line per sample (survives log
    rotation, unlike the bot log)."""
    target = tmp_path / "pool_telemetry.csv"
    monkeypatch.setenv("POOL_TELEMETRY_PATH", str(target))
    await bot_runner._log_pool_telemetry_once(shard_id=2)
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parts = lines[0].split(",")
    assert parts[1] == "2"
    assert len(parts) == 9


@pytest.mark.asyncio
async def test_pool_telemetry_skips_file_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("POOL_TELEMETRY_PATH", raising=False)
    before = set(p.name for p in tmp_path.iterdir())
    monkeypatch.chdir(tmp_path)
    await bot_runner._log_pool_telemetry_once(shard_id=0)
    assert set(p.name for p in tmp_path.iterdir()) == before
