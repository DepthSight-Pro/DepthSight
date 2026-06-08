# ruff: noqa: E402
# api/simulation_router.py
"""
API Endpoints for Simulation: Backtesting, Inspector Matrix, Portfolio Simulator
"""

import logging
import json
import copy
import asyncio
import math
from pathlib import Path
from typing import List, Dict, Any, Optional, AsyncGenerator

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .dependencies import require_permission

logger = logging.getLogger(__name__)
HIDDEN_TRADE_EXIT_REASONS = {"END_OF_DATA"}

# Optional imports
try:
    from bot_module.fast_vector_backtester import FastVectorBacktester

    BACKTESTER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"FastVectorBacktester not available: {e}")
    BACKTESTER_AVAILABLE = False

try:
    from bot_module.genetic_strategy_finder import (
        load_asset_data,
        resample_to_timeframes,
    )

    LOADER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"load_asset_data not available: {e}")
    LOADER_AVAILABLE = False

try:
    # Add project root to path for importing simulator from root
    import sys

    root_path = str(Path(__file__).parent.parent)
    if root_path not in sys.path:
        sys.path.append(root_path)

    from sequential_portfolio_simulator import (
        SequentialPortfolioSimulator,
        SimulatorConfig,
    )

    SIMULATOR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"SequentialPortfolioSimulator not available: {e}")
    print(f"CRITICAL: Initial import failed: {e}")
    SIMULATOR_AVAILABLE = False

try:
    from download_pipeline import ensure_data_for_period

    DOWNLOADER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"download_pipeline not available: {e}")
    DOWNLOADER_AVAILABLE = False

# Oracle model import
try:
    from bot_module.oracle import Oracle

    ORACLE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Oracle not available: {e}")
    ORACLE_AVAILABLE = False

# Global Oracle instance (lazy loaded) with thread-safe access
import threading
import os

_oracle_instance = None
_oracle_lock = threading.Lock()  # Thread-safe lock for Oracle initialization
# Use Path directly since PROJECT_ROOT is defined later
ORACLE_MODEL_PATH = Path(__file__).parent.parent / "data" / "oracle_model.joblib"
ORACLE_THRESHOLD = 0.95


def get_oracle():
    """Get or create Oracle instance (singleton pattern with thread-safe access)"""
    global _oracle_instance

    # First check without lock (fast path)
    if _oracle_instance is not None:
        return _oracle_instance

    # Thread-safe initialization
    with _oracle_lock:
        # Double-check pattern
        if _oracle_instance is None and ORACLE_AVAILABLE:
            if ORACLE_MODEL_PATH.exists():
                try:
                    _oracle_instance = Oracle(ORACLE_MODEL_PATH)
                    logger.info(
                        f"Oracle model loaded from {ORACLE_MODEL_PATH} in worker PID: {os.getpid()}"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to load Oracle model in worker PID {os.getpid()}: {e}"
                    )
            else:
                logger.warning(
                    f"Oracle model not found at {ORACLE_MODEL_PATH} in worker PID: {os.getpid()}"
                )
    return _oracle_instance


def apply_oracle_signal(df, oracle_instance, threshold=0.95):
    """
    Apply Oracle predictions to DataFrame.
    Creates 'oracle_signal' column based on model predictions.

    Args:
        df: DataFrame with market data
        oracle_instance: Loaded Oracle model
        threshold: Confidence threshold for signal

    Returns:
        DataFrame with 'oracle_signal' column
    """
    if oracle_instance is None:
        df["oracle_signal"] = False
        return df

    try:
        import numpy as np

        features = oracle_instance.engineer_features(df)
        feature_cols = ["sensor_memory", "sensor_news", "sensor_complexity"]

        if features[feature_cols].isnull().any().any():
            features = features.fillna(0)

        probs = oracle_instance.model.predict_proba(features[feature_cols])

        # Regimes: 0 = paranoia (flat), 1 = amnesia (trend)
        # We enter when regime == 1 (amnesia/trend)
        TARGET_REGIME = 1  # amnesia = trend
        oracle_regime = np.argmax(probs, axis=1)
        oracle_confidence = np.max(probs, axis=1)

        mask = (oracle_regime == TARGET_REGIME) & (oracle_confidence >= threshold)
        df["oracle_signal"] = mask

        # Also add oracle_regime for visualization
        df["oracle_regime"] = oracle_regime

    except Exception as e:
        logger.warning(f"Failed to apply oracle signal: {e}")
        df["oracle_signal"] = False

    return df


simulation_router = APIRouter()

SIMULATION_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]

# --- Paths ---
PROJECT_ROOT = Path(__file__).parent.parent
# Use 'actual' folder which contains more recent data
DATA_STORAGE_PATH = PROJECT_ROOT / "data_storage" / "actual" / "binance" / "futures"

# --- Pydantic Models ---


class BacktestRequest(BaseModel):
    """Request to start backtest"""

    strategy_json: Dict[str, Any]
    assets: List[str]
    use_oracle: bool = False


class BacktestResult(BaseModel):
    """Backtest result for a single asset"""

    asset: str
    kpis: Dict[str, Any]
    trades: List[Dict[str, Any]]
    equity_curve: List[List[float]]  # [[timestamp, value], ...]


class InspectorRequest(BaseModel):
    """Request for Inspector Matrix"""

    strategy_json: Dict[str, Any]
    assets: List[str]
    variants: List[str] = Field(default_factory=lambda: ["base", "oracle"])
    oracle_threshold: float = 0.6
    # Custom variants with full configuration
    custom_variants: Optional[List[Dict[str, Any]]] = None
    # Date Filtering
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class DownloadDataRequest(BaseModel):
    symbols: List[str]
    start_date: str
    end_date: str


# Custom Variant Configuration
class PartialTPConfig(BaseModel):
    triggerRR: float
    closePercent: float


class OracleConfig(BaseModel):
    enabled: bool = False
    threshold: float = 0.95
    entryRegime: str = "amnesia"  # amnesia, paranoia, any
    onRegimeChange: str = "none"  # none, breakeven, close


class TakeProfitConfig(BaseModel):
    partials: List[PartialTPConfig] = []
    finalTP_RR: float = 2.0


class BreakevenConfig(BaseModel):
    mode: str = "disabled"  # disabled, at_rr, at_first_tp, by_oracle
    triggerRR: float = 1.0


class TrailingStopConfig(BaseModel):
    enabled: bool = False
    trailPercent: float = 0.01


class RiskManagementConfig(BaseModel):
    breakeven: BreakevenConfig = BreakevenConfig()
    trailingStop: TrailingStopConfig = TrailingStopConfig()
    maxHoldCandles: int = 0


class TimeFilterConfig(BaseModel):
    enabled: bool = False
    startHourUTC: int = 0
    endHourUTC: int = 0
    mode: str = "include"  # include, exclude


class CustomVariantConfig(BaseModel):
    """Full custom variant configuration"""

    id: str
    name: str
    color: str = "#06B6D4"
    isBuiltIn: bool = False
    oracle: OracleConfig = OracleConfig()
    takeProfit: TakeProfitConfig = TakeProfitConfig()
    riskManagement: RiskManagementConfig = RiskManagementConfig()
    timeFilter: TimeFilterConfig = TimeFilterConfig()


class InspectorCell(BaseModel):
    """Inspector Matrix cell"""

    pnl_pct: float
    win_rate: float
    trades_count: int
    sharpe: float
    max_dd: float = 0.0
    commission: float = 0.0


class InspectorMatrixResult(BaseModel):
    """Inspector Matrix result"""

    matrix: Dict[str, Dict[str, InspectorCell]]  # asset -> variant -> cell
    assets: List[str]
    variants: List[str]


class SimulationConfigModel(BaseModel):
    """Portfolio simulation configuration"""

    initial_capital: float = 10000
    max_concurrent_positions: int = 5
    base_risk_pct: float = 1.0
    leverage: float = 5.0
    adaptive_risk: bool = True
    compounding: bool = True


class PortfolioSimulationRequest(BaseModel):
    """Request for portfolio simulation (with ready trades)"""

    trades: List[Dict[str, Any]]
    config: SimulationConfigModel


class PortfolioFullRequest(BaseModel):
    """Request for full portfolio simulation (backtest + simulation in one)"""

    strategy_json: Dict[str, Any]
    assets: List[str]
    variants: List[str] = Field(default_factory=lambda: ["raw"])  # List of variants
    config: SimulationConfigModel


class PortfolioSimulationResult(BaseModel):
    """Portfolio simulation result"""

    equity_curve: List[Dict[str, Any]] = Field(
        default_factory=list, serialization_alias="equityCurve"
    )
    trades_summary: List[Dict[str, Any]] = Field(
        default_factory=list, serialization_alias="tradesSummary"
    )
    trades: List[Dict[str, Any]] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class AssetDetailRequest(BaseModel):
    """Request for detailed asset analysis"""

    strategy_json: Dict[str, Any]
    variants: List[str] = Field(default_factory=lambda: ["raw", "oracle_be"])
    config: SimulationConfigModel


# --- Helper: api_round ---
def api_round(val):
    """Rounding values for API response"""
    if val is None:
        return 0
    try:
        return float(round(val, 2))
    except Exception:
        return 0


def _json_default(value: Any) -> Any:
    """JSON fallback for numpy/pandas scalars and timestamps returned by backtests."""
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _json_dumps(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, default=_json_default, allow_nan=False)


def _api_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(numeric):
        return float(default)
    return numeric


def _api_int(value: Any, default: int = 0) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return int(default)
    if not math.isfinite(numeric):
        return int(default)
    return int(numeric)


