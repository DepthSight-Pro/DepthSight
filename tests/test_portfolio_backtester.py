# FILE: tests/test_portfolio_backtester.py

import copy
import pytest
import pandas as pd
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from bot_module.portfolio_backtester import PortfolioBacktester
from bot_module.strategy import (
    StrategySignal,
    SignalDirection,
    OrderMode,
    BaseStrategy,
    STRATEGIES,
    VolumeBreakoutStrategy,
    FakeBreakoutStrategy,
)

# Register strategies for testing since they are not default allowed strategies in production config
STRATEGIES["VolumeBreakout"] = VolumeBreakoutStrategy
STRATEGIES["FakeBreakout"] = FakeBreakoutStrategy


@pytest.fixture(autouse=True)
def register_test_strategies():
    from bot_module import strategy as strat_mod

    strat_mod.STRATEGIES["VolumeBreakout"] = VolumeBreakoutStrategy
    strat_mod.STRATEGIES["FakeBreakout"] = FakeBreakoutStrategy
    STRATEGIES["VolumeBreakout"] = VolumeBreakoutStrategy
    STRATEGIES["FakeBreakout"] = FakeBreakoutStrategy
    yield
    strat_mod.STRATEGIES["VolumeBreakout"] = VolumeBreakoutStrategy
    strat_mod.STRATEGIES["FakeBreakout"] = FakeBreakoutStrategy
    STRATEGIES["VolumeBreakout"] = VolumeBreakoutStrategy
    STRATEGIES["FakeBreakout"] = FakeBreakoutStrategy


# --- Fixtures ---


@pytest.fixture
def sample_contracts_config():
    return [
        {
            "id": "BTC_VB_1h",
            "strategy_name": "VolumeBreakout",
            "symbol": "BTCUSDT",
            "market_type": "spot",
            "exchange_rules": {
                "symbol": "BTCUSDT",
                "tick_size": 0.01,
                "step_size": 0.00001,
                "min_qty": 0.00001,
                "max_qty": 1000.0,
                "min_notional": 5.0,
            },
            "params": {
                "tf": "1h",
                "stop_loss_atr_multiplier": 1.0,
                "take_profit_atr_multiplier": 1.5,
                "atr_period": 14,
                "enabled": True,
            },
        },
        {
            "id": "ETH_FB_1h",
            "strategy_name": "FakeBreakout",
            "symbol": "ETHUSDT",
            "market_type": "spot",
            "exchange_rules": {
                "symbol": "ETHUSDT",
                "tick_size": 0.01,
                "step_size": 0.0001,
                "min_qty": 0.0001,
                "max_qty": 1000.0,
                "min_notional": 5.0,
            },
            "params": {
                "tf": "1h",
                "lookback_candles": 10,
                "atr_period": 14,
                "enabled": True,
            },
        },
    ]


@pytest.fixture
def sample_risk_limits():
    return {
        "max_total_exposure_pct": 2.5,
        "max_concurrent_positions": 1,
        "commission_pct": 0.001,
        "risk_pct_per_trade": 0.01,
    }


@pytest.fixture
def mock_market_data():
    btc_data = pd.DataFrame(
        {
            "open": [20000.0, 20100.0, 20050.0, 20200.0],
            "high": [20200.0, 20150.0, 20100.0, 20300.0],
            "low": [19900.0, 20000.0, 20000.0, 20150.0],
            "close": [20100.0, 20050.0, 20080.0, 20250.0],
            "volume": [100.0, 110.0, 120.0, 130.0],
        },
        index=pd.to_datetime(
            [
                "2023-01-01 10:00",
                "2023-01-01 11:00",
                "2023-01-01 12:00",
                "2023-01-01 13:00",
            ],
            utc=True,
        ),
    )

    eth_data = pd.DataFrame(
        {
            "open": [1500.0, 1510.0, 1505.0, 1520.0],
            "high": [1520.0, 1515.0, 1510.0, 1530.0],
            "low": [1490.0, 1500.0, 1500.0, 1515.0],
            "close": [1510.0, 1505.0, 1508.0, 1525.0],
            "volume": [200.0, 210.0, 220.0, 230.0],
        },
        index=pd.to_datetime(
            [
                "2023-01-01 10:00",
                "2023-01-01 11:00",
                "2023-01-01 12:00",
                "2023-01-01 13:00",
            ],
            utc=True,
        ),
    )

    return {("BTCUSDT", "1h"): btc_data, ("ETHUSDT", "1h"): eth_data}


