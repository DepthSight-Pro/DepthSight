# VECTOR causal execution fixes: review guide

This proposal fixes four reproducible issues in the VECTOR path based on
`a5d372feaa255ad98f7208eea055a2bb2222a929`.

## Changes and examples

- Reject negative, fractional and non-finite historical shifts during strategy
  construction and operand resolution. A future hourly Close must not be exposed
  by `shift=-1`. Non-negative integer shifts retain their existing units.
- Replace backward fills in VECTOR indicator/filter preparation and ATR helpers
  with forward fills. Initial missing indicator values remain missing where
  the existing path does not explicitly define a causal fallback. SMA3 on
  `[100, 100, 400]` must not report 200 on the first candle.
- Record floating equity at the open, adverse excursion, executed stops/targets,
  remaining exposure and final net balance. Track its peak separately from the
  closed balance peak. A 5% realized stop loss must appear in floating drawdown;
  a full TP at 110 must not benefit from a later candle high of 200.
- End a holding timeout at the close of the last bar that was actually processed.
  `max_hold_candles=1` processes the entry bar and exits at its close. Previously
  it used the next bar's Close without processing that bar's SL/TP. A timeout
  exactly at the data boundary is now a TIMEOUT, not an END_OF_DATA close.

## Explicit execution assumption

For the simple SL/TP path, floating observations use an adverse-first OHLC path,
consistent with SL winning when SL and TP both lie in one bar. Observe the open,
then the adverse excursion or stop, then target executions, then the favorable
extreme/close for remaining exposure. This is a declared simulation assumption,
not a reconstruction of exchange ticks. Fees and final funding are included via
the existing ledger and final net-balance observation.

## Validation

Run from the repository root with Python, numpy and pandas:

```sh
python -m unittest discover -s tests/vector_regressions -v
```

20 tests pass on this branch. They cover shift validation, warmup prefix
invariance, long/short stop and gap execution, full and partial targets, floating
drawdown, holding-window boundaries, fee arithmetic and final equity.

The standalone loader extracts unchanged class methods from the actual source
using Python AST, avoiding unrelated Celery/database/application imports.
Execution fixtures fix quantities and bypass external risk checks/exchange
rounding. The SMA adapter is exact rolling arithmetic; it tests warmup handling,
not pandas-ta compatibility. This is intentionally **not** a claim that the full
application test suite, real exchanges or deployment have been verified.

For comparison against another checkout, set `VECTOR_AUDIT_SOURCE` to its root.
Before merging, run the existing VECTOR, strategy and task tests with the real
application dependencies and review indicator-library failure handling. The new
warmup behavior and corrected timeout window intentionally change old results.

## Remaining audit findings / excluded scope

- Source-bar versus minute-bar shift units and hourly entry-trigger cadence.
- Missing-timeframe and missing-indicator error contracts; initial causal ATR
  fallback still exists and is not a fully calculated ATR.
- Full capital PnL versus closed-signal-only END_OF_DATA statistics.
- True exchange margin/liquidation rules, including stops beyond liquidation.
- Historical funding, mark price, spread, liquidity and fills.
- Precision, DCA/grid/scale-in/conditional-management intrabar path equivalence.
- Close timestamps still follow the existing bar-label convention; the timeout
  fix changes the selected bar, not the timestamp API.

Please keep this as a draft until the maintainer's agent independently reviews
the chosen OHLC policy, runs integration tests, and accepts or requests changes.
