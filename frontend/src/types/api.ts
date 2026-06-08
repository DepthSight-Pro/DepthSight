// src/types/api.ts

// --- Common types ---
export interface ApiResponse<T = unknown> {
	data: T;
	error?: string;
	detail?: string;
}

// --- System types ---
export interface SystemComponent {
	name: string;
	status: string;
	message?: string;
}

export interface SystemStatusData {
	status: string;
	version: string;
	timestamp_utc: string;
	components: SystemComponent[];
}

export interface PortfolioData {
	balance: number;
	today_pnl: number;
	is_trading_allowed: boolean;
	consecutive_losses: number;
	timestamp_utc: string;
	market_type?: MarketScope;
	marketType?: MarketScope;
	total_available?: number;
	totalAvailable?: number;
	total_unrealized_pnl?: number;
	totalUnrealizedPnl?: number;
	total_margin_used?: number;
	totalMarginUsed?: number;
	market_breakdown?: MarketBalanceSummary[];
	marketBreakdown?: MarketBalanceSummary[];
}

export type MarketScope = "all" | "futures_usdtm" | "spot";

// --- Types for entities ---
export interface StrategyTemplate {
	name: string;
	description: string;
	default_params: Record<string, unknown>;
}

export interface StrategyData {
	id: string;
	name: string;
	strategy_name: string;
	symbol: string;
	market_type: string;
	status: string;
	pnl: number;
	open_positions: number;
	started_at: string;
	params: Record<string, unknown>;
	mode: "live" | "paper";
	symbol_selection_mode?: "STATIC" | "DYNAMIC";
	symbols?: string[];
}

// We import types from the editor to ensure their full consistency
import type {
	ActionBlock,
	ConditionBlock,
	ManagementBlock,
	TriggerState,
} from "@/components/strategy-editor/types";

// Overriding important types here for file completeness
export interface StrategyConfigData {
	enabled?: boolean;
	strategy_name: string;
	symbol: string;
	signal_source?: "internal" | "tradingview_webhook";
	marketType: "FUTURES" | "SPOT";
	min_foundation_weight_threshold?: number;
	foundation_weights?: Record<string, number> | null;
	filters: ConditionBlock;
	entryTrigger: TriggerState;
	entryConditions: ConditionBlock;
	initialization: ActionBlock;
	positionManagement: ManagementBlock[];
	unsupported_features?: string[];
	oracle_regime?: number | null;
	oracle_confidence?: number;
	use_ml_confirmation?: boolean;
	breakeven_on_regime_change?: boolean;

	// Dynamic Symbol Selection Settings
	natr_settings?: Record<string, unknown> | null;
	oracle_settings?: Record<string, unknown> | null;
	max_concurrent_symbols?: number | null;
}

// Returning and correctly defining StrategyConfig
export interface StrategyConfig {
	id: string;
	name: string;
	description?: string;
	user_id: number;
	config_data: StrategyConfigData;
	symbol_selection_mode: "DYNAMIC" | "STATIC";
	symbols?: string[];
	use_ml_confirmation: boolean;
	created_at: string;
	updated_at: string;
}

// --- NEW TYPE: CombinedStrategy for UI combining Config and Runtime Data ---
export type CombinedStrategy = StrategyConfig &
	Partial<Omit<StrategyData, "id" | "name">>;

export interface TradeData {
	id: number;
	trade_uuid: string;
	timestamp_signal?: number;
	timestamp_entry?: number; // When position was actually opened
	timestamp_close: number;
	symbol: string;
	strategy?: string;
	strategy_config_id?: string;
	direction: "LONG" | "SHORT";
	entry_price?: number; // Can be null for incomplete records
	exit_price?: number; // Can be null for incomplete records
	pnl?: number;
	commission?: number;
	exit_reason?: string;
	quantity?: number;
	executions?: TradeExecution[];
	trade_mode: "LIVE" | "PAPER";

