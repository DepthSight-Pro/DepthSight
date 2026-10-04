# bot_module/hedge_mirror.py
"""Hedge (mirror) mode for trade-mining volume farming.

One strategy runs on two exchanges (two API keys, two TradingControllers):
- Leg A trades the strategy signal as-is.
- Leg B inverts every entry signal (LONG<->SHORT, SL/TP mirrored by distance
  around the leg's own reference price) and manages the position natively:
  partial TPs, trailing stops, DCA/grid, move-to-BE all work untouched,
  because each leg's controller leads its own position lifecycle.

Exit coupling is configurable per hedge group (``exit_policy``):
- ``RACE_FINAL_MARKET`` (default): the first leg's FINAL exit publishes a
  ``HEDGE_CLOSE_LEG`` command; the sibling controller market-closes its
  position for the same symbol/group immediately.
- ``SPREAD_PROFIT_EXIT``: one-sided spread take-profit. Each leg publishes
  its live mark/PnL to Redis; when the PAIR unrealized PnL (my pnl +
  sibling pnl, direction-agnostic by construction) reaches
  ``spread_exit_threshold_pct`` of the combined notional, the leg closes
  itself and market-closes the sibling. Requires ``FIXED_NOTIONAL`` sizing
  (equal notionals are what maps spread deviation to pair PnL).
- ``INDEPENDENT``: legs live until their own TP/SL. The only coupling is
  the paired launch. Best for decorrelated markets: a leg that did not hit
  its stop may still ride into profit after the sibling closed.
- ``MOVE_SL_TO_BE``: reserved for a future soft-coupling (ratchet sibling
  SL to breakeven instead of market-closing). Currently behaves as
  ``INDEPENDENT``.

Volume sync is configurable per hedge group (``size_mode``):
- ``FIXED_NOTIONAL`` (default): both legs open the same USD notional
  (``notional_usd``), so rebate farming earns symmetric volume on both
  exchanges. Implemented as an implied risk-budget override before
  RiskManager sizing; lot-step rounding and safety caps may still cause dust.
- ``SYNC_STEP``: strict volume sync. Both legs first apply the same
  ``notional_usd`` risk-budget override as ``FIXED_NOTIONAL``, then
  quantize down to the shared lot step (``qty_step``, the coarsest step of
  the two exchanges, resolved at launch), enter simultaneously, verify
  executed quantities post-fill, and watch for orphan legs
  (``entry_sync_timeout_sec``). Either both legs hold equal volumes capped
  at ``notional_usd`` or neither holds a position.
- ``INDEPENDENT``: each leg sizes by the strategy's own risk % of its
  account balance (volumes will differ across accounts).

Every leg position is always protected by its own exchange-native SL/TP
placed at entry. The cross-leg command is an optimization, never the
stop-loss mechanism.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Dict, Optional

from bot_module.datatypes import (
    OrderMode,
    PartialTarget,
    SignalDirection,
    StrategySignal,
)

logger = logging.getLogger("bot_module.hedge_mirror")

# --- Policy / role constants (duplicated in api/schemas.py HedgeConfig) ---

HEDGE_EXIT_INDEPENDENT = "INDEPENDENT"
HEDGE_EXIT_RACE_FINAL_MARKET = "RACE_FINAL_MARKET"
HEDGE_EXIT_MOVE_SL_TO_BE = "MOVE_SL_TO_BE"

HEDGE_EXIT_SPREAD_PROFIT = "SPREAD_PROFIT_EXIT"

HEDGE_EXIT_POLICIES = (
    HEDGE_EXIT_RACE_FINAL_MARKET,
    HEDGE_EXIT_INDEPENDENT,
    HEDGE_EXIT_MOVE_SL_TO_BE,
    HEDGE_EXIT_SPREAD_PROFIT,
)

HEDGE_DEFAULT_EXIT_POLICY = HEDGE_EXIT_RACE_FINAL_MARKET

# Spread-exit tuning (seconds / percent).
HEDGE_SPREAD_CHECK_INTERVAL_SEC = 3.0
HEDGE_SIBLING_STALE_SEC = 5.0
HEDGE_MARK_TTL_SEC = 30
HEDGE_COOLDOWN_TTL_SEC = 300
HEDGE_DEFAULT_SPREAD_THRESHOLD_PCT = 0.5
HEDGE_DEFAULT_SPREAD_COOLDOWN_SEC = 60

HEDGE_REDIS_PREFIX = "depthsight:hedge"


def hedge_mark_key(group_id: str, symbol: str, leg: str) -> str:
    """Redis key for one leg's live mark/PnL snapshot."""
    return f"{HEDGE_REDIS_PREFIX}:mark:{group_id}:{str(symbol).upper()}:{leg}"


