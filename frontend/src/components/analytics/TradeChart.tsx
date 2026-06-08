// src/components/analytics/TradeChart.tsx

import {
	type CandlestickData,
	CandlestickSeries,
	ColorType,
	createChart,
	type IChartApi,
	type ISeriesApi,
	type PriceFormat,
	type Time,
	type UTCTimestamp,
} from "lightweight-charts";
import { AlertTriangle, CandlestickChart, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useKlines } from "@/lib/api";
import type { TradeData, TradeExecution } from "@/types/api";

interface TradeChartProps {
	trades: TradeData[];
	symbol: string;
	runId?: string;
	selectedTrade: TradeData | null;
	tickSize?: number;
}

const chartColors = {
	background: "transparent",
	textColor: "#888888",
	borderColor: "#333333",
	entryColor: "#22c55e",
	exitColor: "#ef4444",
};

const TIME_FRAMES = ["5m", "15m", "1h", "4h"];

const getPriceFormat = (tickSize?: number): PriceFormat => {
	if (tickSize === undefined || tickSize <= 0) {
		return { type: "price", precision: 4, minMove: 0.0001 };
	}
	const precision = Math.max(0, Math.ceil(-Math.log10(tickSize)));
	return {
		type: "price",
		precision,
		minMove: tickSize,
	};
};

const getTradeExecutions = (trade: TradeData): TradeExecution[] => {
	if (trade.executions && trade.executions.length > 0) {
		return trade.executions;
	}

	const entryTime = trade.timestamp_entry ?? trade.timestamp_signal;
	const exitTime = trade.timestamp_close;
	if (
		entryTime == null ||
		exitTime == null ||
		trade.entry_price == null ||
		trade.exit_price == null
	) {
		return [];
	}

	return [
		{
			timestamp: new Date(entryTime).toISOString(),
			price: trade.entry_price,
			quantity: trade.quantity ?? 0,
			type: "ENTRY",
		},
		{
			timestamp: new Date(exitTime).toISOString(),
			price: trade.exit_price,
			quantity: trade.quantity ?? 0,
			type: "EXIT",
		},
	];
};

const toTimestampSeconds = (value: string | number | Date): number | null => {
	if (typeof value === "number") {
		const normalized = value > 1_000_000_000_000 ? value / 1000 : value;
		return Number.isFinite(normalized) ? normalized : null;
	}

	const timestamp = new Date(value).getTime();
	return Number.isFinite(timestamp) ? timestamp / 1000 : null;
};

const getKlineTimeSeconds = (time: Time): number => {
	if (typeof time === "number") return time;
	if (typeof time === "string") return new Date(time).getTime() / 1000;
	return Date.UTC(time.year, time.month - 1, time.day) / 1000;
};

const appendSvgMarker = (
	svg: SVGSVGElement,
	x: number,
	y: number,
	type: TradeExecution["type"],
	direction: TradeData["direction"],
) => {
	const size = 7;
	const color =
		type === "ENTRY" ? chartColors.entryColor : chartColors.exitColor;
	const pointsUp = `${x},${y - size} ${x - size},${y + size} ${x + size},${y + size}`;
	const pointsDown = `${x},${y + size} ${x - size},${y - size} ${x + size},${y - size}`;
	const points =
		(type === "ENTRY") === (direction === "LONG") ? pointsUp : pointsDown;

	const marker = document.createElementNS(
		"http://www.w3.org/2000/svg",
		"polygon",
	);
	marker.setAttribute("points", points);
	marker.setAttribute("fill", color);
	marker.setAttribute("stroke", "#0f172a");
	marker.setAttribute("stroke-width", "1.5");
	marker.setAttribute("opacity", "0.95");
	svg.appendChild(marker);
};

