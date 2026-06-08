// frontend/src/components/simulation/types.ts
// TypeScript types for simulation components

export interface Trade {
	id: string;
	asset: string;
	strategy: string;
	entryTime: number;
	exitTime: number;
	entryPrice: number;
	exitPrice: number;
	pnlPct: number;
	pnlAmount: number;
	status: "closed" | "open" | "skipped";
	reason?: string;
	slotIndex?: number;
}

export interface SimulationConfig {
	initialCapital: number;
	maxConcurrentPositions: number;
	baseRiskPct: number;
	leverage: number;
	adaptiveRisk: boolean;
	compounding: boolean;
}

export interface SimulationResult {
	equityCurve: { time: number; value: number; drawdown: number }[];
	trades: Trade[];
	stats: {
		totalPnl: number;
		totalPnlPct: number;
		winRate: number;
		profitFactor: number;
		sharpeRatio: number;
		maxDrawdown: number;
		skippedTrades: number;
		avgWin: number;
		avgLoss: number;
	};
}

export interface InspectorTrade {
	entryTime: number;
	exitTime: number;
	entryPrice: number;
	exitPrice: number;
	pnlPct: number;
}

// Phantom Trade — virtual trade after BE
export interface PhantomTrade {
	entryTime: number;
	beExitTime: number;
	entryPrice: number;
	initialSl: number;
	initialTp: number;
	beExitPrice: number;
	direction: string;
	phantomStatus: "TP_HIT" | "SL_HIT" | "TIMEOUT";
	phantomExitTime?: number;
	phantomExitPrice?: number | null;
	phantomPnlPct?: number | null;
	mfeAfterBe: number; // Maximum Favorable Excursion after BE (%)
	maeAfterBe: number; // Maximum Adverse Excursion after BE (%)
	candlesToResolution: number;
}

export interface InspectorCell {
	pnl_pct: number;
	win_rate: number;
	trades_count: number;
	sharpe: number;
	max_dd?: number;
	commission?: number;
	trades?: InspectorTrade[];
	phantomTrades?: PhantomTrade[]; // Phantom trades for BE analysis
}

export interface InspectorMatrixData {
	matrix: Record<string, Record<string, InspectorCell>>;
	assets: string[];
	variants: string[];
}

export interface StrategyVariant {
	id: string;
	name: string;
	description: string;
}

export interface AssetData {
	symbol: string;
	variants: Record<string, { pnl: number; winRate: number }>;
}

export type SimulationView =
	| "matrix"
	| "portfolio"
	| "deepdive"
	| "compare"
	| "beanalysis";

export const STRATEGY_VARIANTS: StrategyVariant[] = [
	{ id: "raw", name: "Raw", description: "Raw signals without filters" },
	{
		id: "oracle_entry",
		name: "Oracle Entry",
		description: "Oracle entry filter",
	},
	{
		id: "oracle_be",
		name: "Oracle BE",
		description: "BE on Oracle mode change",
	},
	{
		id: "oracle_be_time",
		name: "Oracle BE+Time",
		description: "BE + Time filter (14-07 UTC)",
	},
	{
		id: "oracle_partial",
		name: "Partial",
		description: "Partial exits 1.5R/2.5R",
	},
	{ id: "trailing_dev", name: "Trailing", description: "Trailing stop 1%" },
	{ id: "be_at_1rr", name: "BE at 1R", description: "BE on reaching 1R" },
	{ id: "hybrid_be", name: "Hybrid BE", description: "BE: Oracle OR 1R" },
	{
		id: "hybrid_be_time",
		name: "Hybrid+Time",
		description: "Hybrid + Time filter",
	},
];

// --- Custom Variant Builder Types ---

export const MAX_VARIANTS = 15; // Max ACTIVE variants (built-in + custom selected)

export interface PartialTP {
	triggerRR: number;
	closePercent: number;
}

export interface CustomVariant {
	id: string;
	name: string;
	color: string;
	isBuiltIn: boolean;

	oracle: {
		enabled: boolean;
		threshold: number;
		entryRegime: "amnesia" | "paranoia" | "any";
		onRegimeChange: "none" | "breakeven" | "close";
	};

	takeProfit: {
		partials: PartialTP[];
		finalTP_RR: number;
	};

