# tests/test_api_diagnostics.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import pandas as pd
from datetime import datetime, timezone
import json
from api import models
from fastapi.testclient import TestClient
from api.depthsight_api import app
from api.auth import get_current_user
from api.database import get_db

# Create a TestClient
client = TestClient(app)


@pytest.fixture
def mock_data_loader():
    with patch("api.routes.diagnostics.data_loader") as mock:
        yield mock


@pytest.fixture
def mock_get_current_user():
    # Override the dependency to bypass auth
    user = models.User(
        id="test-user-id",
        username="tester",
        plan="pro",
        hashed_password="hash",
        email="test@example.com",
        level=1,
        xp=0,
    )
    app.dependency_overrides[get_current_user] = lambda: user

    # Mock DB to avoid errors in grant_achievement
    mock_db = AsyncMock()
    # Handle check for existing achievement
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = mock_result

    # Handle db.get(models.User, ...) in grant_achievement
    # We need to return the user object (or a copy)
    async def mock_get(model, id):
        if model == models.User:
            return user
        if model == models.Achievement:
            return models.Achievement(
                id="clairvoyant", name="Clairvoyant", xp_reward=100
            )
        return None

    mock_db.get = AsyncMock(side_effect=mock_get)

    app.dependency_overrides[get_db] = lambda: mock_db

    yield
    app.dependency_overrides = {}


def test_preview_foundation_round_levels(mock_data_loader, mock_get_current_user):
    """
    Test that Round Levels are generated and returned in the response.
    """
    # 1. Mock Kline Data (need enough data for graph)
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq="1h")
    df = pd.DataFrame(
        {
            "open": [50000 + i for i in range(100)],
            "high": [50100 + i for i in range(100)],
            "low": [49900 + i for i in range(100)],
            "close": [50050 + i for i in range(100)],
            "volume": [1000] * 100,
        },
        index=dates,
    )

    mock_data_loader.download_klines = AsyncMock(return_value=df)

    # 2. Mock Open Interest Data (empty for this test to isolate round levels)
    mock_data_loader.download_open_interest = AsyncMock(return_value=pd.DataFrame())

    # 3. Request parameters
    end_date_str = datetime.now(timezone.utc).isoformat()
    params = {
        "symbol": "BTCUSDT",
        "end_date": end_date_str,
        "timeframe": "1h",
        "foundations": "round_level",
        "params": "{}",
    }

    # 4. Make Request
    response = client.get("/api/v1/diagnostics/preview-foundation", params=params)

    # 5. Verify
    assert response.status_code == 200
    data = response.json()["data"]

    # Check if we have levels
    levels = data["visualizations"]["levels"]
    assert len(levels) > 0

    # Check if we have round_level type
    round_levels = [lvl for lvl in levels if lvl["type"] == "round_level"]
    assert len(round_levels) > 0
    # Expected round level near 50000 -> 50000 should be there
    assert any(lvl["price"] == 50000.0 for lvl in round_levels)


def test_preview_foundation_open_interest(mock_data_loader, mock_get_current_user):
    """
    Test that Open Interest is returned in subcharts.
    """
    # 1. Mock Kline Data
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq="1h")
    df_kline = pd.DataFrame(
        {
            "open": [100] * 50,
            "high": [110] * 50,
            "low": [90] * 50,
            "close": [100] * 50,
            "volume": [1000] * 50,
        },
        index=dates,
    )
    mock_data_loader.download_klines = AsyncMock(return_value=df_kline)

    # 2. Mock Open Interest Data
    df_oi = pd.DataFrame(
        {"open_interest": [500 + i * 10 for i in range(50)]}, index=dates
    )
    mock_data_loader.download_open_interest = AsyncMock(return_value=df_oi)

    # 3. Request
    params = {
        "symbol": "BTCUSDT",
        "end_date": datetime.now(timezone.utc).isoformat(),
        "timeframe": "1h",
        "foundations": "open_interest",
        "params": "{}",
    }

    response = client.get("/api/v1/diagnostics/preview-foundation", params=params)
    assert response.status_code == 200
    data = response.json()["data"]

    # 4. Verify subcharts
    subcharts = data["visualizations"]["subcharts"]
    assert "open_interest" in subcharts
    assert len(subcharts["open_interest"]) > 0
    # Check LAST value to ensure data alignment (start_dt calc might cut off earlier values)
    assert subcharts["open_interest"][-1]["value"] == 990.0


def test_preview_foundation_tape_acceleration_key_fix(
    mock_data_loader, mock_get_current_user
):
    """
    Test that 'tape_acceleration' key from frontend triggers the logic.
    """
    # 1. Mock Data (Need 24h of data to avoid 404 in preview_foundation logic)
    # Using 1440 minutes to cover full day
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=1441, freq="1min")

    # Normal volume then a spike at the end
    volumes = [100] * 1439 + [1000] * 2  # Spike > 2x average

    df = pd.DataFrame(
        {
            "open": [100] * 1441,
            "high": [100] * 1441,
            "low": [100] * 1441,
            "close": [100] * 1441,
            "volume": volumes,
        },
        index=dates,
    )

    mock_data_loader.download_klines = AsyncMock(return_value=df)

    # 2. Request with 'tape_acceleration' in foundations list AND params
    # Ensure end_date matches the end of our dataframe
    end_date_str = dates[-1].isoformat()

    params = {
        "symbol": "BTCUSDT",
        "end_date": end_date_str,
        "timeframe": "1m",
        "foundations": "tape_acceleration",
        "params": json.dumps({"tape_acceleration": {"multiplier": 2.0}}),
    }

    response = client.get("/api/v1/diagnostics/preview-foundation", params=params)
    assert response.status_code == 200
    data = response.json()["data"]

    # 3. Verify markers
    markers = data["visualizations"]["markers"]

    # Debug print
    print(f"DEBUG: Markers returned: {markers}")

    # Use robust check filtering out malformed markers if any
    tape_markers = [
        m
        for m in markers
        if isinstance(m, dict) and m.get("type") == "tape_acceleration"
    ]
    assert len(tape_markers) > 0, f"No tape markers found in {markers}"
    assert tape_markers[0]["text"] == "T"


