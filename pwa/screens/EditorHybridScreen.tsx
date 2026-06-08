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
import type {
	BacktestRequest,
	StrategyConfig,
	StrategyConfigCreatePayload,
	StrategyConfigDB,
} from "../types";
import AIChatScreen from "./AIChatScreen";
import EditorScreen from "./EditorScreen";

interface EditorHybridScreenProps {
	strategyToEdit: Partial<StrategyConfigDB> | null;
	onSaveSuccess?: (savedStrategyId: string) => void;
}

const EditorHybridScreen: React.FC<EditorHybridScreenProps> = ({
	strategyToEdit,
	onSaveSuccess,
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
						(fullStrategy as Record<string, unknown>).foundation_weights ||
						fullStrategy.foundationWeights ||
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
			setMessages([
				{
					id: "editor-chat-greeting",
					role: "ai",
					content: t("editor.aiAssistantGreeting"),
				},
			]);
			setIsLoading(false);
		};

		loadInitialStrategy();
	}, [strategyToEdit, loadStrategy, reset, t, setMessages]);

	const handleStrategyGenerated = (generatedJson: Partial<StrategyConfig>) => {
		loadStrategy(generatedJson);
		toast.success(t("editor.strategyGenerated"));
	};

	const handleRunBacktest = useCallback(
		async (details: { symbol: string; startDate: string; endDate: string }) => {
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
					},
				};
				await api.runBacktest(request);
				toast.success(t("editor.backtestStarted"));
			} catch (error) {
				console.error("Backtest error:", error);
				toast.error(t("editor.errorStartingBacktest"));
			}
		},
		[toJson, t],
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

			const payload: Omit<
				StrategyConfigCreatePayload,
				"symbol_selection_mode" | "symbols"
			> & { foundation_weights: Record<string, number> | null } = {
				name: updatedConfigData.name,
				description: storeState.description,
				config_data: updatedConfigData,
				use_ml_confirmation: storeState.use_ml_confirmation,
				foundation_weights: storeState.useFoundationWeights
					? storeState.foundationWeights
					: null,
			};

			if (storeState.id) {
				savedStrategy = await api.updateStrategyConfig(
					storeState.id,
					payload as unknown as StrategyConfigCreatePayload,
				);
			} else {
				savedStrategy = await api.saveStrategy(
					payload as unknown as StrategyConfigCreatePayload,
				);
			}
			toast.success(
				t("editor.strategySaved", { strategyName: savedStrategy.name }),
			);

			// Update the store with the saved strategy's ID and potentially updated weights
			const savedConfigData =
				savedStrategy.config_data as unknown as Record<string, unknown>;
			const weightsAfterSave =
				(savedStrategy as Record<string, unknown>).foundation_weights ||
				savedStrategy.foundationWeights ||
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
