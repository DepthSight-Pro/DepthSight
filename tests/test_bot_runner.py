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
