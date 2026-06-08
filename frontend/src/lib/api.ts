// src/lib/api.ts

import {
	keepPreviousData,
	useMutation,
	useQuery,
	useQueryClient,
} from "@tanstack/react-query";
import type {
	AccountStatusData,
	Achievement,
	AddApiKeyPayload,
	AdminBonusPayload,
	AdminUser,
	AdminUserExtendedDetails,
	AdminUserUpdatePayload,
	AffiliateDashboardStats,
	AIChatMessage,
	ApiKey,
	AppConfig,
	AvailableBonus,
	BacktestRequest,
	BacktestRunDetailsData,
	BacktestRunListItemData,
	BacktestTrade,
	BEAnalysisStats,
	BEScatterDataResponse,
	BinanceKline,
	DashboardStats,
	DatasetRunCreate,
	DatasetRunResponse,
	FoundationStat,
	FoundStrategyData,
	GeneStatsResponse,
	GeneticSearchRunDetailsData,
	GeneticSearchRunListItemData,
	GeneticSearchRunRequest,
	ImpersonateToken,
	LogEntry,
	MarketScope,
	MarketSentimentStat,
	ModelTrainingReport,
	OptimizationRequest,
	PaginatedAdminAffiliateCommissions,
	PaginatedAdminAffiliateReferrals,
	PaginatedAdminUsers,
	PaginatedAffiliateCommissions,
	PaginatedAffiliatePayouts,
	PaginatedAffiliateReferrals,
	PaginatedPhantomTradesResponse,
	PaperWalletData,
	PayoutDetailsPayload,
	PortfolioBacktestRequest,
	PortfolioBacktestRunDetailsData,
	PortfolioBacktestRunListItemData,
	PortfolioData,
	PositionData,
	ShareBacktestPayload,
	ShareBacktestResponse,
	SharedBacktestData,
	StrategyConfig,
	StrategyConfigCreatePayload,
	StrategyConfigData,
	StrategyData,
	StrategyRunRequest,
	SymbolSelectionConfig,
	SystemMetrics,
	SystemStatusData,
	TaskData,
	TradeData,
	TradingViewTestSignalRequest,
	TradingViewWebhookInfo,
	TradingViewWebhookStatus,
	TrainingRunCreate,
	TrainingRunResponse,
	UserAchievement,
	UserGenesResponse,
} from "@/types/api";
import type {
	AdminSupportTicket,
	SupportTicket,
	SupportTicketCreate,
	SupportTicketMessage,
	SupportTicketMessageCreate,
	SupportTicketUpdate,
} from "@/types/support";

export type { AIChatMessage };

export interface Plan {
	key: string;
	name: string;
	price_usd: number;
	active: boolean;
	billing_mode?: "monthly" | "lifetime";
	period_label?: "month" | "lifetime";
	slots?: {
		limit: number;
		used: number;
		reserved: number;
		available: number;
	} | null;
	description: string;
	features: string[];
}

export interface AIChatRequest {
	text_prompt: string;
	session_id: string;
	backtest_id?: string;
	history?: { role: "user" | "assistant"; content: string }[];
	mode?: "advisor" | "generator" | "analyst";
	strategy_json?: Record<string, unknown>;
	analytics_context?: unknown;
	image_base64?: string;
	image_mime_type?: string;
}

export interface AIChatResponse {
	text_response: string;
	session_id: string;
	strategy_json?: Record<string, unknown>;
	analytics_context?: unknown;
}

export interface BitcartPayment {
	payment_address: string;
	payment_url: string;
	amount: string;
	currency: string;
	payment_method?: string;
}

export interface CreatePaymentResponse {
	invoice_id: string;
	invoice_url: string;
	payment_address: string | null;
	payment_url: string | null;
	amount: string | null;
	currency: string | null;
	price_usd: number;
	expiration_seconds: number;
	status: string;
	payments?: BitcartPayment[];
}

import { useTranslation } from "react-i18next";
import type { StrategyState } from "@/components/strategy-editor/types";
import { useToast } from "@/components/ui/use-toast";
import { useApiErrorHandler } from "@/hooks/useApiErrorHandler";
import {
	type BlockRestrictionsConfig,
	DEFAULT_BLOCK_RESTRICTIONS,
	normalizeBlockRestrictions,
} from "@/lib/strategyRestrictions";
import { fetchBinanceKlines } from "./binanceApi";
import { authScopedQueryKey } from "./queryKeys";

export interface TradeHistoryParams {
	strategy?: string;
	strategyConfigId?: string;
	symbol?: string;
	dateFrom?: string;
	dateTo?: string;
	mode?: "live" | "paper";
	limit?: number;
	skip?: number;
	[key: string]: string | number | undefined;
}

// --- NEW TYPE FOR PASSING DATA TO AI HOOK ---
export interface GenerateStrategyPayload {
	text_prompt: string;
	current_config_json?: Record<string, unknown> | StrategyConfigData;
	user_tier?: string;
}

export const useGetLatestChatSession = () => {
	return useQuery<string | null, Error>({
		queryKey: authScopedQueryKey("latestChatSession"),
		queryFn: () => apiClient<string | null>("/ai/chat/latest-session"),
	});
};

export const useGetChatHistory = (sessionId: string | null) => {
	return useQuery<AIChatMessage[], Error>({
		queryKey: authScopedQueryKey("chatHistory", sessionId),
		queryFn: () => apiClient<AIChatMessage[]>(`/ai/chat/history/${sessionId}`),
		enabled: !!sessionId,
	});
};

export const usePostChatMessage = () => {
	return useMutation<AIChatResponse, Error, AIChatRequest>({
		mutationFn: (payload: AIChatRequest) =>
			apiClient<AIChatResponse>("/ai/chat", {
				method: "POST",
				body: JSON.stringify(payload),
			}),
	});
};

export const useDeleteChatSession = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<void, Error, string>({
		mutationFn: (sessionId: string) =>
			apiClient(`/ai/chat/history/${sessionId}`, { method: "DELETE" }),
		onSuccess: (_, sessionId) => {
			queryClient.invalidateQueries({ queryKey: ["chatHistory", sessionId] });
			toast({
				title: "Chat Cleared",
				description: "The chat history has been successfully cleared.",
			});
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: "Error",
				description: `Failed to clear chat: ${error.message}`,
			});
		},
	});
};

export interface PaginatedTradesResponse {
	total: number;
	trades: BacktestTrade[];
}

export interface PaginatedLiveTradesResponse {
	total: number;
	trades: TradeData[];
}

// Type for the period to ensure strict typing
export type EquityPeriod = "1d" | "7d" | "mtd";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

// --- Function for loading Klines from our backend ---
const fetchBacktestKlines = (
	runId: string,
	interval: string,
	startTime?: number,
	endTime?: number,
): Promise<BinanceKline[]> => {
	const params = new URLSearchParams({ timeframe: interval });
	if (startTime) params.append("start_time", String(startTime));
	if (endTime) params.append("end_time", String(endTime));

	// The returned data type is slightly different (no string values), so a cast might be required
	// Binance API returns [ts, "open", "high", ...], while our backend will return [ts, open, high, ...]
	return apiClient<unknown[]>(
		`/backtests/${runId}/klines?${params.toString()}`,
	) as Promise<BinanceKline[]>;
};

let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

const subscribeTokenRefresh = (cb: (token: string) => void) => {
	refreshSubscribers.push(cb);
};

const onRefreshed = (token: string) => {
	refreshSubscribers.forEach((cb) => cb(token));
	refreshSubscribers = [];
};

export const apiClient = async <T>(
	endpoint: string,
	options: RequestInit = {},
): Promise<T> => {
	const fullUrl = `${API_BASE_URL}${endpoint}`;
	const token = localStorage.getItem("authToken");
	const headers = new Headers(options.headers);
	headers.set("Cache-Control", "no-cache");
	headers.set("Pragma", "no-cache");
	if (!options.body || !(options.body instanceof FormData)) {
		headers.set("Content-Type", "application/json");
	}
	if (token) {
		headers.set("Authorization", `Bearer ${token}`);
	}
	let response = await fetch(fullUrl, { ...options, headers });

	if (
		response.status === 401 &&
		!endpoint.includes("/token") &&
		!endpoint.includes("/refresh")
	) {
		const refreshToken = localStorage.getItem("refreshToken");
		if (refreshToken) {
			if (!isRefreshing) {
				isRefreshing = true;
				try {
					const refreshResponse = await fetch(`${API_BASE_URL}/refresh`, {
						method: "POST",
						headers: {
							"Content-Type": "application/json",
						},
						body: JSON.stringify({ refresh_token: refreshToken }),
					});

					if (refreshResponse.ok) {
						const tokenData = await refreshResponse.json();
						localStorage.setItem("authToken", tokenData.access_token);
						if (tokenData.refresh_token) {
							localStorage.setItem("refreshToken", tokenData.refresh_token);
						}
						onRefreshed(tokenData.access_token);
					} else {
						// Refresh failed
						localStorage.removeItem("authToken");
						localStorage.removeItem("refreshToken");
						localStorage.removeItem("originalAuthToken");
						localStorage.removeItem("originalRefreshToken");
						window.location.href = "/login";
					}
				} catch {
					localStorage.removeItem("authToken");
					localStorage.removeItem("refreshToken");
					window.location.href = "/login";
				} finally {
					isRefreshing = false;
				}
			}

			// Wait for the refresh to complete
			const newAccessToken = await new Promise<string>((resolve) => {
				subscribeTokenRefresh((token: string) => {
					resolve(token);
				});
			});

			// Retry original request with new token
			const retryHeaders = new Headers(options.headers);
			retryHeaders.set("Cache-Control", "no-cache");
			retryHeaders.set("Pragma", "no-cache");
			if (!options.body || !(options.body instanceof FormData)) {
				retryHeaders.set("Content-Type", "application/json");
			}
			retryHeaders.set("Authorization", `Bearer ${newAccessToken}`);
			response = await fetch(fullUrl, { ...options, headers: retryHeaders });
		}
	}

	if (!response.ok) {
		const errorBody = (await response.json().catch(() => ({}))) as Record<
			string,
			string | undefined
		>;
		let message =
			errorBody.detail ||
			errorBody.error ||
			`Request failed with status ${response.status}`;
		if (typeof message !== "string") {
			message = JSON.stringify(message);
		}
		throw new Error(message);
	}
	if (response.status === 204) {
		return undefined as T;
	}
	const parsedResponse = await response.json();
	return parsedResponse &&
		typeof parsedResponse === "object" &&
		"data" in parsedResponse
		? parsedResponse.data
		: parsedResponse;
};