	riskManagement: {
		breakeven: {
			mode: "disabled" | "at_rr" | "at_first_tp" | "by_oracle";
			triggerRR: number;
		};
		trailingStop: {
			enabled: boolean;
			trailPercent: number;
		};
		maxHoldCandles: number;
	};

	timeFilter: {
		enabled: boolean;
		startHourUTC: number;
		endHourUTC: number;
		mode: "include" | "exclude";
	};
}

// Default built-in variants as CustomVariant format - 9 distinct colors
export const VARIANT_COLORS = [
	"#EF4444", // Red
	"#06B6D4", // Cyan
	"#8B5CF6", // Purple
	"#10B981", // Emerald
	"#F59E0B", // Amber
	"#EC4899", // Pink
	"#6366F1", // Indigo
	"#84CC16", // Lime
	"#14B8A6", // Teal
];

export const BUILT_IN_VARIANTS: CustomVariant[] = [
	{
		id: "raw",
		name: "Raw",
		color: VARIANT_COLORS[0],
		isBuiltIn: true,
		oracle: {
			enabled: false,
			threshold: 0.95,
			entryRegime: "any",
			onRegimeChange: "none",
		},
		takeProfit: { partials: [], finalTP_RR: 2.0 },
		riskManagement: {
			breakeven: { mode: "disabled", triggerRR: 1.0 },
			trailingStop: { enabled: false, trailPercent: 0.01 },
			maxHoldCandles: 0,
		},
		timeFilter: {
			enabled: false,
			startHourUTC: 0,
			endHourUTC: 0,
			mode: "include",
		},
	},
	{
		id: "oracle_entry",
		name: "Oracle Entry",
		color: VARIANT_COLORS[1],
		isBuiltIn: true,
		oracle: {
			enabled: true,
			threshold: 0.95,
			entryRegime: "amnesia",
			onRegimeChange: "none",
		},
		takeProfit: { partials: [], finalTP_RR: 2.0 },
		riskManagement: {
			breakeven: { mode: "disabled", triggerRR: 1.0 },
			trailingStop: { enabled: false, trailPercent: 0.01 },
			maxHoldCandles: 0,
		},
		timeFilter: {
			enabled: false,
			startHourUTC: 0,
			endHourUTC: 0,
			mode: "include",
		},
	},
	{
		id: "oracle_be",
		name: "Oracle BE",
		color: VARIANT_COLORS[2],
		isBuiltIn: true,
		oracle: {
			enabled: true,
			threshold: 0.95,
			entryRegime: "amnesia",
			onRegimeChange: "breakeven",
		},
		takeProfit: { partials: [], finalTP_RR: 2.0 },
		riskManagement: {
			breakeven: { mode: "by_oracle", triggerRR: 1.0 },
			trailingStop: { enabled: false, trailPercent: 0.01 },
			maxHoldCandles: 0,
		},
		timeFilter: {
			enabled: false,
			startHourUTC: 0,
			endHourUTC: 0,
			mode: "include",
		},
	},
	{
		id: "hybrid_be",
		name: "Hybrid BE",
		color: VARIANT_COLORS[3],
		isBuiltIn: true,
		oracle: {
			enabled: true,
			threshold: 0.95,
			entryRegime: "amnesia",
			onRegimeChange: "breakeven",
		},
		takeProfit: { partials: [], finalTP_RR: 2.0 },
		riskManagement: {
			breakeven: { mode: "at_rr", triggerRR: 1.0 },
			trailingStop: { enabled: false, trailPercent: 0.01 },
			maxHoldCandles: 0,
		},
		timeFilter: {
			enabled: false,
			startHourUTC: 0,
			endHourUTC: 0,
			mode: "include",
		},
	},
	{
		id: "oracle_partial",
		name: "Partial",
		color: VARIANT_COLORS[4],
		isBuiltIn: true,
		oracle: {
			enabled: true,
			threshold: 0.95,
			entryRegime: "amnesia",
			onRegimeChange: "breakeven",
		},
		takeProfit: {
			partials: [
				{ triggerRR: 1.5, closePercent: 30 },
				{ triggerRR: 2.5, closePercent: 30 },
			],
			finalTP_RR: 4.0,
		},
		riskManagement: {
			breakeven: { mode: "at_first_tp", triggerRR: 1.0 },
			trailingStop: { enabled: false, trailPercent: 0.01 },
			maxHoldCandles: 0,
		},
		timeFilter: {
			enabled: false,
			startHourUTC: 0,
			endHourUTC: 0,
			mode: "include",
		},
	},
	{
		id: "trailing_dev",
		name: "Trailing",
		color: VARIANT_COLORS[5],
		isBuiltIn: true,
		oracle: {
			enabled: true,
			threshold: 0.95,
			entryRegime: "amnesia",
			onRegimeChange: "none",
		},
		takeProfit: { partials: [], finalTP_RR: 3.0 },
		riskManagement: {
			breakeven: { mode: "disabled", triggerRR: 1.0 },
			trailingStop: { enabled: true, trailPercent: 0.01 },
			maxHoldCandles: 0,
		},
		timeFilter: {
			enabled: false,
			startHourUTC: 0,
			endHourUTC: 0,
			mode: "include",
		},
	},
	{
		id: "be_at_1rr",
		name: "BE at 1R",
		color: VARIANT_COLORS[6],
		isBuiltIn: true,
		oracle: {
			enabled: false,
			threshold: 0.95,
			entryRegime: "any",
			onRegimeChange: "none",
		},
		takeProfit: { partials: [], finalTP_RR: 2.0 },
		riskManagement: {
			breakeven: { mode: "at_rr", triggerRR: 1.0 },
			trailingStop: { enabled: false, trailPercent: 0.01 },
			maxHoldCandles: 0,
		},
		timeFilter: {
			enabled: false,
			startHourUTC: 0,
			endHourUTC: 0,
			mode: "include",
		},
	},
	{
		id: "oracle_be_time",
		name: "Oracle+Time",
		color: VARIANT_COLORS[7],
		isBuiltIn: true,
		oracle: {
			enabled: true,
			threshold: 0.95,
			entryRegime: "amnesia",
			onRegimeChange: "breakeven",
		},
		takeProfit: { partials: [], finalTP_RR: 2.0 },
		riskManagement: {
			breakeven: { mode: "by_oracle", triggerRR: 1.0 },
			trailingStop: { enabled: false, trailPercent: 0.01 },
			maxHoldCandles: 0,
		},
		timeFilter: {
			enabled: true,
			startHourUTC: 14,
			endHourUTC: 7,
			mode: "include",
		},
	},
	{
		id: "hybrid_be_time",
		name: "Hybrid+Time",
		color: VARIANT_COLORS[8],
		isBuiltIn: true,
		oracle: {
			enabled: true,
			threshold: 0.95,
			entryRegime: "amnesia",
			onRegimeChange: "breakeven",
		},
		takeProfit: { partials: [], finalTP_RR: 2.0 },
		riskManagement: {
			breakeven: { mode: "at_rr", triggerRR: 2.0 },
			trailingStop: { enabled: false, trailPercent: 0.01 },
			maxHoldCandles: 0,
		},
		timeFilter: {
			enabled: true,
			startHourUTC: 14,
			endHourUTC: 7,
			mode: "include",
		},
	},
];

