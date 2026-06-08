// src/screens/StrategiesScreen.tsx

import type React from "react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import LaunchStrategyModal, {
	type LaunchFormData,
} from "../components/LaunchStrategyModal";
import { Logo } from "../components/ui/logo";
import { ICONS } from "../constants";
import { api } from "../services/api";
import type { DisplayStrategy } from "../types";

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
	const { id, name, isRunning, runningInstance } = strategy;
	const pnl = runningInstance?.pnl ?? 0;
	const pnlPositive = pnl >= 0;
	const symbol =
		runningInstance?.symbol ??
		strategy.config_data?.name?.split("•")[0].trim() ??
		"N/A";
	const { t } = useTranslation("pwa-common");
	return (
		<div className="p-4 bg-[hsl(var(--card))] rounded-xl mb-3 shadow-sm">
			<div className="flex items-center">
				<div className="flex-1">
					<div className="text-base font-medium mb-1 text-[hsl(var(--card-foreground))]">
						{name}
					</div>
					<div className="text-sm text-[hsl(var(--muted-foreground))]">
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
				<div className="border-t border-[hsl(var(--border))] mt-3 pt-3 flex gap-2">
					<button
						onClick={() => onStop(id)}
						className="w-full text-sm bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] py-2 rounded-lg flex items-center justify-center gap-2 transition hover:opacity-90"
					>
						{" "}
						<ICONS.Stop className="w-4 h-4" /> {t("strategies.stop")}{" "}
					</button>
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
	const [strategies, setStrategies] = useState<DisplayStrategy[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [launchModalOpen, setLaunchModalOpen] = useState(false);
	const [selectedStrategy, setSelectedStrategy] =
		useState<DisplayStrategy | null>(null);
	const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
	const [strategyToDelete, setStrategyToDelete] = useState<string | null>(null);
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
			const [savedRes, runningRes] = await Promise.all([
				api.getSavedStrategies(),
				api.getRunningStrategies(),
			]);
			const savedConfigs = savedRes;
			const runningInstances = runningRes;
			const runningIds = new Set(runningInstances.map((r) => r.id));
			const merged: DisplayStrategy[] = savedConfigs.map((config) => ({
				...config,
				isRunning: runningIds.has(config.id),
				runningInstance: runningInstances.find((r) => r.id === config.id),
			}));
			setStrategies(merged);
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
