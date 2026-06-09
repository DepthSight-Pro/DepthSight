# tests/test_risk_manager.py
import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import math
import logging
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone, timedelta

try:
    from bot_module.risk_manager import RiskManager, SymbolStrategyPerformanceStats
    from bot_module.strategy import StrategySignal, SignalDirection, OrderMode
    from bot_module.exchanges import ExchangeExecutor
    from api import crud, models
except ImportError:
    pytest.skip(
        "Cannot import bot_module/api components for RiskManager tests.",
        allow_module_level=True,
    )

# --- Fixtures ---


@pytest.fixture
def mock_executor():
    executor = AsyncMock(spec=ExchangeExecutor)
    executor.get_account_balance.return_value = {
        "USDT": {"free": "10000.00", "locked": "0.00"}
    }
    return executor


@pytest_asyncio.fixture
async def risk_manager(mock_executor, db_session, test_user):
    """
    Creates a RiskManager instance with user settings and a DB mock.
    """
    # 1. Define custom settings for the test
    user_settings = {
        "risk_management": {
            "dailyMaxLossPercent": 5.0,
            "riskPerTradePercent": 1.0,
            "maxConsecutiveLosses": 3,
            "minRrRatio": 2.0,
            "strategySymbolAdjustmentEnabled": True,
            "strategySymbolWindowSize": 5,
            "strategySymbolMinTradesForAssessment": 3,
            "strategySymbolPnlThresholdPct": -100.0,  # -1.0 in the old format
            "strategySymbolWinRateThresholdPct": 40.0,
            "strategySymbolMaxConsecutiveLosses": 2,
            "strategySymbolRecoveryConsecutiveWins": 2,
            "strategySymbolRecoveryPnlThresholdPct": 50.0,  # 0.5 in the old format
            "strategySymbolCooldownAfterPenaltySeconds": 300,
        }
    }

    # 2. Create a RiskManager instance, passing the settings
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings=user_settings,
    )

    # 3. Calling asynchronous initialization
    # In a real test, it will attempt to load data from an empty DB
    await rm.initialize()

    assert rm.stats.current_balance == 10000.0
    # Check that specifically user settings were applied
    assert rm.risk_per_trade == 0.01
    assert rm._strategy_symbol_window_size == 5
    assert rm._strategy_symbol_max_consec_loss == 2

    yield rm


@pytest.fixture
def sample_signal_long():
    return StrategySignal(
        strategy_name="TestStrat",
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        trigger_price=50000.0,
        stop_loss=49500.0,
        take_profit=51000.0,
        mode=OrderMode.MARKET,
    )


@pytest.fixture
def sample_signal_short():
    return StrategySignal(
        strategy_name="TestStrat",
        symbol="BTCUSDT",
        direction=SignalDirection.SHORT,
        trigger_price=50000.0,
        stop_loss=50500.0,
        take_profit=49000.0,
        mode=OrderMode.MARKET,
    )


# --- Tests ---


@pytest.mark.asyncio
async def test_assess_signal_normal_long(risk_manager, sample_signal_long):
    lot_params = {"minQty": 0.0001, "maxQty": 9000.0, "stepSize": 0.00001}
    min_notional = 10.0
    expected_base_risk_usd = 10000.0 * risk_manager.risk_per_trade
    default_multiplier = risk_manager._strategy_symbol_risk_multipliers[
        risk_manager._s_s_default_risk_idx
    ]
    assert default_multiplier == 1.0
    expected_sizing_risk_usd = expected_base_risk_usd * default_multiplier
    stop_distance = 50000.0 - 49500.0
    expected_base_qty = expected_sizing_risk_usd / stop_distance
    step_dec = Decimal(str(lot_params["stepSize"]))
    base_dec = Decimal(str(expected_base_qty))
    expected_adj_qty = float(
        (base_dec / step_dec).quantize(Decimal("0"), rounding=ROUND_DOWN) * step_dec
    )
    approved, quantity, initial_risk_planned, _ = await risk_manager.assess_signal(
        sample_signal_long, lot_params, min_notional
    )
    assert approved is True
    assert quantity is not None
    assert math.isclose(quantity, expected_adj_qty, rel_tol=1e-9)
    assert initial_risk_planned is not None
    assert math.isclose(initial_risk_planned, expected_base_risk_usd, rel_tol=1e-9)


@pytest.mark.asyncio
async def test_assess_signal_normal_short(risk_manager, sample_signal_short):
    lot_params = {"minQty": 0.0001, "maxQty": 9000.0, "stepSize": 0.00001}
    min_notional = 10.0
    expected_base_risk_usd = 10000.0 * risk_manager.risk_per_trade
    default_multiplier = risk_manager._strategy_symbol_risk_multipliers[
        risk_manager._s_s_default_risk_idx
    ]
    expected_sizing_risk_usd = expected_base_risk_usd * default_multiplier
    stop_distance = 50500.0 - 50000.0
    expected_base_qty = expected_sizing_risk_usd / stop_distance
    step_dec = Decimal(str(lot_params["stepSize"]))
    base_dec = Decimal(str(expected_base_qty))
    expected_adj_qty = float(
        (base_dec / step_dec).quantize(Decimal("0"), rounding=ROUND_DOWN) * step_dec
    )
    approved, quantity, initial_risk_planned, _ = await risk_manager.assess_signal(
        sample_signal_short, lot_params, min_notional
    )
    assert approved is True
    assert quantity is not None
    assert math.isclose(quantity, expected_adj_qty, rel_tol=1e-9)
    assert initial_risk_planned is not None
    assert math.isclose(initial_risk_planned, expected_base_risk_usd, rel_tol=1e-9)


@pytest.mark.asyncio
async def test_assess_signal_skips_min_rr_for_dca_grid_strategy(risk_manager):
    lot_params = {"minQty": 0.0001, "maxQty": 9000.0, "stepSize": 0.00001}
    min_notional = 10.0
    signal = StrategySignal(
        strategy_name="DcaGridStrategy",
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        trigger_price=50000.0,
        stop_loss=49000.0,
        take_profit=50500.0,
        mode=OrderMode.MARKET,
        details={
            "uses_dca_or_grid_management": True,
            "skip_min_rr_for_dca_grid": True,
        },
    )

    approved, quantity, initial_risk_planned, reason = await risk_manager.assess_signal(
        signal,
        lot_params,
        min_notional,
    )

    assert approved is True
    assert quantity is not None and quantity > 0
    assert initial_risk_planned is not None and initial_risk_planned > 0
    assert reason is None


