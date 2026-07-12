# FILE: tests/test_portfolio_backtester.py

import pytest
import pandas as pd
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

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

# --- Fixtures ---


@pytest.fixture
def sample_contracts_config():
    return [
        {
            "id": "BTC_VB_1h",
            "strategy_name": "VolumeBreakout",
            "symbol": "BTCUSDT",
            "market_type": "spot",
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
            "open": [20000, 20100, 20050, 20200],
            "high": [20200, 20150, 20100, 20300],
            "low": [19900, 20000, 20000, 20150],
            "close": [20100, 20050, 20080, 20250],
            "volume": [100, 110, 120, 130],
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
            "open": [1500, 1510, 1505, 1520],
            "high": [1520, 1515, 1510, 1530],
            "low": [1490, 1500, 1500, 1515],
            "close": [1510, 1505, 1508, 1525],
            "volume": [200, 210, 220, 230],
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
@patch("bot_module.portfolio_backtester.download_klines", new_callable=AsyncMock)
async def test_portfolio_backtester_initialization(
    mock_download, sample_contracts_config, sample_risk_limits, mock_market_data
):
    mock_download.side_effect = lambda symbol, timeframe, **kwargs: (
        mock_market_data.get((symbol, timeframe))
    )

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


@patch("bot_module.portfolio_backtester.download_klines", new_callable=AsyncMock)
async def test_run_backtest_and_generate_trades(
    mock_download, sample_contracts_config, sample_risk_limits, mock_market_data
):
    mock_download.side_effect = lambda symbol, timeframe, **kwargs: (
        mock_market_data.get((symbol, timeframe))
    )

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

    def btc_check_signal_sync_side_effect(*args, **kwargs):
        kline = kwargs.get("kline")
        if (
            kline is not None
            and isinstance(kline.get("close"), (int, float))
            and abs(kline["close"] - 20100.0) < 1e-9
        ):
            return [mock_btc_signal]
        return []

    def eth_check_signal_sync_side_effect(*args, **kwargs):
        kline = kwargs.get("kline")
        if (
            kline is not None
            and isinstance(kline.get("close"), (int, float))
            and abs(kline["close"] - 1510.0) < 1e-9
        ):
            return [mock_eth_signal]
        return []

    with (
        patch(
            "bot_module.strategy.VolumeBreakoutStrategy.check_signal_sync",
            side_effect=btc_check_signal_sync_side_effect,
        ),
        patch(
            "bot_module.strategy.FakeBreakoutStrategy.check_signal_sync",
            side_effect=eth_check_signal_sync_side_effect,
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


@patch("bot_module.portfolio_backtester.download_klines", new_callable=AsyncMock)
async def test_l2_impact_changes_fill_price(
    mock_download, sample_contracts_config, sample_risk_limits, mock_market_data
):
    mock_download.side_effect = lambda symbol, timeframe, **kwargs: (
        mock_market_data.get((symbol, timeframe))
    )

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
            if (
                self.emitted_count == 0
                and kline is not None
                and isinstance(kline.get("close"), (int, float))
                and abs(kline["close"] - self.trigger_kline_close_price) < 1e-9
            ):
                self.emitted_count += 1
                return [self.signal_to_emit]
            return []

    with patch(
        "bot_module.strategy.VolumeBreakoutStrategy.check_signal_sync"
    ) as mock_vb_check_signal_sync:
        emitter_no_l2 = SingleSignalEmitter(mock_signal, 20100.0)
        mock_vb_check_signal_sync.side_effect = emitter_no_l2

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
        mock_vb_check_signal_sync.side_effect = emitter_with_l2

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
