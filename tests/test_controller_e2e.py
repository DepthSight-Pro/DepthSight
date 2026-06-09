# tests/test_controller_e2e.py
import asyncio
import logging
import os
import sys
import time
from typing import Optional
from unittest.mock import MagicMock, AsyncMock

import pytest
from dotenv import load_dotenv

from bot_module import config as global_bot_config
from bot_module.controller import TradingController, LivePosition as Position
from bot_module.data_consumer import DataConsumer
from bot_module.exchanges import ExchangeExecutor, create_exchange_executor
from bot_module.risk_manager import RiskManager
from bot_module.strategy import (
    StrategySignal,
    SignalDirection,
    OrderMode,
    STRATEGIES,
    VolumeBreakoutStrategy,
)

load_dotenv()
print(f"SPOT KEY from env: {os.environ.get('BOT_BINANCE_SPOT_API_KEY')}")
print(f"FUTURES KEY from env: {os.environ.get('BOT_BINANCE_FUTURES_API_KEY')}")

STRATEGIES["VolumeBreakout"] = VolumeBreakoutStrategy

logging.getLogger("bot_module.data_consumer").setLevel(logging.ERROR)
logging.getLogger("bot_module.executor").setLevel(logging.DEBUG)
logging.getLogger("bot_module.controller").setLevel(logging.DEBUG)
logging.getLogger("bot_module.risk_manager").setLevel(logging.DEBUG)
logging.getLogger("bot_module.strategy").setLevel(logging.ERROR)
logging.getLogger("bot_module.data_loader").setLevel(logging.ERROR)
logging.getLogger("bot_module.trade_logger").setLevel(logging.ERROR)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = logging.getLogger("bot_module")
if not logger.hasHandlers():
    ch = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.setLevel(logging.DEBUG)

# --- Keys are read from environment variables ---
TESTNET_SPOT_API_KEY = os.environ.get("TESTNET_BINANCE_SPOT_API_KEY")
TESTNET_SPOT_API_SECRET = os.environ.get("TESTNET_BINANCE_SPOT_API_SECRET")
TESTNET_FUTURES_API_KEY = os.environ.get("TESTNET_BINANCE_FUTURES_API_KEY")
TESTNET_FUTURES_API_SECRET = os.environ.get("TESTNET_BINANCE_FUTURES_API_SECRET")

# Parameters for different market types (remain unchanged)
MARKET_PARAMS = {
    "spot": {
        "test_symbol": "BTCUSDT",
        "order_specific_params": lambda price, qty: {"quantity": qty},
        "initial_balance_asset": "USDT",
        "min_balance_check": 5.0,  # reduced for test
    },
    "futures_usdtm": {
        "test_symbol": "BTCUSDT",
        "order_specific_params": lambda price, qty: {"quantity": qty},
        "initial_balance_asset": "USDT",
        "min_balance_check": 5.0,  # reduced for test
    },
}


