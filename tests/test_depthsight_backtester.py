# tests/test_depthsight_backtester.py
import pytest
import pandas as pd
import numpy as np
import msgpack
import zstandard
from typing import Dict, Any, Optional, List, Set, Tuple
from unittest.mock import MagicMock, AsyncMock
import shutil

# Imports
from bot_module import strategy as strategy_module
from bot_module.depthsight_backtester import (
    DepthSightBacktester,
    L2HistoricalDataReader,
)
from bot_module.strategy import (
    BaseStrategy,
    StrategySignal,
    SignalDirection,
    OrderMode,
    PartialTarget,
    VisualBuilderStrategy,
)
from bot_module import config
from bot_module.utils import add_relative_volume
from bot_module.datatypes import (
    OrderbookAnalysisResult,
    DensityInfo,
)


def test_visual_config_indicators_do_not_depend_on_strategy_name():
    bt = DepthSightBacktester.__new__(DepthSightBacktester)
    params = {
        "config": {
            "entryConditions": {
                "type": "AND",
                "children": [
                    {"type": "rsi_condition", "params": {"period": 21}},
                    {"type": "adx_filter", "params": {"period": 18}},
                ],
            }
        }
    }

    indicators = bt._get_required_indicators("CustomStrategyName", params, {})

    assert "RSI_21" in indicators
    assert "ADX_18" in indicators


# --- Fixture for V2 Backtester (VisualBuilderStrategy) ---
@pytest.fixture
def v2_backtester_instance(tmp_path, mocker):
    # Registering VisualBuilderStrategy
    mocker.patch.dict(
        strategy_module.STRATEGIES,
        {"VisualBuilderStrategy": VisualBuilderStrategy},
        clear=True,
    )
    mocker.patch.object(strategy_module, "_strategy_instances", {})

    # Mocking pandas_ta
    mocker.patch("bot_module.depthsight_backtester.PANDAS_TA_AVAILABLE", True)
    mock_ta = mocker.patch("bot_module.depthsight_backtester.ta")

    # Disabling R/R checks for tests
    mocker.patch.object(config, "RISK_MANAGER_MIN_DOLLAR_RR_RATIO", 0.0)
    mocker.patch.object(config, "RISK_MANAGER_MIN_RR_RATIO", 0.0)

    # Creating base data
    kline_df = create_base_kline_data(num_rows=200, start_price=100.0)

    # Setting up indicator mocks
    mock_ta.atr.return_value = pd.Series(
        np.full(len(kline_df), 1.0), index=kline_df.index
    )
    kline_df["ATR_14"] = 1.0

    adx_series = pd.DataFrame(
        {"ADX_14": np.linspace(10, 40, len(kline_df))}, index=kline_df.index
    )
    kline_df["ADX_14"] = adx_series["ADX_14"]
    mock_ta.adx.return_value = adx_series

    # SMA: Fast > Slow (Long Trend)
    kline_df["SMA_10"] = kline_df["close"] + 4
    kline_df["SMA_50"] = kline_df["close"]
    mock_ta.sma.side_effect = lambda close, length, **kwargs: kline_df[f"SMA_{length}"]

    mock_ta.bbands.return_value = pd.DataFrame(
        {
            "BBU_20_2.0": kline_df["close"] + 2,
            "BBM_20_2.0": kline_df["close"],
            "BBL_20_2.0": kline_df["close"] - 2,
        },
        index=kline_df.index,
    )

    kline_df["RSI_14"] = np.linspace(30, 70, len(kline_df))
    mock_ta.rsi.return_value = kline_df["RSI_14"]

    def _create_bt(strategy_json_config: Dict[str, Any]):
        df_copy = kline_df.copy()

        # IMPORTANT: Adding riskPerTradePercent for RiskManager
        risk_params = {
            "riskPerTradePercent": 1.0,
            "max_stop_distance_pct": 50.0,
            "minRrRatio": 0.0,
            "minDollarRrRatio": 0.0,
            "dailyMaxLossPercent": 5.0,
            "maxConsecutiveLosses": 5,
        }

        bt = DepthSightBacktester(
            "VisualBuilderStrategy",
            "TESTUSDT",
            {"config": strategy_json_config},
            {"kline_1m": df_copy},
            10000.0,
            0,
            risk_params,
            risk_params,
            {"commission_pct": 0.001, "slippage_pct": 0.0},
            {"VisualBuilderStrategy": {"risk_pct_per_trade": 0.01}},
            {},
            None,
            l2_storage_path=None,
            exchange_info={
                "tick_size": 0.01,
                "lot_params": {"stepSize": "0.001"},
                "min_notional": 0.0,
            },
            min_foundation_weight_threshold=0.0,
            foundation_weights={},
        )
        # IMPORTANT: Adding kline_1m after initialization
        bt.historical_data["kline_1m"] = bt.klines
        return bt

    return _create_bt


