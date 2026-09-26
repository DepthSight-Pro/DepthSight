// src/pages/BacktestViewer.tsx

import {
	AlertCircle,
	ArrowLeft,
	Rocket,
	Share2,
	Sparkles,
	Target,
	TrendingUp,
	WandSparkles,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { TradeAnalysisModal } from "@/components/analytics/TradeAnalysisModal";
import { PageLayout } from "@/components/layout/PageLayout";
import { BacktestAnalyticsTab } from "@/components/research/BacktestAnalyticsTab";
import { BacktestProgressKpiPanel } from "@/components/research/BacktestProgressKpiPanel";
import { BacktestStructuredAnalyticsTab } from "@/components/research/BacktestStructuredAnalyticsTab";
import { BacktestTradeHistoryTable } from "@/components/research/BacktestTradeHistoryTable";
import { CombinationsPerformanceTable } from "@/components/research/CombinationsPerformanceTable";
import { EquityCurveChart } from "@/components/research/EquityCurveChart";
import { FoundationEffectivenessTable } from "@/components/research/FoundationEffectivenessTable";
import { ShareBacktestDialog } from "@/components/research/ShareBacktestDialog";
import { TaskSummaryCard } from "@/components/research/TaskSummaryCard";
import { AppLoader } from "@/components/shared/AppLoader";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/quant-ui";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/use-toast";
import { useWebSocket } from "@/context/WebSocketProvider";
import { useBacktestRun, useRunOptimization } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAiCopilotStore } from "@/stores/aiCopilotStore";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import type {
	BacktestRunDetailsData,
	BacktestTrade,
	ProgressEventData,
	ProgressInfoData,
	ProgressKpiData,
	StrategyConfigData,
	TradeData,
} from "@/types/api";
import NotFound from "./NotFound";

// Types for WebSocket
interface LiveProgressData {
	progress_info: ProgressInfoData;
	equity_curve_json: [number, number][];
	status: BacktestRunDetailsData["status"];
}

interface BacktestUpdatePayload {
	run_id: string;
	status?: BacktestRunDetailsData["status"];
	equity_point?: [string, number];
	kpis?: ProgressKpiData;
	event?: ProgressEventData;
}

const getBacktestDisplayName = (
	run: BacktestRunDetailsData | null,
	fallback: string,
): string => {
	if (!run) return fallback;
	return (
		((run.parameters_json?.config as unknown as Record<string, unknown>)
			?.name as string) ||
		run.name ||
		run.task_id ||
		fallback
	);
};

