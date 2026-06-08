# bot_module/execution_simulator.py
import logging
from typing import Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass

# Attempting import for integration. If it fails, a local fallback is used.
try:
    from .strategy import SignalDirection
except ImportError:

    class SignalDirection(Enum):
        LONG = "LONG"
        SHORT = "SHORT"


logger = logging.getLogger("bot_module.execution_simulator")


class FillType(str, Enum):
    """Order execution simulation type."""

    L2_MARKET_IMPACT = "L2MarketImpact"
    AGGREGATED_MARKET_IMPACT = "AggregatedMarketImpact"  # New type for bookDepth
    KLINE_SLIPPAGE = "KlineSlippage"
    NO_FILL = "NoFill"
    FORCED_EOD = "ForcedEOD"


# UPDATED DATACLASS
@dataclass
class OrderExecutionResult:
    """Contains the result of the order execution simulation."""

    avg_fill_price: Optional[float]
    filled_quantity: float
    actual_commission_paid: float = 0.0
    slippage_usd: float = 0.0
    levels_consumed: int = 0
    ideal_entry_price: Optional[float] = None
    fill_type: FillType = FillType.NO_FILL  # Use Enum
    message: Optional[str] = None


def simulate_market_order_execution(
    order_quantity: float,
    direction: SignalDirection,
    market_data_for_sim: Optional[Dict[str, Any]],
    ideal_entry_price: Optional[float] = None,
    commission_pct: float = 0.0,
    kline_close_for_fallback: Optional[float] = None,
    simple_slippage_pct: Optional[float] = None,
) -> OrderExecutionResult:
    """
    Simulates market order execution based on available data.
    FIXED VERSION: Correctly calculates slippage for ALL modes.
    """
    if order_quantity <= 1e-9:
        return OrderExecutionResult(
            avg_fill_price=None, filled_quantity=0.0, message="Order quantity is zero."
        )

    orderbook_snapshot = (
        market_data_for_sim.get("depth_trading") if market_data_for_sim else None
    )
    aggregated_snapshot = (
        market_data_for_sim.get("depth_analysis") if market_data_for_sim else None
    )

    # REFERENCE PRICE FOR SLIPPAGE CALCULATION
    # Priority given to ideal_entry_price.
    reference_price = (
        ideal_entry_price if ideal_entry_price is not None else kline_close_for_fallback
    )

    # Priority 1: Simulation by L2 order book
    if (
        orderbook_snapshot
        and isinstance(orderbook_snapshot, dict)
        and (
            orderbook_snapshot.get(
                "asks" if direction == SignalDirection.LONG else "bids"
            )
        )
    ):
        book_side = (
            orderbook_snapshot["asks"]
            if direction == SignalDirection.LONG
            else orderbook_snapshot["bids"]
        )
        total_filled_quantity, total_cost, levels_consumed = 0.0, 0.0, 0
        for price_str, size_str in book_side:
            try:
                price, level_quantity = float(price_str), float(size_str)
            except (ValueError, TypeError):
                continue
            quantity_needed = order_quantity - total_filled_quantity
            if quantity_needed <= 1e-9:
                break
            fill_this_level = min(quantity_needed, level_quantity)
            total_filled_quantity += fill_this_level
            total_cost += fill_this_level * price
            levels_consumed += 1
        if total_filled_quantity > 1e-9:
            avg_fill_price = total_cost / total_filled_quantity
            slippage_usd = (
                abs(avg_fill_price - reference_price) * total_filled_quantity
                if reference_price
                else 0.0
            )
            return OrderExecutionResult(
                avg_fill_price=avg_fill_price,
                filled_quantity=total_filled_quantity,
                actual_commission_paid=avg_fill_price
                * total_filled_quantity
                * commission_pct,
                slippage_usd=slippage_usd,
                levels_consumed=levels_consumed,
                ideal_entry_price=reference_price,
                fill_type=FillType.L2_MARKET_IMPACT,
                message=f"Filled using L2 depth. Levels consumed: {levels_consumed}",
            )

    # Priority 2: Simulation by aggregated order book
    if (
        aggregated_snapshot
        and isinstance(aggregated_snapshot, dict)
        and (
            aggregated_snapshot.get(
                "asks" if direction == SignalDirection.LONG else "bids"
            )
        )
    ):
        book_side = aggregated_snapshot[
            "asks" if direction == SignalDirection.LONG else "bids"
        ]
        total_filled_quantity, total_cost, levels_consumed = 0.0, 0.0, 0
        for bucket in book_side:
            bucket_price, bucket_quantity = bucket.get("price"), bucket.get("quantity")
            if (
                not all([bucket_price, bucket_quantity])
                or bucket_price <= 0
                or bucket_quantity <= 0
            ):
                continue
            quantity_needed = order_quantity - total_filled_quantity
            if quantity_needed <= 1e-9:
                break
            fill_this_bucket = min(quantity_needed, bucket_quantity)
            total_filled_quantity += fill_this_bucket
            total_cost += fill_this_bucket * bucket_price
            levels_consumed += 1
        if total_filled_quantity > 1e-9:
            avg_fill_price = total_cost / total_filled_quantity
            slippage_usd = (
                abs(avg_fill_price - reference_price) * total_filled_quantity
                if reference_price
                else 0.0
            )
            return OrderExecutionResult(
                avg_fill_price=avg_fill_price,
                filled_quantity=total_filled_quantity,
                actual_commission_paid=avg_fill_price
                * total_filled_quantity
                * commission_pct,
                slippage_usd=slippage_usd,
                levels_consumed=levels_consumed,
                ideal_entry_price=reference_price,
                fill_type=FillType.AGGREGATED_MARKET_IMPACT,
                message=f"Filled using aggregated depth. Buckets consumed: {levels_consumed}",
            )

    # Priority 3: Fallback
    if reference_price is None:
        return OrderExecutionResult(
            avg_fill_price=None, filled_quantity=0.0, message="No data for simulation."
        )

    logger.warning(
        f"No L2 or Aggregated data. Falling back to kline-based simulation with reference price: {reference_price}."
    )

    # USE reference_price AS THE BASE FOR ALL CALCULATIONS
    avg_fill_price_fallback = reference_price
    if simple_slippage_pct is not None and simple_slippage_pct > 0:
        slip_multiplier = (
            (1 + simple_slippage_pct)
            if direction == SignalDirection.LONG
            else (1 - simple_slippage_pct)
        )
        avg_fill_price_fallback = reference_price * slip_multiplier

    slippage_usd_fallback = (
        abs(avg_fill_price_fallback - reference_price) * order_quantity
    )

    return OrderExecutionResult(
        avg_fill_price=avg_fill_price_fallback,
        filled_quantity=order_quantity,
        actual_commission_paid=avg_fill_price_fallback
        * order_quantity
        * commission_pct,
        slippage_usd=slippage_usd_fallback,
        ideal_entry_price=reference_price,
        fill_type=FillType.KLINE_SLIPPAGE,
        message="Fallback to kline-based simulation.",
    )
