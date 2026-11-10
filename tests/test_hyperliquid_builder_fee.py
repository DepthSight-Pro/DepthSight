# tests/test_hyperliquid_builder_fee.py
import json
from unittest.mock import Mock
import pytest

from bot_module import config
from bot_module.exchanges import create_exchange_executor
from bot_module.exchanges.ccxt_executor import CcxtExecutor


@pytest.fixture(autouse=True)
def setup_builder_config(monkeypatch):
    monkeypatch.setattr(config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")
    monkeypatch.setattr(
        config,
        "HYPERLIQUID_BUILDER_ADDRESS",
        "0x1111111111111111111111111111111111111111",
    )
    monkeypatch.setattr(config, "HYPERLIQUID_BUILDER_FEE_RATE", "0.05%")


def test_hyperliquid_default_builder_fee():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="hyperliquid",
        api_key="0x1234567890abcdef1234567890abcdef12345678",
        api_secret="0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        session=session,
    )

    assert isinstance(executor, CcxtExecutor)
    opts = executor._exchange.options
    assert opts.get("builder") == "0x1111111111111111111111111111111111111111"
    assert opts.get("feeRate") == "0.05%"
    assert opts.get("feeInt") == 50
    assert opts.get("builderFee") is True


def test_hyperliquid_low_cost_tier():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="hyperliquid",
        api_key="0x1234567890abcdef1234567890abcdef12345678",
        api_secret="0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        session=session,
        builder_fee_rate="0.01%",
    )

    opts = executor._exchange.options
    assert opts.get("feeRate") == "0.01%"
    assert opts.get("feeInt") == 10
    assert opts.get("builderFee") is True


def test_hyperliquid_degen_max_mining_tier():
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="hyperliquid",
        api_key="0x1234567890abcdef1234567890abcdef12345678",
        api_secret="0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        session=session,
        builder_fee_rate="0.10%",
    )

    opts = executor._exchange.options
    assert opts.get("feeRate") == "0.10%"
    assert opts.get("feeInt") == 100
    assert opts.get("builderFee") is True


def test_hyperliquid_packed_secret_tier():
    session = Mock()
    session.closed = False

    packed_secret = json.dumps(
        {
            "secret": "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "password": "0.10%",
            "builder_fee_rate": "0.10%",
        }
    )

    executor = create_exchange_executor(
        exchange="hyperliquid",
        api_key="0x1234567890abcdef1234567890abcdef12345678",
        api_secret=packed_secret,
        session=session,
    )

    opts = executor._exchange.options
    assert opts.get("feeRate") == "0.10%"
    assert opts.get("feeInt") == 100
    assert opts.get("builderFee") is True
    # Verify secret was properly unpacked
    assert executor._exchange.privateKey == "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"


def test_hyperliquid_disabled_builder_fee(monkeypatch):
    monkeypatch.setattr(config, "HYPERLIQUID_BUILDER_ADDRESS", "")
    session = Mock()
    session.closed = False

    executor = create_exchange_executor(
        exchange="hyperliquid",
        api_key="0x1234567890abcdef1234567890abcdef12345678",
        api_secret="0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        session=session,
    )

    opts = executor._exchange.options
    assert opts.get("builderFee") is False
    assert opts.get("approvedBuilderFee") is False


