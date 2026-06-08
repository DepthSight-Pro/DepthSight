// src/pages/admin/AnalyticsPage.tsx

import { BarChart3, Layers, PieChart, Table2, Target } from "lucide-react";
import type React from "react";
import { useMemo, useState } from "react";
import FoundationDistributionChart from "@/components/admin/analytics/FoundationDistributionChart";
import FoundationEffectivenessChart from "@/components/admin/analytics/FoundationEffectivenessChart";
import FoundationScatterChart from "@/components/admin/analytics/FoundationScatterChart";
import FoundationStatsTable from "@/components/admin/analytics/FoundationStatsTable";
import MarketSentimentChart from "@/components/admin/analytics/MarketSentimentChart";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAdminFoundationStats, useAdminMarketSentiment } from "@/lib/api";
import type { FoundationStat } from "@/types/api";

type SourceType = "backtest" | "paper" | "live";

// Function to extract the base type from the condition name
const extractConditionType = (foundationId: string): string => {
	if (!foundationId) return "unknown";

	const name = foundationId.toLowerCase();

	// RSI variants
	if (name.includes("rsi")) return "RSI";
	// MA / EMA / SMA
	if (name.includes("ma_cross") || name.includes("ema") || name.includes("sma"))
		return "Moving Average";
	// MACD
	if (name.includes("macd")) return "MACD";
	// Volume
	if (name.includes("volume") || name.includes("vol_")) return "Volume";
	// Trend
	if (name.includes("trend")) return "Trend";
	// Level / Zone
	if (name.includes("level") || name.includes("zone")) return "Levels & Zones";
	// Tape / Order Book
	if (
		name.includes("tape") ||
		name.includes("order_book") ||
		name.includes("orderbook")
	)
		return "Order Flow";
	// Pattern
	if (
		name.includes("pattern") ||
		name.includes("pinbar") ||
		name.includes("candle")
	)
		return "Patterns";
	// Momentum
	if (name.includes("momentum")) return "Momentum";
	// Bollinger
	if (name.includes("bollinger") || name.includes("bb_"))
		return "Bollinger Bands";
	// Stochastic
	if (name.includes("stoch")) return "Stochastic";
	// Value / Price comparison
	if (
		name.includes("value") ||
		name.includes("price_") ||
		name.includes("retest")
	)
		return "Price Action";
	// Global targets
	if (name.includes("global") || name.includes("target"))
		return "Global Targets";

	// Default: capitalize first part
	return foundationId.split("_")[0].toUpperCase();
};

// Function for aggregating statistics by type
const aggregateByType = (data: FoundationStat[]): FoundationStat[] => {
	const typeMap = new Map<
		string,
		{
			count: number;
			totalWinRate: number;
			grossProfit: number;
			grossLoss: number;
		}
	>();

	data.forEach((stat) => {
		const type = extractConditionType(stat.foundationId);
		const existing = typeMap.get(type) || {
			count: 0,
			totalWinRate: 0,
			grossProfit: 0,
			grossLoss: 0,
		};

		existing.count += stat.count;
		existing.totalWinRate += (stat.avgWinRateContribution || 0) * stat.count;
		existing.grossProfit += stat.totalGrossProfit || 0;
		existing.grossLoss += stat.totalGrossLoss || 0;

		typeMap.set(type, existing);
	});

	return Array.from(typeMap.entries()).map(([type, stats]) => ({
		foundationId: type,
		count: stats.count,
		avgWinRateContribution:
			stats.count > 0 ? stats.totalWinRate / stats.count : 0,
		totalGrossProfit: stats.grossProfit,
		totalGrossLoss: stats.grossLoss,
		profitFactor:
			stats.grossLoss > 0
				? stats.grossProfit / stats.grossLoss
				: stats.grossProfit > 0
					? Infinity
					: 0,
	}));
};

