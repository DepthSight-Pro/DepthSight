from __future__ import annotations

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
