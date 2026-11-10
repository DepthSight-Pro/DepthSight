import pytest
from unittest.mock import AsyncMock, MagicMock
from bot_module.risk_manager import RiskManager


@pytest.fixture
def dummy_settings():
    return {
        "risk_management": {
            "riskPerTradePercent": 1.0,
            "maxConcurrentTrades": 5,
        }
    }


@pytest.mark.asyncio
async def test_risk_manager_update_balance_usdc(dummy_settings):
    mock_executor = MagicMock()
    mock_executor.get_account_balance = AsyncMock(
        return_value={"USDC": {"free": "5.38", "locked": "0.0", "unrealized_pnl": "0"}}
    )

    rm = RiskManager(
        executor=mock_executor,
        paper_executor=None,
        user_id=186,
        db_session=None,
        user_settings=dummy_settings,
    )
    success = await rm.update_balance()

    assert success is True
    assert rm.stats.current_balance == pytest.approx(5.38)


@pytest.mark.asyncio
async def test_risk_manager_update_balance_prefers_positive_usdc_when_usdt_empty(dummy_settings):
    mock_executor = MagicMock()
    mock_executor.get_account_balance = AsyncMock(
        return_value={
            "USDT": {"free": "0.0", "locked": "0.0"},
            "USDC": {"free": "12.50", "locked": "2.50"},
        }
    )

    rm = RiskManager(
        executor=mock_executor,
        paper_executor=None,
        user_id=186,
        db_session=None,
        user_settings=dummy_settings,
    )
    success = await rm.update_balance()

    assert success is True
    assert rm.stats.current_balance == pytest.approx(15.00)


@pytest.mark.asyncio
async def test_risk_manager_update_balance_usdt(dummy_settings):
    mock_executor = MagicMock()
    mock_executor.get_account_balance = AsyncMock(
        return_value={"USDT": {"free": "100.0", "locked": "50.0"}}
    )

    rm = RiskManager(
        executor=mock_executor,
        paper_executor=None,
        user_id=186,
        db_session=None,
        user_settings=dummy_settings,
    )
    success = await rm.update_balance()

    assert success is True
    assert rm.stats.current_balance == pytest.approx(150.00)


@pytest.mark.asyncio
async def test_risk_manager_refresh_balance_and_limits_with_usdc(dummy_settings):
    mock_executor = MagicMock()
    mock_executor.get_account_balance = AsyncMock(
        return_value={"USDC": {"free": "5.38", "locked": "0.0"}}
    )

    rm = RiskManager(
        executor=mock_executor,
        paper_executor=None,
        user_id=186,
        db_session=None,
        user_settings=dummy_settings,
    )
    # min_balance_threshold is 5.0 USD, so 5.38 >= 5.0 allows trading
    success = await rm.refresh_balance_and_limits()

    assert success is True
    assert rm.stats.current_balance == pytest.approx(5.38)
    assert rm._is_trading_allowed is True
