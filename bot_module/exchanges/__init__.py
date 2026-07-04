"""Exchange adapters and factory helpers."""

from .base import ExchangeExecutor
from .common import (
    exchange_settings_key,
    is_binance_exchange,
    normalize_exchange_id,
    supported_exchange_ids,
)


from .models import (
    BalanceSnapshot,
    OrderBookSnapshot,
    OrderRequest,
    OrderResult,
    PositionSnapshot,
    SymbolFilters,
)


def create_exchange_executor(*args, **kwargs):
    from .factory import create_exchange_executor as _create_executor

    return _create_executor(*args, **kwargs)


__all__ = [
    "ExchangeExecutor",
    "create_exchange_executor",
    "exchange_settings_key",
    "is_binance_exchange",
    "normalize_exchange_id",
    "BalanceSnapshot",
    "OrderBookSnapshot",
    "OrderRequest",
    "OrderResult",
    "PositionSnapshot",
    "SymbolFilters",
    "supported_exchange_ids",
]
