// src/pages/PortfolioBacktestViewer.tsx

import {
	AlertTriangle,
	BarChart,
	Briefcase,
	DollarSign,
	Hash,
	TrendingDown,
	TrendingUp,
} from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import { useParams } from "react-router-dom";
import { PageLayout } from "@/components/layout/PageLayout";
import { EquityCurveChart } from "@/components/research/EquityCurveChart";
import GenericPieChart from "@/components/research/GenericPieChart";
import PortfolioTradeHistoryTable from "@/components/research/PortfolioTradeHistoryTable";
import StrategyPerformanceTable from "@/components/research/StrategyPerformanceTable";
import SymbolPerformanceTable from "@/components/research/SymbolPerformanceTable"; // Import the new table
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePortfolioBacktestRun } from "@/lib/api";

const PortfolioKpiCard: React.FC<{
	title: string;
	value: string | number | undefined;
	icon?: React.ReactNode;
	description?: string;
	isLoading?: boolean;
}> = ({ title, value, icon, description, isLoading }) => {
	if (isLoading) {
		return (
			<Card>
				<CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
					<CardTitle className="text-sm font-medium">{title}</CardTitle>
					{icon || <BarChart className="h-4 w-4 text-muted-foreground" />}
				</CardHeader>
				<CardContent>
					<Skeleton className="h-8 w-3/4" />
					{description && <Skeleton className="h-4 w-1/2 mt-1" />}
				</CardContent>
			</Card>
		);
	}
	return (
		<Card>
			<CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
				<CardTitle className="text-sm font-medium">{title}</CardTitle>
				{icon || <BarChart className="h-4 w-4 text-muted-foreground" />}
			</CardHeader>
			<CardContent>
				<div className="text-2xl font-bold">{value ?? "N/A"}</div>
				{description && (
					<p className="text-xs text-muted-foreground">{description}</p>
				)}
			</CardContent>
		</Card>
	);
};

