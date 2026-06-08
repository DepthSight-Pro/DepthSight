// src/stores/strategyEditorStore.ts

import { produce } from "immer";
import { v4 as uuidv4 } from "uuid";
import { create } from "zustand";
import { migrateStrategy } from "@/components/strategy-editor/migration";
import {
	CONDITIONAL_MANAGEMENT_ACTION_TYPES,
	type ComponentType,
	type ConditionalManagementBlock,
	type ConditionBlock,
	type ManagementBlock,
	type ModifyStopLossBlock,
	type MoveToBeBlock,
	type PartialExit,
	type PlanTier,
	type StrategyState,
	type TrailingStopBlock,
} from "@/components/strategy-editor/types";
import i18n from "@/i18n";
import type { StrategyConfigData } from "@/types/api";

export const PRO_BLOCKS: ComponentType[] = [
	"btc_state_filter",
	"correlation",
	"open_interest",
	"tape_condition",
	"order_book_zone_condition",
	"l2_microstructure",
	"conditional_exit",
	"scale_in",
	"conditional_management",
];

export const isBlockPro = (type: ComponentType): boolean =>
	PRO_BLOCKS.includes(type);

export const isStrategyProOnly = (state: StrategyState): boolean => {
	const checkNode = (node: ConditionBlock | null): boolean => {
		if (!node) return false;
		if (isBlockPro(node.type)) return true;
		if (node.children) return node.children.some(checkNode);
		return false;
	};

	if (checkNode(state.filters)) return true;
	if (checkNode(state.entryConditions)) return true;
	if (state.positionManagement.some((m) => isBlockPro(m.type))) return true;
	if (state.initialization.params.partial_exits?.length > 0) return true;

	return false;
};

// --- Tree utilities ---
const findBlockAndParentRecursive = (
	root: ConditionBlock,
	blockId: string,
): {
	parent: ConditionBlock | null;
	block: ConditionBlock | null;
	index: number;
} => {
	if (root.children) {
		for (let i = 0; i < root.children.length; i++) {
			const child = root.children[i];
			if (child.id === blockId) return { parent: root, block: child, index: i };
			const found = findBlockAndParentRecursive(child, blockId);
			if (found.block) return found;
		}
	}
	return { parent: null, block: null, index: -1 };
};

const findBlockAndParentInManagement = (
	roots: ManagementBlock[],
	blockId: string,
): {
	parent: ManagementBlock | ConditionBlock | ConditionalManagementBlock | null;
	block: ConditionBlock | ManagementBlock | null;
	index: number;
} => {
	for (const root of roots) {
		if (root.id === blockId) return { parent: null, block: root, index: -1 };
		if (root.children) {
			for (let i = 0; i < root.children.length; i++) {
				const child = root.children[i];
				if (child.id === blockId)
					return { parent: root, block: child, index: i };
				const tempRoot: ConditionBlock = {
					id: "tempRoot",
					type: "AND",
					children: root.children,
				};
				const foundInChild = findBlockAndParentRecursive(tempRoot, blockId);
				if (foundInChild.block)
					return {
						...foundInChild,
						parent:
							foundInChild.parent === tempRoot ? root : foundInChild.parent,
					};
			}
		}
		if (
			"if_conditions" in root &&
			(root as ConditionalManagementBlock).if_conditions
		) {
			if ((root as ConditionalManagementBlock).if_conditions.id === blockId)
				return {
					parent: root,
					block: (root as ConditionalManagementBlock).if_conditions,
					index: -1,
				};
			const foundInIf = findBlockAndParentRecursive(
				(root as ConditionalManagementBlock).if_conditions,
				blockId,
			);
			if (foundInIf.block) return foundInIf;
		}
		if (
			"then_actions" in root &&
			(root as ConditionalManagementBlock).then_actions
		) {
			const thenActions = (root as ConditionalManagementBlock).then_actions;
			for (let i = 0; i < thenActions.length; i++) {
				const action = thenActions[i];
				if (action.id === blockId)
					return { parent: root, block: action as ManagementBlock, index: i };
			}
		}
	}
	return { parent: null, block: null, index: -1 };
};

const findBlockRecursive = (
	root: ConditionBlock,
	blockId: string,
): ConditionBlock | null => {
	if (root.id === blockId) return root;
	if (root.children) {
		for (const child of root.children) {
			const found = findBlockRecursive(child, blockId);
			if (found) return found;
		}
	}
	return null;
};

const addBlockToParent = (
	root: ConditionBlock,
	parentId: string,
	newBlock: ConditionBlock,
): boolean => {
	if (
		root.id === parentId &&
		["AND", "OR", "senior_tf_confluence"].includes(root.type)
	) {
		root.children = [...(root.children || []), newBlock];
		return true;
	}
	if (root.children) {
		for (const child of root.children) {
			if (addBlockToParent(child, parentId, newBlock)) return true;
		}
	}
	return false;
};

const normalizeFoundationWeightKey = (blockId: string): string => {
	return blockId.startsWith("w_") ? blockId.slice(2) : blockId;
};

const normalizeFoundationWeights = (
	weights: Record<string, number> | null | undefined,
): Record<string, number> => {
	if (!weights || typeof weights !== "object") {
		return {};
	}

	return Object.entries(weights).reduce<Record<string, number>>(
		(acc, [key, value]) => {
			acc[normalizeFoundationWeightKey(key)] = value;
			return acc;
		},
		{},
	);
};

const VISUAL_BUILDER_STRATEGY_NAME = "VisualBuilderStrategy";