// --- Symbol Selection Settings API ---
export const fetchSymbolSelectionSettings =
	async (): Promise<SymbolSelectionConfig> => {
		return apiClient<SymbolSelectionConfig>("/users/settings/symbol-selection");
	};

export const updateSymbolSelectionSettings = async (
	settings: SymbolSelectionConfig,
): Promise<SymbolSelectionConfig> => {
	return apiClient<SymbolSelectionConfig>("/users/settings/symbol-selection", {
		method: "PUT",
		body: JSON.stringify(settings),
	});
};

// --- NEW HOOK ---
export const useTradingViewWebhookInfo = (
	configId?: string | null,
	apiKeyId?: number | null,
) => {
	const searchParams = new URLSearchParams();
	if (configId) {
		searchParams.set("config_id", configId);
	}
	if (typeof apiKeyId === "number") {
		searchParams.set("api_key_id", String(apiKeyId));
	}
	const path = searchParams.toString()
		? `/webhooks/tv-info?${searchParams.toString()}`
		: "/webhooks/tv-info";

	return useQuery<TradingViewWebhookInfo, Error>({
		queryKey: ["tradingViewWebhookInfo", configId ?? null, apiKeyId ?? null],
		queryFn: () => apiClient<TradingViewWebhookInfo>(path),
	});
};

export const useTradingViewWebhookStatus = (configId?: string | null) => {
	return useQuery<TradingViewWebhookStatus, Error>({
		queryKey: ["tradingViewWebhookStatus", configId ?? null],
		queryFn: () =>
			apiClient<TradingViewWebhookStatus>(`/webhooks/tv-status/${configId}`),
		enabled: Boolean(configId),
		refetchInterval: 5000,
	});
};

export const useSendTradingViewTestSignal = () => {
	return useMutation<
		{ status: string; strategy_id: string; event_id?: string },
		Error,
		TradingViewTestSignalRequest
	>({
		mutationFn: (payload) =>
			apiClient<{ status: string; strategy_id: string; event_id?: string }>(
				"/webhooks/tv-test",
				{
					method: "POST",
					body: JSON.stringify(payload),
				},
			),
	});
};

export const useStopGeneticRun = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["research", "common"]);
	return useMutation<unknown, Error, string>({
		mutationFn: (runId: string) =>
			apiClient(`/discovery/runs/${runId}/stop`, { method: "POST" }),
		onSuccess: (_, runId) => {
			toast({
				title: t("research:geneticRunStopSuccessTitle"),
				description: t("research:geneticRunStopSuccessDescription"),
			});
			queryClient.invalidateQueries({ queryKey: ["geneticRuns"] });
			queryClient.invalidateQueries({ queryKey: ["geneticRunDetails", runId] });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("research:geneticRunStopFailedTitle"),
				description: error.message,
			});
		},
	});
};

// --- HOOK FOR GENERATING STRATEGY FROM TEXT ---
export const useGenerateStrategyFromText = () => {
	return useMutation<StrategyConfigData, Error, GenerateStrategyPayload>({
		mutationFn: (payload: GenerateStrategyPayload) =>
			apiClient<StrategyConfigData>("/strategies/generate-from-text", {
				method: "POST",
				body: JSON.stringify(payload),
			}),
	});
};

export const useBacktestRuns = () =>
	useQuery<BacktestRunListItemData[], Error>({
		queryKey: ["backtestRuns"],
		queryFn: () => apiClient<BacktestRunListItemData[]>("/backtests"),
		refetchInterval: (query) =>
			query.state.data?.some(
				(task) => task.status === "RUNNING" || task.status === "PENDING",
			)
				? 5000
				: false,
	});

// Hook for trades with pagination. It is the only one that should handle polling.
export const usePaginatedTrades = (
	runId: string,
	page: number,
	pageSize: number,
	status: string,
) => {
	return useQuery<PaginatedTradesResponse, Error>({
		queryKey: ["trades", runId, page, pageSize],
		queryFn: () => {
			const skip = (page - 1) * pageSize;
			return apiClient<PaginatedTradesResponse>(
				`/trades?run_id=${runId}&skip=${skip}&limit=${pageSize}`,
			);
		},
		enabled: !!runId,
		placeholderData: keepPreviousData,
		refetchInterval:
			// Update only if it's the first page AND the status is active
			page === 1 && (status === "RUNNING" || status === "PENDING")
				? 5000
				: false,
	});
};

// Hook for basic backtest information.
export const useBacktestRun = (runId: string | null) =>
	useQuery<BacktestRunDetailsData, Error>({
		queryKey: ["backtestRun", runId],
		queryFn: () => apiClient<BacktestRunDetailsData>(`/backtests/${runId}`),
		enabled: !!runId,
		refetchOnWindowFocus: false,
		refetchOnReconnect: false,
	});

export const useSystemStatus = () =>
	useQuery<SystemStatusData, Error>({
		queryKey: ["systemStatus"],
		queryFn: () => apiClient<SystemStatusData>("/status"),
		refetchInterval: 5000,
	});
export const usePortfolioStatus = (params?: {
	mode?: "live" | "paper";
	apiKeyId?: number | "all";
	marketType?: MarketScope;
}) =>
	useQuery<PortfolioData, Error>({
		queryKey: authScopedQueryKey(
			"portfolioStatus",
			params?.mode,
			params?.apiKeyId,
			params?.marketType,
		),
		queryFn: () => {
			const queryParams = new URLSearchParams();
			queryParams.append("mode", params?.mode || "paper");
			if (params?.apiKeyId !== undefined && params?.apiKeyId !== "all") {
				queryParams.append("api_key_id", String(params.apiKeyId));
			}
			if (params?.marketType) {
				queryParams.append("market_type", params.marketType);
			}
			return apiClient<PortfolioData>(`/portfolio?${queryParams.toString()}`);
		},
		staleTime: Infinity,
	});
export const usePositions = (options?: {
	refetchInterval?: number | false;
	mode?: "live" | "paper";
	apiKeyId?: number | "all";
	marketType?: MarketScope;
}) => {
	// Build query params
	const params = new URLSearchParams();
	params.append("mode", options?.mode || "paper");
	if (options?.apiKeyId !== undefined && options?.apiKeyId !== "all") {
		params.append("api_key_id", String(options.apiKeyId));
	}
	if (options?.marketType) {
		params.append("market_type", options.marketType);
	}

	return useQuery<PositionData[], Error>({
		queryKey: authScopedQueryKey(
			"positions",
			options?.mode,
			options?.apiKeyId,
			options?.marketType,
		),
		queryFn: () => apiClient<PositionData[]>(`/positions?${params.toString()}`),
		staleTime: 5000, // Consider data fresh for 5 seconds
		refetchInterval: options?.refetchInterval,
	});
};
export const useConfig = () =>
	useQuery<AppConfig, Error>({
		queryKey: authScopedQueryKey("config"),
		queryFn: () => apiClient<AppConfig>("/config"),
		staleTime: 15 * 60 * 1000,
		refetchOnWindowFocus: false,
	});

export const useAccountStatus = () => {
	return useQuery<AccountStatusData, Error>({
		queryKey: authScopedQueryKey("accountStatus"),
		queryFn: () => apiClient<AccountStatusData>("/account/status"),
		staleTime: 5 * 60 * 1000, // 5 minutes
	});
};

export const usePaperWallet = () => {
	// The hook now expects an array of PaperWalletData objects
	return useQuery<PaperWalletData[], Error>({
		queryKey: authScopedQueryKey("paperWallet"),
		queryFn: () => apiClient<PaperWalletData[]>("/account/paper"),
	});
};

