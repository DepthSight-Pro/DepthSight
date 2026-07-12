// frontend/src/components/strategy-editor/migration.ts

import { v4 as uuidv4 } from "uuid";
import type { ComponentType, ConditionBlock } from "./types";

// Default parameters for blocks (synchronized with strategyEditorStore.ts)
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
		default:
			return {};
	}
};

const normalizeNodeParams = (node: unknown) => {
	const n = node as { type?: string; params?: Record<string, unknown> };
	if (!n?.params || typeof n.params !== "object") {
		return;
	}

	const normalizeTapeOutputKey = (key?: string): string | undefined => {
		if (!key) return key;
		if (key.startsWith("tape_accel_mult_volume_"))
			return "acceleration_multiplier_volume";
		if (key.startsWith("tape_accel_mult_count_"))
			return "acceleration_multiplier_count";
		if (key.startsWith("tape_"))
			return key.replace(/^tape_/, "").replace(/_\d+s$/, "");
		return key;
	};

	const normalizeDynamicLinks = (value: unknown): unknown => {
		if (!value || typeof value !== "object") return value;
		if (Array.isArray(value)) return value.map(normalizeDynamicLinks);
		const valObj = value as Record<string, unknown>;
		if (valObj.source === "block_result") {
			return { ...valObj, key: normalizeTapeOutputKey(valObj.key as string) };
		}
		return Object.fromEntries(
			Object.entries(valObj).map(([key, child]) => [
				key,
				normalizeDynamicLinks(child),
			]),
		);
	};

	if (
		n.type === "btc_state_filter" &&
		typeof n.params.required_state === "string"
	) {
		const normalized = n.params.required_state
			.trim()
			.toLowerCase()
			.replace(/[- ]/g, "_");
		const stateMap: Record<string, string> = {
			consolidation: "Consolidation",
			trending_up: "Trending Up",
			trending_down: "Trending Down",
			any: "Any",
		};
		n.params.required_state = stateMap[normalized] || n.params.required_state;
	}

	if (n.type === "trailing_stop" && typeof n.params.type === "string") {
		if (n.params.type.trim().toLowerCase() === "percent") {
			n.params.type = "Percentage";
		}
	}

	if (
		n.type === "return_to_level" &&
		typeof n.params.retest_type === "string"
	) {
		const normalized = n.params.retest_type
			.trim()
			.toLowerCase()
			.replace(/[- ]/g, "_");
		n.params.retest_type =
			normalized === "breakout_retest" ? "breakout_retest" : "touch";
	}

	if (
		n.type === "return_to_level" &&
		n.params.level_block_id &&
		typeof n.params.level_block_id === "object"
	) {
		const lbIdObj = n.params.level_block_id as Record<string, unknown>;
		n.params.level_block_id = lbIdObj.block_id || null;
	}

	n.params = normalizeDynamicLinks(n.params) as Record<string, unknown>;
};

const traverseAndMigrate = (node: ConditionBlock): ConditionBlock => {
	if (!node) return node;

	const migratedNode = { ...node };
	if (!migratedNode.id) {
		migratedNode.id = uuidv4();
	}

	// Migration of incorrect block names generated by AI
	const typeMapping: Record<string, string> = {
		trend_strength_filter: "trend_filter",
		adx_filter: "trend_filter",
		btc_state: "btc_state_filter",
		l2_microstructure_check: "l2_microstructure",
		position_state: "price_vs_level", // Replacing a non-existent block with a similar one
	};

	if (migratedNode.type && typeMapping[migratedNode.type]) {
		console.log(
			`Migrating block type from "${migratedNode.type}" to "${typeMapping[migratedNode.type]}"`,
		);
		migratedNode.type = typeMapping[migratedNode.type] as ComponentType;
	}

	// Filling missing parameters with default values
	if (migratedNode.type && !["AND", "OR"].includes(migratedNode.type)) {
		const defaults = getDefaultBlockParams(migratedNode.type);
		if (defaults && Object.keys(defaults).length > 0) {
			// Merge parameters: first defaults, then existing ones (they overwrite defaults)
			migratedNode.params = { ...defaults, ...(migratedNode.params || {}) };
		}
	}

	// Fixing incorrect parameters for order_book_zone
	normalizeNodeParams(migratedNode);

	if (migratedNode.type === "order_book_zone" && migratedNode.params) {
		// AI sometimes generates range_value as an object { source: "value", value: 1.0 }
		// Need to convert to a simple number
		if (
			migratedNode.params.range_value &&
			typeof migratedNode.params.range_value === "object" &&
			"value" in migratedNode.params.range_value
		) {
			console.log(`Fixing order_book_zone range_value from object to number`);
			migratedNode.params.range_value = (
				migratedNode.params.range_value as Record<string, unknown>
			).value;
		}
	}

	// Migration of the old 'tape_acceleration' into a new composite block
	if (migratedNode.type === "tape_acceleration") {
		const providerId = uuidv4();
		const analysisType =
			migratedNode.params?.analysis_type === "count"
				? "acceleration_multiplier_count"
				: "acceleration_multiplier_volume";

		return {
			id: uuidv4(),
			type: "AND",
			isComposite: true,
			compositeType: "tape_condition",
			children: [
				{
					id: providerId,
					type: "tape_analysis",
					params: {
						time_window_sec: migratedNode.params?.time_window_sec || 5,
					},
				},
				{
					id: uuidv4(),
					type: "value_comparison",
					params: {
						leftOperand: {
							source: "block_result",
							block_id: providerId,
							key: analysisType,
						},
						operator: "gt",
						rightOperand: migratedNode.params?.multiplier || 2.0,
					},
				},
			],
		};
	}

	// Migration of the old 'order_book_analysis'
	if (migratedNode.type === "order_book_analysis") {
		const providerId = uuidv4();
		return {
			id: uuidv4(),
			type: "AND",
			isComposite: true,
			compositeType: "order_book_zone_condition",
			children: [
				{
					id: providerId,
					type: "order_book_zone",
					params: {
						side: migratedNode.params?.side || "any",
						range_type: "Percentage",
						range_value: 2.0,
					},
				},
				{
					id: uuidv4(),
					type: "value_comparison",
					params: {
						leftOperand: {
							source: "block_result",
							block_id: providerId,
							key: "total_volume_usd",
						},
						operator: "gt",
						rightOperand: migratedNode.params?.level_depth_usd || 100000,
					},
				},
			],
		};
	}

	// Recursive traversal of child elements
	if (migratedNode.children) {
		migratedNode.children = migratedNode.children.map(traverseAndMigrate);
	}

	return migratedNode;
};

