// pwa/screens/DashboardScreen.tsx

import type { TFunction } from "i18next";
import type React from "react";
import { useEffect, useState } from "react";
import { toast } from "react-hot-toast";
import { useTranslation } from "react-i18next";
import { useSwipeable } from "react-swipeable";
import {
	Bar,
	BarChart,
	Cell,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import { Logo } from "../components/ui/logo";
import { ICONS } from "../constants";
import { api } from "../services/api";
import type { PortfolioStatus, Position } from "../types";

type PnlPeriod = "1d" | "7d" | "mtd";

const transformEquityToPnl = (
	equityCurve: [number, number][],
	period: PnlPeriod,
): { name: string; pnl: number }[] => {
	if (!equityCurve || equityCurve.length === 0) {
		return [];
	}

	// If there is only one point, add a virtual "now" point to show 0 PnL
	if (equityCurve.length === 1) {
		const [ts, balance] = equityCurve[0];
		const now = Date.now();
		equityCurve = [
			[ts, balance],
			[now, balance],
		];
	}

	if (period === "1d") {
		// PnL by hours
		const hourlyData: { name: string; pnl: number }[] = [];
		let previousBalance = equityCurve[0][1];

		for (let i = 1; i < equityCurve.length; i++) {
			const [timestamp, balance] = equityCurve[i];
			const pnl = balance - previousBalance;
			const hourName = new Date(timestamp).toLocaleTimeString(undefined, {
				hour: "2-digit",
				minute: "2-digit",
			});

			hourlyData.push({ name: hourName, pnl });
			previousBalance = balance;
		}
		return hourlyData;
	} else {
		// PnL by days
		const dailyBalances: { [key: string]: number } = {};

		// Group by days, keeping the last balance of the day
		equityCurve.forEach(([timestamp, balance]) => {
			const dayKey = new Date(timestamp).toISOString().split("T")[0];
			dailyBalances[dayKey] = balance;
		});

		const sortedDailyData = Object.entries(dailyBalances)
			.map(([day, balance]) => ({ day, balance, ts: new Date(day).getTime() }))
			.sort((a, b) => a.ts - b.ts);

		const pnlData: { name: string; pnl: number }[] = [];
		let runningBalance = equityCurve[0][1];

		sortedDailyData.forEach((item) => {
			const pnl = item.balance - runningBalance;
			const dayName = new Date(item.day).toLocaleDateString(undefined, {
				day: "2-digit",
				month: "2-digit",
			});
			pnlData.push({ name: dayName, pnl });
			runningBalance = item.balance;
		});

		// If the first point of the period coincides with the first day of data and PnL is 0,
		// we still keep it, as it might be the only point
		return pnlData.filter((d) => d.pnl !== 0 || pnlData.length === 1);
	}
};

const PnlChart: React.FC<{
	data: { name: string; pnl: number }[];
	t: TFunction;
}> = ({ data, t }) => {
	if (!data || data.length === 0) {
		return (
			<div className="h-52 flex items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
				{t("dashboard.noDataToDisplay")}
			</div>
		);
	}

	return (
		<div className="h-52 bg-[hsl(var(--secondary))] rounded-lg p-2">
			<ResponsiveContainer width="100%" height="100%">
				<BarChart
					data={data}
					margin={{ top: 5, right: 20, left: -10, bottom: 5 }}
				>
					<XAxis
						dataKey="name"
						stroke="hsl(var(--muted-foreground))"
						fontSize={12}
						tickLine={false}
						axisLine={false}
					/>
					<YAxis
						stroke="hsl(var(--muted-foreground))"
						fontSize={12}
						tickLine={false}
						axisLine={false}
						tickFormatter={(value) => `$${value}`}
					/>
					<Tooltip
						contentStyle={{
							backgroundColor: "hsl(var(--popover))",
							border: "1px solid hsl(var(--border))",
							color: "hsl(var(--popover-foreground))",
							borderRadius: "var(--radius)",
						}}
						cursor={{ fill: "hsla(var(--primary), 0.2)" }}
						formatter={(value: number) => [
							`$${value.toFixed(2)}`,
							t("dashboard.pnl"),
						]}
					/>
					<Bar dataKey="pnl">
						{data.map((entry, index) => (
							<Cell
								key={`cell-${index}`}
								fill={
									entry.pnl >= 0 ? "hsl(var(--profit))" : "hsl(var(--loss))"
								}
							/>
						))}
					</Bar>
				</BarChart>
			</ResponsiveContainer>
		</div>
	);
};

const DashboardScreen: React.FC = () => {
	const [mode, setMode] = useState<"live" | "paper">(() => {
		const savedMode = localStorage.getItem("dashboardMode") as "live" | "paper";
		return savedMode || "paper"; // Default is 'paper'
	});
	const [pnlPeriod, setPnlPeriod] = useState<PnlPeriod>("1d");
	const [portfolio, setPortfolio] = useState<PortfolioStatus | null>(null);
	const [positions, setPositions] = useState<Position[]>([]);
	const [pnlHistory, setPnlHistory] = useState<{ name: string; pnl: number }[]>(
		[],
	);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [isLiveModeAvailable, setIsLiveModeAvailable] = useState(false);
	const { t } = useTranslation("pwa-common");

	useEffect(() => {
		const fetchData = async () => {
			setLoading(true);
			setError(null);

			try {
				const config = await api.getConfig();
				const hasApiKeys = config?.apiKeys && config.apiKeys.length > 0;
				setIsLiveModeAvailable(hasApiKeys);

				// If live mode is selected but there are no keys, force switch to paper
				const currentMode = mode === "live" && !hasApiKeys ? "paper" : mode;
				if (mode !== currentMode) {
					setMode(currentMode);
					// The effect will be restarted with the new mode, so we interrupt the current execution
					return;
				}

				const [portfolioRes, positionsRes, equityRes] = await Promise.all([
					api.getPortfolio(currentMode),
					api.getPositions(currentMode),
					api.getPortfolioEquity(currentMode, pnlPeriod),
				]);

				setPortfolio(portfolioRes || null);
				setPositions(positionsRes || []);

				let curve = equityRes || [];
				if (curve.length === 0 && portfolioRes) {
					curve = [[Date.now(), portfolioRes.balance]];
				}

				setPnlHistory(transformEquityToPnl(curve, pnlPeriod));
			} catch (err) {
				console.error("Failed to fetch dashboard data:", err);
				setError(t("dashboard.failedToLoadData"));
				setPortfolio(null);
				setPositions([]);
				setPnlHistory([]);
			} finally {
				setLoading(false);
			}
		};
		fetchData();
	}, [mode, pnlPeriod, t]);

	const handleSetMode = (newMode: "live" | "paper") => {
		if (newMode === "live" && !isLiveModeAvailable) {
			toast.error(t("dashboard.connectApiKeysMessage"));
			return;
		}
		setMode(newMode);
		localStorage.setItem("dashboardMode", newMode);
	};

	const swipeHandlers = useSwipeable({
		onSwipedLeft: () => handleSetMode("paper"),
		onSwipedRight: () => handleSetMode("live"),
		preventScrollOnSwipe: true,
		trackMouse: true,
	});

	const handleClosePosition = async (symbol: string) => {
		if (!window.confirm(t("dashboard.confirmClosePosition", { symbol })))
			return;
		try {
			await api.closePosition(symbol);
			alert(t("dashboard.closePositionCommandSent", { symbol }));
			setTimeout(() => {
				api.getPositions(mode).then((res) => setPositions(res || []));
			}, 2000);
		} catch (err) {
			console.error(err);
			alert(t("dashboard.errorClosingPosition", { symbol }));
		}
	};

	if (loading && !portfolio && !error) {
		return (
			<div className="flex justify-center items-center min-h-screen">
				<Logo size="lg" className="mb-8 animate-pulse" />
			</div>
		);
	}

	if (error) {
		return (
			<div className="p-4 text-center text-[hsl(var(--loss))]">{error}</div>
		);
	}

	const unrealizedPnl = positions.reduce((acc, pos) => acc + pos.pnl, 0);

	return (
		<div {...swipeHandlers} className="p-4 animate-fadeIn">
			<div className="flex gap-1 p-1 bg-[hsl(var(--secondary))] rounded-lg mb-5">
				<button
					onClick={() => handleSetMode("live")}
					className={`flex-1 py-2 px-4 rounded-md transition-all text-sm font-medium ${mode === "live" ? "bg-[hsl(var(--card))] shadow text-[hsl(var(--card-foreground))]" : "bg-transparent text-[hsl(var(--muted-foreground))]"} ${!isLiveModeAvailable ? "opacity-60" : ""}`}
				>
					{t("dashboard.live")}
				</button>
				<button
					onClick={() => handleSetMode("paper")}
					className={`flex-1 py-2 px-4 rounded-md transition-all text-sm font-medium ${mode === "paper" ? "bg-[hsl(var(--card))] shadow text-[hsl(var(--card-foreground))]" : "bg-transparent text-[hsl(var(--muted-foreground))]"}`}
				>
					{t("dashboard.paper")}
				</button>
			</div>

			<div key={mode} className="animate-fadeIn">
				<div className="bg-gradient-to-br from-[hsl(var(--primary))] to-blue-800 text-[hsl(var(--primary-foreground))] p-5 rounded-2xl mb-5 shadow-lg">
					<div className="text-sm opacity-90">
						{t("dashboard.totalBalance")}
					</div>
					<div className="text-4xl font-light my-3">
						$
						{portfolio?.balance.toLocaleString(undefined, {
							minimumFractionDigits: 2,
							maximumFractionDigits: 2,
						}) || "0.00"}
					</div>
					<div className="flex gap-5 mt-4">
						<div className="flex-1">
							<div className="text-xs opacity-90">
								{t("dashboard.dailyPnl")}
							</div>
							<div className="text-lg font-medium">
								{(portfolio?.today_pnl ?? 0 >= 0) ? "+" : ""}$
								{portfolio?.today_pnl.toLocaleString() || "0"}
							</div>
						</div>
						<div className="flex-1">
							<div className="text-xs opacity-90">
								{t("dashboard.unrealizedPnl")}
							</div>
							<div className="text-lg font-medium">
								{unrealizedPnl >= 0 ? "+" : ""}$
								{unrealizedPnl.toLocaleString(undefined, {
									minimumFractionDigits: 2,
									maximumFractionDigits: 2,
								})}
							</div>
						</div>
					</div>
				</div>

				<div className="bg-[hsl(var(--card))] rounded-xl p-4 mb-5 shadow-sm">
					<div className="flex justify-between items-center mb-3">
						<h3 className="text-base font-medium text-[hsl(var(--card-foreground))]">
							{t("dashboard.pnlChart")}
						</h3>
						<div className="flex gap-1 text-xs bg-[hsl(var(--secondary))] p-1 rounded-md">
							<button
								onClick={() => setPnlPeriod("1d")}
								className={`px-2 py-1 rounded ${pnlPeriod === "1d" ? "bg-[hsl(var(--background))] text-[hsl(var(--foreground))]" : "text-[hsl(var(--muted-foreground))]"}`}
							>
								{t("dashboard.1d")}
							</button>
							<button
								onClick={() => setPnlPeriod("7d")}
								className={`px-2 py-1 rounded ${pnlPeriod === "7d" ? "bg-[hsl(var(--background))] text-[hsl(var(--foreground))]" : "text-[hsl(var(--muted-foreground))]"}`}
							>
								{t("dashboard.7d")}
							</button>
							<button
								onClick={() => setPnlPeriod("mtd")}
								className={`px-2 py-1 rounded ${pnlPeriod === "mtd" ? "bg-[hsl(var(--background))] text-[hsl(var(--foreground))]" : "text-[hsl(var(--muted-foreground))]"}`}
							>
								{t("dashboard.mtd")}
							</button>
						</div>
					</div>
					{loading ? (
						<div className="h-52 flex items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
							{t("dashboard.loadingChart")}
						</div>
					) : (
						<PnlChart data={pnlHistory} t={t} />
					)}
				</div>

				<div className="bg-[hsl(var(--card))] rounded-xl p-4 shadow-sm">
					<h3 className="text-base font-medium mb-1 text-[hsl(var(--card-foreground))]">
						{t("dashboard.activePositions")}
					</h3>
					<div className="divide-y divide-[hsl(var(--border))]">
						{positions.length > 0 ? (
							positions.map((pos) => (
								<div
									key={pos.id}
									className="flex justify-between items-center py-3"
								>
									<div>
										<div className="font-medium">{pos.symbol}</div>
										<div className="text-sm text-[hsl(var(--muted-foreground))]">
											{t("dashboard.size")}: {pos.size}
										</div>
									</div>
									<div className="flex items-center gap-4">
										<div className="text-right">
											<div
												className={`font-medium ${pos.pnl >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}`}
											>
												{t("dashboard.pnl")}: {pos.pnl >= 0 ? "+" : ""}
												{pos.pnl.toLocaleString(undefined, {
													minimumFractionDigits: 2,
													maximumFractionDigits: 2,
												})}
											</div>
											<div className="text-xs text-[hsl(var(--muted-foreground))]">
												{pos.pnl_percent >= 0 ? "+" : ""}
												{pos.pnl_percent.toFixed(2)}%
											</div>
										</div>
										<button
											onClick={() => handleClosePosition(pos.symbol)}
											className="w-8 h-8 rounded-full flex items-center justify-center transition bg-[hsl(var(--secondary))] hover:bg-[hsl(var(--accent))]"
											aria-label={t("dashboard.closePosition", {
												symbol: pos.symbol,
											})}
										>
											<ICONS.Close className="w-5 h-5 text-[hsl(var(--muted-foreground))]" />
										</button>
									</div>
								</div>
							))
						) : (
							<p className="text-center text-sm text-[hsl(var(--muted-foreground))] py-4">
								{t("dashboard.noActivePositions")}
							</p>
						)}
					</div>
				</div>
			</div>
		</div>
	);
};

export default DashboardScreen;