export const useResetPaperAccount = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["account", "common"]);
	return useMutation<unknown, Error, void>({
		mutationFn: () => apiClient("/account/paper/reset", { method: "POST" }),
		onSuccess: () => {
			toast({
				title: t("account:paperAccountResetSuccessTitle"),
				description: t("account:paperAccountResetSuccessDescription"),
			});
			queryClient.invalidateQueries({ queryKey: ["paperWallet"] });
			queryClient.invalidateQueries({ queryKey: ["portfolioStatus"] });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("account:paperAccountResetFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useDeleteAccount = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["account", "common"]);

	return useMutation<void, Error, void>({
		mutationFn: () => apiClient("/users/me", { method: "DELETE" }),
		onSuccess: () => {
			toast({
				title: t("account:deleteAccountSuccessTitle"),
				description: t("account:deleteAccountSuccessDescription"),
			});
			queryClient.clear();
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("account:deleteAccountFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const usePlans = (options?: { refetchInterval?: number | false }) => {
	return useQuery<Plan[], Error>({
		queryKey: ["plans"],
		queryFn: () => apiClient<Plan[]>("/payments/plans"),
		staleTime: 60 * 60 * 1000, // 1 hour
		refetchInterval: options?.refetchInterval,
	});
};

export const useCreatePayment = () => {
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);
	return useMutation<
		CreatePaymentResponse,
		Error,
		{ plan_name: string; currency?: string }
	>({
		mutationFn: (payload) =>
			apiClient<CreatePaymentResponse>("/payments/create", {
				method: "POST",
				body: JSON.stringify(payload),
			}),
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("common:paymentCreationFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useTelegramBindUrl = () => {
	return useMutation<{ url: string }, Error, void>({
		mutationFn: () =>
			apiClient<{ url: string }>("/notifications/telegram/bind-url"),
	});
};

export const useUpdateConfig = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<AppConfig, Error, Partial<AppConfig>>({
		mutationFn: (updatedConfig) =>
			apiClient<AppConfig>("/config", {
				method: "PUT",
				body: JSON.stringify(updatedConfig),
			}),
		onSuccess: (data) => {
			queryClient.setQueryData(authScopedQueryKey("config"), data);
			toast({
				title: "Success",
				description: "Configuration updated successfully.",
			});
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: "Update Failed",
				description: error.message,
			}),
	});
};
export const useRunPortfolioBacktest = () => {
	const { toast } = useToast();
	const queryClient = useQueryClient();
	const { t } = useTranslation(["research", "common"]);
	return useMutation<unknown, Error, PortfolioBacktestRequest>({
		mutationFn: (data) =>
			apiClient<unknown>("/portfolio-backtests", {
				method: "POST",
				body: JSON.stringify(data),
			}),
		onSuccess: () => {
			toast({
				title: t("research:portfolioBacktestQueuedTitle"),
				description: t("research:portfolioBacktestQueuedDescription"),
			});
			queryClient.invalidateQueries({ queryKey: ["portfolioBacktestRuns"] });
			queryClient.invalidateQueries({ queryKey: ["researchTasks"] });
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: t("research:portfolioBacktestFailedTitle"),
				description: error.message,
			}),
	});
};
export const usePortfolioBacktestRuns = () =>
	useQuery<PortfolioBacktestRunListItemData[], Error>({
		queryKey: ["portfolioBacktestRuns"],
		queryFn: () =>
			apiClient<PortfolioBacktestRunListItemData[]>("/portfolio-backtests"),
		refetchInterval: (query) =>
			query.state.data?.some(
				(task) => task.status === "RUNNING" || task.status === "PENDING",
			)
				? 5000
				: false,
	});
export const usePortfolioBacktestRun = (runId: string | null) =>
	useQuery<PortfolioBacktestRunDetailsData, Error>({
		queryKey: ["portfolioBacktestRun", runId],
		queryFn: () =>
			apiClient<PortfolioBacktestRunDetailsData>(
				`/portfolio-backtests/${runId}`,
			),
		enabled: !!runId,
		refetchInterval: (query) =>
			query.state.data &&
			(query.state.data.status === "RUNNING" ||
				query.state.data.status === "PENDING")
				? 3000
				: false,
	});
export const useRunGeneticSearch = () => {
	const { toast } = useToast();
	const queryClient = useQueryClient();
	const { t } = useTranslation(["research", "common"]);
	return useMutation<
		GeneticSearchRunDetailsData,
		Error,
		GeneticSearchRunRequest
	>({
		mutationFn: (data: GeneticSearchRunRequest) =>
			apiClient<GeneticSearchRunDetailsData>("/discovery/runs", {
				method: "POST",
				body: JSON.stringify(data),
			}),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["geneticRuns"] });
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: t("research:geneticSearchFailedTitle"),
				description: error.message,
			}),
	});
};

// System Resources for Genetic Command Center
export interface SystemResourcesData {
	system: {
		cpu_count: number;
		cpu_percent: number;
		ram_total_gb: number;
		ram_used_gb: number;
		ram_available_gb: number;
		ram_percent: number;
	};
	queue: {
		running: number;
		pending: number;
		max_concurrent: number;
		cores_per_run: number;
		total_allocated_cores: number;
	};
	user_position: {
		has_pending: boolean;
		estimated_wait_minutes: number;
	};
}

export const useSystemResources = () =>
	useQuery<SystemResourcesData, Error>({
		queryKey: ["systemResources"],
		queryFn: () =>
			apiClient<SystemResourcesData>("/discovery/system-resources"),
		refetchInterval: 5000, // Refresh every 5 seconds
		staleTime: 2000,
	});

export const useStrategies = (params?: {
	mode?: "live" | "paper";
	apiKeyId?: number | "all";
}) => {
	const mode = params?.mode || "paper";
	// Build query params
	const queryParams = new URLSearchParams();
	queryParams.append("mode", mode);
	if (params?.apiKeyId !== undefined && params?.apiKeyId !== "all") {
		queryParams.append("api_key_id", String(params.apiKeyId));
	}

	return useQuery<StrategyData[], Error>({
		queryKey: authScopedQueryKey("strategies", mode, params?.apiKeyId),
		queryFn: () =>
			apiClient<StrategyData[]>(`/strategies?${queryParams.toString()}`),
		refetchInterval: 5000,
	});
};
// Retrieves a single strategy configuration. The returned data type has been updated.
export const useGetStrategy = (id: string | null) => {
	return useQuery<StrategyConfig, Error>({
		queryKey: authScopedQueryKey("strategyConfig", id),
		queryFn: () => apiClient<StrategyConfig>(`/strategies/config/${id}`),
		enabled: !!id,
		staleTime: Infinity,
	});
};
export const useStrategyConfigsList = () => {
	return useQuery<StrategyConfig[], Error>({
		queryKey: authScopedQueryKey("strategyConfigsList"),
		queryFn: () => apiClient<StrategyConfig[]>("/strategies/config"),
	});
};
export const useEventLog = () =>
	useQuery<LogEntry[], Error>({
		queryKey: authScopedQueryKey("eventLog"),
		queryFn: async (): Promise<LogEntry[]> => [],
		initialData: [],
		staleTime: Infinity,
	});

export const useLogHistory = () => {
	return useQuery<LogEntry[], Error>({
		queryKey: authScopedQueryKey("logHistory"),
		queryFn: () => apiClient<LogEntry[]>("/logs/history"),
		staleTime: Infinity,
		refetchOnWindowFocus: false,
	});
};

export const useAddSymbol = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<unknown, Error, string>({
		mutationFn: (symbol) =>
			apiClient<unknown>("/config/datasources/symbols", {
				method: "POST",
				body: JSON.stringify({ symbol }),
			}),
		onSuccess: (data) => {
			queryClient.setQueryData(authScopedQueryKey("config"), data);
			toast({ title: "Success", description: "Symbol added successfully." });
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: "Error adding symbol",
				description: error.message,
			}),
	});
};
export const useDeleteSymbol = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<unknown, Error, string>({
		mutationFn: (symbol) =>
			apiClient<unknown>(
				`/config/datasources/symbols/${encodeURIComponent(symbol)}`,
				{ method: "DELETE" },
			),
		onSuccess: (data) => {
			queryClient.setQueryData(authScopedQueryKey("config"), data);
			toast({ title: "Success", description: "Symbol removed successfully." });
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: "Error deleting symbol",
				description: error.message,
			}),
	});
};

// --- Blacklist Hooks ---
import type {
	AddToBlacklistPayload,
	AutoBlacklistRule,
	BlacklistSettings,
} from "@/types/api";

export const useBlacklist = () => {
	return useQuery<BlacklistSettings, Error>({
		queryKey: ["blacklist"],
		queryFn: () => apiClient<BlacklistSettings>("/config/blacklist"),
		staleTime: 30 * 1000, // 30 seconds
	});
};

export const useAddToBlacklist = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<BlacklistSettings, Error, AddToBlacklistPayload>({
		mutationFn: (payload) =>
			apiClient<BlacklistSettings>("/config/blacklist", {
				method: "POST",
				body: JSON.stringify(payload),
			}),
		onSuccess: (data) => {
			queryClient.setQueryData(["blacklist"], data);
			queryClient.invalidateQueries({ queryKey: ["config"] });
			toast({ title: "Success", description: "Coin added to blacklist." });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: "Error",
				description: error.message,
			});
		},
	});
};

export const useRemoveFromBlacklist = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<BlacklistSettings, Error, string>({
		mutationFn: (symbol) =>
			apiClient<BlacklistSettings>(
				`/config/blacklist/${encodeURIComponent(symbol)}`,
				{
					method: "DELETE",
				},
			),
		onSuccess: (data) => {
			queryClient.setQueryData(["blacklist"], data);
			queryClient.invalidateQueries({ queryKey: ["config"] });
			toast({ title: "Success", description: "Coin removed from blacklist." });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: "Error",
				description: error.message,
			});
		},
	});
};