const BacktestViewerPage = () => {
	const { runId } = useParams<{ runId: string }>();
	const { t } = useTranslation(["research", "common"]);
	const navigate = useNavigate();
	const { toast } = useToast();

	const { data: run, isLoading, isError, error } = useBacktestRun(runId!);
	const { subscribe, unsubscribe } = useWebSocket();
	const { loadStrategy } = useStrategyEditorStore();
	const { isPending: isOptimizing } = useRunOptimization();
	const [isShareDialogOpen, setShareDialogOpen] = useState(false);
	const { widgetState, setWidgetState } = useAiCopilotStore();
	const [tradeForVisualization, setTradeForVisualization] =
		useState<BacktestTrade | null>(null);
	const [bottomTab, setBottomTab] = useState<
		"trades" | "summary" | "analytics" | "structured-analytics"
	>("trades");
	const [subTab, setSubTab] = useState<"combinations" | "foundations">(
		"combinations",
	);

	const [prevRunId, setPrevRunId] = useState<string | null>(null);
	const [liveProgress, setLiveProgress] = useState<LiveProgressData | null>(
		null,
	);

	if (runId !== prevRunId) {
		setPrevRunId(runId || null);
		setLiveProgress(null);
	}

	if (run && !liveProgress && runId === prevRunId) {
		setLiveProgress({
			status: run.status,
			equity_curve_json: run.equity_curve_json || [],
			progress_info: run.progress_info || {
				kpis: {} as ProgressKpiData,
				events: [],
			},
		});
	}

	const handleBacktestUpdate = useCallback((payload: unknown) => {
		const update = payload as BacktestUpdatePayload;
		setLiveProgress((prev) => {
			if (!prev) return null;
			const newEquityPoint: [number, number] | undefined = update.equity_point
				? [new Date(update.equity_point[0]).getTime(), update.equity_point[1]]
				: undefined;

			return {
				equity_curve_json: newEquityPoint
					? [...prev.equity_curve_json, newEquityPoint]
					: prev.equity_curve_json,
				progress_info: {
					kpis: update.kpis || prev.progress_info.kpis,
					events: update.event
						? [...prev.progress_info.events, update.event]
						: prev.progress_info.events,
				},
				status: update.status || prev.status,
			};
		});
	}, []);

	useEffect(() => {
		const taskId = run?.task_id;
		if (!taskId || !runId) return;
		const channel = `backtest-progress:${taskId}`;
		subscribe(channel, handleBacktestUpdate);
		return () => {
			unsubscribe(channel, handleBacktestUpdate);
		};
	}, [runId, run?.task_id, subscribe, unsubscribe, handleBacktestUpdate]);

	const displayRun = useMemo<BacktestRunDetailsData | null>(() => {
		if (!run) return null;
		if (
			(run.status === "RUNNING" || run.status === "PENDING") &&
			liveProgress
		) {
			return {
				...run,
				status: liveProgress.status,
				equity_curve_json: liveProgress.equity_curve_json,
				progress_info: liveProgress.progress_info,
			};
		}
		return run;
	}, [run, liveProgress]);

	const mainTabOptions = useMemo(
		() => [
			{
				value: "trades" as const,
				label: t("backtestViewer.tabTradesAndCombinations"),
			},
			{
				value: "summary" as const,
				label: t("backtestViewer.tabSummary"),
			},
			{
				value: "analytics" as const,
				label: t("backtestViewer.tabTradeAnalytics", "Trade Analytics"),
				disabled: displayRun?.status !== "COMPLETED",
			},
			{
				value: "structured-analytics" as const,
				label: t("backtestViewer.tabEventLog", "Event Log"),
				disabled: displayRun?.status !== "COMPLETED",
			},
		],
		[t, displayRun?.status],
	);

	const subTabOptions = useMemo(
		() => [
			{
				value: "combinations" as const,
				label: t("backtestViewer.tabCombinations"),
			},
			{
				value: "foundations" as const,
				label: t("backtestViewer.tabFoundations"),
			},
		],
		[t],
	);

	const handleDeployStrategy = () => {
		const strategyConfig = displayRun?.parameters_json?.config;
		if (strategyConfig) {
			const newName =
				((strategyConfig as unknown as Record<string, unknown>)
					.name as string) ||
				getBacktestDisplayName(displayRun, "Loaded Strategy");
			const configToLoad = {
				...strategyConfig,
				name: newName.includes("(from Backtest)")
					? newName
					: `${newName} (from Backtest)`,
			};
			loadStrategy(configToLoad);
			toast({
				title: t("backtestViewer.toastStrategyLoaded"),
				description: t("common:loadedToEditor"),
			});
			navigate("/editor");
		} else {
			toast({
				variant: "destructive",
				title: t("common:errorTitle"),
				description: t("backtestViewer.toastConfigNotFound"),
			});
		}
	};

	const handleLaunchOptimization = () => {
		if (!displayRun) return;
		const strategyConfig =
			(displayRun.parameters_json?.config as StrategyConfigData) ||
			({} as StrategyConfigData);
		const marketType =
			(strategyConfig.marketType?.toLowerCase() as "futures" | "spot") ??
			"futures";

		navigate("/research", {
			state: {
				seedStrategy: strategyConfig,
				symbol: displayRun.symbol,
				start_date: displayRun.start_date,
				end_date: displayRun.end_date,
				market_type: marketType,
			},
		});
	};

	const headerActions = (
		<Button asChild variant="outline" size="sm">
			<Link to="/research">
				<ArrowLeft className="w-4 h-4 mr-2" />
				{t("backtestViewer.backButton")}
			</Link>
		</Button>
	);

	const displayRunName = getBacktestDisplayName(displayRun, t("common:na"));
	const pageTitle = displayRun
		? t("backtestViewer.pageTitle", { name: displayRunName })
		: t("backtestViewer.loading");

	if (isLoading) {
		return (
			<PageLayout title={pageTitle} headerActions={headerActions}>
				<div className="flex-1 flex flex-col items-center justify-center min-h-[calc(100vh-220px)] h-full w-full">
					<AppLoader size="xl" fullLogo text={t("backtestViewer.loading")} />
				</div>
			</PageLayout>
		);
	}

	if (isError) {
		return (
			<PageLayout
				title={t("backtestViewer.error")}
				headerActions={headerActions}
			>
				<Alert variant="destructive">
					<AlertCircle className="h-4 w-4" />
					<AlertTitle>{t("common:errorTitle")}</AlertTitle>
					<AlertDescription>
						{error?.message ?? t("common:errors.unknownError")}
					</AlertDescription>
				</Alert>
			</PageLayout>
		);
	}

	if (!displayRun) {
		return <NotFound />;
	}

	return (
		<PageLayout
			title={pageTitle}
			icon={WandSparkles}
			headerActions={headerActions}
		>
			<div className="grid grid-cols-1 lg:grid-cols-5 gap-4 sm:gap-6">
				<div className="lg:col-span-3 rounded-2xl border border-white/10 glass shadow-xl p-4 sm:p-6">
					<div className="flex items-center justify-between pb-4 mb-4 border-b border-white/5">
						<div className="flex items-center gap-2.5">
							<div className="flex h-7 w-7 items-center justify-center rounded-lg bg-cyan/10 border border-cyan/25 text-cyan">
								<TrendingUp size={15} />
							</div>
							<div>
								<h3 className="text-sm font-semibold text-white tracking-wide">
									{t("research:backtestViewer.equityCurveTitle", "Equity Curve")}
								</h3>
								<p className="text-[11px] text-white/40 font-mono">
									{displayRun.symbol} • {displayRun.timeframe}
								</p>
							</div>
						</div>
					</div>
					<EquityCurveChart run={displayRun} />
				</div>
				<div className="lg:col-span-2">
					<BacktestProgressKpiPanel
						run={displayRun}
						liveKpis={displayRun.progress_info?.kpis}
					/>
				</div>
			</div>

			{displayRun.status === "COMPLETED" && (
				<div className="mt-6 rounded-2xl border border-white/10 glass shadow-xl p-4 sm:p-6">
					<div className="mb-4">
						<h3 className="text-sm font-semibold text-white tracking-wide">
							{t("backtestViewer.nextSteps")}
						</h3>
						<p className="text-xs text-white/45 mt-0.5">
							{t("backtestViewer.nextStepsDesc")}
						</p>
					</div>
					<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
						<TooltipProvider>
							<Tooltip>
								<TooltipTrigger asChild>
									<button
										type="button"
										onClick={() =>
											setWidgetState(
												widgetState === "open" ? "minimized" : "open",
											)
										}
										className={cn(
											"group relative flex h-10 w-full items-center justify-center gap-2 overflow-hidden rounded-xl px-4 text-xs font-semibold text-white transition-all cursor-pointer",
											widgetState === "open"
												? "bg-white/10 border border-cyan/40 text-cyan shadow-[0_0_15px_-3px_rgba(0,212,255,0.5)]"
												: "bg-gradient-to-r from-azure to-cyan shadow-[0_0_20px_-5px_rgba(0,212,255,0.85)] hover:shadow-[0_0_28px_-3px_rgba(0,212,255,1)] hover:brightness-110",
										)}
									>
										<span className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
										<Sparkles size={14} className="animate-pulse" />
										<span>
											{t(
												"backtestViewer.analyzeWithAI",
												"Analyze and improve with AI",
											)}
										</span>
									</button>
								</TooltipTrigger>
								<TooltipContent className="bg-popover dark:bg-[#0b0f17] border-border dark:border-white/10 text-popover-foreground dark:text-white/80 text-xs">
									<p>
										{t(
											"backtestViewer.analyzeWithAITooltip",
											"Get insights and suggestions for improvement from the AI assistant.",
										)}
									</p>
								</TooltipContent>
							</Tooltip>
						</TooltipProvider>

						<button
							type="button"
							onClick={handleLaunchOptimization}
							disabled={isOptimizing}
							className="flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 text-xs font-semibold text-white/80 transition-all hover:bg-white/[0.08] hover:text-white disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
						>
							<Target size={14} className="text-cyan" />
							<span>{t("backtestViewer.optimizeButton")}</span>
						</button>

						<button
							type="button"
							onClick={handleDeployStrategy}
							className="flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 text-xs font-semibold text-emerald-400 shadow-[0_0_15px_-4px_rgba(16,224,160,0.25)] transition-all hover:bg-emerald-500/20 hover:brightness-110 cursor-pointer"
						>
							<Rocket size={14} />
							<span>{t("backtestViewer.deployButton")}</span>
						</button>

						<button
							type="button"
							onClick={() => setShareDialogOpen(true)}
							className="flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 text-xs font-semibold text-white/80 transition-all hover:bg-white/[0.08] hover:text-white cursor-pointer"
						>
							<Share2 size={14} />
							<span>{t("backtestViewer.shareButton")}</span>
						</button>
					</div>
				</div>
			)}

			<div className="w-full mt-6 space-y-4">
				<div className="overflow-x-auto pb-1 max-w-full">
					<Segmented<"trades" | "summary" | "analytics" | "structured-analytics">
						value={bottomTab}
						onChange={setBottomTab}
						size="md"
						options={mainTabOptions}
					/>
				</div>

				{bottomTab === "trades" && (
					<div className="grid grid-cols-1 xl:grid-cols-3 gap-6 h-full">
						<div className="h-full xl:col-span-2">
							<BacktestTradeHistoryTable
								runId={displayRun.id}
								status={
									displayRun.status.toLowerCase() as
										| "pending"
										| "running"
										| "completed"
										| "failed"
								}
								onViewTradeOnChart={(trade) =>
									setTradeForVisualization(trade)
								}
							/>
						</div>
						<div className="h-full xl:col-span-1">
							<div className="rounded-2xl border border-white/10 glass shadow-xl p-4 sm:p-5 h-full flex flex-col">
								<div className="pb-3 mb-3 border-b border-white/5">
									<Segmented<"combinations" | "foundations">
										value={subTab}
										onChange={setSubTab}
										size="sm"
										options={subTabOptions}
										className="w-full justify-center"
									/>
								</div>
								<div className="flex-1 overflow-x-auto">
									{subTab === "combinations" && (
										<CombinationsPerformanceTable
											trades={displayRun.trades || []}
										/>
									)}
									{subTab === "foundations" && (
										<FoundationEffectivenessTable
											trades={displayRun.trades || []}
										/>
									)}
								</div>
							</div>
						</div>
					</div>
				)}

				{bottomTab === "summary" && (
					<TaskSummaryCard run={displayRun} />
				)}

				{bottomTab === "analytics" &&
					(displayRun.status === "COMPLETED" ? (
						<BacktestAnalyticsTab run={displayRun} />
					) : (
						<div className="rounded-2xl border border-white/10 glass p-12 text-center text-white/40 font-mono text-xs">
							{t("analytics.analyticsNotAvailable")}
						</div>
					))}

				{bottomTab === "structured-analytics" &&
					(displayRun.status === "COMPLETED" ? (
						<BacktestStructuredAnalyticsTab run={displayRun} />
					) : (
						<div className="rounded-2xl border border-white/10 glass p-12 text-center text-white/40 font-mono text-xs">
							{t("analytics.analyticsNotAvailable")}
						</div>
					))}
			</div>
			<ShareBacktestDialog
				open={isShareDialogOpen}
				onOpenChange={setShareDialogOpen}
				runId={displayRun.id}
			/>
			{/* --- Rendering the deal analysis modal window --- */}
			{tradeForVisualization && (
				<TradeAnalysisModal
					trade={
						{
							...tradeForVisualization,
							trade_uuid: String(tradeForVisualization.id),
							symbol: displayRun.symbol,
							timestamp_entry: new Date(
								tradeForVisualization.timestamp_entry,
							).getTime(),
							timestamp_close: new Date(
								tradeForVisualization.timestamp_exit,
							).getTime(),
							signal_details_json:
								tradeForVisualization.decision_trace_json || undefined,
							trade_mode: "PAPER",
							tick_size: displayRun.tick_size,
						} as unknown as TradeData
					}
					relatedTrades={
						displayRun.trades?.map((t) => ({
							...t,
							trade_uuid: String(t.id),
							symbol: displayRun.symbol,
							timestamp_entry: new Date(t.timestamp_entry).getTime(),
							timestamp_close: new Date(t.timestamp_exit).getTime(),
							signal_details_json: t.decision_trace_json || undefined,
							trade_mode: "PAPER",
							tick_size: displayRun.tick_size,
						})) as unknown as TradeData[]
					}
					strategyConfig={displayRun.parameters_json?.config}
					onClose={() => setTradeForVisualization(null)}
					runId={displayRun.id}
				/>
			)}
		</PageLayout>
	);
};

export default BacktestViewerPage;