@pytest.fixture(scope="function")
async def configured_trading_market_type(request, e2e_exchange_profile):
    # Saving original values
    original_trading_market_type = global_bot_config.TRADING_MARKET_TYPE
    original_active_env = global_bot_config.ACTIVE_TRADING_ENVIRONMENT
    original_active_api_key = global_bot_config.BINANCE_ACTIVE_API_KEY
    original_active_api_secret = global_bot_config.BINANCE_ACTIVE_API_SECRET
    original_allow_short = global_bot_config.ALLOW_SHORT_POSITIONS

    market_type_to_test = request.param
    exchange_profile = e2e_exchange_profile
    exchange_for_market = exchange_profile.get("exchange_by_market", {}).get(
        market_type_to_test, exchange_profile["exchange"]
    )

    # 1. Set global variables for this test
    global_bot_config.ACTIVE_TRADING_ENVIRONMENT = "testnet"
    global_bot_config.TRADING_MARKET_TYPE = market_type_to_test

    # 2. Recalculate active keys using the VARIABLES defined at the top of the file.
    if exchange_profile["exchange"] != "binance_futures":
        global_bot_config.BINANCE_ACTIVE_API_KEY = exchange_profile["api_key"]
        global_bot_config.BINANCE_ACTIVE_API_SECRET = exchange_profile["api_secret"]
        global_bot_config.ALLOW_SHORT_POSITIONS = True
    elif market_type_to_test == "spot":
        global_bot_config.BINANCE_ACTIVE_API_KEY = os.environ.get(
            "TESTNET_BINANCE_SPOT_API_KEY"
        )
        global_bot_config.BINANCE_ACTIVE_API_SECRET = os.environ.get(
            "TESTNET_BINANCE_SPOT_API_SECRET"
        )
        global_bot_config.ALLOW_SHORT_POSITIONS = False
    elif market_type_to_test == "futures_usdtm":
        global_bot_config.BINANCE_ACTIVE_API_KEY = os.environ.get(
            "TESTNET_BINANCE_FUTURES_API_KEY"
        )
        global_bot_config.BINANCE_ACTIVE_API_SECRET = os.environ.get(
            "TESTNET_BINANCE_FUTURES_API_SECRET"
        )
        global_bot_config.ALLOW_SHORT_POSITIONS = True
    else:
        pytest.fail(f"Unsupported market_type_to_test: {market_type_to_test}")

    # 3. Check that the testnet keys are actually loaded from .env
    logger.info(
        f"[DEBUG] market_type_to_test={market_type_to_test}, key={global_bot_config.BINANCE_ACTIVE_API_KEY}"
    )
    if (
        not global_bot_config.BINANCE_ACTIVE_API_KEY
        or "YOUR_" in global_bot_config.BINANCE_ACTIVE_API_KEY
    ):
        pytest.skip(
            f"API keys for {market_type_to_test} testnet not found in .env or are placeholders. Used env vars: TESTNET_BINANCE_{market_type_to_test.upper().replace('_USDTM', '')}_API_KEY/SECRET"
        )

    logger.info("[Fixture] Set ACTIVE_TRADING_ENVIRONMENT to 'testnet'")
    logger.info(f"[Fixture] Set TRADING_MARKET_TYPE to '{market_type_to_test}'")
    logger.info(
        f"[Fixture] Active API Key for test ends with '...{global_bot_config.BINANCE_ACTIVE_API_KEY[-4:]}'"
    )

    yield {
        "market_type": market_type_to_test,
        "exchange": exchange_for_market,
        "api_key": global_bot_config.BINANCE_ACTIVE_API_KEY,
        "api_secret": global_bot_config.BINANCE_ACTIVE_API_SECRET,
        "profile": exchange_profile,
    }

    # Restoring original values after the test
    global_bot_config.TRADING_MARKET_TYPE = original_trading_market_type
    global_bot_config.ACTIVE_TRADING_ENVIRONMENT = original_active_env
    global_bot_config.BINANCE_ACTIVE_API_KEY = original_active_api_key
    global_bot_config.BINANCE_ACTIVE_API_SECRET = original_active_api_secret
    global_bot_config.ALLOW_SHORT_POSITIONS = original_allow_short

    logger.info("[Fixture] Restored global config to original state.")


@pytest.fixture(scope="function")
async def test_executor(
    configured_trading_market_type, ensure_testnet_ready
):  # configured_trading_market_type will already set up the global config
    exchange_config = configured_trading_market_type
    market_type = exchange_config["market_type"]

    # Check that global active keys are set (the configured_trading_market_type fixture should do this)
    if (
        not global_bot_config.BINANCE_ACTIVE_API_KEY
        or not global_bot_config.BINANCE_ACTIVE_API_SECRET
        or "YOUR_" in global_bot_config.BINANCE_ACTIVE_API_KEY
        or "YOUR_" in global_bot_config.BINANCE_ACTIVE_API_SECRET
    ):
        pytest.skip(
            f"Active API keys for market type '{market_type}' not configured for E2E tests by fixture (check config or env vars)."
        )

    import aiohttp

    session = aiohttp.ClientSession()
    executor = create_exchange_executor(
        exchange=exchange_config["exchange"],
        api_key=exchange_config["api_key"],
        api_secret=exchange_config["api_secret"],
        session=session,
        market_type=market_type,
    )
    await ensure_testnet_ready(executor, market_type=market_type)
    assert executor.market_type == market_type
    assert executor.api_key == exchange_config["api_key"]

    yield executor

    await executor.close()
    if not session.closed:
        await session.close()


