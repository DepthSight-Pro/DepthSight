import asyncio
import os
import pytest
import ccxt.async_support as ccxt
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("TESTNET_BINANCE_FUTURES_API_KEY")
api_secret = os.environ.get("TESTNET_BINANCE_FUTURES_API_SECRET")


@pytest.mark.skipif(
    not api_key or not api_secret or "YOUR_" in api_key or "YOUR_" in api_secret,
    reason="TESTNET_BINANCE_FUTURES_API_KEY and TESTNET_BINANCE_FUTURES_API_SECRET must be set in .env",
)
@pytest.mark.asyncio
async def test_sl_lifecycle():
    exchange = ccxt.binance(
        {
            "apiKey": api_key,
            "secret": api_secret,
            "options": {
                "defaultType": "future",
            },
        }
    )
    for key, value in exchange.urls["api"].items():
        if isinstance(value, str):
            if "fapi.binance.com" in value:
                exchange.urls["api"][key] = value.replace(
                    "fapi.binance.com", "demo-fapi.binance.com"
                )

    try:
        trigger_price = 60000.0  # Way below market
        quantity = 0.001

        algo_params = {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "type": "STOP_MARKET",
            "algoType": "CONDITIONAL",
            "triggerPrice": str(trigger_price),
            "quantity": str(quantity),
            "reduceOnly": "true",
        }

        print("\nPlacing Algo Order...")
        try:
            place_resp = await exchange.request(
                "algoOrder", "fapiPrivate", "POST", params=algo_params
            )
            print("Place Response:", place_resp)
        except Exception as e:
            print(f"Exception during request: {type(e)} - {e}")
            raise e

        algo_id = place_resp.get("algoId")
        assert algo_id is not None

        await asyncio.sleep(2)
        print(f"Cancelling Algo Order {algo_id}...")
        cancel_params = {"symbol": "BTCUSDT", "algoId": algo_id}
        cancel_resp = await exchange.request(
            "algoOrder", "fapiPrivate", "DELETE", params=cancel_params
        )
        print("Cancel Response:", cancel_resp)

    finally:
        await exchange.close()
