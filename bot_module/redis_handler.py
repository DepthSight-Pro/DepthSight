# bot_module/redis_handler.py

import logging
import json
import uuid
from contextvars import ContextVar
from datetime import datetime

import redis
from bot_module import config

# Context variable for storing user_id
user_id_context: ContextVar[int | None] = ContextVar("user_id_context", default=None)


class RedisLogHandler(logging.Handler):
    """
    Log handler that writes history to Redis List and publishes to Pub/Sub.
    """

    def __init__(self, max_history=500):
        super().__init__()
        self.redis_client = None
        self.max_history = max_history
        self._connect()

    def _connect(self):
        """Initializes a synchronous connection to Redis."""
        try:
            self.redis_client = redis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                db=config.REDIS_DB,
                username=config.REDIS_USERNAME,
                password=config.REDIS_PASSWORD,
                decode_responses=True,
            )
            self.redis_client.ping()
            print("[RedisLogHandler INFO] Successfully connected to Redis.")
        except redis.exceptions.ConnectionError as e:
            self.redis_client = None
            import sys

            print(
                f"[RedisLogHandler ERROR] Could not connect to Redis: {e}",
                file=sys.stderr,
            )
        except Exception as e:
            self.redis_client = None
            import sys

            print(
                f"[RedisLogHandler ERROR] An unexpected error occurred during Redis connection: {e}",
                file=sys.stderr,
            )

    def emit(self, record: logging.LogRecord):
        """
        Sends the log to Redis.
        """
        user_id = user_id_context.get()
        if not user_id or not self.redis_client:
            return

        try:
            log_entry = self.format_log_entry(record)
            log_json = json.dumps(log_entry)

            # Keys for Redis
            history_key = f"log_history:{user_id}"
            general_channel = f"user_logs:{user_id}"
            important_channel = f"important_logs:{user_id}"

            pipeline = self.redis_client.pipeline()
            # 1. Writing to history (always)
            pipeline.lpush(history_key, log_json)
            pipeline.ltrim(history_key, 0, self.max_history - 1)
            # 2. Publishing to the general channel (always)
            pipeline.publish(general_channel, log_json)

            # 3. Publishing to the important events channel (only for WARNING and above)
            if record.levelno >= logging.WARNING:
                pipeline.publish(important_channel, log_json)

            pipeline.execute()

        except redis.exceptions.ConnectionError as e:
            import sys

            print(
                f"[RedisLogHandler WARNING] Redis connection lost. Attempting to reconnect... Error: {e}",
                file=sys.stderr,
            )
            self._connect()

        except Exception as e:
            import sys

            print(
                f"[RedisLogHandler ERROR] Failed to write log to Redis for user {user_id}: {e}",
                file=sys.stderr,
            )

    def format_log_entry(self, record: logging.LogRecord) -> dict:
        """
        Formats the log entry into a dictionary.
        """
        entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            entry.update(record.extra_data)

        return entry