def _to_ms_safe(val: Any) -> int:
    if val is None:
        return 0
    if hasattr(val, "timestamp"):
        return int(val.timestamp() * 1000)
    if isinstance(val, (int, float)):
        numeric = float(val)
        if not math.isfinite(numeric):
            return 0
        return int(numeric * 1000) if numeric < 1e12 else int(numeric)
    return 0


# --- Helper: Format Response ---
def format_simulation_response(
    stats: Dict, equity_curve: List[Dict], trades_summary: List[Dict]
) -> Dict[str, Any]:
    """Formats simulation results for the frontend (snake_case -> camelCase)"""

    # 1. Format statistics
    formatted_stats = {
        "totalPnl": api_round(stats.get("total_pnl", 0)),
        "totalPnlPct": api_round(stats.get("total_pnl_pct", 0)),
        "winRate": api_round(stats.get("win_rate", 0)),
        "profitFactor": api_round(stats.get("profit_factor", 0)),
        "sharpeRatio": api_round(stats.get("sharpe_ratio", 0)),
        "maxDrawdown": api_round(stats.get("max_drawdown", 0)),
        "skippedTrades": stats.get("skipped_trades", 0),
        "avgWin": api_round(
            stats.get("avg_win_pct", 0)
        ),  # Use percentage for frontend display
        "avgLoss": api_round(
            stats.get("avg_loss_pct", 0)
        ),  # Use percentage for frontend display
        "initialCapital": stats.get("initial_capital", 0),
        "finalCapital": stats.get("final_capital", 0),
        "totalTrades": stats.get("total_trades", 0),
        "maxWinStreak": stats.get("max_win_streak", 0),
        "maxLossStreak": stats.get("max_loss_streak", 0),
        "avgRiskMultiplier": api_round(stats.get("avg_risk_multiplier", 0)),
    }

    # 2. Format trades
    formatted_trades = []
    trades_records = []

    if "trades_df" in stats:
        if hasattr(stats["trades_df"], "to_dict"):
            trades_records = stats["trades_df"].to_dict("records")
        elif isinstance(stats["trades_df"], list):
            trades_records = stats["trades_df"]

    for t in trades_records:
        entry_time = t.get("entry_time")
        exit_time = t.get("exit_time")

        # Convert to milliseconds
        def to_ms(val):
            if val is None:
                return 0
            if hasattr(val, "timestamp"):
                return int(val.timestamp() * 1000)
            if isinstance(val, (int, float)):
                return int(val * 1000) if val < 10000000000 else int(val)
            return 0

        formatted_trades.append(
            {
                "id": str(t.get("id", entry_time)),
                "asset": t.get("asset", "Unknown"),
                "strategy": t.get("strategy", "Unknown"),
                "entryTime": to_ms(entry_time),
                "exitTime": to_ms(exit_time),
                "entryPrice": t.get("entry_price", 0),
                "exitPrice": t.get("exit_price", 0),
                "pnlPct": t.get("pnl_pct", 0),
                "pnlAmount": t.get("pnl_amount", 0),
                "status": "closed",
                "reason": "signal",
                "slotIndex": 0,
            }
        )

    # Return dictionary with snake_case keys for Pydantic model
    # serialization_alias in model converts them to camelCase during serialization
    logger.info(f"format_simulation_response: equity_curve len={len(equity_curve)}")
    return {
        "equity_curve": equity_curve,
        "trades_summary": trades_summary,
        "trades": formatted_trades,
        "stats": formatted_stats,
    }


def _is_user_visible_trade(trade: Any) -> bool:
    if not isinstance(trade, dict):
        return True
    return str(trade.get("exit_reason", "")).upper() not in HIDDEN_TRADE_EXIT_REASONS


