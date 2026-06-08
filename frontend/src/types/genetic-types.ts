// src/types/genetic-types.ts

export interface GeneticAsset {
	id: string;
	name: string;
	type: "CRYPTO" | "STOCK" | "FOREX";
}

export interface IndicatorConfig {
	id: string;
	name: string;
	active: boolean;
	minPeriod: number;
	maxPeriod: number;
	timeframes: string[];
}

export interface FitnessWeights {
	pnl: number;
	drawdown: number;
	consistency: number;
}

export interface EvolutionState {
	isRunning: boolean;
	progress: number;
	generation: number;
	bestFitness: number;
	avgFitness: number;
	logs: string[];
	population: unknown[];
}

export interface Strategy {
	id: string;
	dna: string;
	fitness: number;
	pnl: number;
	drawdown: number;
	trades: number;
	sharpe: number;
	winRate: number;
	logic: string;
	history: unknown[];
	strategy_json?: Record<string, unknown>; // For loading into editor
}

export const INITIAL_ASSETS: GeneticAsset[] = [
	{ id: "BTCUSDT", name: "Bitcoin", type: "CRYPTO" },
	{ id: "ETHUSDT", name: "Ethereum", type: "CRYPTO" },
	{ id: "SOLUSDT", name: "Solana", type: "CRYPTO" },
	{ id: "BNBUSDT", name: "Binance Coin", type: "CRYPTO" },
	{ id: "XRPUSDT", name: "Ripple", type: "CRYPTO" },
	{ id: "ADAUSDT", name: "Cardano", type: "CRYPTO" },
];

export const INITIAL_INDICATORS: IndicatorConfig[] = [
	{
		id: "rsi",
		name: "RSI (Relative Strength Index)",
		active: true,
		minPeriod: 10,
		maxPeriod: 24,
		timeframes: ["15m", "1h"],
	},
	{
		id: "macd",
		name: "MACD (Moving Avg Conv Div)",
		active: true,
		minPeriod: 12,
		maxPeriod: 26,
		timeframes: ["1h", "4h"],
	},
	{
		id: "bb",
		name: "Bollinger Bands",
		active: true,
		minPeriod: 20,
		maxPeriod: 20,
		timeframes: ["15m"],
	},
	{
		id: "adx",
		name: "ADX (Trend Strength)",
		active: true,
		minPeriod: 14,
		maxPeriod: 30,
		timeframes: ["1h"],
	},
	{
		id: "ema_cross",
		name: "EMA Crossover",
		active: true,
		minPeriod: 9,
		maxPeriod: 200,
		timeframes: ["5m", "15m"],
	},
];

export const MOCK_LOGS = [
	"System: Genetic Engine initialized.",
	"System: Loaded 14,500 candles for BTCUSDT.",
	"System: Gene Pool size: 100 individuals.",
	"Evolution: Starting Gen 1...",
	"Evolution: Gen 1 completed. Best Fitness: 42.5",
	"Evolution: Starting Gen 2...",
	"Evolution: Gen 2 completed. Best Fitness: 48.9",
];

// === GENE POOL CONFIGURATION TYPES ===

export type RangeConfig = [number, number]; // [min, max]

// --- FILTERS ---
export interface FilterConfig {
	active: boolean;
	timeframes: string[];
}

export interface TrendFilterConfig extends FilterConfig {
	threshold: RangeConfig;
}

export interface VolatilityFilterConfig extends FilterConfig {
	operator: string[];
	value: RangeConfig;
}

export interface NATRFilterConfig extends FilterConfig {
	period: number[];
	operator: string[];
	value: RangeConfig;
}

export interface ADXFilterConfig extends FilterConfig {
	period: RangeConfig;
	threshold: RangeConfig;
	operator: string[];
}

export interface TimeFilterConfig {
	active: boolean;
	startHourUTC: RangeConfig;
	endHourUTC: RangeConfig;
	mode: string[];
}

export interface RelVolFilterConfig extends FilterConfig {
	rel_vol_threshold: RangeConfig;
	lookback_period: RangeConfig;
}

