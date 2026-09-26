# tests/test_e2e_controller_orderbook.py

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from bot_module import config as global_bot_config
from bot_module.controller import TradingController
from bot_module.data_consumer import DataConsumer
from bot_module.exchanges import ExchangeExecutor
from bot_module.risk_manager import RiskManager
from bot_module.strategy import (
    STRATEGIES,
    OrderbookAnalysisResult,
    VolumeBreakoutStrategy,
)
from bot_module.telegram_notifier import TelegramNotifier

STRATEGIES["VolumeBreakout"] = VolumeBreakoutStrategy


@pytest.fixture
async def setup_controller_system(monkeypatch):
    """Fixture for building the entire system in a test environment."""
    mock_consumer = AsyncMock(spec=DataConsumer)
    mock_executor = AsyncMock(spec=ExchangeExecutor)
    mock_executor.check_open_orders = AsyncMock()
    mock_executor.initialize_equity_tracking = AsyncMock()
    mock_rm = AsyncMock(spec=RiskManager)
    mock_rm._is_trading_allowed = True  # Add attribute
    mock_rm.stats = MagicMock()
    mock_rm.stats.current_balance = 10000.0
    mock_rm.stats.today_pnl = 0.0
    mock_rm.stats.consecutive_losses = 0
    mock_rm.max_concurrent_trades = 5
    mock_rm.get_pnl_for_strategy.return_value = 0.0
    mock_telegram = AsyncMock(spec=TelegramNotifier)

    active_pairs_data = [
        {
            "symbol": "BTCUSDT",
            "natr": 1.5,
            "atr": 350.0,
            "last_price": 50150.0,
            "tick_size": 0.01,
            "lot_params": {"stepSize": "0.001"},
            "min_notional": 10.0,
            "relative_volume": 6.0,
        }
    ]
    mock_consumer.get_active_symbols.return_value = {"BTCUSDT"}
    mock_consumer.get_active_pairs.return_value = active_pairs_data
    mock_consumer.get_active_pair_by_symbol.return_value = active_pairs_data[0]

    # Create at least 25 klines to satisfy MIN_STRATEGY_HISTORY_CANDLES (default 20)
    kline_data = {
        "open_time": pd.date_range(start="2023-01-01 12:00", periods=25, freq="1min"),
        "open": [49800.0] * 25,
        "high": [50200.0] * 25,
        "low": [49700.0] * 25,
        "close": [50150.0] * 25,
        "volume": [10.0] * 25,
    }
    mock_kline_df = pd.DataFrame(kline_data)
    mock_consumer.get_kline_history.return_value = mock_kline_df
    mock_consumer.get_recent_trades.return_value = pd.DataFrame(
        {
            "price": [50150.0] * 10,
            "quantity": [1.0] * 10,
            "time": [pd.Timestamp.now()] * 10,
        }
    )
    mock_consumer.get_latest_depth.return_value = {
        "bids": [["49000.00", "20.0"]],
        "asks": [["51000.00", "15.0"]],
        "lastUpdateId": 123456789,
    }

    mock_executor.fetch_exchange_info.return_value = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.001",
                        "maxQty": "1000",
                        "stepSize": "0.001",
                    },
                    {"filterType": "NOTIONAL", "minNotional": "10.0"},
                ],
            }
        ]
    }
    mock_executor.place_order = AsyncMock(
        return_value={
            "orderId": 12345,
            "status": "FILLED",
            "price": "50150.0",
            "origQty": "0.1",
        }
    )
    mock_executor.market_type = global_bot_config.TRADING_MARKET_TYPE

    # Patch crud to return None for configs to avoid Pydantic validation errors during init
    monkeypatch.setattr(
        "bot_module.controller.crud.get_user_symbol_selection_config",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "bot_module.controller.crud.get_config", AsyncMock(return_value=None)
    )

    mock_rm.assess_signal.return_value = (True, 1.0, 25.0, None)
    mock_rm.is_symbol_trading_allowed.return_value = True

    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("redis.asyncio.Redis", lambda **kwargs: fake_redis)
    monkeypatch.setattr("redis.asyncio.from_url", lambda *args, **kwargs: fake_redis)

    async def mock_get_db_session():
        db = AsyncMock()
        # Mock the result for crud.get_config
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = (
            None  # Return None for config
        )
        db.execute.return_value = mock_result
        yield db

    loop = asyncio.get_running_loop()
    controller = TradingController(
        loop=loop,
        data_consumer=lambda **kwargs: mock_consumer,
        live_executor=mock_executor,
        paper_executor=mock_executor,
        risk_manager=mock_rm,
        user_id=1,
        telegram_notifier=mock_telegram,
        get_db=mock_get_db_session,
    )

    monkeypatch.setitem(
        global_bot_config.STRATEGY_DEFAULTS["VolumeBreakout"], "enabled", True
    )
    for strat_name in STRATEGIES:
        if strat_name != "VolumeBreakout":
            # Ensure that the key exists before modification
            if strat_name not in global_bot_config.STRATEGY_DEFAULTS:
                global_bot_config.STRATEGY_DEFAULTS[strat_name] = {}
            monkeypatch.setitem(
                global_bot_config.STRATEGY_DEFAULTS[strat_name], "enabled", False
            )

    system_components = {
        "controller": controller,
        "mock_consumer": mock_consumer,
        "mock_executor": mock_executor,
        "mock_rm": mock_rm,
    }

    yield system_components

    if hasattr(controller, "_running") and controller._running:
        await controller.stop()


