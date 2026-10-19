# bot_module/logger_setup.py

import logging
import logging.handlers
import os
import sys

#  Using try-except to import config
try:
    from bot_module import config
except ImportError:
    # Creating a stub if config is not found
    print(
        "[logger_setup.py WARNING] bot_module.config not found. Using default log settings.",
        file=sys.stderr,
    )

    class MockLogConfig:
        LOG_LEVEL = "INFO"
        LOG_FILE_BOT = "logs/bot_module_default.log"  # Default path
        LOG_FORMAT = "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s"

    config = MockLogConfig()
try:
    from bot_module.redis_handler import RedisLogHandler

    redis_handler_available = True
except ImportError:
    redis_handler_available = False
    print(
        "[logger_setup.py WARNING] RedisLogHandler not found. Real-time log streaming will be disabled.",
        file=sys.stderr,
    )


def _shard_file_suffix() -> str:
    """Per-process file suffix for multi-process bot_runner fleets.

    Several worker processes used to open one RotatingFileHandler on the same
    path: when one process rotated, the others kept writing to the renamed
    inode, so 8 shards produced interleaved, overlapping log generations and
    everything before the first rotation was lost (2026-10-17 night run).
    A per-shard file makes rotation process-local and race-free again. Set by
    bot_runner.worker_main before (re)initializing logging; empty (no suffix)
    in single-process mode.
    """
    shard = os.environ.get("BOT_SHARD_ID")
    if shard is None:
        return ""
    try:
        return f".shard{int(shard)}"
    except (TypeError, ValueError):
        return ""


def _shard_quota_divisor() -> int:
    """How many worker processes share the LOG_ROTATE_* disk budget.

    LOG_ROTATE_MAX_MB / LOG_ROTATE_BACKUPS describe the whole service's
    budget; with N per-shard files the per-file size must be divided so the
    budget does not multiply by N (8 x 120MB x 20 would hoard 19GB).
    """
    try:
        count = int(os.environ.get("BOT_SHARD_COUNT", 1))
    except (TypeError, ValueError):
        count = 1
    return max(1, count)


def _apply_shard_quota(rotate_mb: float) -> float:
    """Divide the rotation size budget over the shard count (min 1MB)."""
    divisor = _shard_quota_divisor()
    if divisor <= 1:
        return rotate_mb
    return max(1.0, rotate_mb / divisor)