def hedge_cooldown_key(group_id: str, symbol: str) -> str:
    """Redis key holding the last spread-trigger timestamp."""
    return f"{HEDGE_REDIS_PREFIX}:spread_cool:{group_id}:{str(symbol).upper()}"


def hedge_entry_key(group_id: str, symbol: str, leg: str) -> str:
    """Redis key for one leg's executed entry (qty/price/ts)."""
    return f"{HEDGE_REDIS_PREFIX}:entry:{group_id}:{str(symbol).upper()}:{leg}"


HEDGE_ENTRY_TTL_SEC = 7 * 24 * 3600  # entry proof must outlive positions


def quantize_to_shared_step(
    qty: float, shared_step: float, own_step: float
) -> Optional[float]:
    """Floors ``qty`` to the shared hedge lot step (exact-sync volumes).

    Returns None when syncing is unsafe: non-positive inputs, a shared step
    finer than the leg's own step (stale specs — caller falls back), steps
    that are not integer multiples of each other, or a non-positive result.
    """
    try:
        q = Decimal(str(qty))
        shared = Decimal(str(shared_step))
        own = Decimal(str(own_step))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if q <= 0 or shared <= 0 or own <= 0:
        return None
    ratio = shared / own
    if abs(ratio - round(ratio)) > Decimal("1e-9"):
        return None
    steps = (q / shared).to_integral_value(rounding=ROUND_DOWN)
    if steps <= 0:
        return None
    return float(steps * shared)


def hedge_spread_stats_key(group_id: str, symbol: str) -> str:
    """Redis hash with spread-exit stats (exits/dev_sum_pct/last_ts/threshold).

    Lets us rank venue pairs by how often they actually pay, instead of
    guessing. Read with HGETALL; fields are plain numbers/strings.
    """
    return f"{HEDGE_REDIS_PREFIX}:spread_stats:{group_id}:{str(symbol).upper()}"


HEDGE_SPREAD_STATS_TTL_SEC = 30 * 24 * 3600


def sibling_leg(leg: Optional[str]) -> Optional[str]:
    if leg == "A":
        return "B"
    if leg == "B":
        return "A"
    return None


def spread_trigger_fires(
    *,
    my_pnl: float,
    sibling_pnl: float,
    combined_notional_usd: float,
    threshold_pct: float,
) -> bool:
    """One-sided spread take-profit test (pure, direction-agnostic).

    Both PnLs are already signed, so no leg-direction logic is needed here:
    the pair earns exactly when their sum is positive. Fires only when pair
    profit reaches ``threshold_pct`` percent of the combined notional.
    """
    try:
        combined = float(combined_notional_usd)
        threshold = float(threshold_pct)
    except (TypeError, ValueError):
        return False
    if combined <= 0 or threshold <= 0:
        return False
    try:
        pair_pnl = float(my_pnl) + float(sibling_pnl)
    except (TypeError, ValueError):
        return False
    return pair_pnl >= combined * threshold / 100.0


def pair_pnl_pct(
    *,
    my_pnl: float,
    sibling_pnl: float,
    combined_notional_usd: float,
) -> Optional[float]:
    """Pair unrealized PnL in percent of combined notional (None if unknown)."""
    try:
        combined = float(combined_notional_usd)
    except (TypeError, ValueError):
        return None
    if combined <= 0:
        return None
    try:
        return (float(my_pnl) + float(sibling_pnl)) / combined * 100.0
    except (TypeError, ValueError):
        return None