async def wait_for_sl_order_placement(
    controller: TradingController, symbol: str, timeout: float = 20.0
) -> bool:
    """Waits until the SL order ID appears in the position object."""
    start_time = time.monotonic()
    logger.info(
        f"[WaitForSL] Waiting for SL order ID to be set for {symbol} (timeout: {timeout}s)"
    )
    while time.monotonic() - start_time < timeout:
        async with controller._positions_dict_lock:
            position = controller._active_position_get(symbol)
            if position and position.current_sl_order_id is not None:
                logger.info(
                    f"[WaitForSL] SL order ID {position.current_sl_order_id} found for {symbol}."
                )
                return True
        await asyncio.sleep(0.2)
    logger.error(f"[WaitForSL] Timeout waiting for SL order ID for {symbol}.")
    return False


async def cleanup_exchange(executor: ExchangeExecutor):
    """Closes all open positions and cancels all open orders on the exchange."""
    logger.info(f"[Cleanup] Starting exchange cleanup for {executor.market_type}...")
    try:
        # 1. Cancel all open orders
        orders = await executor.get_open_orders()
        if orders:
            logger.info(f"[Cleanup] Cancelling {len(orders)} open orders.")
            for order in orders:
                await executor.cancel_order(
                    order["symbol"],
                    orderId=order.get("orderId") or order.get("algoId"),
                    is_algo_order=("algoId" in order),
                )

        # 2. Close all open positions
        if executor.market_type == "futures_usdtm":
            positions = await executor.get_open_positions()
            if positions:
                logger.info(f"[Cleanup] Closing {len(positions)} open positions.")
                for pos in positions:
                    symbol = pos["symbol"]
                    amt = float(pos["positionAmt"])
                    if abs(amt) > 0:
                        side = "SELL" if amt > 0 else "BUY"
                        logger.info(f"[Cleanup] Closing {symbol}: {side} {abs(amt)}")
                        await executor.place_order(
                            symbol, side, "MARKET", quantity=abs(amt), reduceOnly=True
                        )
        else:  # Spot
            balances = await executor.get_account_balance()
            if balances:
                for asset, data in balances.items():
                    if asset != "USDT":
                        free_qty = float(data["free"])
                        if free_qty > 0:
                            symbol = f"{asset}USDT"
                            # Check if symbol exists and has a price (to avoid non-USDT pairs)
                            ticker = await executor.get_ticker_price(symbol)
                            if ticker and "price" in ticker:
                                logger.info(
                                    f"[Cleanup] Selling spot asset {asset}: {free_qty}"
                                )
                                await executor.place_order(
                                    symbol, "SELL", "MARKET", quantity=free_qty
                                )
    except Exception as e:
        logger.warning(f"[Cleanup] Error during exchange cleanup: {e}", exc_info=True)
    logger.info("[Cleanup] Exchange cleanup finished.")