def setup_bot_logging():
    """Configures logging for the bot module."""
    # Get parameters from config
    log_level_str = getattr(config, "LOG_LEVEL", "INFO").upper()
    log_file_path = getattr(config, "LOG_FILE_BOT", "logs/bot_module_default.log")
    log_file_path = f"{log_file_path}{_shard_file_suffix()}"
    log_format = getattr(
        config,
        "LOG_FORMAT",
        "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s",
    )

    log_level = getattr(logging, log_level_str, logging.DEBUG)  # Fallback to INFO

    # Getting the root logger of our module
    module_logger = logging.getLogger("bot_module")
    module_logger.setLevel(log_level)
    # Preventing message propagation up the hierarchy (e.g., to the Python root logger)
    module_logger.propagate = False

    # Removing existing handlers to avoid duplication on repeated calls
    # (This is important if the function is called multiple times, for example in tests)
    for handler in module_logger.handlers[:]:
        try:
            handler.close()  # Close the handler file
        except Exception as e:
            # Using print, as the logger might not be ready yet
            print(
                f"[logger_setup.py WARNING] Error closing handler {handler}: {e}",
                file=sys.stderr,
            )
        module_logger.removeHandler(handler)

    # Create the logs folder if it doesn't exist
    log_dir = os.path.dirname(log_file_path)
    can_write_to_file = False
    if log_dir and log_file_path:  # Ensure the file path is specified
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)  # exist_ok=True for safety
                can_write_to_file = True
            except OSError as e:
                print(
                    f"[logger_setup.py ERROR] Error creating log directory {log_dir}: {e}",
                    file=sys.stderr,
                )
        else:
            can_write_to_file = True  # Folder exists
    else:
        print(
            f"[logger_setup.py WARNING] Log file path or directory not configured properly. Log file: {log_file_path}",
            file=sys.stderr,
        )

    # Create handlers
    handlers = []
    # Console handler (always adding)
    try:
        stream_handler = logging.StreamHandler(sys.stdout)  # Output to stdout
        stream_formatter = logging.Formatter(log_format)
        stream_handler.setFormatter(stream_formatter)
        # Setting the level for the console (can be a separate parameter in config)
        stream_handler.setLevel(log_level)  # By default, the same as the logger's
        handlers.append(stream_handler)
    except Exception as e:
        print(
            f"[logger_setup.py ERROR] Failed to create StreamHandler: {e}",
            file=sys.stderr,
        )

    # File handler (if path is available)
    if can_write_to_file and log_file_path:
        try:
            # Rotation is env-tunable: a 1000-controller night writes far more
            # than the defaults retain (10MB x 6 covered ~15 minutes at peak
            # churn, eating all forensics). Prod keeps defaults; loadtest
            # sets LOG_ROTATE_MAX_MB=50 / LOG_ROTATE_BACKUPS=20.
            # Unparseable or non-positive values fall back to defaults (a
            # negative backup count would silently destroy history).
            try:
                rotate_mb = float(os.environ.get("LOG_ROTATE_MAX_MB", 10))
                if rotate_mb < 1:
                    raise ValueError
            except (TypeError, ValueError):
                rotate_mb = 10.0
            rotate_mb = _apply_shard_quota(rotate_mb)
            try:
                rotate_backups = int(os.environ.get("LOG_ROTATE_BACKUPS", 5))
                if rotate_backups < 1:
                    raise ValueError
            except (TypeError, ValueError):
                rotate_backups = 5
            file_handler = logging.handlers.RotatingFileHandler(
                log_file_path,
                maxBytes=int(rotate_mb * 1024 * 1024),
                backupCount=rotate_backups,
                encoding="utf-8",
            )
            file_formatter = logging.Formatter(log_format)
            file_handler.setFormatter(file_formatter)
            # The file level can be made more detailed, for example DEBUG
            file_handler.setLevel(logging.DEBUG)  # Write DEBUG and above to the file
            handlers.append(file_handler)
        except Exception as e:
            print(
                f"[logger_setup.py ERROR] Error creating file handler for {log_file_path}: {e}",
                file=sys.stderr,
            )
            can_write_to_file = False  # Failed to create

    # Add RedisLogHandler
    if redis_handler_available:
        try:
            redis_handler = RedisLogHandler()
            redis_handler.setLevel(
                logging.INFO
            )  # Sending INFO level logs and above to Redis
            handlers.append(redis_handler)
        except Exception as e:
            print(
                f"[logger_setup.py ERROR] Failed to create RedisLogHandler: {e}",
                file=sys.stderr,
            )

    # Adding handlers to our logger
    if not handlers:
        print(
            "[logger_setup.py WARNING] No handlers configured for 'bot_module'. Logging might not work.",
            file=sys.stderr,
        )
        # Adding NullHandler as a last resort to avoid the "No handlers could be found" error
        module_logger.addHandler(logging.NullHandler())
    else:
        for handler in handlers:
            module_logger.addHandler(handler)

    # Setting levels for dependencies (optional)
    # Reduce noise from libraries
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(
        logging.WARNING
    )  # asyncio can be noisy in DEBUG
    logging.getLogger("urllib3").setLevel(logging.WARNING)  # requests uses urllib3

    # Informational message to the log (already via the configured logger)
    log_file_info = log_file_path if can_write_to_file else "Console only"
    # Using module_logger itself to record the first message
    module_logger.info(
        f"Bot module logging configured. Level: {log_level_str}. File: {log_file_info}"
    )

    # Return the configured logger
    return module_logger


def setup_global_logging(log_filename: str, log_level: str = "INFO"):
    """
    Configures root logger to write logs to both console and a rotating file log.
    Rotation defaults to 10MB x 5 backups; LOG_ROTATE_MAX_MB / LOG_ROTATE_BACKUPS
    env overrides it (loadtest uses 50 x 20).
    """
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, f"{log_filename}{_shard_file_suffix()}")

    log_format = "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s"
    level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates on re-initialization
    for handler in root_logger.handlers[:]:
        try:
            handler.close()
        except Exception:
            pass
        root_logger.removeHandler(handler)

    # Create console stream handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter(log_format)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(level)
    root_logger.addHandler(console_handler)

    # Create rotating file handler (env-tunable, see setup above: a 1000-bot
    # night outgrows 10MB x 6 in minutes).
    try:
        try:
            rotate_mb = float(os.environ.get("LOG_ROTATE_MAX_MB", 10))
            if rotate_mb < 1:
                raise ValueError
        except (TypeError, ValueError):
            rotate_mb = 10.0
        rotate_mb = _apply_shard_quota(rotate_mb)
        try:
            rotate_backups = int(os.environ.get("LOG_ROTATE_BACKUPS", 5))
            if rotate_backups < 1:
                raise ValueError
        except (TypeError, ValueError):
            rotate_backups = 5
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path,
            maxBytes=int(rotate_mb * 1024 * 1024),
            backupCount=rotate_backups,
            encoding="utf-8",
        )
        file_formatter = logging.Formatter(log_format)
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(level)
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(
            f"[logger_setup.py ERROR] Failed to initialize global file logging for {log_filename}: {e}",
            file=sys.stderr,
        )

    # Disable spammy debug logs from other libraries
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("ccxt.base.exchange").setLevel(logging.WARNING)

    root_logger.info(
        f"Global application logging configured. Target: logs/{log_filename}"
    )
