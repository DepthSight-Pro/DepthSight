from __future__ import annotations

import aiohttp

from bot_module.executor import BinanceExecutor


class BinanceExchangeExecutor(BinanceExecutor):
    """Exchange adapter for Binance.

    It deliberately subclasses the current BinanceExecutor so existing code and
    tests that rely on Binance-specific response shapes keep working while
    callers move to the exchange factory.
    """

    exchange_id = "binance"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        session: aiohttp.ClientSession,
        market_type: str = "futures_usdtm",
        exchange_id: str = "binance",
    ):
        super().__init__(
            api_key=api_key,
            api_secret=api_secret,
            session=session,
            market_type=market_type,
        )
        self.exchange_id = exchange_id
        self.supports_positions = self.market_type == "futures_usdtm"
        self.supports_shorting = self.market_type == "futures_usdtm"
