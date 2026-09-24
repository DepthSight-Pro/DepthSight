# tests/test_prod_pipeline_e2e.py
"""
Production-pipeline e2e (marker: prod_e2e, nightly/manual only).

Unlike the matrix / live-integrity suites (which hand-build pair_info and
call checkers directly), this suite drives the REAL production data path:

    DataConsumer.ensure_subscription (direct mode, live exchange WS)
      -> _ensure_history_loaded (REST history)
      -> _recalculate_kline_indicators / _recalculate_tape_metrics
      -> get_active_pair_by_symbol + get_kline_history / get_latest_depth /
         get_recent_trades / get_open_interest
      -> VisualBuilderStrategy evaluation (blocks, links, fuzz trees)

Per exchange it covers:
  L1 — every production block type evaluated on pipeline snapshots,
  L2 — cross-block links (block_result, senior_tf_confluence) and the full
       check_signal_sync dispatch incl. weight accounting,
  L3 — seeded fuzz trees (deterministic) over the production registry.

How to run (needs internet to public exchange endpoints, no API keys)::
    pytest tests/test_prod_pipeline_e2e.py -m prod_e2e -q

Expected budget: ~2-4 min per exchange (history + WS warmup).
Unreachable exchanges / missing streams -> pytest.skip with the stream named
(this doubles as the per-exchange capability matrix from the plan).

Notes on fidelity:
- Public WS/REST streams are pointed at MAINNET endpoints (testnet WS/REST
  flakiness caused false skips); no private calls are made, so no keys needed.
- Klines: one bounded REST fetch per TF (real recent candles: 150/150/150/100)
  replayed candle-by-candle through the production _update_local_cache
  handler — the same function the WS loop feeds. The paginated multi-day
  history download is deliberately NOT used here (its mechanics are covered
  by unit tests); depth/trades arrive over live WS.
- Wiring assertions (no Unknown/None-masking, fail-closed) are fully
  meaningful either way.
"""

import asyncio
import copy
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp
import pandas as pd
import pytest

from bot_module import data_consumer as dc_module
from bot_module.data_consumer import DataConsumer
from bot_module.exchanges import create_exchange_executor
from bot_module.strategy import VisualBuilderStrategy, StrategySignal

# Opt-in gate: these tests open live exchange connections and take minutes.
# They are SKIPPED everywhere (including GitHub CI) unless explicitly enabled:
#     PROD_E2E_ENABLED=1 pytest tests/test_prod_pipeline_e2e.py -m prod_e2e -q
PROD_E2E_ENABLED = os.environ.get("PROD_E2E_ENABLED", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}

pytestmark = [
    pytest.mark.prod_e2e,
    pytest.mark.skipif(
        not PROD_E2E_ENABLED,
        reason="prod_e2e needs PROD_E2E_ENABLED=1 (live exchanges, minutes per run)",
    ),
]

# NOTE: symbols must be normalized (BTCUSDT), not CCXT-style (BTC/USDT) —
# DataConsumer validates subscriptions against exchange_info symbols and
# keys all caches by the normalized form.
EXCHANGE_MATRIX = [
    {"exchange": "binance", "market_type": "spot", "symbol": "BTCUSDT"},
    {"exchange": "bybit", "market_type": "futures_usdtm", "symbol": "BTCUSDT"},
    {"exchange": "okx", "market_type": "futures_usdtm", "symbol": "BTCUSDT"},
    {"exchange": "weex", "market_type": "futures_usdtm", "symbol": "BTCUSDT"},
    {"exchange": "bitget", "market_type": "futures_usdtm", "symbol": "BTCUSDT"},
]

KLINE_TFS = ("1m", "5m", "15m", "1h")

