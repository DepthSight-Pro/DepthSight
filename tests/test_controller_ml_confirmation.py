# test_controller_ml_confirmation.py
import asyncio
import pytest
import pytest_asyncio
from datetime import timedelta
from unittest.mock import MagicMock, AsyncMock, patch
import pandas as pd
from typing import Dict, Optional

from bot_module.controller import TradingController
from bot_module.strategy import (
    StrategySignal,
    SignalDirection,
    OrderMode,
    BaseStrategy,
)
from bot_module import config as real_config
from bot_module.feature_extractor import (
    FeatureExtractor,
    DEFAULT_KLINE_FEATURES,
    DEFAULT_AGGTRADE_FEATURES,
    NEW_KLINE_FEATURES,
    NEW_AGGTRADE_FEATURES,
)
from bot_module.model_pipeline import ModelPipeline


# --- Fixtures ---
@pytest.fixture
def mock_data_consumer():
    mock_instance = AsyncMock()
    mock_instance.get_active_symbols.return_value = set()
    mock_instance.get_active_pairs.return_value = []
    mock_instance.start = AsyncMock()
    mock_instance.stop = AsyncMock()
    mock_instance.clear_all_subscriptions = AsyncMock()
    return lambda **kwargs: mock_instance


@pytest.fixture
def mock_executor():
    executor = AsyncMock()
    executor.market_type = "futures_usdtm"
    executor.place_order.return_value = {
        "error": False,
        "orderId": 12345,
        "clientOrderId": "mock_id",
        "status": "NEW",
    }
    executor.cancel_order.return_value = {"error": False, "status": "CANCELED"}
    executor.fetch_exchange_info.return_value = {
        "symbols": [
            {
                "symbol": "TESTUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.001",
                        "maxQty": "10000",
                        "stepSize": "0.001",
                    },
                    {"filterType": "MIN_NOTIONAL", "minNotional": "5.0"},
                ],
            }
        ]
    }
    executor.start_user_data_stream = AsyncMock()
    executor.stop_user_data_stream = AsyncMock()
    return executor


@pytest.fixture
def mock_risk_manager():
    rm = AsyncMock()  # Using AsyncMock instead of MagicMock
    rm.initialize_balance = AsyncMock()
    rm.max_concurrent_trades = 10  # Explicitly setting the number
    rm.assess_signal.return_value = (True, 10.0, 5.0, None)  # Returning 4 values
    rm.update_trade_result = AsyncMock()
    rm.update_symbol_strategy_performance = AsyncMock()
    rm.is_symbol_trading_allowed.return_value = True
    rm.save_state = AsyncMock()
    return rm


@pytest.fixture
def mock_trade_logger():
    logger_mock = MagicMock()
    logger_mock.log_event = MagicMock()
    logger_mock.start = MagicMock()
    logger_mock.stop = MagicMock()
    return logger_mock


@pytest.fixture
def mock_realtime_ml_logger():
    logger_mock = MagicMock()
    logger_mock.log_data = MagicMock()
    logger_mock.start = MagicMock()
    logger_mock.stop = MagicMock()
    return logger_mock


@pytest_asyncio.fixture
async def mock_ml_components():
    mock_fe = MagicMock(spec=FeatureExtractor)
    mock_fe.extract_features_optimized.return_value = {
        "feature1": 0.5,
        "feature2": -0.2,
    }
    mock_fe.normalize_features.return_value = {"feature1": 0.45, "feature2": -0.22}
    mock_fe.kline_feature_configs = {**DEFAULT_KLINE_FEATURES, **NEW_KLINE_FEATURES}
    mock_fe.aggtrade_feature_configs = {
        **DEFAULT_AGGTRADE_FEATURES,
        **NEW_AGGTRADE_FEATURES,
    }
    mock_pipeline = MagicMock(spec=ModelPipeline)
    mock_pipeline.load_model.return_value = True
    mock_pipeline.active_features = {"feature1", "feature2"}
    return mock_fe, mock_pipeline


