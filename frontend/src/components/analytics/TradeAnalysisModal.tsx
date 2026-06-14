// frontend/src/components/analytics/TradeAnalysisModal.tsx

import html2canvas from "html2canvas";
import {
	type AutoscaleInfo,
	type CandlestickData,
	CandlestickSeries,
	ColorType,
	CrosshairMode,
	createChart,
	createSeriesMarkers,
	HistogramSeries,
	type IChartApi,
	type ISeriesApi,
	LineSeries,
	LineStyle,
	type Time,
} from "lightweight-charts";
import {
	AlertCircle,
	BarChart3,
	Camera,
	ChevronLeft,
	ChevronRight,
	Loader2,
	TrendingDown,
	TrendingUp,
	X,
} from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import type {
	FoundationChartProps,
	KlineData,
	LevelData,
	MarkerData,
} from "@/components/diagnostics/FoundationChart";
import {
	DecisionTraceTree,
	type TraceNode,
} from "@/components/research/DecisionTraceTree";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/ui/logo";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiClient } from "@/lib/apiClient";
import { cn, estimateTickSize } from "@/lib/utils";
import {
	fetchKlines,
	fetchSymbolInfo,
	KLINE_INTERVALS,
	type Kline,
	type KlineInterval,
} from "@/services/binanceService";
import { fetchBybitKlines, fetchBybitSymbolInfo } from "@/services/bybitService";
import type {
	StrategyConfigData,
	TradeData,
	TradeExecution,
} from "@/types/api";

interface TradeAnalysisModalProps {
	trade: TradeData;
	relatedTrades?: TradeData[];
	onClose: () => void;
	runId?: string;
	strategyConfig?: StrategyConfigData;
}

interface NormalizedExecution {
	timestampSec: number;
	price: number;
	type: "ENTRY" | "EXIT";
	sideIndex: number;
}

const toTimestampSeconds = (
	value: string | number | null | undefined,
): number | null => {
	if (value == null) return null;

	if (typeof value === "string") {
		const trimmed = value.trim();
		const hasExplicitTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
		const looksLikeIsoDateTime = /^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}/.test(
			trimmed,
		);
		const normalized =
			looksLikeIsoDateTime && !hasExplicitTimezone
				? `${trimmed.replace(" ", "T")}Z`
				: trimmed;
		const ms = new Date(normalized).getTime();
		return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
	}

	if (!Number.isFinite(value)) return null;
	return Math.floor(value > 1000000000000 ? value / 1000 : value);
};

const getKlineTimeSeconds = (time: number): number =>
	time > 1000000000000 ? Math.floor(time / 1000) : time;

const getTradeTimestampSeconds = (
	trade: TradeData,
	field: "timestamp_entry" | "timestamp_signal" | "timestamp_close",
): number | null => {
	return toTimestampSeconds(trade[field] as string | number | null | undefined);
};

const getExitType = (trade: TradeData): string =>
	String(trade.exit_type || "").toUpperCase();

const parseTraceObject = (value: unknown): Record<string, unknown> | null => {
	if (!value) return null;
	if (typeof value === "string") {
		try {
			const parsed = JSON.parse(value);
			return parsed && typeof parsed === "object"
				? (parsed as Record<string, unknown>)
				: null;
		} catch {
			return null;
		}
	}
	return typeof value === "object" ? (value as Record<string, unknown>) : null;
};

const getTradeTrace = (trade: TradeData): Record<string, unknown> | null => {
	const details = parseTraceObject(trade.signal_details_json);
	const directTrace = parseTraceObject(
		(trade as unknown as Record<string, unknown>).decision_trace_json,
	);
	return parseTraceObject(details?.decision_trace) || directTrace || details;
};

const toFiniteNumber = (value: unknown): number | undefined => {
	if (value === null || value === undefined || value === "") return undefined;
	const numeric = typeof value === "number" ? value : Number(value);
	return Number.isFinite(numeric) ? numeric : undefined;
};

const formatFiniteNumber = (value: unknown, digits: number): string => {
	const numeric = toFiniteNumber(value);
	return numeric === undefined ? "n/a" : numeric.toFixed(digits);
};

const getTraceNodeParams = (
	node: Record<string, unknown> | null | undefined,
): Record<string, unknown> => {
	const params =
		node?.params && typeof node.params === "object"
			? (node.params as Record<string, unknown>)
			: {};
	const details =
		node?.details && typeof node.details === "object"
			? (node.details as Record<string, unknown>)
			: null;
	const detailsParams =
		details?.params && typeof details.params === "object"
			? (details.params as Record<string, unknown>)
			: {};
	return { ...detailsParams, ...params };
};

const timeframeToSeconds = (timeframe?: string): number => {
	const tf = timeframe || "1m";
	const value = Number.parseInt(tf, 10);
	if (!Number.isFinite(value) || value <= 0) return 60;
	if (tf.endsWith("h")) return value * 60 * 60;
	if (tf.endsWith("d")) return value * 24 * 60 * 60;
	return value * 60;
};

const normalizeFoundationType = (rawType: unknown): string | null => {
	const type = String(rawType || "").toLowerCase();
	if (!type) return null;

	if (type.includes("significant_level")) return "significant_level";
	if (type.includes("local_level")) return "local_level";
	if (type.includes("round_level")) return "round_level";
	if (type.includes("bollinger") || type.includes("bb_condition"))
		return "bollinger_bands_condition";
	if (type.includes("stoch")) return "stochastic_condition";
	if (type.includes("rsi")) return "rsi_condition";
	if (type.includes("macd")) return "macd_condition";
	if (type.includes("adx") || type === "trend_filter" || type === "adx_filter")
		return "trend_filter";
	if (type.includes("natr")) return "natr_filter";
	if (type.includes("volatility_filter")) return "volatility_filter";
	if (type.includes("ma_cross") || type.includes("ma_crossover"))
		return "ma_crossover";
	if (type.includes("trend_direction")) return "trend_direction";
	if (type.includes("volume_confirmation")) return "volume_confirmation";
	if (type.includes("consolidation") || type.includes("price_consolidation"))
		return "price_consolidation";
	if (type.includes("squeeze") || type.includes("volatility_squeeze"))
		return "volatility_squeeze";
	if (type.includes("level_touch")) return "level_touch_analyzer";
	if (type.includes("price_action")) return "price_action_analyzer";
	if (type.includes("tape_acceleration") || type.includes("tape"))
		return "tape_acceleration";
	if (type.includes("open_interest") || type.includes("oi"))
		return "open_interest";
	if (type.includes("rel_vol") || type.includes("relative_volume"))
		return "rel_vol_filter";
	if (type.includes("correlation")) return "correlation";
	if (type.includes("pattern") || type.includes("classic_pattern"))
		return "classic_pattern";

	return null;
};

const normalizeChartKlines = (klines: Kline[]): KlineData[] => {
	return [...klines]
		.map((kline) => ({
			time: getKlineTimeSeconds(kline.time),
			open: Number(kline.open),
			high: Number(kline.high),
			low: Number(kline.low),
			close: Number(kline.close),
			volume: Number((kline as unknown as Record<string, unknown>).volume || 0),
		}))
		.filter(
			(kline) =>
				Number.isFinite(kline.time) &&
				Number.isFinite(kline.open) &&
				Number.isFinite(kline.high) &&
				Number.isFinite(kline.low) &&
				Number.isFinite(kline.close),
		)
		.sort((a, b) => a.time - b.time)
		.filter(
			(kline, index, arr) => index === 0 || kline.time > arr[index - 1].time,
		);
};

const toSubchartSeries = (
	klines: KlineData[],
	values: Array<number | null | undefined>,
) =>
	values
		.map((value, index) => {
			const numeric = toFiniteNumber(value);
			if (numeric === undefined) return null;
			return { time: klines[index].time, value: numeric };
		})
		.filter(
			(point): point is { time: number; value: number } => point !== null,
		);

const smaValues = (
	values: Array<number | null | undefined>,
	period: number,
): Array<number | null> => {
	const result = new Array<number | null>(values.length).fill(null);
	if (period <= 0) return result;

	for (let i = period - 1; i < values.length; i += 1) {
		let sum = 0;
		let count = 0;
		for (let j = i - period + 1; j <= i; j += 1) {
			const numeric = toFiniteNumber(values[j]);
			if (numeric === undefined) break;
			sum += numeric;
			count += 1;
		}
		if (count === period) result[i] = sum / period;
	}

	return result;
};

const emaValues = (
	values: Array<number | null | undefined>,
	period: number,
): Array<number | null> => {
	const result = new Array<number | null>(values.length).fill(null);
	if (period <= 0) return result;

	const multiplier = 2 / (period + 1);
	let ema: number | null = null;
	const seed: number[] = [];

	values.forEach((value, index) => {
		const numeric = toFiniteNumber(value);
		if (numeric === undefined) return;

		if (ema === null) {
			seed.push(numeric);
			if (seed.length === period) {
				ema = seed.reduce((sum, item) => sum + item, 0) / period;
				result[index] = ema;
			}
			return;
		}

		ema = (numeric - ema) * multiplier + ema;
		result[index] = ema;
	});

	return result;
};

const rsiValues = (closes: number[], period: number): Array<number | null> => {
	const result = new Array<number | null>(closes.length).fill(null);
	if (period <= 0 || closes.length <= period) return result;

	let avgGain = 0;
	let avgLoss = 0;
	for (let i = 1; i <= period; i += 1) {
		const delta = closes[i] - closes[i - 1];
		avgGain += Math.max(delta, 0);
		avgLoss += Math.max(-delta, 0);
	}
	avgGain /= period;
	avgLoss /= period;
	result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

	for (let i = period + 1; i < closes.length; i += 1) {
		const delta = closes[i] - closes[i - 1];
		avgGain = (avgGain * (period - 1) + Math.max(delta, 0)) / period;
		avgLoss = (avgLoss * (period - 1) + Math.max(-delta, 0)) / period;
		result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
	}

	return result;
};

const atrValues = (
	klines: KlineData[],
	period: number,
): Array<number | null> => {
	const result = new Array<number | null>(klines.length).fill(null);
	if (period <= 0 || klines.length < period) return result;

	const trueRanges = klines.map((kline, index) => {
		if (index === 0) return kline.high - kline.low;
		const previousClose = klines[index - 1].close;
		return Math.max(
			kline.high - kline.low,
			Math.abs(kline.high - previousClose),
			Math.abs(kline.low - previousClose),
		);
	});

	let atr =
		trueRanges.slice(0, period).reduce((sum, value) => sum + value, 0) / period;
	result[period - 1] = atr;
	for (let i = period; i < trueRanges.length; i += 1) {
		atr = (atr * (period - 1) + trueRanges[i]) / period;
		result[i] = atr;
	}

	return result;
};

const adxValues = (
	klines: KlineData[],
	period: number,
): Array<number | null> => {
	const result = new Array<number | null>(klines.length).fill(null);
	if (period <= 0 || klines.length <= period * 2) return result;

	const trueRanges = new Array<number>(klines.length).fill(0);
	const plusDm = new Array<number>(klines.length).fill(0);
	const minusDm = new Array<number>(klines.length).fill(0);

	for (let i = 1; i < klines.length; i += 1) {
		const upMove = klines[i].high - klines[i - 1].high;
		const downMove = klines[i - 1].low - klines[i].low;
		plusDm[i] = upMove > downMove && upMove > 0 ? upMove : 0;
		minusDm[i] = downMove > upMove && downMove > 0 ? downMove : 0;
		trueRanges[i] = Math.max(
			klines[i].high - klines[i].low,
			Math.abs(klines[i].high - klines[i - 1].close),
			Math.abs(klines[i].low - klines[i - 1].close),
		);
	}

	let trSmooth = trueRanges
		.slice(1, period + 1)
		.reduce((sum, value) => sum + value, 0);
	let plusSmooth = plusDm
		.slice(1, period + 1)
		.reduce((sum, value) => sum + value, 0);
	let minusSmooth = minusDm
		.slice(1, period + 1)
		.reduce((sum, value) => sum + value, 0);
	const dxValues = new Array<number | null>(klines.length).fill(null);

	for (let i = period; i < klines.length; i += 1) {
		if (i > period) {
			trSmooth = trSmooth - trSmooth / period + trueRanges[i];
			plusSmooth = plusSmooth - plusSmooth / period + plusDm[i];
			minusSmooth = minusSmooth - minusSmooth / period + minusDm[i];
		}

		const plusDi = trSmooth === 0 ? 0 : (100 * plusSmooth) / trSmooth;
		const minusDi = trSmooth === 0 ? 0 : (100 * minusSmooth) / trSmooth;
		const denominator = plusDi + minusDi;
		dxValues[i] =
			denominator === 0 ? 0 : (100 * Math.abs(plusDi - minusDi)) / denominator;
	}

	let adx: number | null = null;
	for (let i = period * 2 - 1; i < klines.length; i += 1) {
		if (adx === null) {
			const seed = dxValues
				.slice(period, i + 1)
				.filter((value): value is number => value !== null);
			if (seed.length === period) {
				adx = seed.reduce((sum, value) => sum + value, 0) / period;
				result[i] = adx;
			}
			continue;
		}

		const dx = dxValues[i];
		if (dx !== null) {
			adx = (adx * (period - 1) + dx) / period;
			result[i] = adx;
		}
	}

	return result;
};

const stochasticValues = (
	klines: KlineData[],
	kPeriod: number,
	dPeriod: number,
	slowing: number,
) => {
	const rawK = new Array<number | null>(klines.length).fill(null);
	for (let i = kPeriod - 1; i < klines.length; i += 1) {
		const window = klines.slice(i - kPeriod + 1, i + 1);
		const highest = Math.max(...window.map((kline) => kline.high));
		const lowest = Math.min(...window.map((kline) => kline.low));
		rawK[i] =
			highest === lowest
				? 0
				: ((klines[i].close - lowest) / (highest - lowest)) * 100;
	}

	const k = smaValues(rawK, Math.max(1, slowing));
	const d = smaValues(k, Math.max(1, dPeriod));
	return { k, d };
};

const bollingerValues = (
	closes: number[],
	period: number,
	stdMultiplier: number,
) => {
	const upper = new Array<number | null>(closes.length).fill(null);
	const middle = smaValues(closes, period);
	const lower = new Array<number | null>(closes.length).fill(null);

	for (let i = period - 1; i < closes.length; i += 1) {
		const mid = middle[i];
		if (mid === null) continue;
		const window = closes.slice(i - period + 1, i + 1);
		const variance =
			window.reduce((sum, close) => sum + (close - mid) ** 2, 0) / period;
		const deviation = Math.sqrt(variance) * stdMultiplier;
		upper[i] = mid + deviation;
		lower[i] = mid - deviation;
	}

	return { upper, middle, lower };
};

