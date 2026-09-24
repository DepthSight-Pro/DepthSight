// pwa/services/api.ts

import { useAccountStore } from "../stores/accountStore";
import type {
	AccountStatusData,
	Achievement,
	AIChatMessage,
	AgentMemory,
	AddApiKeyPayload,
	ApiKey,
	AppConfig,
	BacktestRequest,
	BacktestRun,
	BacktestRunListItem,
	BinanceKline,
	CreatePaymentResponse,
	GeneStatsResponse,
	HistoricalRangeItem,
	Message,
	PaperWalletData,
	Plan,
	PortfolioStatus,
	Position,
	RunningStrategy,
	ShareBacktestPayload,
	ShareBacktestResponse,
	StrategyConfigDB,
	StrategyConfigData,
	SymbolSelectionConfig,
	Token,
	TradeData,
	User,
	UserAchievement,
	UserGenesResponse,
	LoginResponse,
	TotpStatusResponse,
	TotpSetupResponse,
	TotpConfirmResponse,
	TotpVerifyLoginPayload,
	TotpDisablePayload,
	TotpRegenerateBackupCodesPayload,
	TotpBackupCodesResponse,
} from "../types";

export const API_BASE_URL = ""; // The proxy will handle the full URL

// --- Typed payloads for PWA API (no explicit `any`) ---

interface ApiErrorPayload {
	detail?: string;
	error?: string;
	message?: string;
	[key: string]: unknown;
}

interface PwaMiningStats {
	eligibleExchanges?: string[];
	eligible_exchanges?: string[];
	rebateRates?: Record<string, number>;
	rebate_rates?: Record<string, number>;
	exchangeMultipliers?: Record<string, number>;
	exchange_multipliers?: Record<string, number>;
	dailyEmission?: number;
	daily_emission?: number;
	yourEpochReward?: number;
	your_epoch_reward?: number;
	epochTotalRebates?: number;
	epoch_total_rebates?: number;
	yourCumulativeRebates?: number;
	your_cumulative_rebates?: number;
	userCumulativeRebate?: number;
	user_cumulative_rebate?: number;
	cumulativeRebates?: number;
	totalDistributed?: number;
	total_distributed?: number;
	serverTotalMined?: number;
	server_total_mined?: number;
	serverTotalVolume?: number;
	server_total_volume?: number;
	yourVolumeShare?: number;
	your_volume_share?: number;
	yourDailyVolume?: number;
	your_daily_volume?: number;
	serverDailyVolume?: number;
	server_daily_volume?: number;
	[key: string]: unknown;
}

interface PwaMiningStatus {
	isMiningEnabled: boolean;
	is_mining_enabled?: boolean;
	isGlobalMiningEnabled?: boolean;
	is_global_mining_enabled?: boolean;
	nodeUuid?: string;
	node_uuid?: string;
	nodeName?: string;
	node_name?: string;
	registeredOnHub?: boolean;
	registered_on_hub?: boolean;
	nodeReferralCode?: string;
	node_referral_code?: string;
	referrerNodeUuid?: string;
	referrer_node_uuid?: string;
	referrerReferralCode?: string;
	referrer_referral_code?: string;
	hasWelcomeBonus?: boolean;
	has_welcome_bonus?: boolean;
	totalMined?: number;
	total_mined?: number;
	totalDistributed?: number;
	total_distributed?: number;
	serverTotalMined?: number;
	server_total_mined?: number;
	dailyEmission?: number;
	daily_emission?: number;
	yourEpochReward?: number;
	your_epoch_reward?: number;
	epochTotalRebates?: number;
	epoch_total_rebates?: number;
	userCumulativeRebate?: number;
	user_cumulative_rebate?: number;
	userRewardSharePercent?: number;
	user_reward_share_percent?: number;
	userTradeVolume?: number;
	user_trade_volume?: number;
	userEstimatedRebate?: number;
	user_estimated_rebate?: number;
	config?: Record<string, unknown>;
	stats?: PwaMiningStats;
	exchangeMultipliers?: Record<string, number>;
	exchange_multipliers?: Record<string, number>;
	[key: string]: unknown;
}

interface PwaPromoQuestRequirements {
	hasExchangeKey?: boolean;
	exchangeUid?: string | null;
	isMasterAccount?: boolean;
	verifiedVolume?: number;
	volumeThreshold?: number;
	totalVolume?: number;
	currentVolume?: number;
	isVolumeVerifying?: boolean;
	isVolumeVerified?: boolean;
	isPhysicalNode?: boolean;
	nodeAgeDays?: number;
	minNodeAgeDays?: number;
	hasWallet?: boolean;
	hasActiveMining?: boolean;
	[key: string]: unknown;
}

