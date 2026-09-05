# tests/test_mining_quality_gates.py
"""
Quality gates for mining-eligible trades:

- Submission gate (_score_trade): minimum hold time — a MISSING duration now
  fails the gate too — and minimum absolute price movement
  (|exit-entry|/entry, %) against MiningConfig.min_price_movement_percent.
- Broker verifier re-checks the REAL holding time and REAL price movement
  derived from exchange order payloads (unspooable level 2); best-effort when
  the API response lacks price/timestamp fields.
"""

from types import SimpleNamespace
import uuid as _uuid

import pytest

from api import crud, models
from api.hub_router import _score_trade, score_trade_with_reason


def _cfg(**overrides) -> models.MiningConfig:
    params = dict(
        is_mining_enabled=True,
        eligible_exchanges=["weex"],
        min_trade_duration_sec=30,
        min_price_movement_percent=0.15,
        quality_gate_operator="AND",
    )
    params.update(overrides)
    return models.MiningConfig(**params)


def _report(duration=3600, entry=100.0, exit_=101.0):
    return SimpleNamespace(
        trade_mode="LIVE",
        trade_duration_sec=duration,
        entry_price=entry,
        exit_price=exit_,
    )


# ---------------------------------------------------------------------------
# Level 1 — submission gate
# ---------------------------------------------------------------------------


def test_score_zero_when_duration_missing():
    """A report without duration must NOT bypass the anti-wash gate."""
    assert _score_trade(_report(duration=None), _cfg()) == 0.0


def test_score_zero_when_duration_below_threshold():
    assert _score_trade(_report(duration=10), _cfg()) == 0.0


def test_score_positive_for_valid_trade():
    assert _score_trade(_report(), _cfg()) > 0


def test_score_zero_when_movement_below_threshold():
    # |100 -> 100.05| = 0.05% < 0.15%
    assert _score_trade(_report(entry=100.0, exit_=100.05), _cfg()) == 0.0


def test_score_positive_at_exact_threshold():
    # exactly 0.15% passes (>= threshold)
    assert _score_trade(_report(entry=100.0, exit_=100.15), _cfg()) > 0


def test_movement_gate_disabled_when_zero():
    cfg = _cfg(min_price_movement_percent=0.0)
    assert _score_trade(_report(entry=100.0, exit_=100.001), cfg) > 0


# ---------------------------------------------------------------------------
# Hub-local saves: IS_CENTRAL_HUB=true must evaluate the report immediately
# (previously rows stayed LOCAL_ONLY / score=0 / ineligible forever)
# ---------------------------------------------------------------------------


def _local_payload(bid: str, exit_=101.0, dur=300):
    return {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 100.0,
        "exit_price": exit_,
        "pnl_percent": 1.0,
        "trade_duration_sec": dur,
        "exit_reason": "take_profit",
        "trade_mode": "LIVE",
        "strategy_blocks": [{"type": "volume_filter", "params": {"m": 2}}],
        "market_context": {},
        "exchange_id": "weex",
        "market_type": "futures",
        "broker_trade_id": bid,
        "entry_broker_trade_ids": [],
        "close_broker_trade_ids": [],
        "trade_volume_usdt": 2000.0,
    }


async def _seed_cfg(db_session):
    db_session.add(
        models.MiningConfig(
            is_mining_enabled=True,
            eligible_exchanges=["weex"],
            min_trade_duration_sec=30,
            min_price_movement_percent=0.15,
            daily_emission_base=100.0,
            referral_mining_boost=0.10,
            rebate_rates={},
        )
    )
    await db_session.commit()


async def test_hub_local_save_good_trade_becomes_pending_eligible(
    db_session, monkeypatch
):
    monkeypatch.setenv("IS_CENTRAL_HUB", "true")
    await _seed_cfg(db_session)

    payload = _local_payload(f"loc-good-{_uuid.uuid4().hex[:8]}")
    row = await crud.save_hub_telemetry_report(db_session, payload, "local-node")

    assert row.verification_status == "PENDING"
    assert row.is_mining_eligible is True
    assert row.score > 0
    # default rebate rate 0.60: 2000 * 0.0005 * 0.60
    assert row.estimated_rebate_usdt == pytest.approx(0.60)


async def test_hub_local_save_flat_trade_stays_ineligible(db_session, monkeypatch):
    monkeypatch.setenv("IS_CENTRAL_HUB", "true")
    await _seed_cfg(db_session)

    payload = _local_payload(
        f"loc-flat-{_uuid.uuid4().hex[:8]}", exit_=100.01
    )  # movement 0.01% < 0.15%
    row = await crud.save_hub_telemetry_report(db_session, payload, "local-node")

    assert row.verification_status == "PENDING"
    assert row.is_mining_eligible is False
    assert row.score == 0.0
    assert row.estimated_rebate_usdt == 0.0
    # Human-readable rejection reason for the UI table.
    assert row.verification_error and "movement" in row.verification_error


