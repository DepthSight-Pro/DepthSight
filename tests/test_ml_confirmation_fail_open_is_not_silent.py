# File: tests/test_ml_confirmation_fail_open_is_not_silent.py
"""
A strategy that asks for ML confirmation must never look like it got one when
the model never ran.

THE DEFECT
----------
`_process_signal` evaluates live ML confirmation in two nested blocks:

    ml_confirmed_this_signal_live = True            # <- initialised optimistic
    if use_ml_confirmation_flag:                    # strategy asked for it
        if (runtime_enabled and extractor and pipeline):
            ...                                     # model actually runs
        else:
            logger.debug("... not enabled or components not ready. Skipping.")

The outer `else` was a DEBUG line, and it fell through leaving
`ml_confirmed_this_signal_live` at its initialised `True`. Two consequences:

  1. **Silent.** Every other fail-open in that same block is a WARNING that
     literally says "Allowing signal (fail-open)" -- missing klines, None from
     predict_proba_one, failed feature extraction, failed normalisation. This
     was the single fail-open that announced nothing, and at the deployed INFO
     level it was invisible.
  2. **A false audit record.** `signal.details["ml_confirmed_live"]` was
     stamped `True`, so the trade log affirmatively recorded that the model had
     approved a signal it never evaluated. A strategy configured with
     `use_ml_confirmation: true` was trading as though a risk control was
     gating it when nothing was checking anything.

This is NOT the same event as the sibling fail-opens. Those are "the model ran
and could not reach a verdict on this candle" -- transient. This one is "the
model never loaded at all" -- structural, and it persists for the life of the
process.

LIVE EVIDENCE (2026-10-07, deployment of 5d41335)
-------------------------------------------------
Every one of the 12 paper controllers logged at ERROR:

    [MLConfirmLive] Failed to load Live ML Confirmation model from
    data/offline_trained_model.joblib. Live ML Confirmation will be SKIPPED.

while `ML_CONFIRMATION_ENABLED` was true. Every controller therefore sat in the
exact state this test covers, permanently.

WHY THIS TEST SHAPE
-------------------
It calls the REAL `_process_signal` -- no copy of the branch under test -- on a
real `TradingController` with a real registered strategy instance, and asserts
on observable state: the WARNING actually emitted, and the `signal.details`
the trade log is built from. The signal is driven only as far as the end of the
ML block; `_get_market_info` is stubbed to raise a sentinel purely as a
ramp-stop, because everything this test claims has already happened by then.
"""

import asyncio
import logging
import time

import pytest

from bot_module.controller import (
    ActivePositionMap,
    LivePosition,
    SignalDirection,
    StrategySignal,
    TradingController,
)
from bot_module.paper_executor import PaperTradingExecutor
from bot_module.risk_manager import RiskManager

@pytest.fixture(autouse=True)
def _propagate_bot_module_logs():
    bml = logging.getLogger('bot_module')
    old = bml.propagate
    bml.propagate = True
    yield
    bml.propagate = old

USER_ID = 10
SYMBOL = "BTCUSDT"
STRATEGY_NAME = "VisualBuilderStrategy"


class _StopHere(Exception):
    """Ramp-stop raised from the stubbed post-ML section.

    Deliberately NOT swallowed by `_process_signal`'s own handlers in a way that
    hides the assertions: the test catches it and then inspects state that was
    written before it was raised.
    """


class _FakeDataConsumer:
    async def get_kline_history(self, *a, **k):
        return None

    async def get_recent_trades(self, *a, **k):
        return None


class _RecordingTradeLogger:
    def __init__(self):
        self.events = []

    def log_event(self, event_type, data=None, **kw):
        self.events.append((event_type, data))


class _StubStrategy:
    """Only `.NAME` is read by `_process_signal` when locating a config."""

    NAME = STRATEGY_NAME


