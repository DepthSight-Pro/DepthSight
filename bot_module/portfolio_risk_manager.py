import logging
from typing import Dict, Any, Optional
from decimal import Decimal
from datetime import datetime

# Assuming StrategySignal and SignalDirection are in strategy.py
from .strategy import StrategySignal, SignalDirection
from .portfolio_datatypes import BacktestPositionState

logger = logging.getLogger(__name__)


class PortfolioRiskManager:
    def __init__(self, global_risk_limits: Dict[str, Any]):
        """
        Initializes the PortfolioRiskManager.

        Args:
            global_risk_limits (Dict[str, Any]): Global risk parameters.
                Example: {
                    "max_total_exposure_pct": 0.5,  # Max 50% of balance as total position values
                    "max_concurrent_positions": 10,
                    "risk_pct_per_trade": 0.01      # Risk 1% of balance per trade
                }
        """
        self.global_risk_limits = global_risk_limits
        logger.info(
            f"PortfolioRiskManager initialized with limits: {global_risk_limits}"
        )

    @staticmethod
    def _adjust_quantity_to_exchange_rules(
        quantity: float,
        symbol: str,  # Added for logging
        exchange_info: Dict[str, Any],
        entry_price: float,
    ) -> Optional[float]:
        try:
            min_qty = (
                float(exchange_info.get("min_qty"))
                if exchange_info.get("min_qty") is not None
                else None
            )
            max_qty = (
                float(exchange_info.get("max_qty"))
                if exchange_info.get("max_qty") is not None
                else None
            )
            step_size = (
                float(exchange_info.get("step_size"))
                if exchange_info.get("step_size") is not None
                else None
            )
            min_notional = (
                float(exchange_info.get("min_notional"))
                if exchange_info.get("min_notional") is not None
                else None
            )
        except (ValueError, TypeError) as e:
            logger.error(
                f"[{symbol}] Error converting exchange_info values to float: {e}. Info: {exchange_info}"
            )
            return None

        if step_size is None or step_size <= 0:
            logger.warning(
                f"[{symbol}] Invalid or missing 'step_size' in exchange_info: {step_size}. Cannot adjust quantity."
            )
            return None

        step_size_dec = Decimal(str(step_size))

        # Initial adjustment for step_size
        quantity_dec = Decimal(str(quantity))
        adjusted_quantity_after_step = float(
            (quantity_dec // step_size_dec) * step_size_dec
        )

        # Store if quantity became zero *only due to step_size* from a non-zero original
        is_zero_after_step_from_nonzero_orig = (
            adjusted_quantity_after_step < 1e-9 and quantity > 1e-9
        )

        current_adjusted_quantity = adjusted_quantity_after_step

        # Check min_notional requirement
        # This check should happen regardless of whether current_adjusted_quantity is zero,
        # if the original quantity was non-zero and min_notional is a concern.
        if min_notional is not None and entry_price > 0:
            # Condition: EITHER current_adjusted_quantity's notional is too low,
            # OR quantity became zero due to step_size (from non-zero) and we need to see if min_notional can be met.
            if (
                current_adjusted_quantity > 1e-9
                and (current_adjusted_quantity * entry_price) < min_notional
            ) or (
                is_zero_after_step_from_nonzero_orig
                and quantity * entry_price < min_notional
                and min_notional > 0
            ):  # Added check for original quantity notional too
                original_qty_for_log = current_adjusted_quantity  # Save for logging before potential override
                logger.info(
                    f"[{symbol}] Initial adjusted qty {original_qty_for_log:.8f} (notional ${original_qty_for_log * entry_price:.2f}) "
                    f"OR original qty {quantity:.8f} (notional ${quantity * entry_price:.2f}) "
                    f"requires check against min_notional ${min_notional:.2f}."
                )

                required_qty_for_min_notional_raw = Decimal(
                    str(min_notional)
                ) / Decimal(str(entry_price))
                # Round UP to the nearest step_size for min_notional
                required_qty_for_min_notional_stepped = float(
                    (
                        (
                            required_qty_for_min_notional_raw
                            + step_size_dec
                            - Decimal("1e-10")
                        )
                        // step_size_dec
                    )
                    * step_size_dec
                )

                final_candidate_qty = required_qty_for_min_notional_stepped

                # Ensure it also meets min_qty
                if min_qty is not None and final_candidate_qty < min_qty:
                    logger.info(
                        f"[{symbol}] Qty for min_notional ({final_candidate_qty:.8f}) is < min_qty ({min_qty:.8f}). Adjusting to min_qty."
                    )
                    final_candidate_qty = min_qty
                    # Re-check step for min_qty if it was changed
                    final_candidate_qty = float(
                        (Decimal(str(final_candidate_qty)) // step_size_dec)
                        * step_size_dec
                    )

                # Now, check if this final_candidate_qty (adjusted for min_notional AND min_qty) is itself valid
                if (final_candidate_qty * entry_price) < min_notional:
                    logger.warning(
                        f"[{symbol}] Cannot meet min_notional. Candidate qty {final_candidate_qty:.8f} (notional ${final_candidate_qty * entry_price:.2f}) is still below min_notional ${min_notional:.2f}."
                    )
                    return None

                if max_qty is not None and final_candidate_qty > max_qty:
                    logger.warning(
                        f"[{symbol}] Candidate qty {final_candidate_qty:.8f} to meet min_notional exceeds max_qty {max_qty:.8f}."
                    )
                    return None

                # If all checks pass for this new candidate quantity
                logger.info(
                    f"[{symbol}] Quantity adjusted from initial {quantity:.8f} (stepped: {original_qty_for_log:.8f}) to {final_candidate_qty:.8f} to meet min_notional and other constraints."
                )
                current_adjusted_quantity = final_candidate_qty

            # If current_adjusted_quantity was already fine for min_notional, no change here.
            # If it was zero from a zero original quantity, it stays zero and will be caught by later checks.

        # Final checks on current_adjusted_quantity (which might have been modified by min_notional logic)
        if current_adjusted_quantity < 1e-9:  # Effectively zero
            logger.info(
                f"[{symbol}] Quantity {quantity:.8f} resulted in effective zero ({current_adjusted_quantity:.8f}) after all adjustments (step, min_notional)."
            )
            return None

        if min_qty is not None and current_adjusted_quantity < min_qty:
            # This can happen if min_notional was not applicable or didn't push qty high enough
            logger.info(
                f"[{symbol}] Final adjusted quantity {current_adjusted_quantity:.8f} is less than min_qty {min_qty:.8f}."
            )
            return None

        if max_qty is not None and current_adjusted_quantity > max_qty:
            logger.info(
                f"[{symbol}] Final adjusted quantity {current_adjusted_quantity:.8f} exceeds max_qty {max_qty:.8f}. Capping to max_qty."
            )
            current_adjusted_quantity = max_qty
            current_adjusted_quantity = float(
                (Decimal(str(current_adjusted_quantity)) // step_size_dec)
                * step_size_dec
            )  # Re-apply step
            # Re-check min_qty after capping to max_qty, as max_qty might be below min_qty (unlikely but possible)
            if min_qty is not None and current_adjusted_quantity < min_qty:
                logger.warning(
                    f"[{symbol}] Quantity after capping to max_qty ({current_adjusted_quantity:.8f}) is now below min_qty ({min_qty:.8f}). This is problematic."
                )
                return None

        if current_adjusted_quantity <= 1e-9:  # Final final check
            logger.info(
                f"[{symbol}] Quantity became zero after all final checks."
            )  # Should be redundant if previous zero check is robust
            return None

        return current_adjusted_quantity

    def calculate_position_size(
        self,
        signal: StrategySignal,
        current_balance: float,
        entry_price: float,
        stop_loss_price: float,
        exchange_info: Dict[
            str, Any
        ],  # e.g. {"min_qty": 0.001, "step_size": 0.001, "min_notional": 10.0}
    ) -> Optional[float]:
        """
        Calculates position size based on risk percentage and stop-loss distance.
        Adjusts for exchange rules.
        """
        risk_pct_per_trade = self.global_risk_limits.get("risk_pct_per_trade")
        if risk_pct_per_trade is None or risk_pct_per_trade <= 0:
            logger.error(
                f"[{signal.symbol}] Invalid 'risk_pct_per_trade': {risk_pct_per_trade}. Cannot calculate position size."
            )
            return None

        if entry_price <= 0 or stop_loss_price <= 0:
            logger.warning(
                f"[{signal.symbol}] Entry price or SL price is zero/negative. Entry: {entry_price}, SL: {stop_loss_price}"
            )
            return None

        sl_distance_abs = abs(entry_price - stop_loss_price)
        if sl_distance_abs < 1e-9:  # Stop loss is too close to entry or at entry
            logger.warning(
                f"[{signal.symbol}] Stop-loss is too close to entry price or at entry. SL Distance: {sl_distance_abs:.8f}"
            )
            return None

        risk_amount_per_trade_usd = current_balance * risk_pct_per_trade

        # Quantity in base asset terms
        calculated_quantity = risk_amount_per_trade_usd / sl_distance_abs

        logger.info(
            f"[{signal.symbol}] Initial size calc: Balance ${current_balance:,.2f}, Risk Pct {risk_pct_per_trade * 100:.2f}%, "
            f"Risk Amt ${risk_amount_per_trade_usd:,.2f}. Entry {entry_price:.4f}, SL {stop_loss_price:.4f}. "
            f"SL Dist Abs ${sl_distance_abs:.4f}. Initial Qty: {calculated_quantity:.8f}"
        )

        if calculated_quantity <= 0:
            logger.warning(
                f"[{signal.symbol}] Calculated quantity is zero or negative: {calculated_quantity:.8f}"
            )
            return None

        # Adjust for exchange rules
        adjusted_quantity = self._adjust_quantity_to_exchange_rules(
            quantity=calculated_quantity,
            symbol=signal.symbol,
            exchange_info=exchange_info,
            entry_price=entry_price,
        )

        if adjusted_quantity is None:
            logger.warning(
                f"[{signal.symbol}] Failed to adjust quantity {calculated_quantity:.8f} to exchange rules."
            )
            return None

        logger.info(
            f"[{signal.symbol}] Calculated and adjusted position size: {adjusted_quantity:.8f}"
        )
        return adjusted_quantity

    def validate_signal(
        self,
        signal: StrategySignal,
        calculated_quantity: float,
        entry_price: float,
        current_balance: float,
        active_positions: Dict[str, BacktestPositionState],
    ) -> bool:
        """
        Validates a signal against portfolio-level risk limits.
        """
        # 1. Max Concurrent Positions Check
        max_concurrent = self.global_risk_limits.get("max_concurrent_positions")
        if max_concurrent is not None and len(active_positions) >= max_concurrent:
            logger.info(
                f"[{signal.symbol}] Signal rejected: Max concurrent positions ({max_concurrent}) reached. "
                f"Currently {len(active_positions)} active."
            )
            return False

        # 2. Max Total Exposure Check
        max_exposure_pct = self.global_risk_limits.get("max_total_exposure_pct")
        if max_exposure_pct is not None and max_exposure_pct > 0:
            current_total_notional = 0.0
            for pos_id, position_state in active_positions.items():
                # Use initial_value_usd if available and reliable, otherwise recalculate
                current_total_notional += position_state.initial_value_usd
                # Alternatives: position_state.entry_price * position_state.quantity
                # or query current mark price * quantity (more complex for backtest)

            new_pos_notional = calculated_quantity * entry_price

            if current_balance <= 0:  # Avoid division by zero if balance wiped out
                logger.warning(
                    f"[{signal.symbol}] Current balance is zero or negative. Cannot calculate exposure."
                )
                return False

            potential_total_exposure_pct = (
                current_total_notional + new_pos_notional
            ) / current_balance

            logger.debug(
                f"[{signal.symbol}] Exposure check: Current notional ${current_total_notional:,.2f}, "
                f"New pos notional ${new_pos_notional:,.2f}, Balance ${current_balance:,.2f}. "
                f"Potential total exposure: {potential_total_exposure_pct * 100:.2f}% "
                f"(Limit: {max_exposure_pct * 100:.2f}%)"
            )

            if potential_total_exposure_pct > max_exposure_pct:
                logger.info(
                    f"[{signal.symbol}] Signal rejected: Potential total exposure {potential_total_exposure_pct * 100:.2f}% "
                    f"exceeds limit {max_exposure_pct * 100:.2f}%."
                )
                return False

        # Add other validations if needed (e.g., per-symbol exposure limits, etc.)

        logger.info(
            f"[{signal.symbol}] Signal validated successfully against portfolio risk limits."
        )
        return True


if __name__ == "__main__":
    # Example Usage
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    dummy_global_limits = {
        "max_total_exposure_pct": 0.5,
        "max_concurrent_positions": 3,
        "risk_pct_per_trade": 0.01,
    }
    risk_manager = PortfolioRiskManager(dummy_global_limits)

    # Example for calculate_position_size
    dummy_signal = StrategySignal(
        strategy_name="TestStrat",
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        stop_loss=29000.0,  # Will be overridden by arg
        take_profit=31000.0,
        trigger_price=30000.0,  # Will be overridden by arg
    )
    dummy_exchange_info_btc = {
        "min_qty": 0.0001,
        "max_qty": 100.0,
        "step_size": 0.0001,
        "min_notional": 10.0,
    }

    balance1 = 100000.0
    entry1 = 30000.0
    sl1 = 29700.0  # 1% SL distance (300 USD)

    print(f"\n--- Testing calculate_position_size for {dummy_signal.symbol} ---")
    qty1 = risk_manager.calculate_position_size(
        dummy_signal, balance1, entry1, sl1, dummy_exchange_info_btc
    )
    print(
        f"Calculated Qty for {dummy_signal.symbol} (1% risk, 1% SL dist): {qty1}"
    )  # Expected: (100000*0.01) / 300 = 3.3333 -> adjusted

    sl2 = 29970.0  # 0.1% SL distance (30 USD)
    qty2 = risk_manager.calculate_position_size(
        dummy_signal, balance1, entry1, sl2, dummy_exchange_info_btc
    )
    print(
        f"Calculated Qty for {dummy_signal.symbol} (1% risk, 0.1% SL dist): {qty2}"
    )  # Expected: (100000*0.01) / 30 = 33.3333 -> adjusted

    # Test min_notional adjustment
    sl3 = 20000.0  # Large SL distance
    balance2 = 100.0  # Small balance
    risk_pct_small_bal = 0.01
    # risk_amount = 1 USD. risk_amount / (30000-20000) = 1/10000 = 0.0001. Notional = 0.0001*30000 = 3 USD. < min_notional
    print(f"\n--- Testing min_notional adjustment for {dummy_signal.symbol} ---")
    # Update risk_pct in global_limits for this specific test, or pass it if method signature changes
    original_risk_pct = risk_manager.global_risk_limits["risk_pct_per_trade"]
    risk_manager.global_risk_limits["risk_pct_per_trade"] = (
        risk_pct_small_bal  # Temporarily change for test
    )
    qty3 = risk_manager.calculate_position_size(
        dummy_signal, balance2, entry1, sl3, dummy_exchange_info_btc
    )
    print(
        f"Calculated Qty for {dummy_signal.symbol} (small balance ${balance2}, large SL, to hit min_notional): {qty3}"
    )
    # Expected qty to be ~ (10 / 30000) = 0.000333 -> 0.0004 after step_size
    if qty3:
        print(f"Notional for qty3: {qty3 * entry1}")
    risk_manager.global_risk_limits["risk_pct_per_trade"] = original_risk_pct  # Restore

    # Example for validate_signal
    print("\n--- Testing validate_signal ---")
    active_positions_map: Dict[str, BacktestPositionState] = {}

    # Scenario 1: No active positions, should pass
    print("Scenario 1: No active positions")
    valid1 = risk_manager.validate_signal(
        dummy_signal, qty1 if qty1 else 0.001, entry1, balance1, active_positions_map
    )
    print(f"Validation 1 result: {valid1}")  # True

    # Scenario 2: Add one position
    if valid1 and qty1:
        pos1_id = "pos_test_1"
        active_positions_map[pos1_id] = BacktestPositionState(
            position_id=pos1_id,
            contract_id="btc_test",
            symbol="BTCUSDT",
            direction=SignalDirection.LONG,
            entry_price=entry1,
            quantity=qty1,
            entry_time=datetime.now(),
            initial_value_usd=entry1 * qty1,
        )
        print(
            f"\nScenario 2: One active position (BTCUSDT, value ${entry1 * qty1:.2f})"
        )
        qty_eth = 0.1  # Assume this is calculated for ETHUSDT
        entry_eth = 2000.0
        sl_eth = 1980.0  # 1% SL
        dummy_signal_eth = StrategySignal(
            "TestStrat",
            "ETHUSDT",
            SignalDirection.LONG,
            sl_eth,
            2200.0,
            trigger_price=entry_eth,
        )
        dummy_exchange_info_eth = {
            "min_qty": 0.001,
            "step_size": 0.001,
            "min_notional": 10.0,
        }

        # Calculate ETH quantity based on remaining risk capacity if we want to be precise for exposure
        # For simplicity, assume qty_eth is pre-calculated based on its own risk %

        valid2 = risk_manager.validate_signal(
            dummy_signal_eth, qty_eth, entry_eth, balance1, active_positions_map
        )
        print(f"Validation 2 result (ETHUSDT): {valid2}")  # True, if exposure is fine

    # Scenario 3: Max positions reached
    if valid2:
        active_positions_map["pos_test_2"] = BacktestPositionState(
            "pos_test_2",
            "eth_test",
            "ETHUSDT",
            SignalDirection.LONG,
            entry_eth,
            qty_eth,
            datetime.now(),
            initial_value_usd=entry_eth * qty_eth,
        )
        # Add another dummy position to reach max_concurrent_positions = 3
        active_positions_map["pos_test_3"] = BacktestPositionState(
            "pos_test_3",
            "link_test",
            "LINKUSDT",
            SignalDirection.LONG,
            15.0,
            100.0,
            datetime.now(),
            initial_value_usd=15.0 * 100.0,
        )
        print(
            f"\nScenario 3: Max ({risk_manager.global_risk_limits['max_concurrent_positions']}) active positions"
        )
        qty_xrp = 1000.0
        entry_xrp = 0.5
        sl_xrp = 0.495  # 1% SL
        dummy_signal_xrp = StrategySignal(
            "TestStrat",
            "XRPUSDT",
            SignalDirection.LONG,
            sl_xrp,
            0.55,
            trigger_price=entry_xrp,
        )
        valid3 = risk_manager.validate_signal(
            dummy_signal_xrp, qty_xrp, entry_xrp, balance1, active_positions_map
        )
        print(f"Validation 3 result (XRPUSDT): {valid3}")  # False

    # Scenario 4: Max exposure reached
    print("\nScenario 4: Max exposure test")
    active_positions_map_exp = {}
    # Expose 30% with one large BTC trade
    large_btc_qty = (
        balance1 * 0.3
    ) / entry1  # Approx 1 BTC for 30k entry, 100k balance
    large_btc_qty_adj = risk_manager._adjust_quantity_to_exchange_rules(
        large_btc_qty, "BTCUSDT", dummy_exchange_info_btc, entry1
    )

    if large_btc_qty_adj:
        active_positions_map_exp["pos_large_btc"] = BacktestPositionState(
            "pos_large_btc",
            "btc_large_test",
            "BTCUSDT",
            SignalDirection.LONG,
            entry_price=entry1,
            quantity=large_btc_qty_adj,
            entry_time=datetime.now(),
            initial_value_usd=entry1 * large_btc_qty_adj,
        )
        current_notional_exp = entry1 * large_btc_qty_adj
        print(
            f"One active BTC position, notional ${current_notional_exp:,.2f} ({current_notional_exp / balance1 * 100:.2f}% of balance)"
        )

        # Try to add another 30% exposure with ETH
        qty_eth_large = (balance1 * 0.3) / entry_eth  # Approx 15 ETH for 2k entry
        qty_eth_large_adj = risk_manager._adjust_quantity_to_exchange_rules(
            qty_eth_large, "ETHUSDT", dummy_exchange_info_eth, entry_eth
        )

        if qty_eth_large_adj:
            print(
                f"Attempting to add ETH position, notional ${qty_eth_large_adj * entry_eth:,.2f} ({(qty_eth_large_adj * entry_eth) / balance1 * 100:.2f}% of balance)"
            )
            valid4 = risk_manager.validate_signal(
                dummy_signal_eth,
                qty_eth_large_adj,
                entry_eth,
                balance1,
                active_positions_map_exp,
            )
            print(
                f"Validation 4 result (ETHUSDT, large): {valid4}"
            )  # False, because 30% + 30% > 50% limit
        else:
            print("Could not adjust large ETH qty for test.")
    else:
        print("Could not adjust large BTC qty for exposure test.")

    print("\n--- Testing _adjust_quantity_to_exchange_rules directly ---")
    info = {"min_qty": 0.01, "step_size": 0.01, "min_notional": 10.0}
    print(
        f"Adjust 0.123, price 100, info {info} -> {PortfolioRiskManager._adjust_quantity_to_exchange_rules(0.123, 'TEST', info, 100.0)}"
    )  # -> 0.12
    print(
        f"Adjust 0.003, price 100, info {info} -> {PortfolioRiskManager._adjust_quantity_to_exchange_rules(0.003, 'TEST', info, 100.0)}"
    )  # -> None (min_qty)
    print(
        f"Adjust 0.05, price 100, info {info} -> {PortfolioRiskManager._adjust_quantity_to_exchange_rules(0.05, 'TEST', info, 100.0)}"
    )  # -> None (min_notional is 10, 0.05*100=5)
    # Should adjust to 0.1
    print(
        f"Adjust 0.09, price 100, info {info} -> {PortfolioRiskManager._adjust_quantity_to_exchange_rules(0.09, 'TEST', info, 100.0)}"
    )  # -> 0.10 to meet min_notional

    info_no_min_notional = {"min_qty": 0.001, "step_size": 0.001}
    print(
        f"Adjust 0.0005, price 100, info {info_no_min_notional} -> {PortfolioRiskManager._adjust_quantity_to_exchange_rules(0.0005, 'TEST', info_no_min_notional, 100.0)}"
    )  # -> None (step adjustment makes it 0)
    print(
        f"Adjust 0.0015, price 100, info {info_no_min_notional} -> {PortfolioRiskManager._adjust_quantity_to_exchange_rules(0.0015, 'TEST', info_no_min_notional, 100.0)}"
    )  # -> 0.001

    info_eth = {
        "symbol": "ETHUSDT",
        "min_qty": 0.001,
        "max_qty": 10000.0,
        "step_size": 0.001,
        "min_notional": 5.0,
    }  # min_notional is 5 USD for ETH
    print(
        f"Adjust for ETH: 0.00234, price 1800, info {info_eth} -> {PortfolioRiskManager._adjust_quantity_to_exchange_rules(0.00234, 'ETHUSDT', info_eth, 1800.0)}"
    )  # -> 0.002 (notional 3.6 < 5). Should adjust to meet min_notional (5/1800 = 0.00277 -> 0.003)
    # Expected: 0.003. Current logic will return None because initial calc (0.002 * 1800 = 3.6) < 5, then it tries to calc required for min_notional
    # (5/1800 = 0.00277), rounds up to step (0.003). 0.003 * 1800 = 5.4 >= 5. So it should be 0.003.
    # My _adjust_quantity... has a bug in min_notional handling when initial adjusted quantity is too small. Fixed.
