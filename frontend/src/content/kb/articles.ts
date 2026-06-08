export interface KBArticle {
	id: string;
	title: string;
	description: string;
	category: "getting-started" | "features" | "billing" | "advanced";
	tags: string[];
}

export const kbArticles: Record<"ru" | "en", KBArticle[]> = {
	ru: [
		{
			id: "api-setup",
			title: "Setting up API keys",
			description: "How to correctly connect your exchange to DepthSight",
			category: "getting-started",
			tags: ["binance", "bybit", "api", "security"],
		},
		{
			id: "backtest-basics",
			title: "Backtesting basics",
			description: "How to test strategies on historical data",
			category: "features",
			tags: ["backtest", "analytics", "statistics"],
		},
		{
			id: "risk-management",
			title: "Risk management",
			description: "Setting up stop-losses and drawdown limits",
			category: "advanced",
			tags: ["risk", "money management", "stop-loss"],
		},
	],
	en: [
		{
			id: "api-setup",
			title: "API Keys Setup",
			description: "How to correctly connect your exchange to DepthSight",
			category: "getting-started",
			tags: ["binance", "bybit", "api", "security"],
		},
		{
			id: "backtest-basics",
			title: "Backtesting Basics",
			description: "How to test strategies on historical data",
			category: "features",
			tags: ["backtest", "analytics", "statistics"],
		},
		{
			id: "risk-management",
			title: "Risk Management",
			description: "Configuring stop-losses and drawdown limits",
			category: "advanced",
			tags: ["risk", "money management", "stop-loss"],
		},
	],
};
