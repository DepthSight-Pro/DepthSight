import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot_module.exchanges.ccxt_executor import CcxtExecutor


def make_executor(exchange_id="bybit", market_type="futures_usdtm"):
    executor = object.__new__(CcxtExecutor)
    executor.exchange_id = exchange_id
    executor.market_type = market_type
    executor.supports_positions = market_type != "spot"
    executor.supports_shorting = executor.supports_positions
    executor._exchange = SimpleNamespace()
    executor._exchange.markets = {}
    executor._exchange_pro = None
    return executor


@pytest.mark.asyncio
async def test_bitget_executor_unpacks_packed_secret_password():
    packed_secret = json.dumps(
        {
            "secret": "secret-value",
            "password": "passphrase-value",
        }
    )
    executor = CcxtExecutor(
        "bitget",
        "key-value",
        packed_secret,
        market_type="futures_usdtm",
        sandbox=False,
    )

    try:
        assert executor._exchange.apiKey == "key-value"
        assert executor._exchange.secret == "secret-value"
        assert executor._exchange.password == "passphrase-value"
        assert executor._exchange.options["defaultType"] == "swap"
    finally:
        await executor.close()


@pytest.mark.asyncio
async def test_binance_demo_patches_ccxt_pro_private_ws_url():
    executor = CcxtExecutor(
        "binance",
        "key-value",
        "secret-value",
        market_type="futures_usdtm",
        sandbox=True,
    )

    try:
        assert (
            executor._exchange.urls["api"]["fapiPrivate"]
            == "https://demo-fapi.binance.com/fapi/v1"
        )
        assert (
            executor._exchange_pro.urls["api"]["fapiPrivate"]
            == "https://demo-fapi.binance.com/fapi/v1"
        )
        assert (
            executor._exchange_pro.urls["api"]["ws"]["future"]
            == "wss://demo-fstream.binance.com/ws"
        )
        assert (
            executor._exchange_pro.get_private_ws_url("future", "listen-key")
            == "wss://demo-fstream.binance.com/private/ws?listenKey=listen-key"
        )
    finally:
        await executor.close()


@pytest.mark.asyncio
async def test_gateio_packed_password_sets_uid_for_private_ws_subscriptions():
    packed_secret = json.dumps(
        {
            "secret": "secret-value",
            "password": "123456",
        }
    )
    executor = CcxtExecutor(
        "gateio",
        "key-value",
        packed_secret,
        market_type="futures_usdtm",
        sandbox=False,
    )

    try:
        assert executor._exchange.uid == "123456"
        assert executor._exchange_pro.uid == "123456"
        assert executor._exchange.options["uid"] == "123456"
        assert executor._exchange_pro.options["uid"] == "123456"
    finally:
        await executor.close()


def test_to_execution_report_maps_ccxt_order_without_name_error():
    executor = make_executor()

    report = executor._to_execution_report(
        {
            "id": "order-1",
            "clientOrderId": "client-1",
            "symbol": "BTC/USDT:USDT",
            "side": "buy",
            "type": "limit",
            "status": "open",
            "amount": 2,
            "filled": 0.5,
            "price": 100,
            "fee": {"cost": 0.01, "currency": "USDT"},
        }
    )

    data = report["o"] if "o" in report else report
    assert data["s"] == "BTCUSDT"
    assert data["X"] == "PARTIALLY_FILLED"
    assert data["x"] == "TRADE"
    assert data["z"] == "0.5"
    assert data["n"] == "0.01"
    assert data["N"] == "USDT"


@pytest.mark.asyncio
async def test_start_user_data_stream_skips_unreliable_sandbox_private_ws():
    executor = make_executor("gateio")
    executor.sandbox = True
    executor._exchange_pro = SimpleNamespace()

    result = await executor.start_user_data_stream(AsyncMock())

    assert result is None
    assert getattr(executor, "_user_data_running", False) is False