@pytest.mark.asyncio
async def test_assess_signal_trading_disabled(
    risk_manager, sample_signal_long, mock_executor
):
    low_balance = risk_manager.min_balance_threshold - 1.0
    mock_executor.get_account_balance.return_value = {
        "USDT": {"free": str(low_balance), "locked": "0.00"}
    }
    expected_base_risk_usd = low_balance * risk_manager.risk_per_trade
    approved, quantity, initial_risk_planned, _ = await risk_manager.assess_signal(
        sample_signal_long, {}, None
    )
    assert approved is False
    assert quantity is None
    assert risk_manager._is_trading_allowed is False
    assert initial_risk_planned is not None
    assert math.isclose(initial_risk_planned, expected_base_risk_usd, rel_tol=1e-9)
    mock_executor.get_account_balance.return_value = {
        "USDT": {"free": "10000.00", "locked": "0.00"}
    }
    await risk_manager.initialize_balance()


@pytest.mark.asyncio
async def test_assess_signal_low_balance(
    risk_manager, sample_signal_long, mock_executor
):
    low_balance_for_test = 99.0
    original_min_balance = risk_manager.min_balance_threshold
    risk_manager.min_balance_threshold = low_balance_for_test + 1.0
    mock_executor.get_account_balance.return_value = {
        "USDT": {"free": str(low_balance_for_test), "locked": "0.00"}
    }
    expected_base_risk_usd = low_balance_for_test * risk_manager.risk_per_trade
    approved, quantity, initial_risk_planned, _ = await risk_manager.assess_signal(
        sample_signal_long, {}, None
    )
    assert approved is False
    assert quantity is None
    assert risk_manager._is_trading_allowed is False
    assert initial_risk_planned is not None
    assert math.isclose(initial_risk_planned, expected_base_risk_usd, rel_tol=1e-9)
    risk_manager.min_balance_threshold = original_min_balance
    mock_executor.get_account_balance.return_value = {
        "USDT": {"free": "10000.00", "locked": "0.00"}
    }
    await risk_manager.initialize_balance()


@pytest.mark.asyncio
async def test_assess_signal_zero_stop_distance(risk_manager, sample_signal_long):
    signal = sample_signal_long
    signal.stop_loss = signal.trigger_price
    expected_base_risk_usd = (
        risk_manager.stats.current_balance * risk_manager.risk_per_trade
    )
    approved, quantity, initial_risk_planned, _ = await risk_manager.assess_signal(
        signal, {}, None
    )
    assert approved is False
    assert quantity is None
    assert initial_risk_planned is not None
    assert math.isclose(initial_risk_planned, expected_base_risk_usd, rel_tol=1e-9)


@pytest.mark.asyncio
async def test_assess_signal_uses_risk_multiplier(
    risk_manager, sample_signal_long, mock_executor
):
    symbol = sample_signal_long.symbol
    strategy_name = sample_signal_long.strategy_name
    perf_key = (symbol, strategy_name)
    mock_executor.get_account_balance.return_value = {
        "USDT": {"free": "10000.00", "locked": "0.00"}
    }
    await risk_manager.update_balance()
    risk_manager._is_trading_allowed = True
    stats_obj = risk_manager._symbol_strategy_performance[perf_key]
    target_idx_reduced = 1
    stats_obj.current_risk_multiplier_index = target_idx_reduced
    lot_params = {"minQty": 0.0001, "maxQty": 9000.0, "stepSize": 0.00001}
    min_notional = 10.0
    expected_base_risk_usd = 10000.0 * risk_manager.risk_per_trade
    applied_multiplier = risk_manager._strategy_symbol_risk_multipliers[
        target_idx_reduced
    ]
    expected_sizing_risk_usd = expected_base_risk_usd * applied_multiplier
    stop_distance = 50000.0 - 49500.0
    expected_base_qty_after_multiplier = expected_sizing_risk_usd / stop_distance
    step_dec = Decimal(str(lot_params["stepSize"]))
    base_dec_multiplied = Decimal(str(expected_base_qty_after_multiplier))
    expected_adj_qty = float(
        (base_dec_multiplied / step_dec).quantize(Decimal("0"), rounding=ROUND_DOWN)
        * step_dec
    )
    approved, quantity, initial_risk_planned, _ = await risk_manager.assess_signal(
        sample_signal_long, lot_params, min_notional
    )
    assert approved is True
    assert quantity is not None
    assert math.isclose(quantity, expected_adj_qty, rel_tol=1e-9)
    assert initial_risk_planned is not None
    assert math.isclose(initial_risk_planned, expected_base_risk_usd, rel_tol=1e-9)
    stats_obj.current_risk_multiplier_index = risk_manager._s_s_default_risk_idx


@pytest.mark.asyncio
async def test_assess_signal_uses_fixed_usd_budget_without_stop(risk_manager):
    signal = StrategySignal(
        strategy_name="TestStrat",
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        trigger_price=50000.0,
        stop_loss=None,
        take_profit=51000.0,
        mode=OrderMode.MARKET,
        risk_usd=300.0,
    )
    lot_params = {"minQty": 0.0001, "maxQty": 9000.0, "stepSize": 0.00001}
    approved, quantity, initial_risk_planned, _ = await risk_manager.assess_signal(
        signal, lot_params, 10.0
    )

    step_dec = Decimal(str(lot_params["stepSize"]))
    expected_qty = float(
        (Decimal(str(300.0 / 50000.0)) / step_dec).quantize(
            Decimal("0"), rounding=ROUND_DOWN
        )
        * step_dec
    )

    assert approved is True
    assert initial_risk_planned == pytest.approx(300.0)
    assert quantity == pytest.approx(expected_qty, rel=1e-9)