export const TradeAnalysisModal: React.FC<TradeAnalysisModalProps> = ({
	trade,
	relatedTrades = [],
	onClose,
	runId,
	strategyConfig,
}) => {
	const { t } = useTranslation("analytics");

	const chartContainerRef = useRef<HTMLDivElement>(null);
	const indicatorContainerRef = useRef<HTMLDivElement>(null);
	const overlayRef = useRef<SVGSVGElement | null>(null);
	const chartRef = useRef<IChartApi | null>(null);
	const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
	const modalContentRef = useRef<HTMLDivElement>(null);

	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [klines, setKlines] = useState<Kline[]>([]);
	const [isCapturing, setIsCapturing] = useState(false);
	const [interval, setInterval] = useState<KlineInterval | undefined>(
		undefined,
	);
	const [showTree, setShowTree] = useState(true);
	const [showIndicators, setShowIndicators] = useState(false);
	const [foundationData, setFoundationData] =
		useState<FoundationChartProps | null>(null);
	const [foundationLoading, setFoundationLoading] = useState(false);
	const [tickSize, setTickSize] = useState<number | undefined>(trade.tick_size);

	// Ruler state
	const [isRulerActive, setIsRulerActive] = useState(false);
	const rulerStartRef = useRef<{ x: number; y: number; price: number } | null>(
		null,
	);
	const rulerCurrentRef = useRef<{
		x: number;
		y: number;
		price: number;
	} | null>(null);

	// Calculate prices and times from executions if they are not set
	const { entryPrice, exitPrice, entryTime, exitTime } = useMemo(() => {
		let entry = trade.entry_price || 0;
		let exit = trade.exit_price || 0;

		// Convert timestamp to numbers (seconds for lightweight-charts)
		const exitT =
			getTradeTimestampSeconds(trade, "timestamp_close") ??
			Math.floor(Date.now() / 1000);

		// Looking for entry time in order of priority:
		// 1. From executions (ENTRY type)
		// 2. From timestamp_signal
		// 3. Fallback: backward approximation from exit
		let entryT: number;

		// First, check executions
		if (trade.executions && trade.executions.length > 0) {
			const sortedExecs = [...trade.executions].sort((a, b) => {
				const timeA = toTimestampSeconds(a.timestamp as string | number) ?? 0;
				const timeB = toTimestampSeconds(b.timestamp as string | number) ?? 0;
				return timeA - timeB;
			});

			// Looking for the first ENTRY execution
			const entryExec =
				sortedExecs.find((e) => e.type === "ENTRY") || sortedExecs[0];
			const exitExec =
				sortedExecs.find((e) => e.type === "EXIT") ||
				sortedExecs[sortedExecs.length - 1];

			if (entryExec) {
				entryT =
					toTimestampSeconds(entryExec.timestamp as string | number) ??
					exitT - 3600;

				// Also use the price from execution if not set
				if (!entry) entry = entryExec.price;
			} else {
				entryT = exitT - 3600; // fallback
			}

			// Exit price from the last EXIT execution
			if (!exit && exitExec) exit = exitExec.price;
		} else if (trade.timestamp_signal) {
			// Use timestamp_signal if there are no executions
			entryT =
				getTradeTimestampSeconds(trade, "timestamp_signal") ?? exitT - 3600;
		} else {
			// Fallback: use 10% of the time until the current moment or a minimum of 5 minutes
			// This provides a reasonable approximation for different trade durations
			const tradeDuration = Math.max(300, (Date.now() / 1000 - exitT) * 0.1);
			entryT = exitT - tradeDuration;
		}

		return {
			entryPrice: entry,
			exitPrice: exit,
			entryTime: entryT,
			exitTime: exitT,
		};
	}, [trade]);

	const realizedPnl = trade.pnl || 0;
	const isLong = ["LONG", "BUY"].includes(String(trade.direction));

	const normalizedExecutions = useMemo<NormalizedExecution[]>(() => {
		const counters: Record<TradeExecution["type"], number> = {
			ENTRY: 0,
			EXIT: 0,
		};
		const markerExecutions: Omit<NormalizedExecution, "sideIndex">[] = [];
		const assignSideIndexes = (
			executions: Omit<NormalizedExecution, "sideIndex">[],
		) =>
			executions
				.sort((a, b) => a.timestampSec - b.timestampSec)
				.map((execution) => {
					counters[execution.type] += 1;
					return { ...execution, sideIndex: counters[execution.type] };
				});

		const positionEntryId = trade.position_entry_id || trade.trade_uuid;
		const samePositionTrades = relatedTrades.filter((candidate) => {
			if (!candidate || candidate.symbol !== trade.symbol) return false;
			if (positionEntryId) {
				return (
					candidate.position_entry_id === positionEntryId ||
					candidate.trade_uuid === positionEntryId
				);
			}
			return candidate.id === trade.id;
		});

		const sourceTrades =
			samePositionTrades.length > 0 ? samePositionTrades : [trade];
		const eventSourceTrades = [
			trade,
			...sourceTrades.filter((candidate) => candidate.id !== trade.id),
		];

		const appendRawExecution = (execution: Record<string, unknown>) => {
			const timestampSec = toTimestampSeconds(
				(execution.timestamp as string | number | null | undefined) ??
					(execution.time as string | number | null | undefined) ??
					(execution.transactTime as string | number | null | undefined) ??
					(execution.updateTime as string | number | null | undefined),
			);
			const price = Number(
				execution.price ??
					execution.fill_price ??
					execution.avgPrice ??
					execution.average,
			);
			const rawType = String(
				execution.type ?? execution.execution_type ?? "",
			).toUpperCase();
			const type: "ENTRY" | "EXIT" = rawType.includes("ENTRY")
				? "ENTRY"
				: "EXIT";

			if (timestampSec === null || !Number.isFinite(price) || price <= 0) {
				return;
			}

			markerExecutions.push({ timestampSec, price, type });
		};

		eventSourceTrades.forEach((sourceTrade) => {
			(sourceTrade.executions || []).forEach((execution) => {
				appendRawExecution(execution as unknown as Record<string, unknown>);
			});

			const details = parseTraceObject(sourceTrade.signal_details_json) as
				| {
						execution_events?: Array<Record<string, unknown>>;
						executions?: Array<Record<string, unknown>>;
				  }
				| null
				| undefined;
			const jsonExecutions =
				details?.execution_events || details?.executions || [];
			jsonExecutions.forEach(appendRawExecution);
		});

		sourceTrades.forEach((candidate) => {
			const exitType = getExitType(candidate);
			const isEntryRecord = exitType === "ENTRY";
			const entryTimestamp =
				getTradeTimestampSeconds(candidate, "timestamp_entry") ??
				getTradeTimestampSeconds(candidate, "timestamp_signal") ??
				getTradeTimestampSeconds(candidate, "timestamp_close");
			const closeTimestamp = getTradeTimestampSeconds(
				candidate,
				"timestamp_close",
			);
			const entryPriceCandidate = Number(candidate.entry_price);
			const exitPriceCandidate = Number(candidate.exit_price);

			if (
				isEntryRecord &&
				entryTimestamp !== null &&
				Number.isFinite(entryPriceCandidate) &&
				entryPriceCandidate > 0
			) {
				markerExecutions.push({
					timestampSec: entryTimestamp,
					price: entryPriceCandidate,
					type: "ENTRY",
				});
				return;
			}

			if (
				!isEntryRecord &&
				closeTimestamp !== null &&
				Number.isFinite(exitPriceCandidate) &&
				exitPriceCandidate > 0
			) {
				markerExecutions.push({
					timestampSec: closeTimestamp,
					price: exitPriceCandidate,
					type: "EXIT",
				});
			}
		});

		const hasEntryMarker = markerExecutions.some(
			(execution) => execution.type === "ENTRY",
		);
		if (!hasEntryMarker) {
			const entryTimestamp =
				getTradeTimestampSeconds(trade, "timestamp_entry") ??
				getTradeTimestampSeconds(trade, "timestamp_signal");
			const entryPriceCandidate = Number(trade.entry_price);

			if (
				entryTimestamp !== null &&
				Number.isFinite(entryPriceCandidate) &&
				entryPriceCandidate > 0
			) {
				markerExecutions.push({
					timestampSec: entryTimestamp,
					price: entryPriceCandidate,
					type: "ENTRY",
				});
			}
		}

		const deduped = markerExecutions.filter((execution, index, executions) => {
			return (
				executions.findIndex(
					(candidate) =>
						candidate.type === execution.type &&
						candidate.timestampSec === execution.timestampSec &&
						Math.abs(candidate.price - execution.price) < 1e-12,
				) === index
			);
		});

		return assignSideIndexes(deduped);
	}, [trade, relatedTrades]);

	const executionPrices = useMemo(
		() => normalizedExecutions.map((execution) => execution.price),
		[normalizedExecutions],
	);

	const decisionTrace = useMemo(() => getTradeTrace(trade), [trade]);

	// Extract indicator values from decision trace nodes
	interface ExtractedIndicators {
		// Price-based (overlay on main chart)
		bbBands: Array<{
			upper: number;
			middle?: number;
			lower: number;
			result: boolean;
		}>;
		significantLevels: Array<{
			price: number;
			levelType: string;
			result: boolean;
		}>;
		localLevels: Array<{ price: number; levelType: string; result: boolean }>;
		roundLevels: Array<{ price: number; result: boolean }>;
		maCrossover: Array<{ fastMa: number; slowMa: number; result: boolean }>;

		// Oscillators (sub-panes)
		stoch: Array<{ k: number; d: number; result: boolean }>;
		rsi: Array<{ value: number; result: boolean }>;
		macd: Array<{
			line: number;
			signal: number;
			histogram: number;
			result: boolean;
		}>;

		// Trend/Volatility (sub-panes)
		adx: Array<{ value: number; result: boolean }>;
		natr: Array<{ value: number; threshold?: number; result: boolean }>;
		atr: Array<{ value: number; result: boolean }>;

		// Other filters (annotations)
		timeFilter: Array<{
			startHour?: number;
			endHour?: number;
			currentHour?: number;
			mode?: string;
			result: boolean;
		}>;
		trendDirection: Array<{ direction: string; result: boolean }>;
		volumeConfirmation: Array<{
			volume?: number;
			threshold?: number;
			result: boolean;
		}>;
		priceConsolidation: Array<{
			rangePercent?: number;
			detectedLevel?: number;
			rollingHigh?: number;
			rollingLow?: number;
			lookbackPeriod?: number;
			timeframe?: string;
			result: boolean;
		}>;
		volatilitySqueeze: Array<{ result: boolean }>;
		levelTouch: Array<{ price: number; result: boolean }>;
		priceAction: Array<{ result: boolean }>;
		tapeAcceleration: Array<{ value?: number; result: boolean }>;
		openInterest: Array<{ change?: number; result: boolean }>;
		relativeVolume: Array<{ value?: number; result: boolean }>;
		correlation: Array<{ value?: number; asset?: string; result: boolean }>;
		pattern: Array<{ patternType?: string; result: boolean }>;
	}

	const extractIndicatorsFromTrace = useCallback(
		(node: TraceNode, indicators: ExtractedIndicators) => {
			if (!node || typeof node !== "object") return;

			const nodeType = node.type?.toLowerCase() || "";
			const details = (node.details as Record<string, unknown>) || {};
			const params = getTraceNodeParams(node);
			const result = node.result ?? true;

			// Bollinger Bands
			if (
				nodeType.includes("bollinger") ||
				nodeType.includes("bb_condition") ||
				nodeType === "bb_condition"
			) {
				if (details.upper !== undefined && details.lower !== undefined) {
					indicators.bbBands.push({
						upper: Number(details.upper),
						middle: toFiniteNumber(details.middle),
						lower: Number(details.lower),
						result,
					});
				}
			}

			// Significant Levels
			if (nodeType.includes("significant_level")) {
				const price = details.detected_level ?? details.price ?? details.level;
				if (price !== undefined) {
					indicators.significantLevels.push({
						price,
						levelType: details.type || "support",
						result,
					});
				}
			}

			// Local Levels
			if (nodeType.includes("local_level")) {
				const price = details.detected_level ?? details.price ?? details.level;
				if (price !== undefined) {
					indicators.localLevels.push({
						price,
						levelType: details.type || "support",
						result,
					});
				}
			}

			// Round Levels
			if (nodeType.includes("round_level")) {
				const price = details.detected_level ?? details.price ?? details.level;
				if (price !== undefined) {
					indicators.roundLevels.push({ price, result });
				}
			}

			// MA Crossover
			if (nodeType.includes("ma_cross") || nodeType.includes("ma_crossover")) {
				if (
					details.fast_ma !== undefined ||
					details.slow_ma !== undefined ||
					details.fast !== undefined ||
					details.slow !== undefined
				) {
					indicators.maCrossover.push({
						fastMa: Number(details.fast_ma ?? details.fast ?? 0),
						slowMa: Number(details.slow_ma ?? details.slow ?? 0),
						result,
					});
				}
			}

			// Stochastic
			if (nodeType.includes("stoch")) {
				if (details.k !== undefined && details.d !== undefined) {
					indicators.stoch.push({ k: details.k, d: details.d, result });
				}
			}

			// RSI
			if (nodeType.includes("rsi")) {
				const rsiValue = details.rsi ?? details.value ?? details.rsi_value;
				if (rsiValue !== undefined) {
					indicators.rsi.push({ value: rsiValue, result });
				}
			}

			// MACD
			if (nodeType.includes("macd")) {
				if (
					details.macd_line !== undefined ||
					details.line !== undefined ||
					details.macd !== undefined
				) {
					indicators.macd.push({
						line: Number(
							details.macd_line ?? details.line ?? details.macd ?? 0,
						),
						signal: Number(details.signal_line ?? details.signal ?? 0),
						histogram: Number(details.histogram ?? details.hist ?? 0),
						result,
					});
				}
			}

			// ADX / Trend Filter
			if (nodeType.includes("adx") || nodeType === "trend_filter") {
				const adxValue =
					details.adx ?? details.adx_actual ?? details.actual ?? details.value;
				if (adxValue !== undefined) {
					indicators.adx.push({ value: Number(adxValue), result });
				}
			}

			// NATR / Volatility Filter
			if (nodeType.includes("natr") || nodeType.includes("volatility_filter")) {
				const natrValue =
					details.natr_val ?? details.natr ?? details.actual ?? details.value;
				if (natrValue !== undefined) {
					indicators.natr.push({
						value: Number(natrValue),
						threshold: toFiniteNumber(details.threshold ?? params.value),
						result,
					});
				}
			}

			// ATR
			if (nodeType.includes("atr") && !nodeType.includes("natr")) {
				if (details.atr !== undefined || details.value !== undefined) {
					indicators.atr.push({ value: details.atr ?? details.value, result });
				}
			}

			// Time Filter
			if (
				nodeType.includes("time_filter") ||
				nodeType.includes("trading_hours") ||
				nodeType.includes("time")
			) {
				indicators.timeFilter.push({
					startHour:
						details.start_hour ??
						details.startHour ??
						details.range?.split("-")[0],
					endHour:
						details.end_hour ?? details.endHour ?? details.range?.split("-")[1],
					currentHour: details.current_hour ?? details.currentHour,
					mode: details.mode,
					result,
				});
			}

			// Trend Direction
			if (
				nodeType.includes("trend_direction") ||
				(nodeType.includes("trend") && !nodeType.includes("filter"))
			) {
				indicators.trendDirection.push({
					direction:
						details.direction ??
						details.trend ??
						(result ? "bullish" : "bearish"),
					result,
				});
			}

			// Volume Confirmation
			if (
				nodeType.includes("volume_confirmation") ||
				(nodeType.includes("volume") && !nodeType.includes("relative"))
			) {
				indicators.volumeConfirmation.push({
					volume: details.volume ?? details.value,
					threshold: details.threshold,
					result,
				});
			}

			// Price Consolidation
			if (nodeType.includes("consolidation")) {
				// Aggressive price extraction
				const detectedLevel =
					details.detected_level ??
					details.level ??
					details.price ??
					details.detectedLevel;
				indicators.priceConsolidation.push({
					rangePercent: toFiniteNumber(
						details.range_percent ?? details.range ?? details.price_range,
					),
					detectedLevel: toFiniteNumber(detectedLevel),
					rollingHigh: toFiniteNumber(
						details.rolling_high ?? details.body_high ?? details.top_price,
					),
					rollingLow: toFiniteNumber(
						details.rolling_low ?? details.body_low ?? details.bottom_price,
					),
					lookbackPeriod: toFiniteNumber(
						details.lookback_period ??
							details.lookback ??
							params.lookback_period,
					),
					timeframe: details.timeframe || details.tf || params.timeframe,
					result,
				});
			}

			// Volatility Squeeze
			if (
				nodeType.includes("squeeze") ||
				nodeType.includes("volatility_squeeze")
			) {
				indicators.volatilitySqueeze.push({ result });
			}

			// Level Touch
			if (nodeType.includes("level_touch")) {
				const price = details.detected_level ?? details.price ?? details.level;
				if (price !== undefined) {
					indicators.levelTouch.push({ price, result });
				}
			}

			// Price Action
			if (nodeType.includes("price_action")) {
				indicators.priceAction.push({ result });
			}

			// Tape Acceleration
			if (nodeType.includes("tape_acceleration") || nodeType.includes("tape")) {
				indicators.tapeAcceleration.push({
					value: details.acceleration ?? details.value,
					result,
				});
			}

			// Open Interest
			if (nodeType.includes("open_interest") || nodeType.includes("oi")) {
				indicators.openInterest.push({
					change: details.change ?? details.oi_change,
					result,
				});
			}

			// Relative Volume
			if (
				nodeType.includes("rel_vol") ||
				nodeType.includes("relative_volume")
			) {
				indicators.relativeVolume.push({
					value: toFiniteNumber(
						details.rel_vol ??
							details.relative_volume ??
							details.rel_vol_actual ??
							details.actual ??
							details.value,
					),
					result,
				});
			}

			// Correlation
			if (nodeType.includes("correlation")) {
				indicators.correlation.push({
					value: details.correlation ?? details.value,
					asset: details.asset ?? details.symbol,
					result,
				});
			}

			// Pattern
			if (
				nodeType.includes("pattern") ||
				nodeType.includes("classic_pattern")
			) {
				indicators.pattern.push({
					patternType: details.pattern ?? details.type ?? details.name,
					result,
				});
			}

			// Recurse into children
			if (node.children && Array.isArray(node.children)) {
				node.children.forEach((child: TraceNode) => {
					extractIndicatorsFromTrace(child, indicators);
				});
			}
		},
		[],
	);

	const extractedIndicators = useMemo(() => {
		const indicators: ExtractedIndicators = {
			bbBands: [],
			significantLevels: [],
			localLevels: [],
			roundLevels: [],
			maCrossover: [],
			stoch: [],
			rsi: [],
			macd: [],
			adx: [],
			natr: [],
			atr: [],
			timeFilter: [],
			trendDirection: [],
			volumeConfirmation: [],
			priceConsolidation: [],
			volatilitySqueeze: [],
			levelTouch: [],
			priceAction: [],
			tapeAcceleration: [],
			openInterest: [],
			relativeVolume: [],
			correlation: [],
			pattern: [],
		};

		if (!decisionTrace) return indicators;

		// Check entry conditions trace
		const entryTrace = decisionTrace.decision_trace || decisionTrace;
		if (entryTrace && typeof entryTrace === "object") {
			extractIndicatorsFromTrace(entryTrace, indicators);
		}

		// Check filters trace
		const filtersTrace = entryTrace?.filters_trace;
		if (filtersTrace && typeof filtersTrace === "object") {
			extractIndicatorsFromTrace(filtersTrace, indicators);
		}

		return indicators;
	}, [decisionTrace, extractIndicatorsFromTrace]);

	// Determine which foundations to request based on extracted indicators or strategy config
	const usedFoundations = useMemo(() => {
		const foundations = new Set<string>();

		const extractFromNode = (
			node: Record<string, unknown> | null | undefined,
		) => {
			if (!node || typeof node !== "object") return;
			const foundationType = normalizeFoundationType(node.type as string);
			if (foundationType) foundations.add(foundationType);

			if (node.children && Array.isArray(node.children)) {
				node.children.forEach((child: unknown) => {
					extractFromNode(child as Record<string, unknown>);
				});
			}
			if (node.filters_trace)
				extractFromNode(node.filters_trace as Record<string, unknown>);
		};

		if (decisionTrace) {
			extractFromNode(
				(decisionTrace.decision_trace || decisionTrace) as Record<
					string,
					unknown
				>,
			);
		}

		if (foundations.size === 0 && strategyConfig) {
			if (strategyConfig.entryConditions)
				extractFromNode(strategyConfig.entryConditions);
			if (strategyConfig.filters) extractFromNode(strategyConfig.filters);
		}

		// 2. Also check extracted indicators from trace (as a fallback or addition)
		if (foundations.size === 0) {
			if (extractedIndicators.bbBands.length > 0)
				foundations.add("bollinger_bands_condition");
			if (extractedIndicators.stoch.length > 0)
				foundations.add("stochastic_condition");
			if (extractedIndicators.rsi.length > 0) foundations.add("rsi_condition");
			if (extractedIndicators.macd.length > 0)
				foundations.add("macd_condition");
			if (extractedIndicators.adx.length > 0) foundations.add("trend_filter");
			if (extractedIndicators.natr.length > 0) foundations.add("natr_filter");
			if (extractedIndicators.maCrossover.length > 0)
				foundations.add("ma_crossover");
			if (extractedIndicators.significantLevels.length > 0)
				foundations.add("significant_level");
			if (extractedIndicators.localLevels.length > 0)
				foundations.add("local_level");
			if (extractedIndicators.roundLevels.length > 0)
				foundations.add("round_level");
			if (extractedIndicators.trendDirection.length > 0)
				foundations.add("trend_direction");
			if (extractedIndicators.volumeConfirmation.length > 0)
				foundations.add("volume_confirmation");
			if (extractedIndicators.priceConsolidation.length > 0)
				foundations.add("price_consolidation");
			if (extractedIndicators.volatilitySqueeze.length > 0)
				foundations.add("volatility_squeeze");
			if (extractedIndicators.levelTouch.length > 0)
				foundations.add("level_touch_analyzer");
			if (extractedIndicators.priceAction.length > 0)
				foundations.add("price_action_analyzer");
			if (extractedIndicators.tapeAcceleration.length > 0)
				foundations.add("tape_acceleration");
			if (extractedIndicators.openInterest.length > 0)
				foundations.add("open_interest");
			if (extractedIndicators.relativeVolume.length > 0)
				foundations.add("rel_vol_filter");
			if (extractedIndicators.correlation.length > 0)
				foundations.add("correlation");
			if (extractedIndicators.pattern.length > 0)
				foundations.add("classic_pattern");
		}

		// 3. EXCLUDE STATIC LEVELS FROM BACKEND REQUEST
		// We strictly use Trace data for levels to avoid re-calculation noise.
		// NOTE: We KEEP price_consolidation here because we need the backend to calculate the zone boundaries (start/end).
		const excludedFromBackend = new Set([
			"significant_level",
			"local_level",
			"round_level",
		]);
		const filteredFoundations = Array.from(foundations).filter(
			(f) => !excludedFromBackend.has(f),
		);

		return filteredFoundations;
	}, [decisionTrace, extractedIndicators, strategyConfig]);

	const foundationParams = useMemo(() => {
		const paramsByType: Record<string, Record<string, unknown>> = {};

		const mergeParams = (
			foundationType: string,
			params: Record<string, unknown>,
		) => {
			paramsByType[foundationType] = {
				...(paramsByType[foundationType] || {}),
				...params,
			};
		};

		const collectFromNode = (
			node: Record<string, unknown> | null | undefined,
			preferTraceDetails = false,
		) => {
			if (!node || typeof node !== "object") return;

			const foundationType = normalizeFoundationType(node.type as string);
			if (foundationType) {
				const nodeParams = preferTraceDetails
					? getTraceNodeParams(node)
					: (node.params as Record<string, unknown>) || {};
				if (nodeParams && typeof nodeParams === "object") {
					mergeParams(foundationType, nodeParams);
				}
			}

			if (Array.isArray(node.children)) {
				node.children.forEach((child: unknown) => {
					collectFromNode(child as Record<string, unknown>, preferTraceDetails);
				});
			}
			if (node.filters_trace)
				collectFromNode(
					node.filters_trace as Record<string, unknown>,
					preferTraceDetails,
				);
		};

		if (strategyConfig?.filters) collectFromNode(strategyConfig.filters);
		if (strategyConfig?.entryConditions)
			collectFromNode(strategyConfig.entryConditions);

		const traceRoot = decisionTrace?.decision_trace || decisionTrace;
		if (traceRoot) collectFromNode(traceRoot, true);

		return paramsByType;
	}, [decisionTrace, strategyConfig]);

	// Determine effective interval for UI highlighting
	const effectiveInterval = useMemo(() => {
		if (interval) return interval;

		// Auto-calculation logic based on trade duration
		const durationMs = (exitTime - entryTime) * 1000;
		const durationMinutes = durationMs / 60000;

		if (durationMinutes > 43200) return "4h";
		if (durationMinutes > 10080) return "1h";
		if (durationMinutes > 1440) return "15m";
		if (durationMinutes > 300) return "5m";
		return "1m";
	}, [interval, entryTime, exitTime]);

	const buildTraceFoundationData =
		useCallback((): FoundationChartProps | null => {
			if (!decisionTrace || klines.length === 0) return null;

			const traceRoot = decisionTrace.decision_trace || decisionTrace;
			const signalTime =
				toTimestampSeconds(traceRoot?.details?.signal_time) ??
				getTradeTimestampSeconds(trade, "timestamp_signal") ??
				entryTime;
			const foundationKlines: KlineData[] = klines.map((k) => ({
				time: getKlineTimeSeconds(k.time),
				open: k.open,
				high: k.high,
				low: k.low,
				close: k.close,
				volume: Number((k as Record<string, unknown>).volume || 0),
			}));

			const makePointSeries = (value: unknown) => {
				const numeric = toFiniteNumber(value);
				if (numeric === undefined) return [];
				return [{ time: signalTime, value: numeric, source: "decision_trace" }];
			};

			const visualizations: FoundationChartProps["visualizations"] = {
				levels: [],
				markers: [],
				zones: [],
				subcharts: {},
			};

			const addSubchart = (key: string, value: unknown) => {
				const series = makePointSeries(value);
				if (series.length > 0) visualizations.subcharts[key] = series;
			};

			const addLevel = (
				price: unknown,
				type: string,
				label: string,
				color: string,
			) => {
				const numeric = toFiniteNumber(price);
				if (numeric === undefined || numeric <= 0) return;
				visualizations.levels.push({
					time: signalTime,
					price: numeric,
					type,
					label,
					color,
				} as LevelData & { color?: string });
			};

			const addMarkerAt = (
				time: unknown,
				text: string,
				position: "aboveBar" | "belowBar" | "inBar",
				shape: "circle" | "square" | "arrowUp" | "arrowDown",
				color: string,
				type: string,
			) => {
				const markerTime = toTimestampSeconds(
					time as string | number | null | undefined,
				);
				if (markerTime === null) return;
				visualizations.markers.push({
					time: markerTime,
					position,
					color,
					shape,
					text,
					type,
				} as MarkerData & { type?: string });
			};

			const addMarker = (text: string, result: boolean, type: string) => {
				addMarkerAt(
					signalTime,
					text,
					result ? "belowBar" : "aboveBar",
					"circle",
					result ? "#22c55e" : "#ef4444",
					type,
				);
			};

			const addZone = (
				type: string,
				label: string,
				color: string,
				start: unknown,
				end: unknown,
			) => {
				const startTime = toTimestampSeconds(
					start as string | number | null | undefined,
				);
				const endTime = toTimestampSeconds(
					end as string | number | null | undefined,
				);
				if (startTime === null || endTime === null || endTime <= startTime)
					return;
				visualizations.zones.push({
					startTime,
					endTime,
					start_time: startTime,
					end_time: endTime,
					type,
					label,
					color,
				} as Record<string, unknown>);
			};

			const lookbackWindow = (
				rawLookback: unknown,
				rawTimeframe: unknown,
				fallbackLookback = 20,
			) => {
				const lookback = Math.max(
					1,
					Math.trunc(toFiniteNumber(rawLookback) ?? fallbackLookback),
				);
				const tf = String(
					rawTimeframe || interval || effectiveInterval || "1m",
				);
				return {
					start: signalTime - lookback * timeframeToSeconds(tf),
					end: signalTime + timeframeToSeconds(tf),
				};
			};

			const klineAtRecentIndex = (lookback: number, index: unknown) => {
				const numericIndex = toFiniteNumber(index);
				if (numericIndex === undefined) return null;
				const recent = foundationKlines
					.filter((kline) => kline.time <= signalTime)
					.slice(-Math.max(1, lookback));
				return recent[Math.trunc(numericIndex)] || null;
			};

			const traverse = (node: TraceNode) => {
				if (!node || typeof node !== "object") return;

				const nodeType = String(node.type || "").toLowerCase();
				const details =
					node.details && typeof node.details === "object"
						? (node.details as Record<string, unknown>)
						: {};
				const params = getTraceNodeParams(node);
				const result = Boolean(node.result);

				if (nodeType.includes("local_level")) {
					addLevel(
						details.detected_level ??
							details.level_hit ??
							details.level ??
							details.price,
						"local_level",
						"DECISION: LOCAL LEVEL",
						"#3b82f6",
					);
				} else if (nodeType.includes("significant_level")) {
					addLevel(
						details.detected_level ??
							details.level_hit ??
							details.level ??
							details.price,
						"significant_level",
						"DECISION: SIGNIFICANT LEVEL",
						"#6366f1",
					);
				} else if (
					nodeType.includes("round_level") ||
					nodeType.includes("round_number")
				) {
					addLevel(
						details.detected_level ??
							details.level_hit ??
							details.round_level ??
							details.level ??
							details.price,
						"round_level",
						"DECISION: ROUND LEVEL",
						"#94a3b8",
					);
				} else if (nodeType.includes("level_touch")) {
					const level =
						details.level ?? details.level_price ?? details.detected_level;
					const numericLevel = toFiniteNumber(level);
					addLevel(
						level,
						"level_touch_analyzer",
						numericLevel !== undefined ? `LVL ${numericLevel}` : "LVL",
						"#06b6d4",
					);

					const lookback = Math.max(
						1,
						Math.trunc(
							toFiniteNumber(
								details.lookback_candles ?? params.lookback_candles,
							) ?? 100,
						),
					);
					if (Array.isArray(details.touch_times)) {
						details.touch_times.forEach((touchTime: unknown) => {
							addMarkerAt(
								touchTime,
								"T",
								"inBar",
								"circle",
								"#FFD700",
								"level_touch_analyzer",
							);
						});
					} else if (Array.isArray(details.touch_indices)) {
						details.touch_indices.forEach((touchIndex: unknown) => {
							const kline = klineAtRecentIndex(lookback, touchIndex);
							if (kline)
								addMarkerAt(
									kline.time,
									"T",
									"inBar",
									"circle",
									"#FFD700",
									"level_touch_analyzer",
								);
						});
					} else if (toFiniteNumber(details.touches_count) && result) {
						addMarkerAt(
							signalTime,
							"T",
							"inBar",
							"circle",
							"#FFD700",
							"level_touch_analyzer",
						);
					}
					if (Array.isArray(details.pierce_times)) {
						details.pierce_times.forEach((pierceTime: unknown) => {
							addMarkerAt(
								pierceTime,
								"P",
								"inBar",
								"circle",
								"#ef5350",
								"level_touch_analyzer",
							);
						});
					} else if (Array.isArray(details.pierce_indices)) {
						details.pierce_indices.forEach((pierceIndex: unknown) => {
							const kline = klineAtRecentIndex(lookback, pierceIndex);
							if (kline)
								addMarkerAt(
									kline.time,
									"P",
									"inBar",
									"circle",
									"#ef5350",
									"level_touch_analyzer",
								);
						});
					} else if (details.pierce_detected === true) {
						addMarkerAt(
							signalTime,
							"P",
							"inBar",
							"circle",
							"#ef5350",
							"level_touch_analyzer",
						);
					}
				} else if (nodeType.includes("price_vs_level")) {
					const right = details.right?.actual ?? details.right_value_resolved;
					addLevel(
						right,
						"price_vs_level",
						"DECISION: COMPARED LEVEL",
						"#a855f7",
					);
				} else if (nodeType.includes("orderbook")) {
					addLevel(
						details.support_found_at,
						"orderbook_condition",
						"DECISION: OB SUPPORT",
						"#22c55e",
					);
					addLevel(
						details.resistance_found_at,
						"orderbook_condition",
						"DECISION: OB RESISTANCE",
						"#ef4444",
					);
				}

				if (nodeType.includes("consolidation")) {
					const topPrice = toFiniteNumber(
						details.rolling_high ?? details.body_high ?? details.top_price,
					);
					const bottomPrice = toFiniteNumber(
						details.rolling_low ?? details.body_low ?? details.bottom_price,
					);
					const lookback =
						toFiniteNumber(
							details.lookback_period ??
								details.lookback ??
								params.lookback_period,
						) ?? 1;
					const tf = String(
						details.timeframe ||
							params.timeframe ||
							interval ||
							effectiveInterval ||
							"1m",
					);
					const startTime =
						toTimestampSeconds(details.zone_start_time) ??
						signalTime - lookback * timeframeToSeconds(tf);
					const endTime =
						toTimestampSeconds(details.zone_end_time) ?? signalTime;

					addZone(
						"price_consolidation",
						"Consolidation",
						"rgba(128, 128, 128, 0.5)",
						startTime,
						endTime,
					);
					const latestZone = visualizations.zones[
						visualizations.zones.length - 1
					] as Record<string, unknown>;
					if (latestZone?.type === "price_consolidation") {
						latestZone.top_price = topPrice;
						latestZone.bottom_price = bottomPrice;
						latestZone.detectedLevel = toFiniteNumber(
							details.detected_level ??
								details.level ??
								details.price ??
								details.detectedLevel,
						);
					}
				}

				if (nodeType.includes("trend_direction")) {
					addSubchart(
						"SMA_Fast",
						details.sma_fast ?? details.fast_sma ?? details.fast_ma,
					);
					addSubchart(
						"SMA_Slow",
						details.sma_slow ?? details.slow_sma ?? details.slow_ma,
					);
					addSubchart("RSI", details.rsi);

					const detectedTrend = String(
						details.detected_trend ??
							details.direction ??
							details.trend ??
							details.required_trend ??
							params.required_trend ??
							params.direction ??
							"",
					).toUpperCase();
					const label =
						detectedTrend.includes("SHORT") || detectedTrend.includes("DOWN")
							? "Trend Short"
							: detectedTrend.includes("LONG") || detectedTrend.includes("UP")
								? "Trend Long"
								: "Trend Flat";
					const color = label.includes("Long")
						? "rgba(0, 255, 0, 0.15)"
						: label.includes("Short")
							? "rgba(255, 0, 0, 0.15)"
							: "rgba(128, 128, 128, 0.12)";
					const window = lookbackWindow(
						details.lookback_period ??
							details.sma_slow_period ??
							details.slow_period ??
							params.sma_slow_period ??
							params.slow_period,
						details.timeframe ?? params.timeframe,
						50,
					);
					addZone(
						"trend_direction",
						label,
						color,
						details.zone_start_time ?? details.start_time ?? window.start,
						details.zone_end_time ?? details.end_time ?? window.end,
					);
				}

				if (
					nodeType.includes("bollinger") ||
					nodeType.includes("bb_condition")
				) {
					addSubchart("BB_Upper", details.upper);
					addSubchart("BB_Middle", details.middle);
					addSubchart("BB_Lower", details.lower);
				} else if (
					nodeType.includes("ma_cross") ||
					nodeType.includes("ma_crossover")
				) {
					addSubchart("MA_Fast", details.fast_ma ?? details.fast);
					addSubchart("MA_Slow", details.slow_ma ?? details.slow);
				} else if (nodeType.includes("rsi")) {
					addSubchart("RSI", details.rsi ?? details.value ?? details.rsi_value);
				} else if (nodeType.includes("macd")) {
					addSubchart(
						"MACD_Line",
						details.macd_line ?? details.line ?? details.macd,
					);
					addSubchart("MACD_Signal", details.signal_line ?? details.signal);
					addSubchart("MACD_Hist", details.histogram ?? details.hist);
				} else if (nodeType.includes("stoch")) {
					addSubchart("Stoch_K", details.k);
					addSubchart("Stoch_D", details.d);
				} else if (nodeType.includes("adx") || nodeType === "trend_filter") {
					addSubchart(
						"ADX",
						details.adx ?? details.adx_actual ?? details.actual,
					);
				} else if (nodeType.includes("natr")) {
					addSubchart(
						"NATR",
						details.natr ?? details.natr_val ?? details.actual,
					);
				} else if (nodeType.includes("volatility_filter")) {
					addSubchart(
						String(details.indicator || "ATR"),
						details.actual ?? details.value,
					);
				} else if (
					nodeType.includes("squeeze") ||
					nodeType.includes("volatility_squeeze")
				) {
					addSubchart("Squeeze_Current_Range", details.current_range_pct);
					addSubchart("Squeeze_Past_Range", details.past_range_pct);
					if (result || details.is_squeezing === true) {
						const window = lookbackWindow(
							details.lookback_period ??
								details.lookback_candles ??
								params.lookback_period ??
								params.lookback_candles,
							details.timeframe ?? params.timeframe,
							20,
						);
						addZone(
							"volatility_squeeze",
							"Volatility Squeeze",
							"rgba(255, 255, 0, 0.3)",
							details.zone_start_time ?? details.start_time ?? window.start,
							details.zone_end_time ?? details.end_time ?? window.end,
						);
					}
				} else if (
					nodeType.includes("rel_vol") ||
					nodeType.includes("relative_volume")
				) {
					addMarker("RV", result, "rel_vol_filter");
				} else if (
					nodeType.includes("open_interest") ||
					nodeType.includes("oi")
				) {
					addSubchart(
						"open_interest",
						details.oi_actual ??
							details.change ??
							details.oi_change ??
							details.actual ??
							details.value,
					);
				} else if (nodeType.includes("correlation")) {
					addSubchart(
						"correlation",
						details.correlation_actual ??
							details.correlation ??
							details.actual ??
							details.value,
					);
				} else if (nodeType.includes("market_activity")) {
					addSubchart("NATR", details.natr_actual ?? details.natr);
				} else if (nodeType.includes("volume_confirmation")) {
					addMarker("V", result, "volume_confirmation");
				} else if (nodeType.includes("tape")) {
					addMarker("T", result, "tape");
				} else if (nodeType.includes("price_action")) {
					if (Array.isArray(details.markers)) {
						details.markers.forEach((marker: Record<string, unknown>) => {
							addMarkerAt(
								marker.time as number,
								(marker.text as string) || "",
								(marker.position as "aboveBar" | "belowBar" | "inBar") ||
									"inBar",
								(marker.shape as string) || "circle",
								(marker.color as string) || "#4CAF50",
								(marker.type as string) || "price_action_analyzer",
							);
						});
					} else if (result) {
						addMarker("PA", result, "price_action_analyzer");
					}
				} else if (
					nodeType.includes("pattern") ||
					nodeType.includes("classic_pattern")
				) {
					addMarker("P", result, "pattern");
				}

				if (Array.isArray(node.children)) node.children.forEach(traverse);
				if (node.filters_trace) traverse(node.filters_trace);
			};

			traverse(traceRoot);

			return {
				klines: foundationKlines,
				visualizations,
			};
		}, [decisionTrace, klines, trade, entryTime, interval, effectiveInterval]);

	const buildComputedIndicatorSubcharts =
		useCallback((): FoundationChartProps["visualizations"]["subcharts"] => {
			const foundationKlines = normalizeChartKlines(klines);
			if (foundationKlines.length === 0) return {};

			const requested = new Set(usedFoundations);
			const closes = foundationKlines.map((kline) => kline.close);
			const volumes = foundationKlines.map((kline) => kline.volume);
			const subcharts: FoundationChartProps["visualizations"]["subcharts"] = {};

			const addSeries = (
				key: string,
				values: Array<number | null | undefined>,
			) => {
				const series = toSubchartSeries(foundationKlines, values);
				if (series.length > 1) subcharts[key] = series;
			};

			if (requested.has("rsi_condition") || requested.has("trend_direction")) {
				const params = foundationParams.rsi_condition || {};
				const period = Math.max(
					1,
					Math.trunc(toFiniteNumber(params.period ?? params.rsi_period) ?? 14),
				);
				addSeries("RSI", rsiValues(closes, period));
			}

			if (requested.has("macd_condition")) {
				const params = foundationParams.macd_condition || {};
				const fast = Math.max(
					1,
					Math.trunc(toFiniteNumber(params.fast ?? params.fast_period) ?? 12),
				);
				const slow = Math.max(
					fast + 1,
					Math.trunc(toFiniteNumber(params.slow ?? params.slow_period) ?? 26),
				);
				const signal = Math.max(
					1,
					Math.trunc(
						toFiniteNumber(params.signal ?? params.signal_period) ?? 9,
					),
				);
				const fastEma = emaValues(closes, fast);
				const slowEma = emaValues(closes, slow);
				const macdLine = closes.map((_, index) => {
					const fastValue = fastEma[index];
					const slowValue = slowEma[index];
					return fastValue === null || slowValue === null
						? null
						: fastValue - slowValue;
				});
				const signalLine = emaValues(macdLine, signal);
				const histogram = macdLine.map((value, index) => {
					const signalValue = signalLine[index];
					return value === null || signalValue === null
						? null
						: value - signalValue;
				});
				addSeries("MACD_Line", macdLine);
				addSeries("MACD_Signal", signalLine);
				addSeries("MACD_Hist", histogram);
			}

			if (requested.has("stochastic_condition")) {
				const params = foundationParams.stochastic_condition || {};
				const kPeriod = Math.max(
					1,
					Math.trunc(toFiniteNumber(params.k_period ?? params.k) ?? 14),
				);
				const dPeriod = Math.max(
					1,
					Math.trunc(toFiniteNumber(params.d_period ?? params.d) ?? 3),
				);
				const slowing = Math.max(
					1,
					Math.trunc(
						toFiniteNumber(
							params.slowing ?? params.smoothing ?? params.smooth_k,
						) ?? 3,
					),
				);
				const stoch = stochasticValues(
					foundationKlines,
					kPeriod,
					dPeriod,
					slowing,
				);
				addSeries("Stoch_K", stoch.k);
				addSeries("Stoch_D", stoch.d);
			}

			if (requested.has("trend_filter")) {
				const params = foundationParams.trend_filter || {};
				const period = Math.max(
					1,
					Math.trunc(toFiniteNumber(params.period ?? params.adx_period) ?? 14),
				);
				addSeries("ADX", adxValues(foundationKlines, period));
			}

			if (requested.has("volatility_filter")) {
				const params = foundationParams.volatility_filter || {};
				const indicator = String(params.indicator || "ATR").toUpperCase();
				const period = Math.max(
					1,
					Math.trunc(
						toFiniteNumber(
							params.period ?? params.atr_period ?? params.length,
						) ?? 14,
					),
				);
				if (indicator === "BBW") {
					const bbPeriod = Math.max(
						1,
						Math.trunc(
							toFiniteNumber(
								params.bb_period ?? params.period ?? params.length,
							) ?? 20,
						),
					);
					const std =
						toFiniteNumber(params.std ?? params.stddev ?? params.multiplier) ??
						2;
					const bands = bollingerValues(closes, bbPeriod, std);
					const bbw = closes.map((_, index) => {
						const upper = bands.upper[index];
						const middle = bands.middle[index];
						const lower = bands.lower[index];
						return upper === null ||
							middle === null ||
							lower === null ||
							middle === 0
							? null
							: (upper - lower) / middle;
					});
					addSeries("BBW", bbw);
				} else {
					addSeries("ATR", atrValues(foundationKlines, period));
				}
			}

			if (requested.has("natr_filter")) {
				const params = foundationParams.natr_filter || {};
				const period = Math.max(
					1,
					Math.trunc(
						toFiniteNumber(
							params.period ?? params.atr_period ?? params.length,
						) ?? 14,
					),
				);
				const atr = atrValues(foundationKlines, period);
				const natr = atr.map((value, index) =>
					value === null || closes[index] === 0
						? null
						: (value / closes[index]) * 100,
				);
				addSeries("NATR", natr);
			}

			if (requested.has("rel_vol_filter")) {
				const params = foundationParams.rel_vol_filter || {};
				const period = Math.max(
					1,
					Math.trunc(toFiniteNumber(params.period ?? params.lookback) ?? 20),
				);
				const avgVolume = smaValues(volumes, period);
				const relVol = volumes.map((volume, index) => {
					const avg = avgVolume[index];
					return avg === null || avg === 0 ? null : volume / avg;
				});
				addSeries("RelVol", relVol);
			}

			if (requested.has("bollinger_bands_condition")) {
				const params = foundationParams.bollinger_bands_condition || {};
				const period = Math.max(
					1,
					Math.trunc(toFiniteNumber(params.period ?? params.length) ?? 20),
				);
				const std =
					toFiniteNumber(params.std ?? params.stddev ?? params.multiplier) ?? 2;
				const bands = bollingerValues(closes, period, std);
				addSeries("BB_Upper", bands.upper);
				addSeries("BB_Middle", bands.middle);
				addSeries("BB_Lower", bands.lower);
			}

			if (requested.has("ma_crossover") || requested.has("trend_direction")) {
				const params =
					foundationParams.ma_crossover ||
					foundationParams.trend_direction ||
					{};
				const fastPeriod = Math.max(
					1,
					Math.trunc(
						toFiniteNumber(
							params.fast_period ?? params.sma_fast_period ?? params.fast,
						) ?? 9,
					),
				);
				const slowPeriod = Math.max(
					fastPeriod + 1,
					Math.trunc(
						toFiniteNumber(
							params.slow_period ?? params.sma_slow_period ?? params.slow,
						) ?? 21,
					),
				);
				const maType = String(
					params.ma_type || params.type || "EMA",
				).toUpperCase();
				const fastValues =
					maType === "SMA"
						? smaValues(closes, fastPeriod)
						: emaValues(closes, fastPeriod);
				const slowValues =
					maType === "SMA"
						? smaValues(closes, slowPeriod)
						: emaValues(closes, slowPeriod);
				addSeries("MA_Fast", fastValues);
				addSeries("MA_Slow", slowValues);
			}

			return subcharts;
		}, [klines, usedFoundations, foundationParams]);

	// Load foundation visualization data
	const loadFoundationData = useCallback(async () => {
		if (!showIndicators || !trade.symbol || !exitTime) {
			setFoundationData(null);
			return;
		}

		setFoundationLoading(true);
		try {
			const traceData = buildTraceFoundationData();
			const computedSubcharts = buildComputedIndicatorSubcharts();
			const fallbackKlines = traceData?.klines || normalizeChartKlines(klines);
			const traceVisualizations = traceData?.visualizations || {
				levels: [],
				markers: [],
				zones: [],
				subcharts: {},
			};

			if (runId) {
				setFoundationData({
					klines: fallbackKlines,
					visualizations: {
						...traceVisualizations,
						subcharts: {
							...traceVisualizations.subcharts,
							...computedSubcharts,
						},
					},
				});
				return;
			}

			if (usedFoundations.length > 0) {
				try {
					const intervalSec = timeframeToSeconds(effectiveInterval);
					const startDate = new Date(
						Math.max(0, entryTime - intervalSec * 200) * 1000,
					).toISOString();
					const endDate = new Date(
						(exitTime + intervalSec * 50) * 1000,
					).toISOString();
					const queryParams = new URLSearchParams({
						symbol: trade.symbol,
						timeframe: effectiveInterval,
						foundations: usedFoundations.join(","),
						params: JSON.stringify(foundationParams),
						start_date: startDate,
						end_date: endDate,
					});
					const previewData = await apiClient<FoundationChartProps>(
						`/diagnostics/preview-foundation?${queryParams.toString()}`,
					);

					setFoundationData({
						klines: previewData.klines?.length
							? previewData.klines
							: fallbackKlines,
						visualizations: {
							levels: traceVisualizations.levels,
							markers: traceVisualizations.markers,
							zones: traceVisualizations.zones,
							subcharts: {
								...traceVisualizations.subcharts,
								...computedSubcharts,
								...(previewData.visualizations?.subcharts || {}),
							},
						},
					});
					return;
				} catch (previewError) {
					console.warn(
						"Failed to load foundation preview, falling back to decision trace:",
						previewError,
					);
				}
			}

			setFoundationData({
				klines: fallbackKlines,
				visualizations: {
					...traceVisualizations,
					subcharts: {
						...traceVisualizations.subcharts,
						...computedSubcharts,
					},
				},
			});
		} catch (err) {
			console.error("Failed to build trace foundation data:", err);
			setFoundationData(null);
		} finally {
			setFoundationLoading(false);
		}
	}, [
		showIndicators,
		trade.symbol,
		exitTime,
		runId,
		usedFoundations,
		effectiveInterval,
		entryTime,
		foundationParams,
		buildTraceFoundationData,
		buildComputedIndicatorSubcharts,
		klines,
	]);

	// Load foundation data when toggle is enabled
	useEffect(() => {
		if (showIndicators) {
			loadFoundationData();
		} else {
			setFoundationData(null);
		}
	}, [showIndicators, loadFoundationData]);

	// State for rendering
	const [, setCrosshairTime] = useState<number | null>(null);
	const crosshairTimeRef = useRef<number | null>(null); // Keep ref for performant access in syncOverlay or similar

	// Update state only if changed to avoid excessive re-render loops if not needed,
	// but here we want to update the UI on hover.
	// Debouncing might be needed if performance suffers, but for now direct update.

	// Helper to determining indicator color
	const getIndicatorColor = useCallback((key: string, value?: number) => {
		// Histogram Logic
		if (key.includes("Hist")) {
			return (value ?? 0) >= 0 ? "#22c55e" : "#ef4444";
		}

		// Line Logic
		if (key.includes("MACD_Line")) return "#2962FF";
		if (key.includes("MACD_Signal")) return "#FF6D00";
		if (key.includes("RSI")) return "#E91E63";
		if (key.includes("Stoch_K")) return "#2962FF";
		if (key.includes("Stoch_D")) return "#FF6D00";
		if (key === "ADX") return "#22c55e";
		if (key === "ATR" || key.includes("NATR")) return "#9C27B0";
		if (key.toLowerCase().includes("relvol")) return "#00BCD4";

		// Overlays
		if (key.includes("upper")) return "#2962FF";
		if (key.includes("lower")) return "#2962FF";
		if (key.includes("middle") || key.includes("basis")) return "#FF9800";
		if (key.includes("ma_") || key.includes("sma") || key.includes("ema"))
			return "#FF9800";

		return "#78909C"; // Default
	}, []);

	// Sync overlay with chart
	const syncOverlay = useCallback(() => {
		if (
			!overlayRef.current ||
			!chartRef.current ||
			!seriesRef.current ||
			klines.length === 0
		)
			return;

		const overlay = overlayRef.current;
		overlay.innerHTML = "";

		const chart = chartRef.current;
		const series = seriesRef.current;
		const currentKlines =
			showIndicators && foundationData ? foundationData.klines : klines;
		let entryLabelY: number | null = null;
		let exitLabelY: number | null = null;

		// Get chart width for drawing lines to edge
		const chartWidth = chartContainerRef.current?.clientWidth || 800;
		const chartHeight = chartContainerRef.current?.clientHeight || 500;

		// Helper for snapping timestamps to candle centers
		const intervalSec = timeframeToSeconds(effectiveInterval);
		const getSnappedTime = (t: number) => {
			const candle = currentKlines.find((k) => {
				const kt = k.time > 1000000000 ? Math.floor(k.time / 1000) : k.time;
				return t >= kt && t < kt + intervalSec;
			});
			return candle
				? candle.time > 1000000000
					? Math.floor(candle.time / 1000)
					: candle.time
				: t;
		};

		const timeToOverlayCoordinate = (targetTimeSec: number): number | null => {
			const exactX = chart.timeScale().timeToCoordinate(targetTimeSec as Time);
			if (exactX !== null) return exactX;
			if (!currentKlines || currentKlines.length === 0) return null;

			const klineTimes = Array.from(
				new Set(
					currentKlines
						.map((kline) => getKlineTimeSeconds(kline.time))
						.filter((time) => Number.isFinite(time)),
				),
			).sort((a, b) => a - b);

			if (klineTimes.length === 0) return null;

			let barIndex = -1;
			for (let i = 0; i < klineTimes.length; i += 1) {
				if (klineTimes[i] <= targetTimeSec) {
					barIndex = i;
				} else {
					break;
				}
			}

			if (barIndex < 0) barIndex = 0;

			const barTime = klineTimes[barIndex];
			const barX = chart.timeScale().timeToCoordinate(barTime as Time);
			if (barX === null) return null;

			const nextTime = klineTimes[barIndex + 1];
			const prevTime = klineTimes[barIndex - 1];
			const nextX =
				nextTime !== undefined
					? chart.timeScale().timeToCoordinate(nextTime as Time)
					: null;
			const prevX =
				prevTime !== undefined
					? chart.timeScale().timeToCoordinate(prevTime as Time)
					: null;

			if (nextTime !== undefined && nextX !== null && nextTime > barTime) {
				const progress = Math.max(
					0,
					Math.min(1, (targetTimeSec - barTime) / (nextTime - barTime)),
				);
				return barX + (nextX - barX) * progress;
			}

			if (prevTime !== undefined && prevX !== null && barTime > prevTime) {
				const progress = Math.max(
					0,
					Math.min(1, (targetTimeSec - barTime) / (barTime - prevTime)),
				);
				return barX + (barX - prevX) * progress;
			}

			return barX;
		};

		// Draw entry point and line
		if (entryPrice > 0) {
			const snappedEntryTime = getSnappedTime(entryTime);
			const entryX = timeToOverlayCoordinate(snappedEntryTime);
			const entryY = series.priceToCoordinate(entryPrice);
			entryLabelY = entryY;

			if (entryX !== null && entryY !== null) {
				// Entry horizontal line (from point to right edge)
				const entryLine = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"line",
				);
				entryLine.setAttribute("x1", String(entryX));
				entryLine.setAttribute("y1", String(entryY));
				entryLine.setAttribute("x2", String(chartWidth - 60)); // Leave space for price axis
				entryLine.setAttribute("y2", String(entryY));
				entryLine.setAttribute("stroke", "#22c55e");
				entryLine.setAttribute("stroke-width", "1");
				entryLine.setAttribute("stroke-dasharray", "4,4");
				overlay.appendChild(entryLine);

				// Entry circle
				const circle = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"circle",
				);
				circle.setAttribute("cx", String(entryX));
				circle.setAttribute("cy", String(entryY));
				circle.setAttribute("r", "6");
				circle.setAttribute("fill", "#22c55e");
				circle.setAttribute("stroke", "#fff");
				circle.setAttribute("stroke-width", "2");
				overlay.appendChild(circle);
			}
		}

		// Draw exit point and line
		if (exitPrice > 0) {
			const snappedExitTime = getSnappedTime(exitTime);
			const exitX = timeToOverlayCoordinate(snappedExitTime);
			const exitY = series.priceToCoordinate(exitPrice);
			exitLabelY = exitY;

			if (exitX !== null && exitY !== null) {
				// Exit horizontal line (from point to right edge)
				const exitLine = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"line",
				);
				exitLine.setAttribute("x1", String(exitX));
				exitLine.setAttribute("y1", String(exitY));
				exitLine.setAttribute("x2", String(chartWidth - 60));
				exitLine.setAttribute("y2", String(exitY));
				exitLine.setAttribute("stroke", "#ef4444");
				exitLine.setAttribute("stroke-width", "1");
				exitLine.setAttribute("stroke-dasharray", "4,4");
				overlay.appendChild(exitLine);

				// Exit circle
				const circle = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"circle",
				);
				circle.setAttribute("cx", String(exitX));
				circle.setAttribute("cy", String(exitY));
				circle.setAttribute("r", "6");
				circle.setAttribute("fill", "#ef4444");
				circle.setAttribute("stroke", "#fff");
				circle.setAttribute("stroke-width", "2");
				overlay.appendChild(circle);
			}
		}

		// Draw Executions (E1, X1 etc)
		normalizedExecutions.forEach((exec) => {
			const isEntry = exec.type === "ENTRY";
			const isArrowUp = isEntry ? isLong : !isLong;

			// SNAP to candle center to prevent sliding on large timeframes
			const snapTime = getSnappedTime(exec.timestampSec);
			const x = timeToOverlayCoordinate(snapTime);
			const y = series.priceToCoordinate(exec.price);

			if (x !== null && y !== null) {
				const color = isEntry ? "#22c55e" : "#ef4444";

				// Price level line
				const line = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"line",
				);
				line.setAttribute("x1", "0");
				line.setAttribute("y1", String(y));
				line.setAttribute("x2", String(chartWidth - 60));
				line.setAttribute("y2", String(y));
				line.setAttribute("stroke", color);
				line.setAttribute("stroke-width", "1");
				line.setAttribute("stroke-dasharray", "4,4");
				line.setAttribute("opacity", "0.4");
				overlay.appendChild(line);

				// Shape - Triangle pointing to the price
				const shape = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"path",
				);
				const d = isArrowUp
					? `M ${x} ${y + 5} L ${x - 7} ${y + 18} L ${x + 7} ${y + 18} Z` // Below price, pointing UP
					: `M ${x} ${y - 5} L ${x - 7} ${y - 18} L ${x + 7} ${y - 18} Z`; // Above price, pointing DOWN

				shape.setAttribute("d", d);
				shape.setAttribute("fill", color);
				shape.setAttribute("stroke", "white");
				shape.setAttribute("stroke-width", "1");
				overlay.appendChild(shape);

				// Execution Label (E1, X1 etc)
				const labelText = `${isEntry ? "E" : "X"}${exec.sideIndex}`;
				const label = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"text",
				);
				const labelY = isArrowUp ? y + 30 : y - 22; // Position text relative to triangle

				label.setAttribute("x", String(x));
				label.setAttribute("y", String(labelY));
				label.setAttribute("text-anchor", "middle");
				label.setAttribute("fill", color);
				label.setAttribute("font-size", "10px");
				label.setAttribute("font-weight", "bold");
				label.setAttribute("stroke", "rgba(0,0,0,0.8)");
				label.setAttribute("stroke-width", "3");
				label.setAttribute("paint-order", "stroke");
				label.textContent = labelText;
				overlay.appendChild(label);
			}
		});

		// Draw percentage label between entry and exit (no vertical line)
		if (
			entryLabelY !== null &&
			exitLabelY !== null &&
			entryPrice > 0 &&
			exitPrice > 0
		) {
			const rightEdgeX = chartWidth - 120; // Move left to not overlap with price scale
			const isProfit = realizedPnl >= 0;

			// Calculate percentage
			const priceDiff = exitPrice - entryPrice;
			const percentDiff = (priceDiff / entryPrice) * 100;
			const adjustedPercent = isLong ? percentDiff : -percentDiff;

			// Percentage label with background
			const midY = (entryLabelY + exitLabelY) / 2;

			// Background rect for percentage
			const bgRect = document.createElementNS(
				"http://www.w3.org/2000/svg",
				"rect",
			);
			bgRect.setAttribute("x", String(rightEdgeX - 30));
			bgRect.setAttribute("y", String(midY - 10));
			bgRect.setAttribute("width", "60");
			bgRect.setAttribute("height", "20");
			bgRect.setAttribute(
				"fill",
				isProfit ? "rgba(34, 197, 94, 0.9)" : "rgba(239, 68, 68, 0.9)",
			);
			bgRect.setAttribute("rx", "4");
			overlay.appendChild(bgRect);

			const text = document.createElementNS(
				"http://www.w3.org/2000/svg",
				"text",
			);
			text.setAttribute("x", String(rightEdgeX - 25));
			text.setAttribute("y", String(midY + 4));
			text.setAttribute("fill", "white");
			text.setAttribute("font-size", "11px");
			text.setAttribute("font-weight", "bold");
			text.textContent = `${adjustedPercent >= 0 ? "+" : ""}${adjustedPercent.toFixed(2)}%`;
			overlay.appendChild(text);
		}

		// Draw ruler if active
		if (isRulerActive && rulerStartRef.current && rulerCurrentRef.current) {
			const start = rulerStartRef.current;
			const current = rulerCurrentRef.current;

			// Line
			const line = document.createElementNS(
				"http://www.w3.org/2000/svg",
				"line",
			);
			line.setAttribute("x1", String(start.x));
			line.setAttribute("y1", String(start.y));
			line.setAttribute("x2", String(current.x));
			line.setAttribute("y2", String(current.y));
			line.setAttribute("stroke", "#2962FF");
			line.setAttribute("stroke-width", "2");
			line.setAttribute("stroke-dasharray", "5,5");
			overlay.appendChild(line);

			// Calculate percent diff
			const priceDiff = current.price - start.price;
			const percentDiff = (priceDiff / start.price) * 100;

			// Background rect
			const rect = document.createElementNS(
				"http://www.w3.org/2000/svg",
				"rect",
			);
			rect.setAttribute("x", String(current.x + 10));
			rect.setAttribute("y", String(current.y - 15));
			rect.setAttribute("width", "130");
			rect.setAttribute("height", "30");
			rect.setAttribute("fill", "rgba(41, 98, 255, 0.9)");
			rect.setAttribute("rx", "4");
			overlay.appendChild(rect);

			// Text
			const text = document.createElementNS(
				"http://www.w3.org/2000/svg",
				"text",
			);
			text.setAttribute("x", String(current.x + 18));
			text.setAttribute("y", String(current.y + 5));
			text.setAttribute("fill", "white");
			text.setAttribute("font-size", "12px");
			const percentDiffStr = Number.isFinite(percentDiff) ? percentDiff.toFixed(2) : "0.00";
			const priceDiffStr = Number.isFinite(priceDiff) ? priceDiff.toFixed(4) : "0.0000";
			text.textContent = `${percentDiff > 0 ? "+" : ""}${percentDiffStr}% ($${priceDiffStr})`;
			overlay.appendChild(text);
		}

		// Draw "Conditions Plaque" (Static Summary) if indicators are shown
		if (showIndicators && extractedIndicators) {
			const annotations: { text: string; color: string }[] = [];

			extractedIndicators.stoch.forEach((s) => {
				const status = s.result ? "✓" : "✗";
				annotations.push({
					text: `Stoch: K=${formatFiniteNumber(s.k, 1)} D=${formatFiniteNumber(s.d, 1)} ${status}`,
					color: s.result ? "#22c55e" : "#ef4444",
				});
			});
			extractedIndicators.rsi.forEach((r) => {
				const status = r.result ? "✓" : "✗";
				annotations.push({
					text: `RSI: ${formatFiniteNumber(r.value, 1)} ${status}`,
					color: r.result ? "#22c55e" : "#ef4444",
				});
			});
			extractedIndicators.adx.forEach((a) => {
				const status = a.result ? "✓" : "✗";
				annotations.push({
					text: `ADX: ${formatFiniteNumber(a.value, 1)} ${status}`,
					color: a.result ? "#22c55e" : "#ef4444",
				});
			});
			extractedIndicators.natr.forEach((n) => {
				const status = n.result ? "✓" : "✗";
				annotations.push({
					text: `NATR: ${formatFiniteNumber(n.value, 2)}% ${status}`,
					color: n.result ? "#22c55e" : "#ef4444",
				});
			});
			extractedIndicators.bbBands.forEach((bb) => {
				const status = bb.result ? "✓" : "✗";
				annotations.push({
					text: `BB: U=${formatFiniteNumber(bb.upper, 2)} L=${formatFiniteNumber(bb.lower, 2)} ${status}`,
					color: bb.result ? "#22c55e" : "#ef4444",
				});
			});
			// Simplified others
			const addSimple = (label: string, result: boolean) => {
				annotations.push({
					text: `${label} ${result ? "✓" : "✗"}`,
					color: result ? "#22c55e" : "#ef4444",
				});
			};
			extractedIndicators.timeFilter.forEach((tf) => {
				addSimple("Time", tf.result);
			});

			if (annotations.length > 0) {
				const boxX = 15;
				const boxY = 15;
				const lineHeight = 14;
				const boxHeight = annotations.length * lineHeight + 12;
				const boxWidth = 180;

				// Background
				const bg = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"rect",
				);
				bg.setAttribute("x", String(boxX));
				bg.setAttribute("y", String(boxY));
				bg.setAttribute("width", String(boxWidth));
				bg.setAttribute("height", String(boxHeight));
				bg.setAttribute("fill", "rgba(0, 0, 0, 0.8)");
				bg.setAttribute("rx", "6");
				bg.setAttribute("stroke", "#3B82F6");
				bg.setAttribute("stroke-width", "1");
				overlay.appendChild(bg);

				// Text lines
				annotations.forEach((ann, idx) => {
					const txt = document.createElementNS(
						"http://www.w3.org/2000/svg",
						"text",
					);
					txt.setAttribute("x", String(boxX + 8));
					txt.setAttribute("y", String(boxY + 14 + idx * lineHeight));
					txt.setAttribute("fill", ann.color);
					txt.setAttribute("font-size", "11px");
					txt.setAttribute("font-family", "monospace");
					txt.setAttribute("font-weight", "500");
					txt.textContent = ann.text;
					overlay.appendChild(txt);
				});
			}
		}

		// Draw Decision Zones (Consolidation Boxes) from Foundation Data
		if (showIndicators && foundationData?.visualizations?.zones) {
			const chart = chartRef.current;
			const series = seriesRef.current;
			if (chart && series) {
				foundationData.visualizations.zones.forEach((zone) => {
					const sTime = zone.startTime ?? zone.start_time ?? 0;
					const eTime = zone.endTime ?? zone.end_time ?? 0;

					const x1 = timeToOverlayCoordinate(Number(sTime));
					const x2 = timeToOverlayCoordinate(Number(eTime));

					if (x1 === null && x2 === null) return;

					// Use provided prices or fallback to entryPrice area
					const zoneRec = zone as Record<string, unknown>;
					const level =
						(zoneRec.detectedLevel as number) ??
						(zoneRec.price as number) ??
						entryPrice ??
						0;
					const topP = (zoneRec.top_price as number) ?? level * 1.0025;
					const botP = (zoneRec.bottom_price as number) ?? level * 0.9975;

					const yTop = series.priceToCoordinate(topP);
					const yBottom = series.priceToCoordinate(botP);

					if (yTop !== null && yBottom !== null) {
						const isConsolidation = zone.type === "price_consolidation";
						const rect = document.createElementNS(
							"http://www.w3.org/2000/svg",
							"rect",
						);
						const finalX1 = x1 !== null ? x1 : 0;
						const finalX2 = x2 !== null ? x2 : chartWidth - 60;

						rect.setAttribute("x", String(Math.min(finalX1, finalX2)));
						rect.setAttribute(
							"width",
							String(Math.max(2, Math.abs(finalX2 - finalX1))),
						);

						if (isConsolidation) {
							// Subtle shadow from price to bottom
							rect.setAttribute("y", String(yTop));
							rect.setAttribute("height", String(chartHeight - yTop));
							rect.setAttribute("rx", "0");
							rect.setAttribute("fill", "rgba(128, 128, 128, 0.12)");
							rect.setAttribute("stroke", "none");
						} else {
							rect.setAttribute("y", String(Math.min(yTop, yBottom)));
							rect.setAttribute(
								"height",
								String(Math.max(6, Math.abs(yBottom - yTop))),
							);
							rect.setAttribute("rx", "4");

							const lowerLabel = zone.label.toLowerCase();
							const color =
								zone.color ||
								(lowerLabel.includes("long")
									? "rgba(34, 197, 94, 0.4)"
									: lowerLabel.includes("short")
										? "rgba(239, 68, 68, 0.4)"
										: "rgba(251, 191, 36, 0.5)");

							rect.setAttribute("fill", color);
							rect.setAttribute(
								"stroke",
								color.replace("0.4", "0.8").replace("0.5", "0.9"),
							);
							rect.setAttribute("stroke-width", "2");
						}

						overlay.appendChild(rect);

						// Add label if it's wide enough AND not a consolidation (which now uses a pillar)
						if (!isConsolidation && Math.abs(finalX2 - finalX1) > 40) {
							const text = document.createElementNS(
								"http://www.w3.org/2000/svg",
								"text",
							);
							text.setAttribute("x", String(Math.min(finalX1, finalX2) + 6));
							text.setAttribute("y", String(Math.min(yTop, yBottom) + 14));
							text.setAttribute("fill", "white");
							text.setAttribute("font-size", "11px");
							text.setAttribute("font-weight", "800");
							text.setAttribute("style", "text-shadow: 1px 1px 2px black;");
							text.textContent = zone.label.replace("DECISION: ", "");
							overlay.appendChild(text);
						}
					}
				});
			}
		}
	}, [
		klines,
		entryPrice,
		exitPrice,
		entryTime,
		exitTime,
		effectiveInterval,
		isRulerActive,
		showIndicators,
		extractedIndicators,
		foundationData,
		realizedPnl,
		isLong,
		normalizedExecutions,
	]);

	// Force sync overlay when foundation data arrives or chart is ready
	useEffect(() => {
		if (foundationData || klines.length > 0) {
			setTimeout(syncOverlay, 100); // Small delay to ensure chart internal state is ready
		}
	}, [foundationData, klines, syncOverlay]);

	const handleScreenshot = async () => {
		if (!modalContentRef.current) return;

		setIsCapturing(true);
		try {
			const canvas = await html2canvas(modalContentRef.current, {
				backgroundColor: "#0a0a0a", // Match theme background
				scale: 2, // Higher resolution
				useCORS: true,
				logging: false,
			});

			canvas.toBlob(async (blob) => {
				if (!blob) throw new Error("Failed to generate image");

				try {
					await navigator.clipboard.write([
						new ClipboardItem({ "image/png": blob }),
					]);
					toast.success(
						t("screenshotCopied", "Screenshot copied to clipboard"),
					);
				} catch (clipError) {
					// Fallback for browsers that don't support direct clipboard write
					console.error("Clipboard write error:", clipError);
					toast.error(t("screenshotFailed", "Failed to copy to clipboard"));
				}
			}, "image/png");
		} catch (err) {
			console.error("Screenshot error:", err);
			toast.error(t("screenshotFailed", "Failed to take screenshot"));
		} finally {
			setIsCapturing(false);
		}
	};

	// Load klines data
	const loadPriceAction = useCallback(async () => {
		if (!trade.symbol || !entryTime || !exitTime) {
			setLoading(false);
			setError("Invalid trade data");
			return;
		}

		setLoading(true);
		setError(null);

		try {
			// Fetch tick size if not provided
			if (!tickSize) {
				const cleanSymbol = trade.symbol.toUpperCase().replace(/[^a-zA-Z0-9]/g, "");
				const isBybit = String(trade.exchange || "").toLowerCase().includes("bybit");
				if (isBybit) {
					fetchBybitSymbolInfo(trade.symbol).then((info) => {
						if (info && info.result && info.result.list && info.result.list[0]) {
							const symbolInfo = info.result.list[0];
							if (symbolInfo.priceFilter && symbolInfo.priceFilter.tickSize) {
								setTickSize(parseFloat(symbolInfo.priceFilter.tickSize));
							}
						}
					}).catch((err) => {
						console.warn("Failed to fetch Bybit symbol info, falling back to Binance", err);
						fetchSymbolInfo(trade.symbol).then((binanceInfo) => {
							if (binanceInfo && binanceInfo.symbols) {
								const symbolInfo = binanceInfo.symbols.find(
									(s: any) => s.symbol.toUpperCase() === cleanSymbol,
								);
								if (symbolInfo) {
									const priceFilter = symbolInfo.filters.find(
										(f: any) => f.filterType === "PRICE_FILTER",
									);
									if (priceFilter && priceFilter.tickSize) {
										setTickSize(parseFloat(priceFilter.tickSize));
									}
								}
							}
						});
					});
				} else {
					fetchSymbolInfo(trade.symbol).then((info) => {
						if (info && info.symbols) {
							const symbolInfo = info.symbols.find(
								(s: any) => s.symbol.toUpperCase() === cleanSymbol,
							);
							if (symbolInfo) {
								const priceFilter = symbolInfo.filters.find(
									(f: any) => f.filterType === "PRICE_FILTER",
								);
								if (priceFilter && priceFilter.tickSize) {
									setTickSize(parseFloat(priceFilter.tickSize));
								}
							}
						}
					}).catch((err) => {
						console.warn("Failed to fetch Binance symbol info, falling back to Bybit", err);
						fetchBybitSymbolInfo(trade.symbol).then((bybitInfo) => {
							if (bybitInfo && bybitInfo.result && bybitInfo.result.list && bybitInfo.result.list[0]) {
								const symbolInfo = bybitInfo.result.list[0];
								if (symbolInfo.priceFilter && symbolInfo.priceFilter.tickSize) {
									setTickSize(parseFloat(symbolInfo.priceFilter.tickSize));
								}
							}
						});
					});
				}
			}

			let data: Kline[];

			const intervalToUse = interval || effectiveInterval;

			// Calculate buffer: 200 candles before, 50 after
			const getIntervalMs = (tf: string): number => {
				const unit = tf.slice(-1);
				const val = parseInt(tf, 10);
				if (unit === "m") return val * 60 * 1000;
				if (unit === "h") return val * 60 * 60 * 1000;
				if (unit === "d") return val * 24 * 60 * 60 * 1000;
				return 60 * 1000;
			};

			const bufferMs = getIntervalMs(intervalToUse);
			const startTime = entryTime * 1000 - bufferMs * 200;
			const endTime = Math.min(Date.now(), exitTime * 1000 + bufferMs * 50);

			if (runId) {
				// Fetch from our API if runId is provided
				const queryParams = new URLSearchParams({
					timeframe: intervalToUse,
					start_time: Math.floor(startTime).toString(),
					end_time: Math.floor(endTime).toString(),
				});
				const response = await apiClient<unknown[][]>(
					`/backtests/${runId}/klines?${queryParams.toString()}`,
				);
				data = response.map((d) => ({
					time: Number(d[0]),
					open: Number(d[1]),
					high: Number(d[2]),
					low: Number(d[3]),
					close: Number(d[4]),
					volume: Number(d[5] || 0),
				}));
			} else {
				const isBybit = String(trade.exchange || "").toLowerCase().includes("bybit");
				if (isBybit) {
					data = await fetchBybitKlines(
						trade.symbol,
						startTime,
						endTime,
						intervalToUse,
					);
					if (data.length === 0) {
						// Fallback to Binance
						data = await fetchKlines(
							trade.symbol,
							startTime,
							endTime,
							intervalToUse,
						);
					}
				} else {
					data = await fetchKlines(
						trade.symbol,
						startTime,
						endTime,
						intervalToUse,
					);
					if (data.length === 0) {
						// Fallback to Bybit
						data = await fetchBybitKlines(
							trade.symbol,
							startTime,
							endTime,
							intervalToUse,
						);
					}
				}
			}

			if (data.length === 0) {
				setError("No market data available for this period");
				setLoading(false);
				return;
			}

			setKlines(data);
		} catch (err) {
			console.error("Failed to load klines:", err);
			setError("Failed to fetch market data");
		} finally {
			setLoading(false);
		}
	}, [trade.symbol, trade.exchange, entryTime, exitTime, interval, effectiveInterval, runId]);

	useEffect(() => {
		loadPriceAction();
	}, [loadPriceAction]);

	// Initialize charts (Main + Indicators)
	useEffect(() => {
		if (!chartContainerRef.current || klines.length === 0) return;

		// --- 1. Create Main Chart ---
		// If showIndicators is TRUE, the main chart is 65% height. Otherwise 100%.
		// We rely on the ResizeObserver to adjust the internal canvas size, but we need initial dimensions.
		const container = chartContainerRef.current;
		const initialWidth = container.clientWidth || 800;
		const initialHeight = container.clientHeight || 500;

		const mainChart = createChart(container, {
			width: initialWidth,
			height: initialHeight,
			layout: {
				textColor: "#9ca3af",
				background: { type: ColorType.Solid, color: "#0a0a0a" },
			},
			grid: {
				vertLines: { color: "#27272a" },
				horzLines: { color: "#27272a" },
			},
			crosshair: { mode: CrosshairMode.Normal },
			timeScale: {
				borderColor: "#27272a",
				timeVisible: true,
				secondsVisible: false,
			},
			rightPriceScale: {
				borderColor: "#27272a",
				minimumWidth: 60, // Ensure alignment with bottom chart if present
			},
		});

		chartRef.current = mainChart;

		// Add ResizeObserver for Main Chart
		const resizeObserverMain = new ResizeObserver((entries) => {
			if (!mainChart || !container) return;
			const entry = entries[0];
			if (entry) {
				const w = Math.floor(entry.contentRect.width);
				const h = Math.floor(entry.contentRect.height);
				if (w > 0 && h > 0) {
					mainChart.resize(w, h);
					syncOverlay();
				}
			}
		});
		resizeObserverMain.observe(container);

		// Helper to calculate auto-scale range with padding
		const autoScaleProvider = (original: () => AutoscaleInfo | null) => {
			const res = original();
			if (res?.priceRange) {
				let { minValue, maxValue } = res.priceRange;

				// Ensure entry/exit are visible
				if (entryPrice > 0) {
					minValue = Math.min(minValue, entryPrice);
					maxValue = Math.max(maxValue, entryPrice);
				}
				if (exitPrice > 0) {
					minValue = Math.min(minValue, exitPrice);
					maxValue = Math.max(maxValue, exitPrice);
				}

				// Ensure trace levels are visible
				extractedIndicators.localLevels.forEach((lvl) => {
					if (lvl.price) {
						minValue = Math.min(minValue, lvl.price);
						maxValue = Math.max(maxValue, lvl.price);
					}
				});
				extractedIndicators.significantLevels.forEach((lvl) => {
					if (lvl.price) {
						minValue = Math.min(minValue, lvl.price);
						maxValue = Math.max(maxValue, lvl.price);
					}
				});

				executionPrices.forEach((price) => {
					minValue = Math.min(minValue, price);
					maxValue = Math.max(maxValue, price);
				});

				const range = maxValue - minValue;
				const padding =
					range > 0 ? range * 0.1 : Math.max(Math.abs(maxValue) * 0.005, 1);
				return {
					priceRange: {
						minValue: minValue - padding,
						maxValue: maxValue + padding,
					},
				};
			}
			return res;
		};

		const effectiveTickSize = tickSize || estimateTickSize(klines);
		// Series
		const candlestickSeries = mainChart.addSeries(CandlestickSeries, {
			upColor: "#22c55e",
			downColor: "#ef4444",
			borderVisible: false,
			wickUpColor: "#22c55e",
			wickDownColor: "#ef4444",
			autoscaleInfoProvider: autoScaleProvider,
			priceFormat: {
				type: "price",
				precision: Math.ceil(Math.max(0, -Math.log10(effectiveTickSize))),
				minMove: effectiveTickSize,
			},
		});

		seriesRef.current = candlestickSeries;

		// SVG Overlay
		const existingOverlay =
			chartContainerRef.current.querySelector("svg.trade-overlay");
		if (existingOverlay) existingOverlay.remove();
		const svgOverlay = document.createElementNS(
			"http://www.w3.org/2000/svg",
			"svg",
		);
		svgOverlay.classList.add("trade-overlay");
		Object.assign(svgOverlay.style, {
			position: "absolute",
			top: "0",
			left: "0",
			width: "100%",
			height: "100%",
			pointerEvents: "none",
			zIndex: "10",
			overflow: "visible",
		});
		chartContainerRef.current.style.position = "relative";
		chartContainerRef.current.appendChild(svgOverlay);
		overlayRef.current = svgOverlay;

		// Data Preparation
		const sortedKlines = [
			...(showIndicators && foundationData ? foundationData.klines : klines),
		].sort((a, b) => Number(a.time) - Number(b.time));
		const uniqueKlines = sortedKlines.filter(
			(k, i, arr) => i === 0 || k.time > arr[i - 1].time,
		);
		const chartData: CandlestickData[] = uniqueKlines.map((k) => ({
			time: (k.time > 1000000000000
				? Math.floor(k.time / 1000)
				: k.time) as Time,
			open: k.open,
			high: k.high,
			low: k.low,
			close: k.close,
		}));
		candlestickSeries.setData(chartData);

		// Add Volume Series to Main Chart
		const volumeSeries = mainChart.addSeries(HistogramSeries, {
			priceFormat: { type: "volume" },
			priceScaleId: "volume_pane",
		});

		mainChart.priceScale("volume_pane").applyOptions({
			scaleMargins: {
				top: 0.8,
				bottom: 0,
			},
			visible: false,
		});

		const volumeData = uniqueKlines
			.map((k) => ({
				time: (k.time > 1000000000000
					? Math.floor(k.time / 1000)
					: k.time) as Time,
				value: Number((k as Record<string, unknown>).volume || 0),
				color:
					k.close >= k.open
						? "rgba(34, 197, 94, 0.5)"
						: "rgba(239, 68, 68, 0.5)",
			}))
			.sort((a, b) => (a.time as number) - (b.time as number));

		volumeSeries.setData(volumeData);

		const foundationSeriesMarkers = createSeriesMarkers(candlestickSeries);

		// --- 2. Indicators Logic ---
		let indChart: IChartApi | null = null;
		let resizeObserverInd: ResizeObserver | null = null;

		if (showIndicators && foundationData) {
			const viz = foundationData.visualizations;

			if (Array.isArray(viz.markers) && viz.markers.length > 0) {
				foundationSeriesMarkers.setMarkers(
					viz.markers
						.map((marker: Record<string, unknown>) => ({
							...marker,
							time: (Number(marker.time) > 1000000000000
								? Math.floor(Number(marker.time) / 1000)
								: Number(marker.time)) as Time,
						}))
						.sort(
							(a: Record<string, unknown>, b: Record<string, unknown>) =>
								Number(a.time) - Number(b.time),
						),
				);
			}

			// Zones and Levels are drawn on SVG overlay for maximum visibility and stability
			viz.levels.forEach((lvl: LevelData) => {
				candlestickSeries.createPriceLine({
					price: lvl.price,
					color: lvl.color || "#3B82F6",
					lineWidth: 2,
					lineStyle: LineStyle.Dashed,
					axisLabelVisible: true,
					title: lvl.label,
				});
			});

			// We removed AreaSeries zones here as they are now handled by syncOverlay on SVG

			// Split Subcharts
			const subchartKeys = viz.subcharts ? Object.keys(viz.subcharts) : [];
			const overlayKeys: string[] = [];
			const indicatorPaneKeys: string[] = [];

			subchartKeys.forEach((key) => {
				const lowerKey = key.toLowerCase();
				if (
					lowerKey.includes("bb") ||
					lowerKey.includes("bollinger") ||
					lowerKey.includes("ma_") ||
					lowerKey.includes("sma") ||
					lowerKey.includes("ema")
				) {
					overlayKeys.push(key);
				} else {
					indicatorPaneKeys.push(key);
				}
			});

			// Overlays on Main Chart
			overlayKeys.forEach((key) => {
				const data = viz.subcharts[key];
				if (!data || data.length === 0) return;
				const series = mainChart.addSeries(LineSeries, {
					color: getIndicatorColor(key),
					lineWidth: 1,
					title: key,
					priceScaleId: "right",
					autoscaleInfoProvider: autoScaleProvider,
				});
				series.setData(
					data
						.map((d: Record<string, unknown>) => ({
							time: (Number(d.time) > 1000000000000
								? Math.floor(Number(d.time) / 1000)
								: Number(d.time)) as Time,
							value: Number(d.value),
						}))
						.sort(
							(a: { time: number }, b: { time: number }) => a.time - b.time,
						),
				);
			});

			// --- 3. Create Indicator Chart (if needed) ---
			if (indicatorContainerRef.current && indicatorPaneKeys.length > 0) {
				const indContainer = indicatorContainerRef.current;
				const initialIndWidth = indContainer.clientWidth || 800;
				const initialIndHeight = indContainer.clientHeight || 180;
				indChart = createChart(indContainer, {
					width: initialIndWidth,
					height: initialIndHeight,
					layout: {
						textColor: "#9ca3af",
						background: { type: ColorType.Solid, color: "#0a0a0a" },
					},
					grid: {
						vertLines: { color: "#27272a" },
						horzLines: { color: "#27272a" },
					},
					timeScale: {
						visible: true,
						timeVisible: true,
						secondsVisible: false,
						borderColor: "#27272a",
					},
					rightPriceScale: { borderColor: "#27272a", minimumWidth: 60 },
				});

				// Resize Observer for Indicator Chart
				resizeObserverInd = new ResizeObserver((entries) => {
					if (!indChart || !indContainer) return;
					const entry = entries[0];
					if (entry) {
						const w = Math.floor(entry.contentRect.width);
						const h = Math.floor(entry.contentRect.height);
						if (w > 0 && h > 0) {
							indChart.resize(w, h);
						}
					}
				});
				resizeObserverInd.observe(indContainer);

				const paneGroups: { [key: string]: string[] } = {};
				indicatorPaneKeys.forEach((key) => {
					const lowerKey = key.toLowerCase();
					const paneId = lowerKey.includes("rsi")
						? "rsi"
						: lowerKey.includes("macd")
							? "macd"
							: lowerKey.includes("stoch")
								? "stoch"
								: lowerKey.includes("adx")
									? "adx"
									: lowerKey.includes("atr")
										? "atr"
										: `pane_${key.replace(/\W/g, "_")}`;
					if (!paneGroups[paneId]) paneGroups[paneId] = [];
					paneGroups[paneId].push(key);
				});

				const paneIds = Object.keys(paneGroups);
				const paneCount = paneIds.length;

				if (paneCount > 0) {
					const singlePaneHeight = 1.0 / paneCount;
					paneIds.forEach((paneId, index) => {
						const keysInPane = paneGroups[paneId];
						const topMargin = index * singlePaneHeight;
						const bottomMargin = 1.0 - (index + 1) * singlePaneHeight;

						indChart?.priceScale(paneId).applyOptions({
							scaleMargins: {
								top: topMargin,
								bottom: Math.max(0, bottomMargin),
							},
							visible: true,
							borderColor: "#27272a",
						});

						keysInPane.forEach((key) => {
							const data = viz.subcharts[key];
							if (!data) return;
							const sData = data
								.map((d: Record<string, unknown>) => ({
									time: (Number(d.time) > 1000000000000
										? Math.floor(Number(d.time) / 1000)
										: Number(d.time)) as Time,
									value: Number(d.value),
								}))
								.sort(
									(a: { time: number }, b: { time: number }) => a.time - b.time,
								);

							if (key.includes("Hist")) {
								const s = indChart?.addSeries(HistogramSeries, {
									priceScaleId: paneId,
									color: "#26a69a",
									title: key,
								});
								s.setData(
									sData.map((d: { value: number }) => ({
										...d,
										color: d.value >= 0 ? "#22c55e" : "#ef4444",
									})),
								);
							} else {
								const s = indChart?.addSeries(LineSeries, {
									priceScaleId: paneId,
									color: getIndicatorColor(key),
									lineWidth: 1,
									pointMarkersVisible: true,
									pointMarkersRadius: sData.length <= 1 ? 5 : 3,
									title: key,
								});
								s.setData(sData);
							}
						});
					});
				}
			}
		}

		// Initial fit - only if we don't have a previous range or it's a new chart
		requestAnimationFrame(() => {
			if (mainChart) {
				mainChart.timeScale().fitContent();
				if (indChart) indChart.timeScale().fitContent();
				syncOverlay();
			}
		});

		// --- 4. Synchronization ---
		if (indChart) {
			let isSyncingMain = false;
			let isSyncingInd = false;

			mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
				if (isSyncingMain || !indChart || !range) return;
				isSyncingInd = true;
				indChart.timeScale().setVisibleLogicalRange(range);
				isSyncingInd = false;
			});

			indChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
				if (isSyncingInd || !range) return;
				isSyncingMain = true;
				mainChart.timeScale().setVisibleLogicalRange(range);
				isSyncingMain = false;
			});
		}

		// Subscribe to both time and logical range changes so SVG trade markers move with the chart.
		const handleTimeRangeChange = () => syncOverlay();
		const handleLogicalRangeChange = () => syncOverlay();
		mainChart
			.timeScale()
			.subscribeVisibleTimeRangeChange(handleTimeRangeChange);
		mainChart
			.timeScale()
			.subscribeVisibleLogicalRangeChange(handleLogicalRangeChange);
		mainChart.subscribeCrosshairMove((param) => {
			if (param.time) {
				crosshairTimeRef.current = param.time as number;
				setCrosshairTime(param.time as number); // Update state for legend re-render
			} else {
				crosshairTimeRef.current = null;
				setCrosshairTime(null);
			}
			syncOverlay();
		});

		// Initial sync with multiple attempts (charts need time to render)
		setTimeout(syncOverlay, 50);
		setTimeout(syncOverlay, 200);
		setTimeout(syncOverlay, 500);
		setTimeout(syncOverlay, 1000);

		return () => {
			resizeObserverMain.disconnect();
			if (resizeObserverInd) resizeObserverInd.disconnect();
			mainChart
				.timeScale()
				.unsubscribeVisibleTimeRangeChange(handleTimeRangeChange);
			mainChart
				.timeScale()
				.unsubscribeVisibleLogicalRangeChange(handleLogicalRangeChange);
			mainChart.remove();
			if (indChart) indChart.remove();
			if (chartRef.current === mainChart) chartRef.current = null;
			if (seriesRef.current === candlestickSeries) seriesRef.current = null;
			overlayRef.current = null;
		};
	}, [
		klines,
		entryPrice,
		exitPrice,
		executionPrices,
		syncOverlay,
		showIndicators,
		foundationData,
		getIndicatorColor,
		extractedIndicators,
	]);

	// Mouse handlers for ruler
	const handleMouseDown = useCallback(
		(e: React.MouseEvent) => {
			const isShiftClick = e.button === 0 && e.shiftKey;
			const isMiddleClick = e.button === 1;

			if (
				(isShiftClick || isMiddleClick) &&
				chartContainerRef.current &&
				seriesRef.current
			) {
				if (isMiddleClick) e.preventDefault();

				setIsRulerActive(true);

				const rect = chartContainerRef.current.getBoundingClientRect();
				const x = e.clientX - rect.left;
				const y = e.clientY - rect.top;
				const price = seriesRef.current.coordinateToPrice(y);

				if (price !== null) {
					rulerStartRef.current = { x, y, price };
					rulerCurrentRef.current = { x, y, price };

					if (chartRef.current) {
						chartRef.current.applyOptions({
							handleScroll: false,
							handleScale: false,
						});
					}
					syncOverlay();
				}
			}
		},
		[syncOverlay],
	);

	const handleMouseMove = useCallback(
		(e: React.MouseEvent) => {
			if (
				isRulerActive &&
				rulerStartRef.current &&
				chartContainerRef.current &&
				seriesRef.current
			) {
				const rect = chartContainerRef.current.getBoundingClientRect();
				const x = e.clientX - rect.left;
				const y = e.clientY - rect.top;
				const price = seriesRef.current.coordinateToPrice(y);

				if (price !== null) {
					rulerCurrentRef.current = { x, y, price };
					syncOverlay();
				}
			}
		},
		[isRulerActive, syncOverlay],
	);

	const handleMouseUp = useCallback(() => {
		if (isRulerActive) {
			setIsRulerActive(false);
			rulerStartRef.current = null;
			rulerCurrentRef.current = null;

			if (chartRef.current) {
				chartRef.current.applyOptions({
					handleScroll: true,
					handleScale: true,
				});
			}
			syncOverlay();
		}
	}, [isRulerActive, syncOverlay]);

	// Handle ESC key
	useEffect(() => {
		const handleEsc = (e: KeyboardEvent) => {
			if (e.key === "Escape") onClose();
		};
		window.addEventListener("keydown", handleEsc);
		return () => window.removeEventListener("keydown", handleEsc);
	}, [onClose]);

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md"
			onClick={onClose}
		>
			<div
				ref={modalContentRef}
				className="bg-card border border-border w-full max-w-[1920px] rounded-3xl shadow-2xl overflow-hidden flex flex-col max-h-[95vh]"
				onClick={(e) => e.stopPropagation()}
			>
				{/* Header */}
				<div className="p-6 border-b border-border bg-muted/50 flex justify-between items-center">
					<div className="flex items-center gap-4">
						<div
							className={`p-3 rounded-xl ${realizedPnl >= 0 ? "bg-profit/10" : "bg-loss/10"}`}
						>
							{isLong ? (
								<TrendingUp
									className={realizedPnl >= 0 ? "text-profit" : "text-loss"}
								/>
							) : (
								<TrendingDown
									className={realizedPnl >= 0 ? "text-profit" : "text-loss"}
								/>
							)}
						</div>
						<div>
							<h2 className="text-xl font-bold text-foreground flex items-center gap-2">
								{trade.symbol}
								<span className="text-muted-foreground text-sm font-normal">
									{t("executionAnalysis", "Execution Analysis")}
								</span>
							</h2>
							<p className="text-xs text-muted-foreground">
								{t("tradeId", "Trade ID")}:{" "}
								{trade.trade_uuid?.substring(0, 8) || trade.id}
								<span className="ml-4 opacity-60">
									📏 Shift+Click for ruler
								</span>
							</p>
						</div>
					</div>
					<div className="flex items-center gap-2">
						<div className="mr-4 hidden lg:flex items-center bg-background/50 border border-border rounded-lg p-0.5">
							{KLINE_INTERVALS.map((tf) => (
								<button
									key={tf.value}
									onClick={() => setInterval(tf.value)}
									className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${
										effectiveInterval === tf.value
											? "bg-primary text-primary-foreground shadow-sm"
											: "text-muted-foreground hover:text-foreground hover:bg-muted"
									}`}
								>
									{tf.label}
								</button>
							))}
						</div>

						<button
							onClick={() => setShowIndicators(!showIndicators)}
							disabled={foundationLoading}
							className={cn(
								"p-2 rounded-full transition-colors",
								showIndicators
									? "bg-primary text-primary-foreground"
									: "hover:bg-muted text-muted-foreground",
								foundationLoading && "opacity-80 cursor-wait",
							)}
							title={`${t("showIndicators", "Show Indicators")} (${usedFoundations.length})`}
						>
							{foundationLoading ? (
								<Loader2 className="w-5 h-5 animate-spin" />
							) : (
								<BarChart3 className="w-5 h-5" />
							)}
						</button>

						<div className="mr-4 hidden md:block">
							<Logo className="h-10 w-auto" />
						</div>
						<button
							onClick={handleScreenshot}
							disabled={isCapturing}
							className={`p-2 rounded-full hover:bg-muted transition-colors ${isCapturing ? "opacity-50 cursor-not-allowed" : ""}`}
							title={t("shareScreenshot", "Share Screenshot")}
						>
							<Camera className="w-6 h-6 text-muted-foreground" />
						</button>
						<button
							onClick={onClose}
							className="p-2 rounded-full hover:bg-muted transition-colors"
						>
							<X className="w-6 h-6 text-muted-foreground" />
						</button>
					</div>
				</div>

				{/* Content */}
				<div className="flex-1 flex flex-col overflow-hidden p-6 gap-6">
					{/* Quick Stats Grid */}
					<div className="grid grid-cols-2 md:grid-cols-4 gap-4">
						{[
							{
								label: t("result", "Result"),
								value: realizedPnl != null && Number.isFinite(realizedPnl)
									? `${realizedPnl >= 0 ? "+" : ""}$${realizedPnl.toFixed(2)}`
									: "N/A",
								color: realizedPnl >= 0 ? "text-profit" : "text-loss",
							},
							{
								label: t("entry", "Entry"),
								value: entryPrice != null && Number.isFinite(entryPrice)
									? `$${entryPrice.toFixed(4)}`
									: "N/A",
								color: "text-primary",
							},
							{
								label: t("exit", "Exit"),
								value: exitPrice != null && Number.isFinite(exitPrice)
									? `$${exitPrice.toFixed(4)}`
									: "N/A",
								color: "text-amber-500",
							},
							{
								label: t("side", "Side"),
								value: trade.direction,
								color: isLong ? "text-profit" : "text-loss",
							},
						].map((stat, i) => (
							<div
								key={i}
								className="bg-muted/50 border border-border p-4 rounded-2xl"
							>
								<span className="text-[10px] uppercase tracking-wider font-bold text-muted-foreground block mb-1">
									{stat.label}
								</span>
								<span className={`text-lg font-bold ${stat.color}`}>
									{stat.value}
								</span>
							</div>
						))}
					</div>

					{/* Chart & Tree Container */}
					{(() => {
						const potentialTrace =
							decisionTrace?.decision_trace || decisionTrace;

						const isValidTrace =
							potentialTrace &&
							typeof potentialTrace === "object" &&
							"type" in potentialTrace &&
							"result" in potentialTrace;

						if (isValidTrace) {
							return (
								<div className="flex-1 flex flex-col xl:flex-row gap-6 min-h-[600px] overflow-hidden relative">
									{/* Left Column: Decision Tree */}
									<div
										className={cn(
											"flex flex-col shrink-0 transition-all duration-300 ease-in-out overflow-hidden z-20",
											showTree
												? "xl:w-[550px] opacity-100"
												: "xl:w-0 opacity-0 pointer-events-none",
										)}
									>
										<div className="flex items-center justify-between mb-4 px-1">
											<h3 className="text-lg font-semibold flex items-center gap-2 truncate whitespace-nowrap">
												<span className="w-1.5 h-6 bg-primary rounded-full" />
												{t("decisionTree.title")}
											</h3>
											<Button
												variant="ghost"
												size="icon"
												className="h-8 w-8 hover:bg-muted shrink-0"
												onClick={() => setShowTree(false)}
											>
												<ChevronLeft className="h-5 w-5" />
											</Button>
										</div>

										<div className="bg-muted/30 border border-border rounded-2xl overflow-hidden flex-1 flex flex-col min-w-0">
											<ScrollArea className="flex-1 w-full bg-black/20">
												<div className="p-3 space-y-3 w-full overflow-hidden">
													{/* Filters Section */}
													{potentialTrace.filters_trace && (
														<div className="border border-amber-500/30 rounded-lg p-2 bg-amber-500/5">
															<div className="flex items-center gap-2 mb-2">
																<span className="text-xs font-semibold uppercase tracking-wider text-amber-500">
																	{t("decisionTree.filters", "Filters")}
																</span>
																{potentialTrace.filters_trace.result ? (
																	<span className="text-xs text-profit">
																		✓ {t("decisionTree.passed", "Passed")}
																	</span>
																) : (
																	<span className="text-xs text-loss">
																		✗ {t("decisionTree.failed", "Failed")}
																	</span>
																)}
															</div>
															<DecisionTraceTree
																trace={
																	potentialTrace.filters_trace as unknown as TraceNode
																}
															/>
														</div>
													)}

													{/* Entry Conditions Section */}
													<div>
														<div className="flex items-center gap-2 mb-2">
															<span className="text-xs font-semibold uppercase tracking-wider text-primary">
																{t(
																	"decisionTree.entryConditions",
																	"Entry Conditions",
																)}
															</span>
														</div>
														<DecisionTraceTree
															trace={potentialTrace as unknown as TraceNode}
														/>
													</div>
												</div>
											</ScrollArea>
										</div>
									</div>

									{!showTree && (
										<div className="absolute left-[12px] top-[48px] z-30">
											<Button
												variant="secondary"
												size="icon"
												className="h-10 w-10 rounded-full shadow-lg border border-border bg-card/80 backdrop-blur-sm hover:bg-muted transition-all"
												onClick={() => setShowTree(true)}
												title={t("decisionTree.title")}
											>
												<ChevronRight className="h-6 w-6" />
											</Button>
										</div>
									)}

									{/* Right Column: Charts */}
									<div className="flex-1 flex flex-col min-w-0">
										<div
											className={cn(
												"bg-background border border-border rounded-2xl overflow-hidden relative flex-1 flex flex-col",
												isRulerActive ? "cursor-crosshair" : "",
											)}
											onMouseDown={handleMouseDown}
											onMouseMove={handleMouseMove}
											onMouseUp={handleMouseUp}
											onMouseLeave={handleMouseUp}
										>
											{loading ? (
												<div className="h-full flex items-center justify-center flex-col gap-3">
													<div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
													<span className="text-muted-foreground animate-pulse">
														{t("fetchingData", "Fetching market data...")}
													</span>
												</div>
											) : error || klines.length === 0 ? (
												<div className="h-full flex items-center justify-center flex-col gap-2 text-muted-foreground">
													<AlertCircle className="w-10 h-10 mb-2" />
													<span className="font-bold text-foreground">
														{error || t("dataUnavailable", "Data Unavailable")}
													</span>
													<span className="text-xs">
														Symbol: {trade.symbol}, Period:{" "}
														{new Date(entryTime * 1000).toLocaleString()} -{" "}
														{new Date(exitTime * 1000).toLocaleString()}
													</span>
												</div>
											) : (
												<>
													{/* Main Chart - takes remaining space */}
													<div
														className="w-full relative flex-1"
														style={{
															minHeight:
																showIndicators &&
																foundationData &&
																Object.keys(
																	foundationData.visualizations.subcharts || {},
																).length > 0
																	? "65%"
																	: "100%",
														}}
														ref={chartContainerRef}
													/>
													{showIndicators &&
														foundationData &&
														Object.keys(
															foundationData.visualizations.subcharts || {},
														).length > 0 && (
															<div
																className="w-full border-t border-border bg-black/20"
																style={{ height: "180px", flexShrink: 0 }}
																ref={indicatorContainerRef}
															/>
														)}
												</>
											)}
										</div>
									</div>
								</div>
							);
						}

						// Normal layout if no trace available (Fallback)
						return (
							<div
								className={`bg-background border border-border rounded-2xl p-0 overflow-hidden relative flex-1 min-h-[600px] ${isRulerActive ? "cursor-crosshair" : ""}`}
								onMouseDown={handleMouseDown}
								onMouseMove={handleMouseMove}
								onMouseUp={handleMouseUp}
								onMouseLeave={handleMouseUp}
							>
								{/* Reuse same logic for simplicity if needed, but keeping original fallback for now */}
								{loading ? (
									<div className="h-full flex items-center justify-center flex-col gap-3">
										<div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
										<span className="text-muted-foreground animate-pulse">
											{t("fetchingData", "Fetching market data...")}
										</span>
									</div>
								) : error || klines.length === 0 ? (
									<div className="h-full flex items-center justify-center flex-col gap-2 text-muted-foreground">
										<AlertCircle className="w-10 h-10 mb-2" />
										<span className="font-bold text-foreground">
											{error || t("dataUnavailable", "Data Unavailable")}
										</span>
										<span className="text-xs text-muted-foreground">
											Symbol: {trade.symbol}, Period:{" "}
											{new Date(entryTime * 1000).toLocaleString()} -{" "}
											{new Date(exitTime * 1000).toLocaleString()}
										</span>
									</div>
								) : (
									<div ref={chartContainerRef} className="w-full h-full" />
								)}
							</div>
						);
					})()}
				</div>
			</div>
		</div>
	);
};