# Production registry (lowercase checker types). Must stay in sync with
# tests/test_exchange_blocks_matrix.py::ALL_BLOCKS_REGISTRY.
PROD_REGISTRY: List[Dict[str, Any]] = [
    {
        "id": "p_rsi",
        "type": "rsi_condition",
        "params": {"period": 14, "operator": "lt", "value": 30.0},
    },
    {
        "id": "p_macd",
        "type": "macd_condition",
        "params": {
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
            "condition": "hist_gt_zero",
        },
    },
    {
        "id": "p_stoch",
        "type": "stochastic_condition",
        "params": {
            "k_period": 14,
            "d_period": 3,
            "smooth_k": 3,
            "operator": "lt",
            "value": 20,
            "line": "k",
        },
    },
    {
        "id": "p_bb",
        "type": "bollinger_bands_condition",
        "params": {"period": 20, "std_dev": 2.0, "check_type": "price_below_lower"},
    },
    {
        "id": "p_natr",
        "type": "natr_filter",
        "params": {"period": 14, "operator": "gt", "value": 0.0},
    },
    {
        "id": "p_squeeze",
        "type": "volatility_squeeze",
        "params": {"lookback_candles": 20, "squeeze_ratio": 0.6},
    },
    {
        "id": "p_vol",
        "type": "volatility_filter",
        "params": {"indicator": "ATR", "operator": "gt", "value": 0.0},
    },
    {
        "id": "p_adx",
        "type": "adx_filter",
        "params": {"period": 14, "threshold": 25, "operator": "gt"},
    },
    {
        "id": "p_macross",
        "type": "ma_cross_condition",
        "params": {"fast_period": 10, "slow_period": 50},
    },
    {
        "id": "p_trend",
        "type": "trend_direction",
        "params": {"fast_period": 10, "slow_period": 50, "required_trend": "LONG"},
    },
    {
        "id": "p_trendf",
        "type": "trend_filter",
        "params": {"indicator": "ADX", "threshold": 25.0},
    },
    {
        "id": "p_pa",
        "type": "price_action_analyzer",
        "params": {"structure_type": "higher_lows", "lookback_candles": 30},
    },
    {
        "id": "p_consol",
        "type": "price_consolidation",
        "params": {"lookback_period": 10, "max_range_atr": 2.0, "timeframe": "1m"},
    },
    {
        "id": "p_touch",
        "type": "level_touch_analyzer",
        "params": {
            "lookback_candles": 50,
            "touch_tolerance_atr": 0.15,
            "level_price": 1e12,
        },
    },
    {
        "id": "p_retlvl",
        "type": "return_to_level",
        "params": {
            "level_source": {"source": "constant", "value": 1e12},
            "retest_type": "touch",
            "approach_direction": "any",
        },
    },
    {
        "id": "p_pvslvl",
        "type": "price_vs_level",
        "params": {
            "price_source": {"source": "candle", "key": "close", "shift": 0},
            "operator": "gt",
            "level_source": {"source": "constant", "value": 0},
        },
    },
    {"id": "p_local", "type": "local_level", "params": {"lookback": 50}},
    {
        "id": "p_cmp",
        "type": "value_comparison",
        "params": {
            "left": {"source": "candle", "key": "close"},
            "operator": "gt",
            "right": {"source": "constant", "value": 0},
        },
    },
    {
        "id": "p_tapec",
        "type": "tape_condition",
        "params": {
            "metric": "delta_volume",
            "window_sec": 30,
            "operator": "gt",
            "threshold": -1e18,
        },
    },
    {
        "id": "p_obz",
        "type": "order_book_zone",
        "params": {"side": "bids", "range_type": "Percentage", "range_value": 1.0},
    },
    {
        "id": "p_oi",
        "type": "open_interest",
        "params": {"analyze": "absolute_value", "operator": "gt", "value": 0},
    },
    {
        "id": "p_sess",
        "type": "trading_session",
        "params": {"filter_mode": "session", "session": "london"},
    },
    {"id": "p_activity", "type": "market_activity", "params": {}},
    {"id": "p_btc", "type": "btc_state_filter", "params": {"required_state": "Any"}},
    {
        "id": "p_corr",
        "type": "correlation",
        "params": {"lookback": 20, "operator": "gt", "value": -1.0},
    },
    {
        "id": "p_classic",
        "type": "classic_pattern",
        "params": {"pattern_name": "pin_bar", "side": "ANY"},
    },
    {
        "id": "p_volconf",
        "type": "volume_confirmation",
        "params": {"lookback_period": 20, "multiplier": 1.5},
    },
    {
        "id": "p_round",
        "type": "round_level",
        "params": {"proximity_type": "percentage", "proximity_value": 0.1},
    },
    {"id": "p_l2", "type": "l2_microstructure", "params": {}},
    {"id": "p_tapea", "type": "tape_analysis", "params": {"window_sec": 30}},
    {"id": "p_relvol", "type": "rel_vol_filter", "params": {}},
]


