// pwa/components/editor/BlockInspectorModal.tsx
/* eslint-disable @typescript-eslint/no-explicit-any */

import type React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSwipeable } from "react-swipeable";
import { ICONS } from "../../constants";
import { useStrategyEditorStore } from "../../stores/strategyEditorStore";
import type {
	ComponentType,
	ConditionBlock,
	ManagementBlock,
} from "../../types/strategyEditor";

type TranslationFunction = ReturnType<typeof useTranslation>["t"];

import BlockItem from "./BlockItem";
import { type DynamicParam, DynamicValueInput } from "./DynamicValueInput";

interface BlockInspectorModalProps {
	isOpen: boolean;
	onClose: () => void;
	blockId: string | null;
	section: "filters" | "entryConditions" | "positionManagement";
	initialDisplayMode?: "simplified" | "expanded";
}

const ParamRow: React.FC<{ children: React.ReactNode; title?: string }> = ({
	children,
	title,
}) => (
	<div className="flex flex-col gap-2 py-3 border-b border-[hsl(var(--border))] last:border-b-0">
		{title && (
			<label className="text-sm font-medium text-[hsl(var(--muted-foreground))]">
				{title}
			</label>
		)}
		<div className="flex items-center gap-2 w-full">{children}</div>
	</div>
);

const SimpleInput: React.FC<{
	value: string | number;
	onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
	type?: "text" | "number";
	placeholder?: string;
	className?: string;
}> = ({ value, onChange, type = "number", placeholder, className }) => (
	<input
		type={type}
		value={value}
		onChange={onChange}
		placeholder={placeholder}
		className={`w-full h-10 p-2 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-md text-sm text-[hsl(var(--foreground))] outline-none focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary)))] ${className}`}
	/>
);

const ParamSelect: React.FC<{
	value: string | number | undefined;
	onChange: (v: string) => void;
	items: { value: string | number; label: string }[];
	placeholder?: string;
	className?: string;
}> = ({ value, onChange, items, placeholder, className }) => (
	<select
		value={value}
		onChange={(e) => onChange(e.target.value)}
		className={`h-10 p-2 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-md text-sm text-[hsl(var(--foreground))] outline-none focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary)))] ${className || "flex-1"}`}
	>
		{placeholder && (
			<option value="" disabled>
				{placeholder}
			</option>
		)}
		{items.map((i) => (
			<option key={i.value} value={i.value}>
				{i.label}
			</option>
		))}
	</select>
);

const LevelBlockSelect: React.FC<{
	value: string | null | undefined;
	onChange: (val: string) => void;
	t: TranslationFunction;
}> = ({ value, onChange, t }) => {
	const store = useStrategyEditorStore();
	const filters = store.filters;
	const entryConditions = store.entryConditions;
	const positionManagement = store.positionManagement;

	const collectLevelProviderBlocks = (block?: any): any[] => {
		if (!block) return [];
		const current = ["local_level", "significant_level"].includes(block.type)
			? [block]
			: [];
		return [
			...current,
			...(block.children || []).flatMap(collectLevelProviderBlocks),
		];
	};

	const collectManagementLevelProviderBlocks = (
		blocks: any[],
	): any[] => {
		return blocks.flatMap((block) => {
			const b = block as unknown as Record<string, unknown>;
			return [
				...(block.children || []).flatMap(collectLevelProviderBlocks),
				...(b.if_conditions
					? collectLevelProviderBlocks(b.if_conditions as any)
					: []),
				...(Array.isArray(b.then_actions)
					? collectManagementLevelProviderBlocks(
							b.then_actions as any[],
						)
					: []),
			];
		});
	};

	const options = useMemo(() => {
		return [
			...collectLevelProviderBlocks(filters),
			...collectLevelProviderBlocks(entryConditions),
			...collectManagementLevelProviderBlocks(positionManagement),
		];
	}, [filters, entryConditions, positionManagement]);

	const selectItems = options.map((opt) => ({
		value: opt.id,
		label: `${t(`blocks.${opt.type}.title`) || opt.type} [${opt.id.substring(0, 4)}]`,
	}));

	return (
		<ParamSelect
			value={value || undefined}
			onChange={onChange}
			items={selectItems}
			placeholder={t("dynamic_sources.block_results.title", "Block Results")}
			className="w-full flex-grow flex-1 min-w-0"
		/>
	);
};