@pytest.fixture
async def trading_components(
    test_executor, configured_trading_market_type, monkeypatch
):
    loop = asyncio.get_running_loop()
    market_type = configured_trading_market_type["market_type"]

    mock_db_session = MagicMock()
    mock_user_settings = MagicMock()
    test_user_id = 1

    # This mock should work, but we'll keep it just in case.
    def get_setting_side_effect(key, default=None):
        settings = {
            "initial_balance": 10000.0,
            "daily_max_loss_threshold_pct": 5.0,
            "min_balance_threshold": 100.0,
            "max_consecutive_losses": 10,
        }
        return settings.get(key, default)

    mock_user_settings.get_setting.side_effect = get_setting_side_effect

    risk_manager = RiskManager(
        executor=test_executor,
        paper_executor=MagicMock(),  # Added missing argument
        user_id=test_user_id,
        db_session=mock_db_session,
        user_settings=mock_user_settings,
    )
    risk_manager.stats = MagicMock()
    risk_manager.stats.current_balance = 10000.0
    risk_manager.max_concurrent_trades = 5

    # Set ALL necessary values directly in the RiskManager instance
    risk_manager.initial_balance_from_settings = 10000.0
    risk_manager.daily_max_loss_threshold = 0.05
    risk_manager.min_balance_threshold = 100.0
    risk_manager.max_consecutive_losses = 10
    risk_manager.live_max_stop_distance_pct = 0.05  # 5%
    risk_manager.max_stop_distance_pct = 0.05  # 5%

    # --- FROZE BALANCE UPDATES FOR TEST PREDICTABILITY ---
    risk_manager.update_balance = AsyncMock()  # Prevent real balance fetching
    risk_manager.stats.current_balance = 1000.0
    risk_manager.stats.total_equity = 1000.0
    risk_manager.stats.available_balance = 1000.0

    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("redis.asyncio.Redis", lambda **kwargs: fake_redis)
    monkeypatch.setattr("redis.asyncio.from_url", lambda *args, **kwargs: fake_redis)

    async def mock_get_db_session():
        yield mock_db_session

    # Properly mock crud functions to return predictable results and avoid DB hits
    mock_user = MagicMock()
    mock_user.id = test_user_id
    mock_user.username = "testuser"
    mock_user.plan = "pro"
    mock_user.push_subscription = None
    mock_user.telegram_chat_id = "12345678"

    # Mock crud functions so they don't fail when called from controller.start()
    mock_app_config = MagicMock()
    mock_app_config.notifications = {}
    mock_app_config.risk_management = {
        "maxConcurrentTrades": 5,
        "riskPerTradePercent": 1.0,
        "maxDrawdown": 20.0,
        "maxConsecutiveLosses": 10,
        "maxStopDistancePct": 5.0,
    }

    mock_symbol_config_dict = {
        "mode": "STATIC",
        "max_concurrent_symbols": 10,
        "min_natr": 0.5,
        "oracle_regime": 1,
        "oracle_confidence": 0.7,
    }

    monkeypatch.setattr(
        "bot_module.controller.crud.get_config", AsyncMock(return_value=mock_app_config)
    )
    monkeypatch.setattr(
        "bot_module.controller.crud.get_user_symbol_selection_config",
        AsyncMock(return_value=mock_symbol_config_dict),
    )
    monkeypatch.setattr(
        "bot_module.controller.crud.get_last_open_trade_for_symbol",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "bot_module.controller.crud.admin_get_user_details",
        AsyncMock(return_value=mock_user),
    )
    monkeypatch.setattr(
        "bot_module.controller.crud.create_trade", AsyncMock(return_value=MagicMock())
    )

    mock_paper_executor = AsyncMock()
    mock_paper_executor.check_open_orders = AsyncMock()
    mock_paper_executor.initialize_equity_tracking = AsyncMock()
    mock_paper_executor.update_market_info_cache = AsyncMock()

    # --- CLEANUP EXCHANGE BEFORE START ---
    await cleanup_exchange(test_executor)
    await asyncio.sleep(2)  # Give exchange some time to settle

    controller = TradingController(
        loop=loop,
        data_consumer=DataConsumer,
        live_executor=test_executor,
        paper_executor=mock_paper_executor,
        risk_manager=risk_manager,
        user_id=test_user_id,
        get_db=mock_get_db_session,
    )

    # Configuring symbols BEFORE start
    global_bot_config.SYMBOL_SOURCE_MODE = "STATIC_LIST"
    global_bot_config.SYMBOL_SOURCE_STATIC_LIST = ["BTCUSDT"]

    # Immediately after creating the controller (and before start),
    # simulate the launch of the VolumeBreakout strategy so that it is in running_strategy_instances
    mock_strat_payload = {
        "id": "e2e-test-strat-id",
        "user_id": test_user_id,
        "config_data": {
            "strategy_name": "VolumeBreakout",
            "symbol": "BTCUSDT",
            "mode": "live",
            "symbol_selection_mode": "STATIC",
            "symbols": ["BTCUSDT"],
        },
    }
    await controller._handle_start_strategy_command(mock_strat_payload)

    data_consumer_instance = controller.consumer

    global_bot_config.SYMBOL_SOURCE_MODE = "STATIC_LIST"
    global_bot_config.SYMBOL_COOLDOWN_SECONDS = 1
    global_bot_config.DEFAULT_RISK_PER_TRADE_PERCENT = 0.5
    max_pos_size_pct = getattr(
        global_bot_config, "BACKTEST_MAX_POSITION_SIZE_PCT_BALANCE", 0.1
    )
    setattr(
        global_bot_config,
        "BACKTEST_MAX_POSITION_SIZE_PCT_BALANCE",
        max_pos_size_pct if max_pos_size_pct is not None else 0.1,
    )
    global_bot_config.CONTROLLER_LOOP_DELAY = 0.05
    global_bot_config.LOG_LEVEL = "DEBUG"
    global_bot_config.STRATEGY_SYMBOL_PERFORMANCE_ADJUSTMENT_ENABLED = False
    global_bot_config.API_RECV_WINDOW = 60000

    test_strategy_name = "VolumeBreakout"
    if test_strategy_name in global_bot_config.STRATEGY_DEFAULTS:
        global_bot_config.STRATEGY_DEFAULTS[test_strategy_name]["enabled"] = True
    else:
        pytest.skip(
            f"Test strategy {test_strategy_name} not found in STRATEGY_DEFAULTS."
        )

    await controller.start()
    await asyncio.sleep(5)

    yield controller, data_consumer_instance, test_executor, risk_manager, market_type

    # Teardown
    logger.info("[Fixture Teardown] Starting trading_components teardown...")
    if hasattr(controller, "_running") and controller._running:
        logger.info("[Fixture Teardown] Stopping controller...")
        await controller.stop()
        logger.info("[Fixture Teardown] Controller stopped.")

    if hasattr(data_consumer_instance, "_running") and data_consumer_instance._running:
        logger.info("[Fixture Teardown] Explicitly stopping DataConsumer...")
        await data_consumer_instance.stop()
        logger.info("[Fixture Teardown] DataConsumer explicitly stopped.")

    if (
        hasattr(test_executor, "_session")
        and test_executor._session
        and not test_executor._session.closed
    ):
        logger.info(
            "[Fixture Teardown] Executor session found open, attempting explicit close."
        )
        await test_executor.close()
        logger.info("[Fixture Teardown] Executor explicitly closed.")


