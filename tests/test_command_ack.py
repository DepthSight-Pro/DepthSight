"""Regression: START_STRATEGY command acknowledgement (A2 fix).

Pub/sub has no replay, so a START_STRATEGY published while the target
controller is still booting was silently dropped while the API answered 202.
Now every command carries a command_id, the applying side publishes an ack,
and the API waits for it: a missing ack means "not applied, retry".
"""

import asyncio
import json

import pytest

from bot_module import config
from bot_module.redis_handler import publish_command_ack


class FakeRedis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, message):
        self.published.append((channel, message))
        return 1


@pytest.mark.asyncio
async def test_ack_is_noop_without_command_id_or_client():
    client = FakeRedis()
    await publish_command_ack(None, "abc")
    await publish_command_ack(client, None)
    await publish_command_ack(client, "")
    assert client.published == []


@pytest.mark.asyncio
async def test_ack_published_to_ack_channel_with_status():
    client = FakeRedis()
    await publish_command_ack(client, "cmd-1", status="ok", detail="already_active")
    assert len(client.published) == 1
    channel, message = client.published[0]
    assert channel == config.REDIS_COMMAND_ACK_CHANNEL
    payload = json.loads(message)
    assert payload == {
        "command_id": "cmd-1",
        "status": "ok",
        "detail": "already_active",
    }


@pytest.mark.asyncio
async def test_ack_never_raises():
    class Broken:
        async def publish(self, *a, **k):
            raise OSError("redis down")

    # Must not break the command it reports on.
    await publish_command_ack(Broken(), "cmd-1", status="ok")


class FakePubSub:
    """Minimal stand-in for a redis pubsub subscription."""

    def __init__(self, messages):
        self._messages = list(messages)

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        if self._messages:
            return self._messages.pop(0)
        await asyncio.sleep(min(timeout, 0.01))
        return None


def _msg(command_id, status="ok", detail=None):
    return {
        "type": "message",
        "data": json.dumps(
            {"command_id": command_id, "status": status, "detail": detail}
        ),
    }


@pytest.mark.asyncio
async def test_wait_returns_confirmed_on_matching_ok():
    from api.routes.strategies import _wait_for_command_ack

    pubsub = FakePubSub([_msg("cmd-1", status="ok", detail="started")])
    confirmed, detail = await _wait_for_command_ack(pubsub, "cmd-1", 5)
    assert confirmed is True
    assert detail == "started"


@pytest.mark.asyncio
async def test_wait_skips_foreign_ids_and_garbage():
    from api.routes.strategies import _wait_for_command_ack

    pubsub = FakePubSub(
        [
            _msg("someone-else", status="ok"),
            {"type": "message", "data": "not-json{"},
            _msg("cmd-1", status="ok"),
        ]
    )
    confirmed, _ = await _wait_for_command_ack(pubsub, "cmd-1", 5)
    assert confirmed is True


@pytest.mark.asyncio
async def test_wait_reports_bot_error_status():
    from api.routes.strategies import _wait_for_command_ack

    pubsub = FakePubSub([_msg("cmd-1", status="error", detail="not_found")])
    confirmed, detail = await _wait_for_command_ack(pubsub, "cmd-1", 5)
    assert confirmed is False
    assert detail == "not_found"


@pytest.mark.asyncio
async def test_wait_timeout_is_not_an_error():
    from api.routes.strategies import _wait_for_command_ack

    pubsub = FakePubSub([])
    confirmed, detail = await _wait_for_command_ack(pubsub, "cmd-1", 1)
    assert confirmed is False
    assert "timeout" in detail


@pytest.mark.asyncio
async def test_seed_uses_confirmed_without_polling(monkeypatch):
    """A confirmed START needs no state polling (the fast path)."""
    from scripts import loadtest_seed_fleet as seed

    monkeypatch.setattr(seed, "mint_access_token", lambda username: "tok")

    calls = {"posts": 0, "polls": 0}

    class Resp:
        status_code = 202

        def json(self):
            return {"data": {"id": "cfg-1", "confirmed": True}}

    def fail_if_polled(*a, **k):
        calls["polls"] += 1
        raise AssertionError("_strategy_is_running must not be polled when confirmed")

    monkeypatch.setattr(seed, "_strategy_is_running", fail_if_polled)

    # Pre-seed key/config so provision_user reaches the start call: drive it
    # with a client whose key/config endpoints succeed.
    class FullClient:
        def post(self, url, json=None, headers=None, timeout=None):
            calls["posts"] += 1

            class R:
                status_code = 200

                def json(inner_self):
                    if url.endswith("api-keys"):
                        return {"data": {"id": 7}}
                    if url.endswith("strategies/config"):
                        return {"data": {"id": "cfg-1"}}
                    return {"data": {"id": "cfg-1", "confirmed": True}}

            return R()

    row = seed.provision_user(
        FullClient(),
        "http://x",
        "loadtest_0001",
        {"strategy_name": "VisualBuilderStrategy"},
        "BTCUSDT",
        key_id=7,
    )
    assert row["start"] == "ok(ack)"
    assert calls["polls"] == 0