export interface MarketActivityConfig extends FilterConfig {
	mode: string[];
	natr_threshold: RangeConfig;
	rel_vol_threshold: RangeConfig;
}

export interface TradingSessionConfig extends FilterConfig {
	filter_mode: string[];
	session: string[];
	start_hour_utc: RangeConfig;
	end_hour_utc: RangeConfig;
	mode: string[];
}

export interface BTCStateFilterConfig extends FilterConfig {
	required_state: string[];
	consolidation_threshold: RangeConfig;
}

export interface CorrelationConfig extends FilterConfig {
	lookback: RangeConfig;
	operator: string[];
	value: RangeConfig;
}

export interface FiltersConfig {
	trend_filter: TrendFilterConfig;
	volatility_filter: VolatilityFilterConfig;
	natr_filter: NATRFilterConfig;
	adx_filter: ADXFilterConfig;
	time_filter: TimeFilterConfig;
	rel_vol_filter: RelVolFilterConfig;
	market_activity: MarketActivityConfig;
	trading_session: TradingSessionConfig;
	btc_state_filter: BTCStateFilterConfig;
	correlation: CorrelationConfig;
}

// --- CONDITIONS (Building Blocks) ---
export interface ConditionConfig {
	active: boolean;
	timeframes: string[];
}

export interface RSIConditionConfig extends ConditionConfig {
	period: RangeConfig;
	operator: string[];
	value: RangeConfig;
}

export interface MACrossConditionConfig extends ConditionConfig {
	fastPeriod: RangeConfig;
	slowPeriod: RangeConfig;
}

export interface MACDConditionConfig extends ConditionConfig {
	fastPeriod: RangeConfig;
	slowPeriod: RangeConfig;
	signalPeriod: RangeConfig;
	conditionType: string[];
	value: RangeConfig;
}

export interface BBConditionConfig extends ConditionConfig {
	period: RangeConfig;
	stdDev: RangeConfig;
	checkType: string[];
	widthValue: RangeConfig;
}

export interface StochConditionConfig extends ConditionConfig {
	kPeriod: RangeConfig;
	dPeriod: RangeConfig;
	smoothK: RangeConfig;
	value: RangeConfig;
	operator: string[];
	line: string[];
}

export interface ValueComparisonConfig extends ConditionConfig {
	leftOperand: string[];
	rightOperand: string[];
	operator: string[];
}

export interface ClassicPatternConfig extends ConditionConfig {
	patternName: string[];
}

export interface LocalLevelConfig extends ConditionConfig {
	lookbackPeriod: RangeConfig;
	proximityValue: RangeConfig;
}

export interface PriceConsolidationConfig extends ConditionConfig {
	lookbackPeriod: RangeConfig;
	maxRangeATR: RangeConfig;
}

export interface VolumeConfirmationConfig extends ConditionConfig {
	lookbackPeriod: RangeConfig;
	multiplier: RangeConfig;
}

export interface TrendDirectionConfig extends ConditionConfig {
	smaFastPeriod: RangeConfig;
	smaSlowPeriod: RangeConfig;
	rsiPeriod: RangeConfig;
	rsiLowerBound: RangeConfig;
	rsiUpperBound: RangeConfig;
	direction: string[];
}

export interface OpenInterestConfig extends ConditionConfig {
	lookback: RangeConfig;
	analyze: string[];
	operator: string[];
	value: RangeConfig;
}

export interface TapeConditionConfig extends ConditionConfig {
	metric: string[];
	window_sec: number[];
	operator: string[];
	threshold: RangeConfig;
	avg_lookback_sec: number[];
}

export interface VolatilitySqueezeConfig extends ConditionConfig {
	lookback_candles: RangeConfig;
	squeeze_ratio: RangeConfig;
}

export interface RoundLevelConfig extends ConditionConfig {
	proximity_type: string[];
	proximity_value: RangeConfig;
}

