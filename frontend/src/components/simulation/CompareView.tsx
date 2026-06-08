// frontend/src/components/simulation/CompareView.tsx
// Comparison view for multiple strategy variants using cached results (Inspector or Simulator)

import { Activity, Divide, Scale, TrendingUp } from "lucide-react";
import type React from "react";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
	CartesianGrid,
	Legend,
	Line,
	LineChart,
	PolarAngleAxis,
	PolarGrid,
	PolarRadiusAxis,
	Radar,
	RadarChart,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useSimulationStore } from "./simulationStore";
import {
	calculateVariantStatsFromInspector,
	calculateVariantStatsFromSimulator,
	STRATEGY_VARIANTS,
	type Trade,
	type VariantStats,
} from "./types";

// Color palette for multiple variants
const VARIANT_COLORS = [
	"#06B6D4", // Cyan
	"#8B5CF6", // Violet
	"#10B981", // Emerald
	"#F59E0B", // Amber
	"#EF4444", // Red
	"#EC4899", // Pink
	"#6366F1", // Indigo
	"#84CC16", // Lime
	"#14B8A6", // Teal
];

export const CompareView: React.FC = () => {
	const { t } = useTranslation("simulation");
	const {
		inspectorResult,
		simulationResult,
		selectedVariants,
		config,
		compareSource,
		setCompareSource,
	} = useSimulationStore();

	// Determine available sources
	const hasInspectorData =
		!!inspectorResult?.matrix && Object.keys(inspectorResult.matrix).length > 0;
	const hasSimulationData =
		!!simulationResult?.trades && simulationResult.trades.length > 0;

	// Auto-select source if not set
	useEffect(() => {
		if (!compareSource) {
			if (hasInspectorData) setCompareSource("inspector");
			else if (hasSimulationData) setCompareSource("simulator");
		}
	}, [hasInspectorData, hasSimulationData, compareSource, setCompareSource]);

	// --- Use Shared Calculation Logic ---

	const inspectorStats = useMemo<VariantStats[]>(() => {
		if (!inspectorResult?.matrix || !config) return [];

		return selectedVariants
			.map((variantId, idx) => {
				const variantDef = STRATEGY_VARIANTS.find((v) => v.id === variantId);
				const name = variantDef?.name || variantId;
				const color = VARIANT_COLORS[idx % VARIANT_COLORS.length];

				return calculateVariantStatsFromInspector(
					inspectorResult.matrix,
					variantId,
					name,
					color,
					config.initialCapital,
				);
			})
			.filter((s): s is VariantStats => s !== null && s.tradesCount > 0);
	}, [inspectorResult, selectedVariants, config]);

	const simulatorStats = useMemo<VariantStats[]>(() => {
		if (!config) return [];

		// Priority: Use inspector result to get "raw" trades for each variant and simulate fresh
		if (inspectorResult?.matrix) {
			return selectedVariants
				.map((variantId, idx) => {
					const variantDef = STRATEGY_VARIANTS.find((v) => v.id === variantId);
					const name = variantDef?.name || variantId;
					const color = VARIANT_COLORS[idx % VARIANT_COLORS.length];

					// Extract trades for this variant from inspector matrix
					const variantTrades: Trade[] = [];
					Object.entries(inspectorResult.matrix).forEach(
						([asset, variants]) => {
							const cell = variants[variantId];
							if (cell?.trades && Array.isArray(cell.trades)) {
								cell.trades.forEach((t, tradeIdx) => {
									variantTrades.push({
										...t,
										id: `${asset}_${variantId}_${tradeIdx}`,
										asset,
										strategy: variantId,
										pnlAmount: 0,
										status: "closed",
									});
								});
							}
						},
					);

					// Skip if no trades found for this variant
					if (variantTrades.length === 0) return null;

					return calculateVariantStatsFromSimulator(
						variantTrades,
						variantId,
						name,
						color,
						config,
					);
				})
				.filter((s): s is VariantStats => s !== null && s.tradesCount > 0);
		}

		// Fallback: Use existing simulation result trades (if any)
		if (simulationResult?.trades) {
			const variantsToProcess =
				selectedVariants.length > 0
					? selectedVariants
					: [
							...new Set(
								simulationResult.trades.map((t) => t.strategy || "unknown"),
							),
						];

			return variantsToProcess
				.map((variantId, idx) => {
					const variantDef = STRATEGY_VARIANTS.find((v) => v.id === variantId);
					const name = variantDef?.name || variantId;
					const color = VARIANT_COLORS[idx % VARIANT_COLORS.length];

					return calculateVariantStatsFromSimulator(
						simulationResult.trades,
						variantId,
						name,
						color,
						config,
					);
				})
				.filter((s): s is VariantStats => s !== null && s.tradesCount > 0);
		}

		return [];
	}, [simulationResult, inspectorResult, selectedVariants, config]);

	// Active stats based on source
	const activeStats =
		compareSource === "simulator" ? simulatorStats : inspectorStats;

	// --- Charts Data Prep ---

	// Radar Data
	const radarData = useMemo(() => {
		if (activeStats.length === 0) return [];

		// Normalize logic
		// We want to map attributes to 0-100 scale for radar
		const maxPnl = Math.max(
			...activeStats.map((s) => Math.abs(s.totalPnlPct)),
			1,
		);
		const maxSharpe = Math.max(...activeStats.map((s) => s.sharpeRatio), 1);
		const maxPF = Math.max(...activeStats.map((s) => s.profitFactor), 1);

		return [
			{ subject: "Win Rate", full: 100 },
			{ subject: "Profit Factor", full: maxPF },
			{ subject: "Sharpe", full: maxSharpe },
			{ subject: "Total PnL", full: maxPnl },
			{ subject: "Low Drawdown", full: 100 }, // Inverted DD
		].map((metric) => {
			const point: Record<string, string | number> = {
				subject: metric.subject,
			};
			activeStats.forEach((stat) => {
				let val = 0;
				switch (metric.subject) {
					case "Win Rate":
						val = stat.winRate;
						break;
					case "Profit Factor":
						val = Math.min((stat.profitFactor / 6) * 100, 100);
						break; // Cap at 6
					case "Sharpe":
						val = Math.min((stat.sharpeRatio / 3) * 100, 100);
						break; // Cap at 3
					case "Total PnL":
						val = Math.min((Math.max(stat.totalPnlPct, 0) / 50) * 100, 100);
						break; // Cap at 50%
					case "Low Drawdown":
						val = Math.max(100 - Math.abs(stat.maxDrawdown) * 2, 0);
						break;
				}
				point[stat.id] = val;
			});
			return point;
		});
	}, [activeStats]);

	// Combined Equity Data
	const combinedEquity = useMemo(() => {
		if (activeStats.length === 0) return [];

		// Collect all unique timestamps
		const allTimes = new Set<number>();
		activeStats.forEach((s) => {
			s.equityCurve.forEach((p) => {
				allTimes.add(p.time);
			});
		});
		const sortedTimes = Array.from(allTimes).sort((a, b) => a - b);

		// Downsample if too many points for performance
		const points =
			sortedTimes.length > 500
				? sortedTimes.filter(
						(_, i) => i % Math.ceil(sortedTimes.length / 500) === 0,
					)
				: sortedTimes;

		return points.map((time) => {
			const point: Record<string, number> = { time };
			activeStats.forEach((stat) => {
				// Find closest value before or at time
				// Since arrays are sorted, we could optimize, but findLast is usable
				// Fallback to initial capital if before start
				const bisect = stat.equityCurve.reduce(
					(prev, curr) => (curr.time <= time ? curr : prev),
					{ time: 0, value: config.initialCapital },
				);
				point[stat.id] = bisect.value;
			});
			return point;
		});
	}, [activeStats, config.initialCapital]);

	// --- Render ---

	return (
		<div className="space-y-6 animate-in fade-in duration-700">
			{/* Header and Controls */}
			<div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
				<div>
					<h2 className="text-2xl font-bold flex items-center gap-2">
						<Scale className="text-purple-500" />
						{t("compareTitle", "Comparative Analysis")}
					</h2>
					<p className="text-sm text-muted-foreground">
						{t("compareDesc", "Multi-strategy performance comparison")}
					</p>
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
								Inspector ({inspectorStats.length})
							</TabsTrigger>
							<TabsTrigger value="simulator" disabled={!hasSimulationData}>
								Simulator ({simulatorStats.length})
							</TabsTrigger>
						</TabsList>
					</Tabs>
				</div>
			</div>

			{!compareSource ? (
				<div className="flex flex-col items-center justify-center h-full min-h-[400px] text-muted-foreground space-y-4">
					<Scale size={48} className="opacity-50" />
					<div className="text-center">
						<h3 className="text-xl font-bold text-foreground">
							{t("noComparisonData", "No Data to Compare")}
						</h3>
						<p className="max-w-xs mx-auto text-sm">
							{t(
								"runTestsFirst",
								"Run Inspector or Simulation to generate data for comparison.",
							)}
						</p>
					</div>
				</div>
			) : (
				<>
					<div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
						{/* Radar Chart */}
						<Card>
							<CardHeader>
								<CardTitle className="text-sm uppercase tracking-widest text-muted-foreground flex items-center gap-2">
									<Activity size={14} />
									{t("performanceProfile", "Performance Profile")}
								</CardTitle>
							</CardHeader>
							<CardContent className="h-[350px]">
								<ResponsiveContainer width="100%" height="100%">
									<RadarChart
										cx="50%"
										cy="50%"
										outerRadius="75%"
										data={radarData}
									>
										<PolarGrid stroke="hsl(var(--border))" />
										<PolarAngleAxis
											dataKey="subject"
											tick={{
												fill: "hsl(var(--muted-foreground))",
												fontSize: 10,
											}}
										/>
										<PolarRadiusAxis
											domain={[0, 100]}
											tick={false}
											axisLine={false}
										/>
										{activeStats.map((stat) => (
											<Radar
												key={stat.id}
												name={stat.name}
												dataKey={stat.id}
												stroke={stat.color}
												fill={stat.color}
												fillOpacity={0.2}
											/>
										))}
										<Tooltip
											contentStyle={{
												backgroundColor: "hsl(var(--card))",
												borderRadius: "8px",
												border: "1px solid hsl(var(--border))",
											}}
											itemStyle={{ fontSize: "12px", fontWeight: "bold" }}
										/>
										<Legend
											iconType="circle"
											wrapperStyle={{ fontSize: "12px", paddingTop: "10px" }}
										/>
									</RadarChart>
								</ResponsiveContainer>
							</CardContent>
						</Card>

						{/* Metrics Table */}
						<Card className="flex flex-col">
							<CardHeader>
								<CardTitle className="text-sm uppercase tracking-widest text-muted-foreground flex items-center gap-2">
									<Divide size={14} />
									{t("metricsComparison", "Metrics Comparison")}
								</CardTitle>
							</CardHeader>
							<CardContent className="flex-1 p-0">
								<ScrollArea className="h-[350px]">
									<table className="w-full text-sm">
										<thead className="bg-muted/50 text-xs font-bold text-muted-foreground uppercase sticky top-0">
											<tr>
												<th className="p-3 text-left">
													{t("strategy", "Strategy")}
												</th>
												<th className="p-3 text-right">PnL %</th>
												<th className="p-3 text-right">Win Rate</th>
												<th className="p-3 text-right">PF</th>
												<th className="p-3 text-right">Sharpe</th>
												<th className="p-3 text-right">Avg DD %</th>{" "}
												{/* Changed Header */}
											</tr>
										</thead>
										<tbody className="divide-y divide-border/50">
											{activeStats.map((stat) => (
												<tr
													key={stat.id}
													className="hover:bg-muted/20 transition-colors"
												>
													<td className="p-3 font-medium flex items-center gap-2">
														<span
															className="w-2 h-2 rounded-full"
															style={{ backgroundColor: stat.color }}
														/>
														{stat.name}
													</td>
													<td
														className={`p-3 text-right font-mono font-bold ${stat.totalPnlPct > 0 ? "text-emerald-500" : stat.totalPnlPct < 0 ? "text-rose-500" : ""}`}
													>
														{stat.totalPnlPct > 0 ? "+" : ""}
														{stat.totalPnlPct.toFixed(2)}%
													</td>
													<td className="p-3 text-right font-mono">
														{stat.winRate.toFixed(1)}%
													</td>
													<td className="p-3 text-right font-mono">
														{stat.profitFactor.toFixed(2)}
													</td>
													<td className="p-3 text-right font-mono">
														{stat.sharpeRatio.toFixed(2)}
													</td>
													<td className="p-3 text-right font-mono text-rose-500">
														{Math.abs(stat.maxDrawdown).toFixed(2)}%
													</td>
												</tr>
											))}
										</tbody>
									</table>
								</ScrollArea>
							</CardContent>
						</Card>
					</div>

					{/* Equity Chart */}
					<Card>
						<CardHeader>
							<CardTitle className="text-sm uppercase tracking-widest text-muted-foreground flex items-center gap-2">
								<TrendingUp size={14} />
								{t("equityComparison", "Equity Comparison")}
							</CardTitle>
						</CardHeader>
						<CardContent className="h-[400px]">
							{activeStats.every((s) => s.equityCurve.length <= 1) ? (
								<div className="h-full flex items-center justify-center text-muted-foreground text-sm">
									{t(
										"noEquityData",
										"No confirmed trades to build equity curves",
									)}
								</div>
							) : (
								<ResponsiveContainer width="100%" height="100%">
									<LineChart
										data={combinedEquity}
										margin={{ top: 10, right: 10, left: 10, bottom: 0 }}
									>
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
											minTickGap={30}
										/>
										<YAxis
											stroke="hsl(var(--muted-foreground))"
											fontSize={10}
											domain={["auto", "auto"]}
										/>
										<Tooltip
											contentStyle={{
												backgroundColor: "hsl(var(--card))",
												borderRadius: "8px",
												border: "1px solid hsl(var(--border))",
											}}
											labelFormatter={(t) => new Date(t).toLocaleString()}
											itemStyle={{ padding: 0 }}
										/>
										<Legend wrapperStyle={{ paddingTop: "10px" }} />
										{activeStats.map((stat) => (
											<Line
												key={stat.id}
												type="monotone"
												dataKey={stat.id}
												name={stat.name}
												stroke={stat.color}
												strokeWidth={2}
												dot={false}
												activeDot={{ r: 4 }}
											/>
										))}
									</LineChart>
								</ResponsiveContainer>
							)}
						</CardContent>
					</Card>
				</>
			)}
		</div>
	);
};

export default CompareView;
