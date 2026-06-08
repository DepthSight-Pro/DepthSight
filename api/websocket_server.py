# api/websocket_server.py

import asyncio
import json
import re
import uvicorn
import redis.asyncio as aredis
from typing import Dict, Optional
from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    status,
    Query,
    HTTPException,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from redis.exceptions import ConnectionError as RedisConnectionError
from api.security import validate_token
from api.database import async_session_factory
from api import crud
import os
from dotenv import load_dotenv

import logging

logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s"
    )

# Load .env if it exists
load_dotenv()

# --- Settings ---
# Use environment variables as in the main API
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_USERNAME = os.getenv("REDIS_USERNAME") or None
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

MAX_CHANNELS_PER_CLIENT = 50

# --- Global storage for tracking listener tasks ---
# { websocket_client: { "_user_id": int, "channel_name": (asyncio.Task, aredis.Redis), ... } }
active_listeners: Dict[WebSocket, Dict[str, any]] = {}

# --- FastAPI Application ---
app = FastAPI(title="depthsight-websocket-server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; frame-ancestors 'none';"
    )
    return response


def _is_channel_allowed(channel: str, user_id: int) -> bool:
    """
    Checks if the user has access to the channel.
    Channels with user_id in the name are allowed only to the owner.

    Protected channels (require user_id at the end):
    - user_logs:{user_id}
    - important_logs:{user_id}
    - depthsight:events:positions:{user_id}
    - depthsight:events:strategies:{user_id}
    - depthsight:events:portfolio:{user_id}
    """
    # Patterns of protected channels that require matching user_id
    protected_patterns = [
        r"^user_logs:(\d+)$",
        r"^important_logs:(\d+)$",
        r"^depthsight:events:positions:(\d+)$",
        r"^depthsight:events:strategies:(\d+)$",
        r"^depthsight:events:portfolio:(\d+)$",
        r"^log_history:(\d+)$",
        # HFT Channels are currently global for the singleton engine
    ]

    legacy_user_data_channels = {
        "user_logs",
        "important_logs",
        "log_history",
        "depthsight:events:log",
        "depthsight:events:positions",
        "depthsight:events:strategies",
        "depthsight:events:portfolio",
    }

    if channel in legacy_user_data_channels:
        logger.warning(
            f"SECURITY: User {user_id} attempted to access unscoped user-data channel {channel}"
        )
        return False

    for pattern in protected_patterns:
        match = re.match(pattern, channel)
        if match:
            channel_user_id = int(match.group(1))
            if channel_user_id != user_id:
                logger.warning(
                    f"SECURITY: User {user_id} attempted to access channel for user {channel_user_id}"
                )
                return False
            return True

    # Common channels without user_id are allowed (e.g. for public events)
    return True


async def _get_user_id_from_username(username: str) -> Optional[int]:
    """
    Retrieves user_id from the database by username.
    """
    try:
        async with async_session_factory() as db:
            user = await crud.get_user_by_username(db, username=username)
            if user:
                return user.id
            return None
    except Exception as e:
        logger.error(f"Failed to get user_id for username '{username}': {e}")
        return None


