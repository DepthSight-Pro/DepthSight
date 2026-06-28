// pwa/screens/EditorHybridScreen.tsx

import type React from "react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSwipeable } from "react-swipeable";
import { toast } from "sonner";
import { Logo } from "../components/ui/logo";
import { useAIChat } from "../contexts/AIChatContext";
import { api } from "../services/api";
import { useStrategyEditorStore } from "../stores/strategyEditorStore";
import { Screen } from "../types";
import type {
	BacktestRequest,
	StrategyConfigData,
	StrategyConfigDB,
} from "../types";
import AIChatScreen from "./AIChatScreen";
import EditorScreen from "./EditorScreen";

interface EditorHybridScreenProps {
	strategyToEdit: Partial<StrategyConfigDB> | null;
	onSaveSuccess?: (savedStrategyId: string) => void;
	onNavigate?: (screen: Screen) => void;
}

const EditorHybridScreen: React.FC<EditorHybridScreenProps> = ({
	strategyToEdit,
	onSaveSuccess,
	onNavigate,
}) => {
	const [activeTab, setActiveTab] = useState<"constructor" | "ai">(
		"constructor",
	);
	const [isLoading, setIsLoading] = useState(true);
	const { t } = useTranslation("pwa-common");

	const { loadStrategy, toJson, reset } = useStrategyEditorStore();
	const { setMessages } = useAIChat();

	const swipeHandlers = useSwipeable({
		onSwipedLeft: () => setActiveTab("ai"),
		onSwipedRight: () => setActiveTab("constructor"),
		preventScrollOnSwipe: true,
		trackMouse: true,
	});

	useEffect(() => {
		const loadInitialStrategy = async () => {
			setIsLoading(true);
			if (strategyToEdit?.id) {
				// Existing strategy
				try {
					const fullStrategy = await api.getStrategyConfig(strategyToEdit.id);
					const configData = fullStrategy.config_data as Record<string, unknown>;
					const weightsFromApi =
						(fullStrategy as unknown as Record<string, unknown>).foundation_weights ||
						(fullStrategy as unknown as Record<string, unknown>).foundationWeights ||
						configData?.foundation_weights ||
						configData?.foundationWeights ||
						{};
					loadStrategy({
						...fullStrategy.config_data,
						id: fullStrategy.id,
						name: fullStrategy.name,
						description: fullStrategy.description || "",
						foundationWeights: weightsFromApi as Record<string, number>,
					});
				} catch (error) {
					console.error("Failed to load strategy:", error);
					toast.error(t("editor.errorLoadingStrategy"));
				}
			} else if (strategyToEdit) {
				// New strategy from backtest or AI
				loadStrategy(strategyToEdit);
			} else {
				// New strategy from scratch
				reset();
			}
			setMessages((prev) => {
				// If we already have a conversation history, preserve it
				if (
					prev.length > 1 ||
					(prev.length === 1 &&
						prev[0].id !== "initial-greeting" &&
						prev[0].id !== "editor-chat-greeting")
				) {
					return prev;
				}
				// Otherwise, set the editor-specific greeting
				return [
					{
						id: "editor-chat-greeting",
						role: "ai",
						content: t("editor.aiAssistantGreeting"),
					},
				];
			});
			setIsLoading(false);
		};

		loadInitialStrategy();
	}, [strategyToEdit, loadStrategy, reset, t, setMessages]);

	const handleStrategyGenerated = (generatedJson: Partial<StrategyConfigData>) => {
		loadStrategy(generatedJson as Record<string, unknown>);
		setActiveTab("constructor");
		toast.success(t("editor.strategyGenerated"));
	};

	const handleRunBacktest = useCallback(
		async (details: {
			symbol: string;
			startDate: string;
			endDate: string;
			backtestEngine: "vector" | "kline";
		}) => {
			try {
				const configData = toJson();
				const request: BacktestRequest = {
					strategy_name: configData.name,
					symbol: details.symbol,
					start_date: new Date(details.startDate).toISOString(),
					end_date: new Date(details.endDate).toISOString(),
					market_type: configData.marketType.toLowerCase() as
						| "spot"
						| "futures",
					params: {
						config: configData,
						backtest_engine: details.backtestEngine,
					},
				};
				await api.runBacktest(request);
				toast.success(t("editor.backtestStarted"));
				onNavigate?.(Screen.Research);
			} catch (error) {
				console.error("Backtest error:", error);
				toast.error(t("editor.errorStartingBacktest"));
			}
		},
		[toJson, t, onNavigate],
	);

	const handleSaveStrategy = useCallback(async () => {
		try {
			const storeState = useStrategyEditorStore.getState();
			const configData = toJson();
			const updatedConfigData = {
				enabled: true,
				strategy_name: "VisualBuilderStrategy",
				...configData,
			};
			let savedStrategy: StrategyConfigDB;

			const payload = {
				name: updatedConfigData.name,
				description: storeState.description,
				config_data: updatedConfigData as unknown as StrategyConfigData,
				use_ml_confirmation: storeState.use_ml_confirmation,
				foundation_weights: storeState.useFoundationWeights
					? storeState.foundationWeights
					: null,
				oracle_regime: storeState.oracleRegime,
				oracle_confidence: storeState.oracleConfidence,
				symbol_selection_mode: storeState.symbol_selection_mode === "STATIC" ? "STATIC" : "DYNAMIC" as "STATIC" | "DYNAMIC",
				symbols: storeState.symbol_selection_mode === "STATIC" ? [storeState.symbol] : [],
			};

			if (storeState.id) {
				savedStrategy = await api.updateStrategyConfig(
					storeState.id,
					payload
				);
			} else {
				savedStrategy = await api.saveStrategy(
					payload
				);
			}
			toast.success(
				t("editor.strategySaved", { strategyName: savedStrategy.name }),
			);

			// Update the store with the saved strategy's ID and potentially updated weights
			const savedConfigData =
				savedStrategy.config_data as unknown as Record<string, unknown>;
			const weightsAfterSave =
				(savedStrategy as unknown as Record<string, unknown>).foundation_weights ||
				(savedStrategy as unknown as Record<string, unknown>).foundationWeights ||
				savedConfigData?.foundation_weights ||
				savedConfigData?.foundationWeights ||
				{};

			loadStrategy({
				...savedStrategy.config_data,
				id: savedStrategy.id,
				name: savedStrategy.name,
				description: savedStrategy.description || "",
				foundationWeights: weightsAfterSave as Record<string, number>,
			});

			if (onSaveSuccess) onSaveSuccess(savedStrategy.id);
		} catch (error) {
			console.error("Save error:", error);
			toast.error(t("editor.errorSavingStrategy"));
		}
	}, [toJson, loadStrategy, onSaveSuccess, t]);

	if (isLoading) {
		// 2. Replace div with logo
		return (
			<div className="flex items-center justify-center h-full">
				<Logo size="lg" className="mb-8 animate-pulse" />
			</div>
		);
	}

	return (
		<div className="flex flex-col h-full">
			<div className="flex border-b border-[hsl(var(--border))] bg-[hsl(var(--background))]">
				<button
					className={`flex-1 p-3 text-sm font-medium transition-colors ${activeTab === "constructor" ? "text-[hsl(var(--primary))] border-b-2 border-[hsl(var(--primary))]" : "text-[hsl(var(--muted-foreground))]"}`}
					onClick={() => setActiveTab("constructor")}
				>
					{t("editor.constructor")}
				</button>
				<button
					className={`flex-1 p-3 text-sm font-medium transition-colors ${activeTab === "ai" ? "text-[hsl(var(--primary))] border-b-2 border-[hsl(var(--primary))]" : "text-[hsl(var(--muted-foreground))]"}`}
					onClick={() => setActiveTab("ai")}
				>
					✨ {t("editor.aiAssistant")}
				</button>
			</div>
			<main
				{...swipeHandlers}
				className="flex-1 overflow-y-auto min-h-0 relative"
			>
				<div
					style={{
						display: activeTab === "ai" ? "block" : "none",
						height: "100%",
					}}
				>
					<AIChatScreen onStrategyGenerated={handleStrategyGenerated} />
				</div>
				<div
					style={{
						display: activeTab === "constructor" ? "block" : "none",
						height: "100%",
					}}
				>
					<EditorScreen
						onSave={handleSaveStrategy}
						isSaving={false} // TODO: Implement actual saving state
						onInitiateBacktest={handleRunBacktest}
					/>
				</div>
			</main>
		</div>
	);
};

export default EditorHybridScreen;
