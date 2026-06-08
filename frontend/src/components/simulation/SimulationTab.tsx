// frontend/src/components/simulation/SimulationTab.tsx
// Main simulation tab content for LaboratoryPage integration

import { BarChart3, Grid, Scale, Search, Shield } from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/hooks/use-toast";
import { AssetDeepDiveView } from "./AssetDeepDiveView";
import { BEAnalysisView } from "./BEAnalysisView";
import { CompareView } from "./CompareView";
import { InspectorMatrix } from "./InspectorMatrix";
import { SimulationDashboard } from "./SimulationDashboard";
import { SimulationSidebar } from "./SimulationSidebar";
import { useSimulationStore } from "./simulationStore";
import type { InspectorCell } from "./types";

// We now rely on Vite proxy in vite.config.ts to handle /api requests correctly
// both in production and development (docker).
const API_BASE = "";
const ACTIVE_INSPECTOR_TASK_KEY = "depthsight.simulation.activeInspectorTask";

type ActiveInspectorTask = {
	taskId: string;
	assets: string[];
	variants: string[];
	startedAt: number;
};

type InspectorStreamEvent = {
	type?: string;
	assets?: unknown;
	variants?: unknown;
	asset?: string;
	variant?: string;
	data?: InspectorCell;
	progress?: number;
	total?: number;
	message?: string;
};

const readActiveInspectorTask = (): ActiveInspectorTask | null => {
	try {
		const raw = localStorage.getItem(ACTIVE_INSPECTOR_TASK_KEY);
		return raw ? (JSON.parse(raw) as ActiveInspectorTask) : null;
	} catch {
		return null;
	}
};

const saveActiveInspectorTask = (task: ActiveInspectorTask) => {
	localStorage.setItem(ACTIVE_INSPECTOR_TASK_KEY, JSON.stringify(task));
};

const clearActiveInspectorTask = (taskId?: string) => {
	const active = readActiveInspectorTask();
	if (!taskId || active?.taskId === taskId) {
		localStorage.removeItem(ACTIVE_INSPECTOR_TASK_KEY);
	}
};

const readResponseError = async (response: Response) => {
	const data = await response.json().catch(() => null);
	return data?.detail || `HTTP ${response.status}`;
};

