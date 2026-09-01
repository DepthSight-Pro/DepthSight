import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot_module.exchanges.ccxt_executor import CcxtExecutor
from bot_module.controller import TradingController
from bot_module.exchanges.common import normalize_exchange_id, supported_exchange_ids


def test_weex_exchange_support_registration():
    assert "weex" in supported_exchange_ids()
    assert normalize_exchange_id("weex") == "weex"
    assert normalize_exchange_id("weex_futures") == "weex"
    assert normalize_exchange_id("weex_spot") == "weex_spot"


@pytest.mark.asyncio
async def test_weex_executor_market_type_params():
    executor_futures = CcxtExecutor(
        exchange_id="weex",
        api_key="mock_key",
        api_secret="mock_secret",
        market_type="futures_usdtm",
    )
    executor_spot = CcxtExecutor(
        exchange_id="weex",
        api_key="mock_key",
        api_secret="mock_secret",
        market_type="spot",
    )

    executor_futures._exchange.fetch_balance = AsyncMock(
        return_value={
            "info": {},
            "total": {"USDT": 100},
            "free": {"USDT": 100},
            "used": {"USDT": 0},
        }
    )
    executor_spot._exchange.fetch_balance = AsyncMock(
        return_value={
            "info": {},
            "total": {"USDT": 50},
            "free": {"USDT": 50},
            "used": {"USDT": 0},
        }
    )

    bal_futures = await executor_futures.get_account_balance()
    bal_spot = await executor_spot.get_account_balance()

    executor_futures._exchange.fetch_balance.assert_called_once_with({"type": "swap"})
    executor_spot._exchange.fetch_balance.assert_called_once_with({"type": "spot"})

    assert bal_futures["USDT"]["free"] == "100.0"
    assert bal_spot["USDT"]["free"] == "50.0"

    await executor_futures.close()
    await executor_spot.close()


@pytest.mark.asyncio
async def test_controller_accepts_weex_start_strategy():
    mock_data_consumer = MagicMock()
    mock_live_executor = MagicMock()
    mock_live_executor.exchange_id = "weex"
    mock_live_executor.supports_positions = True

    mock_paper_executor = MagicMock()
    mock_risk_manager = MagicMock()
    mock_risk_manager.initialize = AsyncMock()

    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=mock_data_consumer,
        live_executor=mock_live_executor,
        paper_executor=mock_paper_executor,
        risk_manager=mock_risk_manager,
        user_id=158,
        api_key_id=99,
        api_key_name="WEEX_KEY",
    )

    controller._update_monitored_symbols = AsyncMock()

    start_payload = {
        "user_id": 158,
        "api_key_id": 99,
        "id": "test-config-12345",
        "mode": "paper",
        "symbol_selection_mode": "STATIC",
        "symbols": ["XRPUSDT"],
        "config_data": {
            "strategy_name": "VisualBuilderStrategy",
            "symbol": "XRPUSDT",
            "market_type": "futures_usdtm",
        },
    }

    await controller._handle_start_strategy_command(start_payload)

    assert "test-config-12345" in controller.running_strategy_instances
    controller._update_monitored_symbols.assert_called_once()
