# tests/test_websocket_server.py
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient
from api.websocket_server import app
from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect


@pytest.mark.asyncio
async def test_websocket_auth_success():
    """WebSocket successful authentication test."""

    # Create a "dummy" for redis_channel_listener, as its logic is not important in this test.
    # This prevents the background task from starting and a CancelledError.
    async def mock_listener_noop(*args, **kwargs):
        return

    async def mock_get_user_id(username):
        return 1

    with (
        patch(
            "api.websocket_server.validate_token", return_value="testuser"
        ) as mock_validate,
        patch("api.websocket_server._get_user_id_from_username", new=mock_get_user_id),
        patch("api.websocket_server.redis_channel_listener", new=mock_listener_noop),
    ):
        with TestClient(app) as client:
            # Successful connection and clean disconnection upon exiting with.
            with client.websocket_connect("/ws?token=valid_token"):
                pass

    mock_validate.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_auth_failure():
    """WebSocket unsuccessful authentication test."""
    with patch(
        "api.websocket_server.validate_token",
        side_effect=HTTPException(status_code=401, detail="Invalid Token"),
    ):
        with TestClient(app) as client:
            # We expect WebSocketDisconnect to be called within this block
            with pytest.raises(WebSocketDisconnect) as excinfo:
                # We use a context manager for connection,
                # but we expect any socket operation to fail.
                with client.websocket_connect("/ws?token=invalid_token") as websocket:
                    # This line MUST raise an exception,
                    # since the server has already sent a close frame.
                    websocket.receive_text()
            # Check that the close code is exactly the one we set on the server.
            assert excinfo.value.code == 1008


# =============================================================================
# CHANNEL ISOLATION TESTS (User Data Isolation)
# =============================================================================


class TestChannelAccessValidation:
    """Tests for the _is_channel_allowed function - validation of channel access rights."""

    def test_user_can_access_own_logs_channel(self):
        """User can subscribe to their logs channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 1
        channel = f"user_logs:{user_id}"

        assert _is_channel_allowed(channel, user_id) is True

    def test_user_cannot_access_other_user_logs_channel(self):
        """User CANNOT subscribe to another user's logs channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 1
        other_user_id = 2
        channel = f"user_logs:{other_user_id}"

        assert _is_channel_allowed(channel, user_id) is False

    def test_user_can_access_own_positions_channel(self):
        """User can subscribe to their positions channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 42
        channel = f"depthsight:events:positions:{user_id}"

        assert _is_channel_allowed(channel, user_id) is True

    def test_user_cannot_access_other_user_positions_channel(self):
        """User CANNOT subscribe to another user's positions channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 42
        other_user_id = 99
        channel = f"depthsight:events:positions:{other_user_id}"

        assert _is_channel_allowed(channel, user_id) is False

    def test_user_can_access_own_strategies_channel(self):
        """User can subscribe to their own strategies channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 5
        channel = f"depthsight:events:strategies:{user_id}"

        assert _is_channel_allowed(channel, user_id) is True

    def test_user_cannot_access_other_user_strategies_channel(self):
        """User CANNOT subscribe to another user's strategies channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 5
        other_user_id = 10
        channel = f"depthsight:events:strategies:{other_user_id}"

        assert _is_channel_allowed(channel, user_id) is False

    def test_user_can_access_own_portfolio_channel(self):
        """User can subscribe to their own portfolio channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 123
        channel = f"depthsight:events:portfolio:{user_id}"

        assert _is_channel_allowed(channel, user_id) is True

    def test_user_can_access_own_trades_channel(self):
        """User can subscribe to their own trades-invalidation channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 9
        channel = f"depthsight:events:trades:{user_id}"

        assert _is_channel_allowed(channel, user_id) is True

    def test_user_cannot_access_other_user_trades_channel(self):
        """User CANNOT subscribe to another user's trades channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 9
        other_user_id = 10
        channel = f"depthsight:events:trades:{other_user_id}"

        assert _is_channel_allowed(channel, user_id) is False

    def test_user_cannot_access_other_user_portfolio_channel(self):
        """User cannot subscribe to another user's portfolio channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 123
        other_user_id = 456
        channel = f"depthsight:events:portfolio:{other_user_id}"

        assert _is_channel_allowed(channel, user_id) is False

    def test_user_can_access_own_important_logs_channel(self):
        """User can subscribe to their own important logs channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 7
        channel = f"important_logs:{user_id}"

        assert _is_channel_allowed(channel, user_id) is True

    def test_user_cannot_access_other_user_important_logs_channel(self):
        """User CANNOT subscribe to another user's important logs channel."""
        from api.websocket_server import _is_channel_allowed

        user_id = 7
        other_user_id = 8
        channel = f"important_logs:{other_user_id}"

        assert _is_channel_allowed(channel, user_id) is False

    def test_user_can_access_public_channel(self):
        """User can subscribe to a public channel without user_id."""
        from api.websocket_server import _is_channel_allowed

        user_id = 1
        channel = "depthsight:events:public"

        assert _is_channel_allowed(channel, user_id) is True

    @pytest.mark.parametrize(
        "channel",
        [
            "user_logs",
            "important_logs",
            "log_history",
            "depthsight:events:log",
            "depthsight:events:positions",
            "depthsight:events:strategies",
            "depthsight:events:portfolio",
            "depthsight:events:trades",
        ],
    )
    def test_user_cannot_access_unscoped_user_data_channels(self, channel):
        """User-data WebSocket channels must include the current user's id."""
        from api.websocket_server import _is_channel_allowed

        assert _is_channel_allowed(channel, user_id=1) is False

    def test_user_can_access_arbitrary_channel_without_user_id(self):
        """User can subscribe to an arbitrary channel without user_id at the end."""
        from api.websocket_server import _is_channel_allowed

        user_id = 999
        channel = "some:random:channel"

        assert _is_channel_allowed(channel, user_id) is True


