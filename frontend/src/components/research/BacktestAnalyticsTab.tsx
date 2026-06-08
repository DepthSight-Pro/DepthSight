// src/components/research/BacktestAnalyticsTab.tsx

import type React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { AnalyticsFilters } from "@/components/analytics/AnalyticsFilters";
import { CumulativePnlChart } from "@/components/analytics/CumulativePnlChart";
import { PnlDistributionChart } from "@/components/analytics/PnlDistributionChart";
import { TradeChart } from "@/components/analytics/TradeChart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type {
	BacktestRunDetailsData,
	BacktestTrade,
	TradeData,
} from "@/types/api";
import { BacktestTradeHistoryTable } from "./BacktestTradeHistoryTable";

const calculateStats = (trades: BacktestTrade[]) => {
	if (!trades || trades.length === 0) {
		return {
			netProfit: 0,
			totalTrades: 0,
			winRate: 0,
			profitFactor: "N/A",
			avgPnl: 0,
		};
	}
	const netProfit = trades.reduce((sum, t) => sum + t.pnl, 0);
	const winningTradesCount = trades.filter((t) => t.pnl > 0).length;
	const totalTradesForRate = trades.length;
	const winRate =
		totalTradesForRate > 0
			? (winningTradesCount / totalTradesForRate) * 100
			: 0;
	const grossProfit = trades
		.filter((t) => t.pnl > 0)
		.reduce((sum, t) => sum + t.pnl, 0);
	const grossLoss = trades
		.filter((t) => t.pnl < 0)
		.reduce((sum, t) => sum + t.pnl, 0);
	const profitFactor =
		grossLoss !== 0 ? Math.abs(grossProfit / grossLoss) : Infinity;
	const avgPnl = totalTradesForRate > 0 ? netProfit / totalTradesForRate : 0;
	return {
		netProfit,
		totalTrades: trades.length,
		winRate,
		profitFactor,
		avgPnl,
	};
};

const StatCard = ({
	label,
	value,
	prefix = "",
	suffix = "",
}: {
	label: string;
	value: string | number;
	prefix?: string;
	suffix?: string;
}) => (
	<Card>
		<CardHeader className="pb-2">
			<CardTitle className="text-sm font-normal text-muted-foreground">
				{label}
			</CardTitle>
		</CardHeader>
		<CardContent>
			<div className="text-2xl font-bold mono">
				{prefix}
				{value}
				{suffix}
			</div>
		</CardContent>
	</Card>
);

interface BacktestAnalyticsTabProps {
	run: BacktestRunDetailsData;
}