	// New fields for grouping partial exits by positions
	position_entry_id?: string; // Entry ID for grouping (e.g.: "x-entry-4286085483cf46")
	exit_type?:
		| "ENTRY"
		| "PARTIAL_TAKE_PROFIT"
		| "FINAL_TAKE_PROFIT"
		| "PARTIAL_STOP_LOSS"
		| "FINAL_STOP_LOSS"
		| "EXIT"
		| "MANUAL";
	is_final_exit?: boolean; // true if this is the last exit from the position

	// Maximum floating profit and loss during the trade (for analytics)
	max_floating_profit?: number; // MFP - Maximum floating profit in USD
	max_floating_loss?: number; // MFL - Maximum floating loss in USD

	// Decision trace for foundation analysis (works for visual and genetic strategies)
	signal_details_json?: Record<string, unknown>;
}
/**
 * Describes data for direct strategy launch.
 * Can be used for test runs or ML strategies.
 */
export interface StrategyRunRequest {
	strategy_name: string;
	symbol: string;
	market_type: string;
	params: Record<string, unknown>;
	mode: "live" | "paper";
}

export interface StrategyConfigCreatePayload {
	name: string;
	description?: string | null;
	config_data: StrategyConfigData;
	symbol_selection_mode: "DYNAMIC" | "STATIC";
	symbols?: string[];
	use_ml_confirmation: boolean;
	foundation_weights: Record<string, number> | null;
	oracle_regime?: number | null;
	oracle_confidence?: number;
}

// --- Other types that you already had ---
export interface TradingViewWebhookInfo {
	url: string;
	user_secret_token_masked: string;
	sample_payload: Record<string, unknown>;
	requires_strategy_id: boolean;
	strategy_id?: string | null;
	symbol?: string | null;
}

export interface TradingViewWebhookStatus {
	config_id: string;
	status: string;
	updated_at: string;
	message?: string | null;
	source?: string | null;
	action?: string | null;
	symbol?: string | null;
	event_id?: string | null;
	api_key_id?: number | null;
	trace?: Record<string, unknown> | null;
}

export interface TradingViewTestSignalRequest {
	config_id: string;
	action: "buy" | "sell";
	api_key_id?: number | null;
}

export interface PositionData {
	id: string;
	symbol: string;
	strategy: string;
	direction: "LONG" | "SHORT";
	size: number;
	entry_price: number;
	mark_price: number;
	pnl: number;
	pnl_percent: number;
	entry_time: string;
	stop_loss?: number;
	take_profit?: number;
	market_type?: "futures_usdtm" | "spot";
	marketType?: "futures_usdtm" | "spot";
	signal_details_json?: Record<string, unknown>; // Decision trace for foundation analytics
}

// --- Types for tasks (backtest/optimization) ---
export interface BacktestRequest {
	name?: string;
	strategy_name: string;
	symbol: string;
	start_date: string;
	end_date: string;
	market_type: "spot" | "futures";
	params?: {
		config?: StrategyConfigData;
		[key: string]: unknown;
	};
	min_foundation_weight_threshold?: number | null;
	foundation_weights?: Record<string, number> | null;
}
export interface OptimizationRequest {
	strategy_name: string;
	symbol: string;
	start_date: string;
	end_date: string;
	optuna_config: Record<string, unknown>;
	market_type: "spot" | "futures";
}

// 1. New type for a single execution (fill)
export interface TradeExecution {
	timestamp: string;
	price: number;
	quantity: number;
	type: "ENTRY" | "EXIT";
}

// --- UPDATE BacktestTrade ---
export interface BacktestTrade {
	id: number;
	direction: "LONG" | "SHORT";
	timestamp_entry: string;
	timestamp_exit: string;
	entry_price: number;
	exit_price: number;
	quantity: number;
	pnl: number;
	commission: number;
	exit_reason: string;
	decision_trace_json: Record<string, unknown> | null;
	executions?: TradeExecution[];
}

// --- Final KPIs (replaces the old BacktestResultsData) ---
export interface BacktestKpiResults {
	total_pnl: number;
	sharpe_ratio: number;
	win_rate: number;
	max_drawdown: number;
	trades: number;
	total_commission?: number;
}