@pytest.mark.asyncio
async def test_update_performance_buffer_and_stats(risk_manager, caplog):
    bot_module_actual_logger = logging.getLogger("bot_module")
    original_bot_module_propagate_status = bot_module_actual_logger.propagate
    bot_module_actual_logger.propagate = True

    try:
        symbol = "BTCUSDT"
        strategy_name = "TestStrat"
        perf_key = (symbol, strategy_name)

        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, pnl_usd=50.0, initial_risk_usd_planned=100.0
        )
        stats = risk_manager._symbol_strategy_performance[perf_key]
        assert stats.current_consecutive_losses == 0
        assert stats.current_consecutive_wins_for_recovery == 1
        assert stats.current_risk_multiplier_index == risk_manager._s_s_default_risk_idx

        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, pnl_usd=-30.0, initial_risk_usd_planned=100.0
        )
        stats = risk_manager._symbol_strategy_performance[perf_key]
        assert stats.current_consecutive_losses == 1
        assert stats.current_consecutive_wins_for_recovery == 0
        assert stats.current_risk_multiplier_index == risk_manager._s_s_default_risk_idx

        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, pnl_usd=20.0, initial_risk_usd_planned=100.0
        )
        stats = risk_manager._symbol_strategy_performance[perf_key]
        assert stats.current_consecutive_losses == 0
        assert stats.current_consecutive_wins_for_recovery == 1
        assert stats.current_risk_multiplier_index == risk_manager._s_s_default_risk_idx

        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, pnl_usd=-10.0, initial_risk_usd_planned=100.0
        )
        stats = risk_manager._symbol_strategy_performance[perf_key]
        assert stats.current_consecutive_losses == 1
        assert stats.current_consecutive_wins_for_recovery == 0
        assert stats.current_risk_multiplier_index == risk_manager._s_s_default_risk_idx

        caplog.clear()
        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, pnl_usd=40.0, initial_risk_usd_planned=100.0
        )
        stats = risk_manager._symbol_strategy_performance[perf_key]
        assert stats.current_consecutive_losses == 0
        assert stats.current_consecutive_wins_for_recovery == 0
        assert (
            stats.current_risk_multiplier_index
            == risk_manager._s_s_default_risk_idx + 1
        )
        assert any(
            "RISK ENHANCED" in record.message or "RISK RECOVERED" in record.message
            for record in caplog.records
            if record.levelname == "INFO"
        )

        caplog.clear()
        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, pnl_usd=-25.0, initial_risk_usd_planned=100.0
        )
        stats = risk_manager._symbol_strategy_performance[perf_key]
        assert stats.current_consecutive_losses == 1
        assert stats.current_consecutive_wins_for_recovery == 0
        assert (
            stats.current_risk_multiplier_index
            == risk_manager._s_s_default_risk_idx + 1
        )
        assert not any(
            "RISK REDUCED" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )
    finally:
        bot_module_actual_logger.propagate = original_bot_module_propagate_status


@pytest.mark.asyncio
async def test_performance_risk_reduction_and_recovery(risk_manager, caplog):
    bot_module_actual_logger = logging.getLogger("bot_module")
    original_bot_module_propagate_status = bot_module_actual_logger.propagate
    bot_module_actual_logger.propagate = True
    try:
        logging.getLogger("bot_module.risk_manager").setLevel(logging.DEBUG)
        caplog.set_level(logging.DEBUG)

        symbol = "ETHUSDT"
        strategy_name = "TrendFollow"
        default_idx = risk_manager._s_s_default_risk_idx
        stats = risk_manager._symbol_strategy_performance[(symbol, strategy_name)]
        assert stats.current_risk_multiplier_index == default_idx

        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, 10.0, 100.0
        )
        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, 10.0, 100.0
        )
        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, -10.0, 100.0
        )

        caplog.clear()
        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, -10.0, 100.0
        )
        stats = risk_manager._symbol_strategy_performance[(symbol, strategy_name)]
        assert stats.current_risk_multiplier_index == default_idx - 1
        assert stats.last_penalty_timestamp > 0
        last_penalty_ts_reduction = stats.last_penalty_timestamp

        reduction_log_found = False
        for record in caplog.records:
            if (
                record.levelname == "WARNING"
                and "RISK REDUCED" in record.message
                and "ConsecLoss 2 >= 2" in record.message
            ):
                reduction_log_found = True
                break
        assert reduction_log_found, (
            "RISK REDUCED log for ConsecLoss not found or incorrect"
        )

        with patch(
            "time.time",
            return_value=last_penalty_ts_reduction
            + risk_manager._strategy_symbol_cooldown_penalty_sec
            + 10,
        ):
            stats.current_risk_multiplier_index = default_idx - 1
            stats.last_penalty_timestamp = last_penalty_ts_reduction
            stats.trade_results_buffer.clear()
            stats.trade_results_buffer.extend(
                [(10.0, 100.0), (10.0, 100.0), (-10.0, 100.0), (-10.0, 100.0)]
            )
            stats.current_pnl_sum_usd = 0
            stats.sum_initial_risk_usd_in_window = 400
            stats.current_wins_in_window = 2
            stats.current_trades_in_window = 4
            stats.current_consecutive_losses = 2
            stats.current_consecutive_wins_for_recovery = 0
            stats.total_trades_for_assessment = 4
            caplog.clear()
            await risk_manager.update_symbol_strategy_performance(
                symbol, strategy_name, 30.0, 100.0
            )
            stats = risk_manager._symbol_strategy_performance[(symbol, strategy_name)]
            assert stats.current_risk_multiplier_index == default_idx

            recovery_log_found = False
            logged_pnl_pct = (
                (stats.current_pnl_sum_usd / stats.sum_initial_risk_usd_in_window * 100)
                if stats.sum_initial_risk_usd_in_window > 1e-9
                else 0
            )
            expected_reason = f"PnL {logged_pnl_pct:.2f}% > {risk_manager._strategy_symbol_rec_pnl_thresh_pct:.2f}%"
            for record in caplog.records:
                if (
                    record.levelname == "INFO"
                    and (
                        "RISK RECOVERED" in record.message
                        or "RISK ENHANCED" in record.message
                    )
                    and expected_reason in record.message
                ):
                    recovery_log_found = True
                    break
            assert recovery_log_found, (
                f"RISK RECOVERED/ENHANCED log for PNL% not found. Expected reason: {expected_reason}. Caplog: {caplog.text}"
            )

        stats.current_risk_multiplier_index = default_idx
        stats.current_consecutive_losses = 0
        stats.current_consecutive_wins_for_recovery = 0
        stats.last_penalty_timestamp = 0
        stats.trade_results_buffer.clear()
        stats.current_pnl_sum_usd = 0
        stats.sum_initial_risk_usd_in_window = 0
        stats.current_wins_in_window = 0
        stats.current_trades_in_window = 0
        stats.total_trades_for_assessment = (
            risk_manager._strategy_symbol_min_trades_assess
        )
        caplog.clear()
        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, -10.0, 100.0
        )
        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, 5.0, 100.0
        )
        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, -10.0, 100.0
        )
        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, 5.0, 100.0
        )
        await risk_manager.update_symbol_strategy_performance(
            symbol, strategy_name, -10.0, 100.0
        )
        stats = risk_manager._symbol_strategy_performance[(symbol, strategy_name)]
        assert stats.current_risk_multiplier_index == default_idx - 1

        pnl_reduction_log_found = False
        logged_pnl_pct_2 = (
            (stats.current_pnl_sum_usd / stats.sum_initial_risk_usd_in_window * 100)
            if stats.sum_initial_risk_usd_in_window > 1e-9
            else 0
        )
        expected_reason_pnl = f"PnL {logged_pnl_pct_2:.2f}% < {risk_manager._strategy_symbol_pnl_thresh_pct:.2f}%"
        consec_loss_reason_str = f"ConsecLoss {stats.current_consecutive_losses} >= {risk_manager._strategy_symbol_max_consec_loss}"

        for record in caplog.records:
            if record.levelname == "WARNING" and "RISK REDUCED" in record.message:
                assert consec_loss_reason_str not in record.message, (
                    "ConsecLoss should not be the reason for reduction here"
                )
                if expected_reason_pnl in record.message:
                    pnl_reduction_log_found = True
        assert pnl_reduction_log_found, (
            f"RISK REDUCED log for PNL% not found. Expected reason: {expected_reason_pnl}. Caplog: {caplog.text}"
        )
    finally:
        bot_module_actual_logger.propagate = original_bot_module_propagate_status