export const useUpdateBlacklistRules = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<BlacklistSettings, Error, AutoBlacklistRule[]>({
		mutationFn: (rules) =>
			apiClient<BlacklistSettings>("/config/blacklist/rules", {
				method: "PUT",
				body: JSON.stringify({ autoRules: rules }),
			}),
		onSuccess: (data) => {
			queryClient.setQueryData(["blacklist"], data);
			queryClient.invalidateQueries({ queryKey: ["config"] });
			toast({ title: "Success", description: "Auto-blacklist rules updated." });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: "Error",
				description: error.message,
			});
		},
	});
};

export const useTestApiKey = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<ApiKey, Error, number>({
		mutationFn: (apiKeyId) =>
			apiClient<ApiKey>(`/config/api-keys/${apiKeyId}/test`, {
				method: "POST",
			}),
		onSuccess: (updatedApiKey, apiKeyId) => {
			queryClient.setQueryData<AppConfig>(["config"], (oldConfig) => {
				if (!oldConfig) return undefined;
				return {
					...oldConfig,
					apiKeys: oldConfig.apiKeys.map((key) =>
						key.id === apiKeyId
							? { ...key, status: updatedApiKey.status }
							: key,
					),
				};
			});
			toast({
				title: "API Key Test",
				description: `Test completed. Status: ${updatedApiKey.status}`,
			});
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: "Error testing API Key",
				description: error.message,
			});
			queryClient.invalidateQueries({ queryKey: ["config"] });
		},
	});
};
// useStrategyTemplates removed - template library is no longer used

// --- The useStartStrategy hook now accepts all necessary parameters for launching ---
export const useStartStrategy = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);
	// Adding symbol_selection_mode, symbols, params, and apiKeyId
	return useMutation<
		unknown,
		Error,
		{
			configId: string;
			mode: "live" | "paper";
			symbol_selection_mode?: "STATIC" | "DYNAMIC";
			symbols?: string[];
			params?: Record<string, unknown>;
			apiKeyId?: number; // ADDED FIELD for multi-accounts
		}
	>({
		mutationFn: ({
			configId,
			mode,
			symbol_selection_mode,
			symbols,
			params,
			apiKeyId,
		}) => {
			// Explicitly creating an object that matches the `StrategyStartRequest` schema on the backend.
			const requestBody: Record<string, unknown> = {
				config_id: configId,
				mode: mode,
				symbol_selection_mode: symbol_selection_mode,
				symbols: symbols,
				params: params,
			};

			// Adding api_key_id only if it is specified
			if (apiKeyId !== undefined) {
				requestBody.api_key_id = apiKeyId;
			}

			// Sending the object converted to a JSON string.
			return apiClient<unknown>("/strategies", {
				method: "POST",
				body: JSON.stringify(requestBody),
			});
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["strategies"] });
			queryClient.invalidateQueries({ queryKey: ["strategyConfigsList"] });
			toast({
				title: t("common:strategyStartSuccessTitle"),
				description: t("common:strategyStartSuccessDescription"),
			});
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: t("common:strategyStartFailedTitle"),
				description: error.message,
			}),
	});
};

// Saves a NEW configuration. Uses the new StrategyConfigCreatePayload type.
export const useSaveStrategyConfig = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);
	return useMutation<StrategyConfig, Error, StrategyConfigCreatePayload>({
		mutationFn: (newConfigData) => {
			console.log(
				"Saving strategy config:",
				JSON.stringify(newConfigData, null, 2),
			);
			return apiClient<StrategyConfig>("/strategies/config", {
				method: "POST",
				body: JSON.stringify(newConfigData),
			});
		},
		onSuccess: (data) => {
			queryClient.invalidateQueries({ queryKey: ["strategyConfigsList"] });
			queryClient.setQueryData(
				authScopedQueryKey("strategyConfig", data.id),
				data,
			);
			toast({ title: t("common:configurationSavedTitle") });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("common:configurationSaveFailedTitle"),
				description: error.message,
			});
		},
	});
};

// Updates the EXISTING configuration.
export const useUpdateStrategyConfig = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);
	return useMutation<
		StrategyConfig,
		Error,
		{ id: string; payload: StrategyConfigCreatePayload }
	>({
		mutationFn: ({ id, payload }) => {
			console.log(
				`Updating strategy config ${id}:`,
				JSON.stringify(payload, null, 2),
			);
			return apiClient<StrategyConfig>(`/strategies/config/${id}`, {
				method: "PUT",
				body: JSON.stringify(payload),
			});
		},
		onSuccess: (data) => {
			queryClient.invalidateQueries({ queryKey: ["strategyConfigsList"] });
			queryClient.setQueryData(
				authScopedQueryKey("strategyConfig", data.id),
				data,
			);
			toast({
				title: t("common:strategyUpdateSuccessTitle"),
				description: t("common:strategyUpdateSuccessDescription"),
			});
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("common:strategyUpdateFailedTitle"),
				description: error.message,
			});
		},
	});
};
export const useUpdateStrategy = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<StrategyState, Error, StrategyState>({
		mutationFn: (data) =>
			apiClient<StrategyState>(`/strategies/config/${data.id}`, {
				method: "PUT",
				body: JSON.stringify(data),
			}),
		onSuccess: (data) => {
			queryClient.invalidateQueries({ queryKey: ["strategies"] });
			queryClient.setQueryData(["strategy", data.id], data);
			toast({
				title: "Strategy Saved",
				description: "Your strategy configuration has been updated.",
			});
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: "Save Failed",
				description: error.message,
			}),
	});
};
export const useAddApiKey = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<ApiKey, Error, AddApiKeyPayload>({
		mutationFn: (payload) =>
			apiClient<ApiKey>("/config/api-keys", {
				method: "POST",
				body: JSON.stringify(payload),
			}),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["config"] });
			toast({ title: "Success", description: "API Key added successfully." });
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: "Error adding API Key",
				description: error.message,
			}),
	});
};
export const useDeleteApiKey = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<void, Error, number>({
		// Accepts key ID (number)
		mutationFn: (apiKeyId) =>
			apiClient(`/config/api-keys/${apiKeyId}`, { method: "DELETE" }),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["config"] });
			toast({ title: "Success", description: "API Key deleted successfully." });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: "Error deleting API Key",
				description: error.message,
			});
		},
	});
};

// --- Multi-Account API Hooks ---
import type { MultiAccountOverview } from "@/types/api";

export const useToggleApiKeyStatus = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<ApiKey, Error, { keyId: number; isActive: boolean }>({
		mutationFn: ({ keyId, isActive }) =>
			apiClient<ApiKey>(`/config/api-keys/${keyId}/status`, {
				method: "PATCH",
				body: JSON.stringify({ is_active: isActive }),
			}),
		onSuccess: (updatedKey, { isActive }) => {
			queryClient.setQueryData<AppConfig>(["config"], (oldConfig) => {
				if (!oldConfig) return undefined;
				return {
					...oldConfig,
					apiKeys: oldConfig.apiKeys.map((key) =>
						key.id === updatedKey.id
							? { ...key, isActive: updatedKey.isActive }
							: key,
					),
				};
			});
			queryClient.invalidateQueries({ queryKey: ["multiAccountBalances"] });
			toast({
				title: isActive ? "Account Activated" : "Account Deactivated",
				description: `${updatedKey.name} has been ${isActive ? "activated" : "deactivated"}.`,
			});
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: "Error updating API key status",
				description: error.message,
			});
		},
	});
};

export const useMultiAccountBalances = (marketType: MarketScope = "all") => {
	return useQuery<MultiAccountOverview, Error>({
		queryKey: ["multiAccountBalances", marketType],
		queryFn: () =>
			apiClient<MultiAccountOverview>(
				`/config/api-keys/balances?market_type=${marketType}`,
			),
		staleTime: 30 * 1000, // 30 seconds
		refetchInterval: 60 * 1000, // Refresh every minute
	});
};

export const useActiveApiKeys = () => {
	const { data: config } = useConfig();
	return config?.apiKeys?.filter((key) => key.isActive) ?? [];
};

