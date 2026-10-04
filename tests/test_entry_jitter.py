"""Regression: live entries must be staggerable to survive candle-close bursts.

When hundreds of bots evaluate the same candle, unstaggered entry+TP+SL
placements trip per-IP rate limits (Bitget 100/s, Bybit 600/5s + 10-min ban).
ENTRY_JITTER_MAX_SECONDS spreads them; paper simulation is never delayed.
"""

import pytest

from bot_module import config as bot_config
from bot_module.controller import TradingController


def _ctrl():
    return TradingController.__new__(TradingController)


def test_paper_never_delayed(monkeypatch):
    monkeypatch.setattr(bot_config, "ENTRY_JITTER_MAX_SECONDS", 30.0)
    assert _ctrl()._entry_jitter_seconds("paper") == 0.0


def test_zero_cap_means_no_delay(monkeypatch):
    monkeypatch.setattr(bot_config, "ENTRY_JITTER_MAX_SECONDS", 0)
    for _ in range(20):
        assert _ctrl()._entry_jitter_seconds("live") == 0.0


def test_invalid_cap_means_no_delay(monkeypatch):
    monkeypatch.setattr(bot_config, "ENTRY_JITTER_MAX_SECONDS", "garbage")
    assert _ctrl()._entry_jitter_seconds("live") == 0.0
    monkeypatch.setattr(bot_config, "ENTRY_JITTER_MAX_SECONDS", -5)
    assert _ctrl()._entry_jitter_seconds("live") == 0.0


def test_live_delay_within_cap(monkeypatch):
    monkeypatch.setattr(bot_config, "ENTRY_JITTER_MAX_SECONDS", 5.0)
    seen = {_ctrl()._entry_jitter_seconds("live") for _ in range(50)}
    assert all(0 <= d <= 5.0 for d in seen)
    assert len(seen) > 1, "delays must actually vary"


@pytest.mark.asyncio
async def test_stagger_sleeps_on_live_entry(monkeypatch):
    """_maybe_stagger_entry honors the cap through the real sleep call."""
    import asyncio as aio

    calls = []

    async def fake_sleep(delay):
        calls.append(delay)

    monkeypatch.setattr(bot_config, "ENTRY_JITTER_MAX_SECONDS", 5.0)
    monkeypatch.setattr(aio, "sleep", fake_sleep)

    delay = await _ctrl()._maybe_stagger_entry("live", log_prefix="[t]")
    assert len(calls) == 1
    assert calls[0] == delay
    assert 0 <= delay <= 5.0


@pytest.mark.asyncio
async def test_stagger_skips_sleep_when_disabled(monkeypatch):
    import asyncio as aio

    async def fail_sleep(delay):
        raise AssertionError("sleep must not be called")

    monkeypatch.setattr(aio, "sleep", fail_sleep)

    monkeypatch.setattr(bot_config, "ENTRY_JITTER_MAX_SECONDS", 0)
    assert await _ctrl()._maybe_stagger_entry("live") == 0.0
    monkeypatch.setattr(bot_config, "ENTRY_JITTER_MAX_SECONDS", 5.0)
    assert await _ctrl()._maybe_stagger_entry("paper") == 0.0