@pytest.mark.asyncio
async def test_initialize_clears_performance_stats_if_no_load(
    risk_manager, mock_executor
):
    """
    Verifies that repeated full initialization clears statistics
    in memory before loading (which in this test will find nothing in the DB).
    """
    # Manually "pollute" the state of an already initialized manager
    risk_manager._symbol_strategy_performance[("BTCUSDT", "StratA")] = (
        SymbolStrategyPerformanceStats(
            current_pnl_sum_usd=100.0,
            current_risk_multiplier_index=risk_manager._s_s_default_risk_idx + 1,
        )
    )
    assert len(risk_manager._symbol_strategy_performance) == 1

    mock_executor.get_account_balance.return_value = {
        "USDT": {"free": "10000.00", "locked": "0.00"}
    }

    # Call the full initialization method, which should perform cleanup
    await risk_manager.initialize()

    # The dictionary should be empty because initialize() cleared it, and the DB in this test is empty
    assert len(risk_manager._symbol_strategy_performance) == 0

    # Also verify that the child call initialize_balance() correctly reset the daily statistics
    default_stats = risk_manager._symbol_strategy_performance[
        ("BTCUSDT", "StratA")
    ]  # defaultdict will create a new empty object
    assert default_stats.current_pnl_sum_usd == 0.0
    assert (
        default_stats.current_risk_multiplier_index
        == risk_manager._s_s_default_risk_idx
    )
    assert risk_manager.stats.today_pnl == 0.0
    assert risk_manager.stats.consecutive_losses == 0
    assert math.isclose(risk_manager.stats.start_of_day_balance, 10000.0)


@pytest.mark.asyncio
async def test_risk_limits_consecutive_losses(risk_manager):
    assert risk_manager._is_trading_allowed is True
    await risk_manager.update_trade_result("BTCUSDT", -10.0)
    await risk_manager.update_trade_result("BTCUSDT", -20.0)
    assert risk_manager.stats.consecutive_losses == 2
    assert risk_manager._is_trading_allowed is True
    await risk_manager.update_trade_result("BTCUSDT", -15.0)
    assert risk_manager.stats.consecutive_losses == 3
    assert risk_manager._is_trading_allowed is False
    risk_manager.stats.consecutive_losses = 0
    risk_manager._is_trading_allowed = True
    await risk_manager.update_trade_result("BTCUSDT", 50.0)
    assert risk_manager.stats.consecutive_losses == 0
    assert risk_manager._is_trading_allowed is True


@pytest.mark.asyncio
async def test_risk_limits_daily_loss(risk_manager):
    assert risk_manager._is_trading_allowed is True
    allowed_loss = (
        risk_manager.stats.start_of_day_balance * risk_manager.daily_max_loss_threshold
    )
    await risk_manager.update_trade_result("ETHUSDT", -allowed_loss * 0.8)
    assert risk_manager._is_trading_allowed is True
    assert math.isclose(risk_manager.stats.today_pnl, -allowed_loss * 0.8)
    await risk_manager.update_trade_result("ETHUSDT", -allowed_loss * 0.3)
    assert risk_manager._is_trading_allowed is False
    assert risk_manager.stats.today_pnl < -allowed_loss


