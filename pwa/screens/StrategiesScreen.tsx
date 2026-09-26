// src/screens/StrategiesScreen.tsx

import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import LaunchStrategyModal, {
	type LaunchFormData,
} from "../components/LaunchStrategyModal";
import { Logo } from "../components/ui/logo";
import { ICONS } from "../constants";
import { useLiveMarks } from "../hooks/useLiveMarks";
import {
	applyLiveMarksToPositions,
	overlayLiveStrategyPnl,
	readExchangeOf,
} from "../lib/livePnl";
import { resolveStrategyTimeframe } from "../lib/strategyMeta";
import { api, hasUsableAuthToken } from "../services/api";
import { useAccountStore } from "../stores/accountStore";
import { useRealtimeStore } from "../stores/realtimeStore";
import type { DisplayStrategy, StrategyConfigDB } from "../types";

interface StrategyItemProps {
	strategy: DisplayStrategy;
	onStop: (id: string) => void;
	onStart: (id: string) => void;
	onBacktest: (strategy: DisplayStrategy) => void;
	onEdit: (strategy: DisplayStrategy) => void;
	onDelete: (id: string) => void;
}

const StrategyItem: React.FC<StrategyItemProps> = ({
	strategy,
	onStop,
	onStart,
	onBacktest,
	onEdit,
	onDelete,
}) => {
	const { id, name, isRunning, runningInstance, runningInstances } = strategy;
	const instances = runningInstances && runningInstances.length > 0
		? runningInstances
		: runningInstance
			? [runningInstance]
			: [];
	const pnl =
		instances.length > 0
			? instances.reduce((acc, i) => acc + (i.pnl ?? 0), 0)
			: (runningInstance?.pnl ?? 0);
	const pnlPositive = pnl >= 0;
	const symbol =
		runningInstance?.symbol ??
		strategy.config_data?.name?.split("•")[0].trim() ??
		"N/A";
	const timeframe = resolveStrategyTimeframe(strategy.config_data) ?? "15m";
	const { t } = useTranslation("pwa-common");
	return (
		<div className="p-4 bg-[hsl(var(--card))] rounded-xl mb-3 shadow-sm">
			<div className="flex items-center">
				<div className="flex-1">
					<div className="text-base font-medium mb-1 text-[hsl(var(--card-foreground))]">
						{name}
					</div>
					<div className="text-sm text-[hsl(var(--muted-foreground))]">
						<span className="font-mono uppercase">{timeframe}</span>
						{" · "}
						{symbol}
					</div>
				</div>
				<div className="flex flex-col items-end gap-2">
					<span
						className={`px-3 py-1 rounded-full text-xs font-medium ${isRunning ? "bg-[hsl(var(--profit))] text-[hsl(var(--primary-foreground))]" : "bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))]"}`}
					>
						{isRunning
							? t("strategies.status.running")
							: t("strategies.status.stopped")}
					</span>
					{isRunning && runningInstance?.mode && (
						<span className="px-2 py-0.5 rounded-full text-[10px] font-mono uppercase border border-white/15 text-[hsl(var(--muted-foreground))]">
							{runningInstance.mode}
						</span>
					)}
					{instances.length > 1 && (
						<span className="text-xs text-[hsl(var(--muted-foreground))]">
							{instances.length}{" "}
							{t("strategies.copiesCount", "copies")}
						</span>
					)}
					{isRunning && (
						<span
							className={`text-sm font-medium ${pnlPositive ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}`}
						>
							{" "}
							{pnlPositive ? "+" : ""}${pnl.toLocaleString()}{" "}
						</span>
					)}
				</div>
			</div>
			{!isRunning && (
				<div className="border-t border-[hsl(var(--border))] mt-3 pt-3 space-y-2">
					<div className="flex gap-2">
						<button
							onClick={() => onStart(id)}
							className="flex-1 text-sm bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] py-2 rounded-lg flex items-center justify-center gap-2 transition hover:opacity-90"
						>
							{" "}
							<ICONS.Play className="w-4 h-4" /> {t("strategies.run")}{" "}
						</button>
						<button
							onClick={() => onBacktest(strategy)}
							className="flex-1 text-sm bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] py-2 rounded-lg flex items-center justify-center gap-2 transition hover:bg-[hsl(var(--accent))]"
						>
							{" "}
							<ICONS.History className="w-4 h-4" /> {t(
								"strategies.backtest",
							)}{" "}
						</button>
					</div>
					<div className="flex gap-2">
						<button
							onClick={() => onEdit(strategy)}
							className="flex-1 text-sm bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] py-2 rounded-lg flex items-center justify-center gap-2 transition hover:opacity-90"
						>
							{" "}
							<ICONS.Edit className="w-4 h-4" /> {t("strategies.edit")}{" "}
						</button>
						<button
							onClick={() => onDelete(id)}
							className="flex-1 text-sm bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] py-2 rounded-lg flex items-center justify-center gap-2 transition hover:opacity-90"
						>
							{" "}
							<ICONS.Trash className="w-4 h-4" /> {t("strategies.delete")}{" "}
						</button>
					</div>
				</div>
			)}
			{isRunning && (
				<div className="border-t border-[hsl(var(--border))] mt-3 pt-3 space-y-2">
					{instances.map((inst) => (
						<div
							key={inst.id}
							className="flex items-center justify-between gap-2"
						>
							<div className="flex-1 min-w-0">
								<div className="text-sm font-medium truncate text-[hsl(var(--card-foreground))]">
									{inst.symbol_selection_mode === "STATIC"
										? inst.symbols?.join(", ") || inst.symbol
										: t("strategies.dynamic", "Dynamic")}
								</div>
								<div className="text-xs text-[hsl(var(--muted-foreground))]">
									{inst.mode ? `${inst.mode.toUpperCase()} · ` : ""}
									{inst.open_positions != null
										? `${t("strategies.openPositions", "Open Positions")}: ${inst.open_positions}`
										: ""}
								</div>
							</div>
							<div className="flex items-center gap-2">
								<button
									onClick={() => onStop(inst.id)}
									className="text-sm bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] px-3 py-1.5 rounded-lg flex items-center justify-center gap-2 transition hover:opacity-90"
								>
									<ICONS.Stop className="w-4 h-4" />{" "}
									{t("strategies.stop")}
								</button>
							</div>
						</div>
					))}
				</div>
			)}
		</div>
	);
};