export interface SignificantLevelConfig extends ConditionConfig {
	level_type: string[];
	proximity_type: string[];
	proximity_value: RangeConfig;
}

export interface PriceActionAnalyzerConfig extends ConditionConfig {
	lookback_candles: RangeConfig;
	order: RangeConfig;
	min_points: RangeConfig;
	structure_type: string[];
	required_structure: string[];
}

export interface ConditionsConfig {
	rsi_condition: RSIConditionConfig;
	ma_cross_condition: MACrossConditionConfig;
	macd_condition: MACDConditionConfig;
	bb_condition: BBConditionConfig;
	stoch_condition: StochConditionConfig;
	value_comparison: ValueComparisonConfig;
	classic_pattern: ClassicPatternConfig;
	local_level: LocalLevelConfig;
	price_consolidation: PriceConsolidationConfig;
	volume_confirmation: VolumeConfirmationConfig;
	trend_direction: TrendDirectionConfig;
	open_interest: OpenInterestConfig;
	tape_condition: TapeConditionConfig;
	volatility_squeeze: VolatilitySqueezeConfig;
	round_level: RoundLevelConfig;
	significant_level: SignificantLevelConfig;
	price_action_analyzer: PriceActionAnalyzerConfig;
}

// --- INITIALIZATION (Entry/Exit) ---
export interface InitializationConfig {
	direction: string[];
	slType: string[];
	slValueATR: RangeConfig;
	tpType: string[];
	tpValueRR: RangeConfig;
	moveSLtoBEonFirstTP: boolean;
	maxHoldCandles: number;
	maxPartialExits: number;
	partialTPValueRR: RangeConfig;
	partialSizePct: RangeConfig;
}

// --- COMPLETE GENE POOL CONFIG (Filters + Conditions only, Entry/Exit is in ExecutionRiskModule) ---
export interface GenePoolConfig {
	filters: FiltersConfig;
	conditions: ConditionsConfig;
}

// --- DEFAULT VALUES (All blocks active to match backend GENE_POOL) ---
export const DEFAULT_FILTERS_CONFIG: FiltersConfig = {
	trend_filter: { active: true, threshold: [10, 100], timeframes: ["1h"] },
	volatility_filter: {
		active: true,
		operator: ["gt"],
		value: [0.005, 0.03],
		timeframes: ["1m", "5m", "15m"],
	},
	natr_filter: {
		active: true,
		period: [30],
		operator: ["gt"],
		value: [0.2, 5.0],
		timeframes: ["1m", "5m", "15m"],
	},
	adx_filter: {
		active: true,
		period: [7, 14],
		threshold: [15, 25],
		operator: ["gt"],
		timeframes: ["15m", "1h"],
	},
	time_filter: {
		active: true,
		startHourUTC: [0, 23],
		endHourUTC: [0, 23],
		mode: ["include", "exclude"],
	},
	rel_vol_filter: {
		active: false,
		rel_vol_threshold: [1.0, 3.0],
		lookback_period: [10, 50],
		timeframes: ["1m", "5m", "15m"],
	},
	market_activity: {
		active: false,
		mode: ["percentile", "relative"],
		natr_threshold: [0.5, 3.0],
		rel_vol_threshold: [1.0, 3.0],
		timeframes: ["1m", "5m", "15m"],
	},
	trading_session: {
		active: false,
		filter_mode: ["session", "hours"],
		session: ["london", "new_york", "asia", "sydney"],
		start_hour_utc: [0, 23],
		end_hour_utc: [0, 23],
		mode: ["include", "exclude"],
		timeframes: ["1m", "5m"],
	},
	btc_state_filter: {
		active: false,
		required_state: ["Trending Up", "Trending Down", "Consolidation"],
		consolidation_threshold: [0.5, 2.5],
		timeframes: ["1m"],
	},
	correlation: {
		active: false,
		lookback: [20, 100],
		operator: ["lt", "gt"],
		value: [-0.9, 0.9],
		timeframes: ["1m"],
	},
};