interface PwaPromoQuestProgress {
	questType: string;
	title?: string;
	description?: string;
	reward?: number;
	totalSlots?: number;
	claimedSlots?: number;
	remainingSlots?: number;
	isClaimed?: boolean;
	allRequirementsMet?: boolean;
	requirements?: PwaPromoQuestRequirements;
	[key: string]: unknown;
}

interface PwaPromoStatus {
	hasActiveCampaign: boolean;
	has_active_campaign?: boolean;
	campaignId?: string;
	campaign_id?: string;
	campaignName?: string;
	campaign_name?: string;
	description?: string;
	exchangeId?: string;
	exchange_id?: string;
	isActive?: boolean;
	isAdminPreview?: boolean;
	is_admin_preview?: boolean;
	totalPool?: number;
	distributed?: number;
	remainingPool?: number;
	rebateMultiplier?: number;
	quests?: PwaPromoQuestProgress[];
	uiConfig?: Record<string, unknown>;
	ui_config?: Record<string, unknown>;
	[key: string]: unknown;
}

interface PwaPromoClaimResponse {
	success: boolean;
	message: string;
	rewardAmount?: number;
	reward_amount?: number;
	questType?: string;
	quest_type?: string;
	claimedAt?: string;
	claimed_at?: string;
	[key: string]: unknown;
}

interface PwaMiningReferralItem {
	id: string;
	name?: string;
	createdAt?: string;
	created_at?: string;
	tradeVolumeUsdt?: number;
	trade_volume_usdt?: number;
	totalMinedDepth?: number;
	total_mined_depth?: number;
	referralBonusEarned?: number;
	referral_bonus_earned?: number;
	hasWelcomeBonus?: boolean;
	has_welcome_bonus?: boolean;
	status?: string;
	[key: string]: unknown;
}

interface PwaMiningReferralsResponse {
	totalInvited?: number;
	total_invited?: number;
	activeReferrals?: number;
	active_referrals?: number;
	totalReferralRewardsDepth?: number;
	total_referral_rewards_depth?: number;
	totalReferralVolumeUsdt?: number;
	total_referral_volume_usdt?: number;
	referrals?: PwaMiningReferralItem[];
	[key: string]: unknown;
}

interface PwaMiningDeactivateResponse {
	success: boolean;
	message?: string;
	[key: string]: unknown;
}

// --- Helper Functions ---

/**
 * Read the access token tolerantly. PWA stores JSON {access_token, ...},
 * but the web app on the same origin shares localStorage["authToken"] and
 * stores a raw JWT — whichever logged in last wins. Accept both.
 */
export const readAccessToken = (): string | null => {
	try {
		const raw = localStorage.getItem("authToken");
		if (!raw) return null;
		const trimmed = raw.trim();
		if (trimmed.startsWith("{")) {
			const parsed: unknown = JSON.parse(trimmed);
			if (parsed && typeof parsed === "object") {
				const at = (parsed as Record<string, unknown>).access_token;
				return typeof at === "string" && at.length > 0 ? at : null;
			}
			return null;
		}
		// Raw JWT fallback: three base64url segments.
		return /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(trimmed)
			? trimmed
			: null;
	} catch (e) {
		console.error("Could not parse auth token", e);
		return null;
	}
};

/** PWA-format refresh token, if present (raw-JWT storage has none). */
const readRefreshToken = (): string | null => {
	try {
		const raw = localStorage.getItem("authToken");
		if (!raw || !raw.trim().startsWith("{")) return null;
		const parsed: unknown = JSON.parse(raw);
		if (parsed && typeof parsed === "object") {
			const rt = (parsed as Record<string, unknown>).refresh_token;
			return typeof rt === "string" && rt.length > 0 ? rt : null;
		}
		return null;
	} catch {
		return null;
	}
};

/** True when at least one request can be authenticated. */
export const hasUsableAuthToken = (): boolean => readAccessToken() !== null;

/** Re-login is required: drop the broken token and reboot to AuthScreen. */
const forceReLogin = () => {
	localStorage.removeItem("authToken");
	window.location.reload();
};