interface StrategiesScreenProps {
	onInitiateBacktest: (strategy: DisplayStrategy) => void;
	onEditStrategy: (strategy: DisplayStrategy) => void;
}

import { useSwipeable } from "react-swipeable";

const StrategiesScreen: React.FC<StrategiesScreenProps> = ({
	onInitiateBacktest,
	onEditStrategy,
}) => {
	const [tab, setTab] = useState<"active" | "saved">("active");
	const [savedConfigs, setSavedConfigs] = useState<StrategyConfigDB[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [launchModalOpen, setLaunchModalOpen] = useState(false);
	const [selectedStrategy, setSelectedStrategy] =
		useState<DisplayStrategy | null>(null);
	const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
	const [strategyToDelete, setStrategyToDelete] = useState<string | null>(null);
	const [refreshing, setRefreshing] = useState(false);
	const lastVisibleRefreshRef = useRef(0);
	// Account scope mirrors the web dashboard: a specific account shows only
	// its own instances, "all" shows everything (pushes merge cross-account).
	const selectedApiKeyId = useAccountStore((s) => s.selectedApiKeyId);
	const { t } = useTranslation("pwa-common");

	const swipeHandlers = useSwipeable({
		onSwipedLeft: () => setTab("saved"),
		onSwipedRight: () => setTab("active"),
		preventScrollOnSwipe: true,
		trackMouse: true,
	});

	const fetchStrategies = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			const [savedRes, liveRes, paperRes] = await Promise.all([
				api.getSavedStrategies(),
				api.getRunningStrategies("live"),
				api.getRunningStrategies("paper"),
			]);
			setSavedConfigs(savedRes ?? []);
			const rt = useRealtimeStore.getState();
			rt.setStrategies("live", liveRes ?? []);
			rt.setStrategies("paper", paperRes ?? []);
		} catch (err) {
			console.error(err);
			setError(t("profile.failedToLoadPlans"));
		} finally {
			setLoading(false);
		}
	}, [t]);

	useEffect(() => {
		const timer = setTimeout(() => {
			fetchStrategies();
		}, 0);
		return () => clearTimeout(timer);
	}, [fetchStrategies]);

	// Manual + visibility refresh: full REST truth (saved + running both
	// modes + positions for the overlay). Used to recover from any stale
	// push-merge state; throttled for visibility events.
	const handleManualRefresh = useCallback(async () => {
		if (refreshing) return;
		if (!hasUsableAuthToken()) return;
		setRefreshing(true);
		try {
			const [savedRes, liveRun, paperRun, livePos, paperPos] =
				await Promise.all([
					api.getSavedStrategies(),
					api.getRunningStrategies("live"),
					api.getRunningStrategies("paper"),
					api.getPositions("live"),
					api.getPositions("paper"),
				]);
			setSavedConfigs(savedRes ?? []);
			const rt = useRealtimeStore.getState();
			rt.setStrategies("live", liveRun ?? []);
			rt.setStrategies("paper", paperRun ?? []);
			rt.setPositions("live", livePos ?? []);
			rt.setPositions("paper", paperPos ?? []);
		} catch (err) {
			console.error("Failed manual refresh:", err);
		} finally {
			setRefreshing(false);
		}
	}, [refreshing]);

	useEffect(() => {
		const onVis = () => {
			if (document.visibilityState !== "visible") return;
			if (Date.now() - lastVisibleRefreshRef.current < 10000) return;
			lastVisibleRefreshRef.current = Date.now();
			void handleManualRefresh();
		};
		document.addEventListener("visibilitychange", onVis);
		return () => document.removeEventListener("visibilitychange", onVis);
	}, [handleManualRefresh]);

	// Snapshot positions for the live PnL overlay (both modes, shared store).
	const setStorePositions = useRealtimeStore((s) => s.setPositions);
	useEffect(() => {
		let cancelled = false;
		Promise.all([api.getPositions("live"), api.getPositions("paper")])
			.then(([liveRes, paperRes]) => {
				if (cancelled) return;
				setStorePositions("live", liveRes || []);
				setStorePositions("paper", paperRes || []);
			})
			.catch((err) => console.error("Failed to fetch positions:", err));
		return () => {
			cancelled = true;
		};
	}, [setStorePositions]);

	const liveModeStrategies = useRealtimeStore((s) => s.strategiesByMode.live);
	const paperModeStrategies = useRealtimeStore((s) => s.strategiesByMode.paper);
	const storeStrategies = useMemo(
		() => [...liveModeStrategies, ...paperModeStrategies],
		[liveModeStrategies, paperModeStrategies],
	);
	const tradesSeq = useRealtimeStore((s) => s.tradesSeq);
	const wsConnected = useRealtimeStore((s) => s.wsConnected);
	const strategyRemovalSeq = useRealtimeStore((s) => s.strategyRemovalSeq);
	const lastReconcileRef = useRef(0);
	// Stable selectors + memo: never spread inside a selector (new identity
	// every evaluation causes an infinite re-render loop, React error #185).
	const liveModePositions = useRealtimeStore((s) => s.positionsByMode.live);
	const paperModePositions = useRealtimeStore((s) => s.positionsByMode.paper);
	const snapshotPositions = useMemo(
		() => [...liveModePositions, ...paperModePositions],
		[liveModePositions, paperModePositions],
	);

	// Live mark-prices straight from exchanges (zero backend load).
	// useLiveMarks reconnects only when the symbol set actually changes.
	const { marks: strategyMarks } = useLiveMarks(
		snapshotPositions.map((p) => ({
			symbol: String(p.symbol),
			exchange: readExchangeOf(p),
		})),
	);
	const liveSnapshotPositions = useMemo(
		() => applyLiveMarksToPositions(snapshotPositions, strategyMarks),
		[snapshotPositions, strategyMarks],
	);
	const liveRunningStrategies = useMemo(
		() =>
			overlayLiveStrategyPnl(
				storeStrategies,
				snapshotPositions,
				liveSnapshotPositions,
			) ?? storeStrategies,
		[storeStrategies, snapshotPositions, liveSnapshotPositions],
	);

	// A push removed strategies: it may be a legit stop — or a stale push
	// wiping live rows. Reconcile with REST (authoritative) after a short
	// delay, throttled so a flapping publisher can't cause a request storm.
	useEffect(() => {
		if (strategyRemovalSeq === 0) return;
		if (Date.now() - lastReconcileRef.current < 20000) return;
		const timer = setTimeout(async () => {
			lastReconcileRef.current = Date.now();
			try {
				const [liveRes, paperRes] = await Promise.all([
					api.getRunningStrategies("live"),
					api.getRunningStrategies("paper"),
				]);
				const rt = useRealtimeStore.getState();
				rt.setStrategies("live", liveRes || []);
				rt.setStrategies("paper", paperRes || []);
			} catch (err) {
				console.error("Failed to reconcile strategies:", err);
			}
		}, 4000);
		return () => clearTimeout(timer);
	}, [strategyRemovalSeq]);

	// Trades push (position closed) → refresh the running list.
	useEffect(() => {
		if (tradesSeq === 0) return;
		let cancelled = false;
		Promise.all([
			api.getRunningStrategies("live"),
			api.getRunningStrategies("paper"),
		])
			.then(([liveRes, paperRes]) => {
				if (!cancelled) {
					const rt = useRealtimeStore.getState();
					rt.setStrategies("live", liveRes || []);
					rt.setStrategies("paper", paperRes || []);
				}
			})
			.catch((err) => console.error("Failed to refresh strategies:", err));
		return () => {
			cancelled = true;
		};
	}, [tradesSeq]);

	// Fallback polling while the socket is down (realtime is push-driven).
	// Skipped without a usable token to avoid 401 storms when logged out.
	useEffect(() => {
		if (wsConnected) return;
		const id = setInterval(async () => {
			if (!hasUsableAuthToken()) return;
			try {
				const [runningLive, runningPaper, liveRes, paperRes] = await Promise.all([
					api.getRunningStrategies("live"),
					api.getRunningStrategies("paper"),
					api.getPositions("live"),
					api.getPositions("paper"),
				]);
				useRealtimeStore.getState().setStrategies("live", runningLive || []);
				useRealtimeStore.getState().setStrategies("paper", runningPaper || []);
				setStorePositions("live", liveRes || []);
				setStorePositions("paper", paperRes || []);
			} catch (err) {
				console.error("Failed fallback refresh:", err);
			}
		}, 5000);
		return () => clearInterval(id);
	}, [wsConnected, setStorePositions]);

	// Account-scoped view (web parity): a specific account shows only its
	// own instances; push-merged foreign rows never flash on screen.
	const scopedRunningStrategies = useMemo(() => {
		if (selectedApiKeyId === "all") return liveRunningStrategies;
		return liveRunningStrategies.filter((inst) => {
			if (inst.mode === "paper") return true;
			const k = (inst as unknown as Record<string, unknown>).api_key_id;
			return (
				k !== null && k !== undefined && Number(k) === Number(selectedApiKeyId)
			);
		});
	}, [liveRunningStrategies, selectedApiKeyId]);

	// Refetch when the selected account changes (REST is account-filtered).
	const firstAccountRef = useRef(true);
	useEffect(() => {
		if (firstAccountRef.current) {
			firstAccountRef.current = false;
			return;
		}
		fetchStrategies();
	}, [selectedApiKeyId, fetchStrategies]);
	const strategies = useMemo((): DisplayStrategy[] => {
		const instancesByConfig = new Map<
			string,
			(typeof scopedRunningStrategies)[number][]
		>();
		for (const inst of scopedRunningStrategies) {
			const keys = new Set<string>();
			if (inst.config_id) keys.add(String(inst.config_id));
			if (inst.id) keys.add(String(inst.id));
			for (const key of keys) {
				const arr = instancesByConfig.get(key) ?? [];
				if (!arr.some((existing) => existing.id === inst.id)) {
					arr.push(inst);
				}
				instancesByConfig.set(key, arr);
			}
		}
		const matchedIds = new Set<string>();
		const mapped = savedConfigs.map((config) => {
			const configIdStr = String(config.id);
			const instances = instancesByConfig.get(configIdStr) ?? [];
			instances.forEach((i) => matchedIds.add(i.id));
			const primary = instances[0];
			const isRunning = instances.length > 0;
			return {
				...config,
				...(primary ? primary : {}),
				id: config.id,
				name: config.name,
				status: isRunning ? primary?.status || "RUNNING" : "STOPPED",
				isRunning,
				runningInstance: primary,
				runningInstances: instances,
				instances,
			} as unknown as DisplayStrategy;
		});
		// Running instances whose config is gone (deleted/duplicate config,
		// webhook launches): show them anyway so live bots never hide.
		const orphans = scopedRunningStrategies
			.filter((inst) => !matchedIds.has(inst.id))
			.map(
				(inst) =>
					({
						...inst,
						id: inst.id,
						name: inst.strategy_name,
						isRunning: true,
						runningInstance: inst,
						runningInstances: [inst],
						instances: [inst],
						status: inst.status,
					}) as unknown as DisplayStrategy,
			);
		return [...mapped, ...orphans];
	}, [savedConfigs, scopedRunningStrategies]);

	const handleStartStrategy = (id: string) => {
		const strategy = strategies.find((s) => s.id === id);
		if (strategy) {
			setSelectedStrategy(strategy);
			setLaunchModalOpen(true);
		}
	};

	const handleConfirmLaunch = async (details: LaunchFormData) => {
		if (!selectedStrategy) return;

		try {
			const symbolsArray =
				details.symbolSelectionMode === "STATIC" && details.symbols
					? details.symbols
							.split(",")
							.map((s) => s.trim())
							.filter(Boolean)
					: [];

			// Build params object with all dynamic settings
			const params: Record<string, unknown> = {};

			if (details.symbolSelectionMode === "DYNAMIC") {
				params.max_concurrent_symbols = details.maxConcurrentSymbols;

				if (details.dynamicMode === "DYNAMIC_NATR") {
					params.natr_settings = { min_natr: details.minNatr };
					params.oracle_settings = null;
					params.oracle_regime = null;
					params.oracle_confidence = 0;
				} else if (details.dynamicMode === "DYNAMIC_ORACLE") {
					const regime = parseInt(details.oracleRegime || "1", 10);
					const confidence = details.oracleConfidence || 95;
					params.oracle_settings = { regime, confidence };
					params.oracle_regime = regime;
					params.oracle_confidence = confidence;
					params.natr_settings = null;
				}
			} else {
				params.oracle_regime = null;
				params.oracle_confidence = 0;
			}

			// ML & Regime settings
			params.use_ml_confirmation = details.useMlConfirmation ?? false;
			params.breakeven_on_regime_change =
				details.breakevenOnRegimeChange ?? false;

			await api.startStrategy(
				selectedStrategy.id,
				details.mode,
				details.symbolSelectionMode,
				symbolsArray.length > 0 ? symbolsArray : undefined,
				params,
			);

			alert(
				t("backtestResultScreen.toast.strategySavedAndLaunched", {
					strategyName: selectedStrategy.name,
				}),
			);
			setLaunchModalOpen(false);
			setSelectedStrategy(null);
			setTimeout(fetchStrategies, 1000);
		} catch (err) {
			console.error(err);
			alert(t("backtestResultScreen.toast.errorLaunchingStrategy"));
		}
	};

	const handleStopStrategy = async (id: string) => {
		try {
			await api.stopStrategy(id);
			alert(t("profile.closePositionCommandSent"));
			setTimeout(fetchStrategies, 1000);
		} catch (err) {
			console.error(err);
			alert(t("profile.errorClosingPosition"));
		}
	};

	const handleEditStrategy = (strategy: DisplayStrategy) => {
		onEditStrategy(strategy);
	};

	const handleDeleteStrategy = (id: string) => {
		setStrategyToDelete(id);
		setDeleteConfirmOpen(true);
	};

	const confirmDelete = async () => {
		if (!strategyToDelete) return;

		try {
			await api.deleteStrategyConfig(strategyToDelete);
			alert(t("profile.accountDeleted"));
			setDeleteConfirmOpen(false);
			setStrategyToDelete(null);
			fetchStrategies();
		} catch (err) {
			console.error(err);
			alert(t("profile.failedToDeleteAccount"));
		}
	};

	const activeStrategies = strategies.filter((s) => s.isRunning);
	const savedStrategies = strategies.filter((s) => !s.isRunning);
	const strategiesToShow =
		tab === "active" ? activeStrategies : savedStrategies;

	return (
		// --- 3. Apply handlers to the main container ---
		<div {...swipeHandlers} className="p-4">
			<div className="flex justify-end items-center gap-2 mb-2">
				<button
					type="button"
					onClick={() => void handleManualRefresh()}
					disabled={refreshing}
					className="rounded-full border border-white/15 px-2 py-0.5 font-mono text-[10px] text-[hsl(var(--muted-foreground))] disabled:opacity-50"
					title={t("strategies.refresh", "Refresh")}
				>
					{refreshing ? "…" : "↻"}
				</button>
				<span
					className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
						wsConnected
							? "border-emerald-400/30 text-emerald-600"
							: "border-amber-400/30 text-amber-600"
					}`}
				>
					{wsConnected
						? t("strategies.realtimeLive", "live")
						: t("strategies.realtimePolling", "polling")}
				</span>
			</div>
			<div className="flex gap-2 mb-4 p-1 bg-[hsl(var(--secondary))] rounded-lg">
				<button
					onClick={() => setTab("active")}
					className={`flex-1 py-2 text-sm rounded-md transition-all ${tab === "active" ? "bg-[hsl(var(--card))] shadow text-[hsl(var(--card-foreground))]" : "bg-transparent text-[hsl(var(--muted-foreground))]"}`}
				>
					{t("strategies.status.running")} ({activeStrategies.length})
				</button>
				<button
					onClick={() => setTab("saved")}
					className={`flex-1 py-2 text-sm rounded-md transition-all ${tab === "saved" ? "bg-[hsl(var(--card))] shadow text-[hsl(var(--card-foreground))]" : "bg-transparent text-[hsl(var(--muted-foreground))]"}`}
				>
					{t("strategies.status.stopped")} ({savedStrategies.length})
				</button>
			</div>

			<div className="min-h-[600px] relative">
				{loading ? (
					<div className="absolute inset-0 flex items-center justify-center">
						<Logo size="lg" className="mb-8" />
					</div>
				) : (
					<div key={tab} className="animate-fadeIn h-full">
						{error && (
							<p className="text-center text-[hsl(var(--loss))]">{error}</p>
						)}

						{!error && (
							<div className="h-full">
								{strategiesToShow.length > 0 ? (
									strategiesToShow.map((strategy) => (
										<StrategyItem
											key={strategy.id}
											strategy={strategy}
											onStop={handleStopStrategy}
											onStart={handleStartStrategy}
											onBacktest={onInitiateBacktest}
											onEdit={handleEditStrategy}
											onDelete={handleDeleteStrategy}
										/>
									))
								) : (
									<div className="h-full flex items-center justify-center">
										<p className="text-center text-sm text-[hsl(var(--muted-foreground))]">
											{tab === "active"
												? t("profile.noActivePositions")
												: t("profile.noAchievements")}
										</p>
									</div>
								)}
							</div>
						)}
					</div>
				)}
			</div>
			<div className="h-24"></div>

			<LaunchStrategyModal
				isOpen={launchModalOpen}
				onClose={() => {
					setLaunchModalOpen(false);
					setSelectedStrategy(null);
				}}
				onSubmit={handleConfirmLaunch}
				strategy={selectedStrategy}
			/>

			{/* Delete Confirmation Modal */}
			{deleteConfirmOpen && (
				<>
					<div
						className="fixed inset-0 bg-black/50 z-40 transition-opacity duration-300"
						onClick={() => setDeleteConfirmOpen(false)}
					></div>
					<div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[90%] max-w-md bg-[hsl(var(--card))] rounded-3xl shadow-[-4px_0_20px_rgba(0,0,0,0.1)] p-6 z-50">
						<h2 className="text-xl font-medium mb-2 text-[hsl(var(--card-foreground))]">
							{t("profile.deleteAccountTitle")}
						</h2>
						<p className="text-sm text-[hsl(var(--muted-foreground))] mb-6">
							{t("profile.deleteAccountDescription")}
						</p>
						<div className="flex gap-3">
							<button
								className="flex-1 py-3 rounded-lg border-none text-sm font-medium bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] transition hover:opacity-90"
								onClick={() => setDeleteConfirmOpen(false)}
							>
								{t("buttons.cancel")}
							</button>
							<button
								className="flex-1 py-3 rounded-lg border-none text-sm font-medium bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] transition hover:opacity-90"
								onClick={confirmDelete}
							>
								{t("strategies.delete")}
							</button>
						</div>
					</div>
				</>
			)}
		</div>
	);
};

export default StrategiesScreen;
