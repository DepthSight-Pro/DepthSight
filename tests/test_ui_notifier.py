# tests/test_ui_notifier.py
"""Unit tests for bot_module.ui_notifier (in-app / push mirror). Pure builders,
settings gating and the transparent TelegramNotifier proxy. No real Redis/DB."""

import asyncio
import json

from bot_module import ui_notifier


class FakeRedis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, message):
        self.published.append((channel, message))
        return 1


class FailingRedis:
    async def publish(self, channel, message):
        raise ConnectionError("redis down")


class FakeInner:
    def __init__(self):
        self.calls = []

    async def new_position(self, *args, **kwargs):
        self.calls.append(("new_position", args, kwargs))
        return "ok"

    async def bot_error(self, *args, **kwargs):
        self.calls.append(("bot_error", args, kwargs))
        return "ok"


def _ctx(redis, settings=None):
    return {
        "get_user_id": lambda: 42,
        "get_api_key_id": lambda: 7,
        "get_api_key_name": lambda: "main",
        "get_redis": lambda: redis,
        "get_loop": lambda: asyncio.get_running_loop(),
        "get_settings": lambda: settings or {},
        "resolve_push_subscription": None,
    }


async def test_position_opened_payload_contract():
    redis = FakeRedis()
    payload = await ui_notifier.emit_position_opened(
        redis,
        user_id=42,
        api_key_id=7,
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=67432.5,
        quantity=0.05,
        base_asset="BTC",
        stop_loss=66800.0,
        take_profit=69000.0,
        strategy="trend",
        client_order_id="cid-1",
        market_type="futures_usdtm",
        leverage=10,
    )
    assert payload is not None
    assert set(payload) == {
        "id",
        "type",
        "severity",
        "title",
        "body",
        "symbol",
        "side",
        "ts_ms",
        "user_id",
        "api_key_id",
        "tag",
        "data",
    }
    assert payload["type"] == "position_opened"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["side"] == "LONG"
    assert "67432.5" in payload["title"]
    assert len(redis.published) == 1
    channel, raw = redis.published[0]
    assert channel == "user:42:notifications"
    assert json.loads(raw)["id"] == payload["id"]


async def test_position_closed_severity_by_pnl_sign():
    redis = FakeRedis()
    base = dict(
        user_id=1,
        symbol="ETHUSDT",
        direction="SHORT",
        entry_price=3000.0,
        exit_price=2900.0,
        quote_asset="USDT",
        exit_reason="TAKE_PROFIT",
        closed_quantity=1.0,
        initial_quantity=1.0,
        base_asset="ETH",
        duration_seconds=3661,
        entry_client_order_id="e1",
    )
    profit = await ui_notifier.emit_position_closed(redis, pnl=100.0, **base)
    loss = await ui_notifier.emit_position_closed(redis, pnl=-50.0, **base)
    assert profit["severity"] == "success"
    assert loss["severity"] == "error"
    assert "1h 1m" in profit["body"]


async def test_same_toggles_suppress_delivery():
    redis = FakeRedis()
    payload = await ui_notifier.emit_position_opened(
        redis,
        user_id=1,
        symbol="BTCUSDT",
        notification_settings={"notifyNewPosition": False},
    )
    assert payload is None
    assert redis.published == []
    # Missing settings default to allowed (backward compatible).
    payload = await ui_notifier.emit_position_opened(redis, user_id=1, symbol="BTCUSDT")
    assert payload is not None


async def test_transport_never_raises():
    payload = await ui_notifier.emit_bot_error(
        FailingRedis(), user_id=1, error_description="boom"
    )
    assert payload is not None
    assert payload["type"] == "bot_error"
    payload = await ui_notifier.emit_bot_error(
        None, user_id=1, error_description="boom"
    )
    assert payload is not None


