// src/components/genetic-command-center/GenePoolSettingsModal.tsx

import {
	Activity,
	BarChart2,
	Clock,
	Download,
	Filter,
	Layers,
	Target,
	TrendingUp,
	Upload,
	Zap,
} from "lucide-react";
import type React from "react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
	AVAILABLE_TIMEFRAMES,
	type ConditionsConfig,
	DEFAULT_GENE_POOL_CONFIG,
	type FiltersConfig,
	type GenePoolConfig,
	type RangeConfig,
} from "@/types/genetic-types";

interface GenePoolSettingsModalProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	config: GenePoolConfig;
	onChange: (config: GenePoolConfig) => void;
}

// Helper component for range inputs
const RangeInput: React.FC<{
	label: string;
	value: RangeConfig;
	onChange: (value: RangeConfig) => void;
	step?: number;
}> = ({ label, value, onChange, step = 1 }) => (
	<div className="space-y-1">
		<label className="text-[10px] text-muted-foreground uppercase font-bold">
			{label}
		</label>
		<div className="flex items-center gap-2">
			<input
				type="number"
				value={value[0]}
				onChange={(e) => onChange([parseFloat(e.target.value) || 0, value[1]])}
				step={step}
				className="w-16 bg-background border border-border rounded px-2 py-1 text-xs font-mono"
			/>
			<span className="text-muted-foreground">-</span>
			<input
				type="number"
				value={value[1]}
				onChange={(e) => onChange([value[0], parseFloat(e.target.value) || 0])}
				step={step}
				className="w-16 bg-background border border-border rounded px-2 py-1 text-xs font-mono"
			/>
		</div>
	</div>
);

// Helper component for timeframe selection
const TimeframeSelector: React.FC<{
	value: string[];
	onChange: (value: string[]) => void;
}> = ({ value, onChange }) => (
	<div className="flex flex-wrap gap-1">
		{AVAILABLE_TIMEFRAMES.map((tf) => (
			<button
				key={tf}
				onClick={() => {
					const newValue = value.includes(tf)
						? value.filter((t) => t !== tf)
						: [...value, tf];
					onChange(newValue);
				}}
				className={`px-2 py-0.5 text-[10px] rounded border transition-colors ${
					value.includes(tf)
						? "bg-primary/20 border-primary/50 text-primary"
						: "bg-muted border-border text-muted-foreground hover:border-primary/30"
				}`}
			>
				{tf}
			</button>
		))}
	</div>
);

// Filter item component
const FilterItem: React.FC<{
	name: string;
	icon: React.ReactNode;
	active: boolean;
	onToggle: () => void;
	children: React.ReactNode;
}> = ({ name, icon, active, onToggle, children }) => (
	<div
		className={`p-3 rounded-lg border transition-all ${active ? "border-primary/30 bg-primary/5" : "border-border bg-muted/20"}`}
	>
		<div className="flex items-center justify-between mb-2">
			<div className="flex items-center gap-2">
				{icon}
				<span
					className={`text-sm font-medium ${active ? "text-foreground" : "text-muted-foreground"}`}
				>
					{name}
				</span>
			</div>
			<Switch checked={active} onCheckedChange={onToggle} />
		</div>
		{active && (
			<div className="pt-2 border-t border-border/50 space-y-3">{children}</div>
		)}
	</div>
);

