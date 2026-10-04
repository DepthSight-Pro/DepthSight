import pytest
from datetime import datetime, timezone, timedelta
from bot_module.phantom_tracker import PhantomTracker


class TestPhantomTracker:
    @pytest.fixture
    def tracker(self, monkeypatch):
        # The tracker is a no-op unless explicitly enabled. Pin it on: these
        # tests verify tracking logic and must not depend on the ambient
        # PHANTOM_TRACKING_ENABLED value (currently off in this tree).
        from bot_module import config as bot_config

        monkeypatch.setattr(bot_config, "PHANTOM_TRACKING_ENABLED", True)
        return PhantomTracker()

    def test_create_phantom(self, tracker):
        """Test creating a phantom trade."""
        now = datetime.now(timezone.utc)
        tracker.create_phantom(
            real_trade_id="test_trade_1",
            user_id=1,
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=50000.0,
            entry_time=now - timedelta(hours=1),
            initial_stop_loss=49000.0,
            initial_take_profit=52000.0,
            be_trigger_time=now,
            be_exit_price=50500.0,
            real_pnl_pct=0.1,
            strategy_config_id="strat_1",
        )

        phantoms = tracker.get_active_phantoms("BTCUSDT")
        assert len(phantoms) == 1
        phantom = phantoms[0]
        assert phantom.real_trade_id == "test_trade_1"
        assert phantom.symbol == "BTCUSDT"
        assert phantom.status.value == "TRACKING"
        assert phantom.mfe_after_be == 0.0
        assert phantom.mae_after_be == 0.0

    def test_update_tracking_tp_hit(self, tracker):
        """Test phantom trade resolving to TP HIT."""
        now = datetime.now(timezone.utc)
        tracker.create_phantom(
            real_trade_id="tp_hit_trade",
            user_id=1,
            symbol="ETHUSDT",
            direction="LONG",
            entry_price=2000.0,
            entry_time=now - timedelta(hours=1),
            initial_stop_loss=1900.0,
            initial_take_profit=2100.0,
            be_trigger_time=now,
            be_exit_price=2010.0,
            real_pnl_pct=0.5,
            strategy_config_id="strat_1",
        )

        # Update with price hitting TP
        resolved = tracker.update(
            symbol="ETHUSDT",
            current_price=2105.0,  # Above TP
            current_time=now + timedelta(minutes=5),
            high_price=2110.0,
            low_price=2005.0,
        )

        assert len(resolved) == 1
        assert len(tracker.get_active_phantoms("ETHUSDT")) == 0

        res = resolved[0]
        assert res.status.value == "TP_HIT"
        assert res.phantom_exit_price == 2100.0
        # PnL should be calculated from entry to TP
        # (2100 - 2000) / 2000 * 100 = 5.0%
        assert res.phantom_pnl_pct == pytest.approx(5.0)

    def test_update_tracking_sl_hit(self, tracker):
        """Test phantom trade resolving to SL HIT."""
        now = datetime.now(timezone.utc)
        tracker.create_phantom(
            real_trade_id="sl_hit_trade",
            user_id=1,
            symbol="SOLUSDT",
            direction="LONG",
            entry_price=100.0,
            entry_time=now - timedelta(hours=1),
            initial_stop_loss=90.0,
            initial_take_profit=120.0,
            be_trigger_time=now,
            be_exit_price=102.0,
            real_pnl_pct=2.0,
            strategy_config_id="strat_1",
        )

        # Update with price hitting SL
        resolved = tracker.update(
            symbol="SOLUSDT",
            current_price=85.0,  # Below SL
            current_time=now + timedelta(minutes=10),
            high_price=103.0,
            low_price=88.0,
        )

        assert len(resolved) == 1
        res = resolved[0]
        assert res.status.value == "SL_HIT"
        assert res.phantom_exit_price == 90.0
        # PnL: (90 - 100) / 100 * 100 = -10.0%
        assert res.phantom_pnl_pct == pytest.approx(-10.0)

    def test_update_tracking_timeout(self, tracker):
        """Test phantom trade timing out."""
        now = datetime.now(timezone.utc)
        tracker.create_phantom(
            real_trade_id="timeout_trade",
            user_id=1,
            symbol="ADAUSDT",
            direction="SHORT",
            entry_price=0.5,
            entry_time=now - timedelta(hours=5),
            initial_stop_loss=0.55,
            initial_take_profit=0.4,
            be_trigger_time=now
            - timedelta(minutes=61),  # Default timeout is 60 mins? Check config default
            be_exit_price=0.49,
            real_pnl_pct=2.0,
            strategy_config_id="strat_1",
        )

        # Force timeout by setting timeout_candles small or relying on time
        phantom = tracker.get_active_phantoms("ADAUSDT")[0]
        phantom.timeout_candles = 5  # Set small timeout for test

        # 1st update
        tracker.update("ADAUSDT", 0.49, now, 0.495, 0.485)
        assert len(tracker.get_active_phantoms("ADAUSDT")) == 1

        # 5 more updates
        all_resolved = []
        for i in range(5):
            res = tracker.update(
                "ADAUSDT", 0.49, now + timedelta(minutes=i), 0.495, 0.485
            )
            all_resolved.extend(res)

        assert len(all_resolved) == 1
        res = all_resolved[0]
        assert res.status.value == "TIMEOUT"
        assert res.phantom_exit_price == 0.49  # Last close price

    def test_mfe_mae_tracking_long(self, tracker):
        """Test MFE and MAE updates for LONG position."""
        now = datetime.now(timezone.utc)
        exit_price_be = 100.0
        tracker.create_phantom(
            real_trade_id="mfe_mae_long",
            user_id=1,
            symbol="LINKUSDT",
            direction="LONG",
            entry_price=100.0,
            entry_time=now,
            initial_stop_loss=90.0,
            initial_take_profit=120.0,
            be_trigger_time=now,
            be_exit_price=exit_price_be,
            real_pnl_pct=0.0,
            strategy_config_id="strat_1",
        )

        # 1. Price goes up (MFE increases)
        tracker.update("LINKUSDT", 105.0, now, 106.0, 100.0)
        phantom = tracker.get_active_phantoms("LINKUSDT")[0]
        # MFE: (106 - 100) / 100 * 100 = 6%
        assert phantom.mfe_after_be == pytest.approx(6.0)
        assert phantom.mae_after_be == 0.0  # Low was 100 (exit price), so no adverse

        # 2. Price goes down (MAE increases)
        tracker.update("LINKUSDT", 95.0, now, 105.0, 94.0)
        phantom = tracker.get_active_phantoms("LINKUSDT")[0]
        # MFE should stay same (max high was 106 in prev candle)
        assert phantom.mfe_after_be == pytest.approx(6.0)

        # MAE: (100 - 94) / 100 * 100 = 6.0% (positive for drawdown usually?)
        # Let's check logic: mae_after_be = ((phantom.be_exit_price - low_price) / phantom.be_exit_price) * 100
        # (100 - 94) / 100 * 100 = 6.0
        # So it's positive.
        assert phantom.mae_after_be == pytest.approx(6.0)
