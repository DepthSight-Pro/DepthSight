# datatypes.py

from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
from typing import Optional, List, Tuple, Dict, Any
from enum import Enum
import time
from typing_extensions import Literal
import logging


# Enums and Dataclasses
class SignalDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class OrderMode(Enum):
    MARKET = "MARKET"
    LIMIT_BREAK = "LIMIT_BREAK"
    LIMIT_RETEST = "LIMIT_RETEST"


@dataclass
class PartialTarget:
    price: float
    fraction: float

    def __post_init__(self):
        if not (0 < self.fraction <= 1.0):
            raise ValueError(
                f"Partial target fraction must be between 0.0 and 1.0 (exclusive of 0). Got: {self.fraction}"
            )
        if self.price <= 0:
            raise ValueError(
                f"Partial target price must be positive. Got: {self.price}"
            )


@dataclass
class StrategySignal:
    strategy_name: str
    symbol: str
    direction: SignalDirection
    stop_loss: Optional[float]
    take_profit: Optional[float]
    entry_price: Optional[float] = None
    mode: OrderMode = OrderMode.MARKET
    signal_time: float = field(default_factory=time.time)
    confidence: float = 0.5
    trigger_price: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    partial_targets: Optional[List[PartialTarget]] = None
    move_sl_to_be_on_first_tp: bool = False
    risk_pct: Optional[float] = None
    risk_usd: Optional[float] = None
    no_stop_loss: bool = False

    def __post_init__(self):
        try:
            self.no_stop_loss = self.stop_loss is None
            sl_float = float(self.stop_loss) if self.stop_loss is not None else None
            tp_float = float(self.take_profit) if self.take_profit is not None else None
            entry_float = (
                float(self.entry_price) if self.entry_price is not None else None
            )
            trigger_float = (
                float(self.trigger_price) if self.trigger_price is not None else None
            )
            risk_pct_float = float(self.risk_pct) if self.risk_pct is not None else None
            risk_usd_float = float(self.risk_usd) if self.risk_usd is not None else None
            # stop_loss=None means "no stop" mode (for DCA/Grid strategies)
            if sl_float is not None and sl_float <= 0:
                self.stop_loss = None
                self.no_stop_loss = True
                sl_float = None
            if tp_float is not None and tp_float <= 0:
                raise ValueError(f"Invalid take_profit: {self.take_profit}")
            if risk_pct_float is not None and risk_pct_float < 0:
                raise ValueError(f"Invalid risk_pct: {self.risk_pct}")
            if risk_usd_float is not None and risk_usd_float < 0:
                raise ValueError(f"Invalid risk_usd: {self.risk_usd}")
            comparison_price = None
            if self.mode != OrderMode.MARKET:
                if entry_float is None or entry_float <= 0:
                    raise ValueError(
                        f"LIMIT mode requires valid positive entry_price. Got: {self.entry_price}"
                    )
                comparison_price = entry_float
            else:
                if trigger_float is None or trigger_float <= 0:
                    raise ValueError(
                        f"MARKET mode requires valid positive trigger_price. Got: {self.trigger_price}"
                    )
                comparison_price = trigger_float
            comp_float = comparison_price
            # SL validation only if it is set (not None = no stop mode)
            if sl_float is not None:
                if self.direction == SignalDirection.LONG:
                    if sl_float >= comp_float:
                        raise ValueError(
                            f"SL ({sl_float:.8f}) must be below comparison price ({comp_float:.8f}) for LONG."
                        )
                elif self.direction == SignalDirection.SHORT:
                    if sl_float <= comp_float:
                        raise ValueError(
                            f"SL ({sl_float:.8f}) must be above comparison price ({comp_float:.8f}) for SHORT."
                        )
            if self.direction == SignalDirection.LONG:
                if tp_float is not None and tp_float <= comp_float:
                    raise ValueError(
                        f"TP ({tp_float:.8f}) must be above comparison price ({comp_float:.8f}) for LONG."
                    )
            elif self.direction == SignalDirection.SHORT:
                if tp_float is not None and tp_float >= comp_float:
                    raise ValueError(
                        f"TP ({tp_float:.8f}) must be below comparison price ({comp_float:.8f}) for SHORT."
                    )
        except (ValueError, TypeError) as e:
            error_msg = f"Invalid StrategySignal base parameters for {self.strategy_name}/{self.symbol}: {e}"
            logging.error(error_msg)
            details_str = f"Dir={self.direction}, Mode={self.mode}, Entry={self.entry_price}, Trig={self.trigger_price}, SL={self.stop_loss}, TP={self.take_profit}"
            raise ValueError(f"{error_msg}. Details: {details_str}") from e
        if self.partial_targets:
            total_fraction = 0.0
            last_target_price = None
            comparison_price_pt = (
                entry_float if self.mode != OrderMode.MARKET else trigger_float
            )
            if comparison_price_pt is None:
                raise ValueError(
                    "Cannot validate partial targets without comparison price (entry/trigger)"
                )
            for i, target in enumerate(self.partial_targets):
                if self.direction == SignalDirection.LONG:
                    if target.price <= comparison_price_pt:
                        raise ValueError(
                            f"Partial target {i + 1} price ({target.price}) must be above comparison price ({comparison_price_pt}) for LONG."
                        )
                    if (
                        last_target_price is not None
                        and target.price <= last_target_price
                    ):
                        raise ValueError(
                            f"Partial target {i + 1} price ({target.price}) must be greater than previous target price ({last_target_price}) for LONG."
                        )
                elif self.direction == SignalDirection.SHORT:
                    if target.price >= comparison_price_pt:
                        raise ValueError(
                            f"Partial target {i + 1} price ({target.price}) must be below comparison price ({comparison_price_pt}) for SHORT."
                        )
                    if (
                        last_target_price is not None
                        and target.price >= last_target_price
                    ):
                        raise ValueError(
                            f"Partial target {i + 1} price ({target.price}) must be less than previous target price ({last_target_price}) for SHORT."
                        )
                last_target_price = target.price
                total_fraction += target.fraction
            if total_fraction > 1.000001:
                raise ValueError(
                    f"Sum of partial target fractions ({total_fraction}) cannot exceed 1.0."
                )
            if abs(total_fraction - 1.0) < 1e-9 and self.take_profit is not None:
                logging.warning(
                    f"Partial targets cover 100% ({total_fraction:.4f}), but a final take_profit ({self.take_profit}) is also set. Final TP will be ignored by the controller if all partials are hit."
                )
            if total_fraction < (1.0 - 1e-9) and self.take_profit is None:
                raise ValueError(
                    "Final take_profit must be set if partial targets do not sum to 1.0."
                )


