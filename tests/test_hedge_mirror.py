# tests/test_hedge_mirror.py
"""Unit tests for the hedge (mirror) signal inversion (bot_module/hedge_mirror)."""

import pytest

from bot_module.datatypes import (
    OrderMode,
    PartialTarget,
    SignalDirection,
    StrategySignal,
)
from bot_module.hedge_mirror import (
    HEDGE_DEFAULT_EXIT_POLICY,
    get_hedge_config,
    hedge_cooldown_key,
    hedge_entry_key,
    hedge_mark_key,
    invert_signal,
    is_mirror_leg,
    maybe_apply_hedge_sizing,
    maybe_mirror_hedge_signal,
    mirror_price,
    pair_pnl_pct,
    quantize_to_shared_step,
    sibling_leg,
    spread_trigger_fires,
    tag_hedge_details,
)


def _long_signal(**overrides):
    base = {
        "strategy_name": "TestStrategy",
        "symbol": "BTCUSDT",
        "direction": SignalDirection.LONG,
        "stop_loss": 990.0,
        "take_profit": 1030.0,
        "mode": OrderMode.MARKET,
        "trigger_price": 1000.0,
    }
    base.update(overrides)
    return StrategySignal(**base)


def _hedge_b_cfg(**overrides):
    cfg = {
        "enabled": True,
        "group_id": "abc123",
        "leg": "B",
        "invert": True,
        "exit_policy": HEDGE_DEFAULT_EXIT_POLICY,
        "sibling_api_key_id": 7,
    }
    cfg.update(overrides)
    return cfg


def test_mirror_price_symmetry():
    assert mirror_price(1000.0, 990.0) == pytest.approx(1010.0)
    assert mirror_price(1000.0, 1030.0) == pytest.approx(970.0)


def test_invert_long_market_signal():
    mirrored = invert_signal(_long_signal(), _hedge_b_cfg())
    assert mirrored.direction == SignalDirection.SHORT
    # Distances preserved around trigger 1000: SL 990 -> 1010, TP 1030 -> 970
    assert mirrored.stop_loss == pytest.approx(1010.0)
    assert mirrored.take_profit == pytest.approx(970.0)
    assert mirrored.trigger_price == pytest.approx(1000.0)
    assert mirrored.details["hedge_mirrored"] is True
    assert mirrored.details["hedge_original_direction"] == "LONG"
    assert mirrored.details["hedge_group_id"] == "abc123"
    assert mirrored.details["hedge_leg"] == "B"


def test_invert_short_signal():
    sig = _long_signal(
        direction=SignalDirection.SHORT,
        stop_loss=1010.0,
        take_profit=970.0,
    )
    mirrored = invert_signal(sig, _hedge_b_cfg())
    assert mirrored.direction == SignalDirection.LONG
    assert mirrored.stop_loss == pytest.approx(990.0)
    assert mirrored.take_profit == pytest.approx(1030.0)


def test_invert_limit_signal_uses_entry_price():
    sig = _long_signal(
        mode=OrderMode.LIMIT_RETEST,
        entry_price=995.0,
        trigger_price=None,
        stop_loss=985.0,
        take_profit=1015.0,
    )
    mirrored = invert_signal(sig, _hedge_b_cfg())
    assert mirrored.direction == SignalDirection.SHORT
    assert mirrored.entry_price == pytest.approx(995.0)
    assert mirrored.stop_loss == pytest.approx(1005.0)
    assert mirrored.take_profit == pytest.approx(975.0)


def test_invert_partial_targets_mirrored():
    sig = _long_signal(
        partial_targets=[
            PartialTarget(price=1010.0, fraction=0.5),
            PartialTarget(price=1020.0, fraction=0.3),
        ],
        take_profit=1030.0,
    )
    mirrored = invert_signal(sig, _hedge_b_cfg())
    assert mirrored.partial_targets is not None
    assert [pt.fraction for pt in mirrored.partial_targets] == [0.5, 0.3]
    assert [pt.price for pt in mirrored.partial_targets] == pytest.approx(
        [990.0, 980.0]
    )