// --- Updating the task type to match the BacktestRun model ---
export interface BacktestRunListItemData {
	id: string; // run_id
	task_id: string;
	strategy_name: string;
	symbol: string;
	status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
	created_at: string;
	completed_at?: string;
	pnl?: number;
	win_rate?: number;
}

export interface BacktestRunDetailsData {
	id: string;
	task_id: string;
	strategy_name: string;
	symbol: string;
	status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
	created_at: string;
	completed_at?: string;
	start_date: string;
	end_date: string;
	parameters_json: {
		config?: StrategyConfigData;
		[key: string]: unknown;
	};
	kpi_results_json?: BacktestKpiResults;
	equity_curve_json?: [number, number][];
	analytics_report_json?: Record<string, unknown>;
	trades: BacktestTrade[];
	progress_info?: ProgressInfoData;
	error_message?: string;
}

// --- Share Backtest Types ---
export interface ShareBacktestPayload {
	runId: string;
	isStrategyNamePublic: boolean;
	areParametersPublic: boolean;
	publishToLeaderboard: boolean;
}

export interface ShareBacktestResponse {
	shareUrl: string;
	publicSlug: string;
}

export interface SharedBacktestData {
	strategyName: string;
	symbol: string;
	period: {
		start: string;
		end: string;
	};
	kpis: BacktestKpiResults;
	equityCurve: [number, number][];
	parameters?: Record<string, unknown>;
	strategyConfig?: StrategyConfigData;
}

// --- Updating ProgressInfoData to use the new trade type ---
export interface ProgressKpiData {
	progress: number;
	current_date: string;
	balance: number;
	pnl: number;
	trades: number;
	win_rate: number;
	max_drawdown: number;
	equity_curve_live?: [number, number][];
	live_trades: BacktestTrade[];
}
export interface ProgressEventData {
	timestamp: string;
	type: string;
	message: string;
}
export interface ProgressInfoData {
	kpis: ProgressKpiData;
	events: ProgressEventData[];
}

export interface BacktestResultsData {
	total_pnl: number;
	sharpe_ratio: number;
	win_rate: number;
	max_drawdown: number;
	trades_count: number;
	equity_curve?: [number, number][];
	trades: TradeData[];
}

export interface OptimizationTrial {
	trial_number: number;
	value: number;
	datetime_start: string;
	datetime_complete: string;
	params: Record<string, number | string | boolean>;
}

// --- Optimization results ---
export interface OptimizationResultsData {
	best_trial: OptimizationTrial | null;
	best_params: Record<string, unknown> | null;
	best_value: number | null;
	trials: OptimizationTrial[];
	parameter_importance: ParameterImportanceData | null;
	metric_name?: string;
}

export interface OptimizationProgressInfo {
	current_trial_number: number;
	total_trials_planned?: number;
	best_trial_so_far?: OptimizationTrial;
	recent_trials?: OptimizationTrial[];
	status_message?: string;
}

export interface TrialData {
	id: number;
	value: number;
	status: string;
	params_json: Record<string, unknown>;
}

export interface ParameterImportanceData {
	[key: string]: number;
}

export interface OptimizationRunDetailsData extends BacktestRunListItemData {
	fitness_metric: string;
	trials: TrialData[];
	best_trial: TrialData | null;
	parameter_importance_json: ParameterImportanceData | null;
	progress?: {
		current_trial: number;
		total_trials: number;
		best_value_so_far: number;
	};
}

export interface TaskData {
	task_id: string;
	status: "pending" | "running" | "completed" | "failed";
	submitted_at: string;
	completed_at?: string;
	error_message?: string;
	request_params?: BacktestRequest | OptimizationRequest;
	results?: BacktestResultsData | OptimizationResultsData;
	progress_info?: ProgressInfoData | OptimizationProgressInfo;
}

// --- Log types ---
export interface LogEntry {
	id: string;
	timestamp: string;
	level: "INFO" | "SUCCESS" | "WARNING" | "ERROR" | "DEBUG";
	component: string;
	message: string;
	strategy_id?: string;
}