export default function PortfolioBacktestViewer() {
	const { runId } = useParams<{ runId: string }>();
	const { t } = useTranslation(["research", "common"]); // Load namespaces
	// --- Ensure runId is not undefined before passing to the hook ---
	const {
		data: runDetails,
		isLoading,
		isError,
		error,
	} = usePortfolioBacktestRun(runId || null);

	if (isLoading) {
		return (
			<PageLayout title={t("portfolioViewer.loading")} icon={Briefcase}>
				<div className="space-y-4">
					<div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
						{[...Array(4)].map((_, i) => (
							<PortfolioKpiCard
								key={i}
								title={t("common:loading")}
								value="..."
								isLoading
							/>
						))}
					</div>
					<Card>
						<CardHeader>
							<Skeleton className="h-6 w-1/4" />
						</CardHeader>
						<CardContent>
							<Skeleton className="h-64 w-full" />
						</CardContent>
					</Card>
					<Card>
						<CardHeader>
							<Skeleton className="h-6 w-1/4" />
						</CardHeader>
						<CardContent>
							<Skeleton className="h-48 w-full" />
						</CardContent>
					</Card>
				</div>
			</PageLayout>
		);
	}

	if (isError || !runDetails) {
		return (
			<PageLayout title={t("common:errorTitle")} icon={AlertTriangle}>
				<Alert variant="destructive">
					<AlertTriangle className="h-4 w-4" />
					<AlertTitle>{t("portfolioViewer.error")}</AlertTitle>
					<AlertDescription>
						{error?.message || t("common:errors.unknownError")}
					</AlertDescription>
				</Alert>
			</PageLayout>
		);
	}

	const kpis = runDetails.kpi_results_json;
	const pageTitle = t("portfolioViewer.pageTitle", { name: runDetails.name });
	const pageDescription = t("portfolioViewer.runId", { id: runDetails.run_id });

	return (
		<PageLayout
			title={pageTitle}
			icon={Briefcase}
			description={pageDescription}
		>
			{/* Top KPI Block */}
			<div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-6">
				<PortfolioKpiCard
					title={t("portfolioViewer.kpiTotalPnl")}
					value={
						kpis?.total_portfolio_pnl != null
							? `$${kpis.total_portfolio_pnl.toFixed(2)}`
							: t("common:na")
					}
					icon={<DollarSign className="h-4 w-4 text-muted-foreground" />}
					description={
						kpis?.total_portfolio_pnl == null
							? undefined
							: kpis.total_portfolio_pnl >= 0
								? t("portfolioViewer.kpiTotalPnlDescPositive")
								: t("portfolioViewer.kpiTotalPnlDescNegative")
					}
				/>
				<PortfolioKpiCard
					title={t("portfolioViewer.kpiSharpe")}
					value={
						kpis?.portfolio_sharpe_ratio != null
							? kpis.portfolio_sharpe_ratio.toFixed(3)
							: t("common:na")
					}
					icon={<TrendingUp className="h-4 w-4 text-muted-foreground" />}
					description={t("portfolioViewer.kpiSharpeDesc")}
				/>
				<PortfolioKpiCard
					title={t("portfolioViewer.kpiMaxDd")}
					value={
						kpis?.portfolio_max_drawdown != null
							? `${(kpis.portfolio_max_drawdown * 100).toFixed(2)}%`
							: t("common:na")
					}
					icon={<TrendingDown className="h-4 w-4 text-muted-foreground" />}
					description={t("portfolioViewer.kpiMaxDdDesc")}
				/>
				<PortfolioKpiCard
					title={t("portfolioViewer.kpiTotalTrades")}
					value={
						kpis?.total_trades ??
						(runDetails.trades ? runDetails.trades.length : t("common:na"))
					}
					icon={<Hash className="h-4 w-4 text-muted-foreground" />}
					description={t("portfolioViewer.kpiTotalTradesDesc")}
				/>
			</div>

			{/* Main Block with Equity Curve and Tabs */}
			<div className="grid grid-cols-1 gap-6">
				{/* Integrate EquityCurveChart */}
				<EquityCurveChart run={runDetails} isPortfolio={true} />

				<Tabs defaultValue="overview">
					<TabsList className="grid w-full grid-cols-4">
						<TabsTrigger value="overview">
							{t("portfolioViewer.tabOverview")}
						</TabsTrigger>
						<TabsTrigger value="trades">
							{t("portfolioViewer.tabTradeHistory")}
						</TabsTrigger>
						<TabsTrigger value="strategy_performance">
							{t("portfolioViewer.tabStrategyPerf")}
						</TabsTrigger>
						<TabsTrigger value="symbol_performance">
							{t("portfolioViewer.tabSymbolPerf")}
						</TabsTrigger>
					</TabsList>

					<TabsContent value="overview" className="pt-4">
						<Card>
							<CardHeader>
								<CardTitle>{t("portfolioViewer.tabOverview")}</CardTitle>
							</CardHeader>
							<CardContent className="space-y-4">
								{!runDetails.trades || runDetails.trades.length === 0 ? (
									<p className="text-center text-muted-foreground py-4">
										{t("portfolioViewer.overview.noTradeDataForCharts")}
									</p>
								) : (
									<div className="grid md:grid-cols-2 gap-6">
										<Card>
											<CardHeader>
												<CardTitle className="text-lg">
													{t("portfolioViewer.pnlByStrategy")}
												</CardTitle>
											</CardHeader>
											<CardContent>
												<GenericPieChart
													data={Object.entries(
														runDetails.trades.reduce(
															(acc, trade) => {
																const key =
																	trade.strategy_name || trade.strategy_id;
																acc[key] = (acc[key] || 0) + trade.pnl;
																return acc;
															},
															{} as Record<string, number>,
														),
													).map(([name, value]) => ({ name, value }))}
												/>
											</CardContent>
										</Card>
										<Card>
											<CardHeader>
												<CardTitle className="text-lg">
													{t("portfolioViewer.pnlBySymbol")}
												</CardTitle>
											</CardHeader>
											<CardContent>
												<GenericPieChart
													data={Object.entries(
														runDetails.trades.reduce(
															(acc, trade) => {
																acc[trade.symbol] =
																	(acc[trade.symbol] || 0) + trade.pnl;
																return acc;
															},
															{} as Record<string, number>,
														),
													).map(([name, value]) => ({ name, value }))}
												/>
											</CardContent>
										</Card>
									</div>
								)}
							</CardContent>
						</Card>
					</TabsContent>

					<TabsContent value="trades" className="pt-4">
						<Card>
							<CardHeader>
								<CardTitle>{t("portfolioViewer.tabTradeHistory")}</CardTitle>
							</CardHeader>
							<CardContent>
								{!runDetails.trades || runDetails.trades.length === 0 ? (
									<p className="text-center text-muted-foreground py-4">
										{t("portfolioViewer.trades.noTradesExecuted")}
									</p>
								) : (
									<PortfolioTradeHistoryTable trades={runDetails.trades} />
								)}
							</CardContent>
						</Card>
					</TabsContent>

					<TabsContent value="strategy_performance" className="pt-4">
						<Card>
							<CardHeader>
								<CardTitle>{t("portfolioViewer.tabStrategyPerf")}</CardTitle>
							</CardHeader>
							<CardContent>
								{!runDetails.strategy_performance_breakdown ||
								runDetails.strategy_performance_breakdown.length === 0 ? (
									<p className="text-center text-muted-foreground py-4">
										{t("portfolioViewer.strategyPerf.noData")}
									</p>
								) : (
									<StrategyPerformanceTable
										performanceData={runDetails.strategy_performance_breakdown}
									/>
								)}
							</CardContent>
						</Card>
					</TabsContent>

					<TabsContent value="symbol_performance" className="pt-4">
						<Card>
							<CardHeader>
								<CardTitle>{t("portfolioViewer.tabSymbolPerf")}</CardTitle>
							</CardHeader>
							<CardContent>
								{!runDetails.symbol_performance_breakdown ||
								runDetails.symbol_performance_breakdown.length === 0 ? (
									<p className="text-center text-muted-foreground py-4">
										{t("portfolioViewer.symbolPerf.noData")}
									</p>
								) : (
									<SymbolPerformanceTable
										performanceData={runDetails.symbol_performance_breakdown}
									/>
								)}
							</CardContent>
						</Card>
					</TabsContent>
				</Tabs>
			</div>
		</PageLayout>
	);
}