def test_invert_no_stop_loss_stays_none():
    sig = _long_signal(stop_loss=None)
    assert sig.no_stop_loss is True
    mirrored = invert_signal(sig, _hedge_b_cfg())
    assert mirrored.stop_loss is None
    assert mirrored.direction == SignalDirection.SHORT


def test_invert_missing_reference_raises():
    sig = _long_signal()
    sig.trigger_price = None  # corrupt after validation to simulate bad feed data
    with pytest.raises(ValueError):
        invert_signal(sig, _hedge_b_cfg())


def test_get_hedge_config_and_roles():
    assert get_hedge_config({}) is None
    assert get_hedge_config({"config_data": {}}) is None
    assert get_hedge_config({"config_data": {"hedge": {"enabled": False}}}) is None
    payload = {"config_data": {"hedge": _hedge_b_cfg()}}
    cfg = get_hedge_config(payload)
    assert cfg is not None and is_mirror_leg(cfg) is True
    leg_a = dict(_hedge_b_cfg(), leg="A", invert=False)
    assert is_mirror_leg(leg_a) is False


def test_maybe_mirror_tags_leg_a_without_inverting():
    sig = _long_signal()
    leg_a_cfg = _hedge_b_cfg(leg="A", invert=False)
    out = maybe_mirror_hedge_signal(sig, {"config_data": {"hedge": leg_a_cfg}})
    assert out is sig  # same object, not inverted
    assert out.direction == SignalDirection.LONG
    assert out.details["hedge_group_id"] == "abc123"
    assert out.details["hedge_leg"] == "A"


def test_maybe_mirror_inverts_leg_b():
    sig = _long_signal()
    out = maybe_mirror_hedge_signal(sig, {"config_data": {"hedge": _hedge_b_cfg()}})
    assert out is not sig
    assert out.direction == SignalDirection.SHORT


def test_maybe_mirror_fail_closed_on_bad_signal():
    sig = _long_signal()
    sig.trigger_price = None  # corrupt after validation to simulate bad feed data
    out = maybe_mirror_hedge_signal(sig, {"config_data": {"hedge": _hedge_b_cfg()}})
    assert out is None


def test_maybe_mirror_passthrough_without_hedge():
    sig = _long_signal()
    assert maybe_mirror_hedge_signal(sig, {}) is sig
    assert maybe_mirror_hedge_signal(sig, None) is sig


def test_tag_hedge_details():
    details = tag_hedge_details({}, _hedge_b_cfg())
    assert details["hedge_group_id"] == "abc123"
    assert details["hedge_leg"] == "B"
    assert details["hedge_exit_policy"] == HEDGE_DEFAULT_EXIT_POLICY
    assert details["hedge_sibling_api_key_id"] == 7


def _hedge_sized_cfg(notional=200.0, leg="A", **overrides):
    cfg = {
        "enabled": True,
        "group_id": "grp1",
        "leg": leg,
        "invert": leg == "B",
        "exit_policy": HEDGE_DEFAULT_EXIT_POLICY,
        "sibling_api_key_id": 9,
        "size_mode": "FIXED_NOTIONAL",
        "notional_usd": notional,
    }
    cfg.update(overrides)
    return {"config_data": {"hedge": cfg}}


def test_sizing_fixed_notional_long():
    # LONG 1000, SL 990 (dist 10) -> risk_usd = 200 * 10 / 1000 = 2.0
    sig = _long_signal(risk_pct=1.0)
    out = maybe_apply_hedge_sizing(sig, _hedge_sized_cfg())
    assert out is sig
    assert out.risk_usd == pytest.approx(2.0)
    assert out.risk_pct is None
    assert out.details["hedge_notional_usd"] == pytest.approx(200.0)
    assert out.details["hedge_size_mode"] == "FIXED_NOTIONAL"


def test_sizing_fixed_notional_short():
    # SHORT 1000, SL 1010 (dist 10) -> risk_usd = 2.0 as well (symmetric)
    sig = _long_signal(
        direction=SignalDirection.SHORT, stop_loss=1010.0, take_profit=970.0
    )
    out = maybe_apply_hedge_sizing(sig, _hedge_sized_cfg())
    assert out.risk_usd == pytest.approx(2.0)
    assert out.risk_pct is None