const renderBlockContent = (
	block: ConditionBlock | ManagementBlock,
	updateParams: (p: Record<string, any>) => void,
	t: TranslationFunction,
): React.ReactNode | null => {
	const p = (block.params as Record<string, any>) || {};
	const handleNumberChange = (key: string, value: string) =>
		updateParams({ [key]: parseFloat(value) || 0 });

	switch (block.type as ComponentType) {
		case "market_activity": {
			const mode = p.mode || "relative";
			return (
				<>
					<ParamRow title="Mode">
						<ParamSelect
							value={mode}
							onChange={(v) => updateParams({ mode: v })}
							items={[
								{ value: "relative", label: "Relative Volume" },
								{ value: "percentile", label: "Percentile Spike" },
							]}
						/>
					</ParamRow>
					<ParamRow title="NATR">
						<DynamicValueInput
							value={p.natr_threshold}
							onChange={(v) => updateParams({ natr_threshold: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					{mode !== "percentile" && (
						<>
							<ParamRow title="Relative volume">
								<DynamicValueInput
									value={p.rel_vol_threshold}
									onChange={(v) => updateParams({ rel_vol_threshold: v })}
									className="flex-grow flex-1 min-w-0"
								/>
							</ParamRow>
							<ParamRow title="Lookback period">
								<DynamicValueInput
									value={p.lookback_period || 20}
									onChange={(v) => updateParams({ lookback_period: v })}
									className="flex-grow flex-1 min-w-0"
								/>
							</ParamRow>
						</>
					)}
				</>
			);
		}
		case "l2_microstructure":
		case "l2_microstructure_check":
			return (
				<>
					<ParamRow title={t("blocks.l2_microstructure_check.text_1")}>
						<ParamSelect
							value={p.check_type}
							onChange={(v) => updateParams({ check_type: v })}
							items={[
								{
									value: "large_order",
									label: t(
										"blocks.l2_microstructure_check.options.large_order",
									),
								},
							]}
						/>
					</ParamRow>
					<ParamRow title="Single order USD">
						<DynamicValueInput
							value={p.single_order_size_usd}
							onChange={(v) => updateParams({ single_order_size_usd: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "tradingview_signal":
			return (
				<>
					<ParamRow
						title={t("blocks.tradingview_signal.signal_id_label", "Signal ID")}
					>
						<SimpleInput
							type="text"
							value={p.signal_id || ""}
							onChange={(e) => updateParams({ signal_id: e.target.value })}
						/>
					</ParamRow>
					<ParamRow
						title={t("blocks.tradingview_signal.ttl_label", "TTL seconds")}
					>
						<DynamicValueInput
							value={p.ttl_seconds}
							onChange={(v) => updateParams({ ttl_seconds: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "level_touch_analyzer":
			return (
				<>
					<ParamRow
						title={t("blocks.level_touch_analyzer.text_1", "Level source")}
					>
						<DynamicValueInput
							value={p.level_source}
							onChange={(v) => updateParams({ level_source: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Lookback">
						<SimpleInput
							value={p.lookback_candles || 50}
							onChange={(e) => handleNumberChange("lookback_candles", e.target.value)}
						/>
					</ParamRow>
					<ParamRow title="Tolerance %">
						<SimpleInput
							value={p.touch_tolerance_pct || 0.1}
							onChange={(e) => handleNumberChange("touch_tolerance_pct", e.target.value)}
						/>
					</ParamRow>
					<ParamRow title="Min touches">
						<SimpleInput
							value={p.min_touches || 1}
							onChange={(e) => handleNumberChange("min_touches", e.target.value)}
						/>
					</ParamRow>
					<ParamRow title="Options">
						<label className="flex items-center gap-2 text-sm text-[hsl(var(--foreground))]">
							<input
								type="checkbox"
								checked={p.invalidate_on_pierce ?? true}
								onChange={(e) =>
									updateParams({ invalidate_on_pierce: e.target.checked })
								}
								className="form-checkbox h-4 w-4 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded"
							/>
							<span>{t("blocks.level_touch_analyzer.invalidate", "No pierce")}</span>
						</label>
					</ParamRow>
				</>
			);
		case "volatility_squeeze":
			return (
				<>
					<ParamRow title="Lookback">
						<SimpleInput
							value={p.lookback_candles || 20}
							onChange={(e) => handleNumberChange("lookback_candles", e.target.value)}
						/>
					</ParamRow>
					<ParamRow title="Squeeze ratio">
						<SimpleInput
							value={p.squeeze_ratio || 0.6}
							onChange={(e) => handleNumberChange("squeeze_ratio", e.target.value)}
						/>
					</ParamRow>
				</>
			);
		case "price_action_analyzer":
			return (
				<>
					<ParamRow title={t("blocks.price_action_analyzer.text", "Structure")}>
						<ParamSelect
							value={p.structure_type}
							onChange={(v) => updateParams({ structure_type: v })}
							items={[
								{ value: "higher_lows", label: "Higher lows" },
								{ value: "lower_highs", label: "Lower highs" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Lookback">
						<SimpleInput
							value={p.lookback_candles || 30}
							onChange={(e) => handleNumberChange("lookback_candles", e.target.value)}
						/>
					</ParamRow>
					<ParamRow title="Min points">
						<SimpleInput
							value={p.min_points || 2}
							onChange={(e) => handleNumberChange("min_points", e.target.value)}
						/>
					</ParamRow>
					<ParamRow title="Order">
						<SimpleInput
							value={p.order || 3}
							onChange={(e) => handleNumberChange("order", e.target.value)}
						/>
					</ParamRow>
				</>
			);
		case "trailing_stop":
			if (
				p.activation_price_type !== undefined ||
				p.trailing_offset_type !== undefined
			) {
				return (
					<>
						<ParamRow title="Activation">
							<ParamSelect
								value={p.activation_price_type}
								onChange={(v) => updateParams({ activation_price_type: v })}
								items={[
									{ value: "rr_multiplier", label: "RR" },
									{ value: "percent_from_price", label: "%" },
								]}
								className="w-28"
							/>
							<DynamicValueInput
								value={p.activation_price_value}
								onChange={(v) => updateParams({ activation_price_value: v })}
								className="flex-grow flex-1 min-w-0"
							/>
						</ParamRow>
						<ParamRow title="Trailing offset">
							<ParamSelect
								value={p.trailing_offset_type}
								onChange={(v) => updateParams({ trailing_offset_type: v })}
								items={[
									{ value: "atr_multiplier", label: "ATR" },
									{ value: "percent_from_price", label: "%" },
								]}
								className="w-28"
							/>
							<DynamicValueInput
								value={p.trailing_offset_value}
								onChange={(v) => updateParams({ trailing_offset_value: v })}
								className="flex-grow flex-1 min-w-0"
							/>
						</ParamRow>
					</>
				);
			}
			return (
				<>
					<ParamRow title={t("blocks.trailing_stop.text_1", "Trailing type")}>
						<ParamSelect
							value={p.type || "Percentage"}
							onChange={(v) => updateParams({ type: v })}
							items={[
								{ value: "Percentage", label: "%" },
								{ value: "ATR", label: "ATR" },
							]}
							className="w-32"
						/>
						<DynamicValueInput
							value={p.value}
							onChange={(v) => updateParams({ value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Mode">
						<ParamSelect
							value={p.mode || "local"}
							onChange={(v) => updateParams({ mode: v })}
							items={[
								{ value: "local", label: "Local" },
								{ value: "exchange", label: "Exchange" },
							]}
						/>
					</ParamRow>
				</>
			);
		case "move_to_breakeven":
			if (p.trigger_price_type !== undefined) {
				return (
					<ParamRow title={t("blocks.move_to_breakeven.text_1")}>
						<ParamSelect
							value={p.trigger_price_type}
							onChange={(v) => updateParams({ trigger_price_type: v })}
							items={[
								{ value: "rr_multiplier", label: "RR" },
								{ value: "percent_from_price", label: "%" },
							]}
							className="w-28"
						/>
						<DynamicValueInput
							value={p.trigger_price_value}
							onChange={(v) => updateParams({ trigger_price_value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				);
			}
			return (
				<>
					<ParamRow title={t("blocks.move_to_breakeven.text_1")}>
						<ParamSelect
							value={p.target_type}
							onChange={(v) => updateParams({ target_type: v })}
							items={[
								{ value: "rr_multiplier", label: "RR" },
								{ value: "percent_from_price", label: "%" },
								{ value: "atr_multiplier", label: "ATR" },
							]}
							className="w-28"
						/>
						<DynamicValueInput
							value={p.target_value}
							onChange={(v) => updateParams({ target_value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Offset pips">
						<SimpleInput
							value={p.offset_pips || 0}
							onChange={(e) =>
								handleNumberChange("offset_pips", e.target.value)
							}
						/>
					</ParamRow>
				</>
			);
		case "modify_take_profit":
			return (
				<ParamRow
					title={t("blocks.modify_take_profit.new_tp_price", "New take profit")}
				>
					<DynamicValueInput
						value={p.new_tp_price}
						onChange={(v) => updateParams({ new_tp_price: v })}
						className="flex-grow flex-1 min-w-0"
					/>
				</ParamRow>
			);
		case "close_position":
			return (
				<ParamRow title={t("blocks.close_position.text_1", "Close position")}>
					<span className="text-sm text-muted-foreground">
						{t("blocks.noParams")}
					</span>
				</ParamRow>
			);
		case "dca_management":
			return (
				<>
					<ParamRow title={t("blocks.dca_management.so", "Safety orders")}>
						<SimpleInput
							value={p.max_safety_orders || ""}
							onChange={(e) =>
								handleNumberChange("max_safety_orders", e.target.value)
							}
						/>
					</ParamRow>
					<ParamRow
						title={t("blocks.dca_management.mult", "Volume multiplier")}
					>
						<DynamicValueInput
							value={p.volume_multiplier}
							onChange={(v) => updateParams({ volume_multiplier: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Step">
						<ParamSelect
							value={p.step_type}
							onChange={(v) => updateParams({ step_type: v })}
							items={[
								{ value: "percentage", label: "%" },
								{ value: "atr", label: "ATR" },
								{ value: "custom_condition", label: "Condition" },
							]}
							className="w-40"
						/>
						<DynamicValueInput
							value={p.step_value}
							onChange={(v) => updateParams({ step_value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "grid_management":
			return (
				<>
					<ParamRow title={t("blocks.grid_management.levels", "Levels")}>
						<SimpleInput
							value={p.grid_levels || ""}
							onChange={(e) =>
								handleNumberChange("grid_levels", e.target.value)
							}
						/>
					</ParamRow>
					<ParamRow title="Range">
						<ParamSelect
							value={p.range_type}
							onChange={(v) => updateParams({ range_type: v })}
							items={[
								{ value: "percentage", label: "%" },
								{ value: "atr", label: "ATR" },
								{ value: "fixed_prices", label: "Fixed" },
							]}
						/>
					</ParamRow>
					<ParamRow title={t("blocks.grid_management.upper", "Upper")}>
						<DynamicValueInput
							value={p.upper_bound}
							onChange={(v) => updateParams({ upper_bound: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title={t("blocks.grid_management.lower", "Lower")}>
						<DynamicValueInput
							value={p.lower_bound}
							onChange={(v) => updateParams({ lower_bound: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "trading_session": {
			const filterMode =
				p.filter_mode ||
				(p.start_hour !== undefined || p.end_hour !== undefined
					? "hours"
					: "session");
			const startH = p.start_hour_utc ?? p.start_hour ?? 0;
			const endH = p.end_hour_utc ?? p.end_hour ?? 23;
			const mode = p.mode || "include";

			return (
				<>
					<ParamRow title="Mode">
						<ParamSelect
							value={filterMode}
							onChange={(v) => updateParams({ filter_mode: v })}
							items={[
								{ value: "session", label: t("blocks.trading_session.modes.session") || "By Session" },
								{ value: "hours", label: t("blocks.trading_session.modes.hours") || "By Hours" },
							]}
						/>
					</ParamRow>
					{filterMode === "hours" ? (
						<>
							<ParamRow title="Start Hour (UTC)">
								<SimpleInput
									value={startH}
									onChange={(e) => updateParams({ start_hour_utc: parseInt(e.target.value, 10) || 0 })}
								/>
							</ParamRow>
							<ParamRow title="End Hour (UTC)">
								<SimpleInput
									value={endH}
									onChange={(e) => updateParams({ end_hour_utc: parseInt(e.target.value, 10) || 23 })}
								/>
							</ParamRow>
							<ParamRow title="Action">
								<ParamSelect
									value={mode}
									onChange={(v) => updateParams({ mode: v })}
									items={[
										{ value: "include", label: t("blocks.trading_session.include") || "Include" },
										{ value: "exclude", label: t("blocks.trading_session.exclude") || "Exclude" },
									]}
								/>
							</ParamRow>
						</>
					) : (
						<ParamRow title="Session">
							<ParamSelect
								value={p.session || "london"}
								onChange={(v) => updateParams({ session: v })}
								items={[
									{ value: "london", label: t("blocks.trading_session.sessions.london") || "London" },
									{ value: "new_york", label: t("blocks.trading_session.sessions.new_york") || "New York" },
									{ value: "asia", label: t("blocks.trading_session.sessions.asia") || "Asia" },
									{ value: "sydney", label: t("blocks.trading_session.sessions.sydney") || "Sydney" },
								]}
							/>
						</ParamRow>
					)}
				</>
			);
		}
		case "volatility_filter":
			return (
				<>
					<ParamRow title="Indicator">
						<ParamSelect
							value={p.indicator}
							onChange={(v) => updateParams({ indicator: v })}
							items={[
								{ value: "ATR", label: "ATR" },
								{ value: "BBW", label: "Bollinger Bands Width" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Condition">
						<ParamSelect
							value={p.operator}
							onChange={(v) => updateParams({ operator: v })}
							items={[
								{ value: "gt", label: ">" },
								{ value: "lt", label: "<" },
							]}
							className="w-24"
						/>
						<DynamicValueInput
							value={p.value}
							onChange={(v) => updateParams({ value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "trend_filter":
			return (
				<ParamRow title={t("blocks.trend_filter.text")}>
					<ParamSelect
						value={p.indicator}
						onChange={(v) => updateParams({ indicator: v })}
						items={[{ value: "ADX", label: "ADX (14)" }]}
						className="w-32"
					/>
					<span className="text-muted-foreground">&gt;</span>
					<DynamicValueInput
						value={p.threshold}
						onChange={(v) => updateParams({ threshold: v })}
						className="flex-grow flex-1 min-w-0"
					/>
				</ParamRow>
			);
		case "btc_state_filter":
			return (
				<ParamRow title={t("blocks.btc_state_filter.required_state")}>
					<ParamSelect
						value={p.required_state}
						onChange={(v) => updateParams({ required_state: v })}
						items={[
							{
								value: "Consolidation",
								label: t("blocks.btc_state_filter.states.consolidation"),
							},
							{
								value: "Trending Up",
								label: t("blocks.btc_state_filter.states.trending_up"),
							},
							{
								value: "Trending Down",
								label: t("blocks.btc_state_filter.states.trending_down"),
							},
							{ value: "Any", label: t("blocks.btc_state_filter.states.any") },
						]}
					/>
				</ParamRow>
			);
		case "correlation":
			return (
				<>
					<ParamRow title="Period (bars)">
						<DynamicValueInput
							value={p.lookback}
							onChange={(v) => updateParams({ lookback: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Condition">
						<ParamSelect
							value={p.operator}
							onChange={(v) => updateParams({ operator: v })}
							items={[
								{ value: "gt", label: ">" },
								{ value: "lt", label: "<" },
							]}
							className="w-24"
						/>
						<DynamicValueInput
							value={p.value}
							onChange={(v) => updateParams({ value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "natr_filter":
			return (
				<ParamRow title="NATR threshold >">
					<DynamicValueInput
						value={p.natr_threshold ?? p.value ?? p.threshold}
						onChange={(v) => updateParams({ natr_threshold: v })}
						className="flex-grow flex-1 min-w-0"
					/>
				</ParamRow>
			);
		case "rel_vol_filter":
			return (
				<>
					<ParamRow title="Rel. volume threshold >">
						<DynamicValueInput
							value={p.rel_vol_threshold}
							onChange={(v) => updateParams({ rel_vol_threshold: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Lookback period">
						<DynamicValueInput
							value={p.lookback_period || 20}
							onChange={(v) => updateParams({ lookback_period: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "open_interest":
			return (
				<>
					<ParamRow title={t("blocks.open_interest.analyze")}>
						<ParamSelect
							value={p.analyze}
							onChange={(v) => updateParams({ analyze: v })}
							items={[
								{
									value: "change_pct",
									label: t("blocks.open_interest.analysis_types.change_pct"),
								},
								{
									value: "absolute_value",
									label: t(
										"blocks.open_interest.analysis_types.absolute_value",
									),
								},
							]}
						/>
					</ParamRow>
					<ParamRow title="Period (bars)">
						<DynamicValueInput
							value={p.lookback}
							onChange={(v) => updateParams({ lookback: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Condition">
						<ParamSelect
							value={p.operator}
							onChange={(v) => updateParams({ operator: v })}
							items={[
								{ value: "gt", label: ">" },
								{ value: "lt", label: "<" },
							]}
							className="w-24"
						/>
						<DynamicValueInput
							value={p.value}
							onChange={(v) => updateParams({ value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "significant_level":
			return (
				<>
					<ParamRow title={t("blocks.significant_level.text_1")}>
						<ParamSelect
							value={p.level_type}
							onChange={(v) => updateParams({ level_type: v })}
							items={[
								{
									value: "daily_high",
									label: t("blocks.significant_level.levels.daily_high"),
								},
								{
									value: "daily_low",
									label: t("blocks.significant_level.levels.daily_low"),
								},
								{
									value: "weekly_high",
									label: t("blocks.significant_level.levels.weekly_high"),
								},
								{
									value: "weekly_low",
									label: t("blocks.significant_level.levels.weekly_low"),
								},
							]}
						/>
					</ParamRow>
					<ParamRow title={t("blocks.significant_level.text_2")}>
						<DynamicValueInput
							value={p.proximity_value}
							onChange={(v: DynamicParam) =>
								updateParams({ proximity_value: v })
							}
							className="flex-grow flex-1 min-w-0"
						/>
						<ParamSelect
							value={p.proximity_type}
							onChange={(v) => updateParams({ proximity_type: v })}
							items={[
								{
									value: "atr_multiplier",
									label: t("blocks.significant_level.options.atr_multiplier"),
								},
								{
									value: "percentage",
									label: t("blocks.significant_level.options.percentage"),
								},
							]}
							className="w-28"
						/>
					</ParamRow>
				</>
			);
		case "round_level":
			return (
				<ParamRow title={t("blocks.round_level.text")}>
					<DynamicValueInput
						value={p.proximity_value}
						onChange={(v: DynamicParam) => updateParams({ proximity_value: v })}
						className="flex-grow flex-1 min-w-0"
					/>
					<ParamSelect
						value={p.proximity_type}
						onChange={(v) => updateParams({ proximity_type: v })}
						items={[
							{
								value: "percentage",
								label: t("blocks.round_level.options.percentage"),
							},
							{ value: "pips", label: t("blocks.round_level.options.pips") },
						]}
						className="w-28"
					/>
				</ParamRow>
			);
		case "trend_direction":
			return (
				<>
					<ParamRow title={t("blocks.trend_direction.text_on_tf")}>
						<ParamSelect
							value={p.timeframe || "5m"}
							onChange={(v) => updateParams({ timeframe: v })}
							items={[
								{ value: "1m", label: "1m" },
								{ value: "5m", label: "5m" },
								{ value: "15m", label: "15m" },
								{ value: "1h", label: "1h" },
								{ value: "4h", label: "4h" },
								{ value: "1d", label: "1d" },
							]}
						/>
					</ParamRow>
					<ParamRow title={t("blocks.trend_direction.is")}>
						<ParamSelect
							value={p.required_trend || "LONG"}
							onChange={(v) => updateParams({ required_trend: v })}
							items={[
								{
									value: "LONG",
									label: t("blocks.trend_direction.trends.long"),
								},
								{
									value: "SHORT",
									label: t("blocks.trend_direction.trends.short"),
								},
								{
									value: "ANY_TREND",
									label: t("blocks.trend_direction.trends.any_trend"),
								},
								{
									value: "FLAT",
									label: t("blocks.trend_direction.trends.flat"),
								},
							]}
						/>
					</ParamRow>
				</>
			);
		case "classic_pattern":
			return (
				<>
					<ParamRow title={t("blocks.classic_pattern.text")}>
						<ParamSelect
							value={p.pattern_name}
							onChange={(v) => updateParams({ pattern_name: v, side: "any" })}
							items={[
								{
									value: "bullish_engulfing",
									label: t("blocks.classic_pattern.bullish_engulfing"),
								},
								{
									value: "bearish_engulfing",
									label: t("blocks.classic_pattern.bearish_engulfing"),
								},
								{
									value: "pin_bar",
									label: t("blocks.classic_pattern.pin_bar"),
								},
								{ value: "doji", label: t("blocks.classic_pattern.doji") },
								{
									value: "inside_bar",
									label: t("blocks.classic_pattern.inside_bar"),
								},
							]}
						/>
					</ParamRow>
					{p.pattern_name === "pin_bar" && (
						<ParamRow title="Pin bar type">
							<ParamSelect
								value={p.side || "any"}
								onChange={(v) => updateParams({ side: v })}
								items={[
									{
										value: "any",
										label: t("blocks.classic_pattern.sides.any"),
									},
									{
										value: "bullish",
										label: t("blocks.classic_pattern.sides.bullish"),
									},
									{
										value: "bearish",
										label: t("blocks.classic_pattern.sides.bearish"),
									},
								]}
							/>
						</ParamRow>
					)}
				</>
			);
		case "volume_confirmation":
			return (
				<>
					<ParamRow title={t("blocks.volume_confirmation.text")}>
						<DynamicValueInput
							value={p.multiplier}
							onChange={(v) => updateParams({ multiplier: v })}
							className="flex-grow flex-1 min-w-0"
						/>
						<span className="text-muted-foreground whitespace-nowrap">
							{t("blocks.volume_confirmation.x_average") || "x average"}
						</span>
					</ParamRow>
					<ParamRow title="Lookback period">
						<DynamicValueInput
							value={p.lookback_period || 20}
							onChange={(v) => updateParams({ lookback_period: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "price_consolidation":
			return (
				<>
					<ParamRow title="Timeframe">
						<ParamSelect
							value={p.timeframe || "auto"}
							onChange={(v) => updateParams({ timeframe: v })}
							items={[
								{ value: "auto", label: "Auto" },
								{ value: "1m", label: "1m" },
								{ value: "5m", label: "5m" },
								{ value: "15m", label: "15m" },
								{ value: "1h", label: "1h" },
								{ value: "4h", label: "4h" },
								{ value: "1d", label: "1d" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Period (bars)">
						<DynamicValueInput
							value={p.lookback_period}
							onChange={(v) => updateParams({ lookback_period: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Max range (in ATR)">
						<DynamicValueInput
							value={p.max_range_atr}
							onChange={(v) => updateParams({ max_range_atr: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "return_to_level": {
			const retestType = p.retest_type || "touch";
			return (
				<>
					<ParamRow title="Level block ID">
						<LevelBlockSelect
							value={p.level_block_id}
							onChange={(v) => updateParams({ level_block_id: v })}
							t={t}
						/>
					</ParamRow>
					<ParamRow title="Retest type">
						<ParamSelect
							value={retestType}
							onChange={(v) => updateParams({ retest_type: v })}
							items={[
								{ value: "touch", label: "Touch" },
								{ value: "breakout_retest", label: "Breakout and retest" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Approach direction">
						<ParamSelect
							value={p.approach_direction || "any"}
							onChange={(v) => updateParams({ approach_direction: v })}
							items={[
								{ value: "any", label: t("blocks.return_to_level.directions.any") || "Any direction" },
								{ value: "from_above", label: t("blocks.return_to_level.directions.from_above") || "From above" },
								{ value: "from_below", label: t("blocks.return_to_level.directions.from_below") || "From below" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Confirmation time (sec)">
						<DynamicValueInput
							value={p.confirmation_time_sec}
							onChange={(v) => updateParams({ confirmation_time_sec: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Proximity">
						<DynamicValueInput
							value={p.proximity_value ?? p.proximity_multiplier}
							onChange={(v) => updateParams({ proximity_value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
						<ParamSelect
							value={p.proximity_type || "atr_multiplier"}
							onChange={(v) => updateParams({ proximity_type: v })}
							items={[
								{ value: "atr_multiplier", label: "ATR" },
								{ value: "percentage", label: "%" },
							]}
							className="w-24"
						/>
					</ParamRow>
					{retestType === "breakout_retest" && (
						<ParamRow title="Departure">
							<DynamicValueInput
								value={p.departure_value ?? p.departure_multiplier}
								onChange={(v) => updateParams({ departure_value: v })}
								className="flex-grow flex-1 min-w-0"
							/>
							<ParamSelect
								value={p.departure_type || "atr_multiplier"}
								onChange={(v) => updateParams({ departure_type: v })}
								items={[
									{ value: "atr_multiplier", label: "ATR" },
									{ value: "percentage", label: "%" },
								]}
								className="w-24"
							/>
						</ParamRow>
					)}
				</>
			);
		}
		case "rsi_condition":
			return (
				<>
					<ParamRow title="RSI period">
						<DynamicValueInput
							value={p.period}
							onChange={(v) => updateParams({ period: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Condition">
						<span className="text-sm text-muted-foreground">RSI</span>
						<ParamSelect
							value={p.operator}
							onChange={(v) => updateParams({ operator: v })}
							items={[
								{ value: "gt", label: ">" },
								{ value: "lt", label: "<" },
							]}
							className="w-24"
						/>
						<DynamicValueInput
							value={p.value}
							onChange={(v) => updateParams({ value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Offset (bars back)">
						<SimpleInput
							value={p.shift || 0}
							onChange={(e) => handleNumberChange("shift", e.target.value)}
						/>
					</ParamRow>
				</>
			);
		case "ma_cross_condition":
			return (
				<>
					<ParamRow title="Fast MA">
						<DynamicValueInput
							value={p.fast_period || p.fast}
							onChange={(v) => updateParams({ fast_period: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Slow MA">
						<DynamicValueInput
							value={p.slow_period || p.slow}
							onChange={(v) => updateParams({ slow_period: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Crossover">
						<ParamSelect
							value={p.operator}
							onChange={(v) => updateParams({ operator: v })}
							items={[
								{ value: "crosses_above", label: "Above" },
								{ value: "crosses_below", label: "Below" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Offset (bars back)">
						<SimpleInput
							value={p.shift || 0}
							onChange={(e) => handleNumberChange("shift", e.target.value)}
						/>
					</ParamRow>
				</>
			);
		case "value_comparison":
			return (
				<>
					<ParamRow title="Left value">
						<DynamicValueInput
							value={p.leftOperand}
							onChange={(v) => updateParams({ leftOperand: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Operator">
						<ParamSelect
							value={p.operator}
							onChange={(v) => updateParams({ operator: v })}
							items={[
								{ value: "gt", label: ">" },
								{ value: "lt", label: "<" },
								{ value: "gte", label: ">=" },
								{ value: "lte", label: "<=" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Right value">
						<DynamicValueInput
							value={p.rightOperand}
							onChange={(v) => updateParams({ rightOperand: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "price_vs_level":
			return (
				<>
					<ParamRow title="Price source">
						<DynamicValueInput
							value={p.price_source}
							onChange={(v) => updateParams({ price_source: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Operator">
						<ParamSelect
							value={p.operator}
							onChange={(v) => updateParams({ operator: v })}
							items={[
								{ value: "gt", label: ">" },
								{ value: "lt", label: "<" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Level source">
						<DynamicValueInput
							value={p.level_source}
							onChange={(v) => updateParams({ level_source: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
				</>
			);
		case "scale_in":
			return (
				<>
					<ParamRow title={t("blocks.scale_in.add_size_pct_of_initial_risk")}>
						<SimpleInput
							value={p.add_size_pct_of_initial_risk || ""}
							onChange={(e) =>
								handleNumberChange(
									"add_size_pct_of_initial_risk",
									e.target.value,
								)
							}
						/>
						<span className="text-muted-foreground">%</span>
					</ParamRow>
					<ParamRow title="Max entries">
						<SimpleInput
							value={p.max_entries || ""}
							onChange={(e) =>
								handleNumberChange("max_entries", e.target.value)
							}
						/>
					</ParamRow>
				</>
			);
		case "modify_stop_loss":
			return (
				<ParamRow title={t("blocks.modify_stop_loss.new_sl_price")}>
					<DynamicValueInput
						value={p.new_sl_price}
						onChange={(v) => updateParams({ new_sl_price: v })}
						className="flex-grow flex-1 min-w-0"
					/>
				</ParamRow>
			);
		case "local_level":
			return (
				<>
					<ParamRow title="Timeframe">
						<ParamSelect
							value={p.timeframe || "5m"}
							onChange={(v) => updateParams({ timeframe: v })}
							items={[
								{ value: "1m", label: "1m" },
								{ value: "5m", label: "5m" },
								{ value: "15m", label: "15m" },
								{ value: "1h", label: "1h" },
								{ value: "4h", label: "4h" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Lookback period">
						<DynamicValueInput
							value={p.lookback_period}
							onChange={(v) => updateParams({ lookback_period: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Level type">
						<ParamSelect
							value={p.level_type || "all"}
							onChange={(v) => updateParams({ level_type: v })}
							items={[
								{ value: "high", label: t("blocks.local_level.level_types.high") || "High" },
								{ value: "low", label: t("blocks.local_level.level_types.low") || "Low" },
								{ value: "all", label: t("blocks.local_level.level_types.all") || "High/Low" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Proximity type">
						<ParamSelect
							value={p.proximity_type || "atr_multiplier"}
							onChange={(v) => updateParams({ proximity_type: v })}
							items={[
								{ value: "atr_multiplier", label: "ATR" },
								{ value: "percentage", label: "%" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Proximity value">
						<DynamicValueInput
							value={p.proximity_value}
							onChange={(v) => updateParams({ proximity_value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Options">
						<label className="flex items-center gap-2 text-sm text-[hsl(var(--foreground))]">
							<input
								type="checkbox"
								checked={p.is_data_provider || false}
								onChange={(e) =>
									updateParams({ is_data_provider: e.target.checked })
								}
								className="form-checkbox h-4 w-4 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded"
							/>
							<span>{t("blocks.local_level.is_data_provider_label") || "Is data provider"}</span>
						</label>
					</ParamRow>
				</>
			);
		case "senior_tf_confluence":
			return (
				<ParamRow title={t("blocks.senior_tf_confluence.text") || "Timeframe"}>
					<ParamSelect
						value={p.timeframe || "1h"}
						onChange={(v) => updateParams({ timeframe: v })}
						items={[
							{ value: "15m", label: "15m" },
							{ value: "1h", label: "1h" },
							{ value: "4h", label: "4h" },
							{ value: "1d", label: "1d" },
						]}
					/>
				</ParamRow>
			);
		case "tape_analysis":
			return (
				<ParamRow title={t("blocks.tape_analysis.text") || "Time window"}>
					<ParamSelect
						value={p.time_window_sec || 5}
						onChange={(v) => updateParams({ time_window_sec: parseInt(v, 10) || 5 })}
						items={[
							{ value: 5, label: "5s" },
							{ value: 10, label: "10s" },
							{ value: 30, label: "30s" },
						]}
					/>
				</ParamRow>
			);
		case "order_book_zone":
			return (
				<>
					<ParamRow title="Side">
						<ParamSelect
							value={p.side || "bids"}
							onChange={(v) => updateParams({ side: v })}
							items={[
								{ value: "bids", label: t("blocks.order_book_zone.options.bids") || "Bids" },
								{ value: "asks", label: t("blocks.order_book_zone.options.asks") || "Asks" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Range value">
						<DynamicValueInput
							value={p.range_value}
							onChange={(v) => updateParams({ range_value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Range type">
						<ParamSelect
							value={p.range_type || "Percentage"}
							onChange={(v) => updateParams({ range_type: v })}
							items={[
								{ value: "Percentage", label: t("blocks.order_book_zone.range_type_percentage") || "%" },
								{ value: "ATR Multiplier", label: t("blocks.order_book_zone.range_type_atr") || "ATR" },
								{ value: "Ticks", label: t("blocks.order_book_zone.range_type_ticks") || "Ticks" },
							]}
						/>
					</ParamRow>
				</>
			);
		case "macd_condition":
			return (
				<>
					<ParamRow title="Fast period">
						<DynamicValueInput
							value={p.fast_period || p.fast}
							onChange={(v) => updateParams({ fast_period: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Slow period">
						<DynamicValueInput
							value={p.slow_period || p.slow}
							onChange={(v) => updateParams({ slow_period: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Signal period">
						<DynamicValueInput
							value={p.signal_period || p.signal}
							onChange={(v) => updateParams({ signal_period: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Condition">
						<ParamSelect
							value={p.condition}
							onChange={(v) => updateParams({ condition: v })}
							items={[
								{
									value: "macd_cross_above_signal",
									label: t("blocks.macd_condition.options.macd_cross_above_signal") || "MACD cross above Signal",
								},
								{
									value: "macd_cross_below_signal",
									label: t("blocks.macd_condition.options.macd_cross_below_signal") || "MACD cross below Signal",
								},
								{
									value: "hist_gt_zero",
									label: t("blocks.macd_condition.options.hist_gt_zero") || "Histogram > 0",
								},
								{
									value: "hist_lt_zero",
									label: t("blocks.macd_condition.options.hist_lt_zero") || "Histogram < 0",
								},
							]}
						/>
					</ParamRow>
					<ParamRow title="Offset (bars back)">
						<SimpleInput
							value={p.shift || 0}
							onChange={(e) => handleNumberChange("shift", e.target.value)}
						/>
					</ParamRow>
				</>
			);
		case "bollinger_bands_condition":
		case "bb_condition":
			return (
				<>
					<ParamRow title="Price source">
						<ParamSelect
							value={p.source || "close"}
							onChange={(v) => updateParams({ source: v })}
							items={[
								{ value: "close", label: t("blocks.bollinger_bands_condition.source_options.close") || "Close" },
								{ value: "high", label: t("blocks.bollinger_bands_condition.source_options.high") || "High" },
								{ value: "low", label: t("blocks.bollinger_bands_condition.source_options.low") || "Low" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Condition">
						<ParamSelect
							value={p.location || p.check_type}
							onChange={(v) => updateParams({ location: v, check_type: v })}
							items={[
								{ value: "above_upper", label: t("blocks.bollinger_bands_condition.location_options.above_upper") || "Above Upper Band" },
								{ value: "below_lower", label: t("blocks.bollinger_bands_condition.location_options.below_lower") || "Below Lower Band" },
								{ value: "price_above_upper", label: t("blocks.bollinger_bands_condition.location_options.above_upper") || "Above Upper Band" },
								{ value: "price_below_lower", label: t("blocks.bollinger_bands_condition.location_options.below_lower") || "Below Lower Band" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Offset (bars back)">
						<SimpleInput
							value={p.shift || 0}
							onChange={(e) => handleNumberChange("shift", e.target.value)}
						/>
					</ParamRow>
				</>
			);
		case "stochastic_condition":
		case "stoch_condition":
			return (
				<>
					<ParamRow title="K period">
						<DynamicValueInput
							value={p.k_period}
							onChange={(v) => updateParams({ k_period: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Condition">
						<ParamSelect
							value={p.condition || p.operator}
							onChange={(v) => updateParams({ condition: v, operator: v })}
							items={[
								{ value: "k_cross_above_d", label: t("blocks.stochastic_condition.options.k_cross_above_d") || "K cross above D" },
								{ value: "k_cross_below_d", label: t("blocks.stochastic_condition.options.k_cross_below_d") || "K cross below D" },
								{ value: "k_above_level", label: t("blocks.stochastic_condition.options.k_above_level") || "K > level" },
								{ value: "k_below_level", label: t("blocks.stochastic_condition.options.k_below_level") || "K < level" },
								{ value: "cross_above", label: t("blocks.stochastic_condition.options.k_cross_above_d") || "K cross above D" },
								{ value: "cross_below", label: t("blocks.stochastic_condition.options.k_cross_below_d") || "K cross below D" },
								{ value: "gt", label: t("blocks.stochastic_condition.options.k_above_level") || "K > level" },
								{ value: "lt", label: t("blocks.stochastic_condition.options.k_below_level") || "K < level" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Level / Value">
						<DynamicValueInput
							value={p.level || p.value}
							onChange={(v) => updateParams({ level: v, value: v })}
							className="flex-grow flex-1 min-w-0"
						/>
					</ParamRow>
					<ParamRow title="Offset (bars back)">
						<SimpleInput
							value={p.shift || 0}
							onChange={(e) => handleNumberChange("shift", e.target.value)}
						/>
					</ParamRow>
				</>
			);
		default: {
			const noParamsMessage: React.ReactNode = t(
				"blocks.noParams",
				"There are no configurable parameters for this block.",
			);
			return (
				<p className="text-sm text-muted-foreground p-4 text-center">
					{noParamsMessage}
				</p>
			);
		}
	}
};

// --- Rendering for COMPOSITE blocks ---
const renderCompositeBlockContent = (
	block: ConditionBlock,
	updateParams: (p: Record<string, any>) => void,
	t: TranslationFunction,
): React.ReactNode | null => {
	switch (block.compositeType) {
		case "tape_condition": {
			const [provider, consumer] = block.children || [];
			if (!provider || !consumer) return null;
			const pParams = (provider.params as Record<string, any>) || {};
			const cParams = (consumer.params as Record<string, any>) || {};
			const timeWindow = pParams.time_window_sec || 5;
			const metricKey =
				cParams.leftOperand?.key || `delta_volume_usd_${timeWindow}s`;
			const operator = cParams.operator || "gt";
			const rightOperand = cParams.rightOperand;
			const comparisonType =
				typeof rightOperand === "object" &&
				rightOperand !== null &&
				rightOperand.source === "value_multiplier"
					? "multiplier"
					: "absolute";
			return (
				<>
					<ParamRow title={t("blocks.tape_condition.for")}>
						<ParamSelect
							value={String(timeWindow)}
							onChange={(v) =>
								updateParams({ time_window_sec: parseInt(v, 10) })
							}
							items={[
								{ value: 5, label: "5s" },
								{ value: 10, label: "10s" },
								{ value: 30, label: "30s" },
							]}
						/>
					</ParamRow>
					<ParamRow title={t("blocks.tape_condition.check")}>
						<ParamSelect
							value={metricKey}
							onChange={(v) => updateParams({ metric: v })}
							items={[
								{
									value: `tape_delta_volume_usd_${timeWindow}s`,
									label: t("blocks.tape_condition.metrics.delta_volume_usd"),
								},
								{
									value: `tape_buy_volume_usd_${timeWindow}s`,
									label: t("blocks.tape_condition.metrics.buy_volume_usd"),
								},
								{
									value: `tape_total_volume_usd_${timeWindow}s`,
									label: t("blocks.tape_condition.metrics.total_volume_usd"),
								},
								{
									value: `tape_accel_mult_volume_${timeWindow}s_60s`,
									label: t(
										"blocks.tape_condition.metrics.acceleration_multiplier_volume",
									),
								},
							]}
						/>
					</ParamRow>
					<ParamRow title="Condition">
						<ParamSelect
							value={operator}
							onChange={(v) => updateParams({ operator: v })}
							items={[
								{ value: "gt", label: ">" },
								{ value: "lt", label: "<" },
							]}
							className="w-24"
						/>
						<ParamSelect
							value={comparisonType}
							onChange={(v) => {
								if (v === "absolute") updateParams({ value: 100000 });
								else
									updateParams({
										value: { source: "value_multiplier", multiplier: 2.0 },
									});
							}}
							items={[
								{
									value: "absolute",
									label: t("blocks.tape_condition.absolute_value"),
								},
								{
									value: "multiplier",
									label: t("blocks.tape_condition.multiplier_value"),
								},
							]}
							className="w-48"
						/>
					</ParamRow>
					<ParamRow title="Value">
						{comparisonType === "absolute" ? (
							<DynamicValueInput
								value={typeof rightOperand === "number" ? rightOperand : 0}
								onChange={(v: DynamicParam) => updateParams({ value: v })}
							/>
						) : (
							<div className="flex items-center gap-2 w-full">
								<span>x</span>
								<SimpleInput
									value={
										typeof rightOperand === "object" &&
										rightOperand !== null &&
										"multiplier" in rightOperand
											? (rightOperand as { multiplier: number }).multiplier
											: 2.0
									}
									onChange={(e) =>
										updateParams({
											value: {
												...(rightOperand as object),
												source: "value_multiplier",
												multiplier: parseFloat(e.target.value) || 0,
											},
										})
									}
								/>
								<span className="text-sm text-[hsl(var(--muted-foreground))]">
									{t("blocks.tape_condition.of_average")}
								</span>
							</div>
						)}
					</ParamRow>
				</>
			);
		}
		case "order_book_zone_condition": {
			const [provider, consumer] = block.children || [];
			if (!provider || !consumer) return null;
			const pParams = (provider.params as Record<string, any>) || {};
			const cParams = (consumer.params as Record<string, any>) || {};
			return (
				<>
					<ParamRow title={t("blocks.order_book_zone_condition.in")}>
						<ParamSelect
							value={pParams.side}
							onChange={(v) => updateParams({ side: v })}
							items={[
								{
									value: "bids",
									label: t("blocks.order_book_zone_condition.sides.bids"),
								},
								{
									value: "asks",
									label: t("blocks.order_book_zone_condition.sides.asks"),
								},
							]}
						/>
					</ParamRow>
					<ParamRow title={t("blocks.order_book_zone_condition.in_range")}>
						<DynamicValueInput
							value={pParams.range_value}
							onChange={(v) => updateParams({ range_value: v })}
						/>
						<ParamSelect
							value={pParams.range_type}
							onChange={(v) => updateParams({ range_type: v })}
							items={[
								{ value: "Percentage", label: "%" },
								{
									value: "ATR Multiplier",
									label: t(
										"blocks.order_book_zone_condition.range_types.atr_multiplier",
									),
								},
								{
									value: "Ticks",
									label: t(
										"blocks.order_book_zone_condition.range_types.ticks",
									),
								},
							]}
							className="w-32"
						/>
					</ParamRow>
					<ParamRow title="Condition">
						<ParamSelect
							value={cParams.leftOperand?.key}
							onChange={(v) => updateParams({ metric: v })}
							items={[
								{
									value: "total_volume_usd",
									label: t(
										"blocks.order_book_zone_condition.metrics.total_volume_usd",
									),
								},
								{
									value: "largest_level_usd",
									label: t(
										"blocks.order_book_zone_condition.metrics.largest_level_usd",
									),
								},
								{
									value: "level_count",
									label: t(
										"blocks.order_book_zone_condition.metrics.level_count",
									),
								},
							]}
						/>
						<ParamSelect
							value={cParams.operator}
							onChange={(v) => updateParams({ operator: v })}
							items={[
								{ value: "gt", label: ">" },
								{ value: "lt", label: "<" },
							]}
							className="w-24"
						/>
						<DynamicValueInput
							value={cParams.rightOperand}
							onChange={(v) => updateParams({ value: v })}
						/>
					</ParamRow>
				</>
			);
		}
		case "level_proximity_condition": {
			const provider = block.children?.[0];
			if (!provider) return null;
			const pParams = (provider.params as Record<string, any>) || {};
			return (
				<>
					<ParamRow title={t("blocks.level_proximity_condition.price")}>
						<ParamSelect
							value={pParams.price_source}
							onChange={(v) => updateParams({ price_source: v })}
							items={[
								{
									value: "close",
									label: t(
										"blocks.level_proximity_condition.price_sources.close",
									),
								},
								{
									value: "high",
									label: t(
										"blocks.level_proximity_condition.price_sources.high",
									),
								},
								{
									value: "low",
									label: t(
										"blocks.level_proximity_condition.price_sources.low",
									),
								},
							]}
						/>
					</ParamRow>
					<ParamRow title={t("blocks.level_proximity_condition.near_level_on")}>
						<ParamSelect
							value={pParams.timeframe}
							onChange={(v) => updateParams({ timeframe: v })}
							items={[
								{ value: "1m", label: "1m" },
								{ value: "5m", label: "5m" },
								{ value: "15m", label: "15m" },
								{ value: "1h", label: "1h" },
								{ value: "4h", label: "4h" },
							]}
						/>
					</ParamRow>
					<ParamRow
						title={`${t("blocks.level_proximity_condition.tf_for")}...`}
					>
						<DynamicValueInput
							value={pParams.lookback_period}
							onChange={(v) => updateParams({ lookback_period: v })}
						/>
						<span className="text-sm text-muted-foreground">
							{t("blocks.level_proximity_condition.bars_within")}
						</span>
					</ParamRow>
					<ParamRow
						title={t("blocks.level_proximity_condition.within_proximity")}
					>
						<DynamicValueInput
							value={pParams.proximity_value}
							onChange={(v) => updateParams({ proximity_value: v })}
						/>
						<ParamSelect
							value={pParams.proximity_type}
							onChange={(v) => updateParams({ proximity_type: v })}
							items={[
								{ value: "atr_multiplier", label: "x ATR" },
								{ value: "percentage", label: "%" },
							]}
							className="w-28"
						/>
					</ParamRow>
					<ParamRow>
						<div className="flex items-center space-x-2">
							<input
								type="checkbox"
								id="is_data_provider"
								checked={pParams.is_data_provider || false}
								onChange={(e) =>
									updateParams({ is_data_provider: e.target.checked })
								}
								className="form-checkbox"
							/>
							<label
								htmlFor="is_data_provider"
								className="text-sm font-medium text-[hsl(var(--foreground))]"
							>
								{t("blocks.local_level.is_data_provider_label")}
							</label>
						</div>
					</ParamRow>
				</>
			);
		}

		default:
			return (
				<p className="text-sm text-muted-foreground p-4 text-center">
					Configuration for this block not found.
				</p>
			);
	}
};

const BlockInspectorModal: React.FC<BlockInspectorModalProps> = ({
	isOpen,
	onClose,
	blockId,
	section,
	initialDisplayMode,
}) => {
	const { t } = useTranslation("pwa-common");
	const store = useStrategyEditorStore();
	const {
		updateBlockParams,
		removeBlock,
		removeManagementBlock,
		updateCompositeConditionParams,
		updateBlockDisplayMode,
	} = store;
	const [displayMode, setDisplayMode] = useState<"simplified" | "expanded">(
		"simplified",
	);

	const currentBlock = useMemo(() => {
		if (!blockId) return null;
		return store.findBlock(blockId);
	}, [blockId, store]);

	useEffect(() => {
		if (isOpen) {
			const timer = setTimeout(() => {
				setDisplayMode(initialDisplayMode || "simplified");
			}, 0);
			return () => clearTimeout(timer);
		}
	}, [isOpen, initialDisplayMode]);

	const swipeHandlers = useSwipeable({
		onSwipedDown: () => onClose(),
		preventScrollOnSwipe: true,
		trackMouse: true,
	});

	const handleUpdate = useCallback(
		(newParams: Record<string, any>) => {
			if (!currentBlock) return;
			if ("isComposite" in currentBlock && currentBlock.isComposite) {
				updateCompositeConditionParams(currentBlock.id, newParams);
			} else {
				updateBlockParams(currentBlock.id, newParams);
			}
		},
		[currentBlock, updateBlockParams, updateCompositeConditionParams],
	);

	const handleToggleDisplayMode = useCallback(() => {
		if (!currentBlock) return;
		const newMode = displayMode === "simplified" ? "expanded" : "simplified";
		setDisplayMode(newMode);
		updateBlockDisplayMode(currentBlock.id, newMode);
	}, [currentBlock, displayMode, updateBlockDisplayMode]);

	const handleSave = useCallback(() => onClose(), [onClose]);

	const handleDelete = useCallback(() => {
		if (currentBlock && window.confirm(t("blocks.confirm_delete_block"))) {
			if (section === "positionManagement")
				removeManagementBlock(currentBlock.id);
			else removeBlock(currentBlock.id);
			onClose();
		}
	}, [currentBlock, section, removeBlock, removeManagementBlock, onClose, t]);

	const isComposite =
		currentBlock && "isComposite" in currentBlock && currentBlock.isComposite;
	const blockType = isComposite
		? (currentBlock as ConditionBlock).compositeType!
		: currentBlock?.type;

	return (
		<>
			<div
				className={`fixed inset-0 bg-black/50 z-40 transition-opacity duration-300 ${isOpen ? "opacity-100" : "opacity-0 pointer-events-none"}`}
				onClick={onClose}
			/>
			<div
				{...swipeHandlers}
				className={`fixed bottom-0 left-0 right-0 bg-[hsl(var(--card))] rounded-t-3xl shadow-[-4px_0_20px_rgba(0,0,0,0.1)] w-full max-w-lg mx-auto z-50 transition-transform duration-300 ease-out ${isOpen ? "translate-y-0" : "translate-y-full"}`}
			>
				<div
					{...swipeHandlers}
					className="w-12 h-1 bg-[hsl(var(--border))] rounded-full mx-auto mt-3 mb-4 cursor-grab"
				></div>
				<div className="px-6 pb-4 border-b border-[hsl(var(--border))]">
					<div className="flex justify-between items-start">
						<div className="flex-1">
							<h2 className="text-xl font-medium text-[hsl(var(--card-foreground))]">
								{t("editor.configPanel.paramsTitle")}:{" "}
								{blockType ? t(`blocks.${blockType}.title`) : ""}
							</h2>
							{blockType && (
								<p className="text-sm text-[hsl(var(--muted-foreground))] mt-1">
									{t(`blocks.${blockType}.desc`)}
								</p>
							)}
						</div>
						{isComposite && (
							<button
								onClick={handleToggleDisplayMode}
								className="p-2 rounded-full transition hover:bg-[hsl(var(--secondary))] ml-2 flex-shrink-0"
							>
								<ICONS.Settings className="w-5 h-5 text-[hsl(var(--muted-foreground))]" />
							</button>
						)}
						<button
							onClick={onClose}
							className="w-8 h-8 flex items-center justify-center rounded-full transition hover:bg-[hsl(var(--secondary))] ml-2 flex-shrink-0"
						>
							<ICONS.Close className="w-5 h-5 text-[hsl(var(--muted-foreground))]" />
						</button>
					</div>
				</div>

				<div className="p-6 max-h-[60vh] overflow-y-auto">
					{currentBlock ? (
						isComposite ? (
							<>
								{renderCompositeBlockContent(
									currentBlock as ConditionBlock,
									handleUpdate,
									t,
								)}
								{displayMode === "expanded" && (
									<div className="mt-4 pt-4 border-t border-[hsl(var(--border))]">
										<h3 className="text-sm font-semibold text-[hsl(var(--muted-foreground))] mb-2">
											{t("blocks.showAdvancedMode")}
										</h3>
										{(currentBlock as ConditionBlock).children?.map((child) => (
											<div
												key={child.id}
												className="mb-2 opacity-70 pointer-events-none"
											>
												<BlockItem
													block={child}
													section={section}
													onClick={() => {}}
													onAddCondition={() => {}}
												/>
											</div>
										))}
									</div>
								)}
							</>
						) : (
							renderBlockContent(currentBlock, handleUpdate, t)
						)
					) : (
						<p className="text-center text-sm text-[hsl(var(--muted-foreground))] py-8">
							{t("blocks.select_block_to_configure")}
						</p>
					)}
				</div>

				<div className="flex gap-3 mt-2 p-6 border-t border-[hsl(var(--border))]">
					<button
						className="flex-1 py-3 rounded-lg border-none text-sm font-medium bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] transition hover:opacity-90"
						onClick={handleDelete}
					>
						{t("blocks.delete")}
					</button>
					<button
						className="flex-1 py-3 rounded-lg border-none text-sm font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90"
						onClick={handleSave}
					>
						{t("buttons.save")}
					</button>
				</div>
			</div>
		</>
	);
};

export default BlockInspectorModal;