def test_score_trade_reasons():
    cfg = models.MiningConfig(
        is_mining_enabled=True,
        eligible_exchanges=["weex"],
        min_trade_duration_sec=30,
        min_price_movement_percent=0.15,
    )

    def rep(**kw):
        base = dict(
            trade_mode="LIVE",
            trade_duration_sec=300,
            entry_price=100.0,
            exit_price=101.0,
        )
        base.update(kw)
        return SimpleNamespace(**base)

    # Missing duration
    score, reason = score_trade_with_reason(rep(trade_duration_sec=None), cfg)
    assert (score, reason) == (0.0, "missing trade duration (min 30s)")

    # Short hold
    score, reason = score_trade_with_reason(rep(trade_duration_sec=10), cfg)
    assert score == 0.0 and "10s < min 30s" in reason

    # Flat
    score, reason = score_trade_with_reason(rep(exit_price=100.05), cfg)
    assert score == 0.0 and "movement 0.050%" in reason

    # Not LIVE
    score, reason = score_trade_with_reason(rep(trade_mode="PAPER"), cfg)
    assert score == 0.0 and "not LIVE" in reason

    # Passing trade has no reason
    score, reason = score_trade_with_reason(rep(), cfg)
    assert score > 0 and reason is None


async def test_local_save_untouched_on_regular_node(db_session, monkeypatch):
    """Non-hub deployments keep the legacy LOCAL_ONLY placeholder semantics."""
    monkeypatch.setenv("IS_CENTRAL_HUB", "false")
    await _seed_cfg(db_session)

    payload = _local_payload(f"loc-legacy-{_uuid.uuid4().hex[:8]}")
    row = await crud.save_hub_telemetry_report(db_session, payload, "local-node")

    assert row.verification_status == "LOCAL_ONLY"
    assert row.is_mining_eligible is False


def test_score_trade_or_operator_duration_passes_movement_fails():
    """In OR mode, meeting duration threshold alone qualifies the trade."""
    cfg = _cfg(quality_gate_operator="OR")
    rep = SimpleNamespace(
        trade_mode="LIVE",
        trade_duration_sec=300,
        entry_price=100.0,
        exit_price=100.05,  # 0.05% < 0.15%
    )
    score, reason = score_trade_with_reason(rep, cfg)
    assert score > 0
    assert reason is None


def test_score_trade_or_operator_movement_passes_duration_fails():
    """In OR mode, meeting price movement threshold alone qualifies the trade."""
    cfg = _cfg(quality_gate_operator="OR")
    rep = SimpleNamespace(
        trade_mode="LIVE",
        trade_duration_sec=10,  # 10s < 30s
        entry_price=100.0,
        exit_price=101.0,  # 1.0% >= 0.15%
    )
    score, reason = score_trade_with_reason(rep, cfg)
    assert score > 0
    assert reason is None


def test_score_trade_or_operator_movement_passes_duration_missing():
    """In OR mode, missing duration passes if price movement meets threshold."""
    cfg = _cfg(quality_gate_operator="OR")
    rep = SimpleNamespace(
        trade_mode="LIVE",
        trade_duration_sec=None,
        entry_price=100.0,
        exit_price=101.0,  # 1.0% >= 0.15%
    )
    score, reason = score_trade_with_reason(rep, cfg)
    assert score > 0
    assert reason is None


def test_score_trade_or_operator_both_fail():
    """In OR mode, failing both duration and movement rejects with combined reason."""
    cfg = _cfg(quality_gate_operator="OR")
    rep = SimpleNamespace(
        trade_mode="LIVE",
        trade_duration_sec=10,  # 10s < 30s
        entry_price=100.0,
        exit_price=100.05,  # 0.05% < 0.15%
    )
    score, reason = score_trade_with_reason(rep, cfg)
    assert score == 0.0
    assert reason is not None
    assert "10s < min 30s" in reason
    assert "movement 0.050%" in reason


def test_score_trade_or_operator_both_fail_missing_duration():
    """In OR mode, missing duration + flat movement rejects with combined reason."""
    cfg = _cfg(quality_gate_operator="OR")
    rep = SimpleNamespace(
        trade_mode="LIVE",
        trade_duration_sec=None,
        entry_price=100.0,
        exit_price=100.05,  # 0.05% < 0.15%
    )
    score, reason = score_trade_with_reason(rep, cfg)
    assert score == 0.0
    assert reason is not None
    assert "missing trade duration" in reason
    assert "movement 0.050%" in reason


def test_score_trade_and_operator_requires_both():
    """In AND mode, failing either duration or movement rejects the trade."""
    cfg = _cfg(quality_gate_operator="AND")
    # Duration passes, movement fails -> reject
    rep_flat = SimpleNamespace(
        trade_mode="LIVE",
        trade_duration_sec=300,
        entry_price=100.0,
        exit_price=100.05,
    )
    score1, reason1 = score_trade_with_reason(rep_flat, cfg)
    assert score1 == 0.0
    assert reason1 and "movement" in reason1

    # Movement passes, duration fails -> reject
    rep_short = SimpleNamespace(
        trade_mode="LIVE",
        trade_duration_sec=10,
        entry_price=100.0,
        exit_price=101.0,
    )
    score2, reason2 = score_trade_with_reason(rep_short, cfg)
    assert score2 == 0.0
    assert reason2 and "10s < min 30s" in reason2


def test_mining_config_update_schema_operator_validation():
    from api.schemas import MiningConfigUpdate

    u1 = MiningConfigUpdate(quality_gate_operator="OR")
    assert u1.quality_gate_operator == "OR"

    u2 = MiningConfigUpdate(quality_gate_operator="or")
    assert u2.quality_gate_operator == "OR"

    u3 = MiningConfigUpdate(quality_gate_operator="and")
    assert u3.quality_gate_operator == "AND"

    with pytest.raises(ValueError):
        MiningConfigUpdate(quality_gate_operator="INVALID")
