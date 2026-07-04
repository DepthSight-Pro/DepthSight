# tasks.py
# ruff: noqa: E402

import sys
import asyncio
import nest_asyncio
import json
import logging
import math
from time import time
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, date
from typing import Dict, Optional, Callable, Any, List, Tuple
import redis.asyncio as aredis
import redis
import ast
from collections import defaultdict

# --- 1. Setup path for Celery Worker ---
# This is critical so that a worker started from the command line
# can find all the modules of your project.
# Determine the root folder of the project (where the 'api' and 'bot_module' folders are located)
# and add it to the Python path.
PROJECT_ROOT = Path(
    __file__
).parent.parent  # Go up one level if tasks.py is inside api/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Setup global logging for Celery Worker
from bot_module.logger_setup import setup_global_logging

setup_global_logging("celery_worker.log")
logger = logging.getLogger(__name__)

STATS_EXCLUDED_EXIT_REASONS = {"END_OF_DATA"}

# --- 2. Main imports from the project ---
# Now that the path is set up, imports should work without problems.
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.future import select
from datetime import timedelta
from bot_module import config
from bot_module.trainer import Trainer
from bot_module.depthsight_backtester import DepthSightBacktester
from bot_module.portfolio_backtester import PortfolioBacktester
from bot_module.data_loader import download_klines
from bot_module.genetic_strategy_finder import (
    GeneticStrategyFinder,
    resample_to_timeframes,
)
from bot_module.fast_vector_backtester import FastVectorBacktester
from bot_module.train_offline_model import run_river_training_from_config
from bot_module.train_sklearn_batch import run_sklearn_training_from_config
from bot_module.dataset_generator import DatasetGenerator
from api.database import (
    get_isolated_worker_session,
    AsyncSession,
    get_db,
    get_session_for_worker,
)
from api import crud, schemas, models
from api.analytics_parsers import StrategyConfigParser, DecisionTraceParser
from api.gamification import grant_achievement
from api.genome_analyzer import GenomeAnalyzer
from api.live_runtime import build_deactivate_api_key_command, get_active_api_key_ids
from api.push_sender import send_push_notification  # New import
from bot_module.runtime_dependencies import configure_runtime_dependencies

configure_runtime_dependencies(
    crud_module=crud,
    get_db_factory=get_db,
    push_sender=send_push_notification,
)

# logger = logging.getLogger('bot_module.tasks')
# If the logger is not set up, Celery may intercept output.
# It is best to set up logging when starting the worker.

# --- 3. Setup Celery application ---
# --- 3. Setup Celery application ---
from api.celery_app import (
    celery_app,
    redis_client_for_tasks,
    SIMULATION_INSPECTOR_STATE_TTL_SECONDS,
    _simulation_inspector_state_key,
    _simulation_inspector_events_key,
)


def _simulation_inspector_update_state(
    task_id: str, state_payload: Dict[str, Any]
) -> None:
    if redis_client_for_tasks is None:
        return
    try:
        compact_payload = {k: v for k, v in state_payload.items() if k != "events"}
        redis_client_for_tasks.setex(
            _simulation_inspector_state_key(task_id),
            SIMULATION_INSPECTOR_STATE_TTL_SECONDS,
            json.dumps(convert_datetimes_to_iso(compact_payload), ensure_ascii=False),
        )
    except Exception as redis_err:
        logger.warning(
            f"Simulation inspector task {task_id}: failed to persist Redis state: {redis_err}"
        )


def _simulation_inspector_append_event(
    task_id: str, event_payload: Dict[str, Any]
) -> None:
    if redis_client_for_tasks is None:
        return
    try:
        key = _simulation_inspector_events_key(task_id)
        redis_client_for_tasks.rpush(
            key,
            json.dumps(convert_datetimes_to_iso(event_payload), ensure_ascii=False),
        )
        redis_client_for_tasks.expire(key, SIMULATION_INSPECTOR_STATE_TTL_SECONDS)
    except Exception as redis_err:
        logger.warning(
            f"Simulation inspector task {task_id}: failed to append Redis event: {redis_err}"
        )


def _simulation_inspector_format_result(
    asset: str,
    variant: str,
    bt_result: Dict[str, Any],
    progress: float,
) -> Dict[str, Any]:
    from api.simulation_router import _api_float, _api_int, _to_ms_safe

    kpis = bt_result.get("kpis", {}) if isinstance(bt_result, dict) else {}
    trade_log = bt_result.get("trade_log", []) if isinstance(bt_result, dict) else []
    phantom_log = (
        bt_result.get("phantom_log", []) if isinstance(bt_result, dict) else []
    )

    formatted_trades = []
    for trade in trade_log:
        if not isinstance(trade, dict):
            continue
        formatted_trades.append(
            {
                "entryTime": _to_ms_safe(trade.get("entry_time")),
                "exitTime": _to_ms_safe(trade.get("exit_time")),
                "entryPrice": _api_float(trade.get("entry_price", 0)),
                "exitPrice": _api_float(trade.get("exit_price", 0)),
                "pnlPct": _api_float(trade.get("pnl_pct", 0)),
            }
        )

    formatted_phantoms = []
    for pt in phantom_log:
        if not isinstance(pt, dict):
            continue
        formatted_phantoms.append(
            {
                "entryTime": _to_ms_safe(pt.get("entry_time")),
                "beExitTime": _to_ms_safe(pt.get("be_exit_time")),
                "entryPrice": _api_float(pt.get("entry_price", 0)),
                "initialSl": _api_float(pt.get("initial_sl", 0)),
                "initialTp": _api_float(pt.get("initial_tp", 0)),
                "beExitPrice": _api_float(pt.get("be_exit_price", 0)),
                "direction": pt.get("direction", ""),
                "phantomStatus": pt.get("phantom_status", "TIMEOUT"),
                "phantomExitTime": _to_ms_safe(pt.get("phantom_exit_time")),
                "phantomExitPrice": _api_float(pt.get("phantom_exit_price", 0))
                if pt.get("phantom_exit_price")
                else None,
                "phantomPnlPct": _api_float(pt.get("phantom_pnl_pct", 0))
                if pt.get("phantom_pnl_pct")
                else None,
                "mfeAfterBe": _api_float(pt.get("mfe_after_be", 0)),
                "maeAfterBe": _api_float(pt.get("mae_after_be", 0)),
                "candlesToResolution": _api_int(pt.get("candles_to_resolution", 0)),
            }
        )

    return {
        "type": "result",
        "asset": asset,
        "variant": variant,
        "data": {
            "pnl_pct": _api_float(kpis.get("total_pnl_pct", 0)),
            "win_rate": _api_float(kpis.get("win_rate", 0)),
            "trades_count": _api_int(kpis.get("total_trades", 0)),
            "sharpe": _api_float(kpis.get("sharpe_ratio", 0)),
            "max_dd": _api_float(kpis.get("max_dd", 0)),
            "commission": _api_float(kpis.get("total_commission", 0)),
            "trades": formatted_trades,
            "phantomTrades": formatted_phantoms,
        },
        "progress": progress,
    }


@celery_app.task(bind=True, name="run_simulation_inspector_task")
def run_simulation_inspector_task(self, request_dict: Dict[str, Any]):
    task_id = self.request.id
    logger.info(f"Received simulation inspector task {task_id}")

    from api.simulation_router import (
        DATA_STORAGE_PATH,
        CustomVariantConfig,
        build_simulation_mtf_data,
        run_custom_variant_backtest,
        run_variant_backtest,
    )
    from bot_module.genetic_strategy_finder import load_asset_data

    assets = list(request_dict.get("assets") or [])
    variants = list(request_dict.get("variants") or [])
    strategy_json = request_dict.get("strategy_json") or {}
    custom_variants = request_dict.get("custom_variants") or []
    start_date = request_dict.get("start_date")
    end_date = request_dict.get("end_date")

    total_tasks = max(len(assets) * len(variants), 0)
    state_payload: Dict[str, Any] = {
        "task_id": task_id,
        "status": "PROGRESS",
        "total": total_tasks,
        "completed": 0,
        "progress": 0.0,
        "assets": assets,
        "variants": variants,
        "error": None,
    }
    _simulation_inspector_update_state(task_id, state_payload)
    self.update_state(
        state="PROGRESS",
        meta={"progress_info": {"progress": 0.0, "completed": 0, "total": total_tasks}},
    )

    try:
        if total_tasks == 0:
            state_payload["status"] = "SUCCESS"
            _simulation_inspector_update_state(task_id, state_payload)
            return {
                "task_id": task_id,
                "status": "SUCCESS",
                "total": 0,
                "completed": 0,
                "progress": 100.0,
            }

        custom_variant_by_id = {
            cv.get("id"): cv
            for cv in custom_variants
            if isinstance(cv, dict) and cv.get("id")
        }

        for asset_idx, asset in enumerate(assets):
            try:
                parquet_path = DATA_STORAGE_PATH / asset / "kline_1m.parquet"
                if not parquet_path.exists():
                    raise FileNotFoundError(
                        f"No parquet file for {asset}: {parquet_path}"
                    )

                klines = load_asset_data(parquet_path, include_tape=False)
                if klines is None or klines.empty:
                    raise ValueError(f"No data for {asset}")
                backtest_data = build_simulation_mtf_data(klines)

                for variant in variants:
                    custom_variant_config = custom_variant_by_id.get(variant)
                    try:
                        if custom_variant_config:
                            try:
                                cv_model = CustomVariantConfig(**custom_variant_config)
                                bt_result = run_custom_variant_backtest(
                                    backtest_data,
                                    strategy_json,
                                    cv_model,
                                    start_date,
                                    end_date,
                                    asset=asset,
                                )
                            except Exception as cv_err:
                                logger.warning(
                                    f"Custom variant parsing failed for {variant}: {cv_err}, falling back to built-in"
                                )
                                bt_result = run_variant_backtest(
                                    backtest_data,
                                    strategy_json,
                                    variant,
                                    start_date,
                                    end_date,
                                    asset=asset,
                                )
                        else:
                            bt_result = run_variant_backtest(
                                backtest_data,
                                strategy_json,
                                variant,
                                start_date,
                                end_date,
                                asset=asset,
                            )

                        state_payload["completed"] += 1
                        progress = round(
                            (state_payload["completed"] / total_tasks) * 100, 1
                        )
                        event = _simulation_inspector_format_result(
                            asset, variant, bt_result, progress
                        )
                    except Exception as variant_err:
                        logger.error(
                            f"Simulation inspector error for {asset}/{variant}: {variant_err}",
                            exc_info=True,
                        )
                        state_payload["completed"] += 1
                        progress = round(
                            (state_payload["completed"] / total_tasks) * 100, 1
                        )
                        event = {
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
                            "progress": progress,
                            "error": str(variant_err),
                        }

                    state_payload["progress"] = event["progress"]
                    logger.info(
                        "SIM_INSPECTOR_EVENT task=%s asset=%s variant=%s progress=%s pnl=%s trades=%s error=%s",
                        task_id,
                        asset,
                        variant,
                        event.get("progress"),
                        event.get("data", {}).get("pnl_pct")
                        if isinstance(event.get("data"), dict)
                        else None,
                        event.get("data", {}).get("trades_count")
                        if isinstance(event.get("data"), dict)
                        else None,
                        event.get("error"),
                    )
                    _simulation_inspector_append_event(task_id, event)
                    _simulation_inspector_update_state(task_id, state_payload)
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "progress_info": {
                                "progress": state_payload["progress"],
                                "completed": state_payload["completed"],
                                "total": total_tasks,
                            }
                        },
                    )

            except Exception as asset_err:
                logger.error(
                    f"Simulation inspector data load error for {asset}: {asset_err}",
                    exc_info=True,
                )
                for variant in variants:
                    state_payload["completed"] += 1
                    progress = round(
                        (state_payload["completed"] / total_tasks) * 100, 1
                    )
                    event = {
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
                        "progress": progress,
                        "error": str(asset_err),
                    }
                    state_payload["progress"] = progress
                    _simulation_inspector_append_event(task_id, event)
                    _simulation_inspector_update_state(task_id, state_payload)
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "progress_info": {
                                "progress": progress,
                                "completed": state_payload["completed"],
                                "total": total_tasks,
                            }
                        },
                    )

        state_payload["status"] = "SUCCESS"
        state_payload["progress"] = 100.0
        _simulation_inspector_update_state(task_id, state_payload)
        logger.info(f"Simulation inspector task {task_id} completed successfully.")
        return {
            "task_id": task_id,
            "status": "SUCCESS",
            "total": total_tasks,
            "completed": state_payload["completed"],
            "progress": state_payload["progress"],
        }

    except Exception as e:
        logger.critical(
            f"Simulation inspector task {task_id} failed: {e}", exc_info=True
        )
        state_payload["status"] = "FAILURE"
        state_payload["error"] = str(e)
        _simulation_inspector_update_state(task_id, state_payload)
        raise