def test_map_ccxt_order_uses_average_and_filled_for_market_orders():
    executor = make_executor("bybit")

    mapped = executor._map_ccxt_order_to_binance(
        {
            "id": "order-1",
            "clientOrderId": "client-1",
            "symbol": "XRP/USDT",
            "type": "market",
            "side": "buy",
            "status": None,
            "amount": 12,
            "filled": 12,
            "price": None,
            "average": 2.5,
        }
    )

    assert mapped["status"] == "FILLED"
    assert mapped["price"] == "2.5"
    assert mapped["avgPrice"] == "2.5"
    assert mapped["origQty"] == "12.0"
    assert mapped["executedQty"] == "12.0"


def test_map_ccxt_order_handles_bybit_ack_with_empty_unified_fields():
    executor = make_executor("bybit")

    mapped = executor._map_ccxt_order_to_binance(
        {
            "id": "order-1",
            "clientOrderId": "client-1",
            "symbol": "XRP/USDT:USDT",
            "type": "market",
            "side": None,
            "status": None,
            "amount": None,
            "filled": None,
            "price": None,
            "average": None,
            "info": {
                "orderId": "order-1",
                "orderLinkId": "client-1",
                "symbol": "XRPUSDT",
                "side": "Buy",
                "orderType": "Market",
                "qty": "20.5",
            },
        }
    )

    assert mapped["symbol"] == "XRPUSDT"
    assert mapped["orderId"] == "order-1"
    assert mapped["clientOrderId"] == "client-1"
    assert mapped["side"] == "BUY"
    assert mapped["type"] == "MARKET"
    assert mapped["origQty"] == "20.5"
    assert mapped["status"] == "NEW"