/**
 * Generate human-readable description for a CustomVariant
 */
export function generateVariantDescription(variant: CustomVariant): string {
	const parts: string[] = [];

	// Oracle
	if (variant.oracle.enabled) {
		parts.push("🔮 Oracle");
		if (variant.oracle.onRegimeChange === "breakeven") {
			parts.push("BE@mode");
		} else if (variant.oracle.onRegimeChange === "close") {
			parts.push("Close@mode");
		}
	} else {
		parts.push("📊 Raw");
	}

	// Take Profit
	if (variant.takeProfit.partials.length > 0) {
		parts.push(`${variant.takeProfit.partials.length}×TP`);
	} else {
		parts.push(`TP:${variant.takeProfit.finalTP_RR}R`);
	}

	// Breakeven
	const be = variant.riskManagement.breakeven;
	if (be.mode === "at_rr") {
		parts.push(`BE@${be.triggerRR}R`);
	} else if (be.mode === "at_first_tp") {
		parts.push("BE@TP1");
	} else if (be.mode === "by_oracle") {
		// Already handled above
	}

	// Trailing
	if (variant.riskManagement.trailingStop.enabled) {
		parts.push(
			`Trail:${(variant.riskManagement.trailingStop.trailPercent * 100).toFixed(1)}%`,
		);
	}

	// Time filter
	if (variant.timeFilter.enabled) {
		parts.push(
			`⏰ ${variant.timeFilter.startHourUTC}-${variant.timeFilter.endHourUTC}h`,
		);
	}

	// Max hold
	if (variant.riskManagement.maxHoldCandles > 0) {
		parts.push(`Max:${variant.riskManagement.maxHoldCandles}🕯️`);
	}

	return parts.join(" • ");
}