# --- 4. Helper to run async code from sync Celery task ---
def run_async_from_sync(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    nest_asyncio.apply(loop)
    try:
        result = loop.run_until_complete(coro)
        return result
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def convert_datetimes_to_iso(obj):
    """
    Recursively traverses an object (dict, list) and converts all
    instances of datetime.datetime and datetime.date into ISO format strings.
    """
    if isinstance(obj, dict):
        return {k: convert_datetimes_to_iso(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_datetimes_to_iso(elem) for elem in obj]
    # Special handling for equity_point tuple (datetime, number)
    elif isinstance(obj, tuple) and len(obj) == 2 and isinstance(obj[0], datetime):
        return (obj[0].isoformat(), obj[1])
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, np.generic):
        return convert_datetimes_to_iso(obj.item())
    elif isinstance(obj, float) and not math.isfinite(obj):
        return None
    else:
        return obj


def _ensure_utc_datetime(value: Any) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()

    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if not isinstance(value, datetime):
        raise ValueError(f"Unsupported datetime value: {value!r}")

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _normalize_exit_reason(value: Any) -> str:
    return str(value or "").upper()


def _trade_is_included_in_stats(trade: Dict[str, Any]) -> bool:
    return (
        _normalize_exit_reason(trade.get("exit_reason"))
        not in STATS_EXCLUDED_EXIT_REASONS
    )


def _split_trades_for_stats(
    trades: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    included: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []

    for trade in trades:
        if _trade_is_included_in_stats(trade):
            included.append(trade)
        else:
            excluded.append(trade)

    return included, excluded


def _normalize_vector_trade_records(
    raw_trades: List[Dict[str, Any]],
    run_id: str,
    initial_balance: float,
    commission_pct: float,
) -> Tuple[List[Dict[str, Any]], float]:
    normalized_trades: List[Dict[str, Any]] = []
    total_commission = 0.0

    for idx, trade in enumerate(raw_trades):
        if "entry_time" not in trade or "exit_time" not in trade:
            continue

        entry_dt = _ensure_utc_datetime(trade["entry_time"])
        exit_dt = _ensure_utc_datetime(trade["exit_time"])
        entry_price = float(
            trade.get("avg_entry_price", trade.get("entry_price", 0.0)) or 0.0
        )
        exit_price = float(trade.get("exit_price", entry_price) or entry_price)
        quantity = float(
            trade.get("filled_quantity", trade.get("quantity", 0.0)) or 0.0
        )
        trade_balance = float(
            trade.get("current_balance", initial_balance) or initial_balance
        )
        commission = float(
            trade.get(
                "commission_usd",
                trade_balance * commission_pct * max(quantity, 0.0) * 2,
            )
        )
        pnl = float(trade.get("pnl_usd", 0.0) or 0.0)

        direction_raw = trade.get("direction", "LONG")
        direction = (
            direction_raw.name
            if hasattr(direction_raw, "name")
            else str(direction_raw).upper()
        )

        raw_executions = (
            trade.get("executions") if isinstance(trade.get("executions"), list) else []
        )
        normalized_executions: List[Dict[str, Any]] = []
        for execution in raw_executions:
            if not isinstance(execution, dict):
                continue
            try:
                normalized_executions.append(
                    {
                        "timestamp": _ensure_utc_datetime(execution.get("timestamp")),
                        "price": float(execution.get("price")),
                        "quantity": float(execution.get("quantity", quantity) or 0.0),
                        "type": str(execution.get("type", "")).upper(),
                    }
                )
            except (TypeError, ValueError):
                continue

        if not normalized_executions:
            normalized_executions = [
                {
                    "timestamp": entry_dt,
                    "price": entry_price,
                    "quantity": quantity,
                    "type": "ENTRY",
                },
                {
                    "timestamp": exit_dt,
                    "price": exit_price,
                    "quantity": quantity,
                    "type": "EXIT",
                },
            ]

        normalized_executions.sort(
            key=lambda item: (item["timestamp"], 0 if item["type"] == "ENTRY" else 1)
        )

        raw_trace = trade.get("decision_trace_json") or trade.get("decision_trace")
        decision_trace_json = (
            convert_datetimes_to_iso(raw_trace) if isinstance(raw_trace, dict) else None
        )

        normalized_trades.append(
            {
                "client_order_id": f"vector-{run_id}-{idx}",
                "timestamp_entry": entry_dt,
                "timestamp_exit": exit_dt,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": quantity,
                "pnl": pnl,
                "commission": commission,
                "direction": direction,
                "exit_reason": str(trade.get("exit_reason", "UNKNOWN")),
                "decision_trace_json": decision_trace_json,
                "executions": normalized_executions,
            }
        )
        total_commission += commission

    return normalized_trades, total_commission


def _normalize_vector_results(
    raw_results: Dict[str, Any],
    normalized_trades: List[Dict[str, Any]],
    total_commission: float,
    initial_balance: float,
) -> Dict[str, Any]:
    def _safe_float(
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

    stat_trades, excluded_trades = _split_trades_for_stats(normalized_trades)
    total_pnl = float(sum(trade["pnl"] for trade in stat_trades))
    wins = sum(1 for trade in stat_trades if trade["pnl"] > 0)
    losses = len(stat_trades) - wins
    gross_profit = sum(trade["pnl"] for trade in stat_trades if trade["pnl"] > 0)
    gross_loss = abs(sum(trade["pnl"] for trade in stat_trades if trade["pnl"] < 0))
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 1e-9
        else (99999.0 if gross_profit > 1e-9 else 0.0)
    )
    win_rate = (wins / len(stat_trades) * 100.0) if stat_trades else 0.0
    avg_trade_pnl = (total_pnl / len(stat_trades)) if stat_trades else 0.0

    raw_curve = raw_results.get("equity_curve", [])
    if raw_curve and isinstance(raw_curve[0], (list, tuple)) and len(raw_curve[0]) >= 1:
        equity_start_ts = _ensure_utc_datetime(raw_curve[0][0])
    elif stat_trades:
        equity_start_ts = stat_trades[0]["timestamp_entry"]
    elif normalized_trades:
        equity_start_ts = normalized_trades[0]["timestamp_entry"]
    else:
        equity_start_ts = datetime.now(timezone.utc)

    normalized_equity_curve = [
        (int(equity_start_ts.timestamp() * 1000), float(initial_balance))
    ]
    running_balance = float(initial_balance)
    for trade in stat_trades:
        running_balance += float(trade.get("pnl", 0.0) or 0.0)
        normalized_equity_curve.append(
            (
                int(trade["timestamp_exit"].timestamp() * 1000),
                float(running_balance),
            )
        )

    equity_values = [point[1] for point in normalized_equity_curve]
    peak_equity = equity_values[0] if equity_values else float(initial_balance)
    max_drawdown = 0.0
    for balance in equity_values:
        peak_equity = max(peak_equity, balance)
        if peak_equity > 1e-9:
            max_drawdown = max(
                max_drawdown, (peak_equity - balance) / peak_equity * 100.0
            )

    total_pnl_pct = (
        ((running_balance / initial_balance) - 1.0) * 100.0
        if initial_balance > 1e-9
        else 0.0
    )
    stats_commission = float(
        sum(trade.get("commission", 0.0) or 0.0 for trade in stat_trades)
    )

    return {
        "trades": len(stat_trades),
        "trades_all": len(normalized_trades),
        "excluded_end_of_data_trades": len(excluded_trades),
        "total_pnl": _safe_float(total_pnl),
        "profit_factor": _safe_float(profit_factor, pos_inf=99999.0),
        "max_drawdown": _safe_float(max_drawdown),
        "win_rate": _safe_float(win_rate),
        "total_commission": _safe_float(stats_commission),
        "wins": wins,
        "losses": losses,
        "avg_trade_pnl": _safe_float(avg_trade_pnl),
        "sharpe_ratio": _safe_float(raw_results.get("sharpe_ratio", 0.0)),
        "sortino_ratio": _safe_float(raw_results.get("sortino_ratio", 0.0)),
        "consistency_score": _safe_float(raw_results.get("consistency_score", 0.0)),
        "total_pnl_pct": _safe_float(total_pnl_pct),
        "equity_curve": normalized_equity_curve,
        "analytics_report": raw_results.get("analytics_report"),
    }


# --- 5. Main async logic for backtest ---
async def _single_symbol_backtest_body(
    celery_task,
    task_id: str,
    run_params: dict,
    user_id: int,
    symbol: str,
    session: AsyncSession,
    progress_callback: Callable,
):
    """
    This function contains logic for ONE symbol and accepts an already created session.
    """
    run_id = None
    all_results = {}
    try:
        run_request_schema = schemas.BacktestRunRequest(**run_params)

        logger.info(
            f"[TASKS.PY] Parsed run_request_schema.foundation_weights: {run_request_schema.foundation_weights}"
        )

        if run_request_schema.market_type == "futures":
            run_request_schema.market_type = "futures_usdtm"

        # Do NOT create a new task since it has already been created at the top level
        logger.info(
            f"[TASKS.PY] Calling crud.create_backtest_run with run_data.foundation_weights: {run_request_schema.foundation_weights}"
        )
        db_run = await crud.create_backtest_run(
            db=session,
            user_id=user_id,
            task_id=task_id,
            run_data=run_request_schema,
            initial_balance=config.BACKTEST_INITIAL_BALANCE,
        )
        await session.commit()
        await session.refresh(db_run)
        run_id = db_run.id

        logger.info(
            f"Task {task_id} (Symbol: {symbol}): Created DB records. Assigned run_id: {run_id}."
        )

        celery_task.update_state(
            state="PROGRESS",
            meta={"status": f"Loading historical data for {symbol}..."},
        )
        # 1. Take start_dt and end_dt FROM THE CREATED RECORD IN THE DB (db_run),
        #    where they are already correct datetime objects.
        start_dt = db_run.start_date
        end_dt = db_run.end_date

        trainer = Trainer()

        # Correctly extract parameters, including nested JSON, to determine requirements
        request_params = run_request_schema.params or {}
        params_for_requirements = request_params.copy()

        required_data = trainer.get_data_requirements_for_strategy(
            strategy_name=run_request_schema.strategy_name,
            params=params_for_requirements,
            symbol=symbol,
            market_type=run_request_schema.market_type,
        )

        historical_data = await trainer._load_historical_data(
            symbol,
            start_dt,
            end_dt,
            required_data,
            market_type=run_request_schema.market_type,
        )

        if not historical_data or not any(
            df is not None and not df.empty for df in historical_data.values()
        ):
            raise ValueError(f"Failed to load historical data for {symbol}.")

        celery_task.update_state(
            state="PROGRESS", meta={"status": f"Running backtest for {symbol}..."}
        )

        # For classic strategies, all settings from the modal window reside within 'params' -> 'config'
        config_payload = request_params.get(
            "config", request_params
        )  # If 'config' is not present, take 'params' in full

        # Now all parameters are read from a single place - config_payload
        # Use run_request_schema for top-level parameters (symbol, dates), and config_payload for everything else
        min_foundation_weight_threshold = (
            run_request_schema.min_foundation_weight_threshold
            if run_request_schema.min_foundation_weight_threshold is not None
            else config_payload.get("min_foundation_weight_threshold")
        )
        foundation_weights = (
            run_request_schema.foundation_weights
            if run_request_schema.foundation_weights is not None
            else config_payload.get("foundation_weights")
        )
        use_ml_confirmation_flag = config_payload.get("use_ml_confirmation", False)

        logger.info(
            f"Task {task_id} (Symbol: {symbol}): Loading user's actual risk configuration from DB..."
        )
        user_config = await crud.get_config(session, user_id)
        if not user_config or not user_config.risk_management:
            logger.error(
                f"Task {task_id}: Failed to load user config or risk_management section for user {user_id}. Using fallback defaults."
            )
            # Use hardcoding only as a last resort
            actual_risk_params = {
                "risk_pct_per_trade": 0.01,
                "daily_max_loss_pct": 0.05,
                "max_consecutive_losses": 10,
                "max_stop_distance_pct": 0.05,
            }
            backtest_risk_params = actual_risk_params
        else:
            # Convert Pydantic model to dictionary
            actual_risk_params = user_config.risk_management.model_dump()
            backtest_risk_params = (
                user_config.backtest_risk_management.model_dump()
                if user_config.backtest_risk_management
                else actual_risk_params
            )
            logger.info(
                f"Task {task_id} (Symbol: {symbol}): Successfully loaded risk params: {actual_risk_params}"
            )
            logger.info(
                f"Task {task_id} (Symbol: {symbol}): Successfully loaded backtest risk params: {backtest_risk_params}"
            )

        engine = schemas.normalize_backtest_engine(
            request_params.get("backtest_engine"), default="vector"
        )

        # Pre-fetch exchange info for the symbol
        all_exchange_info = trainer._get_exchange_info()
        symbol_exchange_info = all_exchange_info.get(symbol, {})

        if engine == "vector":
            logger.info(
                f"Task {task_id} (Symbol: {symbol}): Initializing FastVectorBacktester..."
            )
            start_date_str = start_dt.isoformat() if start_dt else None
            end_date_str = end_dt.isoformat() if end_dt else None

            backtester = FastVectorBacktester(
                historical_data=historical_data,
                strategy_json=request_params,
                params=request_params,
                use_oracle=request_params.get("use_oracle", False),
                start_date=start_date_str,
                end_date=end_date_str,
                initial_balance=config.BACKTEST_INITIAL_BALANCE,
                risk_params=actual_risk_params,
                backtest_risk_params=backtest_risk_params,
                execution_config=trainer.backtest_execution_config,
                strategy_defaults=trainer.strategy_defaults,
                symbol=symbol,
                strategy_name=run_request_schema.strategy_name,
                market_type=run_request_schema.market_type,
                actual_trading_start_dt=start_dt,
                exchange_info=symbol_exchange_info,
            )
            raw_vector_results = backtester.run()
            normalized_vector_trades, total_vector_commission = (
                _normalize_vector_trade_records(
                    raw_vector_results.get("trades", []),
                    run_id=run_id,
                    initial_balance=config.BACKTEST_INITIAL_BALANCE,
                    commission_pct=getattr(backtester, "commission_pct", 0.0),
                )
            )
            results = _normalize_vector_results(
                raw_results=raw_vector_results,
                normalized_trades=normalized_vector_trades,
                total_commission=total_vector_commission,
                initial_balance=config.BACKTEST_INITIAL_BALANCE,
            )
            visible_vector_trades, _ = _split_trades_for_stats(normalized_vector_trades)

            for normalized_trade in visible_vector_trades:
                db_trade = models.BacktestTrade(
                    backtest_run_id=run_id,
                    client_order_id=normalized_trade["client_order_id"],
                    direction=normalized_trade["direction"],
                    timestamp_entry=normalized_trade["timestamp_entry"],
                    timestamp_exit=normalized_trade["timestamp_exit"],
                    entry_price=normalized_trade["entry_price"],
                    exit_price=normalized_trade["exit_price"],
                    quantity=normalized_trade["quantity"],
                    pnl=normalized_trade["pnl"],
                    commission=normalized_trade["commission"],
                    exit_reason=normalized_trade["exit_reason"],
                    decision_trace_json=normalized_trade["decision_trace_json"],
                    l2_entry_slippage_usd=0.0,
                    l2_exit_slippage_usd=0.0,
                )
                session.add(db_trade)
                await session.flush()

                for execution in normalized_trade["executions"]:
                    session.add(
                        models.BacktestTradeExecution(
                            trade_id=db_trade.id,
                            timestamp=execution["timestamp"],
                            price=execution["price"],
                            quantity=execution["quantity"],
                            type=execution["type"],
                        )
                    )

            await session.commit()

        else:
            logger.info(
                f"Task {task_id} (Symbol: {symbol}): Initializing DepthSightBacktester..."
            )
            backtester = DepthSightBacktester(
                strategy_name=run_request_schema.strategy_name,
                symbol=symbol,
                params=request_params,
                market_type=run_request_schema.market_type,
                min_foundation_weight_threshold=min_foundation_weight_threshold,
                foundation_weights=foundation_weights,
                enable_ml_confirmation_backtest=use_ml_confirmation_flag,
                historical_data=historical_data,
                initial_balance=config.BACKTEST_INITIAL_BALANCE,
                min_trades_required=0,
                risk_params=actual_risk_params,
                backtest_risk_params=backtest_risk_params,
                execution_config=trainer.backtest_execution_config,
                strategy_defaults=trainer.strategy_defaults,
                actual_trading_start_dt=start_dt,
                run_id=run_id,
                db_session=session,
                progress_callback=progress_callback,
                ml_training_config={},
                ml_sim_log_path=None,
                exchange_info=symbol_exchange_info,
            )
            results = await backtester.run_async()

        if not results:
            raise ValueError(f"Backtester returned no results for {symbol}.")

        celery_task.update_state(
            state="PROGRESS", meta={"status": f"Finalizing results for {symbol}..."}
        )

        # FORCE UPDATE OBJECT FROM THE DB AFTER A LONG AWAIT
        # This prevents the MissingGreenlet error during lazy loading.
        await session.refresh(db_run)

        if results and isinstance(results, dict):
            kpis = results.get("kpis", results)
            if kpis:
                trades_count = kpis.get("trades", 0)

                # Grant achievements based on KPIs
                if kpis.get("sharpe_ratio", 0) > 2.0:
                    await grant_achievement(session, user_id, "alpha_hunter")

                if kpis.get("sharpe_ratio", 0) < -2.0:
                    await grant_achievement(session, user_id, "underminer")

                if trades_count >= 20 and kpis.get("win_rate", 0) > 0.8:
                    await grant_achievement(session, user_id, "sniper")

                max_drawdown_pct = kpis.get(
                    "max_drawdown_pct", kpis.get("max_drawdown", 100)
                )
                if trades_count >= 50 and max_drawdown_pct < 0.05:
                    await grant_achievement(session, user_id, "hard_nut")

                if kpis.get("profit_factor", 0) > 3.0:
                    await grant_achievement(session, user_id, "money_printer")

                if trades_count >= 10 and kpis.get("win_rate", 0) == 1.0:
                    await grant_achievement(session, user_id, "flawless_victory")

                if kpis.get("max_consecutive_wins", 0) >= 10:
                    await grant_achievement(session, user_id, "winning_streak")

            # Grant marathon_runner achievement
            if (end_dt - start_dt).days > 365:
                await grant_achievement(session, user_id, "marathon_runner")

            # Phoenix achievement logic
            equity_curve = results.get("equity_curve", [])
            if len(equity_curve) > 1:
                max_equity = equity_curve[0][1]
                in_drawdown = False

                for _, equity in equity_curve:
                    if equity > max_equity:
                        if in_drawdown:
                            # We have recovered from a drawdown and made a new high
                            await grant_achievement(session, user_id, "phoenix")
                            break  # Grant only once per backtest
                        max_equity = equity
                        in_drawdown = False

                    drawdown_pct = (max_equity - equity) / max_equity
                    if drawdown_pct > 0.10 and not in_drawdown:
                        in_drawdown = True

        if hasattr(backtester, "strategy_instance") and backtester.strategy_instance:
            strategy = backtester.strategy_instance
            if hasattr(strategy, "foundation_weights"):
                final_weights = strategy.foundation_weights

                if db_run and final_weights:
                    logger.info(
                        f"Updating parameters_json on run {run_id} with final foundation_weights."
                    )
                    current_params = db_run.parameters_json or {}
                    current_params["foundation_weights"] = final_weights
                    db_run.parameters_json = current_params
                    flag_modified(db_run, "parameters_json")
                    logger.info(
                        f"New parameters_json for run {run_id}: {db_run.parameters_json}"
                    )

        kpi_results_to_save = results if isinstance(results, dict) else {}
        await crud.update_backtest_run_results(
            db=session,
            run_id=run_id,
            kpi_results=kpi_results_to_save,
            equity_curve=kpi_results_to_save.get("equity_curve"),
            analytics_report=kpi_results_to_save.get("analytics_report"),
        )
        kpi_results_to_save["run_id"] = run_id
        all_results[symbol] = kpi_results_to_save

        # Complete the transaction here so that trades are definitely in the DB before analysis
        await session.commit()

        # --- NEW: Send Push Notification for completed backtest ---
        user = await crud.admin_get_user_details(
            session, user_id
        )  # Re-using admin_get_user_details for simplicity, it just fetches the user
        if user and user.push_subscription:
            try:
                send_push_notification(
                    subscription_info=user.push_subscription,
                    title="Backtest completed!",
                    body=f"Your backtest for {symbol} ({run_request_schema.strategy_name}) has completed successfully.",
                    tag=f"backtest-completed-{run_id}",
                )
            except Exception as push_exc:
                logger.error(
                    f"Failed to send push notification for backtest {run_id} to user {user_id}: {push_exc}",
                    exc_info=True,
                )
        # --- END NEW ---

        # --- GENOME PROJECT: Analyze backtest for gene discovery ---
        try:
            logger.info(
                f"Task {task_id}: Analyzing backtest run {run_id} for gene discovery..."
            )

            # Re-request the db_run object with explicit loading of trades
            # to avoid lazy loading error.
            # Use get_backtest_run_with_trades, which already contains selectinload.
            reloaded_db_run = await crud.get_backtest_run_with_trades(
                session, user_id=user_id, run_id=run_id
            )
            if not reloaded_db_run:
                raise ValueError(
                    f"Could not reload backtest run {run_id} for gene analysis."
                )

            # Now use the reloaded object reloaded_db_run
            if reloaded_db_run.status == "COMPLETED" and reloaded_db_run.trades:
                genome_analyzer = GenomeAnalyzer(session)
                source_type = "manual"
                newly_discovered_genes = await genome_analyzer.analyze_backtest(
                    reloaded_db_run, source_type=source_type
                )

                if newly_discovered_genes:
                    logger.info(
                        f"Task {task_id}: Discovered {len(newly_discovered_genes)} new genes for user {user_id}!"
                    )

                    # WebSocket notifications (code remains unchanged)
                    try:
                        redis_pub = aredis.Redis(
                            host=config.REDIS_HOST,
                            port=config.REDIS_PORT,
                            db=0,
                            username=config.REDIS_USERNAME,
                            password=config.REDIS_PASSWORD,
                            decode_responses=True,
                        )
                        for user_gene in newly_discovered_genes:
                            await session.refresh(user_gene)
                            gene = await session.get(models.Gene, user_gene.gene_id)
                            if gene:
                                notification_data = {
                                    "type": "gene_discovered",
                                    "gene": {
                                        "id": gene.id,
                                        "name": gene.name,
                                        "components": gene.components,
                                        "rarity": gene.rarity,
                                        "source_type": user_gene.source_type,
                                    },
                                }
                                channel = f"user:{user_id}:notifications"
                                await redis_pub.publish(
                                    channel, json.dumps(notification_data)
                                )
                                logger.info(
                                    f"Sent gene discovery notification to channel {channel}"
                                )
                        await redis_pub.close()
                    except Exception as ws_error:
                        logger.error(
                            f"Failed to send WebSocket notification: {ws_error}"
                        )
                else:
                    logger.info(
                        f"Task {task_id}: No new genes discovered (KPIs too low or combinations already known)."
                    )
            else:
                logger.debug(
                    f"Task {task_id}: Skipping gene analysis - backtest not completed or has no trades."
                )
        except Exception as gene_error:
            logger.error(
                f"Task {task_id}: Failed to analyze genes for run {run_id}: {gene_error}",
                exc_info=True,
            )

        # Commit for gene analyzer (if it changed anything)
        await session.commit()
        return all_results

    except Exception as e:
        logger.error(
            f"Backtest task {task_id} (run_id: {run_id}, symbol: {symbol}) failed: {e}",
            exc_info=True,
        )
        await session.rollback()
        if run_id:
            # Use get instead of execute, as it is simpler for PK
            db_run_on_error = await session.get(models.BacktestRun, run_id)
            if db_run_on_error:
                # update_backtest_run_status commits internally, which is not ideal, but we'll leave it for now
                await crud.update_backtest_run_status(
                    session, run_id, status="FAILED", error_message=str(e)
                )
        await session.commit()  # Commit FAILED status
        raise


async def _async_backtest_logic(
    celery_task, task_id: str, backtest_params: dict, user_id: int
):
    """
    Main async logic for backtest execution.
    """
    from bot_module.redis_handler import user_id_context

    token = user_id_context.set(user_id)
    redis_pub_client = None
    try:
        redis_pub_client = aredis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=0,
            username=config.REDIS_USERNAME,
            password=config.REDIS_PASSWORD,
            decode_responses=True,
        )
        await redis_pub_client.ping()
        logger.info(
            f"Task {task_id}: Successfully connected to Redis for real-time progress publishing."
        )
    except Exception as e:
        logger.error(
            f"Task {task_id}: Could not connect to Redis for Pub/Sub: {e}. Real-time updates will be disabled."
        )
        redis_pub_client = None

    original_symbol_str = backtest_params.get("symbol", "")
    symbols_to_run = [
        s.strip().upper() for s in original_symbol_str.split(",") if s.strip()
    ]

    if not symbols_to_run:
        raise ValueError("No valid symbols provided for the backtest.")

    logger.info(
        f"Task {task_id}: Received request for symbols: {symbols_to_run} with params: {backtest_params}"
    )

    async with get_isolated_worker_session() as session:
        try:
            await crud.create_task(
                session, user_id, task_id, "backtest", backtest_params
            )
            await session.commit()

            total_symbols = len(symbols_to_run)
            last_update_time = 0
            update_interval_seconds = 2.0
            event_buffer = []
            latest_kpis = {}
            latest_equity_point = None

            def create_progress_callback(symbol_index: int):
                nonlocal \
                    last_update_time, \
                    event_buffer, \
                    latest_kpis, \
                    latest_equity_point

                async def progress_callback(meta: Optional[Dict] = None):
                    nonlocal \
                        last_update_time, \
                        event_buffer, \
                        latest_kpis, \
                        latest_equity_point
                    if not meta or not isinstance(meta, dict):
                        return

                    if meta.get("events"):
                        event_buffer.extend(meta["events"])
                    if meta.get("kpis"):
                        latest_kpis = meta["kpis"]
                    if meta.get("equity_point"):
                        latest_equity_point = meta["equity_point"]

                    current_time = time()
                    if (current_time - last_update_time) < update_interval_seconds:
                        return

                    last_update_time = current_time
                    per_symbol_progress = latest_kpis.get("progress", 0)
                    overall_progress = ((symbol_index / total_symbols) * 100) + (
                        per_symbol_progress / total_symbols
                    )

                    if latest_kpis:
                        latest_kpis["progress"] = round(overall_progress, 2)

                    payload_for_redis = {
                        "kpis": latest_kpis,
                        "equity_point": latest_equity_point,
                        "events": event_buffer,
                    }
                    payload_for_celery_meta = {
                        "kpis": latest_kpis,
                        "events": event_buffer,
                    }
                    celery_task.update_state(
                        state="PROGRESS",
                        meta={"progress_info": payload_for_celery_meta},
                    )

                    if redis_pub_client:
                        try:
                            channel = f"backtest-progress:{task_id}"
                            json_safe_payload = convert_datetimes_to_iso(
                                payload_for_redis
                            )
                            message = json.dumps(json_safe_payload)
                            await redis_pub_client.publish(channel, message)
                        except Exception as e:
                            logger.warning(
                                f"Task {task_id}: Failed to publish throttled progress to Redis: {e}"
                            )

                    event_buffer.clear()
                    latest_equity_point = None

                return progress_callback

            all_symbols_results = {}
            for i, symbol in enumerate(symbols_to_run):
                logger.info(
                    f"--- Task {task_id}: Starting backtest for symbol {i + 1}/{total_symbols}: {symbol} ---"
                )
                current_run_params = backtest_params.copy()
                current_run_params["symbol"] = symbol

                current_progress_callback = create_progress_callback(symbol_index=i)

                symbol_result = await _single_symbol_backtest_body(
                    celery_task,
                    task_id,
                    current_run_params,
                    user_id,
                    symbol,
                    session,
                    current_progress_callback,
                )
                all_symbols_results.update(symbol_result)

                if symbol_result and symbol in symbol_result:
                    run_id = symbol_result[symbol].get("run_id")
                    if run_id:
                        logger.info(
                            f"Task {task_id}: Enqueuing analytics processing for run_id: {run_id}"
                        )
                        process_backtest_analytics_task.delay(
                            run_id=run_id, user_id=user_id
                        )

            # Check for first backtest achievement
            result = await session.execute(
                select(models.BacktestRun)
                .where(models.BacktestRun.user_id == user_id)
                .limit(2)  # Check if there are more than 1 backtest
            )
            backtest_runs = result.scalars().all()
            if len(backtest_runs) <= len(symbols_to_run):
                await grant_achievement(session, user_id, "first_backtest")

            await crud.update_task_status(
                session, task_id, "COMPLETED", all_symbols_results, None
            )
            await session.commit()
            logger.info(
                f"--- All backtests for task {task_id} completed successfully. ---"
            )
            return all_symbols_results

        except Exception as e:
            logger.error(
                f"An error occurred in the main backtest logic for task {task_id}: {e}",
                exc_info=True,
            )
            await session.rollback()
            await crud.update_task_status(session, task_id, "FAILED", None, str(e))
            await session.commit()
            raise
        finally:
            user_id_context.reset(token)
            if redis_pub_client:
                await redis_pub_client.close()
                logger.info(f"Task {task_id}: Redis Pub/Sub client closed.")


async def _async_process_backtest_analytics_logic(run_id: str, user_id: int):
    """Async logic for processing analytics based on backtest results."""
    from bot_module.redis_handler import user_id_context

    token = user_id_context.set(user_id)
    try:
        async with get_isolated_worker_session() as session:
            try:
                logger.info(
                    f"Starting analytics processing for backtest run_id: {run_id}"
                )
                backtest_run = await crud.get_backtest_run(session, run_id, user_id)
                if not backtest_run:
                    logger.error(
                        f"BacktestRun with id {run_id} not found for user {user_id}."
                    )
                    return

                strategy_config = None
                strategy_config_id = None
                config_data_for_parser = {}

                if backtest_run.strategy_name:
                    result = await session.execute(
                        select(models.StrategyConfig).filter_by(
                            name=backtest_run.strategy_name, user_id=user_id
                        )
                    )
                    strategy_config = result.scalars().first()

                if strategy_config:
                    strategy_config_id = strategy_config.id
                    config_data_for_parser = strategy_config.config_data or {}
                else:
                    logger.warning(
                        f"Could not find a matching StrategyConfig named '{backtest_run.strategy_name}' for user {user_id}. Analytics for filters/management blocks may be incomplete."
                    )
                    config_data_for_parser = backtest_run.parameters_json or {}

                config_parser = StrategyConfigParser(config_data_for_parser)
                used_filters = config_parser.get_used_filters()
                used_management_blocks = config_parser.get_used_management_blocks()

                for trade in backtest_run.trades:
                    if not trade.direction:
                        logger.warning(
                            f"Skipping analytics for trade {trade.id} in run {run_id} because direction is missing."
                        )
                        continue
                    if (
                        _normalize_exit_reason(trade.exit_reason)
                        in STATS_EXCLUDED_EXIT_REASONS
                    ):
                        continue

                    trace_parser = DecisionTraceParser(trade.decision_trace_json or {})
                    used_foundations = trace_parser.get_used_foundations()
                    pnl = trade.pnl or 0
                    win_rate_contribution = 1 if pnl > 0 else -1 if pnl < 0 else 0
                    profit_factor_gross_profit = pnl if pnl > 0 else 0
                    profit_factor_gross_loss = abs(pnl) if pnl < 0 else 0

                    analytics_data = schemas.TradeAnalyticsCreate(
                        user_id=user_id,
                        source_type="backtest",
                        source_trade_id=str(trade.id),
                        strategy_config_id=strategy_config_id,
                        symbol=backtest_run.symbol,
                        direction=trade.direction,
                        timestamp_close=trade.timestamp_exit,
                        pnl_usd=pnl,
                        win_rate_contribution=win_rate_contribution,
                        profit_factor_gross_profit=profit_factor_gross_profit,
                        profit_factor_gross_loss=profit_factor_gross_loss,
                        used_foundations=used_foundations,
                        used_filters=used_filters,
                        used_management_blocks=used_management_blocks,
                    )
                    await crud.create_trade_analytics(session, analytics_data)

                await session.commit()
                logger.info(
                    f"Successfully processed and stored analytics for backtest run_id: {run_id}"
                )

            except Exception as e:
                logger.error(
                    f"Error processing analytics for backtest run_id {run_id}: {e}",
                    exc_info=True,
                )
                await session.rollback()
    finally:
        user_id_context.reset(token)


@celery_app.task(name="tasks.process_backtest_analytics")
def process_backtest_analytics_task(run_id: str, user_id: int):
    """Celery task to trigger analytics processing for backtest results."""
    logger.info(f"Received analytics task for backtest run_id: {run_id}")
    run_async_from_sync(
        _async_process_backtest_analytics_logic(run_id=run_id, user_id=user_id)
    )


async def _async_process_live_trade_analytics_logic(trade_id: int, user_id: int):
    """Async logic for processing analytics based on live trade results."""
    from bot_module.redis_handler import user_id_context

    token = user_id_context.set(user_id)
    try:
        async with get_isolated_worker_session() as session:
            try:
                logger.info(
                    f"Starting analytics processing for live trade_id: {trade_id}"
                )
                trade = await session.get(models.Trade, trade_id)
                if not trade:
                    logger.error(f"Trade with id {trade_id} not found.")
                    return

                # Initialize with empty lists - analytics will be created even without strategy config
                used_foundations = []  # Now includes ALL entry conditions (foundations + indicators)
                used_filters = []
                used_management_blocks = []

                # Priority 1: Use signal_details_json with decision_trace (most accurate - shows what actually triggered)
                if trade.signal_details_json and trade.signal_details_json.get(
                    "decision_trace"
                ):
                    logger.info(
                        f"Trade {trade_id}: Using decision_trace from signal_details_json for foundations"
                    )
                    trace_parser = DecisionTraceParser(
                        trade.signal_details_json.get("decision_trace", {})
                    )
                    used_foundations = (
                        trace_parser.get_used_foundations()
                    )  # Now includes indicators too
                    used_filters = trace_parser.get_used_filters()
                    used_management_blocks = trace_parser.get_used_management_blocks()

                # Priority 2: Fall back to strategy_config if no decision_trace (less accurate - shows what's configured)
                elif trade.strategy_config_id:
                    strategy_config = await crud.get_strategy_config(
                        session, user_id, trade.strategy_config_id
                    )
                    if strategy_config:
                        logger.info(
                            f"Trade {trade_id}: Using StrategyConfigParser (no decision_trace available)"
                        )
                        config_parser = StrategyConfigParser(
                            strategy_config.config_data or {}
                        )
                        used_foundations = (
                            config_parser.get_all_foundations()
                        )  # Now includes indicators too
                        used_filters = config_parser.get_used_filters()
                        used_management_blocks = (
                            config_parser.get_used_management_blocks()
                        )
                    else:
                        logger.warning(
                            f"StrategyConfig {trade.strategy_config_id} not found for trade {trade_id}."
                        )
                else:
                    logger.info(
                        f"Trade {trade_id} has no decision_trace or strategy_config_id. Creating analytics with empty foundation data."
                    )

                pnl = trade.pnl or 0
                win_rate_contribution = 1 if pnl > 0 else -1 if pnl < 0 else 0
                profit_factor_gross_profit = pnl if pnl > 0 else 0
                profit_factor_gross_loss = abs(pnl) if pnl < 0 else 0

                # Determine source_type based on trade_mode (LIVE or PAPER)
                source_type = "paper" if trade.trade_mode == "PAPER" else "live"

                analytics_data = schemas.TradeAnalyticsCreate(
                    user_id=user_id,
                    source_type=source_type,
                    source_trade_id=str(trade.id),
                    strategy_config_id=trade.strategy_config_id,
                    symbol=trade.symbol,
                    direction=trade.direction,
                    timestamp_close=trade.timestamp_close,
                    pnl_usd=pnl,
                    win_rate_contribution=win_rate_contribution,
                    profit_factor_gross_profit=profit_factor_gross_profit,
                    profit_factor_gross_loss=profit_factor_gross_loss,
                    used_foundations=used_foundations,
                    used_filters=used_filters,
                    used_management_blocks=used_management_blocks,
                )
                await crud.create_trade_analytics(session, analytics_data)

                await session.commit()
                logger.info(
                    f"Successfully processed and stored analytics for live trade_id: {trade_id}"
                )

            except Exception as e:
                logger.error(
                    f"Error processing analytics for live trade_id {trade_id}: {e}",
                    exc_info=True,
                )
                await session.rollback()
    finally:
        user_id_context.reset(token)


@celery_app.task(name="tasks.process_live_trade_analytics")
def process_live_trade_analytics_task(trade_id: int, user_id: int):
    """Celery task to trigger analytics processing for live trade results."""
    logger.info(f"Received analytics task for live trade_id: {trade_id}")
    run_async_from_sync(
        _async_process_live_trade_analytics_logic(trade_id=trade_id, user_id=user_id)
    )


async def _async_portfolio_backtest_logic(
    celery_task, task_id: str, request_dict: dict, user_id: int
):
    """
    Async coroutine for performing portfolio backtest.
    """
    from bot_module.redis_handler import user_id_context

    token = user_id_context.set(user_id)
    try:
        session_factory = get_session_for_worker()
        async with session_factory() as session:
            try:
                await crud.create_task(
                    session, user_id, task_id, "portfolio_backtest", request_dict
                )
                await session.commit()
                logger.info(
                    f"Portfolio backtest task {task_id} for user {user_id} created in DB."
                )

                celery_task.update_state(
                    state="PROGRESS", meta={"status": "Parsing request..."}
                )
                try:
                    request_data = schemas.PortfolioBacktestRunRequest(**request_dict)
                except Exception as e_parse:
                    logger.error(
                        f"Task {task_id}: Failed to parse PortfolioBacktestRunRequest: {e_parse}",
                        exc_info=True,
                    )
                    raise ValueError(f"Invalid request data format: {e_parse}")

                start_dt_obj = datetime.fromisoformat(
                    request_data.start_date.replace("Z", "+00:00")
                    if "Z" in request_data.start_date
                    else request_data.start_date
                )
                end_dt_obj = datetime.fromisoformat(
                    request_data.end_date.replace("Z", "+00:00")
                    if "Z" in request_data.end_date
                    else request_data.end_date
                )
                contracts_for_backtester = [
                    c.model_dump(exclude_none=True) for c in request_data.contracts
                ]

                celery_task.update_state(
                    state="PROGRESS",
                    meta={"status": "Initializing PortfolioBacktester..."},
                )
                portfolio_backtester = PortfolioBacktester(
                    initial_balance=request_data.initial_balance,
                    start_date=start_dt_obj,
                    end_date=end_dt_obj,
                    contracts=contracts_for_backtester,
                    global_risk_limits=request_data.global_risk_limits,
                    l2_storage_path=request_data.l2_storage_path,
                )

                celery_task.update_state(
                    state="PROGRESS", meta={"status": "Running portfolio backtest..."}
                )
                results_dict = await portfolio_backtester.run_backtest()

                if not results_dict:
                    raise ValueError("PortfolioBacktester returned no results.")

                celery_task.update_state(
                    state="PROGRESS",
                    meta={
                        "status": "Validating and saving portfolio backtest results..."
                    },
                )
                try:
                    if "equity_curve" in results_dict and results_dict["equity_curve"]:
                        results_dict["equity_curve"] = [
                            (
                                ts.isoformat() if isinstance(ts, datetime) else str(ts),
                                val,
                            )
                            for ts, val in results_dict["equity_curve"]
                        ]
                    validated_results = schemas.PortfolioBacktestResult(**results_dict)
                    results_to_store = validated_results.model_dump()
                except Exception as e_val:
                    logger.error(
                        f"Task {task_id}: Failed to validate PortfolioBacktestResult: {e_val}",
                        exc_info=True,
                    )
                    raise ValueError(f"Result validation error: {e_val}")

                await crud.update_task_status(
                    session, task_id, "COMPLETED", results_to_store, None
                )
                await session.commit()

                logger.info(
                    f"Portfolio backtest task {task_id} completed successfully."
                )
                return results_to_store

            except Exception as e:
                logger.error(
                    f"Portfolio backtest task {task_id} failed: {e}", exc_info=True
                )
                if session.is_active:
                    await session.rollback()
                    await crud.update_task_status(
                        session, task_id, "FAILED", None, str(e)
                    )
                    await session.commit()
                raise
    finally:
        user_id_context.reset(token)


# --- 6. The Celery tasks themselves, which are entry points ---


@celery_app.task(bind=True, name="run_backtest_task")
def run_backtest_task(self, backtest_params_dict: dict, user_id: int):
    task_id = self.request.id
    logger.info(f"Received backtest task {task_id} with params: {backtest_params_dict}")
    self.update_state(state="PENDING", meta={"status": "Task received and queued."})

    redis_key = f"concurrent_tasks:user:{user_id}"
    try:
        results = run_async_from_sync(
            _async_backtest_logic(self, task_id, backtest_params_dict, user_id)
        )
        logger.info(
            f"Backtest task {task_id} (DepthSightBacktester) completed successfully."
        )
        return results
    except Exception:
        logger.critical(
            f"Task {task_id} is being marked as FAILED due to an unhandled exception."
        )
        raise
    finally:
        if redis_client_for_tasks:
            try:
                # Check if key exists, only then decrement
                if redis_client_for_tasks.exists(redis_key):
                    count = redis_client_for_tasks.decr(redis_key)
                    logger.info(
                        f"Task {task_id} finished. Decremented concurrent task counter for user {user_id}. New count: {count}"
                    )
                else:
                    logger.warning(
                        f"Task {task_id}: Could not find redis key '{redis_key}' to decrement. It may have expired or was never set."
                    )
            except Exception as redis_err:
                logger.error(
                    f"Task {task_id}: FAILED to access Redis for task counter decrement. Key: {redis_key}. Error: {redis_err}"
                )


async def check_and_grant_first_optimization_achievement(user_id: int):
    async with get_isolated_worker_session() as session:
        result = await session.execute(
            select(models.Task)
            .where(
                models.Task.user_id == user_id, models.Task.task_type == "optimization"
            )
            .limit(2)
        )
        tasks = result.scalars().all()
        if len(tasks) <= 1:
            await grant_achievement(session, user_id, "first_optimization")


@celery_app.task(bind=True, name="run_optimization_task")
def run_optimization_task(self, optimization_params: dict, user_id: int):
    """
    Background task for launching optimization. Currently uses synchronous logic.
    """
    task_id = self.request.id
    logger.info(
        f"Received optimization task {task_id} with params: {optimization_params}"
    )
    self.update_state(state="PENDING", meta={"status": "Optimization task received."})

    run_async_from_sync(check_and_grant_first_optimization_achievement(user_id))

    def optuna_progress_callback(study, trial):
        best_trial_data = None
        if study.best_trial:
            best_trial_data = schemas.OptimizationTrial(
                trial_number=study.best_trial.number,
                params=study.best_trial.params,
                value=study.best_trial.value,
                datetime_start=study.best_trial.datetime_start,
                datetime_complete=study.best_trial.datetime_complete,
            )
        current_trial_data = schemas.OptimizationTrial(
            trial_number=trial.number,
            params=trial.params,
            value=trial.value,
            datetime_start=trial.datetime_start,
            datetime_complete=trial.datetime_complete,
        )
        progress_payload = schemas.OptimizationProgressInfo(
            current_trial_number=trial.number,
            total_trials_planned=study.n_trials
            if hasattr(study, "n_trials") and study.n_trials
            else None,
            best_trial_so_far=best_trial_data,
            recent_trials=[current_trial_data],
            status_message=f"Completed trial {trial.number + 1}.",
        )
        self.update_state(
            state="PROGRESS",
            meta={"progress_info": progress_payload.model_dump(exclude_none=True)},
        )
        logger.info(
            f"Optimization Task {task_id}: Updated progress for trial {trial.number}"
        )

    redis_key = f"concurrent_tasks:user:{user_id}"
    try:
        trainer = Trainer()
        self.update_state(
            state="PROGRESS",
            meta={
                "progress_info": schemas.OptimizationProgressInfo(
                    current_trial_number=0, status_message="Starting optimization..."
                ).model_dump()
            },
        )
        result = run_async_from_sync(
            trainer.run_single_optimization(
                strategy_name=optimization_params["strategy_name"],
                symbol=optimization_params["symbol"],
                start_dt=datetime.fromisoformat(
                    optimization_params["start_date"].rstrip("Z")
                ),
                end_dt=datetime.fromisoformat(
                    optimization_params["end_date"].rstrip("Z")
                ),
                optuna_config=optimization_params.get("optuna_config") or {},
                progress_callback=optuna_progress_callback,
            )
        )
        if not result:
            raise ValueError("Optimization returned no results.")
        logger.info(f"Optimization task {task_id} completed successfully.")
        return result
    except Exception as e:
        logger.error(f"Optimization task {task_id} failed: {e}", exc_info=True)
        raise
    finally:
        if redis_client_for_tasks:
            try:
                # Check if key exists, only then decrement
                if redis_client_for_tasks.exists(redis_key):
                    count = redis_client_for_tasks.decr(redis_key)
                    logger.info(
                        f"Task {task_id} finished. Decremented concurrent task counter for user {user_id}. New count: {count}"
                    )
                else:
                    logger.warning(
                        f"Task {task_id}: Could not find redis key '{redis_key}' to decrement. It may have expired or was never set."
                    )
            except Exception as redis_err:
                logger.error(
                    f"Task {task_id}: FAILED to access Redis for task counter decrement. Key: {redis_key}. Error: {redis_err}"
                )


async def check_and_grant_first_portfolio_backtest_achievement(user_id: int):
    async with get_isolated_worker_session() as session:
        result = await session.execute(
            select(models.Task)
            .where(
                models.Task.user_id == user_id,
                models.Task.task_type == "portfolio_backtest",
            )
            .limit(2)
        )
        tasks = result.scalars().all()
        if len(tasks) <= 1:
            await grant_achievement(session, user_id, "diversifier")


@celery_app.task(bind=True, name="run_portfolio_backtest_task")
def run_portfolio_backtest_task(self, request_data_dict: Dict, user_id: int):
    """
    Celery task for running a portfolio backtest.
    """
    task_id = self.request.id
    logger.info(
        f"Received portfolio backtest task {task_id} for user {user_id} with data: {request_data_dict}"
    )
    self.update_state(
        state="PENDING", meta={"status": "Portfolio backtest task received."}
    )

    run_async_from_sync(check_and_grant_first_portfolio_backtest_achievement(user_id))

    redis_key = f"concurrent_tasks:user:{user_id}"
    try:
        results = run_async_from_sync(
            _async_portfolio_backtest_logic(self, task_id, request_data_dict, user_id)
        )
        logger.info(
            f"Portfolio backtest task {task_id} completed successfully with results."
        )
        if results and results.get("run_id"):
            process_backtest_analytics_task.delay(
                run_id=results.get("run_id"), user_id=user_id
            )
        return results
    except Exception as e:
        logger.critical(
            f"Portfolio backtest task {task_id} FAILED due to unhandled exception: {e}",
            exc_info=True,
        )
        raise
    finally:
        if redis_client_for_tasks:
            try:
                # Check if key exists, only then decrement
                if redis_client_for_tasks.exists(redis_key):
                    count = redis_client_for_tasks.decr(redis_key)
                    logger.info(
                        f"Task {task_id} finished. Decremented concurrent task counter for user {user_id}. New count: {count}"
                    )
                else:
                    logger.warning(
                        f"Task {task_id}: Could not find redis key '{redis_key}' to decrement. It may have expired or was never set."
                    )
            except Exception as redis_err:
                logger.error(
                    f"Task {task_id}: FAILED to access Redis for task counter decrement. Key: {redis_key}. Error: {redis_err}"
                )


async def _async_evaluate_strategy(
    celery_task,
    strategy_json: dict,
    run_config_subset: dict,
    evaluation_data_info: dict,
    user_id: int,
) -> tuple:
    from bot_module.redis_handler import user_id_context

    token = user_id_context.set(user_id)
    try:
        task_id = celery_task.request.id
        logger.info(
            f"Task {task_id}: Starting evaluation for strategy (hash: {hash(json.dumps(strategy_json))}) with config subset: {run_config_subset}"
        )
        session_factory = get_session_for_worker()
        async with session_factory() as session:
            try:
                symbol = evaluation_data_info["symbol"]
                start_date_iso = evaluation_data_info["start_date_iso"]
                end_date_iso = evaluation_data_info["end_date_iso"]
                l2_storage_path = run_config_subset.get("l2_storage_path")
                celery_task.update_state(
                    state="PROGRESS",
                    meta={
                        "status": f"Loading data for {symbol} from {start_date_iso} to {end_date_iso}"
                    },
                )
                start_dt_eval = datetime.fromisoformat(
                    start_date_iso.replace("Z", "+00:00")
                )
                end_dt_eval = datetime.fromisoformat(
                    end_date_iso.replace("Z", "+00:00")
                )
                main_tf = run_config_subset.get("main_timeframe", "1m")
                # _async_evaluate_strategy
                kline_key = f"kline_{main_tf}"
                # download_klines is async, so we await it directly. It handles offloading internally.
                df_eval = await download_klines(
                    symbol, start_dt_eval, end_dt_eval, main_tf
                )
                if df_eval is None or df_eval.empty:
                    logger.error(
                        f"Task {task_id}: No evaluation data loaded for {symbol} ({start_date_iso}-{end_date_iso})."
                    )
                    return (-99999.0,)
                historical_data = {kline_key: df_eval}
                logger.info(
                    f"Task {task_id}: Evaluation data loaded for {symbol}. Shape: {df_eval.shape}"
                )
                initial_balance = run_config_subset.get("initial_balance", 10000.0)
                risk_params = run_config_subset.get(
                    "risk_params", {"risk_pct_per_trade": 0.01}
                )
                execution_config = run_config_subset.get(
                    "execution_config", {"commission_pct": 0.001, "slippage_pct": 0.0}
                )
                strategy_defaults_gs = {"GeneticStrategy": {}}
                backtester = DepthSightBacktester(
                    strategy_name="GeneticStrategy",
                    symbol=symbol,
                    params={},
                    strategy_json=strategy_json,
                    historical_data=historical_data,
                    initial_balance=initial_balance,
                    min_trades_required=run_config_subset.get(
                        "min_trades_for_evaluation", 5
                    ),
                    risk_params=risk_params,
                    execution_config=execution_config,
                    strategy_defaults=strategy_defaults_gs,
                    ml_training_config={},
                    ml_sim_log_path=None,
                    l2_storage_path=l2_storage_path,
                    db_session=session,
                    run_id=None,
                )
                celery_task.update_state(
                    state="PROGRESS",
                    meta={"status": f"Running backtest for strategy on {symbol}"},
                )
                results = await backtester.run_async()
                if not results or "kpis" not in results:
                    logger.warning(
                        f"Task {task_id}: Backtest for strategy on {symbol} returned no results or no KPIs."
                    )
                    return (-99999.0,)
                kpis = results["kpis"]
                fitness_metric_key = run_config_subset.get(
                    "fitness_metric", "profit_factor"
                )
                fitness_value = float(kpis.get(fitness_metric_key, -99999.0))
                total_trades = int(kpis.get("total_trades", 0))
                if total_trades < run_config_subset.get("min_trades_for_evaluation", 5):
                    fitness_value = -abs(fitness_value) - 1000
                logger.info(
                    f"Task {task_id}: Evaluation for strategy on {symbol} complete. Fitness ({fitness_metric_key}): {fitness_value}, Trades: {total_trades}"
                )
                return (fitness_value,)
            except Exception as e:
                logger.error(
                    f"Task {task_id}: Error during strategy evaluation for {strategy_json}: {e}",
                    exc_info=True,
                )
                return (-999999.0,)
    finally:
        user_id_context.reset(token)


@celery_app.task(bind=True, name="evaluate_strategy_task")
def evaluate_strategy_task(
    self,
    strategy_json: dict,
    run_config_subset: dict,
    evaluation_data_info: dict,
    user_id: int,
) -> tuple:
    """
    Celery worker task to evaluate a single strategy using DepthSightBacktester.
    """
    return run_async_from_sync(
        _async_evaluate_strategy(
            self, strategy_json, run_config_subset, evaluation_data_info, user_id
        )
    )


async def _async_run_genetic_search(celery_task, run_id: str, user_id: int):
    from bot_module.redis_handler import user_id_context

    token = user_id_context.set(user_id)
    try:
        task_id = celery_task.request.id
        logger.info(
            f"Task {task_id}: Starting genetic search for GeneticRun ID: {run_id}, User ID: {user_id}"
        )
        session_factory = get_session_for_worker()

        # === PHASE 1: Initialize run and load config (separate session) ===
        run_config = None
        target_symbol = None
        data_start_date_iso = None
        data_end_date_iso = None

        async with session_factory() as session:
            try:
                db_run = await crud.get_genetic_run(
                    session, run_id=run_id, user_id=user_id
                )
                if not db_run:
                    logger.error(
                        f"Task {task_id}: GeneticRun with ID {run_id} not found for user {user_id}."
                    )
                    raise ValueError(f"GeneticRun with ID {run_id} not found.")
                db_run.status = "RUNNING"
                db_run.started_at = datetime.now(timezone.utc)
                db_run.celery_task_id = task_id
                await session.commit()

                # Extract config before closing session
                run_config = dict(db_run.config_json) if db_run.config_json else {}
                target_symbol = run_config.get("target_symbols", ["BTCUSDT"])[0]
                data_start_date_iso = run_config.get(
                    "data_start_date", "2023-01-01T00:00:00Z"
                )
                data_end_date_iso = run_config.get(
                    "data_end_date", "2023-12-31T23:59:59Z"
                )

            except Exception as e:
                logger.error(
                    f"Task {task_id}: Failed to initialize GeneticRun {run_id}: {e}",
                    exc_info=True,
                )
                raise

        # === PHASE 2: Load data (outside of session context) ===
        total_start_dt = datetime.fromisoformat(
            data_start_date_iso.replace("Z", "+00:00")
        )
        total_end_dt = datetime.fromisoformat(data_end_date_iso.replace("Z", "+00:00"))
        screening_duration_days = (total_end_dt - total_start_dt).days * 0.3
        screening_end_dt = total_start_dt + timedelta(
            days=max(1, int(screening_duration_days))
        )

        # Always load 1m data for resampling to higher timeframes
        logger.info(
            f"Task {task_id}: Loading 1m data for {target_symbol} from {total_start_dt} to {screening_end_dt}"
        )
        screening_df_1m = await download_klines(
            target_symbol, "1m", total_start_dt, screening_end_dt
        )

        if screening_df_1m is None or screening_df_1m.empty:
            # Update status to FAILED in new session
            async with session_factory() as session:
                db_run_err = await session.get(models.GeneticRun, run_id)
                if db_run_err:
                    db_run_err.status = "FAILED"
                    db_run_err.error_message = (
                        f"Failed to load screening data for {target_symbol}"
                    )
                    db_run_err.completed_at = datetime.now(timezone.utc)
                    await session.commit()
            raise ValueError(f"Failed to load screening data for {target_symbol}")

        # Resample 1m data to multiple timeframes (5m, 15m, 1h, 4h)
        logger.info(
            f"Task {task_id}: Resampling 1m data to multiple timeframes for MTF support..."
        )
        mtf_data = resample_to_timeframes(
            screening_df_1m, ["1m", "5m", "15m", "1h", "4h"]
        )
        logger.info(
            f"Task {task_id}: Created MTF data with timeframes: {list(mtf_data.keys())}"
        )
        for tf, df in mtf_data.items():
            logger.info(f"  - {tf}: {len(df)} bars")

        # === PHASE 3: Run genetic algorithm (CPU-bound, no DB needed) ===
        # GeneticStrategyFinder expects training_data as Dict[symbol, Dict[timeframe, DataFrame]]
        training_data = {target_symbol: mtf_data}

        # === SEED STRATEGY SUPPORT ===
        seed_population = []
        keep_structure = False
        seed_config = run_config.get("seed_config", {})

        if seed_config and seed_config.get("mode") != "random":
            seed_mode = seed_config.get("mode")
            top_n = seed_config.get("top_n", 10)
            keep_structure = seed_config.get("keep_structure", False)

            if seed_mode == "previous_run":
                # Load strategies from previous run
                prev_run_id = seed_config.get("run_id")
                if prev_run_id:
                    logger.info(
                        f"Task {task_id}: Loading seed strategies from previous run {prev_run_id}"
                    )
                    async with session_factory() as session:
                        try:
                            found_strategies = await crud.get_found_strategies_for_run(
                                session, run_id=prev_run_id, limit=top_n
                            )
                            seed_population = [
                                fs.strategy_json
                                for fs in found_strategies
                                if fs.strategy_json
                            ]
                            logger.info(
                                f"Task {task_id}: Loaded {len(seed_population)} seed strategies from run {prev_run_id}"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Task {task_id}: Failed to load seed strategies from {prev_run_id}: {e}"
                            )

            elif seed_mode == "upload":
                # Use uploaded strategies directly
                uploaded_strategies = seed_config.get("strategies", [])
                if uploaded_strategies:
                    seed_population = uploaded_strategies[:top_n]
                    logger.info(
                        f"Task {task_id}: Using {len(seed_population)} uploaded seed strategies"
                    )

        gs_finder = GeneticStrategyFinder(
            training_data=training_data,
            run_config=run_config,
            run_id=run_id,
            seed_population=seed_population if seed_population else None,
            keep_structure=keep_structure,
        )

        def progress_callback(data):
            current_progress_data = schemas.GeneticRunProgress(
                current_generation=data["current_generation"],
                total_generations=data["total_generations"],
                best_fitness_so_far=data["best_fitness_so_far"],
                average_fitness_this_gen=data["average_fitness_this_gen"],
                status_message=f"Generation {data['current_generation']}/{data['total_generations']}: Screening...",
            )
            celery_task.update_state(
                state="PROGRESS",
                meta={
                    "progress_info": current_progress_data.model_dump(exclude_none=True)
                },
            )

            # NOTE: We removed DB save from here because mixing sync callbacks with async DB
            # operations causes "connection was closed" errors. Progress history will be saved
            # at the end of the run. Real-time updates go through Redis -> WebSocket.

            # === Publish to Redis for WebSocket real-time updates ===
            if redis_client_for_tasks:
                try:
                    ws_payload = {
                        "channel": f"genetic-progress:{run_id}",
                        "payload": {
                            "generation": data["current_generation"],
                            "best_fitness": data["best_fitness_so_far"],
                            "avg_fitness": data["average_fitness_this_gen"],
                            "status_message": f"Gen {data['current_generation']}/{data['total_generations']}: Best={data['best_fitness_so_far']:.4f}, Avg={data['average_fitness_this_gen']:.4f}",
                        },
                    }
                    redis_client_for_tasks.publish(
                        f"genetic-progress:{run_id}", json.dumps(ws_payload["payload"])
                    )
                    logger.debug(
                        f"Published genetic progress to Redis channel: genetic-progress:{run_id}"
                    )
                except Exception as redis_err:
                    logger.warning(
                        f"Task {task_id}: Failed to publish genetic progress to Redis: {redis_err}"
                    )

        logger.info(
            f"Task {task_id}: Starting Phase 1: Fast screening with GeneticStrategyFinder..."
        )
        hall_of_fame = gs_finder.run(
            map_function=map, progress_callback=progress_callback
        )

        logger.info(
            f"Task {task_id}: Phase 1 finished. Found {len(hall_of_fame)} candidates in Hall of Fame."
        )

        # === PHASE 4: Save results (new separate session) ===
        async with session_factory() as session:
            try:
                db_run_final_op = await session.get(models.GeneticRun, run_id)
                if not db_run_final_op:
                    raise Exception(
                        f"GeneticRun {run_id} disappeared during HoF processing."
                    )

                logger.info(
                    f"Task {task_id}: Dispatching final evaluation tasks for Hall of Fame strategies for run {run_id}..."
                )
                top_n_to_save = run_config.get("hof_size_to_save", 10)
                dispatched_hof_tasks = 0

                for result in hall_of_fame[:top_n_to_save]:
                    strategy_json_to_save = result["strategy_json"]
                    fitness_score_from_ga = result["fitness_score"]

                    backtest_params_for_hof_task = {
                        "strategy_name": "GeneticStrategy",
                        "symbol": target_symbol,
                        "start_date": data_start_date_iso,
                        "end_date": data_end_date_iso,
                        "params": {
                            "config": strategy_json_to_save,
                            "genetic_run_id": run_id,
                            "ga_rank": result["rank"],
                            "ga_fitness_score": fitness_score_from_ga,
                        },
                        "l2_storage_path": run_config.get("l2_storage_path"),
                    }

                    try:
                        hof_backtest_task = run_backtest_task.delay(
                            backtest_params_for_hof_task, user_id
                        )
                        dispatched_hof_tasks += 1

                        kpis_from_ga = result["kpis_json"]
                        kpis_from_ga["status"] = "PENDING_EVALUATION"
                        kpis_from_ga["backtest_task_id"] = hof_backtest_task.id

                        await crud.create_found_strategy(
                            db=session,
                            genetic_run_id=run_id,
                            rank=result["rank"],
                            strategy_json=strategy_json_to_save,
                            fitness_score=fitness_score_from_ga,
                            kpis_json=kpis_from_ga,
                        )
                    except Exception as e_dispatch:
                        logger.error(
                            f"Task {task_id}: Failed to dispatch or save FoundStrategy for HoF rank {result['rank']}: {e_dispatch}",
                            exc_info=True,
                        )

                db_run_final_op.status = "COMPLETED"
                db_run_final_op.completed_at = datetime.now(timezone.utc)
                if db_run_final_op.progress is None:
                    db_run_final_op.progress = {}
                db_run_final_op.progress["status_message"] = (
                    f"Genetic search complete. Dispatched {dispatched_hof_tasks} final evaluation tasks."
                )
                flag_modified(db_run_final_op, "progress")
                await session.commit()

                return {
                    "status": "COMPLETED",
                    "run_id": run_id,
                    "hall_of_fame_tasks_dispatched": dispatched_hof_tasks,
                }

            except Exception as e:
                logger.error(
                    f"Task {task_id}: Genetic search for Run ID {run_id} failed during save: {e}",
                    exc_info=True,
                )
                if session.is_active:
                    await session.rollback()
                    db_run_on_error = await session.get(models.GeneticRun, run_id)
                    if db_run_on_error:
                        db_run_on_error.status = "FAILED"
                        db_run_on_error.error_message = str(e)[:2000]
                        db_run_on_error.completed_at = datetime.now(timezone.utc)
                        await session.commit()
                raise
    finally:
        user_id_context.reset(token)


@celery_app.task(bind=True, name="run_genetic_search_task")
def run_genetic_search_task(self, run_id: str, user_id: int):
    task_id = self.request.id
    redis_key = f"concurrent_tasks:user:{user_id}"
    try:
        return run_async_from_sync(_async_run_genetic_search(self, run_id, user_id))
    except Exception as e:
        logger.critical(
            f"Genetic search master task {task_id} FAILED: {e}", exc_info=True
        )
        raise
    finally:
        if redis_client_for_tasks:
            try:
                # Check if key exists, only then decrement
                if redis_client_for_tasks.exists(redis_key):
                    count = redis_client_for_tasks.decr(redis_key)
                    logger.info(
                        f"Task {task_id} finished. Decremented concurrent task counter for user {user_id}. New count: {count}"
                    )
                else:
                    logger.warning(
                        f"Task {task_id}: Could not find redis key '{redis_key}' to decrement. It may have expired or was never set."
                    )
            except Exception as redis_err:
                logger.error(
                    f"Task {task_id}: FAILED to access Redis for task counter decrement. Key: {redis_key}. Error: {redis_err}"
                )


async def _async_generate_dataset_logic(
    celery_task, run_id: str, user_id: int, session: Optional[AsyncSession] = None
):
    from bot_module.redis_handler import user_id_context

    token = user_id_context.set(user_id)
    try:

        async def task_body(db_session: AsyncSession):
            db_run = None
            try:
                db_run = await crud.get_dataset_run(
                    db_session, user_id=user_id, run_id=run_id
                )
                if not db_run:
                    raise ValueError(f"DatasetRun with ID {run_id} not found.")
                db_run.status = "RUNNING"
                await db_session.commit()
                if celery_task:
                    celery_task.update_state(
                        state="PROGRESS",
                        meta={"status": "Initializing data generator..."},
                    )
                params = db_run.parameters_json
                generator = DatasetGenerator(run_params=params, user_id=user_id)
                final_df, feature_names = await generator.generate()
                if final_df is None:
                    raise ValueError("Dataset generator returned error (None).")
                dataset_path = Path(config.DATASETS_STORAGE_PATH) / f"{run_id}.parquet"
                dataset_path.parent.mkdir(parents=True, exist_ok=True)
                final_df.to_parquet(dataset_path, index=False)
                db_run.status = "COMPLETED"
                db_run.completed_at = datetime.now(timezone.utc)
                db_run.file_path = str(dataset_path)
                db_run.feature_list = feature_names
                db_run.dataset_shape = {
                    "rows": len(final_df),
                    "cols": len(final_df.columns),
                }
                await db_session.commit()
                return {"status": "Completed", "file_path": str(dataset_path)}
            except Exception as e:
                logger.error(
                    f"Dataset generation task (Run ID: {run_id}) failed: {e}",
                    exc_info=True,
                )
                if db_session and db_run:
                    await db_session.rollback()
                    db_run.status = "FAILED"
                    db_run.error_message = str(e)
                    db_run.completed_at = datetime.now(timezone.utc)
                    await db_session.commit()
                raise

        if session:
            return await task_body(session)
        else:
            session_factory = get_session_for_worker()
            async with session_factory() as new_session:
                return await task_body(new_session)
    finally:
        user_id_context.reset(token)


@celery_app.task(bind=True, name="tasks.generate_dataset")
def generate_dataset_task(self, run_id: str, user_id: int):
    task_id = self.request.id
    logger.info(f"Received dataset generation task {task_id} (Run ID: {run_id})")
    self.update_state(state="PENDING", meta={"status": "Task received and queued."})

    redis_key = f"concurrent_tasks:user:{user_id}"
    try:
        return run_async_from_sync(_async_generate_dataset_logic(self, run_id, user_id))
    except Exception as e:
        logger.critical(f"Dataset generation task {task_id} FAILED: {e}", exc_info=True)
        raise
    finally:
        if redis_client_for_tasks:
            try:
                # Check if key exists, only then decrement
                if redis_client_for_tasks.exists(redis_key):
                    count = redis_client_for_tasks.decr(redis_key)
                    logger.info(
                        f"Task {task_id} finished. Decremented concurrent task counter for user {user_id}. New count: {count}"
                    )
                else:
                    logger.warning(
                        f"Task {task_id}: Could not find redis key '{redis_key}' to decrement. It may have expired or was never set."
                    )
            except Exception as redis_err:
                logger.error(
                    f"Task {task_id}: FAILED to access Redis for task counter decrement. Key: {redis_key}. Error: {redis_err}"
                )


async def _async_train_model_logic(
    celery_task, run_id: str, user_id: int, session: Optional[AsyncSession] = None
):
    from bot_module.redis_handler import user_id_context

    token = user_id_context.set(user_id)
    try:

        async def task_body(db_session: AsyncSession):
            db_run = None
            try:
                db_run = await crud.get_training_run(
                    db_session, user_id=user_id, run_id=run_id
                )
                if not db_run:
                    raise ValueError(f"TrainingRun with ID {run_id} not found.")
                db_run.status = "RUNNING"
                await db_session.commit()
                if celery_task:
                    celery_task.update_state(
                        state="PROGRESS", meta={"status": "Starting model training..."}
                    )
                dataset_path = db_run.dataset.file_path
                if not dataset_path or not Path(dataset_path).exists():
                    raise FileNotFoundError(f"Dataset file not found: {dataset_path}")
                training_params = db_run.parameters_json
                model_type = training_params.get("model_type")
                model_filename = (
                    f"{run_id}.joblib" if "River" in model_type else f"{run_id}.pkl"
                )
                report_filename = (
                    f"{run_id}.json" if "River" in model_type else f"{run_id}.csv"
                )
                model_output_path = Path(config.MODELS_STORAGE_PATH) / model_filename
                report_output_path = Path(config.REPORTS_STORAGE_PATH) / report_filename
                model_output_path.parent.mkdir(parents=True, exist_ok=True)
                report_output_path.parent.mkdir(parents=True, exist_ok=True)
                training_config = {
                    "data_file": dataset_path,
                    "model_out": str(model_output_path),
                    "report_out": str(report_output_path),
                    "model_type": model_type,
                    "feature_set_name": db_run.dataset.name,
                    "use_all_numeric_features": True,
                    **(training_params.get("hyperparameters") or {}),
                }
                loop = asyncio.get_running_loop()
                model_path_result, report_path_result = None, None
                if "River" in model_type:
                    model_path_result, report_path_result = await loop.run_in_executor(
                        None, run_river_training_from_config, training_config
                    )
                else:
                    report_path_result = await loop.run_in_executor(
                        None, run_sklearn_training_from_config, training_config
                    )
                    model_path_result = "N/A for sklearn batch"
                logger.info(
                    f"Training completed. Model: {model_path_result}, Report: {report_path_result}"
                )
                db_run.status = "COMPLETED"
                db_run.completed_at = datetime.now(timezone.utc)
                db_run.model_path = str(model_path_result)
                db_run.report_path = str(report_path_result)
                await db_session.commit()
                return {
                    "status": "Completed",
                    "model_path": str(model_path_result),
                    "report_path": str(report_path_result),
                }
            except Exception as e:
                logger.error(
                    f"Model training task (Run ID: {run_id}) failed: {e}", exc_info=True
                )
                if db_session and db_run:
                    await db_session.rollback()
                    db_run.status = "FAILED"
                    db_run.error_message = str(e)
                    db_run.completed_at = datetime.now(timezone.utc)
                    await db_session.commit()
                raise

        if session:
            return await task_body(session)
        else:
            session_factory = get_session_for_worker()
            async with session_factory() as new_session:
                return await task_body(new_session)
    finally:
        user_id_context.reset(token)


async def check_and_grant_first_model_training_achievement(user_id: int):
    async with get_isolated_worker_session() as session:
        result = await session.execute(
            select(models.Task)
            .where(
                models.Task.user_id == user_id, models.Task.task_type == "train_model"
            )
            .limit(2)
        )
        tasks = result.scalars().all()
        if len(tasks) <= 1:
            await grant_achievement(session, user_id, "the_professor")


@celery_app.task(bind=True, name="tasks.train_model")
def train_model_task(self, run_id: str, user_id: int):
    task_id = self.request.id
    logger.info(f"Received model training task {task_id} (Run ID: {run_id})")
    self.update_state(state="PENDING", meta={"status": "Task received and queued."})

    run_async_from_sync(check_and_grant_first_model_training_achievement(user_id))

    redis_key = f"concurrent_tasks:user:{user_id}"
    try:
        return run_async_from_sync(_async_train_model_logic(self, run_id, user_id))
    except Exception as e:
        logger.critical(f"Model training task {task_id} FAILED: {e}", exc_info=True)
        raise
    finally:
        if redis_client_for_tasks:
            try:
                # Check if key exists, only then decrement
                if redis_client_for_tasks.exists(redis_key):
                    count = redis_client_for_tasks.decr(redis_key)
                    logger.info(
                        f"Task {task_id} finished. Decremented concurrent task counter for user {user_id}. New count: {count}"
                    )
                else:
                    logger.warning(
                        f"Task {task_id}: Could not find redis key '{redis_key}' to decrement. It may have expired or was never set."
                    )
            except Exception as redis_err:
                logger.error(
                    f"Task {task_id}: FAILED to access Redis for task counter decrement. Key: {redis_key}. Error: {redis_err}"
                )


@celery_app.task(bind=True, name="tasks.run_paper_trading_session")
def run_paper_trading_session_task(
    self, user_id: int, config_id: str, launch_overrides: Dict[str, Any]
):
    """
    Sends a command to the main TradingController to start a paper trading session.
    """
    task_id = self.request.id
    logger.info(
        f"Dispatching paper trading start command for task {task_id} for user {user_id} with config {config_id}"
    )
    self.update_state(state="STARTED", meta={"status": "Dispatching start command."})

    try:
        # This task is now lightweight and uses an async helper to dispatch the command.
        run_async_from_sync(
            _async_dispatch_paper_start_command(
                self, task_id, user_id, config_id, launch_overrides
            )
        )
        logger.info(
            f"Paper trading start command for task {task_id} dispatched successfully."
        )
        return {"status": "dispatched"}
    except Exception as e:
        logger.critical(
            f"Failed to dispatch paper trading start command for task {task_id}: {e}",
            exc_info=True,
        )
        self.update_state(state="FAILURE", meta={"status": str(e)})
        raise


async def _async_dispatch_paper_start_command(
    celery_task,
    task_id: str,
    user_id: int,
    config_id: str,
    launch_overrides: Dict[str, Any],
):
    """
    Asynchronously fetches config and dispatches the START_STRATEGY command to Redis.
    """
    # The spec requires a synchronous redis client.
    # We will create it here but use it carefully in an async context.
    # Publishing is a fast, fire-and-forget operation, so blocking should be minimal.
    redis_sync_client = None
    try:
        # 1. Get DB session and fetch config
        async with get_isolated_worker_session() as session:
            config_to_run = await crud.get_strategy_config(
                session, user_id=user_id, config_id=config_id
            )
            if not config_to_run:
                raise ValueError(
                    f"Strategy config {config_id} not found for user {user_id}"
                )

            pydantic_config = schemas.StrategyConfig.model_validate(config_to_run)
            config_data_dict = pydantic_config.config_data

            # Grant achievement for starting paper trading
            await grant_achievement(session, user_id, "first_paper_trade")
            await session.commit()

        # 2. Construct the full payload
        logger.info(
            f"Task {task_id}: Overriding saved config with launch params: {launch_overrides}"
        )

        payload = {
            "user_id": user_id,
            "id": config_id,  # Use 'id' for the instance identifier
            "config_id": config_id,  # Also include config_id for clarity
            "mode": "paper",  # CRITICAL: Ensure the mode is set to 'paper'
            "symbol_selection_mode": launch_overrides.get(
                "symbol_selection_mode", pydantic_config.symbol_selection_mode
            ),
            "symbols": launch_overrides.get("symbols", pydantic_config.symbols),
            "config_data": config_data_dict,
            "name": pydantic_config.name,
            "description": pydantic_config.description,
            "use_ml_confirmation": pydantic_config.use_ml_confirmation,
            "foundation_weights": pydantic_config.foundation_weights,
        }

        # 3. Create a synchronous Redis client
        redis_sync_client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            username=config.REDIS_USERNAME,
            password=config.REDIS_PASSWORD,
            decode_responses=True,
        )

        # 4. Form the command
        command = {"command": "START_STRATEGY", "payload": payload}

        # 5. Publish the command
        redis_sync_client.publish(config.REDIS_COMMAND_CHANNEL, json.dumps(command))

        logger.info(
            f"Published START_STRATEGY command for config {config_id} to {config.REDIS_COMMAND_CHANNEL}"
        )

    except Exception as e:
        logger.error(
            f"Error in _async_dispatch_paper_start_command for task {task_id}: {e}",
            exc_info=True,
        )
        raise
    finally:
        if redis_sync_client:
            redis_sync_client.close()