# --- The test now needs to be async to call the async run_backtest ---
@patch("bot_module.portfolio_backtester.download_klines")
async def test_portfolio_backtester_initialization(
    mock_download, sample_contracts_config, sample_risk_limits, mock_market_data
):
    async def mock_download_klines(symbol, timeframe, **kwargs):
        return mock_market_data.get((symbol, timeframe))

    mock_download.side_effect = mock_download_klines

    pb = PortfolioBacktester(
        initial_balance=10000.0,
        start_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2023, 1, 2, tzinfo=timezone.utc),
        contracts=sample_contracts_config,
        global_risk_limits=sample_risk_limits,
    )

    await pb.run_backtest()

    assert pb.initial_balance == 10000.0
    assert len(pb.strategy_instances) == 2
    assert "BTC_VB_1h" in pb.strategy_instances
    assert "ETH_FB_1h" in pb.strategy_instances
    assert isinstance(pb.strategy_instances["BTC_VB_1h"], BaseStrategy)
    assert not pb.market_data[("BTCUSDT", "1h")].empty
    assert "atr" in pb.market_data[("BTCUSDT", "1h")].columns


@patch("bot_module.portfolio_backtester.download_klines")
async def test_run_backtest_and_generate_trades(
    mock_download, sample_contracts_config, sample_risk_limits, mock_market_data
):
    async def mock_download_klines(symbol, timeframe, **kwargs):
        return mock_market_data.get((symbol, timeframe))

    mock_download.side_effect = mock_download_klines

    mock_btc_signal = StrategySignal(
        "VolumeBreakoutStrategy",
        "BTCUSDT",
        SignalDirection.LONG,
        stop_loss=20000.0,
        take_profit=20300.0,
        trigger_price=20100.0,
        mode=OrderMode.MARKET,
    )
    mock_eth_signal = StrategySignal(
        "FakeBreakoutStrategy",
        "ETHUSDT",
        SignalDirection.LONG,
        stop_loss=1500.0,
        take_profit=1550.0,
        trigger_price=1510.0,
        mode=OrderMode.MARKET,
    )

    def extract_close_from_args(*args, **kwargs):
        kline = kwargs.get("kline")
        if kline is None and len(args) > 0:
            for arg in args:
                if isinstance(arg, (dict, pd.Series)) and (
                    "close" in arg or hasattr(arg, "get")
                ):
                    kline = arg
                    break
        try:
            if kline is not None:
                return float(kline["close"])
        except Exception:
            pass
        return 0.0

    def check_signal_sync_dispatcher(self, *args, **kwargs):
        strat_name = getattr(self, "NAME", "") or getattr(
            self, "strategy_name", ""
        )
        close_price = extract_close_from_args(*args, **kwargs)

        if strat_name == "VolumeBreakout" or "BTC" in getattr(
            self, "contract_id", ""
        ):
            if abs(close_price - 20100.0) < 1e-4:
                return [copy.deepcopy(mock_btc_signal)]
        elif strat_name == "FakeBreakout" or "ETH" in getattr(
            self, "contract_id", ""
        ):
            if abs(close_price - 1510.0) < 1e-4:
                return [copy.deepcopy(mock_eth_signal)]
        return []

    with (
        patch.object(
            BaseStrategy,
            "check_signal_sync",
            check_signal_sync_dispatcher,
        ),
        patch.object(
            VolumeBreakoutStrategy,
            "check_signal_sync",
            check_signal_sync_dispatcher,
        ),
        patch.object(
            FakeBreakoutStrategy,
            "check_signal_sync",
            check_signal_sync_dispatcher,
        ),
    ):
        pb = PortfolioBacktester(
            initial_balance=10000.0,
            start_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2023, 1, 2, tzinfo=timezone.utc),
            contracts=sample_contracts_config,
            global_risk_limits=sample_risk_limits,
        )

        kpis = await pb.run_backtest()

        assert len(pb.trade_log) == 1
        assert kpis["total_trades"] == 1

        trade = pb.trade_log[0]
        assert trade["symbol"] == "BTCUSDT"
        assert trade["strategy_name"] == "VolumeBreakout"
        assert trade["exit_reason"] == "STOP_LOSS"
        assert trade["exit_price"] == pytest.approx(19990.0)
        assert trade["pnl_net_total_trade"] < 0

        assert pb.current_balance != pb.initial_balance
        assert len(pb.equity_curve) > 2