def test_preview_foundation_correlation(mock_data_loader, mock_get_current_user):
    """
    Test that Correlation is calculated and returned.
    """
    # 1. Mock Data
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq="1h")

    # Target Symbol (ETH) - Moves UP
    df_eth = pd.DataFrame(
        {
            "close": [1000 + i for i in range(100)],
            "open": [1000] * 100,
            "high": [1000] * 100,
            "low": [1000] * 100,
            "volume": [100] * 100,
        },
        index=dates,
    )

    # Benchmark Symbol (BTC) - Moves UP (High Correlation)
    df_btc = pd.DataFrame(
        {
            "close": [50000 + i * 50 for i in range(100)],
            "open": [50000] * 100,
            "high": [50000] * 100,
            "low": [50000] * 100,
            "volume": [100] * 100,
        },
        index=dates,
    )

    # Side effect for download_klines to return different DFs based on symbol
    async def side_effect(symbol, *args, **kwargs):
        if symbol == "ETHUSDT":
            return df_eth
        if symbol == "BTCUSDT":
            return df_btc
        return df_eth  # Default

    mock_data_loader.download_klines = AsyncMock(side_effect=side_effect)

    # 2. Request
    params = {
        "symbol": "ETHUSDT",
        "end_date": datetime.now(timezone.utc).isoformat(),
        "timeframe": "1h",
        "foundations": "correlation",
        "params": json.dumps({"correlation": {"lookback": 10}}),
    }

    response = client.get("/api/v1/diagnostics/preview-foundation", params=params)
    assert response.status_code == 200
    data = response.json()["data"]

    # 3. Verify
    subcharts = data["visualizations"]["subcharts"]
    assert "correlation" in subcharts
    # Correlation of two perfect linear up trends should be 1.0
    # There might be some NaN at the start due to rolling window
    valid_values = [d["value"] for d in subcharts["correlation"]]
    assert len(valid_values) > 0
    assert valid_values[-1] > 0.99


def test_preview_foundation_indicators(mock_data_loader, mock_get_current_user):
    """
    Test that indicators (ATR, ADX, NATR, RelVol, BB) are calculated and returned.
    """
    # 1. Mock Kline Data (need enough periods for indicators like ADX-14, BB-20)
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq="1h")
    df = pd.DataFrame(
        {
            "open": [100 + i for i in range(100)],
            "high": [110 + i for i in range(100)],
            "low": [90 + i for i in range(100)],
            "close": [100 + i for i in range(100)],
            "volume": [1000 + (i % 10) * 100 for i in range(100)],
        },
        index=dates,
    )

    mock_data_loader.download_klines = AsyncMock(return_value=df)
    mock_data_loader.download_open_interest = AsyncMock(return_value=pd.DataFrame())

    # 2. Request all indicators
    params = {
        "symbol": "BTCUSDT",
        "end_date": datetime.now(timezone.utc).isoformat(),
        "timeframe": "1h",
        "foundations": "volatility_filter,trend_filter,natr_filter,rel_vol_filter,bollinger_bands_condition,ma_crossover,macd_condition",
        "params": json.dumps(
            {
                "volatility_filter": {"indicator": "ATR"},
                "trend_filter": {"threshold": 25.0},
                "natr_filter": {"natr_threshold": 1.0},
                "rel_vol_filter": {"rel_vol_threshold": 1.5},
                "bollinger_bands_condition": {"source": "close"},
                "ma_crossover": {"fast_period": 9, "slow_period": 21, "ma_type": "EMA"},
                "macd_condition": {"fast": 12, "slow": 26, "signal": 9},
            }
        ),
    }

    response = client.get("/api/v1/diagnostics/preview-foundation", params=params)
    assert response.status_code == 200
    data = response.json()["data"]
    subcharts = data["visualizations"]["subcharts"]

    # 3. Verify Subcharts
    assert "ATR" in subcharts
    assert "ADX" in subcharts
    assert "NATR" in subcharts
    assert "RelVol" in subcharts

    # Verify Bollinger Bands
    assert "BB_Upper" in subcharts
    assert "BB_Middle" in subcharts
    assert "BB_Lower" in subcharts

    # Verify MA Crossover
    # Dynamic keys depend on periods, we expect MA_Fast_9 and MA_Slow_21
    assert any(k.startswith("MA_Fast_") for k in subcharts.keys())
    assert any(k.startswith("MA_Slow_") for k in subcharts.keys())

    # Verify MACD
    assert "MACD_Line" in subcharts
    assert "MACD_Signal" in subcharts
    assert "MACD_Hist" in subcharts

    assert len(subcharts["ATR"]) > 0
    assert len(subcharts["BB_Upper"]) > 0