export const useKlines = (
	params: {
		symbol: string;
		interval: string;
		startTime?: number;
		endTime?: number;
		limit?: number;
		runId?: string;
	},
	options?: { enabled?: boolean },
) => {
	const { symbol, interval, startTime, endTime, limit, runId } = params;

	// The hook is active only if there is a symbol and an interval (and optionally runId)
	const isHookEnabled = options?.enabled !== false && !!symbol && !!interval;

	const queryResult = useQuery<BinanceKline[], Error>({
		// Add runId to the request key so that the cache works correctly
		queryKey: [
			"klines",
			{ symbol, interval, startTime, endTime, limit, runId },
		],

		// --- Data source selection logic ---
		queryFn: () => {
			if (runId) {
				// If there is a runId, request data from our backend
				return fetchBacktestKlines(runId, interval, startTime, endTime);
			} else {
				// Otherwise, as before, go to the Binance API
				return fetchBinanceKlines(symbol, interval, startTime, endTime, limit);
			}
		},
		enabled: isHookEnabled,
		staleTime: 15 * 60 * 1000,
		refetchOnWindowFocus: false,
		retry: 1,
	});

	// Error handler remains unchanged
	useApiErrorHandler(
		queryResult.error,
		runId
			? `Backtest Klines (${runId})`
			: `Binance Klines (${symbol}/${interval})`,
	);

	return queryResult;
};
export const useStopStrategy = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);
	return useMutation<unknown, Error, string>({
		mutationFn: (configId: string) =>
			apiClient(`/strategies/${configId}`, { method: "DELETE" }),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["strategies"] });
			queryClient.invalidateQueries({ queryKey: ["strategyConfigsList"] });
			toast({
				title: t("common:strategyStopSuccessTitle"),
				description: t("common:strategyStopSuccessDescription"),
			});
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: t("common:strategyStopFailedTitle"),
				description: error.message,
			}),
	});
};
export const useDeleteStrategy = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);
	return useMutation<void, Error, string>({
		mutationFn: (strategyId: string) =>
			apiClient(`/strategies/${strategyId}`, { method: "DELETE" }),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["strategies"] });
			toast({
				title: t("common:strategyDeleteSuccessTitle"),
				description: t("common:strategyDeleteSuccessDescription"),
			});
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: t("common:strategyDeleteFailedTitle"),
				description: error.message,
			}),
	});
};
export const useUpdatePositionSlTp = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);
	return useMutation<
		PositionData,
		Error,
		{
			positionId: string;
			stop_loss?: number | null;
			take_profit?: number | null;
		}
	>({
		mutationFn: ({ positionId, stop_loss, take_profit }) =>
			apiClient<PositionData>(`/positions/${positionId}`, {
				method: "PATCH",
				body: JSON.stringify({ stop_loss, take_profit }),
			}),
		onSuccess: (updatedPosition) => {
			queryClient.setQueryData<PositionData[]>(
				["positions"],
				(oldPositions) =>
					oldPositions?.map((p) =>
						p.id === updatedPosition.id ? updatedPosition : p,
					) || [],
			);
			toast({
				title: t("common:slTpUpdateSuccessTitle"),
				description: t("common:slTpUpdateSuccessDescription"),
			});
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: t("common:slTpUpdateFailedTitle"),
				description: error.message,
			}),
	});
};
export const useTradeHistory = (
	params: TradeHistoryParams,
	options?: { enabled?: boolean },
) => {
	// Creating a copy of the parameters to avoid mutating the original object
	const queryKeyParams = { ...params };
	const queryResult = useQuery<PaginatedLiveTradesResponse, Error>({
		queryKey: authScopedQueryKey("tradeHistory", queryKeyParams),
		queryFn: async () => {
			const apiParams = new URLSearchParams();
			// Iterate through all parameters and add them to the URL only if they have a value
			// Iterate through all parameters and add them to the URL only if they have a value
			Object.entries(params).forEach(([key, value]) => {
				// Skip special handling keys
				if (key === "apiKeyId") return;

				// Adding the parameter only if it is not undefined, not null, and not an empty string
				if (value !== undefined && value !== null && value !== "") {
					// Manual mapping for date fields
					if (key === "startDate") {
						apiParams.append("date_from", String(value));
					} else if (key === "endDate") {
						apiParams.append("date_to", String(value));
					} else {
						// Default snake_case conversion
						const backendKey = key.replace(
							/[A-Z]/g,
							(letter) => `_${letter.toLowerCase()}`,
						);
						apiParams.append(backendKey, String(value));
					}
				}
			});
			// Add api_key_id parameter if present in queryKeyParams (passed implicitly via params object spread)
			if (params.apiKeyId !== undefined && params.apiKeyId !== "all") {
				apiParams.append("api_key_id", String(params.apiKeyId));
			}
			return apiClient<PaginatedLiveTradesResponse>(
				`/trades?${apiParams.toString()}`,
			);
		},
		enabled: options?.enabled ?? true,
		staleTime: 5 * 60 * 1000,
		refetchOnWindowFocus: false,
	});
	// useApiErrorHandler(queryResult.error, `Trade History`); // Can be uncommented for debugging
	return queryResult;
};
export const useRunBacktest = () => {
	const { toast } = useToast();
	const queryClient = useQueryClient();
	const { t } = useTranslation(["research", "common"]);
	return useMutation<{ task_id: string }, Error, BacktestRequest>({
		mutationFn: (data: BacktestRequest) =>
			apiClient<{ task_id: string }>("/backtests", {
				method: "POST",
				body: JSON.stringify(data),
			}),
		onSuccess: (data) => {
			toast({
				title: t("research:backtestQueuedTitle"),
				description: t("research:backtestQueuedDescription", {
					taskId: data.task_id,
				}),
			});
			queryClient.invalidateQueries({ queryKey: ["researchTasks"] });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("research:backtestFailedTitle"),
				description: error.message,
			});
		},
	});
};
export const useEmergencyStop = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);
	return useMutation<unknown, Error, void>({
		mutationFn: () => apiClient("/portfolio/positions", { method: "DELETE" }),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["portfolioStatus"] });
			queryClient.invalidateQueries({ queryKey: ["positions"] });
			queryClient.invalidateQueries({ queryKey: ["strategies"] });
			toast({
				title: t("common:emergencyStopSuccessTitle"),
				description: t("common:emergencyStopSuccessDescription"),
			});
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: t("common:emergencyStopFailedTitle"),
				description: error.message,
			}),
	});
};
export const useDeleteBacktestRun = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["research", "common"]);
	return useMutation<void, Error, string>({
		mutationFn: (runId) =>
			apiClient(`/backtests/${runId}`, { method: "DELETE" }),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["backtestRuns"] });
			queryClient.invalidateQueries({ queryKey: ["researchTasks"] });
			toast({
				title: t("research:backtestDeleteSuccessTitle"),
				description: t("research:backtestDeleteSuccessDescription"),
			});
		},
		onError: (error) =>
			toast({
				variant: "destructive",
				title: t("research:backtestDeleteFailedTitle"),
				description: error.message,
			}),
	});
};

// --- To get optimization details via the general task endpoint ---
export const useOptimizationRun = (taskId: string | null) => {
	const queryResult = useQuery<TaskData, Error>({
		queryKey: ["taskStatus", taskId, "optimization"], // More specific key
		queryFn: () => apiClient<TaskData>(`/tasks/${taskId}`),
		enabled: !!taskId,
		refetchInterval: (query) => {
			const data = query.state.data;
			return data &&
				(data.status.toUpperCase() === "RUNNING" ||
					data.status.toUpperCase() === "PENDING")
				? 4000
				: false;
		},
	});
	useApiErrorHandler(queryResult.error, `Optimization Run Task ${taskId}`);
	return queryResult;
};

