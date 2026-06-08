from __future__ import annotations

import aiohttp

from .base import ExchangeExecutor


_EXCHANGE_ALIASES = {
    "binance": "binance",
    "binance_futures": "binance",
    "binance_usdtm": "binance",
    "binance_linear": "binance",
    "binance_spot": "binance",
    "bybit": "bybit_linear",
    "bybit_linear": "bybit_linear",
    "bybit_futures": "bybit_linear",
    "bybit_spot": "bybit_spot",
    "bitget": "bitget",
    "bitget_futures": "bitget",
    "bitget_usdtm": "bitget",
    "bitget_linear": "bitget",
    "bitget_spot": "bitget_spot",
    "gate": "gateio",
    "gateio": "gateio",
    "gateio_futures": "gateio",
    "gateio_usdtm": "gateio",
    "gateio_linear": "gateio",
    "gateio_spot": "gateio_spot",
    "bingx": "bingx",
    "bingx_futures": "bingx",
    "bingx_usdtm": "bingx",
    "bingx_linear": "bingx",
    "bingx_spot": "bingx_spot",
    "okx": "okx",
    "okx_futures": "okx",
    "okx_usdtm": "okx",
    "okx_linear": "okx",
    "okx_spot": "okx_spot",
}


def normalize_exchange_id(exchange: str | None) -> str:
    raw = (exchange or "binance").strip().lower()

    # Check for testnet suffix
    if raw.endswith("_testnet"):
        base = raw.replace("_testnet", "")
        normalized_base = _EXCHANGE_ALIASES.get(base, base)
        return f"{normalized_base}_testnet"

    return _EXCHANGE_ALIASES.get(raw, raw)


def supported_exchange_ids() -> tuple[str, ...]:
    return ("binance", "bybit", "gateio", "okx", "bitget", "kucoin", "bingx")


def is_binance_exchange(exchange: str | None) -> bool:
    return normalize_exchange_id(exchange).startswith("binance")


def exchange_settings_key(exchange: str | None) -> str:
    # We want to use the base exchange for settings/config lookups
    return normalize_exchange_id(exchange).replace("_testnet", "")


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
    }:
        return "spot"
    if raw in {
        "futures",
        "future",
        "futures_usdtm",
        "usdtm",
        "linear",
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

    # Detect testnet from suffix or global config
    from bot_module import config

    is_testnet = exchange_id.endswith("_testnet") or (
        getattr(config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet") == "testnet"
    )

    # Strip testnet suffix for mapping and CCXT
    clean_exchange_id = exchange_id.replace("_testnet", "")

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
    }

    target_ccxt_id = ccxt_id_map.get(clean_exchange_id, clean_exchange_id)

    from .ccxt_executor import CcxtExecutor

    return CcxtExecutor(
        exchange_id=target_ccxt_id,
        api_key=api_key,
        api_secret=api_secret,
        market_type=resolved_market_type,
        sandbox=is_testnet,
        **kwargs,
    )