from celery.schedules import crontab


async def validate_backtest_for_leaderboard(backtest_run: models.BacktestRun) -> bool:
    """Validates a backtest run for leaderboard submission."""
    if not backtest_run.kpi_results_json:
        return False

    trades_count = backtest_run.kpi_results_json.get("total_trades", 0)
    if trades_count < 30:
        logger.warning(
            f"Backtest {backtest_run.id} has less than 30 trades, rejecting from leaderboard."
        )
        return False

    # TODO: Add more validation logic (anti-HODL, anti-pump)

    return True


async def publish_to_leaderboard(
    db: AsyncSession,
    backtest_run: models.BacktestRun,
    shared_backtest: models.SharedBacktest,
):
    """Publishes a validated backtest to the leaderboard."""
    if not await validate_backtest_for_leaderboard(backtest_run):
        return

    kpis = backtest_run.kpi_results_json
    if not kpis:
        return

    categories = ["sharpe_ratio", "net_pnl_percent"]
    for category in categories:
        if category in kpis:
            entry = models.LeaderboardEntry(
                user_id=backtest_run.user_id,
                backtest_run_id=backtest_run.id,
                shared_backtest_slug=shared_backtest.public_slug,
                period=models.LeaderboardPeriod.ALL_TIME,  # For now, only all_time
                category=category,
                score=kpis[category],
                rank=0,  # Rank will be calculated later
                meta_data={
                    "pnl": kpis.get("total_pnl"),
                    "win_rate": kpis.get("win_rate"),
                    "trades": kpis.get("total_trades"),
                    "symbol": backtest_run.symbol,
                },
            )
            db.add(entry)

    await db.commit()


