import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from market_data_service import MarketDataService


@pytest.mark.asyncio
async def test_market_data_service_dynamic_consumers():
    # Mocking external dependencies
    with (
        patch("market_data_service.redis_asyncio.Redis") as mock_redis_class,
        patch("market_data_service.aiohttp.ClientSession") as mock_session_class,
        patch("market_data_service.create_exchange_executor") as mock_create_executor,
        patch("market_data_service.DataConsumer") as mock_data_consumer_class,
    ):
        # Setup mock Redis
        mock_redis = MagicMock()
        mock_redis_class.return_value = mock_redis
        mock_redis.ping = AsyncMock()
        mock_redis.close = AsyncMock()  # Added this

        # pubsub() is a regular (sync) method that returns a PubSub object
        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()
        mock_redis.pubsub.return_value = mock_pubsub

        # Setup mock session
        mock_session = MagicMock()
        mock_session.close = AsyncMock()  # Added this
        mock_session_class.return_value = mock_session

        # Setup mock DataConsumer
        mock_consumers = []

        def create_mock_consumer(*args, **kwargs):
            c = MagicMock()
            c.ensure_subscription = AsyncMock()
            c.remove_subscription = AsyncMock()
            c.stop = AsyncMock()
            mock_consumers.append(c)
            return c

        mock_data_consumer_class.side_effect = create_mock_consumer

        service = MarketDataService()

        # 1. Test Start (should create Binance consumer by default)
        await service.start()

        assert "binance" in service.consumers
        assert len(service.consumers) == 1
        assert mock_create_executor.call_count == 2  # 1 for futures, 1 for spot

        # 2. Test Dynamic Subscription (Bybit)
        subscribe_command = {
            "type": "subscribe",
            "subscriber_id": "test_sub",
            "stream_keys": [
                {
                    "stream_key": "bybit:futures_usdtm:btcusdt@kline_1m",
                    "data_type_key": "kline_1m",
                    "symbol": "BTCUSDT",
                    "market_type": "futures_usdtm",
                    "exchange_id": "bybit",
                }
            ],
        }

        await service._handle_command(subscribe_command)

        assert "bybit" in service.consumers
        assert len(service.consumers) == 2
        # Bybit consumer should have been called for subscription
        bybit_consumer = service.consumers["bybit"]
        bybit_consumer.ensure_subscription.assert_called_once()

        # 3. Test Reusing Consumer (another Bybit sub)
        subscribe_command_2 = {
            "type": "subscribe",
            "subscriber_id": "test_sub_2",
            "stream_keys": [
                {
                    "stream_key": "bybit:futures_usdtm:ethusdt@kline_1m",
                    "data_type_key": "kline_1m",
                    "symbol": "ETHUSDT",
                    "market_type": "futures_usdtm",
                    "exchange_id": "bybit",
                }
            ],
        }
        await service._handle_command(subscribe_command_2)
        assert len(service.consumers) == 2  # Still 2
        assert bybit_consumer.ensure_subscription.call_count == 2

        # 4. Test Stop (should stop all consumers)
        await service.stop()
        for c in mock_consumers:
            c.stop.assert_called_once()
        assert len(service.consumers) == 0


if __name__ == "__main__":
    asyncio.run(test_market_data_service_dynamic_consumers())