export const TradeChart = ({
	trades,
	symbol,
	runId,
	selectedTrade,
	tickSize,
}: TradeChartProps) => {
	const { t } = useTranslation("analytics");
	const chartContainerRef = useRef<HTMLDivElement>(null);
	const chartRef = useRef<IChartApi | null>(null);
	const [interval, setInterval] = useState("15m");

	const { timeRange, relevantTrades } = useMemo(() => {
		if (!symbol || trades.length === 0) {
			return { timeRange: null, relevantTrades: [] };
		}
		const symbolTrades = trades.filter((trade) => trade.symbol === symbol);
		if (symbolTrades.length === 0) {
			return { timeRange: null, relevantTrades: [] };
		}

		const tradeTimestamps = symbolTrades
			.flatMap((trade) => [
				trade.timestamp_signal,
				trade.timestamp_entry,
				trade.timestamp_close,
			])
			.filter((timestamp): timestamp is number => timestamp !== undefined);
		const executionTimestamps = symbolTrades
			.flatMap((trade) => getTradeExecutions(trade))
			.map((exec) => toTimestampSeconds(exec.timestamp))
			.filter((timestamp): timestamp is number => timestamp !== null)
			.map((timestamp) => timestamp * 1000);
		const allTimestamps = [...tradeTimestamps, ...executionTimestamps];
		const minTimestamp =
			allTimestamps.length > 0 ? Math.min(...allTimestamps) : 0;
		const maxTimestamp =
			allTimestamps.length > 0
				? Math.max(...allTimestamps)
				: 24 * 60 * 60 * 1000;
		const padding = (maxTimestamp - minTimestamp) * 0.1 || 60 * 60 * 1000;

		return {
			timeRange: {
				startTime: Math.max(0, minTimestamp - padding),
				endTime: maxTimestamp + padding,
			},
			relevantTrades: symbolTrades,
		};
	}, [trades, symbol]);

	const {
		data: klines,
		isLoading: klinesLoading,
		isError: klinesError,
		error: klinesApiError,
	} = useKlines(
		{
			symbol: symbol || "",
			interval,
			startTime: timeRange?.startTime,
			endTime: timeRange?.endTime,
			limit: 1000,
			runId,
		},
		{ enabled: !!symbol && !!timeRange },
	);

	useEffect(() => {
		if (!chartContainerRef.current || !klines || klines.length === 0) return;

		chartContainerRef.current.innerHTML = "";
		chartContainerRef.current.style.position = "relative";

		const priceFormat = getPriceFormat(tickSize);

		const chart = createChart(chartContainerRef.current, {
			width: chartContainerRef.current.clientWidth,
			height: 500,
			layout: {
				background: { type: ColorType.Solid, color: chartColors.background },
				textColor: chartColors.textColor,
			},
			grid: {
				vertLines: { color: chartColors.borderColor },
				horzLines: { color: chartColors.borderColor },
			},
			timeScale: { borderColor: chartColors.borderColor, timeVisible: true },
		});
		chartRef.current = chart;

		const candleSeries = chart.addSeries(CandlestickSeries, {
			upColor: chartColors.entryColor,
			downColor: chartColors.exitColor,
			borderVisible: false,
			wickUpColor: chartColors.entryColor,
			wickDownColor: chartColors.exitColor,
			priceFormat,
		});

		const klineData: CandlestickData[] = klines.map((kline) => ({
			time: (Number(kline[0]) / 1000) as UTCTimestamp,
			open: parseFloat(String(kline[1])),
			high: parseFloat(String(kline[2])),
			low: parseFloat(String(kline[3])),
			close: parseFloat(String(kline[4])),
		}));
		const klineTimes = klineData
			.map((kline) => getKlineTimeSeconds(kline.time))
			.sort((a, b) => a - b);
		const defaultInterval =
			klineTimes.length > 1 ? klineTimes[1] - klineTimes[0] : 60;

		candleSeries.setData(klineData);

		const overlaySvg = document.createElementNS(
			"http://www.w3.org/2000/svg",
			"svg",
		);
		overlaySvg.style.position = "absolute";
		overlaySvg.style.inset = "0";
		overlaySvg.style.width = "100%";
		overlaySvg.style.height = "100%";
		overlaySvg.style.pointerEvents = "none";
		overlaySvg.style.zIndex = "5";
		chartContainerRef.current.appendChild(overlaySvg);

		const timeToOverlayCoordinate = (rawSeconds: number): number | null => {
			if (!Number.isFinite(rawSeconds) || klineTimes.length === 0) return null;

			let left = 0;
			let right = klineTimes.length - 1;
			let matchedIndex = -1;
			while (left <= right) {
				const mid = Math.floor((left + right) / 2);
				if (klineTimes[mid] <= rawSeconds) {
					matchedIndex = mid;
					left = mid + 1;
				} else {
					right = mid - 1;
				}
			}

			const index = Math.max(0, matchedIndex);
			const currentTime = klineTimes[index];
			const nextTime = klineTimes[index + 1] ?? currentTime + defaultInterval;
			const currentX = chart
				.timeScale()
				.timeToCoordinate(currentTime as UTCTimestamp);
			if (currentX == null) return null;

			const nextX = chart
				.timeScale()
				.timeToCoordinate(nextTime as UTCTimestamp);
			if (nextX == null || nextTime <= currentTime) return currentX;

			const progress = Math.max(
				0,
				Math.min(1, (rawSeconds - currentTime) / (nextTime - currentTime)),
			);
			return currentX + (nextX - currentX) * progress;
		};

		const syncExecutionOverlay = () => {
			if (!chartContainerRef.current) return;
			const { clientWidth, clientHeight } = chartContainerRef.current;
			overlaySvg.setAttribute("width", String(clientWidth));
			overlaySvg.setAttribute("height", String(clientHeight));
			overlaySvg.setAttribute("viewBox", `0 0 ${clientWidth} ${clientHeight}`);
			overlaySvg.innerHTML = "";

			relevantTrades.forEach((trade: TradeData) => {
				getTradeExecutions(trade).forEach((exec: TradeExecution) => {
					const executionTime = toTimestampSeconds(exec.timestamp);
					if (executionTime == null || !Number.isFinite(exec.price)) return;
					const x = timeToOverlayCoordinate(executionTime);
					const y = (
						candleSeries as ISeriesApi<"Candlestick">
					).priceToCoordinate(exec.price);
					if (x == null || y == null) return;
					appendSvgMarker(overlaySvg, x, y, exec.type, trade.direction);
				});
			});
		};

		chart.timeScale().fitContent();
		syncExecutionOverlay();
		const overlayTimer = window.setTimeout(syncExecutionOverlay, 0);
		chart.timeScale().subscribeVisibleTimeRangeChange(syncExecutionOverlay);

		const handleResize = () => {
			chart.applyOptions({ width: chartContainerRef.current?.clientWidth });
			syncExecutionOverlay();
		};
		window.addEventListener("resize", handleResize);

		return () => {
			window.clearTimeout(overlayTimer);
			chart.timeScale().unsubscribeVisibleTimeRangeChange(syncExecutionOverlay);
			window.removeEventListener("resize", handleResize);
			chart.remove();
		};
	}, [klines, relevantTrades, tickSize]);

	useEffect(() => {
		if (
			selectedTrade &&
			chartRef.current &&
			selectedTrade.timestamp_signal &&
			selectedTrade.timestamp_close
		) {
			const chart = chartRef.current;
			const from = (selectedTrade.timestamp_signal / 1000) as UTCTimestamp;
			const to = (selectedTrade.timestamp_close / 1000) as UTCTimestamp;
			const duration = to - from;
			const padding = duration > 0 ? duration * 0.5 : 60 * 15;

			chart.timeScale().setVisibleRange({
				from: (from - padding) as UTCTimestamp,
				to: (to + padding) as UTCTimestamp,
			});
		}
	}, [selectedTrade]);

	const renderChartContent = () => {
		if (!symbol) {
			return (
				<div className="h-[500px] flex items-center justify-center text-muted-foreground">
					{t("selectSymbolToViewChart")}
				</div>
			);
		}

		if (klinesLoading) {
			return (
				<div className="h-[500px] flex justify-center items-center">
					<Loader2 className="h-8 w-8 animate-spin text-primary" />
				</div>
			);
		}

		if (klinesError) {
			return (
				<div className="h-[500px] flex items-center justify-center p-4">
					<Alert variant="destructive" className="my-4">
						<AlertTriangle className="h-4 w-4" />
						<AlertTitle>Error loading kline data for {symbol}</AlertTitle>
						<AlertDescription>
							{klinesApiError?.message ||
								"Chart data is not available for this symbol"}
						</AlertDescription>
					</Alert>
				</div>
			);
		}

		if (!klines || klines.length === 0) {
			return (
				<div className="h-[500px] flex items-center justify-center text-muted-foreground">
					No kline data available for {symbol} in this period.
				</div>
			);
		}

		return (
			<div ref={chartContainerRef} style={{ height: "500px", width: "100%" }} />
		);
	};

	return (
		<Card className="mt-6">
			<CardHeader>
				<div className="flex justify-between items-center">
					<CardTitle className="flex items-center">
						<CandlestickChart className="w-5 h-5 mr-2" />
						{t("tradeChart.title")}
					</CardTitle>
					<ToggleGroup
						type="single"
						defaultValue="15m"
						aria-label="Timeframe"
						value={interval}
						onValueChange={(value) => {
							if (value) setInterval(value);
						}}
					>
						{TIME_FRAMES.map((tf) => (
							<ToggleGroupItem key={tf} value={tf} aria-label={`Select ${tf}`}>
								{tf}
							</ToggleGroupItem>
						))}
					</ToggleGroup>
				</div>
			</CardHeader>
			<CardContent>{renderChartContent()}</CardContent>
		</Card>
	);
};
