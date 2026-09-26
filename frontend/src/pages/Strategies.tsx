// src/pages/Strategies.tsx

import { formatDistanceToNowStrict } from "date-fns";
import {
	GitBranch,
	Layers,
	Loader2,
	Pencil,
	Play,
	Plus,
	RefreshCw,
	Square,
	Star,
	Trash2,
	TrendingUp,
	X,
} from "lucide-react";
import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ExchangeBadge } from "@/components/layout/AccountSelector";
import { PageLayout } from "@/components/layout/PageLayout";
import { useWebSocket } from "@/context/WebSocketProvider";
import { useLiveMarks } from "@/hooks/useLiveMarks";
import { normalizeExchangeKey } from "@/lib/exchanges";
import {
	applyLiveMarksToPositions,
	overlayLiveStrategyPnl,
} from "@/lib/livePnl";
import { resolveStrategyTimeframe } from "@/lib/strategyMeta";
import { ConfirmationModal } from "@/components/shared/ConfirmationModal";
import {
	type LaunchFormData,
	LaunchStrategyModal,
} from "@/components/strategies/LaunchStrategyModal";
import { StrategyDetailsPanel } from "@/components/strategies/StrategyDetailsPanel";
import {
	Badge,
	Btn,
	fmt,
	Panel,
	Segmented,
	Sparkline,
	Stat,
	toneText,
} from "@/components/ui/quant-ui";
import { Skeleton } from "@/components/ui/skeleton";
import {
	useDeleteStrategyConfig,
	usePositions,
	useStartStrategy,
	useStopStrategy,
	useStrategies,
	useStrategyConfigsList,
	useTradeHistory,
} from "@/lib/api";
import { cumulativePnlByStrategy } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import { useAccountStore } from "@/stores/accountStore";
import type { PositionData, StrategyConfig, StrategyData } from "@/types/api";

// Helper to format runtime
const calculateRuntime = (startTime: string | undefined): string => {
	if (!startTime) return "—";
	try {
		return formatDistanceToNowStrict(new Date(startTime));
	} catch {
		return "—";
	}
};

// Helper to resolve equity series for strategy card
const resolveStrategyEquity = (
	s: CombinedStrategy,
	primary?: StrategyData,
	equityMap?: Map<string, number[]>,
): number[] => {
	if (!equityMap) return [];
	const candidateKeys: (string | undefined | null)[] = [
		s.id ? String(s.id) : undefined,
		primary?.config_id ? String(primary.config_id) : undefined,
		s.name,
		primary?.name,
		s.config_data?.strategy_name,
		primary?.strategy_name,
		primary?.id ? String(primary.id) : undefined,
	];

	if (s.instances && s.instances.length > 0) {
		for (const inst of s.instances) {
			candidateKeys.push(
				inst.config_id ? String(inst.config_id) : undefined,
				inst.name,
				inst.strategy_name,
				inst.id ? String(inst.id) : undefined,
			);
		}
	}

	let bestMatch: number[] = [];
	for (const key of candidateKeys) {
		if (!key) continue;
		const eq = equityMap.get(key);
		if (eq && eq.length >= 2) {
			return eq;
		}
		if (eq && eq.length > bestMatch.length) {
			bestMatch = eq;
		}
	}
	return bestMatch;
};

export type CombinedStrategy = StrategyConfig &
	Partial<Omit<StrategyData, "id" | "name">> & {
		instances?: StrategyData[];
	};

type FilterType = "all" | "running" | "stopped" | "paper" | "live" | "favorites";

const FAVORITES_STORAGE_KEY = "depthsight_favorite_strategies";