HEDGE_SIDE_MODE_OPPOSITE = "OPPOSITE"

HEDGE_SIZE_FIXED_NOTIONAL = "FIXED_NOTIONAL"
HEDGE_SIZE_INDEPENDENT = "INDEPENDENT"
HEDGE_SIZE_SYNC_STEP = "SYNC_STEP"
HEDGE_DEFAULT_SIZE_MODE = HEDGE_SIZE_FIXED_NOTIONAL
HEDGE_SIZE_MODES = (
    HEDGE_SIZE_FIXED_NOTIONAL,
    HEDGE_SIZE_INDEPENDENT,
    HEDGE_SIZE_SYNC_STEP,
)

HEDGE_CLOSE_REASON_PREFIX = "HEDGE_RACE"
HEDGE_SPREAD_REASON_PREFIX = "HEDGE_SPREAD"
HEDGE_SYNC_FAIL_REASON_PREFIX = "HEDGE_SYNC_FAIL"

HEDGE_CLOSE_REASON_PREFIX = "HEDGE_RACE"
HEDGE_SPREAD_REASON_PREFIX = "HEDGE_SPREAD"


def get_hedge_config(running_instance_config: Any) -> Optional[Dict[str, Any]]:
    """Extracts the hedge block from a START_STRATEGY payload (if enabled).

    The API fans a hedge launch out into two payloads; each carries
    ``config_data.hedge = {enabled, group_id, leg, invert, exit_policy, ...}``.
    Returns the hedge dict or None when this instance is not a hedge leg.
    """
    if not isinstance(running_instance_config, dict):
        return None
    config_data = running_instance_config.get("config_data")
    if not isinstance(config_data, dict):
        return None
    hedge = config_data.get("hedge")
    if not isinstance(hedge, dict) or not hedge.get("enabled"):
        return None
    return hedge


def is_mirror_leg(hedge_cfg: Optional[Dict[str, Any]]) -> bool:
    """True when this instance must trade inverted signals (leg B)."""
    if not hedge_cfg:
        return False
    return hedge_cfg.get("leg") == "B" and bool(hedge_cfg.get("invert"))


def mirror_price(reference: float, price: float) -> float:
    """Mirrors ``price`` around ``reference`` (2*ref - price)."""
    return 2.0 * float(reference) - float(price)


def tag_hedge_details(
    details: Dict[str, Any], hedge_cfg: Dict[str, Any]
) -> Dict[str, Any]:
    """Stamps hedge attribution onto a signal/position details dict.

    Applied to BOTH legs so positions and trades carry ``hedge_group_id``,
    ``hedge_leg`` and ``hedge_exit_policy`` for analytics and race-coupling.
    """
    details["hedge_group_id"] = hedge_cfg.get("group_id")
    details["hedge_leg"] = hedge_cfg.get("leg")
    if hedge_cfg.get("exit_policy"):
        details["hedge_exit_policy"] = hedge_cfg.get("exit_policy")
    if hedge_cfg.get("sibling_api_key_id") is not None:
        details["hedge_sibling_api_key_id"] = hedge_cfg.get("sibling_api_key_id")
    if hedge_cfg.get("size_mode"):
        details["hedge_size_mode"] = hedge_cfg.get("size_mode")
    if hedge_cfg.get("notional_usd") is not None:
        details["hedge_notional_usd"] = hedge_cfg.get("notional_usd")
    return details