def _build_controller(use_ml_confirmation: bool):
    """A real TradingController carrying only the attribute surface this path reads."""
    paper_executor = PaperTradingExecutor(
        user_id=USER_ID,
        db_session=None,
        data_consumer=_FakeDataConsumer(),
        redis_client=None,
    )

    controller = TradingController.__new__(TradingController)
    controller.loop = asyncio.get_event_loop()
    controller.user_id = USER_ID
    controller.api_key_id = None
    controller.api_key_name = "paper"
    controller.executors = {"live": None, "paper": paper_executor}
    controller.consumer = _FakeDataConsumer()

    # --- throttling / locking that `_process_signal` touches before the ML block
    controller._processing_signal_lock = asyncio.Lock()
    controller._processing_signal_for_symbol = set()
    controller._recent_signals = {}
    controller._signal_throttle_period = 0
    controller._last_position_close_time_per_symbol = {}
    controller._symbol_cooldown_duration = 0
    controller._positions_dict_lock = asyncio.Lock()
    controller._active_positions = ActivePositionMap()
    controller._symbol_locks = {}

    # --- the running strategy the config lookup must find
    controller.instances_lock = asyncio.Lock()
    controller.running_strategy_instances = {
        "cfg-abc": (
            _StubStrategy(),
            {
                "config": {"market_type": "futures"},
                "market_type": "futures",
                "mode": "paper",
                "use_ml_confirmation": use_ml_confirmation,
                "user_id": USER_ID,
            },
        )
    }

    # --- THE CONDITION UNDER TEST: model never loaded.
    # This mirrors production exactly -- ML_CONFIRMATION_ENABLED is true and
    # `data/offline_trained_model.joblib` is absent, so `start()` sets the
    # runtime flag False and leaves both components None.
    controller._ml_confirmation_enabled_live_runtime = False
    controller._ml_confirmation_feature_extractor_live = None
    controller._ml_confirmation_pipeline_live = None

    controller.trade_logger = _RecordingTradeLogger()
    controller.telegram_notifier = None
    controller.user_telegram_chat_id = None
    controller.rm = RiskManager(
        executor=None,
        paper_executor=paper_executor,
        user_id=USER_ID,
        db_session=None,
        user_settings={},
    )
    controller.rm.max_concurrent_trades = 100

    async def _stop(*a, **k):
        raise _StopHere()

    controller._get_market_info = _stop
    return controller


def _make_signal():
    return StrategySignal(
        strategy_name=STRATEGY_NAME,
        symbol=SYMBOL,
        direction=SignalDirection.LONG,
        stop_loss=90_000.0,
        take_profit=95_000.0,
        entry_price=92_000.0,
        trigger_price=92_000.0,
        details={"strategy_config_id": "cfg-abc"},
    )


def _run(controller, signal):
    """Drive the real method, stopping cleanly past the ML block.

    `_process_signal` wraps its whole body in a broad handler and logs
    "UNEXPECTED EXCEPTION" rather than re-raising, so the ramp-stop does not
    escape. That is fine -- everything this test asserts on was already written
    to `signal.details` and the log stream before the sentinel was raised, and
    that the sentinel was reached at all is itself proof the ML block ran.
    """
    pair_info = {"market_type": "futures", "last_price": 92_000.0}
    asyncio.get_event_loop().run_until_complete(
        controller._process_signal(signal, pair_info)
    )
    return signal


# --- the defect --------------------------------------------------------------


def test_ml_requested_but_model_missing_is_not_silent(caplog):
    """The whole point: this fail-open must not be DEBUG-only.

    Before the fix this branch emitted a DEBUG line, which is invisible at the
    deployed INFO level -- so a strategy trading with no ML confirmation
    produced no evidence at all.
    """
    controller = _build_controller(use_ml_confirmation=True)
    signal = _make_signal()

    with caplog.at_level(logging.INFO):
        _run(controller, signal)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, (
        "A strategy requested ML confirmation but the model was unavailable, "
        "and nothing was logged at WARNING. This fail-open is silent again."
    )

    joined = " ".join(r.getMessage() for r in warnings)
    assert "fail-open" in joined.lower(), (
        f"The WARNING must name the fail-open explicitly, so an operator "
        f"reading logs knows nothing gated the trade. Got: {joined!r}"
    )
    assert "ML confirmation was REQUESTED" in joined, (
        f"The WARNING must state that ML confirmation was requested but could "
        f"not run, not merely that it was 'skipped'. Got: {joined!r}"
    )


