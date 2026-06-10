# bot_module/fast_vector_backtester.py

import logging
import json
import math
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import pandas as pd
import numpy as np

# pandas_ta<=0.3.14b0 still imports numpy.NaN, while numpy>=2 removed the alias.
if not hasattr(np, "NaN"):
    np.NaN = np.nan

import pandas_ta as ta
from typing import Dict, Any, Optional, List, Set

from bot_module import config
from .strategy_risk import resolve_strategy_risk_override

from .condition_core import (
    normalize_condition_type,
    evaluate_time_filter_vectorized,
    evaluate_trend_filter_vectorized,
    evaluate_volatility_filter_vectorized,
    evaluate_adx_filter_vectorized,
    evaluate_ma_cross_vectorized,
    evaluate_bollinger_vectorized,
    evaluate_stochastic_vectorized,
    evaluate_rsi_vectorized,
    evaluate_macd_vectorized,
    evaluate_trend_direction_vectorized,
    evaluate_tape_condition_vectorized,
)
from .strategy import _generate_round_levels
from .utils import (
    add_relative_volume,
    add_volume_percentile_rank,
    calculate_scalper_natr,
    round_price_by_tick,
)

logger = logging.getLogger("bot_module.fast_vector_backtester")


class FastVectorBacktester:
    SUPPORTED_CONDITION_TYPES: Set[str] = {
        "trading_session",
        "time_filter",
        "trend_filter",
        "volatility_filter",
        "natr_filter",
        "adx_filter",
        "ma_cross_condition",
        "bollinger_bands_condition",
        "stochastic_condition",
        "rsi_condition",
        "macd_condition",
        "trend_direction",
        "tape_condition",
        "value_comparison",
        "price_vs_level",
        "volume_confirmation",
        "rel_vol_filter",
        "market_activity",
        "price_consolidation",
        "significant_level",
        "local_level",
        "round_level",
        "classic_pattern",
        "btc_state_filter",
        "open_interest",
        "correlation",
        "level_touch_analyzer",
        "volatility_squeeze",
        "price_action_analyzer",
        "return_to_level",
    }
    SUPPORTED_CONTAINERS: Set[str] = {"AND", "OR"}
    SUPPORTED_PM_BLOCK_TYPES: Set[str] = {
        "dca_management",
        "grid_management",
        "move_to_breakeven",
        "scale_in",
        "conditional_management",
    }
    SUPPORTED_PM_ACTION_TYPES: Set[str] = {
        "modify_stop_loss",
        "modify_take_profit",
        "close_position",
    }
    SUPPORTED_VALUE_SOURCES: Set[str] = {
        "value",
        "constant",
        "candle",
        "indicator",
        "block_result",
    }
    UNSUPPORTED_DYNAMIC_SOURCES: Set[str] = {"block_result", "position_state"}

    @staticmethod
    def _normalize_btc_state_value(raw_state: Any) -> str:
        if not isinstance(raw_state, str):
            return "Any"

        normalized = raw_state.strip()
        if not normalized:
            return "Any"

        canonical_map = {
            "consolidation": "Consolidation",
            "trending_up": "Trending Up",
            "trending_down": "Trending Down",
            "any": "Any",
        }
        normalized_key = normalized.lower().replace("-", "_").replace(" ", "_")
        return canonical_map.get(normalized_key, normalized)

    @staticmethod
    def _extract_numeric_param(raw_value: Any, default: float) -> float:
        if isinstance(raw_value, dict):
            source = raw_value.get("source")
            if source in {"value", "constant"}:
                raw_value = raw_value.get("value", raw_value.get("key", default))
            else:
                return float(default)
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _normalize_ma_cross_direction(params: Dict[str, Any]) -> str:
        raw_direction = (
            params.get("direction") or params.get("operator") or "crosses_above"
        )
        normalized = str(raw_direction).strip().lower()
        if normalized in {"below", "cross_below", "crosses_below"}:
            return "crosses_below"
        return "crosses_above"

    @staticmethod
    def _normalize_bollinger_check_type(params: Dict[str, Any]) -> str:
        raw_value = (
            params.get("check_type") or params.get("location") or "price_below_lower"
        )
        normalized = str(raw_value).strip().lower()
        alias_map = {
            "below_lower": "price_below_lower",
            "above_upper": "price_above_upper",
        }
        return alias_map.get(normalized, normalized)

    @classmethod
    def _normalize_stochastic_params(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(params or {})
        smooth_value = (
            normalized.get("smooth_k")
            if normalized.get("smooth_k") is not None
            else normalized.get("smoothing", normalized.get("slowing", 3))
        )
        normalized["smooth_k"] = int(cls._extract_numeric_param(smooth_value, 3.0))

        raw_condition = normalized.get("operator")
        if not raw_condition:
            raw_condition = normalized.get("condition", "gt")
        normalized_condition = str(raw_condition).strip().lower()
        normalized["operator"] = {
            "k_cross_above_d": "cross_above",
            "k_cross_below_d": "cross_below",
            "k_above_level": "gt",
            "k_below_level": "lt",
        }.get(normalized_condition, normalized_condition)

        if normalized.get("value") is None and normalized.get("level") is not None:
            normalized["value"] = normalized.get("level")
        normalized.setdefault("line", "k")
        return normalized

    @classmethod
    def _iter_nodes(cls, node: Any):
        if not isinstance(node, dict):
            return
        yield node
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                yield from cls._iter_nodes(child)

    @classmethod
    def _collect_dynamic_source_issues(
        cls,
        value: Any,
        bucket: List[Dict[str, Any]],
        path: str,
        *,
        allow_block_result: bool = False,
        allow_position_state: bool = False,
    ) -> None:
        if isinstance(value, dict):
            source = value.get("source")
            source_allowed = (allow_block_result and source == "block_result") or (
                allow_position_state and source == "position_state"
            )
            if source in cls.UNSUPPORTED_DYNAMIC_SOURCES and not source_allowed:
                bucket.append({"path": path, "source": source})
            for key, nested in value.items():
                cls._collect_dynamic_source_issues(
                    nested,
                    bucket,
                    f"{path}.{key}",
                    allow_block_result=allow_block_result,
                    allow_position_state=allow_position_state,
                )
        elif isinstance(value, list):
            for idx, nested in enumerate(value):
                cls._collect_dynamic_source_issues(
                    nested,
                    bucket,
                    f"{path}[{idx}]",
                    allow_block_result=allow_block_result,
                    allow_position_state=allow_position_state,
                )

    @classmethod
    def _collect_indicator_timeframes(
        cls, node: Any, indicator_timeframes: Dict[str, Set[str]]
    ) -> None:
        if not isinstance(node, dict):
            return

        params = node.get("params", {})
        timeframe = str(params.get("timeframe", "1m"))
        node_type = normalize_condition_type(node.get("type", ""))

        if node_type in {"value_comparison", "price_vs_level"}:
            operand_names = (
                ("price_source", "level_source")
                if node_type == "price_vs_level"
                else ("leftOperand", "rightOperand")
            )
            for operand_name in operand_names:
                operand = params.get(operand_name, {})
                if isinstance(operand, dict) and operand.get("source") == "indicator":
                    key = operand.get("key")
                    if isinstance(key, str) and key:
                        indicator_timeframes.setdefault(key, set()).add(
                            str(operand.get("timeframe", timeframe))
                        )

        indicator_keys: List[str] = []
        if node_type == "trend_filter" and params.get("indicator") == "ADX":
            indicator_keys.append("ADX_14")
        elif node_type == "trend_filter" and "threshold" in params:
            indicator_keys.append(f"SMA_{int(params['threshold'])}")
        elif node_type == "volatility_filter":
            indicator = str(params.get("indicator", "")).upper()
            if indicator == "ATR":
                indicator_keys.append(f"ATR_{int(params.get('period', 14))}")
        elif node_type == "natr_filter":
            indicator_keys.append(f"NATR_{int(params.get('period', 14))}")
        elif node_type == "adx_filter":
            indicator_keys.append(f"ADX_{int(params.get('period', 14))}")
        elif node_type == "rsi_condition":
            indicator_keys.append(f"RSI_{int(params.get('period', 14))}")
        elif node_type == "ma_cross_condition":
            indicator_keys.extend(
                [
                    f"EMA_{int(params.get('fast_period', 9))}",
                    f"EMA_{int(params.get('slow_period', 21))}",
                ]
            )
        elif node_type == "macd_condition":
            fast = int(params.get("fast_period", 12))
            slow = int(params.get("slow_period", 26))
            signal = int(params.get("signal_period", 9))
            fast, slow = min(fast, slow), max(fast, slow)
            indicator_keys.append(f"MACD_{fast}_{slow}_{signal}")
        elif node_type == "trend_direction":
            fast = params.get("sma_fast_period") or params.get("fast_period")
            slow = params.get("sma_slow_period") or params.get("slow_period")
            rsi = params.get("rsi_period", 14)
            if fast:
                indicator_keys.append(f"SMA_{int(fast)}")
            if slow:
                indicator_keys.append(f"SMA_{int(slow)}")
            indicator_keys.append(f"RSI_{int(rsi)}")

        for key in indicator_keys:
            indicator_timeframes.setdefault(key, set()).add(timeframe)

        children = node.get("children") or []
        for child in children:
            cls._collect_indicator_timeframes(child, indicator_timeframes)

    @classmethod
    def analyze_strategy_compatibility(
        cls, strategy_json: Dict[str, Any]
    ) -> Dict[str, Any]:
        strategy = cls.normalize_strategy(strategy_json or {})
        report: Dict[str, Any] = {
            "is_fast_compatible": True,
            "unsupported_conditions": [],
            "unsupported_position_management": [],
            "unsupported_actions": [],
            "unsupported_features": [],
            "warnings": [],
            "required_data": [],
        }

        required_data: Set[str] = set()
        indicator_timeframes: Dict[str, Set[str]] = {}

        def walk_condition_tree(
            node: Any, path: str, *, allow_position_state: bool = False
        ) -> None:
            if not isinstance(node, dict):
                return

            raw_type = node.get("type", "")
            node_type = normalize_condition_type(raw_type)
            params = node.get("params", {})

            if node_type in cls.SUPPORTED_CONTAINERS:
                children = node.get("children") or []
                for idx, child in enumerate(children):
                    walk_condition_tree(
                        child,
                        f"{path}.children[{idx}]",
                        allow_position_state=allow_position_state,
                    )
                return

            if node_type == "position_state" and allow_position_state:
                cls._collect_dynamic_source_issues(
                    params,
                    report["unsupported_features"],
                    f"{path}.params",
                    allow_block_result=True,
                    allow_position_state=True,
                )
                return

            if node_type not in cls.SUPPORTED_CONDITION_TYPES:
                report["unsupported_conditions"].append(
                    {"path": path, "type": raw_type}
                )
                return

            cls._collect_dynamic_source_issues(
                params,
                report["unsupported_features"],
                f"{path}.params",
                allow_block_result=True,
                allow_position_state=allow_position_state,
            )

            if node_type in {"value_comparison", "price_vs_level"}:
                operand_names = (
                    ("price_source", "level_source")
                    if node_type == "price_vs_level"
                    else ("leftOperand", "rightOperand")
                )
                for operand_name in operand_names:
                    operand = params.get(operand_name, {})
                    source = (
                        operand.get("source") if isinstance(operand, dict) else "value"
                    )
                    if source not in cls.SUPPORTED_VALUE_SOURCES and not (
                        allow_position_state and source == "position_state"
                    ):
                        report["unsupported_features"].append(
                            {
                                "path": f"{path}.params.{operand_name}",
                                "source": source,
                            }
                        )
            elif node_type == "tape_condition":
                required_data.add("tape")
            elif node_type in {"btc_state_filter", "correlation"}:
                required_data.add("btc")
            elif node_type == "open_interest":
                required_data.add("open_interest")

        for root_key in ("entryConditions", "filters"):
            if root_key in strategy:
                walk_condition_tree(strategy[root_key], root_key)
                cls._collect_indicator_timeframes(
                    strategy[root_key], indicator_timeframes
                )

        init_params = strategy.get("initialization", {}).get("params", {})
        cls._collect_dynamic_source_issues(
            init_params, report["unsupported_features"], "initialization.params"
        )

        order_type = str(init_params.get("order_type", "MARKET")).upper()
        if order_type not in {"", "MARKET"}:
            report["unsupported_features"].append(
                {"path": "initialization.params.order_type", "value": order_type}
            )

        for block_idx, block in enumerate(strategy.get("positionManagement", [])):
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")
            block_path = f"positionManagement[{block_idx}]"
            if block_type not in cls.SUPPORTED_PM_BLOCK_TYPES:
                report["unsupported_position_management"].append(
                    {"path": block_path, "type": block_type}
                )
                continue

            cls._collect_dynamic_source_issues(
                block.get("params", {}),
                report["unsupported_features"],
                f"{block_path}.params",
            )
            if block_type == "dca_management":
                params = block.get("params", {})
                if (
                    str(params.get("step_type", "percentage")).lower()
                    == "custom_condition"
                ):
                    condition_root = None
                    step_value_condition = params.get("step_value")
                    if isinstance(
                        step_value_condition, dict
                    ) and step_value_condition.get("type"):
                        condition_root = step_value_condition
                    else:
                        condition_root = block.get("params", {}).get(
                            "conditions"
                        ) or block.get("children")

                    if isinstance(condition_root, dict):
                        walk_condition_tree(
                            condition_root, f"{block_path}.custom_condition"
                        )
                    elif isinstance(condition_root, list) and condition_root:
                        walk_condition_tree(
                            {"type": "AND", "children": condition_root},
                            f"{block_path}.custom_condition",
                        )
            elif block_type == "scale_in":
                condition_root = cls._pm_conditions_root(block)
                if condition_root:
                    walk_condition_tree(
                        condition_root,
                        f"{block_path}.conditions",
                        allow_position_state=True,
                    )
            elif block_type == "conditional_management":
                if_conditions = block.get("if_conditions")
                if if_conditions:
                    walk_condition_tree(
                        if_conditions,
                        f"{block_path}.if_conditions",
                        allow_position_state=True,
                    )

            then_actions = block.get("then_actions") or []
            if not isinstance(then_actions, list):
                then_actions = []
            for action_idx, action in enumerate(then_actions):
                if not isinstance(action, dict):
                    report["unsupported_actions"].append(
                        {
                            "path": f"{block_path}.then_actions[{action_idx}]",
                            "type": type(action).__name__,
                        }
                    )
                    continue
                action_type = action.get("type")
                if (
                    block_type == "conditional_management"
                    and action_type in cls.SUPPORTED_PM_ACTION_TYPES
                ):
                    cls._collect_dynamic_source_issues(
                        action.get("params", {}),
                        report["unsupported_features"],
                        f"{block_path}.then_actions[{action_idx}].params",
                        allow_block_result=True,
                        allow_position_state=True,
                    )
                    continue

                report["unsupported_actions"].append(
                    {
                        "path": f"{block_path}.then_actions[{action_idx}]",
                        "type": action_type,
                    }
                )

        conflicting_timeframes = {
            key: sorted(timeframes)
            for key, timeframes in indicator_timeframes.items()
            if len(timeframes) > 1
        }
        if conflicting_timeframes:
            report["unsupported_features"].append(
                {
                    "path": "strategy",
                    "type": "multi_timeframe_indicator_collision",
                    "details": conflicting_timeframes,
                }
            )

        report["required_data"] = sorted(required_data)
        report["is_fast_compatible"] = not any(
            report[bucket]
            for bucket in (
                "unsupported_conditions",
                "unsupported_position_management",
                "unsupported_actions",
                "unsupported_features",
            )
        )
        return report

    @staticmethod
    def normalize_strategy(strategy_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Strategy format unification.

        Handles the following formats:
        1. Direct format: {filters: ..., entryConditions: ...}
        2. config_data wrapper: {config_data: {filters: ..., entryConditions: ...}}
        3. Genetic format: {strategy: {filters: ..., entryConditions: ...}, fitness: ...}
        4. strategy_json wrapper: {strategy_json: {filters: ..., entryConditions: ...}}
        """
        result = strategy_json

        # 1. Unpacking config_data (format of saved strategies)
        if "config_data" in result and isinstance(result["config_data"], dict):
            inner = result["config_data"]
            if "id" not in inner and "id" in result:
                inner["id"] = result["id"]
            if "name" not in inner and "name" in result:
                inner["name"] = result["name"]
            result = inner

        # 2. Unpacking strategy (genetic format with rank, fitness)
        if "strategy" in result and isinstance(result["strategy"], dict):
            inner = result["strategy"]
            # Save rank and fitness if present
            if "rank" in result and "rank" not in inner:
                inner["rank"] = result["rank"]
            if "fitness" in result and "fitness" not in inner:
                inner["fitness"] = result["fitness"]
            result = inner

        # 3. Unpacking strategy_json (alternative API format)
        if "strategy_json" in result and isinstance(result["strategy_json"], dict):
            inner = result["strategy_json"]
            if "id" not in inner and "id" in result:
                inner["id"] = result["id"]
            result = inner

        if "config" in result and isinstance(result["config"], dict):
            inner = result["config"]
            if any(
                key in inner
                for key in (
                    "entryConditions",
                    "filters",
                    "initialization",
                    "positionManagement",
                )
            ):
                if "id" not in inner and "id" in result:
                    inner["id"] = result["id"]
                if "name" not in inner and "name" in result:
                    inner["name"] = result["name"]
                result = inner

        return result

    @staticmethod
    def _strategy_uses_dca_or_grid_management(node: Any) -> bool:
        if isinstance(node, dict):
            if str(node.get("type", "")).lower() in {
                "dca_management",
                "grid_management",
            }:
                return True
            return any(
                FastVectorBacktester._strategy_uses_dca_or_grid_management(value)
                for value in node.values()
            )
        if isinstance(node, list):
            return any(
                FastVectorBacktester._strategy_uses_dca_or_grid_management(item)
                for item in node
            )
        return False

    def __init__(
        self,
        klines_input=None,
        strategy_json: Optional[Dict[str, Any]] = None,
        use_oracle: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        initial_balance: float = 100.0,
        **kwargs,
    ):
        self.initial_balance = initial_balance
        self.config = (
            kwargs.get("_config_override")
            if kwargs.get("_config_override") is not None
            else config
        )
        self.params = (
            kwargs.get("params").copy()
            if isinstance(kwargs.get("params"), dict)
            else {}
        )
        self.foundation_weights: Dict[str, float] = {}
        self.min_total_foundation_weight_threshold = 0.0
        self.max_possible_expensive_weight = 0.0
        self.strategy_name = kwargs.get("strategy_name") or str(
            self.params.get("name") or "FastVectorBacktester"
        )
        self.symbol = kwargs.get("symbol") or str(
            self.params.get("symbol") or "UNKNOWN"
        )
        self.market_type = kwargs.get("market_type", "futures_usdtm")
        self.strategy_defaults = kwargs.get("strategy_defaults") or {}
        self.exchange_info = kwargs.get("exchange_info") or {}
        self.min_trades_required = int(kwargs.get("min_trades_required", 0) or 0)
        self.risk_params = (
            kwargs.get("backtest_risk_params").copy()
            if isinstance(kwargs.get("backtest_risk_params"), dict)
            else (
                kwargs.get("risk_params").copy()
                if isinstance(kwargs.get("risk_params"), dict)
                else {}
            )
        )
        self.execution_config = self._build_execution_config(
            kwargs.get("execution_config")
        )
        self.commission_pct = self.execution_config["commission_pct"]
        self.slippage_pct = self.execution_config["slippage_pct"]
        self.actual_trading_start_dt = self._normalize_datetime_like(
            kwargs.get("actual_trading_start_dt")
        )
        self.trade_start_ts = self.actual_trading_start_dt
        self.base_timeframe = str(
            self.params.get("candle_timeframe")
            or self.params.get("entry_timeframe")
            or "1m"
        )
        """
        Backtester initialization.
        
        Args:
            klines_input: Either pd.DataFrame (old format) or Dict[str, pd.DataFrame] (MTF format)
            strategy_json: Strategy in JSON format
            use_oracle: Use Oracle signals
            start_date: Start date (ISO string or YYYY-MM-DD)
            end_date: End date (ISO string or YYYY-MM-DD)
        """
        # Checking input data format
        if klines_input is None and isinstance(kwargs.get("historical_data"), dict):
            klines_input = self._build_data_context_from_historical_data(
                kwargs["historical_data"]
            )

        if strategy_json is None:
            strategy_json = self._extract_strategy_json(self.params)

        strategy_json = self.normalize_strategy(strategy_json or {})
        self.strategy_json = strategy_json
        self.base_timeframe = self._resolve_main_timeframe(klines_input)

        if isinstance(klines_input, dict):
            # Multi-timeframe format: {'1m': df_1m, '5m': df_5m, ...}
            self.data_context = dict(klines_input)
            if (
                self.base_timeframe in self.data_context
                and "1m" not in self.data_context
            ):
                self.data_context["1m"] = self.data_context[self.base_timeframe]
            if (
                "1m" in self.data_context
                and self.base_timeframe not in self.data_context
            ):
                self.data_context[self.base_timeframe] = self.data_context["1m"]

            # 1m - always the main timeframe
            if "1m" not in self.data_context or self.data_context["1m"].empty:
                raise ValueError(
                    "1m timeframe DataFrame is required and cannot be empty."
                )

            self.main_df = self.data_context["1m"]
            self.is_mtf = True

        elif isinstance(klines_input, pd.DataFrame):
            # Old format: just a DataFrame
            if klines_input.empty:
                raise ValueError("Kline DataFrame cannot be empty.")

            self.main_df = klines_input
            # Create data_context for compatibility
            self.data_context = {"1m": klines_input, self.base_timeframe: klines_input}
            self.is_mtf = False
        else:
            raise ValueError(
                "klines_input must be either DataFrame or Dict[str, DataFrame]"
            )

        # FILTERING AND NORMALIZATION BY DATES

        # 1. Forced timezone normalization (convert everything to naive UTC)
        # This is critical for the correct operation of indicators and reindex within MTF
        try:
            if self.main_df.index.tz is not None:
                self.main_df.index = self.main_df.index.tz_convert(None)

            if self.is_mtf:
                for tf in self.data_context:
                    if self.data_context[tf].index.tz is not None:
                        self.data_context[tf].index = self.data_context[
                            tf
                        ].index.tz_convert(None)
                # Synchronization
                self.data_context["1m"] = self.main_df
                if self.base_timeframe not in self.data_context:
                    self.data_context[self.base_timeframe] = self.main_df

        except Exception as e:
            logger.error(f"Timezone normalization error: {e}")

        # 2. Filtering
        if start_date or end_date:
            try:
                # Filter dates are also made naive
                s_ts = (
                    pd.to_datetime(start_date).replace(tzinfo=None)
                    if start_date
                    else None
                )
                e_ts = (
                    pd.to_datetime(end_date).replace(tzinfo=None) if end_date else None
                )

                # Extending e_ts to the end of the day
                if e_ts and e_ts.hour == 0 and e_ts.minute == 0:
                    e_ts = e_ts + pd.Timedelta(hours=23, minutes=59, seconds=59)

                if s_ts:
                    self.main_df = self.main_df[self.main_df.index >= s_ts]
                if e_ts:
                    self.main_df = self.main_df[self.main_df.index <= e_ts]

                # MTF Update
                if self.is_mtf:
                    for tf in list(self.data_context.keys()):
                        df = self.data_context[tf]
                        if s_ts:
                            df = df[df.index >= s_ts]
                        if e_ts:
                            df = df[df.index <= e_ts]
                        self.data_context[tf] = df
                    self.main_df = self.data_context["1m"]

                if self.main_df.empty:
                    logger.warning(
                        f"Backtester: Data EMPTY after filtering {start_date} - {end_date}"
                    )
                else:
                    logger.info(
                        f"Backtester: Range {self.main_df.index.min()} - {self.main_df.index.max()}. Rows: {len(self.main_df)}"
                    )

            except Exception as e:
                logger.error(f"Error filtering data by date: {e}", exc_info=True)
        # Create a lightweight working context only for signals
        # Copy only the index to preserve the time structure
        self.signals = pd.DataFrame(index=self.main_df.index)

        # Cache for broadcasted series
        self.broadcasted_cache = {}

        self.strategy_json = strategy_json
        self.uses_dca_or_grid_management = self._strategy_uses_dca_or_grid_management(
            self.strategy_json.get(
                "positionManagement", self.strategy_json.get("management", [])
            )
        )
        raw_foundation_weights = (
            kwargs.get("foundation_weights")
            if isinstance(kwargs.get("foundation_weights"), dict)
            else self.params.get(
                "foundation_weights", self.strategy_json.get("foundation_weights", {})
            )
        )
        self.foundation_weights = (
            raw_foundation_weights if isinstance(raw_foundation_weights, dict) else {}
        )
        raw_min_weight_threshold = kwargs.get(
            "min_total_foundation_weight_threshold",
            kwargs.get(
                "min_foundation_weight_threshold",
                self.params.get(
                    "min_total_foundation_weight_threshold",
                    self.params.get(
                        "min_foundation_weight_threshold",
                        self.strategy_json.get(
                            "min_total_foundation_weight_threshold",
                            self.strategy_json.get(
                                "min_foundation_weight_threshold",
                                getattr(
                                    self.config,
                                    "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD",
                                    50.0,
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
        self.min_total_foundation_weight_threshold = self._coerce_float(
            raw_min_weight_threshold,
            float(getattr(self.config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 50.0)),
        )
        entry_conditions_root = self.strategy_json.get("entryConditions")
        if isinstance(entry_conditions_root, dict):
            self.max_possible_expensive_weight = (
                self._get_max_possible_expensive_weight(entry_conditions_root)
            )
        self.compatibility_report = self.analyze_strategy_compatibility(
            self.strategy_json
        )
        self.use_oracle = use_oracle
        self.trade_log: List[Dict[str, Any]] = []
        self.phantom_log: List[Dict[str, Any]] = []  # Phantom trades after BE
        if not hasattr(self, "initial_balance"):
            self.initial_balance = 100.0
        self._reset_runtime_state()

    @staticmethod
    def _normalize_datetime_like(value: Optional[Any]) -> Optional[pd.Timestamp]:
        if value is None:
            return None
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            ts = ts.tz_convert(None)
        return ts

    @staticmethod
    def _coerce_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _build_execution_config(
        self, execution_config: Optional[Dict[str, Any]]
    ) -> Dict[str, float]:
        cfg = execution_config.copy() if isinstance(execution_config, dict) else {}
        return {
            "commission_pct": self._coerce_float(
                cfg.get("commission_pct"),
                float(getattr(self.config, "BACKTEST_COMMISSION_PCT", 0.0012)),
            ),
            "slippage_pct": self._coerce_float(
                cfg.get("slippage_pct"),
                float(getattr(self.config, "BACKTEST_SLIPPAGE_PCT", 0.0006)),
            ),
        }

    @staticmethod
    def _extract_strategy_json(params: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(params, dict):
            return {}
        normalized = FastVectorBacktester.normalize_strategy(params.copy())
        if any(
            key in normalized
            for key in (
                "entryConditions",
                "filters",
                "initialization",
                "positionManagement",
            )
        ):
            return normalized
        return {}

    def _resolve_main_timeframe(self, klines_input: Any) -> str:
        timeframe = str(
            self.params.get("candle_timeframe")
            or self.params.get("entry_timeframe")
            or (
                self.strategy_json.get("entryTrigger", {}).get("timeframe")
                if isinstance(getattr(self, "strategy_json", None), dict)
                and isinstance(self.strategy_json.get("entryTrigger"), dict)
                else None
            )
            or "1m"
        )
        if isinstance(klines_input, dict):
            if timeframe in klines_input:
                return timeframe
            if "1m" in klines_input:
                return "1m"
        return timeframe

    def _build_data_context_from_historical_data(
        self,
        historical_data: Dict[str, Optional[pd.DataFrame]],
    ) -> Dict[str, pd.DataFrame]:
        data_context: Dict[str, pd.DataFrame] = {}
        if not isinstance(historical_data, dict):
            return data_context

        for key, df in historical_data.items():
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue

            if key.startswith("kline_"):
                suffix = key[len("kline_") :]
                if "_" in suffix:
                    timeframe, symbol_hint = suffix.split("_", 1)
                    if symbol_hint.upper().startswith("BTC"):
                        data_context[f"btc_{timeframe}"] = df
                    else:
                        data_context[timeframe] = df
                else:
                    data_context[suffix] = df
            elif key == "open_interest":
                data_context["open_interest"] = df

        if "1m" not in data_context and self.base_timeframe in data_context:
            data_context["1m"] = data_context[self.base_timeframe]
        elif "1m" not in data_context:
            raise ValueError(
                f"Historical data must contain 'kline_{self.base_timeframe}' or 'kline_1m' for FastVectorBacktester."
            )

        if self.base_timeframe not in data_context and "1m" in data_context:
            data_context[self.base_timeframe] = data_context["1m"]

        return data_context

    @staticmethod
    def _to_python_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if hasattr(value, "to_pydatetime"):
            return value.to_pydatetime()
        return pd.Timestamp(value).to_pydatetime()

    def _build_structured_report(self) -> Dict[str, Any]:
        foundation_trigger_counts: Dict[str, int] = {}
        if isinstance(getattr(self, "foundation_weights", None), dict):
            foundation_trigger_counts = {
                str(foundation_id): 0
                for foundation_id in self.foundation_weights.keys()
            }

        return {
            "event_counters": {
                "signals_generated_total": 0,
                "foundation_trigger_counts": foundation_trigger_counts,
                "rejections": {
                    "by_global_risk_limit": 0,
                    "by_cooldown": 0,
                    "by_filter": {},
                    "by_weight_threshold": 0,
                    "by_position_calculation": 0,
                    "by_slippage_beyond_sl": 0,
                    "by_risk_manager": 0,
                    "by_risk_manager_reasons": {},
                },
                "trades_opened": 0,
                "errors": {},
            },
            "anomalies": [],
        }

    def _append_structured_anomaly(
        self, anomaly_type: str, timestamp: Optional[Any], message: str
    ) -> None:
        ts_iso = None
        if timestamp is not None:
            try:
                ts_iso = self._to_python_datetime(timestamp).isoformat()
            except Exception:
                ts_iso = str(timestamp)

        self.structured_report["anomalies"].append(
            {
                "type": anomaly_type,
                "timestamp": ts_iso,
                "message": message,
            }
        )

    def _increment_error_counter(self, error_key: str) -> None:
        errors = self.structured_report["event_counters"]["errors"]
        errors[error_key] = int(errors.get(error_key, 0)) + 1

    def _record_filter_rejections(
        self, rejected_mask: np.ndarray, failed_filter_ids: np.ndarray
    ) -> None:
        if failed_filter_ids.size == 0 or rejected_mask.size == 0:
            return

        by_filter = self.structured_report["event_counters"]["rejections"]["by_filter"]
        for failed_filter_id in failed_filter_ids[rejected_mask]:
            if not failed_filter_id:
                continue
            filter_key = str(failed_filter_id)
            by_filter[filter_key] = int(by_filter.get(filter_key, 0)) + 1

    def _record_position_rejection(self, rejection_reason: Optional[str]) -> None:
        if not rejection_reason:
            return

        rejections = self.structured_report["event_counters"]["rejections"]
        if rejection_reason == "GLOBAL_RISK_LIMIT":
            rejections["by_global_risk_limit"] += 1
            return

        if rejection_reason in {
            "INVALID_ENTRY_PRICE",
            "ZERO_STOP_DISTANCE",
            "STOP_DIRECTION_INVALID",
            "NON_POSITIVE_QUANTITY",
        }:
            rejections["by_position_calculation"] += 1
            return

        rejections["by_risk_manager"] += 1
        reasons = rejections["by_risk_manager_reasons"]
        reasons[rejection_reason] = int(reasons.get(rejection_reason, 0)) + 1

    def _reset_runtime_state(self) -> None:
        self.trade_log = []
        self.phantom_log = []
        self.current_balance = float(self.initial_balance)
        self.total_pnl_usd = 0.0
        self.total_commission_usd = 0.0
        self.peak_equity = float(self.initial_balance)
        self.max_drawdown = 0.0
        self.is_trading_allowed = True
        self._is_liquidated = False  # Liquidation is an irreversible state
        self._risk_daily_pnl: Dict[str, float] = {}
        self._risk_last_known_day_str = ""
        self._risk_start_of_day_balance = float(self.initial_balance)
        self._risk_consecutive_losses = 0
        self._risk_max_consecutive_losses = 0
        self._entry_condition_result: Optional[pd.Series] = None
        self._entry_node_results: Dict[str, pd.Series] = {}
        self._filter_condition_result: Optional[pd.Series] = None
        self._filter_node_results: Dict[str, pd.Series] = {}
        self._dynamic_block_results: Dict[str, Dict[str, pd.Series]] = {}
        self._series_eval_cache: Dict[str, Any] = {}
        self.structured_report = self._build_structured_report()
        start_point = self.trade_start_ts or (
            pd.Timestamp(self.main_df.index[0])
            if not self.main_df.empty
            else pd.Timestamp.utcnow()
        )
        self.equity_curve: List[Any] = [
            (self._to_python_datetime(start_point), float(self.initial_balance))
        ]

    def _evaluate_condition_tree_with_failures(
        self, node: Dict[str, Any]
    ) -> tuple[pd.Series, np.ndarray]:
        default_mask = pd.Series(True, index=self.main_df.index, dtype=bool)
        default_failures = np.full(len(self.main_df.index), None, dtype=object)

        if not isinstance(node, dict):
            return default_mask, default_failures

        node_type = normalize_condition_type(node.get("type"))
        children = node.get("children", [])

        if node_type in {"AND", "OR"}:
            if not children:
                return default_mask, default_failures

            result_mask = pd.Series(
                node_type == "AND", index=self.main_df.index, dtype=bool
            )
            failed_leaf_ids = np.full(len(self.main_df.index), None, dtype=object)

            for child in children:
                child_mask, child_failed_ids = (
                    self._evaluate_condition_tree_with_failures(child)
                )
                child_mask = self._coerce_mask_series(child_mask).fillna(False)

                if node_type == "AND":
                    result_mask = result_mask & child_mask
                else:
                    result_mask = result_mask | child_mask

                first_failure_slots = (~child_mask.to_numpy()) & pd.isna(
                    failed_leaf_ids
                )
                failed_leaf_ids[first_failure_slots] = child_failed_ids[
                    first_failure_slots
                ]

            failed_leaf_ids[result_mask.to_numpy()] = None
            return result_mask, failed_leaf_ids

        leaf_mask = self._coerce_mask_series(
            self._evaluate_condition_tree(node)
        ).fillna(False)
        self._register_block_result(node, leaf_mask)
        failed_leaf_id = str(node.get("id") or node.get("type") or "unknown_filter")
        failed_leaf_ids = np.where(leaf_mask.to_numpy(), None, failed_leaf_id)
        return leaf_mask, failed_leaf_ids

    def _coerce_mask_series(self, mask: Any) -> pd.Series:
        if isinstance(mask, pd.Series):
            return mask.reindex(self.main_df.index, fill_value=False)

        if isinstance(mask, np.ndarray):
            if mask.ndim == 0:
                return pd.Series(
                    bool(mask.item()), index=self.main_df.index, dtype=bool
                )
            if len(mask) != len(self.main_df.index):
                raise ValueError(
                    f"Mask length mismatch: expected {len(self.main_df.index)}, got {len(mask)}"
                )
            return pd.Series(mask, index=self.main_df.index, dtype=bool)

        if isinstance(mask, (bool, np.bool_)):
            return pd.Series(bool(mask), index=self.main_df.index, dtype=bool)

        return pd.Series(mask, index=self.main_df.index, dtype=bool)

    @staticmethod
    def _series_bool_at(
        series: Optional[pd.Series], idx: int, default: bool = False
    ) -> bool:
        if series is None or idx < 0 or idx >= len(series):
            return default
        try:
            value = series.iloc[idx]
        except Exception:
            return default
        if pd.isna(value):
            return default
        return bool(value)

    @staticmethod
    def _normalize_trace_detail_value(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, np.generic):
            return FastVectorBacktester._normalize_trace_detail_value(value.item())
        if isinstance(value, (pd.Timestamp, datetime)):
            return FastVectorBacktester._to_python_datetime(value).isoformat()
        if isinstance(value, Decimal):
            value = float(value)
        if isinstance(value, float):
            return float(value) if math.isfinite(value) else None
        if isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, dict):
            return {
                str(k): FastVectorBacktester._normalize_trace_detail_value(v)
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [
                FastVectorBacktester._normalize_trace_detail_value(v) for v in value
            ]
        return str(value)

    def _trace_series_value_at(self, series: Optional[pd.Series], idx: int) -> Any:
        if series is None or idx < 0 or idx >= len(series):
            return None
        try:
            value = series.iloc[idx]
        except Exception:
            return None
        if pd.isna(value):
            return None
        return self._normalize_trace_detail_value(value)

    def _constant_series(self, value: Any, *, dtype: Optional[str] = None) -> pd.Series:
        return pd.Series(value, index=self.main_df.index, dtype=dtype)

    def _empty_numeric_series(self) -> pd.Series:
        return pd.Series(np.nan, index=self.main_df.index, dtype=float)

    def _coerce_numeric_series(self, series: Any) -> pd.Series:
        if isinstance(series, pd.Series):
            aligned = series.reindex(self.main_df.index)
        else:
            aligned = self._constant_series(series)
        return pd.to_numeric(aligned, errors="coerce").astype(float)

    def _resolve_value_series(self, operand: Any) -> pd.Series:
        if not isinstance(operand, dict) or "source" not in operand:
            return self._constant_series(operand)

        source = operand.get("source")
        key = operand.get("key")
        value = operand.get("value", key)
        shift = int(self._extract_numeric_param(operand.get("shift", 0), 0))

        if source in {"constant", "value"}:
            return self._constant_series(value)

        if source == "candle":
            if not key:
                return self._empty_numeric_series()
            timeframe = str(operand.get("timeframe", self.base_timeframe))
            df_tf = self._get_timeframe_df(timeframe)
            key_str = str(key)
            if key_str not in df_tf.columns:
                return self._empty_numeric_series()
            series = df_tf[key_str].astype(float)
            if shift:
                series = series.shift(shift)
            return self._align_series_to_main_index(series).reindex(self.main_df.index)

        if source == "indicator":
            if not key:
                return self._empty_numeric_series()
            key_str = str(key)
            candidates = [key_str, key_str.upper(), key_str.lower()]
            series = None
            signal_key = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate in self.signals.columns
                ),
                None,
            )
            main_key = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate in self.main_df.columns
                ),
                None,
            )
            if signal_key is not None:
                series = self.signals[signal_key].astype(float)
            elif main_key is not None:
                series = self.main_df[main_key].astype(float)
            else:
                series = next(
                    (
                        cached
                        for cached_key, cached in self.broadcasted_cache.items()
                        if any(
                            cached_key.startswith(f"{candidate}|")
                            for candidate in candidates
                        )
                    ),
                    None,
                )
                if series is not None:
                    series = series.astype(float)
            if series is None:
                return self._empty_numeric_series()
            if shift:
                series = series.shift(shift)
            return series.reindex(self.main_df.index)

        if source == "block_result":
            block_id = operand.get("block_id")
            result_key = key or "result"
            if not block_id:
                return self._empty_numeric_series()
            block_details = self._dynamic_block_results.get(str(block_id), {})
            series = block_details.get(str(result_key))
            if series is None:
                return self._empty_numeric_series()
            if shift:
                series = series.shift(shift)
            return series.reindex(self.main_df.index)

        return self._empty_numeric_series()

    @staticmethod
    def _normalize_comparison_operator(operator: Any) -> str:
        normalized = str(operator or "gt").strip().lower()
        return {
            ">": "gt",
            ">=": "gte",
            "<": "lt",
            "<=": "lte",
            "==": "eq",
            "=": "eq",
            "!=": "ne",
            "crosses_above": "cross_above",
            "crosses_below": "cross_below",
            "above": "gt",
            "below": "lt",
        }.get(normalized, normalized)

    def _compare_value_series(
        self, left: pd.Series, right: pd.Series, operator: Any
    ) -> pd.Series:
        left_num = self._coerce_numeric_series(left)
        right_num = self._coerce_numeric_series(right)
        valid = left_num.notna() & right_num.notna()
        op = self._normalize_comparison_operator(operator)

        if op == "gt":
            result = left_num > right_num
        elif op == "lt":
            result = left_num < right_num
        elif op == "gte":
            result = left_num >= right_num
        elif op == "lte":
            result = left_num <= right_num
        elif op == "eq":
            result = (left_num - right_num).abs() < 1e-9
        elif op == "ne":
            result = (left_num - right_num).abs() >= 1e-9
        elif op == "cross_above":
            result = (left_num > right_num) & (left_num.shift(1) <= right_num.shift(1))
        elif op == "cross_below":
            result = (left_num < right_num) & (left_num.shift(1) >= right_num.shift(1))
        else:
            result = pd.Series(False, index=self.main_df.index, dtype=bool)

        return (result & valid).fillna(False).astype(bool)

    def _evaluate_value_comparison_dynamic(self, params: Dict[str, Any]) -> pd.Series:
        left = self._resolve_value_series(params.get("leftOperand", {}))
        right = self._resolve_value_series(params.get("rightOperand", {}))
        return self._compare_value_series(left, right, params.get("operator", "gt"))

    def _evaluate_price_vs_level(self, params: Dict[str, Any]) -> pd.Series:
        left = self._resolve_value_series(params.get("price_source", {}))
        right = self._resolve_value_series(params.get("level_source", {}))
        return self._compare_value_series(left, right, params.get("operator", "gt"))

    def _register_block_result(
        self, node: Dict[str, Any], result_mask: pd.Series
    ) -> None:
        node_id = node.get("id")
        if node_id is None:
            return

        node_type = normalize_condition_type(node.get("type"))
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        details: Dict[str, pd.Series] = {
            "result": self._coerce_mask_series(result_mask).fillna(False).astype(bool)
        }

        if node_type == "value_comparison":
            details["left_value_resolved"] = self._coerce_numeric_series(
                self._resolve_value_series(params.get("leftOperand", {}))
            )
            details["right_value_resolved"] = self._coerce_numeric_series(
                self._resolve_value_series(params.get("rightOperand", {}))
            )
        elif node_type == "price_vs_level":
            details["left_value_resolved"] = self._coerce_numeric_series(
                self._resolve_value_series(params.get("price_source", {}))
            )
            details["right_value_resolved"] = self._coerce_numeric_series(
                self._resolve_value_series(params.get("level_source", {}))
            )
        elif node_type == "local_level":
            details["detected_level"] = self._resolve_local_level_series(params)
        elif node_type == "significant_level":
            details["detected_level"] = self._resolve_significant_level_series(
                str(params.get("level_type", "daily_high")).strip().lower()
            )
        elif node_type == "level_touch_analyzer":
            _, analyzer_details = self._evaluate_level_touch_analyzer(params)
            details.update(analyzer_details)
        elif node_type == "volatility_squeeze":
            _, squeeze_details = self._evaluate_volatility_squeeze(params)
            details.update(squeeze_details)
        elif node_type == "price_action_analyzer":
            _, pa_details = self._evaluate_price_action_analyzer(params)
            details.update(pa_details)
        elif node_type == "price_consolidation":
            details.update(self._price_consolidation_trace_details(params))

        self._dynamic_block_results[str(node_id)] = {
            str(key): value.reindex(self.main_df.index)
            for key, value in details.items()
            if isinstance(value, pd.Series)
        }

    def _trace_column_value(self, column: Optional[str], idx: int) -> Any:
        if not column:
            return None
        candidates = [str(column), str(column).upper(), str(column).lower()]
        for df in (getattr(self, "signals", None), getattr(self, "main_df", None)):
            if df is None:
                continue
            for candidate in candidates:
                if candidate in df.columns:
                    return self._trace_series_value_at(df[candidate], idx)
        return None

    def _trace_first_column_value(self, candidates: List[str], idx: int) -> Any:
        for candidate in candidates:
            value = self._trace_column_value(candidate, idx)
            if value is not None:
                return value

        for df in (getattr(self, "signals", None), getattr(self, "main_df", None)):
            if df is None:
                continue
            for candidate in candidates:
                candidate_str = str(candidate)
                match = next(
                    (col for col in df.columns if str(col).startswith(candidate_str)),
                    None,
                )
                if match:
                    value = self._trace_series_value_at(df[match], idx)
                    if value is not None:
                        return value
        return None

    def _trace_operand_details(self, operand: Any, idx: int) -> Dict[str, Any]:
        if not isinstance(operand, dict):
            return {
                "source": "value",
                "actual": self._normalize_trace_detail_value(operand),
            }

        source = operand.get("source")
        key = operand.get("key")
        value = operand.get("value", key)
        details: Dict[str, Any] = {
            "source": source,
            "key": key,
        }

        if source == "candle":
            details["actual"] = self._trace_column_value(str(key), idx)
        elif source == "indicator":
            details["actual"] = self._trace_column_value(str(key), idx)
        elif source == "block_result":
            details["block_id"] = operand.get("block_id")
            details["actual"] = self._trace_series_value_at(
                self._resolve_value_series(operand), idx
            )
        elif source in {"constant", "value"}:
            details["actual"] = self._normalize_trace_detail_value(value)
        else:
            details["actual"] = None

        return details

    def _level_touch_trace_events(
        self,
        params: Dict[str, Any],
        idx: int,
        level_value: Any,
        tolerance_value: Any,
    ) -> Dict[str, Any]:
        try:
            level = float(level_value)
            tolerance = float(tolerance_value)
        except (TypeError, ValueError):
            return {}
        if not np.isfinite(level) or not np.isfinite(tolerance) or level <= 0:
            return {}

        lookback = max(
            1, int(self._extract_numeric_param(params.get("lookback_candles", 50), 50))
        )
        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        df_tf = self._get_timeframe_df(timeframe)
        if df_tf.empty or idx < 0 or idx >= len(self.main_df.index):
            return {}

        signal_time = self.main_df.index[idx]
        try:
            end_idx = df_tf.index.get_indexer([signal_time], method="ffill")[0]
        except Exception:
            return {}
        if end_idx < 0:
            return {}

        start_idx = max(0, end_idx - lookback + 1)
        recent = df_tf.iloc[start_idx : end_idx + 1]
        if recent.empty or not {"high", "low"}.issubset(recent.columns):
            return {}

        close_series = (
            recent["close"]
            if "close" in recent.columns
            else (recent["high"] + recent["low"]) / 2
        )
        configured_side = str(params.get("level_side", "auto")).strip().lower()
        if configured_side in {"resistance", "upper"}:
            level_side = "resistance"
        elif configured_side in {"support", "lower"}:
            level_side = "support"
        else:
            level_side = (
                "resistance" if float(close_series.median()) <= level else "support"
            )

        touch_indices: List[int] = []
        pierce_indices: List[int] = []
        touch_times: List[int] = []
        pierce_times: List[int] = []
        for local_idx, (timestamp, row) in enumerate(recent.iterrows()):
            high = float(row["high"])
            low = float(row["low"])
            ts_seconds = (
                int(timestamp.timestamp()) if hasattr(timestamp, "timestamp") else None
            )
            if high >= level - tolerance and low <= level + tolerance:
                touch_indices.append(local_idx)
                if ts_seconds is not None:
                    touch_times.append(ts_seconds)
            if level_side == "resistance" and high > level + tolerance:
                pierce_indices.append(local_idx)
                if ts_seconds is not None:
                    pierce_times.append(ts_seconds)
            elif level_side == "support" and low < level - tolerance:
                pierce_indices.append(local_idx)
                if ts_seconds is not None:
                    pierce_times.append(ts_seconds)

        return {
            "level_side": level_side,
            "lookback_candles": lookback,
            "touch_indices": touch_indices,
            "pierce_indices": pierce_indices,
            "touch_times": touch_times,
            "pierce_times": pierce_times,
        }

    def _price_action_trace_markers(
        self, params: Dict[str, Any], idx: int
    ) -> List[Dict[str, Any]]:
        lookback = max(
            3, int(self._extract_numeric_param(params.get("lookback_candles", 30), 30))
        )
        order = max(1, int(self._extract_numeric_param(params.get("order", 3), 3)))
        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        df_tf = self._get_timeframe_df(timeframe)
        if df_tf.empty or idx < 0 or idx >= len(self.main_df.index):
            return []

        signal_time = self.main_df.index[idx]
        try:
            end_idx = df_tf.index.get_indexer([signal_time], method="ffill")[0]
        except Exception:
            return []
        if end_idx < 0:
            return []

        start_idx = max(0, end_idx - lookback + 1)
        data = df_tf.iloc[start_idx : end_idx + 1].copy()
        if len(data) < order * 2 + 1 or not {"high", "low"}.issubset(data.columns):
            return []

        highs_all = data["high"].astype(float).to_numpy()
        lows_all = data["low"].astype(float).to_numpy()
        found_points: List[Dict[str, Any]] = []

        for local_idx in range(order, len(data) - order):
            high_value = highs_all[local_idx]
            low_value = lows_all[local_idx]
            is_high = all(
                high_value > highs_all[local_idx - j]
                and high_value > highs_all[local_idx + j]
                for j in range(1, order + 1)
            )
            is_low = all(
                low_value < lows_all[local_idx - j]
                and low_value < lows_all[local_idx + j]
                for j in range(1, order + 1)
            )
            ts = data.index[local_idx]
            timestamp = int(ts.timestamp()) if hasattr(ts, "timestamp") else None
            if is_high:
                found_points.append(
                    {
                        "idx": local_idx,
                        "price": float(high_value),
                        "point_type": "H",
                        "time": timestamp,
                    }
                )
            if is_low:
                found_points.append(
                    {
                        "idx": local_idx,
                        "price": float(low_value),
                        "point_type": "L",
                        "time": timestamp,
                    }
                )

        found_points.sort(key=lambda point: point["idx"])
        markers: List[Dict[str, Any]] = []
        last_h = None
        last_l = None
        for point in found_points:
            if point.get("time") is None:
                continue
            label = point["point_type"]
            value = point["price"]
            if point["point_type"] == "H":
                if last_h is not None:
                    label = "HH" if value > last_h else "LH"
                last_h = value
                markers.append(
                    {
                        "time": point["time"],
                        "type": "price_action_analyzer",
                        "position": "aboveBar",
                        "color": "#2196F3"
                        if label == "HH"
                        else ("#ef5350" if label == "LH" else "#888888"),
                        "shape": "arrowDown",
                        "text": label,
                    }
                )
            else:
                if last_l is not None:
                    label = "LL" if value < last_l else "HL"
                last_l = value
                markers.append(
                    {
                        "time": point["time"],
                        "type": "price_action_analyzer",
                        "position": "belowBar",
                        "color": "#4CAF50"
                        if label == "HL"
                        else ("#ef5350" if label == "LL" else "#888888"),
                        "shape": "arrowUp",
                        "text": label,
                    }
                )

        return markers

    def _round_level_trace_details(
        self, params: Dict[str, Any], idx: int
    ) -> Dict[str, Any]:
        if (
            idx < 0
            or idx >= len(self.main_df.index)
            or "close" not in self.main_df.columns
        ):
            return {}

        tick_size = self._get_tick_size()
        if tick_size <= 0:
            return {}

        last_price = self._trace_column_value("close", idx)
        if last_price is None:
            return {}

        try:
            last_price_float = float(last_price)
        except (TypeError, ValueError):
            return {}

        candidate_levels = _generate_round_levels(
            last_price_float,
            tick_size,
            [],
            2,
            None,
            None,
        )
        if not candidate_levels:
            return {}

        closest_level = min(
            candidate_levels, key=lambda level: abs(last_price_float - level)
        )
        return {
            "detected_level": float(closest_level),
            "last_price": last_price_float,
        }

    def _open_interest_trace_details(
        self, params: Dict[str, Any], idx: int
    ) -> Dict[str, Any]:
        oi_df = self.data_context.get("open_interest")
        if isinstance(oi_df, pd.DataFrame):
            if "open_interest" in oi_df.columns:
                oi_series = oi_df["open_interest"]
            elif oi_df.shape[1] >= 1:
                oi_series = oi_df.iloc[:, 0]
            else:
                return {}
        elif isinstance(oi_df, pd.Series):
            oi_series = oi_df
        else:
            return {}

        lookback = max(
            2, int(self._extract_numeric_param(params.get("lookback", 5), 5))
        )
        analyze_type = str(params.get("analyze", "change_pct")).lower()
        aligned = oi_series.reindex(self.main_df.index, method="ffill")
        if idx < 0 or idx >= len(aligned):
            return {}

        latest = self._normalize_trace_detail_value(aligned.iloc[idx])
        if analyze_type == "absolute_value":
            actual = latest
        elif idx - lookback + 1 >= 0:
            initial = self._normalize_trace_detail_value(
                aligned.iloc[idx - lookback + 1]
            )
            actual = ((latest - initial) / initial * 100.0) if initial else None
        else:
            actual = None

        return {
            "oi_actual": actual,
            "open_interest": latest,
            "lookback": lookback,
            "analyze": analyze_type,
            "operator": params.get("operator", "gt"),
            "threshold": self._extract_numeric_param(params.get("value", 1.0), 1.0),
        }

    def _correlation_trace_details(
        self, params: Dict[str, Any], idx: int
    ) -> Dict[str, Any]:
        btc_df = self.data_context.get("btc_1m")
        if (
            not isinstance(btc_df, pd.DataFrame)
            or btc_df.empty
            or "close" not in btc_df.columns
        ):
            return {}
        if (
            idx < 0
            or idx >= len(self.main_df.index)
            or "close" not in self.main_df.columns
        ):
            return {}

        lookback = max(
            2, int(self._extract_numeric_param(params.get("lookback", 50), 50))
        )
        main_close = self.main_df["close"].astype(float)
        btc_close = (
            btc_df["close"].astype(float).reindex(self.main_df.index, method="ffill")
        )
        start = idx - lookback + 1
        if start < 0:
            return {
                "lookback": lookback,
                "operator": params.get("operator", "lt"),
                "threshold": self._extract_numeric_param(params.get("value", 0.7), 0.7),
            }

        correlation = main_close.iloc[start : idx + 1].corr(
            btc_close.iloc[start : idx + 1]
        )
        return {
            "correlation_actual": self._normalize_trace_detail_value(correlation),
            "lookback": lookback,
            "operator": params.get("operator", "lt"),
            "threshold": self._extract_numeric_param(params.get("value", 0.7), 0.7),
        }

    def _rel_vol_trace_details(
        self, params: Dict[str, Any], idx: int
    ) -> Dict[str, Any]:
        if idx < 0 or idx >= len(self.main_df.index):
            return {}

        lookback = max(
            1, int(self._extract_numeric_param(params.get("lookback_period", 20), 20))
        )
        threshold = self._extract_numeric_param(
            params.get("rel_vol_threshold", params.get("multiplier", 1.5)), 1.5
        )
        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        df_tf = self._get_timeframe_df(timeframe)
        if df_tf.empty or "volume" not in df_tf.columns:
            return {
                "threshold": threshold,
                "lookback_period": lookback,
                "timeframe": timeframe,
                "error": "volume data unavailable",
            }

        if "relative_volume" in df_tf.columns and lookback == 20:
            rel_vol_series = df_tf["relative_volume"]
        else:
            rel_vol_series = add_relative_volume(df_tf.copy(), lookback)[
                "relative_volume"
            ]

        if timeframe in {"1m", self.base_timeframe}:
            aligned = rel_vol_series.reindex(self.main_df.index, method="ffill")
        else:
            aligned = self._broadcast_to_1m(rel_vol_series, timeframe).reindex(
                self.main_df.index
            )

        return {
            "relative_volume": self._trace_series_value_at(aligned, idx),
            "threshold": threshold,
            "lookback_period": lookback,
            "timeframe": timeframe,
        }

    def _market_activity_trace_details(
        self, params: Dict[str, Any], idx: int
    ) -> Dict[str, Any]:
        details = self._rel_vol_trace_details(params, idx)
        rel_vol = details.get("relative_volume")
        details["rel_vol_actual"] = rel_vol
        details["rel_vol_threshold"] = details.get("threshold")
        details["natr_actual"] = self._trace_first_column_value(["NATR_", "natr"], idx)
        return details

    def _build_trace_details_for_node(
        self, node: Dict[str, Any], node_type: str, idx: int
    ) -> Dict[str, Any]:
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        details: Dict[str, Any] = {}

        if params:
            details["params"] = self._normalize_trace_detail_value(params)

        if 0 <= idx < len(self.main_df.index):
            details["time"] = self._to_python_datetime(
                self.main_df.index[idx]
            ).isoformat()

        node_id = node.get("id")
        registered_details = (
            self._dynamic_block_results.get(str(node_id))
            if node_id is not None
            else None
        )
        if registered_details and node_type in {
            "local_level",
            "significant_level",
            "level_touch_analyzer",
            "volatility_squeeze",
            "price_action_analyzer",
            "price_consolidation",
            "value_comparison",
            "price_vs_level",
        }:
            for key, series in registered_details.items():
                details[key] = self._trace_series_value_at(series, idx)
            if node_type == "level_touch_analyzer":
                details.update(
                    self._level_touch_trace_events(
                        params, idx, details.get("level"), details.get("tolerance")
                    )
                )
            if node_type == "price_action_analyzer":
                details["markers"] = self._price_action_trace_markers(params, idx)
            if node_type not in {"value_comparison", "price_vs_level"}:
                return details

        if node_type == "rsi_condition":
            period = int(self._extract_numeric_param(params.get("period", 14), 14))
            operator = params.get("operator", "gt")
            threshold = self._extract_numeric_param(params.get("value", 50), 50)
            details.update(
                {
                    "rsi": self._trace_column_value(f"RSI_{period}", idx),
                    "period": period,
                    "operator": operator,
                    "threshold": threshold,
                }
            )
            return details

        if node_type == "ma_cross_condition":
            fast_period = int(
                self._extract_numeric_param(params.get("fast_period", 9), 9)
            )
            slow_period = int(
                self._extract_numeric_param(params.get("slow_period", 21), 21)
            )
            details.update(
                {
                    "fast": self._trace_column_value(f"EMA_{fast_period}", idx),
                    "slow": self._trace_column_value(f"EMA_{slow_period}", idx),
                    "prev_fast": self._trace_column_value(
                        f"EMA_{fast_period}", idx - 1
                    ),
                    "prev_slow": self._trace_column_value(
                        f"EMA_{slow_period}", idx - 1
                    ),
                    "fast_period": fast_period,
                    "slow_period": slow_period,
                    "direction": self._normalize_ma_cross_direction(params),
                }
            )
            return details

        if node_type == "macd_condition":
            fast = int(self._extract_numeric_param(params.get("fast_period", 12), 12))
            slow = int(self._extract_numeric_param(params.get("slow_period", 26), 26))
            signal = int(self._extract_numeric_param(params.get("signal_period", 9), 9))
            fast, slow = min(fast, slow), max(fast, slow)
            details.update(
                {
                    "macd": self._trace_column_value(
                        f"MACD_{fast}_{slow}_{signal}", idx
                    ),
                    "signal": self._trace_column_value(
                        f"MACDs_{fast}_{slow}_{signal}", idx
                    ),
                    "histogram": self._trace_first_column_value(
                        [
                            f"MACDh_{fast}_{slow}_{signal}",
                            f"MACD_hist_{fast}_{slow}_{signal}",
                        ],
                        idx,
                    ),
                    "condition": params.get(
                        "condition", params.get("condition_type", "crossover")
                    ),
                    "fast_period": fast,
                    "slow_period": slow,
                    "signal_period": signal,
                }
            )
            return details

        if node_type == "stochastic_condition":
            normalized_params = self._normalize_stochastic_params(params)
            k_period = int(normalized_params.get("k_period", 14))
            d_period = int(normalized_params.get("d_period", 3))
            smooth_k = int(normalized_params.get("smooth_k", 3))
            details.update(
                {
                    "k": self._trace_column_value(
                        f"STOCHk_{k_period}_{d_period}_{smooth_k}", idx
                    ),
                    "d": self._trace_column_value(
                        f"STOCHd_{k_period}_{d_period}_{smooth_k}", idx
                    ),
                    "k_period": k_period,
                    "d_period": d_period,
                    "slowing": smooth_k,
                    "operator": normalized_params.get("operator", "gt"),
                    "threshold": self._extract_numeric_param(
                        normalized_params.get("value", 80), 80
                    ),
                    "line": normalized_params.get("line", "k"),
                }
            )
            return details

        if node_type == "bollinger_bands_condition":
            period = int(self._extract_numeric_param(params.get("period", 20), 20))
            std_dev = self._extract_numeric_param(params.get("std_dev", 2.0), 2.0)
            details.update(
                {
                    "lower": self._trace_first_column_value(
                        [f"BBL_{period}_{std_dev}", f"BBL_{period}"], idx
                    ),
                    "upper": self._trace_first_column_value(
                        [f"BBU_{period}_{std_dev}", f"BBU_{period}"], idx
                    ),
                    "width": self._trace_first_column_value(
                        [f"BBB_{period}_{std_dev}", f"BBB_{period}"], idx
                    ),
                    "close": self._trace_column_value("close", idx),
                    "period": period,
                    "std_dev": std_dev,
                    "check": self._normalize_bollinger_check_type(params),
                }
            )
            return details

        if node_type == "adx_filter":
            period = int(self._extract_numeric_param(params.get("period", 14), 14))
            details.update(
                {
                    "adx": self._trace_column_value(f"ADX_{period}", idx),
                    "period": period,
                    "threshold": self._extract_numeric_param(
                        params.get("threshold", 25), 25
                    ),
                    "operator": params.get("operator", "gt"),
                }
            )
            return details

        if node_type == "natr_filter":
            period = int(self._extract_numeric_param(params.get("period", 14), 14))
            details.update(
                {
                    "natr": self._trace_column_value(f"NATR_{period}", idx),
                    "period": period,
                    "threshold": self._extract_numeric_param(
                        params.get(
                            "value",
                            params.get("threshold", params.get("natr_threshold", 1.0)),
                        ),
                        1.0,
                    ),
                    "operator": params.get("operator", "gt"),
                }
            )
            return details

        if node_type == "trend_filter":
            indicator = params.get("indicator", "SMA")
            details["indicator"] = indicator
            details["threshold"] = self._extract_numeric_param(
                params.get("threshold", 50), 50
            )
            details["operator"] = params.get("operator", "gt")
            if indicator == "ADX":
                details["actual"] = self._trace_column_value("ADX_14", idx)
            else:
                period = int(
                    self._extract_numeric_param(params.get("threshold", 50), 50)
                )
                details["actual"] = self._trace_column_value(f"SMA_{period}", idx)
                details["close"] = self._trace_column_value("close", idx)
            return details

        if node_type == "volatility_filter":
            details.update(
                {
                    "actual": self._trace_column_value("atr", idx)
                    or self._trace_first_column_value(["ATR_"], idx),
                    "operator": params.get("operator", "gt"),
                    "threshold": self._extract_numeric_param(
                        params.get("value", 0.005), 0.005
                    ),
                }
            )
            return details

        if node_type == "trend_direction":
            fast = params.get("sma_fast_period") or params.get("fast_period", 10)
            slow = params.get("sma_slow_period") or params.get("slow_period", 50)
            rsi_period = int(
                self._extract_numeric_param(params.get("rsi_period", 14), 14)
            )
            sma_fast = self._trace_column_value(
                f"SMA_{int(self._extract_numeric_param(fast, 10))}", idx
            )
            sma_slow = self._trace_column_value(
                f"SMA_{int(self._extract_numeric_param(slow, 50))}", idx
            )
            rsi_value = self._trace_column_value(f"RSI_{rsi_period}", idx)
            rsi_lower = self._extract_numeric_param(
                params.get("rsi_lower_bound", 40), 40
            )
            rsi_upper = self._extract_numeric_param(
                params.get("rsi_upper_bound", 60), 60
            )
            detected_trend = None
            if sma_fast is not None and sma_slow is not None and rsi_value is not None:
                try:
                    if (
                        float(sma_fast) > float(sma_slow)
                        and float(rsi_value) > rsi_upper
                    ):
                        detected_trend = "LONG"
                    elif (
                        float(sma_fast) < float(sma_slow)
                        and float(rsi_value) < rsi_lower
                    ):
                        detected_trend = "SHORT"
                    else:
                        detected_trend = "FLAT"
                except (TypeError, ValueError):
                    detected_trend = None
            details.update(
                {
                    "sma_fast": sma_fast,
                    "sma_slow": sma_slow,
                    "rsi": rsi_value,
                    "detected_trend": detected_trend,
                    "required_trend": params.get("direction")
                    or params.get("required_trend")
                    or "long",
                }
            )
            return details

        if node_type == "round_level":
            details.update(self._round_level_trace_details(params, idx))
            return details

        if node_type == "open_interest":
            details.update(self._open_interest_trace_details(params, idx))
            return details

        if node_type == "correlation":
            details.update(self._correlation_trace_details(params, idx))
            return details

        if node_type == "rel_vol_filter":
            details.update(self._rel_vol_trace_details(params, idx))
            return details

        if node_type == "market_activity":
            details.update(self._market_activity_trace_details(params, idx))
            return details

        if node_type == "value_comparison":
            details.update(
                {
                    "left": self._trace_operand_details(
                        params.get("leftOperand", {}), idx
                    ),
                    "right": self._trace_operand_details(
                        params.get("rightOperand", {}), idx
                    ),
                    "operator": params.get("operator", "gt"),
                }
            )
            return details

        if node_type == "price_vs_level":
            details.update(
                {
                    "left": self._trace_operand_details(
                        params.get("price_source", {}), idx
                    ),
                    "right": self._trace_operand_details(
                        params.get("level_source", {}), idx
                    ),
                    "operator": params.get("operator", "gt"),
                }
            )
            return details

        if node_type == "volume_confirmation":
            lookback = int(
                self._extract_numeric_param(params.get("lookback_period", 20), 20)
            )
            multiplier = self._extract_numeric_param(params.get("multiplier", 1.5), 1.5)
            volume = self._trace_column_value("volume", idx)
            vol_ma = None
            if "volume" in self.main_df.columns and idx >= 0:
                start = max(0, idx - lookback + 1)
                vol_ma = self._normalize_trace_detail_value(
                    self.main_df["volume"].iloc[start : idx + 1].mean()
                )
            details.update(
                {
                    "volume": volume,
                    "volume_ma": vol_ma,
                    "lookback_period": lookback,
                    "multiplier": multiplier,
                    "threshold": vol_ma * multiplier if vol_ma is not None else None,
                }
            )
            return details

        if node_type == "tape_condition":
            metric = params.get("metric", "delta_volume")
            window_sec = int(
                self._extract_numeric_param(params.get("window_sec", 5), 5)
            )
            avg_lookback_sec = int(
                self._extract_numeric_param(params.get("avg_lookback_sec", 60), 60)
            )
            metric_to_column = {
                "delta_volume": f"tape_delta_volume_usd_{window_sec}s",
                "delta_count": f"tape_delta_count_{window_sec}s",
                "ratio_volume": f"tape_buy_sell_ratio_volume_{window_sec}s",
                "ratio_count": f"tape_buy_sell_ratio_count_{window_sec}s",
                "accel_volume": f"tape_accel_mult_volume_{window_sec}s_{avg_lookback_sec}s",
                "accel_count": f"tape_accel_mult_count_{window_sec}s_{avg_lookback_sec}s",
                "total_volume": f"tape_total_volume_usd_{window_sec}s",
                "total_count": f"tape_total_count_{window_sec}s",
            }
            column = metric_to_column.get(metric)
            details.update(
                {
                    "metric": metric,
                    "actual": self._trace_column_value(column, idx),
                    "operator": params.get("operator", "gt"),
                    "threshold": self._extract_numeric_param(
                        params.get("threshold", 0.0), 0.0
                    ),
                    "window_sec": window_sec,
                }
            )
            return details

        return details

    def _build_trace_node(
        self,
        node: Dict[str, Any],
        node_results: Dict[str, pd.Series],
        idx: int,
        path: str = "root",
    ) -> Dict[str, Any]:
        raw_type = node.get("type", "unknown")
        node_type = (
            raw_type
            if raw_type in {"AND", "OR"}
            else normalize_condition_type(str(raw_type))
        )
        node_id = str(node.get("id") or path)
        children = (
            node.get("children") if isinstance(node.get("children"), list) else []
        )
        trace: Dict[str, Any] = {
            "id": node_id,
            "type": raw_type,
            "result": False,
            "details": {},
        }
        params_for_trace = node.get("params")
        if isinstance(params_for_trace, dict):
            trace["params"] = self._normalize_trace_detail_value(params_for_trace)

        if node_type in {"AND", "OR"}:
            child_traces = [
                self._build_trace_node(child, node_results, idx, f"{path}.{child_idx}")
                for child_idx, child in enumerate(children)
                if isinstance(child, dict)
            ]
            trace["children"] = child_traces
            if node_id in node_results:
                trace["result"] = self._series_bool_at(node_results.get(node_id), idx)
            elif child_traces:
                child_results = [bool(child.get("result")) for child in child_traces]
                trace["result"] = (
                    all(child_results) if node_type == "AND" else any(child_results)
                )
            else:
                trace["result"] = node_type == "AND"
                trace["details"]["info"] = "Empty logic gate evaluated."
            return trace

        result_series = node_results.get(node_id)
        if result_series is None:
            try:
                result_series = self._coerce_mask_series(
                    self._evaluate_condition_tree(node)
                ).fillna(False)
            except Exception as exc:
                trace["details"]["error"] = f"Vector trace evaluation failed: {exc}"
                return trace

        trace["result"] = self._series_bool_at(result_series, idx)
        trace["details"] = self._build_trace_details_for_node(node, node_type, idx)
        return trace

    def _build_decision_trace_for_index(
        self, signal_idx: int, direction: str
    ) -> Optional[Dict[str, Any]]:
        entry_conditions = self.strategy_json.get("entryConditions")
        if (
            not isinstance(entry_conditions, dict)
            or signal_idx < 0
            or signal_idx >= len(self.main_df.index)
        ):
            return None

        trace = self._build_trace_node(
            entry_conditions, self._entry_node_results, signal_idx, "entryConditions"
        )
        if self._entry_condition_result is not None:
            trace["result"] = self._series_bool_at(
                self._entry_condition_result, signal_idx, bool(trace.get("result"))
            )

        signal_time = self._to_python_datetime(self.main_df.index[signal_idx])
        details = trace.setdefault("details", {})
        details.update(
            {
                "engine": "vector",
                "signal_time": signal_time.isoformat(),
                "direction": direction,
            }
        )

        if "foundation_total_weight" in self.signals.columns:
            total_weight = float(
                self.signals["foundation_total_weight"].iloc[signal_idx]
            )
            effective_threshold = min(
                self.min_total_foundation_weight_threshold,
                self.max_possible_expensive_weight,
            )
            details.update(
                {
                    "foundation_total_weight": total_weight,
                    "foundation_weight_threshold": float(effective_threshold),
                    "weight_passed": bool(total_weight >= effective_threshold),
                }
            )

        filters_config = self.strategy_json.get("filters")
        if isinstance(filters_config, dict):
            filter_trace = self._build_trace_node(
                filters_config, self._filter_node_results, signal_idx, "filters"
            )
            if self._filter_condition_result is not None:
                filter_trace["result"] = self._series_bool_at(
                    self._filter_condition_result,
                    signal_idx,
                    bool(filter_trace.get("result")),
                )
            trace["filters_trace"] = filter_trace

        return trace

    def _resolve_foundation_weight_key(self, node_id: Optional[Any]) -> Optional[str]:
        if not isinstance(self.foundation_weights, dict) or not self.foundation_weights:
            return None
        if node_id is None:
            return None

        normalized_id = str(node_id)
        if normalized_id in self.foundation_weights:
            return normalized_id

        if normalized_id.startswith("w_"):
            stripped_id = normalized_id[2:]
            if stripped_id in self.foundation_weights:
                return stripped_id
        else:
            legacy_key = f"w_{normalized_id}"
            if legacy_key in self.foundation_weights:
                return legacy_key

        return None

    def _get_max_possible_expensive_weight(self, node: Dict[str, Any]) -> float:
        if not isinstance(node, dict):
            return 0.0

        node_type = normalize_condition_type(node.get("type"))
        if node_type == "AND":
            return sum(
                self._get_max_possible_expensive_weight(child)
                for child in node.get("children", []) or []
            )
        if node_type == "OR":
            child_weights = [
                self._get_max_possible_expensive_weight(child)
                for child in node.get("children", []) or []
            ]
            return max(child_weights, default=0.0)

        analysis_level = str(node.get("analysis_level", "second_bar_trigger"))
        if analysis_level != "second_bar_trigger":
            return 0.0

        weight_key = self._resolve_foundation_weight_key(node.get("id"))
        if weight_key is None:
            return 0.0

        return self._coerce_float(self.foundation_weights.get(weight_key), 0.0)

    def _evaluate_condition_tree_with_node_results(
        self, node: Dict[str, Any]
    ) -> tuple[pd.Series, Dict[str, pd.Series]]:
        default_mask = pd.Series(True, index=self.main_df.index, dtype=bool)
        if not isinstance(node, dict):
            return default_mask, {}

        raw_type = node.get("type")
        node_type = normalize_condition_type(raw_type)

        if node_type in {"AND", "OR"}:
            children = node.get("children", []) or []
            if not children:
                empty_mask = pd.Series(
                    node_type == "AND", index=self.main_df.index, dtype=bool
                )
                node_results: Dict[str, pd.Series] = {}
                node_id = node.get("id")
                if node_id is not None:
                    node_results[str(node_id)] = empty_mask
                return empty_mask, node_results

            child_masks: List[pd.Series] = []
            node_results: Dict[str, pd.Series] = {}
            for child in children:
                child_mask, child_results = (
                    self._evaluate_condition_tree_with_node_results(child)
                )
                child_masks.append(self._coerce_mask_series(child_mask).fillna(False))
                node_results.update(child_results)

            if node_type == "AND":
                result_mask = self._coerce_mask_series(
                    np.logical_and.reduce(child_masks)
                )
            else:
                result_mask = self._coerce_mask_series(
                    np.logical_or.reduce(child_masks)
                )

            node_id = node.get("id")
            if node_id is not None:
                node_results[str(node_id)] = result_mask
                self._register_block_result(node, result_mask)
            return result_mask, node_results

        leaf_mask = self._coerce_mask_series(
            self._evaluate_condition_tree(node)
        ).fillna(False)
        self._register_block_result(node, leaf_mask)
        node_id = node.get("id")
        node_results = {str(node_id): leaf_mask} if node_id is not None else {}
        return leaf_mask, node_results

    def _calculate_weight_from_node_results(
        self,
        node_results: Dict[str, pd.Series],
        *,
        eligible_mask: Optional[pd.Series] = None,
    ) -> tuple[pd.Series, Dict[str, int]]:
        total_weight = pd.Series(0.0, index=self.main_df.index, dtype=float)
        triggered_counts = {
            str(foundation_id): 0
            for foundation_id in (self.foundation_weights or {}).keys()
        }
        if not self.foundation_weights:
            return total_weight, triggered_counts

        allowed_mask = (
            self._coerce_mask_series(eligible_mask).fillna(False)
            if eligible_mask is not None
            else pd.Series(True, index=self.main_df.index, dtype=bool)
        )

        for node_id, result_mask in node_results.items():
            weight_key = self._resolve_foundation_weight_key(node_id)
            if weight_key is None:
                continue

            weight_value = self._coerce_float(
                self.foundation_weights.get(weight_key), 0.0
            )
            normalized_mask = self._coerce_mask_series(result_mask).fillna(False)
            total_weight = total_weight + normalized_mask.astype(float) * weight_value
            triggered_counts[weight_key] = triggered_counts.get(weight_key, 0) + int(
                (normalized_mask & allowed_mask).sum()
            )

        return total_weight, triggered_counts

    @staticmethod
    def _get_first_configured(source: Optional[Dict[str, Any]], *keys: str) -> Any:
        if not isinstance(source, dict):
            return None
        for key in keys:
            if key in source and source.get(key) is not None:
                return source.get(key)
        return None

    def _get_percent_setting(
        self,
        percent_keys: List[str],
        ratio_keys: List[str],
        default_percent: float,
    ) -> float:
        raw_ratio = self._get_first_configured(self.risk_params, *ratio_keys)
        if raw_ratio is not None:
            value = self._coerce_float(raw_ratio, default_percent / 100.0)
            return value / 100.0 if value > 1.0 else value

        raw_percent = self._get_first_configured(self.risk_params, *percent_keys)
        if raw_percent is not None:
            return self._coerce_float(raw_percent, default_percent) / 100.0

        return float(default_percent) / 100.0

    def _get_numeric_setting(self, keys: List[str], default: float) -> float:
        raw_value = self._get_first_configured(self.risk_params, *keys)
        return self._coerce_float(raw_value, default)

    def _check_and_reset_daily_stats(self, current_dt: datetime) -> None:
        current_day_str = current_dt.strftime("%Y-%m-%d")
        if self._risk_last_known_day_str != current_day_str:
            self._risk_start_of_day_balance = self.current_balance
            self._risk_consecutive_losses = 0
            self._risk_last_known_day_str = current_day_str
            # Do NOT reset is_trading_allowed if the account is liquidated
            if not self.is_trading_allowed and not self._is_liquidated:
                self.is_trading_allowed = True

    def _check_liquidation(self) -> bool:
        """Checks for liquidation: if balance <= 0, trading stops forever."""
        if self._is_liquidated:
            return True
        if self.current_balance <= 0:
            self._is_liquidated = True
            self.is_trading_allowed = False
            self.current_balance = 0.0
            logger.warning(
                "LIQUIDATION: Account balance reached zero. "
                "All further trading is disabled for this backtest."
            )
            return True
        return False

    def _check_risk_limits_after_trade(
        self, trade_pnl_usd: float, current_dt: datetime
    ) -> None:
        # Check liquidation first
        if self._check_liquidation():
            return

        self._check_and_reset_daily_stats(current_dt)
        current_day_str = current_dt.strftime("%Y-%m-%d")
        self._risk_daily_pnl[current_day_str] = self._risk_daily_pnl.get(
            current_day_str, 0.0
        ) + float(trade_pnl_usd)

        if trade_pnl_usd <= 0:
            self._risk_consecutive_losses += 1
        else:
            self._risk_consecutive_losses = 0

        self._risk_max_consecutive_losses = max(
            self._risk_max_consecutive_losses, self._risk_consecutive_losses
        )
        if not self.is_trading_allowed:
            return

        daily_max_loss_pct = self._get_percent_setting(
            ["dailyMaxLossPercent", "daily_max_loss_pct"],
            ["daily_max_loss_ratio"],
            100.0,  # Default to 100% (disabled)
        )
        max_consecutive_losses = int(
            self._get_numeric_setting(
                ["maxConsecutiveLosses", "max_consecutive_losses"], 10000
            )
        )
        max_drawdown_pct = self._get_percent_setting(
            ["maxDrawdown", "max_drawdown_pct", "max_drawdown"],
            ["max_drawdown_ratio"],
            100.0,  # Default to 100% (disabled)
        )

        day_pnl = self._risk_daily_pnl.get(current_day_str, 0.0)
        daily_loss_limit_usd = -(self._risk_start_of_day_balance * daily_max_loss_pct)
        drawdown = (
            ((self.peak_equity - self.current_balance) / self.peak_equity)
            if self.peak_equity > 1e-9
            else 0.0
        )

        if (
            day_pnl <= daily_loss_limit_usd
            or self._risk_consecutive_losses >= max_consecutive_losses
            or drawdown >= max_drawdown_pct
        ):
            self.is_trading_allowed = False

    def _strategy_risk_fraction_override(
        self, init_params: Dict[str, Any]
    ) -> Optional[float]:
        for key in ("risk_pct_per_trade", "riskPctPerTrade"):
            raw = init_params.get(key)
            if raw is None:
                continue
            value = self._coerce_float(raw, 0.0)
            return value / 100.0 if value > 1.0 else value

        raw_percent = init_params.get("riskPerTradePercent")
        if raw_percent is None:
            return None
        return self._coerce_float(raw_percent, 1.0) / 100.0

    def _strategy_risk_usd_override(
        self, init_params: Dict[str, Any]
    ) -> Optional[float]:
        raw_risk_value = init_params.get("risk_value", init_params.get("riskValue"))
        if raw_risk_value is None:
            return None

        risk_override = resolve_strategy_risk_override(
            init_params.get(
                "risk_type", init_params.get("riskType", "percent_balance")
            ),
            self._extract_numeric_param(raw_risk_value, 0.0),
        )
        if risk_override.risk_usd is not None:
            return risk_override.risk_usd
        if risk_override.risk_pct is not None:
            return self.current_balance * risk_override.risk_pct

        return None

    def _adjust_quantity_to_exchange(
        self,
        quantity: float,
        price: float,
        stop_distance: float,
        target_max_risk_usd: Optional[float] = None,
    ) -> tuple[float, Optional[str]]:
        if quantity <= 1e-12:
            return 0.0, "NON_POSITIVE_QUANTITY"

        lot_params = self.exchange_info.get("lot_params") or {}
        min_notional = self.exchange_info.get(
            "min_notional", self.exchange_info.get("minNotional")
        )
        max_notional_multiplier = self._coerce_float(
            getattr(
                self.config,
                "MAX_REAL_POSITION_SIZE_PCT_BALANCE",
                getattr(self.config, "BACKTEST_MAX_POSITION_SIZE_PCT_BALANCE", 0.50),
            ),
            0.50,
        )
        max_notional_usd = self.current_balance * max_notional_multiplier
        if target_max_risk_usd is None:
            target_max_risk_usd = self.current_balance * self._get_percent_setting(
                ["riskPerTradePercent"],
                ["risk_pct_per_trade", "risk_per_trade_percent"],
                getattr(self.config, "DEFAULT_RISK_PER_TRADE_PERCENT", 1.0),
            )
        target_max_risk_usd = max(target_max_risk_usd, 0.0)

        qty = Decimal(str(quantity))
        entry_price_d = Decimal(str(price))
        stop_distance_d = Decimal(str(stop_distance))
        step_size_d = (
            Decimal(str(lot_params.get("stepSize", "0")))
            if lot_params
            else Decimal("0")
        )
        min_qty_d = (
            Decimal(str(lot_params.get("minQty", "0"))) if lot_params else Decimal("0")
        )
        max_qty_float = (
            self._coerce_float(lot_params.get("maxQty"), float("inf"))
            if lot_params
            else float("inf")
        )
        min_notional_d = (
            Decimal(str(min_notional)) if min_notional is not None else Decimal("0")
        )
        target_max_risk_d = Decimal(str(target_max_risk_usd))
        max_notional_d = Decimal(str(max_notional_usd))

        if step_size_d > Decimal("0"):
            qty = (qty / step_size_d).quantize(
                Decimal("0"), rounding=ROUND_DOWN
            ) * step_size_d

        if float(qty) > max_qty_float:
            qty = Decimal(str(max_qty_float))
            if step_size_d > Decimal("0"):
                qty = (qty / step_size_d).quantize(
                    Decimal("0"), rounding=ROUND_DOWN
                ) * step_size_d

        if qty < min_qty_d:
            candidate = min_qty_d
            if candidate * entry_price_d <= max_notional_d and (
                stop_distance_d <= Decimal("0")
                or candidate * stop_distance_d <= target_max_risk_d
            ):
                qty = candidate
            else:
                return 0.0, "EXCHANGE_LIMITS"

        if min_notional_d > Decimal("0") and qty * entry_price_d < min_notional_d:
            required_qty = min_notional_d / entry_price_d
            if step_size_d > Decimal("0"):
                required_qty = (required_qty / step_size_d).quantize(
                    Decimal("0"), rounding=ROUND_UP
                ) * step_size_d
            if required_qty * entry_price_d <= max_notional_d and (
                stop_distance_d <= Decimal("0")
                or required_qty * stop_distance_d <= target_max_risk_d
            ):
                qty = required_qty
            else:
                return 0.0, "EXCHANGE_LIMITS"

        if qty <= Decimal("0"):
            return 0.0, "EXCHANGE_LIMITS"

        return float(qty), None

    def _determine_position_size(
        self,
        entry_price: float,
        stop_price: Optional[float],
        take_profit: Optional[float],
        init_params: Dict[str, Any],
        current_dt: datetime,
        is_short: bool,
    ) -> tuple[float, float, Optional[str]]:
        self._check_and_reset_daily_stats(current_dt)
        if not self.is_trading_allowed:
            return 0.0, 0.0, "GLOBAL_RISK_LIMIT"

        risk_usd_override = self._strategy_risk_usd_override(init_params)
        if risk_usd_override is not None:
            initial_risk_usd_planned = risk_usd_override
        else:
            risk_fraction = self._strategy_risk_fraction_override(init_params)
            if risk_fraction is None:
                risk_fraction = self._get_percent_setting(
                    [
                        "riskPerTradePercent",
                        "risk_pct_per_trade",
                        "risk_per_trade_percent",
                    ],
                    ["risk_ratio_per_trade", "risk_fraction"],
                    getattr(self.config, "DEFAULT_RISK_PER_TRADE_PERCENT", 1.0),
                )
            initial_risk_usd_planned = self.current_balance * risk_fraction

        if entry_price <= 0 or initial_risk_usd_planned <= 0:
            return 0.0, 0.0, "INVALID_ENTRY_PRICE"

        max_notional_multiplier = self._coerce_float(
            getattr(
                self.config,
                "MAX_REAL_POSITION_SIZE_PCT_BALANCE",
                getattr(self.config, "BACKTEST_MAX_POSITION_SIZE_PCT_BALANCE", 0.50),
            ),
            0.50,
        )
        max_notional_usd = self.current_balance * max_notional_multiplier

        if stop_price is None:
            raw_qty = min(initial_risk_usd_planned, max_notional_usd) / entry_price
            quantity, rejection_reason = self._adjust_quantity_to_exchange(
                raw_qty,
                entry_price,
                0.0,
                initial_risk_usd_planned,
            )
            return quantity, initial_risk_usd_planned, rejection_reason

        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 1e-12:
            return 0.0, 0.0, "ZERO_STOP_DISTANCE"

        if (is_short and stop_price <= entry_price) or (
            not is_short and stop_price >= entry_price
        ):
            if getattr(self, "_debug_count_dir", 0) < 10:
                print(
                    f"DEBUG DIRECTION REJECT: is_short={is_short}, stop={stop_price}, entry={entry_price}"
                )
                self._debug_count_dir = getattr(self, "_debug_count_dir", 0) + 1
            return 0.0, 0.0, "STOP_DIRECTION_INVALID"

        max_stop_distance_pct = self._get_percent_setting(
            ["maxStopDistancePercent", "maxStopDistancePct", "max_stop_distance_pct"],
            ["max_stop_distance_ratio"],
            float(getattr(self.config, "RISK_MANAGER_MAX_STOP_DISTANCE_PCT", 5.0)),
        )
        min_stop_distance_pct = (
            float(getattr(self.config, "RISK_MANAGER_MIN_STOP_DISTANCE_PCT", 0.05))
            / 100.0
        )

        if (
            stop_distance > entry_price * max_stop_distance_pct
            or stop_distance < entry_price * min_stop_distance_pct
        ):
            return 0.0, 0.0, "STOP_DISTANCE_LIMIT"

        min_rr_ratio = self._get_numeric_setting(
            ["minRrRatio", "min_rr_ratio"],
            float(getattr(self.config, "RISK_MANAGER_MIN_RR_RATIO", 1.0)),
        )
        if take_profit is not None and not self.uses_dca_or_grid_management:
            profit_distance = abs(take_profit - entry_price)
            if profit_distance <= 1e-12 or (profit_distance / stop_distance) < (
                min_rr_ratio - 1e-6
            ):
                return 0.0, 0.0, "RR_BELOW_MIN"

        raw_qty = min(
            initial_risk_usd_planned / stop_distance, max_notional_usd / entry_price
        )
        quantity, rejection_reason = self._adjust_quantity_to_exchange(
            raw_qty,
            entry_price,
            stop_distance,
            initial_risk_usd_planned,
        )
        return quantity, initial_risk_usd_planned, rejection_reason

    def _broadcast_to_1m(self, series: pd.Series, source_tf: str) -> pd.Series:
        """
        Broadcasts a data series from a higher timeframe to a 1m index.

        CRITICALLY IMPORTANT: We do shift(1) BEFORE broadcasting to prevent Look-Ahead Bias.

        Example: At 10:05 we do NOT know the close of the H1 candle (10:00-11:00).
        We only know the close of the previous H1 candle (09:00-10:00).

        Args:
            series: Data series (indicator, price, etc.)
            source_tf: Source timeframe ('5m', '1h', etc.)

        Returns:
            Series broadcasted to 1m index with FFill
        """
        if series.index.equals(self.main_df.index):
            return series  # Already on 1m, broadcasting not needed

        # Perform shift(1) to avoid using the current unclosed candle
        shifted_series = series.shift(1)

        # Reindex to 1m index with forward fill
        broadcasted = shifted_series.reindex(self.main_df.index, method="ffill")

        return broadcasted

    def _get_timeframe_df(self, timeframe: str = "1m") -> pd.DataFrame:
        if timeframe == "auto":
            return self.main_df
        df = self.data_context.get(timeframe)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df
        return self.main_df

    def _eval_cache_key(self, prefix: str, params: Any) -> str:
        try:
            payload = json.dumps(params, sort_keys=True, default=str)
        except TypeError:
            payload = str(params)
        return f"{prefix}:{payload}"

    def _align_series_to_main_index(self, series: pd.Series) -> pd.Series:
        if series.index.equals(self.main_df.index):
            return series.reindex(self.main_df.index)
        return series.reindex(self.main_df.index, method="ffill")

    def _broadcast_closed_signal_to_main(self, series: pd.Series) -> pd.Series:
        if series.index.equals(self.main_df.index):
            return series.reindex(self.main_df.index)
        return series.shift(1).reindex(self.main_df.index, method="ffill")

    def _get_main_atr_series(self) -> pd.Series:
        if "ATR_14" in self.main_df.columns:
            return (
                self.main_df["ATR_14"]
                .astype(float)
                .reindex(self.main_df.index)
                .bfill()
                .ffill()
            )
        if "ATR_14" in self.signals.columns:
            return (
                self.signals["ATR_14"]
                .astype(float)
                .reindex(self.main_df.index)
                .bfill()
                .ffill()
            )
        return (self.main_df["close"].astype(float) * 0.01).reindex(self.main_df.index)

    def _get_tick_size(self) -> float:
        try:
            return float(
                self.exchange_info.get("tick_size")
                or getattr(self.config, "DEFAULT_TICK_SIZE", 0.0)
                or 0.0
            )
        except (TypeError, ValueError):
            return 0.0

    def _maybe_apply_move_to_breakeven(
        self,
        blocks: List[Dict[str, Any]],
        *,
        entry_price: float,
        reference_stop_price: Optional[float],
        current_sl: Optional[float],
        atr_value: float,
        price_for_check: float,
        is_short: bool,
    ) -> Optional[float]:
        if current_sl is None or entry_price <= 0 or not np.isfinite(price_for_check):
            return None

        tick_size = self._get_tick_size()
        if tick_size <= 0:
            return None

        pnl_per_unit = (
            (entry_price - price_for_check)
            if is_short
            else (price_for_check - entry_price)
        )
        if pnl_per_unit <= 0:
            return None

        for block in blocks:
            params = block.get("params", {})
            target_type = (
                str(params.get("target_type", "atr_multiplier")).strip().lower()
            )
            target_value = self._extract_numeric_param(
                params.get("target_value", 1.0), 1.0
            )
            should_activate = False

            if target_type in {"unrealized_pnl_rr", "rr_multiplier"}:
                risk_reference_stop = (
                    reference_stop_price
                    if reference_stop_price is not None
                    else current_sl
                )
                risk_distance = (
                    abs(entry_price - risk_reference_stop)
                    if risk_reference_stop is not None
                    else 0.0
                )
                should_activate = (
                    risk_distance > 1e-12
                    and (pnl_per_unit / risk_distance) >= target_value
                )
            elif target_type == "atr_multiplier":
                should_activate = atr_value > 0 and pnl_per_unit >= (
                    atr_value * target_value
                )
            elif target_type == "percent_from_price":
                should_activate = pnl_per_unit >= (entry_price * (target_value / 100.0))
            else:
                continue

            if not should_activate:
                continue

            offset_pips = max(
                0, int(self._extract_numeric_param(params.get("offset_pips", 2), 2.0))
            )
            raw_new_sl = (
                entry_price - (offset_pips * tick_size)
                if is_short
                else entry_price + (offset_pips * tick_size)
            )
            rounding_direction = ROUND_DOWN if is_short else ROUND_UP
            new_sl = round_price_by_tick(raw_new_sl, tick_size, rounding_direction)
            if new_sl is None:
                continue

            is_better = (
                current_sl is None
                or (is_short and new_sl < current_sl)
                or ((not is_short) and new_sl > current_sl)
            )
            if is_better:
                return float(new_sl)

        return None

    def _resolve_significant_level_series(self, level_type: str) -> pd.Series:
        normalized_level_type = str(level_type or "daily_high").strip().lower()
        cache_key = self._eval_cache_key(
            "significant_level_series", normalized_level_type
        )
        cached = self._series_eval_cache.get(cache_key)
        if isinstance(cached, pd.Series):
            return cached

        level_windows: Dict[str, List[tuple[str, int, str]]] = {
            "daily_high": [("1d", 1, "high"), ("4h", 6, "high"), ("1h", 24, "high")],
            "daily_low": [("1d", 1, "low"), ("4h", 6, "low"), ("1h", 24, "low")],
            "weekly_high": [("1d", 7, "high"), ("4h", 42, "high"), ("1h", 168, "high")],
            "weekly_low": [("1d", 7, "low"), ("4h", 42, "low"), ("1h", 168, "low")],
        }
        fallback_chain = level_windows.get(
            normalized_level_type, level_windows["daily_high"]
        )
        resolved = pd.Series(np.nan, index=self.main_df.index, dtype=float)

        for timeframe, window, column in fallback_chain:
            df_tf = self._get_timeframe_df(timeframe)
            if df_tf.empty or column not in df_tf.columns:
                continue

            if column == "high":
                level_series = (
                    df_tf[column].rolling(window=window, min_periods=1).max().shift(1)
                )
            else:
                level_series = (
                    df_tf[column].rolling(window=window, min_periods=1).min().shift(1)
                )

            aligned = self._align_series_to_main_index(level_series.astype(float))
            resolved = resolved.combine_first(aligned)
            if not resolved.isna().any():
                break

        self._series_eval_cache[cache_key] = resolved
        return resolved

    def _evaluate_significant_level(self, params: Dict[str, Any]) -> pd.Series:
        level_type = str(params.get("level_type", "daily_high")).strip().lower()
        proximity_type = (
            str(params.get("proximity_type", "atr_multiplier")).strip().lower()
        )
        proximity_value = self._extract_numeric_param(
            params.get("proximity_value", 0.25), 0.25
        )
        level_series = self._resolve_significant_level_series(level_type)
        last_price = self.main_df["close"].astype(float)

        if proximity_type == "percentage":
            threshold = level_series.abs() * (proximity_value / 100.0)
        else:
            threshold = self._get_main_atr_series() * proximity_value

        return (
            level_series.notna()
            & threshold.notna()
            & ((last_price - level_series).abs() <= threshold)
        ).fillna(False)

    def _resolve_local_level_series(self, params: Dict[str, Any]) -> pd.Series:
        cache_key = self._eval_cache_key("local_level_series", params)
        cached = self._series_eval_cache.get(cache_key)
        if isinstance(cached, pd.Series):
            return cached

        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe
        lookback_period = max(
            1, int(self._extract_numeric_param(params.get("lookback_period", 20), 20))
        )
        level_type = str(params.get("level_type", "all") or "all").strip().lower()
        level_type = {
            "any": "all",
            "both": "all",
            "max": "high",
            "maximum": "high",
            "highs": "high",
            "hi": "high",
            "min": "low",
            "minimum": "low",
            "lows": "low",
            "lo": "low",
        }.get(level_type, level_type)
        columns = ("high", "low")
        if level_type == "high":
            columns = ("high",)
        elif level_type == "low":
            columns = ("low",)

        df_tf = self._get_timeframe_df(timeframe)
        if df_tf.empty or "high" not in df_tf.columns or "low" not in df_tf.columns:
            empty = self._empty_numeric_series()
            self._series_eval_cache[cache_key] = empty
            return empty

        last_price = self.main_df["close"].astype(float)
        closest_level = pd.Series(np.nan, index=self.main_df.index, dtype=float)
        min_diff = pd.Series(np.inf, index=self.main_df.index, dtype=float)

        candidate_levels: List[pd.Series] = []
        if "high" in columns:
            high_level = (
                df_tf["high"]
                .astype(float)
                .shift(1)
                .rolling(
                    window=lookback_period,
                    min_periods=1,
                )
                .max()
            )
            candidate_levels.append(self._align_series_to_main_index(high_level))
        if "low" in columns:
            low_level = (
                df_tf["low"]
                .astype(float)
                .shift(1)
                .rolling(
                    window=lookback_period,
                    min_periods=1,
                )
                .min()
            )
            candidate_levels.append(self._align_series_to_main_index(low_level))

        for candidate_series in candidate_levels:
            candidate_series = candidate_series.reindex(self.main_df.index)
            candidate_diff = (last_price - candidate_series).abs()
            update_mask = candidate_series.notna() & (candidate_diff < min_diff)
            if update_mask.any():
                min_diff = min_diff.where(~update_mask, candidate_diff)
                closest_level = closest_level.where(~update_mask, candidate_series)

        self._series_eval_cache[cache_key] = closest_level
        return closest_level

    def _evaluate_local_level(self, params: Dict[str, Any]) -> pd.Series:
        if bool(params.get("is_data_provider", False)):
            return pd.Series(True, index=self.main_df.index)

        proximity_type = (
            str(params.get("proximity_type", "atr_multiplier")).strip().lower()
        )
        proximity_value = self._extract_numeric_param(
            params.get("proximity_value", 0.25), 0.25
        )
        closest_level = self._resolve_local_level_series(params)
        last_price = self.main_df["close"].astype(float)
        min_diff = (last_price - closest_level).abs()

        if proximity_type == "percentage":
            threshold = closest_level.abs() * (proximity_value / 100.0)
        else:
            threshold = self._get_main_atr_series() * proximity_value

        return (
            closest_level.notna() & threshold.notna() & (min_diff <= threshold)
        ).fillna(False)

    def _timeframe_ohlc_series(
        self, timeframe: str, *, closed_only: bool = False
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        df_tf = self._get_timeframe_df(timeframe)
        close = (
            df_tf["close"].astype(float)
            if "close" in df_tf.columns
            else pd.Series(np.nan, index=df_tf.index, dtype=float)
        )
        high = df_tf["high"].astype(float) if "high" in df_tf.columns else close
        low = df_tf["low"].astype(float) if "low" in df_tf.columns else close
        align = (
            self._broadcast_closed_signal_to_main
            if closed_only
            else self._align_series_to_main_index
        )
        return (
            align(high).reindex(self.main_df.index),
            align(low).reindex(self.main_df.index),
            align(close).reindex(self.main_df.index),
        )

    def _evaluate_level_touch_analyzer(
        self, params: Dict[str, Any]
    ) -> tuple[pd.Series, Dict[str, pd.Series]]:
        cache_key = self._eval_cache_key("level_touch_analyzer", params)
        cached = self._series_eval_cache.get(cache_key)
        if cached is not None:
            return cached

        raw_level = params.get("level_source")
        if raw_level is None:
            raw_level = params.get("level_price")
        level = self._coerce_numeric_series(self._resolve_value_series(raw_level))
        lookback = max(
            1, int(self._extract_numeric_param(params.get("lookback_candles", 50), 50))
        )

        tolerance_pct_param = params.get("touch_tolerance_pct")
        if tolerance_pct_param is not None:
            tolerance_pct = self._extract_numeric_param(tolerance_pct_param, 0.1)
            tolerance = level.abs() * (float(tolerance_pct) / 100.0)
        else:
            proximity_type = str(params.get("proximity_type", "")).strip().lower()
            proximity_value = params.get("proximity_value")
            if proximity_type == "percentage" and proximity_value is not None:
                tolerance_pct = self._extract_numeric_param(proximity_value, 0.1)
                tolerance = level.abs() * (float(tolerance_pct) / 100.0)
            elif (
                params.get("touch_tolerance_atr") is not None
                or proximity_type == "atr_multiplier"
            ):
                atr_multiplier = self._extract_numeric_param(
                    params.get(
                        "touch_tolerance_atr",
                        proximity_value if proximity_value is not None else 0.15,
                    ),
                    0.15,
                )
                tolerance = self._get_main_atr_series().astype(float) * float(
                    atr_multiplier
                )
            else:
                tolerance = level.abs() * 0.001

        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe
        use_closed_htf = not self._get_timeframe_df(timeframe).index.equals(
            self.main_df.index
        )
        high, low, close = self._timeframe_ohlc_series(
            timeframe, closed_only=use_closed_htf
        )
        median_close = close.rolling(window=lookback, min_periods=1).median()
        configured_side = str(params.get("level_side", "auto")).strip().lower()
        if configured_side in {"resistance", "upper"}:
            resistance_side = pd.Series(True, index=self.main_df.index, dtype=bool)
        elif configured_side in {"support", "lower"}:
            resistance_side = pd.Series(False, index=self.main_df.index, dtype=bool)
        else:
            resistance_side = (median_close <= level).fillna(False)

        touches_count = pd.Series(0, index=self.main_df.index, dtype=int)
        pierce_count = pd.Series(0, index=self.main_df.index, dtype=int)
        for shift_steps in range(lookback):
            high_shifted = high.shift(shift_steps)
            low_shifted = low.shift(shift_steps)
            touched = (
                level.notna()
                & tolerance.notna()
                & high_shifted.notna()
                & low_shifted.notna()
                & (high_shifted >= level - tolerance)
                & (low_shifted <= level + tolerance)
            )
            pierced_resistance = resistance_side & (high_shifted > level + tolerance)
            pierced_support = (~resistance_side) & (low_shifted < level - tolerance)
            pierced = (
                level.notna()
                & tolerance.notna()
                & (pierced_resistance | pierced_support)
            )
            touches_count = touches_count + touched.fillna(False).astype(int)
            pierce_count = pierce_count + pierced.fillna(False).astype(int)

        min_touches = max(
            1, int(self._extract_numeric_param(params.get("min_touches", 1), 1))
        )
        invalidate_on_pierce = bool(params.get("invalidate_on_pierce", False))
        pierce_detected = pierce_count > 0
        is_valid = (
            (~pierce_detected)
            if invalidate_on_pierce
            else pd.Series(True, index=self.main_df.index, dtype=bool)
        )
        result = (
            (level.notna() & is_valid & (touches_count >= min_touches))
            .fillna(False)
            .astype(bool)
        )
        tolerance_pct_series = (tolerance / level.abs() * 100.0).replace(
            [np.inf, -np.inf], np.nan
        )

        output = (
            result,
            {
                "level": level,
                "touches_count": touches_count.astype(float),
                "is_valid": is_valid.astype(bool),
                "touch_tolerance_pct": tolerance_pct_series,
                "tolerance": tolerance,
                "pierce_detected": pierce_detected.astype(bool),
                "min_touches": self._constant_series(min_touches, dtype=float),
            },
        )
        self._series_eval_cache[cache_key] = output
        return output

    def _evaluate_volatility_squeeze(
        self, params: Dict[str, Any]
    ) -> tuple[pd.Series, Dict[str, pd.Series]]:
        cache_key = self._eval_cache_key("volatility_squeeze", params)
        cached = self._series_eval_cache.get(cache_key)
        if cached is not None:
            return cached

        lookback = max(
            4,
            int(
                self._extract_numeric_param(
                    params.get("lookback_candles", params.get("lookback_period", 20)),
                    20,
                )
            ),
        )
        squeeze_ratio = float(
            self._extract_numeric_param(params.get("squeeze_ratio", 0.6), 0.6)
        )
        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        high, low, close = self._timeframe_ohlc_series(timeframe)

        past_len = lookback // 2
        current_len = lookback - past_len
        current_width = (
            high.rolling(window=current_len, min_periods=current_len).max()
            - low.rolling(window=current_len, min_periods=current_len).min()
        )
        current_mid = close.rolling(window=current_len, min_periods=current_len).mean()
        past_high = (
            high.shift(current_len).rolling(window=past_len, min_periods=past_len).max()
        )
        past_low = (
            low.shift(current_len).rolling(window=past_len, min_periods=past_len).min()
        )
        past_mid = (
            close.shift(current_len)
            .rolling(window=past_len, min_periods=past_len)
            .mean()
        )

        current_range_pct = (current_width / current_mid.abs() * 100.0).replace(
            [np.inf, -np.inf], np.nan
        )
        past_range_pct = ((past_high - past_low) / past_mid.abs() * 100.0).replace(
            [np.inf, -np.inf], np.nan
        )
        result = (
            (
                past_range_pct.notna()
                & current_range_pct.notna()
                & (past_range_pct > 0)
                & (current_range_pct <= past_range_pct * squeeze_ratio)
            )
            .fillna(False)
            .astype(bool)
        )

        output = (
            result,
            {
                "is_squeezing": result,
                "current_range_pct": current_range_pct,
                "past_range_pct": past_range_pct,
                "squeeze_ratio": self._constant_series(squeeze_ratio, dtype=float),
            },
        )
        self._series_eval_cache[cache_key] = output
        return output

    def _evaluate_return_to_level(
        self, params: Dict[str, Any]
    ) -> tuple[pd.Series, Dict[str, pd.Series]]:
        cache_key = self._eval_cache_key("return_to_level", params)
        cached = self._series_eval_cache.get(cache_key)
        if cached is not None:
            return cached

        raw_level = params.get("level_source")
        if raw_level is None:
            block_id = params.get("level_block_id")
            if block_id:
                raw_level = {
                    "source": "block_result",
                    "block_id": block_id,
                    "key": "detected_level",
                }

        level_series = self._coerce_numeric_series(
            self._resolve_value_series(raw_level)
        )

        retest_type = (
            str(params.get("retest_type", "touch"))
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        approach_direction = (
            str(params.get("approach_direction", "any")).strip().lower()
        )
        confirmation_time_sec = float(
            self._extract_numeric_param(params.get("confirmation_time_sec", 0), 0)
        )
        cooldown_sec = float(
            self._extract_numeric_param(params.get("cooldown_sec", 60), 60)
        )

        atr = self._get_main_atr_series().astype(float)

        def _get_threshold_series(
            p_type_key, p_val_key, p_legacy_key, default_val, current_atr, current_level
        ):
            val = params.get(p_val_key, params.get(p_legacy_key, default_val))
            if params.get(p_type_key, "atr_multiplier") == "percentage":
                return (val / 100.0) * current_level
            return val * current_atr

        proximity = _get_threshold_series(
            "proximity_type",
            "proximity_value",
            "proximity_multiplier",
            0.1,
            atr,
            level_series,
        )
        departure_threshold = _get_threshold_series(
            "departure_type",
            "departure_value",
            "departure_multiplier",
            1.5,
            atr,
            level_series,
        )

        price_series = self.main_df["close"].astype(float)
        price_np = price_series.to_numpy()
        level_np = level_series.to_numpy()
        prox_np = proximity.to_numpy()
        dept_np = departure_threshold.to_numpy()

        # Use main_df index as basis for timestamps (seconds)
        ts_np = self.main_df.index.view(np.int64) // 10**9

        results = np.zeros(len(price_np), dtype=bool)

        # State machine variables
        departed = False
        departed_above = False
        confirmed_at = 0
        fired_at = 0

        for i in range(len(price_np)):
            lp = price_np[i]
            lvl = level_np[i]
            prx = prox_np[i]
            dpt = dept_np[i]
            curr_ts = ts_np[i]

            if np.isnan(lp) or np.isnan(lvl) or np.isnan(prx):
                continue

            near = abs(lp - lvl) <= prx
            above = lp > lvl

            if retest_type == "touch":
                if not near:
                    confirmed_at = 0
                    continue

                if approach_direction == "from_above" and not above:
                    confirmed_at = 0
                    continue
                if approach_direction == "from_below" and above:
                    confirmed_at = 0
                    continue

                if fired_at > 0 and (curr_ts - fired_at) < cooldown_sec:
                    confirmed_at = 0
                    continue

                if confirmation_time_sec <= 0:
                    results[i] = True
                    fired_at = curr_ts
                    confirmed_at = 0
                else:
                    if confirmed_at == 0:
                        confirmed_at = curr_ts
                    elif (curr_ts - confirmed_at) >= confirmation_time_sec:
                        results[i] = True
                        fired_at = curr_ts
                        confirmed_at = 0

            elif retest_type == "breakout_retest":
                if not departed:
                    if abs(lp - lvl) > dpt:
                        departed = True
                        departed_above = above
                        confirmed_at = 0
                else:
                    if not near:
                        confirmed_at = 0
                        continue

                    if approach_direction == "from_above" and not departed_above:
                        continue
                    if approach_direction == "from_below" and departed_above:
                        continue

                    if fired_at > 0 and (curr_ts - fired_at) < cooldown_sec:
                        continue

                    if confirmation_time_sec <= 0:
                        results[i] = True
                        fired_at = curr_ts
                        confirmed_at = 0
                        departed = False
                    else:
                        if confirmed_at == 0:
                            confirmed_at = curr_ts
                        elif (curr_ts - confirmed_at) >= confirmation_time_sec:
                            results[i] = True
                            fired_at = curr_ts
                            confirmed_at = 0
                            departed = False

        result_series = pd.Series(results, index=self.main_df.index)
        output = (
            result_series,
            {
                "level": level_series,
                "is_near": pd.Series(
                    abs(price_np - level_np) <= prox_np, index=self.main_df.index
                ),
            },
        )
        self._series_eval_cache[cache_key] = output
        return output

    def _evaluate_price_action_analyzer(
        self, params: Dict[str, Any]
    ) -> tuple[pd.Series, Dict[str, pd.Series]]:
        cache_key = self._eval_cache_key("price_action_analyzer", params)
        cached = self._series_eval_cache.get(cache_key)
        if cached is not None:
            return cached

        lookback = max(
            3, int(self._extract_numeric_param(params.get("lookback_candles", 30), 30))
        )
        order = max(1, int(self._extract_numeric_param(params.get("order", 3), 3)))
        min_points = max(
            2, int(self._extract_numeric_param(params.get("min_points", 2), 2))
        )
        structure_type = params.get("structure_type") or "higher_lows"
        required_structure = params.get("required_structure")
        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        high, low, _ = self._timeframe_ohlc_series(timeframe)

        highs_np = high.to_numpy(dtype=float)
        lows_np = low.to_numpy(dtype=float)
        len_data = len(self.main_df.index)

        def shifted(values: np.ndarray, periods: int) -> np.ndarray:
            if periods <= 0:
                return values.copy()
            output = np.full(len(values), np.nan, dtype=float)
            if periods < len(values):
                output[periods:] = values[:-periods]
            return output

        def compute_extrema(
            values: np.ndarray, *, find_min: bool
        ) -> tuple[np.ndarray, np.ndarray, np.ndarray, List[np.ndarray]]:
            count = np.zeros(len_data, dtype=float)
            last = np.full(len_data, np.nan, dtype=float)
            prev = np.full(len_data, np.nan, dtype=float)
            recent = [np.full(len_data, np.nan, dtype=float) for _ in range(min_points)]

            if lookback < (order * 2 + 1):
                return count, last, prev, recent

            valid_window = np.arange(len_data) >= (order * 2)
            max_lag = max(0, lookback - 1 - order)
            for lag in range(max_lag, 0, -1):
                candidate = shifted(values, lag)
                valid = valid_window & np.isfinite(candidate)

                for left_lag in range(lag + 1, lag + order + 1):
                    left = shifted(values, left_lag)
                    valid &= np.isfinite(left)
                    comparison = candidate < left if find_min else candidate > left
                    valid &= comparison

                for right_lag in range(lag - 1, max(lag - order, 0) - 1, -1):
                    right = shifted(values, right_lag)
                    valid &= np.isfinite(right)
                    comparison = candidate < right if find_min else candidate > right
                    valid &= comparison

                if not valid.any():
                    continue

                count += valid.astype(float)
                prev = np.where(valid, last, prev)
                last = np.where(valid, candidate, last)
                for recent_idx in range(min_points - 1):
                    recent[recent_idx] = np.where(
                        valid, recent[recent_idx + 1], recent[recent_idx]
                    )
                recent[-1] = np.where(valid, candidate, recent[-1])

            return count, last, prev, recent

        def points_increasing(points: List[np.ndarray]) -> np.ndarray:
            if not points:
                return np.zeros(len_data, dtype=bool)
            result_mask = np.isfinite(points[0])
            for idx in range(1, len(points)):
                result_mask &= np.isfinite(points[idx])
                result_mask &= points[idx] > points[idx - 1]
            return result_mask

        def points_decreasing(points: List[np.ndarray]) -> np.ndarray:
            if not points:
                return np.zeros(len_data, dtype=bool)
            result_mask = np.isfinite(points[0])
            for idx in range(1, len(points)):
                result_mask &= np.isfinite(points[idx])
                result_mask &= points[idx] < points[idx - 1]
            return result_mask

        highs_count, last_high, prev_high, recent_highs = compute_extrema(
            highs_np, find_min=False
        )
        lows_count, last_low, prev_low, recent_lows = compute_extrema(
            lows_np, find_min=True
        )

        if required_structure == "HH_HL" and params.get("structure_type") is None:
            result = points_increasing(recent_highs) & points_increasing(recent_lows)
        elif required_structure == "LH_LL" and params.get("structure_type") is None:
            result = points_decreasing(recent_highs) & points_decreasing(recent_lows)
        elif structure_type == "higher_lows":
            result = points_increasing(recent_lows)
        elif structure_type == "lower_highs":
            result = points_decreasing(recent_highs)
        else:
            result = np.zeros(len_data, dtype=bool)

        result_series = pd.Series(result, index=self.main_df.index, dtype=bool)
        output = (
            result_series,
            {
                "is_valid": result_series,
                "highs_count": pd.Series(highs_count, index=self.main_df.index),
                "lows_count": pd.Series(lows_count, index=self.main_df.index),
                "last_high": pd.Series(last_high, index=self.main_df.index),
                "prev_high": pd.Series(prev_high, index=self.main_df.index),
                "last_low": pd.Series(last_low, index=self.main_df.index),
                "prev_low": pd.Series(prev_low, index=self.main_df.index),
                "min_points": self._constant_series(min_points, dtype=float),
            },
        )
        self._series_eval_cache[cache_key] = output
        return output

    def _evaluate_round_level(self, params: Dict[str, Any]) -> pd.Series:
        tick_size = self._get_tick_size()
        cache_key = self._eval_cache_key(
            "round_level", {"params": params, "tick_size": tick_size}
        )
        cached = self._series_eval_cache.get(cache_key)
        if isinstance(cached, pd.Series):
            return cached

        proximity_type = str(params.get("proximity_type", "pips")).strip().lower()
        raw_value = params.get("proximity_value", params.get("proximity_pips", 5))
        proximity_value = self._extract_numeric_param(raw_value, 5.0)
        if tick_size <= 0:
            result = pd.Series(False, index=self.main_df.index)
            self._series_eval_cache[cache_key] = result
            return result

        price_values = self.main_df["close"].astype(float).to_numpy()
        results = np.zeros(len(price_values), dtype=bool)
        valid_mask = np.isfinite(price_values) & (price_values > 0)
        if not valid_mask.any():
            result = pd.Series(results, index=self.main_df.index)
            self._series_eval_cache[cache_key] = result
            return result

        if proximity_type == "percentage":
            proximity_pct = proximity_value / 100.0
            min_tick_prox = 1
        else:
            proximity_pct = 0.0
            min_tick_prox = int(proximity_value)
        min_tick_tolerance = min_tick_prox * tick_size

        with np.errstate(divide="ignore", invalid="ignore"):
            price_orders = np.floor(np.log10(price_values[valid_mask])).astype(int)

        valid_indices = np.flatnonzero(valid_mask)
        for price_order in np.unique(price_orders):
            order_indices = valid_indices[price_orders == price_order]
            if len(order_indices) == 0:
                continue

            representative_price = float(price_values[order_indices[0]])
            candidate_levels = _generate_round_levels(
                representative_price,
                tick_size,
                [],
                2,
                None,
                None,
            )
            if not candidate_levels:
                continue

            order_prices = price_values[order_indices]
            order_results = np.zeros(len(order_indices), dtype=bool)
            for round_level in candidate_levels:
                tolerance_abs = round_level * proximity_pct
                final_tolerance = max(tolerance_abs, min_tick_tolerance)
                order_results |= np.abs(order_prices - round_level) <= final_tolerance
                if order_results.all():
                    break

            results[order_indices] = order_results

        result = pd.Series(results, index=self.main_df.index)
        self._series_eval_cache[cache_key] = result
        return result

    def _evaluate_classic_pattern(self, params: Dict[str, Any]) -> pd.Series:
        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        pattern_name = str(params.get("pattern_name", "")).strip().lower()
        side = str(params.get("side", "any")).strip().lower()
        df_tf = self._get_timeframe_df(timeframe)
        if df_tf.empty:
            return pd.Series(False, index=self.main_df.index)

        open_series = df_tf["open"].astype(float)
        high_series = df_tf["high"].astype(float)
        low_series = df_tf["low"].astype(float)
        close_series = df_tf["close"].astype(float)

        prev_open = open_series.shift(1)
        prev_high = high_series.shift(1)
        prev_low = low_series.shift(1)
        prev_close = close_series.shift(1)
        prev_range = prev_high - prev_low
        prev_body = (prev_open - prev_close).abs()
        prev_range_safe = prev_range.replace(0.0, np.nan)
        prev_is_doji = (prev_range < 1e-9) | ((prev_body / prev_range_safe) < 0.1)

        if pattern_name == "bullish_engulfing":
            result = (
                (prev_close < prev_open)
                & (close_series > open_series)
                & (~prev_is_doji.fillna(True))
                & (open_series < prev_close)
                & (close_series > prev_open)
            )
        elif pattern_name == "bearish_engulfing":
            result = (
                (prev_close > prev_open)
                & (close_series < open_series)
                & (~prev_is_doji.fillna(True))
                & (open_series > prev_close)
                & (close_series < prev_open)
            )
        elif pattern_name == "doji":
            candle_range = high_series - low_series
            candle_body = (open_series - close_series).abs()
            candle_range_safe = candle_range.replace(0.0, np.nan)
            result = (candle_range < 1e-9) | ((candle_body / candle_range_safe) < 0.1)
        elif pattern_name == "inside_bar":
            result = (high_series < prev_high) & (low_series > prev_low)
        elif pattern_name == "pin_bar":
            candle_range = high_series - low_series
            candle_range_safe = candle_range.replace(0.0, np.nan)
            candle_body = (open_series - close_series).abs()
            upper_wick = high_series - pd.concat(
                [open_series, close_series], axis=1
            ).max(axis=1)
            lower_wick = (
                pd.concat([open_series, close_series], axis=1).min(axis=1) - low_series
            )
            common_mask = (candle_range >= 1e-9) & (
                (candle_body / candle_range_safe) <= 0.33
            )
            bullish_pin = (
                common_mask
                & ((lower_wick / candle_range_safe) > 0.5)
                & (upper_wick < candle_body)
            )
            bearish_pin = (
                common_mask
                & ((upper_wick / candle_range_safe) > 0.5)
                & (lower_wick < candle_body)
            )
            if side == "bullish":
                result = bullish_pin
            elif side == "bearish":
                result = bearish_pin
            else:
                result = bullish_pin | bearish_pin
        else:
            result = pd.Series(False, index=df_tf.index)

        result = result.fillna(False).astype(bool)
        aligned = (
            self._broadcast_closed_signal_to_main(result)
            if not df_tf.index.equals(self.main_df.index)
            else result.reindex(self.main_df.index)
        )
        return aligned.fillna(False).astype(bool)

    def _ensure_market_features(self) -> None:
        for key, raw_df in list(self.data_context.items()):
            if key == "open_interest" or key.startswith("btc_"):
                continue
            if not isinstance(raw_df, pd.DataFrame) or raw_df.empty:
                continue

            df = raw_df.copy()
            if "relative_volume" not in df.columns:
                df = add_relative_volume(df, period=20)
            if "natr" not in df.columns:
                df = calculate_scalper_natr(df, period=30)
            if "is_volume_spike" not in df.columns:
                df = add_volume_percentile_rank(df, period=1000, percentile=90)
            self.data_context[key] = df

        self.main_df = self.data_context.get(
            "1m", self.data_context.get(self.base_timeframe, self.main_df)
        )

    def _indicator_params_from_key(
        self, key: str, timeframe: str
    ) -> Dict[str, Dict[str, Any]]:
        params: Dict[str, Dict[str, Any]] = {}
        if not isinstance(key, str) or "_" not in key:
            return params

        parts = key.split("_")
        prefix = parts[0].upper()
        try:
            if (
                prefix in {"EMA", "SMA", "RSI", "ADX", "NATR", "ATR"}
                and len(parts) >= 2
            ):
                params[key] = {"period": int(parts[1]), "timeframe": timeframe}
            elif prefix == "MACD" and len(parts) >= 4:
                params[key] = {
                    "fast": int(parts[1]),
                    "slow": int(parts[2]),
                    "signal": int(parts[3]),
                    "timeframe": timeframe,
                }
        except (TypeError, ValueError):
            return {}
        return params

    @staticmethod
    def _compare_numeric_series(
        series: pd.Series, operator: str, threshold: float
    ) -> pd.Series:
        normalized_operator = str(operator or "gt").lower()
        if normalized_operator in {"lt", "<"}:
            return series < threshold
        if normalized_operator in {"gte", "ge", ">="}:
            return series >= threshold
        if normalized_operator in {"lte", "le", "<="}:
            return series <= threshold
        return series > threshold

    def _align_filter_series(self, series: pd.Series, timeframe: str) -> pd.Series:
        if series.index.equals(self.main_df.index):
            return series.reindex(self.main_df.index)
        return self._broadcast_to_1m(series, timeframe)

    def _evaluate_volatility_filter(self, params: Dict[str, Any]) -> pd.Series:
        if "indicator" not in params:
            return evaluate_volatility_filter_vectorized(
                self.main_df,
                self._extract_numeric_param(params.get("value", 0.005), 0.005),
                params.get("operator", "gt"),
            )

        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        df_tf = self._get_timeframe_df(timeframe)
        if df_tf.empty:
            return pd.Series(False, index=self.main_df.index)

        indicator = str(params.get("indicator", "ATR")).upper()
        threshold = self._extract_numeric_param(params.get("value", 0.0), 0.0)
        operator = params.get("operator", "gt")

        if indicator == "ATR":
            period = int(self._extract_numeric_param(params.get("period", 14), 14))
            column = f"ATR_{period}"
            if column in df_tf.columns:
                series = df_tf[column].astype(float)
            elif (
                timeframe in {"1m", self.base_timeframe}
                and column in self.signals.columns
            ):
                series = self.signals[column].astype(float)
            else:
                series = ta.atr(
                    high=df_tf["high"],
                    low=df_tf["low"],
                    close=df_tf["close"],
                    length=period,
                )
                if series is None:
                    return pd.Series(False, index=self.main_df.index)
                series = series.bfill().ffill().fillna(0.0)

            aligned = self._align_filter_series(series, timeframe)
            return self._compare_numeric_series(
                aligned.astype(float), operator, threshold
            ).fillna(False)

        if indicator == "BBW":
            period = int(self._extract_numeric_param(params.get("period", 20), 20))
            std_dev = self._extract_numeric_param(params.get("std_dev", 2.0), 2.0)
            bb_df = ta.bbands(close=df_tf["close"], length=period, std=std_dev)
            if bb_df is None or bb_df.empty:
                return pd.Series(False, index=self.main_df.index)

            lower_col = next(
                (col for col in bb_df.columns if str(col).startswith("BBL")), None
            )
            upper_col = next(
                (col for col in bb_df.columns if str(col).startswith("BBU")), None
            )
            middle_col = next(
                (col for col in bb_df.columns if str(col).startswith("BBM")), None
            )
            if not lower_col or not upper_col or not middle_col:
                return pd.Series(False, index=self.main_df.index)

            middle = bb_df[middle_col].replace(0.0, np.nan)
            series = (
                ((bb_df[upper_col] - bb_df[lower_col]) / middle)
                .bfill()
                .ffill()
                .fillna(0.0)
            )
            aligned = self._align_filter_series(series, timeframe)
            return self._compare_numeric_series(
                aligned.astype(float), operator, threshold
            ).fillna(False)

        return (
            evaluate_volatility_filter_vectorized(
                df_tf,
                threshold,
                operator,
            )
            .pipe(lambda series: self._align_filter_series(series, timeframe))
            .fillna(False)
        )

    def _evaluate_natr_filter(self, params: Dict[str, Any]) -> pd.Series:
        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        df_tf = self._get_timeframe_df(timeframe)
        if df_tf.empty:
            return pd.Series(False, index=self.main_df.index)

        period = int(self._extract_numeric_param(params.get("period", 14), 14))
        threshold = self._extract_numeric_param(
            params.get(
                "value", params.get("threshold", params.get("natr_threshold", 1.0))
            ),
            1.0,
        )
        operator = params.get("operator", "gt")
        column = f"NATR_{period}"

        if column in df_tf.columns:
            series = df_tf[column].astype(float)
        elif (
            timeframe in {"1m", self.base_timeframe} and column in self.signals.columns
        ):
            series = self.signals[column].astype(float)
        else:
            high_low = df_tf["high"] - df_tf["low"]
            close_adj = df_tf["close"].replace(0, 1)
            series = (
                ((high_low / close_adj) * 100.0)
                .rolling(window=period)
                .mean()
                .bfill()
                .ffill()
                .fillna(0.0)
            )

        aligned = self._align_filter_series(series, timeframe)
        return self._compare_numeric_series(
            aligned.astype(float), operator, threshold
        ).fillna(False)

    def _evaluate_rel_vol_filter(self, params: Dict[str, Any]) -> pd.Series:
        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        threshold = self._extract_numeric_param(
            params.get("rel_vol_threshold", 1.5), 1.5
        )
        lookback = int(
            self._extract_numeric_param(params.get("lookback_period", 20), 20.0)
        )

        df_tf = self._get_timeframe_df(timeframe)
        if df_tf.empty:
            return pd.Series(False, index=self.main_df.index)

        if (
            "relative_volume" in df_tf.columns and lookback == 20
        ):  # Use cached if period matches default
            rel_vol = df_tf["relative_volume"]
        else:
            rel_vol = add_relative_volume(df_tf.copy(), lookback)["relative_volume"]

        series = (
            rel_vol
            if timeframe in {"1m", self.base_timeframe}
            else self._broadcast_to_1m(rel_vol, timeframe)
        )
        return series > threshold

    def _evaluate_market_activity(self, params: Dict[str, Any]) -> pd.Series:
        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        df_tf = self._get_timeframe_df(timeframe)
        if df_tf.empty:
            return pd.Series(False, index=self.main_df.index)

        mode = str(params.get("mode", "percentile")).lower()
        natr_threshold = self._extract_numeric_param(
            params.get("natr_threshold", 1.0), 1.0
        )
        natr_series = (
            df_tf["natr"]
            if "natr" in df_tf.columns
            else calculate_scalper_natr(df_tf.copy(), 30)["natr"]
        )
        natr_series = (
            natr_series
            if timeframe in {"1m", self.base_timeframe}
            else self._broadcast_to_1m(natr_series, timeframe)
        )
        natr_ok = natr_series >= natr_threshold

        if mode == "relative":
            rel_vol_threshold = self._extract_numeric_param(
                params.get("rel_vol_threshold", 1.5), 1.5
            )
            rel_vol_series = (
                df_tf["relative_volume"]
                if "relative_volume" in df_tf.columns
                else add_relative_volume(df_tf.copy(), 20)["relative_volume"]
            )
            rel_vol_series = (
                rel_vol_series
                if timeframe in {"1m", self.base_timeframe}
                else self._broadcast_to_1m(rel_vol_series, timeframe)
            )
            volume_ok = rel_vol_series >= rel_vol_threshold
        else:
            spike_series = (
                df_tf["is_volume_spike"]
                if "is_volume_spike" in df_tf.columns
                else add_volume_percentile_rank(df_tf.copy(), 1000, 90)[
                    "is_volume_spike"
                ]
            )
            volume_ok = (
                spike_series
                if timeframe in {"1m", self.base_timeframe}
                else self._broadcast_to_1m(spike_series.astype(bool), timeframe).astype(
                    bool
                )
            )

        return (natr_ok | volume_ok).fillna(False)

    def _evaluate_price_consolidation(self, params: Dict[str, Any]) -> pd.Series:
        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        lookback_period = max(
            1, int(self._extract_numeric_param(params.get("lookback_period", 10), 10))
        )
        max_range_atr = self._extract_numeric_param(
            params.get("max_range_atr", 0.8), 0.8
        )
        df_tf = self._get_timeframe_df(timeframe)
        if df_tf.empty:
            return pd.Series(False, index=self.main_df.index)

        # 1. Use body max/min (ignoring shadows) as in strategy.find_consolidation_zones
        body_max = df_tf[["open", "close"]].max(axis=1)
        body_min = df_tf[["open", "close"]].min(axis=1)

        # 2. Range calculation by bodies (without shift(1), as the signal is taken at the end of candle i for entry at i+1)
        rolling_high = body_max.rolling(window=lookback_period).max()
        rolling_low = body_min.rolling(window=lookback_period).min()
        price_range = rolling_high - rolling_low

        # 3. Use ewm(100) for ATR as in strategy.py (find_consolidation_zones)
        # Calculating TR (True Range)
        tr = pd.DataFrame(index=df_tf.index)
        tr["h-l"] = df_tf["high"] - df_tf["low"]
        tr["h-pc"] = (df_tf["high"] - df_tf["close"].shift(1)).abs()
        tr["l-pc"] = (df_tf["low"] - df_tf["close"].shift(1)).abs()
        tr["tr"] = tr[["h-l", "h-pc", "l-pc"]].max(axis=1)

        # ATR as a moving average of TR with ewm span=100
        atr_series = tr["tr"].ewm(span=100, adjust=False).mean()

        atr_threshold = atr_series * max_range_atr
        result = (price_range <= atr_threshold).fillna(False)

        return (
            result
            if timeframe in {"1m", self.base_timeframe}
            else self._broadcast_to_1m(result.astype(bool), timeframe).astype(bool)
        )

    def _price_consolidation_trace_details(
        self, params: Dict[str, Any]
    ) -> Dict[str, pd.Series]:
        timeframe = str(params.get("timeframe", "auto"))
        if timeframe == "auto":
            timeframe = self.base_timeframe

        lookback_period = max(
            1, int(self._extract_numeric_param(params.get("lookback_period", 10), 10))
        )
        max_range_atr = self._extract_numeric_param(
            params.get("max_range_atr", 0.8), 0.8
        )
        df_tf = self._get_timeframe_df(timeframe)
        if df_tf.empty:
            empty = pd.Series(np.nan, index=self.main_df.index, dtype=float)
            return {
                "detected_level": empty,
                "rolling_high": empty,
                "rolling_low": empty,
                "price_range": empty,
                "atr_threshold": empty,
                "lookback_period": pd.Series(lookback_period, index=self.main_df.index),
                "timeframe": pd.Series(timeframe, index=self.main_df.index),
            }

        body_max = df_tf[["open", "close"]].max(axis=1)
        body_min = df_tf[["open", "close"]].min(axis=1)
        rolling_high = body_max.rolling(window=lookback_period).max()
        rolling_low = body_min.rolling(window=lookback_period).min()
        price_range = rolling_high - rolling_low

        tr = pd.DataFrame(index=df_tf.index)
        tr["h-l"] = df_tf["high"] - df_tf["low"]
        tr["h-pc"] = (df_tf["high"] - df_tf["close"].shift(1)).abs()
        tr["l-pc"] = (df_tf["low"] - df_tf["close"].shift(1)).abs()
        tr["tr"] = tr[["h-l", "h-pc", "l-pc"]].max(axis=1)
        atr_threshold = tr["tr"].ewm(span=100, adjust=False).mean() * max_range_atr
        detected_level = (rolling_high + rolling_low) / 2.0

        def align(series: pd.Series) -> pd.Series:
            if timeframe in {"1m", self.base_timeframe}:
                return series.reindex(self.main_df.index)
            return self._broadcast_to_1m(series, timeframe).reindex(self.main_df.index)

        return {
            "detected_level": align(detected_level),
            "rolling_high": align(rolling_high),
            "rolling_low": align(rolling_low),
            "price_range": align(price_range),
            "atr_threshold": align(atr_threshold),
            "lookback_period": pd.Series(lookback_period, index=self.main_df.index),
            "timeframe": pd.Series(timeframe, index=self.main_df.index),
        }

    def _evaluate_btc_state_filter(self, params: Dict[str, Any]) -> pd.Series:
        required_state = self._normalize_btc_state_value(
            params.get("required_state", "Any")
        )
        if required_state == "Any":
            return pd.Series(True, index=self.main_df.index)

        btc_df = self.data_context.get("btc_1m")
        if not isinstance(btc_df, pd.DataFrame) or btc_df.empty:
            return pd.Series(False, index=self.main_df.index)

        threshold_pct = (
            self._extract_numeric_param(params.get("consolidation_threshold", 1.0), 1.0)
            / 100.0
        )
        btc_close = btc_df["close"].reindex(self.main_df.index, method="ffill")
        btc_sma = (
            btc_df["close"]
            .rolling(window=20, min_periods=20)
            .mean()
            .reindex(self.main_df.index, method="ffill")
        )
        upper_bound = btc_sma * (1 + threshold_pct)
        lower_bound = btc_sma * (1 - threshold_pct)

        state = pd.Series("Consolidation", index=self.main_df.index, dtype="object")
        state = state.mask(btc_close > upper_bound, "Trending Up")
        state = state.mask(btc_close < lower_bound, "Trending Down")
        return (state == required_state).fillna(False)

    def _evaluate_open_interest(self, params: Dict[str, Any]) -> pd.Series:
        oi_df = self.data_context.get("open_interest")
        if isinstance(oi_df, pd.DataFrame):
            if "open_interest" in oi_df.columns:
                oi_series = oi_df["open_interest"]
            elif oi_df.shape[1] >= 1:
                oi_series = oi_df.iloc[:, 0]
            else:
                return pd.Series(False, index=self.main_df.index)
        elif isinstance(oi_df, pd.Series):
            oi_series = oi_df
        else:
            return pd.Series(False, index=self.main_df.index)

        oi_series = oi_series.reindex(self.main_df.index, method="ffill")
        lookback = max(
            2, int(self._extract_numeric_param(params.get("lookback", 5), 5))
        )
        analyze_type = str(params.get("analyze", "change_pct")).lower()
        operator = str(params.get("operator", "gt")).lower()
        value = self._extract_numeric_param(params.get("value", 1.0), 1.0)

        if analyze_type == "absolute_value":
            actual = oi_series
        else:
            actual = oi_series.pct_change(periods=lookback - 1) * 100.0

        if operator == "lt":
            return actual < value
        return actual > value

    def _evaluate_correlation(self, params: Dict[str, Any]) -> pd.Series:
        btc_df = self.data_context.get("btc_1m")
        if not isinstance(btc_df, pd.DataFrame) or btc_df.empty:
            return pd.Series(False, index=self.main_df.index)

        lookback = max(
            2, int(self._extract_numeric_param(params.get("lookback", 50), 50))
        )
        operator = str(params.get("operator", "lt")).lower()
        value = self._extract_numeric_param(params.get("value", 0.7), 0.7)

        main_close = self.main_df["close"]
        btc_close = btc_df["close"].reindex(self.main_df.index, method="ffill")
        corr = main_close.rolling(window=lookback, min_periods=lookback).corr(btc_close)
        if operator == "gt":
            return corr > value
        return corr < value

    def run(self) -> Dict[str, float]:
        if self.main_df.empty:
            return self._get_default_kpis()
        try:
            self._reset_runtime_state()
            self._prepare_data()
            self._generate_signals()
            self._simulate_trades_vectorized_v2()
            return self._calculate_kpis()
        except Exception as e:
            logger.error("FastVectorBacktester failed: %s", e, exc_info=True)
            self._increment_error_counter("ENGINE_EXCEPTION")
            self._append_structured_anomaly(
                "ENGINE_EXCEPTION",
                self.main_df.index[-1] if not self.main_df.empty else datetime.utcnow(),
                f"Unhandled vector backtest exception: {e}",
            )
            return self._get_default_kpis()

    def _prepare_data(self) -> None:
        self._ensure_market_features()
        # Calculation of ATR if missing (always on 1m)
        if "ATR_14" in self.main_df.columns:
            # Ensure no NaNs from external sources
            self.main_df["ATR_14"] = self.main_df["ATR_14"].bfill().fillna(0)

        if (
            "ATR_14" not in self.main_df.columns
            and "ATR_14" not in self.signals.columns
        ):
            try:
                high, low, close = (
                    self.main_df["high"],
                    self.main_df["low"],
                    self.main_df["close"],
                )
                atr = ta.atr(high=high, low=low, close=close, length=14)
                # Fallback for NaNs at the beginning
                atr = atr.fillna(close * 0.01)
                self.signals["ATR_14"] = atr.bfill().fillna(0)
            except Exception as e:
                logger.warning(f"Failed to calculate ATR_14: {e}")
                self.signals["ATR_14"] = self.main_df["close"] * 0.01

        # Extracting indicators from JSON (now with timeframe information)
        required_indicators = {}
        if "entryConditions" in self.strategy_json:
            required_indicators.update(
                self._extract_indicators_from_json(
                    self.strategy_json["entryConditions"]
                )
            )
        if "filters" in self.strategy_json:
            required_indicators.update(
                self._extract_indicators_from_json(self.strategy_json["filters"])
            )

        # Calculation of indicators considering timeframe
        for name, params in required_indicators.items():
            # Create a unique key with timeframe
            tf = params.get("timeframe", self.base_timeframe)
            cache_key = f"{name}_{tf}"

            # Checking cache
            if cache_key in self.broadcasted_cache:
                continue

            # If the indicator is already in main_df, take it and cache it
            if tf == "1m" and name in self.main_df.columns:
                self.broadcasted_cache[cache_key] = self.main_df[name]
                continue
            # If already in signals, cache it too
            if tf == "1m" and name in self.signals.columns:
                self.broadcasted_cache[cache_key] = self.signals[name]
                continue

            try:
                # Get the required DataFrame by timeframe
                if tf not in self.data_context:
                    logger.warning(
                        f"Timeframe {tf} not available, using {self.base_timeframe} instead for {name}"
                    )
                    tf = self.base_timeframe

                df_tf = self.data_context[tf]

                indicator_type = name.split("_")[0].lower()
                close_tf = df_tf["close"]

                result_series = None

                if indicator_type == "ema":
                    result_series = ta.ema(
                        close=close_tf, length=params.get("period")
                    ).bfill()
                elif indicator_type == "sma":
                    result_series = ta.sma(
                        close=close_tf, length=params.get("period")
                    ).bfill()
                elif indicator_type == "rsi":
                    result_series = ta.rsi(
                        close=close_tf, length=params.get("period")
                    ).bfill()
                elif indicator_type == "natr":
                    period = params.get("period", 14)
                    high_low = df_tf["high"] - df_tf["low"]
                    close_adj = df_tf["close"].replace(0, 1)
                    val = (high_low / close_adj) * 100
                    result_series = val.rolling(window=period).mean().bfill()

                elif indicator_type == "atr":
                    period = params.get("period", 14)
                    result_series = ta.atr(
                        high=df_tf["high"],
                        low=df_tf["low"],
                        close=close_tf,
                        length=period,
                    )
                    if result_series is not None:
                        result_series = result_series.bfill()

                elif indicator_type == "adx":
                    period = params.get("period", 14)
                    adx_df = ta.adx(
                        high=df_tf["high"],
                        low=df_tf["low"],
                        close=close_tf,
                        length=period,
                    )
                    if adx_df is not None:
                        result_series = adx_df[f"ADX_{period}"].bfill()

                elif indicator_type == "macd":
                    p1, p2 = params.get("fast", 12), params.get("slow", 26)
                    fast, slow = min(p1, p2), max(p1, p2)
                    macd_df = ta.macd(
                        close=close_tf,
                        fast=fast,
                        slow=slow,
                        signal=params.get("signal", 9),
                    )
                    if macd_df is not None:
                        # Copy all MACD columns (with broadcasting)
                        for col in macd_df.columns:
                            broadcasted_col = self._broadcast_to_1m(
                                macd_df[col].bfill(), tf
                            )
                            col_cache_key = f"{col}_{tf}"
                            self.broadcasted_cache[col_cache_key] = broadcasted_col
                            self.signals[col] = broadcasted_col

                elif indicator_type == "bb":
                    period = params.get("period", 20)
                    std = params.get("std", 2.0)
                    bb_df = ta.bbands(close=close_tf, length=period, std=std)
                    if bb_df is not None:
                        for col in bb_df.columns:
                            broadcasted_col = self._broadcast_to_1m(
                                bb_df[col].bfill(), tf
                            )
                            col_cache_key = f"{col}_{tf}"
                            self.broadcasted_cache[col_cache_key] = broadcasted_col
                            self.signals[col] = broadcasted_col

                elif indicator_type == "stoch":
                    k = params.get("k", 14)
                    d = params.get("d", 3)
                    smooth = params.get("smooth", 3)
                    stoch_df = ta.stoch(
                        high=df_tf["high"],
                        low=df_tf["low"],
                        close=close_tf,
                        k=k,
                        d=d,
                        smooth_k=smooth,
                    )
                    if stoch_df is not None:
                        for col in stoch_df.columns:
                            broadcasted_col = self._broadcast_to_1m(
                                stoch_df[col].bfill(), tf
                            )
                            col_cache_key = f"{col}_{tf}"
                            self.broadcasted_cache[col_cache_key] = broadcasted_col
                            self.signals[col] = broadcasted_col

                # Apply broadcasting for single series
                if result_series is not None:
                    broadcasted = self._broadcast_to_1m(result_series, tf)
                    self.broadcasted_cache[cache_key] = broadcasted
                    self.signals[name] = broadcasted

            except Exception as e:
                logger.warning(f"Failed to calculate {name} on {tf}: {e}")
                pass

        self.signals.ffill(inplace=True)
        # self.signals.fillna(0, inplace=True) # REMOVED: fillna(0) causes false signals on NaN indicators (e.g. price > 0)

    def _extract_indicators_from_json(self, block: Dict[str, Any]) -> Dict[str, Dict]:
        indicators = {}
        if not isinstance(block, dict):
            return indicators
        raw_type = block.get("type", "")
        node_type = normalize_condition_type(raw_type)
        params = block.get("params", {})

        # Extract timeframe (default 1m)
        tf = params.get("timeframe", self.base_timeframe)

        if node_type == "trend_filter":
            if params.get("indicator") == "ADX":
                indicators["ADX_14"] = {"period": 14, "timeframe": tf}
            elif "threshold" in params:
                indicators[f"SMA_{params['threshold']}"] = {
                    "period": params["threshold"],
                    "timeframe": tf,
                }

        elif node_type == "volatility_filter":
            indicator = str(params.get("indicator", "")).upper()
            if indicator == "ATR":
                period = int(params.get("period", 14))
                indicators[f"ATR_{period}"] = {"period": period, "timeframe": tf}

        elif node_type == "natr_filter":
            period = int(params.get("period", 14))
            indicators[f"NATR_{period}"] = {"period": period, "timeframe": tf}

        elif node_type == "adx_filter":
            indicators[f"ADX_{params.get('period', 14)}"] = {
                "period": params.get("period", 14),
                "timeframe": tf,
            }

        elif node_type == "rsi_condition" and "period" in params:
            indicators[f"RSI_{params['period']}"] = {
                "period": params["period"],
                "timeframe": tf,
            }

        elif node_type == "ma_cross_condition":
            indicators[f"EMA_{params.get('fast_period', 9)}"] = {
                "period": params.get("fast_period", 9),
                "timeframe": tf,
            }
            indicators[f"EMA_{params.get('slow_period', 21)}"] = {
                "period": params.get("slow_period", 21),
                "timeframe": tf,
            }

        elif node_type == "bollinger_bands_condition":
            indicators[f"BB_{params.get('period', 20)}"] = {
                "period": params.get("period", 20),
                "std": params.get("std_dev", 2.0),
                "timeframe": tf,
            }

        elif node_type == "stochastic_condition":
            smooth_value = params.get(
                "smooth_k", params.get("smoothing", params.get("slowing", 3))
            )
            indicators[f"STOCH_{params.get('k_period', 14)}"] = {
                "k": params.get("k_period", 14),
                "d": params.get("d_period", 3),
                "smooth": smooth_value,
                "timeframe": tf,
            }

        elif node_type == "macd_condition":
            p1, p2 = params.get("fast_period", 12), params.get("slow_period", 26)
            fast, slow = min(p1, p2), max(p1, p2)
            s = params.get("signal_period", 9)
            indicators[f"MACD_{fast}_{slow}_{s}"] = {
                "fast": fast,
                "slow": slow,
                "signal": s,
                "timeframe": tf,
            }

        elif node_type == "trend_direction":
            f_p = params.get("sma_fast_period") or params.get("fast_period")
            s_p = params.get("sma_slow_period") or params.get("slow_period")
            r_p = params.get("rsi_period", 14)
            if f_p:
                indicators[f"SMA_{f_p}"] = {"period": int(f_p), "timeframe": tf}
            if s_p:
                indicators[f"SMA_{s_p}"] = {"period": int(s_p), "timeframe": tf}
            if r_p:
                indicators[f"RSI_{r_p}"] = {"period": int(r_p), "timeframe": tf}

        elif node_type in {"value_comparison", "price_vs_level"}:
            operand_names = (
                ["price_source", "level_source"]
                if node_type == "price_vs_level"
                else ["leftOperand", "rightOperand"]
            )
            for op in operand_names:
                src = params.get(op, {})
                if isinstance(src, dict) and src.get("source") == "indicator":
                    key = src.get("key", "")
                    indicators.update(
                        self._indicator_params_from_key(key, src.get("timeframe", tf))
                    )

        if "children" in block:
            for child in block.get("children", []):
                indicators.update(self._extract_indicators_from_json(child))
        return indicators

    def _generate_signals(self) -> None:
        entry_conditions = self.strategy_json.get("entryConditions")
        if not entry_conditions:
            return

        self._dynamic_block_results = {}
        self._series_eval_cache = {}
        entry_mask, entry_node_results = (
            self._evaluate_condition_tree_with_node_results(entry_conditions)
        )
        entry_mask = self._coerce_mask_series(entry_mask).fillna(False)
        self._entry_condition_result = entry_mask.copy()
        self._entry_node_results = entry_node_results
        eligible_for_weight_mask = pd.Series(True, index=self.main_df.index, dtype=bool)

        filters_config = self.strategy_json.get("filters")
        if filters_config:
            filter_mask, failed_filter_ids = (
                self._evaluate_condition_tree_with_failures(filters_config)
            )
            filter_mask = self._coerce_mask_series(filter_mask).fillna(False)
            filter_trace_mask, filter_node_results = (
                self._evaluate_condition_tree_with_node_results(filters_config)
            )
            self._filter_condition_result = self._coerce_mask_series(
                filter_trace_mask
            ).fillna(False)
            self._filter_node_results = filter_node_results
            rejected_by_filter_mask = entry_mask.to_numpy() & ~filter_mask.to_numpy()
            self._record_filter_rejections(rejected_by_filter_mask, failed_filter_ids)
            eligible_for_weight_mask = filter_mask
        # Determine direction from initialization.params.direction
        if self.foundation_weights:
            total_weight, foundation_trigger_counts = (
                self._calculate_weight_from_node_results(
                    entry_node_results,
                    eligible_mask=eligible_for_weight_mask,
                )
            )
            self.signals["foundation_total_weight"] = total_weight
            for foundation_id, trigger_count in foundation_trigger_counts.items():
                self.structured_report["event_counters"]["foundation_trigger_counts"][
                    foundation_id
                ] = int(
                    self.structured_report["event_counters"][
                        "foundation_trigger_counts"
                    ].get(foundation_id, 0)
                ) + int(trigger_count)

            effective_threshold = min(
                self.min_total_foundation_weight_threshold,
                self.max_possible_expensive_weight,
            )
            weight_pass_mask = total_weight >= effective_threshold
            rejected_by_weight_mask = eligible_for_weight_mask & ~weight_pass_mask
            self.structured_report["event_counters"]["rejections"][
                "by_weight_threshold"
            ] += int(rejected_by_weight_mask.sum())
            entry_mask = entry_mask & eligible_for_weight_mask & weight_pass_mask
        else:
            entry_mask = entry_mask & eligible_for_weight_mask

        init_params = self.strategy_json.get("initialization", {}).get("params", {})
        direction = init_params.get("direction", "LONG").upper()

        # Oracle logic at Entry
        # Oracle shows market MODE: 1 = amnesia/euphoria (trading), 2 = paranoia (not trading)
        # Mode is the same for LONG and SHORT - trade only when oracle_signal == True (mode 1)
        if self.use_oracle and "oracle_signal" in self.main_df.columns:
            # Entry = Technique + Amnesia mode (for both directions)
            filtered_mask = entry_mask & self._coerce_mask_series(
                self.main_df["oracle_signal"]
            ).fillna(False)

        else:
            filtered_mask = entry_mask

        # Save the signal to the correct key depending on the direction
        self.structured_report["event_counters"]["signals_generated_total"] = int(
            filtered_mask.sum()
        )

        if direction == "SHORT":
            self.signals["enter_short"] = filtered_mask
        else:
            self.signals["enter_long"] = filtered_mask

    def _evaluate_condition_tree(self, node: Dict[str, Any]) -> pd.Series:
        """
        Evaluate condition tree using unified evaluators from condition_core.
        Supports both genetic and visual strategy condition types via aliases.
        """
        raw_type = node.get("type")
        node_type = normalize_condition_type(
            raw_type
        )  # Normalization for backward compatibility
        params = node.get("params", {})

        # Logical operators AND/OR
        if node_type in ["AND", "OR"]:
            children = node.get("children", [])
            if not children:
                return pd.Series(True, index=self.main_df.index)
            results = [
                self._coerce_mask_series(self._evaluate_condition_tree(child))
                for child in children
            ]
            if node_type == "AND":
                return self._coerce_mask_series(np.logical_and.reduce(results))
            else:
                return self._coerce_mask_series(np.logical_or.reduce(results))

        # === FILTERS ===

        if node_type == "trading_session":
            filter_mode = params.get("filter_mode", "session")
            if filter_mode == "hours":
                start = int(params.get("start_hour_utc", 0))
                end = int(params.get("end_hour_utc", 23))
                mode = params.get("mode", "include")
            else:
                session_map = {
                    "london": (7, 16),
                    "new_york": (12, 21),
                    "asia": (0, 9),
                    "sydney": (21, 6),
                }
                session = params.get("session", "london")
                start, end = session_map.get(session, (0, 24))
                mode = "include"

            return evaluate_time_filter_vectorized(self.main_df.index, start, end, mode)

        if node_type == "time_filter":
            # Alias or specific usage
            return evaluate_time_filter_vectorized(
                self.main_df.index,
                int(params.get("start_hour_utc", 0)),
                int(params.get("end_hour_utc", 23)),
                params.get("mode", "include"),
            )

        if node_type == "trend_filter":
            return evaluate_trend_filter_vectorized(
                self.main_df,
                self.signals,
                params.get("indicator", "SMA"),
                float(params.get("threshold", 50)),
            )

        if node_type == "volatility_filter":
            return self._evaluate_volatility_filter(params)

        if node_type == "natr_filter":
            return self._evaluate_natr_filter(params)

        if node_type == "adx_filter":
            return evaluate_adx_filter_vectorized(
                self.main_df,
                self.signals,
                int(params.get("period", 14)),
                float(params.get("threshold", 25)),
                params.get("operator", "gt"),
            )

        # === ENTRY CONDITIONS ===

        if node_type == "ma_cross_condition":
            return evaluate_ma_cross_vectorized(
                self.main_df,
                self.signals,
                int(params.get("fast_period", 9)),
                int(params.get("slow_period", 21)),
                self._normalize_ma_cross_direction(params),
            )

        if node_type == "bollinger_bands_condition":
            check_type = self._normalize_bollinger_check_type(params)
            return evaluate_bollinger_vectorized(
                self.main_df,
                self.signals,
                int(params.get("period", 20)),
                float(params.get("std_dev", 2.0)),
                check_type,
                float(params.get("width_value", 0.01)),
            )

        if node_type == "stochastic_condition":
            normalized_params = self._normalize_stochastic_params(params)
            return evaluate_stochastic_vectorized(
                self.main_df,
                self.signals,
                int(normalized_params.get("k_period", 14)),
                int(normalized_params.get("d_period", 3)),
                int(normalized_params.get("smooth_k", 3)),
                normalized_params.get("operator", "gt"),
                float(normalized_params.get("value", 80)),
                normalized_params.get("line", "k"),
            )

        if node_type == "rsi_condition":
            return evaluate_rsi_vectorized(
                self.main_df,
                self.signals,
                int(params.get("period", 14)),
                params.get("operator", "gt"),
                float(params.get("value", 50)),
            )

        if node_type == "macd_condition":
            return evaluate_macd_vectorized(
                self.main_df,
                self.signals,
                int(params.get("fast_period", 12)),
                int(params.get("slow_period", 26)),
                int(params.get("signal_period", 9)),
                params.get("condition_type", "crossover"),
            )

        if node_type == "trend_direction":
            return evaluate_trend_direction_vectorized(
                self.main_df,
                self.signals,
                int(params.get("sma_fast_period") or params.get("fast_period", 10)),
                int(params.get("sma_slow_period") or params.get("slow_period", 50)),
                int(params.get("rsi_period", 14)),
                float(params.get("rsi_lower_bound", 40)),
                float(params.get("rsi_upper_bound", 60)),
                params.get("direction") or params.get("required_trend") or "long",
            )

        if node_type == "tape_condition":
            return evaluate_tape_condition_vectorized(
                self.main_df,
                params.get("metric", "delta_volume"),
                int(params.get("window_sec", 5)),
                params.get("operator", "gt"),
                float(params.get("threshold", 0.0)),
                int(params.get("avg_lookback_sec", 60)),
            )

        if node_type == "value_comparison":
            return self._evaluate_value_comparison_dynamic(params)

        if node_type == "price_vs_level":
            return self._evaluate_price_vs_level(params)

        if node_type == "rel_vol_filter":
            return self._evaluate_rel_vol_filter(params)

        if node_type == "market_activity":
            return self._evaluate_market_activity(params)

        if node_type == "price_consolidation":
            return self._evaluate_price_consolidation(params)

        if node_type == "significant_level":
            return self._evaluate_significant_level(params)

        if node_type == "local_level":
            return self._evaluate_local_level(params)

        if node_type == "level_touch_analyzer":
            result, _ = self._evaluate_level_touch_analyzer(params)
            return result

        if node_type == "return_to_level":
            result, _ = self._evaluate_return_to_level(params)
            return result

        if node_type == "volatility_squeeze":
            result, _ = self._evaluate_volatility_squeeze(params)
            return result

        if node_type == "price_action_analyzer":
            result, _ = self._evaluate_price_action_analyzer(params)
            return result

        if node_type == "round_level":
            return self._evaluate_round_level(params)

        if node_type == "classic_pattern":
            return self._evaluate_classic_pattern(params)

        if node_type == "btc_state_filter":
            return self._evaluate_btc_state_filter(params)

        if node_type == "open_interest":
            return self._evaluate_open_interest(params)

        if node_type == "correlation":
            return self._evaluate_correlation(params)

        if node_type == "volume_confirmation":
            # Volume confirmation: current volume > average * multiplier
            lookback = int(params.get("lookback_period", 20))
            multiplier = float(params.get("multiplier", 1.5))

            vol = self.main_df["volume"]
            vol_ma = vol.rolling(window=lookback, min_periods=1).mean()

            return vol > (vol_ma * multiplier)

        # Default: return True for unknown types (backwards compatibility)
        # TODO: Add warning logging to track missing types
        logger.warning(
            f"Unknown or unsupported condition type: {raw_type} (normalized: {node_type}) - returning False"
        )
        return pd.Series(False, index=self.main_df.index)

    def _evaluate_value_comparison(self, params):
        return self._evaluate_value_comparison_dynamic(params)

    @staticmethod
    def _normalize_price_mode(raw_value: Any, default: str) -> str:
        value = str(raw_value or default).lower()
        if value in {"percent", "percentage", "percent_from_price"}:
            return "percent_from_price"
        if value in {"atr", "atr_multiplier"}:
            return "atr_multiplier"
        if value in {"rr", "rr_multiplier"}:
            return "rr_multiplier"
        if value in {"fixed", "fixed_price", "price"}:
            return "fixed_price"
        return default

    @staticmethod
    def _normalize_grid_range_type(raw_value: Any) -> str:
        value = str(raw_value or "fixed_prices").lower()
        if value in {"percent", "percentage"}:
            return "percentage"
        if value in {"atr", "atr_multiplier"}:
            return "atr"
        return "fixed_prices"

    @staticmethod
    def _pm_conditions_root(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        params_conditions = block.get("params", {}).get("conditions")
        if isinstance(params_conditions, dict) and params_conditions:
            return params_conditions

        children = block.get("children")
        if isinstance(children, list) and children:
            return {
                "id": f"{block.get('id', 'pm_block')}_root",
                "type": "AND",
                "children": children,
            }
        return None

    @staticmethod
    def _contains_value_source(value: Any, source_name: str) -> bool:
        if isinstance(value, dict):
            if value.get("source") == source_name:
                return True
            return any(
                FastVectorBacktester._contains_value_source(nested, source_name)
                for nested in value.values()
            )
        if isinstance(value, list):
            return any(
                FastVectorBacktester._contains_value_source(item, source_name)
                for item in value
            )
        return False

    def _runtime_position_state_value(self, key: Any, state: Dict[str, Any]) -> Any:
        key_str = str(key or "")
        avg_entry_price = float(state.get("avg_entry_price") or 0.0)
        current_price = float(state.get("current_price") or 0.0)
        is_short = bool(state.get("is_short"))

        if key_str == "entry_price":
            return avg_entry_price
        if key_str == "current_size_qty":
            return state.get(
                "remaining_qty_actual", state.get("remaining_qty_rel", 0.0)
            )
        if key_str == "number_of_entries":
            return state.get("entry_count", 1)
        if key_str == "partial_exits_count":
            return state.get("partial_exits_count", 0)
        if key_str == "time_in_trade_sec":
            entry_dt = pd.Timestamp(state.get("entry_dt"))
            current_dt = pd.Timestamp(state.get("current_dt"))
            return max((current_dt - entry_dt).total_seconds(), 0.0)
        if key_str == "unrealized_pnl_pct":
            if avg_entry_price <= 0:
                return 0.0
            pnl = (
                avg_entry_price - current_price
                if is_short
                else current_price - avg_entry_price
            )
            return (pnl / avg_entry_price) * 100.0
        if key_str == "unrealized_pnl_rr":
            risk_reference = state.get("initial_sl_price")
            if risk_reference is None:
                risk_reference = state.get("curr_sl")
            try:
                risk_per_unit = abs(avg_entry_price - float(risk_reference))
            except (TypeError, ValueError):
                risk_per_unit = 0.0
            if risk_per_unit <= 1e-12:
                return 0.0
            pnl_per_unit = (
                avg_entry_price - current_price
                if is_short
                else current_price - avg_entry_price
            )
            return pnl_per_unit / risk_per_unit
        if key_str == "current_sl_price":
            return state.get("curr_sl")
        if key_str == "take_profit":
            targets = state.get("targets") or []
            pending_targets = [target for target in targets if not target.get("done")]
            return pending_targets[-1].get("price") if pending_targets else None
        return None

    def _resolve_runtime_pm_value(
        self, value: Any, idx: int, state: Dict[str, Any]
    ) -> Any:
        if not isinstance(value, dict) or "source" not in value:
            return value

        source = value.get("source")
        key = value.get("key")
        if source in {"value", "constant"}:
            return value.get("value", key)
        if source == "position_state":
            return self._runtime_position_state_value(key, state)

        series = self._resolve_value_series(value)
        if isinstance(series, pd.Series) and 0 <= idx < len(series):
            resolved = series.iloc[idx]
            return None if pd.isna(resolved) else resolved
        return None

    def _evaluate_runtime_pm_condition(
        self,
        node: Dict[str, Any],
        idx: int,
        state: Dict[str, Any],
        static_mask_cache: Dict[int, np.ndarray],
    ) -> bool:
        if not isinstance(node, dict):
            return True

        node_type = normalize_condition_type(node.get("type"))
        if node_type in {"AND", "OR"}:
            children = node.get("children") or []
            if not children:
                return node_type == "AND"
            results = [
                self._evaluate_runtime_pm_condition(
                    child, idx, state, static_mask_cache
                )
                for child in children
            ]
            return all(results) if node_type == "AND" else any(results)

        if node_type in {"value_comparison", "price_vs_level"}:
            params = node.get("params", {})
            left_key = (
                "price_source" if node_type == "price_vs_level" else "leftOperand"
            )
            right_key = (
                "level_source" if node_type == "price_vs_level" else "rightOperand"
            )
            left = self._resolve_runtime_pm_value(params.get(left_key, {}), idx, state)
            right = self._resolve_runtime_pm_value(
                params.get(right_key, {}), idx, state
            )
            try:
                left_val = float(left)
                right_val = float(right)
            except (TypeError, ValueError):
                return False

            op = self._normalize_comparison_operator(params.get("operator", "gt"))
            if op == "gt":
                return left_val > right_val
            if op == "lt":
                return left_val < right_val
            if op == "gte":
                return left_val >= right_val
            if op == "lte":
                return left_val <= right_val
            if op == "eq":
                return abs(left_val - right_val) < 1e-9
            if op == "ne":
                return abs(left_val - right_val) >= 1e-9
            return False

        if node_type == "position_state":
            params = node.get("params", {})
            position_value = self._runtime_position_state_value(
                params.get("key"), state
            )
            target_value = self._resolve_runtime_pm_value(
                params.get("value"), idx, state
            )
            try:
                left_val = float(position_value)
                right_val = float(target_value)
            except (TypeError, ValueError):
                return False
            return bool(
                self._compare_value_series(
                    pd.Series([left_val]),
                    pd.Series([right_val]),
                    params.get("operator", "gt"),
                ).iloc[0]
            )

        cache_key = id(node)
        mask = static_mask_cache.get(cache_key)
        if mask is None:
            condition_mask, _ = self._evaluate_condition_tree_with_node_results(node)
            mask = self._coerce_mask_series(condition_mask).fillna(False).values
            static_mask_cache[cache_key] = mask
        return bool(mask[idx]) if idx < len(mask) else False

    def _calculate_stop_price(
        self,
        entry_price: float,
        is_short: bool,
        sl_type: str,
        sl_value: float,
        atr_value: float,
    ) -> Optional[float]:
        sl_mode = self._normalize_price_mode(sl_type, "atr_multiplier")
        if sl_mode == "fixed_price":
            return float(sl_value) if float(sl_value) > 0 else None
        if sl_mode == "atr_multiplier":
            if float(sl_value) == 0 or atr_value <= 0:
                return None
            distance = atr_value * float(sl_value)
        else:
            if float(sl_value) == 0:
                return None
            distance = entry_price * (float(sl_value) / 100.0)

        if distance <= 0:
            return None
        return entry_price + distance if is_short else entry_price - distance

    def _calculate_target_price(
        self,
        comparison_price: float,
        is_short: bool,
        target_type: str,
        target_value: float,
        stop_price: Optional[float],
        atr_value: float,
    ) -> Optional[float]:
        if comparison_price <= 0:
            return None

        tp_mode = self._normalize_price_mode(target_type, "rr_multiplier")
        target_value = float(target_value)

        if tp_mode == "fixed_price":
            target_price = target_value
        elif tp_mode == "percent_from_price":
            multiplier = (
                1.0 - (target_value / 100.0)
                if is_short
                else 1.0 + (target_value / 100.0)
            )
            target_price = comparison_price * multiplier
        elif tp_mode == "atr_multiplier":
            if atr_value <= 0:
                return None
            distance = atr_value * target_value
            target_price = (
                comparison_price - distance if is_short else comparison_price + distance
            )
        else:
            if stop_price is None:
                return None
            risk_distance = abs(comparison_price - stop_price)
            if risk_distance <= 1e-12:
                return None
            target_price = (
                comparison_price - (risk_distance * target_value)
                if is_short
                else comparison_price + (risk_distance * target_value)
            )

        if target_price <= 0:
            return None
        if is_short and target_price >= comparison_price:
            return None
        if not is_short and target_price <= comparison_price:
            return None
        return float(target_price)

    def _build_trade_targets(
        self,
        quantity_rel: float,
        entry_price: float,
        stop_price: Optional[float],
        atr_value: float,
        is_short: bool,
        init_params: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if quantity_rel <= 1e-12 or entry_price <= 0:
            return []

        targets: List[Dict[str, Any]] = []
        total_partial_fraction = 0.0

        partial_exits_conf = init_params.get("partial_exits", [])
        if isinstance(partial_exits_conf, list):
            for partial_cfg in partial_exits_conf:
                try:
                    fraction = float(partial_cfg.get("size_pct", 0.0)) / 100.0
                    tp_value = float(partial_cfg.get("tp_value", 0.0))
                except (TypeError, ValueError):
                    continue

                if fraction <= 0:
                    continue

                target_price = self._calculate_target_price(
                    comparison_price=entry_price,
                    is_short=is_short,
                    target_type=partial_cfg.get("tp_type", "rr_multiplier"),
                    target_value=tp_value,
                    stop_price=stop_price,
                    atr_value=atr_value,
                )
                if target_price is None:
                    continue

                targets.append(
                    {
                        "price": target_price,
                        "qty_rel": quantity_rel * fraction,
                        "done": False,
                    }
                )
                total_partial_fraction += fraction

        remaining_fraction = 1.0 - total_partial_fraction
        if remaining_fraction > 0.01:
            try:
                final_tp_value = float(
                    init_params.get("tp_value", init_params.get("tp_value_rr", 2.0))
                )
            except (TypeError, ValueError):
                final_tp_value = 0.0

            final_target = self._calculate_target_price(
                comparison_price=entry_price,
                is_short=is_short,
                target_type=init_params.get("tp_type", "rr_multiplier"),
                target_value=final_tp_value,
                stop_price=stop_price,
                atr_value=atr_value,
            )
            if final_target is not None:
                targets.append(
                    {
                        "price": final_target,
                        "qty_rel": quantity_rel * remaining_fraction,
                        "done": False,
                    }
                )

        targets.sort(key=lambda item: item["price"], reverse=is_short)
        return targets

    def _resolve_grid_bound_price(
        self,
        raw_bound: Any,
        range_type: str,
        reference_price: float,
        atr_value: float,
    ) -> Optional[float]:
        try:
            bound_value = float(raw_bound)
        except (TypeError, ValueError):
            return None

        range_mode = self._normalize_grid_range_type(range_type)
        if range_mode == "percentage":
            return reference_price * (1.0 + bound_value / 100.0)
        if range_mode == "atr":
            if atr_value <= 0:
                return None
            return reference_price + (atr_value * bound_value)
        return bound_value

    def _initialize_grid_orders(
        self,
        reference_price: float,
        quantity_rel: float,
        is_short: bool,
        grid_params: Dict[str, Any],
        atr_value: float,
    ) -> List[Dict[str, Any]]:
        if reference_price <= 0 or quantity_rel <= 0:
            return []

        levels_raw = grid_params.get("grid_levels", grid_params.get("levels", 10))
        try:
            levels = max(int(levels_raw), 1)
        except (TypeError, ValueError):
            levels = 1

        range_type = grid_params.get("range_type", "fixed_prices")
        lower_bound = self._resolve_grid_bound_price(
            grid_params.get("lower_bound"), range_type, reference_price, atr_value
        )
        upper_bound = self._resolve_grid_bound_price(
            grid_params.get("upper_bound"), range_type, reference_price, atr_value
        )
        if lower_bound is None or upper_bound is None:
            return []

        if lower_bound > upper_bound:
            lower_bound, upper_bound = upper_bound, lower_bound

        if levels == 1:
            raw_prices = [(lower_bound + upper_bound) / 2.0]
        else:
            step = (upper_bound - lower_bound) / (levels - 1)
            raw_prices = [lower_bound + (step * idx) for idx in range(levels)]

        candidate_prices: List[float] = []
        seen_prices = set()
        for raw_price in raw_prices:
            rounded_key = round(float(raw_price), 10)
            if rounded_key in seen_prices:
                continue
            if is_short:
                if raw_price > reference_price + 1e-12:
                    candidate_prices.append(float(raw_price))
                    seen_prices.add(rounded_key)
            else:
                if raw_price < reference_price - 1e-12:
                    candidate_prices.append(float(raw_price))
                    seen_prices.add(rounded_key)

        qty_per_level = (quantity_rel * 2.0) / max(levels, 1)
        return [
            {"price": price, "qty_rel": qty_per_level}
            for price in candidate_prices
            if qty_per_level > 1e-12
        ]

    @staticmethod
    def _realized_pnl_rel(
        avg_entry_price: float,
        exit_price: float,
        quantity_rel: float,
        initial_reference_price: float,
        is_short: bool,
    ) -> float:
        if quantity_rel <= 0 or avg_entry_price <= 0 or initial_reference_price <= 0:
            return 0.0
        pnl_abs = (
            (avg_entry_price - exit_price) * quantity_rel
            if is_short
            else (exit_price - avg_entry_price) * quantity_rel
        )
        return pnl_abs / initial_reference_price

    def _simulate_trades_vectorized_v2(self) -> None:
        """Sequential trade simulation with DCA/grid support and TP repricing after scale-ins."""
        init_params = self.strategy_json.get("initialization", {}).get("params", {})
        direction = str(init_params.get("direction", "LONG")).upper()
        is_short = direction == "SHORT"
        signal_key = "enter_short" if is_short else "enter_long"

        if signal_key not in self.signals or not self.signals[signal_key].any():
            self.trade_log = []
            return

        def _to_float(value: Any, default: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        SLIPPAGE_PCT = self.slippage_pct
        np_open = self.main_df["open"].values
        np_high = self.main_df["high"].values
        np_low = self.main_df["low"].values
        np_close = self.main_df["close"].values
        np_oracle = (
            self.main_df["oracle_signal"].values
            if "oracle_signal" in self.main_df.columns
            else None
        )

        if "ATR_14" in self.main_df.columns:
            np_atr = self.main_df["ATR_14"].values
        elif "ATR_14" in self.signals.columns:
            np_atr = self.signals["ATR_14"].values
        else:
            np_atr = np.zeros(len(self.main_df))

        sl_type = init_params.get("sl_type", "atr_multiplier")
        sl_val = _to_float(
            init_params.get("sl_value", init_params.get("sl_value_atr", 1.5)), 1.5
        )
        partial_exits_conf = init_params.get("partial_exits", [])
        if not isinstance(partial_exits_conf, list):
            partial_exits_conf = []
        move_sl_to_be = bool(init_params.get("move_sl_to_be_on_first_tp", False))
        max_hold_candles = int(init_params.get("max_hold_candles", 0) or 0)
        sim_trailing_pct = _to_float(init_params.get("sim_trailing_pct", 0.0), 0.0)
        sim_breakeven_rr = _to_float(init_params.get("sim_breakeven_rr", 0.0), 0.0)
        regime_exit_enabled = bool(init_params.get("regime_exit_enabled", False))
        regime_exit_mode = init_params.get("regime_exit_mode", "close")

        position_management = self.strategy_json.get("positionManagement", [])
        if not isinstance(position_management, list):
            position_management = []

        dca_blocks: List[Dict[str, Any]] = []
        grid_blocks: List[Dict[str, Any]] = []
        move_to_breakeven_blocks: List[Dict[str, Any]] = []
        scale_in_blocks: List[Dict[str, Any]] = []
        conditional_management_blocks: List[Dict[str, Any]] = []
        dca_condition_masks: Dict[int, np.ndarray] = {}
        scale_in_condition_masks: Dict[int, np.ndarray] = {}
        conditional_management_masks: Dict[int, np.ndarray] = {}
        conditional_runtime_static_masks: Dict[int, np.ndarray] = {}
        scale_in_runtime_static_masks: Dict[int, np.ndarray] = {}

        for block in position_management:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")
            if block_type == "dca_management":
                dca_blocks.append(block)
                params = block.get("params", {})
                if (
                    str(params.get("step_type", "percentage")).lower()
                    != "custom_condition"
                ):
                    continue

                condition_root = None
                step_value_condition = params.get("step_value")
                if isinstance(step_value_condition, dict) and step_value_condition.get(
                    "type"
                ):
                    condition_root = step_value_condition
                else:
                    condition_root = self._pm_conditions_root(block)

                if condition_root:
                    condition_mask, _ = self._evaluate_condition_tree_with_node_results(
                        condition_root
                    )
                    dca_condition_masks[id(block)] = (
                        self._coerce_mask_series(condition_mask).fillna(False).values
                    )
            elif block_type == "grid_management":
                grid_blocks.append(block)
            elif block_type == "move_to_breakeven":
                move_to_breakeven_blocks.append(block)
            elif block_type == "scale_in":
                scale_in_blocks.append(block)
                condition_root = self._pm_conditions_root(block)
                if condition_root and not self._contains_value_source(
                    condition_root, "position_state"
                ):
                    condition_mask, _ = self._evaluate_condition_tree_with_node_results(
                        condition_root
                    )
                    scale_in_condition_masks[id(block)] = (
                        self._coerce_mask_series(condition_mask).fillna(False).values
                    )
            elif block_type == "conditional_management":
                conditional_management_blocks.append(block)
                if_conditions = block.get("if_conditions")
                if if_conditions and not self._contains_value_source(
                    if_conditions, "position_state"
                ):
                    condition_mask, _ = self._evaluate_condition_tree_with_node_results(
                        if_conditions
                    )
                    conditional_management_masks[id(block)] = (
                        self._coerce_mask_series(condition_mask).fillna(False).values
                    )

        index_vals = self.main_df.index
        entry_mask = self.signals[signal_key].fillna(False).values

        self.trade_log = []
        potential_entry_locs = np.where(entry_mask)[0]
        last_exit_loc = -1
        len_data = len(np_close)

        for entry_loc in potential_entry_locs:
            # Liquidation check: if the deposit is liquidated — stop all trading
            if self._is_liquidated or self.current_balance <= 0:
                self._check_liquidation()
                break
            if entry_loc <= last_exit_loc:
                self.structured_report["event_counters"]["rejections"][
                    "by_cooldown"
                ] += 1
                continue
            if entry_loc + 1 >= len_data:
                break

            real_entry_idx = entry_loc + 1
            if real_entry_idx >= len_data:
                break
            entry_dt = self._to_python_datetime(index_vals[real_entry_idx])

            if (
                self.trade_start_ts is not None
                and pd.Timestamp(entry_dt) < self.trade_start_ts
            ):
                continue
            entry_price = np_open[real_entry_idx] * (
                1.0 - SLIPPAGE_PCT if is_short else 1.0 + SLIPPAGE_PCT
            )
            atr_val = (
                float(np_atr[max(0, real_entry_idx - 1)])
                if real_entry_idx < len(np_atr)
                else 0.0
            )

            curr_sl = self._calculate_stop_price(
                entry_price=entry_price,
                is_short=is_short,
                sl_type=sl_type,
                sl_value=sl_val,
                atr_value=atr_val,
            )
            if getattr(self, "_debug_loop_count_2", 0) < 5:
                print(f"DEBUG: atr={atr_val}, entry={entry_price}, sl={curr_sl}")
                self._debug_loop_count_2 = getattr(self, "_debug_loop_count_2", 0) + 1

            initial_sl_price = curr_sl
            initial_reference_price = float(entry_price)
            initial_risk_distance = (
                abs(initial_reference_price - curr_sl) if curr_sl is not None else 0.0
            )

            if curr_sl is not None:
                is_slippage_beyond_sl = (
                    is_short and entry_price >= curr_sl - 1e-12
                ) or (not is_short and entry_price <= curr_sl + 1e-12)
                if is_slippage_beyond_sl:
                    self.structured_report["event_counters"]["rejections"][
                        "by_slippage_beyond_sl"
                    ] += 1
                    continue

            avg_entry_price = float(entry_price)
            remaining_qty_rel = 1.0
            total_entered_qty_rel = 1.0
            total_closed_qty_rel = 0.0
            dca_active_sos = 0
            entry_count = 1
            realized_pnl_rel = 0.0
            weighted_exit_sum = 0.0
            exit_reason = "TIMEOUT"
            final_abs_idx = real_entry_idx
            final_exit_price = float(entry_price)
            be_activated = False
            partials_hit = False
            partial_exits_count = 0

            targets = self._build_trade_targets(
                quantity_rel=remaining_qty_rel,
                entry_price=avg_entry_price,
                stop_price=curr_sl,
                atr_value=atr_val,
                is_short=is_short,
                init_params=init_params,
            )
            initial_tp_price = targets[-1]["price"] if targets else None
            actual_base_qty, initial_risk_usd_planned, position_rejection_reason = (
                self._determine_position_size(
                    entry_price=avg_entry_price,
                    stop_price=curr_sl,
                    take_profit=initial_tp_price,
                    init_params=init_params,
                    current_dt=entry_dt,
                    is_short=is_short,
                )
            )
            if actual_base_qty <= 1e-12:
                self._record_position_rejection(position_rejection_reason)
                continue

            entry_balance_usd = self.current_balance
            remaining_qty_actual = actual_base_qty
            total_entered_qty_actual = actual_base_qty
            total_closed_qty_actual = 0.0
            realized_pnl_usd = 0.0
            total_commission_usd = abs(
                avg_entry_price * actual_base_qty * self.commission_pct
            )
            execution_events: List[Dict[str, Any]] = [
                {
                    "timestamp": entry_dt,
                    "price": float(avg_entry_price),
                    "quantity": float(actual_base_qty),
                    "type": "ENTRY",
                }
            ]
            self.structured_report["event_counters"]["trades_opened"] += 1

            pending_grid_orders: List[Dict[str, Any]] = []
            for grid_block in grid_blocks:
                grid_orders = self._initialize_grid_orders(
                    reference_price=avg_entry_price,
                    quantity_rel=1.0,
                    is_short=is_short,
                    grid_params=grid_block.get("params", {}),
                    atr_value=atr_val,
                )
                for order in grid_orders:
                    pending_grid_orders.append({**order, "created_idx": real_entry_idx})

            timeout_limit_idx: Optional[int] = None
            if max_hold_candles > 0:
                timeout_limit_idx = real_entry_idx + max_hold_candles
                end_search = min(len_data, timeout_limit_idx)
            else:
                end_search = len_data

            for i in range(real_entry_idx, end_search):
                o = np_open[i]
                h = np_high[i]
                l = np_low[i]  # noqa: E741
                c = np_close[i]
                candle_atr = float(np_atr[i]) if i < len(np_atr) else atr_val

                if pending_grid_orders and remaining_qty_rel > 1e-12:
                    remaining_grid_orders: List[Dict[str, Any]] = []
                    fill_candidates: List[Dict[str, Any]] = []

                    for order in pending_grid_orders:
                        if i <= int(order.get("created_idx", -1)):
                            remaining_grid_orders.append(order)
                            continue

                        order_price = float(order["price"])
                        fill_price = None
                        if is_short:
                            if h >= order_price:
                                fill_price = max(o, order_price)
                        else:
                            if l <= order_price:
                                fill_price = min(o, order_price)

                        if fill_price is None:
                            remaining_grid_orders.append(order)
                            continue

                        fill_candidates.append(
                            {**order, "fill_price": float(fill_price)}
                        )

                    fill_candidates.sort(
                        key=lambda item: item["price"], reverse=not is_short
                    )

                    for order in fill_candidates:
                        fill_price = float(order["fill_price"])
                        if curr_sl is not None:
                            if (is_short and fill_price >= curr_sl - 1e-12) or (
                                not is_short and fill_price <= curr_sl + 1e-12
                            ):
                                continue

                        add_qty_rel = float(order.get("qty_rel", 0.0))
                        if add_qty_rel <= 1e-12:
                            continue

                        new_remaining_qty = remaining_qty_rel + add_qty_rel
                        avg_entry_price = (
                            (avg_entry_price * remaining_qty_rel)
                            + (fill_price * add_qty_rel)
                        ) / new_remaining_qty
                        remaining_qty_rel = new_remaining_qty
                        total_entered_qty_rel += add_qty_rel
                        add_qty_actual = actual_base_qty * add_qty_rel
                        remaining_qty_actual += add_qty_actual
                        total_entered_qty_actual += add_qty_actual
                        total_commission_usd += abs(
                            fill_price * add_qty_actual * self.commission_pct
                        )
                        execution_events.append(
                            {
                                "timestamp": self._to_python_datetime(index_vals[i]),
                                "price": float(fill_price),
                                "quantity": float(add_qty_actual),
                                "type": "ENTRY",
                            }
                        )
                        entry_count += 1

                        if not partials_hit:
                            targets = self._build_trade_targets(
                                quantity_rel=remaining_qty_rel,
                                entry_price=avg_entry_price,
                                stop_price=curr_sl,
                                atr_value=candle_atr,
                                is_short=is_short,
                                init_params=init_params,
                            )

                    pending_grid_orders = remaining_grid_orders

                # Mid-candle liquidation check (worst-case unrealized PnL)
                worst_price = l if not is_short else h
                unrealized_pnl_usd = (
                    (worst_price - avg_entry_price) * remaining_qty_actual
                    if not is_short
                    else (avg_entry_price - worst_price) * remaining_qty_actual
                )
                # Floating equity check
                if (
                    self.current_balance
                    - total_commission_usd
                    + realized_pnl_usd
                    + unrealized_pnl_usd
                    <= 0
                ):
                    exit_reason = "LIQUIDATION"
                    final_exit_price = worst_price
                    realized_pnl_rel += self._realized_pnl_rel(
                        avg_entry_price=avg_entry_price,
                        exit_price=final_exit_price,
                        quantity_rel=remaining_qty_rel,
                        initial_reference_price=initial_reference_price,
                        is_short=is_short,
                    )
                    realized_pnl_usd += (
                        (avg_entry_price - final_exit_price) * remaining_qty_actual
                        if is_short
                        else (final_exit_price - avg_entry_price) * remaining_qty_actual
                    )
                    total_commission_usd += abs(
                        final_exit_price * remaining_qty_actual * self.commission_pct
                    )
                    weighted_exit_sum += final_exit_price * remaining_qty_rel
                    total_closed_qty_rel += remaining_qty_rel
                    total_closed_qty_actual += remaining_qty_actual
                    execution_events.append(
                        {
                            "timestamp": self._to_python_datetime(index_vals[i]),
                            "price": float(final_exit_price),
                            "quantity": float(remaining_qty_actual),
                            "type": "EXIT",
                        }
                    )
                    remaining_qty_rel = 0.0
                    remaining_qty_actual = 0.0
                    final_abs_idx = i
                    break

                if curr_sl is not None and remaining_qty_rel > 1e-12:
                    sl_hit = h >= curr_sl if is_short else l <= curr_sl
                    if sl_hit:
                        final_exit_price = curr_sl * (
                            1.0 + SLIPPAGE_PCT if is_short else 1.0 - SLIPPAGE_PCT
                        )
                        realized_pnl_rel += self._realized_pnl_rel(
                            avg_entry_price=avg_entry_price,
                            exit_price=final_exit_price,
                            quantity_rel=remaining_qty_rel,
                            initial_reference_price=initial_reference_price,
                            is_short=is_short,
                        )
                        realized_pnl_usd += (
                            (avg_entry_price - final_exit_price) * remaining_qty_actual
                            if is_short
                            else (final_exit_price - avg_entry_price)
                            * remaining_qty_actual
                        )
                        total_commission_usd += abs(
                            final_exit_price
                            * remaining_qty_actual
                            * self.commission_pct
                        )
                        weighted_exit_sum += final_exit_price * remaining_qty_rel
                        total_closed_qty_rel += remaining_qty_rel
                        total_closed_qty_actual += remaining_qty_actual
                        execution_events.append(
                            {
                                "timestamp": self._to_python_datetime(index_vals[i]),
                                "price": float(final_exit_price),
                                "quantity": float(remaining_qty_actual),
                                "type": "EXIT",
                            }
                        )
                        remaining_qty_rel = 0.0
                        remaining_qty_actual = 0.0
                        exit_reason = "STOP_LOSS" if not be_activated else "SL_AT_BE"
                        final_abs_idx = i
                        break

                hit_new_tp = False
                for target in targets:
                    if target.get("done"):
                        continue

                    tp_hit = l <= target["price"] if is_short else h >= target["price"]
                    if not tp_hit:
                        continue

                    close_qty = min(
                        remaining_qty_rel, float(target.get("qty_rel", 0.0))
                    )
                    if close_qty <= 1e-12:
                        target["done"] = True
                        continue

                    exit_price = float(target["price"]) * (
                        1.0 + SLIPPAGE_PCT if is_short else 1.0 - SLIPPAGE_PCT
                    )
                    close_qty_actual = actual_base_qty * close_qty
                    realized_pnl_rel += self._realized_pnl_rel(
                        avg_entry_price=avg_entry_price,
                        exit_price=exit_price,
                        quantity_rel=close_qty,
                        initial_reference_price=initial_reference_price,
                        is_short=is_short,
                    )
                    realized_pnl_usd += (
                        (avg_entry_price - exit_price) * close_qty_actual
                        if is_short
                        else (exit_price - avg_entry_price) * close_qty_actual
                    )
                    total_commission_usd += abs(
                        exit_price * close_qty_actual * self.commission_pct
                    )
                    weighted_exit_sum += exit_price * close_qty
                    total_closed_qty_rel += close_qty
                    total_closed_qty_actual += close_qty_actual
                    execution_events.append(
                        {
                            "timestamp": self._to_python_datetime(index_vals[i]),
                            "price": float(exit_price),
                            "quantity": float(close_qty_actual),
                            "type": "EXIT",
                        }
                    )
                    remaining_qty_rel -= close_qty
                    remaining_qty_actual = max(
                        0.0, remaining_qty_actual - close_qty_actual
                    )
                    target["done"] = True
                    hit_new_tp = True
                    partials_hit = True
                    partial_exits_count += 1
                    final_abs_idx = i
                    final_exit_price = exit_price

                    if remaining_qty_rel <= 1e-9:
                        remaining_qty_rel = 0.0
                        exit_reason = "TAKE_PROFIT"
                        break

                if remaining_qty_rel <= 1e-12:
                    break

                if (
                    move_sl_to_be
                    and hit_new_tp
                    and not be_activated
                    and curr_sl is not None
                ):
                    if is_short:
                        curr_sl = min(curr_sl, avg_entry_price * 0.998)
                    else:
                        curr_sl = max(curr_sl, avg_entry_price * 1.002)
                    be_activated = True

                if (
                    move_to_breakeven_blocks
                    and not be_activated
                    and curr_sl is not None
                ):
                    be_stop = self._maybe_apply_move_to_breakeven(
                        move_to_breakeven_blocks,
                        entry_price=avg_entry_price,
                        reference_stop_price=initial_sl_price,
                        current_sl=curr_sl,
                        atr_value=candle_atr,
                        price_for_check=l if is_short else h,
                        is_short=is_short,
                    )
                    if be_stop is not None:
                        curr_sl = be_stop
                        be_activated = True

                if sim_breakeven_rr > 0 and not be_activated and curr_sl is not None:
                    current_risk = abs(avg_entry_price - curr_sl)
                    if current_risk > 1e-12:
                        dist_passed = (
                            (avg_entry_price - l) if is_short else (h - avg_entry_price)
                        )
                        rr_now = dist_passed / current_risk
                        if rr_now >= sim_breakeven_rr:
                            if is_short:
                                curr_sl = min(curr_sl, avg_entry_price * 0.998)
                            else:
                                curr_sl = max(curr_sl, avg_entry_price * 1.002)
                            be_activated = True

                if sim_trailing_pct > 0 and curr_sl is not None:
                    if is_short:
                        new_sl = l * (1.0 + sim_trailing_pct)
                        if new_sl < curr_sl:
                            curr_sl = new_sl
                    else:
                        new_sl = h * (1.0 - sim_trailing_pct)
                        if new_sl > curr_sl:
                            curr_sl = new_sl

                if (
                    self.use_oracle
                    and regime_exit_enabled
                    and np_oracle is not None
                    and remaining_qty_rel > 1e-12
                ):
                    oracle_exit_signal = not bool(np_oracle[i])
                    if oracle_exit_signal:
                        if regime_exit_mode == "close":
                            final_abs_idx = min(i + 1, len_data - 1)
                            final_exit_price = np_open[final_abs_idx] * (
                                1.0 + SLIPPAGE_PCT if is_short else 1.0 - SLIPPAGE_PCT
                            )
                            realized_pnl_rel += self._realized_pnl_rel(
                                avg_entry_price=avg_entry_price,
                                exit_price=final_exit_price,
                                quantity_rel=remaining_qty_rel,
                                initial_reference_price=initial_reference_price,
                                is_short=is_short,
                            )
                            realized_pnl_usd += (
                                (avg_entry_price - final_exit_price)
                                * remaining_qty_actual
                                if is_short
                                else (final_exit_price - avg_entry_price)
                                * remaining_qty_actual
                            )
                            total_commission_usd += abs(
                                final_exit_price
                                * remaining_qty_actual
                                * self.commission_pct
                            )
                            weighted_exit_sum += final_exit_price * remaining_qty_rel
                            total_closed_qty_rel += remaining_qty_rel
                            total_closed_qty_actual += remaining_qty_actual
                            execution_events.append(
                                {
                                    "timestamp": self._to_python_datetime(
                                        index_vals[final_abs_idx]
                                    ),
                                    "price": float(final_exit_price),
                                    "quantity": float(remaining_qty_actual),
                                    "type": "EXIT",
                                }
                            )
                            remaining_qty_rel = 0.0
                            remaining_qty_actual = 0.0
                            exit_reason = "ORACLE_EXIT"
                            break

                        if (
                            regime_exit_mode == "breakeven"
                            and not be_activated
                            and curr_sl is not None
                        ):
                            if is_short:
                                curr_sl = min(curr_sl, avg_entry_price * 0.998)
                            else:
                                curr_sl = max(curr_sl, avg_entry_price * 1.002)
                            be_activated = True

                if remaining_qty_rel > 1e-12 and conditional_management_blocks:
                    runtime_state = {
                        "avg_entry_price": avg_entry_price,
                        "current_price": c,
                        "curr_sl": curr_sl,
                        "initial_sl_price": initial_sl_price,
                        "remaining_qty_rel": remaining_qty_rel,
                        "remaining_qty_actual": remaining_qty_actual,
                        "entry_count": entry_count,
                        "partial_exits_count": partial_exits_count,
                        "entry_dt": entry_dt,
                        "current_dt": self._to_python_datetime(index_vals[i]),
                        "is_short": is_short,
                        "targets": targets,
                    }

                    for conditional_block in conditional_management_blocks:
                        if_conditions = conditional_block.get("if_conditions")
                        if not if_conditions:
                            continue

                        mask = conditional_management_masks.get(id(conditional_block))
                        condition_met = (
                            bool(mask[i])
                            if mask is not None and i < len(mask)
                            else self._evaluate_runtime_pm_condition(
                                if_conditions,
                                i,
                                runtime_state,
                                conditional_runtime_static_masks,
                            )
                        )
                        if not condition_met:
                            continue

                        then_actions = conditional_block.get("then_actions") or []
                        if not isinstance(then_actions, list):
                            continue

                        for action in then_actions:
                            if not isinstance(action, dict):
                                continue
                            action_type = action.get("type")
                            action_params = action.get("params", {})
                            if not isinstance(action_params, dict):
                                action_params = {}

                            if action_type == "modify_stop_loss":
                                new_sl = self._resolve_runtime_pm_value(
                                    action_params.get("new_sl_price"), i, runtime_state
                                )
                                try:
                                    new_sl_float = float(new_sl)
                                except (TypeError, ValueError):
                                    continue
                                if new_sl_float > 0:
                                    curr_sl = new_sl_float
                                    runtime_state["curr_sl"] = curr_sl

                            elif action_type == "modify_take_profit":
                                new_tp = self._resolve_runtime_pm_value(
                                    action_params.get("new_tp_price"), i, runtime_state
                                )
                                try:
                                    new_tp_float = float(new_tp)
                                except (TypeError, ValueError):
                                    continue
                                if new_tp_float <= 0:
                                    continue

                                pending_targets = [
                                    target
                                    for target in targets
                                    if not target.get("done")
                                ]
                                if pending_targets:
                                    pending_targets[-1]["price"] = new_tp_float
                                    targets.sort(
                                        key=lambda item: item["price"], reverse=is_short
                                    )
                                elif remaining_qty_rel > 1e-12:
                                    targets = [
                                        {
                                            "price": new_tp_float,
                                            "qty_rel": remaining_qty_rel,
                                            "done": False,
                                        }
                                    ]
                                runtime_state["targets"] = targets

                            elif action_type == "close_position":
                                final_exit_price = c * (
                                    1.0 + SLIPPAGE_PCT
                                    if is_short
                                    else 1.0 - SLIPPAGE_PCT
                                )
                                realized_pnl_rel += self._realized_pnl_rel(
                                    avg_entry_price=avg_entry_price,
                                    exit_price=final_exit_price,
                                    quantity_rel=remaining_qty_rel,
                                    initial_reference_price=initial_reference_price,
                                    is_short=is_short,
                                )
                                realized_pnl_usd += (
                                    (avg_entry_price - final_exit_price)
                                    * remaining_qty_actual
                                    if is_short
                                    else (final_exit_price - avg_entry_price)
                                    * remaining_qty_actual
                                )
                                total_commission_usd += abs(
                                    final_exit_price
                                    * remaining_qty_actual
                                    * self.commission_pct
                                )
                                weighted_exit_sum += (
                                    final_exit_price * remaining_qty_rel
                                )
                                total_closed_qty_rel += remaining_qty_rel
                                total_closed_qty_actual += remaining_qty_actual
                                execution_events.append(
                                    {
                                        "timestamp": self._to_python_datetime(
                                            index_vals[i]
                                        ),
                                        "price": float(final_exit_price),
                                        "quantity": float(remaining_qty_actual),
                                        "type": "EXIT",
                                    }
                                )
                                remaining_qty_rel = 0.0
                                remaining_qty_actual = 0.0
                                exit_reason = "PM_ACTION_CLOSE"
                                final_abs_idx = i
                                break

                        if remaining_qty_rel <= 1e-12:
                            break

                if remaining_qty_rel <= 1e-12:
                    break

                if remaining_qty_rel > 1e-12 and scale_in_blocks:
                    for scale_in_block in scale_in_blocks:
                        params = scale_in_block.get("params", {})
                        try:
                            max_entries = max(int(params.get("max_entries", 1) or 1), 1)
                        except (TypeError, ValueError):
                            max_entries = 1
                        if entry_count >= max_entries:
                            continue

                        condition_root = self._pm_conditions_root(scale_in_block)
                        mask = scale_in_condition_masks.get(id(scale_in_block))
                        if mask is not None:
                            condition_met = bool(mask[i]) if i < len(mask) else False
                        elif condition_root:
                            runtime_state = {
                                "avg_entry_price": avg_entry_price,
                                "current_price": c,
                                "curr_sl": curr_sl,
                                "initial_sl_price": initial_sl_price,
                                "remaining_qty_rel": remaining_qty_rel,
                                "remaining_qty_actual": remaining_qty_actual,
                                "entry_count": entry_count,
                                "partial_exits_count": partial_exits_count,
                                "entry_dt": entry_dt,
                                "current_dt": self._to_python_datetime(index_vals[i]),
                                "is_short": is_short,
                                "targets": targets,
                            }
                            condition_met = self._evaluate_runtime_pm_condition(
                                condition_root,
                                i,
                                runtime_state,
                                scale_in_runtime_static_masks,
                            )
                        else:
                            condition_met = False
                        if not condition_met:
                            continue

                        add_size_pct = _to_float(
                            params.get("add_size_pct_of_initial_risk", 100.0), 100.0
                        )
                        if add_size_pct <= 0:
                            continue

                        if curr_sl is None:
                            add_qty_rel = (
                                (add_size_pct / 100.0) * (initial_reference_price / c)
                                if c > 0
                                else 0.0
                            )
                        else:
                            stop_loss_distance = abs(c - curr_sl)
                            if stop_loss_distance <= 1e-12:
                                continue
                            add_qty_rel = (
                                initial_risk_distance * (add_size_pct / 100.0)
                            ) / stop_loss_distance

                        if add_qty_rel <= 1e-12:
                            continue

                        fill_price = c * (
                            1.0 - SLIPPAGE_PCT if is_short else 1.0 + SLIPPAGE_PCT
                        )
                        if curr_sl is not None:
                            if (is_short and fill_price >= curr_sl - 1e-12) or (
                                not is_short and fill_price <= curr_sl + 1e-12
                            ):
                                continue

                        new_remaining_qty = remaining_qty_rel + add_qty_rel
                        avg_entry_price = (
                            (avg_entry_price * remaining_qty_rel)
                            + (fill_price * add_qty_rel)
                        ) / new_remaining_qty
                        remaining_qty_rel = new_remaining_qty
                        total_entered_qty_rel += add_qty_rel
                        add_qty_actual = actual_base_qty * add_qty_rel
                        remaining_qty_actual += add_qty_actual
                        total_entered_qty_actual += add_qty_actual
                        total_commission_usd += abs(
                            fill_price * add_qty_actual * self.commission_pct
                        )
                        execution_events.append(
                            {
                                "timestamp": self._to_python_datetime(index_vals[i]),
                                "price": float(fill_price),
                                "quantity": float(add_qty_actual),
                                "type": "ENTRY",
                            }
                        )
                        entry_count += 1

                        if not partials_hit:
                            targets = self._build_trade_targets(
                                quantity_rel=remaining_qty_rel,
                                entry_price=avg_entry_price,
                                stop_price=curr_sl,
                                atr_value=candle_atr,
                                is_short=is_short,
                                init_params=init_params,
                            )
                        break

                if remaining_qty_rel > 1e-12 and dca_blocks:
                    for dca_block in dca_blocks:
                        params = dca_block.get("params", {})
                        max_sos = int(params.get("max_safety_orders", 0) or 0)
                        if dca_active_sos >= max_sos:
                            continue

                        step_type = str(params.get("step_type", "percentage")).lower()
                        step_multiplier = _to_float(
                            params.get("step_multiplier", 1.0), 1.0
                        )
                        active_step_multiplier = step_multiplier**dca_active_sos
                        trigger_so = False

                        if step_type == "percentage":
                            step_value = _to_float(params.get("step_value", 1.0), 1.0)
                            target_step_value = step_value * active_step_multiplier
                            deviation_pct = (
                                abs(c - avg_entry_price) / avg_entry_price * 100.0
                                if avg_entry_price > 0
                                else 0.0
                            )
                            if deviation_pct >= target_step_value:
                                if (not is_short and c < avg_entry_price) or (
                                    is_short and c > avg_entry_price
                                ):
                                    trigger_so = True
                        elif step_type == "atr":
                            step_value = _to_float(params.get("step_value", 1.0), 1.0)
                            target_step_value = step_value * active_step_multiplier
                            deviation_abs = abs(c - avg_entry_price)
                            if (
                                candle_atr > 0
                                and deviation_abs >= candle_atr * target_step_value
                            ):
                                if (not is_short and c < avg_entry_price) or (
                                    is_short and c > avg_entry_price
                                ):
                                    trigger_so = True
                        elif step_type == "custom_condition":
                            mask = dca_condition_masks.get(id(dca_block))
                            trigger_so = (
                                bool(mask[i])
                                if mask is not None and i < len(mask)
                                else False
                            )

                        if not trigger_so:
                            continue

                        vol_mult = _to_float(params.get("volume_multiplier", 1.0), 1.0)
                        add_size_pct = 100.0 * (vol_mult ** (dca_active_sos + 1))

                        if curr_sl is None:
                            add_qty_rel = (
                                (add_size_pct / 100.0) * (initial_reference_price / c)
                                if c > 0
                                else 0.0
                            )
                        else:
                            stop_loss_distance = abs(c - curr_sl)
                            if stop_loss_distance <= 1e-12:
                                continue
                            add_qty_rel = (
                                initial_risk_distance * (add_size_pct / 100.0)
                            ) / stop_loss_distance

                        if add_qty_rel <= 1e-12:
                            continue

                        fill_price = c * (
                            1.0 - SLIPPAGE_PCT if is_short else 1.0 + SLIPPAGE_PCT
                        )
                        if curr_sl is not None:
                            if (is_short and fill_price >= curr_sl - 1e-12) or (
                                not is_short and fill_price <= curr_sl + 1e-12
                            ):
                                continue

                        new_remaining_qty = remaining_qty_rel + add_qty_rel
                        avg_entry_price = (
                            (avg_entry_price * remaining_qty_rel)
                            + (fill_price * add_qty_rel)
                        ) / new_remaining_qty
                        remaining_qty_rel = new_remaining_qty
                        total_entered_qty_rel += add_qty_rel
                        add_qty_actual = actual_base_qty * add_qty_rel
                        remaining_qty_actual += add_qty_actual
                        total_entered_qty_actual += add_qty_actual
                        total_commission_usd += abs(
                            fill_price * add_qty_actual * self.commission_pct
                        )
                        execution_events.append(
                            {
                                "timestamp": self._to_python_datetime(index_vals[i]),
                                "price": float(fill_price),
                                "quantity": float(add_qty_actual),
                                "type": "ENTRY",
                            }
                        )
                        dca_active_sos += 1
                        entry_count += 1

                        if not partials_hit:
                            targets = self._build_trade_targets(
                                quantity_rel=remaining_qty_rel,
                                entry_price=avg_entry_price,
                                stop_price=curr_sl,
                                atr_value=candle_atr,
                                is_short=is_short,
                                init_params=init_params,
                            )
                        break
            else:
                final_abs_idx = min(end_search, len_data - 1)
                if remaining_qty_rel > 1e-12:
                    final_exit_price = np_close[final_abs_idx] * (
                        1.0 + SLIPPAGE_PCT if is_short else 1.0 - SLIPPAGE_PCT
                    )
                    realized_pnl_rel += self._realized_pnl_rel(
                        avg_entry_price=avg_entry_price,
                        exit_price=final_exit_price,
                        quantity_rel=remaining_qty_rel,
                        initial_reference_price=initial_reference_price,
                        is_short=is_short,
                    )
                    realized_pnl_usd += (
                        (avg_entry_price - final_exit_price) * remaining_qty_actual
                        if is_short
                        else (final_exit_price - avg_entry_price) * remaining_qty_actual
                    )
                    total_commission_usd += abs(
                        final_exit_price * remaining_qty_actual * self.commission_pct
                    )
                    weighted_exit_sum += final_exit_price * remaining_qty_rel
                    total_closed_qty_rel += remaining_qty_rel
                    total_closed_qty_actual += remaining_qty_actual
                    execution_events.append(
                        {
                            "timestamp": self._to_python_datetime(
                                index_vals[final_abs_idx]
                            ),
                            "price": float(final_exit_price),
                            "quantity": float(remaining_qty_actual),
                            "type": "EXIT",
                        }
                    )
                    remaining_qty_rel = 0.0
                    remaining_qty_actual = 0.0
                exit_reason = (
                    "TIMEOUT"
                    if timeout_limit_idx is not None and timeout_limit_idx < len_data
                    else "END_OF_DATA"
                )

            commission_val = self.commission_pct * (
                total_entered_qty_rel + total_closed_qty_rel
            )
            net_pnl = realized_pnl_rel - commission_val
            net_pnl_usd = realized_pnl_usd - total_commission_usd
            balance_return_pct = (
                (net_pnl_usd / entry_balance_usd) if entry_balance_usd > 1e-12 else 0.0
            )
            avg_exit_price = (
                weighted_exit_sum / total_closed_qty_rel
                if total_closed_qty_rel > 1e-12
                else final_exit_price
            )

            exit_dt = self._to_python_datetime(index_vals[final_abs_idx])
            self.current_balance += net_pnl_usd
            self.total_pnl_usd += net_pnl_usd
            self.total_commission_usd += total_commission_usd

            # Liquidation check after each trade
            if self.current_balance <= 0:
                self.current_balance = 0.0
                self._is_liquidated = True
                self.is_trading_allowed = False
                self.max_drawdown = 1.0  # 100% drawdown
                self.equity_curve.append((exit_dt, 0.0))
                logger.warning(
                    "LIQUIDATION at %s: balance depleted after trade PnL=%.2f USD",
                    exit_dt,
                    net_pnl_usd,
                )
            else:
                self.peak_equity = max(self.peak_equity, self.current_balance)
                if self.peak_equity > 1e-12:
                    drawdown = (
                        self.peak_equity - self.current_balance
                    ) / self.peak_equity
                    self.max_drawdown = max(self.max_drawdown, drawdown)
                self.equity_curve.append((exit_dt, float(self.current_balance)))

            self._check_risk_limits_after_trade(net_pnl_usd, exit_dt)

            self.trade_log.append(
                {
                    "symbol": self.symbol,
                    "strategy": self.strategy_name,
                    "signal_time": self._to_python_datetime(index_vals[entry_loc]),
                    "entry_time": entry_dt,
                    "exit_time": exit_dt,
                    "pnl_pct": net_pnl,
                    "balance_return_pct": balance_return_pct,
                    "pnl_usd": net_pnl_usd,
                    "entry_price": avg_entry_price,
                    "initial_entry_price": initial_reference_price,
                    "avg_entry_price": avg_entry_price,
                    "exit_price": avg_exit_price,
                    "exit_reason": exit_reason,
                    "direction": direction,
                    "quantity": total_entered_qty_rel,
                    "filled_quantity": total_entered_qty_actual,
                    "closed_quantity": total_closed_qty_actual,
                    "commission_usd": total_commission_usd,
                    "current_balance": entry_balance_usd,
                    "balance_after_trade": self.current_balance,
                    "initial_risk_usd_planned": initial_risk_usd_planned,
                    "entry_count": entry_count,
                    "decision_trace": self._build_decision_trace_for_index(
                        entry_loc, direction
                    ),
                    "executions": execution_events,
                }
            )

            if (
                exit_reason == "SL_AT_BE"
                and config.PHANTOM_TRACKING_ENABLED
                and initial_tp_price is not None
                and initial_sl_price is not None
            ):
                phantom_result = self._simulate_phantom_trade(
                    np_high=np_high,
                    np_low=np_low,
                    np_close=np_close,
                    index_vals=index_vals,
                    start_idx=final_abs_idx + 1,
                    end_idx=len_data,
                    entry_price=initial_reference_price,
                    initial_sl=initial_sl_price,
                    initial_tp=initial_tp_price,
                    is_short=is_short,
                    direction=direction,
                    be_exit_price=curr_sl
                    if curr_sl is not None
                    else initial_reference_price,
                    be_exit_time=index_vals[final_abs_idx],
                    trade_entry_time=index_vals[real_entry_idx],
                )
                if phantom_result:
                    self.phantom_log.append(phantom_result)

            last_exit_loc = final_abs_idx

    def _simulate_trades_vectorized(self) -> None:
        self._simulate_trades_vectorized_v2()
        return
        """
        FULL TRADE SIMULATION (LONG and SHORT).
        Includes:
        1. TP / SL / Partials
        2. Trailing Stop
        3. Oracle Exit
        4. Breakeven by RR
        5. Timeouts
        6. SHORT positions
        """
        # Determine direction from strategy
        init_params = self.strategy_json.get("initialization", {}).get("params", {})
        direction = init_params.get("direction", "LONG").upper()
        is_short = direction == "SHORT"

        # Selecting the required signal
        signal_key = "enter_short" if is_short else "enter_long"

        if signal_key not in self.signals or not self.signals[signal_key].any():
            self.trade_log = []
            return

        SLIPPAGE_PCT = 0.0006

        np_open = self.main_df["open"].values
        np_high = self.main_df["high"].values
        np_low = self.main_df["low"].values
        np_close = self.main_df["close"].values

        # For Oracle
        np_oracle = (
            self.main_df["oracle_signal"].values
            if "oracle_signal" in self.main_df.columns
            else None
        )

        # ATR can be either in main_df or in signals
        if "ATR_14" in self.main_df.columns:
            np_atr = self.main_df["ATR_14"].values
        elif "ATR_14" in self.signals.columns:
            np_atr = self.signals["ATR_14"].values
        else:
            np_atr = np.zeros(len(self.main_df))

        index_vals = self.main_df.index
        entry_mask = self.signals[signal_key].values  # NumPy array

        # STRATEGY PARAMETERS
        sl_type = init_params.get("sl_type", "atr_multiplier")
        sl_val = float(
            init_params.get("sl_value", init_params.get("sl_value_atr", 1.5))
        )
        tp_val = float(init_params.get("tp_value", init_params.get("tp_value_rr", 2.0)))

        partial_exits_conf = init_params.get("partial_exits", [])
        move_sl_to_be = init_params.get("move_sl_to_be_on_first_tp", False)

        # NEW MANAGEMENT PARAMETERS
        max_hold_candles = int(init_params.get("max_hold_candles", 0))

        # Trailing
        sim_trailing_pct = float(init_params.get("sim_trailing_pct", 0.0))

        # Breakeven by RR (without profit taking)
        sim_breakeven_rr = float(init_params.get("sim_breakeven_rr", 0.0))

        # Exit by Oracle (Regime Exit)
        regime_exit_enabled = init_params.get("regime_exit_enabled", False)
        regime_exit_mode = init_params.get(
            "regime_exit_mode", "close"
        )  # 'close' or 'breakeven'

        self.trade_log = []
        potential_entry_locs = np.where(entry_mask)[0]
        last_exit_loc = -1

        len_data = len(np_close)

        for entry_loc in potential_entry_locs:
            if entry_loc <= last_exit_loc:
                continue
            if entry_loc + 1 >= len_data:
                break

            # Entry (on the next candle after the signal)
            real_entry_idx = entry_loc + 1

            # For LONG: buy more expensive (entry price + slippage)
            # For SHORT: sell cheaper (entry price - slippage)
            if is_short:
                entry_price = np_open[real_entry_idx] * (1.0 - SLIPPAGE_PCT)
            else:
                entry_price = np_open[real_entry_idx] * (1.0 + SLIPPAGE_PCT)

            # SL distance calculation
            atr_val = np_atr[entry_loc]
            sl_dist = (
                atr_val * sl_val
                if sl_type == "atr_multiplier"
                else entry_price * (sl_val / 100.0)
            )

            # For LONG: SL below entry price
            # For SHORT: SL above entry price
            if is_short:
                sl_price = entry_price + sl_dist
                curr_sl = sl_price
                initial_risk = sl_price - entry_price
            else:
                sl_price = entry_price - sl_dist
                curr_sl = sl_price
                initial_risk = entry_price - sl_price

            if initial_risk <= 0:
                continue

            # Targets (TP)
            targets = []
            total_partial_weight = 0.0

            for pt in partial_exits_conf:
                w = float(pt.get("size_pct", 0)) / 100.0
                p_val = float(pt.get("tp_value", 1.0))

                # For LONG: TP above entry price
                # For SHORT: TP below entry price
                if is_short:
                    t_price = entry_price - (initial_risk * p_val)
                    if t_price < entry_price and w > 0:
                        targets.append({"price": t_price, "weight": w, "done": False})
                        total_partial_weight += w
                else:
                    t_price = entry_price + (initial_risk * p_val)
                    if t_price > entry_price and w > 0:
                        targets.append({"price": t_price, "weight": w, "done": False})
                        total_partial_weight += w

            rem_weight = 1.0 - total_partial_weight
            if rem_weight > 0.01 and tp_val > 0:
                if is_short:
                    f_price = entry_price - (initial_risk * tp_val)
                else:
                    f_price = entry_price + (initial_risk * tp_val)
                targets.append({"price": f_price, "weight": rem_weight, "done": False})

            # Sorting: for LONG ascending, for SHORT descending
            if is_short:
                targets.sort(key=lambda x: x["price"], reverse=True)
            else:
                targets.sort(key=lambda x: x["price"])

            # Save initial levels for phantom tracking
            initial_sl_price = sl_price
            initial_tp_price = (
                targets[-1]["price"] if targets else None
            )  # Last target = final TP

            # Simulation
            cum_pnl = 0.0
            closed_weight = 0.0
            exit_reason = "TIMEOUT"
            final_abs_idx = real_entry_idx

            end_search = len_data

            timeout_limit_idx: Optional[int] = None
            if max_hold_candles > 0:
                timeout_limit_idx = real_entry_idx + max_hold_candles
                end_search = min(len_data, timeout_limit_idx)
            else:
                end_search = len_data

            be_activated = False  # Breakeven activation flag

            for i in range(real_entry_idx, end_search):
                h = np_high[i]
                l = np_low[i]  # noqa: E741

                # 1. STOP LOSS
                # LONG: SL triggers when l <= curr_sl
                # SHORT: SL triggers when h >= curr_sl
                sl_hit = h >= curr_sl if is_short else l <= curr_sl

                if sl_hit:
                    rem_w = 1.0 - closed_weight
                    # Exit slippage
                    if is_short:
                        exit_p = curr_sl * (
                            1.0 + SLIPPAGE_PCT
                        )  # Buying higher to close short
                        pnl = (entry_price - exit_p) / entry_price
                    else:
                        exit_p = curr_sl * (
                            1.0 - SLIPPAGE_PCT
                        )  # Selling lower to close long
                        pnl = (exit_p - entry_price) / entry_price

                    cum_pnl += pnl * rem_w
                    closed_weight = 1.0
                    exit_reason = "STOP_LOSS" if not be_activated else "SL_AT_BE"
                    final_abs_idx = i
                    break

                # 2. TAKE PROFITS
                hit_new_tp = False
                for t in targets:
                    # LONG: TP triggers when h >= price
                    # SHORT: TP triggers when l <= price
                    tp_hit = l <= t["price"] if is_short else h >= t["price"]

                    if not t["done"] and tp_hit:
                        if is_short:
                            exit_p = t["price"] * (1.0 + SLIPPAGE_PCT)  # Buying higher
                            pnl = (entry_price - exit_p) / entry_price
                        else:
                            exit_p = t["price"] * (1.0 - SLIPPAGE_PCT)  # Selling lower
                            pnl = (exit_p - entry_price) / entry_price

                        cum_pnl += pnl * t["weight"]
                        t["done"] = True
                        closed_weight += t["weight"]
                        hit_new_tp = True
                        if closed_weight >= 0.99:
                            exit_reason = "TAKE_PROFIT"
                            final_abs_idx = i
                            break

                if closed_weight >= 0.99:
                    break

                # 3. MANAGEMENT: BREAK-EVEN BY TAKE PROFIT
                if move_sl_to_be and hit_new_tp and not be_activated:
                    if is_short:
                        # For short: move SL below the entry price (slightly below BE)
                        curr_sl = min(curr_sl, entry_price * 0.998)
                    else:
                        # For long: move SL above the entry price (slightly above BE)
                        curr_sl = max(curr_sl, entry_price * 1.002)
                    be_activated = True

                # 4. MANAGEMENT: BREAK-EVEN BY RR (If price has moved X risks)
                if sim_breakeven_rr > 0 and not be_activated:
                    if is_short:
                        dist_passed = (
                            entry_price - l
                        )  # For short: profit when price falls
                    else:
                        dist_passed = (
                            h - entry_price
                        )  # For long: profit when price rises

                    rr_now = dist_passed / initial_risk
                    if rr_now >= sim_breakeven_rr:
                        if is_short:
                            curr_sl = min(curr_sl, entry_price * 0.998)
                        else:
                            curr_sl = max(curr_sl, entry_price * 1.002)
                        be_activated = True

                # 5. MANAGEMENT: TRAILING (If enabled)
                if sim_trailing_pct > 0:
                    if is_short:
                        # For short: trailing from minimum upwards
                        new_sl = l * (1.0 + sim_trailing_pct)
                        if new_sl < curr_sl:
                            curr_sl = new_sl
                    else:
                        # For long: trailing from maximum downwards
                        new_sl = h * (1.0 - sim_trailing_pct)
                        if new_sl > curr_sl:
                            curr_sl = new_sl

                # 6. MANAGEMENT: ORACLE EXIT (Regime Exit)
                if self.use_oracle and regime_exit_enabled and np_oracle is not None:
                    # Oracle shows market MODE: True = amnesia (trading), False = paranoia (not trading)
                    # For both directions (LONG and SHORT): exit when the mode changes to paranoia
                    oracle_exit_signal = not np_oracle[i]

                    if oracle_exit_signal:
                        if regime_exit_mode == "close":
                            exit_idx = min(i + 1, len_data - 1)
                            if is_short:
                                exit_p = np_open[exit_idx] * (1.0 + SLIPPAGE_PCT)
                                pnl = (entry_price - exit_p) / entry_price
                            else:
                                exit_p = np_open[exit_idx] * (1.0 - SLIPPAGE_PCT)
                                pnl = (exit_p - entry_price) / entry_price

                            rem_w = 1.0 - closed_weight
                            cum_pnl += pnl * rem_w
                            closed_weight = 1.0
                            exit_reason = "ORACLE_EXIT"
                            final_abs_idx = exit_idx
                            break

                        elif regime_exit_mode == "breakeven" and not be_activated:
                            if is_short:
                                curr_sl = min(curr_sl, entry_price * 0.998)
                            else:
                                curr_sl = max(curr_sl, entry_price * 1.002)
                            be_activated = True

            else:
                # TIMEOUT: closing at market price
                final_abs_idx = min(end_search, len_data - 1)
                rem_w = 1.0 - closed_weight
                if rem_w > 0.001:
                    if is_short:
                        exit_p = np_close[final_abs_idx] * (1.0 + SLIPPAGE_PCT)
                        pnl = (entry_price - exit_p) / entry_price
                    else:
                        exit_p = np_close[final_abs_idx] * (1.0 - SLIPPAGE_PCT)
                        pnl = (exit_p - entry_price) / entry_price
                    cum_pnl += pnl * rem_w
                exit_reason = (
                    "TIMEOUT"
                    if timeout_limit_idx is not None and timeout_limit_idx < len_data
                    else "END_OF_DATA"
                )

            # Commission
            commission_val = self.commission_pct * 2
            net_pnl = cum_pnl - commission_val

            self.trade_log.append(
                {
                    "entry_time": index_vals[real_entry_idx],
                    "exit_time": index_vals[final_abs_idx],
                    "pnl_pct": net_pnl,
                    "entry_price": entry_price,
                    "exit_reason": exit_reason,
                    "direction": direction,
                }
            )

            # Phantom Trade Simulation: tracking what would happen without BE
            if (
                exit_reason == "SL_AT_BE"
                and config.PHANTOM_TRACKING_ENABLED
                and initial_tp_price is not None
            ):
                phantom_result = self._simulate_phantom_trade(
                    np_high=np_high,
                    np_low=np_low,
                    np_close=np_close,
                    index_vals=index_vals,
                    start_idx=final_abs_idx + 1,
                    end_idx=len_data,
                    entry_price=entry_price,
                    initial_sl=initial_sl_price,
                    initial_tp=initial_tp_price,
                    is_short=is_short,
                    direction=direction,
                    be_exit_price=curr_sl,
                    be_exit_time=index_vals[final_abs_idx],
                    trade_entry_time=index_vals[real_entry_idx],
                )
                if phantom_result:
                    self.phantom_log.append(phantom_result)

            last_exit_loc = final_abs_idx

    def _simulate_phantom_trade(
        self,
        np_high: np.ndarray,
        np_low: np.ndarray,
        np_close: np.ndarray,
        index_vals: np.ndarray,
        start_idx: int,
        end_idx: int,
        entry_price: float,
        initial_sl: float,
        initial_tp: float,
        is_short: bool,
        direction: str,
        be_exit_price: float,
        be_exit_time,
        trade_entry_time,
    ) -> Optional[Dict[str, Any]]:
        """
        Simulates a 'phantom' trade after exiting at BE.
        Determines if the price would have reached the original TP or SL.
        """
        if start_idx >= end_idx:
            return None

        # Timeout in candles
        timeout_candles = config.PHANTOM_TRACKING_DEFAULT_TIMEOUT_CANDLES
        max_idx = min(start_idx + timeout_candles, end_idx)

        # MFE/MAE initialization
        mfe_after_be = 0.0  # Maximum Favorable Excursion
        mae_after_be = 0.0  # Maximum Adverse Excursion
        mfe_price = be_exit_price
        mae_price = be_exit_price

        phantom_status = "TIMEOUT"
        phantom_exit_time = None
        phantom_exit_price = None
        candles_tracked = 0

        for i in range(start_idx, max_idx):
            candles_tracked += 1
            h = np_high[i]
            l = np_low[i]  # noqa: E741

            # Updating MFE/MAE
            if is_short:
                # For short: MFE = minimum low, MAE = maximum high
                if l < mfe_price:
                    mfe_price = l
                    mfe_after_be = ((be_exit_price - l) / be_exit_price) * 100
                if h > mae_price:
                    mae_price = h
                    mae_after_be = ((h - be_exit_price) / be_exit_price) * 100
            else:
                # For long: MFE = maximum high, MAE = minimum low
                if h > mfe_price:
                    mfe_price = h
                    mfe_after_be = ((h - be_exit_price) / be_exit_price) * 100
                if l < mae_price:
                    mae_price = l
                    mae_after_be = ((be_exit_price - l) / be_exit_price) * 100

            # Checking TP/SL
            tp_hit = False
            sl_hit = False

            if is_short:
                tp_hit = l <= initial_tp
                sl_hit = h >= initial_sl
            else:
                tp_hit = h >= initial_tp
                sl_hit = l <= initial_sl

            if tp_hit and sl_hit:
                # If both are on the same candle — count SL first (conservative)
                sl_hit = True
                tp_hit = False

            if tp_hit:
                phantom_status = "TP_HIT"
                phantom_exit_time = index_vals[i]
                phantom_exit_price = initial_tp
                break

            if sl_hit:
                phantom_status = "SL_HIT"
                phantom_exit_time = index_vals[i]
                phantom_exit_price = initial_sl
                break

        # If timeout
        if phantom_status == "TIMEOUT" and candles_tracked > 0:
            phantom_exit_time = index_vals[
                min(start_idx + candles_tracked - 1, end_idx - 1)
            ]
            phantom_exit_price = np_close[
                min(start_idx + candles_tracked - 1, end_idx - 1)
            ]

        # Calculating phantom PnL
        phantom_pnl_pct = None
        if phantom_exit_price is not None:
            if is_short:
                phantom_pnl_pct = (
                    (entry_price - phantom_exit_price) / entry_price
                ) * 100
            else:
                phantom_pnl_pct = (
                    (phantom_exit_price - entry_price) / entry_price
                ) * 100

        return {
            "entry_time": trade_entry_time,
            "be_exit_time": be_exit_time,
            "entry_price": entry_price,
            "initial_sl": initial_sl,
            "initial_tp": initial_tp,
            "be_exit_price": be_exit_price,
            "direction": direction,
            "phantom_status": phantom_status,
            "phantom_exit_time": phantom_exit_time,
            "phantom_exit_price": phantom_exit_price,
            "phantom_pnl_pct": phantom_pnl_pct,
            "mfe_after_be": mfe_after_be,
            "mae_after_be": mae_after_be,
            "mfe_price": mfe_price,
            "mae_price": mae_price,
            "candles_to_resolution": candles_tracked,
        }

    def _calculate_kpis(self) -> Dict[str, Any]:
        if not self.trade_log:
            return self._get_default_kpis()

        def _finite_float(
            value: Any,
            default: float = 0.0,
            *,
            pos_inf: Optional[float] = None,
            neg_inf: Optional[float] = None,
        ) -> float:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return float(default)

            if math.isnan(numeric):
                return float(default)
            if math.isinf(numeric):
                if numeric > 0 and pos_inf is not None:
                    return float(pos_inf)
                if numeric < 0 and neg_inf is not None:
                    return float(neg_inf)
                return float(default)
            return numeric

        df_all = pd.DataFrame(self.trade_log)
        df_all["exit_time"] = pd.to_datetime(df_all["exit_time"])
        if "entry_time" in df_all.columns:
            df_all["entry_time"] = pd.to_datetime(df_all["entry_time"])

        if "exit_reason" in df_all.columns:
            stats_mask = ~df_all["exit_reason"].astype(str).str.upper().eq(
                "END_OF_DATA"
            )
        else:
            stats_mask = pd.Series(True, index=df_all.index)

        df = df_all.loc[stats_mask].copy()
        excluded_end_of_data_trades = int(len(df_all) - len(df))
        self.trade_log = df_all.to_dict("records")

        if df.empty:
            start_point = self.trade_start_ts or (
                pd.Timestamp(df_all["entry_time"].iloc[0])
                if "entry_time" in df_all.columns and not df_all.empty
                else pd.Timestamp.utcnow()
            )
            start_py = self._to_python_datetime(start_point)
            return {
                "total_trades": 0.0,
                "trades_all": float(len(df_all)),
                "excluded_end_of_data_trades": excluded_end_of_data_trades,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_pnl_pct": 0.0,
                "total_pnl": 0.0,
                "max_dd": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "consistency_score": 0.0,
                "sortino_ratio": 0.0,
                "total_commission": 0.0,
                "wins": 0,
                "losses": 0,
                "avg_trade_pnl": 0.0,
                "trades": self.trade_log,
                "equity_curve": [(start_py, float(self.initial_balance))],
                "analytics_report": self.structured_report,
            }

        return_series = (
            df["balance_return_pct"]
            if "balance_return_pct" in df.columns
            else df["pnl_pct"]
        )
        df["multiplier"] = 1 + return_series

        if "balance_after_trade" in df.columns:
            equity_values = df["balance_after_trade"].astype(float)
            total_pnl_usd = (
                float(df["pnl_usd"].sum())
                if "pnl_usd" in df.columns
                else float(equity_values.iloc[-1] - self.initial_balance)
            )
            total_pnl_pct = (
                ((equity_values.iloc[-1] / self.initial_balance) - 1.0) * 100
                if self.initial_balance > 1e-12
                else 0.0
            )
            peak_balance = equity_values.cummax()
            dd = (equity_values - peak_balance) / peak_balance.replace(0, np.nan)
            max_dd = abs(dd.min()) * 100 if not dd.empty else 0.0
        else:
            shifted_equity = df["multiplier"].cumprod().shift(1).fillna(1.0)
            df["current_balance"] = self.initial_balance * shifted_equity
            df["pnl_usd"] = df["pnl_pct"] * df["current_balance"]
            equity_curve = df["multiplier"].cumprod()
            final_equity = equity_curve.iloc[-1]
            total_pnl_pct = (final_equity - 1) * 100
            total_pnl_usd = float(df["pnl_usd"].sum())
            peak = equity_curve.cummax()
            dd = (equity_curve - peak) / peak
            max_dd = abs(dd.min()) * 100

        start_point = self.trade_start_ts or (
            pd.Timestamp(df_all["entry_time"].iloc[0])
            if "entry_time" in df_all.columns and not df_all.empty
            else pd.Timestamp.utcnow()
        )
        equity_curve_list = [
            (self._to_python_datetime(start_point), float(self.initial_balance))
        ]
        if "balance_after_trade" in df.columns:
            for _, row in df.sort_values("exit_time").iterrows():
                equity_curve_list.append(
                    (
                        self._to_python_datetime(row["exit_time"]),
                        float(row["balance_after_trade"]),
                    )
                )
        else:
            cumulative_balances = self.initial_balance * df["multiplier"].cumprod()
            for exit_ts, balance in zip(df["exit_time"], cumulative_balances):
                equity_curve_list.append(
                    (
                        self._to_python_datetime(exit_ts),
                        float(balance),
                    )
                )

        pnl_series = df["pnl_usd"] if "pnl_usd" in df.columns else df["pnl_pct"]
        wins = int((pnl_series > 0).sum())
        losses = int(len(df) - wins)
        win_rate = (wins / len(df)) * 100 if len(df) > 0 else 0

        gross_profit = pnl_series[pnl_series > 0].sum()
        gross_loss = abs(pnl_series[pnl_series < 0].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 1e-9 else 0.0

        sharpe_input = return_series.astype(float)
        pnl_std = sharpe_input.std()
        if not math.isfinite(pnl_std) or pnl_std < 1e-9:
            pnl_std = 1e-9
        sharpe_ratio = (sharpe_input.mean() / pnl_std) * np.sqrt(min(len(df), 252))

        downside = sharpe_input[sharpe_input < 0]
        downside_std = downside.std()
        if not math.isfinite(downside_std) or downside_std < 1e-9:
            downside_std = 1e-9
        sortino = (sharpe_input.mean() / downside_std) * np.sqrt(len(df))

        if "exit_time" in df.columns:
            df["month"] = df["exit_time"].dt.tz_localize(None).dt.to_period("M")
            pnl_col = "pnl_usd" if "pnl_usd" in df.columns else "pnl_pct"
            monthly = df.groupby("month")[pnl_col].sum()
            consistency = (monthly > 0).sum() / len(monthly) if len(monthly) > 0 else 0
        else:
            consistency = 0.0

        # Commission = commission_rate * 2 (entry + exit) * number of trades
        total_commission = self.commission_pct * 2 * len(df) * 100  # in percent

        return {
            "total_trades": float(len(df)),
            "trades_all": float(len(df_all)),
            "excluded_end_of_data_trades": excluded_end_of_data_trades,
            "total_pnl_pct": _finite_float(total_pnl_pct),
            "total_pnl": _finite_float(total_pnl_usd),
            "win_rate": _finite_float(win_rate),
            "max_dd": _finite_float(max_dd),
            "max_drawdown": _finite_float(max_dd),
            "profit_factor": _finite_float(profit_factor, pos_inf=99999.0),
            "sharpe_ratio": _finite_float(sharpe_ratio),
            "sortino_ratio": _finite_float(sortino),
            "consistency_score": _finite_float(consistency),
            "total_commission": _finite_float(df["commission_usd"].sum())
            if "commission_usd" in df.columns
            else _finite_float(total_commission),
            "wins": wins,
            "losses": losses,
            "avg_trade_pnl": _finite_float(
                total_pnl_usd / len(df) if len(df) > 0 else 0.0
            ),
            "trades": self.trade_log,
            "equity_curve": equity_curve_list,
            "analytics_report": self.structured_report,
            "tick_size": self._get_tick_size(),
        }

    def _get_default_kpis(self) -> Dict[str, Any]:
        default_equity_curve = list(getattr(self, "equity_curve", []))
        if not default_equity_curve:
            default_equity_curve = [
                (datetime.utcnow(), getattr(self, "initial_balance", 100.0))
            ]
        return {
            "total_trades": 0.0,
            "trades_all": 0.0,
            "excluded_end_of_data_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_pnl_pct": 0.0,
            "total_pnl": 0.0,
            "max_dd": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "consistency_score": 0.0,
            "sortino_ratio": 0.0,
            "total_commission": 0.0,
            "wins": 0,
            "losses": 0,
            "avg_trade_pnl": 0.0,
            "trades": [],
            "equity_curve": default_equity_curve,
            "analytics_report": getattr(
                self, "structured_report", self._build_structured_report()
            ),
            "tick_size": self._get_tick_size(),
        }
