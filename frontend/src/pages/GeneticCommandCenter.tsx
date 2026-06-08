// src/pages/GeneticCommandCenter.tsx

import {
	Activity,
	Dna,
	Play,
	RefreshCw,
	Settings,
	Square,
	Terminal,
	Trophy,
} from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import DNAArchitectureModule from "@/components/genetic-command-center/DNAArchitectureModule";
import EvolutionMonitor from "@/components/genetic-command-center/EvolutionMonitor";
import ExecutionRiskModule from "@/components/genetic-command-center/ExecutionRiskModule";
import FitnessLabModule from "@/components/genetic-command-center/FitnessLabModule";
import HallOfFame from "@/components/genetic-command-center/HallOfFame";
import SeedStrategySelector from "@/components/genetic-command-center/SeedStrategySelector";
// Modules
import UniverseDataModule from "@/components/genetic-command-center/UniverseDataModule";
// Platform Components
import { PageLayout } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/use-toast";
// WebSocket
import { useWebSocket } from "@/context/WebSocketProvider";
// API Hooks
import {
	useFoundStrategies,
	useGeneticRunDetails,
	useGeneticRuns,
	useRunGeneticSearch,
	useStopGeneticRun,
} from "@/lib/api";
// Types
import type { EvolutionState } from "@/types/genetic-types";
import {
	DEFAULT_DNA_CONFIG,
	DEFAULT_EXECUTION_CONFIG,
	DEFAULT_FITNESS_CONFIG,
	DEFAULT_SEED_CONFIG,
	DEFAULT_UNIVERSE_CONFIG,
	type DNAArchitectureConfig,
	type ExecutionRiskConfig,
	type FitnessLabConfig,
	type SeedConfig,
	type UniverseDataConfig,
} from "@/types/genetic-types";

// Genetic progress update type from WebSocket
interface GeneticProgressUpdate {
	generation: number;
	best_fitness: number;
	avg_fitness: number;
	status_message?: string;
}

// Helper to get API base URL (borrowed from SimulationTab.tsx)
const getApiBase = () => {
	return import.meta.env.VITE_PUBLIC_API_URL || "";
};

