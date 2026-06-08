// src/components/dashboard/TotalPnl.tsx

import { AlertTriangle, TrendingDown, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
	Area,
	AreaChart,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import {
	type EquityPeriod,
	usePortfolioEquity,
	usePortfolioStatus,
	useTradeHistory,
} from "@/lib/api";
import { useAccountStore } from "@/stores/accountStore";

interface ChartPoint {
	time: number;
	value: number;
}

interface TooltipPayload {
	payload: ChartPoint;
}

const CustomTooltip = ({
	active,
	payload,
}: {
	active?: boolean;
	payload?: TooltipPayload[];
}) => {
	if (active && payload?.length) {
		const data = payload[0].payload;
		return (
			<div className="rounded-lg border bg-background p-2 shadow-sm text-xs">
				<p className="font-bold">${data.value.toFixed(2)}</p>
				<p className="text-muted-foreground">
					{new Date(data.time).toLocaleString()}
				</p>
			</div>
		);
	}
	return null;
};

const getPeriodStart = (period: EquityPeriod, now: Date): Date => {
	switch (period) {
		case "7d":
			return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
		case "mtd":
			return new Date(now.getFullYear(), now.getMonth(), 1);
		default:
			return new Date(now.getTime() - 24 * 60 * 60 * 1000);
	}
};

const toTimestampMs = (value: string | number | undefined): number | null => {
	if (value === undefined || value === null) return null;
	if (typeof value === "number") {
		const normalized = value > 1_000_000_000_000 ? value : value * 1000;
		return Number.isFinite(normalized) ? normalized : null;
	}

	const timestamp = new Date(value).getTime();
	return Number.isFinite(timestamp) ? timestamp : null;
};

const TOTAL_PNL_PERIOD_STORAGE_KEY = "dashboard.totalPnl.period";

const getStoredPeriod = (): EquityPeriod => {
	if (typeof window === "undefined") return "1d";
	const stored = window.localStorage.getItem(TOTAL_PNL_PERIOD_STORAGE_KEY);
	return stored === "1d" || stored === "7d" || stored === "mtd" ? stored : "1d";
};

export function TotalPnl() {
	const { t } = useTranslation(["index", "common"]);
	const [period, setPeriod] = useState<EquityPeriod>(() => getStoredPeriod());
	const [rangeNow, setRangeNow] = useState(() => new Date());
	const { mode } = usePortfolioMode();
	const { selectedApiKeyId, selectedMarketType } = useAccountStore();

	const now = rangeNow;
	const periodStart = useMemo(() => getPeriodStart(period, now), [period, now]);
	const scopedApiKeyId = mode === "live" ? selectedApiKeyId : undefined;

	const {
		data: portfolioData,
		isLoading: isLoadingPnl,
		isError: isErrorPnl,
		error: errorPnl,
	} = usePortfolioStatus({
		mode,
		apiKeyId: scopedApiKeyId,
		marketType: mode === "live" ? selectedMarketType : undefined,
	});

	const { data: equityData, isLoading: isLoadingEquity } = usePortfolioEquity(
		period,
		mode,
	);

	const { data: periodTradesData, isLoading: isLoadingTrades } =
		useTradeHistory({
			mode,
			startDate: periodStart.toISOString(),
			endDate: now.toISOString(),
			limit: 10000,
			apiKeyId: scopedApiKeyId,
		});

	const periodTrades = useMemo(() => {
		const startMs = periodStart.getTime();
		const endMs = now.getTime();
		return (periodTradesData?.trades || []).filter((trade) => {
			const closeMs = toTimestampMs(trade.timestamp_close);
			return closeMs !== null && closeMs >= startMs && closeMs <= endMs;
		});
	}, [periodTradesData, periodStart, now]);

	const { periodPnl, periodPnlPercent, isPositive } = useMemo(() => {
		if (periodTrades.length > 0) {
			const pnl = periodTrades.reduce(
				(sum, trade) => sum + (Number(trade.pnl) || 0),
				0,
			);
			const startValue = (portfolioData?.balance ?? 0) - pnl;
			return {
				periodPnl: pnl,
				periodPnlPercent: startValue > 0 ? (pnl / startValue) * 100 : 0,
				isPositive: pnl >= 0,
			};
		}

		const fallbackPnl = period === "1d" ? (portfolioData?.today_pnl ?? 0) : 0;
		const startValue = (portfolioData?.balance ?? 0) - fallbackPnl;
		return {
			periodPnl: fallbackPnl,
			periodPnlPercent: startValue > 0 ? (fallbackPnl / startValue) * 100 : 0,
			isPositive: fallbackPnl >= 0,
		};
	}, [periodTrades, portfolioData, period]);

	const periodButtons: { key: EquityPeriod; label: string }[] = [
		{ key: "1d", label: t("index:dailyPnl.period1D") },
		{ key: "7d", label: t("index:dailyPnl.period7D") },
		{ key: "mtd", label: t("index:dailyPnl.periodMTD") },
	];

	const chartData = useMemo<ChartPoint[]>(() => {
		if (periodTrades.length > 0) {
			let cumulative = 0;
			const sortedTrades = [...periodTrades].sort((a, b) => {
				const aTime = toTimestampMs(a.timestamp_close) ?? 0;
				const bTime = toTimestampMs(b.timestamp_close) ?? 0;
				return aTime - bTime;
			});

			const points: ChartPoint[] = [{ time: periodStart.getTime(), value: 0 }];
			sortedTrades.forEach((trade) => {
				const closeMs = toTimestampMs(trade.timestamp_close);
				if (closeMs === null) return;
				cumulative += Number(trade.pnl) || 0;
				points.push({ time: closeMs, value: cumulative });
			});
			return points;
		}

		if (equityData && equityData.length > 1) {
			return equityData.map(([time, value]) => ({ time, value }));
		}

		if (portfolioData?.balance !== undefined) {
			const currentTime = now.getTime();
			return [
				{
					time: periodStart.getTime(),
					value: portfolioData.balance - periodPnl,
				},
				{ time: currentTime, value: portfolioData.balance },
			];
		}

		return [];
	}, [equityData, portfolioData, periodPnl, periodTrades, periodStart, now]);

	const chartColor = isPositive ? "hsl(var(--profit))" : "hsl(var(--loss))";
	const chartGradientId = isPositive ? "gradient-profit" : "gradient-loss";
	const isLoadingValue = isLoadingPnl || isLoadingTrades;

	return (
		<Card className="h-full flex flex-col">
			<CardHeader className="pb-2 flex flex-row items-center justify-between">
				<CardTitle className="text-base font-medium text-foreground">
					{period === "1d"
						? t("index:dailyPnl.title1D")
						: period === "7d"
							? t("index:dailyPnl.title7D")
							: t("index:dailyPnl.titleMTD")}
				</CardTitle>
				<div className="flex space-x-1 bg-muted p-1 rounded-md">
					{periodButtons.map((button) => (
						<button
							key={button.key}
							onClick={() => {
								setRangeNow(new Date());
								window.localStorage.setItem(
									TOTAL_PNL_PERIOD_STORAGE_KEY,
									button.key,
								);
								setPeriod(button.key);
							}}
							className={`px-2 py-0.5 text-xs rounded-sm transition-colors ${
								period === button.key
									? "bg-background text-foreground shadow-sm"
									: "text-muted-foreground hover:bg-background/50"
							}`}
						>
							{button.label}
						</button>
					))}
				</div>
			</CardHeader>
			<CardContent className="flex-grow flex flex-col">
				<div className="mb-2">
					{isLoadingValue && <Skeleton className="h-12 w-3/4" />}
					{isErrorPnl && !isLoadingPnl && (
						<Alert variant="destructive">
							<AlertTriangle className="h-4 w-4" />
							<AlertTitle>{t("common:errorTitle")}</AlertTitle>
							<AlertDescription>{errorPnl?.message}</AlertDescription>
						</Alert>
					)}
					{!isLoadingValue && !isErrorPnl && portfolioData && (
						<div className="space-y-1">
							<div
								className={`text-3xl font-bold mono flex items-center ${isPositive ? "text-profit" : "text-loss"}`}
							>
								{isPositive ? "+" : ""}${periodPnl.toFixed(2)}
							</div>
							<div
								className={`text-sm mono flex items-center ${isPositive ? "text-profit" : "text-loss"}`}
							>
								{isPositive ? (
									<TrendingUp className="h-4 w-4 mr-1" />
								) : (
									<TrendingDown className="h-4 w-4 mr-1" />
								)}
								{isPositive ? "+" : ""}
								{periodPnlPercent.toFixed(2)}%
							</div>
						</div>
					)}
				</div>
				<div className="flex-grow min-h-[100px]">
					{isLoadingEquity && <Skeleton className="h-full w-full" />}

					{!isLoadingEquity && chartData.length > 1 ? (
						<ResponsiveContainer width="100%" height="100%">
							<AreaChart
								data={chartData}
								margin={{ top: 5, right: 0, left: -45, bottom: -10 }}
							>
								<defs>
									<linearGradient
										id="gradient-profit"
										x1="0"
										y1="0"
										x2="0"
										y2="1"
									>
										<stop
											offset="5%"
											stopColor={chartColor}
											stopOpacity={0.4}
										/>
										<stop offset="95%" stopColor={chartColor} stopOpacity={0} />
									</linearGradient>
									<linearGradient
										id="gradient-loss"
										x1="0"
										y1="0"
										x2="0"
										y2="1"
									>
										<stop
											offset="5%"
											stopColor={chartColor}
											stopOpacity={0.4}
										/>
										<stop offset="95%" stopColor={chartColor} stopOpacity={0} />
									</linearGradient>
								</defs>
								<XAxis dataKey="time" hide />
								<YAxis
									domain={[
										"dataMin - (dataMax - dataMin) * 0.1",
										"dataMax + (dataMax - dataMin) * 0.1",
									]}
									hide
								/>
								<Tooltip content={<CustomTooltip />} cursor={false} />
								<Area
									type="monotone"
									dataKey="value"
									stroke={chartColor}
									strokeWidth={2}
									fillOpacity={1}
									fill={`url(#${chartGradientId})`}
								/>
							</AreaChart>
						</ResponsiveContainer>
					) : (
						!isLoadingEquity && (
							<div className="h-full flex items-center justify-center text-xs text-muted-foreground">
								{t("index:dailyPnl.notEnoughDataForChart")}
							</div>
						)
					)}
				</div>
			</CardContent>
		</Card>
	);
}