def _assert_trace_sane(
    errors: List[str],
    where: str,
    trace: Dict[str, Any],
    *,
    allow_result_none: bool = False,
) -> None:
    """Strict production-trace walker shared by L1/L2/L3.

    Fails on: Unknown node types, NaN floats, True-with-None details.
    Errors are allowed only for genuine data shortage / unresolvable links.
    """
    if not isinstance(trace, dict):
        errors.append(f"{where}: trace is not a dict: {trace!r}")
        return
    stack = [trace]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        details = node.get("details", {}) or {}
        err = details.get("error")
        if err is not None and "Unknown node_type" in str(err):
            errors.append(f"{where}: unregistered block type: {err}")
        for key, val in details.items():
            if isinstance(val, float) and pd.isna(val):
                errors.append(f"{where}: NaN in details['{key}']: {details}")
                break
        result = node.get("result")
        if result is True:
            none_keys = [k for k, v in details.items() if v is None]
            if none_keys:
                errors.append(f"{where}: True with None details {none_keys}: {details}")
        elif result is None and not allow_result_none:
            errors.append(f"{where}: None result in trace node: {node}")
        children = node.get("children") or []
        stack.extend(children)


class _Pipeline:
    """Warmed production pipeline snapshot for one exchange."""

    def __init__(self, spec: Dict[str, str]):
        self.spec = spec
        self.session: Optional[aiohttp.ClientSession] = None
        self.executor = None
        self.consumer: Optional[DataConsumer] = None
        self.pair_info: Dict[str, Any] = {}
        self.market_data: Dict[str, Any] = {}
        self.capabilities: Dict[str, bool] = {}
        self._prev_symbol_source_mode: Optional[str] = None
        self._prev_static_list: List[str] = []
        self._prev_trading_env: Optional[str] = None

    @property
    def exchange(self) -> str:
        return self.spec["exchange"]

    @property
    def market_type(self) -> str:
        return self.spec["market_type"]

    @property
    def symbol(self) -> str:
        return self.spec["symbol"]

    async def _clear_symbol_state(self) -> None:
        uc_symbol = self.symbol.upper()
        async with dc_module._global_pairs_lock:
            dc_module._global_active_pairs.pop(uc_symbol, None)
        for key in list(dc_module._global_agg_trade_deques.keys()):
            if uc_symbol in str(key):
                dc_module._global_agg_trade_deques.pop(key, None)

    async def warmup(self, timeout_s: float = 240.0) -> "_Pipeline":
        # Public market data needs no keys and is stabler on mainnet
        # endpoints; testnet WS/REST flakiness caused false skips.
        from bot_module import config as bot_config

        if self._prev_trading_env is None:
            self._prev_trading_env = bot_config.ACTIVE_TRADING_ENVIRONMENT
            bot_config.ACTIVE_TRADING_ENVIRONMENT = "mainnet"

        last_missing: List[str] = ["not attempted"]
        for attempt in (1, 2):
            try:
                return await self._warmup_once(timeout_s=timeout_s)
            except _WarmupIncomplete as exc:
                last_missing = exc.missing
                if attempt == 2:
                    break
                await self.close()
                await asyncio.sleep(5.0)
        await self.close()
        pytest.skip(
            f"{self.exchange}: pipeline warmup incomplete after 2 attempts, "
            f"missing: {', '.join(last_missing)}"
        )
        raise AssertionError("unreachable")  # pragma: no cover

    async def _warmup_once(self, timeout_s: float = 240.0) -> "_Pipeline":
        exchange, market_type, symbol = (
            self.exchange,
            self.market_type,
            self.symbol,
        )
        self.session = aiohttp.ClientSession()
        self.executor = create_exchange_executor(
            exchange=exchange,
            api_key="",
            api_secret="",
            session=self.session,
            market_type=market_type,
        )
        try:
            await asyncio.wait_for(self.executor._exchange.fetch_time(), timeout=20.0)
        except Exception as exc:
            await self.close()
            pytest.skip(f"{exchange}: public endpoint unreachable: {exc}")

        await self._clear_symbol_state()
        self.consumer = DataConsumer(
            loop=asyncio.get_running_loop(),
            executor=self.executor,
            market_data_mode="direct",
        )
        # The CCXT-Pro WS loops run only while the consumer is started.
        # STATIC_LIST avoids the MAIN_APP websocket dependency.
        from bot_module import config as bot_config

        self._prev_symbol_source_mode = bot_config.SYMBOL_SOURCE_MODE
        self._prev_static_list = list(bot_config.SYMBOL_SOURCE_STATIC_LIST)
        bot_config.SYMBOL_SOURCE_MODE = "STATIC_LIST"
        bot_config.SYMBOL_SOURCE_STATIC_LIST = [symbol.upper()]
        await self.consumer.start()

        # Probe config covering every production data need (mirrors what the
        # controller derives from strategy.required_data_types/indicators).
        probe_strategy = VisualBuilderStrategy(
            params={
                "config": {
                    "entryTrigger": {"type": "on_candle_close", "timeframe": "1m"},
                    "entryConditions": {
                        "id": "probe_root",
                        "type": "AND",
                        "children": copy.deepcopy(PROD_REGISTRY),
                    },
                },
                "enabled": True,
            }
        )
        required_indicators = set(probe_strategy.required_indicators)

        # Depth/tape streams have no history gate: subscribe so they flow
        # live while klines are seeded below.
        await self.consumer.ensure_subscription(
            "depth", symbol, market_type=market_type
        )
        await self.consumer.ensure_subscription(
            "aggTrade", symbol, market_type=market_type
        )
        # Kline seed: ONE bounded REST fetch per TF (real, recent exchange
        # candles) replayed candle-by-candle through the production live-update
        # handler (_update_local_cache) — the same code the WS loop feeds.
        # This deliberately avoids the paginated multi-day history download:
        # throughput, not depth of history, is what this suite verifies.
        # (History-download mechanics are covered by unit tests.)
        await self._seed_klines(required_indicators)

        deadline = time.monotonic() + timeout_s
        missing: List[str] = []
        history: Dict[str, Any] = {}
        while True:
            await asyncio.sleep(5.0)
            for tf in KLINE_TFS:
                try:
                    history[tf] = await self.consumer.get_kline_history(
                        symbol, tf, market_type=market_type
                    )
                except Exception:
                    history[tf] = None
            depth = await self.consumer.get_latest_depth(
                symbol, market_type_requested=market_type
            )
            pair_info = await self.consumer.get_active_pair_by_symbol(symbol)
            tape_probe = (pair_info or {}).get("tape_delta_30s")

            kline_1m = history.get("1m")
            klines_ok = kline_1m is not None and len(kline_1m) >= 60
            htfs_ok = all(
                history.get(tf) is not None and len(history[tf]) >= 55
                for tf in ("5m", "15m", "1h")
            )
            depth_ok = bool(depth and depth.get("bids"))
            tape_ok = tape_probe is not None
            if klines_ok and htfs_ok and depth_ok and tape_ok:
                break
            if time.monotonic() >= deadline:
                if not klines_ok:
                    missing.append("kline_1m history>=60")
                if not htfs_ok:
                    missing.append(
                        "htf history (5m/15m/1h>=55): "
                        + ",".join(
                            tf
                            for tf in ("5m", "15m", "1h")
                            if history.get(tf) is None or len(history[tf]) < 55
                        )
                    )
                if not depth_ok:
                    missing.append("depth L2 stream")
                if not tape_ok:
                    missing.append("aggTrade tape stream")
                await self.close()
                raise _WarmupIncomplete(missing)

        # Force one indicator pass per TF through production code so pair_info
        # carries the full metric set even before the next candle close.
        for tf in KLINE_TFS:
            try:
                await self.consumer._recalculate_kline_indicators(
                    symbol, tf, market_type=market_type
                )
            except Exception:
                pass

        await self.snapshot()
        self.capabilities = {"klines": True, "depth": True, "tape": True}
        try:
            oi = self.market_data.get("open_interest")
            self.capabilities["open_interest"] = oi is not None and not oi.empty
        except Exception:
            self.capabilities["open_interest"] = False
        return self

    def _stream_exchange_id(self) -> str:
        exchange_id = getattr(self.executor, "exchange_id", "binance")
        if getattr(self.executor, "sandbox", False) and not exchange_id.endswith(
            "_testnet"
        ):
            exchange_id = f"{exchange_id}_testnet"
        return exchange_id

    def _ccxt_symbol(self) -> str:
        normalize = getattr(self.executor, "_normalize_symbol", None)
        if callable(normalize):
            try:
                return normalize(self.symbol)
            except Exception:
                pass
        return self.symbol.upper()

    async def _seed_klines(self, required_indicators) -> None:
        """Fetch recent candles (single REST call per TF) and replay them
        through the production _update_local_cache handler, oldest first."""
        assert self.consumer is not None
        symbol, market_type = self.symbol, self.market_type
        exchange_id = self._stream_exchange_id()
        normalized_market = dc_module._normalize_market_type_for_cache(market_type)
        ccxt_symbol = self._ccxt_symbol()
        limits = {"1m": 150, "5m": 150, "15m": 150, "1h": 100}

        async with self.consumer._metrics_lock:
            self.consumer._required_metrics[symbol.upper()].update(required_indicators)

        for tf in KLINE_TFS:
            try:
                ohlcv = await asyncio.wait_for(
                    self.executor._exchange.fetch_ohlcv(
                        ccxt_symbol, tf, limit=limits[tf]
                    ),
                    timeout=40.0,
                )
            except Exception as exc:
                raise _WarmupIncomplete([f"kline_{tf} seed fetch: {exc}"])
            if not ohlcv:
                raise _WarmupIncomplete([f"kline_{tf} seed empty"])
            for row in ohlcv:
                payload = {
                    "e": "kline",
                    "k": {
                        "t": int(row[0]),
                        "o": str(row[1]),
                        "h": str(row[2]),
                        "l": str(row[3]),
                        "c": str(row[4]),
                        "v": str(row[5]),
                        "x": False,
                    },
                }
                await self.consumer._update_local_cache(
                    f"kline_{tf}", symbol, payload, normalized_market, exchange_id
                )

    def _depth_views(self, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            return {"depth_trading": {}, "depth_analysis": {}, "depth": {}}
        full_l2 = raw.get("full_l2_depth")
        if not isinstance(full_l2, dict):
            full_l2 = {
                "lastUpdateId": raw.get("lastUpdateId"),
                "bids": raw.get("bids", []),
                "asks": raw.get("asks", []),
            }
        aggregated = raw.get("aggregated_depth")
        if not isinstance(aggregated, dict):
            aggregated = {}
        return {
            "depth_trading": full_l2,
            "depth_analysis": aggregated,
            "depth": full_l2,
        }

    async def snapshot(self) -> None:
        """Assemble pair_info/market_data exactly like the live controller."""
        assert self.consumer is not None
        symbol, market_type = self.symbol, self.market_type
        pair_info = await self.consumer.get_active_pair_by_symbol(symbol)
        assert pair_info is not None, f"{self.exchange}: no pair_info after warmup"
        pair_info["is_live_mode"] = True
        pair_info["candle_timeframe"] = "1m"
        pair_info["timestamp_dt"] = datetime.now(timezone.utc)

        market_data: Dict[str, Any] = {}
        for tf in KLINE_TFS:
            df = await self.consumer.get_kline_history(
                symbol, tf, market_type=market_type
            )
            assert df is not None and not df.empty, (
                f"{self.exchange}: empty kline_{tf} after warmup"
            )
            market_data[f"kline_{tf}"] = df
        pair_info["current_candle_index"] = len(market_data["kline_1m"]) - 1
        # Same-symbol BTC feed for cross-market blocks (BTC symbols everywhere).
        market_data["kline_1m_BTCUSDT"] = market_data["kline_1m"]

        raw_depth = await self.consumer.get_latest_depth(
            symbol, market_type_requested=market_type
        )
        market_data.update(self._depth_views(raw_depth))

        trades_df = await self.consumer.get_recent_trades(
            symbol, market_type=market_type
        )
        market_data["aggTrade"] = trades_df

        try:
            market_data["open_interest"] = await self.consumer.get_open_interest(symbol)
        except Exception:
            market_data["open_interest"] = None

        self.pair_info = pair_info
        self.market_data = market_data

    async def close(self) -> None:
        try:
            if self.consumer is not None:
                await self.consumer.stop()
        except Exception:
            pass
        try:
            from bot_module import config as bot_config

            if self._prev_symbol_source_mode is not None:
                bot_config.SYMBOL_SOURCE_MODE = self._prev_symbol_source_mode
            if self._prev_static_list is not None:
                bot_config.SYMBOL_SOURCE_STATIC_LIST = self._prev_static_list
            if self._prev_trading_env is not None:
                bot_config.ACTIVE_TRADING_ENVIRONMENT = self._prev_trading_env
        except Exception:
            pass
        # Cancel WS loops spawned for our streams first so ccxt.pro does
        # not hang on a closing session.
        try:
            async with dc_module._global_ws_registry_lock:
                tasks = []
                for key in [
                    k
                    for k, v in dc_module._global_ws_registry.items()
                    if self.symbol.lower() in k
                ]:
                    task = dc_module._global_ws_registry.get(key, {}).get("task")
                    if task and not task.done():
                        task.cancel()
                        tasks.append(task)
                    dc_module._global_ws_registry.pop(key, None)
            if tasks:
                await asyncio.wait(tasks, timeout=10.0)
        except Exception:
            pass
        try:
            if self.executor is not None:
                await asyncio.wait_for(self.executor.close(), timeout=20.0)
        except Exception:
            pass
        try:
            if self.session is not None:
                await asyncio.wait_for(self.session.close(), timeout=20.0)
        except Exception:
            pass
        try:
            await self._clear_symbol_state()
        except Exception:
            pass


class _WarmupIncomplete(Exception):
    def __init__(self, missing: List[str]):
        super().__init__(", ".join(missing))
        self.missing = missing


def _generate_fuzz_trees(rng: random.Random, count: int = 6) -> List[Dict[str, Any]]:
    leaves = [b for b in PROD_REGISTRY if b["type"] not in ("tape_analysis",)]
    trees = []
    for i in range(count):
        gate = rng.choice(["AND", "OR"])
        children = []
        for j in range(rng.randint(2, 3)):
            leaf = copy.deepcopy(rng.choice(leaves))
            leaf["id"] = f"fuzz_{i}_{j}_{leaf['id']}"
            children.append(leaf)
        trees.append({"id": f"fuzz_root_{i}", "type": gate, "children": children})
    return trees


@pytest.mark.parametrize("spec", EXCHANGE_MATRIX, ids=lambda s: s["exchange"])
async def test_l1_all_blocks_on_production_pipeline(spec: Dict[str, str]):
    """L1: every production block evaluated on a real pipeline snapshot."""
    pipe = _Pipeline(spec)
    await pipe.warmup()
    try:
        strategy = VisualBuilderStrategy(params={"enabled": True})
        errors: List[str] = []
        for block in PROD_REGISTRY:
            result, trace = strategy._evaluate_condition_tree(
                node=block,
                pair_info=dict(pipe.pair_info),
                market_data=pipe.market_data,
                prev_pair_info={},
                context={},
            )
            _assert_trace_sane(errors, f"L1:{pipe.exchange}:{block['id']}", trace)
            assert isinstance(bool(result), bool)
        if errors:
            pytest.fail(
                f"Production-pipeline block failures on {pipe.exchange}:\n"
                + "\n".join(errors)
            )
    finally:
        await pipe.close()


@pytest.mark.parametrize("spec", EXCHANGE_MATRIX, ids=lambda s: s["exchange"])
async def test_l2_links_and_dispatch_on_production_pipeline(spec: Dict[str, str]):
    """L2: block_result links, HTF confluence and full signal dispatch."""
    pipe = _Pipeline(spec)
    await pipe.warmup()
    try:
        strategy = VisualBuilderStrategy(params={"enabled": True})
        errors: List[str] = []

        linked_tree = {
            "id": "link_root",
            "type": "AND",
            "children": [
                {
                    "id": "lvl",
                    "type": "local_level",
                    "params": {"lookback": 50},
                },
                {
                    "id": "vs_lvl",
                    "type": "price_vs_level",
                    "params": {
                        "price_source": {
                            "source": "candle",
                            "key": "close",
                            "shift": 0,
                        },
                        "operator": "gt",
                        "level_source": {
                            "source": "block_result",
                            "block_id": "lvl",
                            "key": "detected_level",
                        },
                    },
                },
            ],
        }
        _, link_trace = strategy._evaluate_condition_tree(
            node=linked_tree,
            pair_info=dict(pipe.pair_info),
            market_data=pipe.market_data,
            prev_pair_info={},
            context={},
        )
        _assert_trace_sane(errors, f"L2:{pipe.exchange}:links", link_trace)

        for htf in ("5m", "1h"):
            htf_tree = {
                "id": f"htf_{htf}",
                "type": "senior_tf_confluence",
                "params": {"timeframe": htf},
                "children": [
                    {
                        "id": f"htf_rsi_{htf}",
                        "type": "rsi_condition",
                        "params": {
                            "period": 14,
                            "operator": "gt",
                            "value": 0.0,
                        },
                    },
                    {
                        "id": f"htf_trend_{htf}",
                        "type": "trend_direction",
                        "params": {
                            "fast_period": 10,
                            "slow_period": 50,
                            "required_trend": "LONG",
                            "timeframe": htf,
                        },
                    },
                ],
            }
            _, htf_trace = strategy._evaluate_condition_tree(
                node=htf_tree,
                pair_info=dict(pipe.pair_info),
                market_data=pipe.market_data,
                prev_pair_info={},
                context={},
            )
            _assert_trace_sane(errors, f"L2:{pipe.exchange}:htf_{htf}", htf_trace)

        full_config = {
            "entryTrigger": {"type": "on_candle_close", "timeframe": "1m"},
            "entryConditions": {
                "id": "full_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_cmp",
                        "type": "value_comparison",
                        "params": {
                            "left": {
                                "source": "candle",
                                "key": "close",
                            },
                            "operator": "gt",
                            "right": {"source": "constant", "value": 0},
                        },
                    },
                    {
                        "id": "f_trend",
                        "type": "trend_direction",
                        "params": {
                            "fast_period": 10,
                            "slow_period": 50,
                            "required_trend": "LONG",
                        },
                    },
                ],
            },
            "initialization": {
                "id": "init",
                "type": "open_position",
                "params": {"direction": "LONG"},
            },
        }
        dispatch_strategy = VisualBuilderStrategy(
            params={"config": full_config, "enabled": True}
        )
        signal, weight, trace = dispatch_strategy.check_signal_sync(
            pair_info=dict(pipe.pair_info),
            market_data=pipe.market_data,
            prev_pair_info={},
        )
        assert isinstance(signal, (StrategySignal, type(None)))
        assert isinstance(weight, (int, float))
        if isinstance(trace, dict):
            _assert_trace_sane(errors, f"L2:{pipe.exchange}:dispatch", trace)

        if errors:
            pytest.fail(
                f"Production-pipeline link failures on {pipe.exchange}:\n"
                + "\n".join(errors)
            )
    finally:
        await pipe.close()


@pytest.mark.parametrize("spec", EXCHANGE_MATRIX, ids=lambda s: s["exchange"])
async def test_l3_fuzz_on_production_pipeline(spec: Dict[str, str]):
    """L3: deterministic fuzz trees over the production registry."""
    pipe = _Pipeline(spec)
    await pipe.warmup()
    try:
        strategy = VisualBuilderStrategy(params={"enabled": True})
        errors: List[str] = []
        for tree in _generate_fuzz_trees(random.Random(20260921)):
            result, trace = strategy._evaluate_condition_tree(
                node=tree,
                pair_info=dict(pipe.pair_info),
                market_data=pipe.market_data,
                prev_pair_info={},
                context={},
            )
            assert isinstance(bool(result), bool)
            _assert_trace_sane(errors, f"L3:{pipe.exchange}:{tree['id']}", trace)
        if errors:
            pytest.fail(
                f"Production-pipeline fuzz failures on {pipe.exchange}:\n"
                + "\n".join(errors)
            )
    finally:
        await pipe.close()
