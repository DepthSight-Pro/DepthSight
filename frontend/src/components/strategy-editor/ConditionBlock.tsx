// src/components/strategy-editor/ConditionBlock.tsx

import { useDraggable, useDroppable } from "@dnd-kit/core";
import type { TFunction } from "i18next";
import {
	Activity,
	AlertTriangle,
	Anchor,
	AreaChart,
	BarChartHorizontal,
	CandlestickChart,
	ChevronDown,
	ChevronRight,
	Combine,
	Eye,
	Gauge,
	GitMerge,
	Globe,
	GripVertical,
	Layers,
	Move,
	Plus,
	Rss,
	Settings2,
	Shield,
	Sigma,
	Signal,
	Target,
	Timer,
	TrendingDown,
	TrendingUp,
	Waves,
	Wind,
	X,
} from "lucide-react";
import React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import { type DynamicParam, DynamicValueInput } from "./DynamicValueInput";
import { InfoTooltip } from "./InfoTooltip";
import type {
	ConditionBlock as BlockType,
	ComponentType,
	ManagementBlock,
} from "./types";

interface ConditionBlockProps {
	block: BlockType;
	stateKey?: "filters" | "entryConditions";
	depth?: number;
}

const compositeIcons: Record<
	NonNullable<BlockType["compositeType"]>,
	React.ReactNode
> = {
	tape_condition: <Wind className="w-4 h-4 text-muted-foreground" />,
	order_book_zone_condition: (
		<Layers className="w-4 h-4 text-muted-foreground" />
	),
	level_proximity_condition: (
		<AreaChart className="w-4 h-4 text-muted-foreground" />
	),
};

const ShiftInput = ({
	value,
	onChange,
}: {
	value: number;
	onChange: (val: number) => void;
}) => (
	<Input
		type="number"
		placeholder="0"
		value={value || ""}
		onChange={(e) => onChange(parseInt(e.target.value, 10) || 0)}
		className="w-14 h-8 text-center"
	/>
);

const ParamSelect = ({
	value,
	onChange,
	items,
	placeholder,
	className,
}: {
	value: string | number | undefined;
	onChange: (val: string) => void;
	items: { value: string | number; label: string }[];
	placeholder?: string;
	className?: string;
}) => (
	<Select value={value ? String(value) : undefined} onValueChange={onChange}>
		<SelectTrigger className={cn("h-8", className)}>
			<SelectValue placeholder={placeholder} />
		</SelectTrigger>
		<SelectContent>
			{items.map((i) => (
				<SelectItem key={String(i.value)} value={String(i.value)}>
					{i.label}
				</SelectItem>
			))}
		</SelectContent>
	</Select>
);

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

const collectLevelProviderBlocks = (block?: BlockType): BlockType[] => {
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
	blocks: ManagementBlock[],
): BlockType[] => {
	return blocks.flatMap((block) => {
		const b = block as unknown as Record<string, unknown>;
		return [
			...(block.children || []).flatMap(collectLevelProviderBlocks),
			...(b.if_conditions
				? collectLevelProviderBlocks(b.if_conditions as BlockType)
				: []),
			...(Array.isArray(b.then_actions)
				? collectManagementLevelProviderBlocks(
						b.then_actions as ManagementBlock[],
					)
				: []),
		];
	});
};

const LevelBlockSelect = ({
	value,
	onChange,
	t,
}: {
	value: string | null | undefined;
	onChange: (val: string) => void;
	t: TFunction<"strategy-editor">;
}) => {
	const filters = useStrategyEditorStore((s) => s.filters);
	const entryConditions = useStrategyEditorStore((s) => s.entryConditions);
	const positionManagement = useStrategyEditorStore(
		(s) => s.positionManagement,
	);

	const options = React.useMemo(() => {
		return [
			...collectLevelProviderBlocks(filters),
			...collectLevelProviderBlocks(entryConditions),
			...collectManagementLevelProviderBlocks(positionManagement),
		];
	}, [filters, entryConditions, positionManagement]);

	return (
		<Select value={value || undefined} onValueChange={onChange}>
			<SelectTrigger className="h-8 w-44">
				<SelectValue
					placeholder={t(
						"dynamic_sources.block_results.title",
						"Block Results",
					)}
				/>
			</SelectTrigger>
			<SelectContent>
				{options.map((option) => (
					<SelectItem key={option.id} value={option.id}>
						{t(`blocks.${option.type}.title`)} [{option.id.slice(0, 4)}]
					</SelectItem>
				))}
			</SelectContent>
		</Select>
	);
};

