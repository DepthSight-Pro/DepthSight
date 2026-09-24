// frontend/src/lib/nodeLeaderboardPlans.ts

import type { AdminPlanItem } from "@/types/api";

// Default baseline plans for nodes that have not customized their tiers yet
export const DEFAULT_NODE_PLANS: Record<string, AdminPlanItem> = {
	free: {
		name: "Free",
		price_usd: 0,
		active: true,
		description: "Basic capabilities and standard strategy blocks.",
		features: ["20 fast backtests per day", "Standard blocks (Logic, Indicators, Proximity)", "Limited history (90 days)", "10 AI Assistant queries per day"],
		quotas: {
			run_vector_backtest_per_day: 20,
			use_ai_assistant_per_day: 10,
		},
		limits: {
			allow_real_trading: false,
			max_live_strategies: 0,
			max_backtest_duration_days: 90,
		},
	},
	standard: {
		name: "Standard",
		price_usd: 19,
		active: true,
		description: "For active traders. Live trading and standard blocks.",
		features: ["50 backtests per day", "35 AI Assistant queries per day", "Live trading enabled", "10 live trading strategies"],
		quotas: {
			run_vector_backtest_per_day: 50,
			use_ai_assistant_per_day: 35,
		},
		limits: {
			allow_real_trading: true,
			max_live_strategies: 10,
			max_backtest_duration_days: 365,
		},
	},
	pro: {
		name: "Professional",
		price_usd: 49,
		active: true,
		description: "Maximum power. Access to all PRO blocks and genetic search.",
		features: ["Unlimited backtests", "50 AI Assistant queries per day", "Access to PRO blocks (Tape, Book, OI)", "30 live trading strategies"],
		quotas: {
			run_vector_backtest_per_day: -1,
			use_ai_assistant_per_day: 50,
		},
		limits: {
			allow_real_trading: true,
			max_live_strategies: 30,
			max_backtest_duration_days: -1,
			allow_intracandle_triggers: true,
		},
		billing: {
			lifetime: {
				enabled: true,
				price_usd: 99,
				slot_limit: 50,
			},
		},
	},
};
