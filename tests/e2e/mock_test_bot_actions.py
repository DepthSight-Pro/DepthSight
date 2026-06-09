# tests/e2e/test_bot_actions.py
import pytest
import requests
import time
import logging

logger = logging.getLogger(__name__)

MOCK_BINANCE_URL = "http://127.0.0.1:9999"  # Port of your mock server


@pytest.mark.e2e
def test_signal_triggers_order_placement(
    running_bot_with_mock_binance,  # New fixture that we will create in conftest.py
):
    """
    Checks that the bot places an order after receiving market data from the mock server.
    """
    logger.info("--- Starting test: test_signal_triggers_order_placement ---")

    # 1. Clear the mock server state before the test
    requests.delete(f"{MOCK_BINANCE_URL}/__control/clear_state")
    logger.info("Mock server state cleared.")

    # 2. Form "trigger" data for the candle
    trigger_kline_data = {
        "e": "kline",
        "E": int(time.time() * 1000),
        "s": "BTCUSDT",
        "k": {
            "t": int(time.time() * 1000) - 60000,
            "T": int(time.time() * 1000) - 1,
            "s": "BTCUSDT",
            "i": "1m",
            "f": 100,
            "L": 200,
            "o": "70000",
            "c": "71000",
            "h": "71100",
            "l": "69900",
            "v": "100",  # Large volume for VolumeBreakout
            "n": 100,
            "x": True,
            "q": "7050000",
            "V": "50",
            "Q": "3525000",
        },
    }

    # 3. "Feed" data to the bot via our mock server
    logger.info("Pushing trigger kline data to mock server...")
    response = requests.post(
        f"{MOCK_BINANCE_URL}/__control/push_ws_data",
        json={"stream": "btcusdt@kline_1m", "data": trigger_kline_data},
    )
    assert response.status_code == 200
    logger.info("Data pushed successfully.")

    # 4. Give the bot time to process (determined experimentally)
    time.sleep(3)

    # 5. Check if our mock server received an order from the bot
    logger.info("Fetching received orders from mock server...")
    response = requests.get(f"{MOCK_BINANCE_URL}/__control/get_received_orders")
    assert response.status_code == 200
    data = response.json()

    assert "orders" in data
    assert len(data["orders"]) == 1, (
        f"Expected 1 order, received: {len(data['orders'])}. Response: {data}"
    )

    received_order = data["orders"][0]
    logger.info(f"Received order: {received_order}")

    # 6. Check order details
    assert received_order["symbol"] == "BTCUSDT"
    assert received_order["side"] == "BUY"
    assert received_order["type"] == "MARKET"
    assert float(received_order["quantity"]) > 0

    logger.info("E2E Test Passed: Bot successfully placed an order.")