const hasVisualStrategyShape = (value: unknown): boolean => {
	return Boolean(
		value &&
			typeof value === "object" &&
			("entryConditions" in value ||
				"filters" in value ||
				"initialization" in value ||
				"positionManagement" in value),
	);
};

const resolveRuntimeStrategyName = (
	strategyName: string | null | undefined,
	strategyConfig?: unknown,
): string => {
	if (strategyName === "GeneticStrategy") {
		return "GeneticStrategy";
	}
	if (!strategyName || hasVisualStrategyShape(strategyConfig)) {
		return VISUAL_BUILDER_STRATEGY_NAME;
	}
	return strategyName;
};

const cloneJsonLike = <T>(value: T): T => {
	if (value === undefined || value === null) {
		return value;
	}
	return JSON.parse(JSON.stringify(value)) as T;
};

const cloneConditionTree = (block: ConditionBlock): ConditionBlock => {
	const clonedBlock: ConditionBlock = { ...block };

	if (block.params) {
		clonedBlock.params = cloneJsonLike(block.params);
	}
	if (block.children) {
		clonedBlock.children = block.children.map(cloneConditionTree);
	}

	return clonedBlock;
};

const buildSerializedPmConditionsRoot = (
	block: ManagementBlock,
): ConditionBlock | null => {
	if (
		!["conditional_exit", "scale_in", "dca_management"].includes(block.type)
	) {
		return null;
	}

	const existingRoot = block.params?.conditions;
	const sourceChildren = Array.isArray(block.children)
		? block.children
		: Array.isArray(existingRoot?.children)
			? existingRoot.children
			: [];

	if (!existingRoot && sourceChildren.length === 0) {
		return null;
	}

	return {
		...(existingRoot && typeof existingRoot === "object"
			? cloneJsonLike(existingRoot)
			: {}),
		id: existingRoot?.id || `${block.id}_conditions_root`,
		type: existingRoot?.type === "OR" ? "OR" : "AND",
		children: sourceChildren.map(cloneConditionTree),
	};
};

const serializeManagementBlock = (block: ManagementBlock): ManagementBlock => {
	if (block.type === "conditional_management") {
		const conditionalBlock = block as ConditionalManagementBlock;
		return {
			...conditionalBlock,
			params: cloneJsonLike(conditionalBlock.params),
			if_conditions: cloneConditionTree(conditionalBlock.if_conditions),
			then_actions: conditionalBlock.then_actions.map(
				(action) =>
					serializeManagementBlock(
						action as ManagementBlock,
					) as ConditionalManagementBlock["then_actions"][number],
			),
		} as ConditionalManagementBlock;
	}

	const serializedBlock: ManagementBlock = {
		...block,
		...(block.params ? { params: cloneJsonLike(block.params) } : {}),
	};

	delete (serializedBlock as Partial<ManagementBlock>).children;

	const conditionsRoot = buildSerializedPmConditionsRoot(block);
	if (conditionsRoot) {
		if (block.type === "dca_management") {
			serializedBlock.params = {
				...(serializedBlock.params || {}),
				step_value: conditionsRoot,
			};
		} else {
			serializedBlock.params = {
				...(serializedBlock.params || {}),
				conditions: conditionsRoot,
			};
		}
	} else if (serializedBlock.params) {
		if (block.type === "dca_management") {
			if (serializedBlock.params.step_type === "custom_condition") {
				delete serializedBlock.params.step_value;
			}
		} else {
			delete serializedBlock.params.conditions;
		}
	}

	return serializedBlock;
};