/**
 * Generate short badge-style tags for variant
 */
export function getVariantTags(variant: CustomVariant): string[] {
	const tags: string[] = [];

	if (variant.oracle.enabled) tags.push("🔮");
	if (variant.takeProfit.partials.length > 0)
		tags.push(`${variant.takeProfit.partials.length}TP`);
	if (variant.riskManagement.breakeven.mode !== "disabled") tags.push("BE");
	if (variant.riskManagement.trailingStop.enabled) tags.push("Trail");
	if (variant.timeFilter.enabled) tags.push("⏰");

	return tags;
}

// --- Shared Statistics Calculation ---

export interface VariantStats {
	id: string;
	name: string;
	color: string;
	totalPnl: number; // $ amount
	totalPnlPct: number; // Sum of compound PnL per asset (%)
	portfolioROI: number; // Real ROI based on full portfolio
	winRate: number; // Average WR across assets (%)
	profitFactor: number;
	sharpeRatio: number;
	maxDrawdown: number; // Average of Individual Asset Max Drawdowns (positive value)
	avgWin: number; // in %
	avgLoss: number; // in %
	skippedTrades: number;
	tradesCount: number;
	assetsCount: number;
	equityCurve: { time: number; value: number; drawdown: number }[];
	trades?: Trade[];
}

/**
 * Shared function to calculate variant statistics from Inspector matrix
 * Metric Logic:
 * - Total PnL % = SUM of (Compound PnL % of each asset)
 * - Win Rate = AVERAGE of (Win Rate of each asset)
 * - Max Drawdown = AVERAGE of (Max Drawdown of each asset)
 * - Equity Curve = SUM of (Cumulative PnL % curve of each asset) at each time point
 */