const getAuthToken = (): string | null => readAccessToken();

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
		const refreshToken = readRefreshToken();
		if (!refreshToken) {
			// Raw-JWT storage (written by the web app) or no token at all:
			// refresh is impossible, re-login is required.
			forceReLogin();
			throw new Error("Not authenticated");
		}
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
					forceReLogin();
					throw new Error("Not authenticated");
				}
			} catch (e) {
				// Refresh failed or is impossible: back to AuthScreen.
				forceReLogin();
				throw e;
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

	if (!response.ok) {
		let errorData: ApiErrorPayload;
		try {
			errorData = (await response.json()) as ApiErrorPayload;
		} catch {
			errorData = { error: `HTTP error! status: ${response.status}` };
		}
		console.error(`API Error on ${endpoint}:`, errorData);
		const detailMessage =
			typeof errorData.detail === "string" && errorData.detail
				? errorData.detail
				: typeof errorData.error === "string" && errorData.error
					? errorData.error
					: typeof errorData.message === "string" && errorData.message
						? errorData.message
						: `Request failed with status ${response.status}`;
		throw new Error(detailMessage);
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
	strategy_json?: StrategyConfigData;
	history?: Message[];
	image_base64?: string;
	image_mime_type?: string;
}

interface AiChatResponse {
	text_response: string;
	session_id: string;
	strategy_json?: StrategyConfigData | null;
}

export const api = {
	// --- Auth ---
	login: (formData: FormData): Promise<LoginResponse> => {
		return fetch(`${API_BASE_URL}/api/v1/token`, {
			method: "POST",
			body: formData,
		}).then((res) => (res.ok ? res.json() : Promise.reject(res)));
	},
	verifyTotpLogin: (
		payload: TotpVerifyLoginPayload,
	): Promise<{ token: Token; user: User }> =>
		fetch(`${API_BASE_URL}/api/v1/auth/2fa/verify-login`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
		}).then(async (res) => {
			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw new Error(err.detail || "2FA verification failed");
			}
			return res.json();
		}),
	getTotpStatus: (): Promise<TotpStatusResponse> =>
		apiFetch<TotpStatusResponse>("/auth/2fa/status"),
	setupTotp: (): Promise<TotpSetupResponse> =>
		apiFetch<TotpSetupResponse>("/auth/2fa/setup", {
			method: "POST",
		}),
	confirmTotp: (payload: {
		secret: string;
		code: string;
	}): Promise<TotpConfirmResponse> =>
		apiFetch<TotpConfirmResponse>("/auth/2fa/confirm", {
			method: "POST",
			body: JSON.stringify(payload),
		}),
	disableTotp: (payload: TotpDisablePayload): Promise<{ message: string }> =>
		apiFetch<{ message: string }>("/auth/2fa/disable", {
			method: "POST",
			body: JSON.stringify(payload),
		}),
	regenerateBackupCodes: (
		payload: TotpRegenerateBackupCodesPayload,
	): Promise<TotpBackupCodesResponse> =>
		apiFetch<TotpBackupCodesResponse>("/auth/2fa/regenerate-backup-codes", {
			method: "POST",
			body: JSON.stringify(payload),
		}),
	register: (userData: Record<string, unknown>): Promise<{ token: Token; user: User }> =>
		apiFetch("/register", {
			method: "POST",
			body: JSON.stringify(userData),
		}),
	getMe: (): Promise<User> => apiFetch<User>("/users/me"),
	getAgentMemories: (): Promise<AgentMemory[]> =>
		apiFetch<AgentMemory[]>("/ai/memories"),
	deleteAgentMemories: (): Promise<void> =>
		apiFetch<void>("/ai/memories", {
			method: "DELETE",
		}),
	deleteAgentMemory: (memoryId: string): Promise<void> =>
		apiFetch<void>(`/ai/memories/${memoryId}`, {
			method: "DELETE",
		}),
	deduplicateAgentMemories: (): Promise<{ deleted_count: number }> =>
		apiFetch<{ deleted_count: number }>("/ai/memories/deduplicate", {
			method: "POST",
		}),
	updateCommunityMemorySharing: (
		enabled: boolean,
	): Promise<{ share_community_memories: boolean; promoted_count?: number }> =>
		apiFetch<{ share_community_memories: boolean; promoted_count?: number }>("/ai/memories/community-sharing", {
			method: "PUT",
			body: JSON.stringify({ enabled }),
		}),
	shareAgentMemory: (
		memoryId: string,
	): Promise<{ status: string; community_memory_id?: string }> =>
		apiFetch<{ status: string; community_memory_id?: string }>(`/ai/memories/${memoryId}/share`, {
			method: "POST",
		}),

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
	// Last close price for a symbol via backend ccxt proxy (WEEX tick fallback).
	getProxyKlines: (
		symbol: string,
		interval: string,
		exchange: string,
		limit = 1,
	): Promise<Array<[number, number, number, number, number, number]>> => {
		const q = new URLSearchParams({
			symbol: symbol.replace(/[^a-zA-Z0-9]/g, "").toUpperCase(),
			interval,
			exchange,
			limit: String(limit),
		});
		return apiFetch<Array<[number, number, number, number, number, number]>>(
			`/proxy/klines?${q.toString()}`,
		);
	},

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
	getChatHistory: (sessionId: string): Promise<AIChatMessage[]> =>
		apiFetch<AIChatMessage[]>(`/ai/chat/history/${sessionId}`),
	deleteChatSession: (sessionId: string): Promise<void> =>
		apiFetch<void>(`/ai/chat/history/${sessionId}`, {
			method: "DELETE",
		}),
	getBlockRestrictions: (): Promise<{ proOnly: string[]; klineOnly: string[] }> =>
		apiFetch<{ proOnly: string[]; klineOnly: string[] }>("/config/block-restrictions"),

	shareBacktest: (
		payload: ShareBacktestPayload,
	): Promise<ShareBacktestResponse> =>
		apiFetch<ShareBacktestResponse>(`/backtests/${payload.runId}/share`, {
			method: "POST",
			body: JSON.stringify(payload),
		}),

	getHistoricalRanges: (symbol?: string): Promise<HistoricalRangeItem[]> => {
		const query = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
		return apiFetch<HistoricalRangeItem[]>(`/backtests/historical-ranges${query}`);
	},

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
		config_data: StrategyConfigData;
		use_ml_confirmation?: boolean;
		foundation_weights?: Record<string, number> | null;
		oracle_regime?: number | null;
		oracle_confidence?: number;
		symbol_selection_mode?: "DYNAMIC" | "STATIC";
		symbols?: string[] | null;
	}): Promise<StrategyConfigDB> =>
		apiFetch<StrategyConfigDB>("/strategies/config", {
			method: "POST",
			body: JSON.stringify(data),
		}),
	updateStrategyConfig: (
		configId: string,
		data: {
			name?: string;
			description?: string;
			config_data?: StrategyConfigData;
			use_ml_confirmation?: boolean;
			foundation_weights?: Record<string, number> | null;
			oracle_regime?: number | null;
			oracle_confidence?: number;
			symbol_selection_mode?: "DYNAMIC" | "STATIC";
			symbols?: string[] | null;
		},
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

	getMiningStatus: (): Promise<PwaMiningStatus> =>
		apiFetch<PwaMiningStatus>("/mining/status"),
	getPromoStatus: (nodeUuid?: string): Promise<PwaPromoStatus> =>
		apiFetch<PwaPromoStatus>(
			`/hub/promo/status${nodeUuid ? `?node_uuid=${encodeURIComponent(nodeUuid)}` : ""}`,
		),
	claimPromoQuest: (
		campaignId: string,
		questType: string,
		nodeUuid?: string,
	): Promise<PwaPromoClaimResponse> =>
		apiFetch<PwaPromoClaimResponse>(
			`/hub/promo/claim${nodeUuid ? `?node_uuid=${encodeURIComponent(nodeUuid)}` : ""}`,
			{
				method: "POST",
				body: JSON.stringify({
					campaign_id: campaignId,
					quest_type: questType,
				}),
			},
		),
	getMiningReferrals: (): Promise<PwaMiningReferralsResponse> =>
		apiFetch<PwaMiningReferralsResponse>("/hub/mining/referrals"),
	activateMining: (referrerCode?: string): Promise<PwaMiningStatus> =>
		apiFetch<PwaMiningStatus>("/mining/activate", {
			method: "POST",
			body: JSON.stringify({
				referrer_code: referrerCode,
				referrerCode: referrerCode,
			}),
		}),
	deactivateMining: (): Promise<PwaMiningDeactivateResponse> =>
		apiFetch<PwaMiningDeactivateResponse>("/mining/deactivate", {
			method: "POST",
		}),
	getWalletNonce: (address: string): Promise<{ nonce: string; message: string }> =>
		apiFetch<{ nonce: string; message: string }>("/node/wallet/nonce", {
			method: "POST",
			body: JSON.stringify({ address }),
		}),
	verifyWalletSignature: (
		address: string,
		signature: string,
		nonce: string,
		message?: string
	): Promise<{ walletAddress: string; nodeUuid: string; status: string }> =>
		apiFetch<{ walletAddress: string; nodeUuid: string; status: string }>("/node/wallet/verify", {
			method: "POST",
			body: JSON.stringify({ address, signature, nonce, message }),
		}),
	getWalletStatus: (): Promise<{ walletAddress?: string; nodeUuid?: string; walletConfigured: boolean }> =>
		apiFetch<{ walletAddress?: string; nodeUuid?: string; walletConfigured: boolean }>("/node/wallet/status"),
	disconnectWallet: (): Promise<{ success: boolean }> =>
		apiFetch<{ success: boolean }>("/node/wallet/disconnect", {
			method: "POST",
		}),
};