async def wait_for_position_status(
    controller: TradingController,
    symbol: str,
    target_status: str,
    timeout: float = 30.0,
    expect_removal_if_closed: bool = False,
) -> Optional[Position]:
    start_time = time.monotonic()
    logger.info(
        f"[WaitForStatus] Waiting for {symbol} to reach status '{target_status}' (timeout: {timeout}s, expect_removal_if_closed: {expect_removal_if_closed})"
    )

    last_known_position_status: Optional[str] = None

    while time.monotonic() - start_time < timeout:
        current_position: Optional[Position] = None
        is_symbol_active = False
        async with controller._positions_dict_lock:  # Ensure thread-safe access
            current_position = controller._active_position_get(symbol)
            if current_position:
                is_symbol_active = True
                last_known_position_status = current_position.status
            else:  # Symbol not in _active_positions
                is_symbol_active = False
                last_known_position_status = "NOT_IN_ACTIVE_POSITIONS"

        if target_status == "CLOSED" and expect_removal_if_closed:
            if (
                not is_symbol_active
            ):  # Key check: symbol removed AND it was there before
                logger.info(
                    f"[WaitForStatus] {symbol} successfully removed from _active_positions (expected for CLOSED status)."
                )
                return None
            # If still active, continue polling until timeout, even if current_position.status is "CLOSED"
            # The removal is the true sign for this specific condition.
        elif (
            current_position and current_position.status == target_status
        ):  # Check current_position exists before accessing status
            logger.info(
                f"[WaitForStatus] {symbol} reached target status '{target_status}'. Position: {current_position}"
            )
            return current_position
        # Removed the specific check for "OPEN" and not position_was_once_active as it's covered by the general logic.

        await asyncio.sleep(0.2)  # Poll interval

    logger.warning(
        f"[WaitForStatus] Timeout waiting for {symbol} to reach status '{target_status}' (or be removed if expect_removal_if_closed=True). Last known status: {last_known_position_status}"
    )
    async with controller._positions_dict_lock:
        return controller._active_position_get(symbol)