@celery_app.task(name="tasks.update_leaderboard_ranks")
def update_leaderboard_ranks_task():
    """Periodically updates the ranks in the leaderboard."""
    logger.info("Updating leaderboard ranks...")
    run_async_from_sync(_async_update_leaderboard_ranks())


async def _async_update_leaderboard_ranks():
    async with get_isolated_worker_session() as session:
        periods = [p.value for p in models.LeaderboardPeriod]
        categories = ["sharpe_ratio", "net_pnl_percent"]

        for period in periods:
            for category in categories:
                entries = await session.execute(
                    select(models.LeaderboardEntry)
                    .filter(
                        models.LeaderboardEntry.period == period,
                        models.LeaderboardEntry.category == category,
                    )
                    .order_by(models.LeaderboardEntry.score.desc())
                )

                rank = 1
                for entry in entries.scalars().all():
                    entry.rank = rank
                    rank += 1

        await session.commit()
    logger.info("Leaderboard ranks updated.")


@celery_app.task
def recalculate_gene_rarity():
    """
    Periodically recalculates rarity for all genes based on current user ownership.
    Rarity = (users_with_gene / total_active_users) * 100
    """
    logger.info("Running periodic task: recalculate_gene_rarity")
    run_async_from_sync(_async_recalculate_gene_rarity())


