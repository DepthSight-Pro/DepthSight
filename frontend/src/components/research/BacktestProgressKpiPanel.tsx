// src/components/research/BacktestProgressKpiPanel.tsx

import type React from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type {
	BacktestKpiResults,
	BacktestRunDetailsData,
	ProgressKpiData,
} from "@/types/api";

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
	colorClass = "text-white",
	isLoading = false,
	description,
}) => (
	<div className="flex items-center justify-between p-2.5 rounded-xl bg-white/[0.02] border border-white/5 hover:border-white/10 transition-colors">
		<div>
			<p className="text-[11px] text-white/50 font-mono uppercase tracking-wider">{label}</p>
			{description && !isLoading && (
				<p className="text-[10px] text-white/30 mt-0.5">{description}</p>
			)}
		</div>
		{isLoading ? (
			<Skeleton className="h-5 w-20 bg-white/5" />
		) : (
			<p className={`font-mono text-sm font-bold ${colorClass}`}>{value}</p>
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

	// Effective live KPIs for loading state (prop wins, else run.progress_info).
	const hasEffectiveLiveKpis = Boolean(liveKpis ?? run.progress_info?.kpis);
	// --- Adding a check for trades ---
	const isLoadingKpis =
		status === "RUNNING" && !hasEffectiveLiveKpis && (!trades || trades.length === 0);

	const progressValue = useMemo(() => {
		if (status === "COMPLETED" || status === "FAILED") return 100;
		if (status === "PENDING") return 0;
		return liveKpis?.progress ?? run.progress_info?.kpis.progress ?? 0;
	}, [status, liveKpis, run.progress_info]);

	const progressText = useMemo(() => {
		switch (status) {
			case "COMPLETED":
				return t("statuses.completed");
			case "FAILED":
				return t("statuses.failed");
			case "RUNNING":
				return `${progressValue.toFixed(1)}%`;
			case "PENDING":
				return t("statuses.pending");
			default:
				return status;
		}
	}, [status, progressValue, t]);

	const displayKpis = useMemo(() => {
		// Backend canonical key is `trades`; accept legacy aliases just in case.
		const finalTrades =
			finalKpis?.trades ??
			(finalKpis as (BacktestKpiResults & Record<string, unknown>) | undefined)
				?.trades_count ??
			(finalKpis as (BacktestKpiResults & Record<string, unknown>) | undefined)
				?.total_trades ??
			0;
		if (status === "COMPLETED" && finalKpis) {
			return {
				isLive: false as const,
				pnl: finalKpis.total_pnl ?? 0,
				tradesCount:
					typeof finalTrades === "number" ? finalTrades : Number(finalTrades) || 0,
				winRate: finalKpis.win_rate ?? 0,
				maxDrawdown: finalKpis.max_drawdown ?? 0,
				totalCommission: finalKpis.total_commission,
				effectiveLiveKpis: undefined as ProgressKpiData | undefined,
			};
		}
		// Effective live KPIs: explicit prop wins, otherwise fall back to the
		// KPIs embedded in run.progress_info (BacktestViewer passes them as the
		// prop, but BacktestLiveViewTab renders the panel without it).
		const effectiveLiveKpis = liveKpis ?? run.progress_info?.kpis;
		if (effectiveLiveKpis) {
			// Backend sends `pnl` / `trades`; accept legacy `current_pnl` /
			// `trades_count` aliases for forward/backward compatibility.
			const liveRecord = effectiveLiveKpis as ProgressKpiData &
				Record<string, unknown>;
			const livePnl = Number(
				effectiveLiveKpis.pnl ?? liveRecord.current_pnl ?? 0,
			);
			const liveTrades = Number(
				effectiveLiveKpis.trades ?? liveRecord.trades_count ?? 0,
			);
			return {
				isLive: true as const,
				pnl: Number.isFinite(livePnl) ? livePnl : 0,
				tradesCount: Number.isFinite(liveTrades) ? liveTrades : 0,
				winRate: effectiveLiveKpis.win_rate ?? 0,
				maxDrawdown: effectiveLiveKpis.max_drawdown ?? 0,
				totalCommission: undefined,
				effectiveLiveKpis,
			};
		}
		// Final fallback: derive the count from the loaded trade list so a
		// completed run with trades never shows "0" due to a KPI key mismatch.
		return {
			isLive: false as const,
			pnl: 0,
			tradesCount: trades?.length ?? 0,
			winRate: 0,
			maxDrawdown: 0,
			totalCommission: undefined,
			effectiveLiveKpis: undefined as ProgressKpiData | undefined,
		};
	}, [status, finalKpis, liveKpis, run.progress_info, trades]);

	const pnlColor =
		displayKpis.pnl > 0
			? "text-emerald-400"
			: displayKpis.pnl < 0
				? "text-rose-400"
				: "text-white/70";
	const pnlPrefix = displayKpis.pnl > 0 ? "+" : "";

	return (
		<div className="h-full rounded-2xl border border-white/10 glass shadow-xl overflow-hidden flex flex-col">
			<div className="p-4 sm:p-6 border-b border-white/5">
				<h2 className="text-base font-bold text-white tracking-tight">
					{displayKpis.isLive
						? t("progressKpiPanel.liveTitle")
						: t("progressKpiPanel.finalTitle")}
				</h2>
				{displayKpis.isLive && displayKpis.effectiveLiveKpis?.current_date && (
					<p className="text-xs text-white/50 mt-1 font-mono">
						{t("progressKpiPanel.asOfDate", {
							date: new Date(
								displayKpis.effectiveLiveKpis.current_date,
							).toLocaleString(currentLocale),
						})}
					</p>
				)}
			</div>
			<div className="p-4 sm:p-6 flex-1 flex flex-col justify-between space-y-4">
				<div>
					<div className="flex justify-between mb-1.5 text-xs font-mono">
						<span className="text-white/50 uppercase tracking-wider">
							{t("progressKpiPanel.statusLabel")}
						</span>
						<span className="font-semibold text-white/90">{progressText}</span>
					</div>
					<Progress
						value={progressValue}
						className="h-2 bg-white/5"
						indicatorClassName={
							status === "FAILED"
								? "bg-rose-500"
								: displayKpis.isLive
									? "bg-gradient-to-r from-azure to-cyan shadow-[0_0_12px_rgba(0,212,255,0.7)]"
									: "bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.7)]"
						}
					/>
					{displayKpis.isLive && (
						<p className="text-[11px] text-white/40 mt-1 text-right font-mono">
							{t("progressKpiPanel.progressComplete", {
								value: progressValue.toFixed(1),
							})}
						</p>
					)}
				</div>
				<div className="space-y-2 pt-2">
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
					{displayKpis.totalCommission != null && (
						<KpiItem
							label={t("progressKpiPanel.totalCommissionLabel")}
							value={`$${displayKpis.totalCommission.toFixed(2)}`}
							colorClass="text-white/60"
							isLoading={isLoadingKpis && !displayKpis.isLive}
							description={t("progressKpiPanel.descCommissionTotal")}
						/>
					)}
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
						colorClass="text-rose-400"
						isLoading={isLoadingKpis && !displayKpis.isLive}
						description={
							displayKpis.isLive
								? t("progressKpiPanel.descMaxDrawdownCurrent")
								: t("progressKpiPanel.descMaxDrawdownOverall")
						}
					/>
				</div>
			</div>
		</div>
	);
};