const getDefaultBlockParams = (
	type: ComponentType,
): Record<string, unknown> => {
	switch (type) {
		case "trading_session":
			return { session: "london" };
		case "volatility_filter":
			return { indicator: "ATR", operator: "gt", value: 1.5 };
		case "trend_filter":
			return { indicator: "ADX", threshold: 25.0 };
		case "senior_tf_confluence":
			return { timeframe: "1h" };
		case "market_activity":
			return {
				mode: "percentile",
				natr_threshold: 1.0,
				rel_vol_threshold: 1.5,
			};
		case "natr_filter":
			return { natr_threshold: 1.0 };
		case "rel_vol_filter":
			return { mode: "relative", rel_vol_threshold: 1.5 };
		case "significant_level":
			return {
				level_type: "daily_high",
				proximity_type: "percentage",
				proximity_value: 0.2,
			};
		case "round_level":
			return { proximity_type: "percentage", proximity_value: 0.2 };
		case "trend_direction":
			return {
				timeframe: "15m",
				required_trend: "LONG",
				fast_period: 10,
				slow_period: 50,
				rsi_period: 14,
				rsi_lower_bound: 40,
				rsi_upper_bound: 60,
			};
		case "volume_confirmation":
			return { multiplier: 1.5 };
		case "local_level":
			return {
				timeframe: "1h",
				lookback_period: 24,
				level_type: "high",
				proximity_type: "percentage",
				proximity_value: 0.2,
				is_data_provider: false,
			};
		case "tape_analysis":
			return { time_window_sec: 5 };
		case "order_book_zone":
			return { side: "bids", range_type: "Percentage", range_value: 1.0 };
		case "l2_microstructure":
		case "l2_microstructure_check":
			return {
				check_type: "large_order",
				single_order_size_usd: 250000,
				side: "bids",
				levels_to_scan: 200,
			};
		case "classic_pattern":
			return { pattern_name: "bullish_engulfing" };
		case "price_consolidation":
			return { lookback_period: 10, max_range_atr: 0.8, timeframe: "auto" };
		case "return_to_level":
			return {
				level_block_id: null,
				retest_type: "touch",
				approach_direction: "any",
				confirmation_time_sec: 5,
				cooldown_sec: 60,
				proximity_type: "atr_multiplier",
				proximity_value: 0.1,
				departure_type: "atr_multiplier",
				departure_value: 1.5,
			};
		case "value_comparison":
			return { operator: "gt", rightOperand: 0 };
		case "rsi_condition":
			return { period: 14, operator: "gt", value: 70, shift: 0 };
		case "ma_cross_condition":
			return {
				fast_period: 9,
				slow_period: 21,
				ma_type: "ema",
				shift: 0,
				operator: "crosses_above",
			};
		case "macd_condition":
			return {
				fast_period: 12,
				slow_period: 26,
				signal_period: 9,
				condition: "macd_cross_above_signal",
				shift: 0,
			};
		case "bollinger_bands_condition":
			return {
				period: 20,
				std_dev: 2,
				source: "close",
				location: "above_upper",
				shift: 0,
			};
		case "stochastic_condition":
			return {
				k_period: 14,
				d_period: 3,
				smoothing: 3,
				condition: "k_cross_above_d",
				shift: 0,
			};
		case "price_vs_level":
			return {
				price_source: { source: "candle", key: "close", shift: 0 },
				operator: "gt",
				level_source: null,
			};
		case "btc_state_filter":
			return { required_state: "Consolidation" };
		case "open_interest":
			return { analyze: "change_pct", lookback: 5, operator: "gt", value: 1.0 };
		case "correlation":
			return { lookback: 50, operator: "lt", value: 0.7 };
		case "scale_in":
			return { add_size_pct_of_initial_risk: 100, max_entries: 3 };
		case "modify_stop_loss":
			return {};
		case "modify_take_profit":
			return {};
		case "close_position":
			return {};
		case "trailing_stop":
			return { type: "Percentage", value: 2.0, mode: "local" };
		case "move_to_breakeven":
			return {
				target_type: "rr_multiplier",
				target_value: 1.0,
				offset_pips: 2,
			};
		case "dca_management":
			return {
				max_safety_orders: 5,
				volume_multiplier: 1.5,
				step_type: "percentage",
				step_value: 1.0,
			};
		case "grid_management":
			return {
				grid_levels: 10,
				range_type: "percentage",
				upper_bound: 5.0,
				lower_bound: 5.0,
			};
		case "level_touch_analyzer":
			return {
				level_source: null,
				lookback_candles: 50,
				touch_tolerance_pct: 0.1,
				invalidate_on_pierce: true,
				min_touches: 3,
			};
		case "volatility_squeeze":
			return { lookback_candles: 20, squeeze_ratio: 0.6 };
		case "price_action_analyzer":
			return {
				structure_type: "higher_lows",
				lookback_candles: 30,
				min_points: 2,
				order: 3,
			};
		case "tradingview_signal":
			return { signal_id: "buy_signal_1", ttl_seconds: 60 };
		default:
			return {};
	}
};

// --- Factories for creating new blocks ---
const createNewBlock = (
	type: ComponentType,
): ConditionBlock | ManagementBlock => {
	const id = uuidv4();
	if (type === "conditional_management") {
		return {
			id,
			type,
			if_conditions: { id: uuidv4(), type: "AND", children: [] },
			then_actions: [],
		} as ConditionalManagementBlock;
	}
	const base = { id, type, params: getDefaultBlockParams(type) };
	const hasChildren = [
		"AND",
		"OR",
		"senior_tf_confluence",
		"conditional_exit",
		"scale_in",
		"dca_management",
	].includes(type);
	return { ...base, ...(hasChildren && { children: [] }) };
};
const createNewPartialExit = (): PartialExit => ({
	id: uuidv4(),
	size_pct: 50,
	tp_type: "rr_multiplier",
	tp_value: 1.0,
});

const normalizeTapeOutputKey = (key?: string): string => {
	if (!key) return "total_volume_usd";
	if (key.startsWith("tape_accel_mult_volume_"))
		return "acceleration_multiplier_volume";
	if (key.startsWith("tape_accel_mult_count_"))
		return "acceleration_multiplier_count";
	if (key.startsWith("tape_"))
		return key.replace(/^tape_/, "").replace(/_\d+s$/, "");
	return key;
};

// --- Initial state ---
const getDefaultInitialState = (): StrategyState => ({
	id: null,
	strategy_name: "VisualBuilderStrategy",
	userTier: "free",
	signal_source: "internal",
	name: i18n.t("strategy-editor:defaultStrategyName", "New Strategy"),
	description: "",
	symbol: "BTCUSDT",
	marketType: "FUTURES",
	min_foundation_weight_threshold: 0,
	filters: { id: "filters_root", type: "AND", children: [] },
	entryTrigger: { type: "on_candle_close", timeframe: "5m" },
	entryConditions: { id: "entry_root", type: "AND", children: [] },
	initialization: {
		id: "init_action_1",
		type: "open_position",
		params: {
			direction: "LONG",
			risk_type: "percent_balance",
			risk_value: 1.0,
			sl_type: "atr_multiplier",
			sl_value: 1.5,
			tp_type: "rr_multiplier",
			tp_value: 2.0,
			partial_exits: [],
		},
	},
	positionManagement: [],
	useFoundationWeights: false,
	foundationWeights: {},
	oracleRegime: null,
	oracleConfidence: 0,
	use_ml_confirmation: false,
	breakeven_on_regime_change: false,
	symbol_selection_mode: "STATIC",
	max_concurrent_symbols: 5,
	min_natr: 0.5,
	animationEpoch: 0,
	isClearing: false,
});

