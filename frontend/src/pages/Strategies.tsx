// src/pages/Strategies.tsx

import { formatDistanceToNowStrict } from "date-fns";
import { AnimatePresence, motion } from "framer-motion";
import {
	AlertTriangle,
	Cog,
	Eye,
	FlaskConical,
	Loader2,
	Pencil,
	Play,
	Plus,
	Search,
	Square,
	Trash2,
	TrendingDown,
	TrendingUp,
} from "lucide-react";
import { forwardRef, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

// UI Components
import { PageLayout } from "@/components/layout/PageLayout";
import { ConfirmationModal } from "@/components/shared/ConfirmationModal";
import {
	type BacktestFormData,
	BacktestModal,
} from "@/components/strategies/BacktestModal";
import {
	type LaunchFormData,
	LaunchStrategyModal,
} from "@/components/strategies/LaunchStrategyModal";
import { StrategyDetailsPanel } from "@/components/strategies/StrategyDetailsPanel";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardFooter,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/use-toast";
// API & Types
import {
	useDeleteStrategyConfig,
	useRunBacktest,
	useStartStrategy,
	useStopStrategy,
	useStrategies,
	useStrategyConfigsList,
} from "@/lib/api";
import { useAccountStore } from "@/stores/accountStore";
import type { StrategyConfig, StrategyData } from "@/types/api";

// --- Helper Functions ---
const calculateRuntime = (startTime: string | undefined): string => {
	if (!startTime) return "—";
	try {
		return formatDistanceToNowStrict(new Date(startTime));
	} catch {
		return "N/A";
	}
};

const getStatusColor = (status: string | undefined) => {
	const s = status?.toLowerCase() || "stopped";
	if (s === "running" || s === "active" || s === "in_position")
		return "bg-emerald-500 hover:bg-emerald-600 text-white";
	if (s === "stopped" || s === "paused")
		return "bg-slate-400 hover:bg-slate-500 text-white";
	if (s === "error" || s === "failed")
		return "bg-red-500 hover:bg-red-600 text-white";
	return "bg-slate-400 hover:bg-slate-500 text-white";
};

// --- Export CombinedStrategy for reuse ---
export type CombinedStrategy = StrategyConfig &
	Partial<Omit<StrategyData, "id" | "name">>;
type FilterType = "all" | "running" | "stopped" | "paper" | "live";

// --- Strategy Card Component ---
const StrategyCard = forwardRef<
	HTMLDivElement,
	{
		strategy: CombinedStrategy;
		onView: () => void;
		onStart: () => void;
		onStop: () => void;
		onDelete: () => void;
		onBacktest: () => void;
		isPending: boolean;
	}
>(
	(
		{ strategy, onView, onStart, onStop, onDelete, onBacktest, isPending },
		ref,
	) => {
		const { t } = useTranslation(["strategies", "common"]);
		const isRunning = strategy.status?.toUpperCase() !== "STOPPED";

		return (
			<TooltipProvider>
				<motion.div
					ref={ref}
					layout
					initial={{ opacity: 0, scale: 0.9 }}
					animate={{ opacity: 1, scale: 1 }}
					exit={{ opacity: 0, scale: 0.9 }}
					transition={{ duration: 0.2 }}
				>
					<Card className="h-full flex flex-col hover:shadow-lg transition-all border-2 hover:border-primary/50">
						<CardHeader className="pb-3">
							<div className="flex items-start justify-between gap-2">
								<div className="flex-1 min-w-0">
									<CardTitle className="text-lg truncate">
										{strategy.name}
									</CardTitle>
									<CardDescription className="text-xs mt-1 font-mono truncate">
										{strategy.id}
									</CardDescription>
								</div>
								<div className="flex flex-col gap-1 items-end flex-shrink-0">
									<Badge className={getStatusColor(strategy.status)}>
										{strategy.status?.toUpperCase() || "STOPPED"}
									</Badge>
									<Badge
										variant={
											strategy.mode === "live" ? "destructive" : "secondary"
										}
										className="text-xs"
									>
										{strategy.mode?.toUpperCase() || "PAPER"}
									</Badge>
								</div>
							</div>
							{strategy.description && (
								<p className="text-xs text-muted-foreground mt-2 line-clamp-2">
									{strategy.description}
								</p>
							)}
						</CardHeader>

						<CardContent className="flex-1 space-y-3 pb-3">
							{/* Strategy Type */}
							<div className="flex items-center justify-between text-sm">
								<span className="text-muted-foreground">
									{t("colStrategy")}:
								</span>
								<span className="font-medium">
									{strategy.strategy_name ||
										strategy.config_data?.strategy_name ||
										"N/A"}
								</span>
							</div>

							{/* Symbols */}
							<div className="flex items-center justify-between text-sm">
								<span className="text-muted-foreground">
									{t("colSymbols")}:
								</span>
								<span className="font-medium text-xs truncate max-w-[150px]">
									{strategy.symbol_selection_mode === "STATIC"
										? strategy.symbols?.join(", ") || "N/A"
										: "Dynamic"}
								</span>
							</div>

							{/* PnL */}
							{strategy.pnl != null && (
								<div className="flex items-center justify-between text-sm p-2 rounded-md bg-accent/50">
									<span className="text-muted-foreground font-medium">
										{t("colTotalPnl")}:
									</span>
									<div className="flex items-center gap-1">
										{strategy.pnl! >= 0 ? (
											<TrendingUp className="h-4 w-4 text-emerald-500" />
										) : (
											<TrendingDown className="h-4 w-4 text-red-500" />
										)}
										<span
											className={`font-bold ${strategy.pnl! >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}
										>
											{strategy.pnl! >= 0 ? "+" : ""}
											{strategy.pnl?.toFixed(2)} USDT
										</span>
									</div>
								</div>
							)}

							{/* Runtime */}
							{isRunning && (
								<div className="flex items-center justify-between text-sm">
									<span className="text-muted-foreground">
										{t("colRuntime")}:
									</span>
									<span className="font-medium">
										{calculateRuntime(strategy.started_at)}
									</span>
								</div>
							)}

							{/* Open Positions */}
							{isRunning && strategy.open_positions != null && (
								<div className="flex items-center justify-between text-sm">
									<span className="text-muted-foreground">
										{t("openPositions", "Open Positions")}:
									</span>
									<Badge variant="outline" className="font-medium">
										{strategy.open_positions}
									</Badge>
								</div>
							)}
						</CardContent>

						<CardFooter className="pt-3 border-t flex gap-2 justify-end">
							{/* View Details */}
							<Tooltip>
								<TooltipTrigger asChild>
									<Button
										size="icon"
										onClick={onView}
										className="bg-blue-500/80 hover:bg-blue-600 text-white"
									>
										<Eye className="h-4 w-4" />
									</Button>
								</TooltipTrigger>
								<TooltipContent>
									<p>{t("viewButton", "Details")}</p>
								</TooltipContent>
							</Tooltip>

							{/* Edit */}
							<Tooltip>
								<TooltipTrigger asChild>
									<Button
										size="icon"
										asChild
										className="bg-emerald-500/80 hover:bg-emerald-600 text-white"
									>
										<Link to={`/editor/${strategy.id}`}>
											<Pencil className="h-4 w-4" />
										</Link>
									</Button>
								</TooltipTrigger>
								<TooltipContent>
									<p>{t("editButton", "Edit")}</p>
								</TooltipContent>
							</Tooltip>

							{/* Backtest */}
							<Tooltip>
								<TooltipTrigger asChild>
									<Button
										size="icon"
										onClick={onBacktest}
										disabled={isPending}
										className="bg-purple-500/80 hover:bg-purple-600 text-white"
									>
										<FlaskConical className="h-4 w-4" />
									</Button>
								</TooltipTrigger>
								<TooltipContent>
									<p>{t("backtestTooltip", "Backtest")}</p>
								</TooltipContent>
							</Tooltip>

							{/* Start/Stop Button */}
							{isRunning ? (
								<Tooltip>
									<TooltipTrigger asChild>
										<Button
											size="icon"
											onClick={onStop}
											disabled={isPending}
											className="bg-amber-500/80 hover:bg-amber-600 text-white"
										>
											{isPending ? (
												<Loader2 className="h-4 w-4 animate-spin" />
											) : (
												<Square className="h-4 w-4" />
											)}
										</Button>
									</TooltipTrigger>
									<TooltipContent>
										<p>{t("stopTooltip", "Stop")}</p>
									</TooltipContent>
								</Tooltip>
							) : (
								<Tooltip>
									<TooltipTrigger asChild>
										<Button
											size="icon"
											onClick={onStart}
											disabled={isPending}
											className="bg-emerald-500/80 hover:bg-emerald-600 text-white"
										>
											{isPending ? (
												<Loader2 className="h-4 w-4 animate-spin" />
											) : (
												<Play className="h-4 w-4" />
											)}
										</Button>
									</TooltipTrigger>
									<TooltipContent>
										<p>{t("startTooltip", "Start")}</p>
									</TooltipContent>
								</Tooltip>
							)}

							{/* Delete Button - Only when stopped */}
							{!isRunning && (
								<Tooltip>
									<TooltipTrigger asChild>
										<Button
											size="icon"
											onClick={onDelete}
											disabled={isPending}
											className="bg-red-500/80 hover:bg-red-600 text-white"
										>
											{isPending ? (
												<Loader2 className="h-4 w-4 animate-spin" />
											) : (
												<Trash2 className="h-4 w-4" />
											)}
										</Button>
									</TooltipTrigger>
									<TooltipContent>
										<p>{t("deleteTooltip", "Delete")}</p>
									</TooltipContent>
								</Tooltip>
							)}
						</CardFooter>
					</Card>
				</motion.div>
			</TooltipProvider>
		);
	},
);

// --- Empty State Component ---
const EmptyState = () => {
	const { t } = useTranslation("strategies");
	return (
		<div className="flex flex-col items-center justify-center py-16 text-center">
			<div className="rounded-full bg-primary/10 p-6 mb-4">
				<Cog className="h-12 w-12 text-primary" />
			</div>
			<h3 className="text-xl font-semibold mb-2">
				{t("emptyState.title", "No Strategies Yet")}
			</h3>
			<p className="text-muted-foreground mb-6 max-w-md">
				{t(
					"emptyState.description",
					"Create your first trading strategy to start automating your trading.",
				)}
			</p>
			<Button asChild size="lg" className="bg-primary hover:bg-primary/90">
				<Link to="/editor">
					<Plus className="h-4 w-4 mr-2" />
					{t("createButton", "Create")}
				</Link>
			</Button>
		</div>
	);
};

// --- Main Component ---
export default function Strategies() {
	const { t } = useTranslation(["strategies", "common"]);
	const navigate = useNavigate();
	const { toast } = useToast();

	// Global account filter
	const { selectedApiKeyId } = useAccountStore();

	const { data: liveRunningStrategies = [], isLoading: isLoadingLive } =
		useStrategies({
			mode: "live",
			apiKeyId: selectedApiKeyId,
		});
	const { data: paperRunningStrategies = [], isLoading: isLoadingPaper } =
		useStrategies({ mode: "paper" });
	const {
		data: savedConfigs = [],
		isLoading: isLoadingConfigs,
		isError: isErrorConfigs,
		error: errorConfigs,
	} = useStrategyConfigsList();

	const runningStrategies = useMemo(() => {
		return [...liveRunningStrategies, ...paperRunningStrategies];
	}, [liveRunningStrategies, paperRunningStrategies]);

	const isLoadingRunning = isLoadingLive || isLoadingPaper;
	const { mutate: stopStrategy, isPending: isStopping } = useStopStrategy();
	const { mutate: startStrategy, isPending: isStarting } = useStartStrategy();
	const { mutate: deleteStrategyConfig, isPending: isDeleting } =
		useDeleteStrategyConfig();

	const [selectedStrategyId, setSelectedStrategyId] = useState<string | null>(
		null,
	);
	const [pendingActionId, setPendingActionId] = useState<string | null>(null);
	const [searchQuery, setSearchQuery] = useState("");
	const [filterType, setFilterType] = useState<FilterType>("all");
	const [confirmAction, setConfirmAction] = useState<{
		open: boolean;
		actionType: "stop" | "delete" | null;
		configId: string | null;
		title: string;
		description: string;
	}>({
		open: false,
		actionType: null,
		configId: null,
		title: "",
		description: "",
	});
	const [launchConfig, setLaunchConfig] = useState<{
		open: boolean;
		configId: string | null;
		strategy: CombinedStrategy | null;
	}>({ open: false, configId: null, strategy: null });
	const [backtestConfig, setBacktestConfig] = useState<{
		open: boolean;
		configId: string | null;
		strategy: CombinedStrategy | null;
	}>({ open: false, configId: null, strategy: null });

	const { mutate: runBacktest, isPending: isBacktesting } = useRunBacktest();

	const combinedStrategies = useMemo((): CombinedStrategy[] => {
		if (!savedConfigs) return [];
		const runningMap = new Map(runningStrategies.map((s) => [s.id, s]));
		return savedConfigs.map((config) => {
			const runningData = runningMap.get(config.id);
			return {
				...config,
				...runningData,
				name: config.name,
				status: runningData?.status || "STOPPED",
			};
		});
	}, [savedConfigs, runningStrategies]);

	// Filtering and searching
	const filteredStrategies = useMemo(() => {
		let result = combinedStrategies;

		// Apply search
		if (searchQuery) {
			const query = searchQuery.toLowerCase();
			result = result.filter(
				(s) =>
					s.name.toLowerCase().includes(query) ||
					s.id.toLowerCase().includes(query) ||
					s.config_data.strategy_name?.toLowerCase().includes(query),
			);
		}

		// Apply filter
		if (filterType !== "all") {
			result = result.filter((s) => {
				if (filterType === "running")
					return s.status?.toLowerCase() !== "stopped";
				if (filterType === "stopped")
					return s.status?.toLowerCase() === "stopped";
				if (filterType === "paper") return s.mode === "paper";
				if (filterType === "live") return s.mode === "live";
				return true;
			});
		}

		return result;
	}, [combinedStrategies, searchQuery, filterType]);

	const selectedStrategy = combinedStrategies.find(
		(s) => s.id === selectedStrategyId,
	);

	const strategyForPanel = useMemo(() => {
		if (!selectedStrategy) return null;
		return {
			id: selectedStrategy.id,
			name: selectedStrategy.name,
			strategy_name:
				selectedStrategy.config_data.strategy_name || "Unknown Type",
			symbol:
				selectedStrategy.config_data.symbol ||
				(selectedStrategy.symbols || [])[0] ||
				"N/A",
			market_type:
				selectedStrategy.market_type ||
				selectedStrategy.config_data.marketType ||
				"FUTURES",
			status: selectedStrategy.status || "STOPPED",
			pnl: selectedStrategy.pnl ?? 0,
			open_positions: selectedStrategy.open_positions ?? 0,
			started_at: selectedStrategy.started_at || "",
			params: selectedStrategy.config_data as unknown as Record<
				string,
				unknown
			>, // Always use the full config_data
			mode: selectedStrategy.mode || "paper",
			config_data: selectedStrategy.config_data,
			symbols: selectedStrategy.symbols ?? undefined,
		};
	}, [selectedStrategy]);

	const handleStart = (strategy: CombinedStrategy) => {
		setLaunchConfig({ open: true, configId: strategy.id, strategy });
	};

	const handleBacktest = (strategy: CombinedStrategy) => {
		setBacktestConfig({ open: true, configId: strategy.id, strategy });
	};

	const handleConfirmBacktest = (formData: BacktestFormData) => {
		if (!backtestConfig.strategy) return;

		const configPayload = backtestConfig.strategy.config_data;

		runBacktest(
			{
				strategy_name: configPayload.strategy_name || "VisualBuilderStrategy",
				symbol: formData.symbol,
				market_type: (configPayload.marketType?.toLowerCase() || "futures") as
					| "futures"
					| "spot",
				start_date: formData.startDate,
				end_date: formData.endDate,
				min_foundation_weight_threshold:
					configPayload.min_foundation_weight_threshold,
				foundation_weights: configPayload.foundation_weights,
				params: { config: configPayload },
			},
			{
				onSuccess: (data) => {
					toast({
						title: t("common:successTitle"),
						description: t("common:taskSubmittedWithId", {
							taskId: data.task_id,
						}),
					});
					setBacktestConfig({ open: false, configId: null, strategy: null });
					navigate("/research");
				},
			},
		);
	};

	const handleConfirmStart = (formData: LaunchFormData) => {
		if (!launchConfig.configId) return;

		setPendingActionId(launchConfig.configId);

		// Prepare symbols array
		let symbolsArray: string[] | undefined;
		if (formData.symbolSelectionMode === "STATIC" && formData.symbols) {
			symbolsArray = formData.symbols
				.split(",")
				.map((s) => s.trim())
				.filter(Boolean);
		}

		// Construct dynamic configuration overrides
		const configDataOverrides: Record<string, unknown> = {};
		if (formData.symbolSelectionMode === "DYNAMIC") {
			configDataOverrides.max_concurrent_symbols =
				formData.maxConcurrentSymbols;

			if (formData.dynamicMode === "DYNAMIC_NATR") {
				configDataOverrides.natr_settings = { min_natr: formData.minNatr };
				// Clear oracle settings if switching modes
				configDataOverrides.oracle_settings = null;
				// Reset oracle settings at the top level
				configDataOverrides.oracle_regime = null;
				configDataOverrides.oracle_confidence = 0;
			} else if (formData.dynamicMode === "DYNAMIC_ORACLE") {
				const regime = parseInt(formData.oracleRegime || "1", 10);
				const confidence = formData.oracleConfidence || 95;
				configDataOverrides.oracle_settings = {
					regime: regime,
					confidence: confidence,
				};
				// Synchronize with the top level for compatibility with backtests
				configDataOverrides.oracle_regime = regime;
				configDataOverrides.oracle_confidence = confidence;
				// Clear natr settings if switching modes
				configDataOverrides.natr_settings = null;
			}
		} else {
			// STATIC mode - reset oracle settings
			configDataOverrides.oracle_regime = null;
			configDataOverrides.oracle_confidence = 0;
		}

		// ML & Regime settings - always apply
		configDataOverrides.use_ml_confirmation =
			formData.useMlConfirmation ?? false;
		configDataOverrides.breakeven_on_regime_change =
			formData.breakevenOnRegimeChange ?? false;

		startStrategy(
			{
				configId: launchConfig.configId,
				mode: formData.mode,
				symbol_selection_mode: formData.symbolSelectionMode,
				symbols: symbolsArray,
				// Pass overrides as part of params (which merges into config_data on backend)
				params: configDataOverrides,
				apiKeyId:
					typeof selectedApiKeyId === "number" ? selectedApiKeyId : undefined,
			},
			{
				onSettled: () => {
					setPendingActionId(null);
					setLaunchConfig({ open: false, configId: null, strategy: null });
				},
			},
		);
	};

	const openConfirmationModal = (
		actionType: "stop" | "delete",
		strategy: CombinedStrategy,
	) => {
		const isRunning = strategy.status?.toLowerCase() !== "stopped";
		if (actionType === "delete" && isRunning) return;
		setConfirmAction({
			open: true,
			actionType,
			configId: strategy.id,
			title: t(`confirmation.${actionType}Title`, { name: strategy.name }),
			description: t(`confirmation.${actionType}Description`),
		});
	};

	const handleConfirmAction = () => {
		if (!confirmAction.configId || !confirmAction.actionType) return;
		setPendingActionId(confirmAction.configId);
		const onSettled = () => {
			if (selectedStrategyId === confirmAction.configId)
				setSelectedStrategyId(null);
			setConfirmAction({
				open: false,
				actionType: null,
				configId: null,
				title: "",
				description: "",
			});
			setPendingActionId(null);
		};
		if (confirmAction.actionType === "stop")
			stopStrategy(confirmAction.configId, { onSettled });
		else if (confirmAction.actionType === "delete")
			deleteStrategyConfig(confirmAction.configId, { onSettled });
	};

	const headerActions = (
		<Button asChild>
			<Link to="/editor">
				<Plus className="w-4 h-4 mr-2" />
				{t("createButton")}
			</Link>
		</Button>
	);

	const isLoading = isLoadingConfigs || isLoadingRunning;
	const isActionPending = isStarting || isStopping || isDeleting;

	return (
		<PageLayout title={t("pageTitle")} icon={Cog} headerActions={headerActions}>
			{/* Search and Filters */}
			<div className="mb-6 flex flex-col sm:flex-row gap-4">
				<div className="relative flex-1">
					<Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
					<Input
						placeholder={t("searchPlaceholder", "Search strategies...")}
						value={searchQuery}
						onChange={(e) => setSearchQuery(e.target.value)}
						className="pl-10"
					/>
				</div>
				<div className="flex gap-2 overflow-x-auto pb-2 sm:pb-0">
					{(["all", "running", "stopped", "paper", "live"] as FilterType[]).map(
						(filter) => (
							<Button
								key={filter}
								variant={filterType === filter ? "default" : "outline"}
								size="sm"
								onClick={() => setFilterType(filter)}
								className="whitespace-nowrap"
							>
								{t(
									`filters.${filter}`,
									filter.charAt(0).toUpperCase() + filter.slice(1),
								)}
							</Button>
						),
					)}
				</div>
			</div>

			{/* Content */}
			{isLoading ? (
				<div className="grid gap-6 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
					{[...Array(6)].map((_, i) => (
						<Skeleton key={i} className="h-[320px] w-full" />
					))}
				</div>
			) : isErrorConfigs ? (
				<Alert variant="destructive">
					<AlertTriangle className="h-4 w-4" />
					<AlertTitle>{t("common:errorTitle")}</AlertTitle>
					<AlertDescription>
						{errorConfigs instanceof Error
							? errorConfigs.message
							: t("common:errors.unknownError")}
					</AlertDescription>
				</Alert>
			) : filteredStrategies.length === 0 ? (
				searchQuery || filterType !== "all" ? (
					<div className="text-center py-16">
						<p className="text-muted-foreground">
							{t("noResults", "No strategies found matching your filters.")}
						</p>
					</div>
				) : (
					<EmptyState />
				)
			) : (
				<div className="grid gap-6 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
					<AnimatePresence mode="popLayout">
						{filteredStrategies.map((strategy) => (
							<StrategyCard
								key={strategy.id}
								strategy={strategy}
								onView={() => setSelectedStrategyId(strategy.id)}
								onStart={() => handleStart(strategy)}
								onStop={() => openConfirmationModal("stop", strategy)}
								onDelete={() => openConfirmationModal("delete", strategy)}
								onBacktest={() => handleBacktest(strategy)}
								isPending={isActionPending && pendingActionId === strategy.id}
							/>
						))}
					</AnimatePresence>
				</div>
			)}

			{/* Strategy Details Panel */}
			<AnimatePresence>
				{strategyForPanel && (
					<motion.div
						initial={{ opacity: 0, y: 20 }}
						animate={{ opacity: 1, y: 0 }}
						exit={{ opacity: 0, y: 20 }}
						className="mt-6"
					>
						<StrategyDetailsPanel
							selectedStrategy={strategyForPanel}
							onClose={() => setSelectedStrategyId(null)}
						/>
					</motion.div>
				)}
			</AnimatePresence>

			{/* Modals */}
			<ConfirmationModal
				open={confirmAction.open}
				onOpenChange={(open) => setConfirmAction((prev) => ({ ...prev, open }))}
				title={confirmAction.title}
				description={confirmAction.description}
				onConfirm={handleConfirmAction}
				loading={isStopping || isDeleting}
			/>

			<LaunchStrategyModal
				isOpen={launchConfig.open}
				onClose={() =>
					setLaunchConfig({ open: false, configId: null, strategy: null })
				}
				onConfirm={handleConfirmStart}
				strategyName={launchConfig.strategy?.name}
				isLoading={isStarting}
				currentSymbols={launchConfig.strategy?.symbols || []}
				currentMode={launchConfig.strategy?.symbol_selection_mode}
			/>

			<BacktestModal
				isOpen={backtestConfig.open}
				onClose={() =>
					setBacktestConfig({ open: false, configId: null, strategy: null })
				}
				onConfirm={handleConfirmBacktest}
				strategyName={backtestConfig.strategy?.name}
				isLoading={isBacktesting}
				strategy={backtestConfig.strategy}
			/>
		</PageLayout>
	);
}