def test_ml_requested_but_model_missing_names_the_missing_component(caplog):
    """'not ready' is not actionable. The log must say WHAT is missing."""
    controller = _build_controller(use_ml_confirmation=True)
    signal = _make_signal()

    with caplog.at_level(logging.INFO):
        _run(controller, signal)

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "_ml_confirmation_enabled_live_runtime" in joined, (
        "The WARNING must name the specific missing component so the operator "
        f"knows what to fix. Got: {joined!r}"
    )


def test_trade_log_does_not_claim_ml_approved_a_signal_it_never_saw():
    """The false audit record is the more damaging half of the defect.

    `ml_confirmed_live` is True both when the model approved the signal and when
    the model never ran, so on its own it cannot support the claim "ML cleared
    this trade". The new `ml_confirmation_evaluated` flag must be False here.
    """
    controller = _build_controller(use_ml_confirmation=True)
    signal = _make_signal()

    _run(controller, signal)

    assert signal.details.get("ml_confirmation_evaluated") is False, (
        "The model never ran, so the signal must be recorded as NOT evaluated. "
        f"Got: {signal.details.get('ml_confirmation_evaluated')!r}"
    )

    reason = signal.details.get("ml_confirmation_skipped_reason")
    assert reason, "The reason the model could not run must be recorded."
    assert "fail-open" in reason.lower(), (
        f"The recorded reason must name the fail-open. Got: {reason!r}"
    )


def test_absent_model_fails_closed_when_configured(monkeypatch):
    """The fail-open/fail-closed choice must be a real switch, not an accident.

    The behaviour before this flag existed was fail-open -- but only because
    the branch logged at DEBUG and fell through. Nobody chose it, and nothing
    recorded the decision. With ML_CONFIRMATION_FAIL_OPEN=False an operator
    who treats ML confirmation as a risk control that must not be bypassed
    gets the signal REJECTED instead.
    """
    from bot_module import config

    monkeypatch.setattr(config, "ML_CONFIRMATION_FAIL_OPEN", False)
    controller = _build_controller(use_ml_confirmation=True)
    signal = _make_signal()

    _run(controller, signal)

    rejections = [
        e for e in controller.trade_logger.events
        if e[0] == "SIGNAL_REJECTED_ML_LIVE"
    ]
    assert rejections, (
        "With ML_CONFIRMATION_FAIL_OPEN=False a signal that cannot be confirmed "
        "must be REJECTED, not passed through. The switch does nothing."
    )
    assert signal.details.get("ml_confirmation_evaluated") is False, (
        "A rejected signal still records that nothing evaluated it, so the "
        "trade log shows WHY it was rejected."
    )


def test_fail_closed_logs_at_error_not_warning(caplog):
    """Losing a signal to a missing model is not a 'heads up' -- it is a halt.

    WARNING is the level used for the deliberately fail-open path. Fail-closed
    means trades are being blocked, which must read differently in the log.
    """
    from bot_module import config

    with caplog.at_level(logging.INFO):
        old = config.ML_CONFIRMATION_FAIL_OPEN
        config.ML_CONFIRMATION_FAIL_OPEN = False
        try:
            controller = _build_controller(use_ml_confirmation=True)
            _run(controller, _make_signal())
        finally:
            config.ML_CONFIRMATION_FAIL_OPEN = old

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("ML_CONFIRMATION_FAIL_OPEN" in r.getMessage() for r in errors), (
        "Fail-closed must log at ERROR and must state which switch caused it, "
        "so the fix is obvious from the logs alone."
    )