@patch("bot_module.portfolio_backtester.download_klines")
async def test_l2_impact_changes_fill_price(
    mock_download, sample_contracts_config, sample_risk_limits, mock_market_data
):
    async def mock_download_klines(symbol, timeframe, **kwargs):
        return mock_market_data.get((symbol, timeframe))

    mock_download.side_effect = mock_download_klines

    mock_l2_reader = MagicMock()

    async def get_book_snapshot_at(symbol, timestamp_ms):
        return {
            "bids": [["20099.0", "10.0"]],
            "asks": [["20105.0", "0.1"], ["20110.0", "0.2"]],
            "ts": timestamp_ms,
        }

    mock_l2_reader.get_book_snapshot_at = get_book_snapshot_at

    mock_signal = StrategySignal(
        strategy_name="VolumeBreakoutStrategy",
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        stop_loss=20000.0,
        take_profit=20300.0,
        trigger_price=20100.0,
        mode=OrderMode.MARKET,
    )

    class SingleSignalEmitter:
        def __init__(self, signal_to_emit, trigger_kline_close_price):
            self.signal_to_emit = signal_to_emit
            self.trigger_kline_close_price = trigger_kline_close_price
            self.emitted_count = 0

        def __call__(self, *args, **kwargs):
            kline = kwargs.get("kline")
            if kline is None and len(args) > 0:
                for arg in args:
                    if isinstance(arg, (dict, pd.Series)) and (
                        "close" in arg or hasattr(arg, "get")
                    ):
                        kline = arg
                        break
            try:
                kline_close = (
                    float(kline["close"]) if kline is not None else 0.0
                )
            except Exception:
                kline_close = 0.0

            if (
                self.emitted_count == 0
                and abs(kline_close - self.trigger_kline_close_price) < 1e-4
            ):
                self.emitted_count += 1
                return [copy.deepcopy(self.signal_to_emit)]
            return []

    def make_emitter_dispatcher(emitter):
        def _dispatcher(self, *args, **kwargs):
            return emitter(*args, **kwargs)

        return _dispatcher

    emitter_no_l2 = SingleSignalEmitter(mock_signal, 20100.0)
    with (
        patch.object(
            BaseStrategy,
            "check_signal_sync",
            make_emitter_dispatcher(emitter_no_l2),
        ),
        patch.object(
            VolumeBreakoutStrategy,
            "check_signal_sync",
            make_emitter_dispatcher(emitter_no_l2),
        ),
    ):
        pb_no_l2 = PortfolioBacktester(
            initial_balance=10000.0,
            start_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2023, 1, 2, tzinfo=timezone.utc),
            contracts=[sample_contracts_config[0]],
            global_risk_limits=sample_risk_limits,
            l2_reader=None,
        )
        await pb_no_l2.run_backtest()

    emitter_with_l2 = SingleSignalEmitter(mock_signal, 20100.0)
    with (
        patch.object(
            BaseStrategy,
            "check_signal_sync",
            make_emitter_dispatcher(emitter_with_l2),
        ),
        patch.object(
            VolumeBreakoutStrategy,
            "check_signal_sync",
            make_emitter_dispatcher(emitter_with_l2),
        ),
    ):
        pb_with_l2 = PortfolioBacktester(
            initial_balance=10000.0,
            start_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2023, 1, 2, tzinfo=timezone.utc),
            contracts=[sample_contracts_config[0]],
            global_risk_limits=sample_risk_limits,
            l2_reader=mock_l2_reader,
        )
        await pb_with_l2.run_backtest()

    assert len(pb_no_l2.trade_log) == 1, "Expected 1 trade without L2 data"
    assert len(pb_with_l2.trade_log) == 1, "Expected 1 trade with L2 data"

    trade_no_l2 = pb_no_l2.trade_log[0]
    trade_with_l2 = pb_with_l2.trade_log[0]

    assert trade_no_l2["entry_price"] == pytest.approx(20110.05)
    assert trade_with_l2["entry_price"] == pytest.approx(20108.3333, abs=1e-4)
    assert trade_no_l2["entry_price"] != trade_with_l2["entry_price"]

    assert "slippage_usd" in trade_with_l2["l2_entry_details"]
    assert trade_with_l2["l2_entry_details"]["slippage_usd"] > 0