export function calculateVariantStatsFromInspector(
	matrix: Record<string, Record<string, InspectorCell>>,
	variantId: string,
	variantName: string,
	variantColor: string,
	initialCapital: number,
): VariantStats | null {
	// Group trades by asset
	const tradesByAsset: Record<string, InspectorTrade[]> = {};
	const allTrades: (InspectorTrade & { asset: string })[] = [];

	Object.entries(matrix).forEach(([asset, variants]) => {
		const cell = variants[variantId];
		if (cell?.trades && Array.isArray(cell.trades)) {
			tradesByAsset[asset] = cell.trades;
			cell.trades.forEach((trade) => {
				allTrades.push({ ...trade, asset });
			});
		}
	});

	if (allTrades.length === 0) return null;

	// --- Per-Asset Metrics Calculation ---
	// Collect metrics DIRECTLY from cells to match Matrix Summary exactly
	const cellPnls: number[] = [];
	const cellWrs: number[] = [];
	const cellMaxDDs: number[] = [];

	// Re-iterate matrix to collect scalar stats consistently
	Object.values(matrix).forEach((variants) => {
		const cell = variants[variantId];
		if (cell && cell.trades_count > 0) {
			cellPnls.push(cell.pnl_pct);
			cellWrs.push(cell.win_rate);
			if (cell.max_dd && cell.max_dd > 0) {
				cellMaxDDs.push(cell.max_dd);
			}
		}
	});

	// Calculate Aggregated Metrics from CELLS (Single Source of Truth)
	const totalPnlPct = cellPnls.reduce((sum, pnl) => sum + pnl, 0);

	const avgWinRate =
		cellWrs.length > 0
			? cellWrs.reduce((sum, wr) => sum + wr, 0) / cellWrs.length
			: 0;

	// IMPORTANT: Filter out 0-drawdowns identical to InspectorMatrix.tsx
	const avgMaxDrawdown =
		cellMaxDDs.length > 0
			? cellMaxDDs.reduce((sum, dd) => sum + dd, 0) / cellMaxDDs.length
			: 0;

	// --- Equity Curve Construction (still needs trades) ---
	const assetCurves: Record<string, { time: number; val: number }[]> = {};

	Object.entries(tradesByAsset).forEach(([asset, trades]) => {
		if (trades.length === 0) return;

		// Sort trades by exit time
		const sortedTrades = [...trades].sort(
			(a, b) =>
				(a.exitTime || a.entryTime || 0) - (b.exitTime || b.entryTime || 0),
		);

		// 1. Calculate Asset Cumulative Curve & PnL
		let equity = 1;
		let maxEquity = 1;
		let localMaxDD = 0;

		const curvePoints: { time: number; val: number }[] = [];
		// Add start point
		const startTime =
			sortedTrades[0].entryTime || sortedTrades[0].exitTime || 0;
		curvePoints.push({ time: startTime - 1, val: 0 });

		sortedTrades.forEach((t) => {
			equity *= 1 + (t.pnlPct || 0);

			// Track Max DD for this asset
			if (equity > maxEquity) maxEquity = equity;
			const dd = maxEquity > 0 ? ((maxEquity - equity) / maxEquity) * 100 : 0;
			if (dd > localMaxDD) localMaxDD = dd;

			const pnlPctAccumulated = (equity - 1) * 100;
			curvePoints.push({
				time: t.exitTime || t.entryTime || 0,
				val: pnlPctAccumulated,
			});
		});

		assetCurves[asset] = curvePoints;
		// 2. Asset Metrics for Curve Construction ONLY (Scalars used from Cell above)
		// We only need the curve points here
	});

	// --- Combined Equity Curve (Sum of Asset Curves) ---
	// Collect all unique timestamps
	const allTimes = new Set<number>();
	allTrades.forEach((t) => {
		allTimes.add(t.exitTime || t.entryTime || 0);
	});
	// Add start times from asset curves just in case
	Object.values(assetCurves).forEach((c) => {
		c.forEach((p) => {
			allTimes.add(p.time);
		});
	});

	const sortedTimes = Array.from(allTimes).sort((a, b) => a - b);

	// Build summed curve
	let globalPeak = 0; // Since we are summing PnL %, start is 0
	const equityCurve = sortedTimes.map((time) => {
		let currentTotalPnlPct = 0;

		// Sum value from each asset at this timestamp
		Object.values(assetCurves).forEach((curve) => {
			// Find last point <= time
			// Naive search is O(N), acceptable for <1000 points.
			// For optimization, we could maintain indices, but let's keep it simple first.
			const point = curve.reduce(
				(prev, curr) => (curr.time <= time ? curr : prev),
				{ time: 0, val: 0 },
			);
			currentTotalPnlPct += point.val;
		});

		// Let's make "Value" = InitialCapital * (1 + currentTotalPnlPct / 100)
		const implicitCapital = initialCapital * (1 + currentTotalPnlPct / 100);

		// Initialization:
		if (time === sortedTimes[0])
			globalPeak = Math.max(initialCapital, implicitCapital); // Init
		else if (implicitCapital > globalPeak) globalPeak = implicitCapital;

		const curveDrawdown =
			globalPeak > 0 ? ((globalPeak - implicitCapital) / globalPeak) * 100 : 0;

		return {
			time,
			value: Math.round(implicitCapital * 100) / 100,
			drawdown: Math.round(curveDrawdown * 100) / 100,
		};
	});

	// --- Other Stats ---
	const sortedAllTrades = [...allTrades].sort(
		(a, b) =>
			(a.exitTime || a.entryTime || 0) - (b.exitTime || b.entryTime || 0),
	);

	const winningTrades = sortedAllTrades.filter((t) => (t.pnlPct || 0) > 0);
	const losingTrades = sortedAllTrades.filter((t) => (t.pnlPct || 0) < 0);

	// Profit factor
	const totalGains = winningTrades.reduce(
		(sum, t) => sum + Math.abs(t.pnlPct || 0),
		0,
	);
	const totalLosses = losingTrades.reduce(
		(sum, t) => sum + Math.abs(t.pnlPct || 0),
		0,
	);
	const profitFactor =
		totalLosses > 0 ? totalGains / totalLosses : totalGains > 0 ? Infinity : 0;

	// Avg win/loss
	const avgWin =
		winningTrades.length > 0
			? (winningTrades.reduce((sum, t) => sum + Math.abs(t.pnlPct || 0), 0) /
					winningTrades.length) *
				100
			: 0;
	const avgLoss =
		losingTrades.length > 0
			? (losingTrades.reduce((sum, t) => sum + Math.abs(t.pnlPct || 0), 0) /
					losingTrades.length) *
				100
			: 0;

	// Sharpe (Calculation remains on trade stream as approximation)
	const returns = sortedAllTrades.map((t) => t.pnlPct || 0);
	let sharpeRatio = 0;
	if (returns.length > 1) {
		const meanReturn = returns.reduce((a, b) => a + b, 0) / returns.length;
		const stdDev = Math.sqrt(
			returns.reduce((sum, r) => sum + (r - meanReturn) ** 2, 0) /
				returns.length,
		);
		sharpeRatio =
			stdDev > 0.0001 ? (meanReturn / stdDev) * Math.sqrt(returns.length) : 0;
	}

	const assetsCount = Object.keys(matrix).length;
	const totalPnl = (totalPnlPct / 100) * initialCapital;
	const fullPortfolioDeposit = assetsCount * initialCapital;
	const portfolioROI =
		fullPortfolioDeposit > 0 ? (totalPnl / fullPortfolioDeposit) * 100 : 0;

	return {
		id: variantId,
		name: variantName,
		color: variantColor,
		totalPnl,
		totalPnlPct,
		portfolioROI,
		winRate: avgWinRate,
		profitFactor,
		sharpeRatio,
		maxDrawdown: -avgMaxDrawdown, // Used Avg Asset DD as requested
		avgWin,
		avgLoss,
		skippedTrades: 0,
		tradesCount: sortedAllTrades.length,
		assetsCount,
		equityCurve,
	};
}

