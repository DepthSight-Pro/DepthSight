// src/pages/BacktestViewer.tsx

import {
	AlertCircle,
	ArrowLeft,
	Rocket,
	Share2,
	Target,
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
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/use-toast";
import { useWebSocket } from "@/context/WebSocketProvider";
import { useBacktestRun, useRunOptimization } from "@/lib/api";
import { useAiCopilotStore } from "@/stores/aiCopilotStore";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import type {
	BacktestRunDetailsData,
	BacktestTrade,
	ProgressEventData,
	ProgressInfoData,
	ProgressKpiData,
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
	kpis?: ProgressKpiData;
	equity_point?: [string, number];
	events?: ProgressEventData[];
}

const getBacktestDisplayName = (
	run: BacktestRunDetailsData | null | undefined,
	fallback: string,
): string => {
	const params = run?.parameters_json as Record<string, unknown> | undefined;
	const config = params?.config as Record<string, unknown> | undefined;
	return (
		(params?.name as string | undefined) ||
		(params?.strategy_display_name as string | undefined) ||
		(config?.name as string) ||
		run?.strategy_name ||
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
	const { setWidgetState } = useAiCopilotStore();
	const [tradeForVisualization, setTradeForVisualization] =
		useState<BacktestTrade | null>(null);

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
					events: update.events
						? [...prev.progress_info.events, ...update.events]
						: prev.progress_info.events,
				},
				status: update.kpis
					? update.kpis.progress === 100
						? "COMPLETED"
						: "RUNNING"
					: prev.status,
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
				<div className="flex items-center justify-center h-full">
					<AppLoader size="lg" fullLogo text={t("backtestViewer.loading")} />
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
			<div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
				<div className="lg:col-span-3">
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
				<Card className="mt-6">
					<CardHeader>
						<CardTitle>{t("backtestViewer.nextSteps")}</CardTitle>
						<CardDescription>
							{t("backtestViewer.nextStepsDesc")}
						</CardDescription>
					</CardHeader>
					<CardContent className="flex flex-col sm:flex-row gap-4">
						<TooltipProvider>
							<Tooltip>
								<TooltipTrigger asChild>
									{/* --- The button now controls the global store --- */}
									<Button
										onClick={() => setWidgetState("open")}
										className="w-full relative overflow-hidden bg-gradient-to-r from-purple-500 to-indigo-600 text-white shadow-lg hover:shadow-xl transition-shadow duration-300 ease-in-out before:content-[''] before:absolute before:top-0 before:-left-full before:w-full before:h-full before:bg-gradient-to-r before:from-transparent before:via-white/30 before:to-transparent before:animate-[shimmer_2s_infinite]"
									>
										<WandSparkles className="w-4 h-4 mr-2" />
										{t(
											"backtestViewer.analyzeWithAI",
											"Analyze and improve with AI",
										)}
									</Button>
								</TooltipTrigger>
								<TooltipContent>
									<p>
										{t(
											"backtestViewer.analyzeWithAITooltip",
											"Get insights and suggestions for improvement from the AI assistant.",
										)}
									</p>
								</TooltipContent>
							</Tooltip>
						</TooltipProvider>
						<Button
							className="w-full"
							onClick={handleLaunchOptimization}
							disabled={isOptimizing}
						>
							<Target className="w-4 h-4 mr-2" />
							{t("backtestViewer.optimizeButton")}
						</Button>
						<Button
							className="w-full bg-green-600 hover:bg-green-700"
							onClick={handleDeployStrategy}
						>
							<Rocket className="w-4 h-4 mr-2" />
							{t("backtestViewer.deployButton")}
						</Button>
						<Button
							variant="outline"
							className="w-full"
							onClick={() => setShareDialogOpen(true)}
						>
							<Share2 className="w-4 h-4 mr-2" />
							{t("backtestViewer.shareButton")}
						</Button>
					</CardContent>
				</Card>
			)}

			<Tabs defaultValue="trades" className="w-full mt-6">
				<TabsList className="grid w-full grid-cols-4">
					<TabsTrigger value="trades">
						{t("backtestViewer.tabTradesAndCombinations")}
					</TabsTrigger>
					<TabsTrigger value="summary">
						{t("backtestViewer.tabSummary")}
					</TabsTrigger>
					<TabsTrigger
						value="analytics"
						disabled={displayRun.status !== "COMPLETED"}
					>
						{t("backtestViewer.tabTradeAnalytics", "Trade Analytics")}
					</TabsTrigger>
					<TabsTrigger
						value="structured-analytics"
						disabled={displayRun.status !== "COMPLETED"}
					>
						{t("backtestViewer.tabEventLog", "Event Log")}
					</TabsTrigger>
				</TabsList>

				<TabsContent value="trades" className="mt-4">
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
								onViewTradeOnChart={(trade) => setTradeForVisualization(trade)}
							/>
						</div>
						<div className="h-full xl:col-span-1">
							<Card className="h-full flex flex-col">
								<CardHeader>
									<Tabs defaultValue="combinations" className="w-full">
										<TabsList className="grid w-full grid-cols-2">
											<TabsTrigger value="combinations">
												{t("backtestViewer.tabCombinations")}
											</TabsTrigger>
											<TabsTrigger value="foundations">
												{t("backtestViewer.tabFoundations")}
											</TabsTrigger>
										</TabsList>
										<TabsContent value="combinations" className="mt-4">
											<CombinationsPerformanceTable
												trades={displayRun.trades || []}
											/>
										</TabsContent>
										<TabsContent value="foundations" className="mt-4">
											<FoundationEffectivenessTable
												trades={displayRun.trades || []}
											/>
										</TabsContent>
									</Tabs>
								</CardHeader>
							</Card>
						</div>
					</div>
				</TabsContent>
				<TabsContent value="summary" className="mt-4">
					<TaskSummaryCard run={displayRun} />
				</TabsContent>
				<TabsContent value="analytics" className="mt-4">
					{displayRun.status === "COMPLETED" ? (
						<BacktestAnalyticsTab run={displayRun} />
					) : (
						<div className="text-center text-muted-foreground p-8">
							{t("analytics.analyticsNotAvailable")}
						</div>
					)}
				</TabsContent>

				<TabsContent value="structured-analytics" className="mt-4">
					{displayRun.status === "COMPLETED" ? (
						<BacktestStructuredAnalyticsTab run={displayRun} />
					) : (
						<div className="text-center text-muted-foreground p-8">
							{t("analytics.analyticsNotAvailable")}
						</div>
					)}
				</TabsContent>
			</Tabs>
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