async def _async_recalculate_gene_rarity():
    async with get_isolated_worker_session() as session:
        try:
            # Count total active users
            total_users_result = await session.execute(
                select(models.User).where(models.User.is_active)
            )
            total_users = len(total_users_result.scalars().all())

            if total_users == 0:
                logger.info("No active users found. Skipping rarity calculation.")
                return

            # Get all genes
            genes_result = await session.execute(select(models.Gene))
            genes = genes_result.scalars().all()

            updated_count = 0
            for gene in genes:
                # Count users who have this gene
                users_with_gene_result = await session.execute(
                    select(models.UserGene)
                    .join(models.User, models.UserGene.user_id == models.User.id)
                    .where(
                        models.UserGene.gene_id == gene.id,
                        models.User.is_active,
                    )
                )
                users_with_gene = len(users_with_gene_result.scalars().all())

                # Calculate new rarity
                new_rarity = round((users_with_gene / total_users) * 100.0, 2)

                if gene.rarity != new_rarity:
                    gene.rarity = new_rarity
                    updated_count += 1

            await session.commit()
            logger.info(
                f"Updated rarity for {updated_count}/{len(genes)} genes. Total active users: {total_users}"
            )
        except Exception as e:
            logger.error(f"Error recalculating gene rarity: {e}", exc_info=True)
            await session.rollback()


