# bot_module/realtime_ml_logger.py
import csv
import logging
import os
import threading
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Dict, Any, Optional
import json
import time
import sys

try:
    from bot_module import config
except ImportError:
    print(
        "[realtime_ml_logger.py WARNING] bot_module.config not found. Using default log path.",
        file=sys.stderr,
    )

    class MockRealtimeMLConfig:
        LOG_FILE_REALTIME_ML = "logs/realtime_ml_data.csv"  # Default path
        LOG_FORMAT = "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s"

    config = MockRealtimeMLConfig()

logger = logging.getLogger("bot_module.realtime_ml_logger")
if not logging.getLogger(
    "bot_module"
).hasHandlers():  # Setup if the module's root logger is not configured
    logging.basicConfig(
        level=logging.INFO,
        format=getattr(
            config,
            "LOG_FORMAT",
            "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s",
        ),
    )
    logger.warning(
        "Root logger 'bot_module' has no handlers for realtime_ml_logger. Basic config applied."
    )


class RealtimeMLLogger:
    """
    Asynchronously records the context of real signals and trade results
    for subsequent ML model training.
    """

    # Fields for logging signal context (before opening)
    SIGNAL_CONTEXT_FIELDNAMES = [
        "log_timestamp",
        "event_type",  # 'SIGNAL_CONTEXT' or 'TRADE_RESULT'
        "signal_timestamp",
        "controller_client_order_id",
        "original_signal_client_order_id",
        "strategy",
        "symbol",
        "direction",
        "signal_trigger_price",
        "signal_entry_price",
        "signal_sl",
        "signal_tp",
        "initial_risk_usd_planned",
        "raw_features_live_json",  # Features calculated at the time of the signal (if any)
        "orderbook_snapshot_json",  # Raw order book snapshot (top N levels)
        "orderbook_features_live_json",  # Features extracted from the order book (if any)
        "signal_details_json",  # Additional details from the StrategySignal object
        # Fields that will be None for SIGNAL_CONTEXT and filled for TRADE_RESULT
        "close_timestamp",
        "actual_entry_price",
        "actual_exit_price",
        "pnl",
        "exit_reason",
        "commission",
        "y_true",
    ]
    # All fields together for convenience, DictWriter will handle it
    ALL_FIELDNAMES = list(
        dict.fromkeys(SIGNAL_CONTEXT_FIELDNAMES)
    )  # Remove duplicates while preserving order

    def __init__(self, log_file_path: Optional[str] = None, max_queue_size=1000):
        self.log_queue: Queue[Optional[Dict[str, Any]]] = Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()

        self._log_file_path = log_file_path or getattr(
            config, "LOG_FILE_REALTIME_ML", "logs/realtime_ml_data.csv"
        )

        self._ensure_file_exists()
        self._writer_thread: Optional[threading.Thread] = None
        self._running = False
        logger.info(f"RealtimeMLLogger initialized. Logging to: {self._log_file_path}")

    def _ensure_file_exists(self):
        """Creates a folder and a file (with a header) if they do not exist."""
        try:
            log_dir = os.path.dirname(self._log_file_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
                logger.info(f"Created log directory for RealtimeML: {log_dir}")

            file_exists = os.path.exists(self._log_file_path)
            header_ok = False
            if file_exists and os.path.getsize(self._log_file_path) > 0:
                try:
                    with open(
                        self._log_file_path, "r", newline="", encoding="utf-8"
                    ) as csvfile:
                        reader = csv.reader(csvfile)
                        header_row = next(reader)
                        header_ok = [h.strip() for h in header_row] == [
                            f.strip() for f in self.ALL_FIELDNAMES
                        ]
                except StopIteration:  # File is empty but exists
                    header_ok = False
                except Exception as e_read:
                    logger.error(
                        f"Error reading header from existing RealtimeML log file {self._log_file_path}: {e_read}"
                    )
                    header_ok = False

            if not file_exists or not header_ok:
                mode = "a" if file_exists and not header_ok else "w"
                if (
                    not header_ok
                    and file_exists
                    and os.path.getsize(self._log_file_path) > 0
                ):
                    logger.warning(
                        f"RealtimeML log file {self._log_file_path} exists but header is incorrect. Appending new header (may create inconsistencies)."
                    )
                elif not file_exists:
                    logger.info(
                        f"RealtimeML log file {self._log_file_path} not found. Creating new file."
                    )

                try:
                    with open(
                        self._log_file_path, mode, newline="", encoding="utf-8"
                    ) as csvfile:
                        writer = csv.DictWriter(csvfile, fieldnames=self.ALL_FIELDNAMES)
                        if mode == "w" or csvfile.tell() == 0:
                            writer.writeheader()
                            logger.info(
                                f"Initialized RealtimeML log file with header: {self._log_file_path}"
                            )
                except IOError as e_write:
                    logger.error(
                        f"Error writing header to RealtimeML log file {self._log_file_path}: {e_write}"
                    )

        except Exception as e:
            logger.error(
                f"Error ensuring RealtimeML log file {self._log_file_path}: {e}",
                exc_info=True,
            )

    def start(self):
        if self._running:
            logger.warning("RealtimeMLLogger writer thread already running.")
            return
        if self._writer_thread is not None and self._writer_thread.is_alive():
            logger.warning(
                "RealtimeMLLogger writer thread is alive but _running is False? Resetting."
            )
            self._stop_event.set()
            try:
                self.log_queue.put_nowait(None)
            except Exception:
                pass
            self._writer_thread.join(timeout=1.0)

        self._stop_event.clear()
        self._writer_thread = threading.Thread(
            target=self._write_loop, name="RealtimeMLLoggerThread", daemon=True
        )
        self._running = True
        self._writer_thread.start()
        logger.info("RealtimeMLLogger writer thread started.")

    def stop(self):
        if not self._running or self._writer_thread is None:
            return
        logger.info("Stopping RealtimeMLLogger writer thread...")
        self._stop_event.set()
        try:
            self.log_queue.put(None, timeout=1.0)
        except Exception:
            logger.warning(
                "Could not add None sentinel to RealtimeML queue during stop."
            )

        if threading.current_thread() != self._writer_thread:
            self._writer_thread.join(timeout=5.0)
            if self._writer_thread.is_alive():
                logger.warning(
                    "RealtimeMLLogger writer thread did not stop gracefully."
                )

        self._running = False
        self._writer_thread = None
        logger.info("RealtimeMLLogger writer thread stopped.")

    def log_data(self, event_type: str, data: Dict[str, Any]):
        """
        Places data into the write queue.
        `event_type` must be 'SIGNAL_CONTEXT' or 'TRADE_RESULT'.
        `data` must contain keys corresponding to `SIGNAL_CONTEXT_FIELDNAMES`.
        For 'TRADE_RESULT', `data` must contain `controller_client_order_id` and result fields.
        """
        if event_type not in ["SIGNAL_CONTEXT", "TRADE_RESULT"]:
            logger.error(f"Invalid event_type '{event_type}' for RealtimeMLLogger.")
            return

        log_entry: Dict[str, Any] = {field: None for field in self.ALL_FIELDNAMES}
        log_entry["log_timestamp"] = datetime.now(timezone.utc).isoformat(
            timespec="microseconds"
        )
        log_entry["event_type"] = event_type

        # Fill fields from data
        for key, value in data.items():
            if key in self.ALL_FIELDNAMES:
                # Serialize dictionaries/lists to JSON for the corresponding fields
                if key.endswith("_json") and isinstance(value, (dict, list)):
                    try:
                        log_entry[key] = json.dumps(value, separators=(",", ":"))
                    except TypeError as e_ser:
                        logger.error(
                            f"Could not serialize field '{key}' to JSON: {e_ser}. Value: {value}"
                        )
                        log_entry[key] = str(value)  # Save as a string on error
                elif isinstance(value, float):  # Format float
                    log_entry[key] = f"{value:.8f}"
                else:
                    log_entry[key] = value
            # Ignore unknown keys since we have a strict set of fields

        try:
            self.log_queue.put_nowait(log_entry)
        except Exception:  # QueueFull
            log_info_short = {
                "event": event_type,
                "symbol": data.get("symbol"),
                "cid": data.get("controller_client_order_id"),
            }
            logger.warning(
                f"RealtimeML log queue is full. Log entry discarded: {log_info_short}"
            )

    def _write_loop(self):
        logger.debug("RealtimeMLLogger write loop starting.")
        while True:
            log_entry = None
            try:
                log_entry = self.log_queue.get(block=True)
                if log_entry is None:
                    logger.info("RealtimeMLLogger writer thread received stop signal.")
                    break

                try:
                    with open(
                        self._log_file_path, "a", newline="", encoding="utf-8"
                    ) as csvfile:
                        writer = csv.DictWriter(
                            csvfile,
                            fieldnames=self.ALL_FIELDNAMES,
                            extrasaction="ignore",
                            quoting=csv.QUOTE_MINIMAL,
                        )
                        row_to_write = {
                            k: ("" if v is None else v) for k, v in log_entry.items()
                        }
                        writer.writerow(row_to_write)
                except IOError as e:
                    logger.error(
                        f"Error writing to RealtimeML log file {self._log_file_path}: {e}"
                    )
                except Exception as e:
                    logger.error(
                        f"Unexpected error writing RealtimeML log entry: {log_entry.get('event_type')}, Error: {e}",
                        exc_info=True,
                    )
                finally:
                    self.log_queue.task_done()

            except Empty:
                continue
            except Exception as e:
                logger.error(
                    f"Error in RealtimeMLLogger write loop (getting from queue): {e}",
                    exc_info=True,
                )
                if log_entry:
                    self.log_queue.task_done()
                time.sleep(0.5)
        logger.debug("RealtimeMLLogger write loop finished.")