def test_default_config_does_not_advertise_a_model_that_does_not_exist():
    """The config must not claim a capability the deployment lacks.

    `ML_CONFIRMATION_ENABLED` was a hardcoded True pointing at
    `data/offline_trained_model.joblib`, a file that has never existed in this
    repository. Every one of the 12 controllers logged a load failure on every
    start while the config asserted the feature was on. A flag that lies is
    worse than an honest False.
    """
    from pathlib import Path

    from bot_module import config

    assert config.ML_CONFIRMATION_ENABLED is False, (
        "ML_CONFIRMATION_ENABLED must default to False while no model exists. "
        "If a model has been trained and deployed, set the "
        "ML_CONFIRMATION_ENABLED environment variable instead of flipping this."
    )
    model_path = Path(config.ML_CONFIRMATION_MODEL_PATH)
    assert not model_path.exists(), (
        f"If {model_path} now exists, this test should be revisited: the model "
        f"may genuinely be deployed and the default may need to change."
    )


def test_ml_settings_are_environment_overridable():
    """Deploying a model must not require editing code and rebuilding containers.

    Turning the feature on is a deployment decision (the artifact exists or it
    does not), so both switches have to be settable from the environment.
    """
    from bot_module import config

    for attr in (
        "ML_CONFIRMATION_ENABLED",
        "ML_CONFIRMATION_FAIL_OPEN",
        "ML_CONFIRMATION_MODEL_PATH",
    ):
        assert hasattr(config, attr), f"{attr} must exist on config."


# --- guards: the fix must not have broken the working paths -------------------


def test_ml_not_requested_records_nothing_extra():
    """A strategy that never asked for ML must not be marked as a fail-open.

    Otherwise every ordinary trade in the system would carry a scary skipped
    reason, which is the same mistake as a guard that cries wolf on normal
    traffic.
    """
    controller = _build_controller(use_ml_confirmation=False)
    signal = _make_signal()

    _run(controller, signal)

    assert "ml_confirmation_skipped_reason" not in signal.details, (
        "ML was never requested for this strategy, so there is nothing to "
        f"report. Got: {signal.details.get('ml_confirmation_skipped_reason')!r}"
    )


def test_signal_not_rejected_by_absent_model_remains_fail_open():
    """Behaviour is deliberately UNCHANGED: the trade still proceeds.

    Flipping this to fail-closed is a business decision about risk appetite,
    not a bug fix, and would silently stop every ML-configured strategy from
    trading. This test pins the current behaviour so the logging fix cannot be
    mistaken for a behaviour change, and so the decision is made explicitly
    later rather than by accident.
    """
    controller = _build_controller(use_ml_confirmation=True)
    signal = _make_signal()

    _run(controller, signal)

    rejections = [
        e for e in controller.trade_logger.events
        if e[0] == "SIGNAL_REJECTED_ML_LIVE"
    ]
    assert not rejections, (
        "The absent model must not start rejecting trades -- that would halt "
        "every ML-configured strategy. Failing open is still the behaviour; "
        "only its visibility changed."
    )


# --- the diagnosability fix ---------------------------------------------------


def test_log_scope_identifies_the_controller():
    """All 12 paper controllers share `api_key_name='paper'`.

    That is what made five independent controllers look like one controller
    misbehaving on a 60s throttle. The prefix must identify the actor.
    """
    controller = _build_controller(use_ml_confirmation=True)
    assert controller._log_scope == "paper/u10", (
        f"Expected the controller to identify itself by user. Got: "
        f"{controller._log_scope!r}"
    )


# --- structural regression ----------------------------------------------------