const renderBlockContent = (
	block: BlockType,
	updateParams: (p: Record<string, unknown>) => void,
	t: TFunction<"strategy-editor">,
): React.ReactNode | null => {
	const p = block.params || {};
	const icons: Record<string, React.ReactNode> = {
		trading_session: <Timer className="w-4 h-4 text-muted-foreground" />,
		volatility_filter: <Activity className="w-4 h-4 text-muted-foreground" />,
		trend_filter: <TrendingDown className="w-4 h-4 text-muted-foreground" />,
		senior_tf_confluence: <Rss className="w-4 h-4 text-muted-foreground" />,
		market_activity: <Activity className="w-4 h-4 text-muted-foreground" />,
		btc_state_filter: <Globe className="w-4 h-4 text-muted-foreground" />,
		correlation: <GitMerge className="w-4 h-4 text-muted-foreground" />,
		open_interest: <Rss className="w-4 h-4 text-muted-foreground" />,
		natr_filter: <Activity className="w-4 h-4 text-muted-foreground" />,
		rel_vol_filter: <Gauge className="w-4 h-4 text-muted-foreground" />,
		order_book_zone: <Layers className="w-4 h-4 text-muted-foreground" />,
		l2_microstructure: <Shield className="w-4 h-4 text-muted-foreground" />,
		l2_microstructure_check: (
			<Shield className="w-4 h-4 text-muted-foreground" />
		),
		significant_level: <Anchor className="w-4 h-4 text-muted-foreground" />,
		local_level: <AreaChart className="w-4 h-4 text-muted-foreground" />,
		tape_analysis: <Wind className="w-4 h-4 text-muted-foreground" />,
		classic_pattern: (
			<CandlestickChart className="w-4 h-4 text-muted-foreground" />
		),
		round_level: <Target className="w-4 h-4 text-muted-foreground" />,
		trend_direction: <TrendingUp className="w-4 h-4 text-muted-foreground" />,
		volume_confirmation: <Signal className="w-4 h-4 text-muted-foreground" />,
		return_to_level: (
			<AlertTriangle className="w-4 h-4 text-muted-foreground" />
		),
		ma_cross_condition: <Move className="w-4 h-4 text-muted-foreground" />,
		rsi_condition: <Settings2 className="w-4 h-4 text-muted-foreground" />,
		value_comparison: <Sigma className="w-4 h-4 text-muted-foreground" />,
		macd_condition: (
			<BarChartHorizontal className="w-4 h-4 text-muted-foreground" />
		),
		bollinger_bands_condition: (
			<Waves className="w-4 h-4 text-muted-foreground" />
		),
		stochastic_condition: <Wind className="w-4 h-4 text-muted-foreground" />,
		price_vs_level: <Target className="w-4 h-4 text-muted-foreground" />,
		level_touch_analyzer: <Target className="w-4 h-4 text-muted-foreground" />,
		volatility_squeeze: <Activity className="w-4 h-4 text-muted-foreground" />,
		price_action_analyzer: (
			<CandlestickChart className="w-4 h-4 text-muted-foreground" />
		),
		tradingview_signal: <Signal className="w-4 h-4 text-primary" />,
		AND: <Combine className="w-4 h-4 text-primary" />,
		OR: <GitMerge className="w-4 h-4 text-amber-500" />,
	};

	return (
		<div className="flex items-center gap-2 flex-wrap">
			{icons[block.type] || (
				<Settings2 className="w-4 h-4 text-muted-foreground" />
			)}
			{(() => {
				switch (block.type) {
					case "time_filter": // Genetic alias - fallthrough
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
								<span>{t("blocks.trading_session.text")}</span>
								<ParamSelect
									value={filterMode}
									onChange={(v: string) => updateParams({ filter_mode: v })}
									items={[
										{
											value: "session",
											label:
												t("blocks.trading_session.modes.session") ||
												"By Session",
										},
										{
											value: "hours",
											label:
												t("blocks.trading_session.modes.hours") || "By Hours",
										},
									]}
									className="w-36"
								/>
								{filterMode === "hours" ? (
									<>
										<span>UTC</span>
										<Input
											type="number"
											placeholder="0"
											value={startH}
											onChange={(e) =>
												updateParams({
													start_hour_utc: parseInt(e.target.value, 10) || 0,
												})
											}
											className="w-16 h-8"
											min={0}
											max={23}
										/>
										<span>—</span>
										<Input
											type="number"
											placeholder="23"
											value={endH}
											onChange={(e) =>
												updateParams({
													end_hour_utc: parseInt(e.target.value, 10) || 23,
												})
											}
											className="w-16 h-8"
											min={0}
											max={23}
										/>
										<ParamSelect
											value={mode}
											onChange={(v: string) => updateParams({ mode: v })}
											items={[
												{
													value: "include",
													label:
														t("blocks.trading_session.include") || "Include",
												},
												{
													value: "exclude",
													label:
														t("blocks.trading_session.exclude") || "Exclude",
												},
											]}
											className="w-28"
										/>
									</>
								) : (
									<ParamSelect
										value={p.session || "london"}
										onChange={(v: string) => updateParams({ session: v })}
										items={[
											{
												value: "london",
												label: t("blocks.trading_session.sessions.london"),
											},
											{
												value: "new_york",
												label: t("blocks.trading_session.sessions.new_york"),
											},
											{
												value: "asia",
												label: t("blocks.trading_session.sessions.asia"),
											},
											{
												value: "sydney",
												label: t("blocks.trading_session.sessions.sydney"),
											},
										]}
										className="w-36"
									/>
								)}
							</>
						);
					}
					case "volatility_filter":
						return (
							<>
								<span>{t("blocks.volatility_filter.text")}</span>
								<ParamSelect
									value={p.indicator}
									onChange={(v: string) => updateParams({ indicator: v })}
									items={[
										{ value: "ATR", label: "ATR" },
										{ value: "BBW", label: "Bollinger Bands Width" },
									]}
									className="w-44"
								/>
								<ParamSelect
									value={p.operator}
									onChange={(v: string) => updateParams({ operator: v })}
									items={[
										{ value: "gt", label: ">" },
										{ value: "lt", label: "<" },
									]}
									className="w-16"
								/>
								<div className="w-32">
									<DynamicValueInput
										value={p.value}
										onChange={(v: DynamicParam) => updateParams({ value: v })}
									/>
								</div>
							</>
						);
					case "trend_filter":
						return (
							<>
								<span>{t("blocks.trend_filter.text")}</span>
								<ParamSelect
									value={p.indicator}
									onChange={(v: string) => updateParams({ indicator: v })}
									items={[{ value: "ADX", label: "ADX (14)" }]}
									className="w-28"
								/>
								<span> &gt; </span>
								<div className="w-32">
									<DynamicValueInput
										value={p.threshold}
										onChange={(v: DynamicParam) =>
											updateParams({ threshold: v })
										}
									/>
								</div>
							</>
						);
					case "senior_tf_confluence":
						return (
							<>
								<span>{t("blocks.senior_tf_confluence.text")}</span>
								<ParamSelect
									value={p.timeframe}
									onChange={(v: string) => updateParams({ timeframe: v })}
									items={[
										{ value: "15m", label: "15m" },
										{ value: "1h", label: "1h" },
										{ value: "4h", label: "4h" },
										{ value: "1d", label: "1d" },
									]}
									className="w-32"
								/>
							</>
						);
					case "market_activity":
						return (
							<>
								<span>{t("blocks.market_activity.text")}</span>
								<ParamSelect
									value={p.mode || "relative"}
									onChange={(v: string) => updateParams({ mode: v })}
									items={[
										{ value: "relative", label: "Relative Volume" },
										{ value: "percentile", label: "Percentile Spike" },
									]}
									className="w-40"
								/>
								<span>NATR &gt;</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.natr_threshold}
										onChange={(v: DynamicParam) =>
											updateParams({ natr_threshold: v })
										}
									/>
								</div>
								{p.mode !== "percentile" && (
									<>
										<span>Rel.Vol &gt;</span>
										<div className="w-32">
											<DynamicValueInput
												value={p.rel_vol_threshold}
												onChange={(v: DynamicParam) =>
													updateParams({ rel_vol_threshold: v })
												}
											/>
										</div>
										<span>{t("blocks.rel_vol_filter.lookback")}</span>
										<div className="w-32">
											<DynamicValueInput
												value={p.lookback_period || 20}
												onChange={(v: DynamicParam) =>
													updateParams({ lookback_period: v })
												}
											/>
										</div>
									</>
								)}
							</>
						);
					case "btc_state_filter":
						return (
							<>
								<span>{t("blocks.btc_state_filter.required_state")}</span>
								<ParamSelect
									value={p.required_state}
									onChange={(v: string) => updateParams({ required_state: v })}
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
										{
											value: "Any",
											label: t("blocks.btc_state_filter.states.any"),
										},
									]}
									className="w-32"
								/>
							</>
						);
					case "correlation":
						return (
							<>
								<span>
									{t("blocks.correlation.correlation_with")} BTCUSDT for
								</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.lookback}
										onChange={(v: DynamicParam) =>
											updateParams({ lookback: v })
										}
									/>
								</div>
								<span>bars</span>
								<ParamSelect
									value={p.operator}
									onChange={(v: string) => updateParams({ operator: v })}
									items={[
										{ value: "gt", label: ">" },
										{ value: "lt", label: "<" },
									]}
									className="w-16"
								/>
								<div className="w-32">
									<DynamicValueInput
										value={p.value}
										onChange={(v: DynamicParam) => updateParams({ value: v })}
									/>
								</div>
							</>
						);
					case "open_interest":
						return (
							<>
								<span>{t("blocks.open_interest.analyze")}</span>
								<ParamSelect
									value={p.analyze}
									onChange={(v: string) => updateParams({ analyze: v })}
									items={[
										{
											value: "change_pct",
											label: t(
												"blocks.open_interest.analysis_types.change_pct",
											),
										},
										{
											value: "absolute_value",
											label: t(
												"blocks.open_interest.analysis_types.absolute_value",
											),
										},
									]}
									className="w-32"
								/>
								<span>for</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.lookback}
										onChange={(v: DynamicParam) =>
											updateParams({ lookback: v })
										}
									/>
								</div>
								<span>bars</span>
								<ParamSelect
									value={p.operator}
									onChange={(v: string) => updateParams({ operator: v })}
									items={[
										{ value: "gt", label: ">" },
										{ value: "lt", label: "<" },
									]}
									className="w-16"
								/>
								<div className="w-32">
									<DynamicValueInput
										value={p.value}
										onChange={(v: DynamicParam) => updateParams({ value: v })}
									/>
								</div>
							</>
						);
					case "natr_filter":
						return (
							<>
								<span>NATR &gt;</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.natr_threshold || p.value || p.threshold}
										onChange={(v: DynamicParam) =>
											updateParams({ natr_threshold: v })
										}
									/>
								</div>
							</>
						);
					case "rel_vol_filter":
						return (
							<>
								<span>{t("blocks.rel_vol_filter.text_1")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.rel_vol_threshold}
										onChange={(v: DynamicParam) =>
											updateParams({ rel_vol_threshold: v })
										}
									/>
								</div>
								<span>{t("blocks.rel_vol_filter.lookback")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.lookback_period || 20}
										onChange={(v: DynamicParam) =>
											updateParams({ lookback_period: v })
										}
									/>
								</div>
							</>
						);
					case "tape_analysis":
						return (
							<>
								<span className="font-semibold text-sm">
									{t("blocks.tape_analysis.text")}
								</span>
								<ParamSelect
									value={p.time_window_sec}
									onChange={(v: string) =>
										updateParams({ time_window_sec: parseInt(v, 10) })
									}
									items={[
										{ value: 5, label: "5s" },
										{ value: 10, label: "10s" },
										{ value: 30, label: "30s" },
									]}
									className="w-32"
								/>
								<span className="text-xs text-muted-foreground">
									(Provides data)
								</span>
							</>
						);
					case "classic_pattern":
						return (
							<>
								<span>{t("blocks.classic_pattern.text")}</span>
								<ParamSelect
									value={p.pattern_name}
									onChange={(v: string) =>
										updateParams({ pattern_name: v, side: "any" })
									}
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
									className="w-32"
								/>
								{p.pattern_name === "pin_bar" && (
									<ParamSelect
										value={p.side || "any"}
										onChange={(v: string) => updateParams({ side: v })}
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
										className="w-32"
									/>
								)}
							</>
						);
					case "price_consolidation":
						return (
							<>
								<span>{t("blocks.price_consolidation.text_1")}</span>
								<ParamSelect
									value={p.timeframe || "auto"}
									onChange={(v: string) => updateParams({ timeframe: v })}
									items={[
										{ value: "auto", label: "Auto" },
										{ value: "1m", label: "1m" },
										{ value: "5m", label: "5m" },
										{ value: "15m", label: "15m" },
										{ value: "1h", label: "1h" },
										{ value: "4h", label: "4h" },
										{ value: "1d", label: "1d" },
									]}
									className="w-24"
								/>
								<div className="w-32">
									<DynamicValueInput
										value={p.lookback_period}
										onChange={(v: DynamicParam) =>
											updateParams({ lookback_period: v })
										}
									/>
								</div>
								<span>{t("blocks.price_consolidation.text_2")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.max_range_atr}
										onChange={(v: DynamicParam) =>
											updateParams({ max_range_atr: v })
										}
									/>
								</div>
								<span>{t("blocks.price_consolidation.text_3")}</span>
							</>
						);
					case "order_book_zone":
						return (
							<>
								<span className="font-semibold text-sm">
									{t("blocks.order_book_zone.text_1")}
								</span>
								<ParamSelect
									value={p.side}
									onChange={(v: string) => updateParams({ side: v })}
									items={[
										{
											value: "bids",
											label: t("blocks.order_book_zone.options.bids"),
										},
										{
											value: "asks",
											label: t("blocks.order_book_zone.options.asks"),
										},
									]}
									className="w-32"
								/>
								<span>{t("blocks.order_book_zone.text_2")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.range_value}
										onChange={(v: DynamicParam) =>
											updateParams({ range_value: v })
										}
									/>
								</div>
								<ParamSelect
									value={p.range_type}
									onChange={(v: string) => updateParams({ range_type: v })}
									items={[
										{
											value: "Percentage",
											label: t("blocks.order_book_zone.range_type_percentage"),
										},
										{
											value: "ATR Multiplier",
											label: t("blocks.order_book_zone.range_type_atr"),
										},
										{
											value: "Ticks",
											label: t("blocks.order_book_zone.range_type_ticks"),
										},
									]}
									className="w-40"
								/>
								<span className="text-xs text-muted-foreground">
									(Provides data)
								</span>
							</>
						);
					case "l2_microstructure":
					case "l2_microstructure_check":
						return (
							<>
								<span>{t("blocks.l2_microstructure_check.text_1")}</span>
								<ParamSelect
									value={p.check_type}
									onChange={(v: string) => updateParams({ check_type: v })}
									items={[
										{
											value: "large_order",
											label: t(
												"blocks.l2_microstructure_check.options.large_order",
											),
										},
									]}
									className="w-40"
								/>
								<span>&gt; $</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.single_order_size_usd}
										onChange={(v: DynamicParam) =>
											updateParams({ single_order_size_usd: v })
										}
									/>
								</div>
							</>
						);
					case "local_level":
						return (
							<>
								<span>{t("blocks.local_level.text_1")}</span>
								<ParamSelect
									value={p.timeframe}
									onChange={(v: string) => updateParams({ timeframe: v })}
									items={[
										{ value: "1m", label: "1m" },
										{ value: "5m", label: "5m" },
										{ value: "15m", label: "15m" },
										{ value: "1h", label: "1h" },
										{ value: "4h", label: "4h" },
									]}
									className="w-32"
								/>
								<span>{t("blocks.local_level.text_2")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.lookback_period}
										onChange={(v: DynamicParam) =>
											updateParams({ lookback_period: v })
										}
									/>
								</div>
								<span>
									{t("blocks.local_level.level_type_label", {
										defaultValue: "level",
									})}
								</span>
								<ParamSelect
									value={p.level_type || "all"}
									onChange={(v: string) => updateParams({ level_type: v })}
									items={[
										{
											value: "high",
											label: t("blocks.local_level.level_types.high", {
												defaultValue: "High",
											}),
										},
										{
											value: "low",
											label: t("blocks.local_level.level_types.low", {
												defaultValue: "Low",
											}),
										},
										{
											value: "all",
											label: t("blocks.local_level.level_types.all", {
												defaultValue: "High/Low",
											}),
										},
									]}
									className="w-32"
								/>
								<span>{t("blocks.local_level.text_3")}</span>
								<ParamSelect
									value={p.proximity_type}
									onChange={(v: string) => updateParams({ proximity_type: v })}
									items={[
										{ value: "atr_multiplier", label: "ATR" },
										{ value: "percentage", label: "%" },
									]}
									className="w-32"
								/>
								<span>x</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.proximity_value}
										onChange={(v: DynamicParam) =>
											updateParams({ proximity_value: v })
										}
									/>
								</div>
								<div className="flex items-center space-x-2 mt-2">
									<input
										type="checkbox"
										id="is_data_provider"
										checked={p.is_data_provider || false}
										onChange={(e) =>
											updateParams({ is_data_provider: e.target.checked })
										}
										className="form-checkbox"
									/>
									<label
										htmlFor="is_data_provider"
										className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
									>
										{t("blocks.local_level.is_data_provider_label")}
									</label>
								</div>
							</>
						);
					case "significant_level":
						return (
							<>
								<span>{t("blocks.significant_level.text_1")}</span>
								<ParamSelect
									value={p.level_type}
									onChange={(v: string) => updateParams({ level_type: v })}
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
									className="w-44"
								/>
								<span>{t("blocks.significant_level.text_2")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.proximity_value}
										onChange={(v: DynamicParam) =>
											updateParams({ proximity_value: v })
										}
									/>
								</div>
								<ParamSelect
									value={p.proximity_type}
									onChange={(v: string) => updateParams({ proximity_type: v })}
									items={[
										{
											value: "atr_multiplier",
											label: t(
												"blocks.significant_level.options.atr_multiplier",
											),
										},
										{
											value: "percentage",
											label: t("blocks.significant_level.options.percentage"),
										},
									]}
									className="w-24"
								/>
							</>
						);
					case "round_level":
						return (
							<>
								<span>{t("blocks.round_level.text")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.proximity_value}
										onChange={(v: DynamicParam) =>
											updateParams({ proximity_value: v })
										}
									/>
								</div>
								<ParamSelect
									value={p.proximity_type}
									onChange={(v: string) => updateParams({ proximity_type: v })}
									items={[
										{
											value: "percentage",
											label: t("blocks.round_level.options.percentage"),
										},
										{
											value: "pips",
											label: t("blocks.round_level.options.pips"),
										},
									]}
									className="w-24"
								/>
							</>
						);
					case "trend_direction":
						return (
							<>
								<span>{t("blocks.trend_direction.text_on_tf")}</span>
								<ParamSelect
									value={p.timeframe || "5m"}
									onChange={(v: string) => updateParams({ timeframe: v })}
									items={[
										{ value: "1m", label: "1m" },
										{ value: "5m", label: "5m" },
										{ value: "15m", label: "15m" },
										{ value: "1h", label: "1h" },
										{ value: "4h", label: "4h" },
										{ value: "1d", label: "1d" },
									]}
									className="w-32"
								/>
								<span>{t("blocks.trend_direction.is")}</span>
								<ParamSelect
									value={p.required_trend || "LONG"}
									onChange={(v: string) => updateParams({ required_trend: v })}
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
									className="w-40"
								/>
							</>
						);
					case "volume_confirmation":
						return (
							<>
								<span>{t("blocks.volume_confirmation.text")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.multiplier}
										onChange={(v: DynamicParam) =>
											updateParams({ multiplier: v })
										}
									/>
								</div>
								<span>
									x average {t("blocks.volume_confirmation.lookback")}
								</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.lookback_period || 20}
										onChange={(v: DynamicParam) =>
											updateParams({ lookback_period: v })
										}
									/>
								</div>
							</>
						);
					case "return_to_level":
						return (
							<>
								<span>
									{t("blocks.return_to_level.text1", "Return to level")}
								</span>
								<LevelBlockSelect
									value={
										typeof p.level_block_id === "string"
											? p.level_block_id
											: null
									}
									onChange={(v: string) => updateParams({ level_block_id: v })}
									t={t}
								/>
								<ParamSelect
									value={p.retest_type}
									onChange={(v: string) => updateParams({ retest_type: v })}
									items={[
										{
											value: "touch",
											label: t("blocks.return_to_level.types.touch", "Touch"),
										},
										{
											value: "breakout_retest",
											label: t(
												"blocks.return_to_level.types.breakout_retest",
												"Breakout & Retest",
											),
										},
									]}
									className="w-40"
								/>
								<ParamSelect
									value={p.approach_direction || "any"}
									onChange={(v: string) =>
										updateParams({ approach_direction: v })
									}
									items={[
										{
											value: "any",
											label: t(
												"blocks.return_to_level.directions.any",
												"Any direction",
											),
										},
										{
											value: "from_above",
											label: t(
												"blocks.return_to_level.directions.from_above",
												"From above",
											),
										},
										{
											value: "from_below",
											label: t(
												"blocks.return_to_level.directions.from_below",
												"From below",
											),
										},
									]}
									className="w-36"
								/>
								<span>{t("blocks.return_to_level.within", "within")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.confirmation_time_sec}
										onChange={(v: DynamicParam) =>
											updateParams({ confirmation_time_sec: v })
										}
									/>
								</div>
								<span>{t("blocks.return_to_level.seconds", "sec")}</span>
								<span>{t("blocks.return_to_level.prox", "Prox:")}</span>
								<div className="w-24">
									<DynamicValueInput
										value={p.proximity_value ?? p.proximity_multiplier}
										onChange={(v: DynamicParam) =>
											updateParams({ proximity_value: v })
										}
									/>
								</div>
								<ParamSelect
									value={p.proximity_type || "atr_multiplier"}
									onChange={(v: string) => updateParams({ proximity_type: v })}
									items={[
										{ value: "atr_multiplier", label: "ATR" },
										{ value: "percentage", label: "%" },
									]}
									className="w-20"
								/>
								{p.retest_type === "breakout_retest" && (
									<>
										<span>{t("blocks.return_to_level.dept", "Dept:")}</span>
										<div className="w-24">
											<DynamicValueInput
												value={p.departure_value ?? p.departure_multiplier}
												onChange={(v: DynamicParam) =>
													updateParams({ departure_value: v })
												}
											/>
										</div>
										<ParamSelect
											value={p.departure_type || "atr_multiplier"}
											onChange={(v: string) =>
												updateParams({ departure_type: v })
											}
											items={[
												{ value: "atr_multiplier", label: "ATR" },
												{ value: "percentage", label: "%" },
											]}
											className="w-20"
										/>
									</>
								)}
							</>
						);
					case "rsi_condition":
						return (
							<>
								<span>RSI (</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.period}
										onChange={(v: DynamicParam) => updateParams({ period: v })}
									/>
								</div>
								<span>)</span>
								<ParamSelect
									value={p.operator}
									onChange={(v: string) => updateParams({ operator: v })}
									items={[
										{ value: "gt", label: ">" },
										{ value: "lt", label: "<" },
									]}
									className="w-16"
								/>
								<div className="w-32">
									<DynamicValueInput
										value={p.value}
										onChange={(v: DynamicParam) => updateParams({ value: v })}
									/>
								</div>
								<span>Shift [-</span>
								<ShiftInput
									value={p.shift}
									onChange={(v: number) => updateParams({ shift: v })}
								/>
								<span>]</span>
							</>
						);
					case "ma_cross_condition":
						return (
							<>
								<span>{t("blocks.ma_cross_condition.ma_label")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.fast_period || p.fast}
										onChange={(v: DynamicParam) =>
											updateParams({ fast_period: v })
										}
									/>
								</div>
								<span>{t("blocks.ma_cross_condition.crosses_label")}</span>
								<ParamSelect
									value={p.operator}
									onChange={(v: string) => updateParams({ operator: v })}
									items={[
										{
											value: "crosses_above",
											label: t("blocks.ma_cross_condition.options.above"),
										},
										{
											value: "crosses_below",
											label: t("blocks.ma_cross_condition.options.below"),
										},
									]}
									className="w-28"
								/>
								<span>{t("blocks.ma_cross_condition.ma_label")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.slow_period || p.slow}
										onChange={(v: DynamicParam) =>
											updateParams({ slow_period: v })
										}
									/>
								</div>
								<span>{t("blocks.ma_cross_condition.shift_label_start")}</span>
								<ShiftInput
									value={p.shift}
									onChange={(v: number) => updateParams({ shift: v })}
								/>
								<span>{t("blocks.ma_cross_condition.shift_label_end")}</span>
							</>
						);
					case "value_comparison":
						return (
							<>
								<div className="w-32">
									<DynamicValueInput
										value={p.leftOperand}
										onChange={(v: DynamicParam) =>
											updateParams({ leftOperand: v })
										}
									/>
								</div>
								<ParamSelect
									value={p.operator}
									onChange={(v: string) => updateParams({ operator: v })}
									items={[
										{ value: "gt", label: ">" },
										{ value: "lt", label: "<" },
										{ value: "gte", label: ">=" },
										{ value: "lte", label: "<=" },
									]}
									className="w-16"
								/>
								<div className="w-32">
									<DynamicValueInput
										value={p.rightOperand}
										onChange={(v: DynamicParam) =>
											updateParams({ rightOperand: v })
										}
									/>
								</div>
							</>
						);
					case "macd_condition":
						return (
							<>
								<span>{t("blocks.macd_condition.text_1")}</span>
								<div className="w-28">
									<DynamicValueInput
										value={p.fast_period || p.fast}
										onChange={(v: DynamicParam) =>
											updateParams({ fast_period: v })
										}
									/>
								</div>
								<span>{t("blocks.macd_condition.text_comma")}</span>{" "}
								<div className="w-28">
									<DynamicValueInput
										value={p.slow_period || p.slow}
										onChange={(v: DynamicParam) =>
											updateParams({ slow_period: v })
										}
									/>
								</div>
								<span>{t("blocks.macd_condition.text_comma")}</span>{" "}
								<div className="w-28">
									<DynamicValueInput
										value={p.signal_period || p.signal}
										onChange={(v: DynamicParam) =>
											updateParams({ signal_period: v })
										}
									/>
								</div>
								<span>{t("blocks.macd_condition.text_2")}</span>
								<ParamSelect
									value={p.condition}
									onChange={(v: string) => updateParams({ condition: v })}
									items={[
										{
											value: "macd_cross_above_signal",
											label: t(
												"blocks.macd_condition.options.macd_cross_above_signal",
											),
										},
										{
											value: "macd_cross_below_signal",
											label: t(
												"blocks.macd_condition.options.macd_cross_below_signal",
											),
										},
										{
											value: "hist_gt_zero",
											label: t("blocks.macd_condition.options.hist_gt_zero"),
										},
										{
											value: "hist_lt_zero",
											label: t("blocks.macd_condition.options.hist_lt_zero"),
										},
									]}
									className="w-64"
								/>
								<span>{t("blocks.macd_condition.shift_label_start")}</span>
								<ShiftInput
									value={p.shift}
									onChange={(v: number) => updateParams({ shift: v })}
								/>
								<span>{t("blocks.macd_condition.shift_label_end")}</span>
							</>
						);
					case "bollinger_bands_condition":
					case "bb_condition": // Genetic alias
						return (
							<>
								<span>{t("blocks.bollinger_bands_condition.price_label")}</span>
								<ParamSelect
									value={p.source || "close"}
									onChange={(v: string) => updateParams({ source: v })}
									items={[
										{
											value: "close",
											label: t(
												"blocks.bollinger_bands_condition.source_options.close",
											),
										},
										{
											value: "high",
											label: t(
												"blocks.bollinger_bands_condition.source_options.high",
											),
										},
										{
											value: "low",
											label: t(
												"blocks.bollinger_bands_condition.source_options.low",
											),
										},
									]}
									className="w-32"
								/>
								<ParamSelect
									value={p.location || p.check_type}
									onChange={(v: string) =>
										updateParams({ location: v, check_type: v })
									}
									items={[
										{
											value: "above_upper",
											label: t(
												"blocks.bollinger_bands_condition.location_options.above_upper",
											),
										},
										{
											value: "below_lower",
											label: t(
												"blocks.bollinger_bands_condition.location_options.below_lower",
											),
										},
										{
											value: "price_above_upper",
											label: t(
												"blocks.bollinger_bands_condition.location_options.above_upper",
											),
										},
										{
											value: "price_below_lower",
											label: t(
												"blocks.bollinger_bands_condition.location_options.below_lower",
											),
										},
									]}
									className="w-56"
								/>
								<span>
									{t("blocks.bollinger_bands_condition.shift_label_start")}
								</span>
								<ShiftInput
									value={p.shift}
									onChange={(v: number) => updateParams({ shift: v })}
								/>
								<span>
									{t("blocks.bollinger_bands_condition.shift_label_end")}
								</span>
							</>
						);
					case "stochastic_condition":
					case "stoch_condition": // Genetic alias
						return (
							<>
								<span>{t("blocks.stochastic_condition.text_1")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.k_period}
										onChange={(v: DynamicParam) =>
											updateParams({ k_period: v })
										}
									/>
								</div>
								<span>{t("blocks.stochastic_condition.text_2")}</span>
								<ParamSelect
									value={p.condition || p.operator}
									onChange={(v: string) =>
										updateParams({ condition: v, operator: v })
									}
									items={[
										{
											value: "k_cross_above_d",
											label: t(
												"blocks.stochastic_condition.options.k_cross_above_d",
											),
										},
										{
											value: "k_cross_below_d",
											label: t(
												"blocks.stochastic_condition.options.k_cross_below_d",
											),
										},
										{
											value: "k_above_level",
											label: t(
												"blocks.stochastic_condition.options.k_above_level",
											),
										},
										{
											value: "k_below_level",
											label: t(
												"blocks.stochastic_condition.options.k_below_level",
											),
										},
										{
											value: "cross_above",
											label: t(
												"blocks.stochastic_condition.options.k_cross_above_d",
											),
										},
										{
											value: "cross_below",
											label: t(
												"blocks.stochastic_condition.options.k_cross_below_d",
											),
										},
										{
											value: "gt",
											label: t(
												"blocks.stochastic_condition.options.k_above_level",
											),
										},
										{
											value: "lt",
											label: t(
												"blocks.stochastic_condition.options.k_below_level",
											),
										},
									]}
									className="w-56"
								/>
								<div className="w-32">
									<DynamicValueInput
										value={p.level || p.value}
										onChange={(v: DynamicParam) =>
											updateParams({ level: v, value: v })
										}
									/>
								</div>
								<span>
									{t("blocks.stochastic_condition.shift_label_start")}
								</span>
								<ShiftInput
									value={p.shift}
									onChange={(v: number) => updateParams({ shift: v })}
								/>
								<span>{t("blocks.stochastic_condition.shift_label_end")}</span>
							</>
						);
					case "price_vs_level":
						return (
							<>
								<div className="w-32">
									<DynamicValueInput
										value={p.price_source}
										onChange={(v: DynamicParam) =>
											updateParams({ price_source: v })
										}
									/>
								</div>
								<ParamSelect
									value={p.operator}
									onChange={(v: string) => updateParams({ operator: v })}
									items={[
										{ value: "gt", label: ">" },
										{ value: "lt", label: "<" },
									]}
									className="w-16"
								/>
								<div className="w-32">
									<DynamicValueInput
										value={p.level_source}
										onChange={(v: DynamicParam) =>
											updateParams({ level_source: v })
										}
									/>
								</div>
							</>
						);
					case "tradingview_signal":
						return (
							<>
								<span>{t("blocks.tradingview_signal.signal_id_label")}</span>
								<Input
									value={p.signal_id || ""}
									onChange={(e) => updateParams({ signal_id: e.target.value })}
									className="w-32 h-8"
									placeholder="e.g. buy_1"
								/>
								<span>{t("blocks.tradingview_signal.ttl_label")}</span>
								<div className="w-24">
									<DynamicValueInput
										value={p.ttl_seconds}
										onChange={(v: DynamicParam) =>
											updateParams({ ttl_seconds: v })
										}
									/>
								</div>
							</>
						);
					case "level_touch_analyzer":
						return (
							<>
								<span>{t("blocks.level_touch_analyzer.text_1")}</span>
								<div className="w-32">
									<DynamicValueInput
										value={p.level_source ?? 0}
										onChange={(v: DynamicParam) =>
											updateParams({ level_source: v })
										}
									/>
								</div>
								<span>Lookback:</span>
								<div className="w-20">
									<Input
										type="number"
										value={p.lookback_candles}
										onChange={(e) =>
											updateParams({
												lookback_candles: parseInt(e.target.value, 10) || 50,
											})
										}
										className="h-8"
									/>
								</div>
								<span>Tol %:</span>
								<div className="w-20">
									<Input
										type="number"
										step="0.01"
										value={p.touch_tolerance_pct}
										onChange={(e) =>
											updateParams({
												touch_tolerance_pct: parseFloat(e.target.value) || 0.1,
											})
										}
										className="h-8"
									/>
								</div>
								<span>Touches:</span>
								<div className="w-16">
									<Input
										type="number"
										value={p.min_touches}
										onChange={(e) =>
											updateParams({
												min_touches: parseInt(e.target.value, 10) || 1,
											})
										}
										className="h-8"
									/>
								</div>
								<label className="flex items-center gap-1 text-xs">
									<input
										type="checkbox"
										checked={p.invalidate_on_pierce ?? true}
										onChange={(e) =>
											updateParams({ invalidate_on_pierce: e.target.checked })
										}
									/>
									<span>
										{t("blocks.level_touch_analyzer.invalidate", "No pierce")}
									</span>
								</label>
							</>
						);
					case "volatility_squeeze":
						return (
							<>
								<span>{t("blocks.volatility_squeeze.text")}</span>
								<span>Lookback:</span>
								<div className="w-20">
									<Input
										type="number"
										value={p.lookback_candles}
										onChange={(e) =>
											updateParams({
												lookback_candles: parseInt(e.target.value, 10) || 20,
											})
										}
										className="h-8"
									/>
								</div>
								<span>Ratio:</span>
								<div className="w-20">
									<Input
										type="number"
										step="0.05"
										value={p.squeeze_ratio}
										onChange={(e) =>
											updateParams({
												squeeze_ratio: parseFloat(e.target.value) || 0.6,
											})
										}
										className="h-8"
									/>
								</div>
							</>
						);
					case "price_action_analyzer":
						return (
							<>
								<span>{t("blocks.price_action_analyzer.text")}</span>
								<ParamSelect
									value={p.structure_type}
									onChange={(v: string) => updateParams({ structure_type: v })}
									items={[
										{ value: "higher_lows", label: "Higher Lows" },
										{ value: "lower_highs", label: "Lower Highs" },
									]}
									className="w-36"
								/>
								<span>Lookback:</span>
								<div className="w-20">
									<Input
										type="number"
										value={p.lookback_candles}
										onChange={(e) =>
											updateParams({
												lookback_candles: parseInt(e.target.value, 10) || 30,
											})
										}
										className="h-8"
									/>
								</div>
								<span>Points:</span>
								<div className="w-16">
									<Input
										type="number"
										value={p.min_points}
										onChange={(e) =>
											updateParams({
												min_points: parseInt(e.target.value, 10) || 2,
											})
										}
										className="h-8"
									/>
								</div>
								<span>Order:</span>
								<div className="w-16">
									<Input
										type="number"
										value={p.order}
										onChange={(e) =>
											updateParams({ order: parseInt(e.target.value, 10) || 3 })
										}
										className="h-8"
									/>
								</div>
							</>
						);
					case "AND":
						return (
							<div className="font-semibold">
								<span>{t("blocks.and.title")}</span>
							</div>
						);
					case "OR":
						return (
							<div className="font-semibold">
								<span>{t("blocks.or.title")}</span>
							</div>
						);
					default:
						return (
							<span className="text-sm text-red-500 font-semibold">
								Unknown Block: {block.type}
							</span>
						);
				}
			})()}
		</div>
	);
};