async def _async_watchdog_logic():
    """
    Async logic to check and fix stuck counters
    and "zombie" tasks.
    """
    logger.info("[WATCHDOG] Starting concurrent task watchdog check...")

    # 1. Get the actual list of active tasks from all Celery workers
    active_celery_tasks = {}
    try:
        # Inspection is a blocking operation, we perform it in a separate thread
        # to avoid blocking the event loop.
        def inspect_workers():
            i = celery_app.control.inspect()
            return i.active()

        loop = asyncio.get_running_loop()
        active_tasks_per_worker = await loop.run_in_executor(None, inspect_workers)

        if not active_tasks_per_worker:
            logger.info(
                "[WATCHDOG] No active Celery workers found or no tasks running."
            )
            active_tasks_per_worker = {}

        # Consolidate all active tasks into a single dict {task_id: user_id}
        for worker, tasks in active_tasks_per_worker.items():
            for task_info in tasks:
                task_id = task_info["id"]
                try:
                    # Arguments are passed as a string, parse them safely
                    # Example: "({}, 1)" -> ({...}, 1)
                    args = ast.literal_eval(task_info.get("args", "()"))
                    if len(args) > 1 and isinstance(args[1], int):
                        user_id = args[1]
                        active_celery_tasks[task_id] = user_id
                except (ValueError, SyntaxError):
                    logger.warning(
                        f"[WATCHDOG] Could not parse args for task {task_id}: {task_info.get('args')}"
                    )

        logger.info(
            f"[WATCHDOG] Found {len(active_celery_tasks)} actually running tasks across all workers."
        )

    except Exception as e:
        logger.error(
            f"[WATCHDOG] Could not inspect Celery workers: {e}. Aborting check.",
            exc_info=True,
        )
        return

    # 2. Find all users with non-zero counter in Redis
    stale_counters_fixed = 0
    if redis_client_for_tasks:
        user_counters = {}
        try:
            # Use SCAN_ITER for safe key scanning
            for key in redis_client_for_tasks.scan_iter("concurrent_tasks:user:*"):
                user_id_str = key.split(":")[-1]
                if user_id_str.isdigit():
                    user_id = int(user_id_str)
                    count = int(redis_client_for_tasks.get(key) or 0)
                    if count > 0:
                        user_counters[user_id] = count
        except Exception as e:
            logger.error(f"[WATCHDOG] Failed to scan Redis for task counters: {e}")
            user_counters = {}  # Reset to avoid continuing with incomplete data

        if user_counters:
            logger.info(
                f"[WATCHDOG] Found {len(user_counters)} users with non-zero task counters in Redis. Verifying..."
            )

            # 3. Verify counters against reality
            active_tasks_by_user = defaultdict(list)
            for task_id, user_id in active_celery_tasks.items():
                active_tasks_by_user[user_id].append(task_id)

            for user_id, redis_count in user_counters.items():
                actual_running_count = len(active_tasks_by_user.get(user_id, []))

                if redis_count != actual_running_count:
                    logger.warning(
                        f"[WATCHDOG] Discrepancy for user {user_id}: "
                        f"Redis count is {redis_count}, but actually running {actual_running_count} tasks. Fixing..."
                    )
                    redis_key = f"concurrent_tasks:user:{user_id}"
                    redis_client_for_tasks.set(redis_key, actual_running_count)
                    stale_counters_fixed += 1

    logger.info(
        f"[WATCHDOG] Finished counter verification. Fixed {stale_counters_fixed} stale counters."
    )

    # 4. Find and fix "zombie" tasks in our DB
    zombie_tasks_fixed = 0
    async with get_isolated_worker_session() as session:
        try:
            running_db_tasks_result = await session.execute(
                select(models.Task).where(models.Task.status == "RUNNING")
            )
            running_db_tasks = running_db_tasks_result.scalars().all()

            if not running_db_tasks:
                logger.info(
                    "[WATCHDOG] No tasks with 'RUNNING' status found in DB. Nothing to check."
                )
                return

            logger.info(
                f"[WATCHDOG] Found {len(running_db_tasks)} tasks with 'RUNNING' status in DB. Checking against active workers..."
            )

            for db_task in running_db_tasks:
                if db_task.task_id not in active_celery_tasks:
                    logger.warning(
                        f"[WATCHDOG] Found zombie task! Task ID {db_task.task_id} (User: {db_task.user_id}) "
                        f"is 'RUNNING' in DB but not active on any worker. Marking as FAILED."
                    )
                    db_task.status = "FAILED"
                    db_task.error_message = "Watchdog: Task was found in 'RUNNING' state but was not active on any worker. Likely terminated unexpectedly."
                    db_task.completed_at = datetime.now(timezone.utc)
                    zombie_tasks_fixed += 1

            if zombie_tasks_fixed > 0:
                await session.commit()

            logger.info(
                f"[WATCHDOG] Finished zombie task cleanup. Marked {zombie_tasks_fixed} tasks as FAILED."
            )

        except Exception as e:
            logger.error(
                f"[WATCHDOG] Error during zombie task cleanup: {e}", exc_info=True
            )
            await session.rollback()