async def test_proxy_forwards_and_mirrors():
    redis = FakeRedis()
    inner = FakeInner()
    proxy = ui_notifier.wrap_telegram_notifier(inner, **_ctx(redis))
    assert bool(proxy)
    result = await proxy.new_position(
        symbol="BTCUSDT", direction="LONG", entry_price=1.0, client_order_id="c1"
    )
    assert result == "ok"
    assert inner.calls and inner.calls[0][0] == "new_position"
    await asyncio.sleep(0.05)  # let the mirror task run
    assert len(redis.published) == 1
    payload = json.loads(redis.published[0][1])
    assert payload["type"] == "position_opened"
    assert payload["user_id"] == 42
    assert payload["api_key_id"] == 7


async def test_proxy_bot_error_mirror_and_suppression():
    redis = FakeRedis()
    inner = FakeInner()
    proxy = ui_notifier.wrap_telegram_notifier(
        inner, **_ctx(redis, settings={"notifyBotErrors": False})
    )
    await proxy.bot_error(error_description="disk full", module_function="db")
    await asyncio.sleep(0.05)
    assert inner.calls and inner.calls[0][0] == "bot_error"  # telegram unaffected
    assert redis.published == []  # UI suppressed by the same toggle


async def test_wrap_none_and_idempotent():
    assert ui_notifier.wrap_telegram_notifier(None, get_user_id=lambda: 1) is None
    inner = FakeInner()
    once = ui_notifier.wrap_telegram_notifier(inner, get_user_id=lambda: 1)
    assert ui_notifier.wrap_telegram_notifier(once, get_user_id=lambda: 1) is once
    assert once.new_position  # transparent attribute access works


def test_is_allowed_matrix():
    assert ui_notifier.is_allowed("NEW_POSITION", None)
    assert ui_notifier.is_allowed("NEW_POSITION", {})
    assert not ui_notifier.is_allowed("NEW_POSITION", {"notifyNewPosition": False})
    assert (
        ui_notifier.is_allowed("position_opened", {"notifyNewPosition": False}) is False
    )
    assert ui_notifier.is_allowed("HFT_INFO", {"notifyNewPosition": False})
    assert ui_notifier.is_allowed("UNKNOWN_FUTURE_EVENT", {})


def test_normalize_settings_variants():
    assert ui_notifier.normalize_settings(None) == {}
    assert ui_notifier.normalize_settings({"a": 1}) == {"a": 1}
    assert ui_notifier.normalize_settings('{"notifyNewPosition": false}') == {
        "notifyNewPosition": False
    }
    assert ui_notifier.normalize_settings("not-json") == {}


async def test_hft_subtypes_map_to_ui_types():
    redis = FakeRedis()
    sig = await ui_notifier.emit_hft(
        redis,
        user_id=1,
        subtype="signal",
        event_data={"symbol": "BTCUSDT", "side": "LONG", "price": 67000.0, "prob": 0.8},
    )
    assert sig["type"] == "hft_signal"
    trade = await ui_notifier.emit_hft(
        redis,
        user_id=1,
        subtype="trade",
        event_data={
            "symbol": "BTCUSDT",
            "side": "SHORT",
            "price": 67000.0,
            "qty": 0.1,
            "realized_pnl": 12.5,
        },
    )
    assert trade["type"] == "hft_closed"
    assert trade["severity"] == "success"
    assert await ui_notifier.emit_hft(redis, user_id=1, subtype="weird") is None


async def test_proxy_binds_positional_args():
    """Call sites may pass error_description positionally; mirror must still fire."""
    redis = FakeRedis()
    inner = FakeInner()
    proxy = ui_notifier.wrap_telegram_notifier(inner, **_ctx(redis))
    await proxy.bot_error("disk full", chat_id="123")
    await asyncio.sleep(0.05)
    assert inner.calls[0][0] == "bot_error"
    assert len(redis.published) == 1
    payload = json.loads(redis.published[0][1])
    assert payload["type"] == "bot_error"
    assert "disk full" in payload["body"]