const migrateManagementBlock = (block: unknown): unknown => {
	if (!block || typeof block !== "object") {
		return block;
	}

	const migratedBlock = { ...(block as Record<string, unknown>) };
	if (!migratedBlock.id) {
		migratedBlock.id = uuidv4();
	}
	const defaults = getDefaultBlockParams(migratedBlock.type as ComponentType);

	if (defaults && Object.keys(defaults).length > 0) {
		migratedBlock.params = {
			...defaults,
			...((migratedBlock.params as Record<string, unknown>) || {}),
		};
	}
	normalizeNodeParams(migratedBlock);

	if (
		typeof migratedBlock.type === "string" &&
		["conditional_exit", "scale_in", "dca_management"].includes(
			migratedBlock.type,
		)
	) {
		const isDca = migratedBlock.type === "dca_management";
		const params = migratedBlock.params as Record<string, unknown> | undefined;
		const existingConditionsRoot =
			params?.conditions || (isDca ? params?.step_value : null);

		let sourceChildren: unknown[] = [];
		const conditionsRootObj = existingConditionsRoot as
			| Record<string, unknown>
			| null
			| undefined;
		if (
			conditionsRootObj &&
			typeof conditionsRootObj === "object" &&
			Array.isArray(conditionsRootObj.children)
		) {
			sourceChildren = conditionsRootObj.children;
		} else if (
			isDca &&
			conditionsRootObj &&
			typeof conditionsRootObj === "object" &&
			conditionsRootObj.type
		) {
			sourceChildren = [conditionsRootObj];
		} else if (Array.isArray(migratedBlock.children)) {
			sourceChildren = migratedBlock.children as unknown[];
		}

		migratedBlock.children = sourceChildren.map((c) =>
			traverseAndMigrate(c as ConditionBlock),
		);

		if (conditionsRootObj && typeof conditionsRootObj === "object" && !isDca) {
			migratedBlock.params = {
				...((migratedBlock.params as Record<string, unknown>) || {}),
				conditions: {
					...conditionsRootObj,
					children: migratedBlock.children,
				},
			};
		}
	} else if (migratedBlock.children && Array.isArray(migratedBlock.children)) {
		migratedBlock.children = migratedBlock.children.map((c) =>
			traverseAndMigrate(c as ConditionBlock),
		);
	}
	if (migratedBlock.if_conditions) {
		migratedBlock.if_conditions = traverseAndMigrate(
			migratedBlock.if_conditions as ConditionBlock,
		);
	}
	if (Array.isArray(migratedBlock.then_actions)) {
		migratedBlock.then_actions = migratedBlock.then_actions.map(
			migrateManagementBlock,
		);
	}

	return migratedBlock;
};

export const migrateStrategy = (strategy: unknown): unknown => {
	if (!strategy) return strategy;

	const newStrategy = { ...(strategy as Record<string, unknown>) };

	if (newStrategy.filters) {
		newStrategy.filters = traverseAndMigrate(
			newStrategy.filters as ConditionBlock,
		);
	}
	if (newStrategy.entryConditions) {
		newStrategy.entryConditions = traverseAndMigrate(
			newStrategy.entryConditions as ConditionBlock,
		);
	}
	// Check that positionManagement exists and is an array
	if (
		newStrategy.positionManagement &&
		Array.isArray(newStrategy.positionManagement)
	) {
		newStrategy.positionManagement = newStrategy.positionManagement.map(
			migrateManagementBlock,
		);
	} else if (newStrategy.positionManagement) {
		// If the field exists but is not an array, log a warning and reset it
		console.warn(
			"Migration warning: `positionManagement` was not an array. Resetting to an empty array. Received:",
			newStrategy.positionManagement,
		);
		newStrategy.positionManagement = [];
	}
	if (newStrategy.initialization && typeof newStrategy.initialization === "object") {
		const init = { ...(newStrategy.initialization as Record<string, unknown>) };
		if (!init.id) {
			init.id = uuidv4();
		}
		newStrategy.initialization = init;
	}
	return newStrategy;
};