/**
 * Shared function to calculate variant statistics from Simulator trades
 * UPDATED: Uses SequentialSimulator for correct portfolio simulation (time-based, capital constraints)
 */
import { SequentialSimulator } from "./SequentialSimulator";

export function calculateVariantStatsFromSimulator(
	trades: Trade[],
	variantId: string,
	variantName: string,
	variantColor: string,
	// Accept full config or fallbacks
	userConfig: SimulationConfig,
): VariantStats | null {
	// Filter trades for this variant
	const variantTrades = trades.filter(
		(trade) =>
			trade.strategy === variantId ||
			("variant" in trade &&
				(trade as Trade & { variant: string }).variant === variantId),
	);

	if (variantTrades.length === 0) return null;

	// Use passed config
	const simConfig: SimulationConfig = {
		initialCapital: userConfig.initialCapital || 10000,
		maxConcurrentPositions: userConfig.maxConcurrentPositions || 5,
		baseRiskPct: userConfig.baseRiskPct || 1.0,
		leverage: userConfig.leverage || 1.0,
		adaptiveRisk: userConfig.adaptiveRisk ?? true,
		compounding: userConfig.compounding ?? true,
	};

	const simulator = new SequentialSimulator(simConfig);
	const result = simulator.simulate(variantTrades);

	const { stats, equityCurve, trades: simulatedTrades } = result;

	// We need to count assets involved
	const uniqueAssets = new Set(variantTrades.map((t) => t.asset)).size;

	// Return in VariantStats format
	return {
		id: variantId,
		name: variantName,
		color: variantColor,
		totalPnl: stats.totalPnl,
		totalPnlPct: stats.totalPnlPct,
		portfolioROI: stats.totalPnlPct, // ROI is same as PnL% here
		winRate: stats.winRate,
		profitFactor: stats.profitFactor,
		sharpeRatio: stats.sharpeRatio,
		maxDrawdown: stats.maxDrawdown,
		avgWin: stats.avgWin,
		avgLoss: stats.avgLoss,
		skippedTrades: stats.skippedTrades,
		tradesCount: simulatedTrades.length,
		assetsCount: uniqueAssets,
		equityCurve: equityCurve,
		trades: simulatedTrades,
	};
}
