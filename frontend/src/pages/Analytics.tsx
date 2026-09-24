// src/pages/Analytics.tsx

import { subDays } from "date-fns";
import { BarChart, Sparkles, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import type { DateRange } from "react-day-picker"; // Added missing import
import { useTranslation } from "react-i18next";
import { AdvancedStatCard } from "@/components/analytics/AdvancedStatCard";
import { AnalyticsFilters } from "@/components/analytics/AnalyticsFilters";
import { DayOfWeekPnlChart } from "@/components/analytics/DayOfWeekPnlChart";
import { HourlyPnlChart } from "@/components/analytics/HourlyPnlChart";
import { InteractiveAssetChart } from "@/components/analytics/InteractiveAssetChart";
import { LiveTradeHistoryTable } from "@/components/analytics/LiveTradeHistoryTable";
import { PhantomAnalysisTab } from "@/components/analytics/PhantomAnalysisTab";
import { TradeAnalysisModal } from "@/components/analytics/TradeAnalysisModal";
// --- UI Components ---
import { PageLayout } from "@/components/layout/PageLayout";
import { EquityCurveChart } from "@/components/research/EquityCurveChart";
import { Panel, Segmented } from "@/components/ui/quant-ui";
import { Skeleton } from "@/components/ui/skeleton";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
// --- API & Types ---
import {
	type TradeHistoryParams,
	useStrategyConfigsList,
	useTradeHistory,
} from "@/lib/api";
import { useAccountStore } from "@/stores/accountStore";
import { useAiCopilotStore } from "@/stores/aiCopilotStore";
import type { TradeData } from "@/types/api";

// --- Types for Dashboard Stats ---
interface DashboardStats {
	totalPnl: number;
	winRate: number;
	profitFactor: number;
	expectancy: number;
	sharpeRatio: number;
	sharpeInsufficient: boolean; // true if not enough days for calculation
	totalTrades: number;
	wins: number;
	losses: number;
	totalCommission: number;
	avgWinLossRatio: number;
	totalVolume: number;
}

// --- Helper Functions ---
const calculateAdvancedStats = (trades: TradeData[]): DashboardStats | null => {
	if (trades.length === 0) return null;

	const tradesWithRealizedPnl = trades.map((t) => ({
		...t,
		realizedPnl: t.pnl || 0,
	}));

	const totalPnl = tradesWithRealizedPnl.reduce(
		(sum, t) => sum + t.realizedPnl,
		0,
	);
	const wins = tradesWithRealizedPnl.filter((t) => t.realizedPnl > 0);
	const losses = tradesWithRealizedPnl.filter((t) => t.realizedPnl <= 0);
	const winRate = (wins.length / tradesWithRealizedPnl.length) * 100;

	const grossProfit = wins.reduce((sum, t) => sum + t.realizedPnl, 0);
	const grossLoss = Math.abs(losses.reduce((sum, t) => sum + t.realizedPnl, 0));
	const profitFactor = grossLoss === 0 ? grossProfit : grossProfit / grossLoss;

	const avgWin = wins.length > 0 ? grossProfit / wins.length : 0;
	const avgLoss = losses.length > 0 ? grossLoss / losses.length : 0;
	const expectancy = (winRate / 100) * avgWin - (1 - winRate / 100) * avgLoss;
	const avgWinLossRatio = avgLoss > 0 ? avgWin / avgLoss : avgWin;

	// Total commission
	const totalCommission = trades.reduce(
		(sum, t) => sum + (t.commission || 0),
		0,
	);

	// Total volume
	const totalVolume = trades.reduce((sum, t) => {
		const qty = t.quantity || 0;
		return sum + qty * (t.entry_price || 0) + qty * (t.exit_price || 0);
	}, 0);

	// --- Improved Sharpe Ratio (Daily annualization) ---
	const dailyPnLMap: Record<string, number> = {};
	tradesWithRealizedPnl.forEach((t) => {
		// Use close time for daily bucketing
		const dateKey = new Date(t.timestamp_close).toISOString().split("T")[0];
		dailyPnLMap[dateKey] = (dailyPnLMap[dateKey] || 0) + t.realizedPnl;
	});

	const dailyReturns = Object.values(dailyPnLMap);

	let sharpeRatio = 0;
	let sharpeInsufficient = false;
	// Require at least 2 days for variance calculation
	if (dailyReturns.length >= 2) {
		const avgDailyReturn =
			dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
		// Use Sample Variance (N-1) for better estimation on small samples
		const dailyVariance =
			dailyReturns.reduce((sum, ret) => sum + (ret - avgDailyReturn) ** 2, 0) /
			(dailyReturns.length - 1);
		const dailyStdDev = Math.sqrt(dailyVariance);

		// Avoid division by zero
		if (dailyStdDev > 0.0001) {
			sharpeRatio = (avgDailyReturn / dailyStdDev) * Math.sqrt(365);
		} else {
			// If deviation is zero (perfectly consistent returns)
			if (avgDailyReturn > 0)
				sharpeRatio = 50; // Max cap
			else if (avgDailyReturn < 0) sharpeRatio = -50; // Min cap
		}

		// Clamp extreme values
		if (sharpeRatio > 50) sharpeRatio = 50;
		if (sharpeRatio < -50) sharpeRatio = -50;
	} else {
		sharpeInsufficient = true; // Not enough days for calculation
	}

	return {
		totalPnl,
		winRate,
		profitFactor,
		expectancy,
		sharpeRatio,
		sharpeInsufficient,
		totalTrades: tradesWithRealizedPnl.length,
		wins: wins.length,
		losses: losses.length,
		totalCommission,
		avgWinLossRatio,
		totalVolume,
	};
};

export default function Analytics() {
	const { t } = useTranslation(["analytics", "common"]);
	// Pagination constants
	const PAGE_SIZE = 50;

	// Global account filter
	const { selectedApiKeyId } = useAccountStore();
	const { mode } = usePortfolioMode();
	const { setWidgetState, setAnalyticsContext } = useAiCopilotStore();

	const [dateRange, setDateRange] = useState<DateRange | undefined>({
		from: subDays(new Date(), 30),
		to: new Date(),
	});

	const [selectedStrategy, setSelectedStrategy] = useState<string>("all");
	const [selectedSymbol, setSelectedSymbol] = useState<string>("");
	const [activeTab, setActiveTab] = useState<"overview" | "be_analysis">(
		"overview",
	);

	// State for pagination
	const [tablePage, setTablePage] = useState(1);

	// State for trade analysis modal window
	const [selectedTrade, setSelectedTrade] = useState<TradeData | null>(null);

	const { data: configsList = [] } = useStrategyConfigsList();

	const filters: TradeHistoryParams = useMemo(() => {
		return {
			startDate: dateRange?.from ? dateRange.from.toISOString() : undefined,
			endDate: dateRange?.to ? dateRange.to.toISOString() : undefined,
			strategyConfigId:
				selectedStrategy !== "all" ? selectedStrategy : undefined,
			symbol: selectedSymbol || undefined,
			limit: 10000, // Requesting more data for statistics
			apiKeyId: mode === "live" ? selectedApiKeyId : undefined, // Pass selectedApiKeyId
		};
	}, [dateRange, selectedStrategy, selectedSymbol, selectedApiKeyId, mode]);

	const {
		data: paginatedData, // Renamed from paginatedResponse to match usage
		isLoading,
		isError,
		error,
	} = useTradeHistory({ ...filters, mode });

	// Original trades from API (after server-side filters)
	const serverTrades = useMemo(() => {
		const rawTrades = paginatedData?.trades || []; // paginatedData is now correct
		// Filter out invalid trades to prevent chart errors
		return rawTrades.filter((t) => {
			if (!t?.symbol || !t.timestamp_close) return false;
			const d = new Date(t.timestamp_close);
			return !Number.isNaN(d.getTime()); // Ensure date is valid
		});
	}, [paginatedData]);

	// --- Interactive Filter States ---
	const [activeHours, setActiveHours] = useState<number[]>(
		Array.from({ length: 24 }, (_, i) => i),
	);
	const [activeDays, setActiveDays] = useState<number[]>(
		Array.from({ length: 7 }, (_, i) => i),
	);
	const [activeTickers, setActiveTickers] = useState<string[]>([]);
	const [prevServerTrades, setPrevServerTrades] = useState<TradeData[] | null>(
		null,
	);

	// Get all unique tickers from server trades
	const allUniqueTickers = useMemo(() => {
		const tickers = new Set(serverTrades.map((t) => t.symbol));
		return Array.from(tickers);
	}, [serverTrades]);

	// Reset active tickers when server trades change via render-phase synchronization
	if (serverTrades !== prevServerTrades) {
		setPrevServerTrades(serverTrades);
		setActiveTickers(allUniqueTickers);
		setActiveHours(Array.from({ length: 24 }, (_, i) => i));
		setActiveDays(Array.from({ length: 7 }, (_, i) => i));
	}

	// --- Client-side filtering based on interactive filters ---
	const filteredTrades = useMemo(() => {
		return serverTrades.filter((trade) => {
			const closeTime = new Date(trade.timestamp_close);
			const h = closeTime.getHours();
			const d = closeTime.getDay();
			return (
				activeHours.includes(h) &&
				activeDays.includes(d) &&
				activeTickers.includes(trade.symbol)
			);
		});
	}, [serverTrades, activeHours, activeDays, activeTickers]);

	// --- Calculate stats from filtered trades ---
	const stats = useMemo(
		() => calculateAdvancedStats(filteredTrades),
		[filteredTrades],
	);

	// --- Paginated trades for table display ---
	const paginatedTableTrades = useMemo(() => {
		const startIndex = (tablePage - 1) * PAGE_SIZE;
		const endIndex = startIndex + PAGE_SIZE;
		return filteredTrades.slice(startIndex, endIndex);
	}, [filteredTrades, tablePage]);

	// Total pages for current filtered dataset
	const filteredTotalPages = Math.ceil(filteredTrades.length / PAGE_SIZE);

	// Handle page change
	const handlePageChange = (newPage: number) => {
		if (newPage >= 1 && newPage <= filteredTotalPages) {
			setTablePage(newPage);
		}
	};

	// --- Prepare equity curve data for EquityCurveChart ---
	const equityCurveData = useMemo(() => {
		if (filteredTrades.length === 0) return [];

		let cumulative = 0;
		const sortedTrades = [...filteredTrades].sort(
			(a, b) =>
				new Date(a.timestamp_close).getTime() -
				new Date(b.timestamp_close).getTime(),
		);

		// Add starting point (0, 0) at the beginning of the first trade
		const firstTradeTime = sortedTrades[0]
			? new Date(sortedTrades[0].timestamp_close).getTime()
			: 0;
		const curveData: [number, number][] = [[firstTradeTime - 1000, 0]];

		sortedTrades.forEach((trade) => {
			// Safely convert to number to avoid NaN
			const realizedPnl = Number(trade.pnl) || 0;
			cumulative += realizedPnl;

			const ts = new Date(trade.timestamp_close).getTime();
			if (!Number.isNaN(ts)) {
				curveData.push([ts, cumulative]);
			}
		});

		return curveData;
	}, [filteredTrades]);

	// --- Check if any filter is active ---
	const isFiltered =
		activeHours.length < 24 ||
		activeDays.length < 7 ||
		activeTickers.length < allUniqueTickers.length;

	// --- Toggle handlers ---
	const toggleHour = (hour: number) => {
		setActiveHours((prev) =>
			prev.includes(hour) ? prev.filter((h) => h !== hour) : [...prev, hour],
		);
		setTablePage(1);
	};

	const toggleDay = (day: number) => {
		setActiveDays((prev) =>
			prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day],
		);
		setTablePage(1);
	};

	const toggleTicker = (ticker: string) => {
		setActiveTickers((prev) =>
			prev.includes(ticker)
				? prev.filter((t) => t !== ticker)
				: [...prev, ticker],
		);
		setTablePage(1);
	};

	const resetFilters = () => {
		setActiveHours(Array.from({ length: 24 }, (_, i) => i));
		setActiveDays(Array.from({ length: 7 }, (_, i) => i));
		setActiveTickers(allUniqueTickers);
		setTablePage(1);
	};

	const handleApplyFilters = (newFilters: TradeHistoryParams) => {
		if (newFilters.startDate && newFilters.endDate) {
			setDateRange({
				from: new Date(newFilters.startDate),
				to: new Date(newFilters.endDate),
			});
		}
		// Keep the saved config id as the stable strategy identity for analytics.
		setSelectedStrategy(
			newFilters.strategyConfigId ? String(newFilters.strategyConfigId) : "all",
		);
		setSelectedSymbol(newFilters.symbol || "");
		setTablePage(1); // Reset to first page when filters change
	};
	const handleClearFilters = () => {
		// Reset to default values (30 days)
		setDateRange({
			from: subDays(new Date(), 30),
			to: new Date(),
		});
		setSelectedStrategy("all");
		setSelectedSymbol("");
		setTablePage(1); // Reset to first page
	};

	const handleAskAi = () => {
		const context: Record<string, unknown> = {
			kpis: stats as unknown as Record<string, unknown>,
		};

		if (selectedStrategy !== "all") {
			const config = configsList.find((c) => String(c.id) === selectedStrategy);
			if (config) {
				context.strategy_json = config.config_data;
			}

			const sortedByPnl = [...filteredTrades].sort(
				(a, b) => (b.pnl || 0) - (a.pnl || 0),
			);
			context.top_trades = sortedByPnl.slice(0, 5).map((t) => ({
				pnl: t.pnl,
				exit_reason: t.exit_reason,
				exit_time: t.timestamp_close,
				symbol: t.symbol,
			}));
			context.bottom_trades = sortedByPnl
				.slice(-5)
				.reverse()
				.map((t) => ({
					pnl: t.pnl,
					exit_reason: t.exit_reason,
					exit_time: t.timestamp_close,
					symbol: t.symbol,
				}));
		}

		setAnalyticsContext(context);
		setWidgetState("open");
	};

	return (
		<PageLayout title={t("pageTitle", "Analytics")} hideHeader>
			<div className="space-y-6">
				{/* Top Controls Bar */}
				<div className="flex items-center overflow-x-auto pb-1 max-w-full touch-pan-x [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<Segmented<"overview" | "be_analysis">
						size="md"
						value={activeTab}
						onChange={setActiveTab}
						options={[
							{
								value: "overview",
								label: t("tabs.overview", "Overview"),
								icon: <BarChart className="w-4 h-4" />,
							},
							{
								value: "be_analysis",
								label: t("beAnalysis.title", "BE Analysis"),
								icon: <TrendingUp className="w-4 h-4" />,
							},
						]}
					/>
				</div>

				{activeTab === "overview" && (
					<div className="space-y-6 animate-fade-up">
						{/* Server-side filters */}
						<div className="flex items-center justify-between gap-4 w-full flex-wrap">
							<div className="flex-1 min-w-[300px]">
								<AnalyticsFilters
									onApply={handleApplyFilters}
									onClear={handleClearFilters}
									strategies={configsList || []}
									isInteractiveFiltered={isFiltered}
									onResetInteractive={resetFilters}
								/>
							</div>
							<button
								type="button"
								onClick={handleAskAi}
								className="group relative flex h-9 items-center gap-1.5 overflow-hidden rounded-lg px-3.5 text-[11.5px] font-semibold text-white transition-all bg-gradient-to-r from-azure to-cyan shadow-[0_0_20px_-5px_rgba(0,212,255,0.85)] hover:shadow-[0_0_28px_-3px_rgba(0,212,255,1)] hover:brightness-110 shrink-0 self-end mb-1"
							>
								<span className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
								<Sparkles size={13} className="animate-pulse" />
								<span>Ask AI Analyst</span>
							</button>
						</div>

						{/* Stats Cards */}
						{isLoading ? (
							<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8 gap-3.5 mb-6">
								{Array.from({ length: 8 }).map((_, i) => (
									<div
										key={i}
										className="h-[105px] rounded-2xl bg-white/5 border border-white/5 animate-pulse"
									/>
								))}
							</div>
						) : stats ? (
							<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8 gap-3.5 mb-6">
							<AdvancedStatCard
								label={t("overview.netProfit", "Net PnL")}
								value={`${stats.totalPnl >= 0 ? "+" : ""}$${stats.totalPnl.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
								icon="DollarSign"
								colorClass={
									stats.totalPnl >= 0 ? "bg-emerald-500" : "bg-rose-500"
								}
								subValue={`${stats.totalTrades} trades`}
							/>
							<AdvancedStatCard
								label={t("overview.winRate", "Win Rate")}
								value={`${stats.winRate.toFixed(1)}%`}
								icon="Target"
								colorClass={
									stats.winRate >= 50 ? "bg-emerald-500" : "bg-rose-500"
								}
								subValue={`${stats.wins}W / ${stats.losses}L`}
							/>
							<AdvancedStatCard
								label={t("overview.profitFactor", "Profit Factor")}
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
								label={t("overview.expectancy", "Expectancy")}
								value={`$${stats.expectancy.toFixed(2)}`}
								icon="PieChart"
								colorClass={
									stats.expectancy >= 0 ? "bg-emerald-500" : "bg-rose-500"
								}
								subValue={t("overview.perTrade", "Per trade average")}
							/>
							<AdvancedStatCard
								label={t("overview.sharpeRatio", "Sharpe Ratio")}
								value={
									stats.sharpeInsufficient
										? "N/A"
										: stats.sharpeRatio.toFixed(2)
								}
								icon="Activity"
								colorClass={
									stats.sharpeInsufficient
										? "bg-zinc-500"
										: stats.sharpeRatio >= 1
											? "bg-emerald-500"
											: stats.sharpeRatio >= 0
												? "bg-amber-500"
												: "bg-rose-500"
								}
								subValue={
									stats.sharpeInsufficient
										? t("overview.needsMoreDays", "Needs 2+ days")
										: t("overview.annualized", "Annualized")
								}
							/>
							<AdvancedStatCard
								label={t("overview.totalCommission", "Commission")}
								value={`-$${stats.totalCommission.toFixed(2)}`}
								icon="Receipt"
								colorClass="bg-rose-500"
								subValue={t("overview.totalFees", "Total fees paid")}
							/>
							<AdvancedStatCard
								label={t("overview.avgWinLossRatio", "Win/Loss Ratio")}
								value={
									stats.avgWinLossRatio === Infinity
										? "∞"
										: stats.avgWinLossRatio.toFixed(2)
								}
								icon="TrendingUp"
								colorClass={
									stats.avgWinLossRatio >= 1 ? "bg-emerald-500" : "bg-rose-500"
								}
								subValue={t("overview.avgWinVsLoss", "Avg W vs L")}
							/>
							<AdvancedStatCard
								label={t("overview.totalVolume", "Volume")}
								value={
									stats.totalVolume >= 1000
										? `$${(stats.totalVolume / 1000).toFixed(1)}k`
										: `$${stats.totalVolume.toFixed(0)}`
								}
								icon="BarChart"
								colorClass="bg-blue-500"
								subValue={t("overview.tradedVolume", "Total traded")}
							/>
						</div>
					) : null}

					{/* Charts Section */}
					<div className="space-y-6">
						{/* Equity Curve & Asset Performance */}
						<div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
							<div className="xl:col-span-2">
								<Panel
									title={
										<span className="flex items-center gap-2">
											<TrendingUp className="w-4 h-4 text-cyan" />
											{t("tabs.cumulativePnl", "Equity Curve")}
										</span>
									}
								>
									<div className="min-h-[350px] pt-1">
										{isLoading ? (
											<Skeleton className="w-full h-[350px] bg-white/5 rounded-xl" />
										) : isError ? (
											<div className="text-rose-400 font-mono text-center p-8">
												{error?.message || t("errorOccurred")}
											</div>
										) : (
											<EquityCurveChart
												run={{
													equity_curve_json: equityCurveData,
													status: "COMPLETED",
												}}
												isSingleDay={
													equityCurveData.length > 0 &&
													equityCurveData[equityCurveData.length - 1][0] -
														equityCurveData[0][0] <
														24 * 60 * 60 * 1000
												}
											/>
										)}
									</div>
								</Panel>
							</div>
							<InteractiveAssetChart
								trades={serverTrades}
								activeTickers={activeTickers}
								onToggleTicker={toggleTicker}
							/>
						</div>

						{/* Hourly & Daily Performance */}
						<div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
							<HourlyPnlChart
								trades={serverTrades}
								activeHours={activeHours}
								onToggleHour={toggleHour}
							/>
							<DayOfWeekPnlChart
								trades={serverTrades}
								activeDays={activeDays}
								onToggleDay={toggleDay}
							/>
						</div>
					</div>

					{/* Trade History Table */}
					<LiveTradeHistoryTable
						trades={paginatedTableTrades}
						isLoading={isLoading}
						totalTrades={filteredTrades.length}
						isFiltered={isFiltered}
						onTradeSelect={setSelectedTrade}
						currentPage={tablePage}
						totalPages={filteredTotalPages}
						onPageChange={handlePageChange}
					/>

					{/* Trade Analysis Modal */}
					{selectedTrade && (
						<TradeAnalysisModal
							trade={selectedTrade}
							relatedTrades={serverTrades}
							strategyConfig={
								configsList.find(
									(s) =>
										s.id === selectedTrade.strategy_config_id ||
										s.name === selectedTrade.strategy,
								)?.config_data
							}
							onClose={() => setSelectedTrade(null)}
						/>
					)}
				</div>
			)}

			{activeTab === "be_analysis" && (
				<div className="animate-fade-up">
					<PhantomAnalysisTab />
				</div>
			)}
		</div>
	</PageLayout>
);
}