// --- Configuration types ---
export interface ApiKey {
	id: number;
	name: string;
	keyPrefix: string;
	createdAt: string;
	lastUsed?: string;
	status?: "active" | "revoked" | "untested" | "valid" | "invalid" | "testing";
	exchange?: string;
	isActive: boolean; // Multi-account support
}

// --- Multi-Account Types ---
export interface AssetBalance {
	asset: string;
	free: number;
	locked: number;
	total: number;
}

export interface AccountBalance {
	apiKeyId: number;
	apiKeyName: string;
	exchange: string;
	marketType: "futures_usdtm" | "spot";
	balance: number;
	availableBalance: number;
	unrealizedPnl: number;
	marginUsed: number;
	totalEquity: number;
	assets: AssetBalance[];
}

export interface MarketBalanceSummary {
	marketType: "futures_usdtm" | "spot";
	totalBalance: number;
	totalAvailable: number;
	totalUnrealizedPnl: number;
	totalMarginUsed: number;
	totalEquity: number;
	accountsCount: number;
}

export interface MultiAccountOverview {
	marketType: MarketScope;
	totalBalance: number;
	totalAvailable: number;
	totalUnrealizedPnl: number;
	totalMarginUsed: number;
	totalEquity: number;
	marketBreakdown: MarketBalanceSummary[];
	accounts: AccountBalance[];
}

// --- Coin blacklist ---
export interface BlacklistedCoin {
	symbol: string;
	until: string | null; // ISO date string or null for permanent
	reason?: string;
	addedAt: string;
}

export type AutoBlacklistDuration =
	| "1h"
	| "4h"
	| "8h"
	| "end_of_day"
	| "permanent";
export type AutoBlacklistWithinPeriod =
	| "15m"
	| "30m"
	| "1h"
	| "2h"
	| "4h"
	| "8h"
	| "24h"
	| null;

export interface AutoBlacklistRule {
	id: string;
	enabled: boolean;
	consecutiveStops: number;
	withinPeriod?: AutoBlacklistWithinPeriod; // null = no time limit
	duration: AutoBlacklistDuration;
}

export interface BlacklistSettings {
	coins: BlacklistedCoin[];
	autoRules?: AutoBlacklistRule[];
}

export interface AddToBlacklistPayload {
	symbol: string;
	duration?: "end_of_day" | "permanent" | "custom";
	customUntil?: string; // ISO date string if duration === 'custom'
	reason?: string;
}

export interface RiskManagementSettings {
	maxDrawdown?: number;
	dailyMaxLossPercent?: number;
	maxConsecutiveLosses?: number;
	maxConcurrentTrades?: number;
	stopLossEnabled: boolean;
	defaultStopLossPercent?: number;
	maxStopDistancePct?: number;

	// --- START: ADD THESE FIELDS ---
	// Ensure that camelCase names match those sent by the API
	strategySymbolAdjustmentEnabled?: boolean;
	strategySymbolWindowSize?: number;
	strategySymbolMinTradesForAssessment?: number;
	strategySymbolPnlThresholdPct?: number;
	strategySymbolWinRateThresholdPct?: number;
	strategySymbolMaxConsecutiveLosses?: number;
	strategySymbolRecoveryConsecutiveWins?: number;
	strategySymbolRecoveryPnlThresholdPct?: number;
	strategySymbolCooldownAfterPenaltySeconds?: number;
	strategySymbolAdjustmentEnabledForBacktest?: boolean;

	// --- Coin blacklist ---
	blacklist?: BlacklistSettings;
}

export interface BacktestRiskManagementSettings {
	maxDrawdown?: number;
	dailyMaxLossPercent?: number;
	maxConsecutiveLosses?: number;
	maxConcurrentTrades?: number;
	stopLossEnabled: boolean;
	defaultStopLossPercent?: number;
	maxStopDistancePct?: number;
	riskPerTradePercent?: number;
	leverage?: number;
	strategySymbolAdjustmentEnabledForBacktest?: boolean;
}

export interface ExchangePlatformSettings {
	enabled: boolean;
	apiKeyName: string;
}

