import React, { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { format, subDays } from "date-fns";
import {
	RefreshCw,
	AlertCircle,
	CheckCircle2,
	Clock,
	Globe,
	Server,
	Users,
	Coins,
	ArrowLeft,
	ArrowUpRight,
	Search,
	ChevronLeft,
	ChevronRight,
	BarChart3,
	Activity,
	ShieldCheck,
	Zap,
	Sparkles,
	DollarSign,
} from "lucide-react";
import {
	ResponsiveContainer,
	LineChart,
	Line,
	BarChart,
	Bar,
	AreaChart,
	Area,
	XAxis,
	YAxis,
	Tooltip,
	CartesianGrid,
	Legend,
} from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/use-toast";

import {
	useGetMiningAnalytics,
	useGetMiningAnalyticsTrades,
	useTriggerMiningEpoch,
	useSystemStatus,
} from "@/lib/api";
import type { MiningAnalyticsTradeItem } from "@/types/api";
import { TradeDetailModal } from "@/components/mining/TradeDetailModal";

const CHART_COLORS = [
	"#10b981", // Emerald
	"#06b6d4", // Cyan
	"#8b5cf6", // Violet
	"#f59e0b", // Amber
	"#ec4899", // Pink
	"#3b82f6", // Blue
	"#6366f1", // Indigo
];

interface AnalyticsTooltipPayloadItem {
	name?: string;
	value?: number | string;
	color?: string;
	fill?: string;
	stroke?: string;
	dataKey?: string;
}

interface AnalyticsChartTooltipProps {
	active?: boolean;
	payload?: AnalyticsTooltipPayloadItem[];
	label?: string;
	valueFormatter?: (val: number, name?: string) => string;
}

const AnalyticsChartTooltip: React.FC<AnalyticsChartTooltipProps> = ({
	active,
	payload,
	label,
	valueFormatter,
}) => {
	if (!active || !payload || !payload.length) return null;

	return (
		<div className="bg-slate-900/95 border border-white/15 rounded-xl p-3 shadow-2xl backdrop-blur-xl min-w-[200px] text-xs">
			{label && (
				<div className="font-semibold text-slate-300 pb-2 mb-2 border-b border-white/10 font-mono">
					{label}
				</div>
			)}
			<div className="space-y-1.5">
				{payload.map((entry, index) => {
					const dotColor = entry.color || entry.stroke || entry.fill || "#3b82f6";
					const numVal = Number(entry.value || 0);
					const formattedVal = valueFormatter
						? valueFormatter(numVal, entry.name)
						: numVal.toLocaleString();

					return (
						<div
							key={`${entry.name || index}-${index}`}
							className="flex items-center justify-between gap-4 py-0.5"
						>
							<div className="flex items-center gap-2">
								<span
									className="w-2.5 h-2.5 rounded-full inline-block flex-shrink-0 shadow-sm ring-1 ring-white/20"
									style={{ backgroundColor: dotColor }}
								/>
								<span className="text-slate-300 font-medium">{entry.name}</span>
							</div>
							<span className="font-mono font-bold text-foreground">
								{formattedVal}
							</span>
						</div>
					);
				})}
			</div>
		</div>
	);
};

export const AdminMiningAnalytics: React.FC = () => {
	const { t } = useTranslation("mining");
	const { toast } = useToast();
	const { data: systemStatus } = useSystemStatus();
	const isCentralHub = Boolean(systemStatus?.isCentralHub);

	// Date Range State
	const [rangePreset, setRangePreset] = useState<"7d" | "14d" | "30d" | "90d" | "all" | "custom">("30d");
	const [customDateFrom, setCustomDateFrom] = useState<string>(() =>
		format(subDays(new Date(), 30), "yyyy-MM-dd")
	);
	const [customDateTo, setCustomDateTo] = useState<string>(() =>
		format(new Date(), "yyyy-MM-dd")
	);

	const activeDates = useMemo(() => {
		const today = new Date();
		const todayStr = format(today, "yyyy-MM-dd");
		if (rangePreset === "7d") return { dateFrom: format(subDays(today, 7), "yyyy-MM-dd"), dateTo: todayStr };
		if (rangePreset === "14d") return { dateFrom: format(subDays(today, 14), "yyyy-MM-dd"), dateTo: todayStr };
		if (rangePreset === "30d") return { dateFrom: format(subDays(today, 30), "yyyy-MM-dd"), dateTo: todayStr };
		if (rangePreset === "90d") return { dateFrom: format(subDays(today, 90), "yyyy-MM-dd"), dateTo: todayStr };
		if (rangePreset === "all") return { dateFrom: "2024-01-01", dateTo: todayStr };
		return { dateFrom: customDateFrom, dateTo: customDateTo };
	}, [rangePreset, customDateFrom, customDateTo]);

	// Trades Filter State
	const [page, setPage] = useState(1);
	const [pageSize, setPageSize] = useState(25);
	const [exchangeFilter, setExchangeFilter] = useState("ALL");
	const [statusFilter, setStatusFilter] = useState("ALL");
	const [searchQuery, setSearchQuery] = useState("");
	const [selectedNodeUuid, setSelectedNodeUuid] = useState<string | undefined>(undefined);

	// Selected Trade for Modal
	const [selectedTrade, setSelectedTrade] = useState<MiningAnalyticsTradeItem | null>(null);

	// API Queries
	const {
		data: analyticsData,
		isLoading: isLoadingSummary,
		isFetching: isFetchingSummary,
		refetch: refetchSummary,
	} = useGetMiningAnalytics(activeDates, true);

	const {
		data: tradesData,
		isLoading: isLoadingTrades,
		isFetching: isFetchingTrades,
		refetch: refetchTrades,
	} = useGetMiningAnalyticsTrades(
		{
			page,
			limit: pageSize,
			dateFrom: activeDates.dateFrom,
			dateTo: activeDates.dateTo,
			exchange: exchangeFilter,
			statusFilter,
			search: searchQuery,
			nodeUuid: selectedNodeUuid,
		},
		true
	);

	// Reprocess Epoch Mutation
	const { mutate: reprocessEpoch, isPending: isReprocessing } = useTriggerMiningEpoch();

	const handleReprocessEpoch = (epochDate: string) => {
		reprocessEpoch(epochDate, {
			onSuccess: () => {
				toast({
					title: "Epoch Reprocessed",
					description: t("analyticsEpochReprocessSuccess", { date: epochDate }),
				});
				refetchSummary();
				refetchTrades();
			},
			onError: (err) => {
				toast({
					title: "Reprocess Failed",
					description: t("analyticsEpochReprocessError", { error: err.message }),
					variant: "destructive",
				});
			},
		});
	};

	const handleRefresh = () => {
		refetchSummary();
		refetchTrades();
		toast({
			title: "Refreshed",
			description: "Analytics data updated to latest state",
			duration: 2000,
		});
	};

	// Collect dynamic exchange keys for the volume chart
	const chartExchanges = useMemo(() => {
		if (!analyticsData?.dailyTrends) return [];
		const set = new Set<string>();
		analyticsData.dailyTrends.forEach((d) => {
			Object.keys(d.volumeByExchange || {}).forEach((k) => set.add(k));
		});
		return Array.from(set);
	}, [analyticsData]);

	// Reconciliation Summary totals
	const reconTotals = useMemo(() => {
		if (!analyticsData?.exchangeBreakdown) return { totalRebate: 0, verifiedVolume: 0, totalVolume: 0 };
		const totalRebate = analyticsData.exchangeBreakdown.reduce((sum, e) => sum + (e.verifiedRebateUsdt || 0), 0);
		const verifiedVolume = analyticsData.exchangeBreakdown.reduce((sum, e) => sum + (e.verifiedVolumeUsdt || 0), 0);
		const totalVolume = analyticsData.exchangeBreakdown.reduce((sum, e) => sum + (e.totalVolumeUsdt || 0), 0);
		return { totalRebate, verifiedVolume, totalVolume };
	}, [analyticsData]);

	return (
		<div className="space-y-8 pb-16">
			{/* Page Header */}
			<div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 border-b border-border/40 pb-6">
				<div>
					<div className="flex items-center gap-3">
						<div className="p-2.5 rounded-xl bg-gradient-to-br from-primary/20 via-primary/10 to-transparent border border-primary/30 text-primary shadow-lg shadow-primary/10">
							<BarChart3 className="w-6 h-6" />
						</div>
						<div>
							<h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-foreground flex items-center gap-2.5">
								{t("analyticsTitle")}
								{isCentralHub && (
									<Badge variant="outline" className="text-[11px] font-mono border-primary/40 text-primary bg-primary/10">
										HUB AUTHORITY
									</Badge>
								)}
							</h1>
							<p className="text-sm text-muted-foreground mt-0.5 max-w-2xl">
								{t("analyticsSubtitle")}
							</p>
						</div>
					</div>
				</div>

				<div className="flex flex-wrap items-center gap-2.5">
					<Button asChild variant="outline" size="sm" className="gap-2">
						<Link to="/admin/mining">
							<ArrowLeft className="w-4 h-4" />
							<span>{t("analyticsBackToSettings")}</span>
						</Link>
					</Button>

					{/* Date Range Preset Selector */}
					<div className="flex items-center bg-muted/40 p-1 rounded-xl border border-border/50">
						{(["7d", "14d", "30d", "90d", "all"] as const).map((preset) => (
							<Button
								key={preset}
								variant={rangePreset === preset ? "secondary" : "ghost"}
								size="sm"
								className={`h-7 px-2.5 text-xs font-medium rounded-lg ${
									rangePreset === preset ? "font-bold shadow-sm" : "text-muted-foreground hover:text-foreground"
								}`}
								onClick={() => {
									setRangePreset(preset);
									setPage(1);
								}}
							>
								{preset.toUpperCase()}
							</Button>
						))}
					</div>

					<Button
						variant="outline"
						size="sm"
						onClick={handleRefresh}
						disabled={isFetchingSummary || isFetchingTrades}
						className="gap-1.5"
					>
						<RefreshCw className={`w-4 h-4 ${isFetchingSummary || isFetchingTrades ? "animate-spin" : ""}`} />
						<span className="hidden sm:inline">{t("analyticsRefresh")}</span>
					</Button>
				</div>
			</div>

			{/* Custom Date Range Picker (visible when custom range or for fine-tuning) */}
			{rangePreset === "custom" && (
				<Card className="border border-border/60 bg-card/60 backdrop-blur">
					<CardContent className="pt-4 pb-4 flex flex-wrap items-center gap-4">
						<div className="flex items-center gap-2 text-xs">
							<span className="text-muted-foreground font-medium">{t("analyticsFilterFrom")}:</span>
							<Input
								type="date"
								value={customDateFrom}
								onChange={(e) => setCustomDateFrom(e.target.value)}
								className="h-8 w-40 font-mono text-xs"
							/>
						</div>
						<div className="flex items-center gap-2 text-xs">
							<span className="text-muted-foreground font-medium">{t("analyticsFilterTo")}:</span>
							<Input
								type="date"
								value={customDateTo}
								onChange={(e) => setCustomDateTo(e.target.value)}
								className="h-8 w-40 font-mono text-xs"
							/>
						</div>
					</CardContent>
				</Card>
			)}

			{/* ROW 1: Network Scale KPIs */}
			<div className="space-y-3">
				<div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
					<Server className="w-3.5 h-3.5 text-primary" />
					<span>Network Infrastructure & Scope</span>
				</div>
				<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
					{/* KPI 1: Total Users */}
					<Card className="border border-border/60 bg-gradient-to-br from-card/90 via-card/60 to-card/30 backdrop-blur-md shadow-md hover:border-primary/40 transition-colors">
						<CardContent className="p-5 flex items-center justify-between">
							<div className="space-y-1">
								<p className="text-xs font-medium text-muted-foreground">{t("analyticsKpiTotalUsers")}</p>
								<div className="text-2xl font-black font-mono tracking-tight text-foreground">
									{isLoadingSummary ? <Skeleton className="h-8 w-20" /> : analyticsData?.totalUsers.toLocaleString() ?? "0"}
								</div>
								<p className="text-[11px] text-muted-foreground/80">{t("analyticsKpiTotalUsersDesc")}</p>
							</div>
							<div className="p-3 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400">
								<Users className="w-5 h-5" />
							</div>
						</CardContent>
					</Card>

					{/* KPI 2: Total Nodes */}
					<Card className="border border-border/60 bg-gradient-to-br from-card/90 via-card/60 to-card/30 backdrop-blur-md shadow-md hover:border-primary/40 transition-colors">
						<CardContent className="p-5 flex items-center justify-between">
							<div className="space-y-1">
								<p className="text-xs font-medium text-muted-foreground">{t("analyticsKpiTotalNodes")}</p>
								<div className="text-2xl font-black font-mono tracking-tight text-foreground flex items-center gap-2">
									{isLoadingSummary ? (
										<Skeleton className="h-8 w-20" />
									) : (
										<>
											<span>{analyticsData?.totalNodes ?? 0}</span>
											<span className="text-xs font-medium text-emerald-400 font-sans">
												({analyticsData?.nodeBreakdown.filter((n) => n.isOnline).length ?? 0} online)
											</span>
										</>
									)}
								</div>
								<p className="text-[11px] text-muted-foreground/80">{t("analyticsKpiTotalNodesDesc")}</p>
							</div>
							<div className="p-3 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
								<Server className="w-5 h-5" />
							</div>
						</CardContent>
					</Card>

					{/* KPI 3: Active Exchanges */}
					<Card className="border border-border/60 bg-gradient-to-br from-card/90 via-card/60 to-card/30 backdrop-blur-md shadow-md hover:border-primary/40 transition-colors">
						<CardContent className="p-5 flex items-center justify-between">
							<div className="space-y-1">
								<p className="text-xs font-medium text-muted-foreground">{t("analyticsKpiActiveExchanges")}</p>
								<div className="text-2xl font-black font-mono tracking-tight text-foreground">
									{isLoadingSummary ? <Skeleton className="h-8 w-16" /> : analyticsData?.activeExchanges.length ?? 0}
								</div>
								<p className="text-[11px] text-muted-foreground/80">{t("analyticsKpiActiveExchangesDesc")}</p>
							</div>
							<div className="p-3 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400">
								<Globe className="w-5 h-5" />
							</div>
						</CardContent>
					</Card>

					{/* KPI 4: Mining System Status */}
					<Card className="border border-border/60 bg-gradient-to-br from-card/90 via-card/60 to-card/30 backdrop-blur-md shadow-md hover:border-primary/40 transition-colors">
						<CardContent className="p-5 flex items-center justify-between">
							<div className="space-y-1">
								<p className="text-xs font-medium text-muted-foreground">{t("analyticsKpiSystemStatus")}</p>
								<div className="text-lg font-bold font-mono tracking-tight text-foreground flex items-center gap-2">
									{isLoadingSummary ? (
										<Skeleton className="h-7 w-28" />
									) : analyticsData?.isMiningEnabled ? (
										<span className="flex items-center gap-1.5 text-emerald-400">
											<span className="relative flex h-2.5 w-2.5">
												<span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
												<span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
											</span>
											{t("analyticsKpiSystemStatusActive")}
										</span>
									) : (
										<span className="text-amber-400 flex items-center gap-1.5">
											<Clock className="w-4 h-4" />
											{t("analyticsKpiSystemStatusPaused")}
										</span>
									)}
								</div>
								<p className="text-[11px] text-muted-foreground/80">Federation Consensus & Verification</p>
							</div>
							<div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
								<ShieldCheck className="w-5 h-5" />
							</div>
						</CardContent>
					</Card>
				</div>
			</div>

			{/* ROW 2: Trade Mining Performance KPIs */}
			<div className="space-y-3">
				<div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
					<Coins className="w-3.5 h-3.5 text-emerald-400" />
					<span>Trade Mining & Settlement Performance</span>
				</div>
				<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
					{/* KPI 5: Total Trades */}
					<Card className="border border-border/60 bg-gradient-to-br from-card/90 via-card/60 to-card/30 backdrop-blur-md shadow-md hover:border-primary/40 transition-colors">
						<CardContent className="p-5 flex items-center justify-between">
							<div className="space-y-1">
								<p className="text-xs font-medium text-muted-foreground">{t("analyticsKpiTotalTrades")}</p>
								<div className="text-2xl font-black font-mono tracking-tight text-foreground">
									{isLoadingSummary ? <Skeleton className="h-8 w-24" /> : analyticsData?.totalTrades.toLocaleString() ?? "0"}
								</div>
								<p className="text-[11px] text-muted-foreground/80">{t("analyticsKpiTotalTradesDesc")}</p>
							</div>
							<div className="p-3 rounded-xl bg-primary/10 border border-primary/20 text-primary">
								<Activity className="w-5 h-5" />
							</div>
						</CardContent>
					</Card>

					{/* KPI 6: Verification Rate */}
					<Card className="border border-border/60 bg-gradient-to-br from-card/90 via-card/60 to-card/30 backdrop-blur-md shadow-md hover:border-primary/40 transition-colors">
						<CardContent className="p-5 flex items-center justify-between">
							<div className="space-y-1">
								<p className="text-xs font-medium text-muted-foreground">{t("analyticsKpiVerificationRate")}</p>
								<div className="text-2xl font-black font-mono tracking-tight text-emerald-500">
									{isLoadingSummary ? <Skeleton className="h-8 w-20" /> : `${analyticsData?.verificationRate ?? 0}%`}
								</div>
								<p className="text-[11px] text-muted-foreground/80">
									{analyticsData?.verifiedCount.toLocaleString() ?? 0} {t("analyticsKpiVerificationRateDesc").toLowerCase()}
								</p>
							</div>
							<div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-500">
								<CheckCircle2 className="w-5 h-5" />
							</div>
						</CardContent>
					</Card>

					{/* KPI 7: Pending & Errors */}
					<Card className="border border-border/60 bg-gradient-to-br from-card/90 via-card/60 to-card/30 backdrop-blur-md shadow-md hover:border-primary/40 transition-colors">
						<CardContent className="p-5 flex items-center justify-between">
							<div className="space-y-1">
								<p className="text-xs font-medium text-muted-foreground">{t("analyticsKpiPendingErrors")}</p>
								<div className="text-2xl font-black font-mono tracking-tight text-foreground flex items-center gap-2">
									{isLoadingSummary ? (
										<Skeleton className="h-8 w-24" />
									) : (
										<>
											<span className="text-amber-400">{analyticsData?.pendingCount ?? 0}</span>
											<span className="text-muted-foreground font-light text-base">/</span>
											<span className="text-rose-400">{analyticsData?.errorCount ?? 0}</span>
										</>
									)}
								</div>
								<p className="text-[11px] text-muted-foreground/80">
									{t("analyticsKpiPendingErrorsDesc", {
										pending: analyticsData?.pendingCount ?? 0,
										errors: analyticsData?.errorCount ?? 0,
									})}
								</p>
							</div>
							<div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400">
								<AlertCircle className="w-5 h-5" />
							</div>
						</CardContent>
					</Card>

					{/* KPI 8: Total Distributed & Volume */}
					<Card className="border border-border/60 bg-gradient-to-br from-card/90 via-card/60 to-card/30 backdrop-blur-md shadow-md hover:border-primary/40 transition-colors">
						<CardContent className="p-5 flex items-center justify-between">
							<div className="space-y-1">
								<p className="text-xs font-medium text-muted-foreground">{t("analyticsKpiDistributedTokens")}</p>
								<div className="text-2xl font-black font-mono tracking-tight text-foreground flex items-center gap-1.5">
									{isLoadingSummary ? (
										<Skeleton className="h-8 w-28" />
									) : (
										<>
											<Zap className="w-5 h-5 text-amber-400 flex-shrink-0" />
											<span>{Math.round(analyticsData?.totalDistributedDepth ?? 0).toLocaleString()}</span>
										</>
									)}
								</div>
								<p className="text-[11px] text-muted-foreground/80 font-mono">
									${(analyticsData?.totalVerifiedVolumeUsdt ?? 0).toLocaleString()} verified volume
								</p>
							</div>
							<div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400">
								<Coins className="w-5 h-5" />
							</div>
						</CardContent>
					</Card>
				</div>
			</div>

			{/* RECHARTS TREND CHARTS */}
			<div className="space-y-4">
				<div className="flex items-center justify-between">
					<div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
						<BarChart3 className="w-3.5 h-3.5 text-primary" />
						<span>{t("analyticsTrendsTitle")}</span>
					</div>
				</div>

				<div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
					{/* Chart 1: Daily Volume by Exchange */}
					<Card className="border border-border/60 bg-card/70 backdrop-blur-md shadow-lg">
						<CardHeader className="pb-2">
							<CardTitle className="text-base font-bold flex items-center gap-2">
								<Activity className="w-4 h-4 text-emerald-400" />
								{t("analyticsDailyVolumeChartTitle")}
							</CardTitle>
							<CardDescription className="text-xs">
								Aggregated daily USDT trade volume across connected brokers
							</CardDescription>
						</CardHeader>
						<CardContent className="pt-2">
							<div className="h-72 w-full">
								{isLoadingSummary ? (
									<Skeleton className="h-full w-full" />
								) : analyticsData?.dailyTrends && analyticsData.dailyTrends.length > 0 ? (
									<ResponsiveContainer width="100%" height="100%">
										<LineChart data={analyticsData.dailyTrends}>
											<CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
											<XAxis
												dataKey="date"
												stroke="rgba(255,255,255,0.4)"
												tick={{ fontSize: 11 }}
												tickFormatter={(val) => val.slice(5)}
											/>
											<YAxis
												stroke="rgba(255,255,255,0.4)"
												tick={{ fontSize: 11 }}
												tickFormatter={(val) => `$${(val / 1000).toFixed(0)}k`}
											/>
											<Tooltip content={<AnalyticsChartTooltip valueFormatter={(val) => `$${val.toLocaleString()}`} />} />
											<Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
											{chartExchanges.map((exKey, idx) => (
												<Line
													key={exKey}
													type="monotone"
													dataKey={`volumeByExchange.${exKey}`}
													name={exKey}
													stroke={CHART_COLORS[idx % CHART_COLORS.length]}
													strokeWidth={2}
													dot={false}
													activeDot={{ r: 5 }}
												/>
											))}
											<Line
												type="monotone"
												dataKey="totalVolume"
												name="Total Volume"
												stroke="#ffffff"
												strokeWidth={2}
												strokeDasharray="4 4"
												dot={false}
											/>
										</LineChart>
									</ResponsiveContainer>
								) : (
									<div className="h-full flex items-center justify-center text-xs text-muted-foreground">
										{t("analyticsNoData")}
									</div>
								)}
							</div>
						</CardContent>
					</Card>

					{/* Chart 2: Daily Emission vs Distributed Rewards */}
					<Card className="border border-border/60 bg-card/70 backdrop-blur-md shadow-lg">
						<CardHeader className="pb-2">
							<CardTitle className="text-base font-bold flex items-center gap-2">
								<Coins className="w-4 h-4 text-amber-400" />
								{t("analyticsEmissionChartTitle")}
							</CardTitle>
							<CardDescription className="text-xs">
								Daily protocol cap (halving curve) vs actual distributed $DEPTH tokens
							</CardDescription>
						</CardHeader>
						<CardContent className="pt-2">
							<div className="h-72 w-full">
								{isLoadingSummary ? (
									<Skeleton className="h-full w-full" />
								) : analyticsData?.epochTrends && analyticsData.epochTrends.length > 0 ? (
									<ResponsiveContainer width="100%" height="100%">
										<BarChart data={analyticsData.epochTrends}>
											<CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
											<XAxis
												dataKey="epochDate"
												stroke="rgba(255,255,255,0.4)"
												tick={{ fontSize: 11 }}
												tickFormatter={(val) => val.slice(5)}
											/>
											<YAxis
												stroke="rgba(255,255,255,0.4)"
												tick={{ fontSize: 11 }}
												tickFormatter={(val) => `${(val / 1000).toFixed(0)}k`}
											/>
											<Tooltip content={<AnalyticsChartTooltip valueFormatter={(val) => `${val.toLocaleString()} $DEPTH`} />} />
											<Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
											<Bar dataKey="dailyEmission" name="Max Emission Cap" fill="#475569" radius={[4, 4, 0, 0]} />
											<Bar dataKey="totalDistributed" name="Distributed Rewards" fill="#10b981" radius={[4, 4, 0, 0]} />
										</BarChart>
									</ResponsiveContainer>
								) : (
									<div className="h-full flex items-center justify-center text-xs text-muted-foreground">
										{t("analyticsNoData")}
									</div>
								)}
							</div>
						</CardContent>
					</Card>
				</div>

				{/* Chart 3: Verification Funnel / Status Over Time */}
				<Card className="border border-border/60 bg-card/70 backdrop-blur-md shadow-lg">
					<CardHeader className="pb-2">
						<CardTitle className="text-base font-bold flex items-center gap-2">
							<ShieldCheck className="w-4 h-4 text-cyan-400" />
							{t("analyticsVerificationTrendTitle")}
						</CardTitle>
						<CardDescription className="text-xs">
							Daily volume of confirmed, pending, and flagged trades across the network
						</CardDescription>
					</CardHeader>
					<CardContent className="pt-2">
						<div className="h-64 w-full">
							{isLoadingSummary ? (
								<Skeleton className="h-full w-full" />
							) : analyticsData?.dailyTrends && analyticsData.dailyTrends.length > 0 ? (
								<ResponsiveContainer width="100%" height="100%">
									<AreaChart data={analyticsData.dailyTrends}>
										<CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
										<XAxis
											dataKey="date"
											stroke="rgba(255,255,255,0.4)"
											tick={{ fontSize: 11 }}
											tickFormatter={(val) => val.slice(5)}
										/>
										<YAxis stroke="rgba(255,255,255,0.4)" tick={{ fontSize: 11 }} />
										<Tooltip content={<AnalyticsChartTooltip valueFormatter={(val) => `${val.toLocaleString()} trades`} />} />
										<Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
										<Area
											type="monotone"
											dataKey="verifiedCount"
											name="Verified"
											stackId="1"
											stroke="#10b981"
											fill="#10b981"
											fillOpacity={0.3}
										/>
										<Area
											type="monotone"
											dataKey="pendingCount"
											name="Pending"
											stackId="1"
											stroke="#f59e0b"
											fill="#f59e0b"
											fillOpacity={0.3}
										/>
										<Area
											type="monotone"
											dataKey="errorCount"
											name="Errors"
											stackId="1"
											stroke="#ef4444"
											fill="#ef4444"
											fillOpacity={0.3}
										/>
									</AreaChart>
								</ResponsiveContainer>
							) : (
								<div className="h-full flex items-center justify-center text-xs text-muted-foreground">
									{t("analyticsNoData")}
								</div>
							)}
						</div>
					</CardContent>
				</Card>
			</div>

			{/* EXCHANGE BREAKDOWN & RECONCILIATION */}
			<div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
				{/* Card 1: Exchange Breakdown & Auto-Discovery */}
				<Card className="border border-border/60 bg-card/70 backdrop-blur-md shadow-lg">
					<CardHeader className="pb-3">
						<div className="flex items-center justify-between">
							<div>
								<CardTitle className="text-base font-bold flex items-center gap-2">
									<Globe className="w-4 h-4 text-purple-400" />
									{t("analyticsExchangesTitle")}
								</CardTitle>
								<CardDescription className="text-xs">
									{t("analyticsExchangesSubtitle")}
								</CardDescription>
							</div>
						</div>
					</CardHeader>
					<CardContent className="p-0">
						<Table>
							<TableHeader>
								<TableRow className="border-border/40 hover:bg-transparent">
									<TableHead className="text-xs">{t("analyticsExchangeCol")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsExchangeTrades")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsExchangeVerified")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsExchangePending")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsExchangeErrors")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsExchangeVolume")}</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{isLoadingSummary ? (
									Array.from({ length: 3 }).map((_, i) => (
										<TableRow key={i}>
											<TableCell colSpan={6}><Skeleton className="h-6 w-full" /></TableCell>
										</TableRow>
									))
								) : analyticsData?.exchangeBreakdown && analyticsData.exchangeBreakdown.length > 0 ? (
									analyticsData.exchangeBreakdown.map((ex) => (
										<TableRow key={ex.exchangeId} className="border-border/30 hover:bg-muted/30">
											<TableCell className="font-mono text-xs font-semibold flex items-center gap-2">
												<span>{ex.exchangeId}</span>
												{ex.isNew && (
													<Badge className="bg-primary/20 text-primary border-primary/40 text-[10px] px-1.5 py-0 h-4 font-bold flex items-center gap-0.5">
														<Sparkles className="w-2.5 h-2.5" />
														{t("analyticsExchangeNewBadge")}
													</Badge>
												)}
											</TableCell>
											<TableCell className="font-mono text-xs text-right">{ex.tradeCount.toLocaleString()}</TableCell>
											<TableCell className="font-mono text-xs text-right text-emerald-400">{ex.verifiedCount.toLocaleString()}</TableCell>
											<TableCell className="font-mono text-xs text-right text-amber-400">{ex.pendingCount.toLocaleString()}</TableCell>
											<TableCell className="font-mono text-xs text-right text-rose-400">{ex.errorCount.toLocaleString()}</TableCell>
											<TableCell className="font-mono text-xs text-right font-medium text-foreground">
												${ex.totalVolumeUsdt.toLocaleString()}
											</TableCell>
										</TableRow>
									))
								) : (
									<TableRow>
										<TableCell colSpan={6} className="text-center text-xs text-muted-foreground py-6">
											{t("analyticsNoData")}
										</TableCell>
									</TableRow>
								)}
							</TableBody>
						</Table>
					</CardContent>
				</Card>

				{/* Card 2: Broker Rebate Reconciliation */}
				<Card className="border border-border/60 bg-card/70 backdrop-blur-md shadow-lg">
					<CardHeader className="pb-3">
						<div className="flex items-center justify-between">
							<div>
								<CardTitle className="text-base font-bold flex items-center gap-2">
									<DollarSign className="w-4 h-4 text-emerald-400" />
									{t("analyticsReconciliationTitle")}
								</CardTitle>
								<CardDescription className="text-xs">
									{t("analyticsReconciliationSubtitle")}
								</CardDescription>
							</div>
							{reconTotals.totalRebate > 0 && (
								<Badge variant="outline" className="text-xs font-mono font-bold text-emerald-400 border-emerald-500/30 bg-emerald-500/10">
									{t("analyticsReconTotalRealRebate")}: ${reconTotals.totalRebate.toFixed(2)} USDT
								</Badge>
							)}
						</div>
					</CardHeader>
					<CardContent className="p-0">
						<Table>
							<TableHeader>
								<TableRow className="border-border/40 hover:bg-transparent">
									<TableHead className="text-xs">{t("analyticsExchangeCol")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsReconClaimedVolume")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsReconVerifiedVolume")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsReconDelta")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsReconVerifiedRebate")}</TableHead>
									<TableHead className="text-xs text-center">{t("analyticsReconStatus")}</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{isLoadingSummary ? (
									Array.from({ length: 3 }).map((_, i) => (
										<TableRow key={i}>
											<TableCell colSpan={6}><Skeleton className="h-6 w-full" /></TableCell>
										</TableRow>
									))
								) : analyticsData?.exchangeBreakdown && analyticsData.exchangeBreakdown.length > 0 ? (
									analyticsData.exchangeBreakdown.map((ex) => {
										const claimedVol = ex.totalVolumeUsdt || 0;
										const verifiedVol = ex.verifiedVolumeUsdt || 0;
										const realRebate = ex.verifiedRebateUsdt || 0;
										const diff = claimedVol > 0 && ex.verifiedCount > 0
											? ((verifiedVol - claimedVol) / claimedVol) * 100
											: 0;
										const isGapSignificant = ex.verifiedCount > 0 && Math.abs(diff) > 5;

										return (
											<TableRow key={ex.exchangeId} className="border-border/30 hover:bg-muted/30">
												<TableCell className="font-mono text-xs font-semibold">{ex.exchangeId}</TableCell>
												<TableCell className="font-mono text-xs text-right text-muted-foreground">
													${claimedVol.toLocaleString()}
												</TableCell>
												<TableCell className="font-mono text-xs text-right font-medium text-foreground">
													${verifiedVol.toLocaleString()}
												</TableCell>
												<TableCell className={`font-mono text-xs text-right ${isGapSignificant ? "text-rose-400 font-bold" : "text-muted-foreground"}`}>
													{ex.verifiedCount > 0 ? `${diff >= 0 ? "+" : ""}${diff.toFixed(1)}%` : "—"}
												</TableCell>
												<TableCell className="font-mono text-xs text-right font-bold text-emerald-400">
													${realRebate.toFixed(2)}
												</TableCell>
												<TableCell className="text-center">
													{ex.pendingCount > 0 ? (
														<Badge variant="outline" className="border-amber-500/40 text-amber-400 bg-amber-500/10 text-[10px] px-1.5 py-0">
															⏳ {t("analyticsReconPending")} ({ex.pendingCount})
														</Badge>
													) : isGapSignificant ? (
														<Badge variant="outline" className="border-rose-500/40 text-rose-400 bg-rose-500/10 text-[10px] px-1.5 py-0">
															⚠️ {t("analyticsReconWarning")}
														</Badge>
													) : (
														<Badge variant="outline" className="border-emerald-500/40 text-emerald-400 bg-emerald-500/10 text-[10px] px-1.5 py-0">
															✓ {t("analyticsReconMatched")}
														</Badge>
													)}
												</TableCell>
											</TableRow>
										);
									})
								) : (
									<TableRow>
										<TableCell colSpan={6} className="text-center text-xs text-muted-foreground py-6">
											{t("analyticsNoData")}
										</TableCell>
									</TableRow>
								)}
							</TableBody>
						</Table>
					</CardContent>
				</Card>
			</div>

			{/* NODE NETWORK BREAKDOWN TABLE */}
			<Card className="border border-border/60 bg-card/70 backdrop-blur-md shadow-lg">
				<CardHeader className="pb-3">
					<div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
						<div>
							<CardTitle className="text-base font-bold flex items-center gap-2">
								<Server className="w-4 h-4 text-cyan-400" />
								{t("analyticsNodesTitle")}
							</CardTitle>
							<CardDescription className="text-xs">
								{t("analyticsNodesSubtitle")}
							</CardDescription>
						</div>
						{selectedNodeUuid && (
							<Button
								variant="ghost"
								size="sm"
								className="text-xs text-primary self-start"
								onClick={() => setSelectedNodeUuid(undefined)}
							>
								Clear Node Filter ({selectedNodeUuid.slice(0, 8)}...)
							</Button>
						)}
					</div>
				</CardHeader>
				<CardContent className="p-0">
					<div className="overflow-x-auto">
						<Table>
							<TableHeader>
								<TableRow className="border-border/40 hover:bg-transparent">
									<TableHead className="text-xs">{t("analyticsNodeCol")}</TableHead>
									<TableHead className="text-xs">{t("analyticsNodeUuid")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsNodeTrades")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsNodeVerified")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsNodeErrors")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsNodeVolume")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsNodeMined")}</TableHead>
									<TableHead className="text-xs">{t("analyticsNodeLastPing")}</TableHead>
									<TableHead className="text-xs text-center">Status</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{isLoadingSummary ? (
									Array.from({ length: 3 }).map((_, i) => (
										<TableRow key={i}>
											<TableCell colSpan={9}><Skeleton className="h-6 w-full" /></TableCell>
										</TableRow>
									))
								) : analyticsData?.nodeBreakdown && analyticsData.nodeBreakdown.length > 0 ? (
									analyticsData.nodeBreakdown.map((node) => (
										<TableRow
											key={node.nodeUuid}
											className={`border-border/30 hover:bg-muted/30 cursor-pointer ${
												selectedNodeUuid === node.nodeUuid ? "bg-primary/10 border-l-2 border-l-primary" : ""
											}`}
											onClick={() => {
												setSelectedNodeUuid(selectedNodeUuid === node.nodeUuid ? undefined : node.nodeUuid);
												setPage(1);
											}}
										>
											<TableCell className="font-semibold text-xs text-foreground flex items-center gap-1.5">
												<span>{node.name}</span>
											</TableCell>
											<TableCell className="font-mono text-xs text-muted-foreground">
												{node.nodeUuid.slice(0, 8)}...
											</TableCell>
											<TableCell className="font-mono text-xs text-right">{node.tradeCount.toLocaleString()}</TableCell>
											<TableCell className="font-mono text-xs text-right text-emerald-400">{node.verifiedCount.toLocaleString()}</TableCell>
											<TableCell className="font-mono text-xs text-right text-rose-400">{node.errorCount.toLocaleString()}</TableCell>
											<TableCell className="font-mono text-xs text-right font-medium">${node.totalVolumeUsdt.toLocaleString()}</TableCell>
											<TableCell className="font-mono text-xs text-right text-primary font-bold">
												{node.totalMinedDepth.toLocaleString()} $DEPTH
											</TableCell>
											<TableCell className="font-mono text-xs text-muted-foreground">
												{node.lastPing ? format(new Date(node.lastPing), "yyyy-MM-dd HH:mm") : "—"}
											</TableCell>
											<TableCell className="text-center">
												{node.isOnline ? (
													<Badge variant="outline" className="border-emerald-500/40 text-emerald-400 bg-emerald-500/10 text-[10px] px-2 py-0">
														🟢 {t("analyticsNodeOnline")}
													</Badge>
												) : (
													<Badge variant="outline" className="border-border/50 text-muted-foreground bg-muted/20 text-[10px] px-2 py-0">
														⚪ {t("analyticsNodeOffline")}
													</Badge>
												)}
											</TableCell>
										</TableRow>
									))
								) : (
									<TableRow>
										<TableCell colSpan={9} className="text-center text-xs text-muted-foreground py-6">
											{t("analyticsNoData")}
										</TableCell>
									</TableRow>
								)}
							</TableBody>
						</Table>
					</div>
				</CardContent>
			</Card>

			{/* EPOCH HISTORY TABLE */}
			<Card className="border border-border/60 bg-card/70 backdrop-blur-md shadow-lg">
				<CardHeader className="pb-3">
					<CardTitle className="text-base font-bold flex items-center gap-2">
						<Clock className="w-4 h-4 text-amber-400" />
						{t("analyticsEpochsTitle")}
					</CardTitle>
					<CardDescription className="text-xs">
						{t("analyticsEpochsSubtitle")}
					</CardDescription>
				</CardHeader>
				<CardContent className="p-0">
					<div className="overflow-x-auto">
						<Table>
							<TableHeader>
								<TableRow className="border-border/40 hover:bg-transparent">
									<TableHead className="text-xs">{t("analyticsEpochDate")}</TableHead>
									<TableHead className="text-xs">{t("analyticsEpochStatus")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsEpochEmission")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsEpochRebatePool")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsEpochDistributed")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsEpochNodes")}</TableHead>
									<TableHead className="text-xs">{t("analyticsEpochProcessedAt")}</TableHead>
									<TableHead className="text-xs text-right">Actions</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{isLoadingSummary ? (
									Array.from({ length: 3 }).map((_, i) => (
										<TableRow key={i}>
											<TableCell colSpan={8}><Skeleton className="h-6 w-full" /></TableCell>
										</TableRow>
									))
								) : analyticsData?.epochs && analyticsData.epochs.length > 0 ? (
									analyticsData.epochs.map((ep) => (
										<TableRow key={ep.epochDate} className="border-border/30 hover:bg-muted/30">
											<TableCell className="font-mono text-xs font-semibold">{ep.epochDate}</TableCell>
											<TableCell>
												{ep.status === "closed" || ep.status === "finalized" || Boolean(ep.processedAt) ? (
													<Badge variant="outline" className="border-emerald-500/40 text-emerald-400 bg-emerald-500/10 text-[10px]">
														✓ {t("analyticsEpochStatusClosed")}
													</Badge>
												) : (
													<Badge variant="outline" className="border-amber-500/40 text-amber-400 bg-amber-500/10 text-[10px]">
														⏳ {t("analyticsEpochStatusOpen")}
													</Badge>
												)}
											</TableCell>
											<TableCell className="font-mono text-xs text-right">{Math.round(ep.dailyEmission).toLocaleString()} $DEPTH</TableCell>
											<TableCell className="font-mono text-xs text-right font-medium text-emerald-400">${ep.totalRebatePool.toFixed(2)}</TableCell>
											<TableCell className="font-mono text-xs text-right font-bold text-primary">{Math.round(ep.totalDistributed).toLocaleString()} $DEPTH</TableCell>
											<TableCell className="font-mono text-xs text-right font-mono">{ep.participatingNodes}</TableCell>
											<TableCell className="font-mono text-xs text-muted-foreground">
												{ep.processedAt ? format(new Date(ep.processedAt), "yyyy-MM-dd HH:mm") : "⏳ Not finalized"}
											</TableCell>
											<TableCell className="text-right">
												<Button
													variant="ghost"
													size="sm"
													className="h-7 text-xs font-mono"
													disabled={isReprocessing}
													onClick={() => handleReprocessEpoch(ep.epochDate)}
												>
													<RefreshCw className={`w-3 h-3 mr-1 ${isReprocessing ? "animate-spin" : ""}`} />
													{t("analyticsEpochReprocess")}
												</Button>
											</TableCell>
										</TableRow>
									))
								) : (
									<TableRow>
										<TableCell colSpan={8} className="text-center text-xs text-muted-foreground py-6">
											{t("analyticsNoData")}
										</TableCell>
									</TableRow>
								)}
							</TableBody>
						</Table>
					</div>
				</CardContent>
			</Card>

			{/* PAGINATED TRADES & TELEMETRY TABLE */}
			<Card className="border border-border/60 bg-card/70 backdrop-blur-md shadow-lg">
				<CardHeader className="pb-3">
					<div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
						<div>
							<CardTitle className="text-base font-bold flex items-center gap-2">
								<Activity className="w-4 h-4 text-primary" />
								{t("analyticsTradesTitle")}
							</CardTitle>
							<CardDescription className="text-xs">
								{t("analyticsTradesSubtitle")}
							</CardDescription>
						</div>

						{/* Filters */}
						<div className="flex flex-wrap items-center gap-2.5">
							{/* Search */}
							<div className="relative w-48 sm:w-64">
								<Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
								<Input
									placeholder={t("analyticsSearchPlaceholder")}
									value={searchQuery}
									onChange={(e) => {
										setSearchQuery(e.target.value);
										setPage(1);
									}}
									className="h-8 pl-8 text-xs font-mono"
								/>
							</div>

							{/* Exchange Filter */}
							<Select
								value={exchangeFilter}
								onValueChange={(val) => {
									setExchangeFilter(val);
									setPage(1);
								}}
							>
								<SelectTrigger className="h-8 w-36 text-xs font-mono">
									<SelectValue placeholder={t("analyticsFilterAllExchanges")} />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="ALL">{t("analyticsFilterAllExchanges")}</SelectItem>
									{analyticsData?.activeExchanges.map((ex) => (
										<SelectItem key={ex} value={ex} className="font-mono text-xs">
											{ex}
										</SelectItem>
									))}
								</SelectContent>
							</Select>

							{/* Status Filter */}
							<Select
								value={statusFilter}
								onValueChange={(val) => {
									setStatusFilter(val);
									setPage(1);
								}}
							>
								<SelectTrigger className="h-8 w-36 text-xs font-mono">
									<SelectValue placeholder={t("analyticsFilterAllStatuses")} />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="ALL">{t("analyticsFilterAllStatuses")}</SelectItem>
									<SelectItem value="VERIFIED">{t("analyticsFilterStatusVerified")}</SelectItem>
									<SelectItem value="PENDING">{t("analyticsFilterStatusPending")}</SelectItem>
									<SelectItem value="ERROR">{t("analyticsFilterStatusError")}</SelectItem>
									<SelectItem value="GATED">{t("analyticsFilterStatusGated")}</SelectItem>
								</SelectContent>
							</Select>
						</div>
					</div>
				</CardHeader>
				<CardContent className="p-0">
					<div className="overflow-x-auto">
						<Table>
							<TableHeader>
								<TableRow className="border-border/40 hover:bg-transparent">
									<TableHead className="text-xs">{t("analyticsTradeSymbol")}</TableHead>
									<TableHead className="text-xs">{t("analyticsTradeDirection")}</TableHead>
									<TableHead className="text-xs">{t("analyticsTradeExchange")}</TableHead>
									<TableHead className="text-xs">{t("analyticsTradeNode")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsTradeVolume")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsTradeEstRebate")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsTradeVerifiedVol")}</TableHead>
									<TableHead className="text-xs text-center">{t("analyticsTradeStatus")}</TableHead>
									<TableHead className="text-xs">{t("analyticsTradeError")}</TableHead>
									<TableHead className="text-xs text-right">{t("analyticsTradeReward")}</TableHead>
									<TableHead className="text-xs">{t("analyticsTradeCreatedAt")}</TableHead>
									<TableHead className="text-xs text-right">Inspect</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{isLoadingTrades ? (
									Array.from({ length: 5 }).map((_, i) => (
										<TableRow key={i}>
											<TableCell colSpan={12}><Skeleton className="h-6 w-full" /></TableCell>
										</TableRow>
									))
								) : tradesData?.items && tradesData.items.length > 0 ? (
									tradesData.items.map((tr) => {
										const isLong = tr.direction?.toUpperCase() === "LONG";
										const isVer = tr.verificationStatus === "VERIFIED";
										const isPend = tr.verificationStatus === "PENDING";

										return (
											<TableRow
												key={tr.id}
												className="border-border/30 hover:bg-muted/30 cursor-pointer"
												onClick={() => setSelectedTrade(tr)}
											>
												<TableCell className="font-mono text-xs font-bold text-foreground">
													{tr.symbol}
												</TableCell>
												<TableCell>
													<Badge
														variant="outline"
														className={`text-[10px] font-mono px-1.5 py-0 font-bold ${
															isLong
																? "border-emerald-500/40 text-emerald-400 bg-emerald-500/10"
																: "border-rose-500/40 text-rose-400 bg-rose-500/10"
														}`}
													>
														{tr.direction}
													</Badge>
												</TableCell>
												<TableCell className="font-mono text-xs text-muted-foreground">
													<div className="flex items-center gap-1.5">
														<span>{tr.exchangeId || "—"}</span>
														{tr.miningMultiplier && tr.miningMultiplier > 1 && (
															<Badge className="bg-amber-500/20 text-amber-400 border-amber-500/40 text-[10px] px-1.5 py-0 h-4 font-bold">
																x{tr.miningMultiplier}
															</Badge>
														)}
													</div>
												</TableCell>
												<TableCell className="text-xs font-medium text-foreground">
													{tr.nodeName || tr.nodeUuid?.slice(0, 8) || "—"}
												</TableCell>
												<TableCell className="font-mono text-xs text-right font-medium">
													${(tr.tradeVolumeUsdt ?? 0).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
												</TableCell>
												<TableCell className="font-mono text-xs text-right text-muted-foreground">
													${(tr.estimatedRebateUsdt ?? 0).toFixed(3)}
												</TableCell>
												<TableCell className="font-mono text-xs text-right text-emerald-400">
													{tr.verifiedVolumeUsdt != null ? `$${tr.verifiedVolumeUsdt.toLocaleString()}` : "—"}
												</TableCell>
												<TableCell className="text-center">
													<Badge
														variant="outline"
														className={`text-[10px] font-mono px-1.5 py-0 ${
															isVer
																? "border-emerald-500/40 text-emerald-400 bg-emerald-500/10"
																: isPend
																? "border-amber-500/40 text-amber-400 bg-amber-500/10"
																: "border-rose-500/40 text-rose-400 bg-rose-500/10"
														}`}
													>
														{tr.verificationStatus}
													</Badge>
												</TableCell>
												<TableCell className="font-mono text-xs text-rose-400 max-w-[140px] truncate" title={tr.verificationError || ""}>
													{tr.verificationError || "—"}
												</TableCell>
												<TableCell className="font-mono text-xs text-right text-primary font-bold">
													{tr.rewardTokens ? `${tr.rewardTokens.toFixed(1)}` : "—"}
												</TableCell>
												<TableCell className="font-mono text-xs text-muted-foreground">
													{format(new Date(tr.createdAt), "MM-dd HH:mm")}
												</TableCell>
												<TableCell className="text-right">
													<Button
														variant="ghost"
														size="icon"
														className="h-7 w-7"
														onClick={(e) => {
															e.stopPropagation();
															setSelectedTrade(tr);
														}}
													>
														<ArrowUpRight className="w-3.5 h-3.5" />
													</Button>
												</TableCell>
											</TableRow>
										);
									})
								) : (
									<TableRow>
										<TableCell colSpan={12} className="text-center text-xs text-muted-foreground py-8">
											{t("analyticsNoData")}
										</TableCell>
									</TableRow>
								)}
							</TableBody>
						</Table>
					</div>

					{/* Pagination Footer */}
					{tradesData && tradesData.totalPages > 1 && (
						<div className="flex flex-col sm:flex-row items-center justify-between gap-3 p-4 border-t border-border/40">
							<div className="text-xs text-muted-foreground font-mono">
								{t("analyticsPaginationShowing", {
									start: (page - 1) * pageSize + 1,
									end: Math.min(page * pageSize, tradesData.total),
									total: tradesData.total,
								})}
							</div>

							<div className="flex items-center gap-2">
								<Select
									value={String(pageSize)}
									onValueChange={(val) => {
										setPageSize(Number(val));
										setPage(1);
									}}
								>
									<SelectTrigger className="h-8 w-20 text-xs font-mono">
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="10">10</SelectItem>
										<SelectItem value="25">25</SelectItem>
										<SelectItem value="50">50</SelectItem>
										<SelectItem value="100">100</SelectItem>
									</SelectContent>
								</Select>

								<Button
									variant="outline"
									size="sm"
									className="h-8 w-8 p-0"
									disabled={page <= 1}
									onClick={() => setPage((p) => Math.max(1, p - 1))}
								>
									<ChevronLeft className="h-4 w-4" />
								</Button>
								<span className="text-xs font-mono text-muted-foreground px-2">
									{page} / {tradesData.totalPages}
								</span>
								<Button
									variant="outline"
									size="sm"
									className="h-8 w-8 p-0"
									disabled={page >= tradesData.totalPages}
									onClick={() => setPage((p) => Math.min(tradesData.totalPages, p + 1))}
								>
									<ChevronRight className="h-4 w-4" />
								</Button>
							</div>
						</div>
					)}
				</CardContent>
			</Card>

			{/* Trade Detail Modal */}
			<TradeDetailModal
				trade={selectedTrade}
				isOpen={Boolean(selectedTrade)}
				onClose={() => setSelectedTrade(null)}
			/>
		</div>
	);
};

export default AdminMiningAnalytics;