export const DEFAULT_CONDITIONS_CONFIG: ConditionsConfig = {
	rsi_condition: {
		active: true,
		period: [5, 14],
		operator: ["gt", "lt"],
		value: [25, 75],
		timeframes: ["1m", "5m", "15m", "1h"],
	},
	ma_cross_condition: {
		active: true,
		fastPeriod: [3, 20],
		slowPeriod: [21, 50],
		timeframes: ["1m", "5m", "15m"],
	},
	macd_condition: {
		active: true,
		fastPeriod: [6, 26],
		slowPeriod: [12, 52],
		signalPeriod: [5, 18],
		conditionType: ["crossover", "value_above", "value_below"],
		value: [0.0, 0.01],
		timeframes: ["5m", "15m", "1h"],
	},
	bb_condition: {
		active: true,
		period: [14, 20],
		stdDev: [2.0, 2.5],
		checkType: ["price_above_upper", "price_below_lower", "width_gt"],
		widthValue: [0.002, 0.02],
		timeframes: ["1m", "5m", "15m"],
	},
	stoch_condition: {
		active: true,
		kPeriod: [5, 21],
		dPeriod: [3, 9],
		smoothK: [3, 9],
		value: [20, 80],
		operator: ["cross_above", "cross_below", "gt", "lt"],
		line: ["k", "d"],
		timeframes: ["1m", "5m", "15m"],
	},
	value_comparison: {
		active: true,
		leftOperand: ["close", "EMA_20"],
		rightOperand: ["EMA_50"],
		operator: ["gt", "lt", "cross_above", "cross_below"],
		timeframes: ["1m", "5m", "15m", "1h"],
	},
	classic_pattern: {
		active: true,
		patternName: ["bullish_engulfing", "bearish_engulfing", "pin_bar", "doji"],
		timeframes: ["1m", "5m", "15m"],
	},
	local_level: {
		active: true,
		lookbackPeriod: [10, 100],
		proximityValue: [0.1, 1.0],
		timeframes: ["5m", "15m", "1h"],
	},
	price_consolidation: {
		active: true,
		lookbackPeriod: [10, 100],
		maxRangeATR: [0.5, 2.0],
		timeframes: ["5m", "15m", "1h"],
	},
	volume_confirmation: {
		active: true,
		lookbackPeriod: [10, 50],
		multiplier: [1.5, 3.0],
		timeframes: ["1m", "5m"],
	},
	trend_direction: {
		active: true,
		smaFastPeriod: [10, 50],
		smaSlowPeriod: [51, 200],
		rsiPeriod: [7, 28],
		rsiLowerBound: [20, 45],
		rsiUpperBound: [55, 80],
		direction: ["long", "short"],
		timeframes: ["1h"],
	},
	open_interest: {
		active: false,
		lookback: [3, 20],
		analyze: ["change_pct", "absolute_value"],
		operator: ["gt", "lt"],
		value: [0.1, 5.0],
		timeframes: ["1m", "5m"],
	},
	tape_condition: {
		active: false,
		metric: [
			"delta_volume",
			"delta_count",
			"ratio_volume",
			"ratio_count",
			"accel_volume",
			"accel_count",
			"total_volume",
			"total_count",
		],
		window_sec: [5, 10, 30],
		operator: ["gt", "lt"],
		threshold: [0.1, 10.0],
		avg_lookback_sec: [60, 120],
		timeframes: ["1m"],
	},
	volatility_squeeze: {
		active: false,
		lookback_candles: [10, 50],
		squeeze_ratio: [0.3, 0.8],
		timeframes: ["1m", "5m", "15m", "1h"],
	},
	round_level: {
		active: false,
		proximity_type: ["pips", "percentage"],
		proximity_value: [1.0, 10.0],
		timeframes: ["1m", "5m", "15m"],
	},
	significant_level: {
		active: false,
		level_type: ["daily_high", "daily_low", "weekly_high", "weekly_low"],
		proximity_type: ["atr_multiplier", "percentage"],
		proximity_value: [0.1, 1.0],
		timeframes: ["1m", "5m", "15m", "1h"],
	},
	price_action_analyzer: {
		active: false,
		lookback_candles: [10, 60],
		order: [2, 5],
		min_points: [2, 4],
		structure_type: ["higher_lows", "lower_highs"],
		required_structure: ["HH_HL", "LH_LL"],
		timeframes: ["5m", "15m", "1h"],
	},
};

