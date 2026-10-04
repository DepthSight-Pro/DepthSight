"""Regression: periodic reconcile must not waste exchange calls (B4).

Controllers that run no LIVE strategy have nothing to reconcile, but the
periodic loop used to run the multi-REST-call reconcile body every 60s for
every controller - including paper-only ones. The gate below skips it.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from bot_module.controller import TradingController


def _bare_controller():
    ctrl = TradingController.__new__(TradingController)
    ctrl.running_strategy_instances = {}
    ctrl.instances_lock = asyncio.Lock()
    return ctrl


@pytest.mark.asyncio
async def test_no_instances_means_no_live():
    ctrl = _bare_controller()
    assert await ctrl._has_live_strategy_instances() is False


@pytest.mark.asyncio
async def test_paper_only_means_no_live():
    ctrl = _bare_controller()
    ctrl.running_strategy_instances = {
        "cfg1:aaa": (MagicMock(), {"mode": "paper"}),
        "cfg2:bbb": (MagicMock(), {"mode": "PAPER"}),
    }
    assert await ctrl._has_live_strategy_instances() is False


@pytest.mark.asyncio
async def test_any_live_instance_counts():
    ctrl = _bare_controller()
    ctrl.running_strategy_instances = {
        "cfg1:aaa": (MagicMock(), {"mode": "paper"}),
        "cfg2:bbb": (MagicMock(), {"mode": "live"}),
    }
    assert await ctrl._has_live_strategy_instances() is True


@pytest.mark.asyncio
async def test_malformed_payload_is_ignored_not_fatal():
    ctrl = _bare_controller()
    ctrl.running_strategy_instances = {
        "cfg1:aaa": (MagicMock(), None),
        "cfg2:bbb": (MagicMock(), "not-a-dict"),
    }
    assert await ctrl._has_live_strategy_instances() is False
