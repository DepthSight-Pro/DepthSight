export interface PartialTakeProfitConfig {
	use_limit_orders: boolean;
	ptp1_enabled: boolean;
	ptp1_rr: number;
	ptp1_percent: number;
	ptp2_enabled: boolean;
	ptp2_rr: number;
	ptp2_percent: number;
	ptp3_enabled: boolean;
	ptp3_rr: number;
	ptp3_percent: number;
	ptp4_enabled: boolean;
	ptp4_rr: number;
	ptp4_percent: number;
}

export interface HftConfig {
	entry_threshold: number;
	max_position_size_usd: number;
	sl_type: "PERCENT" | "ATR" | "VOLATILITY";
	sl_val: number;
	min_sl_percent?: number; // Minimum SL distance matching Config
	stop_loss_cooldown_seconds?: number;
	tp_type: "PERCENT" | "ATR" | "RR" | "VOLATILITY";
	tp_val: number;
	partial_tp: PartialTakeProfitConfig;
	be_enabled: boolean;
	be_type: "PERCENT" | "RR";
	be_threshold: number;
	be_offset_pct?: number; // Break-even offset to cover fees (e.g. 0.1%)
	trailing_stop_enabled: boolean;
	risk_per_trade_pct: number;
	max_leverage: number;
	max_hold_minutes: number;
	use_screener: boolean;
	use_oracle: boolean;
	max_analyzed_symbols: number;
	max_concurrent_trades: number;
	use_risk_size: boolean;
	use_maker_mode?: boolean; // Limit entry mode (lower fees, 2s timeout)
	min_volume_24h?: number; // 24h Volume Filter
	entry_slippage_limit?: number;
	liquidity_safety_factor?: number;
	max_spread_pct?: number;
	auto_exit_on_low_confidence?: boolean; // Exit if confidence drops
	exit_confidence_threshold?: number; // Threshold (e.g. 0.4)
	sl_trigger_type?: string; // "MARK" or "LAST"
	trade_on_close_only?: boolean; // If true, enter only when candle closes
	ignore_auto_blacklist_rules?: boolean; // If true, ignore auto blacklist rules (only manual blacklist applies)

	// Mock Screener (Manual Symbol Lists)
	mock_screener_enabled?: boolean;
	mock_screener_symbols?: string[];
}

export interface HftSystemStatus {
	active_bots: number;
	latency_ms: number;
	server_load_cpu: number;
	server_load_ram: number;
	components: {
		[key: string]: "ok" | "error" | "disconnected";
	};
	engine_active: boolean;
}

export interface HftEquityUpdate {
	balance: number;
	equity: number;
	unrealized_pnl: number;
	total_exposure: number;
	drawdown_pct: number;
	timestamp: number;
}

export interface OracleSymbol {
	symbol: string;
	regime_confidence: number;
	duration_in_regime_sec: number;
	volatility_natr: number;
	price_change_percent: number;
	confidence: number;
	volume_24h?: number; // Optional as older events might miss it
	timestamp: number;
}

export interface HftLogEvent {
	id: string;
	timestamp: number;
	type: "INFO" | "WARNING" | "ERROR" | "TRADE";
	message: string;
	symbol?: string;
	meta?: Record<string, unknown>;
}

export interface HftState {
	config: HftConfig | null;
	status: HftSystemStatus | null;
	equityHistory: HftEquityUpdate[];
	oracleSymbols: OracleSymbol[];
	logs: HftLogEvent[];
	isConnected: boolean;
	isEngineRunning: boolean;
	selectedApiKeyId: number | null;
}

// === Rust Bot Event Types (from protocol.rs) ===
// These match the HftEvent enum serialization from the Rust bot

export interface HftEventHeartbeat {
	type: "heartbeat";
	timestamp: number;
	active_bots: number;
	latency_ms: number;
	cpu_usage: number;
	ram_usage: number;
}

export interface HftEventBotStarted {
	type: "bot_started";
	bot_id: string;
	user_id: number;
}

export interface HftEventBotStopped {
	type: "bot_stopped";
	bot_id: string;
}

export interface HftEventSignal {
	type: "signal";
	bot_id: string;
	symbol: string;
	side: string;
	price: string;
	prob: number;
}

export interface HftEventTrade {
	type: "trade";
	bot_id: string;
	user_id: number;
	symbol: string;
	side: string;
	price: string;
	qty: string;
	leverage: number;
	realized_pnl: string;
}

export interface HftEventStatus {
	type: "status";
	bot_id: string;
	position_usd: string;
	pnl_usd: string;
}

export interface HftEventError {
	type: "error";
	bot_id: string;
	message: string;
}

export interface HftEventLogMessage {
	type: "log";
	bot_id: string;
	level: string;
	message: string;
}

export type HftBotEvent =
	| HftEventHeartbeat
	| HftEventBotStarted
	| HftEventBotStopped
	| HftEventSignal
	| HftEventTrade
	| HftEventStatus
	| HftEventError
	| HftEventLogMessage;