@pytest.mark.asyncio
async def test_risk_limits_new_day_reset(risk_manager):
    risk_manager.stats.consecutive_losses = risk_manager.max_consecutive_losses
    risk_manager._check_risk_limits()
    assert risk_manager._is_trading_allowed is False
    penalty_key = ("XYZUSDT", "OldStrat")
    stats_obj = risk_manager._symbol_strategy_performance[penalty_key]
    stats_obj.current_risk_multiplier_index = 0
    past_ts = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    stats_obj.last_penalty_timestamp = past_ts
    risk_manager.stats.last_known_day_str = "2020-01-01"
    current_balance_before_reset = risk_manager.stats.current_balance
    with patch("bot_module.risk_manager.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(
            2020, 1, 2, 1, 0, 0, tzinfo=timezone.utc
        )
        mock_datetime.combine = datetime.combine
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        risk_manager._check_and_reset_daily_stats()
    actual_current_day_str = datetime(
        2020, 1, 2, 1, 0, 0, tzinfo=timezone.utc
    ).strftime("%Y-%m-%d")
    assert risk_manager._is_trading_allowed is True
    assert risk_manager.stats.consecutive_losses == 0
    assert risk_manager.stats.today_pnl == 0.0
    assert math.isclose(
        risk_manager.stats.start_of_day_balance, current_balance_before_reset
    )
    assert risk_manager.stats.last_known_day_str == actual_current_day_str
    assert penalty_key in risk_manager._symbol_strategy_performance
    stats_obj_after_reset = risk_manager._symbol_strategy_performance[penalty_key]
    assert stats_obj_after_reset.current_risk_multiplier_index == 0
    assert math.isclose(stats_obj_after_reset.last_penalty_timestamp, past_ts)


# --- START: NEW TESTS for checking saving and loading from the DB ---


@pytest.mark.asyncio
async def test_performance_state_is_saved_to_db(risk_manager, db_session, test_user):
    """
    Criterion 3: Ensure that the strategy performance state
    is recorded in the database after a trade.
    """
    symbol, strategy_name = "ETHUSDT", "TrendFollow"

    # Call the method that should trigger saving to the DB
    await risk_manager.update_symbol_strategy_performance(
        symbol=symbol,
        strategy_name=strategy_name,
        pnl_usd=-50.0,
        initial_risk_usd_planned=100.0,
    )
    # Complete the transaction so that the data becomes visible in the next session
    await db_session.commit()

    # Check directly in the DB that the record appeared
    records = await crud.get_all_symbol_strategy_performance(
        db=db_session, user_id=test_user.id
    )
    assert len(records) == 1
    record = records[0]
    assert record.symbol == symbol
    assert record.strategy_name == strategy_name
    assert record.total_pnl_usd == -50.0
    assert record.total_trades_for_assessment == 1


@pytest.mark.asyncio
async def test_performance_state_is_loaded_from_db(
    mock_executor, db_session, test_user
):
    """
    Criterion 1: Ensure that settings (state) are loaded correctly.
    """
    # 1. Pre-create a record in the DB as if it had been saved earlier
    symbol, strategy_name = "SOLUSDT", "MeanReversion"
    initial_data = {
        "symbol": symbol,
        "strategy_name": strategy_name,
        "trade_results_buffer_json": "[[10, 100], [-5, 100]]",
        "current_risk_multiplier_index": 1,
        "last_penalty_timestamp": 12345.0,
        "total_trades_for_assessment": 10,
        "total_pnl_usd": 5.0,
    }
    await crud.update_or_create_symbol_strategy_performance(
        db=db_session, user_id=test_user.id, performance_data=initial_data
    )
    await db_session.commit()

    # 2. Create a NEW RiskManager instance, which should load this data
    rm2 = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={
            "risk_management": {"strategySymbolAdjustmentEnabled": True}
        },  # Test settings
    )
    await rm2.initialize()  # This method calls _load_performance_from_db

    # 3. Verify that the internal state of RiskManager matches the data from the DB
    perf_key = (symbol, strategy_name)
    assert perf_key in rm2._symbol_strategy_performance

    loaded_stats = rm2._symbol_strategy_performance[perf_key]
    assert len(loaded_stats.trade_results_buffer) == 2
    assert list(loaded_stats.trade_results_buffer) == [[10, 100], [-5, 100]]
    assert loaded_stats.current_risk_multiplier_index == 1
    assert loaded_stats.total_pnl_usd == 5.0


@pytest.mark.asyncio
async def test_bot_uses_user_specific_settings(mock_executor, db_session, test_user):
    """
    Criterion 2: Verify that the bot uses specifically user settings.
    We have already indirectly verified this in the new `risk_manager` fixture, but this test does it explicitly.
    """
    user_settings = {
        "risk_management": {
            "riskPerTradePercent": 5.0,  # 5% instead of the default 1%
            "strategySymbolWindowSize": 99,
            "strategySymbolMaxConsecutiveLosses": 7,
        }
    }

    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings=user_settings,
    )

    assert rm.risk_per_trade == 0.05
    assert rm._strategy_symbol_window_size == 99
    assert rm._strategy_symbol_max_consec_loss == 7


@pytest.mark.asyncio
async def test_calculate_scaled_in_quantity(risk_manager, mock_executor):
    """
    Tests the calculation of quantity for a scale-in order.
    """
    position = MagicMock()
    position.symbol = "BTCUSDT"
    position.initial_risk_usd_planned = 100.0
    position.current_sl_price = 49000.0

    lot_params = {"minQty": 0.001, "maxQty": 100.0, "stepSize": 0.001}
    min_notional = 10.0

    # Test with 50% additional risk
    add_size_pct = 50.0
    expected_additional_risk = 50.0
    stop_distance = 1000.0
    expected_quantity = expected_additional_risk / stop_distance  # 0.05

    # Manually apply rounding
    step = Decimal(str(lot_params["stepSize"]))
    qty_dec = Decimal(str(expected_quantity))
    expected_adj_qty = float(
        (qty_dec / step).quantize(Decimal("0"), rounding=ROUND_DOWN) * step
    )  # 0.05

    calculated_quantity = await risk_manager.calculate_scaled_in_quantity(
        position, add_size_pct, 50000.0, lot_params, min_notional
    )

    assert calculated_quantity is not None
    assert math.isclose(calculated_quantity, expected_adj_qty, rel_tol=1e-9)


# --- START: BLACKLIST TESTS ---