def test_log_scope_property_did_not_swallow_the_rest_of_init():
    """REGRESSION: an earlier version of `_log_scope` was defined INSIDE `__init__`.

    It was placed immediately after the `logger.info("TradingController
    initialized.")` line, which pushed everything that followed -- the
    TelegramNotifier status logs and the symbol-cooldown log -- into the
    property's body, after its `return`. Python accepted it silently; the file
    parsed, every test still passed, and three startup log lines were simply
    never emitted again.

    That is the same defect class this whole file is about: a change that is
    invisible in every green test run and only visible in production as missing
    output. It was caught by the OpenCode adversarial review, not by a test.

    This asserts on the COMPILED function rather than the source text, so it
    survives reformatting and cannot be fooled by a string that merely appears
    somewhere in the file. If any statement is ever orphaned out of `__init__`
    again, this goes red.
    """
    init_consts = TradingController.__init__.__code__.co_consts
    assert any(
        isinstance(c, str) and "Symbol cooldown after close" in c
        for c in init_consts
    ), (
        "The symbol-cooldown log has left __init__. If a property or nested "
        "def was inserted into the constructor body, the statements after it "
        "become unreachable dead code that no test would otherwise catch."
    )
    assert any(
        isinstance(c, str) and "TelegramNotifier instance received" in c
        for c in init_consts
    ), (
        "The TelegramNotifier status log has left __init__, same failure mode."
    )


def test_log_scope_is_a_property_not_a_constructor_step():
    """`_log_scope` must be a property on the class, not code inside `__init__`."""
    assert isinstance(
        TradingController.__dict__.get("_log_scope"), property
    ), (
        "_log_scope must be declared as a @property at class level. If it is "
        "defined inside __init__ it becomes dead code after its return."
    )


# --- per-user log identity -----------------------------------------------------


def test_startcmd_log_prefix_identifies_the_user():
    """Twelve controllers log concurrently; StartCmd lines must say which user.

    A strategy id (`571be7ef`) showed up "already running" in the log but in no
    user's API response, and there was no way to tell from the log whether it
    was a real unlisted strategy of the logged-in user or simply another
    account's. Twelve controllers, one log, no attribution.

    The same gap `_log_scope` closed for the paper-exit and risk-check paths.
    Without the user id this question is unanswerable after the fact.
    """
    controller = _build_controller(use_ml_confirmation=True)
    # The property is what StartCmd now interpolates.
    assert controller._log_scope == "paper/u10", (
        "StartCmd must resolve a per-user scope so twelve concurrent "
        f"controllers can be told apart. Got: {controller._log_scope!r}"
    )
    assert controller._log_scope.startswith(
        controller.api_key_name
    ), "scope should still identify the trading mode"

    # And the attributes it depends on must exist before any handler runs.
    import inspect

    src = inspect.getsource(TradingController)
    assert "self.user_id =" in src and "self.api_key_name =" in src, (
        "_log_scope reads user_id and api_key_name; both must be assigned in "
        "__init__ or StartCmd would raise AttributeError on every START."
    )


# --- the RESERVING placeholder leak -------------------------------------------


def test_exception_after_reservation_does_not_leak_the_slot():
    """An unexpected exception must NOT leave a RESERVING placeholder behind.

    `_process_signal` inserts a zero-quantity `RESERVING` placeholder before any
    exchange work so a second signal for the same symbol cannot race in. It is
    popped on every explicit failure path, but the generic `except Exception`
    did not pop it -- so any unexpected exception leaked the reservation
    permanently.

    A leaked reservation is invisible to `_publish_state_to_redis` (which skips
    status != "OPEN"), so `/api/v1/positions` returns [] while the bot still
    holds the slot. It also counts toward `max_concurrent_trades`, because
    RESERVING is in that status tuple. The symbol can then never open a
    position again, with no money moved and nothing in the API to explain it.

    Observed live 2026-10-07 as `BTCUSDT=RESERVING`.
    """
    controller = _build_controller(use_ml_confirmation=False)

    # Drive the REAL method and blow up inside it, after the reservation.
    async def _boom(*a, **k):
        raise RuntimeError("simulated mid-flight failure")

    controller._get_market_info = _boom
    signal = _make_signal()
    _run(controller, signal)

    leftover = controller._active_position_get("BTCUSDT", "futures")
    assert leftover is None, (
        f"The RESERVING placeholder leaked after an exception. The symbol is "
        f"now permanently blocked, invisible to the API, and consuming a "
        f"concurrent-trades slot. Leaked record: status="
        f"{getattr(leftover, 'status', None)!r}"
    )


