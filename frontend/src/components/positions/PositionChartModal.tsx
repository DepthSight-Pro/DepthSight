// src/components/positions/PositionChartModal.tsx

import { format } from "date-fns";
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
	AlertTriangle,
	BarChart3,
	ChevronLeft,
	ChevronRight,
	Loader2,
	RefreshCw,
	Save,
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
import type { PositionData, TradeExecution } from "@/types/api";
import { useConfig } from "@/lib/api";

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

const getIndicatorColor = (key: string): string => {
	const k = key.toLowerCase();
	if (k.includes("fast") || k.includes("k_") || k.includes("squeeze_current"))
		return "#2962FF";
	if (k.includes("slow") || k.includes("d_") || k.includes("squeeze_past"))
		return "#FF2929";
	if (k.includes("upper")) return "#22C55E";
	if (k.includes("lower")) return "#EF4444";
	if (k.includes("middle") || k.includes("basis")) return "#FF9800";
	if (k.includes("ma_") || k.includes("sma") || k.includes("ema"))
		return "#FF9800";

	return "#78909C"; // Default
};

interface PositionChartModalProps {
	position: PositionData;
	isOpen: boolean;
	onClose: () => void;
	onSave: (data: {
		stop_loss: number | null;
		take_profit: number | null;
	}) => void;
	isSaving?: boolean;
}