export interface ExchangeSettings {
	binanceFutures: ExchangePlatformSettings;
}

export interface NotificationSettings {
	emailEnabled: boolean;
	telegramEnabled: boolean;
	telegramChatId?: string;
	telegramUsername?: string;
	// Granular Telegram notification settings
	notifyNewPosition?: boolean;
	notifyPositionClosed?: boolean;
	notifyPartialTp?: boolean;
	notifySlMovedToBe?: boolean;
	notifyRiskAlerts?: boolean;
	notifyOrderErrors?: boolean;
	notifyBotErrors?: boolean;
	notifyBlacklistAlerts?: boolean;
}

export interface DataSourceStatus {
	name: string;
	connected: boolean;
	lastSync?: string;
	error?: string;
}

export interface AppConfig {
	apiKeys: ApiKey[];
	riskManagement: RiskManagementSettings;
	backtestRiskManagement: BacktestRiskManagementSettings;
	notifications: NotificationSettings;
	dataSources: {
		symbols: string[];
		statuses: DataSourceStatus[];
	};
	logLevel?: "INFO" | "DEBUG" | "WARNING" | "ERROR";
}

// --- Types for external APIs ---
export type BinanceKline = [
	number,
	string,
	string,
	string,
	string,
	string,
	number,
	string,
	number,
	string,
	string,
	string,
];

// --- Types for Portfolio Backtests ---
export interface PortfolioBacktestRequest {
	name?: string;
	start_date: string;
	end_date: string;
	initial_balance: number;
	contracts: Array<{
		strategy_name: string;
		symbol: string;
		params?: Record<string, unknown>;
	}>;
	global_risk_limits?: Record<string, unknown>;
	simulate_market_impact?: boolean;
}

export interface PortfolioBacktestRunListItemData {
	run_id: string;
	name: string;
	status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
	created_at: string;
	completed_at?: string;
	portfolio_pnl?: number;
	sharpe_ratio?: number;
}

export interface PortfolioBacktestRunDetailsData
	extends PortfolioBacktestRunListItemData {
	description?: string;
	start_date: string;
	end_date: string;
	initial_balance: number;
	kpi_results_json?: PortfolioBacktestKpiResults;
	error_message?: string;
	portfolio_equity_curve_json?: [number, number][];
	strategy_performance_breakdown?: StrategyPerformanceData[];
	symbol_performance_breakdown?: SymbolPerformanceData[];
	trades?: PortfolioTrade[];
	progress_info?: ProgressInfoData;
}

export interface PortfolioTrade extends BacktestTrade {
	symbol: string;
	strategy_id: string;
	strategy_name?: string;
}

export interface SymbolPerformanceData {
	symbol: string;
	total_pnl: number;
	win_rate: number;
	total_trades: number;
}

export interface StrategyPerformanceData {
	strategy_id: string;
	strategy_name?: string;
	total_pnl: number;
	win_rate: number;
	total_trades: number;
	sharpe_ratio?: number;
	max_drawdown?: number;
}

export interface PortfolioBacktestKpiResults {
	total_portfolio_pnl: number;
	portfolio_sharpe_ratio: number;
	average_strategy_win_rate?: number;
	portfolio_max_drawdown: number;
	total_trades?: number;
}

export interface User {
	id: number;
	username: string;
	email: string;
	createdAt: string;
	plan: "free" | "standard" | "pro";
	referralCode?: string;
	role: "admin" | "user" | "affiliate";
	xp: number;
	level: number;
}

export interface QuotaStatus {
	name: string;
	used: number;
	limit: number; // -1 for unlimited
	period: "day" | "month" | "week";
}

export interface BonusInfo {
	featureName: string;
	quantity: number;
	status: string;
}

export interface AccountStatusData {
	planName: string;
	planExpiresAt?: string | null;
	quotas: QuotaStatus[];
	bonuses: BonusInfo[];
	referralProgram?: {
		referrer_bonus: { feature_name: string; quantity: number };
		referred_user_bonus: { feature_name: string; quantity: number };
	};
}

export interface PaperWalletData {
	asset: string;
	balance: number;
}