def maybe_apply_hedge_sizing(
    signal: StrategySignal, running_instance_config: Any
) -> StrategySignal:
    """Synchronizes hedge leg volumes to the same USD notional.

    In ``FIXED_NOTIONAL`` and ``SYNC_STEP`` modes both legs override the
    strategy's risk budget with an implied ``risk_usd`` that yields
    ``notional_usd`` at the signal reference price
    (``qty = risk / SL_distance`` in RiskManager, so
    ``risk_usd = notional * SL_distance / ref``). ``SYNC_STEP`` additionally
    quantizes the approved qty to the shared lot step in the controller, so
    without this override the strategy risk-% sizing would open arbitrary
    (e.g. $60 instead of the requested $20) equal-but-oversized legs.
    Exchange lot-step rounding and the max-notional safety cap may still
    cause dust-level differences; hard limits (minQty/min-notional) keep
    rejecting as before.
    Never raises: on any problem the signal is left unchanged (fail-open to
    the strategy's own risk-% sizing).
    """
    try:
        hedge_cfg = get_hedge_config(running_instance_config)
    except Exception as exc:
        logger.debug("Hedge sizing lookup failed, skipping: %s", exc)
        return signal
    if not hedge_cfg:
        return signal
    size_mode = str(hedge_cfg.get("size_mode") or HEDGE_SIZE_INDEPENDENT).upper()
    if size_mode not in (HEDGE_SIZE_FIXED_NOTIONAL, HEDGE_SIZE_SYNC_STEP):
        return signal
    try:
        notional = float(hedge_cfg.get("notional_usd") or 0.0)
    except (TypeError, ValueError) as exc:
        logger.error(
            "[HedgeSize:%s] Invalid notional_usd (%s). Using strategy sizing.",
            getattr(signal, "symbol", "?"),
            exc,
        )
        return signal
    if notional <= 0:
        logger.error(
            "[HedgeSize:%s] Non-positive notional_usd. Using strategy sizing.",
            getattr(signal, "symbol", "?"),
        )
        return signal

    # Reference price must match RiskManager.assess_signal, which sizes by
    # trigger_price when present (else entry_price). Using a mode-based
    # ref here (entry for LIMIT) diverged from RM and produced
    # notional != requested whenever trigger != entry.
    ref = (
        signal.trigger_price if signal.trigger_price is not None else signal.entry_price
    )
    if ref is None or float(ref) <= 0:
        logger.error(
            "[HedgeSize:%s] No reference price for fixed-notional sizing. "
            "Using strategy sizing.",
            getattr(signal, "symbol", "?"),
        )
        return signal
    ref = float(ref)

    if signal.stop_loss is None:
        # No-SL branch of RiskManager sizes straight by notional.
        signal.risk_usd = notional
        signal.risk_pct = None
    else:
        sl_distance = abs(ref - float(signal.stop_loss))
        if sl_distance <= 0:
            logger.error(
                "[HedgeSize:%s] Zero SL distance. Using strategy sizing.",
                getattr(signal, "symbol", "?"),
            )
            return signal
        signal.risk_usd = notional * sl_distance / ref
        signal.risk_pct = None

    try:
        if signal.details is None:
            signal.details = {}
        if isinstance(signal.details, dict):
            signal.details["hedge_notional_usd"] = notional
            signal.details["hedge_size_mode"] = size_mode
    except Exception as exc:
        logger.debug("Hedge sizing tagging failed (non-fatal): %s", exc)
    logger.info(
        "[HedgeSize:%s] %s $%.2f -> risk_usd $%.4f (ref %.4f).",
        signal.symbol,
        size_mode,
        notional,
        float(signal.risk_usd or 0.0),
        ref,
    )
    return signal


