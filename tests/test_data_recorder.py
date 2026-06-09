# tests/test_data_recorder.py
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import MagicMock, AsyncMock, patch

import msgpack
import pytest
import zstandard

from bot_module.data_recorder import L2StreamRecorder

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

pytestmark = pytest.mark.asyncio


@pytest.fixture
def temp_storage(tmp_path):
    return tmp_path


@pytest.fixture
def recorder(temp_storage):
    config = {
        "storage_path": str(temp_storage),
        "exchanges": {
            "mock_exchange": {"enabled": True, "markets": {"spot": ["BTC/USDT"]}}
        },
    }
    recorder_instance = L2StreamRecorder(config)
    # Use a simple MagicMock. We will configure it in the test itself.
    mock_exchange_instance = MagicMock()
    mock_exchange_instance.id = "mock_exchange"
    recorder_instance.exchanges["mock_exchange"] = mock_exchange_instance
    return recorder_instance


# --- Tests that already pass remain unchanged ---
async def test_initialization(temp_storage):
    config = {"storage_path": str(temp_storage)}
    recorder_instance = L2StreamRecorder(config)
    assert recorder_instance.storage_path == temp_storage


async def test_get_file_path_structure(recorder):
    now = datetime.now(timezone.utc)
    path = recorder._get_file_path("mock_exchange", "BTC/USDT")
    assert isinstance(path, Path)
    expected_parent = (
        recorder.storage_path / "mock_exchange" / "BTC_USDT" / now.strftime("%Y/%m/%d")
    )
    assert path.parent == expected_parent


@patch("aiofiles.open", new_callable=AsyncMock)
async def test_get_writer_creates_new_file(mock_aio_open, recorder):
    mock_writer = AsyncMock()
    mock_aio_open.return_value = mock_writer
    await recorder._get_writer("mock_exchange", "BTC/USDT")
    mock_aio_open.assert_called_once()


@patch("aiofiles.open", new_callable=AsyncMock)
async def test_file_rotation(mock_aio_open, recorder):
    mock_writer1, mock_writer2 = AsyncMock(), AsyncMock()
    mock_aio_open.side_effect = [mock_writer1, mock_writer2]
    with patch("bot_module.data_recorder.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2024, 6, 13, 10, 59, 0, tzinfo=timezone.utc)
        await recorder._get_writer("mock_exchange", "BTC/USDT")
    with patch("bot_module.data_recorder.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2024, 6, 13, 11, 1, 0, tzinfo=timezone.utc)
        await recorder._get_writer("mock_exchange", "BTC/USDT")
    mock_writer1.close.assert_called_once()
    assert mock_aio_open.call_count == 2


async def test_record_loop_writes_data(recorder, temp_storage):
    """
    Integration test: checking the full cycle - data retrieval, serialization, and writing.
    """
    mock_orderbook = {
        "timestamp": 1672531200000,
        "bids": [[9999.0, 1.5]],
        "asks": [[10001.0, 2.5]],
        "nonce": 12345,
    }

    # 1. Create an asynchronous generator that we want our mock to return
    async def mock_generator(*args, **kwargs):
        yield mock_orderbook

    # 2. **KEY CHANGE:** We replace the `watch_order_book` method with our
    #    asynchronous generator function DIRECTLY, without `AsyncMock`.
    recorder.exchanges["mock_exchange"].watch_order_book = mock_generator

    # 3. Start _record_loop in the background
    record_task = asyncio.create_task(
        recorder._record_loop("mock_exchange", "BTC/USDT", "spot")
    )

    # 4. Wait long enough for the loop to complete one iteration and write the data
    await asyncio.sleep(0.1)

    # 5. Stop the loop and the task
    recorder._running = False
    record_task.cancel()
    try:
        await record_task
    except asyncio.CancelledError:
        pass  # This is the expected behavior

    # 6. Get the file path BEFORE stopping the recorder, as stop() will clear it
    file_path_to_check = recorder._current_file_path.get("mock_exchange_BTC/USDT")

    # Correctly stop the recorder so it closes all files
    await recorder.stop()

    # 7. Check the result
    assert file_path_to_check is not None, (
        "File path was not set in recorder before stop()"
    )
    # After stop() _current_file_path will be empty, so file_path_to_check must be used for existence check
    assert file_path_to_check.exists(), f"File {file_path_to_check} was not created"

    decompressor = zstandard.ZstdDecompressor()
    # Use the saved path file_path_to_check
    with open(file_path_to_check, "rb") as f:
        compressed_content = f.read()
        assert len(compressed_content) > 0, "Written file is empty"

        decompressed_content = decompressor.decompress(compressed_content)
        unpacked_data = msgpack.unpackb(decompressed_content, raw=False)

    assert unpacked_data["ts"] == mock_orderbook["timestamp"]
    assert unpacked_data["bids"] == mock_orderbook["bids"]
    assert unpacked_data["nonce"] == mock_orderbook["nonce"]
