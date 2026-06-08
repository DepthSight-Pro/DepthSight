// pwa/services/api.ts

import { useAccountStore } from "../stores/accountStore";
import type {
	AccountStatusData,
	Achievement,
	AddApiKeyPayload,
	ApiKey,
	AppConfig,
	BacktestRequest,
	BacktestRun,
	BacktestRunListItem,
	BinanceKline,
	CreatePaymentResponse,
	GeneStatsResponse,
	PaperWalletData,
	Plan,
	PortfolioStatus,
	Position,
	RunningStrategy,
	ShareBacktestPayload,
	ShareBacktestResponse,
	StrategyConfig,
	StrategyConfigDB,
	SymbolSelectionConfig,
	Token,
	TradeData,
	User,
	UserAchievement,
	UserGenesResponse,
} from "../types";

export const API_BASE_URL = ""; // The proxy will handle the full URL

// --- Helper Functions ---

const getAuthToken = (): string | null => {
	try {
		const tokenData = localStorage.getItem("authToken");
		return tokenData ? JSON.parse(tokenData).access_token : null;
	} catch (e) {
		console.error("Could not parse auth token", e);
		return null;
	}
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

const apiFetch = async <T = unknown>(
	endpoint: string,
	options: RequestInit = {},
): Promise<T> => {
	const token = getAuthToken();
	const headers = new Headers(options.headers);

	if (!headers.has("Content-Type")) {
		headers.set("Content-Type", "application/json");
	}

	if (token) {
		headers.set("Authorization", `Bearer ${token}`);
	}

	let response = await fetch(`${API_BASE_URL}/api/v1${endpoint}`, {
		...options,
		headers,
	});

	if (
		response.status === 401 &&
		!endpoint.includes("/token") &&
		!endpoint.includes("/refresh")
	) {
		const tokenDataString = localStorage.getItem("authToken");
		if (tokenDataString) {
			try {
				const parsedToken = JSON.parse(tokenDataString);
				const refreshToken = parsedToken.refresh_token;
				if (refreshToken) {
					if (!isRefreshing) {
						isRefreshing = true;
						try {
							const refreshResponse = await fetch(
								`${API_BASE_URL}/api/v1/refresh`,
								{
									method: "POST",
									headers: {
										"Content-Type": "application/json",
									},
									body: JSON.stringify({ refresh_token: refreshToken }),
								},
							);

							if (refreshResponse.ok) {
								const newTokenData = await refreshResponse.json();
								localStorage.setItem("authToken", JSON.stringify(newTokenData));
								onRefreshed(newTokenData.access_token);
							} else {
								localStorage.removeItem("authToken");
								window.location.href = "/login";
							}
						} catch {
							localStorage.removeItem("authToken");
							window.location.href = "/login";
						} finally {
							isRefreshing = false;
						}
					}

					const newAccessToken = await new Promise<string>((resolve) => {
						subscribeTokenRefresh((token: string) => {
							resolve(token);
						});
					});

					headers.set("Authorization", `Bearer ${newAccessToken}`);
					response = await fetch(`${API_BASE_URL}/api/v1${endpoint}`, {
						...options,
						headers,
					});
				}
			} catch (e) {
				console.error("Error parsing auth token", e);
			}
		}
	}

	if (!response.ok) {
		let errorData;
		try {
			errorData = await response.json();
		} catch {
			errorData = { error: `HTTP error! status: ${response.status}` };
		}
		console.error(`API Error on ${endpoint}:`, errorData);
		throw new Error(
			errorData.error || `Request failed with status ${response.status}`,
		);
	}

	if (response.status === 204) {
		return null as T;
	}

	const json = await response.json();
	return (json.data !== undefined ? json.data : json) as T;
};

// Helper to get API key query param
const getApiKeyQuery = (mode?: "live" | "paper") => {
	if (mode === "paper") return "";
	const { selectedApiKeyId } = useAccountStore.getState();
	if (selectedApiKeyId !== "all" && selectedApiKeyId !== undefined) {
		return `&api_key_id=${selectedApiKeyId}`;
	}
	return "";
};

// --- API Service Object ---

interface AiChatRequest {
	text_prompt: string;
	session_id: string;
	mode?: "advisor" | "generator";
	backtest_id?: string | null;
	strategy_json?: StrategyConfig;
	history?: Message[];
}

interface AiChatResponse {
	text_response: string;
	session_id: string;
	strategy_json?: StrategyConfig | null;
}

export const api = {
	// --- Auth ---
	login: (formData: FormData): Promise<{ token: Token; user: User }> => {
		return fetch(`${API_BASE_URL}/api/v1/token`, {
			method: "POST",
			body: formData,
		}).then((res) => (res.ok ? res.json() : Promise.reject(res)));
	},
	register: (userData: Record<string, unknown>): Promise<{ token: Token; user: User }> =>
		apiFetch("/register", {
			method: "POST",
			body: JSON.stringify(userData),
		}),
	getMe: (): Promise<User> => apiFetch<User>("/users/me"),

	// --- Dashboard ---
	getPortfolio: (mode: "live" | "paper"): Promise<PortfolioStatus> =>
		apiFetch<PortfolioStatus>(`/portfolio?mode=${mode}${getApiKeyQuery(mode)}`),
	getPositions: (mode: "live" | "paper"): Promise<Position[]> =>
		apiFetch<Position[]>(`/positions?mode=${mode}${getApiKeyQuery(mode)}`),
	getPortfolioEquity: (
		mode: "live" | "paper",
		period: "1d" | "7d" | "mtd",
	): Promise<[number, number][]> =>
		apiFetch<[number, number][]>(
			`/portfolio/equity?mode=${mode}&period=${period}${getApiKeyQuery(mode)}`,
		),
	closePosition: (symbol: string): Promise<{ message: string }> =>
		apiFetch<{ message: string }>(`/positions/${symbol}`, {
			method: "DELETE",
		}),

	// --- AI Chat ---
	aiChat: (request: AiChatRequest): Promise<AiChatResponse> =>
		apiFetch<AiChatResponse>("/ai/chat", {
			method: "POST",
			body: JSON.stringify(request),
		}),
	getLatestChatSession: (): Promise<string | null> =>
		apiFetch<string | null>("/ai/chat/latest-session"),
	initChatSession: (sessionId: string, initialMessage: string): Promise<void> =>
		apiFetch<void>("/ai/chat/history/init", {
			method: "POST",
			body: JSON.stringify({
				session_id: sessionId,
				initial_message: initialMessage,
			}),
		}),
	getChatHistory: (sessionId: string): Promise<Message[]> =>
		apiFetch<Message[]>(`/ai/chat/history/${sessionId}`),
	deleteChatSession: (sessionId: string): Promise<void> =>
		apiFetch<void>(`/ai/chat/history/${sessionId}`, {
			method: "DELETE",
		}),

	shareBacktest: (
		payload: ShareBacktestPayload,
	): Promise<ShareBacktestResponse> =>
		apiFetch<ShareBacktestResponse>(`/backtests/${payload.runId}/share`, {
			method: "POST",
			body: JSON.stringify(payload),
		}),

	// --- Strategies ---
	getSavedStrategies: (): Promise<StrategyConfigDB[]> =>
		apiFetch<StrategyConfigDB[]>("/strategies/config"),
	getStrategyConfig: (configId: string): Promise<StrategyConfigDB> =>
		apiFetch<StrategyConfigDB>(`/strategies/config/${configId}`),
	getRunningStrategies: (): Promise<RunningStrategy[]> => {
		const q = getApiKeyQuery("live");
		return apiFetch<RunningStrategy[]>(`/strategies${q ? `?${q.substring(1)}` : ""}`);
	},
	startStrategy: (
		config_id: string,
		mode: "live" | "paper" = "live",
		symbolSelectionMode?: "STATIC" | "DYNAMIC",
		symbols?: string[],
		params?: Record<string, unknown>,
	): Promise<unknown> => {
		const payload: Record<string, unknown> = { config_id, mode };
		if (symbolSelectionMode)
			payload.symbol_selection_mode = symbolSelectionMode;
		if (symbols && symbols.length > 0) payload.symbols = symbols;
		if (params) payload.params = params;
		if (mode === "live") {
			const { selectedApiKeyId } = useAccountStore.getState();
			if (selectedApiKeyId !== "all" && selectedApiKeyId !== undefined) {
				payload.api_key_id = selectedApiKeyId;
			}
		}
		return apiFetch("/strategies", {
			method: "POST",
			body: JSON.stringify(payload),
		});
	},
	stopStrategy: (instance_id: string): Promise<unknown> =>
		apiFetch(`/strategies/${instance_id}`, {
			method: "DELETE",
		}),
	saveStrategy: (data: {
		name: string;
		description: string;
		config_data: StrategyConfig;
	}): Promise<StrategyConfigDB> =>
		apiFetch<StrategyConfigDB>("/strategies/config", {
			method: "POST",
			body: JSON.stringify(data),
		}),
	updateStrategyConfig: (
		configId: string,
		data: { name?: string; description?: string; config_data?: StrategyConfig },
	): Promise<StrategyConfigDB> =>
		apiFetch<StrategyConfigDB>(`/strategies/config/${configId}`, {
			method: "PUT",
			body: JSON.stringify(data),
		}),
	deleteStrategyConfig: (configId: string): Promise<void> =>
		apiFetch<void>(`/strategies/config/${configId}`, {
			method: "DELETE",
		}),

	// --- Backtests ---
	getBacktests: (): Promise<BacktestRunListItem[]> => apiFetch<BacktestRunListItem[]>("/backtests"),
	getBacktestDetails: (runId: string): Promise<BacktestRun> =>
		apiFetch<BacktestRun>(`/backtests/${runId}`),
	runBacktest: (request: BacktestRequest): Promise<unknown> =>
		apiFetch("/backtests", {
			method: "POST",
			body: JSON.stringify(request),
		}),
	getBacktestKlines: (
		runId: string,
		interval: string,
		startTime?: number,
		endTime?: number,
	): Promise<BinanceKline[]> => {
		let url = `/backtests/${runId}/klines?interval=${interval}`;
		if (startTime) url += `&startTime=${startTime}`;
		if (endTime) url += `&endTime=${endTime}`;
		return apiFetch<BinanceKline[]>(url);
	},

	// --- Account ---
	getAccountStatus: (): Promise<AccountStatusData> =>
		apiFetch<AccountStatusData>("/account/status"),
	getPaperWallet: (): Promise<PaperWalletData[]> => apiFetch<PaperWalletData[]>("/account/paper"),
	resetPaperAccount: (): Promise<void> =>
		apiFetch<void>("/account/paper/reset", { method: "POST" }),
	deleteAccount: (): Promise<void> =>
		apiFetch<void>("/users/me", { method: "DELETE" }),
	getPlans: (): Promise<Plan[]> => apiFetch<Plan[]>("/payments/plans"),
	createPayment: (data: {
		plan_name: string;
	}): Promise<CreatePaymentResponse> =>
		apiFetch<CreatePaymentResponse>("/payments/create", {
			method: "POST",
			body: JSON.stringify(data),
		}),

	// --- Config ---
	getConfig: (): Promise<AppConfig> => apiFetch<AppConfig>("/config"),
	updateConfig: (data: Partial<AppConfig>): Promise<AppConfig> =>
		apiFetch<AppConfig>("/config", {
			method: "PUT",
			body: JSON.stringify(data),
		}),

	// --- API Keys ---
	addApiKey: (data: AddApiKeyPayload): Promise<ApiKey> =>
		apiFetch<ApiKey>("/config/api-keys", {
			method: "POST",
			body: JSON.stringify(data),
		}),
	deleteApiKey: (apiKeyId: number): Promise<void> =>
		apiFetch<void>(`/config/api-keys/${apiKeyId}`, {
			method: "DELETE",
		}),
	testApiKey: (apiKeyId: number): Promise<ApiKey> =>
		apiFetch<ApiKey>(`/config/api-keys/${apiKeyId}/test`, {
			method: "POST",
		}),

	// --- Data Sources ---
	addSymbol: (symbol: string): Promise<unknown> =>
		apiFetch("/config/datasources/symbols", {
			method: "POST",
			body: JSON.stringify({ symbol }),
		}),
	deleteSymbol: (symbol: string): Promise<unknown> =>
		apiFetch(`/config/datasources/symbols/${encodeURIComponent(symbol)}`, {
			method: "DELETE",
		}),

	// --- Gamification ---
	getAchievements: (): Promise<Achievement[]> => apiFetch<Achievement[]>("/achievements"),
	getUserAchievements: (userId: number): Promise<UserAchievement[]> =>
		apiFetch<UserAchievement[]>(`/users/${userId}/achievements`),
	getMyGenes: (): Promise<UserGenesResponse> => apiFetch<UserGenesResponse>("/genes/my"),
	getGeneStats: (): Promise<GeneStatsResponse> => apiFetch<GeneStatsResponse>("/genes/stats"),

	// --- Symbol Selection ---
	fetchSymbolSelectionSettings: (): Promise<SymbolSelectionConfig> =>
		apiFetch<SymbolSelectionConfig>("/users/settings/symbol-selection"),
	updateSymbolSelectionSettings: (
		settings: SymbolSelectionConfig,
	): Promise<SymbolSelectionConfig> =>
		apiFetch<SymbolSelectionConfig>("/users/settings/symbol-selection", {
			method: "PUT",
			body: JSON.stringify(settings),
		}),

	getTrades: (
		params: Record<string, unknown>,
	): Promise<{ trades: TradeData[]; total: number }> => {
		const queryParams = new URLSearchParams();
		Object.entries(params).forEach(([key, value]) => {
			if (value !== undefined && value !== null)
				queryParams.append(key, String(value));
		});

		if (params.mode === "live") {
			const keyQuery = getApiKeyQuery("live");
			if (keyQuery) {
				const id = keyQuery.split("=")[1];
				queryParams.append("api_key_id", id);
			}
		}

		return apiFetch<{ trades: TradeData[]; total: number }>(`/trades?${queryParams.toString()}`);
	},
};
