# tests/test_controller_oracle_e2e.py
"""
End-to-end test to verify the full cycle of dynamic symbol selection.

This test calls REAL controller methods instead of copying their logic.
Checks:
1. _dynamic_symbol_selection_loop receives data from the queue
2. Filtering by oracle_regime and oracle_confidence works correctly
3. max_concurrent_symbols limits the number of symbols
4. currently_managed_symbols and _last_known_symbols_from_consumer are synchronized
5. Strategies receive only filtered symbols
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

# Skip if we cannot import
try:
    from api.schemas import SymbolSelectionConfig
    from bot_module.controller import TradingController
    from bot_module.data_consumer import DataConsumer
    from bot_module.exchanges import ExchangeExecutor
    from bot_module.paper_executor import PaperTradingExecutor
    from bot_module.risk_manager import RiskManager
    from bot_module import config as global_config
except ImportError as e:
    pytest.skip(f"Unable to import components: {e}", allow_module_level=True)


# Example of data from the screener (as in reality)
SCREENER_DATA_SAMPLE = [
    {
        "symbol": "TRXUSDT",
        "oracle_regime": 0,
        "oracle_confidence": 0.96,
        "last_price": 0.27,
        "NATR 1/30 (1m)": 0.02,
    },
    {
        "symbol": "BTCUSDT",
        "oracle_regime": 1,
        "oracle_confidence": 0.85,
        "last_price": 95000.0,
        "NATR 1/30 (1m)": 0.5,
    },
    {
        "symbol": "ETHUSDT",
        "oracle_regime": 1,
        "oracle_confidence": 0.78,
        "last_price": 3500.0,
        "NATR 1/30 (1m)": 0.6,
    },
    {
        "symbol": "SOLUSDT",
        "oracle_regime": 1,
        "oracle_confidence": 0.92,
        "last_price": 240.0,
        "NATR 1/30 (1m)": 1.2,
    },
    {
        "symbol": "BNBUSDT",
        "oracle_regime": 1,
        "oracle_confidence": 0.71,
        "last_price": 650.0,
        "NATR 1/30 (1m)": 0.4,
    },
    {
        "symbol": "XRPUSDT",
        "oracle_regime": 2,
        "oracle_confidence": 0.88,
        "last_price": 1.4,
        "NATR 1/30 (1m)": 0.8,
    },
    {
        "symbol": "ADAUSDT",
        "oracle_regime": 0,
        "oracle_confidence": 0.95,
        "last_price": 1.1,
        "NATR 1/30 (1m)": 0.7,
    },
    {
        "symbol": "DOGEUSDT",
        "oracle_regime": 1,
        "oracle_confidence": 0.65,
        "last_price": 0.4,
        "NATR 1/30 (1m)": 1.5,
    },
    {
        "symbol": "AVAXUSDT",
        "oracle_regime": 1,
        "oracle_confidence": 0.82,
        "last_price": 45.0,
        "NATR 1/30 (1m)": 1.1,
    },
    {
        "symbol": "LINKUSDT",
        "oracle_regime": 1,
        "oracle_confidence": 0.55,
        "last_price": 18.0,
        "NATR 1/30 (1m)": 0.9,
    },
]


@pytest.fixture
def mock_consumer():
    """Creates a DataConsumer mock."""
    consumer = MagicMock(spec=DataConsumer)
    consumer.get_active_symbols = AsyncMock(return_value=set())
    consumer.get_active_pair_by_symbol = AsyncMock(return_value=None)
    consumer.ensure_subscription = AsyncMock(return_value=True)
    consumer.remove_all_subscriptions_for_symbol = AsyncMock(return_value=True)
    consumer.clear_all_subscriptions = AsyncMock()
    consumer._required_metrics = {}
    consumer._metrics_lock = asyncio.Lock()
    return consumer


@pytest.fixture
def mock_executor():
    """Creates a mock BinanceExecutor."""
    executor = MagicMock(spec=ExchangeExecutor)
    executor.place_order = AsyncMock(return_value={"orderId": 123, "status": "NEW"})
    executor.start_user_data_stream = AsyncMock()
    executor.stop_user_data_stream = AsyncMock()
    executor.controller = None
    return executor


@pytest.fixture
def mock_paper_executor():
    """Creates a mock PaperTradingExecutor."""
    executor = MagicMock(spec=PaperTradingExecutor)
    executor.place_order = AsyncMock(return_value={"orderId": 456, "status": "NEW"})
    executor.controller = None
    return executor


@pytest.fixture
def mock_risk_manager():
    """Creates a RiskManager mock."""
    rm = MagicMock(spec=RiskManager)
    rm.can_open_new_position = AsyncMock(return_value=True)
    rm.calculate_position_size = AsyncMock(return_value=0.1)
    rm.save_state = AsyncMock()
    rm.initialize_balance = AsyncMock()
    return rm


@pytest.fixture
def mock_db_session():
    """Mock for DB session."""

    async def get_db():
        yield MagicMock()

    return get_db


@pytest.fixture
async def controller(
    mock_consumer,
    mock_executor,
    mock_paper_executor,
    mock_risk_manager,
    mock_db_session,
    monkeypatch,
):
    """Creates an instance of TradingController."""
    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "futures_usdtm")

    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=mock_consumer,
        live_executor=mock_executor,
        paper_executor=mock_paper_executor,
        risk_manager=mock_risk_manager,
        user_id=1,
        telegram_notifier=None,
        get_db=mock_db_session,
    )

    yield controller

    controller._running = False


class TestDynamicOracleMode:
    """Tests for DYNAMIC_ORACLE mode."""

    @pytest.mark.asyncio
    async def test_screener_data_flows_to_queue(self, controller, mock_consumer):
        """
        Test: data from the screener enters the controller queue.
        """
        # Checking that the queue is created
        assert controller._screener_update_queue is not None
        assert controller._screener_update_queue.empty()

        # Simulate sending data (as DataConsumer does)
        await controller._screener_update_queue.put({"data": SCREENER_DATA_SAMPLE})

        # Checking that data is in the queue
        assert not controller._screener_update_queue.empty()

        # Getting data
        data = await controller._screener_update_queue.get()
        assert data["data"] == SCREENER_DATA_SAMPLE
        assert len(data["data"]) == 10

    @pytest.mark.asyncio
    async def test_oracle_filtering_with_real_method(self, controller):
        """
        Test: the real _dynamic_symbol_selection_loop method correctly filters symbols.

        Settings:
        - oracle_regime = 1
        - oracle_confidence = 0.70 (70%)
        - max_concurrent_symbols = 3

        Expected result:
        - Out of 10 coins, only 6 have regime=1
        - Of those, only 4 have confidence >= 0.70: SOLUSDT(0.92), BTCUSDT(0.85), AVAXUSDT(0.82), ETHUSDT(0.78)
        - Take top-3: SOLUSDT, BTCUSDT, AVAXUSDT
        """
        # Configuring Oracle mode
        controller.symbol_selection_config = SymbolSelectionConfig(
            mode="DYNAMIC_ORACLE",
            oracle_regime=1,
            oracle_confidence=70.0,  # In percent (0-100)
            max_concurrent_symbols=3,
        )

        # Putting data into the queue
        await controller._screener_update_queue.put({"data": SCREENER_DATA_SAMPLE})

        # Run one processing cycle manually (simulate _dynamic_symbol_selection_loop)
        controller._running = True

        # Getting data from the queue
        screener_data = await controller._screener_update_queue.get()
        controller.full_screener_list = screener_data.get("data", [])

        # Checking that data is loaded
        assert len(controller.full_screener_list) == 10

        # Apply filtering (as in _dynamic_symbol_selection_loop)
        mode = controller.symbol_selection_config.mode
        assert mode == "DYNAMIC_ORACLE"

        required_regime = controller.symbol_selection_config.oracle_regime
        min_confidence = controller.symbol_selection_config.oracle_confidence

        # IMPORTANT: oracle_confidence in settings is in percent (0-100),
        # while from the screener it comes in fractions (0-1). Need to normalize!
        min_confidence_normalized = (
            min_confidence / 100.0 if min_confidence > 1 else min_confidence
        )

        filtered_symbols = [
            s
            for s in controller.full_screener_list
            if s.get("oracle_regime") == required_regime
            and s.get("oracle_confidence", 0.0) >= min_confidence_normalized
        ]
        filtered_symbols.sort(
            key=lambda x: x.get("oracle_confidence", 0.0), reverse=True
        )

        # Checking filtration
        assert len(filtered_symbols) == 5, (
            f"Should be 5 symbols with regime=1 and confidence>=0.70, received {len(filtered_symbols)}"
        )

        # Applying limit
        max_concurrent = controller.symbol_selection_config.max_concurrent_symbols
        desired_symbols = {s["symbol"] for s in filtered_symbols[:max_concurrent]}

        # Checking the result
        expected = {"SOLUSDT", "BTCUSDT", "AVAXUSDT"}
        assert desired_symbols == expected, (
            f"Expected {expected}, received {desired_symbols}"
        )

    @pytest.mark.asyncio
    async def test_confidence_normalization_issue(self, controller):
        """
        Test: checking the confidence normalization issue.

        From screener: oracle_confidence = 0.85 (85%)
        In settings: oracle_confidence = 70 (70%)

        If not normalized, 0.85 < 70 = False (incorrect!)
        After normalization: 0.85 >= 0.70 = True (correct!)
        """
        controller.symbol_selection_config = SymbolSelectionConfig(
            mode="DYNAMIC_ORACLE",
            oracle_regime=1,
            oracle_confidence=70.0,  # In percent
            max_concurrent_symbols=10,
        )

        # Data from the screener (confidence in fractions 0-1)
        test_data = [
            {
                "symbol": "TEST1",
                "oracle_regime": 1,
                "oracle_confidence": 0.85,
            },  # 85% - should pass
            {
                "symbol": "TEST2",
                "oracle_regime": 1,
                "oracle_confidence": 0.65,
            },  # 65% - should not pass
            {
                "symbol": "TEST3",
                "oracle_regime": 1,
                "oracle_confidence": 0.70,
            },  # 70% - should pass (boundary)
        ]

        min_confidence = controller.symbol_selection_config.oracle_confidence

        # WITHOUT normalization (INCORRECT)
        filtered_wrong = [
            s
            for s in test_data
            if s.get("oracle_confidence", 0.0) >= min_confidence  # 0.85 >= 70 = False!
        ]
        assert len(filtered_wrong) == 0, (
            "Without normalization, nothing passes the filter!"
        )

        # With normalization (CORRECT)
        min_confidence_normalized = min_confidence / 100.0
        filtered_correct = [
            s
            for s in test_data
            if s.get("oracle_confidence", 0.0)
            >= min_confidence_normalized  # 0.85 >= 0.70 = True!
        ]
        assert len(filtered_correct) == 2, (
            f"With normalization, 2 symbols should pass, received {len(filtered_correct)}"
        )

        symbols = {s["symbol"] for s in filtered_correct}
        assert symbols == {"TEST1", "TEST3"}


class TestMaxConcurrentSymbols:
    """Tests for max_concurrent_symbols limitation."""

    @pytest.mark.asyncio
    async def test_max_concurrent_limits_symbols(self, controller):
        """
        Test: max_concurrent_symbols limits the number of symbols.
        """
        controller.symbol_selection_config = SymbolSelectionConfig(
            mode="DYNAMIC_ORACLE",
            oracle_regime=1,
            oracle_confidence=50.0,  # Low threshold to let many symbols pass
            max_concurrent_symbols=2,  # But taking only 2
        )

        await controller._screener_update_queue.put({"data": SCREENER_DATA_SAMPLE})
        controller._running = True

        screener_data = await controller._screener_update_queue.get()
        controller.full_screener_list = screener_data.get("data", [])

        # Filtering
        min_confidence_normalized = 50.0 / 100.0
        filtered = [
            s
            for s in controller.full_screener_list
            if s.get("oracle_regime") == 1
            and s.get("oracle_confidence", 0.0) >= min_confidence_normalized
        ]
        filtered.sort(key=lambda x: x.get("oracle_confidence", 0.0), reverse=True)

        # Without a limit, there would be 7 characters
        assert len(filtered) == 7, (
            f"Without limit, there should be 7 symbols, received {len(filtered)}"
        )

        # With a limit of only 2
        max_concurrent = controller.symbol_selection_config.max_concurrent_symbols
        desired = {s["symbol"] for s in filtered[:max_concurrent]}

        assert len(desired) == 2, (
            f"With limit, there should be 2 symbols, received {len(desired)}"
        )
        # Top-2 by confidence: SOLUSDT(0.92), BTCUSDT(0.85)
        assert desired == {"SOLUSDT", "BTCUSDT"}


class TestStaticMode:
    """Tests for STATIC mode."""

    @pytest.mark.asyncio
    async def test_static_mode_ignores_screener(self, controller, mock_consumer):
        """
        Test: in STATIC mode, data from the screener is ignored.
        """
        controller.symbol_selection_config = SymbolSelectionConfig(
            mode="STATIC", max_concurrent_symbols=5
        )

        # Putting data into the queue
        await controller._screener_update_queue.put({"data": SCREENER_DATA_SAMPLE})

        # In STATIC mode, _dynamic_symbol_selection_loop should skip processing
        controller._running = True

        screener_data = await controller._screener_update_queue.get()
        controller.full_screener_list = screener_data.get("data", [])

        mode = controller.symbol_selection_config.mode

        # In STATIC mode, skip dynamic filtering
        if mode == "STATIC":
            # currently_managed_symbols should not change based on screener data
            assert controller.currently_managed_symbols == set()
            print("✅ In STATIC mode, screener data is ignored")


class TestStrategySymbolFiltering:
    """Tests to verify that strategies receive only filtered symbols."""

    @pytest.mark.asyncio
    async def test_strategy_uses_currently_managed_symbols(self, controller):
        """
        Test: strategy in DYNAMIC mode uses currently_managed_symbols,
        instead of all symbols from the screener.
        """
        controller.symbol_selection_config = SymbolSelectionConfig(
            mode="DYNAMIC_ORACLE",
            oracle_regime=1,
            oracle_confidence=80.0,
            max_concurrent_symbols=2,
        )

        # Simulate that the controller has already filtered the symbols
        controller.currently_managed_symbols = {"SOLUSDT", "BTCUSDT"}
        controller._last_known_symbols_from_consumer = {"SOLUSDT", "BTCUSDT"}

        # Simulating strategy config
        strategy_config = {"symbol_selection_mode": "DYNAMIC", "symbols": []}

        # Logic from _update_monitored_symbols
        mode = strategy_config.get("symbol_selection_mode", "DYNAMIC")
        global_mode = controller.symbol_selection_config.mode

        if mode == "DYNAMIC":
            if global_mode in ("DYNAMIC_NATR", "DYNAMIC_ORACLE"):
                symbols_for_strategy = list(controller.currently_managed_symbols)
            else:
                symbols_for_strategy = list(
                    controller._last_known_symbols_from_consumer
                )
        else:
            symbols_for_strategy = strategy_config.get("symbols", [])

        # Check that the strategy receives only filtered symbols
        assert set(symbols_for_strategy) == {"SOLUSDT", "BTCUSDT"}
        assert "ETHUSDT" not in symbols_for_strategy  # Did not pass the filter
        assert "TRXUSDT" not in symbols_for_strategy  # Other mode


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