const GenePoolSettingsModal: React.FC<GenePoolSettingsModalProps> = ({
	open,
	onOpenChange,
	config,
	onChange,
}) => {
	const { t } = useTranslation("discovery");
	const [localConfig, setLocalConfig] = useState<GenePoolConfig>(config);
	const fileInputRef = useRef<HTMLInputElement>(null);

	const updateFilters = (
		key: keyof FiltersConfig,
		value: Partial<FiltersConfig[typeof key]>,
	) => {
		setLocalConfig((prev) => ({
			...prev,
			filters: { ...prev.filters, [key]: { ...prev.filters[key], ...value } },
		}));
	};

	const updateConditions = (
		key: keyof ConditionsConfig,
		value: Partial<ConditionsConfig[typeof key]>,
	) => {
		setLocalConfig((prev) => ({
			...prev,
			conditions: {
				...prev.conditions,
				[key]: { ...prev.conditions[key], ...value },
			},
		}));
	};

	const handleApply = () => {
		onChange(localConfig);
		onOpenChange(false);
	};

	// Export config as JSON file
	const handleExport = () => {
		const dataStr = JSON.stringify(localConfig, null, 2);
		const dataBlob = new Blob([dataStr], { type: "application/json" });
		const url = URL.createObjectURL(dataBlob);
		const link = document.createElement("a");
		link.href = url;
		link.download = `gene_pool_config_${new Date().toISOString().split("T")[0]}.json`;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		URL.revokeObjectURL(url);
	};

	// Import config from JSON file
	const handleImport = (event: React.ChangeEvent<HTMLInputElement>) => {
		const file = event.target.files?.[0];
		if (!file) return;

		const reader = new FileReader();
		reader.onload = (e) => {
			try {
				const imported = JSON.parse(
					e.target?.result as string,
				) as GenePoolConfig;
				// Validate structure
				if (imported.filters && imported.conditions) {
					setLocalConfig(imported);
				} else {
					alert("Invalid config file structure");
				}
			} catch {
				alert("Failed to parse JSON file");
			}
		};
		reader.readAsText(file);
		// Reset input
		if (fileInputRef.current) fileInputRef.current.value = "";
	};

	// Reset to defaults
	const handleReset = () => {
		setLocalConfig(DEFAULT_GENE_POOL_CONFIG);
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-w-4xl max-h-[85vh] overflow-hidden flex flex-col">
				<DialogHeader>
					<div className="flex items-center justify-between">
						<DialogTitle className="flex items-center gap-2">
							<Layers className="w-5 h-5 text-primary" />
							{t("gcc.modal.title", "Advanced Gene Pool Settings")}
						</DialogTitle>
						<div className="flex items-center gap-2">
							<input
								type="file"
								ref={fileInputRef}
								onChange={handleImport}
								accept=".json"
								className="hidden"
							/>
							<Button
								variant="outline"
								size="sm"
								onClick={() => fileInputRef.current?.click()}
							>
								<Upload className="w-4 h-4 mr-1" />{" "}
								{t("gcc.modal.import", "Import")}
							</Button>
							<Button variant="outline" size="sm" onClick={handleExport}>
								<Download className="w-4 h-4 mr-1" />{" "}
								{t("gcc.modal.export", "Export")}
							</Button>
						</div>
					</div>
				</DialogHeader>

				<Tabs
					defaultValue="filters"
					className="flex-1 overflow-hidden flex flex-col"
				>
					<TabsList className="grid w-full grid-cols-2">
						<TabsTrigger value="filters" className="flex items-center gap-2">
							<Filter className="w-4 h-4" /> {t("gcc.modal.filters", "Filters")}
						</TabsTrigger>
						<TabsTrigger value="conditions" className="flex items-center gap-2">
							<Zap className="w-4 h-4" />{" "}
							{t("gcc.modal.conditions", "Conditions")}
						</TabsTrigger>
					</TabsList>

					<div className="flex-1 overflow-y-auto mt-4 pr-2">
						{/* FILTERS TAB */}
						<TabsContent value="filters" className="mt-0 space-y-3">
							<p className="text-xs text-muted-foreground mb-4">
								{t(
									"gcc.modal.filtersDesc",
									"Configure market filters that must pass before entering trades.",
								)}
							</p>

							<FilterItem
								name={t("gcc.modal.trendFilter", "Trend Filter")}
								icon={<TrendingUp className="w-4 h-4 text-blue-500" />}
								active={localConfig.filters.trend_filter.active}
								onToggle={() =>
									updateFilters("trend_filter", {
										active: !localConfig.filters.trend_filter.active,
									})
								}
							>
								<RangeInput
									label={t("gcc.modal.threshold", "Threshold")}
									value={localConfig.filters.trend_filter.threshold}
									onChange={(v) =>
										updateFilters("trend_filter", { threshold: v })
									}
								/>
								<div className="space-y-1">
									<label className="text-[10px] text-muted-foreground uppercase font-bold">
										{t("gcc.modal.timeframes", "Timeframes")}
									</label>
									<TimeframeSelector
										value={localConfig.filters.trend_filter.timeframes}
										onChange={(v) =>
											updateFilters("trend_filter", { timeframes: v })
										}
									/>
								</div>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.adxFilter", "ADX Filter")}
								icon={<Activity className="w-4 h-4 text-emerald-500" />}
								active={localConfig.filters.adx_filter.active}
								onToggle={() =>
									updateFilters("adx_filter", {
										active: !localConfig.filters.adx_filter.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.period", "Period")}
										value={localConfig.filters.adx_filter.period}
										onChange={(v) => updateFilters("adx_filter", { period: v })}
									/>
									<RangeInput
										label={t("gcc.modal.threshold", "Threshold")}
										value={localConfig.filters.adx_filter.threshold}
										onChange={(v) =>
											updateFilters("adx_filter", { threshold: v })
										}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.filters.adx_filter.timeframes}
									onChange={(v) =>
										updateFilters("adx_filter", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t(
									"gcc.modal.volatilityFilter",
									"Volatility Filter (ATR)",
								)}
								icon={<BarChart2 className="w-4 h-4 text-orange-500" />}
								active={localConfig.filters.volatility_filter.active}
								onToggle={() =>
									updateFilters("volatility_filter", {
										active: !localConfig.filters.volatility_filter.active,
									})
								}
							>
								<RangeInput
									label={t("gcc.modal.valueRange", "Value Range")}
									value={localConfig.filters.volatility_filter.value}
									onChange={(v) =>
										updateFilters("volatility_filter", { value: v })
									}
									step={0.001}
								/>
								<TimeframeSelector
									value={localConfig.filters.volatility_filter.timeframes}
									onChange={(v) =>
										updateFilters("volatility_filter", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.natrFilter", "NATR Filter")}
								icon={<BarChart2 className="w-4 h-4 text-purple-500" />}
								active={localConfig.filters.natr_filter.active}
								onToggle={() =>
									updateFilters("natr_filter", {
										active: !localConfig.filters.natr_filter.active,
									})
								}
							>
								<RangeInput
									label={t("gcc.modal.valueRange", "Value Range")}
									value={localConfig.filters.natr_filter.value}
									onChange={(v) => updateFilters("natr_filter", { value: v })}
									step={0.1}
								/>
								<TimeframeSelector
									value={localConfig.filters.natr_filter.timeframes}
									onChange={(v) =>
										updateFilters("natr_filter", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.timeFilter", "Time Filter")}
								icon={<Clock className="w-4 h-4 text-cyan-500" />}
								active={localConfig.filters.time_filter.active}
								onToggle={() =>
									updateFilters("time_filter", {
										active: !localConfig.filters.time_filter.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.startHourUTC", "Start Hour (UTC)")}
										value={localConfig.filters.time_filter.startHourUTC}
										onChange={(v) =>
											updateFilters("time_filter", { startHourUTC: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.endHourUTC", "End Hour (UTC)")}
										value={localConfig.filters.time_filter.endHourUTC}
										onChange={(v) =>
											updateFilters("time_filter", { endHourUTC: v })
										}
									/>
								</div>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.relVolFilter", "Relative Volume")}
								icon={<BarChart2 className="w-4 h-4 text-emerald-400" />}
								active={localConfig.filters.rel_vol_filter.active}
								onToggle={() =>
									updateFilters("rel_vol_filter", {
										active: !localConfig.filters.rel_vol_filter.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.relVolThreshold", "Vol Multiplier")}
										value={localConfig.filters.rel_vol_filter.rel_vol_threshold}
										onChange={(v) =>
											updateFilters("rel_vol_filter", { rel_vol_threshold: v })
										}
										step={0.1}
									/>
									<RangeInput
										label={t("gcc.modal.lookbackPeriod", "MA Period")}
										value={localConfig.filters.rel_vol_filter.lookback_period}
										onChange={(v) =>
											updateFilters("rel_vol_filter", { lookback_period: v })
										}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.filters.rel_vol_filter.timeframes}
									onChange={(v) =>
										updateFilters("rel_vol_filter", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.marketActivity", "Market Activity")}
								icon={<Activity className="w-4 h-4 text-cyan-400" />}
								active={localConfig.filters.market_activity.active}
								onToggle={() =>
									updateFilters("market_activity", {
										active: !localConfig.filters.market_activity.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.natrThreshold", "NATR Threshold %")}
										value={localConfig.filters.market_activity.natr_threshold}
										onChange={(v) =>
											updateFilters("market_activity", { natr_threshold: v })
										}
										step={0.1}
									/>
									<RangeInput
										label={t("gcc.modal.relVolThreshold", "Rel Vol Threshold")}
										value={
											localConfig.filters.market_activity.rel_vol_threshold
										}
										onChange={(v) =>
											updateFilters("market_activity", { rel_vol_threshold: v })
										}
										step={0.1}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.filters.market_activity.timeframes}
									onChange={(v) =>
										updateFilters("market_activity", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.tradingSession", "Trading Session")}
								icon={<Clock className="w-4 h-4 text-rose-400" />}
								active={localConfig.filters.trading_session.active}
								onToggle={() =>
									updateFilters("trading_session", {
										active: !localConfig.filters.trading_session.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.startHour", "Start Hour (UTC)")}
										value={localConfig.filters.trading_session.start_hour_utc}
										onChange={(v) =>
											updateFilters("trading_session", { start_hour_utc: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.endHour", "End Hour (UTC)")}
										value={localConfig.filters.trading_session.end_hour_utc}
										onChange={(v) =>
											updateFilters("trading_session", { end_hour_utc: v })
										}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.filters.trading_session.timeframes}
									onChange={(v) =>
										updateFilters("trading_session", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.btcStateFilter", "BTC State Filter")}
								icon={<TrendingUp className="w-4 h-4 text-amber-500" />}
								active={localConfig.filters.btc_state_filter.active}
								onToggle={() =>
									updateFilters("btc_state_filter", {
										active: !localConfig.filters.btc_state_filter.active,
									})
								}
							>
								<RangeInput
									label={t(
										"gcc.modal.consolidationThreshold",
										"Consolidation Range %",
									)}
									value={
										localConfig.filters.btc_state_filter.consolidation_threshold
									}
									onChange={(v) =>
										updateFilters("btc_state_filter", {
											consolidation_threshold: v,
										})
									}
									step={0.1}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.correlationFilter", "BTC Correlation")}
								icon={<BarChart2 className="w-4 h-4 text-blue-500" />}
								active={localConfig.filters.correlation.active}
								onToggle={() =>
									updateFilters("correlation", {
										active: !localConfig.filters.correlation.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.correlationPeriod", "Period")}
										value={localConfig.filters.correlation.lookback}
										onChange={(v) =>
											updateFilters("correlation", { lookback: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.correlationValue", "Value Range")}
										value={localConfig.filters.correlation.value}
										onChange={(v) => updateFilters("correlation", { value: v })}
										step={0.1}
									/>
								</div>
							</FilterItem>
						</TabsContent>

						{/* CONDITIONS TAB */}
						<TabsContent value="conditions" className="mt-0 space-y-3">
							<p className="text-xs text-muted-foreground mb-4">
								{t(
									"gcc.modal.conditionsDesc",
									"Configure building blocks for entry/exit logic.",
								)}
							</p>

							<FilterItem
								name={t("gcc.modal.rsiCondition", "RSI Condition")}
								icon={<Activity className="w-4 h-4 text-rose-500" />}
								active={localConfig.conditions.rsi_condition.active}
								onToggle={() =>
									updateConditions("rsi_condition", {
										active: !localConfig.conditions.rsi_condition.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.period", "Period")}
										value={localConfig.conditions.rsi_condition.period}
										onChange={(v) =>
											updateConditions("rsi_condition", { period: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.value", "Value")}
										value={localConfig.conditions.rsi_condition.value}
										onChange={(v) =>
											updateConditions("rsi_condition", { value: v })
										}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.conditions.rsi_condition.timeframes}
									onChange={(v) =>
										updateConditions("rsi_condition", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.maCrossCondition", "MA Cross Condition")}
								icon={<TrendingUp className="w-4 h-4 text-blue-500" />}
								active={localConfig.conditions.ma_cross_condition.active}
								onToggle={() =>
									updateConditions("ma_cross_condition", {
										active: !localConfig.conditions.ma_cross_condition.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.fastPeriod", "Fast Period")}
										value={localConfig.conditions.ma_cross_condition.fastPeriod}
										onChange={(v) =>
											updateConditions("ma_cross_condition", { fastPeriod: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.slowPeriod", "Slow Period")}
										value={localConfig.conditions.ma_cross_condition.slowPeriod}
										onChange={(v) =>
											updateConditions("ma_cross_condition", { slowPeriod: v })
										}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.conditions.ma_cross_condition.timeframes}
									onChange={(v) =>
										updateConditions("ma_cross_condition", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.macdCondition", "MACD Condition")}
								icon={<BarChart2 className="w-4 h-4 text-emerald-500" />}
								active={localConfig.conditions.macd_condition.active}
								onToggle={() =>
									updateConditions("macd_condition", {
										active: !localConfig.conditions.macd_condition.active,
									})
								}
							>
								<div className="grid grid-cols-3 gap-2">
									<RangeInput
										label={t("gcc.modal.fast", "Fast")}
										value={localConfig.conditions.macd_condition.fastPeriod}
										onChange={(v) =>
											updateConditions("macd_condition", { fastPeriod: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.slow", "Slow")}
										value={localConfig.conditions.macd_condition.slowPeriod}
										onChange={(v) =>
											updateConditions("macd_condition", { slowPeriod: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.signal", "Signal")}
										value={localConfig.conditions.macd_condition.signalPeriod}
										onChange={(v) =>
											updateConditions("macd_condition", { signalPeriod: v })
										}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.conditions.macd_condition.timeframes}
									onChange={(v) =>
										updateConditions("macd_condition", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.bbCondition", "Bollinger Bands")}
								icon={<Layers className="w-4 h-4 text-purple-500" />}
								active={localConfig.conditions.bb_condition.active}
								onToggle={() =>
									updateConditions("bb_condition", {
										active: !localConfig.conditions.bb_condition.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.period", "Period")}
										value={localConfig.conditions.bb_condition.period}
										onChange={(v) =>
											updateConditions("bb_condition", { period: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.stdDev", "Std Dev")}
										value={localConfig.conditions.bb_condition.stdDev}
										onChange={(v) =>
											updateConditions("bb_condition", { stdDev: v })
										}
										step={0.1}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.conditions.bb_condition.timeframes}
									onChange={(v) =>
										updateConditions("bb_condition", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.stochCondition", "Stochastic")}
								icon={<Activity className="w-4 h-4 text-cyan-500" />}
								active={localConfig.conditions.stoch_condition.active}
								onToggle={() =>
									updateConditions("stoch_condition", {
										active: !localConfig.conditions.stoch_condition.active,
									})
								}
							>
								<div className="grid grid-cols-3 gap-2">
									<RangeInput
										label={t("gcc.modal.kPeriod", "K")}
										value={localConfig.conditions.stoch_condition.kPeriod}
										onChange={(v) =>
											updateConditions("stoch_condition", { kPeriod: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.dPeriod", "D")}
										value={localConfig.conditions.stoch_condition.dPeriod}
										onChange={(v) =>
											updateConditions("stoch_condition", { dPeriod: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.smoothK", "Smooth")}
										value={localConfig.conditions.stoch_condition.smoothK}
										onChange={(v) =>
											updateConditions("stoch_condition", { smoothK: v })
										}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.conditions.stoch_condition.timeframes}
									onChange={(v) =>
										updateConditions("stoch_condition", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.valueComparison", "Value Comparison")}
								icon={<Zap className="w-4 h-4 text-yellow-500" />}
								active={localConfig.conditions.value_comparison.active}
								onToggle={() =>
									updateConditions("value_comparison", {
										active: !localConfig.conditions.value_comparison.active,
									})
								}
							>
								<TimeframeSelector
									value={localConfig.conditions.value_comparison.timeframes}
									onChange={(v) =>
										updateConditions("value_comparison", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.classicPattern", "Classic Patterns")}
								icon={<Layers className="w-4 h-4 text-amber-500" />}
								active={localConfig.conditions.classic_pattern.active}
								onToggle={() =>
									updateConditions("classic_pattern", {
										active: !localConfig.conditions.classic_pattern.active,
									})
								}
							>
								<TimeframeSelector
									value={localConfig.conditions.classic_pattern.timeframes}
									onChange={(v) =>
										updateConditions("classic_pattern", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.localLevel", "Local Level")}
								icon={<Target className="w-4 h-4 text-teal-500" />}
								active={localConfig.conditions.local_level.active}
								onToggle={() =>
									updateConditions("local_level", {
										active: !localConfig.conditions.local_level.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.lookback", "Lookback")}
										value={localConfig.conditions.local_level.lookbackPeriod}
										onChange={(v) =>
											updateConditions("local_level", { lookbackPeriod: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.proximity", "Proximity")}
										value={localConfig.conditions.local_level.proximityValue}
										onChange={(v) =>
											updateConditions("local_level", { proximityValue: v })
										}
										step={0.1}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.conditions.local_level.timeframes}
									onChange={(v) =>
										updateConditions("local_level", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.priceConsolidation", "Price Consolidation")}
								icon={<Layers className="w-4 h-4 text-indigo-500" />}
								active={localConfig.conditions.price_consolidation.active}
								onToggle={() =>
									updateConditions("price_consolidation", {
										active: !localConfig.conditions.price_consolidation.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.lookback", "Lookback")}
										value={
											localConfig.conditions.price_consolidation.lookbackPeriod
										}
										onChange={(v) =>
											updateConditions("price_consolidation", {
												lookbackPeriod: v,
											})
										}
									/>
									<RangeInput
										label={t("gcc.modal.maxRangeATR", "Max Range ATR")}
										value={
											localConfig.conditions.price_consolidation.maxRangeATR
										}
										onChange={(v) =>
											updateConditions("price_consolidation", {
												maxRangeATR: v,
											})
										}
										step={0.1}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.conditions.price_consolidation.timeframes}
									onChange={(v) =>
										updateConditions("price_consolidation", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.volumeConfirmation", "Volume Confirmation")}
								icon={<BarChart2 className="w-4 h-4 text-rose-500" />}
								active={localConfig.conditions.volume_confirmation.active}
								onToggle={() =>
									updateConditions("volume_confirmation", {
										active: !localConfig.conditions.volume_confirmation.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.lookback", "Lookback")}
										value={
											localConfig.conditions.volume_confirmation.lookbackPeriod
										}
										onChange={(v) =>
											updateConditions("volume_confirmation", {
												lookbackPeriod: v,
											})
										}
									/>
									<RangeInput
										label={t("gcc.modal.multiplier", "Multiplier")}
										value={
											localConfig.conditions.volume_confirmation.multiplier
										}
										onChange={(v) =>
											updateConditions("volume_confirmation", { multiplier: v })
										}
										step={0.1}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.conditions.volume_confirmation.timeframes}
									onChange={(v) =>
										updateConditions("volume_confirmation", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.trendDirection", "Trend Direction")}
								icon={<TrendingUp className="w-4 h-4 text-emerald-500" />}
								active={localConfig.conditions.trend_direction.active}
								onToggle={() =>
									updateConditions("trend_direction", {
										active: !localConfig.conditions.trend_direction.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.smaFast", "SMA Fast")}
										value={localConfig.conditions.trend_direction.smaFastPeriod}
										onChange={(v) =>
											updateConditions("trend_direction", { smaFastPeriod: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.smaSlow", "SMA Slow")}
										value={localConfig.conditions.trend_direction.smaSlowPeriod}
										onChange={(v) =>
											updateConditions("trend_direction", { smaSlowPeriod: v })
										}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.conditions.trend_direction.timeframes}
									onChange={(v) =>
										updateConditions("trend_direction", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.openInterest", "Open Interest")}
								icon={<Activity className="w-4 h-4 text-purple-400" />}
								active={localConfig.conditions.open_interest.active}
								onToggle={() =>
									updateConditions("open_interest", {
										active: !localConfig.conditions.open_interest.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.oiLookback", "OI Lookback Period")}
										value={localConfig.conditions.open_interest.lookback}
										onChange={(v) =>
											updateConditions("open_interest", { lookback: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.oiValue", "OI Change % Range")}
										value={localConfig.conditions.open_interest.value}
										onChange={(v) =>
											updateConditions("open_interest", { value: v })
										}
										step={0.1}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.conditions.open_interest.timeframes}
									onChange={(v) =>
										updateConditions("open_interest", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.tapeCondition", "Tape Condition")}
								icon={<Zap className="w-4 h-4 text-orange-400" />}
								active={localConfig.conditions.tape_condition.active}
								onToggle={() =>
									updateConditions("tape_condition", {
										active: !localConfig.conditions.tape_condition.active,
									})
								}
							>
								<RangeInput
									label={t(
										"gcc.modal.tapeThreshold",
										"Tape Threshold Multiplier",
									)}
									value={localConfig.conditions.tape_condition.threshold}
									onChange={(v) =>
										updateConditions("tape_condition", { threshold: v })
									}
									step={0.1}
								/>
								<TimeframeSelector
									value={localConfig.conditions.tape_condition.timeframes}
									onChange={(v) =>
										updateConditions("tape_condition", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.volatilitySqueeze", "Volatility Squeeze")}
								icon={<Activity className="w-4 h-4 text-pink-400" />}
								active={localConfig.conditions.volatility_squeeze.active}
								onToggle={() =>
									updateConditions("volatility_squeeze", {
										active: !localConfig.conditions.volatility_squeeze.active,
									})
								}
							>
								<div className="grid grid-cols-2 gap-3">
									<RangeInput
										label={t("gcc.modal.squeezeLookback", "Lookback Candles")}
										value={
											localConfig.conditions.volatility_squeeze.lookback_candles
										}
										onChange={(v) =>
											updateConditions("volatility_squeeze", {
												lookback_candles: v,
											})
										}
									/>
									<RangeInput
										label={t("gcc.modal.squeezeRatio", "Squeeze Ratio Range")}
										value={
											localConfig.conditions.volatility_squeeze.squeeze_ratio
										}
										onChange={(v) =>
											updateConditions("volatility_squeeze", {
												squeeze_ratio: v,
											})
										}
										step={0.1}
									/>
								</div>
								<TimeframeSelector
									value={localConfig.conditions.volatility_squeeze.timeframes}
									onChange={(v) =>
										updateConditions("volatility_squeeze", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.roundLevel", "Round Level")}
								icon={<Target className="w-4 h-4 text-teal-400" />}
								active={localConfig.conditions.round_level.active}
								onToggle={() =>
									updateConditions("round_level", {
										active: !localConfig.conditions.round_level.active,
									})
								}
							>
								<RangeInput
									label={t(
										"gcc.modal.roundProximity",
										"Proximity Zone (Pips / %)",
									)}
									value={localConfig.conditions.round_level.proximity_value}
									onChange={(v) =>
										updateConditions("round_level", { proximity_value: v })
									}
									step={0.5}
								/>
								<TimeframeSelector
									value={localConfig.conditions.round_level.timeframes}
									onChange={(v) =>
										updateConditions("round_level", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.significantLevel", "Significant Level")}
								icon={<Layers className="w-4 h-4 text-indigo-400" />}
								active={localConfig.conditions.significant_level.active}
								onToggle={() =>
									updateConditions("significant_level", {
										active: !localConfig.conditions.significant_level.active,
									})
								}
							>
								<RangeInput
									label={t("gcc.modal.levelProximity", "Proximity Zone Range")}
									value={
										localConfig.conditions.significant_level.proximity_value
									}
									onChange={(v) =>
										updateConditions("significant_level", {
											proximity_value: v,
										})
									}
									step={0.1}
								/>
								<TimeframeSelector
									value={localConfig.conditions.significant_level.timeframes}
									onChange={(v) =>
										updateConditions("significant_level", { timeframes: v })
									}
								/>
							</FilterItem>

							<FilterItem
								name={t("gcc.modal.priceAction", "Price Action Structure")}
								icon={<TrendingUp className="w-4 h-4 text-emerald-400" />}
								active={localConfig.conditions.price_action_analyzer.active}
								onToggle={() =>
									updateConditions("price_action_analyzer", {
										active:
											!localConfig.conditions.price_action_analyzer.active,
									})
								}
							>
								<div className="grid grid-cols-3 gap-2">
									<RangeInput
										label={t("gcc.modal.paLookback", "Lookback Period")}
										value={
											localConfig.conditions.price_action_analyzer
												.lookback_candles
										}
										onChange={(v) =>
											updateConditions("price_action_analyzer", {
												lookback_candles: v,
											})
										}
									/>
									<RangeInput
										label={t("gcc.modal.paOrder", "Fractal Order")}
										value={localConfig.conditions.price_action_analyzer.order}
										onChange={(v) =>
											updateConditions("price_action_analyzer", { order: v })
										}
									/>
									<RangeInput
										label={t("gcc.modal.paConfirmPoints", "Min Points")}
										value={
											localConfig.conditions.price_action_analyzer.min_points
										}
										onChange={(v) =>
											updateConditions("price_action_analyzer", {
												min_points: v,
											})
										}
									/>
								</div>
								<TimeframeSelector
									value={
										localConfig.conditions.price_action_analyzer.timeframes
									}
									onChange={(v) =>
										updateConditions("price_action_analyzer", { timeframes: v })
									}
								/>
							</FilterItem>
						</TabsContent>
					</div>
				</Tabs>

				<div className="flex justify-between gap-3 pt-4 border-t border-border mt-4">
					<Button variant="ghost" onClick={handleReset}>
						{t("common:reset", "Reset to Defaults")}
					</Button>
					<div className="flex gap-3">
						<Button variant="outline" onClick={() => onOpenChange(false)}>
							{t("common:cancel", "Cancel")}
						</Button>
						<Button onClick={handleApply}>{t("common:apply", "Apply")}</Button>
					</div>
				</div>
			</DialogContent>
		</Dialog>
	);
};

export default GenePoolSettingsModal;
