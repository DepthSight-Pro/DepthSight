// pwa/services/geminiService.ts

import i18n from "../i18n";
import type { BacktestRun, StrategyConfig } from "../types";
import { api } from "./api";

export const getInitialGreeting = (): string => {
	// The greeting can be left on the frontend, it is static
	return i18n.t("aiChat.initialGreeting", {
		defaultValue:
			"Hello! I am your AI assistant for creating trading strategies. Describe what strategy you want to create?",
	});
};

export const getAIResponse = async (userMessage: string): Promise<string> => {
	// Call the backend in 'advisor' mode
	const response = await api.aiChat({
		text_prompt: userMessage,
		mode: "advisor",
		session_id: "placeholder_session_id", // TODO: Replace with actual session ID
		// Not passing history yet for simplicity, but it can be added
	});

	return response.text_response;
};

export const generateStrategyConfig = async (
	userPrompt: string,
): Promise<StrategyConfig> => {
	// Call the backend in 'generator' mode
	// Important: your generator needs a userPrompt to understand what to do
	const response = await api.aiChat({
		text_prompt: userPrompt, // Pass the user's last message
		mode: "generator",
		session_id: "placeholder_session_id", // TODO: Replace with actual session ID
	});

	if (!response.strategy_json) {
		throw new Error("AI failed to generate a valid strategy configuration.");
	}

	return response.strategy_json;
};

export const getAIAnalysisForBacktest = async (
	data: BacktestRun,
): Promise<string> => {
	// Call the backend in 'advisor' mode with the backtest context
	const response = await api.aiChat({
		text_prompt: i18n.t("aiChat.analyzeBacktestPrompt", {
			strategyName: data.strategy_name,
			defaultValue: `Please analyze this backtest: ${data.strategy_name}`,
		}),
		mode: "advisor",
		backtest_id: data.id, // Pass backtest ID
		session_id: "placeholder_session_id", // TODO: Replace with actual session ID
	});

	return response.text_response;
};