@celery_app.task(name="tasks.concurrent_task_watchdog")
def concurrent_task_watchdog():
    """
    Celery task to run watchdog timer logic.
    """
    run_async_from_sync(_async_watchdog_logic())


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        crontab(hour=0, minute=5),
        check_expired_subscriptions.s(),
    )
    sender.add_periodic_task(
        crontab(hour=0, minute=15),
        update_affiliate_commissions_task.s(),
    )
    sender.add_periodic_task(
        crontab(minute=0),
        update_leaderboard_ranks_task.s(),
    )
    sender.add_periodic_task(
        crontab(hour=3, minute=0),
        recalculate_gene_rarity.s(),
    )
    sender.add_periodic_task(crontab(minute="*/15"), concurrent_task_watchdog.s())


@celery_app.task
def check_expired_subscriptions():
    """
    Checks for users with expired plans and downgrades them to the 'free' plan.
    """
    logger.info("Running periodic task: check_expired_subscriptions")
    run_async_from_sync(_async_check_expired_subscriptions())


@celery_app.task
def update_affiliate_commissions_task():
    """
    Moves commissions from 'pending' to 'available' if the hold period has passed.
    """
    logger.info("Running periodic task: update_affiliate_commissions_task")
    run_async_from_sync(_async_update_affiliate_commissions())


