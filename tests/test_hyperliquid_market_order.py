import pytest
from unittest.mock import AsyncMock, MagicMock
from bot_module.exchanges.ccxt_executor import CcxtExecutor


@pytest.mark.asyncio
async def test_hyperliquid_market_order_resolves_price_from_signal_details():
    mock_exchange = MagicMock()
    mock_exchange.create_order = AsyncMock(
        return_value={
            "id": "12345678",
            "symbol": "XRP/USDC:USDC",
            "type": "market",
            "side": "buy",
            "amount": 15.0,
            "status": "closed",
            "filled": 15.0,
            "price": 1.1784,
        }
    )
    mock_exchange.close = AsyncMock()
    mock_exchange.amount_to_precision = MagicMock(side_effect=lambda sym, amt: str(amt))
    mock_exchange.price_to_precision = MagicMock(side_effect=lambda sym, px: str(px))

    executor = CcxtExecutor(
        exchange_id="hyperliquid",
        api_key="0x" + "a" * 40,
        api_secret="0x" + "b" * 64,
        market_type="futures_usdtm",
        sandbox=False,
    )
    old_pro = executor._exchange_pro
    executor._exchange = mock_exchange

    try:
        res = await executor.place_order(
            symbol="XRPUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=15.0,
            price=None,
            newClientOrderId="x-entry-cc5267e3e29e4c",
            signal_details={"signal_last_price": 1.1784},
        )

        assert not res.get("error")
        # Verify create_order was called with resolved price and slippage
        mock_exchange.create_order.assert_called_once()
        call_kwargs = mock_exchange.create_order.call_args.kwargs
        assert call_kwargs["symbol"] == "XRP/USDC:USDC"
        assert call_kwargs["type"] == "market"
        assert call_kwargs["side"] == "buy"
        assert call_kwargs["price"] == pytest.approx(1.1784)
        assert call_kwargs["params"]["slippage"] == "0.05"
        # Verify cloid was formatted as 128-bit hex
        assert call_kwargs["params"]["clientOrderId"].startswith("0x")
        assert len(call_kwargs["params"]["clientOrderId"]) == 34  # 0x + 32 hex chars
        # Verify response preserved raw clientOrderId for controller
        assert res.get("clientOrderId") == "x-entry-cc5267e3e29e4c"
    finally:
        if old_pro:
            await old_pro.close()


@pytest.mark.asyncio
async def test_hyperliquid_market_order_resolves_price_from_ticker_fallback():
    mock_exchange = MagicMock()
    mock_exchange.create_order = AsyncMock(
        return_value={
            "id": "12345679",
            "symbol": "XRP/USDC:USDC",
            "type": "market",
            "side": "sell",
            "amount": 10.0,
            "status": "closed",
            "filled": 10.0,
            "price": 1.1850,
        }
    )
    mock_exchange.fetch_ticker = AsyncMock(return_value={"last": 1.1850})
    mock_exchange.close = AsyncMock()
    mock_exchange.amount_to_precision = MagicMock(side_effect=lambda sym, amt: str(amt))
    mock_exchange.price_to_precision = MagicMock(side_effect=lambda sym, px: str(px))

    executor = CcxtExecutor(
        exchange_id="hyperliquid",
        api_key="0x" + "a" * 40,
        api_secret="0x" + "b" * 64,
        market_type="futures_usdtm",
        sandbox=False,
    )
    old_pro = executor._exchange_pro
    executor._exchange = mock_exchange

    try:
        res = await executor.place_order(
            symbol="XRPUSDT",
            side="SELL",
            order_type="MARKET",
            quantity=10.0,
            price=None,
        )

        assert not res.get("error")
        mock_exchange.create_order.assert_called_once()
        call_kwargs = mock_exchange.create_order.call_args.kwargs
        assert call_kwargs["price"] == pytest.approx(1.1850)
    finally:
        if old_pro:
            await old_pro.close()
