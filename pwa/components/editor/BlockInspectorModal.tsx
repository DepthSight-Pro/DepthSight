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

const renderBlockContent = (
	block: ConditionBlock | ManagementBlock,
	updateParams: (p: Record<string, any>) => void,
	t: TranslationFunction,
): React.ReactNode | null => {
	const p = (block.params as Record<string, any>) || {};
	const handleNumberChange = (key: string, value: string) =>
		updateParams({ [key]: parseFloat(value) || 0 });

	switch (block.type as ComponentType) {
		case "market_activity":
			return (
				<>
					<ParamRow title="Mode">
						<ParamSelect
							value={p.mode}
							onChange={(v) => updateParams({ mode: v })}
							items={[
								{ value: "percentile", label: "Percentile" },
								{ value: "threshold", label: "Threshold" },
							]}
						/>
					</ParamRow>
					<ParamRow title="NATR">
						<DynamicValueInput
							value={p.natr_threshold}
							onChange={(v) => updateParams({ natr_threshold: v })}
						/>
					</ParamRow>
					<ParamRow title="Relative volume">
						<DynamicValueInput
							value={p.rel_vol_threshold}
							onChange={(v) => updateParams({ rel_vol_threshold: v })}
						/>
					</ParamRow>
				</>
			);
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
						<SimpleInput
							value={p.ttl_seconds || ""}
							onChange={(e) =>
								handleNumberChange("ttl_seconds", e.target.value)
							}
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
						/>
					</ParamRow>
					<ParamRow title="Lookback">
						<DynamicValueInput
							value={p.lookback_candles}
							onChange={(v) => updateParams({ lookback_candles: v })}
						/>
					</ParamRow>
					<ParamRow title="Tolerance %">
						<DynamicValueInput
							value={p.touch_tolerance_pct}
							onChange={(v) => updateParams({ touch_tolerance_pct: v })}
						/>
					</ParamRow>
					<ParamRow title="Min touches">
						<DynamicValueInput
							value={p.min_touches}
							onChange={(v) => updateParams({ min_touches: v })}
						/>
					</ParamRow>
				</>
			);
		case "volatility_squeeze":
			return (
				<>
					<ParamRow
						title={t("blocks.volatility_squeeze.text", "Volatility squeeze")}
					>
						<DynamicValueInput
							value={p.lookback_candles}
							onChange={(v) => updateParams({ lookback_candles: v })}
						/>
					</ParamRow>
					<ParamRow title="Squeeze ratio">
						<DynamicValueInput
							value={p.squeeze_ratio}
							onChange={(v) => updateParams({ squeeze_ratio: v })}
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
						<DynamicValueInput
							value={p.lookback_candles}
							onChange={(v) => updateParams({ lookback_candles: v })}
						/>
					</ParamRow>
					<ParamRow title="Min points">
						<DynamicValueInput
							value={p.min_points}
							onChange={(v) => updateParams({ min_points: v })}
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
						/>
					</ParamRow>
					<ParamRow title={t("blocks.grid_management.lower", "Lower")}>
						<DynamicValueInput
							value={p.lower_bound}
							onChange={(v) => updateParams({ lower_bound: v })}
						/>
					</ParamRow>
				</>
			);
		case "trading_session":
			return (
				<ParamRow title={t("blocks.trading_session.text")}>
					<ParamSelect
						value={p.session}
						onChange={(v) => updateParams({ session: v })}
						items={[
							{ value: "london", label: "London" },
							{ value: "new_york", label: "New York" },
							{ value: "asia", label: "Asia" },
							{ value: "sydney", label: "Sydney" },
						]}
					/>
				</ParamRow>
			);
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
								value: "consolidation",
								label: t("blocks.btc_state_filter.states.consolidation"),
							},
							{
								value: "trending_up",
								label: t("blocks.btc_state_filter.states.trending_up"),
							},
							{
								value: "trending_down",
								label: t("blocks.btc_state_filter.states.trending_down"),
							},
							{ value: "any", label: t("blocks.btc_state_filter.states.any") },
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
						/>
					</ParamRow>
				</>
			);
		case "natr_filter":
			return (
				<ParamRow title="NATR threshold >">
					<DynamicValueInput
						value={p.natr_threshold}
						onChange={(v) => updateParams({ natr_threshold: v })}
					/>
				</ParamRow>
			);
		case "rel_vol_filter":
			return (
				<ParamRow title="Rel. volume threshold >">
					<DynamicValueInput
						value={p.rel_vol_threshold}
						onChange={(v) => updateParams({ rel_vol_threshold: v })}
					/>
				</ParamRow>
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
				<ParamRow title={t("blocks.volume_confirmation.text")}>
					<SimpleInput
						value={p.multiplier || ""}
						onChange={(e) => handleNumberChange("multiplier", e.target.value)}
					/>
					<span className="text-muted-foreground">
						{t("blocks.volume_confirmation.x_average")}
					</span>
				</ParamRow>
			);
		case "price_consolidation":
			return (
				<>
					<ParamRow title="Period (bars)">
						<DynamicValueInput
							value={p.lookback_period}
							onChange={(v) => updateParams({ lookback_period: v })}
						/>
					</ParamRow>
					<ParamRow title="Max range (in ATR)">
						<DynamicValueInput
							value={p.max_range_atr}
							onChange={(v) => updateParams({ max_range_atr: v })}
						/>
					</ParamRow>
				</>
			);
		case "return_to_level":
			return (
				<>
					<ParamRow title="Level block ID">
						<DynamicValueInput
							value={p.level_block_id}
							onChange={(v) => updateParams({ level_block_id: v })}
						/>
					</ParamRow>
					<ParamRow title="Retest type">
						<ParamSelect
							value={p.retest_type}
							onChange={(v) => updateParams({ retest_type: v })}
							items={[
								{ value: "touch", label: "Touch" },
								{ value: "breakout_retest", label: "Breakout and retest" },
							]}
						/>
					</ParamRow>
					<ParamRow title="Confirmation time (sec)">
						<DynamicValueInput
							value={p.confirmation_time_sec}
							onChange={(v) => updateParams({ confirmation_time_sec: v })}
						/>
					</ParamRow>
				</>
			);
		case "rsi_condition":
			return (
				<>
					<ParamRow title="RSI period">
						<SimpleInput
							value={p.period || ""}
							onChange={(e) => handleNumberChange("period", e.target.value)}
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
						<SimpleInput
							value={p.value || ""}
							onChange={(e) => handleNumberChange("value", e.target.value)}
						/>
					</ParamRow>
					<ParamRow title="Offset (bars back)">
						<SimpleInput
							value={p.shift || ""}
							onChange={(e) => handleNumberChange("shift", e.target.value)}
						/>
					</ParamRow>
				</>
			);
		case "ma_cross_condition":
			return (
				<>
					<ParamRow title="Fast MA">
						<SimpleInput
							value={p.fast_period || ""}
							onChange={(e) =>
								handleNumberChange("fast_period", e.target.value)
							}
						/>
					</ParamRow>
					<ParamRow title="Slow MA">
						<SimpleInput
							value={p.slow_period || ""}
							onChange={(e) =>
								handleNumberChange("slow_period", e.target.value)
							}
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
							value={p.shift || ""}
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
					/>
				</ParamRow>
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
