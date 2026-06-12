from bot_module.controller import TradingController
from bot_module.paper_executor import PaperTradingExecutor
from bot_module.risk_manager import RiskManager
import bot_module.data_consumer as dc_module  # Import module to access global caches
from bot_module.data_consumer import DataConsumer
from unittest.mock import MagicMock, AsyncMock
from bot_module.strategy import SignalDirection
import pytest
import asyncio
import time
import pandas as pd
import logging


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_full_integration_visual_strategy(mocker):
    """
    Integration test checking the entire chain from strategy launch to signal reception.
    """
    mocker.patch(
        "bot_module.data_consumer.download_klines",
        return_value=pd.DataFrame(
            {
                "open_time": pd.to_datetime(
                    pd.date_range(start="2023-01-01", periods=20, freq="1min", tz="UTC")
                ),
                "open": [100] * 20,
                "high": [100] * 20,
                "low": [100] * 20,
                "close": [100] * 20,
                "volume": [100] * 20,
            }
        ).set_index("open_time"),
    )
    # --- Step 1: Logging setup ---
    logging.getLogger("bot_module.controller").setLevel(logging.INFO)
    logging.getLogger("bot_module.strategy").setLevel(logging.INFO)
    logging.getLogger("bot_module.data_consumer").setLevel(logging.INFO)

    loop = asyncio.get_running_loop()

    mock_executor = MagicMock(spec=PaperTradingExecutor)
    mock_executor.place_order = AsyncMock(
        return_value={
            "status": "FILLED",
            "orderId": "123",
            "avgPrice": "105.0",
            "executedQty": "0.1",
            "clientOrderId": "test_entry",
        }
    )
    mock_executor.start_user_data_stream = AsyncMock()
    mock_executor.stop_user_data_stream = AsyncMock()
    mock_executor.fetch_exchange_info = AsyncMock(
        return_value={
            "symbols": [
                {
                    "symbol": "TESTUSDT",
                    "pair": "TESTUSDT",
                    "contractType": "PERPETUAL",
                    "quoteAsset": "USDT",
                    "status": "TRADING",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {"filterType": "LOT_SIZE", "stepSize": "0.001"},
                    ],
                }
            ]
        }
    )
    mock_executor.get_open_positions = AsyncMock(
        return_value=[]
    )  # No open positions on the exchange
    mock_rm = MagicMock(spec=RiskManager)
    mock_rm.assess_signal = AsyncMock(
        return_value=(True, 1.0, 10.0, None)
    )  # 4 values: approved, qty, risk_usd, rejection_reason
    mock_rm.initialize_balance = AsyncMock()
    mock_rm.save_state = AsyncMock()
    mock_rm.max_concurrent_trades = 5  # Adding a limit on simultaneous trades
    mock_rm.is_symbol_trading_allowed = AsyncMock(
        return_value=True
    )  # Allowing trading for the symbol
    mock_rm._adjust_and_round_quantity = MagicMock(
        return_value=1.0
    )  # Mocking quantity rounding
    # Mock stats for _publish_state_to_redis
    mock_rm.stats = MagicMock()
    mock_rm.stats.current_balance = 10000.0

    event_queue = asyncio.Queue()
    consumer = DataConsumer(loop=loop, executor=mock_executor, event_queue=event_queue)
    spy_ensure_subscription = mocker.spy(consumer, "ensure_subscription")

    # Correct mock for websockets to support 'async with' and 'async for'
    mock_ws = AsyncMock()
    mock_ws.__aenter__.return_value = mock_ws
    # For 'async for message in ws'
    mock_ws.__aiter__.return_value = AsyncMock()
    mock_ws.recv = AsyncMock(
        side_effect=asyncio.CancelledError
    )  # Stop loop immediately

    mocker.patch("websockets.connect", return_value=mock_ws)

    # Create a mock for get_db
    mock_db_session = AsyncMock()

    async def mock_get_db():
        yield mock_db_session

    # Mock crud functions to return valid config structure - patch via api.crud
    mock_app_config = MagicMock()
    mock_app_config.risk_management = {}
    mock_app_config.notifications = {}
    mocker.patch(
        "api.crud.get_config", new_callable=AsyncMock, return_value=mock_app_config
    )
    mocker.patch(
        "api.crud.get_user_symbol_selection_config",
        new_callable=AsyncMock,
        return_value=None,
    )

    controller = TradingController(
        loop=loop,
        data_consumer=consumer,
        live_executor=mock_executor,
        paper_executor=mock_executor,
        risk_manager=mock_rm,
        user_id=1,
        get_db=mock_get_db,  # Pass mocked DB session factory
    )
    # Ensure consumer uses controller's queue if it wasn't already linked (though init should handle it)
    consumer.event_queue = controller.event_queue

    strategy_config = {
        "id": "visual_rsi_strategy_1",
        "user_id": 1,
        "symbol_selection_mode": "STATIC",
        "symbols": ["TESTUSDT"],
        "config_data": {
            "strategy_name": "VisualBuilderStrategy",
            "enabled": True,
            "entryTrigger": {"type": "on_candle_close"},  # For controller
            "min_total_foundation_weight_threshold": 0.0,
            "entryConditions": {
                "type": "AND",
                "children": [
                    {
                        "type": "rsi_condition",
                        "params": {"period": 14, "operator": "gt", "value": 60},
                    }
                ],
            },
            "initialization": {
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "atr_multiplier",
                    "sl_value": 1.5,
                    "tp_type": "rr_multiplier",
                    "tp_value": 2.0,
                },
            },
        },
    }

    # Mocks to prevent DB/Redis connection errors
    controller.load_user_configuration = AsyncMock()
    controller.load_symbol_selection_config = AsyncMock()
    controller._load_runtime_state = AsyncMock()
    controller._save_runtime_state = AsyncMock()
    controller._publish_state_to_redis = AsyncMock()  # Prevent Redis errors
    controller._reconcile_positions_with_exchange = (
        AsyncMock()
    )  # Prevent exchange API calls

    # --- Step 2: Launch and subscription ---
    try:
        # We don't call controller.start() to avoid background tasks interference
        # Just register the strategy manually
        await controller._handle_start_strategy_command(strategy_config)
        await asyncio.sleep(0.1)

        logging.info(
            f"DEBUG: Strategy instances: {list(controller.running_strategy_instances.keys())}"
        )
        for inst, inst_config in controller.running_strategy_instances.values():
            logging.info(
                f"DEBUG: Strategy {inst.contract_id} params keys: {list(inst._instance_params.keys())}"
            )
            if "config" in inst._instance_params:
                logging.info("DEBUG: Found 'config' in strategy params.")
            else:
                logging.info("DEBUG: 'config' NOT FOUND in strategy params!")

        spy_ensure_subscription.assert_called()
        found_call = False
        for call in spy_ensure_subscription.call_args_list:
            kwargs = call.kwargs
            metrics = kwargs.get("required_metrics", set())
            # The strategy requires RSI_14 (from condition) AND ATR_14 (from SL config)
            if metrics and "RSI_14" in metrics:
                found_call = True
                break
        assert found_call, (
            "ensure_subscription was not called with required_metrics containing 'RSI_14'"
        )

        # --- Step 3: Mocking data collection and firing an event ---
        mock_kline_df = pd.DataFrame(
            [
                {
                    "close": 102.0,
                    "RSI_14": 75.0,
                    "ATR_14": 0.5,
                    "high": 105.0,
                    "low": 99.0,
                    "open": 100.0,
                }
            ]
            * 20
        )

        async def mock_gather_market_data(strategy_instance, sym):
            logging.info(f"DEBUG: mock_gather_market_data called for {sym}")
            return {"kline_1m": mock_kline_df}

        mocker.patch.object(
            controller,
            "_gather_market_data_for_strategy",
            side_effect=mock_gather_market_data,
        )

        candle_close_event = {
            "type": "CANDLE_CLOSE",
            "symbol": "TESTUSDT",
            "timeframe": "1m",
            "timestamp_ms": int(time.time() * 1000),
        }

        # Update GLOBAL active pairs cache (required for some internal checks)
        dc_module._global_active_pairs["TESTUSDT"] = {
            "symbol": "TESTUSDT",
            "atr": 0.5,
            "rsi_14": 75.0,
            "tick_size": 0.01,
            "last_price": 102.0,
        }
        consumer._active_pairs["TESTUSDT"] = dc_module._global_active_pairs["TESTUSDT"]

        # Mock global kline cache
        cache_key = dc_module._kline_cache_key(
            "TESTUSDT", "1m", "binance", "futures_usdtm"
        )
        dc_module._global_kline_df_cache[cache_key] = mock_kline_df

        logging.info("DEBUG: Calling controller._handle_event with CANDLE_CLOSE...")
        await controller._handle_event(candle_close_event)

        # 5. Check if position was created
        await asyncio.sleep(1.0)  # Increasing wait time for full processing
        # --- Step 4: Checking the result ---
        assert len(controller._active_positions) == 1, (
            "Position was not created after signal trigger"
        )
        position = list(controller._active_positions.values())[0]
        assert position.symbol == "TESTUSDT"
        assert position.direction == SignalDirection.LONG
    finally:
        await controller.stop()