def test_sizing_no_sl_uses_notional_directly():
    sig = _long_signal(stop_loss=None)
    out = maybe_apply_hedge_sizing(sig, _hedge_sized_cfg(notional=150.0))
    assert out.risk_usd == pytest.approx(150.0)
    assert out.risk_pct is None


def test_sizing_independent_mode_leaves_signal():
    sig = _long_signal(risk_pct=1.0)
    payload = _hedge_sized_cfg()
    payload["config_data"]["hedge"]["size_mode"] = "INDEPENDENT"
    out = maybe_apply_hedge_sizing(sig, payload)
    assert out is sig
    assert out.risk_pct == 1.0
    assert out.risk_usd is None
    assert "hedge_notional_usd" not in out.details


def test_sizing_invalid_notional_falls_back():
    sig = _long_signal(risk_pct=1.0)
    out = maybe_apply_hedge_sizing(sig, _hedge_sized_cfg(notional=0.0))
    assert out is sig
    assert out.risk_pct == 1.0
    out2 = maybe_apply_hedge_sizing(sig, _hedge_sized_cfg(notional=None))
    assert out2 is sig


def test_sizing_without_hedge_passthrough():
    sig = _long_signal(risk_pct=1.0)
    assert maybe_apply_hedge_sizing(sig, {}) is sig


def test_sizing_applies_to_mirrored_leg():
    # Mirror first (leg B), then size: SHORT 1000 SL 1010 -> risk 2.0
    sig = _long_signal()
    payload = _hedge_sized_cfg(notional=200.0, leg="B")
    mirrored = maybe_mirror_hedge_signal(sig, payload)
    assert mirrored.direction == SignalDirection.SHORT
    sized = maybe_apply_hedge_sizing(mirrored, payload)
    assert sized.risk_usd == pytest.approx(200.0 * 10.0 / 1000.0)
    assert sized.details["hedge_leg"] == "B"


def test_sibling_leg():
    assert sibling_leg("A") == "B"
    assert sibling_leg("B") == "A"
    assert sibling_leg(None) is None
    assert sibling_leg("X") is None


def test_hedge_redis_keys():
    assert (
        hedge_mark_key("grp", "zecusdt", "A") == "depthsight:hedge:mark:grp:ZECUSDT:A"
    )
    assert (
        hedge_cooldown_key("grp", "ZECUSDT")
        == "depthsight:hedge:spread_cool:grp:ZECUSDT"
    )
    assert (
        hedge_entry_key("grp", "ZECUSDT", "B") == "depthsight:hedge:entry:grp:ZECUSDT:B"
    )


def test_quantize_to_shared_step_weex_case():
    # The live case: $20 notional at ~1.54 with a shared step of 10.
    assert quantize_to_shared_step(12.96, 10.0, 10.0) == pytest.approx(10.0)
    assert quantize_to_shared_step(12.96, 10.0, 0.001) == pytest.approx(10.0)
    assert quantize_to_shared_step(25.0, 10.0, 1.0) == pytest.approx(20.0)


def test_quantize_to_shared_step_rejects_unsafe():
    assert quantize_to_shared_step(5.0, 10.0, 10.0) is None  # rounds to zero
    assert quantize_to_shared_step(10.0, 0.0, 0.001) is None
    assert quantize_to_shared_step(10.0, -1.0, 0.001) is None
    assert quantize_to_shared_step(0.0, 10.0, 10.0) is None
    # Incommensurable steps: syncing would silently desync.
    assert quantize_to_shared_step(10.0, 0.5, 0.3) is None
    assert quantize_to_shared_step("bad", 10.0, 10.0) is None


def test_spread_trigger_fires_on_profit():
    # Pair +$1.0 on $200 combined = +0.5% >= 0.5% threshold.
    assert (
        spread_trigger_fires(
            my_pnl=0.6,
            sibling_pnl=0.4,
            combined_notional_usd=200.0,
            threshold_pct=0.5,
        )
        is True
    )