// --- Types for Genetic Search (Discovery) ---
export interface GeneticSearchRunRequest {
	config_json: Record<string, unknown>;
}

export interface GeneticSearchRunListItemData {
	id: string;
	status:
		| "PENDING"
		| "RUNNING"
		| "COMPLETED"
		| "STOPPED"
		| "FAILED"
		| "EVALUATING_HOF";
	created_at: string;
	progress: {
		current_generation: number | null;
		total_generations: number | null;
		best_fitness_so_far: number | null;
		progress_history?: Array<{
			generation: number;
			best_fitness: number;
			avg_fitness: number;
			best_pnl?: number;
			best_trades?: number;
			best_dd?: number;
		}>;
	} | null;
	config_json: {
		name: string;
		generations?: number;
	};
}

export interface GeneticSearchRunDetailsData
	extends GeneticSearchRunListItemData {
	config_json: Record<string, unknown> & { name: string };
	error_message?: string;
	generation_stats_json?: GenerationStats[];
	run_events?: RunEvent[];
	symbol?: string;
	fitness_metric?: string;
}

export interface GenerationStats {
	generation: number;
	best_fitness: number;
	avg_fitness: number;
	min_fitness?: number;
	max_fitness?: number;
}

export interface RunEvent {
	timestamp: string;
	message: string;
	type: "INFO" | "PROGRESS" | "ERROR" | "WARNING" | "NEW_BEST";
}

export interface FoundStrategyData {
	id: string;
	run_id: string;
	rank: number;
	strategy_json: Record<string, unknown>;
	fitness_score: number;
	kpis_json:
		| BacktestKpiResults
		| { status: "PENDING_EVALUATION"; backtest_task_id: string };
}

// --- Types for Strategy Configurations ---
export interface StrategyConfigSummary {
	id: string;
	name: string;
}

export interface AddApiKeyPayload {
	name: string;
	api_key: string;
	api_secret: string;
	exchange: string;
	api_password?: string;
}

// Types for creating tasks
export interface DatasetRunCreate {
	name: string;
	symbols: string[];
	start_date: string;
	end_date: string;
	feature_types: string[];
	target_variable: string;
}

export interface TrainingRunCreate {
	dataset_id: string;
	model_type: "XGBoost" | "River HOEFFDINGTREE" | "Sklearn RandomForest";
	features_json: Record<string, unknown> | string[];
	hyperparameters_json: Record<string, unknown>;
}

// Types for API responses
export interface DatasetRunResponse {
	id: string;
	name: string;
	user_id: string;
	celery_task_id?: string;
	status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
	created_at: string;
	completed_at?: string;
	file_path?: string;
	error_message?: string;
	parameters_json: {
		symbols: string[];
		start_date: string;
		end_date: string;
		feature_types: string[];
		target_variable: string;
	};
}

export interface TrainingRunResponse {
	id: string;
	dataset_id: string;
	user_id: string;
	celery_task_id?: string;
	status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
	created_at: string;
	completed_at?: string;
	model_path?: string;
	report_path?: string;
	error_message?: string;
	model_type: string;
	live_metrics_json?: Record<string, [number, number][]>;
	parameters_json: {
		features_json: Record<string, unknown> | string[];
		hyperparameters_json: Record<string, unknown>;
	};
}

// Type for the model quality report
export interface ClassificationReportEntry {
	precision: number;
	recall: number;
	"f1-score": number;
	support: number;
}

export interface ModelTrainingReport {
	classification_report: Record<string, ClassificationReportEntry | number>;
	confusion_matrix: number[][];
	feature_importance: Record<string, number>;
	model_type: string;
	dataset_id: string;
}

// Extending the User type for the admin panel to include all fields
export interface AdminUser extends User {
	isActive: boolean;
	role: "admin" | "user" | "affiliate";
	affiliateCommissionRate?: number;
	stats?: {
		referralCount: number;
		payingReferralCount: number;
		totalEarnings: number;
		pendingEarnings: number;
	};
}

export interface PaginatedAdminUsers {
	total: number;
	users: AdminUser[];
}

