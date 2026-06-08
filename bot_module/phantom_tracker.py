# bot_module/phantom_tracker.py
"""
Phantom Trade Tracker — a module for tracking price behavior after BE.

After a trade is closed at breakeven (SL_AT_BE), this module
continues to track the price to determine:
- Would the price have reached the initial TP (BE "stole" the profit)?
- Would the price have reached the initial SL (BE "saved" from loss)?
- Or is the price "dangling" and would not have reached either level (timeout)?

This allows for optimizing BE parameters and understanding its real effectiveness.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
import logging

from bot_module import config

logger = logging.getLogger(__name__)


class PhantomStatus(str, Enum):
    """Phantom trade statuses."""

    TRACKING = "TRACKING"  # Actively tracked
    TP_HIT = "TP_HIT"  # Would have reached TP (BE stole profit)
    SL_HIT = "SL_HIT"  # Would have reached SL (BE saved from loss)
    TIMEOUT = "TIMEOUT"  # Timeout — reached neither TP nor SL


@dataclass
class PhantomTradeData:
    """
    Data for tracking a phantom trade.
    Created when a real trade is closed at SL_AT_BE.
    """

    # Identifiers
    real_trade_id: str
    user_id: int
    symbol: str
    direction: str  # "LONG" or "SHORT"
    strategy_config_id: Optional[str] = None

    # Input parameters
    entry_price: float = 0.0
    entry_time: Optional[datetime] = None

    # Initial levels (before moving to BE)
    initial_stop_loss: float = 0.0
    initial_take_profit: float = 0.0

    # Moment of BE trigger
    be_trigger_time: Optional[datetime] = None
    be_exit_price: float = 0.0
    real_pnl_pct: float = 0.0
    real_pnl_usd: Optional[float] = None

    # Current tracking state
    status: PhantomStatus = PhantomStatus.TRACKING
    candles_tracked: int = 0
    timeout_candles: int = 100

    # MAE/MFE after BE (Maximum Adverse/Favorable Excursion)
    mfe_after_be: float = 0.0  # Maximum movement towards profit (%)
    mae_after_be: float = 0.0  # Maximum movement against the position (%)
    mfe_price: Optional[float] = None
    mae_price: Optional[float] = None

    # Results (filled upon resolution)
    phantom_exit_time: Optional[datetime] = None
    phantom_exit_price: Optional[float] = None
    phantom_pnl_pct: Optional[float] = None
    phantom_pnl_usd: Optional[float] = None


class PhantomTracker:
    """
    Manager for tracking phantom trades.

    Usage:
    1. When a trade closes at SL_AT_BE, call create_phantom()
    2. On each new candle, call update() for all active phantoms
    3. Resolution occurs automatically upon reaching TP/SL/timeout
    """

    def __init__(self):
        self._active_phantoms: Dict[str, PhantomTradeData] = {}
        self._resolved_phantoms: List[PhantomTradeData] = []

    @property
    def active_count(self) -> int:
        return len(self._active_phantoms)

    @property
    def resolved_count(self) -> int:
        return len(self._resolved_phantoms)

    def is_enabled(self) -> bool:
        """Checks if phantom tracking is enabled."""
        return config.PHANTOM_TRACKING_ENABLED

    def create_phantom(
        self,
        real_trade_id: str,
        user_id: int,
        symbol: str,
        direction: str,
        entry_price: float,
        entry_time: datetime,
        initial_stop_loss: float,
        initial_take_profit: float,
        be_trigger_time: datetime,
        be_exit_price: float,
        real_pnl_pct: float,
        real_pnl_usd: Optional[float] = None,
        strategy_config_id: Optional[str] = None,
        max_hold_candles: Optional[int] = None,
    ) -> Optional[PhantomTradeData]:
        """
        Creates a new phantom for tracking after BE.

        Args:
            real_trade_id: Real trade ID
            user_id: User ID
            symbol: Trading pair
            direction: Direction (LONG/SHORT)
            entry_price: Entry price
            entry_time: Entry time
            initial_stop_loss: Initial SL (before moving to BE)
            initial_take_profit: Initial TP
            be_trigger_time: BE trigger time
            be_exit_price: Exit price at BE
            real_pnl_pct: Real PnL in %
            real_pnl_usd: Real PnL in USD
            strategy_config_id: Strategy configuration ID
            max_hold_candles: Max candles to hold (for timeout calculation)

        Returns:
            PhantomTradeData or None if tracking is disabled
        """
        if not self.is_enabled():
            return None

        # Timeout calculation
        if config.PHANTOM_TRACKING_TIMEOUT_MINUTES > 0:
            timeout_candles = config.PHANTOM_TRACKING_TIMEOUT_MINUTES
        elif max_hold_candles:
            timeout_candles = int(
                max_hold_candles * config.PHANTOM_TRACKING_TIMEOUT_MULTIPLIER
            )
        else:
            timeout_candles = config.PHANTOM_TRACKING_DEFAULT_TIMEOUT_CANDLES

        phantom = PhantomTradeData(
            real_trade_id=real_trade_id,
            user_id=user_id,
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            entry_time=entry_time,
            initial_stop_loss=initial_stop_loss,
            initial_take_profit=initial_take_profit,
            be_trigger_time=be_trigger_time,
            be_exit_price=be_exit_price,
            real_pnl_pct=real_pnl_pct,
            real_pnl_usd=real_pnl_usd,
            strategy_config_id=strategy_config_id,
            timeout_candles=timeout_candles,
            # Initialize MFE/MAE with the current price
            mfe_price=be_exit_price,
            mae_price=be_exit_price,
        )

        self._active_phantoms[real_trade_id] = phantom
        logger.info(
            f"[PhantomTracker] Created phantom for {symbol} {direction} | "
            f"Entry: {entry_price:.4f} | Initial SL: {initial_stop_loss:.4f} | "
            f"Initial TP: {initial_take_profit:.4f} | Timeout: {timeout_candles} candles"
        )

        return phantom

    def update(
        self,
        symbol: str,
        current_price: float,
        current_time: datetime,
        high_price: Optional[float] = None,
        low_price: Optional[float] = None,
    ) -> List[PhantomTradeData]:
        """
        Updates all active phantoms for the specified symbol.

        Args:
            symbol: Trading pair
            current_price: Current price (close)
            current_time: Current time
            high_price: Candle High (for accurate MFE)
            low_price: Candle Low (for accurate MAE)

        Returns:
            List of phantoms that were resolved in this update
        """
        if not self.is_enabled():
            return []

        resolved_this_update: List[PhantomTradeData] = []
        phantoms_to_remove: List[str] = []

        for trade_id, phantom in self._active_phantoms.items():
            if phantom.symbol != symbol:
                continue

            phantom.candles_tracked += 1

            # Use high/low if available, otherwise current_price
            check_high = high_price if high_price is not None else current_price
            check_low = low_price if low_price is not None else current_price

            # Update MFE/MAE
            self._update_excursions(phantom, check_high, check_low)

            # Check resolution
            resolution = self._check_resolution(
                phantom, check_high, check_low, current_price, current_time
            )

            if resolution:
                phantoms_to_remove.append(trade_id)
                self._resolved_phantoms.append(phantom)
                resolved_this_update.append(phantom)
                logger.info(
                    f"[PhantomTracker] Resolved {symbol} | Status: {phantom.status.value} | "
                    f"Phantom PnL: {phantom.phantom_pnl_pct:.2f}% | "
                    f"MFE: {phantom.mfe_after_be:.2f}% | MAE: {phantom.mae_after_be:.2f}% | "
                    f"Candles: {phantom.candles_tracked}"
                )

        # Remove resolved phantoms from active ones
        for trade_id in phantoms_to_remove:
            del self._active_phantoms[trade_id]

        return resolved_this_update

    def _update_excursions(
        self,
        phantom: PhantomTradeData,
        high_price: float,
        low_price: float,
    ) -> None:
        """Updates MFE and MAE for the phantom."""
        if phantom.direction == "LONG":
            # For long: MFE = maximum high, MAE = minimum low
            if high_price > (phantom.mfe_price or phantom.be_exit_price):
                phantom.mfe_price = high_price
                phantom.mfe_after_be = (
                    (high_price - phantom.be_exit_price) / phantom.be_exit_price
                ) * 100

            if low_price < (phantom.mae_price or phantom.be_exit_price):
                phantom.mae_price = low_price
                phantom.mae_after_be = (
                    (phantom.be_exit_price - low_price) / phantom.be_exit_price
                ) * 100
        else:
            # For short: MFE = minimum low, MAE = maximum high
            if low_price < (phantom.mfe_price or phantom.be_exit_price):
                phantom.mfe_price = low_price
                phantom.mfe_after_be = (
                    (phantom.be_exit_price - low_price) / phantom.be_exit_price
                ) * 100

            if high_price > (phantom.mae_price or phantom.be_exit_price):
                phantom.mae_price = high_price
                phantom.mae_after_be = (
                    (high_price - phantom.be_exit_price) / phantom.be_exit_price
                ) * 100

    def _check_resolution(
        self,
        phantom: PhantomTradeData,
        high_price: float,
        low_price: float,
        close_price: float,
        current_time: datetime,
    ) -> bool:
        """
        Checks if the phantom has reached TP, SL, or timeout.

        Returns:
            True if the phantom is resolved, False if tracking continues
        """
        tp_hit = False
        sl_hit = False

        if phantom.direction == "LONG":
            # For long: TP higher, SL lower
            tp_hit = high_price >= phantom.initial_take_profit
            sl_hit = low_price <= phantom.initial_stop_loss
        else:
            # For short: TP lower, SL higher
            tp_hit = low_price <= phantom.initial_take_profit
            sl_hit = high_price >= phantom.initial_stop_loss

        # Determine what happened first (if both are on the same candle)
        if tp_hit and sl_hit:
            # If both are on the same candle, we assume SL triggered first (conservative)
            sl_hit = True
            tp_hit = False

        if tp_hit:
            phantom.status = PhantomStatus.TP_HIT
            phantom.phantom_exit_time = current_time
            phantom.phantom_exit_price = phantom.initial_take_profit
            self._calculate_phantom_pnl(phantom)
            return True

        if sl_hit:
            phantom.status = PhantomStatus.SL_HIT
            phantom.phantom_exit_time = current_time
            phantom.phantom_exit_price = phantom.initial_stop_loss
            self._calculate_phantom_pnl(phantom)
            return True

        # Check timeout
        if phantom.candles_tracked >= phantom.timeout_candles:
            phantom.status = PhantomStatus.TIMEOUT
            phantom.phantom_exit_time = current_time
            phantom.phantom_exit_price = close_price
            self._calculate_phantom_pnl(phantom)
            return True

        return False

    def _calculate_phantom_pnl(self, phantom: PhantomTradeData) -> None:
        """Calculates potential PnL for the phantom."""
        if phantom.phantom_exit_price is None:
            return

        if phantom.direction == "LONG":
            phantom.phantom_pnl_pct = (
                (phantom.phantom_exit_price - phantom.entry_price) / phantom.entry_price
            ) * 100
        else:
            phantom.phantom_pnl_pct = (
                (phantom.entry_price - phantom.phantom_exit_price) / phantom.entry_price
            ) * 100

    def get_active_phantoms(
        self, symbol: Optional[str] = None
    ) -> List[PhantomTradeData]:
        """Returns active phantoms, optionally filtering by symbol."""
        if symbol:
            return [p for p in self._active_phantoms.values() if p.symbol == symbol]
        return list(self._active_phantoms.values())

    def get_resolved_phantoms(self) -> List[PhantomTradeData]:
        """Returns all resolved phantoms."""
        return self._resolved_phantoms.copy()

    def clear_resolved(self) -> List[PhantomTradeData]:
        """Clears and returns resolved phantoms (for saving to the DB)."""
        resolved = self._resolved_phantoms.copy()
        self._resolved_phantoms.clear()
        return resolved

    def to_db_dict(self, phantom: PhantomTradeData) -> Dict[str, Any]:
        """Converts PhantomTradeData to a dictionary for saving to the DB."""
        return {
            "user_id": phantom.user_id,
            "real_trade_id": phantom.real_trade_id,
            "symbol": phantom.symbol,
            "direction": phantom.direction,
            "strategy_config_id": phantom.strategy_config_id,
            "entry_price": phantom.entry_price,
            "entry_time": phantom.entry_time,
            "initial_stop_loss": phantom.initial_stop_loss,
            "initial_take_profit": phantom.initial_take_profit,
            "be_trigger_time": phantom.be_trigger_time,
            "be_exit_price": phantom.be_exit_price,
            "real_pnl_pct": phantom.real_pnl_pct,
            "real_pnl_usd": phantom.real_pnl_usd,
            "phantom_status": phantom.status.value,
            "phantom_exit_time": phantom.phantom_exit_time,
            "phantom_exit_price": phantom.phantom_exit_price,
            "phantom_pnl_pct": phantom.phantom_pnl_pct,
            "phantom_pnl_usd": phantom.phantom_pnl_usd,
            "mfe_after_be": phantom.mfe_after_be,
            "mae_after_be": phantom.mae_after_be,
            "mfe_price": phantom.mfe_price,
            "mae_price": phantom.mae_price,
            "candles_to_resolution": phantom.candles_tracked,
            "timeout_candles": phantom.timeout_candles,
        }


# Singleton for use in the controller
_phantom_tracker_instance: Optional[PhantomTracker] = None


def get_phantom_tracker() -> PhantomTracker:
    """Returns the global PhantomTracker instance."""
    global _phantom_tracker_instance
    if _phantom_tracker_instance is None:
        _phantom_tracker_instance = PhantomTracker()
    return _phantom_tracker_instance