const AnalyticsPage: React.FC = () => {
	const [activeSource, setActiveSource] = useState<SourceType>("live");
	const [groupByType, setGroupByType] = useState(false);

	const {
		data: backtestFoundationStats,
		isLoading: isLoadingBacktestFoundation,
	} = useAdminFoundationStats("backtest");
	const { data: backtestMarketSentiment, isLoading: isLoadingBacktestMarket } =
		useAdminMarketSentiment("backtest");
	const { data: liveFoundationStats, isLoading: isLoadingLiveFoundation } =
		useAdminFoundationStats("live");
	const { data: liveMarketSentiment, isLoading: isLoadingLiveMarket } =
		useAdminMarketSentiment("live");
	const { data: paperFoundationStats, isLoading: isLoadingPaperFoundation } =
		useAdminFoundationStats("paper");
	const { data: paperMarketSentiment, isLoading: isLoadingPaperMarket } =
		useAdminMarketSentiment("paper");

	const getDataForSource = (source: SourceType) => {
		switch (source) {
			case "backtest":
				return {
					foundation: backtestFoundationStats || [],
					sentiment: backtestMarketSentiment || [],
					isLoadingFoundation: isLoadingBacktestFoundation,
					isLoadingSentiment: isLoadingBacktestMarket,
					color: "blue",
					label: "Backtests",
				};
			case "paper":
				return {
					foundation: paperFoundationStats || [],
					sentiment: paperMarketSentiment || [],
					isLoadingFoundation: isLoadingPaperFoundation,
					isLoadingSentiment: isLoadingPaperMarket,
					color: "yellow",
					label: "Paper",
				};
			case "live":
				return {
					foundation: liveFoundationStats || [],
					sentiment: liveMarketSentiment || [],
					isLoadingFoundation: isLoadingLiveFoundation,
					isLoadingSentiment: isLoadingLiveMarket,
					color: "green",
					label: "Live",
				};
		}
	};

	const currentData = getDataForSource(activeSource);

	// Apply grouping if enabled
	const displayData = useMemo(() => {
		if (groupByType) {
			return aggregateByType(currentData.foundation);
		}
		return currentData.foundation;
	}, [currentData.foundation, groupByType]);

	// Calculate summary stats
	const totalTrades = currentData.foundation.reduce(
		(sum, s) => sum + s.count,
		0,
	);
	const avgProfitFactor =
		currentData.foundation.length > 0
			? currentData.foundation.reduce(
					(sum, s) => sum + (s.profitFactor || 0),
					0,
				) / currentData.foundation.length
			: 0;
	const avgWinRate =
		currentData.foundation.length > 0
			? (currentData.foundation.reduce(
					(sum, s) => sum + (s.avgWinRateContribution || 0),
					0,
				) /
					currentData.foundation.length) *
				100
			: 0;

	return (
		<div className="space-y-6">
			{/* Header */}
			<div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
				<div>
					<h1 className="text-3xl font-bold mb-2">Product Analytics</h1>
					<p className="text-muted-foreground">
						Track strategy performance and entry condition effectiveness
					</p>
				</div>

				<div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center">
					{/* Group by Type Toggle */}
					<div className="flex items-center space-x-2 bg-muted/30 px-3 py-2 rounded-lg">
						<Layers className="h-4 w-4 text-muted-foreground" />
						<Label htmlFor="group-mode" className="text-sm cursor-pointer">
							Group by Type
						</Label>
						<Switch
							id="group-mode"
							checked={groupByType}
							onCheckedChange={setGroupByType}
						/>
					</div>

					{/* Source Selector */}
					<div className="flex gap-2">
						{(["backtest", "paper", "live"] as const).map((source) => {
							const colors = {
								backtest: "bg-blue-500/20 text-blue-400 border-blue-500/50",
								paper: "bg-yellow-500/20 text-yellow-400 border-yellow-500/50",
								live: "bg-green-500/20 text-green-400 border-green-500/50",
							};
							const activeColors = {
								backtest: "bg-blue-500 text-white",
								paper: "bg-yellow-500 text-black",
								live: "bg-green-500 text-white",
							};
							return (
								<button
									key={source}
									onClick={() => setActiveSource(source)}
									className={`px-4 py-2 rounded-lg border transition-all font-medium ${
										activeSource === source
											? activeColors[source]
											: `${colors[source]} hover:opacity-80`
									}`}
								>
									{source.charAt(0).toUpperCase() + source.slice(1)}
								</button>
							);
						})}
					</div>
				</div>
			</div>

			{/* Grouping indicator */}
			{groupByType && (
				<div className="flex items-center gap-2 px-4 py-2 bg-purple-500/10 border border-purple-500/30 rounded-lg">
					<Layers className="h-4 w-4 text-purple-400" />
					<span className="text-sm text-purple-300">
						Viewing aggregated by condition type ({displayData.length} types
						from {currentData.foundation.length} conditions)
					</span>
				</div>
			)}

			{/* Summary Cards */}
			<div className="grid grid-cols-2 md:grid-cols-4 gap-4">
				<Card className="bg-gradient-to-br from-blue-500/10 to-blue-600/5 border-blue-500/20">
					<CardContent className="pt-6">
						<p className="text-sm text-muted-foreground">Total Trades</p>
						<p className="text-3xl font-bold text-blue-400">
							{totalTrades.toLocaleString()}
						</p>
					</CardContent>
				</Card>
				<Card className="bg-gradient-to-br from-purple-500/10 to-purple-600/5 border-purple-500/20">
					<CardContent className="pt-6">
						<p className="text-sm text-muted-foreground">
							{groupByType ? "Condition Types" : "Unique Conditions"}
						</p>
						<p className="text-3xl font-bold text-purple-400">
							{displayData.length}
						</p>
					</CardContent>
				</Card>
				<Card className="bg-gradient-to-br from-green-500/10 to-green-600/5 border-green-500/20">
					<CardContent className="pt-6">
						<p className="text-sm text-muted-foreground">Avg Win Rate</p>
						<p className="text-3xl font-bold text-green-400">
							{avgWinRate.toFixed(1)}%
						</p>
					</CardContent>
				</Card>
				<Card className="bg-gradient-to-br from-amber-500/10 to-amber-600/5 border-amber-500/20">
					<CardContent className="pt-6">
						<p className="text-sm text-muted-foreground">Avg Profit Factor</p>
						<p className="text-3xl font-bold text-amber-400">
							{avgProfitFactor.toFixed(2)}
						</p>
					</CardContent>
				</Card>
			</div>

			{/* Main Content with Tabs */}
			<Tabs defaultValue="charts" className="space-y-4">
				<TabsList className="bg-muted/50">
					<TabsTrigger value="charts" className="flex items-center gap-2">
						<BarChart3 className="h-4 w-4" />
						Performance Charts
					</TabsTrigger>
					<TabsTrigger value="distribution" className="flex items-center gap-2">
						<PieChart className="h-4 w-4" />
						Distribution
					</TabsTrigger>
					<TabsTrigger value="quality" className="flex items-center gap-2">
						<Target className="h-4 w-4" />
						Quality Matrix
					</TabsTrigger>
					<TabsTrigger value="table" className="flex items-center gap-2">
						<Table2 className="h-4 w-4" />
						Data Table
					</TabsTrigger>
				</TabsList>

				{/* Performance Charts Tab */}
				<TabsContent value="charts" className="space-y-4">
					<div className="grid gap-4 lg:grid-cols-2">
						<FoundationEffectivenessChart
							data={displayData}
							isLoading={currentData.isLoadingFoundation}
							title={`Entry Conditions Performance (${currentData.label})${groupByType ? " - Grouped" : ""}`}
						/>
						<MarketSentimentChart
							data={currentData.sentiment}
							isLoading={currentData.isLoadingSentiment}
							title={`Market Sentiment (${currentData.label})`}
						/>
					</div>
				</TabsContent>

				{/* Distribution Tab */}
				<TabsContent value="distribution" className="space-y-4">
					<div className="grid gap-4 lg:grid-cols-2">
						<FoundationDistributionChart
							data={displayData}
							isLoading={currentData.isLoadingFoundation}
							title={`Trade Distribution (${currentData.label})${groupByType ? " - Grouped" : ""}`}
						/>
						<Card>
							<CardHeader>
								<CardTitle>Top Performers</CardTitle>
								<CardDescription>
									{groupByType ? "Condition types" : "Conditions"} with highest
									profit factor (min 10 trades)
								</CardDescription>
							</CardHeader>
							<CardContent>
								<div className="space-y-3">
									{[...displayData]
										.filter((s) => s.count >= 10)
										.sort(
											(a, b) => (b.profitFactor || 0) - (a.profitFactor || 0),
										)
										.slice(0, 5)
										.map((stat, index) => (
											<div
												key={stat.foundationId}
												className="flex items-center justify-between p-3 bg-muted/30 rounded-lg"
											>
												<div className="flex items-center gap-3">
													<span
														className={`
                            w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold
                            ${
															index === 0
																? "bg-yellow-500/20 text-yellow-500"
																: index === 1
																	? "bg-gray-400/20 text-gray-400"
																	: index === 2
																		? "bg-amber-600/20 text-amber-600"
																		: "bg-muted text-muted-foreground"
														}
                          `}
													>
														#{index + 1}
													</span>
													<div>
														<p className="font-medium text-sm">
															{stat.foundationId || "Unknown"}
														</p>
														<p className="text-xs text-muted-foreground">
															{stat.count} trades
														</p>
													</div>
												</div>
												<div className="text-right">
													<p className="font-bold text-green-500">
														{stat.profitFactor?.toFixed(2) || "N/A"}
													</p>
													<p className="text-xs text-muted-foreground">PF</p>
												</div>
											</div>
										))}
									{displayData.filter((s) => s.count >= 10).length === 0 && (
										<p className="text-center text-muted-foreground py-8">
											No conditions with 10+ trades yet
										</p>
									)}
								</div>
							</CardContent>
						</Card>
					</div>
				</TabsContent>

				{/* Quality Matrix Tab */}
				<TabsContent value="quality" className="space-y-4">
					<FoundationScatterChart
						data={displayData}
						isLoading={currentData.isLoadingFoundation}
						title={`Condition Quality Matrix (${currentData.label})${groupByType ? " - Grouped" : ""}`}
					/>
					<div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
						<Card className="border-green-500/30">
							<CardContent className="pt-6">
								<p className="text-sm text-green-400 font-medium">
									🟢 Excellent
								</p>
								<p className="text-2xl font-bold">
									{
										displayData.filter(
											(s) =>
												(s.avgWinRateContribution || 0) > 0 &&
												(s.profitFactor || 0) > 1.5,
										).length
									}
								</p>
								<p className="text-xs text-muted-foreground">
									WR &gt; 0% & PF &gt; 1.5
								</p>
							</CardContent>
						</Card>
						<Card className="border-blue-500/30">
							<CardContent className="pt-6">
								<p className="text-sm text-blue-400 font-medium">🔵 Good</p>
								<p className="text-2xl font-bold">
									{
										displayData.filter(
											(s) =>
												(s.avgWinRateContribution || 0) > 0 &&
												(s.profitFactor || 0) > 1 &&
												(s.profitFactor || 0) <= 1.5,
										).length
									}
								</p>
								<p className="text-xs text-muted-foreground">
									WR &gt; 0% & PF 1-1.5
								</p>
							</CardContent>
						</Card>
						<Card className="border-yellow-500/30">
							<CardContent className="pt-6">
								<p className="text-sm text-yellow-400 font-medium">
									🟡 Marginal
								</p>
								<p className="text-2xl font-bold">
									{
										displayData.filter(
											(s) =>
												(s.profitFactor || 0) > 1 &&
												(s.avgWinRateContribution || 0) <= 0,
										).length
									}
								</p>
								<p className="text-xs text-muted-foreground">
									PF &gt; 1 but low WR
								</p>
							</CardContent>
						</Card>
						<Card className="border-red-500/30">
							<CardContent className="pt-6">
								<p className="text-sm text-red-400 font-medium">🔴 Poor</p>
								<p className="text-2xl font-bold">
									{displayData.filter((s) => (s.profitFactor || 0) <= 1).length}
								</p>
								<p className="text-xs text-muted-foreground">PF ≤ 1</p>
							</CardContent>
						</Card>
					</div>
				</TabsContent>

				{/* Data Table Tab */}
				<TabsContent value="table" className="space-y-4">
					<div className="grid gap-4 lg:grid-cols-2">
						<FoundationStatsTable
							data={displayData}
							isLoading={currentData.isLoadingFoundation}
							title={`Entry Conditions Data (${currentData.label})${groupByType ? " - Grouped" : ""}`}
						/>
						<MarketSentimentChart
							data={currentData.sentiment}
							isLoading={currentData.isLoadingSentiment}
							title={`Market Sentiment (${currentData.label})`}
						/>
					</div>
				</TabsContent>
			</Tabs>
		</div>
	);
};

export default AnalyticsPage;
