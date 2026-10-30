# tests/test_trade_logger.py
import pytest
import csv
import time
import json
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone
from decimal import Decimal

# Import the class under test and dependencies
try:
    from bot_module.trade_logger import TradeLogger
    from bot_module import config
except ImportError:
    pytest.skip(
        "Cannot import bot_module components for TradeLogger tests.",
        allow_module_level=True,
    )

# --- Fixtures ---


@pytest.fixture
def setup_trade_logger(tmp_path, monkeypatch):
    """Configures TradeLogger with a temporary file and starts/stops the thread."""
    log_file = tmp_path / "test_trades.csv"
    monkeypatch.setattr(config, "LOG_FILE_TRADES", str(log_file))

    # Use a small queue size for tests
    logger_instance = TradeLogger(max_queue_size=10)

    # Start the writer thread
    logger_instance.start()

    yield logger_instance, log_file  # Return the logger and the file path

    # Stop the writer thread after the test
    logger_instance.stop()


# --- Helper function ---
def read_csv_log(filepath: Path) -> list:
    """Reads all lines from the CSV log file."""
    if not filepath.exists():
        return []
    with open(filepath, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Convert lines to dictionaries
        try:
            return list(reader)
        except Exception:  # If the file is empty or invalid
            return []


# --- Tests ---


def test_logger_init_creates_file_and_header(tmp_path, monkeypatch):
    """Test: Initialization creates a file with the correct header."""
    log_file = tmp_path / "init_test.csv"
    assert not log_file.exists()
    monkeypatch.setattr(config, "LOG_FILE_TRADES", str(log_file))

    TradeLogger()  # Just initialize without starting the thread

    assert log_file.exists()
    with open(log_file, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        # Compare headers, removing spaces
        expected_header = [h.strip() for h in TradeLogger.EVENT_LOG_FIELDNAMES]
        actual_header = [h.strip() for h in header]
        assert actual_header == expected_header
        # Check that there are no other lines
        with pytest.raises(StopIteration):
            next(reader)


def test_ensure_file_exists_corrects_header(tmp_path, monkeypatch):
    """Test: _ensure_file_exists fixes/adds the header."""
    log_file = tmp_path / "header_correction.csv"
    monkeypatch.setattr(config, "LOG_FILE_TRADES", str(log_file))

    # 1. Create a file without a header
    log_file.touch()
    TradeLogger()
    rows1 = read_csv_log(log_file)
    # Check that the header was added during initialization
    # Read the file directly, as read_csv_log skips the header
    with open(log_file, "r", newline="", encoding="utf-8") as f:
        header1 = f.readline().strip().split(",")
    assert [h.strip() for h in header1] == [
        f.strip() for f in TradeLogger.EVENT_LOG_FIELDNAMES
    ]
    assert len(rows1) == 0  # No data rows

    # 2. Create a file with an incorrect header
    log_file.write_text("timestamp,wrong_col1,wrong_col2\n", encoding="utf-8")
    TradeLogger()
    # Check that the first line is still INCORRECT (since the file is not empty)
    # Check that the first line is still INCORRECT (since the file is not empty)
    # but the logger should have issued a warning
    with open(log_file, "r", newline="", encoding="utf-8") as f:
        header2 = f.readline().strip().split(",")
    assert header2 == ["timestamp", "wrong_col1", "wrong_col2"]
    # TODO: Check the log for warning (requires caplog configuration)

    # 3. Create a file with the correct header
    with open(log_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TradeLogger.EVENT_LOG_FIELDNAMES)
        writer.writeheader()
    header_size = log_file.stat().st_size
    TradeLogger()
    # Ensure that the file size has not changed (the header was not appended)
    assert log_file.stat().st_size == header_size


def test_log_event_writes_to_file(setup_trade_logger):
    """Test: log_event writes data to a file via a queue and a thread."""
    logger_instance, log_file = setup_trade_logger

    event_data1 = {
        "symbol": "BTCUSDT",
        "strategy": "TestStrat",
        "direction": "LONG",
        "pnl": 123.456789,
        "entry_price": 50000.12345678,
        "commission": Decimal("0.5"),
        "details": {"info": "some details", "value": 10},
    }
    event_data2 = {
        "symbol": "ETHUSDT",
        "strategy": "OtherStrat",
        "order_id": 98765,
        "client_order_id": "test-client-id",
        "details": None,  # Checking None
    }

    logger_instance.log_event("POSITION_CLOSED", event_data1)
    logger_instance.log_event("ORDER_PLACED", event_data2)
    logger_instance.log_event("SIGNAL_REJECTED")  # Event without data

    # Give the thread time to write
    logger_instance.stop()  # stop() will wait for the queue to clear

    # Reading the result
    log_rows = read_csv_log(log_file)
    assert len(log_rows) == 3

    # Checking the first line
    row1 = log_rows[0]
    assert row1["event_type"] == "POSITION_CLOSED"
    assert row1["symbol"] == "BTCUSDT"
    assert row1["strategy"] == "TestStrat"
    assert row1["direction"] == "LONG"
    assert row1["pnl"] == f"{123.456789:.8f}"
    assert row1["entry_price"] == f"{50000.12345678:.8f}"
    assert row1["commission"] == f"{Decimal('0.5'):.8f}"
    # Check JSON in details
    expected_details1 = json.dumps(
        {"info": "some details", "value": 10}, separators=(",", ":")
    )
    assert row1["details"] == expected_details1
    # Check timestamp (just presence)
    assert (
        datetime.fromisoformat(row1["timestamp"].replace("Z", "+00:00")).tzinfo
        == timezone.utc
    )

    # Checking the second line
    row2 = log_rows[1]
    assert row2["event_type"] == "ORDER_PLACED"
    assert row2["symbol"] == "ETHUSDT"
    assert row2["order_id"] == "98765"
    assert row2["client_order_id"] == "test-client-id"
    assert row2["details"] == ""  # None should become an empty string
    assert row2["pnl"] == ""  # Not passed - empty string

    # Checking the third line
    row3 = log_rows[2]
    assert row3["event_type"] == "SIGNAL_REJECTED"
    assert row3["symbol"] == ""
    assert row3["strategy"] == ""
    assert row3["details"] == ""


def test_log_event_queue_full(tmp_path, monkeypatch):
    """Test: Handling queue overflow."""
    log_file = tmp_path / "queue_full.csv"
    monkeypatch.setattr(config, "LOG_FILE_TRADES", str(log_file))

    q_size = 2
    logger_instance = TradeLogger(max_queue_size=q_size)
    # Do not start the thread

    # Filling the queue
    for i in range(q_size):
        logger_instance.log_event(f"EVENT_{i}")
    assert logger_instance.log_queue.full()

    # Mocking logger.warning
    with patch("bot_module.trade_logger.logger.warning") as mock_warning:
        logger_instance.log_event("EVENT_OVERFLOW")

    mock_warning.assert_called_once()

    call_message = mock_warning.call_args[0][0]
    assert "Trade log queue is full" in call_message
    assert "EVENT_OVERFLOW" in call_message

    assert logger_instance.log_queue.qsize() == q_size
    logger_instance.stop()  # Just in case
    log_rows = read_csv_log(log_file)
    assert len(log_rows) == 0


def test_logger_stop_processes_queue(tmp_path, monkeypatch):
    """Test: stop() waits for the queue to be processed."""
    log_file = tmp_path / "stop_test.csv"
    monkeypatch.setattr(config, "LOG_FILE_TRADES", str(log_file))
    q_size = 5
    logger_instance = TradeLogger(max_queue_size=q_size)

    for i in range(q_size):
        # Pass 'value' as an unknown field, it will go into details
        logger_instance.log_event(f"EVENT_STOP_{i}", {"unknown_value": i})

    assert logger_instance.log_queue.qsize() == q_size

    logger_instance.start()
    time.sleep(0.1)
    logger_instance.stop()
    assert logger_instance.log_queue.empty()

    log_rows = read_csv_log(log_file)
    assert len(log_rows) == q_size
    for i in range(q_size):
        assert log_rows[i]["event_type"] == f"EVENT_STOP_{i}"
        assert log_rows[i]["details"], f"Details field is empty for row {i}"
        assert json.loads(log_rows[i]["details"]) == {"unknown_value": i}


def test_log_event_handles_unknown_fields(setup_trade_logger):  # Removed caplog
    """Test: Ignoring unknown fields in data."""
    logger_instance, log_file = setup_trade_logger

    event_data = {
        "symbol": "XYZUSDT",
        # "event_type": "KNOWN_EVENT", # Removed, should not affect
        "unknown_field": "some value",  # Will go into details
        "another_unknown": 123,  # Will go into details
        "pnl": 10.0,  # Will go into the pnl field
    }

    # Mock logger.warning just in case, but it should not be called
    with patch("bot_module.trade_logger.logger.warning") as mock_warning:
        logger_instance.log_event("MY_EVENT", event_data)

    logger_instance.stop()
    log_rows = read_csv_log(log_file)
    assert len(log_rows) == 1
    row = log_rows[0]
    assert row["event_type"] == "MY_EVENT"
    assert row["symbol"] == "XYZUSDT"
    assert row["pnl"] == f"{10.0:.8f}"
    assert row["details"], "Details field is empty"
    expected_details = {"unknown_field": "some value", "another_unknown": 123}
    assert json.loads(row["details"]) == expected_details
    mock_warning.assert_not_called()  # Ensure there were no warnings


def test_event_log_can_be_disabled(tmp_path, monkeypatch):
    """LOG_TRADES_ENABLED=false: no file is created and nothing is queued."""
    log_file = tmp_path / "disabled_events.csv"
    diary_file = tmp_path / "disabled_diary.csv"
    monkeypatch.setattr(config, "LOG_FILE_TRADES", str(log_file))
    monkeypatch.setattr(config, "LOG_FILE_TRADER_DIARY", str(diary_file))
    monkeypatch.setattr(config, "LOG_TRADES_ENABLED", False)

    logger_instance = TradeLogger(max_queue_size=5)
    assert logger_instance._event_log_enabled is False
    assert not log_file.exists()
    # The diary is independent and still enabled.
    assert diary_file.exists()

    logger_instance.log_event("SHOULD_NOT_BE_QUEUED", {"symbol": "BTCUSDT"})
    assert logger_instance.log_queue.empty()
    logger_instance.stop()


def test_trader_diary_can_be_disabled(tmp_path, monkeypatch):
    """LOG_TRADER_DIARY_ENABLED=false: no file is created, no entry queued."""
    log_file = tmp_path / "events.csv"
    diary_file = tmp_path / "disabled_diary.csv"
    monkeypatch.setattr(config, "LOG_FILE_TRADES", str(log_file))
    monkeypatch.setattr(config, "LOG_FILE_TRADER_DIARY", str(diary_file))
    monkeypatch.setattr(config, "LOG_TRADER_DIARY_ENABLED", False)

    logger_instance = TradeLogger(max_queue_size=5)
    assert logger_instance._trader_diary_enabled is False
    assert not diary_file.exists()
    assert log_file.exists()

    logger_instance.log_closed_trade_to_diary({"symbol": "BTCUSDT"})
    assert logger_instance.log_queue.empty()
    logger_instance.stop()


def test_trader_diary_writes_when_enabled(tmp_path, monkeypatch):
    """Enabled diary still writes a row through the writer thread."""
    log_file = tmp_path / "events.csv"
    diary_file = tmp_path / "diary.csv"
    monkeypatch.setattr(config, "LOG_FILE_TRADES", str(log_file))
    monkeypatch.setattr(config, "LOG_FILE_TRADER_DIARY", str(diary_file))

    logger_instance = TradeLogger(max_queue_size=5)
    logger_instance.start()
    logger_instance.log_closed_trade_to_diary(
        {
            "symbol": "ETHUSDT",
            "strategy_name": "TestStrat",
            "direction": "LONG",
            "entry_price": 2500.0,
            "exit_price": 2550.0,
            "quantity": 0.01,
            "pnl_usd": 0.5,
            "exit_reason": "TAKE_PROFIT",
        }
    )
    logger_instance.stop()

    rows = read_csv_log(diary_file)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "ETHUSDT"
    assert rows[0]["strategy_name"] == "TestStrat"
    assert rows[0]["exit_reason"] == "TAKE_PROFIT"