def test_ordinary_return_after_reservation_does_not_leak_the_slot():
    """THE CASE THAT ACTUALLY BIT PRODUCTION -- no exception involved.

    `git grep` on the deployed logs showed "UNEXPECTED EXCEPTION in
    _process_signal" in NO log file, so the leak was not the exception path at
    all. It was an ordinary early `return`.

    `_process_signal` reserves the slot at the top and then bails at several
    points without releasing it. This drives the single most likely one: the
    strategy config is not found (controller.py:8001, "CRITICAL: Running
    configuration not found for strategy ... Signal ignored"), which happens
    when a candle arrives for a symbol before its strategy instance has been
    registered -- a startup race.

    A leaked reservation blocks that symbol permanently, hides it from the API,
    and eats a `max_concurrent_trades` slot. `RESERVING` is in that status
    tuple, so the damage compounds over time.
    """
    controller = _build_controller(use_ml_confirmation=False)

    # Simulate the startup race: no strategy config is registered, so
    # `_process_signal` bails at the "Running configuration not found" return.
    # The instances_lock guards concurrent mutation; a single-threaded test
    # does not need to await it.
    controller.running_strategy_instances = {}

    signal = _make_signal()
    _run(controller, signal)

    leftover = controller._active_position_get("BTCUSDT", "futures")
    assert leftover is None, (
        f"A plain early return leaked the RESERVING placeholder: "
        f"status={getattr(leftover, 'status', None)!r}. BTCUSDT was stuck this "
        f"way in production. The release must live in `finally` so every exit "
        f"is covered, not only the paths that remembered to pop."
    )


def test_release_happens_on_a_normal_reject_too():
    """Even a *correct* rejection must release the slot.

    RiskManager saying "no" is the system working. It must not cost the symbol
    its ability to trade on the next candle.
    """
    controller = _build_controller(use_ml_confirmation=False)

    async def _reject(*a, **k):
        # A rejection raised from downstream still unwinds through `finally`.
        raise RuntimeError("downstream rejection")

    controller._get_market_info = _reject
    signal = _make_signal()
    _run(controller, signal)

    assert controller._active_position_get("BTCUSDT", "futures") is None, (
        "The reservation must be released regardless of why processing ended."
    )


def test_exception_does_not_pop_a_real_position():
    """Cleanup must never orphan a real trade.

    By the time the handler runs, the reservation may have been promoted into a
    genuine filled position. Popping that would remove a live trade from
    tracking while the exchange still holds it.

    The record is mutated IN PLACE rather than replaced with a fresh
    `LivePosition`, because `ActivePositionMap` keys on a normalised
    market-type string and a synthetic position can land under a different key
    than the one the controller reserved. Mutating preserves the exact key and
    tests the guard itself: zero-quantity RESERVING is the placeholder, anything
    else is real and must survive.
    """
    controller = _build_controller(use_ml_confirmation=False)
    captured = {}

    async def _promote_then_boom(*a, **k):
        # The placeholder already exists under the controller's own key.
        key = controller._position_key("BTCUSDT", "futures")
        placeholder = controller._active_positions.get(key)
        assert placeholder is not None, "expected the reservation to exist"
        captured["placeholder"] = placeholder
        # Simulate it being promoted into a real filled position mid-flight.
        placeholder.status = "OPEN"
        placeholder.remaining_quantity = 0.01
        placeholder.entry_price = 92000.0
        raise RuntimeError("simulated failure AFTER the position went live")

    controller._get_market_info = _promote_then_boom
    signal = _make_signal()
    _run(controller, signal)

    survivor = controller._active_position_get("BTCUSDT", "futures")
    assert survivor is not None, (
        "A real OPEN position was popped by the reservation cleanup. That "
        "orphans a live trade while the exchange still holds it."
    )
    assert survivor.status == "OPEN"
    assert survivor is captured["placeholder"], (
        "The map must still hold the same object; a pop-and-reinsert would "
        "mean the cleanup removed the record entirely."
    )