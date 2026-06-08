from __future__ import annotations

from typing import Any, Callable, Coroutine, Dict, List, Optional, Protocol


class ExchangeExecutor(Protocol):
    """Runtime contract used by trading code.

    This is intentionally compatible with the existing BinanceExecutor return
    shapes. Normalized DTOs can be introduced behind this boundary in the next
    phase without changing call sites again.
    """

    exchange_id: str
    market_type: str
    supports_positions: bool
    supports_shorting: bool

    async def close(self) -> None: ...

    async def get_ticker_price(self, symbol: str) -> Optional[Dict[str, Any]]: ...

    async def fetch_exchange_info(
        self,
        force_update: bool = False,
        specific_market_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]: ...

    async def place_order(
        self, symbol: str, side: str, order_type: str, **kwargs: Any
    ) -> Dict[str, Any]: ...

    async def cancel_order(
        self,
        symbol: str,
        orderId: Optional[int] = None,
        origClientOrderId: Optional[str] = None,
        is_algo_order: bool = False,
    ) -> Dict[str, Any]: ...

    async def get_open_orders(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]: ...

    async def get_open_algo_orders(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]: ...

    async def cancel_all_open_orders(self, symbol: str) -> Dict[str, Any]: ...

    async def get_account_balance(self) -> Optional[Dict[str, Dict[str, str]]]: ...

    async def get_open_positions(self) -> List[Dict[str, Any]]: ...

    async def start_user_data_stream(
        self, callback: Callable[[Dict[str, Any]], Coroutine[Any, Any, Any]]
    ) -> Any: ...

    async def stop_user_data_stream(self) -> Any: ...
