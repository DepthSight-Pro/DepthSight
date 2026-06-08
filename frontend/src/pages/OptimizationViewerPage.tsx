// src/pages/OptimizationViewerPage.tsx

import {
	AlertCircle,
	ArrowLeft,
	FlaskConical,
	Loader2,
	PencilRuler,
	Target,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PageLayout } from "@/components/layout/PageLayout";
import { OptimizationHistoryChart } from "@/components/research/OptimizationHistoryChart";
import { OptimizationKpiPanel } from "@/components/research/OptimizationKpiPanel";
import { ParameterImportanceChart } from "@/components/research/ParameterImportanceChart";
import { TrialsTable } from "@/components/research/TrialsTable";
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
import { useToast } from "@/components/ui/use-toast";
import { useOptimizationRun, useRunBacktest } from "@/lib/api";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import type { OptimizationResultsData } from "@/types/api";
import NotFound from "./NotFound";

function isOptimizationResults(
	results: unknown,
): results is OptimizationResultsData {
	return !!(
		results &&
		typeof results === "object" &&
		("best_trial" in results || "trials" in results)
	);
}

const OptimizationViewerPage = () => {
	const { runId } = useParams<{ runId: string }>();
	const { t } = useTranslation(["research", "common"]);
	const navigate = useNavigate();
	const { toast } = useToast();
	const { data: run, isLoading, isError, error } = useOptimizationRun(runId!);

	const { mutate: launchBacktest, isPending: isBacktesting } = useRunBacktest();
	const loadDiscoveredStrategy = useStrategyEditorStore(
		(state) => state.loadDiscoveredStrategy,
	);

	const handleBacktestBestParams = () => {
		if (!run || !isOptimizationResults(run.results)) {
			toast({
				variant: "destructive",
				title: t("common:errorTitle"),
				description: t("optimizationViewer.errors.resultsNotAvailable"),
			});
			return;
		}
		const bestParams = run.results.best_params;

		if (!bestParams || !run?.request_params) {
			toast({
				variant: "destructive",
				title: t("common:errorTitle"),
				description: t("optimizationViewer.errors.bestParamsNotAvailable"),
			});
			return;
		}

		launchBacktest(
			{
				strategy_name: run.request_params.strategy_name,
				symbol: run.request_params.symbol,
				start_date: run.request_params.start_date,
				end_date: run.request_params.end_date,
				market_type:
					((run.request_params as unknown as Record<string, unknown>)
						.market_type as "spot" | "futures") || "futures",
				params: bestParams,
			},
			{
				onSuccess: (data) => {
					toast({
						title: t("optimizationViewer.toastBacktestStarted"),
						description: t("common:taskSubmittedWithId", {
							taskId: data.task_id,
						}),
					});
					navigate("/research");
				},
			},
		);
	};

	const handleLoadBestInEditor = () => {
		if (!run || !isOptimizationResults(run.results)) {
			toast({
				variant: "destructive",
				title: t("common:errorTitle"),
				description: t("optimizationViewer.errors.resultsNotAvailable"),
			});
			return;
		}
		const bestParams = run.results.best_params;

		if (
			bestParams &&
			run?.request_params &&
			"strategy_name" in run.request_params
		) {
			const discoveredStrategy = {
				name: `${run.request_params.strategy_name}${t("optimizationViewer.optimizedSuffix")}`,
				symbol: run.request_params.symbol,
				...bestParams,
			};
			loadDiscoveredStrategy(discoveredStrategy);
			navigate("/strategies/editor");
			toast({
				title: t("optimizationViewer.toastParamsLoaded"),
				description: t("common:loadedToEditor"),
			});
		} else {
			toast({
				variant: "destructive",
				title: t("common:errorTitle"),
				description: t("optimizationViewer.errors.noBestParamsToLoad"),
			});
		}
	};

	const headerActions = (
		<Button asChild variant="outline" size="sm">
			<Link to="/research">
				<ArrowLeft className="w-4 h-4 mr-2" />
				{t("backtestViewer.backButton")}
			</Link>
		</Button>
	);

	const pageTitleWhileLoading = t("optimizationViewer.pageTitle", {
		name: "...",
	});

	if (isLoading && !run) {
		return (
			<PageLayout title={pageTitleWhileLoading} headerActions={headerActions}>
				<div className="flex items-center justify-center h-full">
					<Loader2 className="w-8 h-8 animate-spin text-primary" />
					<span className="ml-4 text-lg">
						{t("optimizationViewer.loading")}
					</span>
				</div>
			</PageLayout>
		);
	}

	if (isError) {
		return (
			<PageLayout title={pageTitleWhileLoading} headerActions={headerActions}>
				<Alert variant="destructive">
					<AlertCircle className="h-4 w-4" />
					<AlertTitle>{t("optimizationViewer.error")}</AlertTitle>
					<AlertDescription>
						{error?.message ?? t("common:errors.unknownError")}
					</AlertDescription>
				</Alert>
			</PageLayout>
		);
	}

	if (!run) {
		return <NotFound />; // NotFound page should also be internationalized later
	}

	const optimizationResults = isOptimizationResults(run.results)
		? run.results
		: null;
	const pageTitle = t("optimizationViewer.pageTitle", {
		name: run.request_params?.strategy_name || t("common:na"),
	});

	return (
		<PageLayout title={pageTitle} icon={Target} headerActions={headerActions}>
			<div className="h-full flex flex-col space-y-6">
				<OptimizationKpiPanel run={run} />

				<Tabs defaultValue="overview" className="flex-grow min-h-0">
					<TabsList className="grid w-full grid-cols-3">
						<TabsTrigger value="overview">
							{t("optimizationViewer.tabOverview")}
						</TabsTrigger>
						<TabsTrigger value="trials">
							{t("optimizationViewer.tabTrials")}
						</TabsTrigger>
						<TabsTrigger value="best_result">
							{t("optimizationViewer.tabBestResult")}
						</TabsTrigger>
					</TabsList>

					<TabsContent value="overview" className="mt-4">
						<div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
							<OptimizationHistoryChart
								trials={optimizationResults?.trials || []}
								bestTrialId={optimizationResults?.best_trial?.trial_number}
							/>
							<ParameterImportanceChart
								importanceData={
									optimizationResults?.parameter_importance || null
								}
							/>
						</div>
					</TabsContent>

					<TabsContent value="trials" className="mt-4 h-full">
						<TrialsTable trials={optimizationResults?.trials || []} />
					</TabsContent>

					<TabsContent value="best_result" className="mt-4">
						<Card>
							<CardHeader>
								<CardTitle>
									{t("optimizationViewer.bestResultTitle", {
										trial:
											optimizationResults?.best_trial?.trial_number || "N/A",
									})}
								</CardTitle>
								<CardDescription>
									{t("optimizationViewer.bestResultDesc", {
										score:
											optimizationResults?.best_trial?.value?.toFixed(4) ||
											"N/A",
									})}
								</CardDescription>
							</CardHeader>
							<CardContent className="space-y-4">
								{optimizationResults?.best_params ? (
									<>
										<pre className="p-4 bg-muted rounded-md text-sm font-mono whitespace-pre-wrap">
											{JSON.stringify(optimizationResults.best_params, null, 2)}
										</pre>
										<div className="flex flex-col md:flex-row gap-4 pt-4 border-t">
											<Button
												className="flex-1"
												onClick={handleBacktestBestParams}
												disabled={isBacktesting}
											>
												{isBacktesting ? (
													<Loader2 className="w-4 h-4 mr-2 animate-spin" />
												) : (
													<FlaskConical className="w-4 h-4 mr-2" />
												)}
												{t("optimizationViewer.backtestBestButton")}
											</Button>
											<Button
												className="flex-1"
												onClick={handleLoadBestInEditor}
											>
												<PencilRuler className="w-4 h-4 mr-2" />
												{t("optimizationViewer.loadInEditorButton")}
											</Button>
										</div>
									</>
								) : (
									<p className="text-muted-foreground">
										{t("optimizationViewer.noBestTrial")}
									</p>
								)}
							</CardContent>
						</Card>
					</TabsContent>
				</Tabs>
			</div>
		</PageLayout>
	);
};

export default OptimizationViewerPage;