def invert_signal(
    signal: StrategySignal, hedge_cfg: Optional[Dict[str, Any]] = None
) -> StrategySignal:
    """Returns an opposite-direction copy of ``signal`` for the mirror leg.

    Distances are preserved around the signal's own reference price
    (``trigger_price`` for MARKET, ``entry_price`` for LIMIT modes), so the
    mirrored SL/TP/partial levels keep the strategy's original risk geometry
    on the second exchange. Raises ValueError if the reference price is
    missing (caller should skip such a signal — fail-closed).
    """
    if signal.direction == SignalDirection.NEUTRAL:
        raise ValueError("Cannot mirror a NEUTRAL signal.")

    if signal.mode != OrderMode.MARKET:
        ref = signal.entry_price
    else:
        ref = signal.trigger_price
    if ref is None or float(ref) <= 0:
        raise ValueError(
            f"Cannot mirror signal without a valid reference price "
            f"(mode={signal.mode}, entry={signal.entry_price}, "
            f"trigger={signal.trigger_price})."
        )
    ref = float(ref)

    new_direction = (
        SignalDirection.SHORT
        if signal.direction == SignalDirection.LONG
        else SignalDirection.LONG
    )

    new_sl = None
    if signal.stop_loss is not None:
        new_sl = mirror_price(ref, float(signal.stop_loss))

    new_tp = None
    if signal.take_profit is not None:
        new_tp = mirror_price(ref, float(signal.take_profit))

    new_partials = None
    if signal.partial_targets:
        new_partials = [
            PartialTarget(
                price=mirror_price(ref, float(pt.price)),
                fraction=pt.fraction,
            )
            for pt in signal.partial_targets
        ]

    details = dict(signal.details or {})
    details["hedge_mirrored"] = True
    details["hedge_original_direction"] = signal.direction.name
    tag_hedge_details(details, hedge_cfg or {})

    mirrored = StrategySignal(
        strategy_name=signal.strategy_name,
        symbol=signal.symbol,
        direction=new_direction,
        stop_loss=new_sl,
        take_profit=new_tp,
        entry_price=signal.entry_price,
        mode=signal.mode,
        signal_time=signal.signal_time,
        confidence=signal.confidence,
        trigger_price=signal.trigger_price,
        details=details,
        partial_targets=new_partials,
        move_sl_to_be_on_first_tp=signal.move_sl_to_be_on_first_tp,
        risk_pct=signal.risk_pct,
        risk_usd=signal.risk_usd,
        no_stop_loss=signal.no_stop_loss,
    )
    logger.info(
        "[HedgeMirror:%s] %s %s -> %s (SL %s->%s, TP %s->%s)",
        signal.symbol,
        signal.direction.name,
        ref,
        new_direction.name,
        signal.stop_loss,
        new_sl,
        signal.take_profit,
        new_tp,
    )
    return mirrored


def maybe_mirror_hedge_signal(
    signal: StrategySignal, running_instance_config: Any
) -> Optional[StrategySignal]:
    """Inverts ``signal`` when this instance is a mirror leg.

    Returns the (possibly new) signal to process, or None when mirroring was
    required but failed — the caller must drop such a signal (fail-closed:
    never trade the non-mirrored direction on a hedge leg). Never raises.
    """
    try:
        hedge_cfg = get_hedge_config(running_instance_config)
    except Exception as exc:  # fail-open for lookup errors (not a hedge leg)
        logger.debug("Hedge config lookup failed, skipping mirror: %s", exc)
        return signal
    if not hedge_cfg:
        return signal
    # Tag both legs so positions/trades carry hedge attribution.
    try:
        if signal.details is None:
            signal.details = {}
        if isinstance(signal.details, dict):
            tag_hedge_details(signal.details, hedge_cfg)
    except Exception as exc:
        logger.debug("Hedge tagging failed, continuing untagged: %s", exc)
    if not is_mirror_leg(hedge_cfg):
        return signal
    if isinstance((signal.details or {}), dict) and signal.details.get(
        "hedge_mirrored"
    ):
        return signal
    try:
        return invert_signal(signal, hedge_cfg)
    except Exception as exc:
        logger.error(
            "[HedgeMirror:%s] Failed to mirror signal (%s). "
            "Dropping mirror-leg entry (fail-closed).",
            getattr(signal, "symbol", "?"),
            exc,
        )
        return None


def build_hedge_race_close_command(
    *,
    user_id: int,
    api_key_id: int,
    group_id: str,
    symbol: str,
    market_type: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Builds a CLOSE_POSITION command that shuts the sibling hedge leg.

    Reuses the existing CLOSE_POSITION command path (filtered by
    ``api_key_id`` in every controller's Redis listener); the ``reason``
    carries a HEDGE_* prefix so the receiving leg does not re-broadcast.
    """
    group_short = str(group_id)[:8]
    payload: Dict[str, Any] = {
        "user_id": user_id,
        "api_key_id": api_key_id,
        "hedge_group_id": group_id,
        "symbol": symbol,
        "reason": reason or f"{HEDGE_CLOSE_REASON_PREFIX}:{group_short}",
    }
    if market_type:
        payload["market_type"] = market_type
    return {"command": "CLOSE_POSITION", "payload": payload}