# --- Helper strategies ---
class NoDepthStrategy(BaseStrategy):
    NAME = "NoDepthStrategy"
    enabled = True
    candle_timeframe = "1m"

    @property
    def required_data_types(self) -> Set[str]:
        return {"kline_1m"}

    def _check_specific_signal_logic(self, pair_info, market_data, foundations):
        return self._create_signal(
            symbol=pair_info["symbol"],
            direction=SignalDirection.LONG,
            trigger_price=pair_info["last_price"],
            stop_loss=pair_info["last_price"] * 0.99,
            take_profit=pair_info["last_price"] * 1.02,
            mode=OrderMode.MARKET,
        )


class DepthUsingStrategy(BaseStrategy):
    NAME = "DepthUsingStrategy"
    enabled = True
    candle_timeframe = "1m"

    @property
    def required_data_types(self) -> Set[str]:
        return {"kline_1m", "depth_trading"}

    def check_foundations(
        self, pair_info: Dict, market_data: Dict
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        foundations, trace_nodes = super().check_foundations(pair_info, market_data)
        ob_analysis_result = foundations.get(strategy_module.FOUNDATION_ORDERBOOK)

        depth = market_data.get("depth_trading")
        has_big_wall = False
        wall_price = 0.0

        if depth and isinstance(depth, dict):
            bids = depth.get("bids", [])
            for p, s in bids:
                if float(p) * float(s) > 500000:
                    has_big_wall = True
                    wall_price = float(p)
                    break

        if has_big_wall and wall_price < pair_info["last_price"]:
            if not isinstance(ob_analysis_result, OrderbookAnalysisResult):
                ob_analysis_result = OrderbookAnalysisResult(is_valid=True)
            else:
                if hasattr(ob_analysis_result, "is_valid"):
                    ob_analysis_result.is_valid = True

            ob_analysis_result.nearest_support = DensityInfo(
                price=wall_price,
                size_usd=wall_price * 5001,
                distance_from_current_price_abs=abs(
                    pair_info["last_price"] - wall_price
                ),
                side="bid",
            )

            for node in trace_nodes:
                if node.get("id") == strategy_module.FOUNDATION_ORDERBOOK:
                    node["result"] = True
                    break

        foundations[strategy_module.FOUNDATION_ORDERBOOK] = ob_analysis_result
        return foundations, trace_nodes

    def _check_specific_signal_logic(
        self, pair_info: Dict, market_data: Dict, foundations: Dict
    ) -> Optional[StrategySignal]:
        ob_analysis = foundations.get(strategy_module.FOUNDATION_ORDERBOOK)
        if (
            isinstance(ob_analysis, OrderbookAnalysisResult)
            and ob_analysis.nearest_support
        ):
            price = pair_info["last_price"]
            return self._create_signal(
                symbol=pair_info["symbol"],
                direction=SignalDirection.LONG,
                trigger_price=price,
                stop_loss=price * 0.99,
                take_profit=price * 1.02,
            )
        return None


class FastFailStrategy(DepthUsingStrategy):
    NAME = "FastFailStrategy"

    async def check_fast_foundations(
        self, pair_info: Dict, market_data: Dict
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        return {strategy_module.FOUNDATION_MARKET_ACTIVITY: False}, []


# --- Main fixture ---
@pytest.fixture
def depthsight_backtester_setup(tmp_path, request, mocker):
    strategy_class = request.param
    l2_storage_path = tmp_path / "L2_data"

    mocker.patch.dict(
        strategy_module.STRATEGIES,
        {
            NoDepthStrategy.NAME: NoDepthStrategy,
            DepthUsingStrategy.NAME: DepthUsingStrategy,
            FastFailStrategy.NAME: FastFailStrategy,
        },
        clear=True,
    )
    mocker.patch.object(strategy_module, "_strategy_instances", {})

    mocker.patch.object(config, "DYNAMIC_SELECTION_REL_VOL_THRESHOLD", 0.1)
    mocker.patch.object(config, "DYNAMIC_SELECTION_NATR_THRESHOLD", 0.1)
    mocker.patch.object(config, "RISK_MANAGER_MIN_DOLLAR_RR_RATIO", 0.0)
    mocker.patch.object(config, "RISK_MANAGER_MIN_RR_RATIO", 0.0)

    mocker.patch("bot_module.depthsight_backtester.PANDAS_TA_AVAILABLE", True)
    mock_ta = mocker.patch("bot_module.depthsight_backtester.ta")

    klines = create_base_kline_data(num_rows=200)

    mock_ta.atr.return_value = pd.Series(np.full(len(klines), 1.0), index=klines.index)
    mock_ta.macd.return_value = pd.DataFrame(
        {
            "MACD_12_26_9": np.full(len(klines), 0.1),
            "MACDs_12_26_9": np.full(len(klines), 0.0),
            "MACDh_12_26_9": np.full(len(klines), 0.1),
        },
        index=klines.index,
    )
    mock_ta.bbands.return_value = pd.DataFrame(
        {
            "BBU_20_2.0": klines["close"] + 2,
            "BBM_20_2.0": klines["close"],
            "BBL_20_2.0": klines["close"] - 2,
        },
        index=klines.index,
    )
    mock_ta.stoch.return_value = pd.DataFrame(
        {
            "STOCHk_14_3_3": np.full(len(klines), 50),
            "STOCHd_14_3_3": np.full(len(klines), 50),
        },
        index=klines.index,
    )
    mock_ta.adx.return_value = pd.DataFrame(
        {"ADX_14": np.full(len(klines), 25)}, index=klines.index
    )

    def create_mock_l2_file(symbol, dt, has_big_wall=False, current_price=None):
        l2_reader = L2HistoricalDataReader(str(l2_storage_path))
        file_path = l2_reader._get_l2_data_path(symbol, int(dt.timestamp() * 1000))
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if current_price is None:
            start_ts = pd.Timestamp("2023-01-01", tz="UTC")
            current_price = 100.0 + (dt - start_ts).total_seconds() / 60 * 0.1

        wall_price = current_price - 1.0
        ask_price_for_test = current_price + 0.01

        bids = (
            [[f"{wall_price:.2f}", "5001"]]
            if has_big_wall
            else [[f"{current_price - 0.01:.2f}", "10"]]
        )
        asks = [[f"{ask_price_for_test:.2f}", "100000"]]

        snapshot = {"ts": int(dt.timestamp() * 1000), "bids": bids, "asks": asks}

        with open(file_path, "wb") as f:
            packer = msgpack.Packer()
            f.write(zstandard.ZstdCompressor().compress(packer.pack(snapshot)))

    # IMPORTANT: Parameters for RiskManager
    backtest_risk_params = {
        "riskPerTradePercent": 1.0,
        "dailyMaxLossPercent": 5.0,
        "risk_pct_per_trade": 0.01,
        "minRrRatio": 0.0,
        "minDollarRrRatio": 0.0,
        "max_stop_distance_pct": 50.0,
    }

    backtester = DepthSightBacktester(
        strategy_class.NAME,
        "TESTUSDT",
        {},
        {"kline_1m": klines.copy()},
        10000,
        1,
        backtest_risk_params,
        backtest_risk_params,
        {"commission_pct": 0.001, "slippage_pct": 0.0},
        {strategy_class.NAME: {"risk_pct_per_trade": 0.01}},
        {},
        None,
        exchange_info={
            "tick_size": 0.01,
            "lot_params": {"stepSize": "0.001"},
            "min_notional": 0.0,
        },
        l2_storage_path=str(l2_storage_path),
        foundation_weights={"market_activity": 50, "orderbook": 50, "trend": 10},
        min_foundation_weight_threshold=0.0,  # Disabling weight threshold for tests
    )

    return backtester, create_mock_l2_file


def create_base_kline_data(num_rows=200, start_price=100.0, trend=0.1):
    data = {
        "open": np.full(num_rows, start_price) + np.arange(num_rows) * trend,
        "close": np.full(num_rows, start_price) + np.arange(num_rows) * trend,
        "volume": np.random.uniform(50, 150, num_rows),
    }
    df = pd.DataFrame(data)
    df["high"] = df[["open", "close"]].max(axis=1) + 2.0
    df["low"] = df[["open", "close"]].min(axis=1) - 2.0
    df.index = pd.to_datetime(
        pd.date_range(start="2023-01-01", periods=num_rows, freq="1min", tz="UTC")
    )
    df = add_relative_volume(df, period=20)

    df.loc[:, "relative_volume"] = df["relative_volume"].fillna(1.0)
    df["natr"] = 1.5
    df["is_volume_spike"] = False

    return df


# --- TESTS ---


@pytest.mark.parametrize(
    "depthsight_backtester_setup", [DepthUsingStrategy], indirect=True
)
@pytest.mark.asyncio
async def test_trade_executes_when_l2_condition_is_met(
    depthsight_backtester_setup, mocker
):
    bt, create_mock_l2_file = depthsight_backtester_setup

    # For this test, we enable the threshold to check that L2 helps overcome it
    bt.strategy_instance.foundation_weights = {
        "market_activity": 1,
        "orderbook": 100,
        "trend": 1,
    }
    bt.min_total_foundation_weight_threshold = 90

    signal_fire_idx = 80
    current_price = bt.klines.iloc[signal_fire_idx]["close"]

    create_mock_l2_file(
        "TESTUSDT",
        bt.klines.index[signal_fire_idx],
        has_big_wall=True,
        current_price=current_price,
    )

    results = await bt.run_async()

    assert results is not None
    assert results["trades"] >= 1, (
        f"Trade should have opened. Trades: {results.get('trades')}"
    )


@pytest.mark.parametrize(
    "depthsight_backtester_setup", [DepthUsingStrategy], indirect=True
)
@pytest.mark.asyncio
async def test_no_trade_when_l2_condition_is_not_met(
    depthsight_backtester_setup, mocker
):
    bt, create_mock_l2_file = depthsight_backtester_setup

    # Enabling threshold
    bt.strategy_instance.foundation_weights = {
        "market_activity": 1,
        "orderbook": 100,
        "trend": 1,
    }
    bt.min_total_foundation_weight_threshold = 90

    signal_fire_idx = 80
    create_mock_l2_file(
        "TESTUSDT", bt.klines.index[signal_fire_idx], has_big_wall=False
    )

    results = await bt.run_async()
    assert results is not None
    assert results["trades"] == 0, (
        "Trade should not have been executed (weight < threshold)"
    )


@pytest.mark.parametrize(
    "depthsight_backtester_setup", [FastFailStrategy], indirect=True
)
@pytest.mark.asyncio
async def test_short_circuit_avoids_l2_read(depthsight_backtester_setup, mocker):
    bt, _ = depthsight_backtester_setup

    if bt.l2_reader:
        mocked_get_book = mocker.patch.object(
            bt.l2_reader, "get_book_snapshot_at", new_callable=AsyncMock
        )
    else:
        bt.l2_reader = MagicMock()
        mocked_get_book = bt.l2_reader.get_book_snapshot_at = AsyncMock()

    mocker.patch.object(config, "USE_COMPANION_ORDERBOOK_ANALYSIS", False)

    bt.max_possible_l2_weight = 50.0
    bt.min_total_foundation_weight_threshold = 90.0

    await bt.run_async()

    mocked_get_book.assert_not_called()


@pytest.mark.parametrize(
    "depthsight_backtester_setup", [NoDepthStrategy, DepthUsingStrategy], indirect=True
)
@pytest.mark.asyncio
async def test_limit_order_fill_and_win(depthsight_backtester_setup, mocker):
    bt, create_mock_l2_file = depthsight_backtester_setup
    signal_fire_idx = 80
    current_price = bt.klines.iloc[signal_fire_idx]["close"]
    limit_entry_price = current_price - 1.0

    if isinstance(bt.strategy_instance, DepthUsingStrategy):
        create_mock_l2_file(
            "TESTUSDT",
            bt.klines.index[signal_fire_idx],
            has_big_wall=True,
            current_price=current_price,
        )

    test_signal = StrategySignal(
        bt.strategy_name,
        "TESTUSDT",
        SignalDirection.LONG,
        mode=OrderMode.LIMIT_RETEST,
        trigger_price=current_price,
        entry_price=limit_entry_price,
        stop_loss=limit_entry_price - 1.0,
        take_profit=limit_entry_price + 2.0,
    )

    mock_foundations_result = (
        {"market_activity": True, "orderbook": True, "trend": True},
        [],
    )
    mocker.patch.object(
        bt.strategy_instance, "check_foundations", return_value=mock_foundations_result
    )

    async def mock_check_signal(pi, md, prev, analysis_level=None):
        if pi["current_candle_index"] == signal_fire_idx:
            return test_signal, 100.0, {}
        return None, 0.0, {}

    bt.strategy_instance.check_signal = mock_check_signal

    # Modifying data
    bt.klines.loc[bt.klines.index[signal_fire_idx + 2], "low"] = limit_entry_price - 0.1
    bt.klines.loc[bt.klines.index[signal_fire_idx + 4], "high"] = (
        limit_entry_price + 2.1
    )

    # IMPORTANT: Updating the backtester's numpy array
    bt.kline_data_array = bt.klines[list(bt.kline_index_map.keys())].to_numpy(
        dtype=np.float64
    )

    results = await bt.run_async()

    assert results["trades"] == 1, "Limit order trade was not executed"
    assert results["wins"] == 1


@pytest.mark.parametrize(
    "depthsight_backtester_setup", [NoDepthStrategy, DepthUsingStrategy], indirect=True
)
@pytest.mark.asyncio
async def test_partial_take_profits_and_be(depthsight_backtester_setup, mocker):
    bt, create_mock_l2_file = depthsight_backtester_setup
    signal_fire_idx = 80
    entry_price = bt.klines.iloc[signal_fire_idx]["close"]

    if isinstance(bt.strategy_instance, DepthUsingStrategy):
        create_mock_l2_file(
            "TESTUSDT",
            bt.klines.index[signal_fire_idx],
            has_big_wall=True,
            current_price=entry_price,
        )

    test_signal = StrategySignal(
        bt.strategy_name,
        "TESTUSDT",
        SignalDirection.LONG,
        mode=OrderMode.MARKET,
        trigger_price=entry_price,
        stop_loss=entry_price - 1.0,
        take_profit=entry_price + 5.0,
        move_sl_to_be_on_first_tp=True,
        partial_targets=[PartialTarget(price=entry_price + 1.0, fraction=0.5)],
    )

    mock_foundations_result = (
        {"market_activity": True, "orderbook": True, "trend": True},
        [],
    )
    mocker.patch.object(
        bt.strategy_instance, "check_foundations", return_value=mock_foundations_result
    )

    async def mock_check_signal(pi, md, prev, analysis_level=None):
        if pi["current_candle_index"] == signal_fire_idx:
            return test_signal, 100.0, {}
        return None, 0.0, {}

    bt.strategy_instance.check_signal = mock_check_signal

    # 0. Ensure that SL is not triggered on the first candle after entry
    bt.klines.loc[bt.klines.index[signal_fire_idx + 1], "high"] = entry_price + 0.5
    bt.klines.loc[bt.klines.index[signal_fire_idx + 1], "low"] = entry_price - 0.5

    # 1. Partial take
    bt.klines.loc[bt.klines.index[signal_fire_idx + 2], "high"] = entry_price + 1.1
    bt.klines.loc[bt.klines.index[signal_fire_idx + 2], "low"] = entry_price + 0.5

    # 2. Does not trigger BE
    bt.klines.loc[bt.klines.index[signal_fire_idx + 3], "high"] = entry_price + 0.8
    bt.klines.loc[bt.klines.index[signal_fire_idx + 3], "low"] = entry_price + 0.1

    # 3. Breakeven hit
    bt.klines.loc[bt.klines.index[signal_fire_idx + 4], "high"] = entry_price + 0.3
    bt.klines.loc[bt.klines.index[signal_fire_idx + 4], "low"] = entry_price - 0.1

    # Updating numpy
    bt.kline_data_array = bt.klines[list(bt.kline_index_map.keys())].to_numpy(
        dtype=np.float64
    )

    results = await bt.run_async()

    assert results["trades"] == 1, "Trade was not opened"
    assert len(bt.trade_log) == 1
    assert "SL_AT_BE" in bt.trade_log[0]["exit_reason"], (
        f"Invalid reason: {bt.trade_log[0].get('exit_reason')}"
    )
    assert bt.trade_log[0]["num_partial_tp_hits"] == 1


@pytest.mark.asyncio
class TestBacktesterV2Lifecycle:
    @pytest.mark.asyncio
    async def test_v2_entry_signal_with_shift(self, v2_backtester_instance):
        v2_config = {
            "filters": {"id": "f_root", "type": "AND", "children": []},
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "e1",
                        "type": "price_condition",
                        "params": {
                            "leftOperand": {
                                "source": "candle",
                                "key": "close",
                                "shift": 0,
                            },
                            "operator": ">",
                            "rightOperand": {"source": "value", "value": 105.0},
                        },
                    }
                ],
            },
            "initialization": {
                "id": "init1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "percent_from_price",
                    "sl_value": 2.0,
                    "tp_type": "percent_from_price",
                    "tp_value": 1.0,
                    "risk_type": "percent_balance",
                    "risk_value": 1.0,
                },
            },
        }

        bt = v2_backtester_instance(v2_config)

        for i in range(60, 70):
            close_val = bt.klines.iloc[i]["close"]
            bt.klines.loc[bt.klines.index[i], "high"] = close_val * 1.02

        bt.kline_data_array = bt.klines[list(bt.kline_index_map.keys())].to_numpy(
            dtype=np.float64
        )

        results = await bt.run_async()
        assert results["trades"] >= 1

    @pytest.mark.asyncio
    async def test_v2_filter_blocks_entry(self, v2_backtester_instance):
        v2_config = {
            "filters": {
                "id": "f_root",
                "type": "AND",
                "children": [
                    {"id": "f1", "type": "trend_filter", "params": {"threshold": 25.0}}
                ],
            },
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "e1",
                        "type": "price_condition",
                        "params": {
                            "leftOperand": {"source": "candle", "key": "close"},
                            "operator": ">",
                            "rightOperand": {"source": "value", "value": 105.0},
                        },
                    }
                ],
            },
            "initialization": {
                "id": "init1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "percent_from_price",
                    "sl_value": 2,
                    "tp_type": "percent_from_price",
                    "tp_value": 1,
                },
            },
        }
        bt = v2_backtester_instance(v2_config)

        for i in range(100, 150):
            close_val = bt.klines.iloc[i]["close"]
            bt.klines.loc[bt.klines.index[i], "high"] = close_val * 1.02

        bt.kline_data_array = bt.klines[list(bt.kline_index_map.keys())].to_numpy(
            dtype=np.float64
        )

        results = await bt.run_async()

        assert results["trades"] > 0
        first_entry_time = bt.trade_log[0]["entry_time"]
        adx_val = bt.klines.loc[first_entry_time]["ADX_14"]
        assert adx_val >= 25.0

    @pytest.mark.asyncio
    async def test_v2_move_to_breakeven_works(self, v2_backtester_instance):
        v2_config = {
            "filters": {"id": "f_root", "type": "AND", "children": []},
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "e1",
                        "type": "price_condition",
                        "params": {
                            "leftOperand": {"source": "candle", "key": "close"},
                            "operator": ">",
                            "rightOperand": {"source": "value", "value": 105.0},
                        },
                    }
                ],
            },
            "initialization": {
                "id": "init1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "percent_from_price",
                    "sl_value": 2,
                    "tp_type": "percent_from_price",
                    "tp_value": 10,
                    "risk_value": 1.0,
                },
            },
            "positionManagement": [
                {
                    "id": "pm1",
                    "type": "move_to_breakeven",
                    "params": {
                        "target_type": "atr_multiplier",
                        "target_value": 2.0,
                        "offset_pips": 5,
                    },
                }
            ],
        }

        bt = v2_backtester_instance(v2_config)
        signal_fire_idx = 60
        entry_price = bt.klines.iloc[signal_fire_idx]["close"]

        bt.klines.loc[bt.klines.index[signal_fire_idx + 2], "high"] = entry_price + 2.5
        bt.klines.loc[bt.klines.index[signal_fire_idx + 2], "low"] = entry_price + 0.5

        bt.klines.loc[bt.klines.index[signal_fire_idx + 3], "high"] = entry_price + 1.0
        bt.klines.loc[bt.klines.index[signal_fire_idx + 3], "low"] = entry_price + 0.2

        bt.klines.loc[bt.klines.index[signal_fire_idx + 4], "high"] = entry_price + 0.5
        bt.klines.loc[bt.klines.index[signal_fire_idx + 4], "low"] = entry_price - 0.1

        bt.kline_data_array = bt.klines[list(bt.kline_index_map.keys())].to_numpy(
            dtype=np.float64
        )

        await bt.run_async()
        assert len(bt.trade_log) >= 1
        assert "SL_AT_BE" in bt.trade_log[0]["exit_reason"]

    @pytest.mark.asyncio
    async def test_v2_fixed_usd_changes_first_entry_size(self, v2_backtester_instance):
        def _config_for_risk(risk_value: float) -> Dict[str, Any]:
            return {
                "filters": {"id": "f_root", "type": "AND", "children": []},
                "entryConditions": {
                    "id": "e_root",
                    "type": "AND",
                    "children": [
                        {
                            "id": "e1",
                            "type": "price_condition",
                            "params": {
                                "leftOperand": {"source": "candle", "key": "close"},
                                "operator": ">",
                                "rightOperand": {"source": "value", "value": 0.0},
                            },
                        }
                    ],
                },
                "initialization": {
                    "id": "init1",
                    "type": "open_position",
                    "params": {
                        "direction": "LONG",
                        "sl_type": "percent_from_price",
                        "sl_value": 0.0,
                        "tp_type": "percent_from_price",
                        "tp_value": 1.0,
                        "risk_type": "fixed_usd",
                        "risk_value": risk_value,
                        "partial_exits": [],
                    },
                },
            }

        async def _run_single_trade(risk_value: float) -> Dict[str, Any]:
            bt = v2_backtester_instance(_config_for_risk(risk_value))
            signal_fire_idx = 60
            entry_price = bt.klines.iloc[signal_fire_idx]["close"]
            bt.klines.loc[bt.klines.index[signal_fire_idx + 1], "high"] = (
                entry_price * 1.02
            )
            bt.kline_data_array = bt.klines[list(bt.kline_index_map.keys())].to_numpy(
                dtype=np.float64
            )

            original_check_signal = bt.strategy_instance.check_signal_sync
            signal_fired = False

            def single_signal_trigger(
                pair_info, market_data, prev_pair_info, *args, **kwargs
            ):
                nonlocal signal_fired
                if (
                    pair_info["current_candle_index"] == signal_fire_idx
                    and not signal_fired
                ):
                    signal_fired = True
                    return original_check_signal(
                        pair_info, market_data, prev_pair_info, *args, **kwargs
                    )
                return None, 0.0, None

            bt.strategy_instance.check_signal_sync = single_signal_trigger

            results = await bt.run_async()
            assert results["trades"] == 1
            assert len(bt.trade_log) == 1
            return bt.trade_log[0]

        trade_100 = await _run_single_trade(100.0)
        trade_300 = await _run_single_trade(300.0)

        assert trade_300["quantity"] == pytest.approx(
            trade_100["quantity"] * 3.0, rel=1e-3
        )
        assert trade_300["pnl"] == pytest.approx(trade_100["pnl"] * 3.0, rel=1e-3)

    @pytest.mark.asyncio
    async def test_v2_level_touch_analyzer_executes_in_backtester(
        self, v2_backtester_instance
    ):
        v2_config = {
            "filters": {"id": "f_root", "type": "AND", "children": []},
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "touch",
                        "type": "level_touch_analyzer",
                        "params": {
                            "level_source": 100.0,
                            "lookback_candles": 20,
                            "touch_tolerance_pct": 0.1,
                            "invalidate_on_pierce": True,
                            "min_touches": 3,
                        },
                    }
                ],
            },
            "initialization": {
                "id": "init1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "percent_from_price",
                    "sl_value": 2.0,
                    "tp_type": "percent_from_price",
                    "tp_value": 1.0,
                    "risk_type": "percent_balance",
                    "risk_value": 1.0,
                },
            },
        }
        bt = v2_backtester_instance(v2_config)
        signal_idx = 60
        window_idx = bt.klines.index[signal_idx - 19 : signal_idx + 1]
        bt.klines.loc[window_idx, "close"] = 99.0
        bt.klines.loc[window_idx, "open"] = 99.0
        bt.klines.loc[window_idx, "high"] = 99.5
        bt.klines.loc[window_idx, "low"] = 98.5
        for idx in [signal_idx - 16, signal_idx - 8, signal_idx]:
            bt.klines.loc[bt.klines.index[idx], "high"] = 100.05
        bt.klines.loc[bt.klines.index[signal_idx + 1], "high"] = 101.5
        bt.kline_data_array = bt.klines[list(bt.kline_index_map.keys())].to_numpy(
            dtype=np.float64
        )

        original_check_signal = bt.strategy_instance.check_signal_sync

        def single_signal_trigger(
            pair_info, market_data, prev_pair_info, *args, **kwargs
        ):
            if pair_info["current_candle_index"] == signal_idx:
                return original_check_signal(
                    pair_info, market_data, prev_pair_info, *args, **kwargs
                )
            return None, 0.0, None

        bt.strategy_instance.check_signal_sync = single_signal_trigger

        results = await bt.run_async()
        assert results["trades"] == 1
        trace = bt.strategy_instance.check_signal_sync(
            {
                "symbol": bt.symbol,
                "atr": 1.0,
                "last_price": float(bt.klines.iloc[signal_idx]["close"]),
                "current_candle_index": signal_idx,
                "candle_timeframe": "1m",
                "timestamp_dt": bt.klines.index[signal_idx].to_pydatetime(),
            },
            {"kline_1m": bt.klines.iloc[: signal_idx + 1]},
            None,
        )[2]
        touch_node = BaseStrategy.find_block_in_trace(trace, "touch")
        assert touch_node["details"]["touches_count"] == 3
        assert touch_node["details"]["is_valid"] is True

    @pytest.mark.asyncio
    async def test_v2_volatility_squeeze_executes_in_backtester(
        self, v2_backtester_instance
    ):
        v2_config = {
            "filters": {"id": "f_root", "type": "AND", "children": []},
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "squeeze",
                        "type": "volatility_squeeze",
                        "params": {
                            "lookback_candles": 20,
                            "squeeze_ratio": 0.6,
                        },
                    }
                ],
            },
            "initialization": {
                "id": "init1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "percent_from_price",
                    "sl_value": 2.0,
                    "tp_type": "percent_from_price",
                    "tp_value": 1.0,
                    "risk_type": "percent_balance",
                    "risk_value": 1.0,
                },
            },
        }
        bt = v2_backtester_instance(v2_config)
        signal_idx = 60
        past_idx = bt.klines.index[signal_idx - 19 : signal_idx - 9]
        current_idx = bt.klines.index[signal_idx - 9 : signal_idx + 1]
        bt.klines.loc[past_idx, ["open", "close"]] = 100.0
        bt.klines.loc[past_idx, "high"] = 105.0
        bt.klines.loc[past_idx, "low"] = 95.0
        bt.klines.loc[current_idx, ["open", "close"]] = 100.0
        bt.klines.loc[current_idx, "high"] = 100.5
        bt.klines.loc[current_idx, "low"] = 99.5
        bt.klines.loc[bt.klines.index[signal_idx + 1], "high"] = 101.5
        bt.kline_data_array = bt.klines[list(bt.kline_index_map.keys())].to_numpy(
            dtype=np.float64
        )

        original_check_signal = bt.strategy_instance.check_signal_sync

        def single_signal_trigger(
            pair_info, market_data, prev_pair_info, *args, **kwargs
        ):
            if pair_info["current_candle_index"] == signal_idx:
                return original_check_signal(
                    pair_info, market_data, prev_pair_info, *args, **kwargs
                )
            return None, 0.0, None

        bt.strategy_instance.check_signal_sync = single_signal_trigger

        results = await bt.run_async()
        assert results["trades"] == 1

    @pytest.mark.asyncio
    async def test_v2_price_action_analyzer_executes_in_backtester(
        self, v2_backtester_instance
    ):
        v2_config = {
            "filters": {"id": "f_root", "type": "AND", "children": []},
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "pa",
                        "type": "price_action_analyzer",
                        "params": {
                            "structure_type": "higher_lows",
                            "lookback_candles": 40,
                            "min_points": 3,
                            "order": 2,
                        },
                    }
                ],
            },
            "initialization": {
                "id": "init1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "percent_from_price",
                    "sl_value": 2.0,
                    "tp_type": "percent_from_price",
                    "tp_value": 1.0,
                    "risk_type": "percent_balance",
                    "risk_value": 1.0,
                },
            },
        }
        bt = v2_backtester_instance(v2_config)
        signal_idx = 60
        window_idx = bt.klines.index[signal_idx - 39 : signal_idx + 1]
        bt.klines.loc[window_idx, ["open", "close"]] = 100.0
        bt.klines.loc[window_idx, "high"] = 101.0
        bt.klines.loc[window_idx, "low"] = 100.0
        for idx, low in [
            (signal_idx - 30, 90.0),
            (signal_idx - 15, 95.0),
            (signal_idx - 2, 98.0),
        ]:
            bt.klines.loc[bt.klines.index[idx], "low"] = low
        bt.klines.loc[bt.klines.index[signal_idx + 1], "high"] = 101.5
        bt.kline_data_array = bt.klines[list(bt.kline_index_map.keys())].to_numpy(
            dtype=np.float64
        )

        original_check_signal = bt.strategy_instance.check_signal_sync

        def single_signal_trigger(
            pair_info, market_data, prev_pair_info, *args, **kwargs
        ):
            if pair_info["current_candle_index"] == signal_idx:
                return original_check_signal(
                    pair_info, market_data, prev_pair_info, *args, **kwargs
                )
            return None, 0.0, None

        bt.strategy_instance.check_signal_sync = single_signal_trigger

        results = await bt.run_async()
        assert results["trades"] == 1