type StateKey = "filters" | "entryConditions";

// --- Factory for creating composite blocks ---
const createCompositeBlock = (
	compositeType: NonNullable<ConditionBlock["compositeType"]>,
): ConditionBlock => {
	const compositeBlockId = uuidv4();

	if (compositeType === "tape_condition") {
		const provider = createNewBlock("tape_analysis") as ConditionBlock;
		const consumer = createNewBlock("value_comparison") as ConditionBlock;
		consumer.params = {
			...consumer.params,
			leftOperand: {
				source: "block_result",
				block_id: provider.id,
				key: "total_volume_usd",
			},
		};
		return {
			id: compositeBlockId,
			type: "AND",
			isComposite: true,
			compositeType,
			children: [provider, consumer],
		};
	}
	if (compositeType === "order_book_zone_condition") {
		const provider = createNewBlock("order_book_zone") as ConditionBlock;
		const consumer = createNewBlock("value_comparison") as ConditionBlock;
		consumer.params = {
			...consumer.params,
			leftOperand: {
				source: "block_result",
				block_id: provider.id,
				key: "total_volume_usd",
			},
			rightOperand: 1000000,
		};
		return {
			id: compositeBlockId,
			type: "AND",
			isComposite: true,
			compositeType,
			children: [provider, consumer],
		};
	}
	if (compositeType === "level_proximity_condition") {
		const provider = createNewBlock("local_level") as ConditionBlock;
		return {
			id: compositeBlockId,
			type: "AND",
			isComposite: true,
			compositeType,
			children: [provider],
		};
	}

	return {
		id: compositeBlockId,
		type: "AND",
		isComposite: true,
		compositeType,
		children: [],
	};
};

interface EditorActions {
	toJson: () => StrategyConfigData;
	loadState: (strategy: unknown) => void;
	loadStrategy: (strategy: unknown) => void;
	loadDiscoveredStrategy: (strategy: Record<string, unknown>) => void;
	setStrategyField: <
		K extends keyof Omit<
			StrategyState,
			| "id"
			| "filters"
			| "entryTrigger"
			| "entryConditions"
			| "initialization"
			| "positionManagement"
		>,
	>(
		field: K,
		value: StrategyState[K],
	) => void;
	setTrigger: (trigger: Partial<StrategyState["entryTrigger"]>) => void;
	setInitializationParam: (key: string, value: unknown) => void;

	addCondition: (
		target: StateKey,
		type: ComponentType,
		parentId: string | null,
		blockToInsert?: ConditionBlock,
	) => void;
	removeCondition: (target: StateKey, blockId: string) => void;
	updateConditionParams: (
		target: StateKey,
		blockId: string,
		newParams: Record<string, unknown>,
	) => void;
	moveCondition: (target: StateKey, activeId: string, overId: string) => void;

	addManagementBlock: (type: ComponentType, index?: number) => void;
	removeManagementBlock: (blockId: string) => void;
	updateManagementBlockParams: (
		blockId: string,
		newParams: Record<string, unknown>,
	) => void;
	addConditionToManagementBlock: (
		blockId: string,
		componentTypeOrBlock: ComponentType | ConditionBlock,
	) => void;
	addConditionToConditionalManagementBlock: (
		blockId: string,
		componentTypeOrBlock: ComponentType | ConditionBlock,
	) => void;
	addActionToConditionalManagementBlock: (
		blockId: string,
		componentTypeOrBlock: ComponentType | ManagementBlock,
	) => void;

	removeBlock: (blockId: string) => void;
	updateBlockParams: (
		blockId: string,
		newParams: Record<string, unknown>,
	) => void;
	findBlock: (blockId: string) => ConditionBlock | ManagementBlock | null;

	addCompositeCondition: (
		targetZone: StateKey,
		compositeType: NonNullable<ConditionBlock["compositeType"]>,
	) => void;
	updateCompositeConditionParams: (
		blockId: string,
		newSimpleParams: Record<string, unknown>,
	) => void;

	addPartialExit: () => void;
	updatePartialExit: (
		id: string,
		field: keyof Omit<PartialExit, "id">,
		value: unknown,
	) => void;
	removePartialExit: (id: string) => void;

	updateFoundationWeight: (blockType: string, weight: number) => void;
	saveFoundationWeights: () => void;
	setUseFoundationWeights: (value: boolean) => void;

	setOracleRegime: (regime: number | null) => void;
	setOracleConfidence: (confidence: number) => void;
	setUseMlConfirmation: (value: boolean) => void;
	setBreakevenOnRegimeChange: (value: boolean) => void;

	setUserTier: (tier: PlanTier) => void;
	startClearing: () => void;
	reset: () => void;
}