@dataclass
class DensityInfo:
    price: float
    size_usd: float
    distance_from_current_price_abs: float
    side: Literal["bid", "ask"]
    distance_from_current_price_atr: Optional[float] = None


@dataclass
class OrderbookAnalysisResult:
    nearest_support: Optional[DensityInfo] = None
    nearest_resistance: Optional[DensityInfo] = None
    is_price_near_support: bool = False
    is_price_near_resistance: bool = False
    is_price_approaching_support: bool = False
    is_price_approaching_resistance: bool = False
    conflict: bool = False


# Dataclasses for position state and performance (from SimpleBacktester)


@dataclass
class BasePosition:
    """Base class describing the state of a trading position."""

    symbol: str
    direction: SignalDirection
    entry_price: float
    initial_quantity: float
    remaining_quantity: float
    entry_time: float  # Unix timestamp
    strategy: str
    initial_stop_loss: Optional[float] = None
    current_sl_price: Optional[float] = None
    initial_take_profit: Optional[float] = None
    no_stop_loss: bool = False

    # General control fields
    is_stop_at_be: bool = False
    move_sl_to_be_enabled: bool = False
    initial_risk_usd_planned: Optional[float] = None
    signal_details: Dict[str, Any] = field(default_factory=dict)

    # Fields for control from JSON
    scale_in_triggered: Optional[Dict[str, Any]] = None  # Flag for the backtester
    number_of_entries: int = 1
    max_entries: Optional[int] = None

    # Identification
    client_order_id: Optional[str] = None  # Use client_order_id as a unique trade ID
    config_id: Optional[str] = None
    user_id: Optional[int] = None
    num_partial_tp_hits: int = 0

    # DCA & GRID state
    dca_active_sos: int = 0
    dca_next_so_price: Optional[float] = None
    dca_management_params: Optional[Dict[str, Any]] = None
    dca_grid_init_triggered: Optional[Dict[str, Any]] = None
    dca_grid_init_in_progress: bool = False
    dca_order_ids: List[int] = field(default_factory=list)
    grid_order_ids: List[str] = field(default_factory=list)
    grid_init_triggered: Optional[Dict[str, Any]] = None
    grid_pending_orders: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BacktestPositionState(BasePosition):
    """Extends BasePosition with fields specific to backtesting."""

    entry_time: datetime  # datetime is more convenient in the backtester

    # List of executed partial exits
    partial_fills: List[Dict[str, Any]] = field(default_factory=list)

    # Partial exit plan (price, share, execution flag)
    partial_targets: List[Tuple[float, float, bool]] = field(default_factory=list)

    # Entry execution information
    entry_commission_paid: float = 0.0
    entry_fill_type: Optional[str] = None
    entry_atr: Optional[float] = None
    ideal_entry_price_l2: Optional[float] = None
    entry_slippage_usd: float = 0.0
    entry_sim_message: Optional[str] = None
    exit_reason: Optional[str] = None
    executions: List[Dict[str, Any]] = field(default_factory=list)

    def get_unrealized_pnl_pct(self, current_price: float) -> float:
        if self.entry_price == 0:
            return 0.0
        if self.direction == SignalDirection.LONG:
            pnl_pct = (current_price - self.entry_price) / self.entry_price * 100.0
        else:  # SHORT
            pnl_pct = (self.entry_price - current_price) / self.entry_price * 100.0
        return pnl_pct


@dataclass
class BtSymbolStrategyPerformanceStats:
    # Stores (pnl_usd: float, initial_risk_usd_planned: float)
    trade_results_buffer: deque = field(
        default_factory=deque
    )  # maxlen will be set in __init__
    current_pnl_sum_usd: float = 0.0
    sum_initial_risk_usd_in_window: float = 0.0
    current_wins_in_window: int = 0
    current_trades_in_window: int = 0  # Total trades in the buffer
    current_consecutive_losses: int = 0
    current_consecutive_wins_for_recovery: int = 0
    current_risk_multiplier_index: int = 0  # Default to 0 (full risk)
    last_penalty_timestamp: float = 0.0  # Timestamp of the last risk reduction
    total_trades_for_assessment: int = 0  # Total trades ever for this combo
