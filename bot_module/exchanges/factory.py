from __future__ import annotations

import aiohttp

from .base import ExchangeExecutor


from .common import (
    is_binance_exchange,
    normalize_exchange_id,
)


def _normalize_market_type(market_type: str | None) -> str | None:
    if market_type is None:
        return None
    raw = market_type.strip().lower()
    if raw in {
        "spot",
        "binance_spot",
        "bitget_spot",
        "gateio_spot",
        "bingx_spot",
        "okx_spot",
        "weex_spot",
        "hyperliquid_spot",
    }:
        return "spot"
    if raw in {
        "futures",
        "future",
        "futures_usdtm",
        "usdtm",
        "linear",
        "swap",
        "binance_futures",
        "bitget_futures",
        "bitget_usdtm",
        "bitget_linear",
        "gateio_futures",
        "gateio_usdtm",
        "gateio_linear",
        "bingx_futures",
        "bingx_usdtm",
        "bingx_linear",
        "okx_futures",
        "okx_usdtm",
        "okx_linear",
        "weex_futures",
        "weex_usdtm",
        "weex_linear",
        "hyperliquid_futures",
        "hyperliquid_swap",
        "hyperliquid_linear",
    }:
        return "futures_usdtm"
    return raw


def _default_market_type_for_exchange(exchange: str | None) -> str:
    raw = (exchange or "binance").strip().lower()
    if raw.endswith("_spot") or raw == "spot":
        return "spot"
    return "futures_usdtm"


def create_exchange_executor(
    exchange: str | None,
    api_key: str,
    api_secret: str,
    session: aiohttp.ClientSession,
    market_type: str | None = None,
    **kwargs,
) -> ExchangeExecutor:
    exchange_id = normalize_exchange_id(exchange)
    resolved_market_type = _normalize_market_type(
        market_type
    ) or _default_market_type_for_exchange(exchange)

    # Strip testnet suffix for mapping and CCXT
    clean_exchange_id = exchange_id.replace("_testnet", "")

    # Detect testnet from explicit kwargs, suffix, or legacy global config
    from bot_module import config

    if "sandbox" in kwargs:
        is_testnet = bool(kwargs.pop("sandbox"))
    elif "is_testnet" in kwargs:
        is_testnet = bool(kwargs.pop("is_testnet"))
    elif exchange_id.endswith("_testnet"):
        is_testnet = True
    elif is_binance_exchange(exchange_id):
        # Legacy Binance untagged keys follow global ACTIVE_TRADING_ENVIRONMENT
        is_testnet = (
            getattr(config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet") == "testnet"
        )
    elif clean_exchange_id == "bingx":
        # BingX uses VST demo sandbox when globally in testnet
        is_testnet = (
            getattr(config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet") == "testnet"
        )
    else:
        is_testnet = False

    # Map known exchange aliases to CCXT identifiers
    supported_ccxt_exchanges = {
        "binance",
        "bybit",
        "okx",
        "bitget",
        "kucoin",
        "bingx",
        "bybit_linear",
        "bybit_spot",
        "bitget_spot",
        "gateio",
        "gateio_spot",
        "bingx_spot",
        "okx_spot",
        "weex",
        "weex_spot",
        "hyperliquid",
        "hyperliquid_spot",
    }
    if clean_exchange_id not in supported_ccxt_exchanges:
        raise NotImplementedError(
            f"Exchange '{clean_exchange_id}' is not supported by the CCXT executor factory."
        )

    # Map back aliases for CCXT
    ccxt_id_map = {
        "bybit_linear": "bybit",
        "bybit_spot": "bybit",
        "bitget_spot": "bitget",
        "gateio_spot": "gateio",
        "bingx_spot": "bingx",
        "okx_spot": "okx",
        "weex_spot": "weex",
        "hyperliquid_spot": "hyperliquid",
    }

    target_ccxt_id = ccxt_id_map.get(clean_exchange_id, clean_exchange_id)

    from .ccxt_executor import CcxtExecutor

    return CcxtExecutor(
        exchange_id=target_ccxt_id,
        api_key=api_key,
        api_secret=api_secret,
        market_type=resolved_market_type,
        sandbox=is_testnet,
        session=session,
        **kwargs,
    )