export const useStrategyEditorStore = create<StrategyState & EditorActions>(
	(set, get) => ({
		...getDefaultInitialState(),

		toJson: (): StrategyConfigData => {
			const state = get();
			const strategyName = resolveRuntimeStrategyName(
				state.strategy_name,
				state,
			);
			const shouldUseFoundationWeights =
				state.signal_source !== "tradingview_webhook" &&
				state.useFoundationWeights;

			return {
				strategy_name: strategyName,
				signal_source: state.signal_source,
				symbol: state.symbol,
				marketType: state.marketType,
				min_foundation_weight_threshold: shouldUseFoundationWeights
					? state.min_foundation_weight_threshold
					: 0,
				foundation_weights: shouldUseFoundationWeights
					? state.foundationWeights
					: null,
				filters: state.filters,
				entryTrigger: state.entryTrigger,
				entryConditions: state.entryConditions,
				initialization: state.initialization,
				positionManagement: state.positionManagement.map(
					serializeManagementBlock,
				),
				oracle_regime: state.oracleRegime,
				oracle_confidence: state.oracleConfidence,
				use_ml_confirmation: state.use_ml_confirmation,
				breakeven_on_regime_change: state.breakeven_on_regime_change,
			};
		},

		loadState: (strategy) =>
			set(
				produce((draft: StrategyState) => {
					console.log("=== START LOADING STRATEGY ===");
					console.log("Strategy received:", strategy);

					const strat = strategy as Record<string, unknown>;
					const configData =
						(strat.config_data as Record<string, unknown>) || {};
					const flattenedData = migrateStrategy(
						strat.config_data
							? { ...strat, ...(strat.config_data as Record<string, unknown>) }
							: strat,
					) as StrategyState;
					const defaults = getDefaultInitialState();

					draft.id = strat.id || null;
					draft.name = strat.name || defaults.name;
					draft.description = strat.description || defaults.description;
					draft.strategy_name = resolveRuntimeStrategyName(
						flattenedData.strategy_name ||
							strat.strategy_name ||
							defaults.strategy_name,
						flattenedData,
					);
					draft.signal_source =
						flattenedData.signal_source ||
						strat.signal_source ||
						defaults.signal_source;
					draft.symbol =
						flattenedData.symbol || strat.symbol || defaults.symbol;
					draft.marketType =
						flattenedData.marketType || strat.marketType || defaults.marketType;
					draft.min_foundation_weight_threshold =
						flattenedData.min_foundation_weight_threshold ??
						strat.min_foundation_weight_threshold ??
						defaults.min_foundation_weight_threshold;

					// New fields for oracle and ML
					draft.oracleRegime =
						flattenedData.oracle_regime ??
						strat.oracle_regime ??
						defaults.oracleRegime;
					draft.oracleConfidence =
						flattenedData.oracle_confidence ??
						strat.oracle_confidence ??
						defaults.oracleConfidence;
					draft.use_ml_confirmation =
						flattenedData.use_ml_confirmation ??
						strat.use_ml_confirmation ??
						defaults.use_ml_confirmation;
					draft.breakeven_on_regime_change =
						flattenedData.breakeven_on_regime_change ??
						strat.breakeven_on_regime_change ??
						defaults.breakeven_on_regime_change;

					// Symbol selection fields
					let mode =
						strat.symbol_selection_mode || defaults.symbol_selection_mode;
					if (mode === "DYNAMIC") {
						// Refining the mode based on existing settings
						if (
							flattenedData.oracle_settings ||
							strat.oracle_regime !== undefined
						) {
							mode = "DYNAMIC_ORACLE";
						} else {
							mode = "DYNAMIC_NATR";
						}
					}
					draft.symbol_selection_mode =
						mode as StrategyState["symbol_selection_mode"];
					draft.max_concurrent_symbols =
						flattenedData.max_concurrent_symbols ??
						strat.max_concurrent_symbols ??
						defaults.max_concurrent_symbols;
					draft.min_natr =
						flattenedData.natr_settings?.min_natr ??
						strat.min_natr ??
						defaults.min_natr;

					// If a specific symbol came in the AI config, force STATIC mode
					const incomingSymbol =
						flattenedData.symbol || configData.symbol || strat.symbol;
					if (
						incomingSymbol &&
						incomingSymbol !== "BTCUSDT" &&
						incomingSymbol !== "GENETIC"
					) {
						draft.symbol_selection_mode = "STATIC";
					}

					if (flattenedData.filters)
						draft.filters = { ...defaults.filters, ...flattenedData.filters };
					if (flattenedData.entryTrigger)
						draft.entryTrigger = {
							...defaults.entryTrigger,
							...flattenedData.entryTrigger,
						};
					if (flattenedData.entryConditions) {
						draft.entryConditions = {
							...defaults.entryConditions,
							...flattenedData.entryConditions,
						};
						draft.useFoundationWeights =
							flattenedData.entryConditions.type === "OR";
					}
					if (flattenedData.initialization) {
						draft.initialization = {
							...defaults.initialization,
							...flattenedData.initialization,
							params: {
								...defaults.initialization.params,
								...(flattenedData.initialization.params || {}),
							},
						};
					}
					if (flattenedData.positionManagement)
						draft.positionManagement = flattenedData.positionManagement;

					const weightsToLoad =
						strat.foundation_weights ||
						strat.foundationWeights ||
						configData.foundation_weights ||
						flattenedData.foundation_weights;

					if (weightsToLoad && typeof weightsToLoad === "object") {
						draft.foundationWeights = normalizeFoundationWeights(weightsToLoad);
						if (Object.keys(draft.foundationWeights).length > 0) {
							draft.useFoundationWeights = true;
						}
					} else {
						draft.foundationWeights = {};
					}

					console.log("=== END LOADING STRATEGY ===");
				}),
			),

		loadStrategy: (strategy) => {
			get().loadState(strategy);
			set((s) => ({ animationEpoch: s.animationEpoch + 1 }));
		},

		loadDiscoveredStrategy: (strategyJson) => {
			const newStructure: Partial<StrategyState> = {
				strategy_name: strategyJson.strategy_name || "GeneticStrategy",
				signal_source: strategyJson.signal_source || "internal",
				name: strategyJson.name,
				symbol: strategyJson.symbol,
				marketType: strategyJson.marketType,
				entryTrigger: strategyJson.entryTrigger || strategyJson.trigger,
				entryConditions: strategyJson.entryConditions ||
					strategyJson.conditions || {
						id: uuidv4(),
						type: "AND",
						children: [],
					},
				initialization: strategyJson.initialization || strategyJson.action,
				positionManagement: strategyJson.positionManagement || [],
			};
			get().loadState(newStructure);
		},

		setStrategyField: (field, value) =>
			set({ [field]: value } as unknown as Partial<StrategyState>),
		setTrigger: (trigger) =>
			set(
				produce((draft: StrategyState) => {
					draft.entryTrigger = { ...draft.entryTrigger, ...trigger };
				}),
			),
		setInitializationParam: (key, value) =>
			set(
				produce((draft: StrategyState) => {
					draft.initialization.params[key] = value;
				}),
			),

		addCondition: (target, type, parentId, blockToInsert) =>
			set(
				produce((draft: StrategyState) => {
					let newBlock: ConditionBlock;
					if (blockToInsert) {
						newBlock = blockToInsert;
					} else if (
						[
							"tape_condition",
							"order_book_zone_condition",
							"level_proximity_condition",
						].includes(type)
					) {
						newBlock = createCompositeBlock(
							type as NonNullable<ConditionBlock["compositeType"]>,
						);
					} else {
						newBlock = createNewBlock(type) as ConditionBlock;
					}

					if (
						!parentId ||
						parentId.includes("root") ||
						parentId.includes("drop-zone")
					) {
						draft[target].children?.push(newBlock);
					} else {
						const added = addBlockToParent(draft[target], parentId, newBlock);
						if (!added) {
							draft[target].children?.push(newBlock);
						}
					}
				}),
			),

		removeCondition: (target, blockId) =>
			set(
				produce((draft: StrategyState) => {
					const { parent, index } = findBlockAndParentRecursive(
						draft[target],
						blockId,
					);
					if (parent && index > -1) {
						parent.children?.splice(index, 1);
					}
				}),
			),

		removeBlock: (blockId: string) =>
			set(
				produce((draft: StrategyState) => {
					let found = findBlockAndParentRecursive(draft.filters, blockId);
					if (found.parent) {
						found.parent.children?.splice(found.index, 1);
						return;
					}
					found = findBlockAndParentRecursive(draft.entryConditions, blockId);
					if (found.parent) {
						found.parent.children?.splice(found.index, 1);
						return;
					}
					const { parent, index } = findBlockAndParentInManagement(
						draft.positionManagement,
						blockId,
					);
					if (parent && index > -1) {
						if ("children" in parent && parent.children) {
							(parent.children as (ConditionBlock | ManagementBlock)[]).splice(
								index,
								1,
							);
						} else if (
							"if_conditions" in parent &&
							(parent as ConditionalManagementBlock).if_conditions?.children
						) {
							(
								parent as ConditionalManagementBlock
							).if_conditions.children?.splice(index, 1);
						} else if (
							"then_actions" in parent &&
							(parent as ConditionalManagementBlock).then_actions
						) {
							(parent as ConditionalManagementBlock).then_actions.splice(
								index,
								1,
							);
						}
					} else {
						draft.positionManagement = draft.positionManagement.filter(
							(b: ManagementBlock) => b.id !== blockId,
						);
					}
				}),
			),

		findBlock: (blockId) => {
			const state = get();
			let block = findBlockRecursive(state.filters, blockId);
			if (block) return block;
			block = findBlockRecursive(state.entryConditions, blockId);
			if (block) return block;

			const findInManagement = (
				roots: ManagementBlock[],
			): ManagementBlock | ConditionBlock | null => {
				for (const root of roots) {
					if (root.id === blockId) return root;
					if (root.children) {
						const tempRoot: ConditionBlock = {
							id: "temp",
							type: "AND",
							children: root.children,
						};
						const found = findBlockRecursive(tempRoot, blockId);
						if (found) return found;
					}
					if (
						"if_conditions" in root &&
						(root as ConditionalManagementBlock).if_conditions
					) {
						if (
							(root as ConditionalManagementBlock).if_conditions.id === blockId
						)
							return (root as ConditionalManagementBlock).if_conditions;
						const found = findBlockRecursive(
							(root as ConditionalManagementBlock).if_conditions,
							blockId,
						);
						if (found) return found;
					}
					if (
						"then_actions" in root &&
						(root as ConditionalManagementBlock).then_actions
					) {
						const found = findInManagement(
							(root as ConditionalManagementBlock)
								.then_actions as ManagementBlock[],
						);
						if (found) return found;
					}
				}
				return null;
			};
			return findInManagement(state.positionManagement);
		},

		updateConditionParams: (target, blockId, newParams) =>
			set(
				produce((draft: StrategyState) => {
					const { block } = findBlockAndParentRecursive(draft[target], blockId);
					if (block) block.params = { ...block.params, ...newParams };
				}),
			),

		updateBlockParams: (blockId, newParams) =>
			set(
				produce((draft: StrategyState) => {
					const findAndUpdate = (
						root: ConditionBlock | ManagementBlock | null,
					): boolean => {
						if (!root) return false;
						if (root.id === blockId) {
							root.params = { ...(root.params || {}), ...newParams };
							return true;
						}
						if (root.children)
							for (const child of root.children)
								if (findAndUpdate(child)) return true;

						const condRoot = root as unknown as ConditionalManagementBlock;
						if (condRoot.if_conditions)
							if (findAndUpdate(condRoot.if_conditions)) return true;
						if (condRoot.then_actions)
							for (const action of condRoot.then_actions)
								if (findAndUpdate(action as unknown as ManagementBlock))
									return true;

						return false;
					};
					if (findAndUpdate(draft.filters)) return;
					if (findAndUpdate(draft.entryConditions)) return;
					for (const pm of draft.positionManagement)
						if (findAndUpdate(pm)) return;
				}),
			),

		addCompositeCondition: (targetZone, compositeType) =>
			set(
				produce((draft: StrategyState) => {
					const newCompositeBlock = createCompositeBlock(compositeType);
					if (draft[targetZone].children) {
						draft[targetZone].children?.push(newCompositeBlock);
					}
				}),
			),

		updateCompositeConditionParams: (blockId, newSimpleParams) =>
			set(
				produce((draft: StrategyState) => {
					const parentBlock =
						findBlockRecursive(draft.filters, blockId) ||
						findBlockRecursive(draft.entryConditions, blockId);
					if (!parentBlock?.isComposite || !parentBlock.children) return;

					const [provider, consumer] = parentBlock.children;

					switch (parentBlock.compositeType) {
						case "tape_condition":
							if (provider?.params && consumer?.params) {
								const leftOp = consumer.params.leftOperand as Record<
									string,
									unknown
								>;
								if (newSimpleParams.metric !== undefined)
									leftOp.key = normalizeTapeOutputKey(
										newSimpleParams.metric as string,
									);
								if (newSimpleParams.operator !== undefined)
									consumer.params.operator = newSimpleParams.operator;
								if (newSimpleParams.value !== undefined)
									consumer.params.rightOperand = newSimpleParams.value;
								if (newSimpleParams.time_window_sec !== undefined) {
									provider.params.time_window_sec =
										newSimpleParams.time_window_sec;
									leftOp.key = normalizeTapeOutputKey(leftOp.key);
								}
							}
							break;
						case "order_book_zone_condition":
							if (provider?.params && consumer?.params) {
								const leftOp = consumer.params.leftOperand as Record<
									string,
									unknown
								>;
								if (newSimpleParams.metric !== undefined)
									leftOp.key = newSimpleParams.metric;
								if (newSimpleParams.side !== undefined)
									provider.params.side = newSimpleParams.side;
								if (newSimpleParams.range_value !== undefined)
									provider.params.range_value = newSimpleParams.range_value;
								if (newSimpleParams.range_type !== undefined)
									provider.params.range_type = newSimpleParams.range_type;
								if (newSimpleParams.operator !== undefined)
									consumer.params.operator = newSimpleParams.operator;
								if (newSimpleParams.value !== undefined)
									consumer.params.rightOperand = newSimpleParams.value;
							}
							break;
						case "level_proximity_condition":
							if (provider?.params) {
								if (newSimpleParams.price_source !== undefined)
									provider.params.price_source = newSimpleParams.price_source;
								if (newSimpleParams.timeframe !== undefined)
									provider.params.timeframe = newSimpleParams.timeframe;
								if (newSimpleParams.level_type !== undefined)
									provider.params.level_type = newSimpleParams.level_type;
								if (newSimpleParams.lookback_period !== undefined)
									provider.params.lookback_period =
										newSimpleParams.lookback_period;
								if (newSimpleParams.proximity_value !== undefined)
									provider.params.proximity_value =
										newSimpleParams.proximity_value;
								if (newSimpleParams.proximity_type !== undefined)
									provider.params.proximity_type =
										newSimpleParams.proximity_type;
								if (newSimpleParams.is_data_provider !== undefined)
									provider.params.is_data_provider =
										newSimpleParams.is_data_provider;
							}
							break;
					}
				}),
			),

		moveCondition: (target, activeId, overId) =>
			set(
				produce((draft: StrategyState) => {
					const root = draft[target];
					const {
						parent: activeParent,
						block: activeBlock,
						index: activeIndex,
					} = findBlockAndParentRecursive(root, activeId);
					if (!activeBlock || !activeParent) return;
					activeParent.children?.splice(activeIndex, 1);
					const { parent: overParent, index: overIndex } =
						findBlockAndParentRecursive(root, overId);
					if (overParent) {
						overParent.children?.splice(overIndex, 0, activeBlock);
					} else {
						const overContainer = findBlockRecursive(root, overId);
						if (overContainer?.children) {
							overContainer.children.push(activeBlock);
						} else {
							root.children?.push(activeBlock);
						}
					}
				}),
			),

		addManagementBlock: (type, index) =>
			set(
				produce((draft: StrategyState) => {
					const newBlock = createNewBlock(type) as ManagementBlock;
					if (index !== undefined) {
						draft.positionManagement.splice(index, 0, newBlock);
					} else {
						draft.positionManagement.push(newBlock);
					}
				}),
			),
		removeManagementBlock: (blockId) =>
			set(
				produce((draft: StrategyState) => {
					draft.positionManagement = draft.positionManagement.filter(
						(b: ManagementBlock) => b.id !== blockId,
					);
				}),
			),
		updateManagementBlockParams: (blockId, newParams) =>
			set(
				produce((draft: StrategyState) => {
					const block = draft.positionManagement.find(
						(b: ManagementBlock) => b.id === blockId,
					);
					if (block?.params) {
						Object.assign(block.params, newParams);
					}
				}),
			),
		addConditionToManagementBlock: (blockId, typeOrBlock) =>
			set(
				produce((draft: StrategyState) => {
					let newBlock: ConditionBlock;
					if (typeof typeOrBlock !== "string") {
						newBlock = typeOrBlock;
					} else if (
						[
							"tape_condition",
							"order_book_zone_condition",
							"level_proximity_condition",
						].includes(typeOrBlock)
					) {
						newBlock = createCompositeBlock(
							typeOrBlock as NonNullable<ConditionBlock["compositeType"]>,
						);
					} else {
						newBlock = createNewBlock(
							typeOrBlock as ComponentType,
						) as ConditionBlock;
					}

					// 1. Direct addition to the management block root
					const rootBlock = draft.positionManagement.find(
						(b: ManagementBlock) => b.id === blockId,
					);
					if (rootBlock && "children" in rootBlock) {
						if (!rootBlock.children) rootBlock.children = [];
						rootBlock.children.push(newBlock);
						return;
					}

					// 2. Recursive addition to logical blocks inside Position Management
					for (const root of draft.positionManagement) {
						if (root.children) {
							for (const child of root.children) {
								if (addBlockToParent(child, blockId, newBlock)) return;
							}
						}
						if (
							"if_conditions" in root &&
							(root as ConditionalManagementBlock).if_conditions
						) {
							if (
								addBlockToParent(
									(root as ConditionalManagementBlock).if_conditions,
									blockId,
									newBlock,
								)
							)
								return;
						}
					}
				}),
			),
		addConditionToConditionalManagementBlock: (blockId, typeOrBlock) =>
			set(
				produce((draft: StrategyState) => {
					let newBlock: ConditionBlock;
					if (typeof typeOrBlock !== "string") {
						newBlock = typeOrBlock;
					} else if (
						[
							"tape_condition",
							"order_book_zone_condition",
							"level_proximity_condition",
						].includes(typeOrBlock)
					) {
						newBlock = createCompositeBlock(
							typeOrBlock as NonNullable<ConditionBlock["compositeType"]>,
						);
					} else {
						newBlock = createNewBlock(
							typeOrBlock as ComponentType,
						) as ConditionBlock;
					}

					for (const root of draft.positionManagement) {
						if (
							"if_conditions" in root &&
							(root as ConditionalManagementBlock).if_conditions
						) {
							const ifRoot = (root as ConditionalManagementBlock).if_conditions;
							if (ifRoot.id === blockId) {
								if (!ifRoot.children) ifRoot.children = [];
								ifRoot.children.push(newBlock);
								return;
							}
							if (addBlockToParent(ifRoot, blockId, newBlock)) return;
						}
					}
				}),
			),
		addActionToConditionalManagementBlock: (blockId, typeOrBlock) =>
			set(
				produce((draft: StrategyState) => {
					const block = draft.positionManagement.find(
						(b: ManagementBlock) => b.id === blockId,
					) as ConditionalManagementBlock | undefined;
					if (
						block?.then_actions &&
						(typeof typeOrBlock === "object" ||
							CONDITIONAL_MANAGEMENT_ACTION_TYPES.includes(
								typeOrBlock as (typeof CONDITIONAL_MANAGEMENT_ACTION_TYPES)[number],
							))
					) {
						const newAction =
							typeof typeOrBlock === "string"
								? (createNewBlock(typeOrBlock as ComponentType) as
										| ModifyStopLossBlock
										| TrailingStopBlock
										| MoveToBeBlock)
								: (typeOrBlock as
										| ModifyStopLossBlock
										| TrailingStopBlock
										| MoveToBeBlock);
						block.then_actions.push(newAction);
					}
				}),
			),
		addPartialExit: () =>
			set(
				produce((draft: StrategyState) => {
					if (!draft.initialization.params.partial_exits) {
						draft.initialization.params.partial_exits = [];
					}
					draft.initialization.params.partial_exits.push(
						createNewPartialExit(),
					);
				}),
			),
		updatePartialExit: (id, field, value) =>
			set(
				produce((draft: StrategyState) => {
					const exit = draft.initialization.params.partial_exits.find(
						(p: PartialExit) => p.id === id,
					);
					if (exit) {
						(exit as unknown as Record<string, unknown>)[field] = value;
					}
				}),
			),
		removePartialExit: (id) =>
			set(
				produce((draft: StrategyState) => {
					draft.initialization.params.partial_exits =
						draft.initialization.params.partial_exits.filter(
							(p: PartialExit) => p.id !== id,
						);
				}),
			),
		updateFoundationWeight: (blockId: string, weight: number) =>
			set(
				produce((draft: StrategyState) => {
					const normalizedBlockId = normalizeFoundationWeightKey(blockId);
					draft.foundationWeights[normalizedBlockId] = weight;
					delete draft.foundationWeights[`w_${normalizedBlockId}`];
				}),
			),
		saveFoundationWeights: () => {
			const { id, foundationWeights } = get();
			if (id) {
				console.log(
					`Saving foundation weights for strategy ${id}:`,
					foundationWeights,
				);
			}
		},
		setUseFoundationWeights: (value) =>
			set(
				produce((draft: StrategyState) => {
					draft.useFoundationWeights = value;
					if (draft.entryConditions) {
						draft.entryConditions.type = value ? "OR" : "AND";
					}
				}),
			),

		setOracleRegime: (regime) =>
			set(
				produce((draft: StrategyState) => {
					draft.oracleRegime = regime;
				}),
			),

		setOracleConfidence: (confidence) =>
			set(
				produce((draft: StrategyState) => {
					draft.oracleConfidence = confidence;
				}),
			),

		setUseMlConfirmation: (value) => set({ use_ml_confirmation: value }),
		setBreakevenOnRegimeChange: (value) =>
			set({ breakeven_on_regime_change: value }),

		setUserTier: (tier) => set({ userTier: tier }),

		startClearing: () => set({ isClearing: true }),
		reset: () => {
			const { userTier } = get();
			set({
				...getDefaultInitialState(),
				userTier,
				animationEpoch: 0,
				isClearing: false,
			});
		},
	}),
);
