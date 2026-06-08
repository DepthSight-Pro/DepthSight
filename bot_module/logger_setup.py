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


def setup_bot_logging():
    """Configures logging for the bot module."""
    # Get parameters from config
    log_level_str = getattr(config, "LOG_LEVEL", "INFO").upper()
    log_file_path = getattr(config, "LOG_FILE_BOT", "logs/bot_module_default.log")
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
            # Using logging.handlers.RotatingFileHandler
            # Increasing file size and number of backups
            file_handler = logging.handlers.RotatingFileHandler(
                log_file_path,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
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
