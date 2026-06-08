import {
	ConditionBlock,
	TriggerState,
	ActionBlock,
	ManagementBlock,
} from "./types/strategyEditor";

// --- Screen Navigation ---
export enum Screen {
	Auth = "Auth",
	Dashboard = "Dashboard",
	Strategies = "Strategies",
	Research = "Research",
	Notifications = "Notifications",
	AIChat = "AIChat",
	Editor = "Editor",
	BacktestResult = "BacktestResult",
	Profile = "Profile",
	Settings = "Settings",
	ForgotPassword = "ForgotPassword",
	ResetPassword = "ResetPassword",
}

// --- AI Chat ---
export interface Message {
	id: string;
	role: "user" | "ai";
	content: React.ReactNode;
	strategy_json?: StrategyConfigData | null;
}

// --- AI Chat History ---

export interface AIChatMessage {
	id: string;
	user_id: number;
	session_id: string;
	role: "user" | "assistant";
	content: string;
	strategy_json?: StrategyConfigData | null;
	created_at: string;
}

export interface AIChatRequest {
	text_prompt: string;
	session_id: string;
	backtest_id?: string;
	history?: { role: "user" | "assistant"; content: string }[];
	strategy_json?: StrategyConfigData | null;
	mode?: "advisor" | "generator";
	image_base64?: string;
	image_mime_type?: string;
}

export interface AIChatResponse {
	text_response: string;
	strategy_json?: StrategyConfigData | null;
}

// --- Strategy Editor ---
export interface StrategyBlock {
	name: string;
	type: string;
	params: Record<string, unknown>;
}

export interface EditableBlock {
	block: StrategyBlock;
	section: "filters" | "entryConditions" | "positionManagement";
}

// Merged type for the UI
export interface DisplayStrategy extends StrategyConfigDB {
	isRunning: boolean;
	runningInstance?: RunningStrategy;
}

export * from "./types/strategyEditor";

// --- General types ---
export interface ApiResponse<T = unknown> {
	data: T;
	error?: string;
	detail?: string;
}

// --- System types ---
export interface SystemComponent {
	name: string;
	status: string;
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
}

// --- Entity types ---
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
}

export interface StrategyConfigData {
	name: string;
	symbol: string;
	marketType: "FUTURES" | "SPOT";
	foundationWeights?: Record<string, number> | null;
	filters: ConditionBlock;
	entryTrigger: TriggerState;
	entryConditions: ConditionBlock;
	initialization: ActionBlock;
	positionManagement: ManagementBlock[];
	strategy_name?: string;
	[key: string]: unknown;
}

export interface StrategyConfig {
	id: string;
	name: string;
	description?: string;
	user_id: number;
	config_data: StrategyConfigData;
	symbol_selection_mode: "DYNAMIC" | "STATIC";
	symbols: string[] | null;
	use_ml_confirmation: boolean;
	created_at: string;
	updated_at: string;
}

export interface TradeData {
	id: number;
	trade_uuid: string;
	timestamp_signal: number;
	timestamp_close: number;
	symbol: string;
	strategy: string;
	direction: "LONG" | "SHORT";
	entry_price: number;
	exit_price: number;
	pnl: number;
	commission: number;
	exit_reason: string;
	quantity: number;
	executions?: TradeExecution[];
	trade_mode: "LIVE" | "PAPER";
}

export interface StrategyRunRequest {
	strategy_name: string;
	symbol: string;
	market_type: string;
	params: Record<string, unknown>;
	mode: "live" | "paper";
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
}

export interface BacktestRequest {
	strategy_name: string;
	symbol: string;
	start_date: string;
	end_date: string;
	market_type: "spot" | "futures";
	params?: {
		config: StrategyConfigData;
		[key: string]: unknown;
	};
	min_foundation_weight_threshold?: number | null;
	foundation_weights?: Record<string, number> | null;
}

export interface StrategyConfigCreatePayload {
	name: string;
	description?: string | null;
	config_data: StrategyConfigData;
	symbol_selection_mode: "DYNAMIC" | "STATIC";
	symbols: string[] | null;
	use_ml_confirmation: boolean;
	foundation_weights: Record<string, number> | null;
}

export interface OptimizationRequest {
	strategy_name: string;
	symbol: string;
	start_date: string;
	end_date: string;
	optuna_config: Record<string, unknown>;
	market_type: "spot" | "futures";
}

export interface TradeExecution {
	timestamp: string;
	price: number;
	quantity: number;
	type: "ENTRY" | "EXIT";
}

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

export interface BacktestKpiResults {
	total_pnl: number;
	sharpe_ratio: number;
	win_rate: number;
	max_drawdown: number;
	trades: number;
	total_commission?: number;
}

export interface BacktestRunListItemData {
	id: string;
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
	initial_balance: number;
	parameters_json: {
		config?: StrategyConfigData;
		[key: string]: unknown;
	};
	kpi_results_json: BacktestKpiResults | null;
	equity_curve_json?: [number, number][];
	trades: BacktestTrade[];
	progress_info?: ProgressInfoData;
	error_message?: string;
}

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

export interface LogEntry {
	id: string;
	timestamp: string;
	level: "INFO" | "SUCCESS" | "WARNING" | "ERROR" | "DEBUG";
	component: string;
	message: string;
	strategy_id?: string;
}

