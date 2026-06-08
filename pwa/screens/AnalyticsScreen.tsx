// pwa/screens/AnalyticsScreen.tsx

import {
	Activity,
	Clock,
	DollarSign,
	Target,
	TrendingUp,
	Zap,
} from "lucide-react";
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
	Area,
	AreaChart,
	Bar,
	CartesianGrid,
	Cell,
	BarChart as RechartsBarChart,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import {
	Card as PWACard,
	CardHeader as PWACardHeader,
	CardTitle as PWACardTitle,
} from "../components/Card";
import { Logo } from "../components/ui/logo";
import { api } from "../services/api";
import type { TradeData } from "../types";

// --- Types ---
interface DashboardStats {
	totalPnl: number;
	winRate: number;
	profitFactor: number;
	expectancy: number;
	sharpeRatio: number;
	sharpeInsufficient: boolean;
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
		realizedPnl: (t.pnl || 0) - (t.commission || 0),
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

	const totalCommission = trades.reduce(
		(sum, t) => sum + (t.commission || 0),
		0,
	);

	const totalVolume = trades.reduce((sum, t) => {
		const qty = t.quantity || 0;
		const price = t.entry_price || t.exit_price || 0;
		return sum + qty * price;
	}, 0);

	// --- Sharpe Ratio ---
	const dailyPnLMap: Record<string, number> = {};
	tradesWithRealizedPnl.forEach((t) => {
		const dateKey = new Date(t.timestamp_close).toISOString().split("T")[0];
		dailyPnLMap[dateKey] = (dailyPnLMap[dateKey] || 0) + t.realizedPnl;
	});

	const dailyReturns = Object.values(dailyPnLMap);