const GeneticCommandCenter: React.FC = () => {
	const { t } = useTranslation(["discovery", "common"]);
	const { toast } = useToast();
	const location = useLocation();
	const [activeTab, setActiveTab] = useState<string>("config");
	const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
	const [availableAssets, setAvailableAssets] = useState<string[]>([]); // New state for backend assets
	const prevDetailsRunIdRef = useRef<string | null>(null);

	const { data: geneticRuns, isLoading: runsLoading } = useGeneticRuns();

	const activeRunId = useMemo(() => {
		if (selectedRunId) return selectedRunId;
		if (geneticRuns && geneticRuns.length > 0) {
			const running = geneticRuns.find(
				(r) => r.status === "RUNNING" || r.status === "PENDING",
			);
			return running ? running.id : geneticRuns[0].id;
		}
		return null;
	}, [selectedRunId, geneticRuns]);

	const setActiveRunId = setSelectedRunId;

	const { data: runDetails } = useGeneticRunDetails(activeRunId);
	const { data: foundStrategies, isLoading: strategiesLoading } =
		useFoundStrategies(activeRunId, {
			enabled: !!activeRunId,
			refetchInterval:
				runDetails?.status === "RUNNING" || runDetails?.status === "PENDING"
					? 10000
					: false, // Update every 10 sec while running
		});
	const startMutation = useRunGeneticSearch();
	const stopMutation = useStopGeneticRun();

	// === Config State (to be passed to API) ===
	const [runName, setRunName] = useState<string>("");
	const [fitnessConfig, setFitnessConfig] = useState<FitnessLabConfig>(
		DEFAULT_FITNESS_CONFIG,
	);
	const [universeConfig, setUniverseConfig] = useState<UniverseDataConfig>(
		DEFAULT_UNIVERSE_CONFIG,
	);
	const [dnaConfig, setDnaConfig] =
		useState<DNAArchitectureConfig>(DEFAULT_DNA_CONFIG);
	const [executionConfig, setExecutionConfig] = useState<ExecutionRiskConfig>(
		DEFAULT_EXECUTION_CONFIG,
	);
	const [seedConfig, setSeedConfig] = useState<SeedConfig>(() => {
		if (location.state?.seedStrategy) {
			return {
				mode: "upload",
				strategies: [location.state.seedStrategy],
				topN: 1,
				keepStructure: true,
				runId: "",
			};
		}
		return DEFAULT_SEED_CONFIG;
	});

	// Intercept incoming seed strategy from Editor or other pages
	useEffect(() => {
		if (location.state?.seedStrategy) {
			// Show a welcoming notification toast
			toast({
				title: t(
					"gcc.toastSeedLoadedTitle",
					"Strategy Loaded for Optimization",
				),
				description: t(
					"gcc.toastSeedLoadedDesc",
					"We've prefilled the Genetics Laboratory with your visual strategy configuration.",
				),
			});

			// Clear history state to avoid reload pre-fill
			window.history.replaceState({}, document.title);
		}
	}, [location.state, toast, t]);

	// Fetch available assets on mount
	useEffect(() => {
		let isMounted = true;
		const fetchAssets = async () => {
			try {
				const response = await fetch(`${getApiBase()}/api/simulation/assets`);
				const data = await response.json();
				if (isMounted) {
					const assets = data.assets || [];
					setAvailableAssets(assets);
					// Auto-select all assets by default only if not already set
					setUniverseConfig((prev) => {
						if (prev.assets.length === 0 && assets.length > 0) {
							return { ...prev, assets };
						}
						return prev;
					});
				}
			} catch (err) {
				console.error("Failed to fetch assets:", err);
			}
		};
		fetchAssets();
		return () => {
			isMounted = false;
		};
	}, []);

	// Convenience accessor for weights (backward compatibility)
	const weights = fitnessConfig.weights;

	// === Build Evolution State from API data ===
	const evoState: EvolutionState = {
		isRunning:
			runDetails?.status === "RUNNING" || runDetails?.status === "PENDING",
		progress: runDetails?.progress?.current_generation
			? Math.round(
					(runDetails.progress.current_generation /
						(Number(
							(runDetails?.config_json as Record<string, unknown> | undefined)
								?.generations,
						) || 100)) *
						100,
				)
			: 0,
		generation: runDetails?.progress?.current_generation || 0,
		bestFitness: runDetails?.progress?.best_fitness_so_far || 0,
		avgFitness: 0, // Not available in current API type
		logs: runDetails?.run_events?.map(
			(e) => `[${new Date(e.timestamp).toLocaleTimeString()}] ${e.message}`,
		) || ["System: Ready to start evolution..."],
		population:
			foundStrategies?.map((s) => ({
				id: s.id,
				rank: s.rank,
				fitness: s.fitness_score,
				strategy: s.strategy_json,
				kpis: s.kpis_json,
			})) || [],
	};

	interface ChartPoint {
		name: string;
		best: string;
		avg: string;
	}

	// Build chart data from progress history (populated from WebSocket)
	const [wsUpdates, setWsUpdates] = useState<ChartPoint[]>([]);
	const [wsLogEntries, setWsLogUpdates] = useState<string[]>([]);

	interface ProgressHistoryItem {
		generation: number;
		best_fitness: number;
		avg_fitness: number;
	}

	const chartData = useMemo(() => {
		const history =
			runDetails?.progress?.progress_history?.map((h: ProgressHistoryItem) => ({
				name: `Gen ${h.generation}`,
				best: Number(h.best_fitness).toFixed(2),
				avg: Number(h.avg_fitness).toFixed(2),
			})) || [];

		// Filter out updates that are already in history
		const newUpdates = wsUpdates.filter(
			(u) => !history.some((h) => h.name === u.name),
		);
		return [...history, ...newUpdates];
	}, [runDetails, wsUpdates]);

	const wsLogs = useMemo(() => {
		const historyLogs =
			runDetails?.progress?.progress_history?.map(
				(h: ProgressHistoryItem) =>
					`[Gen ${h.generation}] Best: ${Number(h.best_fitness).toFixed(4)}, Avg: ${Number(h.avg_fitness).toFixed(4)}`,
			) || [];

		return [
			"System: Ready to start evolution...",
			...historyLogs,
			...wsLogEntries,
		].slice(-50);
	}, [runDetails, wsLogEntries]);

	// === WebSocket for real-time progress ===
	const { subscribe, unsubscribe } = useWebSocket();

	const handleGeneticUpdate = useCallback((payload: unknown) => {
		const update = payload as GeneticProgressUpdate;
		// Add new generation data to updates
		setWsUpdates((prev) => {
			const exists = prev.some((d) => d.name === `Gen ${update.generation}`);
			if (exists) return prev;
			return [
				...prev,
				{
					name: `Gen ${update.generation}`,
					best: update.best_fitness.toFixed(2),
					avg: update.avg_fitness.toFixed(2),
				},
			];
		});

		// Add log entry if status message present
		if (update.status_message) {
			setWsLogUpdates((prev) => [
				...prev,
				`[${new Date().toLocaleTimeString()}] ${update.status_message}`,
			]);
		}
	}, []);

	// Reset WebSocket updates when runId changes
	useEffect(() => {
		if (runDetails?.id !== prevDetailsRunIdRef.current) {
			prevDetailsRunIdRef.current = runDetails?.id || null;
			// Defer state reset to next tick to avoid cascading render warning
			setTimeout(() => {
				setWsUpdates([]);
				setWsLogUpdates([]);
			}, 0);
		}
	}, [runDetails]);

	// Subscribe to WebSocket for active run progress
	useEffect(() => {
		if (!activeRunId || !evoState.isRunning) return;

		const channel = `genetic-progress:${activeRunId}`;
		subscribe(channel, handleGeneticUpdate);

		return () => {
			unsubscribe(channel, handleGeneticUpdate);
		};
	}, [
		activeRunId,
		evoState.isRunning,
		subscribe,
		unsubscribe,
		handleGeneticUpdate,
	]);

	const handleStartSearch = () => {
		interface IndicatorSetting {
			active: boolean;
			minPeriod: number;
			maxPeriod: number;
			timeframes: string[];
		}

		// Build indicators config from DNA module
		const indicatorsConfig: Record<string, IndicatorSetting> = {};
		dnaConfig.indicators.forEach((ind) => {
			if (ind.active) {
				indicatorsConfig[ind.id] = {
					active: true,
					minPeriod: ind.minPeriod,
					maxPeriod: ind.maxPeriod,
					timeframes: ind.timeframes,
				};
			}
		});

		// Build config from current UI state
		const config = {
			config_json: {
				// Run name
				name: runName || `Run ${new Date().toLocaleDateString()}`,

				// Evolution parameters from FitnessLabModule
				population_size: fitnessConfig.evolution.populationSize,
				generations: fitnessConfig.evolution.generations,
				crossover_probability: 0.7,
				mutation_probability: 0.3,

				// From UniverseDataModule
				assets: universeConfig.assets,
				train_split_pct: universeConfig.trainSplitPct,
				trading_fee: universeConfig.tradingFee,
				slippage: universeConfig.slippage,
				initial_capital: universeConfig.initialCapital,

				// From DNAArchitectureModule
				indicators: indicatorsConfig,
				logic_tree_depth: dnaConfig.logicTreeDepth,
				correlation_limit: dnaConfig.correlationLimit,
				signal_pruning: dnaConfig.signalPruning,
				outlier_rejection: dnaConfig.outlierRejection,
				diversity_penalty: dnaConfig.diversityPenalty,

				// From ExecutionRiskModule (now with ranges)
				sl_range: executionConfig.slRange,
				tp_range: executionConfig.tpRange,
				trailing_config: {
					activation_rr: executionConfig.trailingActivationRR,
					strict: executionConfig.strictTrailing,
				},
				breakeven_config: {
					enabled: executionConfig.breakevenEnabled,
					trigger_rr_range: executionConfig.breakevenTriggerRRRange,
					buffer_atr_range: executionConfig.breakevenBufferATRRange,
				},
				partial_tps: executionConfig.partialTPs.map((p) => ({
					size_pct_range: p.sizePctRange,
					target_rr_range: p.targetRRRange,
				})),
				time_stop_candles_range: executionConfig.timeStopCandlesRange,

				// From FitnessLabModule
				fitness_weights: weights,
				kill_switches: fitnessConfig.killSwitches,

				// From Advanced Gene Pool Settings (Modal)
				filters: dnaConfig.genePool.filters,
				conditions: dnaConfig.genePool.conditions,

				// Seed Strategy Config (for continuation/optimization)
				seed_config:
					seedConfig.mode !== "random"
						? {
								mode: seedConfig.mode,
								run_id:
									seedConfig.mode === "previous_run"
										? seedConfig.runId
										: undefined,
								strategies:
									seedConfig.mode === "upload"
										? seedConfig.strategies
										: undefined,
								top_n: seedConfig.topN,
								keep_structure: seedConfig.keepStructure,
							}
						: undefined,
			},
		};

		startMutation.mutate(config, {
			onSuccess: (data) => {
				setActiveRunId(data.id);
				setActiveTab("monitor");
			},
		});
	};

	const handleStopSearch = () => {
		if (activeRunId) {
			stopMutation.mutate(activeRunId);
		}
	};

	const toggleEvolution = () => {
		if (evoState.isRunning) {
			handleStopSearch();
		} else {
			handleStartSearch();
		}
	};

	// Header actions for PageLayout
	const headerActions = (
		<div className="flex items-center gap-4">
			<div className="flex items-center gap-2">
				<Badge
					variant={evoState.isRunning ? "default" : "secondary"}
					className="font-mono"
				>
					<span
						className={`w-2 h-2 rounded-full mr-2 ${evoState.isRunning ? "bg-emerald-400 animate-pulse" : "bg-muted-foreground"}`}
					></span>
					{evoState.isRunning
						? t("gcc.statusEvolving", "EVOLVING...")
						: t("gcc.statusIdle", "IDLE")}
				</Badge>
				{evoState.isRunning && (
					<Badge variant="outline" className="font-mono">
						Gen {evoState.generation}
					</Badge>
				)}
			</div>
			<Button
				onClick={toggleEvolution}
				variant={evoState.isRunning ? "destructive" : "default"}
				className="font-bold"
				disabled={startMutation.isPending || stopMutation.isPending}
			>
				{startMutation.isPending || stopMutation.isPending ? (
					<RefreshCw className="w-4 h-4 mr-2 animate-spin" />
				) : evoState.isRunning ? (
					<Square className="w-4 h-4 mr-2 fill-current" />
				) : (
					<Play className="w-4 h-4 mr-2 fill-current" />
				)}
				{evoState.isRunning
					? t("gcc.btnTerminate", "TERMINATE")
					: t("gcc.btnStartSearch", "START SEARCH")}
			</Button>
		</div>
	);

	return (
		<PageLayout
			title={t("gcc.pageTitle", "Genetic Command Center")}
			icon={Dna}
			headerActions={headerActions}
		>
			<Tabs
				value={activeTab}
				onValueChange={setActiveTab}
				className="h-full flex flex-col"
			>
				<div className="flex items-center justify-between mb-6">
					<TabsList className="grid max-w-md grid-cols-3">
						<TabsTrigger value="config" className="flex items-center gap-2">
							<Settings className="w-4 h-4" />
							{t("gcc.tabs.config", "Config")}
						</TabsTrigger>
						<TabsTrigger value="monitor" className="flex items-center gap-2">
							<Activity className="w-4 h-4" />
							{t("gcc.tabs.monitor", "Monitor")}
						</TabsTrigger>
						<TabsTrigger value="hallOfFame" className="flex items-center gap-2">
							<Trophy className="w-4 h-4" />
							{t("gcc.tabs.results", "Results")}
						</TabsTrigger>
					</TabsList>

					{/* Run Selector - always visible */}
					<div className="flex items-center gap-3">
						<label className="text-sm font-medium text-muted-foreground whitespace-nowrap">
							{t("discovery:hallOfFame.selectRun", "Select Run:")}
						</label>
						<select
							className="flex h-9 w-64 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
							value={activeRunId || ""}
							onChange={(e) => setActiveRunId(e.target.value || null)}
						>
							<option value="">
								{t(
									"discovery:hallOfFame.selectRunPlaceholder",
									"-- Select a run --",
								)}
							</option>
							{geneticRuns?.map((run) => (
								<option key={run.id} value={run.id}>
									{run.config_json?.name || "Unnamed"} (
									{new Date(run.created_at).toLocaleDateString()}) -{" "}
									{run.status}
								</option>
							))}
						</select>
						{strategiesLoading && (
							<RefreshCw className="w-4 h-4 animate-spin text-muted-foreground" />
						)}
					</div>
				</div>

				<div className="flex-1 min-h-0 overflow-y-auto">
					<TabsContent value="config" className="mt-0 h-full">
						<div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
							<div className="xl:col-span-8 space-y-6">
								{/* Run Info Card */}
								<Card>
									<CardContent className="pt-6">
										<div className="flex items-center gap-4">
											<div className="flex-1 space-y-2">
												<Label
													htmlFor="run-name-config"
													className="text-sm font-bold uppercase tracking-widest text-muted-foreground"
												>
													{t(
														"discovery:launchForm.runNameLabel",
														"Genetic Run Name",
													)}
												</Label>
												<Input
													id="run-name-config"
													placeholder={t(
														"discovery:launchForm.runNamePlaceholder",
														"e.g., Aggressive Scalper v1",
													)}
													value={runName}
													onChange={(e) => setRunName(e.target.value)}
													disabled={evoState.isRunning}
													className="h-12 text-lg font-bold"
												/>
												<p className="text-xs text-muted-foreground">
													{t(
														"discovery:launchForm.runNameHelp",
														"Choose a descriptive name to easily identify this search in history",
													)}
												</p>
											</div>
										</div>
									</CardContent>
								</Card>

								<UniverseDataModule
									config={universeConfig}
									onChange={setUniverseConfig}
									availableAssets={availableAssets}
								/>
								<DNAArchitectureModule
									config={dnaConfig}
									onChange={setDnaConfig}
								/>
								<ExecutionRiskModule
									config={executionConfig}
									onChange={setExecutionConfig}
								/>
							</div>
							<div className="xl:col-span-4 space-y-6">
								<FitnessLabModule
									config={fitnessConfig}
									onChange={setFitnessConfig}
								/>
								<SeedStrategySelector
									config={seedConfig}
									onChange={setSeedConfig}
									availableRuns={geneticRuns || []}
									isLoading={runsLoading}
								/>

								<Card>
									<CardHeader className="pb-3">
										<CardTitle className="text-sm font-bold uppercase tracking-widest flex items-center">
											<Terminal className="w-4 h-4 mr-2" />{" "}
											{t("gcc.modules.console.title", "Live Console")}
										</CardTitle>
									</CardHeader>
									<CardContent>
										<div className="h-[400px] overflow-y-auto font-mono text-xs bg-muted/50 p-4 rounded-lg border space-y-2">
											{wsLogs.map((log, i) => (
												<div key={i} className="flex">
													<span className="text-primary mr-2 opacity-50">
														$
													</span>
													<span
														className={
															log.includes("Best") || log.includes("fitness")
																? "text-emerald-400"
																: "text-muted-foreground"
														}
													>
														{log}
													</span>
												</div>
											))}
											{runsLoading && (
												<div className="text-muted-foreground">
													Loading runs...
												</div>
											)}
										</div>
									</CardContent>
								</Card>
							</div>
						</div>
					</TabsContent>

					<TabsContent value="monitor" className="mt-0 h-full">
						<EvolutionMonitor evoState={evoState} chartData={chartData} />
					</TabsContent>

					<TabsContent value="hallOfFame" className="mt-0 h-full">
						<HallOfFame evoState={evoState} />
					</TabsContent>
				</div>
			</Tabs>
		</PageLayout>
	);
};

export default GeneticCommandCenter;