@pytest.mark.asyncio
async def test_depthsight_backtester_l2_market_impact(tmp_path, mocker):
    strategy_class = DepthUsingStrategy
    l2_storage_path = tmp_path / "L2_data"

    mocker.patch.dict(
        strategy_module.STRATEGIES, {strategy_class.NAME: strategy_class}, clear=True
    )
    mocker.patch.object(strategy_module, "_strategy_instances", {})
    mocker.patch.object(config, "DYNAMIC_SELECTION_REL_VOL_THRESHOLD", 0.1)
    mocker.patch.object(config, "DYNAMIC_SELECTION_NATR_THRESHOLD", 0.1)
    mocker.patch("bot_module.depthsight_backtester.PANDAS_TA_AVAILABLE", True)
    mock_ta = mocker.patch("bot_module.depthsight_backtester.ta")

    klines = create_base_kline_data(num_rows=200)
    mock_ta.atr.return_value = pd.Series(np.full(len(klines), 1.0), index=klines.index)

    adx_df = pd.DataFrame({"ADX_14": np.full(len(klines), 25)}, index=klines.index)
    mock_ta.adx.return_value = adx_df
    klines["ADX_14"] = 25.0

    signal_fire_idx = 80
    signal_time = klines.index[signal_fire_idx]
    kline_at_signal = klines.loc[signal_time]

    l2_reader = L2HistoricalDataReader(str(l2_storage_path))
    file_path = l2_reader._get_l2_data_path(
        "TESTUSDT", int(signal_time.timestamp() * 1000)
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)

    ask_price_l2 = kline_at_signal["close"] + 0.1

    l2_snapshot_data = {
        "ts": int(signal_time.timestamp() * 1000),
        "bids": [[f"{kline_at_signal['close'] - 0.1}", "10"]],
        "asks": [[f"{ask_price_l2}", "100000"]],
        "nonce": 123,
    }

    with open(file_path, "wb") as f:
        packer = msgpack.Packer()
        f.write(zstandard.ZstdCompressor().compress(packer.pack(l2_snapshot_data)))

    risk_params = {
        "riskPerTradePercent": 0.1,
        "risk_pct_per_trade": 0.001,
        "max_stop_distance_pct": 0.05,
    }

    bt = DepthSightBacktester(
        strategy_class.NAME,
        "TESTUSDT",
        {},
        {"kline_1m": klines},
        10000,
        1,
        risk_params,
        risk_params,
        {"commission_pct": 0.001, "slippage_pct": 0.0},
        {strategy_class.NAME: {"risk_pct_per_trade": 0.001}},
        {},
        None,
        l2_storage_path=str(l2_storage_path),
        foundation_weights={"market_activity": 100},
        min_foundation_weight_threshold=0.0,
        exchange_info={
            "tick_size": 0.01,
            "lot_params": {"stepSize": "0.001"},
            "min_notional": 0.0,
        },
    )

    test_signal = StrategySignal(
        bt.strategy_name,
        "TESTUSDT",
        SignalDirection.LONG,
        mode=OrderMode.MARKET,
        trigger_price=kline_at_signal["close"],
        stop_loss=kline_at_signal["close"] * 0.99,
        take_profit=kline_at_signal["close"] * 1.02,
    )

    mock_foundations_result = (
        {"market_activity": True, "orderbook": True, "trend": True},
        [],
    )
    mocker.patch.object(
        bt.strategy_instance, "check_foundations", return_value=mock_foundations_result
    )

    async def mock_check_signal(pi, md, prev, analysis_level=None):
        if pi["current_candle_index"] == signal_fire_idx:
            return test_signal, 100.0, {}
        return None, 0.0, {}

    bt.strategy_instance.check_signal = mock_check_signal

    results = await bt.run_async()

    assert results is not None
    assert results["trades"] == 1

    trade_log_entry = bt.trade_log[0]

    assert trade_log_entry["entry_price"] == pytest.approx(ask_price_l2)
    assert trade_log_entry.get("entry_fill_type") == "L2MarketImpact"

    if l2_storage_path.exists():
        shutil.rmtree(l2_storage_path)