@pytest.mark.asyncio
async def test_e2e_signal_approved_on_companion_density(
    setup_controller_system, monkeypatch
):
    controller = setup_controller_system["controller"]
    mock_consumer = setup_controller_system["mock_consumer"]
    mock_executor = setup_controller_system["mock_executor"]

    monkeypatch.setattr(global_bot_config, "TRADING_MARKET_TYPE", "futures_usdtm")
    monkeypatch.setattr(global_bot_config, "USE_COMPANION_ORDERBOOK_ANALYSIS", True)
    monkeypatch.setattr(
        global_bot_config, "ANALYZE_SPOT_ORDERBOOK_FOR_FUTURES_TRADES", True
    )

    from bot_module.strategy import StrategySignal, SignalDirection, OrderMode

    pair_info_for_check = (await mock_consumer.get_active_pairs())[0]
    test_signal = StrategySignal(
        strategy_name="VolumeBreakout",
        symbol=pair_info_for_check["symbol"],
        direction=SignalDirection.LONG,
        trigger_price=pair_info_for_check["last_price"],
        stop_loss=pair_info_for_check["last_price"] - pair_info_for_check["atr"],
        take_profit=pair_info_for_check["last_price"] + pair_info_for_check["atr"] * 2,
        mode=OrderMode.MARKET,
        details={"reason": "Injected by test"},
    )

    await controller.start()
    await asyncio.sleep(0.2)

    # 1. Simulate instance startup via command
    mock_config_payload = {
        "id": "test-config-volume-breakout",
        "user_id": 1,
        "config_data": {"strategy_name": "VolumeBreakout", "params": {}},
        "use_ml_confirmation": False,
    }
    await controller._handle_start_strategy_command(mock_config_payload)

    # 2. Find the running instance
    async with controller.instances_lock:
        instance_tuple = next(
            iter(controller.running_strategy_instances.values()), None
        )
    assert instance_tuple is not None, "Strategy instance was not started"
    volume_breakout_instance, config_dict = instance_tuple

    # 3. Mock its check_signal method (return a tuple of 3 elements)
    volume_breakout_instance.check_signal = AsyncMock(
        return_value=(test_signal, 100.0, {})
    )

    # 3b. Bypass the shared-gather WARMUP freshness gate: the per-instance
    # path only needs a non-empty frame here (check_signal is mocked above
    # and sizing comes from the mocked RiskManager).
    monkeypatch.setattr(
        controller,
        "_gather_market_data_for_strategy",
        AsyncMock(return_value={"kline_1m": pd.DataFrame([{"close": 50150.0}])}),
    )

    # 4. Call signal processing directly for this instance
    await controller._check_and_process_signal_for_instance(
        volume_breakout_instance, config_dict, "BTCUSDT", pair_info_for_check
    )

    await asyncio.sleep(0.5)

    mock_executor.place_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_e2e_signal_blocked_on_conflicting_density(
    setup_controller_system, monkeypatch
):
    controller = setup_controller_system["controller"]
    mock_consumer = setup_controller_system["mock_consumer"]
    mock_executor = setup_controller_system["mock_executor"]

    monkeypatch.setattr(global_bot_config, "TRADING_MARKET_TYPE", "futures_usdtm")
    monkeypatch.setattr(global_bot_config, "USE_COMPANION_ORDERBOOK_ANALYSIS", True)
    monkeypatch.setattr(
        global_bot_config, "ANALYZE_SPOT_ORDERBOOK_FOR_FUTURES_TRADES", True
    )

    # Correct path for patching
    monkeypatch.setattr(
        "bot_module.strategy.BaseStrategy.check_foundations",
        lambda self, pair_info, market_data: {
            "orderbook": OrderbookAnalysisResult(conflict=True)
        },
    )

    await controller.start()
    await asyncio.sleep(0.2)

    pair_info_for_check = (await mock_consumer.get_active_pairs())[0]
    active_strategies = controller._active_strategies.get("BTCUSDT", [])

    # Start the main check loop, which will call the patched method
    await controller._check_signals_for_symbol(
        "BTCUSDT", pair_info_for_check, active_strategies
    )
    await asyncio.sleep(0.5)

    mock_executor.place_order.assert_not_awaited()