export const SimulationTab: React.FC = () => {
	const { t } = useTranslation("simulation");
	const { toast } = useToast();
	const { token } = useAuth();
	const activeStreamRef = useRef<string | null>(null);

	const {
		currentView,
		setView,
		setAvailableAssets,
		selectedAssets,
		selectedVariants,
		strategyJson,
		config,
		customVariants,
		startDate,
		endDate,
	} = useSimulationStore();

	// Fetch available assets on mount and auto-select all
	useEffect(() => {
		const fetchAssets = async () => {
			try {
				const response = await fetch(`${API_BASE}/api/simulation/assets`);
				if (response.ok) {
					const data = await response.json();
					const assets = data.assets || [];
					setAvailableAssets(assets);
					// Auto-select all assets
					useSimulationStore.getState().selectAllAssets();
				}
			} catch (err) {
				console.error("Failed to fetch assets:", err);
			}
		};
		fetchAssets();
	}, [setAvailableAssets]);

	const attachInspectorTask = useCallback(
		async (
			taskId: string,
			fallbackAssets: string[] = [],
			fallbackVariants: string[] = [],
		) => {
			if (!taskId || activeStreamRef.current === taskId) return;
			activeStreamRef.current = taskId;
			const store = useSimulationStore.getState();
			store.setLoading(true);
			store.setView("matrix");

			try {
				const response = await fetch(
					`${API_BASE}/api/simulation/inspector/celery/stream/${taskId}`,
				);

				if (!response.ok) {
					throw new Error(await readResponseError(response));
				}

				const reader = response.body?.getReader();
				const decoder = new TextDecoder();

				if (!reader) {
					throw new Error("No response body");
				}

				let buffer = "";
				const processLine = (line: string) => {
					if (!line.startsWith("data: ")) return;
					let data: InspectorStreamEvent;
					try {
						data = JSON.parse(line.slice(6));
					} catch {
						// Skip unparseable/incomplete SSE messages.
						return;
					}

					if (data.type === "start") {
						const assets =
							Array.isArray(data.assets) && data.assets.length
								? data.assets
								: fallbackAssets;
						const variants =
							Array.isArray(data.variants) && data.variants.length
								? data.variants
								: fallbackVariants;
						if (
							assets.length &&
							variants.length &&
							!useSimulationStore.getState().inspectorResult
						) {
							store.initInspectorMatrix(assets, variants);
						}
						saveActiveInspectorTask({
							taskId,
							assets,
							variants,
							startedAt: Date.now(),
						});
					} else if (data.type === "result") {
						if (data.asset && data.variant && data.data) {
							store.updateInspectorCell(data.asset, data.variant, data.data);
						}
						store.setProgress(data.progress ?? 0);
					} else if (
						data.type === "heartbeat" &&
						typeof data.progress === "number"
					) {
						store.setProgress(data.progress);
					} else if (data.type === "complete") {
						clearActiveInspectorTask(taskId);
						store.setLoading(false);
						store.setProgress(100);
						toast({
							title: t("inspectorComplete", "Inspector Complete"),
							description: `${data.total} ${t("backtestsCompleted", "backtests completed")}`,
						});
					} else if (data.type === "error") {
						throw new Error(data.message);
					}
				};

				while (true) {
					const { done, value } = await reader.read();
					if (done) {
						if (buffer.trim()) processLine(buffer.trim());
						break;
					}

					buffer += decoder.decode(value, { stream: true });
					const lines = buffer.split("\n");
					buffer = lines.pop() || "";

					for (const line of lines) {
						processLine(line);
					}
				}
			} catch (err) {
				console.error("Inspector error:", err);
				toast({
					title: t("error", "Error"),
					description: String(err),
					variant: "destructive",
				});
			} finally {
				if (activeStreamRef.current === taskId) {
					activeStreamRef.current = null;
				}
				store.setLoading(false);
			}
		},
		[toast, t],
	);

	useEffect(() => {
		const activeTask = readActiveInspectorTask();
		if (!activeTask?.taskId) return;

		let cancelled = false;
		const recoverInspectorTask = async () => {
			try {
				const response = await fetch(
					`${API_BASE}/api/simulation/inspector/status/${activeTask.taskId}`,
				);
				if (!response.ok) return;
				const status = await response.json();
				const state = status?.state || {};
				const assets =
					Array.isArray(state.assets) && state.assets.length
						? state.assets
						: activeTask.assets;
				const variants =
					Array.isArray(state.variants) && state.variants.length
						? state.variants
						: activeTask.variants;
				if (cancelled || !assets.length || !variants.length) return;

				const store = useSimulationStore.getState();
				store.initInspectorMatrix(assets, variants);
				store.setProgress(
					typeof state.progress === "number" ? state.progress : 0,
				);
				store.setLoading(true);
				store.setView("matrix");
				await attachInspectorTask(activeTask.taskId, assets, variants);
			} catch (err) {
				console.error("Failed to recover inspector task:", err);
			}
		};

		recoverInspectorTask();
		return () => {
			cancelled = true;
		};
	}, [attachInspectorTask]);

	const handleRunInspector = useCallback(async () => {
		if (!strategyJson || selectedAssets.length === 0) return;

		const store = useSimulationStore.getState();
		store.setLoading(true);
		store.setProgress(0);
		store.initInspectorMatrix(selectedAssets, selectedVariants);
		store.setView("matrix");

		try {
			const response = await fetch(
				`${API_BASE}/api/simulation/inspector/start`,
				{
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						...(token ? { Authorization: `Bearer ${token}` } : {}),
					},
					body: JSON.stringify({
						strategy_json: strategyJson,
						assets: selectedAssets,
						variants: selectedVariants,
						custom_variants: customVariants.filter((cv) =>
							selectedVariants.includes(cv.id),
						),
						start_date: startDate,
						end_date: endDate,
					}),
				},
			);

			if (!response.ok) {
				throw new Error(await readResponseError(response));
			}

			const queuedTask = await response.json();
			const taskId = queuedTask.task_id;
			if (!taskId) {
				throw new Error("No task_id returned");
			}

			saveActiveInspectorTask({
				taskId,
				assets: selectedAssets,
				variants: selectedVariants,
				startedAt: Date.now(),
			});
			await attachInspectorTask(taskId, selectedAssets, selectedVariants);
		} catch (err) {
			console.error("Inspector error:", err);
			clearActiveInspectorTask();
			toast({
				title: t("error", "Error"),
				description: String(err),
				variant: "destructive",
			});
		} finally {
			store.setLoading(false);
		}
	}, [
		strategyJson,
		selectedAssets,
		selectedVariants,
		customVariants,
		startDate,
		endDate,
		attachInspectorTask,
		toast,
		t,
		token,
	]);

	const handleRunSimulation = useCallback(async () => {
		const store = useSimulationStore.getState();
		const inspectorData = store.inspectorResult;

		// Checking for the presence of inspector results
		if (!inspectorData?.matrix) {
			toast({
				title: t("error", "Error"),
				description: t(
					"runInspectorFirst",
					"Please run inspector first to generate trade data",
				),
				variant: "destructive",
			});
			return;
		}

		store.setLoading(true);

		try {
			// Collecting all trades from the inspector results
			const allTrades: Array<{
				asset: string;
				strategy: string;
				entryTime: number;
				exitTime: number;
				entryPrice: number;
				exitPrice: number;
				pnlPct: number;
			}> = [];

			for (const asset of selectedAssets) {
				for (const variant of selectedVariants) {
					const cell = inspectorData.matrix[asset]?.[variant];
					if (cell?.trades && Array.isArray(cell.trades)) {
						for (const trade of cell.trades) {
							allTrades.push({
								asset,
								strategy: variant,
								entryTime: trade.entryTime,
								exitTime: trade.exitTime,
								entryPrice: trade.entryPrice,
								exitPrice: trade.exitPrice,
								pnlPct: trade.pnlPct,
							});
						}
					}
				}
			}

			if (allTrades.length === 0) {
				toast({
					title: t("error", "Error"),
					description: t(
						"noTradesFound",
						"No trades found in inspector results. Try running inspector again.",
					),
					variant: "destructive",
				});
				store.setLoading(false);
				return;
			}

			// Use the /portfolio endpoint with ready-made trades (without re-backtesting)
			const response = await fetch(`${API_BASE}/api/simulation/portfolio`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					...(token ? { Authorization: `Bearer ${token}` } : {}),
				},
				body: JSON.stringify({
					trades: allTrades,
					config: config,
				}),
			});

			if (!response.ok) {
				throw new Error(await readResponseError(response));
			}

			const result = await response.json();
			store.setSimulationResult(result);
			store.setView("portfolio");

			toast({
				title: t("simulationComplete", "Simulation Complete"),
				description: `${t("netProfit", "Net Profit")}: ${result.stats?.totalPnlPct?.toFixed(2) || 0}%`,
			});
		} catch (err) {
			console.error("Portfolio simulation error:", err);
			toast({
				title: t("error", "Error"),
				description: String(err),
				variant: "destructive",
			});
		} finally {
			store.setLoading(false);
		}
	}, [selectedAssets, selectedVariants, config, toast, t, token]);

	return (
		<div className="flex gap-6 h-full min-h-[600px]">
			{/* Sidebar */}
			<div className="w-96 flex-shrink-0">
				<SimulationSidebar
					onRunInspector={handleRunInspector}
					onRunSimulation={handleRunSimulation}
				/>
			</div>

			{/* Main Content */}
			<div className="flex-1 min-w-0">
				<Tabs
					value={currentView}
					onValueChange={(v) => setView(v as typeof currentView)}
					className="h-full"
				>
					<TabsList className="mb-4">
						<TabsTrigger value="matrix" className="flex items-center gap-2">
							<Grid className="w-4 h-4" />
							{t("inspectorMatrix", "Inspector Matrix")}
						</TabsTrigger>
						<TabsTrigger value="portfolio" className="flex items-center gap-2">
							<BarChart3 className="w-4 h-4" />
							{t("portfolio", "Portfolio")}
						</TabsTrigger>
						<TabsTrigger value="deepdive" className="flex items-center gap-2">
							<Search className="w-4 h-4" />
							{t("deepDive", "Deep Dive")}
						</TabsTrigger>
						<TabsTrigger value="compare" className="flex items-center gap-2">
							<Scale className="w-4 h-4" />
							{t("compare", "Compare")}
						</TabsTrigger>
						<TabsTrigger value="beanalysis" className="flex items-center gap-2">
							<Shield className="w-4 h-4" />
							{t("beAnalysis", "BE Analysis")}
						</TabsTrigger>
					</TabsList>

					<TabsContent value="matrix" className="mt-0">
						<InspectorMatrix />
					</TabsContent>

					<TabsContent value="portfolio" className="mt-0">
						<SimulationDashboard />
					</TabsContent>

					<TabsContent value="deepdive" className="mt-0">
						<AssetDeepDiveView />
					</TabsContent>

					<TabsContent value="compare" className="mt-0">
						<CompareView />
					</TabsContent>

					<TabsContent value="beanalysis" className="mt-0">
						<BEAnalysisView />
					</TabsContent>
				</Tabs>
			</div>
		</div>
	);
};

export default SimulationTab;