async def redis_channel_listener(
    websocket: WebSocket, redis_client: aredis.Redis, channel: str
):
    """
    Asynchronous task that listens to ONE Redis channel and forwards messages
    to the specified WebSocket. Supports automatic reconnection.
    """
    pubsub = None
    logger.info(f"Listener starting for channel: {channel}")

    while True:
        try:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel)
            logger.info(f"Subscribed to {channel}")

            while True:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if message and message.get("type") == "message":
                        payload_str = message["data"]
                        event_data = {
                            "topic": channel,
                            "payload": json.loads(payload_str),
                        }
                        await websocket.send_json(event_data)
                except json.JSONDecodeError:
                    logger.warning(
                        f"Could not decode JSON from Redis message on channel {channel}"
                    )
                except (RedisConnectionError, ConnectionRefusedError) as e:
                    logger.warning(f"Redis connection error for channel {channel}: {e}")
                    break  # Break inner loop to trigger reconnect
                except Exception as e:
                    logger.error(f"Error in listener loop for {channel}: {e}")
                    break
                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            logger.info(f"Listener for channel {channel} cancelled.")
            break
        except Exception as e:
            logger.error(f"Failed to subscribe to {channel}, retrying: {e}")
            await asyncio.sleep(2)
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
                except Exception:
                    pass

    logger.info(f"Listener stopped for channel: {channel}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = Query(None)):
    """Main WebSocket entry point managing authentication and subscription lifecycle."""
    username = None
    user_id = None

    # 1. Authentication
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
        username = validate_token(
            token=token, credentials_exception=credentials_exception
        )

        # Get user_id from the database to validate channels
        user_id = await _get_user_id_from_username(username)
        if user_id is None:
            logger.warning(
                f"User '{username}' not found in database during WebSocket auth."
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await websocket.accept()
        logger.info(
            f"WebSocket connection accepted for user: {username} (ID: {user_id})"
        )
        active_listeners[websocket] = {"_user_id": user_id}
    except (HTTPException, Exception) as e:
        logger.warning(
            f"WebSocket connection refused for token '{token[:10] if token else 'None'}...'. Reason: {getattr(e, 'detail', str(e))}"
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 2. Main loop for receiving commands from client (subscribe/unsubscribe)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            channel = data.get("channel")

            if not action or not channel:
                continue

            if action == "subscribe":
                # Check access to the channel
                if not _is_channel_allowed(channel, user_id):
                    logger.warning(
                        f"User {username} (ID: {user_id}) denied access to channel: {channel}"
                    )
                    await websocket.send_json(
                        {"error": f"Access denied to channel: {channel}"}
                    )
                    continue

                if channel not in active_listeners[websocket]:
                    # Limit the number of subscriptions per client to prevent resource exhaustion
                    active_channels_count = len(
                        [
                            k
                            for k in active_listeners[websocket].keys()
                            if k != "_user_id"
                        ]
                    )
                    if active_channels_count >= MAX_CHANNELS_PER_CLIENT:
                        logger.warning(
                            f"User {username} (ID: {user_id}) reached maximum subscription limit of {MAX_CHANNELS_PER_CLIENT} channels."
                        )
                        await websocket.send_json(
                            {
                                "error": f"Subscription limit reached ({MAX_CHANNELS_PER_CLIENT} channels max)"
                            }
                        )
                        continue

                    logger.info(
                        f"User {username} (ID: {user_id}) subscribing to channel: {channel}"
                    )
                    # Create a new Redis client for this subscription
                    redis_client = aredis.Redis(
                        host=REDIS_HOST,
                        port=REDIS_PORT,
                        db=REDIS_DB,
                        username=REDIS_USERNAME,
                        password=REDIS_PASSWORD,
                        decode_responses=True,
                    )
                    task = asyncio.create_task(
                        redis_channel_listener(websocket, redis_client, channel)
                    )
                    active_listeners[websocket][channel] = (task, redis_client)
                else:
                    logger.warning(
                        f"User {username} attempted to subscribe to already active channel: {channel}"
                    )

            elif action == "unsubscribe":
                if channel in active_listeners[websocket] and channel != "_user_id":
                    logger.info(
                        f"User {username} unsubscribing from channel: {channel}"
                    )
                    task, redis_client = active_listeners[websocket].pop(channel)
                    task.cancel()
                    await redis_client.close()
                else:
                    logger.warning(
                        f"User {username} attempted to unsubscribe from inactive channel: {channel}"
                    )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user: {username}")
    except Exception as e:
        logger.error(
            f"An error occurred in the main loop for user {username}: {e}",
            exc_info=True,
        )
    finally:
        # 3. Resource cleanup on disconnect
        if websocket in active_listeners:
            listener_count = len(
                [k for k in active_listeners[websocket].keys() if k != "_user_id"]
            )
            logger.info(
                f"Cleaning up {listener_count} active listeners for disconnected user {username}."
            )
            for channel, value in list(active_listeners[websocket].items()):
                if channel == "_user_id":
                    continue
                task, redis_client = value
                task.cancel()
                try:
                    await redis_client.close()
                except Exception:
                    pass
                logger.info(f"Cleaned up listener for channel: {channel}")
            del active_listeners[websocket]


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