export interface AdminUserUpdatePayload {
	plan?: string;
	isActive?: boolean;
	role?: "admin" | "user" | "affiliate";
	affiliateCommissionRate?: number | null;
}

export interface AdminBonusPayload {
	featureName: string;
	quantity: number;
}

export interface DashboardStats {
	newUsersLast7Days: number;
	tasksRunLast7Days: number;
	taskCountsByType: Record<string, number>;
}

export interface AdminUserExtendedDetails {
	user: AdminUser;
	recentTasks: TaskData[]; // TaskData[]
	paperWallets: PaperWalletData[];
	bonuses: BonusInfo[]; // BonusData[]
}

export interface ImpersonateToken {
	access_token: string;
	token_type: string;
}

export interface AvailableBonus {
	featureName: string;
	description: string;
	defaultQuantity: number;
}

export interface FoundationStat {
	foundationId: string;
	count: number;
	avgWinRateContribution: number;
	totalGrossProfit: number;
	totalGrossLoss: number;
	profitFactor: number;
}

export interface MarketSentimentStat {
	direction: string;
	totalPnl: number;
}

export interface SystemMetrics {
	average_response_time_ms: number;
	uptime_30_days_percent: number;
	total_requests_24h: number;
	error_rate_24h: number;
}

// --- Types for the Affiliate Program (Admin) ---

// For the commissions list for a single affiliate (admin view)
export interface AdminAffiliateCommission {
	id: string;
	createdAt: string;
	amount: number;
	referralId: number;
	status: "pending" | "paid" | "cancelled";
}

// For the referrals list for a single affiliate (admin view)
export interface AdminAffiliateReferral {
	id: number;
	username: string;
	email: string;
	registeredAt: string;
	plan: string;
}

// --- Types for the Affiliate Program (Affiliate View) ---

export interface AffiliateDashboardStats {
	pendingAmount: number;
	availableAmount: number;
	totalPaidOut: number;
	clicks: number;
	registrations: number;
	payingCustomers: number;
}

export interface AffiliateCommission {
	id: string;
	createdAt: string;
	amount: number;
	status: "pending" | "available" | "paid";
	description: string;
}

export interface PaginatedAffiliateCommissions {
	total: number;
	commissions: AffiliateCommission[];
}

export interface AffiliateReferral {
	id: number;
	username: string;
	registeredAt: string;
	isPaying: boolean;
}

export interface PaginatedAffiliateReferrals {
	total: number;
	referrals: AffiliateReferral[];
}

export interface PaginatedAdminAffiliateCommissions {
	total: number;
	commissions: AdminAffiliateCommission[];
}

export interface PaginatedAdminAffiliateReferrals {
	total: number;
	referrals: AdminAffiliateReferral[];
}

export interface AffiliatePayout {
	id: string;
	createdAt: string;
	amount: number;
	status: "pending" | "completed" | "failed";
	transactionId?: string;
}

export interface PaginatedAffiliatePayouts {
	total: number;
	payouts: AffiliatePayout[];
}

export interface PayoutDetailsPayload {
	usdtTrc20Address: string;
}

export interface LeaderboardEntry {
	id: string;
	rank: number;
	score: number;
	user: {
		id: number;
		username: string;
	};
	category: string;
	period: string;
	sharedBacktestSlug: string;
	isConfigPublic: boolean;
	meta_data: {
		pnl: number;
		win_rate: number;
		trades: number;
		symbol: string;
	};
}

// --- Genome Project Types ---

export interface Gene {
	id: string;
	name: string;
	description: string | null;
	components: string[];
	rarity: number;
	discoveredAt: string;
	firstDiscoveredBy: number | null;
	metadata?: {
		win_rate?: number;
		avg_pnl?: number;
		market_regime?: string;
		avg_volatility?: number;
	};
}

export interface UserGene {
	id: number;
	userId: number;
	geneId: string;
	unlockedAt: string;
	sourceStrategyId: string | null;
	sourceType: string | null;
	gene: Gene;
}

export interface UserGenesResponse {
	total: number;
	genes: UserGene[];
}

