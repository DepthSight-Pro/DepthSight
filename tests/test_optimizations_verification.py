import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from bot_module.train_sklearn_batch import PurgedEmbargoCV
from bot_module.genetic_strategy_finder import split_data_is_oos
from bot_module.depthsight_backtester import (
    count_funding_periods,
    calculate_position_funding_pnl,
)


def test_purged_embargo_cv():
    # Generate mock timeline
    t0 = pd.date_range(start="2026-07-01 00:00:00", periods=100, freq="h").to_series()
    # Let each trade last 2 hours
    t1 = t0 + pd.Timedelta(hours=2)

    X = pd.DataFrame(np.random.randn(100, 5))
    y = pd.Series(np.random.choice([0, 1], size=100))

    cv = PurgedEmbargoCV(t0, t1, n_splits=3, embargo_pct=0.01)
    splits = list(cv.split(X, y))

    assert len(splits) == 3
    for train_idx, test_idx in splits:
        assert len(train_idx) > 0
        assert len(test_idx) > 0

        test_t0_min = t0.iloc[test_idx].min()
        test_t1_max = t1.iloc[test_idx].max()

        # Test purging/embargo boundary
        total_duration = t0.max() - t0.min()
        embargo_duration = total_duration * 0.01
        boundary = test_t1_max + embargo_duration

        for idx in train_idx:
            assert idx not in test_idx

            t0_val = t0.iloc[idx]
            t1_val = t1.iloc[idx]
            is_overlap = (t0_val <= test_t1_max) and (t1_val >= test_t0_min)
            assert not is_overlap

            is_embargoed = (t0_val > test_t1_max) and (t0_val <= boundary)
            assert not is_embargoed


def test_split_data_is_oos():
    timestamps = pd.date_range(start="2026-07-01 00:00:00", periods=100, freq="min")
    df_1m = pd.DataFrame({"close": range(100)}, index=timestamps)
    df_1h = pd.DataFrame({"close": range(100)}, index=timestamps)

    dummy_mtf_data = {"BTC/USDT": {"1m": df_1m, "1h": df_1h}}

    is_data, oos_data = split_data_is_oos(dummy_mtf_data, oos_ratio=0.30)

    btc_is = is_data["BTC/USDT"]["1h"]
    btc_oos = oos_data["BTC/USDT"]["1h"]

    assert len(btc_is) == 70
    assert len(btc_oos) == 30
    assert btc_is.index[-1] < btc_oos.index[0]


def test_count_funding_periods():
    # From 07:00 to 09:00, crosses 08:00 (1 period)
    dt1 = datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc)
    dt2 = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
    assert count_funding_periods(dt1, dt2) == 1

    # From 07:00 to 17:00 UTC, crosses 08:00 and 16:00 (2 periods)
    dt3 = datetime(2026, 7, 1, 17, 0, tzinfo=timezone.utc)
    assert count_funding_periods(dt1, dt3) == 2


def test_calculate_position_funding_pnl():
    execs = [
        {
            "timestamp": datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc),
            "price": 50000.0,
            "quantity": 1.0,
            "type": "ENTRY",
        },
        {
            "timestamp": datetime(2026, 7, 1, 17, 0, tzinfo=timezone.utc),
            "price": 51000.0,
            "quantity": 1.0,
            "type": "EXIT",
        },
    ]

    # Long position, pays funding rate of 0.0001 per period
    # position_value = 1.0 * 50000.0 = 50000.0
    # expected_funding_fee = -1.0 * 2 * 50000.0 * 0.0001 = -10.0
    funding_pnl = calculate_position_funding_pnl(
        execs, is_short=False, funding_rate=0.0001
    )
    assert pytest.approx(funding_pnl) == -10.0

    # Short position, receives funding rate of 0.0001 per period
    # expected_funding_fee = 1.0 * 2 * 50000.0 * 0.0001 = +10.0
    funding_pnl_short = calculate_position_funding_pnl(
        execs, is_short=True, funding_rate=0.0001
    )
    assert pytest.approx(funding_pnl_short) == 10.0
