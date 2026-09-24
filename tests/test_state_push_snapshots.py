# tests/test_state_push_snapshots.py
"""Wire-contract tests for realtime push snapshots.

Covers the backend half of the realtime dashboard:
- `_publish_state_to_redis` publishes per-channel payloads carrying data
  (not just `{"user_id": ...}`), with `seq`/`ts_ms`/`type` envelope.
- `_publish_state_to_redis` keeps the limit/partial order rails
  (`partial_tp_orders`, `dca_orders`) in the (otherwise truncated) positions
  push, because the live deal chart renders them straight from the snapshot.
- `_publish_trades_event` emits the trades-invalidation channel.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from bot_module.controller import (
    DcaOrderInfo,
    LivePosition,
    PartialTpOrderInfo,
    TradingController,
)
from bot_module.strategy import SignalDirection


@pytest.fixture
def mock_consumer_cls():
    mock_instance = AsyncMock()
    mock_instance.start = AsyncMock()
    mock_instance.stop = AsyncMock()
    return lambda **kwargs: mock_instance


@pytest.fixture
def mock_executor():
    return AsyncMock()


@pytest.fixture
def mock_risk_manager():
    rm = AsyncMock()
    rm.stats = SimpleNamespace(
        current_balance=1000.0,
        today_pnl=12.5,
        consecutive_losses=0,
    )
    rm.allocated_margin = 0.0
    rm._is_trading_allowed = True
    return rm


@pytest_asyncio.fixture
async def push_controller(mock_consumer_cls, mock_executor, mock_risk_manager):
    with patch("bot_module.controller.redis.Redis") as mock_redis_cls:
        fake_client = AsyncMock()
        # Redis.pipeline() is sync and returns an async context manager.
        fake_client.pipeline = MagicMock(return_value=AsyncMock())
        mock_redis_cls.return_value = fake_client
        controller = TradingController(
            loop=asyncio.get_running_loop(),
            data_consumer=mock_consumer_cls,
            live_executor=mock_executor,
            paper_executor=mock_executor,
            risk_manager=mock_risk_manager,
            user_id=7,
            api_key_id=3,
        )
        yield controller, fake_client


def _pipeline(controller):
    # `async with pipeline()` binds __aenter__'s return value as `pipe`.
    return controller.redis_client.pipeline.return_value.__aenter__.return_value


@pytest.mark.asyncio
async def test_publish_state_carries_data_snapshots(push_controller):
    controller, _ = push_controller

    await controller._publish_state_to_redis()

    pipe = _pipeline(controller)
    # State keys still written for REST/inspector fallback.
    # NOTE: pipeline set/publish are sync (buffered); only execute() is awaited.
    assert pipe.set.call_count == 3
    for call in pipe.set.call_args_list:
        # Ephemeral keys: dead controllers must not haunt "all" aggregation.
        assert call.kwargs.get("ex") == 30
    await pipe.execute()

    assert pipe.publish.call_count == 3
    by_channel = {}
    for call in pipe.publish.call_args_list:
        channel, payload_raw = call.args
        by_channel[channel] = json.loads(payload_raw)

    pos = by_channel["depthsight:events:positions:7"]
    strat = by_channel["depthsight:events:strategies:7"]
    port = by_channel["depthsight:events:portfolio:7"]

    for payload in (pos, strat, port):
        assert payload["user_id"] == 7
        assert payload["type"] == "snapshot"
        assert isinstance(payload["seq"], int) and payload["seq"] >= 1
        assert isinstance(payload["ts_ms"], int)
        assert "data" in payload

    assert pos["data"] == []
    assert strat["data"] == []
    assert port["data"]["total_equity"] == 1000.0
    assert port["data"]["today_pnl"] == 12.5


@pytest.mark.asyncio
async def test_publish_state_seq_increments(push_controller):
    controller, _ = push_controller

    await controller._publish_state_to_redis()
    await controller._publish_state_to_redis()

    pipe = _pipeline(controller)
    seqs = [
        json.loads(call.args[1])["seq"]
        for call in pipe.publish.call_args_list
        if call.args[0] == "depthsight:events:positions:7"
    ]
    assert seqs == [1, 2]


@pytest.mark.asyncio
async def test_publish_state_push_keeps_limit_orders(push_controller):
    """Truncated push rows must still carry the limit/partial order rails."""
    controller, _ = push_controller

    position = LivePosition(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=1500.0,
        initial_quantity=0.01,
        remaining_quantity=0.01,
        entry_time=1790000000.0,
        strategy="VisualBuilderStrategy",
        status="OPEN",
        entry_client_order_id="ds-push-test-1",
        mode="live",
        market_type="futures_usdtm",
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=1530.0,
                orig_fraction=1.0,
                quantity=0.01,
                order_id="tp-1",
                status="PENDING",
            )
        ],
        dca_orders=[
            DcaOrderInfo(
                target_price=1480.0,
                quantity=0.005,
                order_id="dca-1",
                status="NEW",
            )
        ],
        execution_events=[
            {
                "timestamp": "2026-09-21T15:00:00+00:00",
                "price": 1500.0,
                "quantity": 0.01,
                "type": "ENTRY",
            }
        ],
    )
    controller._active_positions[position.symbol] = position
    controller.consumer.get_active_pair_by_symbol = AsyncMock(
        return_value={"last_price": 1505.0}
    )

    await controller._publish_state_to_redis()

    pipe = _pipeline(controller)
    positions_payload = json.loads(
        next(
            call.args[1]
            for call in pipe.publish.call_args_list
            if call.args[0] == "depthsight:events:positions:7"
        )
    )

    assert len(positions_payload["data"]) == 1
    row = positions_payload["data"][0]
    assert row["id"] == "ds-push-test-1"
    assert row["truncated"] is True

    # Limit exits (partial TPs) — the live chart draws these rails.
    assert row["partial_tp_orders"] == [
        {
            "target_price": 1530.0,
            "orig_fraction": 1.0,
            "quantity": 0.01,
            "order_id": "tp-1",
            "client_order_id": None,
            "status": "PENDING",
            "fill_price": None,
            "commission": None,
        }
    ]
    # Limit entries (DCA / scale-in).
    assert len(row["dca_orders"]) == 1
    assert row["dca_orders"][0]["target_price"] == 1480.0
    assert row["dca_orders"][0]["status"] == "NEW"

    # Heavy traces stay out of the push (REST/inspector only).
    assert "executions" not in row
    assert "signal_details_json" not in row


@pytest.mark.asyncio
async def test_publish_trades_event(push_controller):
    controller, fake_client = push_controller
    # _publish_trades_event publishes directly (no pipeline).
    fake_client.publish = AsyncMock()

    await controller._publish_trades_event({"symbol": "BTCUSDT"})

    fake_client.publish.assert_awaited_once()
    channel, payload_raw = fake_client.publish.await_args.args
    assert channel == "depthsight:events:trades:7"
    payload = json.loads(payload_raw)
    assert payload["user_id"] == 7
    assert payload["type"] == "trades_invalidated"
    assert payload["trade"] == {"symbol": "BTCUSDT"}