// Drop zone component inside a container with a unique droppable id
interface InnerDropZoneProps {
	blockId: string;
	stateKey?: "filters" | "entryConditions";
	children: React.ReactNode;
	isEmpty: boolean;
	t: (key: string) => string;
}

const InnerDropZone: React.FC<InnerDropZoneProps> = ({
	blockId,
	stateKey,
	children,
	isEmpty,
	t,
}) => {
	const dropId = `inner-${blockId}`;
	const { setNodeRef, isOver } = useDroppable({
		id: dropId,
		data: { isContainer: true, parentId: blockId, stateKey },
	});
	return (
		<div
			ref={setNodeRef}
			className={cn(
				"p-2 min-h-[52px] space-y-2 rounded-md border-2 border-dashed transition-colors",
				isOver ? "border-primary bg-primary/10" : "border-border/60",
			)}
		>
			{isEmpty && !isOver ? (
				<p className="text-xs text-center text-muted-foreground py-1 select-none">
					{t("canvas.dropZone.conditions")}
				</p>
			) : (
				children
			)}
		</div>
	);
};

export const ConditionBlock: React.FC<ConditionBlockProps> = ({
	block,
	stateKey,
	depth = 0,
}) => {
	const { t } = useTranslation("strategy-editor");
	const [isExpanded, setIsExpanded] = React.useState(
		!block.isComposite && (block.type === "AND" || block.type === "OR"),
	);

	// A container is any block that can have child blocks
	const isContainer = ["AND", "OR", "senior_tf_confluence"].includes(
		block.type,
	);

	const {
		removeBlock,
		updateBlockParams,
		updateCompositeConditionParams,
		addCondition,
		addConditionToManagementBlock,
	} = useStrategyEditorStore();

	const handleRemove = () => {
		removeBlock(block.id);
	};

	const handleUpdateCompositeParams = (newParams: Record<string, unknown>) => {
		updateCompositeConditionParams(block.id, newParams);
	};

	// Quick addition of logic blocks inside the container
	const handleAddLogic = (type: ComponentType) => {
		if (stateKey) {
			addCondition(stateKey, type, block.id);
		} else {
			addConditionToManagementBlock(block.id, type);
		}
	};

	const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
		id: block.id,
		data: { isPaletteItem: false, stateKey, ...block },
	});

	// Droppable for the block itself (for moving existing blocks onto it)
	const { setNodeRef: dropRef, isOver } = useDroppable({
		id: block.id,
		data: { isContainer, stateKey, parentId: block.id },
	});

	if (isDragging) {
		return (
			<div
				ref={setNodeRef}
				className="h-12 rounded-lg bg-accent opacity-70 border border-dashed border-primary"
			/>
		);
	}

	// ─── Composite block ────────────────────────────────────────────────────────
	if (block.isComposite && block.compositeType) {
		const compositeTitle = t(`blocks.${block.compositeType}.title`);
		const Icon = isExpanded ? Eye : Settings2;
		const CompositeIcon = compositeIcons[block.compositeType];

		return (
			<div ref={setNodeRef}>
				<Card
					ref={dropRef}
					className={cn(
						"p-2 group/block",
						isOver &&
							"ring-2 ring-primary ring-offset-2 ring-offset-background",
					)}
				>
					<div className="flex items-center justify-between">
						<div className="flex items-center gap-2 flex-grow">
							<div
								{...listeners}
								{...attributes}
								className="cursor-grab touch-none p-1"
							>
								<GripVertical className="w-5 h-5 text-muted-foreground" />
							</div>
							{CompositeIcon}
							<h4 className="font-semibold text-sm">{compositeTitle}</h4>
						</div>
						<div className="flex items-center shrink-0">
							<InfoTooltip blockType={block.compositeType as ComponentType} />
							{block.compositeType !== "level_proximity_condition" && (
								<Button
									variant="ghost"
									size="icon"
									className="h-7 w-7"
									onClick={() => setIsExpanded(!isExpanded)}
								>
									<Icon className="w-4 h-4" />
								</Button>
							)}
							<Button
								variant="ghost"
								size="icon"
								className="h-7 w-7 opacity-50 group-hover/block:opacity-100"
								onClick={handleRemove}
							>
								<X className="w-4 h-4" />
							</Button>
						</div>
					</div>
					<div className="mt-2 pl-8">
						{isExpanded ? (
							<div
								className={cn(
									"p-2 min-h-[50px] space-y-2 rounded-md border-2 border-dashed transition-colors",
									isOver ? "border-primary bg-accent" : "border-border",
								)}
							>
								{block.children && block.children.length > 0 ? (
									block.children.map((child) => (
										<ConditionBlock
											key={child.id}
											block={child}
											stateKey={stateKey}
											depth={depth + 1}
										/>
									))
								) : (
									<p className="text-xs text-center text-muted-foreground py-2">
										{t("canvas.dropZone.conditions")}
									</p>
								)}
							</div>
						) : (
							<div className="flex flex-col gap-2">
								{(() => {
									const provider = block.children?.[0];
									const consumer = block.children?.[1];

									switch (block.compositeType) {
										case "tape_condition": {
											const timeWindow = provider?.params?.time_window_sec || 5;
											const metricKey = normalizeTapeOutputKey(
												consumer?.params?.leftOperand?.key,
											);
											const operator = consumer?.params?.operator || "gt";
											const rightOperand = consumer?.params?.rightOperand || {
												source: "value_multiplier",
												multiplier: 2.0,
											};
											const comparisonType =
												typeof rightOperand === "object" &&
												rightOperand !== null &&
												(rightOperand as Record<string, unknown>).source ===
													"value_multiplier"
													? "multiplier"
													: "absolute";

											return (
												<div className="flex items-center gap-2 flex-wrap">
													<span>{t("blocks.tape_condition.check")}</span>
													<ParamSelect
														value={metricKey}
														onChange={(v: string) =>
															handleUpdateCompositeParams({ metric: v })
														}
														items={[
															{
																value: "delta_volume_usd",
																label: t(
																	"blocks.tape_condition.metrics.delta_volume_usd",
																),
															},
															{
																value: "buy_volume_usd",
																label: t(
																	"blocks.tape_condition.metrics.buy_volume_usd",
																),
															},
															{
																value: "total_volume_usd",
																label: t(
																	"blocks.tape_condition.metrics.total_volume_usd",
																),
															},
															{
																value: "acceleration_multiplier_volume",
																label: t(
																	"blocks.tape_condition.metrics.acceleration_multiplier_volume",
																),
															},
														]}
														className="w-32"
													/>
													<ParamSelect
														value={operator}
														onChange={(v: string) =>
															handleUpdateCompositeParams({ operator: v })
														}
														items={[
															{ value: "gt", label: ">" },
															{ value: "lt", label: "<" },
														]}
														className="w-16"
													/>
													<ParamSelect
														value={comparisonType}
														onChange={(v: string) => {
															if (v === "absolute") {
																handleUpdateCompositeParams({ value: 100000 });
															} else {
																handleUpdateCompositeParams({
																	value: {
																		source: "value_multiplier",
																		multiplier: 2.0,
																	},
																});
															}
														}}
														items={[
															{
																value: "absolute",
																label: t(
																	"blocks.tape_condition.absolute_value",
																),
															},
															{
																value: "multiplier",
																label: t(
																	"blocks.tape_condition.multiplier_value",
																),
															},
														]}
														className="w-32"
													/>
													{comparisonType === "absolute" ? (
														<div className="w-32">
															<DynamicValueInput
																value={
																	typeof rightOperand === "number"
																		? rightOperand
																		: 0
																}
																onChange={(v: DynamicParam) =>
																	handleUpdateCompositeParams({ value: v })
																}
															/>
														</div>
													) : (
														<div className="flex items-center gap-1">
															<span>x</span>
															<Input
																type="number"
																value={
																	((rightOperand as Record<string, unknown>)
																		?.multiplier as number) || 2.0
																}
																onChange={(e) =>
																	handleUpdateCompositeParams({
																		value: {
																			...(rightOperand as object),
																			source: "value_multiplier",
																			multiplier:
																				parseFloat(e.target.value) || 0,
																		},
																	})
																}
																className="w-20 h-8"
															/>
															<span>
																{t("blocks.tape_condition.of_average")}
															</span>
														</div>
													)}
													<span>{t("blocks.tape_condition.for")}</span>
													<ParamSelect
														value={timeWindow}
														onChange={(v: string) =>
															handleUpdateCompositeParams({
																time_window_sec: parseInt(v, 10),
															})
														}
														items={[
															{ value: 5, label: "5s" },
															{ value: 10, label: "10s" },
															{ value: 30, label: "30s" },
														]}
														className="w-32"
													/>
												</div>
											);
										}
										case "order_book_zone_condition": {
											const side = provider?.params?.side || "bids";
											const rangeValue = provider?.params?.range_value || 1.0;
											const rangeType =
												provider?.params?.range_type || "Percentage";
											const obOperator = consumer?.params?.operator || "gt";
											const obValue = consumer?.params?.rightOperand || 1000000;

											return (
												<div className="flex items-center gap-2 flex-wrap">
													<span>
														{t("blocks.order_book_zone_condition.check")}
													</span>
													<ParamSelect
														value={side}
														onChange={(v: string) =>
															handleUpdateCompositeParams({ side: v })
														}
														items={[
															{
																value: "bids",
																label: t(
																	"blocks.order_book_zone_condition.sides.bids",
																),
															},
															{
																value: "asks",
																label: t(
																	"blocks.order_book_zone_condition.sides.asks",
																),
															},
														]}
														className="w-24"
													/>
													<span>
														{t("blocks.order_book_zone_condition.within")}
													</span>
													<div className="w-32">
														<DynamicValueInput
															value={rangeValue}
															onChange={(v: DynamicParam) =>
																handleUpdateCompositeParams({ range_value: v })
															}
														/>
													</div>
													<ParamSelect
														value={rangeType}
														onChange={(v: string) =>
															handleUpdateCompositeParams({ range_type: v })
														}
														items={[
															{ value: "Percentage", label: "%" },
															{ value: "ATR Multiplier", label: "x ATR" },
														]}
														className="w-28"
													/>
													<span>
														{t("blocks.order_book_zone_condition.is")}
													</span>
													<ParamSelect
														value={obOperator}
														onChange={(v: string) =>
															handleUpdateCompositeParams({ operator: v })
														}
														items={[
															{ value: "gt", label: ">" },
															{ value: "lt", label: "<" },
														]}
														className="w-16"
													/>
													<div className="w-32">
														<DynamicValueInput
															value={obValue}
															onChange={(v: DynamicParam) =>
																handleUpdateCompositeParams({ value: v })
															}
														/>
													</div>
												</div>
											);
										}
										case "level_proximity_condition": {
											const timeframe = provider?.params?.timeframe || "1h";
											const lookback = provider?.params?.lookback_period || 24;
											const levelType = provider?.params?.level_type || "all";
											const proxType =
												provider?.params?.proximity_type || "percentage";
											const proxValue =
												provider?.params?.proximity_value || 0.2;

											return (
												<div className="flex items-center gap-2 flex-wrap">
													<span>
														{t("blocks.level_proximity_condition.check")}
													</span>
													<ParamSelect
														value={timeframe}
														onChange={(v: string) =>
															handleUpdateCompositeParams({ timeframe: v })
														}
														items={[
															{ value: "1m", label: "1m" },
															{ value: "5m", label: "5m" },
															{ value: "15m", label: "15m" },
															{ value: "1h", label: "1h" },
														]}
														className="w-24"
													/>
													<span>
														{t("blocks.level_proximity_condition.lookback")}
													</span>
													<div className="w-24">
														<Input
															type="number"
															value={lookback}
															onChange={(e) =>
																handleUpdateCompositeParams({
																	lookback_period:
																		parseInt(e.target.value, 10) || 0,
																})
															}
															className="h-8"
														/>
													</div>
													<ParamSelect
														value={levelType}
														onChange={(v: string) =>
															handleUpdateCompositeParams({ level_type: v })
														}
														items={[
															{
																value: "high",
																label: t(
																	"blocks.local_level.level_types.high",
																	{ defaultValue: "High" },
																),
															},
															{
																value: "low",
																label: t("blocks.local_level.level_types.low", {
																	defaultValue: "Low",
																}),
															},
															{
																value: "all",
																label: t("blocks.local_level.level_types.all", {
																	defaultValue: "High/Low",
																}),
															},
														]}
														className="w-28"
													/>
													<span>
														{t("blocks.level_proximity_condition.within")}
													</span>
													<div className="w-32">
														<DynamicValueInput
															value={proxValue}
															onChange={(v: DynamicParam) =>
																handleUpdateCompositeParams({
																	proximity_value: v,
																})
															}
														/>
													</div>
													<ParamSelect
														value={proxType}
														onChange={(v: string) =>
															handleUpdateCompositeParams({ proximity_type: v })
														}
														items={[
															{ value: "atr_multiplier", label: "x ATR" },
															{ value: "percentage", label: "%" },
														]}
														className="w-28"
													/>
													<div className="flex items-center space-x-2 mt-2">
														<input
															type="checkbox"
															id={`${block.id}-is-provider`}
															checked={
																provider?.params?.is_data_provider || false
															}
															onChange={(e) =>
																handleUpdateCompositeParams({
																	is_data_provider: e.target.checked,
																})
															}
															className="form-checkbox"
															title={t(
																"blocks.level_proximity_condition.is_data_provider_label",
															)}
														/>
													</div>
												</div>
											);
										}
										default:
											return null;
									}
								})()}
							</div>
						)}
					</div>
				</Card>
			</div>
		);
	}

	// ─── Regular (non-composite) block ──────────────────────────────────────────
	const childCount = block.children?.length ?? 0;

	// Accent colors for different container types
	const containerAccent =
		block.type === "OR"
			? "border-amber-500/40 bg-amber-500/5"
			: block.type === "senior_tf_confluence"
				? "border-cyan-500/40 bg-cyan-500/5"
				: "border-primary/30 bg-primary/5";

	return (
		<div ref={setNodeRef}>
			<Card
				ref={dropRef}
				data-tutorial-id={
					block.type === "rsi_condition" ? "rsi-condition-block" : undefined
				}
				className={cn(
					"p-2 group/block transition-all",
					isContainer && containerAccent,
					isOver && "ring-2 ring-primary ring-offset-2 ring-offset-background",
				)}
			>
				{/* Block header */}
				<div className="flex items-center justify-between">
					<div className="flex items-center gap-2 flex-grow min-w-0">
						<div
							{...listeners}
							{...attributes}
							className="cursor-grab touch-none p-1 shrink-0"
						>
							<GripVertical className="w-5 h-5 text-muted-foreground" />
						</div>
						<div className="flex-grow min-w-0 overflow-hidden">
							{renderBlockContent(
								block,
								(p) => updateBlockParams(block.id, p),
								t,
							)}
						</div>
					</div>
					<div className="flex items-center shrink-0 ml-1">
						<InfoTooltip blockType={block.type} />
						{/* Expand/collapse button for containers */}
						{isContainer && (
							<Button
								variant="ghost"
								size="icon"
								className="h-7 w-7 text-muted-foreground hover:text-foreground"
								onClick={() => setIsExpanded(!isExpanded)}
								title={isExpanded ? "Collapse" : "Expand"}
							>
								{isExpanded ? (
									<ChevronDown className="w-4 h-4" />
								) : (
									<ChevronRight className="w-4 h-4" />
								)}
							</Button>
						)}
						<Button
							variant="ghost"
							size="icon"
							className="h-7 w-7 opacity-50 group-hover/block:opacity-100"
							onClick={handleRemove}
						>
							<X className="w-4 h-4" />
						</Button>
					</div>
				</div>

				{/* Child blocks zone — only for containers */}
				{isContainer && isExpanded && (
					<div className={cn("pl-6 pt-2", depth > 0 && "pl-4")}>
						<InnerDropZone
							blockId={block.id}
							stateKey={stateKey}
							isEmpty={childCount === 0}
							t={t}
						>
							{block.children?.map((child) => (
								<ConditionBlock
									key={child.id}
									block={child}
									stateKey={stateKey}
									depth={depth + 1}
								/>
							))}
						</InnerDropZone>

						{/* Quick logic addition */}
						{stateKey && (
							<div className="flex items-center gap-1.5 mt-1.5">
								<Button
									variant="ghost"
									size="sm"
									className="h-6 px-2 text-xs text-muted-foreground hover:text-primary"
									onClick={() => handleAddLogic("AND")}
								>
									<Plus className="w-3 h-3 mr-1" />
									<Combine className="w-3 h-3 mr-1" />
									AND
								</Button>
								<Button
									variant="ghost"
									size="sm"
									className="h-6 px-2 text-xs text-muted-foreground hover:text-amber-500"
									onClick={() => handleAddLogic("OR")}
								>
									<Plus className="w-3 h-3 mr-1" />
									<GitMerge className="w-3 h-3 mr-1" />
									OR
								</Button>
							</div>
						)}
					</div>
				)}

				{/* Child counter (collapsed state) */}
				{isContainer && !isExpanded && childCount > 0 && (
					<div className="pl-8 pt-1">
						<span className="text-xs text-muted-foreground">
							{childCount}{" "}
							{childCount === 1
								? "condition"
								: childCount < 5
									? "conditions"
									: "conditions"}
						</span>
					</div>
				)}
			</Card>
		</div>
	);
};
