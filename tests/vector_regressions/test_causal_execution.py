"""Run with: python -m unittest discover -s tests/vector_regressions -v.

These are isolated tests of actual engine methods, not a full app integration
suite. Fixed quantities isolate execution; the SMA adapter is exact arithmetic
and tests warmup handling, not pandas-ta compatibility.
"""
import unittest
from types import SimpleNamespace

from load_engine import C, ns, pd, np, sim

FLAT = [100, 101, 99, 100]


class CausalExecutionTests(unittest.TestCase):
    def test_future_and_invalid_shifts_rejected(self):
        for shift in (-1, -0.5, 0.5, 'bad', float('nan'), float('inf')):
            with self.subTest(shift=shift), self.assertRaises(ValueError):
                C._validate_causal_shifts({'children': [{'source': 'candle', 'shift': shift}]})

    def test_valid_historical_shifts(self):
        for value in (0, 1, 10, '2'):
            self.assertEqual(C._historical_shift({'shift': value}), int(value))

    def test_runtime_resolver_also_rejects_future(self):
        with self.assertRaises(ValueError):
            C.__new__(C)._resolve_value_series({'source': 'candle', 'key': 'close', 'shift': -1})

    def test_long_gap_stop(self):
        x = sim([FLAT, FLAT, [90, 92, 89, 91]])
        self.assertEqual(x.trade_log[0]['exit_price'], 90)

    def test_short_gap_stop(self):
        x = sim([FLAT, FLAT, [110, 112, 109, 111]], side='SHORT')
        self.assertEqual(x.trade_log[0]['exit_price'], 110)

    def test_stop_before_liquidation_with_protective_stop(self):
        x = sim([FLAT, [100, 101, 80, 90], FLAT], qty=100, balance=1000)
        self.assertEqual(x.trade_log[0]['exit_reason'], 'STOP_LOSS')
        self.assertEqual(x.current_balance, 500)

    def test_stop_loss_enters_floating_drawdown(self):
        x = sim([FLAT, [100, 101, 94, 100], FLAT], qty=10, balance=1000)
        self.assertAlmostEqual(x.max_floating_dd, 5)

    def test_short_stop_loss_enters_floating_drawdown(self):
        x = sim([FLAT, [100, 106, 99, 100], FLAT], qty=10, balance=1000, side='SHORT')
        self.assertAlmostEqual(x.max_floating_dd, 5)

    def test_no_floating_peak_after_full_target(self):
        x = sim([FLAT, [100, 200, 99, 100], FLAT], qty=10, balance=1000)
        self.assertAlmostEqual(x.max_floating_dd, 1)
        self.assertAlmostEqual(x._floating_peak_equity, 1100)
        self.assertAlmostEqual(x.current_balance, 1100)

    def test_no_short_floating_peak_after_full_target(self):
        x = sim([FLAT, [100, 101, 1, 100], FLAT], qty=10, balance=1000, side='SHORT')
        self.assertAlmostEqual(x.max_floating_dd, 1)
        self.assertAlmostEqual(x._floating_peak_equity, 1100)

    def test_partial_then_full_target_uses_remaining_quantity(self):
        x = sim([FLAT, [100, 200, 99, 100], FLAT], qty=10, balance=1000,
                tp=20, extra={'partial_exits': [{'size_pct': 50, 'tp_type': 'percent_from_price', 'tp_value': 10}]})
        self.assertAlmostEqual(x.current_balance, 1150)
        self.assertAlmostEqual(x._floating_peak_equity, 1150)
        self.assertAlmostEqual(x.max_floating_dd, 1)

    def test_partial_target_marks_only_remaining_exposure(self):
        x = sim([FLAT, [100, 115, 99, 100]], qty=10, balance=1000,
                tp=20, extra={'partial_exits': [{'size_pct': 50, 'tp_type': 'percent_from_price', 'tp_value': 10}]})
        self.assertAlmostEqual(x.current_balance, 1050)
        self.assertAlmostEqual(x._floating_peak_equity, 1125)
        self.assertAlmostEqual(x.max_floating_dd, (1125-1050)/1125*100)

    def test_timeout_uses_last_processed_bar(self):
        x = sim([FLAT, FLAT, [100, 101, 90, 100], FLAT], hold=1)
        t = x.trade_log[0]
        self.assertEqual(t['exit_reason'], 'TIMEOUT')
        self.assertEqual(t['exit_time'], x.main_df.index[1])

    def test_stop_on_last_held_bar_wins_over_timeout(self):
        x = sim([FLAT, FLAT, [100, 101, 90, 100], FLAT], hold=2)
        self.assertEqual(x.trade_log[0]['exit_reason'], 'STOP_LOSS')
        self.assertEqual(x.trade_log[0]['exit_price'], 95)

    def test_timeout_exactly_at_end(self):
        x = sim([FLAT, FLAT], hold=1)
        self.assertEqual(x.trade_log[0]['exit_reason'], 'TIMEOUT')

    def test_fees_and_slippage_conservation(self):
        x = sim([FLAT, FLAT, [110, 111, 109, 110]], sl=0, tp=0, qty=2, fee=.0006, slip=.0005)
        entry, exit = 100 * 1.0005, 110 * .9995
        fee = (entry + exit) * 2 * .0006
        self.assertAlmostEqual(x.trade_log[0]['pnl_usd'], (exit-entry)*2-fee)
        self.assertGreaterEqual(x.max_floating_dd, 0)

    def test_end_of_data_still_reconciles_full_equity(self):
        x = sim([FLAT, FLAT, [99, 100, 98, 99]], sl=0, tp=0)
        k = x._calculate_kpis()
        self.assertEqual(k['final_equity'], 9999)
        self.assertAlmostEqual(k['total_return_all'], -.01)

    def test_atr_helper_preserves_warmup_nan(self):
        b = C.__new__(C)
        b.main_df = pd.DataFrame({'ATR_14': [np.nan, np.nan, 7.]})
        self.assertTrue(pd.isna(b._get_main_atr_series().iloc[0]))

    def test_sma_warmup_is_prefix_invariant(self):
        original_ta = ns.get('ta')
        ns['ta'] = SimpleNamespace(sma=lambda close, length: close.rolling(length).mean())
        try:
            for future_close in (100., 400.):
                b = C.__new__(C)
                b.main_df = pd.DataFrame({'close': [100., 100., future_close], 'ATR_14': [1., 1., 1.]})
                b.base_timeframe = '1m'
                b.data_context = {'1m': b.main_df}
                b.signals = pd.DataFrame(index=b.main_df.index)
                b.broadcasted_cache = {}
                b.strategy_json = {'entryConditions': {'type': 'value_comparison', 'params': {'leftOperand': {'source': 'indicator', 'key': 'SMA_3'}}}}
                b._ensure_market_features = lambda: None
                b._prepare_data()
                self.assertTrue(b.signals.SMA_3.iloc[:2].isna().all())
                self.assertAlmostEqual(b.signals.SMA_3.iloc[2], (200+future_close)/3)
        finally:
            ns['ta'] = original_ta

    def test_closed_hour_does_not_change_with_future(self):
        b = C.__new__(C)
        idx = pd.date_range('2026-01-01 09:00', periods=121, freq='min')
        b.main_df = pd.DataFrame({'close': 100.}, index=idx)
        b.base_timeframe = '1h'
        b.data_context = {'1h': pd.DataFrame({'close': [100., 110., 120.]}, index=idx[::60])}
        operand = {'source': 'candle', 'key': 'close'}
        self.assertEqual(b._resolve_value_series(operand).iloc[61], 100)
        b.data_context['1h'].iloc[1, 0] = 70
        self.assertEqual(b._resolve_value_series(operand).iloc[61], 100)


if __name__ == '__main__':
    unittest.main()
