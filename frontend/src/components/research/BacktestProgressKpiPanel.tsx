// src/components/research/BacktestProgressKpiPanel.tsx

import type React from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type { BacktestRunDetailsData, ProgressKpiData } from "@/types/api";

interface BacktestProgressKpiPanelProps {
	run: BacktestRunDetailsData;
	liveKpis?: ProgressKpiData;
}

const KpiItem: React.FC<{
	label: string;
	value: string | number;
	colorClass?: string;
	isLoading?: boolean;
	description?: string;
}> = ({
	label,
	value,
	colorClass = "text-foreground",
	isLoading = false,
	description,
}) => (
	<div>
		<div className="flex justify-between items-baseline">
			<p className="text-sm text-muted-foreground">{label}</p>
			{isLoading ? (
				<Skeleton className="h-5 w-20" />
			) : (
				<p className={`font-mono font-medium ${colorClass}`}>{value}</p>
			)}
		</div>
		{description && !isLoading && (
			<p className="text-xs text-muted-foreground mt-0.5">{description}</p>
		)}
	</div>
);

export const BacktestProgressKpiPanel: React.FC<
	BacktestProgressKpiPanelProps
> = ({ run, liveKpis }) => {
	const { t } = useTranslation(["research", "common"]);
	const { status, kpi_results_json: finalKpis, trades } = run;
	const currentLocale = t("common:locale", {
		returnObjects: false,
		defaultValue: "en-US",
	});

	// --- Adding a check for trades ---
	const isLoadingKpis =
		status === "RUNNING" && !liveKpis && (!trades || trades.length === 0);

	const progressValue = useMemo(() => {
		if (status === "COMPLETED" || status === "FAILED") return 100;
		if (status === "PENDING") return 0;
		return liveKpis?.progress ?? run.progress_info?.kpis.progress ?? 0;
	}, [status, liveKpis, run.progress_info]);

	// TODO: Consider translating status text if backend provides fixed keys
	// const progressText = status.charAt(0).toUpperCase() + status.slice(1).toLowerCase();
	const progressText = t(`statuses.${status.toLowerCase()}`, {
		defaultValue:
			status.charAt(0).toUpperCase() + status.slice(1).toLowerCase(),
	});

	const displayKpis = useMemo(() => {
		if (status === "RUNNING" && liveKpis) {
			return {
				pnl: liveKpis.pnl,
				tradesCount: liveKpis.trades,
				winRate: liveKpis.win_rate, // Removing * 100 (if liveKpis also comes in percentages)
				maxDrawdown: Math.abs(liveKpis.max_drawdown), // Removing * 100
				current_date: liveKpis.current_date,
				isLive: true,
			};
		}
		if (finalKpis) {
			return {
				pnl: finalKpis.total_pnl,
				tradesCount: finalKpis.trades,
				winRate: finalKpis.win_rate,
				maxDrawdown: Math.abs(finalKpis.max_drawdown),
				totalCommission: finalKpis.total_commission,
				isLive: false,
			};
		}

		// --- Checking that trades exists ---
		if (trades) {
			const calculatedPnl = trades.reduce((sum, trade) => sum + trade.pnl, 0);
			const liveWins = trades.filter((t) => t.pnl > 0).length;
			const calculatedWinRate =
				trades.length > 0 ? (liveWins / trades.length) * 100 : 0;
			return {
				pnl: calculatedPnl,
				tradesCount: trades.length,
				winRate: calculatedWinRate,
				maxDrawdown: 0,
				isLive: status === "RUNNING",
			};
		}

		// Fallback if there is no data at all
		return {
			pnl: 0,
			tradesCount: 0,
			winRate: 0,
			maxDrawdown: 0,
			isLive: status === "RUNNING",
		};
	}, [status, liveKpis, finalKpis, trades]);

	const pnlColor = displayKpis.pnl >= 0 ? "text-profit" : "text-loss";
	const pnlPrefix = displayKpis.pnl >= 0 ? "+" : "";

	return (
		<Card className="h-full">
			<CardHeader>
				<CardTitle>
					{displayKpis.isLive
						? t("progressKpiPanel.liveTitle")
						: t("progressKpiPanel.finalTitle")}
				</CardTitle>
				{displayKpis.isLive && liveKpis?.current_date && (
					<CardDescription>
						{t("progressKpiPanel.asOfDate", {
							date: new Date(liveKpis.current_date).toLocaleString(
								currentLocale,
							),
						})}
					</CardDescription>
				)}
			</CardHeader>
			<CardContent>
				<div className="space-y-4">
					<div>
						<div className="flex justify-between mb-1 text-sm">
							<span className="text-muted-foreground">
								{t("progressKpiPanel.statusLabel")}
							</span>
							<span className="font-mono font-semibold">{progressText}</span>{" "}
							{/* Status text might need translation if not from a fixed set */}
						</div>
						<Progress
							value={progressValue}
							indicatorClassName={
								status === "FAILED"
									? "bg-destructive"
									: displayKpis.isLive
										? "bg-blue-500"
										: ""
							}
						/>
						{displayKpis.isLive && (
							<p className="text-xs text-muted-foreground mt-1 text-right">
								{t("progressKpiPanel.progressComplete", {
									value: progressValue.toFixed(1),
								})}
							</p>
						)}
					</div>
					<div className="space-y-3 pt-2">
						<KpiItem
							label={t("analytics.statNetProfit")}
							value={`${pnlPrefix}$${displayKpis.pnl.toFixed(2)}`}
							colorClass={pnlColor}
							isLoading={isLoadingKpis && !displayKpis.isLive}
							description={
								displayKpis.isLive
									? t("progressKpiPanel.descPnlCurrent")
									: t("progressKpiPanel.descPnlTotal")
							}
						/>
						<KpiItem
							label={t("analytics.statTotalTrades")}
							value={displayKpis.tradesCount}
							isLoading={isLoadingKpis && !displayKpis.isLive}
							description={
								displayKpis.isLive
									? t("progressKpiPanel.descTradesCurrent")
									: t("progressKpiPanel.descTradesTotal")
							}
						/>
						{/* === START: COMMISSION KPI ADDED === */}
						{displayKpis.totalCommission != null && (
							<KpiItem
								label={t("progressKpiPanel.totalCommissionLabel")}
								value={`$${displayKpis.totalCommission.toFixed(2)}`}
								colorClass="text-muted-foreground"
								isLoading={isLoadingKpis && !displayKpis.isLive}
								description={t("progressKpiPanel.descCommissionTotal")}
							/>
						)}
						{/* === END: COMMISSION KPI ADDED === */}
						<KpiItem
							label={t("analytics.statWinRate")}
							value={`${displayKpis.winRate.toFixed(1)}%`}
							isLoading={isLoadingKpis && !displayKpis.isLive}
							description={
								displayKpis.isLive
									? t("progressKpiPanel.descWinRateCurrent")
									: t("progressKpiPanel.descWinRateOverall")
							}
						/>
						<KpiItem
							label={t("progressKpiPanel.maxDrawdownLabel")}
							value={`${displayKpis.maxDrawdown.toFixed(2)}%`}
							colorClass="text-loss"
							isLoading={isLoadingKpis && !displayKpis.isLive}
							description={
								displayKpis.isLive
									? t("progressKpiPanel.descMaxDrawdownCurrent")
									: t("progressKpiPanel.descMaxDrawdownOverall")
							}
						/>
					</div>
				</div>
			</CardContent>
		</Card>
	);
};