async def wait_for_order_update(
    controller: TradingController,
    client_order_id: str,
    target_status: str,
    timeout: float = 15.0,
) -> bool:
    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout:
        async with controller._positions_dict_lock:
            for pos in controller._active_positions.values():
                if (
                    pos.entry_client_order_id == client_order_id
                    and pos.entry_order_status == target_status
                ):
                    return True
                if pos.current_sl_client_order_id == client_order_id:
                    logger.debug(
                        f"SL order CID {client_order_id} found in position, assuming relevant status for test."
                    )
                    return True
                for ptp in pos.partial_tp_orders:
                    if (
                        ptp.client_order_id == client_order_id
                        and ptp.status == target_status
                    ):
                        return True
        await asyncio.sleep(0.2)
    logger.warning(
        f"Timeout waiting for order {client_order_id} to reach status {target_status}"
    )
    return False


@pytest.mark.parametrize(
    "configured_trading_market_type", list(MARKET_PARAMS.keys()), indirect=True
)
@pytest.mark.asyncio
async def test_full_trade_cycle_long_market(
    trading_components, configured_trading_market_type
):
    controller, data_consumer, executor, risk_manager, market_type = trading_components

    market_specifics = MARKET_PARAMS[market_type]
    test_symbol = market_specifics["test_symbol"]
    initial_balance_asset = market_specifics["initial_balance_asset"]
    min_balance_check = market_specifics["min_balance_check"]
    test_strategy_name = "VolumeBreakout"

    logger.info(f"[E2E Test START] Market Type: {market_type}, Symbol: {test_symbol}")

    balance_info = await executor.get_account_balance()
    assert balance_info is not None, (
        f"executor.get_account_balance() returned None for market {market_type}."
    )
    assert balance_info, (
        f"executor.get_account_balance() returned empty for market {market_type}."
    )
    asset_balance_data = balance_info.get(initial_balance_asset, {})
    asset_free_balance_str = asset_balance_data.get("free", "0")
    asset_free_balance = float(asset_free_balance_str)
    assert asset_free_balance > min_balance_check, (
        f"Insufficient {initial_balance_asset} balance for E2E test."
    )

    global_bot_config.SYMBOL_SOURCE_STATIC_LIST = [test_symbol]
    await controller._check_and_update_symbols()

    logger.info(
        "[E2E_Test] Waiting for DataConsumer to initialize subscriptions and history from Testnet..."
    )
    # Increase the timeout significantly. E2E tests can be slow.
    await asyncio.sleep(5)

    assert test_symbol in controller._monitored_symbols
    # Previously we checked controller._active_strategies, but now the bot uses running_strategy_instances.
    async with controller.instances_lock:
        found_instance = any(
            config_dict.get("config_data", {}).get("symbol") == test_symbol
            for _, config_dict in controller.running_strategy_instances.values()
        )
        assert found_instance, (
            f"No strategy instance found for {test_symbol} in running_strategy_instances"
        )

    # Add an additional check to see if the data has loaded
    kline_tf_for_test = global_bot_config.STRATEGY_DEFAULTS[test_strategy_name].get(
        "candle_timeframe", "1m"
    )
    kline_history_check = await data_consumer.get_kline_history(
        test_symbol, kline_tf_for_test, limit=10
    )

    # Binance may block by IP if there are too many requests.
    # This check will help us understand this.
    if kline_history_check is None or kline_history_check.empty:
        logger.warning(
            f"[E2E Test Warning] DataConsumer returned no kline history for {test_symbol} ({market_type}). This might be due to API restrictions (e.g., 451 error). Test will proceed, but strategy behavior might be affected if it heavily relies on history beyond basic price/ATR."
        )
    else:
        logger.info(
            f"[E2E_Test] DataConsumer has kline history for {test_symbol} ({len(kline_history_check)} rows)."
        )

    original_check_and_update_symbols = controller._check_and_update_symbols

    async def mock_do_nothing_check_symbols():
        pass

    controller._check_and_update_symbols = mock_do_nothing_check_symbols
    logger.info(
        "[E2E_Test] Background symbol checking in controller temporarily disabled."
    )

    original_ml_runtime_flag = controller._ml_confirmation_enabled_live_runtime
    controller._ml_confirmation_enabled_live_runtime = False
    logger.info(
        "[E2E Test] Temporarily DISABLED ML Confirmation via internal controller flag."
    )

    try:
        tick_size = await executor.get_tick_size(test_symbol)
        lot_params = await executor.get_lot_size_params(test_symbol)
        min_notional = await executor.get_min_notional(test_symbol)
        assert tick_size is not None and tick_size > 0
        assert lot_params is not None and lot_params.get("stepSize", 0) > 0

        ticker_info = await executor.get_ticker_price(test_symbol)
        assert (
            ticker_info and "price" in ticker_info and not ticker_info.get("error")
        ), (
            f"Failed to get current price for {test_symbol} ({market_type}): {ticker_info}"
        )
        current_price = float(ticker_info["price"])
        test_atr = current_price * 0.01

        pair_info_for_signal = {
            "symbol": test_symbol,
            "last_price": current_price,
            "atr": test_atr,
            "natr": 1.0,
            "tick_size": tick_size,
            "lot_params": lot_params,
            "min_notional": min_notional,
            "candle_timeframe": global_bot_config.STRATEGY_DEFAULTS[
                test_strategy_name
            ].get("candle_timeframe", "1m"),
        }

        sl_price = current_price * 0.99 if market_type == "futures_usdtm" else None
        tp_price = current_price * 1.021  # Small increase for R:R > 2.0

        signal = StrategySignal(
            strategy_name=test_strategy_name,
            symbol=test_symbol,
            direction=SignalDirection.LONG,
            stop_loss=sl_price,
            take_profit=tp_price,
            mode=OrderMode.MARKET,
            trigger_price=current_price,
            details={"test_signal": True, "foundation_total_weight": 100.0},
        )

        logger.info(f"[E2E_Test Signal ({market_type})] {signal}")
        await controller._process_signal(signal, pair_info_for_signal.copy())

        position = await wait_for_position_status(
            controller, test_symbol, "OPEN", timeout=60
        )
        assert position is not None, (
            f"Position for {test_symbol} ({market_type}) not created or timed out."
        )
        logger.info(
            f"[E2E_Test Entry Order FILLED ({market_type})] Pos Status: {position.status}"
        )

        # --- SPOT TESTNET LIMITATION ---
        # On Binance Spot Testnet, placing a STOP_LOSS order requires a separate balance reserve,
        # which is not available after buying the asset. This is a testnet limitation, not a bot error.
        # For spot, skip the SL check; for futures, check it.
        if market_type == "futures_usdtm":
            sl_placed = await wait_for_sl_order_placement(
                controller, test_symbol, timeout=30.0
            )
            assert sl_placed, (
                f"SL order was not placed for {test_symbol} within timeout."
            )
        else:
            logger.warning(
                f"[E2E_Test] Skipping SL order placement check for {market_type} due to Spot Testnet balance reservation limitations."
            )
            # Give time for processing (SL will try to be placed and fail, but the position will remain OPEN)
            await asyncio.sleep(5)

        logger.info(
            f"[E2E_Test Closing Position ({market_type})] Symbol: {test_symbol}"
        )
        await controller.close_position(test_symbol, reason="E2E_TEST_MANUAL_CLOSE")

        position_after_close = await wait_for_position_status(
            controller, test_symbol, "CLOSED", timeout=60, expect_removal_if_closed=True
        )  # Increased timeout
        assert position_after_close is None, (
            f"Position {test_symbol} ({market_type}) not removed after closing."
        )

        logger.info("[E2E_Test] Waiting for exchange order cancellation propagation...")
        await asyncio.sleep(5)
        open_orders_after_close = await executor.get_open_orders(symbol=test_symbol)

        assert not open_orders_after_close, (
            f"Not all exit orders were cancelled for {test_symbol} ({market_type}). Lingering: {open_orders_after_close}"
        )

        logger.info(
            f"[E2E Test COMPLETE] Market Type: {market_type}, Symbol: {test_symbol}"
        )
    finally:
        controller._check_and_update_symbols = original_check_and_update_symbols
        controller._ml_confirmation_enabled_live_runtime = original_ml_runtime_flag
        logger.info(
            "[E2E_Test] Restored background symbol checking and ML runtime flag."
        )
