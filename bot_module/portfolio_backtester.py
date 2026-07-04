# bot_module/portfolio_backtester.py

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import numpy as np  # For NaN
import asyncio
import math  # For math.isinf

from .data_loader import download_klines
from .depthsight_backtester import L2HistoricalDataReader
from .execution_simulator import (
    simulate_market_order_execution,
    OrderExecutionResult,
    FillType,
)
from .strategy import (
    create_strategy_instance,
    BaseStrategy,
    StrategySignal,
    OrderMode,
    SignalDirection,
)
from .utils import calculate_atr
from . import config as global_bot_config
from .portfolio_risk_manager import PortfolioRiskManager
from .portfolio_datatypes import BacktestPositionState

logger = logging.getLogger(__name__)


class PortfolioBacktester:
    def __init__(
        self,
        initial_balance: float,
        start_date: datetime,
        end_date: datetime,
        contracts: List[Dict[str, Any]],
        global_risk_limits: Dict[str, Any],
        l2_reader: Optional[L2HistoricalDataReader] = None,
        l2_storage_path: Optional[str] = None,
    ):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.start_date = start_date
        self.end_date = end_date
        self.contracts = contracts
        self.global_risk_limits = global_risk_limits

        self.commission_pct = global_risk_limits.get("commission_pct", 0.00075)
        self.simple_slippage_pct = global_risk_limits.get(
            "simple_slippage_pct", 0.0005
        )  # For kline fallback
        self.risk_manager = PortfolioRiskManager(self.global_risk_limits)

        self.market_data: Dict[Tuple[str, str], pd.DataFrame] = {}
        self.strategy_instances: Dict[str, BaseStrategy] = {}
        self.contract_details: Dict[str, Dict[str, Any]] = {}
        self.exchange_info_map: Dict[str, Dict[str, Any]] = {}

        self.active_positions: Dict[str, BacktestPositionState] = {}
        self.pending_orders: Dict[str, Dict[str, Any]] = {}
        self.trade_log: List[Dict[str, Any]] = []

        self.equity_curve: List[Tuple[datetime, float]] = []
        self.unified_timeline: List[datetime] = []
        self.snapshots_for_ts: Dict[datetime, Dict[str, Optional[Dict[str, Any]]]] = {}

        self.next_position_id = 1
        self.next_order_id = 1

        self.l2_reader: Optional[L2HistoricalDataReader] = l2_reader
        if self.l2_reader is None and l2_storage_path:
            logger.info(
                f"No L2Reader provided for PortfolioBacktester, but l2_storage_path '{l2_storage_path}' is set. Initializing L2HistoricalDataReader."
            )
            self.l2_reader = L2HistoricalDataReader(storage_path=l2_storage_path)

        self.l2_market_impact_enabled: bool = self.l2_reader is not None
        if self.l2_market_impact_enabled:
            l2_source = (
                "provided instance"
                if l2_reader and self.l2_reader is l2_reader
                else f"path '{l2_storage_path}'"
            )
            logger.info(
                f"PortfolioBacktester: L2 Market Impact simulation is ACTIVE. L2Reader source: {l2_source}"
            )
        else:
            logger.info(
                "PortfolioBacktester: L2 Market Impact simulation is INACTIVE (no L2Reader or path)."
            )

        logger.info("PortfolioBacktester initializing...")
        logger.info(
            f"Initial Balance: ${initial_balance:,.2f}, Commission: {self.commission_pct * 100:.3f}%"
        )
        logger.info(f"Backtest Period: {start_date} to {end_date}")
        logger.info(f"Number of Contracts: {len(self.contracts)}")
        logger.info(f"Global Risk Limits: {global_risk_limits}")

    def _get_next_position_id(self) -> str:
        pos_id = f"pos_{self.next_position_id}"
        self.next_position_id += 1
        return pos_id

    def _get_next_order_id(self) -> str:
        order_id = f"ord_{self.next_order_id}"
        self.next_order_id += 1
        return order_id

    async def _load_data(self) -> None:
        logger.info("Starting data loading process...")
        loaded_count = 0
        tasks = []
        for contract_config in self.contracts:
            tasks.append(self._load_single_contract_data(contract_config))

        results = await asyncio.gather(*tasks)

        for result in results:
            if result:
                symbol, timeframe, data_df, specific_rules = result
                self.market_data[(symbol, timeframe)] = data_df
                self.exchange_info_map[symbol] = specific_rules
                loaded_count += 1

        if loaded_count == 0 and self.contracts:
            logger.critical(
                "CRITICAL: No data loaded for ANY contract. Backtest cannot proceed meaningfully."
            )
        else:
            logger.info(
                f"Data loading completed. Loaded data for {loaded_count} symbol/timeframe pairs."
            )
        logger.info(
            f"Exchange info map populated for symbols: {list(self.exchange_info_map.keys())}"
        )

    async def _load_single_contract_data(
        self, contract_config: Dict[str, Any]
    ) -> Optional[Tuple[str, str, pd.DataFrame, Dict[str, Any]]]:
        symbol = contract_config.get("symbol")
        strategy_name = contract_config.get("strategy_name", "UnknownStrategy")
        params = contract_config.get("params", {})
        timeframe = params.get("tf")

        if not symbol or not timeframe:
            logger.error(
                f"Contract ('{strategy_name}' for '{symbol}') missing 'symbol' or 'params.tf'. Skipping."
            )
            return None

        market_type = contract_config.get("market_type", "spot")
        logger.info(
            f"Loading data for contract: {symbol} ({timeframe}, {market_type}) for strategy '{strategy_name}'..."
        )
        try:
            data_df = await download_klines(
                symbol=symbol,
                timeframe=timeframe,
                start_dt=self.start_date,
                end_dt=self.end_date,
                market_type=market_type,
            )
            if data_df is not None and not data_df.empty:
                atr_period = params.get("atr_period", 14)
                data_df["atr"] = calculate_atr(data_df, period=atr_period)
                data_df["atr"] = data_df["atr"].bfill().ffill()
                data_df["atr"] = data_df["atr"].fillna(0.000001)

                specific_rules = contract_config.get("exchange_rules", {})
                if not specific_rules:
                    specific_rules = global_bot_config.DEFAULT_EXCHANGE_RULES.get(
                        symbol, {}
                    )
                if not specific_rules:
                    specific_rules = global_bot_config.DEFAULT_EXCHANGE_RULES.get(
                        "default", {}
                    )

                logger.info(
                    f"Successfully loaded and processed klines for {symbol} ({timeframe}). ATR added. Exchange rules for {symbol}: {specific_rules}"
                )
                return symbol, timeframe, data_df, specific_rules
            elif data_df is not None and data_df.empty:
                logger.warning(
                    f"No data returned for {symbol} ({timeframe}). Strategy '{strategy_name}' might not operate."
                )
            else:
                logger.error(
                    f"Failed to load data for {symbol} ({timeframe}). Strategy '{strategy_name}' will likely not operate."
                )
        except Exception as e:
            logger.error(
                f"Exception during data loading for {symbol} ({timeframe}): {e}",
                exc_info=True,
            )
        return None

    def _initialize_strategies(self) -> None:
        logger.info("Initializing strategies...")
        successful_initializations = 0
        for i, contract_config_loop in enumerate(self.contracts):
            strategy_name = contract_config_loop.get("strategy_name")
            symbol = contract_config_loop.get("symbol")
            params = contract_config_loop.get("params", {})

            if not strategy_name or not symbol:
                logger.error(
                    f"Skipping strategy initialization for contract {i + 1} due to missing 'strategy_name' or 'symbol'."
                )
                continue

            current_contract_id = contract_config_loop.get(
                "id", f"{strategy_name}_{symbol}_{params.get('tf', 'default_tf')}_{i}"
            )
            self.contract_details[current_contract_id] = contract_config_loop

            instance = create_strategy_instance(
                strategy_name=strategy_name,
                params=params,
                contract_id=current_contract_id,
            )

            if instance:
                primary_tf = params.get("tf")
                market_data_for_init = self.market_data.get((symbol, primary_tf))
                atr_series_for_init = (
                    market_data_for_init["atr"]
                    if market_data_for_init is not None
                    and "atr" in market_data_for_init
                    else None
                )
                try:
                    if hasattr(instance, "initialize") and callable(
                        getattr(instance, "initialize")
                    ):
                        instance.initialize(
                            market_data_klines=market_data_for_init,
                            atr_series=atr_series_for_init,
                        )

                    self.strategy_instances[current_contract_id] = instance
                    logger.info(
                        f"Initialized strategy '{strategy_name}' for contract ID '{current_contract_id}'. Instance type: {type(instance)}. Params via _get_param: {instance._instance_params}"
                    )
                    successful_initializations += 1
                except Exception as e_init_strat:
                    logger.error(
                        f"Error during/after initializing strategy {strategy_name} for {current_contract_id}: {e_init_strat}",
                        exc_info=True,
                    )
            else:
                logger.warning(
                    f"Failed to get instance for strategy '{strategy_name}' (contract ID '{current_contract_id}'). "
                    f"It will not generate signals."
                )
        logger.info(
            f"Strategy initialization completed. {successful_initializations}/{len(self.contracts)} instances created."
        )

    def _open_position(
        self,
        signal: StrategySignal,
        quantity: float,
        entry_price: float,
        entry_time: datetime,
        entry_commission: float,
        l2_entry_details: Dict[str, Any],
    ) -> Optional[str]:
        contract_id = getattr(signal, "contract_id", None)
        if not contract_id:
            logger.error(
                f"Signal for {signal.symbol} by {signal.strategy_name if hasattr(signal, 'strategy_name') else 'UnknownStrategy'} is missing 'contract_id'. Cannot open position."
            )
            return None

        position_id = self._get_next_position_id()
        self.current_balance -= entry_commission

        pos_state = BacktestPositionState(
            position_id=position_id,
            contract_id=contract_id,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=entry_price,
            quantity=quantity,
            entry_time=entry_time,
            current_sl=signal.stop_loss,
            current_tp=signal.take_profit,
            initial_value_usd=entry_price * quantity,
            last_update_time=entry_time,
            entry_commission_paid=entry_commission,
            l2_entry_details=l2_entry_details,
        )
        self.active_positions[position_id] = pos_state
        sl_str = f"{signal.stop_loss:.4f}" if signal.stop_loss is not None else "N/A"
        tp_str = (
            f"{signal.take_profit:.4f}" if signal.take_profit is not None else "N/A"
        )
        logger.info(
            f"Opened Position {position_id}: {pos_state.direction.name} {quantity:.8f} {pos_state.symbol} "
            f"@ {entry_price:.4f}, SL: {sl_str}, TP: {tp_str}. "
            f"Comm: ${entry_commission:.4f}. Balance: ${self.current_balance:.2f}. L2 Details: {l2_entry_details}"
        )
        return position_id

    def _close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_time: datetime,
        reason: str,
        qty_actually_closed: Optional[float] = None,
        exit_commission: float = 0.0,
        l2_exit_details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if position_id not in self.active_positions:
            logger.error(f"Attempted to close non-existent position: {position_id}")
            return

        position = self.active_positions[position_id]
        quantity_to_close = (
            qty_actually_closed
            if qty_actually_closed is not None and qty_actually_closed > 0
            else position.quantity
        )

        if quantity_to_close <= 1e-9:
            logger.warning(
                f"Position {position_id} close attempted with zero or invalid quantity ({quantity_to_close}). Reason: {reason}. No PnL impact."
            )
            if (
                qty_actually_closed is not None
                and qty_actually_closed <= 1e-9
                and position.quantity > 1e-9
            ):
                logger.warning(
                    f"Position {position_id} remains active as attempted close resulted in zero filled quantity."
                )
                return
            if position.quantity > 1e-9 and (
                qty_actually_closed is None or qty_actually_closed <= 1e-9
            ):
                logger.warning(
                    f"Position {position_id} close attempted but no quantity specified as closed. Position remains."
                )
                return

        pnl = 0.0
        if position.direction == SignalDirection.LONG:
            pnl = (exit_price - position.entry_price) * quantity_to_close
        elif position.direction == SignalDirection.SHORT:
            pnl = (position.entry_price - exit_price) * quantity_to_close

        net_pnl_event = pnl - exit_commission
        self.current_balance += net_pnl_event

        total_trade_commission = position.entry_commission_paid + exit_commission
        net_pnl_total_trade = pnl - total_trade_commission

        strategy_name_for_log = "UnknownStrategy"
        if position.contract_id in self.contract_details:
            strategy_name_for_log = self.contract_details[position.contract_id].get(
                "strategy_name", "UnknownStrategyInDetails"
            )

        trade_record = {
            "position_id": position.position_id,
            "contract_id": position.contract_id,
            "strategy_name": strategy_name_for_log,
            "symbol": position.symbol,
            "direction": position.direction.name,
            "entry_time": position.entry_time.isoformat()
            if isinstance(position.entry_time, datetime)
            else str(position.entry_time),
            "entry_price": position.entry_price,
            "original_quantity": position.quantity,
            "closed_quantity": quantity_to_close,
            "exit_time": exit_time.isoformat()
            if isinstance(exit_time, datetime)
            else str(exit_time),
            "exit_price": exit_price,
            "initial_sl": position.current_sl,
            "initial_tp": position.current_tp,
            "exit_reason": reason,
            "pnl_gross_event": pnl,
            "commission_entry": position.entry_commission_paid,
            "commission_exit": exit_commission,
            "pnl_net_total_trade": net_pnl_total_trade,
            "balance_after_trade": self.current_balance,
            "l2_entry_details": position.l2_entry_details,
            "l2_exit_details": l2_exit_details or {},
        }
        self.trade_log.append(trade_record)

        if abs(quantity_to_close - position.quantity) < 1e-9:  # Full close
            del self.active_positions[position_id]
            logger.info(
                f"Closed Position FULLY {position_id}: {position.direction.name} {quantity_to_close:.8f} of {position.quantity:.8f} {position.symbol} "
                f"Exit @ {exit_price:.4f} ({reason}). Event PnL (Net): ${net_pnl_event:.2f} (Gross: ${pnl:.2f}, Exit Comm: ${exit_commission:.4f}). "
                f"Total Trade PnL (Net): ${net_pnl_total_trade:.2f}. "
                f"Balance: ${self.current_balance:.2f}. L2 Exit: {l2_exit_details or {}}"
            )
        else:  # Partial close
            position.quantity -= quantity_to_close
            position.pnl_realized += net_pnl_event
            logger.info(
                f"Partially Closed Position {position_id}: {position.direction.name} {quantity_to_close:.8f} of {position.quantity + quantity_to_close:.8f} {position.symbol}. "
                f"Remaining: {position.quantity:.8f}. "
                f"Exit @ {exit_price:.4f} ({reason}). Event PnL (Net): ${net_pnl_event:.2f}. "
                f"Balance: ${self.current_balance:.2f}. L2 Exit: {l2_exit_details or {}}"
            )

    def _update_position(
        self,
        position_id: str,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
        current_ts_for_update: Optional[datetime] = None,
    ) -> None:
        if position_id in self.active_positions:
            pos = self.active_positions[position_id]
            log_msgs = []
            if new_sl is not None and new_sl != pos.current_sl:
                log_msgs.append(f"SL updated from {pos.current_sl} to {new_sl}")
                pos.current_sl = new_sl
            if new_tp is not None and new_tp != pos.current_tp:
                log_msgs.append(f"TP updated from {pos.current_tp} to {new_tp}")
                pos.current_tp = new_tp
            if log_msgs:
                logger.info(
                    f"Position {position_id} ({pos.symbol}) updated: {'; '.join(log_msgs)}"
                )
                pos.last_update_time = (
                    current_ts_for_update
                    if current_ts_for_update
                    else (
                        self.unified_timeline[-1]
                        if self.unified_timeline
                        else datetime.now(timezone.utc)
                    )
                )
        else:
            logger.warning(f"Attempted to update non-existent position: {position_id}")

    def _place_limit_order(
        self,
        signal: StrategySignal,
        quantity: float,
        limit_price: float,
        place_time: datetime,
        l2_potential_details: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        order_id = self._get_next_order_id()
        contract_id = getattr(signal, "contract_id", None)
        if not contract_id:
            logger.error(
                f"Cannot place limit order: Signal for {signal.symbol} is missing contract_id."
            )
            return None

        self.pending_orders[order_id] = {
            "order_id": order_id,
            "signal": signal,
            "quantity": quantity,
            "limit_price": limit_price,
            "place_time": place_time,
            "status": "PENDING",
            "contract_id": contract_id,
            "l2_potential_details": l2_potential_details or {},
        }
        logger.info(
            f"Placed Limit Order {order_id} for contract {contract_id} ({signal.symbol}) at {limit_price}, Qty: {quantity}"
        )
        return order_id

    def _cancel_order(
        self, order_id: str, current_ts_for_cancel: Optional[datetime] = None
    ) -> None:
        if order_id in self.pending_orders:
            log_msg = f"Cancelled Order {order_id}: {self.pending_orders[order_id]['signal'].symbol}"
            if current_ts_for_cancel:
                log_msg += f" at {current_ts_for_cancel}"
            logger.info(log_msg)
            del self.pending_orders[order_id]
        else:
            logger.warning(f"Attempted to cancel non-existent order: {order_id}")

    async def _process_pending_orders(
        self,
        current_ts: datetime,
        klines_for_ts_event: Dict[Tuple[str, str], pd.Series],
        current_ts_l2_snapshots: Dict[str, Optional[Dict[str, Any]]],
    ) -> None:
        orders_to_remove = []
        for order_id, order_details in list(self.pending_orders.items()):
            signal: StrategySignal = order_details["signal"]
            contract_id_for_order = order_details.get("contract_id")
            if not contract_id_for_order:
                logger.error(
                    f"Order {order_id} is missing 'contract_id' in pending_orders details. Skipping."
                )
                orders_to_remove.append(order_id)
                continue

            contract_config = self.contract_details.get(contract_id_for_order)
            if not contract_config:
                logger.error(
                    f"Missing contract config for order {order_id} (contract_id: {contract_id_for_order}). Skipping."
                )
                orders_to_remove.append(order_id)
                continue

            symbol_for_order = signal.symbol
            tf_for_order = contract_config["params"].get(
                "tf", self.global_risk_limits.get("GLOBAL_DEFAULT_TIMEFRAME", "1h")
            )
            symbol_tf_key = (symbol_for_order, tf_for_order)

            if symbol_tf_key not in klines_for_ts_event:
                logger.debug(
                    f"No kline data for {symbol_tf_key} at {current_ts} for pending order {order_id}. Skipping."
                )
                continue

            current_kline = klines_for_ts_event[symbol_tf_key]
            limit_price = order_details["limit_price"]
            quantity = order_details["quantity"]

            ideal_fill_price_limit: Optional[float] = None
            if (
                signal.direction == SignalDirection.LONG
                and current_kline["low"] <= limit_price
            ):
                ideal_fill_price_limit = min(current_kline["open"], limit_price)
            elif (
                signal.direction == SignalDirection.SHORT
                and current_kline["high"] >= limit_price
            ):
                ideal_fill_price_limit = max(current_kline["open"], limit_price)

            if ideal_fill_price_limit is not None:
                final_entry_price = ideal_fill_price_limit
                final_filled_qty = quantity
                entry_commission = 0.0
                l2_details_for_open: Dict[str, Any] = {}

                orderbook_snapshot = current_ts_l2_snapshots.get(signal.symbol)
                exchange_rules_for_sim = self._get_exchange_info(
                    signal.symbol, contract_config
                )

                exec_result_limit: OrderExecutionResult = (
                    simulate_market_order_execution(
                        order_quantity=quantity,
                        direction=signal.direction,
                        orderbook_snapshot=orderbook_snapshot
                        if self.l2_market_impact_enabled
                        else None,
                        ideal_entry_price=limit_price,
                        commission_pct=self.commission_pct,
                        kline_close_for_fallback=ideal_fill_price_limit,
                        simple_slippage_pct=self.simple_slippage_pct,
                    )
                )

                if (
                    exec_result_limit.fill_type != FillType.NO_FILL
                    and exec_result_limit.avg_fill_price is not None
                ):
                    can_fill_at_limit_or_better = False
                    sim_fill_price = exec_result_limit.avg_fill_price
                    tick_s = float(exchange_rules_for_sim.get("tick_size", 0.00000001))

                    if (
                        signal.direction == SignalDirection.LONG
                        and sim_fill_price <= limit_price + tick_s * 0.5
                    ):
                        can_fill_at_limit_or_better = True
                    elif (
                        signal.direction == SignalDirection.SHORT
                        and sim_fill_price >= limit_price - tick_s * 0.5
                    ):
                        can_fill_at_limit_or_better = True

                    if can_fill_at_limit_or_better:
                        final_filled_qty = exec_result_limit.filled_quantity
                        if final_filled_qty < quantity * 0.1:
                            logger.info(
                                f"Limit Order {order_id} for {signal.symbol} at {limit_price} filled too little ({final_filled_qty}/{quantity}) via sim. Order remains pending. Msg: {exec_result_limit.message}"
                            )
                            continue
                        if final_filled_qty < quantity:
                            logger.warning(
                                f"Limit Order {order_id} for {signal.symbol} at {limit_price} partially filled {final_filled_qty}/{quantity} via sim. Msg: {exec_result_limit.message}"
                            )

                        final_entry_price = sim_fill_price
                        entry_commission = exec_result_limit.actual_commission_paid
                        l2_details_for_open = exec_result_limit.__dict__
                        logger.info(
                            f"Limit Order {order_id} ({signal.symbol}, Sim: {exec_result_limit.fill_type}) Fill: Qty {final_filled_qty:.8f} at {final_entry_price:.4f}. L2D: {l2_details_for_open}"
                        )
                    else:
                        l2_details_for_open = exec_result_limit.__dict__
                    logger.info(
                        f"Limit Order {order_id} ({signal.symbol}, Sim: {exec_result_limit.fill_type.value}) Fill: Qty {final_filled_qty:.8f} at {final_entry_price:.4f}. L2D: {l2_details_for_open}"
                    )
                else:
                    logger.info(
                        f"Limit Order {order_id} for {signal.symbol} at {limit_price} NO FILL from simulation. Order remains pending. Msg: {exec_result_limit.message}"
                    )
                    continue

                if (
                    signal.direction == SignalDirection.LONG
                    and final_entry_price >= (signal.stop_loss or float("inf"))
                ) or (
                    signal.direction == SignalDirection.SHORT
                    and final_entry_price <= (signal.stop_loss or -float("inf"))
                ):
                    logger.warning(
                        f"Limit Order {order_id} for {signal.symbol} fill price {final_entry_price} is beyond SL {signal.stop_loss}. Cancelling."
                    )
                else:
                    self._open_position(
                        signal,
                        final_filled_qty,
                        final_entry_price,
                        current_ts,
                        entry_commission=entry_commission,
                        l2_entry_details=l2_details_for_open,
                    )
                orders_to_remove.append(order_id)

        for order_id_rem in orders_to_remove:
            if order_id_rem in self.pending_orders:
                del self.pending_orders[order_id_rem]

    async def run_backtest(self) -> Optional[Dict[str, Any]]:
        logger.info("Starting portfolio backtest...")

        await self._load_data()
        self._initialize_strategies()

        if not self.market_data:
            logger.error(
                "No market data. Ensure _load_data() was successful and data exists for contracts."
            )
            return None
        if not self.strategy_instances:
            logger.warning(
                "No strategy instances initialized. Backtest will run but no signals will be generated."
            )

        self.current_balance = self.initial_balance
        self.active_positions = {}
        self.pending_orders = {}
        self.trade_log = []
        self.equity_curve = []
        self.unified_timeline = []
        self.snapshots_for_ts = {}

        start_date_to_use = self.start_date
        if self.start_date.tzinfo is None:
            first_df_tz = None
            if self.market_data:
                first_df_key = next(iter(self.market_data))
                if self.market_data[first_df_key].index.tz is not None:
                    first_df_tz = self.market_data[first_df_key].index.tz
            start_date_to_use = self.start_date.replace(
                tzinfo=first_df_tz or timezone.utc
            )
        self.equity_curve = [(start_date_to_use, self.initial_balance)]

        all_timestamps = set()
        for (symbol, timeframe), df in self.market_data.items():
            if df is not None and not df.empty:
                logger.debug(
                    f"Adding {len(df.index)} timestamps from {symbol}-{timeframe}"
                )
                all_timestamps.update(df.index.tolist())

        if not all_timestamps:
            logger.error("No timestamps in market data after loading. Cannot proceed.")
            return None

        self.unified_timeline = sorted(list(all_timestamps))
        logger.info(
            f"Unified timeline created with {len(self.unified_timeline)} unique timestamps, from {self.unified_timeline[0]} to {self.unified_timeline[-1]}."
        )

        for current_ts in self.unified_timeline:
            if not self.equity_curve or self.equity_curve[-1][0] != current_ts:
                self.equity_curve.append((current_ts, self.current_balance))

            klines_for_ts_event: Dict[Tuple[str, str], pd.Series] = {}
            active_symbols_this_ts = set()
            for (symbol, timeframe), df_market in self.market_data.items():
                if current_ts in df_market.index:
                    klines_for_ts_event[(symbol, timeframe)] = df_market.loc[current_ts]
                    active_symbols_this_ts.add(symbol)

            current_ts_l2_snapshots: Dict[str, Optional[Dict[str, Any]]] = {}
            if self.l2_market_impact_enabled and self.l2_reader:
                kline_timestamp_ms = int(current_ts.timestamp() * 1000)
                for symbol_l2 in active_symbols_this_ts:
                    try:
                        snapshot = await self.l2_reader.get_book_snapshot_at(
                            symbol_l2, kline_timestamp_ms
                        )
                        current_ts_l2_snapshots[symbol_l2] = snapshot
                    except Exception as e_l2:
                        logger.error(
                            f"Error fetching L2 for {symbol_l2} at {current_ts}: {e_l2}"
                        )
                        current_ts_l2_snapshots[symbol_l2] = None
            self.snapshots_for_ts[current_ts] = current_ts_l2_snapshots

            await self._process_pending_orders(
                current_ts, klines_for_ts_event, current_ts_l2_snapshots
            )

            positions_to_close_due_to_sl_tp: List[Tuple[str, float, str]] = []
            for pos_id, position_state in list(self.active_positions.items()):
                contract_config_pos = self.contract_details.get(
                    position_state.contract_id
                )
                if not contract_config_pos:
                    continue

                tf_pos = contract_config_pos["params"].get(
                    "tf", self.global_risk_limits.get("GLOBAL_DEFAULT_TIMEFRAME", "1h")
                )
                kline_series_pos = klines_for_ts_event.get(
                    (position_state.symbol, tf_pos)
                )
                if kline_series_pos is None:
                    continue

                k_high = float(kline_series_pos["high"])
                k_low = float(kline_series_pos["low"])
                ideal_exit_price_sl_tp: Optional[float] = None
                exit_reason_sl_tp: Optional[str] = None

                if position_state.direction == SignalDirection.LONG:
                    if position_state.current_sl and k_low <= position_state.current_sl:
                        ideal_exit_price_sl_tp = position_state.current_sl
                        exit_reason_sl_tp = "STOP_LOSS"
                    elif (
                        position_state.current_tp
                        and k_high >= position_state.current_tp
                    ):
                        ideal_exit_price_sl_tp = position_state.current_tp
                        exit_reason_sl_tp = "TAKE_PROFIT"
                elif position_state.direction == SignalDirection.SHORT:
                    if (
                        position_state.current_sl
                        and k_high >= position_state.current_sl
                    ):
                        ideal_exit_price_sl_tp = position_state.current_sl
                        exit_reason_sl_tp = "STOP_LOSS"
                    elif (
                        position_state.current_tp and k_low <= position_state.current_tp
                    ):
                        ideal_exit_price_sl_tp = position_state.current_tp
                        exit_reason_sl_tp = "TAKE_PROFIT"

                if ideal_exit_price_sl_tp is not None and exit_reason_sl_tp is not None:
                    positions_to_close_due_to_sl_tp.append(
                        (pos_id, ideal_exit_price_sl_tp, exit_reason_sl_tp)
                    )

            for (
                pos_id_sl_tp_loop,
                ideal_price_sl_tp_loop,
                reason_sl_tp_loop,
            ) in positions_to_close_due_to_sl_tp:
                if pos_id_sl_tp_loop in self.active_positions:
                    await self._trigger_close_position(
                        pos_id_sl_tp_loop,
                        ideal_price_sl_tp_loop,
                        reason_sl_tp_loop,
                        current_ts,
                        current_ts_l2_snapshots,
                    )

            new_signals_this_ts: List[StrategySignal] = []
            for (
                contract_id_loop,
                strategy_instance_loop,
            ) in self.strategy_instances.items():
                contract_config_loop_event = self.contract_details.get(contract_id_loop)
                if not contract_config_loop_event:
                    continue

                symbol_loop = contract_config_loop_event["symbol"]
                timeframe_loop = contract_config_loop_event["params"]["tf"]
                current_kline_for_strat = klines_for_ts_event.get(
                    (symbol_loop, timeframe_loop)
                )

                if current_kline_for_strat is not None:
                    active_position_for_contract = next(
                        (
                            p
                            for p in self.active_positions.values()
                            if p.contract_id == contract_id_loop
                        ),
                        None,
                    )
                    l2_for_strat_symbol = current_ts_l2_snapshots.get(symbol_loop)

                    try:
                        signals_from_strat: List[StrategySignal] = (
                            strategy_instance_loop.check_signal_sync(
                                kline=current_kline_for_strat,
                                current_balance=self.current_balance,
                                active_position=active_position_for_contract,
                                snapshots=self.snapshots_for_ts.get(current_ts),
                            )
                        )
                        for s_obj in signals_from_strat:
                            s_obj.contract_id = contract_id_loop
                            s_obj.timestamp = current_ts
                            if (
                                not hasattr(s_obj, "strategy_name")
                                or not s_obj.strategy_name
                            ):
                                s_obj.strategy_name = (
                                    strategy_instance_loop.strategy_name
                                    if hasattr(strategy_instance_loop, "strategy_name")
                                    else type(strategy_instance_loop).__name__
                                )
                            new_signals_this_ts.append(s_obj)
                            logger.info(
                                f"Signal from {contract_id_loop} at {current_ts}: {s_obj.direction.name} {s_obj.symbol}"
                            )
                    except Exception as e_sig_gen:
                        logger.error(
                            f"Error in check_signal_sync for {contract_id_loop} at {current_ts}: {e_sig_gen}",
                            exc_info=True,
                        )

                    if active_position_for_contract:
                        try:
                            trailing_signals = (
                                strategy_instance_loop.update_trailing_stops_sync(
                                    kline=current_kline_for_strat,
                                    position=active_position_for_contract,
                                    current_balance=self.current_balance,
                                )
                            )
                            for ts_signal in trailing_signals:
                                ts_signal.contract_id = contract_id_loop
                                ts_signal.timestamp = current_ts
                                if (
                                    not hasattr(ts_signal, "strategy_name")
                                    or not ts_signal.strategy_name
                                ):
                                    ts_signal.strategy_name = (
                                        strategy_instance_loop.strategy_name
                                        if hasattr(
                                            strategy_instance_loop, "strategy_name"
                                        )
                                        else type(strategy_instance_loop).__name__
                                    )
                                new_signals_this_ts.append(ts_signal)
                                logger.info(
                                    f"Trailing stop update signal from {contract_id_loop} for pos {active_position_for_contract.position_id} at {current_ts}"
                                )
                        except Exception as e_ts_update:
                            logger.error(
                                f"Error in update_trailing_stops_sync for {contract_id_loop}: {e_ts_update}",
                                exc_info=True,
                            )

            if new_signals_this_ts:
                logger.debug(
                    f"Timestamp {current_ts}: Processing {len(new_signals_this_ts)} new signals (incl. TSL)."
                )
                for signal_to_process in new_signals_this_ts:
                    contract_cfg_proc = self.contract_details.get(
                        signal_to_process.contract_id
                    )
                    if not contract_cfg_proc:
                        logger.error(
                            f"Signal {getattr(signal_to_process, 'signal_id', 'N/A')} missing contract_cfg. Skipping."
                        )
                        continue

                    if signal_to_process.direction == SignalDirection.NEUTRAL:
                        active_pos_to_close = next(
                            (
                                p
                                for p_id, p in self.active_positions.items()
                                if p.contract_id == signal_to_process.contract_id
                            ),
                            None,
                        )
                        if active_pos_to_close:
                            if (
                                signal_to_process.is_trailing_sl_update
                                or signal_to_process.is_trailing_tp_update
                            ):
                                self._update_position(
                                    active_pos_to_close.position_id,
                                    new_sl=signal_to_process.stop_loss,
                                    new_tp=signal_to_process.take_profit,
                                    current_ts_for_update=current_ts,
                                )
                            else:
                                close_reason = (
                                    signal_to_process.force_close_reason
                                    or "STRATEGY_CLOSE_SIGNAL"
                                )
                                tf_close_sig = contract_cfg_proc["params"].get(
                                    "tf", "1m"
                                )
                                kline_series_close_sig = klines_for_ts_event.get(
                                    (signal_to_process.symbol, tf_close_sig)
                                )
                                ideal_exit_price_close_sig = (
                                    float(kline_series_close_sig["close"])
                                    if kline_series_close_sig is not None
                                    else active_pos_to_close.entry_price
                                )
                                await self._trigger_close_position(
                                    active_pos_to_close.position_id,
                                    ideal_exit_price_close_sig,
                                    close_reason,
                                    current_ts,
                                    current_ts_l2_snapshots,
                                )
                        else:
                            logger.info(
                                f"Neutral signal for {signal_to_process.contract_id} but no active position found."
                            )
                        continue

                    is_pos_active_for_contract_entry = any(
                        p.contract_id == signal_to_process.contract_id
                        for p in self.active_positions.values()
                    )
                    if (
                        is_pos_active_for_contract_entry
                        and not signal_to_process.allow_entry_with_existing_pos
                    ):
                        logger.info(
                            f"Signal for {signal_to_process.contract_id} on {signal_to_process.symbol} ignored: position already active and signal does not allow re-entry."
                        )
                        continue

                    tf_proc_sig = contract_cfg_proc["params"].get("tf", "1m")
                    kline_series_proc_sig = klines_for_ts_event.get(
                        (signal_to_process.symbol, tf_proc_sig)
                    )
                    if kline_series_proc_sig is None:
                        logger.warning(
                            f"No kline data for signal {signal_to_process.symbol}/{tf_proc_sig} at {current_ts}. Cannot process signal."
                        )
                        continue

                    entry_price_for_risk_calc_proc = float(
                        kline_series_proc_sig["close"]
                    )
                    if (
                        signal_to_process.mode == OrderMode.MARKET
                        and signal_to_process.entry_price
                    ):
                        entry_price_for_risk_calc_proc = signal_to_process.entry_price

                    atr_for_risk_calc_proc = float(
                        kline_series_proc_sig.get("atr", 0.000001)
                    )

                    calculated_quantity_proc = (
                        self.risk_manager.calculate_position_size(
                            signal=signal_to_process,
                            current_balance=self.current_balance,
                            entry_price=entry_price_for_risk_calc_proc,
                            stop_loss_price=signal_to_process.stop_loss,
                            exchange_info=self._get_exchange_info(
                                signal_to_process.symbol, contract_cfg_proc
                            ),
                        )
                    )

                    if (
                        calculated_quantity_proc is not None
                        and calculated_quantity_proc > 0
                    ):
                        is_signal_valid_proc = self.risk_manager.validate_signal(
                            signal=signal_to_process,
                            calculated_quantity=calculated_quantity_proc,
                            entry_price=entry_price_for_risk_calc_proc,
                            current_balance=self.current_balance,
                            active_positions=self.active_positions,
                        )
                        if is_signal_valid_proc:
                            if signal_to_process.mode == OrderMode.MARKET:
                                entry_price_base_market = entry_price_for_risk_calc_proc
                                qty_market = calculated_quantity_proc
                                l2_details_market_entry = {}
                                orderbook_snapshot_market_entry = (
                                    current_ts_l2_snapshots.get(
                                        signal_to_process.symbol
                                    )
                                )
                                exchange_rules_proc_sig = self._get_exchange_info(
                                    signal_to_process.symbol, contract_cfg_proc
                                )

                                final_entry_price_market = entry_price_base_market
                                final_filled_qty_market = qty_market
                                entry_commission_market = 0.0

                                market_data_for_sim_entry = (
                                    {"depth_trading": orderbook_snapshot_market_entry}
                                    if orderbook_snapshot_market_entry
                                    else {}
                                )

                                exec_result_market: OrderExecutionResult = simulate_market_order_execution(
                                    order_quantity=qty_market,
                                    direction=signal_to_process.direction,
                                    market_data_for_sim=market_data_for_sim_entry
                                    if self.l2_market_impact_enabled
                                    else None,
                                    ideal_entry_price=entry_price_base_market,
                                    commission_pct=self.commission_pct,
                                    kline_close_for_fallback=entry_price_base_market,
                                    simple_slippage_pct=self.simple_slippage_pct,
                                )

                                if (
                                    exec_result_market.fill_type != FillType.NO_FILL
                                    and exec_result_market.avg_fill_price is not None
                                ):
                                    final_entry_price_market = (
                                        exec_result_market.avg_fill_price
                                    )
                                    final_filled_qty_market = (
                                        exec_result_market.filled_quantity
                                    )
                                    entry_commission_market = (
                                        exec_result_market.actual_commission_paid
                                    )

                                    l2_details_market_entry = (
                                        exec_result_market.__dict__
                                    )
                                    logger.info(
                                        f"Market Order ({signal_to_process.symbol}, Sim: {exec_result_market.fill_type.value}): Qty {final_filled_qty_market:.8f} at {final_entry_price_market:.4f}. L2D: {l2_details_market_entry}"
                                    )

                                    if final_filled_qty_market < qty_market * 0.1:
                                        logger.warning(
                                            f"Market Order for {signal_to_process.symbol} failed to fill significantly ({final_filled_qty_market}/{qty_market}). Order skipped. Msg: {exec_result_market.message}"
                                        )
                                        continue
                                    if final_filled_qty_market < qty_market:
                                        logger.warning(
                                            f"Market Order for {signal_to_process.symbol} partially filled ({final_filled_qty_market}/{qty_market}). Msg: {exec_result_market.message}"
                                        )
                                else:
                                    logger.warning(
                                        f"Market Order for {signal_to_process.symbol} NO FILL from simulation. Skipping. Msg: {exec_result_market.message}"
                                    )
                                    continue

                                open_position_allowed = False
                                if signal_to_process.stop_loss is not None:
                                    if (
                                        signal_to_process.direction
                                        == SignalDirection.LONG
                                        and final_entry_price_market
                                        > signal_to_process.stop_loss
                                    ):
                                        open_position_allowed = True
                                    elif (
                                        signal_to_process.direction
                                        == SignalDirection.SHORT
                                        and final_entry_price_market
                                        < signal_to_process.stop_loss
                                    ):
                                        open_position_allowed = True
                                else:
                                    open_position_allowed = True

                                if open_position_allowed:
                                    self._open_position(
                                        signal_to_process,
                                        final_filled_qty_market,
                                        final_entry_price_market,
                                        current_ts,
                                        entry_commission=entry_commission_market,
                                        l2_entry_details=l2_details_market_entry,
                                    )
                                else:
                                    logger.warning(
                                        f"Signal for {signal_to_process.symbol} rejected: entry price {final_entry_price_market:.4f} (after sim) is NOT safely beyond SL {signal_to_process.stop_loss:.4f}"
                                    )

                            elif (
                                signal_to_process.mode == OrderMode.LIMIT
                                and signal_to_process.entry_price
                            ):
                                self._place_limit_order(
                                    signal_to_process,
                                    calculated_quantity_proc,
                                    signal_to_process.entry_price,
                                    current_ts,
                                )
                            else:
                                logger.warning(
                                    f"Signal mode {signal_to_process.mode.name} not fully supported or invalid for {signal_to_process.symbol}."
                                )
                        else:
                            logger.info(
                                f"Signal for {signal_to_process.symbol} rejected by RiskManager."
                            )
                    else:
                        logger.info(
                            f"Signal for {signal_to_process.symbol} resulted in zero quantity after risk calculation."
                        )

            if self.equity_curve and self.equity_curve[-1][0] == current_ts:
                self.equity_curve[-1] = (current_ts, self.current_balance)
            else:
                self.equity_curve.append((current_ts, self.current_balance))

        if self.active_positions:
            logger.info(
                f"End of backtest timeline ({self.unified_timeline[-1] if self.unified_timeline else 'N/A'}). Closing {len(self.active_positions)} open positions..."
            )
            final_ts = (
                self.unified_timeline[-1] if self.unified_timeline else self.end_date
            )
            last_klines_available = (
                klines_for_ts_event if "klines_for_ts_event" in locals() else {}
            )
            final_l2_snapshots = self.snapshots_for_ts.get(final_ts, {})

            for pos_id_eod in list(self.active_positions.keys()):
                pos_eod = self.active_positions.get(pos_id_eod)
                if not pos_eod:
                    continue

                contract_cfg_eod = self.contract_details.get(pos_eod.contract_id)
                tf_eod = (
                    contract_cfg_eod["params"].get("tf", "1m")
                    if contract_cfg_eod
                    else "1m"
                )
                kline_series_eod_key = (pos_eod.symbol, tf_eod)
                kline_data_eod_series = last_klines_available.get(kline_series_eod_key)

                if kline_data_eod_series is None and (
                    self.market_data.get(kline_series_eod_key) is not None
                    and not self.market_data[kline_series_eod_key].empty
                ):
                    last_available_ts_for_symbol_tf = self.market_data[
                        kline_series_eod_key
                    ].index[-1]
                    if last_available_ts_for_symbol_tf <= final_ts:
                        kline_data_eod_series = self.market_data[
                            kline_series_eod_key
                        ].iloc[-1]
                    elif final_ts in self.market_data[kline_series_eod_key].index:
                        kline_data_eod_series = self.market_data[
                            kline_series_eod_key
                        ].loc[final_ts]

                eod_exit_price = (
                    float(kline_data_eod_series["close"])
                    if kline_data_eod_series is not None
                    else pos_eod.entry_price
                )
                await self._trigger_close_position(
                    pos_id_eod,
                    eod_exit_price,
                    "END_OF_DATA",
                    final_ts,
                    final_l2_snapshots,
                )

        final_timeline_ts = (
            self.unified_timeline[-1] if self.unified_timeline else self.end_date
        )
        if self.equity_curve and self.equity_curve[-1][0] != final_timeline_ts:
            self.equity_curve.append((final_timeline_ts, self.current_balance))
        elif not self.equity_curve:
            self.equity_curve.append((self.start_date, self.initial_balance))
            self.equity_curve.append((self.end_date, self.current_balance))

        logger.info("Portfolio backtest finished.")
        logger.info(f"Final Balance: ${self.current_balance:,.2f}")

        kpi_results = self._calculate_kpis()
        logger.info(f"KPIs: {kpi_results}")
        return kpi_results

    def _get_exchange_info(
        self, symbol: str, contract_config: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if symbol in self.exchange_info_map:
            return self.exchange_info_map[symbol]

        cfg_to_use = contract_config or {}

        default_rules_for_symbol = global_bot_config.DEFAULT_EXCHANGE_RULES.get(
            symbol, {}
        )
        default_generic_rules = global_bot_config.DEFAULT_EXCHANGE_RULES.get(
            "default", {}
        )

        info = {
            "symbol": symbol,
            "tick_size": cfg_to_use.get(
                "tick_size",
                default_rules_for_symbol.get(
                    "tick_size", default_generic_rules.get("tick_size")
                ),
            ),
            "step_size": cfg_to_use.get(
                "step_size",
                default_rules_for_symbol.get(
                    "step_size", default_generic_rules.get("step_size")
                ),
            ),
            "min_qty": cfg_to_use.get(
                "min_qty",
                default_rules_for_symbol.get(
                    "min_qty", default_generic_rules.get("min_qty")
                ),
            ),
            "min_notional": cfg_to_use.get(
                "min_notional",
                default_rules_for_symbol.get(
                    "min_notional", default_generic_rules.get("min_notional")
                ),
            ),
        }
        for key in ["tick_size", "step_size", "min_qty", "min_notional"]:
            if isinstance(info[key], str):
                try:
                    info[key] = float(info[key])
                except ValueError:
                    logger.error(
                        f"Could not convert exchange_info value {info[key]} to float for key {key}, symbol {symbol}"
                    )
                    info[key] = 0.0

        self.exchange_info_map[symbol] = info
        return info

    async def _trigger_close_position(
        self,
        position_id: str,
        ideal_exit_price: float,
        reason: str,
        current_ts: datetime,
        current_ts_l2_snapshots: Dict[str, Optional[Dict[str, Any]]],
    ) -> None:
        if position_id not in self.active_positions:
            logger.warning(
                f"Attempted to trigger close for non-existent position: {position_id}"
            )
            return

        position = self.active_positions[position_id]
        quantity_to_close = position.quantity
        exit_direction = (
            SignalDirection.SHORT
            if position.direction == SignalDirection.LONG
            else SignalDirection.LONG
        )

        actual_exit_price_sim: Optional[float] = ideal_exit_price
        filled_at_exit_sim: float = quantity_to_close
        l2_exit_details_data: Dict[str, Any] = {}
        exit_commission_sim: float = 0.0

        orderbook_snapshot_for_exit = current_ts_l2_snapshots.get(position.symbol)

        market_data_for_sim_exit = (
            {"depth_trading": orderbook_snapshot_for_exit}
            if orderbook_snapshot_for_exit
            else {}
        )

        exec_result_exit: OrderExecutionResult = simulate_market_order_execution(
            order_quantity=quantity_to_close,
            direction=exit_direction,
            market_data_for_sim=market_data_for_sim_exit
            if self.l2_market_impact_enabled
            else None,
            ideal_entry_price=ideal_exit_price,
            commission_pct=self.commission_pct,
            kline_close_for_fallback=ideal_exit_price,
            simple_slippage_pct=self.simple_slippage_pct,
        )

        if (
            exec_result_exit.fill_type != FillType.NO_FILL
            and exec_result_exit.avg_fill_price is not None
        ):
            actual_exit_price_sim = exec_result_exit.avg_fill_price
            filled_at_exit_sim = exec_result_exit.filled_quantity
            exit_commission_sim = exec_result_exit.actual_commission_paid

            l2_exit_details_data = exec_result_exit.__dict__
            logger.info(
                f"Exit Sim ({position.symbol}, {reason}, SimType: {exec_result_exit.fill_type.value}): Qty {filled_at_exit_sim:.8f} at {actual_exit_price_sim:.4f}. L2D: {l2_exit_details_data}"
            )

            if filled_at_exit_sim < quantity_to_close * 0.1:
                logger.critical(
                    f"CRITICAL FILL FAILURE for {position_id} ({position.symbol}) on {reason} exit. "
                    f"Simulated fill: {filled_at_exit_sim}/{quantity_to_close}. Position might remain open or partially closed with error state. Msg: {exec_result_exit.message}"
                )
            elif filled_at_exit_sim < quantity_to_close:
                logger.warning(
                    f"Partial fill on {reason} exit for {position_id} ({position.symbol}). "
                    f"Simulated fill: {filled_at_exit_sim}/{quantity_to_close}. Msg: {exec_result_exit.message}"
                )
        else:
            logger.error(
                f"Exit Sim for {position_id} ({position.symbol}) resulted in NO FILL. Reason: {reason}. Msg: {exec_result_exit.message}. Position NOT closed by this event."
            )
            if reason == "END_OF_DATA":
                logger.warning(
                    f"END_OF_DATA close for {position_id} failed L2/Kline sim. Using ideal_exit_price ({ideal_exit_price}) without further slippage for accounting."
                )
                actual_exit_price_sim = ideal_exit_price
                filled_at_exit_sim = quantity_to_close
                exit_commission_sim = (
                    (actual_exit_price_sim or 0.0)
                    * filled_at_exit_sim
                    * self.commission_pct
                )
                l2_exit_details_data = {
                    "fill_type": FillType.FORCED_EOD.value,
                    "message": "EOD close forced at ideal_exit_price after sim no-fill.",
                    "actual_commission_paid": exit_commission_sim,
                    "filled_quantity": filled_at_exit_sim,
                    "avg_fill_price": actual_exit_price_sim,
                }
            else:
                return

        self._close_position(
            position_id=position_id,
            exit_price=actual_exit_price_sim or ideal_exit_price,
            exit_time=current_ts,
            reason=reason,
            qty_actually_closed=filled_at_exit_sim,
            exit_commission=exit_commission_sim,
            l2_exit_details=l2_exit_details_data,
        )

    def _calculate_kpis(self) -> Dict[str, Any]:
        num_trades = len(self.trade_log)
        kpis = {
            "total_trades": num_trades,
            "net_pnl_total": 0.0,
            "gross_pnl_total": 0.0,
            "total_commission_paid": 0.0,
            "win_rate_pct": 0.0,
            "num_wins": 0,
            "num_losses": 0,
            "profit_factor": 0.0,
            "average_trade_pnl": 0.0,
            "average_winning_trade_pnl": 0.0,
            "average_losing_trade_pnl": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio_simplified": 0.0,
            "final_balance": self.current_balance,
            "initial_balance": self.initial_balance,
            "profit_pct_on_initial": 0.0,
            "total_entry_slippage_usd": 0.0,
            "total_exit_slippage_usd": 0.0,
            "total_slippage_usd": 0.0,
            "avg_slippage_per_active_trade_usd": 0.0,
            "avg_total_slippage_pct": 0.0,
        }

        if num_trades == 0:
            logger.info("No trades executed. KPIs cannot be calculated.")
            kpis["max_drawdown_pct"] = self._calculate_max_drawdown_from_equity() * 100
            kpis["profit_pct_on_initial"] = (
                (self.current_balance / self.initial_balance - 1) * 100
                if self.initial_balance > 0
                else 0.0
            )
            return kpis

        df_trades = pd.DataFrame(self.trade_log)

        df_trades["pnl_net_total_trade"] = pd.to_numeric(
            df_trades["pnl_net_total_trade"], errors="coerce"
        ).fillna(0.0)
        df_trades["pnl_gross_event"] = pd.to_numeric(
            df_trades["pnl_gross_event"], errors="coerce"
        ).fillna(0.0)
        df_trades["commission_entry"] = pd.to_numeric(
            df_trades["commission_entry"], errors="coerce"
        ).fillna(0.0)
        df_trades["commission_exit"] = pd.to_numeric(
            df_trades["commission_exit"], errors="coerce"
        ).fillna(0.0)

        df_trades["l2_entry_slippage_usd"] = df_trades["l2_entry_details"].apply(
            lambda x: x.get("slippage_usd", 0.0) if isinstance(x, dict) else 0.0
        )
        df_trades["l2_exit_slippage_usd"] = df_trades["l2_exit_details"].apply(
            lambda x: x.get("slippage_usd", 0.0) if isinstance(x, dict) else 0.0
        )
        df_trades["l2_ideal_entry_price"] = df_trades["l2_entry_details"].apply(
            lambda x: x.get("ideal_price") if isinstance(x, dict) else np.nan
        )
        df_trades["l2_entry_filled_quantity"] = df_trades["l2_entry_details"].apply(
            lambda x: (
                x.get("filled_qty")
                if isinstance(x, dict)
                else df_trades["original_quantity"]
            )
        )
        df_trades["l2_ideal_exit_price"] = df_trades["l2_exit_details"].apply(
            lambda x: x.get("ideal_price") if isinstance(x, dict) else np.nan
        )
        df_trades["l2_filled_qty_at_exit"] = df_trades["l2_exit_details"].apply(
            lambda x: (
                x.get("filled_qty")
                if isinstance(x, dict)
                else df_trades["closed_quantity"]
            )
        )

        net_pnl_total = df_trades["pnl_net_total_trade"].sum()
        total_commission = (
            df_trades["commission_entry"].sum() + df_trades["commission_exit"].sum()
        )
        gross_pnl_total = net_pnl_total + total_commission

        wins_df = df_trades[df_trades["pnl_net_total_trade"] > 0]
        losses_df = df_trades[df_trades["pnl_net_total_trade"] <= 0]
        num_wins = len(wins_df)
        num_losses = len(losses_df)

        win_rate = (num_wins / num_trades) * 100 if num_trades > 0 else 0

        total_profit_of_wins = wins_df["pnl_net_total_trade"].sum()
        total_loss_of_losses = abs(losses_df["pnl_net_total_trade"].sum())

        profit_factor = (
            total_profit_of_wins / total_loss_of_losses
            if total_loss_of_losses > 0
            else float("inf")
        )
        if math.isinf(profit_factor) and total_profit_of_wins == 0:
            profit_factor = 0.0

        avg_trade_pnl = net_pnl_total / num_trades if num_trades > 0 else 0
        avg_win_pnl = total_profit_of_wins / num_wins if num_wins > 0 else 0
        avg_loss_pnl = total_loss_of_losses / num_losses if num_losses > 0 else 0

        max_drawdown_pct = self._calculate_max_drawdown_from_equity() * 100

        sharpe_ratio = 0.0
        if len(self.equity_curve) > 1:
            equity_df_sr = pd.DataFrame(
                self.equity_curve, columns=["timestamp", "balance"]
            ).set_index("timestamp")
            if not equity_df_sr.index.is_monotonic_increasing:
                equity_df_sr = equity_df_sr.sort_index()
            if equity_df_sr.index.normalize().nunique() > 1:
                daily_returns = (
                    equity_df_sr["balance"].resample("D").last().pct_change().dropna()
                )
                if not daily_returns.empty and daily_returns.std() != 0:
                    annualized_return = daily_returns.mean() * 252
                    annualized_volatility = daily_returns.std() * np.sqrt(252)
                    if annualized_volatility > 1e-9:
                        sharpe_ratio = max(
                            -10.0, min(10.0, annualized_return / annualized_volatility)
                        )
                elif not daily_returns.empty and daily_returns.mean() > 0:
                    sharpe_ratio = 10.0
                elif not daily_returns.empty and daily_returns.mean() < 0:
                    sharpe_ratio = -10.0

        total_entry_slippage_usd_kpi = df_trades["l2_entry_slippage_usd"].sum()
        total_exit_slippage_usd_kpi = df_trades["l2_exit_slippage_usd"].sum()
        total_slippage_usd_kpi = (
            total_entry_slippage_usd_kpi + total_exit_slippage_usd_kpi
        )

        slippage_trades_count_kpi = df_trades[
            (df_trades["l2_entry_slippage_usd"].abs() > 1e-9)
            | (df_trades["l2_exit_slippage_usd"].abs() > 1e-9)
        ].shape[0]
        avg_slippage_per_active_trade_usd_kpi = (
            total_slippage_usd_kpi / slippage_trades_count_kpi
            if slippage_trades_count_kpi > 0
            else 0.0
        )

        df_trades["l2_entry_filled_quantity_num"] = pd.to_numeric(
            df_trades["l2_entry_filled_quantity"], errors="coerce"
        ).fillna(0.0)
        df_trades["l2_filled_qty_at_exit_num"] = pd.to_numeric(
            df_trades["l2_filled_qty_at_exit"], errors="coerce"
        ).fillna(0.0)

        total_ideal_value_entry_kpi = (
            pd.to_numeric(df_trades["l2_ideal_entry_price"], errors="coerce")
            * df_trades["l2_entry_filled_quantity_num"]
        ).sum(skipna=True)
        total_ideal_value_exit_kpi = (
            pd.to_numeric(df_trades["l2_ideal_exit_price"], errors="coerce")
            * df_trades["l2_filled_qty_at_exit_num"]
        ).sum(skipna=True)

        total_ideal_turnover_kpi = (
            total_ideal_value_entry_kpi + total_ideal_value_exit_kpi
        )
        avg_total_slippage_pct_kpi = (
            (total_slippage_usd_kpi / total_ideal_turnover_kpi) * 100
            if total_ideal_turnover_kpi > 1e-9
            else 0.0
        )

        kpis.update(
            {
                "net_pnl_total": net_pnl_total,
                "gross_pnl_total": gross_pnl_total,
                "total_commission_paid": total_commission,
                "win_rate_pct": win_rate,
                "num_wins": num_wins,
                "num_losses": num_losses,
                "profit_factor": profit_factor,
                "average_trade_pnl": avg_trade_pnl,
                "average_winning_trade_pnl": avg_win_pnl,
                "average_losing_trade_pnl": -avg_loss_pnl if num_losses > 0 else 0.0,
                "max_drawdown_pct": max_drawdown_pct,
                "sharpe_ratio_simplified": sharpe_ratio,
                "profit_pct_on_initial": (net_pnl_total / self.initial_balance) * 100
                if self.initial_balance > 0
                else 0.0,
                "total_entry_slippage_usd": total_entry_slippage_usd_kpi,
                "total_exit_slippage_usd": total_exit_slippage_usd_kpi,
                "total_slippage_usd": total_slippage_usd_kpi,
                "avg_slippage_per_active_trade_usd": avg_slippage_per_active_trade_usd_kpi,
                "avg_total_slippage_pct": avg_total_slippage_pct_kpi,
            }
        )

        logger.info("Backtest KPIs:")
        for key, value in kpis.items():
            if isinstance(value, float):
                logger.info(f"  {key.replace('_', ' ').title()}: {value:,.3f}")
            else:
                logger.info(f"  {key.replace('_', ' ').title()}: {value}")

        return kpis

    def _calculate_max_drawdown_from_equity(self) -> float:
        if not self.equity_curve:
            return 0.0

        equity = pd.Series([e[1] for e in self.equity_curve])
        if equity.empty:
            return 0.0

        peak = equity.cummax()
        drawdown = (equity - peak) / peak
        max_drawdown = drawdown.min()
        return abs(max_drawdown)


if __name__ == "__main__":
    example_logger = logging.getLogger("bot_module")
    if not example_logger.hasHandlers():
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        example_logger.addHandler(handler)
    example_logger.setLevel(logging.INFO)

    dummy_contracts = [
        {
            "strategy_name": "VolumeBreakout",
            "symbol": "BTCUSDT",
            "market_type": "spot",
            "params": {
                "tf": "1h",
                "retest_atr_percent": 0.1,
                "stop_loss_atr_multiplier": 1.0,
                "take_profit_atr_multiplier": 1.5,
                "atr_period": 10,
            },
            "tick_size": 0.01,
        },
    ]
    dummy_risk_limits = {
        "max_total_exposure_pct": 0.5,
        "max_concurrent_positions": 5,
        "max_risk_per_trade_pct": 0.01,
        "commission_pct": 0.001,
        "simple_slippage_pct": 0.0005,
    }

    if (
        not hasattr(global_bot_config, "STRATEGY_DEFAULTS")
        or global_bot_config.STRATEGY_DEFAULTS is None
    ):
        global_bot_config.STRATEGY_DEFAULTS = {}
        logger.info(
            "Initialized global_bot_config.STRATEGY_DEFAULTS as it was missing."
        )

    test_l2_data_path = "./test_portfolio_l2_data"
    from pathlib import Path

    Path(test_l2_data_path).mkdir(parents=True, exist_ok=True)