	let sharpeRatio = 0;
	let sharpeInsufficient = false;
	if (dailyReturns.length >= 2) {
		const avgDailyReturn =
			dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
		const dailyVariance =
			dailyReturns.reduce((sum, ret) => sum + (ret - avgDailyReturn) ** 2, 0) /
			(dailyReturns.length - 1);
		const dailyStdDev = Math.sqrt(dailyVariance);

		if (dailyStdDev > 0.0001) {
			sharpeRatio = (avgDailyReturn / dailyStdDev) * Math.sqrt(365);
		} else {
			if (avgDailyReturn > 0) sharpeRatio = 5;
			else if (avgDailyReturn < 0) sharpeRatio = -5;
		}
		if (sharpeRatio > 10) sharpeRatio = 10;
		if (sharpeRatio < -10) sharpeRatio = -10;
	} else {
		sharpeInsufficient = true;
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

interface StatCardProps {
	label: string;
	value: string | number;
	subValue?: string;
	icon: React.ElementType;
	trend?: "up" | "down" | "neutral";
}

const StatCard = ({
	label,
	value,
	subValue,
	icon: Icon,
	trend,
}: StatCardProps) => (
	<PWACard className="flex flex-col justify-between py-3 px-4">
		<div className="flex justify-between items-start mb-2">
			<span className="text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold">
				{label}
			</span>
			<Icon className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />
		</div>
		<div>
			<div
				className={`text-lg font-bold leading-none ${trend === "up" ? "text-[hsl(var(--profit))]" : trend === "down" ? "text-[hsl(var(--loss))]" : "text-[hsl(var(--foreground))]"}`}
			>
				{value}
			</div>
			{subValue && (
				<div className="text-[10px] text-[hsl(var(--muted-foreground))] mt-1">
					{subValue}
				</div>
			)}
		</div>
	</PWACard>
);

const AnalyticsScreen: React.FC = () => {
	const { t } = useTranslation("pwa-common");
	const [trades, setTrades] = useState<TradeData[]>([]);
	const [loading, setLoading] = useState(true);

	useEffect(() => {
		const fetchTrades = async () => {
			setLoading(true);
			try {
				const thirtyDaysAgo = new Date();
				thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

				const response = await api.getTrades({
					dateFrom: thirtyDaysAgo.toISOString().split("T")[0],
					dateTo: new Date().toISOString().split("T")[0],
					limit: 1000,
				});
				setTrades(response.trades);
			} catch (err) {
				console.error("Failed to fetch trades:", err);
			} finally {
				setLoading(false);
			}
		};
		fetchTrades();
	}, []);

	const stats = useMemo(() => calculateAdvancedStats(trades), [trades]);

	const equityCurveData = useMemo(() => {
		if (trades.length === 0) return [];

		let cumulative = 0;
		const sortedTrades = [...trades].sort(
			(a, b) => a.timestamp_close - b.timestamp_close,
		);

		return sortedTrades.map((trade) => {
			const realizedPnl = (trade.pnl || 0) - (trade.commission || 0);
			cumulative += realizedPnl;
			return {
				timestamp: trade.timestamp_close,
				equity: cumulative,
			};
		});
	}, [trades]);

	const hourlyData = useMemo(() => {
		const hours = Array.from({ length: 24 }, (_, i) => ({ hour: i, pnl: 0 }));
		trades.forEach((t) => {
			const h = new Date(t.timestamp_close).getHours();
			hours[h].pnl += (t.pnl || 0) - (t.commission || 0);
		});
		return hours;
	}, [trades]);

	if (loading) {
		return (
			<div className="flex justify-center items-center py-20">
				<Logo size="lg" className="animate-pulse" />
			</div>
		);
	}

	if (!stats) {
		return (
			<div className="text-center py-20 text-[hsl(var(--muted-foreground))]">
				{t("dashboard.noDataToDisplay")}
			</div>
		);
	}

	return (
		<div className="space-y-4 animate-fadeIn">
			{/* Stats Grid */}
			<div className="grid grid-cols-2 gap-3">
				<StatCard
					label={t("analytics.overview.netProfit")}
					value={`${stats.totalPnl >= 0 ? "+" : ""}$${stats.totalPnl.toLocaleString(undefined, { maximumFractionDigits: 1 })}`}
					subValue={`${stats.totalTrades} trades`}
					icon={DollarSign}
					trend={stats.totalPnl >= 0 ? "up" : "down"}
				/>
				<StatCard
					label={t("analytics.overview.winRate")}
					value={`${stats.winRate.toFixed(1)}%`}
					subValue={`${stats.wins}W / ${stats.losses}L`}
					icon={Target}
					trend={stats.winRate >= 50 ? "up" : "down"}
				/>
				<StatCard
					label={t("analytics.overview.profitFactor")}
					value={
						stats.profitFactor === Infinity
							? "∞"
							: stats.profitFactor.toFixed(2)
					}
					icon={Zap}
					trend={stats.profitFactor >= 1 ? "up" : "down"}
				/>
				<StatCard
					label={t("analytics.overview.sharpeRatio")}
					value={
						stats.sharpeInsufficient ? "N/A" : stats.sharpeRatio.toFixed(2)
					}
					subValue={
						stats.sharpeInsufficient
							? t("analytics.overview.needsMoreDays")
							: t("analytics.overview.annualized")
					}
					icon={Activity}
					trend={
						stats.sharpeRatio >= 1
							? "up"
							: stats.sharpeRatio > 0
								? "neutral"
								: "down"
					}
				/>
			</div>

			{/* Equity Curve Chart */}
			<PWACard className="p-4">
				<PWACardHeader className="p-0 border-none mb-4">
					<PWACardTitle className="text-sm flex items-center gap-2">
						<TrendingUp className="w-4 h-4 text-[hsl(var(--primary))]" />
						{t("analytics.tabs.cumulativePnl")}
					</PWACardTitle>
				</PWACardHeader>
				<div className="h-48 w-full">
					<ResponsiveContainer width="100%" height="100%">
						<AreaChart data={equityCurveData}>
							<defs>
								<linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
									<stop
										offset="5%"
										stopColor="hsl(var(--primary))"
										stopOpacity={0.3}
									/>
									<stop
										offset="95%"
										stopColor="hsl(var(--primary))"
										stopOpacity={0}
									/>
								</linearGradient>
							</defs>
							<CartesianGrid
								strokeDasharray="3 3"
								vertical={false}
								stroke="hsl(var(--border))"
							/>
							<XAxis dataKey="timestamp" hide />
							<YAxis hide domain={["auto", "auto"]} />
							<Tooltip
								contentStyle={{
									backgroundColor: "hsl(var(--card))",
									borderColor: "hsl(var(--border))",
									fontSize: "12px",
									borderRadius: "8px",
								}}
								labelStyle={{ display: "none" }}
								formatter={(value: number) => [`$${value.toFixed(2)}`, "PnL"]}
							/>
							<Area
								type="monotone"
								dataKey="equity"
								stroke="hsl(var(--primary))"
								fillOpacity={1}
								fill="url(#colorEquity)"
								strokeWidth={2}
							/>
						</AreaChart>
					</ResponsiveContainer>
				</div>
			</PWACard>

			{/* Hourly Performance Chart */}
			<PWACard className="p-4">
				<PWACardHeader className="p-0 border-none mb-4">
					<PWACardTitle className="text-sm flex items-center gap-2">
						<Clock className="w-4 h-4 text-[hsl(var(--primary))]" />
						{t("analytics.tabs.hourlyPerformance")}
					</PWACardTitle>
				</PWACardHeader>
				<div className="h-40 w-full">
					<ResponsiveContainer width="100%" height="100%">
						<RechartsBarChart data={hourlyData}>
							<CartesianGrid
								strokeDasharray="3 3"
								vertical={false}
								stroke="hsl(var(--border))"
							/>
							<XAxis
								dataKey="hour"
								fontSize={10}
								tickLine={false}
								axisLine={false}
								tickFormatter={(val) => `${val}h`}
							/>
							<YAxis hide />
							<Tooltip
								contentStyle={{
									backgroundColor: "hsl(var(--card))",
									borderColor: "hsl(var(--border))",
									fontSize: "10px",
									borderRadius: "8px",
								}}
								formatter={(value: number) => [`$${value.toFixed(2)}`, "PnL"]}
							/>
							<Bar dataKey="pnl">
								{hourlyData.map((entry, index) => (
									<Cell
										key={`cell-${index}`}
										fill={
											entry.pnl >= 0 ? "hsl(var(--profit))" : "hsl(var(--loss))"
										}
										fillOpacity={0.7}
									/>
								))}
							</Bar>
						</RechartsBarChart>
					</ResponsiveContainer>
				</div>
			</PWACard>

			{/* Additional Stats */}
			<div className="space-y-2">
				<div className="flex justify-between p-3 bg-[hsl(var(--card))] rounded-lg text-sm shadow-sm">
					<span className="text-[hsl(var(--muted-foreground))]">
						{t("analytics.overview.totalCommission")}
					</span>
					<span className="font-medium text-[hsl(var(--loss))]">
						-${stats.totalCommission.toFixed(2)}
					</span>
				</div>
				<div className="flex justify-between p-3 bg-[hsl(var(--card))] rounded-lg text-sm shadow-sm">
					<span className="text-[hsl(var(--muted-foreground))]">
						{t("analytics.overview.expectancy")}
					</span>
					<span
						className={`font-medium ${stats.expectancy >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}`}
					>
						${stats.expectancy.toFixed(2)}
					</span>
				</div>
				<div className="flex justify-between p-3 bg-[hsl(var(--card))] rounded-lg text-sm shadow-sm">
					<span className="text-[hsl(var(--muted-foreground))]">
						{t("analytics.overview.avgWinLossRatio")}
					</span>
					<span className="font-medium">
						{stats.avgWinLossRatio.toFixed(2)}
					</span>
				</div>
				<div className="flex justify-between p-3 bg-[hsl(var(--card))] rounded-lg text-sm shadow-sm">
					<span className="text-[hsl(var(--muted-foreground))]">
						{t("analytics.overview.volume")}
					</span>
					<span className="font-medium font-mono">
						${(stats.totalVolume / 1000).toFixed(1)}k
					</span>
				</div>
			</div>
		</div>
	);
};

export default AnalyticsScreen;