export interface ApiKey {
	id: number;
	name: string;
	keyPrefix: string;
	createdAt: string;
	lastUsed?: string;
	status?: "active" | "revoked" | "untested" | "valid" | "invalid" | "testing";
	exchange?: string;
	isActive: boolean;
}

export interface RiskManagementSettings {
	maxDrawdown?: number;
	dailyMaxLossPercent?: number;
	maxConsecutiveLosses?: number;
	maxConcurrentTrades?: number;
	stopLossEnabled: boolean;
	defaultStopLossPercent?: number;
	maxStopDistancePct?: number;
	strategySymbolAdjustmentEnabled?: boolean;
	strategySymbolWindowSize?: number;
	strategySymbolMinTradesForAssessment?: number;
	strategySymbolPnlThresholdPct?: number;
	strategySymbolWinRateThresholdPct?: number;
	strategySymbolMaxConsecutiveLosses?: number;
	strategySymbolRecoveryConsecutiveWins?: number;
	strategySymbolRecoveryPnlThresholdPct?: number;
	strategySymbolCooldownAfterPenaltySeconds?: number;
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
	created_at: string;
	plan: "free" | "standard" | "pro";
	referralCode?: string;
	role: "admin" | "user" | "affiliate";
	xp: number;
	level: number;
}

export interface QuotaStatus {
	name: string;
	used: number;
	limit: number;
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

export interface Plan {
	key: string;
	name: string;
	price_usd: number;
	active: boolean;
	description: string;
	features: string[];
}

export interface CreatePaymentResponse {
	invoice_url: string;
}

export interface PaperWalletData {
	asset: string;
	balance: number;
}

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
	} | null;
	config_json: {
		name: string;
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

export interface AdminUser extends User {
	isActive: boolean;
	role: "admin" | "user" | "affiliate";
	affiliateCommissionRate?: number;
	stats?: {
		referral_count: number;
		paying_referral_count: number;
		total_earnings: number;
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
	recentTasks: unknown[];
	paperWallets: PaperWalletData[];
	bonuses: unknown[];
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
	foundation_id: string;
	count: number;
	avg_win_rate_contribution: number;
	total_gross_profit: number;
	total_gross_loss: number;
	profit_factor: number;
}

export interface MarketSentimentStat {
	direction: string;
	total_pnl: number;
}

export interface SystemMetrics {
	average_response_time_ms: number;
	uptime_30_days_percent: number;
	total_requests_24h: number;
	error_rate_24h: number;
}

export interface AdminAffiliateCommission {
	id: string;
	createdAt: string;
	amount: number;
	referralId: number;
	status: "pending" | "paid" | "cancelled";
}

export interface AdminAffiliateReferral {
	id: number;
	username: string;
	email: string;
	registeredAt: string;
	plan: string;
}

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
	rank: number;
	score: number;
	user: {
		id: number;
		username: string;
	};
	category: string;
	period: string;
	meta_data: {
		pnl: number;
		win_rate: number;
		trades: number;
		symbol: string;
	};
}

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
	achievement: Achievement;
}

export type RarityTier = "COMMON" | "RARE" | "EPIC" | "LEGENDARY";

export interface SymbolSelectionConfig {
	mode: "STATIC" | "DYNAMIC_NATR";
	min_natr?: number;
	max_concurrent_symbols: number;
}

export interface Token {
	access_token: string;
	token_type: string;
}

export interface PortfolioStatus {
	balance: number;
	today_pnl: number;
	is_trading_allowed: boolean;
	consecutive_losses: number;
	timestamp_utc: string;
}

export interface Position {
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
	stop_loss?: number | null;
	take_profit?: number | null;
}

export interface StrategyConfigDB {
	id: string;
	name: string;
	description?: string;
	config_data: StrategyConfigData;
	symbol_selection_mode?: "DYNAMIC" | "STATIC";
	symbols?: string[] | null;
	mode?: "live" | "paper";
	foundationWeights?: Record<string, number> | null;
	created_at: string;
	updated_at: string;
}

export interface RunningStrategy {
	id: string;
	strategy_name: string;
	symbol: string;
	market_type: string;
	status: "running";
	pnl: number;
	open_positions: number;
	started_at: string;
	params: Record<string, unknown>;
}

export interface BacktestRun {
	id: string;
	task_id: string;
	strategy_name: string;
	symbol: string;
	status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
	created_at: string;
	completed_at?: string | null;
	start_date: string;
	end_date: string;
	initial_balance: number;
	parameters_json: Record<string, unknown>;
	kpi_results_json: BacktestKpiResults | null;
	equity_curve_json: [string, number][] | null;
	trades: Trade[];
}

export interface BacktestRunListItem {
	id: string;
	task_id: string;
	strategy_name: string;
	symbol: string;
	status: string;
	created_at: string;
	completed_at?: string | null;
	pnl?: number | null;
	win_rate?: number | null;
}

export interface Trade {
	id: number;
	side: "LONG" | "SHORT";
	entry_price: number;
	exit_price: number;
	pnl: number;
	pnl_percent: number;
	entry_time: string;
	exit_time: string;
}