export default function Strategies() {
	const { t } = useTranslation(["strategies", "common"]);
	const navigate = useNavigate();
	const { selectedApiKeyId } = useAccountStore();
	const { readyState } = useWebSocket();
	const wsLive = readyState === 1;
	const strategiesPoll = wsLive ? false : 5000;

	// Fetch live and paper running strategies (push-driven; poll on WS outage)
	const {
		data: liveRunning = [],
		isLoading: isLoadingLive,
		refetch: refetchLive,
	} = useStrategies({
		mode: "live",
		apiKeyId: selectedApiKeyId,
		refetchInterval: strategiesPoll,
	});

	const {
		data: paperRunning = [],
		isLoading: isLoadingPaper,
		refetch: refetchPaper,
	} = useStrategies({ mode: "paper", refetchInterval: strategiesPoll });

	const {
		data: savedConfigs = [],
		isLoading: isLoadingConfigs,
		refetch: refetchConfigs,
	} = useStrategyConfigsList();

	// 30d stats trade history to compute equity curves for strategy cards
	const [now] = useState(() => new Date());
	const statsStart = useMemo(
		() => new Date(now.getTime() - 30 * 86400 * 1000),
		[now],
	);
	const scopedApiKeyId =
		selectedApiKeyId !== "all" ? selectedApiKeyId : undefined;

	const { data: liveTradesData, refetch: refetchLiveTrades } = useTradeHistory({
		mode: "live",
		startDate: statsStart.toISOString(),
		endDate: now.toISOString(),
		limit: 10000,
		apiKeyId: scopedApiKeyId,
	});

	const { data: paperTradesData, refetch: refetchPaperTrades } =
		useTradeHistory({
			mode: "paper",
			startDate: statsStart.toISOString(),
			endDate: now.toISOString(),
			limit: 10000,
		});

	const allTrades = useMemo(() => {
		const live = liveTradesData?.trades || [];
		const paper = paperTradesData?.trades || [];
		return [...live, ...paper];
	}, [liveTradesData, paperTradesData]);

	const strategyEquity = useMemo(
		() => cumulativePnlByStrategy(allTrades),
		[allTrades],
	);

	const isInitialLoading =
		isLoadingLive || isLoadingPaper || isLoadingConfigs;

	const runningStrategies = useMemo(() => {
		// Dedupe by instance id: live/paper queries + WS pushes can deliver
		// the same instance twice, which doubled Total P&L.
		const all = [...liveRunning, ...paperRunning];
		const seen = new Set<string>();
		return all.filter((inst) => {
			const key = String(
				inst.id ?? `${inst.config_id}-${inst.mode}-${inst.api_key_id}`,
			);
			if (seen.has(key)) return false;
			seen.add(key);
			return true;
		});
	}, [liveRunning, paperRunning]);

	// Live overlay for strategy PnL: snapshot positions give entry/qty,
	// exchange ticks move the unrealized part (indicative, like Positions tab).
	// Push snapshots keep these queries fresh; poll only on socket outage.
	const { data: liveModePositions } = usePositions({
		mode: "live",
		refetchInterval: strategiesPoll,
	});
	const { data: paperModePositions } = usePositions({
		mode: "paper",
		refetchInterval: strategiesPoll,
	});
	const snapshotPositions = useMemo(
		() => [...(liveModePositions ?? []), ...(paperModePositions ?? [])],
		[liveModePositions, paperModePositions],
	);
	const liveStrategySymbols = useMemo(
		() =>
			snapshotPositions.map((p: PositionData) => ({
				symbol: String(p.symbol),
				exchange: p.exchange ?? null,
			})),
		[snapshotPositions],
	);
	const { marks: strategyMarks } = useLiveMarks(liveStrategySymbols);
	const liveSnapshotPositions = useMemo(
		() => applyLiveMarksToPositions(snapshotPositions, strategyMarks),
		[snapshotPositions, strategyMarks],
	);
	const liveRunningStrategies = useMemo(
		() =>
			overlayLiveStrategyPnl(
				runningStrategies,
				snapshotPositions,
				liveSnapshotPositions,
			) ?? runningStrategies,
		[runningStrategies, snapshotPositions, liveSnapshotPositions],
	);

	// API Mutations
	const { mutate: stopStrategy, isPending: isStopping } = useStopStrategy();
	const { mutate: startStrategy, isPending: isStarting } = useStartStrategy();
	const { mutate: deleteStrategyConfig, isPending: isDeleting } =
		useDeleteStrategyConfig();

	// Local State
	const [searchQuery, setSearchQuery] = useState("");
	const [filterType, setFilterType] = useState<FilterType>("all");

	// Favorites State
	const [favoriteIds, setFavoriteIds] = useState<string[]>(() => {
		try {
			const raw = localStorage.getItem(FAVORITES_STORAGE_KEY);
			return raw ? JSON.parse(raw) : [];
		} catch {
			return [];
		}
	});

	const toggleFavorite = (id: string) => {
		setFavoriteIds((prev) => {
			const next = prev.includes(id)
				? prev.filter((item) => item !== id)
				: [...prev, id];
			try {
				localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(next));
			} catch (e) {
				console.error("Failed to save favorites to localStorage", e);
			}
			return next;
		});
	};
	const [selectedStrategyId, setSelectedStrategyId] = useState<string | null>(
		null,
	);
	const [pendingActionId, setPendingActionId] = useState<string | null>(null);

	// Launch Strategy Modal State
	const [launchConfig, setLaunchConfig] = useState<{
		open: boolean;
		configId: string | null;
		strategy: CombinedStrategy | null;
	}>({ open: false, configId: null, strategy: null });

	// Confirmation Modal State
	const [confirmAction, setConfirmAction] = useState<{
		open: boolean;
		actionType: "stop" | "delete" | null;
		configId: string | null;
		instanceId: string | null;
		title: string;
		description: string;
	}>({
		open: false,
		actionType: null,
		configId: null,
		instanceId: null,
		title: "",
		description: "",
	});

	// Combine saved configs with running instances
	const combinedStrategies = useMemo((): CombinedStrategy[] => {
		if (!savedConfigs) return [];

		const instancesByConfig = new Map<string, StrategyData[]>();
		for (const inst of liveRunningStrategies) {
			const key = inst.config_id || inst.id;
			const arr = instancesByConfig.get(key) ?? [];
			// Guard against the same instance landing here twice
			// (live+paper overlap / WS push duplicates).
			if (!arr.some((existing) => existing.id === inst.id)) {
				arr.push(inst);
			}
			instancesByConfig.set(key, arr);
		}

		return savedConfigs.map((config) => {
			const instances = instancesByConfig.get(config.id) ?? [];
			const primary = instances[0];
			return {
				...config,
				...primary,
				id: config.id,
				name: config.name,
				status: instances.length ? primary?.status || "RUNNING" : "STOPPED",
				instances,
			};
		});
	}, [savedConfigs, liveRunningStrategies]);

	// Filtered list
	const filteredStrategies = useMemo(() => {
		let result = combinedStrategies;

		if (searchQuery.trim()) {
			const q = searchQuery.toLowerCase().trim();
			result = result.filter(
				(s) =>
					s.name.toLowerCase().includes(q) ||
					s.id.toLowerCase().includes(q) ||
					s.config_data?.strategy_name?.toLowerCase().includes(q) ||
					(s.symbols || []).some((sym) => sym.toLowerCase().includes(q)) ||
					(Array.isArray(s.config_data?.symbols) &&
						s.config_data.symbols.some((sym: string) =>
							sym.toLowerCase().includes(q),
						)),
			);
		}

		if (filterType !== "all") {
			result = result.filter((s) => {
				const isRunning = (s.instances ?? []).length > 0;
				if (filterType === "running") return isRunning;
				if (filterType === "stopped") return !isRunning;
				if (filterType === "paper")
					return s.mode === "paper" || s.instances?.some((i) => i.mode === "paper");
				if (filterType === "live")
					return s.mode === "live" || s.instances?.some((i) => i.mode === "live");
				if (filterType === "favorites")
					return favoriteIds.includes(s.id);
				return true;
			});
		}

		// Sort priority: running first, then favorites, then alphabetically by name.
		return [...result].sort((a, b) => {
			const aRunning = (a.instances ?? []).length > 0 ? 0 : 1;
			const bRunning = (b.instances ?? []).length > 0 ? 0 : 1;
			if (aRunning !== bRunning) return aRunning - bRunning;
			const aFav = favoriteIds.includes(a.id) ? 0 : 1;
			const bFav = favoriteIds.includes(b.id) ? 0 : 1;
			if (aFav !== bFav) return aFav - bFav;
			return a.name.localeCompare(b.name, undefined, {
				sensitivity: "base",
			});
		});
	}, [combinedStrategies, searchQuery, filterType, favoriteIds]);

	// Summary statistics
	const totalRunningCount = useMemo(() => {
		return combinedStrategies.filter(
			(s) => (s.instances ?? []).length > 0,
		).length;
	}, [combinedStrategies]);

	const totalRealizedPnl = useMemo(() => {
		// Sum unique instances only so Total P&L matches the sum of cards.
		const seen = new Set<string>();
		return liveRunningStrategies.reduce((sum, inst) => {
			const key = String(
				inst.id ?? `${inst.config_id}-${inst.mode}-${inst.api_key_id}`,
			);
			if (seen.has(key)) return sum;
			seen.add(key);
			return sum + (inst.pnl || 0);
		}, 0);
	}, [liveRunningStrategies]);

	const totalOpenPositions = useMemo(() => {
		const seen = new Set<string>();
		return runningStrategies.reduce((sum, inst) => {
			const key = String(
				inst.id ?? `${inst.config_id}-${inst.mode}-${inst.api_key_id}`,
			);
			if (seen.has(key)) return sum;
			seen.add(key);
			return sum + (inst.open_positions || 0);
		}, 0);
	}, [runningStrategies]);

	// Refresh all data
	const handleRefresh = () => {
		refetchLive();
		refetchPaper();
		refetchConfigs();
		refetchLiveTrades();
		refetchPaperTrades();
	};

	// Start strategy -> open LaunchStrategyModal
	const handleStart = (strategy: CombinedStrategy) => {
		setLaunchConfig({
			open: true,
			configId: strategy.id,
			strategy,
		});
	};

	// Confirm Start in Modal
	const handleConfirmStart = (formData: LaunchFormData) => {
		if (!launchConfig.configId) return;

		setPendingActionId(launchConfig.configId);

		let symbolsArray: string[] | undefined;
		if (formData.symbols) {
			symbolsArray = formData.symbols
				.split(",")
				.map((s) => s.trim())
				.filter(Boolean);
		}

		startStrategy(
			{
				configId: launchConfig.configId,
				mode: formData.mode,
				symbol_selection_mode: formData.symbolSelectionMode || "STATIC",
				symbols: symbolsArray,
				params: {
					use_ml_confirmation: formData.useMlConfirmation ?? false,
					breakeven_on_regime_change: formData.breakevenOnRegimeChange ?? false,
				},
				apiKeyId:
					typeof formData.apiKeyId === "number"
						? formData.apiKeyId
						: typeof selectedApiKeyId === "number"
							? selectedApiKeyId
							: undefined,
			},
			{
				onSettled: () => {
					setPendingActionId(null);
					setLaunchConfig({ open: false, configId: null, strategy: null });
					handleRefresh();
				},
			},
		);
	};

	// Stop click -> confirm dialog
	const handleStopClick = (
		strategy: CombinedStrategy,
		instance?: StrategyData,
	) => {
		const inst = instance || strategy.instances?.[0];
		if (!inst) return;

		setConfirmAction({
			open: true,
			actionType: "stop",
			configId: strategy.id,
			instanceId: inst.id,
			title: t("confirmation.stopTitle", {
				defaultValue: `Stop "${strategy.name}"?`,
				name: strategy.name,
			}),
			description: t("confirmation.stopDescription", {
				defaultValue:
					"Are you sure you want to stop this running bot instance? Active orders may be canceled.",
			}),
		});
	};

	// Delete click -> confirm dialog
	const handleDeleteClick = (strategy: CombinedStrategy) => {
		const isRunning = (strategy.instances ?? []).length > 0;
		if (isRunning) return;

		setConfirmAction({
			open: true,
			actionType: "delete",
			configId: strategy.id,
			instanceId: null,
			title: t("confirmation.deleteTitle", {
				defaultValue: `Delete "${strategy.name}"?`,
				name: strategy.name,
			}),
			description: t("confirmation.deleteDescription", {
				defaultValue:
					"Are you sure you want to permanently delete this strategy configuration? This action cannot be undone.",
			}),
		});
	};

	// Execute confirmed action (Stop or Delete)
	const handleConfirmAction = () => {
		if (!confirmAction.configId || !confirmAction.actionType) return;

		setPendingActionId(
			confirmAction.actionType === "stop"
				? confirmAction.instanceId || confirmAction.configId
				: confirmAction.configId,
		);

		const onSettled = () => {
			if (selectedStrategyId === confirmAction.configId) {
				setSelectedStrategyId(null);
			}
			setConfirmAction({
				open: false,
				actionType: null,
				configId: null,
				instanceId: null,
				title: "",
				description: "",
			});
			setPendingActionId(null);
			handleRefresh();
		};

		if (confirmAction.actionType === "stop") {
			stopStrategy(confirmAction.instanceId || confirmAction.configId, {
				onSettled,
			});
		} else if (confirmAction.actionType === "delete") {
			deleteStrategyConfig(confirmAction.configId, {
				onSettled,
			});
		}
	};

	// Strategy detail drawer selection
	const selectedStrategy = combinedStrategies.find(
		(s) => s.id === selectedStrategyId,
	);

	const strategyForPanel = useMemo(() => {
		if (!selectedStrategy) return null;
		return {
			id: selectedStrategy.id,
			name: selectedStrategy.name,
			strategy_name:
				selectedStrategy.config_data?.strategy_name || "Unknown Type",
			symbol:
				selectedStrategy.config_data?.symbol ||
				(selectedStrategy.symbols || [])[0] ||
				"N/A",
			market_type:
				selectedStrategy.market_type ||
				selectedStrategy.config_data?.marketType ||
				"FUTURES",
			status: selectedStrategy.status || "STOPPED",
			pnl: selectedStrategy.pnl ?? 0,
			open_positions: selectedStrategy.open_positions ?? 0,
			started_at: selectedStrategy.started_at || "",
			params: (selectedStrategy.config_data ||
			{}) as unknown as Record<string, unknown>,
			mode: selectedStrategy.mode || "paper",
			config_data: selectedStrategy.config_data,
			symbols: selectedStrategy.symbols ?? undefined,
		};
	}, [selectedStrategy]);

	return (
		<PageLayout title={t("pageTitle", "Strategies")} hideHeader={true}>
			<div className="space-y-4">
				{/* 1. Top Summary Stats Bar */}
				<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
					<Stat
						label={t("statRunning", "Running Bots")}
						value={<span className="text-profit">{totalRunningCount}</span>}
						accent="#10e0a0"
						icon={<Play size={14} />}
					/>
					<Stat
						label={t("statRealizedPnl", "Total P&L")}
						value={
							<span
								className={
									totalRealizedPnl >= 0 ? "text-profit" : "text-rose-400"
								}
							>
								{fmt.usd(totalRealizedPnl, 2)}
							</span>
						}
						accent={totalRealizedPnl >= 0 ? "#00d4ff" : "#ff3b5c"}
						icon={<TrendingUp size={14} />}
					/>
					<Stat
						label={t("openPositions", "Active Positions")}
						value={totalOpenPositions}
						accent="#0066ff"
						icon={<Layers size={14} />}
					/>
					<Stat
						label={t("statSlots", "Saved Strategies")}
						value={
							<>
								{combinedStrategies.length}
								<span className="text-base text-white/30">
									{" "}
									/ {Math.max(10, combinedStrategies.length)}
								</span>
							</>
						}
						accent="#ffb547"
					/>
				</div>

				{/* 2. Filter & Action Toolbar */}
				<div className="flex flex-wrap items-center gap-2">
					<Segmented
						size="sm"
						value={filterType}
						onChange={(v) => setFilterType(v as FilterType)}
						options={[
							{ value: "all", label: t("filters.all", "All") },
							{
								value: "running",
								label: (
									<span className="text-emerald-400">
										{t("filters.running", "Running")}
									</span>
								),
							},
							{
								value: "stopped",
								label: (
									<span className="text-white/50">
										{t("filters.stopped", "Stopped")}
									</span>
								),
							},
							{
								value: "paper",
								label: (
									<span className="text-cyan">
										{t("filters.paper", "Paper")}
									</span>
								),
							},
							{
								value: "live",
								label: (
									<span className="text-rose-400">
										{t("filters.live", "Live")}
									</span>
								),
							},
							{
								value: "favorites",
								label: (
									<span className="flex items-center gap-1.5 text-amber-400 font-medium">
										<Star
											className={cn(
												"w-3 h-3 transition-all",
												favoriteIds.length > 0
													? "fill-amber-400 text-amber-400 drop-shadow-[0_0_6px_rgba(251,191,36,0.6)]"
													: "text-amber-400/70",
											)}
										/>
										<span>{t("filters.favorites", "Favorites")}</span>
										{favoriteIds.length > 0 && (
											<span className="px-1.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-amber-400/15 text-amber-400 border border-amber-400/25 leading-none">
												{favoriteIds.length}
											</span>
										)}
									</span>
								),
							},
						]}
					/>

					{/* Search Box */}
					<div className="relative">
						<input
							type="text"
							placeholder={t("searchPlaceholder", "Search strategies, symbols...")}
							value={searchQuery}
							onChange={(e) => setSearchQuery(e.target.value)}
							className="h-7.5 w-48 sm:w-60 rounded-lg border border-white/10 bg-white/[0.03] pl-2.5 pr-7 text-[11px] text-white placeholder-white/30 outline-none transition-colors focus:border-cyan/40"
						/>
						{searchQuery && (
							<button
								type="button"
								onClick={() => setSearchQuery("")}
								className="absolute right-2 top-1/2 -translate-y-1/2 text-white/30 hover:text-white"
							>
								<X size={11} />
							</button>
						)}
					</div>

					{/* Refresh Button */}
					<Btn
						variant="ghost"
						size="sm"
						icon={
							<RefreshCw
								size={11}
								className={isInitialLoading ? "animate-spin" : ""}
							/>
						}
						onClick={handleRefresh}
					>
						{t("common:refresh", "Refresh")}
					</Btn>
					<span
						className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
							wsLive
								? "border-emerald-400/30 text-emerald-300"
								: "border-amber-400/30 text-amber-300"
						}`}
						title={
							wsLive
								? "Live push snapshots from engine"
								: "Socket down — polling every 5s"
						}
					>
						{wsLive ? "live push" : "polling 5s"}
					</span>

					<div className="flex-1" />

					{/* Deploy / Create Strategy Button */}
					<Btn
						variant="primary"
						size="sm"
						icon={<Plus size={13} />}
						onClick={() => navigate("/editor")}
					>
						{t("createButton", "Deploy Strategy")}
					</Btn>
				</div>

				{/* 3. Strategies Cards Grid */}
				{isInitialLoading ? (
					<div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
						{[1, 2, 3, 4, 5, 6].map((i) => (
							<div
								key={i}
								className="glass rounded-2xl p-4 space-y-3 animate-pulse border-white/5"
							>
								<div className="flex items-center gap-3">
									<Skeleton className="h-10 w-10 rounded-xl bg-white/5" />
									<div className="space-y-1 flex-1">
										<Skeleton className="h-4 w-32 bg-white/5" />
										<Skeleton className="h-3 w-20 bg-white/5" />
									</div>
								</div>
								<Skeleton className="h-10 w-full bg-white/5 rounded-lg" />
								<Skeleton className="h-8 w-full bg-white/5 rounded-lg" />
							</div>
						))}
					</div>
				) : filteredStrategies.length === 0 ? (
					/* Empty State */
					<Panel noPad className="p-12 text-center">
						<div
							className={cn(
								"mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border mb-3",
								filterType === "favorites"
									? "border-amber-400/30 bg-amber-400/10 text-amber-400 shadow-[0_0_20px_rgba(251,191,36,0.2)]"
									: "border-cyan/30 bg-cyan/10 text-cyan",
							)}
						>
							{filterType === "favorites" ? (
								<Star size={24} className="fill-amber-400 text-amber-400" />
							) : (
								<GitBranch size={24} />
							)}
						</div>
						<h3 className="text-sm font-semibold text-white">
							{filterType === "favorites"
								? t("noFavoritesTitle", "No favorite strategies yet")
								: searchQuery || filterType !== "all"
									? t("noResults", "No strategies match your filter.")
									: t("emptyState.title", "No Strategies Yet")}
						</h3>
						<p className="mt-1 text-xs text-white/40 max-w-sm mx-auto">
							{filterType === "favorites"
								? t(
										"noFavoritesDesc",
										"Click the star icon in the upper right corner of any strategy card to add it to your favorites.",
									)
								: searchQuery || filterType !== "all"
									? t(
											"tryChangingFilters",
											"Try resetting your search query or switching the category filter.",
										)
									: t(
											"emptyState.description",
											"Create your first trading strategy to automate your executions.",
										)}
						</p>
						<div className="mt-4">
							<Btn
								variant="primary"
								size="sm"
								icon={<Plus size={13} />}
								onClick={() => navigate("/editor")}
							>
								{t("createButton", "Deploy Strategy")}
							</Btn>
						</div>
					</Panel>
				) : (
					<div className="grid gap-3.5 md:grid-cols-2 2xl:grid-cols-3">
						{filteredStrategies.map((s) => {
							const isRunning = (s.instances ?? []).length > 0;
							const primary = s.instances?.[0];
							const exchange =
								normalizeExchangeKey(
									(s as CombinedStrategy & { exchange?: string | null }).exchange ??
										primary?.exchange ??
										(s.config_data as StrategyConfig["config_data"] & {
											exchange?: string | null;
										})?.exchange,
								) ?? null;
							const symbolsList: string[] =
								s.symbols && s.symbols.length > 0
									? s.symbols
									: Array.isArray(s.config_data?.symbols) &&
											s.config_data.symbols.length > 0
										? s.config_data.symbols
										: s.config_data?.symbol
											? [s.config_data.symbol]
											: ["BTCUSDT"];
						const pnl = s.pnl ?? primary?.pnl ?? 0;
						const openPositions =
							s.open_positions ?? primary?.open_positions ?? 0;
						const timeframe =
							resolveStrategyTimeframe(s.config_data) ?? "15m";
						const isActionPending =
							pendingActionId === s.id ||
							(primary && pendingActionId === primary.id);
						const equity = resolveStrategyEquity(s, primary, strategyEquity);

							return (
								<div
									key={s.id}
									className={cn(
										"glass group relative rounded-2xl p-4 transition-all hover:-translate-y-0.5 hover:border-white/15 animate-fade-up flex flex-col justify-between",
										isRunning &&
											"border-cyan/30 shadow-[0_0_30px_-15px_rgba(0,212,255,0.35)]",
										s.status === "ERROR" && "border-rose-500/30",
									)}
								>
									{/* Glow when running */}
									{isRunning && (
										<div className="pointer-events-none absolute -right-8 -top-8 h-32 w-32 rounded-full bg-cyan/10 blur-3xl" />
									)}

									{/* Star in Upper Right Corner */}
									<button
										type="button"
										onClick={(e) => {
											e.stopPropagation();
											toggleFavorite(s.id);
										}}
										className={cn(
											"absolute top-3.5 right-3.5 z-10 flex items-center justify-center w-7 h-7 rounded-lg transition-all",
											favoriteIds.includes(s.id)
												? "text-amber-400 bg-amber-400/10 border border-amber-400/30 hover:bg-amber-400/20 shadow-[0_0_12px_rgba(251,191,36,0.35)]"
												: "text-white/30 hover:text-amber-400 hover:bg-white/5 border border-transparent opacity-80 sm:opacity-0 sm:group-hover:opacity-100 focus:opacity-100",
										)}
										title={
											favoriteIds.includes(s.id)
												? t("removeFromFavorites", "Remove from favorites")
												: t("addToFavorites", "Add to favorites")
										}
										aria-label={
											favoriteIds.includes(s.id)
												? t("removeFromFavorites", "Remove from favorites")
												: t("addToFavorites", "Add to favorites")
										}
									>
										<Star
											className={cn(
												"w-4 h-4 transition-transform active:scale-90",
												favoriteIds.includes(s.id)
													? "fill-amber-400 text-amber-400 drop-shadow-[0_0_6px_rgba(251,191,36,0.8)]"
													: "hover:scale-110",
											)}
										/>
									</button>

									<div>
										{/* Top Row: Exchange Logo + Name + Badges */}
										<div className="flex items-start gap-3">
											<div className="relative shrink-0">
												<ExchangeBadge
													exchange={exchange}
													size="xl"
													className={cn(
														"rounded-xl transition-all shadow-md",
														// No exchange logo -> "?" placeholder: muted gray
														// background instead of bright white, with the "?"
														// recolored so it stays readable on gray.
														!exchange &&
															"bg-neutral-600 border-white/10 [&_span]:text-white/75",
														isRunning &&
															"ring-2 ring-cyan/50 shadow-[0_0_15px_-2px_rgba(0,212,255,0.4)]",
													)}
												/>
											</div>

											<div className="min-w-0 flex-1 pr-7">
												<div className="flex items-center gap-1.5 flex-wrap">
													<span
														className="truncate text-[13.5px] font-semibold text-white hover:text-cyan cursor-pointer transition-colors"
														onClick={() => setSelectedStrategyId(s.id)}
														title={s.name}
													>
														{s.name}
													</span>
													<Badge
														tone={
															isRunning
																? "profit"
																: s.status === "ERROR"
																	? "loss"
																	: "neutral"
														}
														dot
														pulse={isRunning}
													>
														{isRunning ? "RUNNING" : s.status || "STOPPED"}
													</Badge>
													{primary && (
														<Badge
															tone={
																primary.mode === "live"
																	? "loss"
																	: "cyan"
															}
														>
															{primary.mode?.toUpperCase() || "PAPER"}
														</Badge>
													)}
												</div>

											{/* Sub-bar: Type + Timeframe */}
											<div className="mt-1 flex items-center gap-2 text-[10.5px] text-white/40">
												<span className="font-mono uppercase text-white/60">
													{timeframe}
												</span>
													<span>·</span>
													<span className="truncate">
														{s.config_data?.strategy_name ||
															"VisualBuilder"}
													</span>
												</div>
											</div>
										</div>

										{/* Symbol Tags */}
										<div className="mt-3 flex flex-wrap gap-1 items-center">
											{symbolsList.slice(0, 4).map((sym) => (
												<span
													key={sym}
													className="rounded-md border border-white/8 bg-white/[0.03] px-2 py-0.5 font-mono text-[10.5px] text-white/70"
												>
													{sym}
												</span>
											))}
											{symbolsList.length > 4 && (
												<span className="rounded-md border border-white/5 bg-white/[0.02] px-1.5 py-0.5 font-mono text-[10px] text-white/40">
													+{symbolsList.length - 4}
												</span>
											)}
										</div>

									{/* Total P&L (live-ticked) & Strategy Equity Sparkline */}
									<div className="mt-3.5 flex items-center justify-between gap-3">
										<div className="flex items-center min-w-[76px]">
											{equity.length >= 2 ? (
												<Sparkline
													data={equity.slice(-30)}
													width={76}
													height={24}
												/>
											) : (
												<span className="w-[76px] text-center font-mono text-[11px] text-white/25">
													—
												</span>
											)}
										</div>

										<div className="text-right font-mono">
											<div
												className={cn(
													"text-[16px] font-semibold leading-tight",
													toneText(pnl),
												)}
											>
												{fmt.signed(pnl, 2)} USDT
											</div>
											<div className="text-[10px] text-white/35">
												{t("colTotalPnl", "Total P&L")}
											</div>
										</div>
									</div>

										{/* Mini Metric Rail */}
										<div className="mt-3 grid grid-cols-3 gap-1.5 rounded-xl border border-white/5 bg-white/[0.02] p-2 text-center">
											<div>
												<div className="text-[9.5px] uppercase tracking-wider text-white/35">
													{t("openPositions", "Positions")}
												</div>
												<div className="font-mono text-[11.5px] font-medium text-white">
													{openPositions}
												</div>
											</div>
											<div>
												<div className="text-[9.5px] uppercase tracking-wider text-white/35">
													{t("copies", "Copies")}
												</div>
												<div className="font-mono text-[11.5px] font-medium text-white">
													{s.instances?.length || 0}
												</div>
											</div>
											<div>
												<div className="text-[9.5px] uppercase tracking-wider text-white/35">
													{t("colRuntime", "Runtime")}
												</div>
												<div className="font-mono text-[11px] text-white/70 truncate">
													{calculateRuntime(primary?.started_at)}
												</div>
											</div>
										</div>
									</div>

									{/* Bottom Action Bar:
										No Pause! Only Stop and Start, and Load in editor, plus Delete when stopped
									*/}
									<div className="mt-4 flex items-center gap-1.5 border-t border-white/5 pt-3">
										{/* Stop Button (if running) */}
										{isRunning ? (
											<Btn
												variant="danger"
												size="xs"
												icon={<Square size={11} />}
												onClick={() => handleStopClick(s, primary)}
												disabled={isActionPending || isStopping}
											>
												{isActionPending && isStopping ? (
													<Loader2 size={11} className="animate-spin mr-1" />
												) : null}
												{t("stopTooltip", "Stop")}
											</Btn>
										) : (
											/* Start Button (if stopped) */
											<Btn
												variant="primary"
												size="xs"
												icon={<Play size={11} />}
												onClick={() => handleStart(s)}
												disabled={isActionPending || isStarting}
											>
												{isActionPending && isStarting ? (
													<Loader2 size={11} className="animate-spin mr-1" />
												) : null}
												{t("startTooltip", "Start")}
											</Btn>
										)}

										{/* Delete Button (Allowed when stopped) */}
										{!isRunning && (
											<Btn
												variant="ghost"
												size="xs"
												icon={<Trash2 size={11} />}
												onClick={() => handleDeleteClick(s)}
												disabled={isActionPending || isDeleting}
												className="text-white/30 hover:text-rose-400 hover:bg-rose-500/10"
												title={t("deleteTooltip", "Delete Strategy")}
											>
												{t("deleteTooltip", "Delete")}
											</Btn>
										)}

										<div className="flex-1" />

										{/* Load in editor ("Загрузить в редактор") */}
										<Btn
											variant="ghost"
											size="xs"
											icon={<Pencil size={11} />}
											onClick={() => navigate(`/editor/${s.id}`)}
											title={t("editButton", "Load in editor")}
											className="text-white/60 hover:text-cyan hover:bg-cyan/10"
										>
											{t("editButton", "Загрузить в редактор")}
										</Btn>
									</div>
								</div>
							);
						})}
					</div>
				)}
			</div>

			{/* Launch Strategy Modal (Configures launch and starts bot) */}
			{launchConfig.strategy && (
				<LaunchStrategyModal
					isOpen={launchConfig.open}
					onClose={() =>
						setLaunchConfig({ open: false, configId: null, strategy: null })
					}
					onConfirm={handleConfirmStart}
					strategyName={launchConfig.strategy.name}
					isLoading={isStarting}
					strategy={launchConfig.strategy}
					currentSymbols={launchConfig.strategy.symbols}
					currentMode={
						(launchConfig.strategy.symbol_selection_mode as
							| "STATIC"
							| "DYNAMIC") || "STATIC"
					}
				/>
			)}

			{/* Stop / Delete Confirmation Modal */}
			<ConfirmationModal
				open={confirmAction.open}
				onOpenChange={(open) =>
					!open && setConfirmAction((prev) => ({ ...prev, open: false }))
				}
				title={confirmAction.title}
				description={confirmAction.description}
				onConfirm={handleConfirmAction}
				loading={confirmAction.actionType === "stop" ? isStopping : isDeleting}
			/>

			{/* Strategy Detail Drawer */}
			{strategyForPanel && (
				<StrategyDetailsPanel
					strategy={strategyForPanel}
					isOpen={!!selectedStrategyId}
					onClose={() => setSelectedStrategyId(null)}
					onStart={() => selectedStrategy && handleStart(selectedStrategy)}
					onStop={() =>
						selectedStrategy && handleStopClick(selectedStrategy)
					}
					onEdit={() => navigate(`/editor/${strategyForPanel.id}`)}
				/>
			)}
		</PageLayout>
	);
}
