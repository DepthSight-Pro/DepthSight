# bot_module/trade_logger.py
import csv
import logging
import os
import threading
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Dict, Any, Optional, List
import json
import time
import sys
from decimal import Decimal

try:
    from bot_module import config
except ImportError:
    print(
        "[trade_logger.py WARNING] bot_module.config not found. Using default log path.",
        file=sys.stderr,
    )

    class MockTradeLogConfig:
        LOG_FILE_TRADES = "logs/trades_and_events.csv"
        LOG_FILE_TRADER_DIARY = "logs/trader_diary.csv"
        LOG_FORMAT = "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s"

    config = MockTradeLogConfig()


logger = logging.getLogger("bot_module.trade_logger")


class TradeLogger:
    # Main fields for the primary event log
    EVENT_LOG_FIELDNAMES = [  # Define as a class attribute
        "timestamp",
        "event_type",
        "symbol",
        "strategy",
        "direction",
        "order_type",
        "execution_type",
        "order_status",
        "entry_price",
        "exit_price",
        "quantity",
        "quantity_ordered",
        "quantity_filled_cumulative",
        "avg_price",
        "last_filled_price",
        "last_filled_qty",
        "initial_stop_loss",
        "initial_take_profit",
        "entry_atr",
        "trigger_price",
        "pnl",
        "commission",
        "commission_asset",
        "order_id",
        "client_order_id",
        "trade_id",
        "exit_reason",
        "ml_confirmation_approved",
        "ml_prob_good_signal",
        "ml_prob_bad_signal",
        "ml_threshold_good",
        "ml_threshold_bad_reject",
        "original_client_order_id",
        "api_key_id",
        "details",
    ]

    # New fields for "Trader's Diary"
    TRADER_DIARY_FIELDNAMES = [  # Define as a class attribute
        "close_timestamp_utc",
        "symbol",
        "strategy_name",
        "direction",
        "entry_price",
        "exit_price",
        "quantity",
        "pnl_usd",
        "pnl_percent",
        "commission_usd",
        "initial_risk_usd_planned",
        "actual_trade_risk_usd",
        "rr_ratio_prices",
        "trade_duration_sec",
        "exit_reason",
        "foundation_total_weight",
        "foundation_details_json",
        "signal_specific_details_json",
        "entry_client_order_id",
        "ml_confirmed_live",
        "ml_prob_good_signal_live",
        "api_key_id",
    ]

    def __init__(self, max_queue_size=1000):
        self.log_queue: Queue[Optional[Dict[str, Any]]] = Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()

        self._event_log_file_path = getattr(
            config, "LOG_FILE_TRADES", "logs/trades_and_events.csv"
        )
        self._trader_diary_file_path = getattr(
            config, "LOG_FILE_TRADER_DIARY", "logs/trader_diary.csv"
        )
        self._ensure_file_exists(
            self._event_log_file_path, TradeLogger.EVENT_LOG_FIELDNAMES, "EventLog"
        )
        self._ensure_file_exists(
            self._trader_diary_file_path,
            TradeLogger.TRADER_DIARY_FIELDNAMES,
            "TraderDiary",
        )

        self._writer_thread: Optional[threading.Thread] = None
        self._running = False
        logger.info(
            f"TradeLogger initialized. Event logging to: {self._event_log_file_path}"
        )
        logger.info(f"Trader Diary logging to: {self._trader_diary_file_path}")

    def _ensure_file_exists(
        self, file_path: str, fieldnames: List[str], log_type_name: str
    ):
        try:
            log_dir = os.path.dirname(file_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
                logger.info(f"Created {log_type_name} directory: {log_dir}")

            file_exists = os.path.exists(file_path)
            header_ok = False
            if file_exists:
                try:
                    with open(file_path, "r", newline="", encoding="utf-8") as csvfile:
                        reader = csv.reader(csvfile)
                        try:
                            header_row = next(reader)
                            header_ok = [h.strip() for h in header_row] == [
                                f.strip() for f in fieldnames
                            ]
                        except StopIteration:
                            header_ok = False
                except Exception as e_read:
                    logger.error(
                        f"Error reading header from existing {log_type_name} file {file_path}: {e_read}"
                    )
                    header_ok = False

            if not file_exists or not header_ok:
                mode = "a" if file_exists else "w"
                if not header_ok and file_exists:
                    logger.warning(
                        f"{log_type_name} file {file_path} exists but header is missing or incorrect. Appending header."
                    )
                try:
                    with open(file_path, mode, newline="", encoding="utf-8") as csvfile:
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                        if mode == "w" or csvfile.tell() == 0:
                            writer.writeheader()
                            logger.info(
                                f"Initialized {log_type_name} file with header: {file_path}"
                            )
                except IOError as e_write:
                    logger.error(
                        f"Error writing header to {log_type_name} file {file_path}: {e_write}"
                    )
        except Exception as e:
            logger.error(
                f"Error ensuring {log_type_name} file {file_path}: {e}", exc_info=True
            )

    def start(self):
        if self._running:
            logger.warning("TradeLogger writer thread already running.")
            return
        if self._writer_thread is not None and self._writer_thread.is_alive():
            logger.warning(
                "TradeLogger writer thread is already alive but _running is False? Resetting state."
            )
            self._stop_event.set()
            try:
                self.log_queue.put_nowait(None)
            except Exception:
                pass
            if threading.current_thread() != self._writer_thread:  # Prevent self-join
                self._writer_thread.join(timeout=1.0)

        self._stop_event.clear()
        self._writer_thread = threading.Thread(
            target=self._write_loop, name="TradeLoggerThread", daemon=True
        )
        self._running = True
        self._writer_thread.start()
        logger.info("TradeLogger writer thread started.")

    def stop(self):
        if not self._running or self._writer_thread is None:
            return
        logger.info("Stopping TradeLogger writer thread...")
        self._stop_event.set()
        try:
            self.log_queue.put(None, timeout=1.0)
        except Exception:
            logger.warning("Could not add None sentinel to queue during stop.")

        if threading.current_thread() != self._writer_thread:
            self._writer_thread.join(timeout=5.0)
            if self._writer_thread.is_alive():
                logger.warning("TradeLogger writer thread did not stop gracefully.")

        self._running = False
        self._writer_thread = None
        logger.info("TradeLogger writer thread stopped.")

    def log_event(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        log_entry: Dict[str, Any] = {
            field: None for field in TradeLogger.EVENT_LOG_FIELDNAMES
        }
        log_entry["timestamp"] = datetime.now(timezone.utc).isoformat(
            timespec="microseconds"
        )
        log_entry["event_type"] = event_type
        log_entry["_log_target_file"] = self._event_log_file_path
        log_entry["_log_fieldnames"] = TradeLogger.EVENT_LOG_FIELDNAMES

        details_dict = {}
        if data:
            data_copy = data.copy()
            details_value = data_copy.pop("details", None)
            if isinstance(details_value, (dict, list)):
                details_dict.update(details_value)
            elif details_value is not None:
                details_dict["original_details"] = str(details_value)

            for key, value in data_copy.items():
                if key in TradeLogger.EVENT_LOG_FIELDNAMES:
                    if isinstance(value, (float, Decimal)):
                        log_entry[key] = f"{float(value):.8f}"
                    else:
                        log_entry[key] = value
                else:
                    details_dict[key] = value

        if details_dict:
            try:
                log_entry["details"] = json.dumps(details_dict, separators=(",", ":"))
            except TypeError as e:
                logger.error(
                    f"Could not serialize collected details for event log: {e}. Details: {details_dict}"
                )
                log_entry["details"] = str(details_dict)
        else:
            log_entry["details"] = None

        try:
            self.log_queue.put_nowait(log_entry)
        except Exception:
            log_info_short = {
                "event": event_type,
                "symbol": data.get("symbol") if data else None,
            }
            logger.warning(
                f"Trade log queue is full. Event log entry discarded: {log_info_short}"
            )

    def log_closed_trade_to_diary(self, trade_data: Dict[str, Any]):
        log_entry: Dict[str, Any] = {
            field: None for field in TradeLogger.TRADER_DIARY_FIELDNAMES
        }
        log_entry["_log_target_file"] = self._trader_diary_file_path
        log_entry["_log_fieldnames"] = TradeLogger.TRADER_DIARY_FIELDNAMES

        log_entry["close_timestamp_utc"] = trade_data.get(
            "close_timestamp_utc",
            datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        )
        log_entry["symbol"] = trade_data.get("symbol")
        log_entry["strategy_name"] = trade_data.get("strategy_name")
        log_entry["direction"] = trade_data.get("direction")

        for key in [
            "entry_price",
            "exit_price",
            "quantity",
            "pnl_usd",
            "pnl_percent",
            "commission_usd",
            "initial_risk_usd_planned",
            "actual_trade_risk_usd",
            "rr_ratio_prices",
            "trade_duration_sec",
            "foundation_total_weight",
        ]:
            val = trade_data.get(key)
            if isinstance(val, (float, Decimal)):
                precision = 8
                if key in [
                    "pnl_usd",
                    "pnl_percent",
                    "commission_usd",
                    "initial_risk_usd_planned",
                    "actual_trade_risk_usd",
                    "rr_ratio_prices",
                    "foundation_total_weight",
                ]:
                    precision = 4
                elif key == "trade_duration_sec":
                    precision = 0
                log_entry[key] = (
                    f"{float(val):.{precision}f}" if val is not None else None
                )
            else:
                log_entry[key] = val

        log_entry["exit_reason"] = trade_data.get("exit_reason")
        log_entry["entry_client_order_id"] = trade_data.get("entry_client_order_id")
        log_entry["ml_confirmed_live"] = trade_data.get("ml_confirmed_live")
        log_entry["ml_prob_good_signal_live"] = trade_data.get(
            "ml_prob_good_signal_live"
        )
        log_entry["api_key_id"] = trade_data.get("api_key_id")

        for json_key in ["foundation_details_json", "signal_specific_details_json"]:
            raw_val = trade_data.get(json_key.replace("_json", ""))
            if isinstance(raw_val, dict):
                try:
                    log_entry[json_key] = json.dumps(raw_val, separators=(",", ":"))
                except TypeError:
                    log_entry[json_key] = str(raw_val)
            elif raw_val is not None:
                log_entry[json_key] = str(raw_val)

        try:
            self.log_queue.put_nowait(log_entry)
        except Exception:
            log_info_short = {
                "event": "CLOSED_TRADE_DIARY",
                "symbol": trade_data.get("symbol"),
            }
            logger.warning(
                f"Trade log queue is full. Trader diary entry discarded: {log_info_short}"
            )

    def _write_loop(self):
        logger.debug("TradeLogger write loop starting.")
        while True:
            log_entry = None
            try:
                log_entry = self.log_queue.get(block=True)
                if log_entry is None:
                    logger.info("TradeLogger writer thread received stop signal.")
                    break

                target_file = log_entry.pop(
                    "_log_target_file", self._event_log_file_path
                )
                target_fieldnames = log_entry.pop(
                    "_log_fieldnames", TradeLogger.EVENT_LOG_FIELDNAMES
                )

                try:
                    with open(
                        target_file, "a", newline="", encoding="utf-8"
                    ) as csvfile:
                        writer = csv.DictWriter(
                            csvfile,
                            fieldnames=target_fieldnames,
                            extrasaction="ignore",
                            quoting=csv.QUOTE_MINIMAL,
                        )
                        row_to_write = {
                            k: ("" if v is None else v)
                            for k, v in log_entry.items()
                            if k in target_fieldnames
                        }  # Added check for target_fieldnames
                        writer.writerow(row_to_write)
                except IOError as e:
                    logger.error(f"Error writing to trade log file {target_file}: {e}")
                except Exception as e:
                    # In the error log, we show only the event type and the symbol itself, if present, to avoid overloading the log
                    event_type_for_log = log_entry.get(
                        "event_type", log_entry.get("strategy_name", "UNKNOWN_EVENT")
                    )
                    symbol_for_log = log_entry.get("symbol", "NO_SYMBOL")
                    logger.error(
                        f"Unexpected error writing log entry to {target_file}: Event/Strategy='{event_type_for_log}', Symbol='{symbol_for_log}'. Error: {e}",
                        exc_info=True,
                    )
                finally:
                    self.log_queue.task_done()

            except Empty:
                continue
            except Exception as e:
                logger.error(
                    f"Error in TradeLogger write loop (getting from queue): {e}",
                    exc_info=True,
                )
                if log_entry:
                    self.log_queue.task_done()
                time.sleep(0.5)
        logger.debug("TradeLogger write loop finished.")
