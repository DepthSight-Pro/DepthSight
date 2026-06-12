import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
from collections import defaultdict
from bot_module.exchanges.factory import create_exchange_executor
from bot_module.data_consumer import DataConsumer, _kline_cache_key, _trade_cache_key
from bot_module import config


# --- MOCKS ---
@pytest.fixture
def mock_ccxt_executor():
    with patch("bot_module.exchanges.ccxt_executor.CcxtExecutor") as m:
        yield m


@pytest.fixture
def mock_data_loader():
    with (
        patch("bot_module.data_consumer.download_klines", new_callable=AsyncMock) as dk,
        patch(
            "bot_module.data_consumer.download_open_interest", new_callable=AsyncMock
        ) as doi,
    ):
        dk.return_value = pd.DataFrame()
        doi.return_value = pd.DataFrame()
        yield dk, doi


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.mark.asyncio
async def test_factory_environment_detection(mock_session, mock_ccxt_executor):
    """Checks that the factory correctly recognizes the testnet by the suffix."""
    with patch.object(config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet"):
        # 1. Regular Binance
        create_exchange_executor("binance", "key", "secret", mock_session)
        mock_ccxt_executor.assert_called_with(
            exchange_id="binance",
            api_key="key",
            api_secret="secret",
            market_type="futures_usdtm",
            sandbox=False,
        )

        # 2. Binance Testnet via suffix
        create_exchange_executor("binance_testnet", "key", "secret", mock_session)
        mock_ccxt_executor.assert_called_with(
            exchange_id="binance",
            api_key="key",
            api_secret="secret",
            market_type="futures_usdtm",
            sandbox=True,
        )
        # 3. Bitget Testnet
        create_exchange_executor("bitget_testnet", "key", "secret", mock_session)
        mock_ccxt_executor.assert_called_with(
            exchange_id="bitget",
            api_key="key",
            api_secret="secret",
            market_type="futures_usdtm",
            sandbox=True,
        )


@pytest.mark.asyncio
async def test_data_consumer_cache_key_isolation():
    """Checks that cache keys are isolated for different environments."""
    symbol = "BTCUSDT"
    timeframe = "5m"
    market = "futures_usdtm"

    # Keys for mainnet
    key_main = _kline_cache_key(symbol, timeframe, "binance", market)
    trade_main = _trade_cache_key(symbol, "binance", market)

    # Keys for testnet
    key_test = _kline_cache_key(symbol, timeframe, "binance_testnet", market)
    trade_test = _trade_cache_key(symbol, "binance_testnet", market)

    assert key_main != key_test
    assert trade_main != trade_test
    assert "binance_testnet" in key_test
    assert "binance_testnet" in trade_test
    assert "binance:" in key_main


@pytest.mark.asyncio
async def test_data_consumer_websocket_url_selection(mock_session):
    """Checks that DataConsumer selects the correct URL for the testnet."""
    # Mock the executor in sandbox mode
    mock_executor_test = MagicMock()
    mock_executor_test.sandbox = True
    mock_executor_test.exchange_id = "binance"
    mock_executor_test.market_type = "futures_usdtm"

    with patch.object(
        config, "BINANCE_FUTURES_TESTNET_MARKET_DATA_WS_URL", "wss://testnet-url"
    ):
        consumer = DataConsumer(executor=mock_executor_test)
        # There is URL selection logic in the DataConsumer constructor
        assert consumer._binance_market_data_base_url == "wss://testnet-url"

    # Mock the executor in mainnet mode
    mock_executor_main = MagicMock()
    mock_executor_main.sandbox = False
    mock_executor_main.exchange_id = "binance"
    mock_executor_main.market_type = "futures_usdtm"

    with patch.object(
        config, "BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER", "wss://mainnet-url"
    ):
        consumer_main = DataConsumer(executor=mock_executor_main)
        assert consumer_main._binance_market_data_base_url == "wss://mainnet-url"


@pytest.mark.asyncio
async def test_data_consumer_subscription_isolation(mock_session, mock_data_loader):
    """Checks that subscriptions in the global registry are isolated."""
    loop = asyncio.get_event_loop()

    dk, doi = mock_data_loader

    # 1. Setting up the mainnet consumer
    mock_executor_main = MagicMock()
    mock_executor_main.sandbox = False
    mock_executor_main.exchange_id = "binance"
    mock_executor_main.market_type = "futures_usdtm"
    consumer_main = DataConsumer(
        loop=loop, executor=mock_executor_main, market_data_mode="direct"
    )

    # 2. Setting up the testnet consumer
    mock_executor_test = MagicMock()
    mock_executor_test.sandbox = True
    mock_executor_test.exchange_id = "binance"
    mock_executor_test.market_type = "futures_usdtm"
    consumer_test = DataConsumer(
        loop=loop, executor=mock_executor_test, market_data_mode="direct"
    )

    # Mock methods to avoid running real WS
    consumer_main._get_valid_symbols_from_exchange_info = AsyncMock(
        return_value={"BTCUSDT"}
    )
    consumer_test._get_valid_symbols_from_exchange_info = AsyncMock(
        return_value={"BTCUSDT"}
    )

    with (
        patch("bot_module.data_consumer._global_ws_registry", {}) as registry,
        patch("bot_module.data_consumer._global_ws_registry_lock", asyncio.Lock()),
        patch("bot_module.data_consumer._global_event_queues", defaultdict(set)),
        patch("bot_module.data_consumer._global_event_queues_lock", asyncio.Lock()),
        patch.object(consumer_main, "_binance_data_ws_loop", return_value=AsyncMock()),
        patch.object(consumer_test, "_binance_data_ws_loop", return_value=AsyncMock()),
    ):
        # Subscribe to mainnet
        await consumer_main.ensure_subscription("kline_1m", "BTCUSDT")
        # Subscribe to testnet
        await consumer_test.ensure_subscription("kline_1m", "BTCUSDT")

        # There should be TWO entries in the registry, as exchange_id is different
        assert len(registry) == 2

        keys = list(registry.keys())
        # Key format: exchange_id:market_type:stream
        assert any("binance_testnet:futures_usdtm:btcusdt@kline_1m" in k for k in keys)
        assert any("binance:futures_usdtm:btcusdt@kline_1m" in k for k in keys)
