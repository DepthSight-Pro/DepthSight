// frontend/src/components/simulation/SimulationDashboard.tsx
// Portfolio results dashboard with metrics, equity curve and trade timeline (styled like Analytics.tsx)

import { Activity, BarChart3, TrendingUp } from "lucide-react";
import type React from "react";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
	Area,
	AreaChart,
	CartesianGrid,
	ReferenceLine,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import { AdvancedStatCard } from "@/components/analytics/AdvancedStatCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useSimulationStore } from "./simulationStore";
import {
	calculateVariantStatsFromInspector,
	calculateVariantStatsFromSimulator,
	STRATEGY_VARIANTS,
	type Trade,
	VARIANT_COLORS,
} from "./types";

export const SimulationDashboard: React.FC = () => {
	const { t } = useTranslation("simulation");
	const {
		simulationResult,
		inspectorResult,
		config,
		isLoading,
		selectedDisplayVariant,
		setSelectedDisplayVariant,
		selectedVariants,
		compareSource,
		setCompareSource,
	} = useSimulationStore();

	// Define available data sources
	const hasInspectorData =
		!!inspectorResult?.matrix && Object.keys(inspectorResult.matrix).length > 0;
	const hasSimulationData =
		!!simulationResult?.trades && simulationResult.trades.length > 0;

	// Automatically select source if not set
	useEffect(() => {
		if (!compareSource) {
			if (hasSimulationData) setCompareSource("simulator");
			else if (hasInspectorData) setCompareSource("inspector");
		}
	}, [hasInspectorData, hasSimulationData, compareSource, setCompareSource]);

	// Get available variants for the selector
	const availableVariants =
		selectedVariants.length > 0 ? selectedVariants : ["raw"];

	// Auto-select first variant if none is selected
	const effectiveVariant = selectedDisplayVariant || availableVariants[0];

	// --- Unified Calculation Logic ---
	const displayData = useMemo(() => {
		const variantDef = STRATEGY_VARIANTS.find((v) => v.id === effectiveVariant);
		const variantName = variantDef?.name || effectiveVariant;
		const variantColor = VARIANT_COLORS[0];

		if (compareSource === "inspector" && inspectorResult?.matrix) {
			const stats = calculateVariantStatsFromInspector(
				inspectorResult.matrix,
				effectiveVariant,
				variantName,
				variantColor,
				config.initialCapital,
			);

			if (!stats) return null;

			const allTrades: Trade[] = [];
			Object.entries(inspectorResult.matrix).forEach(([asset, variants]) => {
				const cell = variants[effectiveVariant];
				if (cell?.trades && Array.isArray(cell.trades)) {
					cell.trades.forEach((t, idx) => {
						allTrades.push({
							...t,
							id: `${asset}_${effectiveVariant}_${idx}`,
							asset,
							strategy: effectiveVariant,
							pnlAmount: 0,
							status: "closed",
						});
					});
				}
			});

			const sortedTrades = allTrades.sort(
				(a, b) =>
					(a.exitTime || a.entryTime || 0) - (b.exitTime || b.entryTime || 0),
			);

			return {
				stats: {
					...stats,
					skippedTrades: 0,
					totalTrades: stats.tradesCount,
				},
				equityCurve: stats.equityCurve,
				trades: sortedTrades,
			};
		}

		if (compareSource === "simulator" && inspectorResult?.matrix) {
			// Use inspector trades as the source for simulation to ensure we simulate on all potential signals
			// This allows correct recalculation when changing config (e.g. capital, risk) on the fly.

			const allPotentialTrades: Trade[] = [];
			Object.entries(inspectorResult.matrix).forEach(([asset, variants]) => {
				const cell = variants[effectiveVariant];
				if (cell?.trades && Array.isArray(cell.trades)) {
					cell.trades.forEach((t, idx) => {
						allPotentialTrades.push({
							...t,
							id: `${asset}_${effectiveVariant}_${idx}`, // Generate ID
							asset,
							strategy: effectiveVariant,
							pnlAmount: 0,
							status: "closed",
						});
					});
				}
			});

			const stats = calculateVariantStatsFromSimulator(
				allPotentialTrades,
				effectiveVariant,
				variantName,
				variantColor,
				config, // Pass full config
			);

			if (!stats) return null;

			return {
				stats: {
					...stats,
					totalTrades: stats.tradesCount,
				},
				equityCurve: stats.equityCurve,
				trades: stats.trades || [],
			};
		}

		return null;
	}, [compareSource, inspectorResult, effectiveVariant, config]);

	// Counts for UI
	const inspectorTradesCount = useMemo(() => {
		if (!inspectorResult?.matrix) return 0;
		let count = 0;
		Object.values(inspectorResult.matrix).forEach((variants) => {
			const cell = variants[effectiveVariant];
			if (cell?.trades) count += cell.trades.length;
		});
		return count;
	}, [inspectorResult, effectiveVariant]);

	const simulatorTradesCount = useMemo(() => {
		// For simulator count, we want to show the number of executed trades in the current simulation config
		if (displayData && compareSource === "simulator") {
			return displayData.stats.tradesCount;
		}
		return 0;
	}, [displayData, compareSource]);

	// Early returns AFTER all hooks
	if (isLoading) {
		return (
			<div className="space-y-6 animate-in fade-in duration-500">
				<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
					{Array.from({ length: 4 }).map((_, i) => (
						<Skeleton key={i} className="h-[120px] rounded-2xl" />
					))}
				</div>
				<Skeleton className="h-[400px] rounded-xl" />
			</div>
		);
	}

	if (!displayData) {
		return (
			<div className="flex flex-col items-center justify-center h-full min-h-[400px] text-muted-foreground space-y-4">
				<div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center animate-bounce">
					<Activity size={32} className="text-primary" />
				</div>
				<div className="text-center">
					<h3 className="text-xl font-bold text-foreground">
						{t("noSimulation", "No Simulation Data")}
					</h3>
					<p className="max-w-xs mx-auto text-sm">
						{t(
							"runInspectorOrSimulation",
							"Run the inspector or portfolio simulation to see results.",
						)}
					</p>
				</div>
			</div>
		);
	}

	const { stats, equityCurve } = displayData;

	return (
		<div className="space-y-6 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700">
			{/* Controls Header */}
			<div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
				{/* Variant Selector - shows for both Inspector and Simulator */}
				<div className="flex items-center gap-4">
					<span className="text-sm text-muted-foreground">
						{t("displayVariant", "Display Variant")}:
					</span>
					<Select
						value={effectiveVariant}
						onValueChange={(v) => setSelectedDisplayVariant(v)}
					>
						<SelectTrigger className="w-[200px]">
							<SelectValue placeholder={t("selectVariant", "Select Variant")} />
						</SelectTrigger>
						<SelectContent>
							{availableVariants.map((v) => {
								const variant = STRATEGY_VARIANTS.find((sv) => sv.id === v);
								return (
									<SelectItem key={v} value={v}>
										{variant?.name || v}
									</SelectItem>
								);
							})}
						</SelectContent>
					</Select>
				</div>

				{/* Source Switcher */}
				<div className="flex items-center gap-2 bg-muted/50 p-1 rounded-lg">
					<Tabs
						value={compareSource || "inspector"}
						onValueChange={(v) =>
							setCompareSource(v as "inspector" | "simulator")
						}
						className="w-[300px]"
					>
						<TabsList className="grid w-full grid-cols-2">
							<TabsTrigger value="inspector" disabled={!hasInspectorData}>
								Inspector ({inspectorTradesCount})
							</TabsTrigger>
							<TabsTrigger value="simulator" disabled={!hasInspectorData}>
								Simulator ({simulatorTradesCount})
							</TabsTrigger>
						</TabsList>
					</Tabs>
				</div>
			</div>
			<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8 gap-4">
				<AdvancedStatCard
					label={t("netProfit", "Net Profit")}
					value={`${stats.totalPnl >= 0 ? "+" : ""}$${stats.totalPnl.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
					icon="DollarSign"
					colorClass={stats.totalPnl >= 0 ? "bg-emerald-500" : "bg-rose-500"}
					subValue={
						compareSource === "simulator"
							? `ROI: ${stats.portfolioROI >= 0 ? "+" : ""}${(stats.portfolioROI || 0).toFixed(2)}% (Initial Deposit: $${config.initialCapital})`
							: `ROI: ${stats.portfolioROI >= 0 ? "+" : ""}${(stats.portfolioROI || 0).toFixed(2)}% (${stats.assetsCount || 0} assets × $${config.initialCapital})`
					}
				/>
				<AdvancedStatCard
					label={t("winRate", "Win Rate")}
					value={`${stats.winRate.toFixed(1)}%`}
					icon="Target"
					colorClass={stats.winRate >= 50 ? "bg-emerald-500" : "bg-rose-500"}
				/>
				<AdvancedStatCard
					label={t("profitFactor", "Profit Factor")}
					value={
						stats.profitFactor === Infinity
							? "∞"
							: stats.profitFactor.toFixed(2)
					}
					icon="Zap"
					colorClass={
						stats.profitFactor >= 1 ? "bg-emerald-500" : "bg-rose-500"
					}
				/>
				<AdvancedStatCard
					label={t("sharpeRatio", "Sharpe Ratio")}
					value={stats.sharpeRatio.toFixed(2)}
					icon="Activity"
					colorClass={
						stats.sharpeRatio >= 1
							? "bg-emerald-500"
							: stats.sharpeRatio >= 0
								? "bg-amber-500"
								: "bg-rose-500"
					}
				/>
				<AdvancedStatCard
					label={t("maxDrawdown", "Max Drawdown")}
					value={`${stats.maxDrawdown.toFixed(2)}%`}
					icon="TrendingDown"
					colorClass="bg-rose-500"
					subValue={
						compareSource === "inspector"
							? t("avgDrawdown", "Avg Asset DD")
							: t("pfDrawdown", "Portfolio DD")
					}
				/>
				<AdvancedStatCard
					label={t("avgWin", "Avg Win")}
					value={`${stats.avgWin.toFixed(2)}%`}
					icon="TrendingUp"
					colorClass="bg-emerald-500"
				/>
				<AdvancedStatCard
					label={t("avgLoss", "Avg Loss")}
					value={`${stats.avgLoss.toFixed(2)}%`}
					icon="TrendingDown"
					colorClass="bg-rose-500"
				/>
				<AdvancedStatCard
					label={t("skippedTrades", "Skipped")}
					value={`${stats.skippedTrades}`}
					icon="BarChart"
					colorClass="bg-amber-500"
					subValue={t("dueToLimits", "Due to limits")}
				/>
			</div>

			{/* Equity & Underwater Chart */}
			<Card>
				<CardHeader>
					<CardTitle className="flex items-center gap-2">
						<TrendingUp className="text-primary" />
						{t("equityCurve", "Equity & Underwater Plot")}
					</CardTitle>
				</CardHeader>
				<CardContent className="min-h-[400px]">
					{!equityCurve || equityCurve.length === 0 ? (
						<div className="h-[400px] flex items-center justify-center text-muted-foreground">
							<p>{t("noEquityData", "No equity curve data available")}</p>
						</div>
					) : (
						<ResponsiveContainer width="100%" height={400}>
							<AreaChart
								data={equityCurve}
								margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
							>
								<defs>
									<linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
										<stop
											offset="5%"
											stopColor="hsl(var(--primary))"
											stopOpacity={0.4}
										/>
										<stop
											offset="95%"
											stopColor="hsl(var(--primary))"
											stopOpacity={0}
										/>
									</linearGradient>
									<linearGradient id="colorDD" x1="0" y1="0" x2="0" y2="1">
										<stop
											offset="5%"
											stopColor="hsl(var(--destructive))"
											stopOpacity={0}
										/>
										<stop
											offset="95%"
											stopColor="hsl(var(--destructive))"
											stopOpacity={0.3}
										/>
									</linearGradient>
								</defs>
								<CartesianGrid
									strokeDasharray="3 3"
									stroke="hsl(var(--border))"
									vertical={false}
								/>
								<XAxis
									dataKey="time"
									tickFormatter={(t) => new Date(t).toLocaleDateString()}
									stroke="hsl(var(--muted-foreground))"
									fontSize={10}
								/>
								<YAxis stroke="hsl(var(--muted-foreground))" fontSize={10} />
								<Tooltip
									contentStyle={{
										backgroundColor: "hsl(var(--card))",
										border: "1px solid hsl(var(--border))",
										borderRadius: "8px",
									}}
									labelFormatter={(t) => new Date(t).toLocaleString()}
								/>
								<ReferenceLine
									y={config.initialCapital}
									stroke="hsl(var(--muted-foreground))"
									strokeDasharray="3 3"
								/>
								<Area
									type="monotone"
									dataKey="value"
									stroke="hsl(var(--primary))"
									fillOpacity={1}
									fill="url(#colorEquity)"
									strokeWidth={2}
								/>
								<Area
									type="monotone"
									dataKey="drawdown"
									stroke="hsl(var(--destructive))"
									fillOpacity={1}
									fill="url(#colorDD)"
									strokeWidth={1}
								/>
							</AreaChart>
						</ResponsiveContainer>
					)}
				</CardContent>
			</Card>

			{/* Trade Timeline */}
			<TradeTimeline
				trades={displayData.trades || []}
				maxSlots={config.maxConcurrentPositions}
				onTradeClick={(trade) => {
					// Navigate to DeepDive for this asset with selected trade
					useSimulationStore.getState().setSelectedTradeForPreview(trade);
					useSimulationStore.getState().setActiveAsset(trade.asset);
				}}
			/>
		</div>
	);
};

// --- Trade Timeline Component ---
interface TradeTimelineProps {
	trades: Array<{
		id: string;
		entryTime: number;
		exitTime: number;
		pnlPct: number;
		asset: string;
		entryPrice?: number;
		exitPrice?: number;
		slotIndex?: number;
		variant?: string;
	}>;
	maxSlots: number;
	onTradeClick?: (trade: TradeTimelineProps["trades"][0]) => void;
}

const TradeTimeline: React.FC<TradeTimelineProps> = ({
	trades,
	maxSlots,
	onTradeClick,
}) => {
	const { t } = useTranslation("simulation");

	if (!trades || trades.length === 0) return null;

	const minTime = Math.min(...trades.map((t) => t.entryTime));
	const maxTime = Math.max(...trades.map((t) => t.exitTime));
	const timeRange = maxTime - minTime;

	// Group trades by slot
	const slots: Array<typeof trades> = Array.from(
		{ length: maxSlots },
		() => [],
	);
	trades.forEach((trade) => {
		const slotIdx = trade.slotIndex ?? 0;
		if (slotIdx < maxSlots) {
			slots[slotIdx].push(trade);
		}
	});

	return (
		<Card>
			<CardHeader>
				<CardTitle className="flex items-center gap-2">
					<BarChart3 className="text-primary" />
					{t("tradeTimeline", "Trade Timeline")} ({trades.length} trades)
				</CardTitle>
			</CardHeader>
			<CardContent>
				<div className="space-y-2">
					{slots.map((slotTrades, idx) => (
						<div key={idx} className="flex items-center gap-2">
							<span className="text-xs text-muted-foreground w-16">
								Slot {idx + 1}
							</span>
							<div className="flex-1 h-6 bg-muted rounded relative">
								{slotTrades.map((trade, tradeIdx) => {
									const left = ((trade.entryTime - minTime) / timeRange) * 100;
									const width = Math.max(
										((trade.exitTime - trade.entryTime) / timeRange) * 100,
										0.5,
									);
									return (
										<div
											key={trade.id || `${idx}_${tradeIdx}`}
											className={`absolute top-0.5 bottom-0.5 rounded transition-all hover:opacity-80 hover:scale-y-110 cursor-pointer ${
												trade.pnlPct > 0 ? "bg-emerald-500" : "bg-rose-500"
											}`}
											style={{ left: `${left}%`, width: `${width}%` }}
											title={`${trade.asset}: ${trade.pnlPct > 0 ? "+" : ""}${(trade.pnlPct * 100).toFixed(2)}%\nClick to view details`}
											onClick={() => onTradeClick?.(trade)}
										/>
									);
								})}
							</div>
						</div>
					))}
				</div>
				<div className="flex justify-between text-xs text-muted-foreground mt-2">
					<span>{new Date(minTime).toLocaleDateString()}</span>
					<span>{new Date(maxTime).toLocaleDateString()}</span>
				</div>
			</CardContent>
		</Card>
	);
};