def test_spread_trigger_direction_agnostic():
    # Same economics expressed from the SHORT leg's perspective.
    assert (
        spread_trigger_fires(
            my_pnl=0.4,
            sibling_pnl=0.6,
            combined_notional_usd=200.0,
            threshold_pct=0.5,
        )
        is True
    )


def test_spread_trigger_ignores_loss_and_noise():
    # Below threshold: no fire.
    assert (
        spread_trigger_fires(
            my_pnl=0.3,
            sibling_pnl=0.2,
            combined_notional_usd=200.0,
            threshold_pct=0.5,
        )
        is False
    )
    # Adverse move must NEVER fire (one-sided by design).
    assert (
        spread_trigger_fires(
            my_pnl=-5.0,
            sibling_pnl=1.0,
            combined_notional_usd=200.0,
            threshold_pct=0.5,
        )
        is False
    )


def test_spread_trigger_rejects_garbage():
    assert (
        spread_trigger_fires(
            my_pnl=10.0,
            sibling_pnl=10.0,
            combined_notional_usd=0.0,
            threshold_pct=0.5,
        )
        is False
    )
    assert (
        spread_trigger_fires(
            my_pnl=10.0,
            sibling_pnl=10.0,
            combined_notional_usd=200.0,
            threshold_pct=0.0,
        )
        is False
    )
    assert (
        spread_trigger_fires(
            my_pnl="bad",
            sibling_pnl=1.0,
            combined_notional_usd=200.0,
            threshold_pct=0.5,
        )
        is False
    )


def test_pair_pnl_pct():
    assert pair_pnl_pct(
        my_pnl=1.0, sibling_pnl=1.0, combined_notional_usd=200.0
    ) == pytest.approx(1.0)
    assert pair_pnl_pct(my_pnl=1.0, sibling_pnl=1.0, combined_notional_usd=0.0) is None


def test_spread_policy_requires_fixed_notional():
    from pydantic import ValidationError

    from api.schemas import HedgeLaunchConfig

    ok = HedgeLaunchConfig(
        enabled=True,
        leg_b_api_key_id=2,
        exit_policy="SPREAD_PROFIT_EXIT",
        size_mode="FIXED_NOTIONAL",
        notional_usd=100.0,
        spread_exit_threshold_pct=0.5,
    )
    assert ok.exit_policy == "SPREAD_PROFIT_EXIT"

    with pytest.raises(ValidationError):
        HedgeLaunchConfig(
            enabled=True,
            leg_b_api_key_id=2,
            exit_policy="SPREAD_PROFIT_EXIT",
            size_mode="INDEPENDENT",
            notional_usd=100.0,
        )

    with pytest.raises(ValidationError):
        HedgeLaunchConfig(
            enabled=True,
            leg_b_api_key_id=2,
            exit_policy="SPREAD_PROFIT_EXIT",
            size_mode="FIXED_NOTIONAL",
            notional_usd=100.0,
            spread_exit_threshold_pct=0.0,
        )

    with pytest.raises(ValidationError):
        HedgeLaunchConfig(
            enabled=True,
            leg_b_api_key_id=2,
            exit_policy="SPREAD_PROFIT_EXIT",
            size_mode="FIXED_NOTIONAL",
            notional_usd=100.0,
            spread_exit_threshold_pct=25.0,
        )


def test_sync_step_schema_validation():
    from pydantic import ValidationError

    from api.schemas import HedgeLaunchConfig

    ok = HedgeLaunchConfig(
        enabled=True,
        leg_b_api_key_id=2,
        size_mode="SYNC_STEP",
        notional_usd=20.0,
        entry_sync_timeout_sec=120.0,
    )
    assert ok.size_mode == "SYNC_STEP"

    with pytest.raises(ValidationError):
        HedgeLaunchConfig(
            enabled=True,
            leg_b_api_key_id=2,
            size_mode="SYNC_STEP",
            entry_sync_timeout_sec=120.0,
        )  # notional required

    with pytest.raises(ValidationError):
        HedgeLaunchConfig(
            enabled=True,
            leg_b_api_key_id=2,
            size_mode="SYNC_STEP",
            notional_usd=20.0,
            entry_sync_timeout_sec=-5.0,
        )