export const DEFAULT_GENE_POOL_CONFIG: GenePoolConfig = {
	filters: DEFAULT_FILTERS_CONFIG,
	conditions: DEFAULT_CONDITIONS_CONFIG,
};

// Available timeframes for UI
export const AVAILABLE_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"];

// === DNA ARCHITECTURE TYPES ===
export interface DNAArchitectureConfig {
	indicators: IndicatorConfig[];
	logicTreeDepth: number;
	correlationLimit: number;
	signalPruning: boolean;
	outlierRejection: boolean;
	diversityPenalty: boolean;
	genePool: GenePoolConfig;
}

export const DEFAULT_DNA_CONFIG: DNAArchitectureConfig = {
	indicators: INITIAL_INDICATORS,
	logicTreeDepth: 3,
	correlationLimit: 0.7,
	signalPruning: true,
	outlierRejection: false,
	diversityPenalty: true,
	genePool: DEFAULT_GENE_POOL_CONFIG,
};

// === EXECUTION RISK TYPES ===
export interface PartialTPRange {
	id: number;
	sizePctRange: [number, number]; // [min %, max %]
	targetRRRange: [number, number]; // [min RR, max RR]
}

export interface ExecutionRiskConfig {
	slRange: [number, number]; // [min ATR, max ATR]
	tpRange: [number, number]; // [min RR, max RR]
	trailingActivationRR: number;
	strictTrailing: boolean;
	breakevenEnabled: boolean;
	breakevenTriggerRRRange: [number, number]; // [min RR, max RR]
	breakevenBufferATRRange: [number, number]; // [min ATR, max ATR]
	partialTPs: PartialTPRange[];
	timeStopCandlesRange: [number, number]; // [min, max candles]
}

export const DEFAULT_EXECUTION_CONFIG: ExecutionRiskConfig = {
	slRange: [1.5, 5.0],
	tpRange: [2.0, 8.0],
	trailingActivationRR: 1.5,
	strictTrailing: true,
	breakevenEnabled: true,
	breakevenTriggerRRRange: [0.5, 1.5],
	breakevenBufferATRRange: [0.02, 0.1],
	partialTPs: [{ id: 1, sizePctRange: [30, 50], targetRRRange: [1.5, 3.0] }],
	timeStopCandlesRange: [144, 576],
};

// === FITNESS LAB TYPES ===
export interface FitnessLabConfig {
	weights: FitnessWeights;
	killSwitches: {
		maxDD: number;
		minTrades: number;
	};
	evolution: {
		generations: number;
		populationSize: number;
	};
}

export const DEFAULT_FITNESS_CONFIG: FitnessLabConfig = {
	weights: { pnl: 40, drawdown: 30, consistency: 30 },
	killSwitches: { maxDD: 20, minTrades: 40 },
	evolution: { generations: 30, populationSize: 100 },
};

// === SEED STRATEGY TYPES ===
export interface SeedConfig {
	mode: "random" | "previous_run" | "upload";
	runId?: string;
	strategies?: object[];
	topN: number;
	keepStructure: boolean;
}

export const DEFAULT_SEED_CONFIG: SeedConfig = {
	mode: "random",
	topN: 10,
	keepStructure: false,
};

// === UNIVERSE DATA TYPES ===
export interface UniverseDataConfig {
	assets: string[];
	trainSplitPct: number;
	tradingFee: number;
	slippage: number;
	initialCapital: number;
}

export const DEFAULT_UNIVERSE_CONFIG: UniverseDataConfig = {
	assets: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"],
	trainSplitPct: 70,
	tradingFee: 0.0004,
	slippage: 0.0001,
	initialCapital: 10000,
};