@pytest.mark.asyncio
async def test_blacklist_permanent_blocks_symbol(mock_executor, db_session, test_user):
    """
    Test: A symbol with a permanent block (until=None) must be blocked.
    """
    from sqlalchemy import select

    # 1. Find the user's AppConfig and update risk_management
    result = await db_session.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == test_user.id)
    )
    user_config = result.scalar_one()

    # Update as a dict (since it's a JSON column in the model)
    risk_management = (
        dict(user_config.risk_management) if user_config.risk_management else {}
    )
    risk_management["blacklist"] = {
        "coins": [
            {
                "symbol": "BTCUSDT",
                "until": None,  # Permanent block
                "reason": "Test permanent block",
                "addedAt": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    user_config.risk_management = risk_management
    await db_session.commit()
    await db_session.refresh(user_config)

    # 2. Creating RiskManager
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={"risk_management": risk_management},
    )
    await rm.initialize()

    # 3. Checking that the symbol is blocked
    result = await rm.is_symbol_trading_allowed("BTCUSDT")
    assert result is False

    # 4. Checking that another symbol is allowed
    result_other = await rm.is_symbol_trading_allowed("ETHUSDT")
    assert result_other is True


@pytest.mark.asyncio
async def test_blacklist_expired_allows_symbol(mock_executor, db_session, test_user):
    """
    Test: A symbol with an expired block (until < now) must be allowed.
    """
    from sqlalchemy import select

    # 1. Find the user's AppConfig and update risk_management
    result = await db_session.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == test_user.id)
    )
    user_config = result.scalar_one()

    past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    risk_management = (
        dict(user_config.risk_management) if user_config.risk_management else {}
    )
    risk_management["blacklist"] = {
        "coins": [
            {
                "symbol": "SOLUSDT",
                "until": past_time,  # Expired lock
                "reason": "Test expired block",
                "addedAt": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    user_config.risk_management = risk_management
    await db_session.commit()
    await db_session.refresh(user_config)

    # 2. Creating RiskManager
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={"risk_management": risk_management},
    )
    await rm.initialize()

    # 3. Check that the symbol is allowed (expired)
    result = await rm.is_symbol_trading_allowed("SOLUSDT")
    assert result is True


@pytest.mark.asyncio
async def test_blacklist_active_until_blocks_symbol(
    mock_executor, db_session, test_user
):
    """
    Test: A symbol with an active block (until > now) must be blocked.
    """
    from sqlalchemy import select

    # 1. Find the user's AppConfig and update risk_management
    result = await db_session.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == test_user.id)
    )
    user_config = result.scalar_one()

    future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    risk_management = (
        dict(user_config.risk_management) if user_config.risk_management else {}
    )
    risk_management["blacklist"] = {
        "coins": [
            {
                "symbol": "XRPUSDT",
                "until": future_time,  # Active lock
                "reason": "Test active block",
                "addedAt": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    user_config.risk_management = risk_management
    await db_session.commit()
    await db_session.refresh(user_config)

    # 2. Creating RiskManager
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={"risk_management": risk_management},
    )
    await rm.initialize()

    # 3. Checking that the symbol is blocked
    result = await rm.is_symbol_trading_allowed("XRPUSDT")
    assert result is False


@pytest.mark.asyncio
async def test_assess_signal_rejects_blacklisted_symbol(
    mock_executor, db_session, test_user
):
    """
    Test: assess_signal should reject a signal for a symbol in the blacklist.
    """
    from sqlalchemy import select

    # 1. Find the user's AppConfig and update risk_management
    result = await db_session.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == test_user.id)
    )
    user_config = result.scalar_one()

    risk_management = (
        dict(user_config.risk_management) if user_config.risk_management else {}
    )
    risk_management["blacklist"] = {
        "coins": [
            {
                "symbol": "AVAXUSDT",
                "until": None,  # Permanent block
                "reason": "Test signal rejection",
                "addedAt": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    user_config.risk_management = risk_management
    await db_session.commit()
    await db_session.refresh(user_config)

    # 2. Creating RiskManager
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={"risk_management": risk_management},
    )
    await rm.initialize()

    # 3. Create a signal for a blocked symbol
    signal = StrategySignal(
        strategy_name="TestStrat",
        symbol="AVAXUSDT",  # Blocked symbol
        direction=SignalDirection.LONG,
        trigger_price=25.0,
        stop_loss=24.5,
        take_profit=26.0,
        mode=OrderMode.MARKET,
    )
    lot_params = {"minQty": 0.1, "maxQty": 10000.0, "stepSize": 0.1}

    # 4. Checking that the signal is rejected
    approved, quantity, risk, reason = await rm.assess_signal(signal, lot_params, 10.0)

    assert approved is False
    assert quantity is None
    assert reason == "SYMBOL_BLACKLISTED"


@pytest.mark.asyncio
async def test_blacklist_case_insensitive(mock_executor, db_session, test_user):
    """
    Test: Blacklist check should be case-insensitive.
    """
    from sqlalchemy import select

    # 1. Find the user's AppConfig and update risk_management
    result = await db_session.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == test_user.id)
    )
    user_config = result.scalar_one()

    risk_management = (
        dict(user_config.risk_management) if user_config.risk_management else {}
    )
    risk_management["blacklist"] = {
        "coins": [
            {
                "symbol": "btcusdt",  # Lowercase
                "until": None,
                "reason": "Test case insensitivity",
                "addedAt": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    user_config.risk_management = risk_management
    await db_session.commit()
    await db_session.refresh(user_config)

    # 2. Creating RiskManager
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={"risk_management": risk_management},
    )
    await rm.initialize()

    # 3. Check in upper case - should be blocked
    result = await rm.is_symbol_trading_allowed("BTCUSDT")
    assert result is False

    # 4. Check in mixed case - should also be blocked
    result_mixed = await rm.is_symbol_trading_allowed("BtcUsdt")
    assert result_mixed is False


@pytest.mark.asyncio
async def test_blacklist_no_db_allows_trading(mock_executor):
    """
    Test: If there is no access to the DB, trading should be allowed (fail-open).
    """
    # Creating RiskManager WITHOUT db_session
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=1,
        db_session=None,  # No DB session
        user_settings={},
    )

    # Trading should be allowed, even without DB access
    result = await rm.is_symbol_trading_allowed("BTCUSDT")
    assert result is True


# --- END: BLACKLIST TESTS ---


# --- START: AUTO-BLACKLIST TESTS ---


@pytest.mark.asyncio
async def test_auto_blacklist_consecutive_stops_tracking(
    mock_executor, db_session, test_user
):
    """
    Test: Verify that consecutive stops are correctly tracked.
    """
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={"risk_management": {}},
    )
    await rm.initialize()

    # Initially, the list of stops should be empty
    assert len(rm._symbol_stop_timestamps.get("BTCUSDT", [])) == 0

    # Trade with a stop
    await rm.update_trade_result("BTCUSDT", -50.0, exit_reason="stop_loss")
    assert len(rm._symbol_stop_timestamps["BTCUSDT"]) == 1

    # Another trade with a stop
    await rm.update_trade_result("BTCUSDT", -30.0, exit_reason="trailing_stop")
    assert len(rm._symbol_stop_timestamps["BTCUSDT"]) == 2

    # A profitable trade should clear the list of stops
    await rm.update_trade_result("BTCUSDT", 100.0, exit_reason="take_profit")
    assert len(rm._symbol_stop_timestamps["BTCUSDT"]) == 0