export const BacktestAnalyticsTab: React.FC<BacktestAnalyticsTabProps> = ({
	run,
}) => {
	const { t } = useTranslation("research");

	// `run.trades` now contains the FULL list of trades for analytics
	const allTrades = useMemo(() => run.trades || [], [run.trades]);

	const [filteredTrades, setFilteredTrades] =
		useState<BacktestTrade[]>(allTrades);
	const [selectedTrade, setSelectedTrade] = useState<BacktestTrade | null>(
		null,
	);

	useEffect(() => {
		setFilteredTrades(allTrades);
	}, [allTrades]);

	const stats = useMemo(() => calculateStats(filteredTrades), [filteredTrades]);

	const handleApplyFilters = (filters: {
		dateFrom?: string;
		dateTo?: string;
	}) => {
		setSelectedTrade(null);
		const { dateFrom, dateTo } = filters;
		const newFilteredTrades = allTrades.filter((trade: BacktestTrade) => {
			const tradeDate = new Date(trade.timestamp_exit);
			const fromMatch = dateFrom ? tradeDate >= new Date(dateFrom) : true;
			const toMatch = dateTo ? tradeDate <= new Date(dateTo) : true;
			return fromMatch && toMatch;
		});
		setFilteredTrades(newFilteredTrades);
	};

	const handleClearFilters = () => {
		setSelectedTrade(null);
		setFilteredTrades(allTrades);
	};

	// --- Converting BacktestTrade to TradeData ---
	const convertBacktestTradeToTradeData = useCallback(
		(trade: BacktestTrade): TradeData => ({
			...trade,
			id: trade.id,
			trade_uuid: `${run.id}-${trade.id}`,
			timestamp_signal: new Date(trade.timestamp_entry).getTime(),
			timestamp_entry: new Date(trade.timestamp_entry).getTime(),
			timestamp_close: new Date(trade.timestamp_exit).getTime(),
			symbol: run.symbol,
			strategy: run.strategy_name,
			trade_mode: "PAPER" as const,
		}),
		[run.id, run.symbol, run.strategy_name],
	);

	// --- Sorting trades for charts ---
	const convertedTradesForCharts = useMemo((): TradeData[] => {
		if (!run || !filteredTrades) return [];
		// Sort by trade start time (ascending)
		const sortedTrades = [...filteredTrades].sort(
			(a, b) =>
				new Date(a.timestamp_entry).getTime() -
				new Date(b.timestamp_entry).getTime(),
		);
		return sortedTrades.map(convertBacktestTradeToTradeData);
	}, [filteredTrades, run, convertBacktestTradeToTradeData]);

	const selectedTradeForChart = useMemo((): TradeData | null => {
		if (!selectedTrade) return null;
		return convertBacktestTradeToTradeData(selectedTrade);
	}, [selectedTrade, convertBacktestTradeToTradeData]);

	if (run.status !== "COMPLETED" || !run.trades) {
		return (
			<p className="text-muted-foreground">{t("analytics.notAvailable")}</p>
		);
	}

	const AnalyticsOverview = () => (
		<div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 mb-6">
			<StatCard
				label={t("analytics.statNetProfit")}
				value={stats.netProfit.toFixed(2)}
				prefix="$"
			/>
			<StatCard
				label={t("analytics.statTotalTrades")}
				value={stats.totalTrades}
			/>
			<StatCard
				label={t("analytics.statWinRate")}
				value={stats.winRate.toFixed(1)}
				suffix="%"
			/>
			<StatCard
				label={t("analytics.statAvgPnlPerTrade")}
				value={stats.avgPnl.toFixed(2)}
				prefix="$"
			/>
			<StatCard
				label={t("analytics.statProfitFactor")}
				value={
					stats.profitFactor === Infinity
						? "∞"
						: typeof stats.profitFactor === "number"
							? stats.profitFactor.toFixed(2)
							: "N/A"
				}
			/>
		</div>
	);

	return (
		<div className="space-y-6">
			<AnalyticsFilters
				onApply={handleApplyFilters}
				onClear={handleClearFilters}
				strategies={[]}
			/>
			<AnalyticsOverview />
			<Tabs defaultValue="cumulative" className="mt-6">
				<TabsList className="bg-card mb-4">
					<TabsTrigger value="cumulative">
						{t("analytics.tabCumulativePnl")}
					</TabsTrigger>
					<TabsTrigger value="distribution">
						{t("analytics.tabDistribution")}
					</TabsTrigger>
				</TabsList>
				<Card>
					<CardContent className="pt-6 min-h-[450px]">
						<TabsContent value="cumulative">
							<CumulativePnlChart tradeData={convertedTradesForCharts} />
						</TabsContent>
						<TabsContent value="distribution">
							<PnlDistributionChart tradeData={convertedTradesForCharts} />
						</TabsContent>
					</CardContent>
				</Card>
			</Tabs>

			<TradeChart
				trades={convertedTradesForCharts}
				symbol={run.symbol || ""}
				runId={run.id}
				selectedTrade={selectedTradeForChart}
			/>

			{/* --- Passing runId to the table --- */}
			<BacktestTradeHistoryTable
				runId={run.id}
				status={
					run.status.toLowerCase() as
						| "completed"
						| "running"
						| "pending"
						| "failed"
				}
				onViewTradeOnChart={(trade) => setSelectedTrade(trade)}
			/>
		</div>
	);
};