def _filter_user_visible_trades(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [trade for trade in trades if _is_user_visible_trade(trade)]


def _main_1m_df(data: Any):
    if isinstance(data, dict):
        df_1m = data.get("1m")
        if df_1m is not None:
            return df_1m
        return next((df for df in data.values() if df is not None), None)
    return data


def build_simulation_mtf_data(df_1m):
    """Build the MTF shape FastVectorBacktester gets in normal vector backtests."""
    try:
        mtf_data = resample_to_timeframes(df_1m, SIMULATION_TIMEFRAMES)
        logger.info(f"Simulation MTF data created: {list(mtf_data.keys())}")
        return mtf_data
    except Exception as e:
        logger.warning(
            f"Failed to build simulation MTF data, falling back to 1m only: {e}",
            exc_info=True,
        )
        return df_1m


def _backtest_event_counters(kpis: Dict[str, Any]) -> Dict[str, Any]:
    analytics_report = kpis.get("analytics_report") if isinstance(kpis, dict) else None
    if not isinstance(analytics_report, dict):
        return {}
    event_counters = analytics_report.get("event_counters")
    return event_counters if isinstance(event_counters, dict) else {}


def _collect_strategy_leaf_nodes(node: Any) -> List[Dict[str, Any]]:
    leaves: List[Dict[str, Any]] = []
    if not isinstance(node, dict):
        return leaves

    children = node.get("children")
    if isinstance(children, list) and children:
        for child in children:
            leaves.extend(_collect_strategy_leaf_nodes(child))
        return leaves

    leaves.append(
        {
            "id": node.get("id"),
            "type": node.get("type"),
            "params": node.get("params", {}),
        }
    )
    return leaves


def _log_asset_strategy_mismatch(
    asset: Optional[str], strategy_config: Dict[str, Any], df_main: Any
) -> None:
    if not asset or not isinstance(strategy_config, dict):
        return

    strategy_symbol = str(strategy_config.get("symbol") or "").upper()
    asset_symbol = str(asset).upper()
    if strategy_symbol and strategy_symbol != asset_symbol:
        logger.warning(
            "SIM_SYMBOL_MISMATCH data_asset=%s strategy_symbol=%s note=%s",
            asset,
            strategy_symbol,
            "Strategy params are applied to this asset; absolute price filters may not transfer across symbols.",
        )

    if df_main is None or "close" not in getattr(df_main, "columns", []):
        return

    try:
        median_close = float(df_main["close"].median())
    except Exception:
        return
    if not math.isfinite(median_close) or median_close <= 0:
        return

    for filter_node in _collect_strategy_leaf_nodes(strategy_config.get("filters")):
        params = filter_node.get("params") if isinstance(filter_node, dict) else None
        if not isinstance(params, dict):
            continue
        if str(filter_node.get("type")) != "volatility_filter":
            continue
        if str(params.get("indicator", "")).upper() != "ATR":
            continue

        try:
            threshold = float(params.get("value", params.get("threshold")))
        except (TypeError, ValueError):
            continue
        threshold_pct_of_price = (threshold / median_close) * 100.0
        if threshold_pct_of_price >= 2.0:
            logger.warning(
                "SIM_ABSOLUTE_ATR_FILTER_RISK asset=%s strategy_symbol=%s filter_id=%s threshold=%s "
                "median_close=%.8f threshold_pct_of_price=%.2f note=%s",
                asset,
                strategy_symbol or None,
                filter_node.get("id"),
                threshold,
                median_close,
                threshold_pct_of_price,
                "ATR threshold is absolute price units; for multi-asset simulation consider NATR/percent volatility or per-asset thresholds.",
            )


def _series_count(series: Any) -> Optional[int]:
    if series is None:
        return None
    try:
        return int(series.fillna(False).astype(bool).sum())
    except Exception:
        return None


def _sample_indices(mask: Any, limit: int = 3) -> List[int]:
    if mask is None:
        return []
    try:
        values = mask.fillna(False).astype(bool).to_numpy()
        return [int(idx) for idx in values.nonzero()[0][:limit]]
    except Exception:
        return []


def _safe_decision_trace(bt: Any, idx: int) -> Optional[Dict[str, Any]]:
    try:
        direction = (
            bt.strategy_json.get("initialization", {})
            .get("params", {})
            .get("direction", "LONG")
        )
        trace = bt._build_decision_trace_for_index(idx, str(direction).upper())
        if not isinstance(trace, dict):
            return None
        return {
            "time": trace.get("details", {}).get("signal_time"),
            "entry_result": trace.get("result"),
            "entry_details": trace.get("details"),
            "filters_trace": trace.get("filters_trace"),
        }
    except Exception as exc:
        return {"trace_error": str(exc), "idx": idx}


def _build_signal_diagnostics(
    bt: Any, event_counters: Dict[str, Any]
) -> Dict[str, Any]:
    entry_mask = getattr(bt, "_entry_condition_result", None)
    filter_mask = getattr(bt, "_filter_condition_result", None)
    diagnostics: Dict[str, Any] = {
        "entry_candidates": _series_count(entry_mask),
        "filter_pass": _series_count(filter_mask),
    }

    rejected_by_filter_mask = None
    try:
        if entry_mask is not None and filter_mask is not None:
            rejected_by_filter_mask = entry_mask.fillna(False).astype(
                bool
            ) & ~filter_mask.fillna(False).astype(bool)
            diagnostics["entry_after_filter"] = int(
                (
                    entry_mask.fillna(False).astype(bool)
                    & filter_mask.fillna(False).astype(bool)
                ).sum()
            )
            diagnostics["entry_rejected_by_filter"] = int(rejected_by_filter_mask.sum())
    except Exception:
        pass

    try:
        node_results = getattr(bt, "_entry_node_results", {}) or {}
        diagnostics["entry_nodes_true"] = {
            str(node_id): _series_count(mask)
            for node_id, mask in node_results.items()
            if _series_count(mask)
        }
    except Exception:
        pass

    try:
        filter_results = getattr(bt, "_filter_node_results", {}) or {}
        failed_filter_counts = (event_counters.get("rejections") or {}).get(
            "by_filter"
        ) or {}
        diagnostics["filter_nodes_true"] = {
            str(node_id): _series_count(mask)
            for node_id, mask in filter_results.items()
            if str(node_id) in failed_filter_counts or _series_count(mask) == 0
        }
    except Exception:
        pass

    sample_source = (
        rejected_by_filter_mask if rejected_by_filter_mask is not None else entry_mask
    )
    sample_ids = _sample_indices(sample_source)
    if sample_ids:
        diagnostics["sample_traces"] = [
            _safe_decision_trace(bt, idx) for idx in sample_ids
        ]

    return diagnostics


# --- Helper: run_variant_backtest ---
def run_variant_backtest(
    df, strategy_config, variant_type, start_date=None, end_date=None, asset=None
):
    """Run backtest for a specific variant - mirrors inspector_v3.py logic"""

    # CRITICAL: Normalize strategy to handle nested formats (genetic, config_data, etc.)
    normalized_strategy = FastVectorBacktester.normalize_strategy(strategy_config)
    df_main = _main_1m_df(df)
    _log_asset_strategy_mismatch(asset, normalized_strategy, df_main)

    # DEBUG: Log input data fingerprint for raw variant to diagnose discrepancies
    if variant_type == "raw":
        df_len = len(df_main) if df_main is not None else 0
        df_cols = list(df_main.columns) if df_main is not None else []
        close_sum = (
            df_main["close"].sum()
            if df_main is not None and "close" in df_main.columns
            else 0
        )
        has_oracle = df_main is not None and "oracle_signal" in df_main.columns
        has_filters = "filters" in normalized_strategy
        tf_keys = list(df.keys()) if isinstance(df, dict) else ["1m"]
        logger.info(
            f"DEBUG RAW INPUT: asset={asset}, rows={df_len}, cols_count={len(df_cols)}, close_sum={close_sum:.2f}, has_oracle={has_oracle}, has_filters={has_filters}, timeframes={tf_keys}"
        )

    config = copy.deepcopy(normalized_strategy)

    # Safeguard
    if "initialization" not in config:
        config["initialization"] = {}
    if "params" not in config["initialization"]:
        config["initialization"]["params"] = {}

    init_params = config["initialization"]["params"]
    use_oracle_flag = False

    # --- SET UP VARIANTS (from inspector_v3.py) ---
    if variant_type == "raw":
        use_oracle_flag = False
        init_params["regime_exit_enabled"] = False

    elif variant_type == "oracle_entry":
        use_oracle_flag = True
        init_params["regime_exit_enabled"] = False

    elif variant_type == "oracle_be":
        use_oracle_flag = True
        init_params["regime_exit_enabled"] = True
        init_params["regime_exit_mode"] = "breakeven"

    elif variant_type == "oracle_be_time":
        use_oracle_flag = True
        init_params["regime_exit_enabled"] = True
        init_params["regime_exit_mode"] = "breakeven"

        # Time filter (14:00 - 07:00 UTC)
        time_filter_node = {
            "type": "time_filter",
            "params": {"start_hour_utc": 14, "end_hour_utc": 7, "mode": "include"},
        }
        current_filters = config.get("filters")
        if not current_filters:
            config["filters"] = time_filter_node
        else:
            config["filters"] = {
                "type": "AND",
                "children": [current_filters, time_filter_node],
            }

    elif variant_type == "oracle_partial":
        use_oracle_flag = True
        init_params["regime_exit_enabled"] = True
        init_params["regime_exit_mode"] = "breakeven"
        init_params["partial_exits"] = [
            {"tp_type": "rr_multiplier", "tp_value": 1.5, "size_pct": 30},
            {"tp_type": "rr_multiplier", "tp_value": 2.5, "size_pct": 30},
        ]
        init_params["move_sl_to_be_on_first_tp"] = True

    elif variant_type == "trailing_dev":
        use_oracle_flag = True
        init_params["regime_exit_enabled"] = False
        init_params["sim_trailing_pct"] = 0.01

    elif variant_type == "be_at_1rr":
        use_oracle_flag = True
        init_params["regime_exit_enabled"] = False
        init_params["sim_breakeven_rr"] = 1.0

    elif variant_type == "hybrid_be":
        use_oracle_flag = True
        init_params["regime_exit_enabled"] = True
        init_params["regime_exit_mode"] = "breakeven"
        init_params["sim_breakeven_rr"] = 1.0

    elif variant_type == "hybrid_be_time":
        use_oracle_flag = True
        init_params["regime_exit_enabled"] = True
        init_params["regime_exit_mode"] = "breakeven"
        init_params["sim_breakeven_rr"] = 2.0

        # Time filter (14:00 - 07:00 UTC)
        time_filter_node = {
            "type": "time_filter",
            "params": {"start_hour_utc": 14, "end_hour_utc": 7, "mode": "include"},
        }
        current_filters = config.get("filters")
        if not current_filters:
            config["filters"] = time_filter_node
        else:
            config["filters"] = {
                "type": "AND",
                "children": [current_filters, time_filter_node],
            }

    # Apply Oracle signal to DataFrame if needed
    df_with_oracle = (
        {tf: frame.copy() for tf, frame in df.items()}
        if isinstance(df, dict)
        else df.copy()
    )
    if use_oracle_flag:
        oracle = get_oracle()
        if oracle is not None:
            if isinstance(df_with_oracle, dict):
                df_with_oracle["1m"] = apply_oracle_signal(
                    df_with_oracle["1m"], oracle, ORACLE_THRESHOLD
                )
            else:
                df_with_oracle = apply_oracle_signal(
                    df_with_oracle, oracle, ORACLE_THRESHOLD
                )
        else:
            logger.warning(
                f"Oracle requested for variant '{variant_type}' but model not available"
            )
            # Set oracle_signal to True so trades still happen (without oracle filtering)
            if isinstance(df_with_oracle, dict):
                df_with_oracle["1m"]["oracle_signal"] = True
            else:
                df_with_oracle["oracle_signal"] = True

    # Backtest
    df_log = _main_1m_df(df_with_oracle)
    logger.info(
        f"Running backtest for {variant_type}. Data range: {df_log.index.min()} to {df_log.index.max()}. Filter requested: {start_date} - {end_date}"
    )
    bt = FastVectorBacktester(
        df_with_oracle,
        config,
        use_oracle=use_oracle_flag,
        start_date=start_date,
        end_date=end_date,
    )
    kpis = bt.run()
    raw_trade_log_len = len(getattr(bt, "trade_log", []) or [])
    event_counters = _backtest_event_counters(kpis)
    signal_diagnostics = _build_signal_diagnostics(bt, event_counters)
    kpis["simulation_diagnostics"] = signal_diagnostics
    logger.info(
        "SIM_BACKTEST_OUTPUT asset=%s strategy_symbol=%s variant=%s total_trades=%s raw_trade_log=%s trades_all=%s "
        "excluded_eod=%s total_pnl_pct=%s win_rate=%s signals=%s foundation=%s rejections=%s errors=%s diagnostics=%s",
        asset,
        config.get("symbol"),
        variant_type,
        kpis.get("total_trades"),
        raw_trade_log_len,
        kpis.get("trades_all"),
        kpis.get("excluded_end_of_data_trades"),
        kpis.get("total_pnl_pct"),
        kpis.get("win_rate"),
        event_counters.get("signals_generated_total"),
        event_counters.get("foundation_trigger_counts"),
        event_counters.get("rejections"),
        event_counters.get("errors"),
        signal_diagnostics,
    )

    # Calculate real win rate
    trade_log = []
    phantom_log = []
    if hasattr(bt, "trade_log") and bt.trade_log:
        stats_trades = _filter_user_visible_trades(bt.trade_log)
        wins = sum(1 for t in stats_trades if t.get("pnl_pct", 0) > 0)
        kpis["win_rate"] = (wins / len(stats_trades)) * 100 if stats_trades else 0
        kpis.setdefault("trades_all", len(bt.trade_log))
        kpis.setdefault(
            "excluded_end_of_data_trades", len(bt.trade_log) - len(stats_trades)
        )
        trade_log = stats_trades

        # DEBUG: Log first asset to compare with inspector_v3.py
        if variant_type == "raw" and len(stats_trades) > 0:
            total_pnl = kpis.get("total_pnl", 0)
            logger.info(
                f"DEBUG RAW OUTPUT: trades={len(stats_trades)}, total_pnl={total_pnl:.2f}%, wins={wins}, WR={kpis['win_rate']:.1f}%, max_dd={kpis.get('max_dd', 0):.1f}%"
            )

    # Phantom trades for BE analysis
    if hasattr(bt, "phantom_log") and bt.phantom_log:
        phantom_log = bt.phantom_log
        logger.debug(f"Phantom trades collected: {len(phantom_log)}")

    # Return both KPI, trade_log, and phantom_log
    return {"kpis": kpis, "trade_log": trade_log, "phantom_log": phantom_log}


# --- Helper: run_custom_variant_backtest ---
def run_custom_variant_backtest(
    df,
    strategy_config,
    variant: CustomVariantConfig,
    start_date=None,
    end_date=None,
    asset=None,
):
    """Run backtest with full custom variant configuration"""
    # CRITICAL: Normalize strategy to handle nested formats
    normalized_strategy = FastVectorBacktester.normalize_strategy(strategy_config)
    _log_asset_strategy_mismatch(asset, normalized_strategy, _main_1m_df(df))
    config = copy.deepcopy(normalized_strategy)

    if "initialization" not in config:
        config["initialization"] = {}
    if "params" not in config["initialization"]:
        config["initialization"]["params"] = {}

    init_params = config["initialization"]["params"]

    # --- Oracle Configuration ---
    use_oracle = variant.oracle.enabled
    if use_oracle:
        init_params["regime_exit_enabled"] = variant.oracle.onRegimeChange != "none"
        if variant.oracle.onRegimeChange == "breakeven":
            init_params["regime_exit_mode"] = "breakeven"
        elif variant.oracle.onRegimeChange == "close":
            init_params["regime_exit_mode"] = "close"

    # --- Take Profit Configuration ---
    if variant.takeProfit.partials:
        init_params["partial_exits"] = [
            {
                "tp_type": "rr_multiplier",
                "tp_value": tp.triggerRR,
                "size_pct": tp.closePercent,
            }
            for tp in variant.takeProfit.partials
        ]

    init_params["tp_value"] = variant.takeProfit.finalTP_RR

    # --- Breakeven Configuration ---
    if variant.riskManagement.breakeven.mode == "at_rr":
        init_params["sim_breakeven_rr"] = variant.riskManagement.breakeven.triggerRR
    elif variant.riskManagement.breakeven.mode == "at_first_tp":
        init_params["move_sl_to_be_on_first_tp"] = True
    elif variant.riskManagement.breakeven.mode == "by_oracle":
        init_params["regime_exit_enabled"] = True
        init_params["regime_exit_mode"] = "breakeven"

    # --- Trailing Stop Configuration ---
    if variant.riskManagement.trailingStop.enabled:
        init_params["sim_trailing_pct"] = (
            variant.riskManagement.trailingStop.trailPercent
        )

    # --- Max Hold ---
    if variant.riskManagement.maxHoldCandles > 0:
        init_params["max_hold_candles"] = variant.riskManagement.maxHoldCandles

    # --- Time Filter (inject into config['filters'] like inspector_v3.py) ---
    if variant.timeFilter.enabled:
        time_filter_node = {
            "type": "time_filter",
            "params": {
                "start_hour_utc": variant.timeFilter.startHourUTC,
                "end_hour_utc": variant.timeFilter.endHourUTC,
                "mode": variant.timeFilter.mode,
            },
        }
        current_filters = config.get("filters")
        if not current_filters:
            config["filters"] = time_filter_node
        else:
            config["filters"] = {
                "type": "AND",
                "children": [current_filters, time_filter_node],
            }

    # Apply Oracle signal to DataFrame if needed
    df_with_oracle = (
        {tf: frame.copy() for tf, frame in df.items()}
        if isinstance(df, dict)
        else df.copy()
    )
    if use_oracle:
        oracle = get_oracle()
        if oracle is not None:
            if isinstance(df_with_oracle, dict):
                df_with_oracle["1m"] = apply_oracle_signal(
                    df_with_oracle["1m"], oracle, variant.oracle.threshold
                )
            else:
                df_with_oracle = apply_oracle_signal(
                    df_with_oracle, oracle, variant.oracle.threshold
                )
        else:
            logger.warning(
                f"Oracle requested for variant '{variant.id}' but model not available"
            )
            if isinstance(df_with_oracle, dict):
                df_with_oracle["1m"]["oracle_signal"] = True
            else:
                df_with_oracle["oracle_signal"] = True

    # Run backtest
    bt = FastVectorBacktester(
        df_with_oracle,
        config,
        use_oracle=use_oracle,
        start_date=start_date,
        end_date=end_date,
    )
    kpis = bt.run()
    raw_trade_log_len = len(getattr(bt, "trade_log", []) or [])
    event_counters = _backtest_event_counters(kpis)
    signal_diagnostics = _build_signal_diagnostics(bt, event_counters)
    kpis["simulation_diagnostics"] = signal_diagnostics
    logger.info(
        "SIM_BACKTEST_OUTPUT asset=%s strategy_symbol=%s variant=%s total_trades=%s raw_trade_log=%s trades_all=%s "
        "excluded_eod=%s total_pnl_pct=%s win_rate=%s signals=%s foundation=%s rejections=%s errors=%s diagnostics=%s",
        asset,
        config.get("symbol"),
        variant.id,
        kpis.get("total_trades"),
        raw_trade_log_len,
        kpis.get("trades_all"),
        kpis.get("excluded_end_of_data_trades"),
        kpis.get("total_pnl_pct"),
        kpis.get("win_rate"),
        event_counters.get("signals_generated_total"),
        event_counters.get("foundation_trigger_counts"),
        event_counters.get("rejections"),
        event_counters.get("errors"),
        signal_diagnostics,
    )

    # Calculate actual win rate
    trade_log = []
    phantom_log = []
    if hasattr(bt, "trade_log") and bt.trade_log:
        stats_trades = _filter_user_visible_trades(bt.trade_log)
        wins = sum(1 for t in stats_trades if t.get("pnl_pct", 0) > 0)
        kpis["win_rate"] = (wins / len(stats_trades)) * 100 if stats_trades else 0
        kpis.setdefault("trades_all", len(bt.trade_log))
        kpis.setdefault(
            "excluded_end_of_data_trades", len(bt.trade_log) - len(stats_trades)
        )
        trade_log = stats_trades

    # Phantom trades for BE analysis
    if hasattr(bt, "phantom_log") and bt.phantom_log:
        phantom_log = bt.phantom_log

    return {"kpis": kpis, "trade_log": trade_log, "phantom_log": phantom_log}


# --- Endpoint: Manual Data Download ---
@simulation_router.post(
    "/download_data", dependencies=[Depends(require_permission("run_simulation"))]
)
async def download_data(request: DownloadDataRequest):
    """Manual trigger for data download."""
    if not DOWNLOADER_AVAILABLE:
        raise HTTPException(status_code=500, detail="Downloader module not available")

    try:
        # Run in a separate thread to not block the event loop
        # But wait for it to complete as user expects "loading"
        logger.info(
            f"Starting manual download for {request.symbols} ({request.start_date} - {request.end_date})"
        )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            ensure_data_for_period,
            request.symbols,
            request.start_date,
            request.end_date,
            DATA_STORAGE_PATH,
        )

        return {"status": "success", "message": "Data check and download completed."}
    except Exception as e:
        logger.error(f"Download failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Endpoints ---


@simulation_router.get("/assets")
async def get_available_assets():
    """Get list of available assets from data_storage"""
    try:
        assets = []
        if DATA_STORAGE_PATH.exists():
            logger.info(f"Scanning assets in: {DATA_STORAGE_PATH}")
            # DEBUG: List first 5 items to log
            try:
                all_items = list(DATA_STORAGE_PATH.iterdir())
                logger.info(f"Total items in folder: {len(all_items)}")
                logger.info(f"First 5 items: {[p.name for p in all_items[:5]]}")
            except Exception as scan_err:
                logger.error(f"Failed to list directory: {scan_err}")

            for folder in DATA_STORAGE_PATH.iterdir():
                if folder.is_dir():
                    # Check for presence of kline_1m.parquet file
                    klines_file = folder / "kline_1m.parquet"
                    if klines_file.exists():
                        assets.append(folder.name)
                    else:
                        # DEBUG: Log why skipped (sample)
                        if len(assets) < 3:
                            logger.info(
                                f"Skipping {folder.name}: kline_1m.parquet not found. Contents: {[f.name for f in folder.glob('*')]}"
                            )
        else:
            logger.error(f"DATA_STORAGE_PATH does not exist: {DATA_STORAGE_PATH}")

        # Sort by popularity (main pairs at top)
        priority = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
        sorted_assets = sorted(
            assets,
            key=lambda x: (priority.index(x) if x in priority else len(priority), x),
        )

        return {"assets": sorted_assets, "total": len(sorted_assets)}
    except Exception as e:
        logger.error(f"Error getting assets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _read_simulation_inspector_state(task_id: str) -> Optional[Dict[str, Any]]:
    try:
        from tasks import _simulation_inspector_state_key, redis_client_for_tasks

        if redis_client_for_tasks is None:
            return None
        raw = redis_client_for_tasks.get(_simulation_inspector_state_key(task_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Failed to read simulation inspector state for {task_id}: {e}")
        return None


def _read_simulation_inspector_events(
    task_id: str, start_index: int
) -> List[Dict[str, Any]]:
    try:
        from tasks import _simulation_inspector_events_key, redis_client_for_tasks

        if redis_client_for_tasks is None:
            return []
        raw_events = redis_client_for_tasks.lrange(
            _simulation_inspector_events_key(task_id), start_index, -1
        )
        events = []
        for raw_event in raw_events:
            try:
                events.append(json.loads(raw_event))
            except Exception as parse_err:
                logger.warning(
                    f"Failed to parse simulation inspector event for {task_id}: {parse_err}"
                )
        return events
    except Exception as e:
        logger.warning(f"Failed to read simulation inspector events for {task_id}: {e}")
        return []


@simulation_router.post(
    "/inspector/start", dependencies=[Depends(require_permission("run_simulation"))]
)
async def start_inspector_task(request: InspectorRequest):
    """Queue Inspector Matrix in Celery and return the task id."""
    try:
        from tasks import run_simulation_inspector_task

        celery_task = run_simulation_inspector_task.apply_async(
            args=[request.model_dump()]
        )
        return {
            "task_id": celery_task.id,
            "status": "PENDING",
            "total": len(request.assets) * len(request.variants),
        }
    except Exception as e:
        logger.error(f"Failed to queue simulation inspector task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@simulation_router.get("/inspector/status/{task_id}")
async def get_inspector_task_status(task_id: str):
    """Return current Celery/Redis state for an Inspector Matrix task."""
    try:
        from celery.result import AsyncResult
        from tasks import celery_app

        celery_result = AsyncResult(task_id, app=celery_app)
        state = await asyncio.to_thread(_read_simulation_inspector_state, task_id)
        return {
            "task_id": task_id,
            "celery_status": celery_result.state,
            "state": state,
        }
    except Exception as e:
        logger.error(
            f"Failed to read simulation inspector task status {task_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


def _simulation_inspector_stream_response(
    task_id: str, total_hint: Optional[int] = None
) -> StreamingResponse:
    async def generate_task_events() -> AsyncGenerator[str, None]:
        try:
            from celery.result import AsyncResult
            from tasks import celery_app
        except Exception as e:
            yield f"data: {_json_dumps({'type': 'error', 'task_id': task_id, 'message': f'Celery unavailable: {e}'})}\n\n"
            return

        last_event_count = 0
        started = False

        while True:
            state = await asyncio.to_thread(_read_simulation_inspector_state, task_id)
            celery_result = AsyncResult(task_id, app=celery_app)

            if not started:
                assets = state.get("assets", []) if isinstance(state, dict) else []
                variants = state.get("variants", []) if isinstance(state, dict) else []
                total = state.get("total") if isinstance(state, dict) else total_hint
                yield f"data: {_json_dumps({'type': 'start', 'task_id': task_id, 'total': total or total_hint or 0, 'assets': assets, 'variants': variants})}\n\n"
                started = True

            new_events = await asyncio.to_thread(
                _read_simulation_inspector_events, task_id, last_event_count
            )
            for event in new_events:
                yield f"data: {_json_dumps(event)}\n\n"
            last_event_count += len(new_events)

            if state:
                status_value = str(state.get("status") or celery_result.state).upper()
                if status_value in {"SUCCESS", "COMPLETED"}:
                    yield f"data: {_json_dumps({'type': 'complete', 'task_id': task_id, 'total': state.get('total', total_hint or 0)})}\n\n"
                    break
                if status_value in {"FAILURE", "FAILED"}:
                    yield f"data: {_json_dumps({'type': 'error', 'task_id': task_id, 'message': state.get('error') or 'Inspector task failed'})}\n\n"
                    break

                yield f"data: {_json_dumps({'type': 'heartbeat', 'task_id': task_id, 'progress': _api_float(state.get('progress', 0))})}\n\n"
            elif celery_result.state == "FAILURE":
                yield f"data: {_json_dumps({'type': 'error', 'task_id': task_id, 'message': str(celery_result.info)})}\n\n"
                break
            elif celery_result.state in {"SUCCESS"}:
                yield f"data: {_json_dumps({'type': 'complete', 'task_id': task_id, 'total': total_hint or 0})}\n\n"
                break
            else:
                yield f": keep-alive {task_id}\n\n"

            await asyncio.sleep(1)

    return StreamingResponse(
        generate_task_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


@simulation_router.get("/inspector/celery/stream/{task_id}")
async def stream_existing_inspector_task(task_id: str):
    """Stream Redis-backed progress for an already queued Inspector Matrix task."""
    return _simulation_inspector_stream_response(task_id)


@simulation_router.post(
    "/inspector/celery/stream",
    dependencies=[Depends(require_permission("run_simulation"))],
)
async def run_inspector_celery_stream(request: InspectorRequest):
    """
    Queue Inspector Matrix in Celery and stream Redis-backed progress.
    Keeps the frontend SSE contract compatible with /inspector/stream.
    """
    try:
        from tasks import run_simulation_inspector_task
    except Exception as e:
        logger.error(f"Simulation inspector Celery imports failed: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Celery unavailable: {e}")

    celery_task = run_simulation_inspector_task.apply_async(args=[request.model_dump()])
    task_id = celery_task.id
    total_tasks = len(request.assets) * len(request.variants)
    logger.info(f"[SSE/Celery] Inspector task queued: {task_id}")
    return _simulation_inspector_stream_response(task_id, total_tasks)


@simulation_router.post(
    "/inspector/stream", dependencies=[Depends(require_permission("run_simulation"))]
)
async def run_inspector_stream(request: InspectorRequest):
    """
    SSE Streaming Inspector - returns results as backtests complete.
    Format: Server-Sent Events (SSE)
    """
    logger.info(f"[SSE] Inspector stream started in worker PID: {os.getpid()}.")
    logger.info(f"Dates received: start={request.start_date}, end={request.end_date}")
    logger.info(f"Downloader available: {DOWNLOADER_AVAILABLE}")

    # 1. Automatic Data Download (if dates provided)
    if DOWNLOADER_AVAILABLE and request.start_date and request.end_date:
        try:
            logger.info(
                f"Checking data for automatic download: {request.start_date} - {request.end_date}"
            )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                ensure_data_for_period,
                request.assets,
                request.start_date,
                request.end_date,
                DATA_STORAGE_PATH,
            )
        except Exception as e:
            logger.error(f"Automatic data download failed: {e}")

    async def generate_results() -> AsyncGenerator[str, None]:
        if not BACKTESTER_AVAILABLE or not LOADER_AVAILABLE:
            yield f"data: {_json_dumps({'type': 'error', 'message': 'Backtester not available'})}\n\n"
            return

        total_tasks = len(request.assets) * len(request.variants)
        completed = 0

        # Send initial status
        yield f"data: {_json_dumps({'type': 'start', 'total': total_tasks, 'assets': request.assets, 'variants': request.variants})}\n\n"

        for asset_idx, asset in enumerate(request.assets):
            try:
                # Data loading - path to parquet file
                parquet_path = DATA_STORAGE_PATH / asset / "kline_1m.parquet"
                if not parquet_path.exists():
                    logger.warning(f"No parquet file for {asset}: {parquet_path}")
                    for variant in request.variants:
                        completed += 1
                        result = {
                            "type": "result",
                            "asset": asset,
                            "variant": variant,
                            "data": {
                                "pnl_pct": 0,
                                "win_rate": 0,
                                "trades_count": 0,
                                "sharpe": 0,
                            },
                            "progress": round(completed / total_tasks * 100, 1),
                        }
                        yield f"data: {_json_dumps(result)}\n\n"
                    continue

                klines = await asyncio.to_thread(
                    load_asset_data, parquet_path, include_tape=False
                )

                # DEBUG: Log loaded data fingerprint for first asset
                if asset_idx == 0 and klines is not None and not klines.empty:
                    logger.info(
                        f"DEBUG LOADED DATA [{asset}]: rows={len(klines)}, cols={len(klines.columns)}, close_sum={klines['close'].sum():.2f}"
                    )

                if klines is None or klines.empty:
                    logger.warning(f"No data for {asset}")
                    for variant in request.variants:
                        completed += 1
                        result = {
                            "type": "result",
                            "asset": asset,
                            "variant": variant,
                            "data": {
                                "pnl_pct": 0,
                                "win_rate": 0,
                                "trades_count": 0,
                                "sharpe": 0,
                                "max_dd": 0,
                                "commission": 0,
                            },
                            "progress": round(completed / total_tasks * 100, 1),
                        }
                        yield f"data: {_json_dumps(result)}\n\n"
                    continue

                backtest_data = build_simulation_mtf_data(klines)

                for variant in request.variants:
                    try:
                        # Check if this is a custom variant
                        custom_variant_config = None
                        if request.custom_variants:
                            for cv in request.custom_variants:
                                if cv.get("id") == variant:
                                    custom_variant_config = cv
                                    break

                        def execute_variant_backtest():
                            if custom_variant_config:
                                try:
                                    cv_model = CustomVariantConfig(
                                        **custom_variant_config
                                    )
                                    return run_custom_variant_backtest(
                                        backtest_data,
                                        request.strategy_json,
                                        cv_model,
                                        request.start_date,
                                        request.end_date,
                                        asset=asset,
                                    )
                                except Exception as cv_err:
                                    logger.warning(
                                        f"Custom variant parsing failed for {variant}: {cv_err}, falling back to built-in"
                                    )
                            return run_variant_backtest(
                                backtest_data,
                                request.strategy_json,
                                variant,
                                request.start_date,
                                request.end_date,
                                asset=asset,
                            )

                        task = asyncio.create_task(
                            asyncio.to_thread(execute_variant_backtest)
                        )
                        yield f"data: {_json_dumps({'type': 'heartbeat', 'asset': asset, 'variant': variant, 'progress': round(completed / total_tasks * 100, 1)})}\n\n"
                        while not task.done():
                            yield f": keep-alive {asset}/{variant}\n\n"
                            await asyncio.sleep(10)
                        bt_result = await task

                        kpis = bt_result.get("kpis", {})
                        trade_log = bt_result.get("trade_log", [])
                        phantom_log = bt_result.get(
                            "phantom_log", []
                        )  # Phantom trades for BE analysis

                        # Format trades for frontend (all trades for simulation)
                        formatted_trades = []
                        for trade in trade_log:  # All trades for portfolio simulation
                            entry_time = trade.get("entry_time")
                            exit_time = trade.get("exit_time")

                            # Convert time to ms
                            if hasattr(entry_time, "timestamp"):
                                entry_time = int(entry_time.timestamp() * 1000)
                            elif (
                                isinstance(entry_time, (int, float))
                                and entry_time < 1e12
                            ):
                                entry_time = int(entry_time * 1000)

                            if hasattr(exit_time, "timestamp"):
                                exit_time = int(exit_time.timestamp() * 1000)
                            elif (
                                isinstance(exit_time, (int, float)) and exit_time < 1e12
                            ):
                                exit_time = int(exit_time * 1000)

                            formatted_trades.append(
                                {
                                    "entryTime": _to_ms_safe(entry_time),
                                    "exitTime": _to_ms_safe(exit_time),
                                    "entryPrice": _api_float(
                                        trade.get("entry_price", 0)
                                    ),
                                    "exitPrice": _api_float(trade.get("exit_price", 0)),
                                    "pnlPct": _api_float(trade.get("pnl_pct", 0)),
                                }
                            )

                        # Format phantom trades for frontend
                        formatted_phantoms = []
                        for pt in phantom_log:
                            formatted_phantoms.append(
                                {
                                    "entryTime": _to_ms_safe(pt.get("entry_time")),
                                    "beExitTime": _to_ms_safe(pt.get("be_exit_time")),
                                    "entryPrice": _api_float(pt.get("entry_price", 0)),
                                    "initialSl": _api_float(pt.get("initial_sl", 0)),
                                    "initialTp": _api_float(pt.get("initial_tp", 0)),
                                    "beExitPrice": _api_float(
                                        pt.get("be_exit_price", 0)
                                    ),
                                    "direction": pt.get("direction", ""),
                                    "phantomStatus": pt.get(
                                        "phantom_status", "TIMEOUT"
                                    ),
                                    "phantomExitTime": _to_ms_safe(
                                        pt.get("phantom_exit_time")
                                    ),
                                    "phantomExitPrice": _api_float(
                                        pt.get("phantom_exit_price", 0)
                                    )
                                    if pt.get("phantom_exit_price")
                                    else None,
                                    "phantomPnlPct": _api_float(
                                        pt.get("phantom_pnl_pct", 0)
                                    )
                                    if pt.get("phantom_pnl_pct")
                                    else None,
                                    "mfeAfterBe": _api_float(pt.get("mfe_after_be", 0)),
                                    "maeAfterBe": _api_float(pt.get("mae_after_be", 0)),
                                    "candlesToResolution": _api_int(
                                        pt.get("candles_to_resolution", 0)
                                    ),
                                }
                            )

                        completed += 1
                        result = {
                            "type": "result",
                            "asset": asset,
                            "variant": variant,
                            "data": {
                                "pnl_pct": _api_float(kpis.get("total_pnl_pct", 0)),
                                "win_rate": _api_float(kpis.get("win_rate", 0)),
                                "trades_count": _api_int(kpis.get("total_trades", 0)),
                                "sharpe": _api_float(kpis.get("sharpe_ratio", 0)),
                                "max_dd": _api_float(kpis.get("max_dd", 0)),
                                "commission": _api_float(
                                    kpis.get("total_commission", 0)
                                ),
                                "trades": formatted_trades,  # Add trades
                                "phantomTrades": formatted_phantoms,  # Add phantom trades
                            },
                            "progress": round(completed / total_tasks * 100, 1),
                        }
                        yield f"data: {_json_dumps(result)}\n\n"

                        # Brief pause to avoid blocking event loop
                        await asyncio.sleep(0.01)

                    except Exception as e:
                        completed += 1
                        logger.error(f"Inspector error for {asset}/{variant}: {e}")
                        result = {
                            "type": "result",
                            "asset": asset,
                            "variant": variant,
                            "data": {
                                "pnl_pct": 0,
                                "win_rate": 0,
                                "trades_count": 0,
                                "sharpe": 0,
                                "max_dd": 0,
                                "commission": 0,
                            },
                            "progress": round(completed / total_tasks * 100, 1),
                            "error": str(e),
                        }
                        yield f"data: {_json_dumps(result)}\n\n"

            except Exception as e:
                logger.error(f"Data load error for {asset}: {e}")
                for variant in request.variants:
                    completed += 1
                    result = {
                        "type": "result",
                        "asset": asset,
                        "variant": variant,
                        "data": {
                            "pnl_pct": 0,
                            "win_rate": 0,
                            "trades_count": 0,
                            "sharpe": 0,
                            "max_dd": 0,
                            "commission": 0,
                        },
                        "progress": round(completed / total_tasks * 100, 1),
                        "error": str(e),
                    }
                    yield f"data: {_json_dumps(result)}\n\n"

        # Completion
        yield f"data: {_json_dumps({'type': 'complete', 'total': total_tasks})}\n\n"

    return StreamingResponse(
        generate_results(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",  # CORS for SSE
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


@simulation_router.post(
    "/backtest",
    response_model=List[BacktestResult],
    dependencies=[Depends(require_permission("run_simulation"))],
)
async def run_backtest(request: BacktestRequest):
    """Run vector backtest for a list of assets"""
    results = []

    for asset in request.assets:
        try:
            # Load asset data
            parquet_path = DATA_STORAGE_PATH / asset / "kline_1m.parquet"
            if not parquet_path.exists():
                logger.warning(f"Asset data not found: {parquet_path}")
                continue

            klines = await asyncio.to_thread(
                load_asset_data, parquet_path, include_tape=False
            )

            if klines is None or klines.empty:
                logger.warning(f"No klines data for {asset}")
                continue

            backtest_data = build_simulation_mtf_data(klines)

            # Run backtester
            backtester = FastVectorBacktester(
                klines_input=backtest_data,
                strategy_json=request.strategy_json,
                use_oracle=request.use_oracle,
            )
            kpis = await asyncio.to_thread(backtester.run)

            # Form equity curve
            trades_list = backtester.trades if hasattr(backtester, "trades") else []
            equity_curve = []
            cumulative = 0
            for trade in trades_list:
                if isinstance(trade, dict):
                    cumulative += trade.get("pnl_pct", 0)
                    exit_time = trade.get("exit_time")
                    if exit_time:
                        ts = (
                            exit_time.timestamp() * 1000
                            if hasattr(exit_time, "timestamp")
                            else exit_time
                        )
                        equity_curve.append([ts, cumulative])

            results.append(
                BacktestResult(
                    asset=asset,
                    kpis=kpis,
                    trades=[t if isinstance(t, dict) else {} for t in trades_list],
                    equity_curve=equity_curve,
                )
            )

        except Exception as e:
            logger.error(f"Backtest error for {asset}: {e}")
            results.append(
                BacktestResult(
                    asset=asset, kpis={"error": str(e)}, trades=[], equity_curve=[]
                )
            )

    return results


@simulation_router.post(
    "/inspector",
    response_model=InspectorMatrixResult,
    dependencies=[Depends(require_permission("run_simulation"))],
)
async def run_inspector(request: InspectorRequest):
    """Run Inspector Matrix for multiple assets and variants (synchronous, without streaming)"""
    if not BACKTESTER_AVAILABLE or not LOADER_AVAILABLE:
        raise HTTPException(
            status_code=503, detail="Backtester or loader not available"
        )

    matrix: Dict[str, Dict[str, InspectorCell]] = {}

    for asset in request.assets:
        matrix[asset] = {}

        try:
            # Load data
            parquet_path = DATA_STORAGE_PATH / asset / "kline_1m.parquet"
            if not parquet_path.exists():
                logger.warning(f"No parquet file for {asset}")
                for variant in request.variants:
                    matrix[asset][variant] = InspectorCell(
                        pnl_pct=0, win_rate=0, trades_count=0, sharpe=0
                    )
                continue

            klines = await asyncio.to_thread(
                load_asset_data, parquet_path, include_tape=False
            )

            if klines is None or klines.empty:
                logger.warning(f"No data for {asset}")
                for variant in request.variants:
                    matrix[asset][variant] = InspectorCell(
                        pnl_pct=0, win_rate=0, trades_count=0, sharpe=0
                    )
                continue

            backtest_data = build_simulation_mtf_data(klines)

            for variant in request.variants:
                try:
                    # Check if this is a custom variant
                    custom_variant_config = None
                    if request.custom_variants:
                        for cv in request.custom_variants:
                            if cv.get("id") == variant:
                                custom_variant_config = cv
                                break

                    if custom_variant_config:
                        # Use custom variant backtest
                        try:
                            cv_model = CustomVariantConfig(**custom_variant_config)
                            result = run_custom_variant_backtest(
                                backtest_data,
                                request.strategy_json,
                                cv_model,
                                asset=asset,
                            )
                        except Exception as cv_err:
                            logger.warning(
                                f"Custom variant parsing failed for {variant}: {cv_err}, falling back to built-in"
                            )
                            result = run_variant_backtest(
                                backtest_data,
                                request.strategy_json,
                                variant,
                                asset=asset,
                            )
                    else:
                        # Use built-in variant backtest
                        result = run_variant_backtest(
                            backtest_data, request.strategy_json, variant, asset=asset
                        )

                    kpis = result["kpis"]  # Extract kpis from result dict

                    matrix[asset][variant] = InspectorCell(
                        pnl_pct=kpis.get("total_pnl_pct", 0),
                        win_rate=kpis.get("win_rate", 0),
                        trades_count=kpis.get("total_trades", 0),
                        sharpe=kpis.get("sharpe_ratio", 0),
                        max_dd=kpis.get("max_dd", 0),
                        commission=kpis.get("total_commission", 0),
                    )

                except Exception as e:
                    logger.error(f"Inspector error for {asset}/{variant}: {e}")
                    matrix[asset][variant] = InspectorCell(
                        pnl_pct=0,
                        win_rate=0,
                        trades_count=0,
                        sharpe=0,
                        max_dd=0,
                        commission=0,
                    )

        except Exception as e:
            logger.error(f"Data load error for {asset}: {e}")
            for variant in request.variants:
                matrix[asset][variant] = InspectorCell(
                    pnl_pct=0,
                    win_rate=0,
                    trades_count=0,
                    sharpe=0,
                    max_dd=0,
                    commission=0,
                )

    return InspectorMatrixResult(
        matrix=matrix, assets=request.assets, variants=request.variants
    )


@simulation_router.post(
    "/portfolio",
    response_model=PortfolioSimulationResult,
    dependencies=[Depends(require_permission("run_simulation"))],
)
async def run_portfolio_simulation(request: PortfolioSimulationRequest):
    """Run sequential portfolio simulation (with ready trades)"""
    if not SIMULATOR_AVAILABLE:
        raise HTTPException(
            status_code=503, detail="SequentialPortfolioSimulator not available"
        )

    try:
        import pandas as pd

        config = SimulatorConfig(
            initial_capital=request.config.initial_capital,
            max_concurrent_positions=request.config.max_concurrent_positions,
            base_risk_pct=request.config.base_risk_pct,
            leverage=request.config.leverage,
            adaptive_risk_enabled=request.config.adaptive_risk,
            # compounding_enabled removed
        )

        simulator = SequentialPortfolioSimulator(config)
        trades_df = pd.DataFrame(request.trades)

        # Column name normalization (camelCase -> snake_case)
        trades_df.rename(
            columns={
                "entryTime": "entry_time",
                "exitTime": "exit_time",
                "entryPrice": "entry_price",
                "exitPrice": "exit_price",
                "pnlPct": "pnl_pct",
                "pnlAmount": "pnl_amount",
            },
            inplace=True,
        )

        if trades_df.empty:
            raise HTTPException(status_code=400, detail="No trades provided")

        # Convert timestamps from milliseconds to datetime
        if "entry_time" in trades_df.columns:
            trades_df["entry_time"] = pd.to_datetime(
                trades_df["entry_time"], unit="ms", utc=True
            )
        if "exit_time" in trades_df.columns:
            trades_df["exit_time"] = pd.to_datetime(
                trades_df["exit_time"], unit="ms", utc=True
            )

        # Sort by entry time
        trades_df = trades_df.sort_values("entry_time").reset_index(drop=True)

        stats = await asyncio.to_thread(simulator.simulate, trades_df)

        equity_curve = []

        # Retrieve data from stats (DataFrame inside)
        if "equity_curve" in stats and not stats["equity_curve"].empty:
            df_eq = stats["equity_curve"]
            for _, row in df_eq.iterrows():
                ts = row["time"]
                val = row["capital"]
                dd = row["drawdown"]

                equity_curve.append(
                    {
                        "time": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                        "value": float(round(val, 2)),
                        "drawdown": float(round(dd, 2)),
                    }
                )
        elif hasattr(simulator, "equity_curve") and simulator.equity_curve:
            # Fallback to class attribute
            for item in simulator.equity_curve:
                # item is a dictionary {'time': ..., 'capital': ..., 'drawdown': ...}
                ts = item["time"]
                val = item["capital"]
                dd = item["drawdown"]

                equity_curve.append(
                    {
                        "time": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                        "value": float(round(val, 2)),
                        "drawdown": float(round(dd, 2)),
                    }
                )

        return format_simulation_response(stats, equity_curve, [])

    except Exception as e:
        logger.error(f"Portfolio simulation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@simulation_router.post(
    "/portfolio-full",
    response_model=PortfolioSimulationResult,
    dependencies=[Depends(require_permission("run_simulation"))],
)
async def run_portfolio_full(request: PortfolioFullRequest):
    """
    Full portfolio simulation:
    1. Runs backtest for all assets with chosen variant
    2. Collects trades internally
    3. Passes them to SequentialPortfolioSimulator
    4. Returns results
    """
    import pandas as pd

    # Detailed diagnostic of module availability
    if not BACKTESTER_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="FastVectorBacktester module not loaded properly. Check server logs.",
        )

    if not LOADER_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="load_asset_data module not loaded properly. Check server logs.",
        )

    if not SIMULATOR_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="SequentialPortfolioSimulator not available. Check server startup logs for import errors.",
        )

    all_trades = []

    try:
        # 1. Collect trades from all assets and ALL variants
        for asset in request.assets:
            try:
                parquet_path = DATA_STORAGE_PATH / asset / "kline_1m.parquet"
                if not parquet_path.exists():
                    logger.warning(f"No parquet file for {asset}")
                    continue

                klines = await asyncio.to_thread(
                    load_asset_data, parquet_path, include_tape=False
                )

                if klines is None or klines.empty:
                    logger.warning(f"No data for {asset}")
                    continue

                backtest_data = build_simulation_mtf_data(klines)

                # Run through ALL selected variants
                for variant in request.variants:
                    try:
                        # Create variant config
                        config = copy.deepcopy(request.strategy_json)
                        if "initialization" not in config:
                            config["initialization"] = {}
                        if "params" not in config["initialization"]:
                            config["initialization"]["params"] = {}

                        init_params = config["initialization"]["params"]
                        use_oracle = variant not in ["raw"]

                        # Apply variant settings (as in run_variant_backtest)
                        if variant == "oracle_entry":
                            init_params["regime_exit_enabled"] = False
                        elif variant == "oracle_be":
                            init_params["regime_exit_enabled"] = True
                            init_params["regime_exit_mode"] = "breakeven"
                        elif variant == "oracle_be_time":
                            init_params["regime_exit_enabled"] = True
                            init_params["regime_exit_mode"] = "breakeven"
                        elif variant == "oracle_partial":
                            init_params["regime_exit_enabled"] = True
                            init_params["regime_exit_mode"] = "breakeven"
                            init_params["partial_exits"] = [
                                {
                                    "tp_type": "rr_multiplier",
                                    "tp_value": 1.5,
                                    "size_pct": 30,
                                },
                                {
                                    "tp_type": "rr_multiplier",
                                    "tp_value": 2.5,
                                    "size_pct": 30,
                                },
                            ]
                            init_params["move_sl_to_be_on_first_tp"] = True
                        elif variant == "trailing_dev":
                            init_params["regime_exit_enabled"] = False
                            init_params["sim_trailing_pct"] = 0.01
                        elif variant == "be_at_1rr":
                            init_params["regime_exit_enabled"] = False
                            init_params["sim_breakeven_rr"] = 1.0
                        elif variant == "hybrid_be":
                            init_params["regime_exit_enabled"] = True
                            init_params["regime_exit_mode"] = "breakeven"
                            init_params["sim_breakeven_rr"] = 1.0
                        elif variant == "hybrid_be_time":
                            init_params["regime_exit_enabled"] = True
                            init_params["regime_exit_mode"] = "breakeven"
                            init_params["sim_breakeven_rr"] = 2.0

                        bt = FastVectorBacktester(
                            backtest_data, config, use_oracle=use_oracle
                        )
                        await asyncio.to_thread(bt.run)

                        # Collect trades
                        if hasattr(bt, "trade_log") and bt.trade_log:
                            for trade in _filter_user_visible_trades(bt.trade_log):
                                trade_copy = (
                                    trade.copy() if isinstance(trade, dict) else {}
                                )
                                trade_copy["asset"] = asset
                                trade_copy["variant"] = variant
                                trade_copy["strategy"] = (
                                    variant  # Simulator requires 'strategy' key
                                )
                                all_trades.append(trade_copy)

                    except Exception as e:
                        logger.error(
                            f"Trade collection error for {asset}/{variant}: {e}"
                        )
                        continue

            except Exception as e:
                logger.error(f"Data load error for {asset}: {e}")
                continue

        if not all_trades:
            return format_simulation_response(
                stats={}, equity_curve=[], trades_summary=[]
            )

        # 3. Run SequentialPortfolioSimulator
        trades_df = pd.DataFrame(all_trades)

        # Normalize columns for simulator
        if "entry_time" in trades_df.columns:
            trades_df["timestamp"] = pd.to_datetime(trades_df["entry_time"])
        elif "timestamp" not in trades_df.columns and len(trades_df) > 0:
            trades_df["timestamp"] = pd.Timestamp.now()

        sim_config = SimulatorConfig(
            initial_capital=request.config.initial_capital,
            max_concurrent_positions=request.config.max_concurrent_positions,
            base_risk_pct=request.config.base_risk_pct,
            leverage=request.config.leverage,
            adaptive_risk_enabled=request.config.adaptive_risk,
            # compounding_enabled not supported in current SimulatorConfig version
        )

        simulator = SequentialPortfolioSimulator(sim_config)
        stats = await asyncio.to_thread(simulator.simulate, trades_df)

        # DEBUG: Log stats structure
        logger.info(
            f"Stats keys: {stats.keys() if isinstance(stats, dict) else 'NOT A DICT'}"
        )
        if isinstance(stats, dict) and "equity_curve" in stats:
            eq = stats["equity_curve"]
            logger.info(
                f"equity_curve type: {type(eq)}, length: {len(eq) if hasattr(eq, '__len__') else 'N/A'}"
            )

        # 4. Form result
        equity_curve = []

        # Retrieve data from stats (DataFrame inside)
        eq_in_stats = "equity_curve" in stats
        eq_is_empty = stats["equity_curve"].empty if eq_in_stats else True
        logger.info(f"equity_curve in stats: {eq_in_stats}, empty: {eq_is_empty}")

        if eq_in_stats and not eq_is_empty:
            df_eq = stats["equity_curve"]
            logger.info(f"equity_curve columns: {list(df_eq.columns)}")

            # Determine column names (may differ)
            time_col = (
                "time"
                if "time" in df_eq.columns
                else "timestamp"
                if "timestamp" in df_eq.columns
                else None
            )
            capital_col = (
                "capital"
                if "capital" in df_eq.columns
                else "equity"
                if "equity" in df_eq.columns
                else "value"
                if "value" in df_eq.columns
                else None
            )
            dd_col = (
                "drawdown"
                if "drawdown" in df_eq.columns
                else "dd"
                if "dd" in df_eq.columns
                else None
            )

            logger.info(
                f"Using columns: time={time_col}, capital={capital_col}, dd={dd_col}"
            )

            # Convert DataFrame to list of dictionaries of expected format
            for idx, row in df_eq.iterrows():
                # Retrieve time (from column or index)
                if time_col:
                    ts = row[time_col]
                else:
                    ts = idx

                # Retrieve capital
                val = row[capital_col] if capital_col else 10000

                # Retrieve drawdown
                dd = row[dd_col] if dd_col else 0

                # Convert time to milliseconds
                if hasattr(ts, "timestamp"):
                    ts_ms = int(ts.timestamp() * 1000)
                elif isinstance(ts, (int, float)):
                    ts_ms = int(ts * 1000) if ts < 1e12 else int(ts)
                else:
                    ts_ms = 0

                # Safeguard against NaN/Infinity
                import math

                safe_val = (
                    float(round(val, 2))
                    if (
                        isinstance(val, (int, float))
                        and not math.isnan(val)
                        and not math.isinf(val)
                    )
                    else 10000.0
                )
                safe_dd = (
                    float(round(dd, 2))
                    if (
                        isinstance(dd, (int, float))
                        and not math.isnan(dd)
                        and not math.isinf(dd)
                    )
                    else 0.0
                )

                equity_curve.append(
                    {"time": ts_ms, "value": safe_val, "drawdown": safe_dd}
                )
        elif hasattr(simulator, "equity_curve") and simulator.equity_curve:
            # Fallback to class attribute (list of dictionaries)
            for item in simulator.equity_curve:
                # item is a dictionary {'time': ..., 'capital': ..., 'drawdown': ...}
                ts = item["time"]
                val = item["capital"]
                dd = item["drawdown"]

                # Convert time to milliseconds
                if hasattr(ts, "timestamp"):
                    ts_ms = int(ts.timestamp() * 1000)
                elif isinstance(ts, (int, float)):
                    ts_ms = int(ts * 1000) if ts < 1e12 else int(ts)
                else:
                    ts_ms = 0

                equity_curve.append(
                    {
                        "time": ts_ms,
                        "value": float(round(val, 2)),
                        "drawdown": float(round(dd, 2)),
                    }
                )

        # Summary of trades (not all, aggregated only)
        trades_summary = [
            {
                "asset": asset,
                "count": len([t for t in all_trades if t.get("asset") == asset]),
            }
            for asset in request.assets
        ]

        logger.info(f"Final equity_curve length before return: {len(equity_curve)}")

        return format_simulation_response(stats, equity_curve, trades_summary)

    except Exception as e:
        logger.error(f"Portfolio full simulation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@simulation_router.post("/upload-strategy")
async def upload_strategy(file: UploadFile = File(...)):
    """Load strategy JSON file"""
    try:
        content = await file.read()
        strategy = json.loads(content.decode("utf-8"))

        # Validate structure
        if not isinstance(strategy, dict):
            raise HTTPException(status_code=400, detail="Invalid strategy format")

        return {"filename": file.filename, "strategy": strategy, "valid": True}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@simulation_router.post("/asset-detail/{asset}")
async def get_asset_detail(asset: str, request: AssetDetailRequest):
    """Get detailed asset data for Deep Dive view"""
    if not BACKTESTER_AVAILABLE or not LOADER_AVAILABLE:
        raise HTTPException(
            status_code=503, detail="Backtester or data loader not available"
        )

    try:
        import pandas as pd

        # 1. Load data WITH ORACLE - use the same method as inspector
        parquet_path = DATA_STORAGE_PATH / asset / "kline_1m.parquet"
        if not parquet_path.exists():
            raise HTTPException(
                status_code=404, detail=f"Asset data not found: {asset}"
            )

        # Use load_asset_data to get merged data with Oracle
        try:
            df = load_asset_data(parquet_path, include_tape=False)
        except Exception as e:
            logger.warning(f"load_asset_data failed, falling back to read_parquet: {e}")
            df = pd.read_parquet(parquet_path)

        backtest_data = build_simulation_mtf_data(df)

        # 2. Form klines for chart (last 5000 candles to cover trades period)
        df_chart = df.tail(5000).copy()
        klines = []

        # Determine time column
        time_col = (
            "time"
            if "time" in df_chart.columns
            else "timestamp"
            if "timestamp" in df_chart.columns
            else None
        )

        for idx, row in df_chart.iterrows():
            # Get timestamp
            if time_col:
                ts = row[time_col]
            else:
                ts = idx  # Use index if time column is missing

            if hasattr(ts, "timestamp"):
                ts = int(ts.timestamp() * 1000)
            elif isinstance(ts, (int, float)) and ts < 1e12:
                ts = int(ts * 1000)
            else:
                ts = int(ts) if ts else 0

            klines.append(
                {
                    "time": ts,
                    "open": float(row["open"]) if "open" in row.index else 0,
                    "high": float(row["high"]) if "high" in row.index else 0,
                    "low": float(row["low"]) if "low" in row.index else 0,
                    "close": float(row["close"]) if "close" in row.index else 0,
                }
            )

        # 3. Extract Oracle zones (Amnesia/Paranoia)
        oracle_zones = []
        regime_col = None

        # APPLY ORACLE MODEL to get regime predictions
        oracle = get_oracle()
        if oracle is not None:
            try:
                df_chart = apply_oracle_signal(df_chart, oracle, ORACLE_THRESHOLD)
                regime_col = (
                    "oracle_regime"  # This column is created by apply_oracle_signal
                )
                logger.info(
                    f"Oracle applied to {asset}: {df_chart['oracle_regime'].value_counts().to_dict()}"
                )
            except Exception as e:
                logger.warning(f"Failed to apply Oracle for zones: {e}")

        # Fallback: search for existing regime column if Oracle failed
        if regime_col is None or regime_col not in df_chart.columns:
            for col in df_chart.columns:
                if (
                    "regime" in col.lower()
                    or "oracle" in col.lower()
                    or "momentum" in col.lower()
                ):
                    regime_col = col
                    break

        if regime_col:
            # Group consecutive identical regime values
            df_chart["regime_group"] = (
                df_chart[regime_col] != df_chart[regime_col].shift()
            ).cumsum()

            for _, group in df_chart.groupby("regime_group"):
                if len(group) < 2:
                    continue

                first_row = group.iloc[0]
                last_row = group.iloc[-1]

                regime_val = first_row[regime_col]

                # Determine regime type
                # 0 = paranoia (flat), 1 = amnesia (trend)
                regime_type = "amnesia"  # Default is trend
                if isinstance(regime_val, str):
                    if "paranoia" in regime_val.lower() or "flat" in regime_val.lower():
                        regime_type = "paranoia"
                elif isinstance(regime_val, (int, float)):
                    # 0 = paranoia (flat), 1 = amnesia (trend)
                    if regime_val == 0:
                        regime_type = "paranoia"

                # Get timestamps
                start_ts = (
                    first_row.get("time")
                    or first_row.get("timestamp")
                    or first_row.name
                )
                end_ts = (
                    last_row.get("time") or last_row.get("timestamp") or last_row.name
                )

                if hasattr(start_ts, "timestamp"):
                    start_ts = int(start_ts.timestamp() * 1000)
                elif isinstance(start_ts, (int, float)) and start_ts < 1e12:
                    start_ts = int(start_ts * 1000)

                if hasattr(end_ts, "timestamp"):
                    end_ts = int(end_ts.timestamp() * 1000)
                elif isinstance(end_ts, (int, float)) and end_ts < 1e12:
                    end_ts = int(end_ts * 1000)

                oracle_zones.append(
                    {
                        "startTime": int(start_ts),
                        "endTime": int(end_ts),
                        "regime": regime_type,
                    }
                )

        # 4. Run backtest to get trades
        trades = []
        for variant in request.variants:
            try:
                result = run_variant_backtest(
                    backtest_data, request.strategy_json, variant, asset=asset
                )
                if result and "trade_log" in result:
                    for trade in result["trade_log"]:
                        entry_time = trade.get("entry_time")
                        exit_time = trade.get("exit_time")

                        # Convert time
                        if hasattr(entry_time, "timestamp"):
                            entry_time = int(entry_time.timestamp() * 1000)
                        elif isinstance(entry_time, (int, float)) and entry_time < 1e12:
                            entry_time = int(entry_time * 1000)

                        if hasattr(exit_time, "timestamp"):
                            exit_time = int(exit_time.timestamp() * 1000)
                        elif isinstance(exit_time, (int, float)) and exit_time < 1e12:
                            exit_time = int(exit_time * 1000)

                        trades.append(
                            {
                                "id": f"{asset}_{variant}_{entry_time}",
                                "entryTime": int(entry_time) if entry_time else 0,
                                "exitTime": int(exit_time) if exit_time else 0,
                                "entryPrice": float(trade.get("entry_price", 0)),
                                "exitPrice": float(trade.get("exit_price", 0)),
                                "pnlPct": float(trade.get("pnl_pct", 0)),
                                "variant": variant,
                            }
                        )
            except Exception as e:
                logger.warning(f"Failed to backtest {variant} for {asset}: {e}")
                continue

        return {"klines": klines, "oracleZones": oracle_zones, "trades": trades}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Asset detail error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