@pytest.mark.asyncio
async def test_auto_blacklist_rule_triggers(mock_executor, db_session, test_user):
    """
    Test: Verify that the auto-blacklist rule triggers when the threshold is reached.
    """
    # 1. Configure auto-blacklist rule: 2 stops in a row -> block for 1 hour
    risk_management = {
        "blacklist": {
            "coins": [],
            "autoRules": [
                {
                    "id": "test-rule-1",
                    "enabled": True,
                    "consecutiveStops": 2,
                    "duration": "1h",
                }
            ],
        }
    }

    # Use crud for correct saving
    await crud.update_config_section(
        db_session, test_user.id, "risk_management", risk_management
    )
    await db_session.commit()

    # 2. Creating RiskManager
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={"risk_management": risk_management},
    )
    await rm.initialize()

    # 3. First stop - the rule should not trigger
    await rm.update_trade_result("SOLUSDT", -50.0, exit_reason="stop_loss")
    assert len(rm._symbol_stop_timestamps["SOLUSDT"]) == 1

    # Checking that the symbol is still allowed
    result = await rm.is_symbol_trading_allowed("SOLUSDT")
    assert result is True

    # 4. Second stop - the rule should trigger
    await rm.update_trade_result("SOLUSDT", -30.0, exit_reason="stop_loss")

    # The list of stops must be cleared after adding to the blacklist
    assert len(rm._symbol_stop_timestamps["SOLUSDT"]) == 0

    # 5. After the rule triggers, the symbol should be blocked
    db_session.expire_all()  # Resetting the cache
    result_after = await rm.is_symbol_trading_allowed("SOLUSDT")
    assert result_after is False


@pytest.mark.asyncio
async def test_auto_blacklist_disabled_rule_does_not_trigger(
    mock_executor, db_session, test_user
):
    """
    Test: A disabled auto-blacklist rule should not trigger.
    """
    from sqlalchemy import select

    # 1. Setting up a disabled rule
    result = await db_session.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == test_user.id)
    )
    user_config = result.scalar_one()

    risk_management = (
        dict(user_config.risk_management) if user_config.risk_management else {}
    )
    risk_management["blacklist"] = {
        "coins": [],
        "autoRules": [
            {
                "id": "disabled-rule",
                "enabled": False,  # Rule disabled
                "consecutiveStops": 1,
                "duration": "permanent",
            }
        ],
    }
    user_config.risk_management = risk_management
    await db_session.commit()
    await db_session.refresh(user_config)

    # 2. Creating RiskManager
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={"risk_management": risk_management},
    )
    await rm.initialize()

    # 3. Stop-loss - the rule should not trigger (it is disabled)
    await rm.update_trade_result("DOTUSDT", -50.0, exit_reason="stop_loss")

    # Stop list should remain (not cleared, as the rule did not trigger)
    assert len(rm._symbol_stop_timestamps["DOTUSDT"]) == 1

    # The symbol should still be allowed
    result = await rm.is_symbol_trading_allowed("DOTUSDT")
    assert result is True


@pytest.mark.asyncio
async def test_auto_blacklist_no_rules_configured(mock_executor, db_session, test_user):
    """
    Test: If no rules are configured, nothing should happen.
    """
    from sqlalchemy import select

    # 1. Set up an empty blacklist without rules
    result = await db_session.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == test_user.id)
    )
    user_config = result.scalar_one()

    risk_management = (
        dict(user_config.risk_management) if user_config.risk_management else {}
    )
    risk_management["blacklist"] = {
        "coins": [],
        "autoRules": [],  # No rules
    }
    user_config.risk_management = risk_management
    await db_session.commit()
    await db_session.refresh(user_config)

    # 2. Creating RiskManager
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={"risk_management": risk_management},
    )
    await rm.initialize()

    # 3. Many stops in a row
    for i in range(5):
        await rm.update_trade_result("ADAUSDT", -10.0, exit_reason="stop_loss")

    # The list of stops should grow
    assert len(rm._symbol_stop_timestamps["ADAUSDT"]) == 5

    # Symbol should still be allowed (no rules for blocking)
    result = await rm.is_symbol_trading_allowed("ADAUSDT")
    assert result is True