@pytest.mark.asyncio
async def test_place_order_maps_conditional_order_params_for_bybit():
    executor = make_executor("bybit")
    executor._exchange.create_order = AsyncMock(
        return_value={
            "id": "order-1",
            "clientOrderId": "client-1",
            "symbol": "BTC/USDT:USDT",
            "status": "open",
            "type": "market",
            "side": "sell",
            "amount": 1,
            "filled": 0,
        }
    )

    response = await executor.place_order(
        "BTCUSDT",
        "SELL",
        "STOP_MARKET",
        quantity="1",
        stopPrice="95000",
        reduceOnly=True,
        newClientOrderId="client-1",
    )

    call = executor._exchange.create_order.call_args.kwargs
    assert call["symbol"] == "BTC/USDT:USDT"
    assert call["type"] == "market"
    assert call["side"] == "sell"
    assert call["amount"] == 1.0
    assert call["params"]["triggerPrice"] == 95000.0
    assert "stopPrice" not in call["params"]
    assert "stopLossPrice" not in call["params"]
    assert "takeProfitPrice" not in call["params"]
    assert call["params"]["triggerDirection"] == 2
    assert call["params"]["reduceOnly"] is True
    assert call["params"]["clientOrderId"] == "client-1"
    assert response["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_place_order_omits_reduce_only_for_spot_markets():
    executor = make_executor("bybit", market_type="spot")
    executor._exchange.create_order = AsyncMock(
        return_value={
            "id": "order-1",
            "clientOrderId": "client-1",
            "symbol": "XRP/USDT",
            "status": "open",
            "type": "limit",
            "side": "sell",
            "amount": 1,
            "filled": 0,
        }
    )

    await executor.place_order(
        "XRPUSDT",
        "SELL",
        "LIMIT",
        quantity="1",
        price="2",
        reduceOnly=True,
        newClientOrderId="client-1",
    )

    call = executor._exchange.create_order.call_args.kwargs
    assert "reduceOnly" not in call["params"]
    assert call["params"]["clientOrderId"] == "client-1"


@pytest.mark.asyncio
async def test_place_order_omits_bybit_trigger_direction_for_spot_stop_orders():
    executor = make_executor("bybit", market_type="spot")
    executor._exchange.create_order = AsyncMock(
        return_value={
            "id": "order-1",
            "clientOrderId": "client-1",
            "symbol": "XRP/USDT",
            "status": "open",
            "type": "market",
            "side": "sell",
            "amount": 1,
            "filled": 0,
        }
    )

    await executor.place_order(
        "XRPUSDT",
        "SELL",
        "STOP_MARKET",
        quantity="1",
        stopPrice="1.1",
        reduceOnly=True,
        newClientOrderId="client-1",
    )

    call = executor._exchange.create_order.call_args.kwargs
    assert call["params"]["triggerPrice"] == 1.1
    assert "triggerDirection" not in call["params"]
    assert "reduceOnly" not in call["params"]
    assert call["params"]["orderFilter"] == "tpslOrder"


@pytest.mark.asyncio
async def test_place_order_uses_ccxt_hedged_param_for_bitget_futures_close():
    executor = make_executor("bitget")
    executor._exchange.create_order = AsyncMock(
        return_value={
            "id": "order-1",
            "clientOrderId": "client-1",
            "symbol": "BTC/USDT:USDT",
            "status": "open",
            "type": "limit",
            "side": "sell",
            "amount": 1,
            "filled": 0,
        }
    )

    await executor.place_order(
        "BTCUSDT",
        "SELL",
        "LIMIT",
        quantity="1",
        price="95000",
        reduceOnly=True,
        newClientOrderId="client-1",
    )

    call = executor._exchange.create_order.call_args.kwargs
    assert call["side"] == "sell"
    assert call["params"]["hedged"] is True
    assert call["params"]["reduceOnly"] is True
    assert "tradeSide" not in call["params"]
    assert "positionSide" not in call["params"]


@pytest.mark.asyncio
async def test_place_order_translates_bitget_tpsl_side_to_position_side():
    executor = make_executor("bitget")
    executor._exchange.create_order = AsyncMock(
        return_value={
            "id": "order-1",
            "clientOrderId": "client-1",
            "symbol": "BTC/USDT:USDT",
            "status": "open",
            "type": "market",
            "side": "buy",
            "amount": 1,
            "filled": 0,
        }
    )

    await executor.place_order(
        "BTCUSDT",
        "SELL",
        "STOP_MARKET",
        quantity="1",
        stopPrice="90000",
        reduceOnly=True,
        newClientOrderId="client-1",
    )

    call = executor._exchange.create_order.call_args.kwargs
    assert call["side"] == "buy"
    assert call["params"]["hedged"] is True
    assert call["params"]["stopLossPrice"] == 90000.0
    assert call["params"]["reduceOnly"] is True
    assert "tradeSide" not in call["params"]
    assert "positionSide" not in call["params"]


@pytest.mark.asyncio
async def test_place_order_bitget_one_way_retry_keeps_reduce_only():
    executor = make_executor("bitget")
    executor._exchange.create_order = AsyncMock(
        side_effect=[
            Exception('bitget {"code":"40774","msg":"mode mismatch"}'),
            {
                "id": "order-1",
                "clientOrderId": "client-1",
                "symbol": "BTC/USDT:USDT",
                "status": "open",
                "type": "market",
                "side": "sell",
                "amount": 1,
                "filled": 0,
            },
        ]
    )

    await executor.place_order(
        "BTCUSDT",
        "SELL",
        "MARKET",
        quantity="1",
        reduceOnly=True,
        newClientOrderId="client-1",
    )

    retry_call = executor._exchange.create_order.call_args_list[1].kwargs
    assert retry_call["params"]["hedged"] is False
    assert retry_call["params"]["reduceOnly"] is True
    assert "tradeSide" not in retry_call["params"]
    assert "positionSide" not in retry_call["params"]
    assert executor._bitget_is_unilateral is True


@pytest.mark.asyncio
async def test_place_order_uses_binance_futures_algo_order_api_for_stop_market():
    executor = make_executor("binance")
    executor._exchange.price_to_precision = lambda symbol, price: f"{price:.1f}"
    executor._exchange.amount_to_precision = lambda symbol, amount: f"{amount:.4f}"
    executor._exchange.fapiPrivatePostAlgoOrder = AsyncMock(
        return_value={
            "algoId": "algo-1",
            "clientAlgoId": "x-sl-1",
            "status": "NEW",
            "type": "STOP_MARKET",
            "side": "SELL",
        }
    )

    response = await executor.place_order(
        "BTCUSDT",
        "SELL",
        "STOP_MARKET",
        quantity="0.0131",
        stopPrice="75502.94",
        reduceOnly="true",
        newClientOrderId="x-sl-1",
    )

    executor._exchange.fapiPrivatePostAlgoOrder.assert_awaited_once_with(
        {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "type": "STOP_MARKET",
            "algoType": "CONDITIONAL",
            "triggerPrice": "75502.9",
            "quantity": "0.0131",
            "reduceOnly": "true",
            "clientAlgoId": "x-sl-1",
        }
    )
    assert response["algoId"] == "algo-1"
    assert response["orderId"] == "algo-1"
    assert response["clientOrderId"] == "x-sl-1"
    assert response["stopPrice"] == "75502.94"


@pytest.mark.asyncio
async def test_place_order_falls_back_to_raw_request_when_binance_algo_method_is_missing():
    executor = make_executor("binance")
    executor._exchange.price_to_precision = lambda symbol, price: f"{price:.1f}"
    executor._exchange.amount_to_precision = lambda symbol, amount: f"{amount:.4f}"
    executor._exchange.request = AsyncMock(
        return_value={
            "algoId": "algo-1",
            "clientAlgoId": "x-sl-1",
            "status": "NEW",
        }
    )

    response = await executor.place_order(
        "BTCUSDT",
        "SELL",
        "STOP_MARKET",
        quantity="0.0131",
        stopPrice="75502.94",
        reduceOnly="true",
        newClientOrderId="x-sl-1",
    )

    executor._exchange.request.assert_awaited_once_with(
        "algoOrder",
        "fapiPrivate",
        "POST",
        {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "type": "STOP_MARKET",
            "algoType": "CONDITIONAL",
            "triggerPrice": "75502.9",
            "quantity": "0.0131",
            "reduceOnly": "true",
            "clientAlgoId": "x-sl-1",
        },
    )
    assert response["algoId"] == "algo-1"
    assert response["clientOrderId"] == "x-sl-1"


@pytest.mark.asyncio
async def test_fetch_exchange_info_converts_decimal_precision_to_steps():
    executor = make_executor("binance")
    executor._exchange.load_markets = AsyncMock(
        return_value={
            "BTC/USDT:USDT": {
                "symbol": "BTC/USDT:USDT",
                "swap": True,
                "spot": False,
                "active": True,
                "base": "BTC",
                "quote": "USDT",
                "precision": {"price": 2, "amount": 3},
                "limits": {"amount": {"min": 0.001, "max": 100}, "cost": {"min": 5}},
            }
        }
    )

    info = await executor.fetch_exchange_info(specific_market_type="futures_usdtm")
    symbol = info["symbols"][0]

    assert symbol["symbol"] == "BTCUSDT"
    assert symbol["tick_size"] == 0.01
    assert symbol["lot_params"]["stepSize"] == 0.001
    assert symbol["lot_params"]["minQty"] == 0.001
    assert symbol["lot_params"]["maxQty"] == 100.0
    assert symbol["min_notional"] == 5.0


@pytest.mark.asyncio
async def test_fetch_exchange_info_converts_gateio_contract_lot_to_base_quantity():
    executor = make_executor("gateio")
    executor._exchange.precisionMode = 4
    executor._exchange.load_markets = AsyncMock(
        return_value={
            "BTC/USDT:USDT": {
                "symbol": "BTC/USDT:USDT",
                "swap": True,
                "contract": True,
                "spot": False,
                "active": True,
                "base": "BTC",
                "quote": "USDT",
                "contractSize": 0.0001,
                "precision": {"price": 0.1, "amount": 1},
                "limits": {"amount": {"min": 1, "max": 1000000}, "cost": {"min": 0}},
            }
        }
    )

    info = await executor.fetch_exchange_info(specific_market_type="futures_usdtm")
    symbol = info["symbols"][0]

    assert symbol["symbol"] == "BTCUSDT"
    assert symbol["lot_params"]["stepSize"] == pytest.approx(0.0001)
    assert symbol["lot_params"]["minQty"] == pytest.approx(0.0001)
    assert symbol["lot_params"]["maxQty"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_place_order_converts_gateio_futures_base_quantity_to_contracts():
    executor = make_executor("gateio")
    executor._exchange.markets = {"BTC/USDT:USDT": {"contractSize": 0.0001}}
    executor._exchange.create_order = AsyncMock(
        return_value={
            "id": "order-1",
            "clientOrderId": "client-1",
            "symbol": "BTC/USDT:USDT",
            "status": "open",
            "type": "market",
            "side": "buy",
            "amount": 55,
            "filled": 0,
        }
    )

    response = await executor.place_order(
        "BTCUSDT",
        "BUY",
        "MARKET",
        quantity="0.0055",
        newClientOrderId="client-1",
    )

    call = executor._exchange.create_order.call_args.kwargs
    assert call["symbol"] == "BTC/USDT:USDT"
    assert call["amount"] == 55.0
    assert call["params"]["type"] == "swap"
    assert call["params"]["settle"] == "usdt"
    assert response["origQty"] == "0.0055"


@pytest.mark.asyncio
async def test_place_order_maps_gateio_futures_trigger_params():
    executor = make_executor("gateio")
    executor._exchange.markets = {"BTC/USDT:USDT": {"contractSize": 0.0001}}
    executor._exchange.create_order = AsyncMock(
        return_value={
            "id": "sl-1",
            "symbol": "BTC/USDT:USDT",
            "status": "open",
            "type": "market",
            "side": "sell",
            "amount": 10,
            "filled": 0,
            "stopPrice": 90000,
        }
    )

    response = await executor.place_order(
        "BTCUSDT",
        "SELL",
        "STOP_MARKET",
        quantity="0.001",
        stopPrice="90000",
        reduceOnly=True,
    )

    call = executor._exchange.create_order.call_args.kwargs
    assert call["amount"] == 10.0
    assert call["params"]["stopLossPrice"] == 90000.0
    assert "triggerPrice" not in call["params"]
    assert "stopPrice" not in call["params"]
    assert call["params"]["reduceOnly"] is True
    assert response["origQty"] == "0.001"


@pytest.mark.asyncio
async def test_place_order_maps_bingx_futures_trigger_params_without_generic_trigger():
    executor = make_executor("bingx")
    executor.sandbox = True
    executor._exchange.create_order = AsyncMock(
        return_value={
            "id": "sl-1",
            "symbol": "BTC/USDT:USDT",
            "status": "open",
            "type": "market",
            "side": "sell",
            "amount": 0.001,
            "filled": 0,
            "stopPrice": 90000,
        }
    )

    response = await executor.place_order(
        "BTCUSDT",
        "SELL",
        "STOP_MARKET",
        quantity="0.001",
        stopPrice="90000",
        reduceOnly=True,
    )

    call = executor._exchange.create_order.call_args.kwargs
    assert call["symbol"] == "BTC/USDT:USDT"
    assert call["amount"] == 0.001
    assert call["params"]["type"] == "swap"
    assert call["params"]["hedged"] is True
    assert call["params"]["stopLossPrice"] == 90000.0
    assert call["params"]["reduceOnly"] is True
    assert "triggerPrice" not in call["params"]
    assert "stopPrice" not in call["params"]
    assert response["orderId"] == "sl-1"


@pytest.mark.asyncio
async def test_request_returns_real_mapped_balances_and_positions():
    executor = make_executor("binance")
    executor.get_account_balance = AsyncMock(
        return_value={"USDT": {"free": "10", "locked": "2"}}
    )
    executor.get_open_positions = AsyncMock(
        return_value=[{"symbol": "BTCUSDT", "positionAmt": "0.1"}]
    )

    account = await executor._request("GET", "/fapi/v2/account")
    positions = await executor._request("GET", "/fapi/v2/positionRisk")

    assert account == [{"asset": "USDT", "availableBalance": "10", "balance": "12.0"}]
    assert positions == [{"symbol": "BTCUSDT", "positionAmt": "0.1"}]


@pytest.mark.asyncio
async def test_cancel_all_open_orders_falls_back_to_fetch_and_cancel():
    executor = make_executor("bybit")
    executor._exchange.fetch_open_orders = AsyncMock(
        return_value=[
            {"id": "order-1"},
            {"id": "order-2"},
        ]
    )
    executor._exchange.cancel_order = AsyncMock(return_value={"status": "canceled"})

    result = await executor.cancel_all_open_orders("BTCUSDT")

    executor._exchange.fetch_open_orders.assert_any_await("BTC/USDT:USDT")
    assert executor._exchange.cancel_order.await_count == 4
    assert result["status"] == "OK"
    assert result["cancelled"] == 4


@pytest.mark.asyncio
async def test_get_open_algo_orders_filters_trigger_orders():
    executor = make_executor("bybit")
    executor._exchange.fetch_open_orders = AsyncMock(
        return_value=[
            {"type": "STOP_MARKET", "stopPrice": "95000"},
        ]
    )
    executor.get_open_orders = AsyncMock(
        return_value=[
            {"type": "LIMIT", "stopPrice": "0"},
            {"type": "STOP_MARKET", "stopPrice": "95000"},
        ]
    )

    orders = await executor.get_open_algo_orders("BTCUSDT")

    assert len(orders) == 1
    assert orders[0]["type"] == "STOP_MARKET"
    assert orders[0]["stopPrice"] == "95000"


@pytest.mark.asyncio
async def test_get_open_algo_orders_fetches_bitget_futures_plan_orders():
    executor = make_executor("bitget")
    executor._exchange.fetch_open_orders = AsyncMock(
        side_effect=[
            [
                {
                    "id": "sl-1",
                    "symbol": "BTC/USDT:USDT",
                    "type": "market",
                    "side": "sell",
                    "status": "open",
                    "amount": 1,
                    "filled": 0,
                    "stopPrice": 90000,
                }
            ],
            [],
            [],
        ]
    )

    orders = await executor.get_open_algo_orders("BTCUSDT")

    assert executor._exchange.fetch_open_orders.await_count == 3
    first_call = executor._exchange.fetch_open_orders.call_args_list[0]
    assert first_call.args[0] == "BTC/USDT:USDT"
    assert first_call.kwargs["params"]["trigger"] is True
    assert first_call.kwargs["params"]["planType"] == "profit_loss"
    assert orders[0]["orderId"] == "sl-1"
    assert orders[0]["stopPrice"] == "90000"


@pytest.mark.asyncio
async def test_cancel_all_open_orders_cancels_bitget_futures_plan_orders():
    executor = make_executor("bitget")
    executor._exchange.fetch_open_orders = AsyncMock(
        side_effect=[
            [],
            [
                {
                    "id": "sl-1",
                    "symbol": "BTC/USDT:USDT",
                    "type": "market",
                    "side": "sell",
                    "status": "open",
                    "amount": 1,
                    "filled": 0,
                    "stopPrice": 90000,
                    "info": {"planType": "pos_loss"},
                }
            ],
            [],
            [],
        ]
    )
    executor._exchange.cancel_order = AsyncMock(return_value={"status": "canceled"})

    result = await executor.cancel_all_open_orders("BTCUSDT")

    cancel_call = executor._exchange.cancel_order.call_args
    assert cancel_call.args[0] == "sl-1"
    assert cancel_call.args[1] == "BTC/USDT:USDT"
    assert cancel_call.args[2]["trigger"] is True
    assert cancel_call.args[2]["planType"] == "pos_loss"
    assert result["cancelled"] == 1


@pytest.mark.asyncio
async def test_get_open_algo_orders_fetches_gateio_trigger_orders():
    executor = make_executor("gateio")
    executor._exchange.markets = {"BTC/USDT:USDT": {"contractSize": 0.0001}}
    executor._exchange.fetch_open_orders = AsyncMock(
        return_value=[
            {
                "id": "sl-1",
                "symbol": "BTC/USDT:USDT",
                "type": "market",
                "side": "sell",
                "status": "open",
                "amount": 10,
                "filled": 0,
                "stopPrice": 90000,
            }
        ]
    )

    orders = await executor.get_open_algo_orders("BTCUSDT")

    call = executor._exchange.fetch_open_orders.call_args
    assert call.args[0] == "BTC/USDT:USDT"
    assert call.kwargs["params"]["trigger"] is True
    assert call.kwargs["params"]["type"] == "swap"
    assert call.kwargs["params"]["settle"] == "usdt"
    assert orders[0]["orderId"] == "sl-1"
    assert orders[0]["origQty"] == "0.001"


@pytest.mark.asyncio
async def test_cancel_all_open_orders_cancels_gateio_trigger_orders():
    executor = make_executor("gateio")
    executor._exchange.fetch_open_orders = AsyncMock(
        side_effect=[
            [],
            [
                {
                    "id": "sl-1",
                    "symbol": "BTC/USDT:USDT",
                    "type": "market",
                    "side": "sell",
                    "status": "open",
                    "amount": 10,
                    "filled": 0,
                    "stopPrice": 90000,
                }
            ],
        ]
    )
    executor._exchange.cancel_order = AsyncMock(return_value={"status": "canceled"})

    result = await executor.cancel_all_open_orders("BTCUSDT")

    assert executor._exchange.fetch_open_orders.await_count == 2
    cancel_call = executor._exchange.cancel_order.call_args
    assert cancel_call.args[0] == "sl-1"
    assert cancel_call.args[1] == "BTC/USDT:USDT"
    assert cancel_call.args[2]["trigger"] is True
    assert cancel_call.args[2]["type"] == "swap"
    assert cancel_call.args[2]["settle"] == "usdt"
    assert result["cancelled"] == 1


@pytest.mark.asyncio
async def test_get_open_algo_orders_fetches_gateio_spot_trigger_orders():
    executor = make_executor("gateio", market_type="spot")
    executor._exchange.fetch_open_orders = AsyncMock(
        return_value=[
            {
                "id": "sl-spot-1",
                "symbol": "BTC/USDT",
                "type": "market",
                "side": "sell",
                "status": "open",
                "amount": 0.001,
                "filled": 0,
                "stopPrice": 90000,
            }
        ]
    )

    orders = await executor.get_open_algo_orders("BTCUSDT")

    call = executor._exchange.fetch_open_orders.call_args
    assert call.args[0] == "BTC/USDT"
    assert call.kwargs["params"]["trigger"] is True
    assert call.kwargs["params"]["type"] == "spot"
    assert orders[0]["orderId"] == "sl-spot-1"


@pytest.mark.asyncio
async def test_cancel_all_open_orders_cancels_gateio_spot_trigger_orders():
    executor = make_executor("gateio", market_type="spot")
    executor._exchange.cancel_all_orders = AsyncMock(return_value={})
    executor._exchange.fetch_open_orders = AsyncMock(
        side_effect=[
            [],
            [
                {
                    "id": "sl-spot-1",
                    "symbol": "BTC/USDT",
                    "type": "market",
                    "side": "sell",
                    "status": "open",
                    "amount": 0.001,
                    "filled": 0,
                    "stopPrice": 90000,
                }
            ],
        ]
    )
    executor._exchange.cancel_order = AsyncMock(return_value={"status": "canceled"})

    result = await executor.cancel_all_open_orders("BTCUSDT")

    executor._exchange.cancel_all_orders.assert_not_awaited()
    assert executor._exchange.fetch_open_orders.await_count == 2
    cancel_call = executor._exchange.cancel_order.call_args
    assert cancel_call.args[0] == "sl-spot-1"
    assert cancel_call.args[1] == "BTC/USDT"
    assert cancel_call.args[2]["trigger"] is True
    assert cancel_call.args[2]["type"] == "spot"
    assert result["cancelled"] == 1


@pytest.mark.asyncio
async def test_get_open_positions_converts_gateio_contracts_to_base_quantity():
    executor = make_executor("gateio")
    executor._exchange.markets = {"BTC/USDT:USDT": {"contractSize": 0.0001}}
    executor._exchange.fetch_positions = AsyncMock(
        return_value=[
            {
                "symbol": "BTC/USDT:USDT",
                "contracts": 55,
                "side": "long",
                "entryPrice": "90000",
                "unrealizedPnl": "1.2",
                "markPrice": "90100",
                "liquidationPrice": "50000",
            }
        ]
    )

    positions = await executor.get_open_positions()

    executor._exchange.fetch_positions.assert_awaited_once_with(
        params={"type": "swap", "settle": "usdt"}
    )
    assert positions[0]["symbol"] == "BTCUSDT"
    assert float(positions[0]["positionAmt"]) == pytest.approx(0.0055)


@pytest.mark.asyncio
async def test_bingx_balance_and_positions_use_swap_type():
    executor = make_executor("bingx")
    executor._exchange.fetch_balance = AsyncMock(
        return_value={
            "total": {"USDT": 10},
            "free": {"USDT": 9},
            "used": {"USDT": 1},
        }
    )
    executor._exchange.fetch_positions = AsyncMock(
        return_value=[
            {
                "symbol": "BTC/USDT:USDT",
                "contracts": 0.002,
                "side": "short",
                "entryPrice": "90000",
                "unrealizedPnl": "0.1",
                "markPrice": "89900",
                "liquidationPrice": "100000",
            }
        ]
    )

    balance = await executor.get_account_balance()
    positions = await executor.get_open_positions()

    executor._exchange.fetch_balance.assert_awaited_once_with({"type": "swap"})
    executor._exchange.fetch_positions.assert_awaited_once_with(params={"type": "swap"})
    assert balance["USDT"]["free"] == "9.0"
    assert positions[0]["symbol"] == "BTCUSDT"
    assert positions[0]["positionAmt"] == "-0.002"


@pytest.mark.asyncio
async def test_bingx_balance_uses_raw_virtual_margin_when_ccxt_balance_is_empty():
    executor = make_executor("bingx")
    executor.sandbox = True
    executor._exchange.fetch_balance = AsyncMock(
        return_value={
            "total": {"USDT": 0},
            "free": {"USDT": 0},
            "used": {"USDT": 0},
            "info": {
                "data": {
                    "balance": {
                        "asset": "VST",
                        "balance": "100000.0000",
                        "equity": "100000.0000",
                        "availableMargin": "100000.0000",
                        "usedMargin": "0.0000",
                        "unrealizedProfit": "0.0000",
                    }
                }
            },
        }
    )

    balance = await executor.get_account_balance()

    executor._exchange.fetch_balance.assert_awaited_once_with({"type": "swap"})
    assert balance["USDT"]["free"] == "100000.0"
    assert balance["USDT"]["locked"] == "0.0"


@pytest.mark.asyncio
async def test_bingx_balance_maps_vst_list_response_to_usdt():
    executor = make_executor("bingx")
    executor.sandbox = True
    executor._exchange.fetch_balance = AsyncMock(
        return_value={
            "total": {},
            "free": {},
            "used": {},
            "info": {
                "data": [
                    {
                        "asset": "VST",
                        "equity": "1000.0000",
                        "availableMargin": "900.0000",
                        "usedMargin": "100.0000",
                        "unrealizedProfit": "5.0000",
                    }
                ]
            },
        }
    )

    balance = await executor.get_account_balance()

    executor._exchange.fetch_balance.assert_awaited_once_with({"type": "swap"})
    assert "VST" not in balance
    assert balance["USDT"]["free"] == "900.0"
    assert balance["USDT"]["locked"] == "100.0"
    assert balance["USDT"]["unrealized_pnl"] == "5.0"


@pytest.mark.asyncio
async def test_get_open_algo_orders_uses_binance_futures_algo_endpoint():
    executor = make_executor("binance")
    executor._exchange.fapiPrivateGetOpenAlgoOrders = AsyncMock(
        return_value=[
            {
                "symbol": "BTCUSDT",
                "algoId": "algo-1",
                "clientAlgoId": "x-sl-1",
                "type": "STOP_MARKET",
                "side": "SELL",
                "triggerPrice": "95000",
                "quantity": "0.1",
                "status": "NEW",
            }
        ]
    )

    orders = await executor.get_open_algo_orders("BTCUSDT")

    executor._exchange.fapiPrivateGetOpenAlgoOrders.assert_awaited_once_with(
        {"symbol": "BTCUSDT"}
    )
    assert orders == [
        {
            "symbol": "BTCUSDT",
            "algoId": "algo-1",
            "orderId": "algo-1",
            "clientAlgoId": "x-sl-1",
            "clientOrderId": "x-sl-1",
            "transactTime": None,
            "price": "0",
            "stopPrice": "95000",
            "origQty": "0.1",
            "executedQty": "0",
            "status": "NEW",
            "type": "STOP_MARKET",
            "side": "SELL",
        }
    ]