@pytest_asyncio.fixture
async def controller_for_ml_confirm(
    mock_data_consumer,
    mock_executor,
    mock_risk_manager,
    mock_trade_logger,
    mock_realtime_ml_logger,
    mock_ml_components,
):
    mock_fe_live, mock_pipeline_live = mock_ml_components
    mock_test_strategy_instance = MagicMock(spec=BaseStrategy)
    mock_test_strategy_instance.NAME = "TestStrategy"
    mock_test_strategy_instance.required_data_types = {"kline_1m", "aggTrade"}
    mock_test_strategy_instance.check_signal = AsyncMock(return_value=None)

    def mock_get_strategy_param(strategy_name, param_name, default=None):
        if strategy_name == "TestStrategy" and param_name in [
            "entry_timeframe",
            "candle_timeframe",
        ]:
            return "1m"
        return default

    with (
        patch.object(real_config, "ML_CONFIRMATION_ENABLED", True),
        patch.object(real_config, "ML_CONFIRMATION_STRATEGIES", ["TestStrategy"]),
        patch.object(real_config, "ML_CONFIRMATION_PROBABILITY_THRESHOLD", 0.7),
        patch.object(real_config, "ML_CONFIRMATION_REJECT_IF_OPPOSITE_HIGH_PROB", True),
        patch.object(real_config, "ML_CONFIRMATION_OPPOSITE_PROB_THRESHOLD", 0.75),
        patch("bot_module.controller.FeatureExtractor", return_value=mock_fe_live),
        patch("bot_module.controller.ModelPipeline", return_value=mock_pipeline_live),
        patch("bot_module.controller.crud", new_callable=MagicMock) as mock_crud,
        patch("bot_module.controller.send_push_notification", new_callable=AsyncMock),
        patch(
            "bot_module.config.get_strategy_param", side_effect=mock_get_strategy_param
        ),
    ):
        # Configure mock_crud to return something meaningful
        mock_crud.admin_get_user_details = AsyncMock(
            return_value=MagicMock(telegram_id=123456789)
        )
        mock_crud.create_order_record = AsyncMock(return_value=MagicMock(id=1))
        mock_crud.create_position_record = AsyncMock(
            return_value=MagicMock(id=1, user_id=1)
        )
        mock_crud.update_position_record = AsyncMock()
        mock_crud.admin_get_user_push_subscriptions = AsyncMock(
            return_value=[]
        )  # Empty list of subscriptions

        # Configure executor so that it always returns an empty list of positions
        mock_executor.get_open_positions = AsyncMock(return_value=[])

        ctrl = TradingController(
            loop=asyncio.get_running_loop(),
            data_consumer=mock_data_consumer,
            live_executor=mock_executor,
            paper_executor=mock_executor,
            risk_manager=mock_risk_manager,
            user_id=1,
        )
        ctrl.trade_logger = mock_trade_logger
        ctrl.realtime_ml_logger = mock_realtime_ml_logger

        mock_config = {
            "id": "ml-config-id-456",
            "user_id": 1,
            "config_data": {"strategy_name": "TestStrategy", "params": {}},
            "use_ml_confirmation": True,  # Enabling ML for this instance
        }
        async with ctrl.instances_lock:
            ctrl.running_strategy_instances[mock_config["id"]] = (
                mock_test_strategy_instance,
                mock_config,
            )

        ctrl._ml_confirmation_enabled_live_runtime = True
        ctrl._ml_confirmation_pipeline_live = mock_pipeline_live
        ctrl._ml_confirmation_feature_extractor_live = mock_fe_live

        await ctrl._update_market_info_cache()
        yield ctrl


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ml_prediction_proba, ml_should_confirm_signal, overall_signal_should_be_risk_assessed",
    [
        ({"1": 0.8, "0": 0.1}, True, True),
        ({"1": 0.6, "0": 0.2}, False, False),
        ({"1": 0.75, "0": 0.8}, False, False),
        ({"1": 0.75, "0": 0.7}, True, True),
        (None, True, True),
    ],
)
async def test_ml_confirmation_processing_signal(
    controller_for_ml_confirm: TradingController,
    mock_data_consumer: MagicMock,
    ml_prediction_proba: Optional[Dict[str, float]],
    ml_should_confirm_signal: bool,
    overall_signal_should_be_risk_assessed: bool,
):
    controller = controller_for_ml_confirm
    mock_risk_manager = controller.rm
    _, mock_pipeline_live = (
        controller._ml_confirmation_feature_extractor_live,
        controller._ml_confirmation_pipeline_live,
    )

    if ml_prediction_proba is not None:
        proba_map_int_keys = {int(k): v for k, v in ml_prediction_proba.items()}
        mock_pipeline_live.predict_proba_one = MagicMock(
            return_value=proba_map_int_keys
        )
    else:
        mock_pipeline_live.predict_proba_one = MagicMock(return_value=None)

    mock_kline_data = pd.DataFrame(
        {
            "open_time": pd.to_datetime(
                [
                    pd.Timestamp.now(tz="UTC") - timedelta(minutes=i)
                    for i in range(5, 0, -1)
                ]
            ),
            "open": [100, 101, 100, 102, 101],
            "high": [102, 103, 101, 104, 102],
            "low": [99, 100, 99, 101, 100],
            "close": [101, 102, 100, 103, 101.5],
            "volume": [1000, 1200, 900, 1500, 1100],
        }
    ).set_index("open_time")

    # get_kline_history is now in the consumer mock, not data_consumer
    controller.consumer.get_kline_history.return_value = mock_kline_data
    controller.consumer.get_recent_trades.return_value = pd.DataFrame()

    symbol = "TESTUSDT"
    strategy_name = "TestStrategy"

    signal_to_process = StrategySignal(
        strategy_name=strategy_name,
        symbol=symbol,
        direction=SignalDirection.LONG,
        stop_loss=99.0,
        take_profit=105.0,
        trigger_price=101.5,
        mode=OrderMode.MARKET,
        details={"original_detail": "some_value"},
    )

    pair_info_for_signal = {
        "symbol": symbol,
        "atr": 0.5,
        "last_price": 101.5,
        "lot_params": {"minQty": 0.001, "maxQty": 10000.0, "stepSize": 0.001},
        "min_notional": 5.0,
        "time_since_last_signal_sec": 300.0,
    }

    mock_risk_manager.assess_signal.reset_mock()
    controller.trade_logger.log_event.reset_mock()

    await controller._process_signal(signal_to_process, pair_info_for_signal)
    await asyncio.sleep(0.1)

    # Validation logic changed
    if overall_signal_should_be_risk_assessed:
        mock_risk_manager.assess_signal.assert_called_once()
        args_assess, _ = mock_risk_manager.assess_signal.call_args
        passed_signal_to_rm: StrategySignal = args_assess[0]
        assert (
            passed_signal_to_rm.details.get("ml_confirmed_live")
            == ml_should_confirm_signal
        )
    else:
        # If the signal was not supposed to reach RM, it means it was rejected by ML
        mock_risk_manager.assess_signal.assert_not_called()
        # And we should find a log about this
        found_ml_reject_log = any(
            call_arg.kwargs.get("event_type") == "SIGNAL_REJECTED_ML_LIVE"
            or (call_arg.args and call_arg.args[0] == "SIGNAL_REJECTED_ML_LIVE")
            for call_arg in controller.trade_logger.log_event.call_args_list
        )
        assert found_ml_reject_log, (
            "Signal was NOT rejected by ML as expected (no reject log found)."
        )

    # Clearing state for the next parameterized run
    async with controller._positions_dict_lock:
        controller._active_positions.clear()
    async with controller._processing_signal_lock:
        if symbol in controller._processing_signal_for_symbol:
            controller._processing_signal_for_symbol.remove(symbol)
    controller._recent_signals.clear()
