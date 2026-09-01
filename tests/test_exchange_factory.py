from unittest.mock import Mock


from bot_module.exchanges import (
    create_exchange_executor,
    exchange_settings_key,
    is_binance_exchange,
    normalize_exchange_id,
    supported_exchange_ids,
)
from bot_module.exchanges.ccxt_executor import CcxtExecutor


def test_exchange_id_normalization():
    assert normalize_exchange_id("binance") == "binance"
    assert normalize_exchange_id("BINANCE_FUTURES") == "binance"
    assert normalize_exchange_id("bybit") == "bybit_linear"
    assert exchange_settings_key("bybit_futures") == "bybit_linear"
    assert normalize_exchange_id("bitget_futures") == "bitget"
    assert normalize_exchange_id("bitget_spot") == "bitget_spot"
    assert normalize_exchange_id("gate") == "gateio"
    assert normalize_exchange_id("gateio_futures") == "gateio"
    assert normalize_exchange_id("gateio_spot") == "gateio_spot"
    assert normalize_exchange_id("bingx_futures") == "bingx"
    assert normalize_exchange_id("bingx_spot") == "bingx_spot"
    assert normalize_exchange_id("okx_futures") == "okx"
    assert normalize_exchange_id("okx_spot") == "okx_spot"
    assert normalize_exchange_id("weex") == "weex"
    assert normalize_exchange_id("weex_futures") == "weex"
    assert normalize_exchange_id("weex_spot") == "weex_spot"


def test_supported_exchanges_are_explicit():
    # Currently still returning ("binance",) from supported_exchange_ids, leaving as is
    # or we could update supported_exchange_ids in factory.py
    assert is_binance_exchange("binance")
    assert is_binance_exchange("binance_futures")
    assert is_binance_exchange("binance_spot")
    assert not is_binance_exchange("bybit_linear")
    assert "bitget" in supported_exchange_ids()
    assert "gateio" in supported_exchange_ids()
    assert "bingx" in supported_exchange_ids()
    assert "okx" in supported_exchange_ids()
    assert "weex" in supported_exchange_ids()


def test_factory_returns_ccxt_adapter_for_existing_exchange():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="binance_futures",
        api_key="test_key",
        api_secret="test_secret",
        session=session,
    )

    assert isinstance(executor, CcxtExecutor)
    assert executor.exchange_id == "binance"
    assert executor.market_type == "futures_usdtm"
    assert executor.supports_positions is True
    assert executor.supports_shorting is True


def test_factory_returns_ccxt_spot_adapter():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="binance_spot",
        api_key="test_key",
        api_secret="test_secret",
        session=session,
    )

    assert isinstance(executor, CcxtExecutor)
    assert executor.exchange_id == "binance"
    assert executor.market_type == "spot"
    assert executor.supports_positions is False
    assert executor.supports_shorting is False


def test_factory_returns_ccxt_for_bybit():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="bybit_linear",
        api_key="test_key",
        api_secret="test_secret",
        session=session,
    )

    assert isinstance(executor, CcxtExecutor)
    assert executor.exchange_id == "bybit"
    assert executor.market_type == "futures_usdtm"
    assert executor.supports_positions is True
    assert executor.supports_shorting is True


def test_factory_returns_ccxt_for_bitget_spot():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="bitget_spot",
        api_key="test_key",
        api_secret="test_secret",
        session=session,
    )

    assert isinstance(executor, CcxtExecutor)
    assert executor.exchange_id == "bitget"
    assert executor.market_type == "spot"
    assert executor.supports_positions is False


def test_factory_returns_ccxt_for_gateio():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="gateio_futures",
        api_key="test_key",
        api_secret="test_secret",
        session=session,
    )

    assert isinstance(executor, CcxtExecutor)
    assert executor.exchange_id == "gateio"
    assert executor.market_type == "futures_usdtm"
    assert executor.supports_positions is True


def test_factory_returns_ccxt_for_bingx():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="bingx_futures",
        api_key="test_key",
        api_secret="test_secret",
        session=session,
    )

    assert isinstance(executor, CcxtExecutor)
    assert executor.exchange_id == "bingx"
    assert executor.market_type == "futures_usdtm"
    assert executor.supports_positions is True


def test_factory_returns_ccxt_for_okx():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="okx_futures",
        api_key="test_key",
        api_secret="test_secret",
        session=session,
    )

    assert isinstance(executor, CcxtExecutor)
    assert executor.exchange_id == "okx"
    assert executor.market_type == "futures_usdtm"
    assert executor.supports_positions is True


def test_factory_returns_ccxt_for_okx_spot():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="okx_spot",
        api_key="test_key",
        api_secret="test_secret",
        session=session,
    )

    assert isinstance(executor, CcxtExecutor)
    assert executor.exchange_id == "okx"
    assert executor.market_type == "spot"
    assert executor.supports_positions is False


def test_factory_enables_bingx_vst_sandbox_in_testnet(monkeypatch):
    from bot_module import config

    monkeypatch.setattr(config, "ACTIVE_TRADING_ENVIRONMENT", "testnet")
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="bingx_futures",
        api_key="test_key",
        api_secret="test_secret",
        session=session,
    )

    assert executor.exchange_id == "bingx"
    assert executor.sandbox is True
    assert executor._exchange.urls["api"]["swap"].startswith("https://open-api-vst.")


def test_factory_returns_ccxt_for_weex():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="weex",
        api_key="test_key",
        api_secret="test_secret",
        session=session,
    )

    assert isinstance(executor, CcxtExecutor)
    assert executor.exchange_id == "weex"
    assert executor.market_type == "futures_usdtm"
    assert executor.supports_positions is True


def test_factory_returns_ccxt_for_weex_spot():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="weex_spot",
        api_key="test_key",
        api_secret="test_secret",
        session=session,
    )

    assert isinstance(executor, CcxtExecutor)
    assert executor.exchange_id == "weex"
    assert executor.market_type == "spot"
    assert executor.supports_positions is False