async def _async_update_affiliate_commissions():
    async with get_isolated_worker_session() as session:
        try:
            updated_count = await crud.update_commission_statuses(session)
            await session.commit()
            if updated_count > 0:
                logger.info(
                    f"Successfully updated {updated_count} affiliate commissions to 'available' status."
                )
        except Exception as e:
            logger.error(f"Error updating affiliate commissions: {e}", exc_info=True)
            await session.rollback()


async def _publish_live_deactivation_commands(
    db_session: AsyncSession, user_ids: List[int]
) -> int:
    if not redis_client_for_tasks:
        logger.warning(
            "Redis client for tasks is unavailable. Skipping live controller deactivation sync for expired subscriptions."
        )
        return 0

    published_commands = 0
    for user_id in user_ids:
        active_api_keys = await crud.get_active_api_keys_for_user(
            db_session, user_id=user_id
        )
        for api_key_id in get_active_api_key_ids(active_api_keys):
            command = build_deactivate_api_key_command(user_id, api_key_id)
            redis_client_for_tasks.publish(
                config.REDIS_COMMAND_CHANNEL, json.dumps(command)
            )
            published_commands += 1

    return published_commands


async def _async_check_expired_subscriptions():
    async with get_isolated_worker_session() as session:
        try:
            expired_users_result = await session.execute(
                select(models.User).where(
                    models.User.plan != "free",
                    models.User.plan_expires_at <= datetime.now(timezone.utc),
                )
            )
            users_to_downgrade = expired_users_result.scalars().all()
            if not users_to_downgrade:
                logger.info("No expired subscriptions found.")
                return
            user_ids_to_stop = [user.id for user in users_to_downgrade]
            for user in users_to_downgrade:
                logger.info(
                    f"User {user.id}'s plan '{user.plan}' has expired. Downgrading to 'free'."
                )
                user.plan = "free"
                user.plan_expires_at = None
            await session.commit()
            logger.info(f"Successfully downgraded {len(users_to_downgrade)} users.")
        except Exception as e:
            logger.error(
                f"Error checking for expired subscriptions: {e}", exc_info=True
            )
            await session.rollback()
            return

        try:
            published_commands = await _publish_live_deactivation_commands(
                session, user_ids_to_stop
            )
            if published_commands:
                logger.info(
                    "Published %s DEACTIVATE_API_KEY commands after subscription expiry downgrade.",
                    published_commands,
                )
        except Exception as e:
            logger.error(
                "Expired subscriptions were downgraded, but live controller deactivation sync failed: %s",
                e,
                exc_info=True,
            )


@celery_app.task(bind=True, name="run_data_pipeline_task")
def run_data_pipeline_task(self, cmd_args: List[str]):
    """
    Runs download_pipeline.py as a subprocess on the Celery worker
    redirecting output to the logs/download_pipeline.log file.
    """
    import subprocess
    from pathlib import Path

    logger.info(
        f"Starting data pipeline task (ID: {self.request.id}) with args: {cmd_args}"
    )

    # Ensure log directory exists inside worker
    log_file_path = Path("logs") / "download_pipeline.log"
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["python", "scripts/download_pipeline.py"] + cmd_args

    # Update status to running and store task_id
    if redis_client_for_tasks:
        try:
            redis_client_for_tasks.set("depthsight:data-pipeline:status", "running")
            redis_client_for_tasks.set(
                "depthsight:data-pipeline:task_id", self.request.id
            )
        except Exception as redis_err:
            logger.warning(f"Failed to write initial status to Redis: {redis_err}")

    with open(log_file_path, "w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(Path(__file__).parent.resolve()),
        )

        try:
            while True:
                try:
                    ret_code = process.wait(timeout=2.0)
                    logger.info(
                        f"Data pipeline process finished with return code {ret_code}"
                    )
                    if ret_code != 0:
                        raise subprocess.CalledProcessError(ret_code, cmd)
                    break
                except subprocess.TimeoutExpired:
                    pass

            # Update status to completed
            if redis_client_for_tasks:
                try:
                    redis_client_for_tasks.set(
                        "depthsight:data-pipeline:status", "completed"
                    )
                except Exception as redis_err:
                    logger.warning(
                        f"Failed to write completed status to Redis: {redis_err}"
                    )

        except BaseException as e:
            logger.warning(
                f"Celery task run_data_pipeline_task was interrupted/cancelled/failed. Terminating subprocess... Error: {e}"
            )
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()

            if redis_client_for_tasks:
                try:
                    if isinstance(e, subprocess.CalledProcessError):
                        redis_client_for_tasks.set(
                            "depthsight:data-pipeline:status", "failed"
                        )
                    else:
                        redis_client_for_tasks.set(
                            "depthsight:data-pipeline:status", "stopped"
                        )
                except Exception as redis_err:
                    logger.warning(
                        f"Failed to write failure/stopped status to Redis: {redis_err}"
                    )
            raise e
