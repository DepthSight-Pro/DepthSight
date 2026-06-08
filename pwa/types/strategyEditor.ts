// pwa/types/strategyEditor.ts

export type DynamicParam =
	| number
	| {
			source: string;
			key?: string;
			shift?: number;
			block_id?: string;
			multiplier?: number;
	  };

export type ComponentCategory =
	| "filter"
	| "foundation"
	| "indicator"
	| "logic"
	| "management";

export type ComponentType =
	// Filters
	| "trading_session"
	| "volatility_filter"
	| "trend_filter"
	| "senior_tf_confluence"
	// Foundations
	| "market_activity"
	| "order_book_zone"
	| "l2_microstructure"
	| "l2_microstructure_check"
	| "significant_level"
	| "local_level"
	| "tape_analysis"
	| "classic_pattern"
	| "round_level"
	| "trend_direction"
	| "pattern"
	| "volume_confirmation"
	| "price_consolidation"
	| "return_to_level"
	| "natr_filter"
	| "rel_vol_filter"
	| "order_book_analysis"
	| "tape_acceleration"
	| "tradingview_signal"
	| "aggregated_density_check"
	// Composite Blocks
	| "tape_condition"
	| "order_book_zone_condition"
	| "level_proximity_condition"
	// Indicators
	| "ma_cross_condition"
	| "rsi_condition"
	| "value_comparison"
	| "macd_condition"
	| "bollinger_bands_condition"
	| "stochastic_condition"
	// Genetic Algorithm Aliases (backwards compatibility)
	| "stoch_condition"
	| "bb_condition"
	| "adx_filter"
	| "time_filter"
	| "price_condition"
	| "price_vs_level"
	// Logic
	| "AND"
	| "OR"
	// Management
	| "trailing_stop"
	| "move_to_breakeven"
	| "conditional_exit"
	| "scale_in"
	| "conditional_management"
	| "modify_stop_loss"
	| "modify_take_profit"
	| "close_position"
	| "dca_management"
	| "grid_management"
	// New Filter Blocks
	| "btc_state_filter"
	| "open_interest"
	| "correlation"
	// New Analyzers
	| "level_touch_analyzer"
	| "volatility_squeeze"
	| "price_action_analyzer"
	// Action
	| "open_position";

export interface BaseBlock {
	id: string;
	type: ComponentType;
}

export interface ConditionBlock extends BaseBlock {
	params?: Record<string, unknown>;
	children?: ConditionBlock[];
	isComposite?: boolean;
	compositeType?:
		| "tape_condition"
		| "order_book_zone_condition"
		| "level_proximity_condition";
	displayMode?: "simplified" | "expanded";
}

export interface ManagementBlock extends BaseBlock {
	params?: Record<string, unknown>;
	children?: ConditionBlock[];
	displayMode?: "simplified" | "expanded";
}

export interface TrailingStopBlock extends ManagementBlock {
	type: "trailing_stop";
	params: {
		type: "ATR" | "Percentage" | "Percent";
		value: DynamicParam;
		mode?: string;
	};
}

export interface MoveToBeBlock extends ManagementBlock {
	type: "move_to_breakeven";
	params: {
		target_type: "rr_multiplier" | "percent_from_price" | "atr_multiplier";
		target_value: DynamicParam;
		offset_pips: number;
	};
}

export interface ScaleInBlock extends ManagementBlock {
	type: "scale_in";
	params: {
		add_size_pct_of_initial_risk: number;
		max_entries: number;
	};
	children: ConditionBlock[];
}

export interface ModifyStopLossBlock extends ManagementBlock {
	type: "modify_stop_loss";
	params: {
		new_sl_price: DynamicParam;
	};
}

export interface ModifyTakeProfitBlock extends ManagementBlock {
	type: "modify_take_profit";
	params: {
		new_tp_price: DynamicParam;
	};
}

export interface ClosePositionBlock extends ManagementBlock {
	type: "close_position";
	params?: Record<string, never>;
}

export interface ConditionalManagementBlock extends ManagementBlock {
	type: "conditional_management";
	if_conditions: ConditionBlock;
	then_actions: (
		| ModifyStopLossBlock
		| ModifyTakeProfitBlock
		| ClosePositionBlock
		| TrailingStopBlock
		| MoveToBeBlock
		| ScaleInBlock
	)[];
}

export interface DCAManagementBlock extends ManagementBlock {
	type: "dca_management";
	params: {
		max_safety_orders: number;
		volume_multiplier: number;
		step_type: "percentage" | "custom_condition" | "atr";
		step_value: DynamicParam;
		step_multiplier?: number;
	};
	children: ConditionBlock[];
}

export interface GridManagementBlock extends ManagementBlock {
	type: "grid_management";
	params: {
		range_type: "percentage" | "atr" | "fixed_prices";
		grid_levels: number;
		upper_bound: DynamicParam;
		lower_bound: DynamicParam;
	};
}

export const TOP_LEVEL_MANAGEMENT_BLOCK_TYPES = [
	"trailing_stop",
	"move_to_breakeven",
	"conditional_exit",
	"scale_in",
	"conditional_management",
	"dca_management",
	"grid_management",
] as const;

export const CONDITIONAL_MANAGEMENT_ACTION_TYPES = [
	"modify_stop_loss",
	"modify_take_profit",
	"close_position",
	"trailing_stop",
	"move_to_breakeven",
] as const;

export interface PartialExit {
	id: string;
	size_pct: number;
	tp_type: "rr_multiplier" | "percent_from_price" | "fixed_price";
	tp_value: DynamicParam;
}

export interface ActionBlock extends BaseBlock {
	type: "open_position";
	params: {
		direction: "LONG" | "SHORT" | "BOTH";
		risk_type: "percent_balance" | "fixed_usd" | "fixed_amount";
		risk_value: number;
		sl_type: "atr_multiplier" | "percent_from_price" | "fixed_price";
		sl_value: DynamicParam;
		tp_type: "rr_multiplier" | "percent_from_price" | "fixed_price";
		tp_value: DynamicParam;
		partial_exits: PartialExit[];
		[key: string]: unknown;
	};
}

export interface TriggerState {
	type: "on_candle_close" | "on_tick" | "on_condition_met";
	timeframe: "1m" | "3m" | "5m" | "15m" | "1h" | "4h";
}

export type PlanTier =
	| "free"
	| "standard"
	| "researcher"
	| "pro"
	| "institutional";

export interface StrategyState {
	id: string | null;
	strategy_name: string | null;
	userTier: PlanTier;
	signal_source: "internal" | "tradingview_webhook";
	name: string;
	description: string;
	symbol: string;
	marketType: "FUTURES" | "SPOT";

	min_foundation_weight_threshold: number;
	foundationWeights: Record<string, number>;

	filters: ConditionBlock;
	entryTrigger: TriggerState;
	entryConditions: ConditionBlock;
	initialization: ActionBlock;
	positionManagement: ManagementBlock[];
	useFoundationWeights: boolean;
	oracleRegime: number | null;
	oracleConfidence: number;
	use_ml_confirmation: boolean;
	breakeven_on_regime_change: boolean;
	symbol_selection_mode: "STATIC" | "DYNAMIC_NATR" | "DYNAMIC_ORACLE";
	max_concurrent_symbols: number;
	min_natr: number;
	animationEpoch: number;
	isClearing: boolean;
}