export const PositionChartModal: React.FC<PositionChartModalProps> = ({
	position,
	isOpen,
	onClose,
	onSave,
	isSaving = false,
}) => {
	const { t } = useTranslation(["positions", "common", "analytics"]);
	const chartContainerRef = useRef<HTMLDivElement>(null);
	const indicatorContainerRef = useRef<HTMLDivElement>(null);
	const chartRef = useRef<IChartApi | null>(null);
	const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
	const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
	const overlayRef = useRef<SVGSVGElement | null>(null);
	const syncOverlayRef = useRef<() => void>(() => {});
	const crosshairTimeRef = useRef<number | null>(null);

	const { data: config } = useConfig();
	const apiKey = config?.apiKeys?.find((key) => key.id === position.api_key_id);
	const exchange = apiKey?.exchange?.toLowerCase() || "binance";

	const [klines, setKlines] = useState<Kline[]>([]);
	const [loading, setLoading] = useState(true);
	const [selectedInterval, setSelectedInterval] = useState<KlineInterval>("1m");
	const [tickSize, setTickSize] = useState<number | undefined>(undefined);

	// Editable SL/TP state
	const [slPrice, setSlPrice] = useState<number | null>(
		position.stop_loss || null,
	);
	const [tpPrice, setTpPrice] = useState<number | null>(
		position.take_profit || null,
	);
	const [hasChanges, setHasChanges] = useState(false);

	// Toggles (Tree & Indicators)
	const [showTree, setShowTree] = useState(false);
	const [showIndicators, setShowIndicators] = useState(false);
	const [foundationData, setFoundationData] =
		useState<FoundationChartProps | null>(null);
	const [foundationLoading, setFoundationLoading] = useState(false);
	const [crosshairTime, setCrosshairTime] = useState<number | null>(null);

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

	// Refs for chart operations to avoid re-renders/jitters during drag
	const slPriceRef = useRef<number | null>(slPrice);
	const tpPriceRef = useRef<number | null>(tpPrice);

	// Dragging state
	const [draggingLine, setDraggingLine] = useState<"SL" | "TP" | null>(null);

	// Update refs when state changes, BUT ONLY if not dragging to prevent autoscale jitter
	// The overlay needs 'slPrice' state to render lines (instant),
	// but autoscale uses 'slPriceRef' which should be stable during drag.
	useEffect(() => {
		if (!draggingLine) {
			slPriceRef.current = slPrice;
			tpPriceRef.current = tpPrice;
		}
	}, [slPrice, tpPrice, draggingLine]);

	// Robust sync state with props
	const prevPositionRef = useRef(position);

	useEffect(() => {
		// 1. If ID changed, full reset
		if (position.id !== prevPositionRef.current.id) {
			setSlPrice(position.stop_loss || null);
			setTpPrice(position.take_profit || null);
			setHasChanges(false);
			prevPositionRef.current = position;
			return;
		} else if (!hasChanges) {
			// 2. Sync if there are no local unsaved edits
			setSlPrice(position.stop_loss || null);
			setTpPrice(position.take_profit || null);
		}
	}, [position, hasChanges]);

	// Load Klines
	const loadData = useCallback(async (silent = false) => {
		if (!isOpen) return;
		if (!silent) setLoading(true);
		try {
			const now = Date.now();
			// If entry_time is very old, we might need a larger interval or just fetch latest
			const entryTime = position.entry_time
				? new Date(position.entry_time).getTime()
				: now - 24 * 60 * 60 * 1000;

			// We want to see from entryTime to now.
			// If we specify startTime, Binance returns first 1500 (our limit) from that time.
			// If now - startTime > 1500 * interval, we won't see the latest data.

			// Strategy: Always try to get a range that includes both entry and now if possible.
			// If not, priority is the latest data for "realtime" feel, user can change TF to see more.
			const startTime = entryTime - 4 * 60 * 60 * 1000;

			let data: Kline[] = [];
			if (exchange === "bybit") {
				try {
					data = await fetchBybitKlines(position.symbol, startTime, now, selectedInterval);
				} catch (bybitErr) {
					console.warn("Failed to load Bybit klines", bybitErr);
				}
				if (data.length === 0) {
					data = await fetchKlines(position.symbol, startTime, now, selectedInterval);
				}
			} else {
				data = await fetchKlines(position.symbol, startTime, now, selectedInterval);
				if (data.length === 0) {
					try {
						data = await fetchBybitKlines(position.symbol, startTime, now, selectedInterval);
					} catch (bybitErr) {
						console.warn("Failed to load Bybit fallback klines", bybitErr);
					}
				}
			}
			setKlines(data);
		} catch (e) {
			console.error("Failed to load chart data", e);
			if (!silent) toast.error(t("common:errors.unknownError"));
		} finally {
			if (!silent) setLoading(false);
		}
	}, [isOpen, position.symbol, position.entry_time, selectedInterval, exchange, t]);

	useEffect(() => {
		loadData();
	}, [loadData]);

	// Auto-refresh klines in background for real-time updates
	useEffect(() => {
		if (!isOpen) return;
		const intervalId = window.setInterval(() => {
			loadData(true);
		}, 5000);
		return () => window.clearInterval(intervalId);
	}, [isOpen, loadData]);

	// Fetch tick size
	useEffect(() => {
		if (!isOpen || !position.symbol) return;
		setTickSize(undefined);

		const cleanSymbol = position.symbol.toUpperCase().replace(/[^a-zA-Z0-9]/g, "");

		const loadBybitSymbolInfo = () => {
			return fetchBybitSymbolInfo(position.symbol).then((bybitInfo) => {
				if (bybitInfo && bybitInfo.result && bybitInfo.result.list && bybitInfo.result.list[0]) {
					const symbolInfo = bybitInfo.result.list[0];
					if (symbolInfo.priceFilter && symbolInfo.priceFilter.tickSize) {
						setTickSize(parseFloat(symbolInfo.priceFilter.tickSize));
						return true;
					}
				}
				return false;
			});
		};

		const loadBinanceSymbolInfo = () => {
			return fetchSymbolInfo(position.symbol).then((info) => {
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
							return true;
						}
					}
				}
				return false;
			});
		};

		if (exchange === "bybit") {
			loadBybitSymbolInfo().then((success) => {
				if (!success) loadBinanceSymbolInfo();
			}).catch(() => {
				loadBinanceSymbolInfo();
			});
		} else {
			loadBinanceSymbolInfo().then((success) => {
				if (!success) loadBybitSymbolInfo();
			}).catch(() => {
				loadBybitSymbolInfo();
			});
		}
	}, [isOpen, position.symbol, exchange]);

	// Update series price format when tick size is fetched or klines load
	useEffect(() => {
		const effectiveTickSize = tickSize || estimateTickSize(klines);
		if (seriesRef.current && effectiveTickSize) {
			seriesRef.current.applyOptions({
				priceFormat: {
					type: "price",
					precision: Math.ceil(Math.max(0, -Math.log10(effectiveTickSize))),
					minMove: effectiveTickSize,
				},
			});
		}
	}, [tickSize, klines]);

	const normalizedExecutions = useMemo<NormalizedExecution[]>(() => {
		const counters: Record<"ENTRY" | "EXIT", number> = {
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

		// 1. Check position.executions
		if (position.executions && Array.isArray(position.executions)) {
			position.executions.forEach((execution) => {
				appendRawExecution(execution as unknown as Record<string, unknown>);
			});
		}

		// 2. Check signal_details_json for execution_events or executions
		const details = parseTraceObject(position.signal_details_json) as
			| {
					execution_events?: Array<Record<string, unknown>>;
					executions?: Array<Record<string, unknown>>;
			  }
			| null
			| undefined;
		const jsonExecutions =
			details?.execution_events || details?.executions || [];
		jsonExecutions.forEach(appendRawExecution);

		// Dedup
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
	}, [position]);

	const executionPrices = useMemo(
		() => normalizedExecutions.map((execution) => execution.price),
		[normalizedExecutions],
	);

	const entryTime = useMemo(() => {
		return toTimestampSeconds(position.entry_time) ?? Math.floor(Date.now() / 1000 - 3600);
	}, [position.entry_time]);

	const exitTime = useMemo(() => {
		return Math.floor(Date.now() / 1000);
	}, []);

	const entryPrice = position.entry_price || 0;
	const exitPrice = position.mark_price || 0;
	const isLong = ["LONG", "BUY"].includes(String(position.direction));



	const decisionTrace = useMemo(() => {
		const details = parseTraceObject(position.signal_details_json);
		const directTrace = parseTraceObject(
			(position as unknown as Record<string, unknown>).decision_trace_json,
		);
		return parseTraceObject(details?.decision_trace) || directTrace || details;
	}, [position]);

	const extractIndicatorsFromTrace = useCallback(
		(node: TraceNode, indicators: any) => {
			if (!node || typeof node !== "object") return;

			const type = String(node.type || "").toLowerCase();
			const details =
				node.details && typeof node.details === "object"
					? (node.details as Record<string, unknown>)
					: {};
			const result = Boolean(node.result);

			if (type.includes("bollinger") || type.includes("bb_condition")) {
				if (
					toFiniteNumber(details.upper) !== undefined &&
					toFiniteNumber(details.lower) !== undefined
				) {
					indicators.bbBands.push({
						upper: Number(details.upper),
						middle: toFiniteNumber(details.middle),
						lower: Number(details.lower),
						result,
					});
				}
			} else if (type.includes("significant_level")) {
				const price =
					toFiniteNumber(details.detected_level) ??
					toFiniteNumber(details.level_hit) ??
					toFiniteNumber(details.level) ??
					toFiniteNumber(details.price);
				if (price !== undefined) {
					indicators.significantLevels.push({
						price,
						levelType: String(details.level_type || "horizontal"),
						result,
					});
				}
			} else if (type.includes("local_level")) {
				const price =
					toFiniteNumber(details.detected_level) ??
					toFiniteNumber(details.level_hit) ??
					toFiniteNumber(details.level) ??
					toFiniteNumber(details.price);
				if (price !== undefined) {
					indicators.localLevels.push({
						price,
						levelType: String(details.level_type || "horizontal"),
						result,
					});
				}
			} else if (type.includes("round_level") || type.includes("round_number")) {
				const price =
					toFiniteNumber(details.detected_level) ??
					toFiniteNumber(details.level_hit) ??
					toFiniteNumber(details.round_level) ??
					toFiniteNumber(details.level) ??
					toFiniteNumber(details.price);
				if (price !== undefined) {
					indicators.roundLevels.push({ price, result });
				}
			} else if (type.includes("ma_cross") || type.includes("ma_crossover")) {
				if (
					toFiniteNumber(details.fast_ma) !== undefined &&
					toFiniteNumber(details.slow_ma) !== undefined
				) {
					indicators.maCrossover.push({
						fastMa: Number(details.fast_ma),
						slowMa: Number(details.slow_ma),
						result,
					});
				}
			} else if (type.includes("stoch")) {
				if (
					toFiniteNumber(details.k) !== undefined &&
					toFiniteNumber(details.d) !== undefined
				) {
					indicators.stoch.push({ k: details.k, d: details.d, result });
				}
			} else if (type.includes("rsi")) {
				const rsiValue =
					toFiniteNumber(details.rsi) ??
					toFiniteNumber(details.value) ??
					toFiniteNumber(details.rsi_value);
				if (rsiValue !== undefined) {
					indicators.rsi.push({ value: rsiValue, result });
				}
			} else if (type.includes("macd")) {
				const line =
					toFiniteNumber(details.macd_line) ??
					toFiniteNumber(details.line) ??
					toFiniteNumber(details.macd);
				const signal =
					toFiniteNumber(details.signal_line) ??
					toFiniteNumber(details.signal);
				const histogram =
					toFiniteNumber(details.histogram) ?? toFiniteNumber(details.hist);
				if (line !== undefined && signal !== undefined && histogram !== undefined) {
					indicators.macd.push({
						line,
						signal,
						histogram,
						result,
					});
				}
			} else if (type.includes("adx") || type === "trend_filter") {
				const adxValue =
					toFiniteNumber(details.adx) ??
					toFiniteNumber(details.adx_actual) ??
					toFiniteNumber(details.actual);
				if (adxValue !== undefined) {
					indicators.adx.push({ value: Number(adxValue), result });
				}
			} else if (type.includes("natr")) {
				const natrVal =
					toFiniteNumber(details.natr) ??
					toFiniteNumber(details.natr_val) ??
					toFiniteNumber(details.actual);
				if (natrVal !== undefined) {
					indicators.natr.push({
						value: Number(natrVal),
						threshold: toFiniteNumber(details.threshold),
						result,
					});
				}
			} else if (type.includes("volatility_filter")) {
				const atrVal = toFiniteNumber(details.actual) ?? toFiniteNumber(details.value);
				if (atrVal !== undefined) {
					indicators.atr.push({ value: atrVal, result });
				}
			} else if (type.includes("time_filter")) {
				indicators.timeFilter.push({
					startHour: toFiniteNumber(details.start_hour),
					endHour: toFiniteNumber(details.end_hour),
					currentHour: toFiniteNumber(details.current_hour),
					mode: String(details.mode || ""),
					result,
				});
			} else if (type.includes("trend_direction")) {
				indicators.trendDirection.push({
					direction: String(
						details.detected_trend ?? details.direction ?? details.trend ?? "",
					),
					result,
				});
			} else if (type.includes("volume_confirmation")) {
				indicators.volumeConfirmation.push({
					volume: toFiniteNumber(details.volume),
					threshold: toFiniteNumber(details.threshold),
					result,
				});
			} else if (type.includes("consolidation") || type.includes("price_consolidation")) {
				indicators.priceConsolidation.push({
					rangePercent: toFiniteNumber(details.range_percent),
					detectedLevel: toFiniteNumber(details.detected_level),
					result,
				});
			} else if (type.includes("squeeze") || type.includes("volatility_squeeze")) {
				indicators.volatilitySqueeze = indicators.volatilitySqueeze || [];
				indicators.volatilitySqueeze.push({ result });
			} else if (type.includes("level_touch")) {
				const price = toFiniteNumber(details.level) ?? toFiniteNumber(details.detected_level);
				if (price !== undefined) {
					indicators.levelTouch = indicators.levelTouch || [];
					indicators.levelTouch.push({ price, result });
				}
			} else if (type.includes("price_action")) {
				indicators.priceAction = indicators.priceAction || [];
				indicators.priceAction.push({ result });
			} else if (type.includes("tape_acceleration") || type.includes("tape")) {
				indicators.tapeAcceleration = indicators.tapeAcceleration || [];
				indicators.tapeAcceleration.push({
					result,
				});
			} else if (type.includes("open_interest") || type.includes("oi")) {
				indicators.openInterest = indicators.openInterest || [];
				indicators.openInterest.push({
					result,
				});
			} else if (type.includes("rel_vol") || type.includes("relative_volume")) {
				indicators.relativeVolume = indicators.relativeVolume || [];
				indicators.relativeVolume.push({
					result,
				});
			} else if (type.includes("correlation")) {
				indicators.correlation = indicators.correlation || [];
				indicators.correlation.push({
					result,
				});
			} else if (type.includes("pattern") || type.includes("classic_pattern")) {
				indicators.pattern = indicators.pattern || [];
				indicators.pattern.push({
					result,
				});
			}

			if (node.children && Array.isArray(node.children)) {
				node.children.forEach((child) => {
					extractIndicatorsFromTrace(child as TraceNode, indicators);
				});
			}
		},
		[],
	);

	const extractedIndicators = useMemo(() => {
		const indicators = {
			bbBands: [] as any[],
			significantLevels: [] as any[],
			localLevels: [] as any[],
			roundLevels: [] as any[],
			maCrossover: [] as any[],
			stoch: [] as any[],
			rsi: [] as any[],
			macd: [] as any[],
			adx: [] as any[],
			natr: [] as any[],
			atr: [] as any[],
			timeFilter: [] as any[],
			trendDirection: [] as any[],
			volumeConfirmation: [] as any[],
			priceConsolidation: [] as any[],
			volatilitySqueeze: [] as any[],
			levelTouch: [] as any[],
			priceAction: [] as any[],
			tapeAcceleration: [] as any[],
			openInterest: [] as any[],
			relativeVolume: [] as any[],
			correlation: [] as any[],
			pattern: [] as any[],
		};

		if (!decisionTrace) return indicators;

		const entryTrace = decisionTrace.decision_trace || decisionTrace;
		if (entryTrace && typeof entryTrace === "object") {
			extractIndicatorsFromTrace(entryTrace, indicators);
		}

		const filtersTrace = entryTrace?.filters_trace;
		if (filtersTrace && typeof filtersTrace === "object") {
			extractIndicatorsFromTrace(filtersTrace, indicators);
		}

		return indicators;
	}, [decisionTrace, extractIndicatorsFromTrace]);

	const usedFoundations = useMemo(() => {
		const foundations = new Set<string>();

		const extractFromNode = (node: any) => {
			if (!node || typeof node !== "object") return;
			const foundationType = normalizeFoundationType(node.type as string);
			if (foundationType) foundations.add(foundationType);

			if (node.children && Array.isArray(node.children)) {
				node.children.forEach((child: any) => {
					extractFromNode(child);
				});
			}
			if (node.filters_trace) extractFromNode(node.filters_trace);
		};

		if (decisionTrace) {
			extractFromNode(decisionTrace.decision_trace || decisionTrace);
		}

		// Exclude static levels from preview diagnostics
		const excludedFromBackend = new Set([
			"significant_level",
			"local_level",
			"round_level",
		]);
		return Array.from(foundations).filter((f) => !excludedFromBackend.has(f));
	}, [decisionTrace]);

	const entryPriceRef = useRef(entryPrice);
	const exitPriceRef = useRef(exitPrice);
	const executionPricesRef = useRef(executionPrices);
	const extractedIndicatorsRef = useRef(extractedIndicators);

	useEffect(() => {
		entryPriceRef.current = entryPrice;
		exitPriceRef.current = exitPrice;
		executionPricesRef.current = executionPrices;
		extractedIndicatorsRef.current = extractedIndicators;
	}, [entryPrice, exitPrice, executionPrices, extractedIndicators]);

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

		const traceRoot = decisionTrace?.decision_trace || decisionTrace;
		if (traceRoot) collectFromNode(traceRoot, true);

		return paramsByType;
	}, [decisionTrace]);

	const effectiveInterval = useMemo(() => {
		return selectedInterval;
	}, [selectedInterval]);

	const buildComputedIndicatorSubcharts = useCallback(() => {
		if (klines.length === 0) return {};
		const subcharts: Record<string, Array<{ time: number; value: number }>> = {};

		const closes = klines.map((k) => Number(k.close));
		const addSeries = (key: string, values: Array<number | null>) => {
			const seriesData = toSubchartSeries(normalizeChartKlines(klines), values);
			if (seriesData.length > 0) subcharts[key] = seriesData;
		};

		// Stochastic
		const stochParams = foundationParams.stochastic_condition || {};
		const kPeriod = Number(stochParams.k_period || 14);
		const dPeriod = Number(stochParams.d_period || 3);
		const slowing = Number(stochParams.slowing || 3);
		const stochRes = stochasticValues(normalizeChartKlines(klines), kPeriod, dPeriod, slowing);
		addSeries("Stoch_K", stochRes.k);
		addSeries("Stoch_D", stochRes.d);

		// RSI
		const rsiParams = foundationParams.rsi_condition || {};
		const rsiPeriod = Number(rsiParams.period || 14);
		addSeries("RSI", rsiValues(closes, rsiPeriod));

		// ATR / NATR
		const natrParams = foundationParams.natr_filter || {};
		const natrPeriod = Number(natrParams.period || 14);
		const atrRes = atrValues(normalizeChartKlines(klines), natrPeriod);
		addSeries("ATR", atrRes);

		const natrValuesComputed = atrRes.map((atrVal, idx) => {
			if (atrVal === null || closes[idx] === 0) return null;
			return (atrVal / closes[idx]) * 100;
		});
		addSeries("NATR", natrValuesComputed);

		// ADX
		const adxParams = foundationParams.trend_filter || {};
		const adxPeriod = Number(adxParams.period || 14);
		addSeries("ADX", adxValues(normalizeChartKlines(klines), adxPeriod));

		// Bollinger
		const bbParams = foundationParams.bollinger_bands_condition || {};
		const bbPeriod = Number(bbParams.period || 20);
		const bbStd = Number(bbParams.std_dev || 2.0);
		const bbRes = bollingerValues(closes, bbPeriod, bbStd);
		addSeries("BB_Upper", bbRes.upper);
		addSeries("BB_Middle", bbRes.middle);
		addSeries("BB_Lower", bbRes.lower);

		return subcharts;
	}, [klines, foundationParams]);

	const buildTraceFoundationData = useCallback((): FoundationChartProps | null => {
		if (!decisionTrace || klines.length === 0) return null;

		const traceRoot = decisionTrace.decision_trace || decisionTrace;
		const signalTime =
			toTimestampSeconds(traceRoot?.details?.signal_time) ??
			entryTime;
		const foundationKlines: KlineData[] = normalizeChartKlines(klines);

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
				rawTimeframe || selectedInterval || effectiveInterval || "1m",
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
						selectedInterval ||
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
							(marker.color as string) || "#3b82f6",
							"price_action_analyzer",
						);
					});
				} else {
					addMarker("PA", result, "price_action_analyzer");
				}
			}

			if (node.children && Array.isArray(node.children)) {
				node.children.forEach((child: unknown) => {
					traverse(child as TraceNode);
				});
			}
			if (node.filters_trace) traverse(node.filters_trace as TraceNode);
		};

		traverse(traceRoot as TraceNode);

		return {
			klines: foundationKlines,
			visualizations,
		};
	}, [decisionTrace, klines, entryTime, selectedInterval, effectiveInterval]);

	// Load foundation visualization data
	const loadFoundationData = useCallback(async () => {
		if (!showIndicators || !position.symbol || !exitTime) {
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
						symbol: position.symbol,
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
		position.symbol,
		exitTime,
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

	// Sync Overlay (drawing lines)
	const syncOverlay = useCallback(() => {
		if (
			!chartRef.current ||
			!seriesRef.current ||
			!overlayRef.current ||
			!chartContainerRef.current
		)
			return;

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

		const containerWidth = chartContainerRef.current?.clientWidth || 800;
		const containerHeight = chartContainerRef.current?.clientHeight || 500;

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

		const drawLine = (
			price: number,
			color: string,
			type: "ENTRY" | "SL" | "TP" | "PTP" | "MARK",
			isDashed = false,
			labelText?: string,
		) => {
			const y = series.priceToCoordinate(price);
			if (y === null) return null;

			// Line
			const line = document.createElementNS(
				"http://www.w3.org/2000/svg",
				"line",
			);
			line.setAttribute("x1", "0");
			line.setAttribute("y1", String(y));
			line.setAttribute("x2", String(containerWidth - 60)); // Leave space for scale
			line.setAttribute("y2", String(y));
			line.setAttribute("stroke", color);
			line.setAttribute("stroke-width", ["ENTRY", "PTP", "MARK"].includes(type) ? "1" : "2");
			if (isDashed) line.setAttribute("stroke-dasharray", "4,4");

			// Add Data attributes for hit testing
			if (type === "SL" || type === "TP") {
				line.setAttribute("class", "draggable-line");
				line.setAttribute("data-type", type);
				line.setAttribute("style", "cursor: ns-resize; pointer-events: all;");
				// Invisible wider hit area
				const hitArea = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"rect",
				);
				hitArea.setAttribute("x", "0");
				hitArea.setAttribute("y", String(y - 10));
				hitArea.setAttribute("width", String(containerWidth - 60));
				hitArea.setAttribute("height", "20");
				hitArea.setAttribute("fill", "transparent");
				hitArea.setAttribute(
					"style",
					"cursor: ns-resize; pointer-events: all;",
				);
				hitArea.setAttribute("data-type", type);
				overlay.appendChild(hitArea);
			}

			overlay.appendChild(line);

			// Label
			const labelGroup = document.createElementNS(
				"http://www.w3.org/2000/svg",
				"g",
			);
			const rect = document.createElementNS(
				"http://www.w3.org/2000/svg",
				"rect",
			);
			const text = document.createElementNS(
				"http://www.w3.org/2000/svg",
				"text",
			);

			const finalLabel = labelText || `${type}: ${price.toFixed(price < 10 ? 4 : 2)}`;
			text.textContent = finalLabel;
			text.setAttribute("fill", "white");
			text.setAttribute("font-size", "10px");
			text.setAttribute("font-weight", "bold");

			// Approx text width
			const textWidth = finalLabel.length * 6 + 10;

			rect.setAttribute("x", String(containerWidth - 60 - textWidth));
			rect.setAttribute("y", String(y - 10));
			rect.setAttribute("width", String(textWidth));
			rect.setAttribute("height", "20");
			rect.setAttribute("fill", color);
			rect.setAttribute("rx", "4");

			text.setAttribute("x", String(containerWidth - 60 - textWidth + 5));
			text.setAttribute("y", String(y + 4));

			labelGroup.appendChild(rect);
			labelGroup.appendChild(text);
			// Make label draggable too
			if (type === "SL" || type === "TP") {
				labelGroup.setAttribute(
					"style",
					"cursor: ns-resize; pointer-events: all;",
				);
				labelGroup.setAttribute("data-type", type);
			}

			overlay.appendChild(labelGroup);
		};

		// 1. Entry Price
		if (position.entry_price) {
			drawLine(position.entry_price, "#fbbf24", "ENTRY", true); // amber-400
		}

		// 2. SL - Red
		if (slPrice) {
			drawLine(slPrice, "#ef4444", "SL");
		}

		// 3. TP - Green/Blue
		if (tpPrice) {
			drawLine(tpPrice, "#22c55e", "TP");
		}

		// 4. Draw Real-time Mark Price
		if (position.mark_price) {
			drawLine(position.mark_price, "#f97316", "MARK", true, `MARK: ${position.mark_price}`); // Orange dashed line
		}

		// 5. Draw Active Partial Take Profits and Entry Orders
		if (position.partial_tp_orders && Array.isArray(position.partial_tp_orders)) {
			position.partial_tp_orders.forEach((ptp, idx) => {
				const status = String(ptp.status || "").toUpperCase();
				if (!["FILLED", "CANCELLED", "FAILED", "REJECTED"].includes(status)) {
					const isEntryOrder = isLong 
						? ptp.target_price < position.entry_price 
						: ptp.target_price > position.entry_price;

					if (isEntryOrder) {
						const label = `ENTRY (P${idx + 1}): ${ptp.target_price}`;
						drawLine(ptp.target_price, "#3b82f6", "PTP", true, label);
					} else {
						const pct = ptp.orig_fraction ? ` (${(ptp.orig_fraction * 100).toFixed(0)}%)` : "";
						const label = `TP (P${idx + 1}): ${ptp.target_price}${pct}`;
						drawLine(ptp.target_price, "#10b981", "PTP", true, label);
					}
				}
			});
		}

		// 5.5 Draw Active DCA Safety Orders (limit buys/entries)
		if (position.dca_orders && Array.isArray(position.dca_orders)) {
			position.dca_orders.forEach((dca, idx) => {
				const status = String(dca.status || "").toUpperCase();
				if (!["FILLED", "CANCELLED", "FAILED", "REJECTED", "EXPIRED"].includes(status)) {
					const label = `LIMIT BUY (S${idx + 1}): ${dca.target_price}`;
					drawLine(dca.target_price, "#3b82f6", "ENTRY", true, label);
				}
			});
		}

		// 6. Draw Executions (E1, X1 etc)
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
				line.setAttribute("x2", String(containerWidth - 60));
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

		// 7. Draw Ruler if active
		// We check refs directly to avoid stale state closure issues
		if (rulerStartRef.current && rulerCurrentRef.current) {
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
			text.textContent = `${percentDiff > 0 ? "+" : ""}${percentDiff.toFixed(2)}% ($${priceDiff.toFixed(4)})`;
			overlay.appendChild(text);
		}

		// 8. Draw "Conditions Plaque" (Static Summary) if indicators are shown
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

		// 9. Draw Decision Zones (Consolidation Boxes) from Foundation Data
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

					const zoneRec = zone as Record<string, unknown>;
					const level =
						(zoneRec.detectedLevel as number) ??
						(zoneRec.price as number) ??
						position.entry_price ??
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
						const finalX2 = x2 !== null ? x2 : containerWidth - 60;

						rect.setAttribute("x", String(Math.min(finalX1, finalX2)));
						rect.setAttribute(
							"width",
							String(Math.max(2, Math.abs(finalX2 - finalX1))),
						);

						if (isConsolidation) {
							rect.setAttribute("y", String(yTop));
							rect.setAttribute("height", String(containerHeight - yTop));
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
								lowerLabel.includes("long")
									? "#22c55e"
									: lowerLabel.includes("short")
										? "#ef4444"
										: "#fbbf24",
							);
							rect.setAttribute("stroke-width", "1");
						}
						overlay.appendChild(rect);
					}
				});
			}
		}
	}, [slPrice, tpPrice, position.entry_price, position.mark_price, position.partial_tp_orders, position.dca_orders, normalizedExecutions, showIndicators, extractedIndicators, foundationData]); // Removed isRulerActive dependency

	// Keep ref updated with latest syncOverlay function
	useEffect(() => {
		syncOverlayRef.current = syncOverlay;
	}, [syncOverlay]);

	// Initial Chart Setup
	useEffect(() => {
		if (!chartContainerRef.current || !isOpen) return;

		const container = chartContainerRef.current;
		const initialWidth = container.clientWidth || 800;
		const initialHeight = container.clientHeight || 500;

		const chart = createChart(container, {
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
				minimumWidth: 60,
			},
			handleScroll: {
				vertTouchDrag: false,
			},
		});

		chartRef.current = chart;

		const autoScaleProvider = (original: () => AutoscaleInfo | null) => {
			const res = original();
			if (res?.priceRange) {
				let { minValue, maxValue } = res.priceRange;

				if (entryPriceRef.current > 0) {
					minValue = Math.min(minValue, entryPriceRef.current);
					maxValue = Math.max(maxValue, entryPriceRef.current);
				}
				if (exitPriceRef.current > 0) {
					minValue = Math.min(minValue, exitPriceRef.current);
					maxValue = Math.max(maxValue, exitPriceRef.current);
				}

				extractedIndicatorsRef.current.localLevels.forEach((lvl: any) => {
					if (lvl.price) {
						minValue = Math.min(minValue, lvl.price);
						maxValue = Math.max(maxValue, lvl.price);
					}
				});
				extractedIndicatorsRef.current.significantLevels.forEach((lvl: any) => {
					if (lvl.price) {
						minValue = Math.min(minValue, lvl.price);
						maxValue = Math.max(maxValue, lvl.price);
					}
				});

				executionPricesRef.current.forEach((price) => {
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
		const candlestickSeries = chart.addSeries(CandlestickSeries, {
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

		// Add Volume Series
		const volumeSeries = chart.addSeries(HistogramSeries, {
			priceFormat: { type: "volume" },
			priceScaleId: "volume_pane",
		});

		chart.priceScale("volume_pane").applyOptions({
			scaleMargins: {
				top: 0.8,
				bottom: 0,
			},
			visible: false,
		});

		volumeSeriesRef.current = volumeSeries;

		// SVG Overlay
		const existingOverlay = container.querySelector("svg");
		if (existingOverlay) existingOverlay.remove();
		const svgOverlay = document.createElementNS(
			"http://www.w3.org/2000/svg",
			"svg",
		);
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
		container.style.position = "relative";
		container.appendChild(svgOverlay);
		overlayRef.current = svgOverlay;

		// Resize Observer for Main Chart
		const resizeObserverMain = new ResizeObserver((entries) => {
			if (!chart || !container) return;
			const entry = entries[0];
			if (entry) {
				const w = Math.floor(entry.contentRect.width);
				const h = Math.floor(entry.contentRect.height);
				if (w > 0 && h > 0) {
					chart.resize(w, h);
					syncOverlayRef.current();
				}
			}
		});
		resizeObserverMain.observe(container);

		// Indicators / Subcharts setup
		let indChart: IChartApi | null = null;
		let resizeObserverInd: ResizeObserver | null = null;

		const currentKlines = showIndicators && foundationData ? foundationData.klines : klines;
		const sortedKlines = [...currentKlines].sort((a, b) => Number(a.time) - Number(b.time));
		const uniqueKlines = sortedKlines.filter((k, i, arr) => i === 0 || k.time > arr[i - 1].time);

		// Populate Main candle data
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

		// Populate Volume data
		const volumeData = uniqueKlines.map((k) => ({
			time: (k.time > 1000000000000
				? Math.floor(k.time / 1000)
				: k.time) as Time,
			value: Number((k as any).volume || 0),
			color: k.close >= k.open ? "rgba(34, 197, 94, 0.5)" : "rgba(239, 68, 68, 0.5)",
		}));
		volumeSeries.setData(volumeData);

		const mainSeriesMarkers = createSeriesMarkers(candlestickSeries);

		if (showIndicators && foundationData) {
			const viz = foundationData.visualizations;

			if (Array.isArray(viz.markers) && viz.markers.length > 0) {
				mainSeriesMarkers.setMarkers(
					viz.markers
						.map((m) => ({
							...m,
							time: (Number(m.time) > 1000000000000
								? Math.floor(Number(m.time) / 1000)
								: Number(m.time)) as Time,
						}))
						.sort((a, b) => Number(a.time) - Number(b.time)),
				);
			}

			// Add main chart price lines from diagnostics levels
			viz.levels.forEach((lvl) => {
				candlestickSeries.createPriceLine({
					price: lvl.price,
					color: lvl.color || "#3B82F6",
					lineWidth: 2,
					lineStyle: LineStyle.Dashed,
					axisLabelVisible: true,
					title: lvl.label,
				});
			});

			// Split subcharts
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

			// Main overlays (Bollinger, MA)
			overlayKeys.forEach((key) => {
				const data = viz.subcharts[key];
				if (!data || data.length === 0) return;
				const series = chart.addSeries(LineSeries, {
					color: getIndicatorColor(key),
					lineWidth: 1,
					title: key,
					priceScaleId: "right",
					autoscaleInfoProvider: autoScaleProvider,
				});
				series.setData(
					data
						.map((d) => ({
							time: (Number(d.time) > 1000000000000
								? Math.floor(Number(d.time) / 1000)
								: Number(d.time)) as Time,
							value: Number(d.value),
						}))
						.sort((a, b) => a.time - b.time),
				);
			});

			// Indicator subcharts (oscillators) in bottom container
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
								.map((d) => ({
									time: (Number(d.time) > 1000000000000
										? Math.floor(Number(d.time) / 1000)
										: Number(d.time)) as Time,
									value: Number(d.value),
								}))
								.sort((a, b) => a.time - b.time);

							if (key.includes("Hist")) {
								const s = indChart?.addSeries(HistogramSeries, {
									priceScaleId: paneId,
									color: "#26a69a",
									title: key,
								});
								s.setData(
									sData.map((d) => ({
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

		// TimeScale synchronization
		if (indChart) {
			let isSyncingMain = false;
			let isSyncingInd = false;

			chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
				if (isSyncingMain || !indChart || !range) return;
				isSyncingInd = true;
				indChart.timeScale().setVisibleLogicalRange(range);
				isSyncingInd = false;
			});

			indChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
				if (isSyncingInd || !range) return;
				isSyncingMain = true;
				chart.timeScale().setVisibleLogicalRange(range);
				isSyncingMain = false;
			});
		}

		const handleTimeRangeChange = () => syncOverlayRef.current();
		const handleLogicalRangeChange = () => syncOverlayRef.current();

		chart.timeScale().subscribeVisibleTimeRangeChange(handleTimeRangeChange);
		chart.timeScale().subscribeVisibleLogicalRangeChange(handleLogicalRangeChange);
		chart.subscribeCrosshairMove((param) => {
			if (param.time) {
				crosshairTimeRef.current = param.time as number;
				setCrosshairTime(param.time as number);
			} else {
				crosshairTimeRef.current = null;
				setCrosshairTime(null);
			}
			syncOverlayRef.current();
		});

		// Initial snaps
		requestAnimationFrame(() => {
			chart.timeScale().fitContent();
			if (indChart) indChart.timeScale().fitContent();
			syncOverlayRef.current();
		});

		setTimeout(syncOverlayRef.current, 100);
		setTimeout(syncOverlayRef.current, 500);

		return () => {
			resizeObserverMain.disconnect();
			if (resizeObserverInd) resizeObserverInd.disconnect();
			chart.timeScale().unsubscribeVisibleTimeRangeChange(handleTimeRangeChange);
			chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleLogicalRangeChange);
			chart.remove();
			if (indChart) indChart.remove();
			if (chartRef.current === chart) chartRef.current = null;
			if (seriesRef.current === candlestickSeries) seriesRef.current = null;
			if (overlayRef.current === svgOverlay) overlayRef.current = null;
		};
	}, [isOpen, showIndicators, foundationData, tickSize]);

	// Update Data (including real-time updates)
	useEffect(() => {
		if (seriesRef.current && klines.length > 0) {
			const currentKlines = showIndicators && foundationData ? foundationData.klines : klines;
			const sortedKlines = [...currentKlines].sort((a, b) => Number(a.time) - Number(b.time));
			const uniqueKlines = sortedKlines.filter((k, i, arr) => i === 0 || k.time > arr[i - 1].time);

			const chartData: CandlestickData[] = uniqueKlines.map((k) => ({
				time: (k.time > 1000000000000
					? Math.floor(k.time / 1000)
					: k.time) as Time,
				open: k.open,
				high: k.high,
				low: k.low,
				close: k.close,
			}));
			seriesRef.current.setData(chartData);

			if (volumeSeriesRef.current) {
				const volumeData = uniqueKlines.map((k) => ({
					time: (k.time > 1000000000000
						? Math.floor(k.time / 1000)
						: k.time) as Time,
					value: Number((k as any).volume || 0),
					color: k.close >= k.open ? "rgba(34, 197, 94, 0.5)" : "rgba(239, 68, 68, 0.5)",
				}));
				volumeSeriesRef.current.setData(volumeData);
			}

			// Snaps overlay
			syncOverlayRef.current();
		}
	}, [klines, showIndicators, foundationData]);

	// Overlay Sync Effect
	useEffect(() => {
		requestAnimationFrame(syncOverlay);
	}, [syncOverlay]);

	// Handle Interactions (Ruler + Drag)
	const handleMouseDown = useCallback((e: React.MouseEvent) => {
		// 1. Ruler Check (Shift+Click or Middle Click)
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
				// Trigger update immediately
				syncOverlayRef.current();
			}
			return; // Don't check for dragging if starting ruler
		}

		// 2. Existing Draggable Check
		const target = e.target as Element;
		const draggable = target.closest("[data-type]");
		if (draggable) {
			const type = draggable.getAttribute("data-type");
			if (type === "SL" || type === "TP") {
				e.preventDefault();
				e.stopPropagation();
				setDraggingLine(type as "SL" | "TP");
				if (chartRef.current) {
					chartRef.current.applyOptions({
						handleScroll: false,
						handleScale: false,
					});
				}
			}
		}
	}, []);

	const handleMouseMove = useCallback(
		(e: React.MouseEvent) => {
			if (!chartRef.current || !seriesRef.current || !chartContainerRef.current)
				return;

			// Ruler Update
			if (isRulerActive && rulerStartRef.current) {
				const rect = chartContainerRef.current.getBoundingClientRect();
				const x = e.clientX - rect.left;
				const y = e.clientY - rect.top;
				const price = seriesRef.current.coordinateToPrice(y);

				if (price !== null) {
					rulerCurrentRef.current = { x, y, price };
					syncOverlayRef.current(); // Sync ruler
				}
				return;
			}

			// SL/TP Dragging Update
			if (draggingLine) {
				const rect = chartContainerRef.current.getBoundingClientRect();
				const y = e.clientY - rect.top;
				const price = seriesRef.current.coordinateToPrice(y);

				if (price) {
					if (draggingLine === "SL") {
						setSlPrice(price);
					} else {
						setTpPrice(price);
					}
					setHasChanges(true);
				}
			}
		},
		[draggingLine, isRulerActive],
	); // Added isRulerActive

	const handleMouseUp = useCallback(() => {
		// End Ruler
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
			syncOverlayRef.current();
		}

		// End Drag
		if (draggingLine) {
			slPriceRef.current = slPrice;
			tpPriceRef.current = tpPrice;

			setDraggingLine(null);
			if (chartRef.current) {
				chartRef.current.applyOptions({
					handleScroll: true,
					handleScale: true,
				});
			}
		}
	}, [draggingLine, slPrice, tpPrice, isRulerActive]);

	const handleSave = () => {
		onSave({
			stop_loss: slPrice,
			take_profit: tpPrice,
		});
		setHasChanges(false);
	};

	if (!isOpen) return null;

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
			<div className="bg-card w-full max-w-7xl rounded-xl border border-border shadow-xl overflow-hidden flex flex-col h-[70vh]">
				{/* Header */}
				<div className="flex items-center justify-between p-4 border-b border-border bg-muted/30">
					<div className="flex items-center gap-4">
						<h2 className="text-xl font-bold flex items-center gap-2">
							{position.symbol}
							<span
								className={`text-sm px-2 py-0.5 rounded ${position.direction === "LONG" ? "bg-green-500/20 text-green-500" : "bg-red-500/20 text-red-500"}`}
							>
								{position.direction}
							</span>
						</h2>

						{/* Timeframe Switcher */}
						<div className="flex items-center bg-background/50 border border-border rounded-lg p-0.5">
							{KLINE_INTERVALS.map((tf) => (
								<button
									key={tf.value}
									onClick={() => setSelectedInterval(tf.value)}
									className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${
										selectedInterval === tf.value
											? "bg-primary text-primary-foreground shadow-sm"
											: "text-muted-foreground hover:text-foreground hover:bg-muted"
									}`}
								>
									{tf.label}
								</button>
							))}
						</div>

						{hasChanges && (
							<span className="text-xs text-amber-500 flex items-center gap-1 animate-pulse">
								<AlertTriangle size={12} />
								Unsaved Changes
							</span>
						)}
					</div>
					<div className="flex items-center gap-2">
						<Button
							onClick={() => setShowIndicators(!showIndicators)}
							disabled={foundationLoading}
							variant={showIndicators ? "default" : "secondary"}
							size="sm"
							className={cn("h-9 w-9 p-0 rounded-lg", foundationLoading && "opacity-80 cursor-wait")}
							title={`${t("analytics:showIndicators", "Show Indicators")} (${usedFoundations.length})`}
						>
							{foundationLoading ? (
								<Loader2 className="w-4 h-4 animate-spin" />
							) : (
								<BarChart3 className="w-4 h-4" />
							)}
						</Button>
						<Button
							variant="ghost"
							size="sm"
							onClick={() => loadData()}
							className="text-muted-foreground"
							title="Refresh Data"
						>
							<RefreshCw
								className={`w-4 h-4 ${loading ? "animate-spin" : ""}`}
							/>
						</Button>
						<Button
							variant={hasChanges ? "default" : "secondary"}
							size="sm"
							onClick={handleSave}
							disabled={!hasChanges || isSaving}
						>
							{isSaving ? (
								<RefreshCw className="w-4 h-4 animate-spin mr-2" />
							) : (
								<Save className="w-4 h-4 mr-2" />
							)}
							{t("common:save", "Save")}
						</Button>
						<Button variant="ghost" size="icon" onClick={onClose}>
							<X className="w-5 h-5" />
						</Button>
					</div>
				</div>

				{/* Chart & Tree Container */}
				{(() => {
					const details = position.signal_details_json as {
						decision_trace?: Record<string, unknown>;
						filters_trace?: Record<string, unknown>;
						type?: string;
						result?: unknown;
					} | null;
					const potentialTrace = (details?.decision_trace || details) as Record<
						string,
						unknown
					> | null;

					const isValidTrace =
						potentialTrace &&
						typeof potentialTrace === "object" &&
						"type" in potentialTrace &&
						"result" in potentialTrace;

					return (
						<div className="flex-1 flex flex-row overflow-hidden relative">
							{/* Left Column: Decision Tree (if valid trace exists) */}
							{isValidTrace && (
								<>
									<div
										className={cn(
											"flex flex-col shrink-0 transition-all duration-300 ease-in-out overflow-hidden z-20 border-r border-border",
											showTree
												? "w-[350px] opacity-100"
												: "w-0 opacity-0 pointer-events-none",
										)}
									>
										<div className="flex items-center justify-between p-3 border-b border-border bg-muted/30">
											<h3 className="text-sm font-semibold flex items-center gap-2 truncate whitespace-nowrap">
												<span className="w-1 h-5 bg-primary rounded-full" />
												{t("decisionTree", "Decision Tree")}
											</h3>
											<Button
												variant="ghost"
												size="icon"
												className="h-7 w-7 hover:bg-muted shrink-0"
												onClick={() => setShowTree(false)}
											>
												<ChevronLeft className="h-4 w-4" />
											</Button>
										</div>

										<div className="flex-1 overflow-hidden bg-muted/20">
											<ScrollArea className="h-full w-full">
												<div className="p-3 space-y-3">
													{/* Filters Section */}
													{potentialTrace.filters_trace && (
														<div className="border border-amber-500/30 rounded-lg p-2 bg-amber-500/5">
															<div className="flex items-center gap-2 mb-2">
																<span className="text-xs font-semibold uppercase tracking-wider text-amber-500">
																	{t("filters", "Filters")}
																</span>
																{potentialTrace.filters_trace.result ? (
																	<span className="text-xs text-profit">
																		✓ {t("passed", "Passed")}
																	</span>
																) : (
																	<span className="text-xs text-loss">
																		✗ {t("failed", "Failed")}
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
																{t("entryConditions", "Entry Conditions")}
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

									{/* Button to show tree when hidden */}
									{!showTree && (
										<div className="absolute left-3 top-3 z-30">
											<Button
												variant="secondary"
												size="icon"
												className="h-9 w-9 rounded-full shadow-lg border border-border bg-card/80 backdrop-blur-sm hover:bg-muted transition-all"
												onClick={() => setShowTree(true)}
												title={t("showDecisionTree", "Show Decision Tree")}
											>
												<ChevronRight className="h-5 w-5" />
											</Button>
										</div>
									)}
								</>
							)}

							{/* Right Column: Chart */}
							<div
								className={cn(
									"flex-1 relative bg-zinc-950 flex flex-col overflow-hidden",
									isRulerActive ? "cursor-crosshair" : "",
								)}
								onMouseDown={handleMouseDown}
								onMouseMove={handleMouseMove}
								onMouseUp={handleMouseUp}
								onMouseLeave={handleMouseUp}
							>
								{loading && (
									<div className="absolute inset-0 flex items-center justify-center z-20 bg-black/50">
										<RefreshCw className="w-8 h-8 animate-spin text-primary" />
									</div>
								)}

								{/* Main Chart */}
								<div
									ref={chartContainerRef}
									className="w-full relative flex-1"
									style={{
										minHeight:
											showIndicators &&
											foundationData &&
											Object.keys(foundationData.visualizations.subcharts || {}).length > 0
												? "65%"
												: "100%",
									}}
								/>

								{/* Indicators Chart Pane */}
								{showIndicators &&
									foundationData &&
									Object.keys(foundationData.visualizations.subcharts || {}).length > 0 && (
										<div
											ref={indicatorContainerRef}
											className="w-full border-t border-border bg-black/20"
											style={{ height: "180px", flexShrink: 0 }}
										/>
									)}

								{/* Instructions Overlay */}
								<div className="absolute bottom-4 left-4 z-10 bg-black/70 backdrop-blur-sm p-3 rounded-lg border border-border/50 text-xs text-muted-foreground pointer-events-none flex flex-col gap-1.5 shadow-2xl">
									<div className="flex items-center gap-2">
										<div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
										<span className="text-foreground font-medium">
											Last Update:{" "}
											{klines.length > 0
												? format(
														new Date(klines[klines.length - 1].time),
														"HH:mm:ss",
													)
												: "--:--:--"}
										</span>
									</div>
									<div className="h-px bg-border/50 my-1" />
									<span>
										Drag the{" "}
										<span className="text-green-500 font-bold">Green (TP)</span>{" "}
										and <span className="text-red-500 font-bold">Red (SL)</span>{" "}
										lines to adjust.
									</span>
									<span className="opacity-80">
										📏 Shift+Click (or Middle Click) for ruler
									</span>
								</div>
							</div>
						</div>
					);
				})()}

				{/* Footer / Current Details */}
				<div className="p-3 border-t border-border bg-muted/10 grid grid-cols-4 gap-4 text-sm">
					<div>
						<span className="text-muted-foreground block text-xs">
							Entry Price
						</span>
						<span className="font-mono">{position.entry_price}</span>
					</div>
					<div>
						<span className="text-muted-foreground block text-xs">
							Current Price
						</span>
						<span className="font-mono">{position.mark_price}</span>
					</div>
					<div>
						<span className="text-muted-foreground block text-xs">
							Stop Loss
						</span>
						<span
							className={`font-mono ${slPrice !== position.stop_loss ? "text-amber-500 font-bold" : ""}`}
						>
							{slPrice
								? slPrice.toFixed(position.entry_price < 10 ? 4 : 2)
								: "None"}
						</span>
					</div>
					<div>
						<span className="text-muted-foreground block text-xs">
							Take Profit
						</span>
						<span
							className={`font-mono ${tpPrice !== position.take_profit ? "text-amber-500 font-bold" : ""}`}
						>
							{tpPrice
								? tpPrice.toFixed(position.entry_price < 10 ? 4 : 2)
								: "None"}
						</span>
					</div>
				</div>
			</div>
		</div>
	);
};