@pytest.mark.asyncio
async def test_auto_blacklist_within_period_filters_old_stops(
    mock_executor, db_session, test_user
):
    """
    Test: Verify that within_period correctly filters old stops.
    Rule: 3 stops in 1 hour -> block.
    If 2 stops were more than an hour ago and 1 is now - the rule will NOT trigger.
    """
    import time as time_module

    # 1. Set up the rule: 3 stops in 1 hour -> block
    risk_management = {
        "blacklist": {
            "coins": [],
            "autoRules": [
                {
                    "id": "test-period-rule",
                    "enabled": True,
                    "consecutiveStops": 3,
                    "withinPeriod": "1h",  # For 1 hour
                    "duration": "1h",
                }
            ],
        }
    }

    await crud.update_config_section(
        db_session, test_user.id, "risk_management", risk_management
    )
    await db_session.commit()

    # 2. Creating RiskManager
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={"risk_management": risk_management},
    )
    await rm.initialize()

    # 3. Add 2 "old" stops (more than an hour ago) manually
    now = time_module.time()
    old_timestamp = now - (2 * 60 * 60)  # 2 hours ago
    rm._symbol_stop_timestamps["XRPUSDT"] = [
        old_timestamp,
        old_timestamp + 60,
    ]  # 2 stops 2 hours ago

    # 4. Adding 1 new stop - the rule should NOT trigger (only 1 stop in the last hour)
    await rm.update_trade_result("XRPUSDT", -50.0, exit_reason="stop_loss")

    # Symbol should be allowed (only 1 stop in the last hour out of 3 required)
    result = await rm.is_symbol_trading_allowed("XRPUSDT")
    assert result is True

    # There should be 3 stops in total (2 old + 1 new)
    assert len(rm._symbol_stop_timestamps["XRPUSDT"]) == 3


@pytest.mark.asyncio
async def test_auto_blacklist_within_period_triggers_when_enough_recent_stops(
    mock_executor, db_session, test_user
):
    """
    Test: Verify that the rule triggers when there are enough stops within the period.
    Rule: 2 stops in 1 hour -> block.
    """
    import time as time_module

    # 1. Set up the rule: 2 stops in 1 hour -> block
    risk_management = {
        "blacklist": {
            "coins": [],
            "autoRules": [
                {
                    "id": "test-period-rule-2",
                    "enabled": True,
                    "consecutiveStops": 2,
                    "withinPeriod": "1h",
                    "duration": "1h",
                }
            ],
        }
    }

    await crud.update_config_section(
        db_session, test_user.id, "risk_management", risk_management
    )
    await db_session.commit()

    # 2. Creating RiskManager
    rm = RiskManager(
        executor=mock_executor,
        paper_executor=mock_executor,
        user_id=test_user.id,
        db_session=db_session,
        user_settings={"risk_management": risk_management},
    )
    await rm.initialize()

    # 3. Adding 1 "fresh" stop (10 minutes ago) manually
    now = time_module.time()
    recent_timestamp = now - (10 * 60)  # 10 minutes ago
    rm._symbol_stop_timestamps["LINKUSDT"] = [recent_timestamp]

    # 4. Adding the 2nd stop now - the rule SHOULD trigger
    await rm.update_trade_result("LINKUSDT", -50.0, exit_reason="stop_loss")

    # The list should be cleared (the rule triggered)
    assert len(rm._symbol_stop_timestamps["LINKUSDT"]) == 0

    # The symbol should be blocked
    db_session.expire_all()
    result = await rm.is_symbol_trading_allowed("LINKUSDT")
    assert result is False


# --- END: AUTO-BLACKLIST TESTS ---


@pytest.mark.asyncio
async def test_assess_signal_no_stop_loss(risk_manager, sample_signal_long):
    """
    Test that assess_signal works properly when stop_loss is None (DCA/Grid mode).
    It should directly use risk limit (e.g. 5% of balance) as the notional size of the order.
    """
    # Create a deep copy or modify carefully as fixtures might be reused
    from copy import copy

    signal = copy(sample_signal_long)
    signal.stop_loss = None  # Enable NO STOP LOSS mode

    lot_params = {"minQty": 0.0001, "maxQty": 9000.0, "stepSize": 0.00001}
    min_notional = 10.0

    # fixture risk_manager uses 1.0% risk (0.01) from fixture settings
    expected_base_risk_usd = 10000.0 * risk_manager.risk_per_trade  # 100.0
    default_multiplier = risk_manager._strategy_symbol_risk_multipliers[
        risk_manager._s_s_default_risk_idx
    ]

    # In 'no stop loss' mode, the target risk = target notional size (using the same USD risk amount)
    expected_sizing_notional_usd = expected_base_risk_usd * default_multiplier

    # qty = target_notional / entry_price
    # trigger_price is 50000.0 in sample_signal_long
    expected_base_qty = expected_sizing_notional_usd / signal.trigger_price

    step_dec = Decimal(str(lot_params["stepSize"]))
    base_dec = Decimal(str(expected_base_qty))
    expected_adj_qty = float(
        (base_dec / step_dec).quantize(Decimal("0"), rounding=ROUND_DOWN) * step_dec
    )

    approved, quantity, initial_risk_planned, reason = await risk_manager.assess_signal(
        signal, lot_params, min_notional
    )

    assert approved is True
    assert quantity is not None
    assert math.isclose(quantity, expected_adj_qty, rel_tol=1e-9)
    assert initial_risk_planned is not None
    assert math.isclose(initial_risk_planned, expected_base_risk_usd, rel_tol=1e-9)


@pytest.mark.asyncio
async def test_calculate_scaled_in_quantity_no_stop_loss(risk_manager, mock_executor):
    """
    Test the calculation of additional quantity for scale-in orders when there is NO STOP LOSS.
    The formula uses additional_risk_usd / current_price.
    """
    position = MagicMock()
    position.symbol = "BTCUSDT"
    position.initial_risk_usd_planned = 100.0
    position.current_sl_price = None  # NO STOP LOSS

    lot_params = {"minQty": 0.001, "maxQty": 100.0, "stepSize": 0.001}
    min_notional = 10.0

    add_size_pct = 200.0  # e.g. 2x multiplier
    expected_additional_risk = 100.0 * (200.0 / 100.0)  # 200.0 notional target

    current_price = 50000.0
    expected_quantity = expected_additional_risk / current_price

    step = Decimal(str(lot_params["stepSize"]))
    qty_dec = Decimal(str(expected_quantity))
    expected_adj_qty = float(
        (qty_dec / step).quantize(Decimal("0"), rounding=ROUND_DOWN) * step
    )

    calculated_quantity = await risk_manager.calculate_scaled_in_quantity(
        position, add_size_pct, current_price, lot_params, min_notional
    )

    assert calculated_quantity is not None
    assert math.isclose(calculated_quantity, expected_adj_qty, rel_tol=1e-9)