async def test_send_push_status_mapping(monkeypatch):
    """_send_push maps sender statuses, clears expired subs, never raises."""
    from unittest.mock import AsyncMock

    import api.push_sender as push_sender_mod
    from pywebpush import WebPushException

    monkeypatch.setattr(push_sender_mod, "VAPID_PRIVATE_KEY", "k")
    monkeypatch.setattr(push_sender_mod, "VAPID_PUBLIC_KEY", "k")
    monkeypatch.setattr(push_sender_mod, "webpush", lambda **kwargs: None)
    # Real crud/get_db are configured in tests; stub the DB cleanup helper
    # and assert it is invoked on expiry only.
    clear_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(ui_notifier, "_clear_expired_push_subscription", clear_mock)
    sub = {"endpoint": "https://push.example/x"}
    assert await ui_notifier._send_push(sub, "T", "B", "tag", user_id=7) == "sent"
    clear_mock.assert_not_called()

    class FakeResponse:
        status_code = 410
        text = "gone"

    def raise_gone(**kwargs):
        raise WebPushException("gone", response=FakeResponse())

    monkeypatch.setattr(push_sender_mod, "webpush", raise_gone)
    assert await ui_notifier._send_push(sub, "T", "B", "tag", user_id=7) == "expired"
    clear_mock.assert_awaited_once_with(7)

    assert await ui_notifier._send_push(None, "T", "B", "tag") == "failed"


async def test_emit_scale_in_contract():
    redis = FakeRedis()
    payload = await ui_notifier.emit_scale_in(
        redis,
        user_id=9,
        symbol="BTCUSDT",
        fill_price=67000.0,
        filled_quantity=0.01,
        new_average_entry=67200.0,
        new_total_quantity=0.03,
        entry_client_order_id="e1",
        direction="LONG",
    )
    assert payload is not None
    assert payload["type"] == "scale_in"
    assert payload["severity"] == "info"
    assert "67000" in payload["title"]
    assert "67200" in payload["body"]
    assert len(redis.published) == 1
    channel, raw = redis.published[0]
    assert channel == "user:9:notifications"
    assert json.loads(raw)["type"] == "scale_in"


async def test_proxy_scale_in_mirror():
    redis = FakeRedis()

    class ScaleInner:
        def __init__(self):
            self.calls = []

        async def scale_in_filled(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return "ok"

    inner = ScaleInner()
    proxy = ui_notifier.wrap_telegram_notifier(inner, **_ctx(redis))
    result = await proxy.scale_in_filled(
        symbol="ETHUSDT",
        fill_price=2900.0,
        filled_quantity=0.1,
        new_average_entry=2950.0,
        new_total_quantity=0.3,
        entry_client_order_id="e2",
    )
    assert result == "ok"
    assert len(inner.calls) == 1
    await asyncio.sleep(0.05)
    assert len(redis.published) == 1
    payload = json.loads(redis.published[0][1])
    assert payload["type"] == "scale_in"
    assert "2900" in payload["title"]


async def test_settings_injected_into_telegram_call():
    """Loaded user toggles must reach the Telegram filter (previously dropped)."""
    redis = FakeRedis()
    inner = FakeInner()
    proxy = ui_notifier.wrap_telegram_notifier(
        inner, **_ctx(redis, settings={"notifyNewPosition": False})
    )
    await proxy.new_position(symbol="BTCUSDT", direction="LONG", entry_price=1.0)
    await asyncio.sleep(0.05)
    assert inner.calls and inner.calls[0][0] == "new_position"
    forwarded_kwargs = inner.calls[0][2]
    assert forwarded_kwargs.get("notification_settings") == {"notifyNewPosition": False}
    # Suppressed in both channels by the same toggle.
    assert redis.published == []


async def test_settings_not_injected_when_empty():
    """Without loaded settings the call is forwarded untouched (legacy global)."""
    redis = FakeRedis()
    inner = FakeInner()
    proxy = ui_notifier.wrap_telegram_notifier(inner, **_ctx(redis))
    await proxy.new_position(symbol="BTCUSDT", direction="LONG", entry_price=1.0)
    await asyncio.sleep(0.05)
    assert inner.calls and inner.calls[0][0] == "new_position"
    assert "notification_settings" not in inner.calls[0][2]
    assert len(redis.published) == 1