export interface GeneStatsResponse {
	totalGenesDiscovered: number;
	totalGenesInSystem: number;
	rarityBreakdown: {
		COMMON: number;
		RARE: number;
		EPIC: number;
		LEGENDARY: number;
	};
	recentDiscoveries: UserGene[];
}

export interface Achievement {
	id: string;
	name: string;
	description: string;
	icon: string;
	xp_reward: number;
	rarity: "COMMON" | "RARE" | "EPIC" | "LEGENDARY";
}

export interface UserAchievement {
	id: number;
	user_id: number;
	achievement_id: string;
	unlocked_at: string;
	achievement: Achievement; // Nested object with achievement details
}

export type RarityTier = "COMMON" | "RARE" | "EPIC" | "LEGENDARY";

export interface SymbolSelectionConfig {
	mode: "STATIC" | "DYNAMIC_NATR" | "DYNAMIC_ORACLE";
	min_natr?: number;
	oracle_regime?: 0 | 1 | 2; // 0: Amnesia, 1: Paranoia, 2: Schizophrenia
	oracle_confidence?: number; // 0-100
	max_concurrent_symbols: number;
}

// --- AI Chat History ---

export interface AIChatMessage {
	id: string;
	user_id: number;
	session_id: string;
	role: "user" | "assistant";
	content: string;
	created_at: string;
	image_base64?: string;
	image_mime_type?: string;
}

export interface AIChatRequest {
	text_prompt: string;
	session_id: string;
	backtest_id?: string;
	history?: { role: "user" | "assistant"; content: string }[];
	strategy_json?: Record<string, unknown>;
	mode?: "advisor" | "generator";
	image_base64?: string;
	image_mime_type?: string;
}

export interface AIChatResponse {
	text_response: string;
	strategy_json?: Record<string, unknown>;
}

// --- Phantom Trade Analysis Types ---

export interface PhantomTrade {
	id: number;
	real_trade_id: string;
	user_id: number;
	symbol: string;
	direction: "LONG" | "SHORT";
	entry_price: number;
	entry_time: string;
	initial_stop_loss: number;
	initial_take_profit: number;
	be_trigger_time: string;
	be_exit_price: number;
	real_pnl_pct: number;
	real_pnl_usd?: number;
	strategy_config_id?: string;
	phantom_status: "TRACKING" | "TP_HIT" | "SL_HIT" | "TIMEOUT";
	phantom_exit_time?: string;
	phantom_exit_price?: number;
	phantom_pnl_pct?: number;
	phantom_pnl_usd?: number;
	mfe_after_be?: number;
	mae_after_be?: number;
	mfe_price?: number;
	mae_price?: number;
	candles_to_resolution?: number;
	timeout_candles?: number;
	created_at: string;
}

export interface PaginatedPhantomTradesResponse {
	total: number;
	trades: PhantomTrade[];
}

export interface BEStatsByOutcome {
	count: number;
	avg_phantom_pnl_pct: number;
	total_phantom_pnl_pct: number;
	avg_candles_to_resolution?: number;
}

export interface BEAnalysisStats {
	total_be_trades: number;
	tp_would_hit: number;
	sl_would_hit: number;
	timeout: number;
	be_saved_pct: number;
	be_stolen_pct: number;
	avg_mfe_after_be: number;
	avg_mae_after_be: number;
	avg_phantom_pnl_if_tp: number;
	avg_phantom_pnl_if_sl: number;
	avg_candles_to_resolution: number;
	by_outcome: Record<string, BEStatsByOutcome>;
	recommendation?: string;
}

export interface BEScatterDataPoint {
	trade_id: string;
	symbol: string;
	direction: "LONG" | "SHORT";
	entry_time: string;
	phantom_status: string;
	real_pnl_pct: number;
	phantom_pnl_pct?: number;
	mfe_after_be?: number;
	mae_after_be?: number;
	candles_to_resolution?: number;
}

export interface BEScatterDataResponse {
	points: BEScatterDataPoint[];
	total_points: number;
	avg_mfe: number;
	avg_mae: number;
}