// --- The useRunOptimization hook now uses /optimizations, but still invalidates the general list ---
export const useRunOptimization = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["research", "common"]);
	return useMutation<
		{ task_id: string; status: string },
		Error,
		OptimizationRequest
	>({
		mutationFn: (data: OptimizationRequest) =>
			apiClient<{ task_id: string; status: string }>("/optimizations", {
				method: "POST",
				body: JSON.stringify(data),
			}),
		onSuccess: (data) => {
			toast({
				title: t("research:optimizationQueuedTitle"),
				description: t("research:optimizationQueuedDescription", {
					taskId: data.task_id,
				}),
			});
			// Optimizations are now shown in the general task list
			queryClient.invalidateQueries({ queryKey: ["researchTasks"] });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("research:optimizationFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useGeneticRuns = () => {
	const queryResult = useQuery<GeneticSearchRunListItemData[], Error>({
		queryKey: ["geneticRuns"],
		queryFn: () => apiClient<GeneticSearchRunListItemData[]>("/discovery/runs"),
		refetchInterval: (query) => {
			const hasActiveTasks = query.state.data?.some(
				(run) => run.status === "RUNNING" || run.status === "PENDING",
			);
			return hasActiveTasks ? 7000 : false;
		},
	});
	useApiErrorHandler(queryResult.error, "Genetic Search Runs");
	return queryResult;
};

export const useGeneticRunDetails = (runId: string | null) => {
	const queryResult = useQuery<GeneticSearchRunDetailsData, Error>({
		queryKey: ["geneticRunDetails", runId],
		queryFn: () =>
			apiClient<GeneticSearchRunDetailsData>(`/discovery/runs/${runId}`),
		enabled: !!runId,
		refetchInterval: (query) => {
			const data = query.state.data;
			return data &&
				(data.status === "RUNNING" ||
					data.status === "PENDING" ||
					data.status === "EVALUATING_HOF")
				? 5000
				: false;
		},
	});
	useApiErrorHandler(queryResult.error, `Genetic Search Run ${runId}`);
	return queryResult;
};

export const useFoundStrategies = (
	runId: string | null,
	options?: { enabled?: boolean; refetchInterval?: number | false },
) => {
	const queryResult = useQuery<FoundStrategyData[], Error>({
		queryKey: ["foundStrategies", runId],
		queryFn: () =>
			apiClient<FoundStrategyData[]>(`/discovery/runs/${runId}/results`),
		enabled: !!runId && options?.enabled !== false,
		refetchInterval: options?.refetchInterval ?? false,
	});
	useApiErrorHandler(queryResult.error, `Found Strategies for Run ${runId}`);
	return queryResult;
};

export interface PaginatedTasksResponse {
	total: number;
	tasks: TaskData[];
}

export const useResearchTasks = (page: number, pageSize: number) => {
	const queryResult = useQuery<PaginatedTasksResponse, Error>({
		queryKey: ["researchTasks", page, pageSize],
		queryFn: () => {
			const params = new URLSearchParams({
				page: String(page),
				page_size: String(pageSize),
			});
			return apiClient<PaginatedTasksResponse>(
				`/tasks/all?${params.toString()}`,
			);
		},
		placeholderData: keepPreviousData,
		refetchInterval: (query) => {
			// Poll if there is any active task
			return query.state.data?.tasks.some(
				(task) =>
					task.status.toUpperCase() === "RUNNING" ||
					task.status.toUpperCase() === "PENDING",
			)
				? 5000
				: false;
		},
	});
	useApiErrorHandler(queryResult.error, "Research Tasks");
	return queryResult;
};

export const useTaskStatus = (taskId: string) => {
	const queryResult = useQuery<TaskData, Error>({
		queryKey: ["taskStatus", taskId],
		queryFn: () => apiClient<TaskData>(`/tasks/${taskId}`),
		enabled: !!taskId,
		refetchInterval: 2000,
	});
	useApiErrorHandler(queryResult.error, `Task Status ${taskId}`);
	return queryResult;
};

// --- Model Lab: Datasets ---
export const useCreateDatasetTask = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["modelLab", "common"]);
	return useMutation<DatasetRunResponse, Error, DatasetRunCreate>({
		mutationFn: (data) =>
			apiClient<DatasetRunResponse>("/model-lab/datasets", {
				method: "POST",
				body: JSON.stringify(data),
			}),
		onSuccess: (data) => {
			toast({
				title: t("modelLab:datasetGenerationStartedTitle"),
				description: t("modelLab:datasetGenerationStartedDescription", {
					name: data.name,
				}),
			});
			queryClient.invalidateQueries({ queryKey: ["datasetRuns"] });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("modelLab:datasetTaskFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useListDatasetRuns = () => {
	return useQuery<DatasetRunResponse[], Error>({
		queryKey: ["datasetRuns"],
		queryFn: () => apiClient<DatasetRunResponse[]>("/model-lab/datasets"),
		refetchInterval: (query) =>
			query.state.data?.some(
				(task) => task.status === "RUNNING" || task.status === "PENDING",
			)
				? 10000
				: false,
	});
};

export const useGetDatasetRunDetails = (runId: string | null) => {
	return useQuery<DatasetRunResponse, Error>({
		queryKey: ["datasetRunDetails", runId],
		queryFn: () =>
			apiClient<DatasetRunResponse>(`/model-lab/datasets/${runId}`),
		enabled: !!runId,
		refetchInterval: (query) =>
			query.state.data &&
			(query.state.data.status === "RUNNING" ||
				query.state.data.status === "PENDING")
				? 5000
				: false,
	});
};

// --- Model Lab: Training ---
export const useCreateModelTrainingTask = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["modelLab", "common"]);
	return useMutation<TrainingRunResponse, Error, TrainingRunCreate>({
		mutationFn: (data) =>
			apiClient<TrainingRunResponse>("/model-lab/train", {
				method: "POST",
				body: JSON.stringify(data),
			}),
		onSuccess: (data) => {
			toast({
				title: t("modelLab:modelTrainingStartedTitle"),
				description: t("modelLab:modelTrainingStartedDescription", {
					model_type: data.model_type,
				}),
			});
			queryClient.invalidateQueries({ queryKey: ["modelLabTasks"] });
			queryClient.invalidateQueries({ queryKey: ["trainingRuns"] });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("modelLab:modelTrainingFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useGetTrainingRunDetails = (runId: string | null) => {
	return useQuery<TrainingRunResponse, Error>({
		queryKey: ["trainingRunDetails", runId],
		queryFn: () => apiClient<TrainingRunResponse>(`/model-lab/train/${runId}`),
		enabled: !!runId,
		refetchInterval: (query) => {
			const data = query.state.data;
			return data && (data.status === "RUNNING" || data.status === "PENDING")
				? 5000
				: false;
		},
	});
};

export const useDeleteTrainingRun = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["modelLab", "common"]);
	return useMutation<void, Error, string>({
		mutationFn: (runId) =>
			apiClient(`/model-lab/train/${runId}`, { method: "DELETE" }),
		onSuccess: () => {
			toast({
				title: t("modelLab:trainingDeleteSuccessTitle"),
				description: t("modelLab:trainingDeleteSuccessDescription"),
			});
			queryClient.invalidateQueries({ queryKey: ["trainingRuns"] });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("modelLab:trainingDeleteFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useGetTrainingRunReport = (
	runId: string | null,
	isCompleted: boolean,
) => {
	return useQuery<ModelTrainingReport, Error>({
		queryKey: ["trainingRunReport", runId],
		queryFn: () =>
			apiClient<ModelTrainingReport>(`/model-lab/train/${runId}/report`),
		enabled: !!runId && isCompleted,
	});
};

// --- Model Lab: Combined Task List ---
export const useModelLabTasks = () => {
	const listDatasetsQuery = useListDatasetRuns();
	// Assuming a similar hook for training runs
	// For now, let's just return datasets for simplicity of the first step
	return {
		data: listDatasetsQuery.data, // TODO: Combine with training runs later
		isLoading: listDatasetsQuery.isLoading,
		isError: listDatasetsQuery.isError,
		error: listDatasetsQuery.error,
	};
};

// --- Model Lab: Datasets ---
export const useDeleteDatasetRun = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["modelLab", "common"]);
	return useMutation<void, Error, string>({
		mutationFn: (runId) =>
			apiClient(`/model-lab/datasets/${runId}`, { method: "DELETE" }),
		onSuccess: () => {
			toast({
				title: t("modelLab:datasetDeleteSuccessTitle"),
				description: t("modelLab:datasetDeleteSuccessDescription"),
			});
			queryClient.invalidateQueries({ queryKey: ["datasetRuns"] });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("modelLab:datasetDeleteFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useListTrainingRuns = () => {
	return useQuery<TrainingRunResponse[], Error>({
		queryKey: ["trainingRuns"],
		queryFn: () => apiClient<TrainingRunResponse[]>("/model-lab/train"),
		refetchInterval: (query) =>
			query.state.data?.some(
				(task) => task.status === "RUNNING" || task.status === "PENDING",
			)
				? 10000
				: false,
	});
};

// Placeholder for future implementation
export const useDeployModel = () => {
	const { toast } = useToast();
	const { t } = useTranslation(["modelLab", "common"]);
	return useMutation<{ success: boolean; message: string }, Error, string>({
		mutationFn: async (modelId: string) => {
			// This would call a backend endpoint like POST /api/v1/models/{model_id}/deploy
			console.log(`Deploying model ${modelId}...`);
			await new Promise((res) => setTimeout(res, 1000)); // Simulate API call
			return { success: true, message: `Model ${modelId} deployed.` };
		},
		onSuccess: (data) => {
			toast({
				title: t("modelLab:deploymentSuccessTitle"),
				description: t("modelLab:deploymentSuccessDescription", {
					modelId: data.message.split(" ")[1],
				}),
			});
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("modelLab:deploymentFailedTitle"),
				description: error.message,
			});
		},
	});
};

// --- HOOK FOR STARTING ML STRATEGY IN LIVE ---
export const useStartMlStrategy = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["modelLab", "common"]);
	// We reuse the same endpoint and request type as for regular strategies
	return useMutation<unknown, Error, StrategyRunRequest>({
		mutationFn: (data) =>
			apiClient<unknown>("/strategies", {
				method: "POST",
				body: JSON.stringify(data),
			}),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["strategies"] });
			toast({
				title: t("modelLab:mlStrategyStartSuccessTitle"),
				description: t("modelLab:mlStrategyStartSuccessDescription"),
			});
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("modelLab:mlStrategyStartFailedTitle"),
				description: error.message,
			});
		},
	});
};

// --- For DELETING configuration ---
export const useDeleteStrategyConfig = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);
	return useMutation<void, Error, string>({
		mutationFn: (configId: string) =>
			apiClient(`/strategies/config/${configId}`, { method: "DELETE" }),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["strategyConfigsList"] });
			queryClient.invalidateQueries({ queryKey: ["strategies"] });
			toast({
				title: t("common:strategyConfigDeleteSuccessTitle"),
				description: t("common:strategyConfigDeleteSuccessDescription"),
			});
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("common:strategyConfigDeleteFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useClosePosition = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);
	return useMutation<unknown, Error, string>({
		// Mutation function sends a DELETE request to the /positions/<symbol> endpoint
		mutationFn: (symbol: string) =>
			apiClient(`/positions/${symbol}`, { method: "DELETE" }),
		onSuccess: (_, symbol) => {
			toast({
				title: t("common:closePositionSuccessTitle"),
				description: t("common:closePositionSuccessDescription", { symbol }),
			});
			// Force update the position list after sending the command
			// Give a small delay so the backend has time to process the command
			setTimeout(() => {
				queryClient.invalidateQueries({ queryKey: ["positions"] });
			}, 1500);
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("common:closePositionFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useShareBacktest = () => {
	return useMutation<ShareBacktestResponse, Error, ShareBacktestPayload>({
		mutationFn: ({ runId, ...payload }) =>
			apiClient<ShareBacktestResponse>(`/backtests/${runId}/share`, {
				method: "POST",
				body: JSON.stringify(payload),
			}),
	});
};

export const useSharedBacktestData = (publicSlug: string | null) => {
	return useQuery<SharedBacktestData, Error>({
		queryKey: ["sharedBacktest", publicSlug],
		queryFn: () => apiClient<SharedBacktestData>(`/shared/${publicSlug}`),
		enabled: !!publicSlug,
		staleTime: 5 * 60 * 1000, // Cache for 5 minutes
	});
};

// --- Admin Panel API Hooks ---

export const useAdminGetUsers = (
	page: number,
	pageSize: number,
	search?: string,
	plan?: string,
) => {
	return useQuery<{ users: AdminUser[]; total: number }, Error>({
		queryKey: ["adminUsers", page, pageSize, search, plan],
		queryFn: () => {
			const params = new URLSearchParams({
				skip: String((page - 1) * pageSize),
				limit: String(pageSize),
			});
			if (search) params.append("search", search);
			if (plan) params.append("plan", plan);
			return apiClient(`/admin/users?${params.toString()}`);
		},
		placeholderData: keepPreviousData,
	});
};

export const useAdminDashboardStats = () => {
	return useQuery<DashboardStats, Error>({
		queryKey: ["adminDashboardStats"],
		queryFn: () => apiClient<DashboardStats>("/admin/dashboard/stats"),
		staleTime: 60000, // Cache for 1 minute
	});
};

export const useAdminErrorLogs = (
	limit: number = 100,
	level: "ERROR" | "WARNING" = "ERROR",
) => {
	return useQuery<LogEntry[], Error>({
		queryKey: ["adminErrorLogs", limit, level],
		queryFn: () =>
			apiClient<LogEntry[]>(`/admin/logs/errors?limit=${limit}&level=${level}`),
		staleTime: 30000, // Cache for 30 seconds
	});
};

export const useAdminUserDetails = (userId: number) => {
	return useQuery<AdminUserExtendedDetails, Error>({
		queryKey: ["adminUserDetails", userId],
		queryFn: () =>
			apiClient<AdminUserExtendedDetails>(`/admin/users/${userId}/details`),
		enabled: !!userId,
	});
};

export const useAdminUpdateUser = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["admin", "common"]);
	return useMutation<
		AdminUser,
		Error,
		{ userId: number; payload: AdminUserUpdatePayload }
	>({
		mutationFn: ({ userId, payload }) =>
			apiClient(`/admin/users/${userId}`, {
				method: "PUT",
				body: JSON.stringify(payload),
			}),
		onSuccess: () => {
			toast({
				title: t("admin:userUpdateSuccessTitle"),
				description: t("admin:userUpdateSuccessDescription"),
			});
			queryClient.invalidateQueries({ queryKey: ["adminUsers"] });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("admin:userUpdateFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useAdminIssueBonus = () => {
	const { toast } = useToast();
	const { t } = useTranslation(["admin", "common"]);
	// Specify that `data` will be an object with a `message` field
	return useMutation<
		{ message: string },
		Error,
		{ userId: number; payload: AdminBonusPayload }
	>({
		mutationFn: ({ userId, payload }) =>
			// apiClient will return { message: string }
			apiClient<{ message: string }>(`/admin/users/${userId}/bonuses`, {
				method: "POST",
				body: JSON.stringify(payload),
			}),
		onSuccess: (data) => {
			toast({
				title: t("admin:bonusIssueSuccessTitle"),
				description: data.message,
			});
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("admin:bonusIssueFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useImpersonateUser = () => {
	const { toast } = useToast();
	const { t } = useTranslation(["admin", "common"]);
	return useMutation<ImpersonateToken, Error, number>({
		mutationFn: (userId: number) =>
			apiClient(`/admin/users/${userId}/impersonate`, { method: "POST" }),
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("admin:impersonationFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useAvailableBonuses = () => {
	return useQuery<AvailableBonus[], Error>({
		queryKey: ["availableBonuses"],
		queryFn: () => apiClient<AvailableBonus[]>("/admin/bonuses/available"),
		staleTime: Infinity, // The list of bonuses changes rarely, cache forever
	});
};

export const useAdminFoundationStats = (
	sourceType: "backtest" | "live" | "paper",
) => {
	return useQuery<FoundationStat[], Error>({
		queryKey: ["adminFoundationStats", sourceType],
		queryFn: () =>
			apiClient<FoundationStat[]>(
				`/admin/analytics/foundations?source_type=${sourceType}`,
			),
	});
};

export const useAdminMarketSentiment = (
	sourceType: "backtest" | "live" | "paper",
) => {
	return useQuery<MarketSentimentStat[], Error>({
		queryKey: ["adminMarketSentiment", sourceType],
		queryFn: () =>
			apiClient<MarketSentimentStat[]>(
				`/admin/analytics/market-sentiment?source_type=${sourceType}`,
			),
	});
};

export const useAdminSystemMetrics = () => {
	return useQuery<SystemMetrics, Error>({
		queryKey: ["adminSystemMetrics"],
		queryFn: () => apiClient<SystemMetrics>("/admin/health/metrics"),
		staleTime: 30000, // Cache for 30 seconds
	});
};

// --- Support Management (Admin) ---

export const useAdminTickets = (status?: string, category?: string) => {
	return useQuery<AdminSupportTicket[], Error>({
		queryKey: ["admin", "support", "tickets", status, category],
		queryFn: () => {
			const params = new URLSearchParams();
			if (status) params.append("status", status);
			if (category) params.append("category", category);
			return apiClient<AdminSupportTicket[]>(
				`/admin/support/tickets?${params.toString()}`,
			);
		},
	});
};

export const useAdminUpdateTicket = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	return useMutation<
		SupportTicket,
		Error,
		{ ticketId: string; payload: SupportTicketUpdate }
	>({
		mutationFn: ({ ticketId, payload }) =>
			apiClient<SupportTicket>(`/admin/support/tickets/${ticketId}`, {
				method: "PATCH",
				body: JSON.stringify(payload),
			}),
		onSuccess: () => {
			toast({ title: "Ticket Updated" });
			queryClient.invalidateQueries({
				queryKey: ["admin", "support", "tickets"],
			});
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: "Update Failed",
				description: error.message,
			});
		},
	});
};

// --- Affiliate Management (Admin) ---

export const useAdminAffiliates = (page: number, pageSize: number) => {
	return useQuery<PaginatedAdminUsers>({
		queryKey: ["admin", "affiliates", "list", page, pageSize],
		queryFn: () => {
			const skip = (page - 1) * pageSize;
			return apiClient<PaginatedAdminUsers>(
				`/admin/affiliates?skip=${skip}&limit=${pageSize}`,
			);
		},
		placeholderData: keepPreviousData,
	});
};

export const useAdminAffiliateCommissions = (
	userId: number,
	page: number,
	pageSize: number,
) => {
	return useQuery<PaginatedAdminAffiliateCommissions>({
		queryKey: ["admin", "affiliates", "commissions", userId, page, pageSize],
		queryFn: () =>
			apiClient<PaginatedAdminAffiliateCommissions>(
				`/admin/affiliates/${userId}/commissions?page=${page}&page_size=${pageSize}`,
			),
		placeholderData: keepPreviousData,
		enabled: !!userId,
	});
};

export const useAdminAffiliateReferrals = (
	userId: number,
	page: number,
	pageSize: number,
) => {
	return useQuery<PaginatedAdminAffiliateReferrals>({
		queryKey: ["admin", "affiliates", "referrals", userId, page, pageSize],
		queryFn: () =>
			apiClient<PaginatedAdminAffiliateReferrals>(
				`/admin/affiliates/${userId}/referrals?page=${page}&page_size=${pageSize}`,
			),
		placeholderData: keepPreviousData,
		enabled: !!userId,
	});
};

// --- Affiliate Dashboard (Affiliate View) ---

export const useAffiliateDashboardStats = () => {
	return useQuery<AffiliateDashboardStats>({
		queryKey: ["affiliate", "dashboard", "stats"],
		queryFn: () => apiClient<AffiliateDashboardStats>("/affiliate/dashboard"),
	});
};

export const useAffiliateCommissions = (page: number, pageSize: number) => {
	return useQuery<PaginatedAffiliateCommissions>({
		queryKey: ["affiliate", "commissions", page, pageSize],
		queryFn: () =>
			apiClient<PaginatedAffiliateCommissions>(
				`/affiliate/commissions?page=${page}&page_size=${pageSize}`,
			),
		placeholderData: keepPreviousData,
	});
};

export const useAffiliateReferrals = (page: number, pageSize: number) => {
	return useQuery<PaginatedAffiliateReferrals>({
		queryKey: ["affiliate", "referrals", page, pageSize],
		queryFn: () =>
			apiClient<PaginatedAffiliateReferrals>(
				`/affiliate/referrals?page=${page}&page_size=${pageSize}`,
			),
		placeholderData: keepPreviousData,
	});
};

export const useAffiliatePayouts = (page: number, pageSize: number) => {
	return useQuery<PaginatedAffiliatePayouts>({
		queryKey: ["affiliate", "payouts", page, pageSize],
		queryFn: () =>
			apiClient<PaginatedAffiliatePayouts>(
				`/affiliate/payouts?page=${page}&page_size=${pageSize}`,
			),
		placeholderData: keepPreviousData,
	});
};

export const useUpdatePayoutDetails = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["affiliate", "common"]);
	return useMutation<unknown, Error, PayoutDetailsPayload>({
		mutationFn: (payload) =>
			apiClient("/affiliate/payout-details", {
				method: "POST",
				body: JSON.stringify(payload),
			}),
		onSuccess: () => {
			toast({
				title: t("affiliate:payoutDetailsUpdateSuccessTitle"),
				description: t("affiliate:payoutDetailsUpdateSuccessDescription"),
			});
			queryClient.invalidateQueries({
				queryKey: ["affiliate", "dashboard", "stats"],
			}); // Or a more specific query
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("affiliate:payoutDetailsUpdateFailedTitle"),
				description: error.message,
			});
		},
	});
};

export const useRequestPayout = () => {
	const queryClient = useQueryClient();
	const { toast } = useToast();
	const { t } = useTranslation(["affiliate", "common"]);
	return useMutation<unknown, Error, void>({
		mutationFn: () =>
			apiClient("/affiliate/request-payout", { method: "POST" }),
		onSuccess: () => {
			toast({
				title: t("affiliate:payoutRequestSuccessTitle"),
				description: t("affiliate:payoutRequestSuccessDescription"),
			});
			queryClient.invalidateQueries({
				queryKey: ["affiliate", "dashboard", "stats"],
			});
			queryClient.invalidateQueries({ queryKey: ["affiliate", "payouts"] });
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: t("affiliate:payoutRequestFailedTitle"),
				description: error.message,
			});
		},
	});
};

// --- HOOK FOR EQUITY CHART ---
export const usePortfolioEquity = (
	period: EquityPeriod,
	mode: "live" | "paper",
) => {
	return useQuery<[number, number][], Error>({
		queryKey: ["portfolioEquity", period, mode],
		queryFn: () =>
			apiClient<[number, number][]>(
				`/portfolio/equity?period=${period}&mode=${mode}`,
			),
		staleTime: 5 * 60 * 1000,
		refetchOnWindowFocus: false,
		// The hook will be active only if 'mode' is passed
		enabled: !!mode,
	});
};

export const useAchievements = () => {
	return useQuery<Achievement[], Error>({
		queryKey: ["achievements"],
		queryFn: () => apiClient<Achievement[]>("/achievements"),
	});
};

export const useUserAchievements = (userId: number | undefined) => {
	return useQuery<UserAchievement[], Error>({
		queryKey: ["userAchievements", userId],
		queryFn: () =>
			apiClient<UserAchievement[]>(`/users/${userId}/achievements`),
		enabled: !!userId,
	});
};

// === Genome Project API ===

export const useMyGenes = (limit: number = 100, offset: number = 0) => {
	return useQuery<UserGenesResponse, Error>({
		queryKey: ["genes", "my", limit, offset],
		queryFn: () =>
			apiClient<UserGenesResponse>(`/genes/my?limit=${limit}&offset=${offset}`),
	});
};

export const useGeneStats = () => {
	return useQuery<GeneStatsResponse, Error>({
		queryKey: ["genes", "stats"],
		queryFn: () => apiClient<GeneStatsResponse>("/genes/stats"),
	});
};

// === Evolution Tree API ===

export interface RootStrategy {
	id: string;
	name: string;
	generation: number;
	created_at: string;
	descendants_count?: number;
}

export interface StrategyNode {
	id: string;
	name: string;
	generation: number;
	source_mutation?: string;
	created_at?: string;
	is_current: boolean;
}

export interface StrategyEdge {
	from: string;
	to: string;
}

export interface StrategyLineageResponse {
	nodes: StrategyNode[];
	edges: StrategyEdge[];
	root_id: string;
}

export const useStrategyLineages = () => {
	return useQuery<RootStrategy[], Error>({
		queryKey: authScopedQueryKey("strategies", "lineages"),
		queryFn: () => apiClient<RootStrategy[]>("/strategies/lineages"),
	});
};

export const useStrategyLineage = (strategyId: string | null) => {
	return useQuery<StrategyLineageResponse, Error>({
		queryKey: authScopedQueryKey("strategies", "lineage", strategyId),
		queryFn: () =>
			apiClient<StrategyLineageResponse>(`/strategies/lineage/${strategyId}`),
		enabled: !!strategyId,
	});
};

// --- HOOK FOR RETRIEVING THE LIST OF AVAILABLE SYMBOLS ---
export const useGetAvailableSymbols = (
	query: string,
	options?: { enabled?: boolean },
) => {
	return useQuery<string[], Error>({
		queryKey: ["availableSymbols", query],
		queryFn: () => {
			// If there is a search query, add it
			const endpoint = query
				? `/diagnostics/available-symbols?q=${query}`
				: "/diagnostics/available-symbols";
			return apiClient<string[]>(endpoint);
		},
		// The hook will be active if `options.enabled` is explicitly true,
		// or if the user has started entering text.
		enabled: (options?.enabled ?? false) || query.length > 0,
		staleTime: 5 * 60 * 1000,
	});
};

export const useTestTelegramNotification = () => {
	const { toast } = useToast();
	// const { t } = useTranslation(['settings', 'common']); // Translation hook usage inside a custom hook might be tricky if context isn't available, but usually works.
	// To avoid potential issues if this file is just a library, I'll use hardcoded strings or assume t is available if I import it.
	// Ideally, messages should be passed or handled in component.
	// For now, simple toast messages.
	return useMutation<unknown, Error, string>({
		mutationFn: (chatId) =>
			apiClient("/notifications/test", {
				method: "POST",
				body: JSON.stringify({ chat_id: chatId }),
			}),
		onSuccess: () => {
			toast({
				title: "Test Notification Sent",
				description: "Please check your Telegram app.",
			});
		},
		onError: (error) => {
			toast({
				variant: "destructive",
				title: "Test Failed",
				description: error.message,
			});
		},
	});
};

// --- Phantom Trade Analysis Hooks ---

export const usePhantomStats = (params: { days?: number }) => {
	return useQuery<BEAnalysisStats, Error>({
		queryKey: ["phantomStats", params],
		queryFn: () => {
			const queryParams = new URLSearchParams();
			if (params.days) queryParams.append("days", String(params.days));
			return apiClient<BEAnalysisStats>(
				`/analytics/phantom/stats?${queryParams.toString()}`,
			);
		},
		staleTime: 5 * 60 * 1000,
	});
};

export const usePhantomTrades = (params: {
	limit?: number;
	skip?: number;
	symbol?: string;
	strategy?: string;
	status?: string;
}) => {
	return useQuery<PaginatedPhantomTradesResponse, Error>({
		queryKey: ["phantomTrades", params],
		queryFn: () => {
			const queryParams = new URLSearchParams();
			Object.entries(params).forEach(([key, value]) => {
				if (value !== undefined && value !== null && value !== "") {
					queryParams.append(key, String(value));
				}
			});
			return apiClient<PaginatedPhantomTradesResponse>(
				`/analytics/phantom/trades?${queryParams.toString()}`,
			);
		},
		staleTime: 1 * 60 * 1000,
	});
};

export const usePhantomScatterData = (params: { days?: number }) => {
	return useQuery<BEScatterDataResponse, Error>({
		queryKey: ["phantomScatterData", params],
		queryFn: () => {
			const queryParams = new URLSearchParams();
			if (params.days) queryParams.append("days", String(params.days));
			return apiClient<BEScatterDataResponse>(
				`/analytics/phantom/scatter-data?${queryParams.toString()}`,
			);
		},
		staleTime: 5 * 60 * 1000,
	});
};

export const useBlockRestrictions = () =>
	useQuery<BlockRestrictionsConfig, Error>({
		queryKey: ["blockRestrictions"],
		queryFn: async () => {
			try {
				const rawRestrictions = await apiClient<unknown>(
					"/config/block-restrictions",
				);
				return normalizeBlockRestrictions(rawRestrictions);
			} catch (error) {
				console.warn(
					"Failed to load block restrictions, using frontend fallback.",
					error,
				);
				return DEFAULT_BLOCK_RESTRICTIONS;
			}
		},
		placeholderData: DEFAULT_BLOCK_RESTRICTIONS,
		staleTime: 0,
		refetchOnWindowFocus: false,
	});

export const useUserTickets = () => {
	return useQuery<SupportTicket[], Error>({
		queryKey: ["userTickets"],
		queryFn: () => apiClient<SupportTicket[]>("/support/tickets"),
	});
};

export const useCreateSupportTicket = () => {
	const queryClient = useQueryClient();
	return useMutation<SupportTicket, Error, SupportTicketCreate>({
		mutationFn: (payload) =>
			apiClient<SupportTicket>("/support/ticket", {
				method: "POST",
				body: JSON.stringify(payload),
			}),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["userTickets"] });
		},
	});
};

export const useTicketMessages = (ticketId: string) => {
	return useQuery<SupportTicketMessage[], Error>({
		queryKey: ["ticketMessages", ticketId],
		queryFn: () =>
			apiClient<SupportTicketMessage[]>(
				`/support/tickets/${ticketId}/messages`,
			),
		enabled: !!ticketId,
		refetchInterval: 5000, // Poll every 5s for new messages
	});
};

export const useSendTicketMessage = () => {
	const queryClient = useQueryClient();
	return useMutation<
		SupportTicketMessage,
		Error,
		{ ticketId: string; payload: SupportTicketMessageCreate }
	>({
		mutationFn: ({ ticketId, payload }) =>
			apiClient<SupportTicketMessage>(`/support/tickets/${ticketId}/messages`, {
				method: "POST",
				body: JSON.stringify(payload),
			}),
		onSuccess: (_, variables) => {
			queryClient.invalidateQueries({
				queryKey: ["ticketMessages", variables.ticketId],
			});
			queryClient.invalidateQueries({ queryKey: ["userTickets"] });
			queryClient.invalidateQueries({
				queryKey: ["admin", "support", "tickets"],
			});
		},
	});
};