@pytest.mark.asyncio
async def test_websocket_denies_access_to_other_user_channel():
    """
    Integration test: when attempting to subscribe to another user's channel,
    the server returns an access error.
    """
    # Mock validate_token to return username
    # Mock _get_user_id_from_username to return user_id = 1
    # Then we try to subscribe to the channel user_id = 2

    async def mock_get_user_id(username):
        return 1  # Current user has ID = 1

    async def mock_listener_noop(*args, **kwargs):
        return

    with (
        patch("api.websocket_server.validate_token", return_value="testuser"),
        patch("api.websocket_server._get_user_id_from_username", new=mock_get_user_id),
        patch("api.websocket_server.redis_channel_listener", new=mock_listener_noop),
    ):
        with TestClient(app) as client:
            with client.websocket_connect("/ws?token=valid_token") as websocket:
                # Attempting to subscribe to another user's channel (user_id = 2)
                websocket.send_json(
                    {
                        "action": "subscribe",
                        "channel": "user_logs:2",  # Someone else's channel!
                    }
                )

                # Should receive an access error
                response = websocket.receive_json()
                assert "error" in response
                assert "Access denied" in response["error"]


@pytest.mark.asyncio
async def test_websocket_allows_access_to_own_channel():
    """
    Integration test: a user can successfully subscribe to their own channel.
    """

    async def mock_get_user_id(username):
        return 1  # Current user has ID = 1

    async def mock_listener_noop(*args, **kwargs):
        # Simulate successful listener start
        await asyncio.sleep(0.01)

    with (
        patch("api.websocket_server.validate_token", return_value="testuser"),
        patch("api.websocket_server._get_user_id_from_username", new=mock_get_user_id),
        patch("api.websocket_server.redis_channel_listener", new=mock_listener_noop),
        patch("api.websocket_server.aredis.Redis") as mock_redis_class,
    ):
        # Mock Redis client
        mock_redis_instance = AsyncMock()
        mock_redis_class.return_value = mock_redis_instance

        with TestClient(app) as client:
            with client.websocket_connect("/ws?token=valid_token") as websocket:
                # Subscribing to OWN channel (user_id = 1)
                websocket.send_json(
                    {
                        "action": "subscribe",
                        "channel": "user_logs:1",  # Own channel!
                    }
                )

                # Small pause for processing
                import time

                time.sleep(0.1)

                # If there are no errors, the test is passed
                # (We do not get an "Access denied" error)


@pytest.mark.asyncio
async def test_websocket_subscription_limit():
    """Integration test: subscribing to more than MAX_CHANNELS_PER_CLIENT returns an error."""

    async def mock_get_user_id(username):
        return 1

    async def mock_listener_noop(*args, **kwargs):
        return

    with (
        patch("api.websocket_server.validate_token", return_value="testuser"),
        patch("api.websocket_server._get_user_id_from_username", new=mock_get_user_id),
        patch("api.websocket_server.redis_channel_listener", new=mock_listener_noop),
        patch("api.websocket_server.aredis.Redis") as mock_redis_class,
        patch("api.websocket_server.MAX_CHANNELS_PER_CLIENT", 2),
    ):
        mock_redis_instance = AsyncMock()
        mock_redis_class.return_value = mock_redis_instance

        import time

        with TestClient(app) as client:
            with client.websocket_connect("/ws?token=valid_token") as websocket:
                websocket.send_json({"action": "subscribe", "channel": "user_logs:1"})
                time.sleep(0.02)
                websocket.send_json(
                    {"action": "subscribe", "channel": "depthsight:events:positions:1"}
                )
                time.sleep(0.02)
                websocket.send_json(
                    {"action": "subscribe", "channel": "depthsight:events:strategies:1"}
                )
                time.sleep(0.02)

                response = websocket.receive_json()
                assert "error" in response
                assert "Subscription limit reached" in response["error"]
