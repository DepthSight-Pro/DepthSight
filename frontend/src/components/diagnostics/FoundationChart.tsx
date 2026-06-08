// frontend/src/components/diagnostics/FoundationChart.tsx

import {
	AreaSeries,
	type CandlestickData,
	CandlestickSeries,
	ColorType,
	createChart,
	createSeriesMarkers,
	HistogramSeries,
	type ISeriesApi,
	type LineData,
	LineSeries,
	LineStyle,
	type LineWidth,
	type Time,
	type UTCTimestamp,
	type WhitespaceData,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

export interface KlineData {
	time: number;
	open: number;
	high: number;
	low: number;
	close: number;
	volume: number;
}
export interface LevelData {
	time: number;
	price: number;
	type: string;
	label: string;
	color?: string;
}
export interface MarkerData {
	time: number;
	position: "aboveBar" | "belowBar" | "inBar";
	color: string;
	shape: "circle" | "square" | "arrowUp" | "arrowDown";
	text?: string;
	size?: number;
}
export interface ZoneData {
	startTime: number;
	endTime: number;
	start_time?: number;
	end_time?: number;
	type: string;
	label: string;
	color?: string;
}
export interface TradeOverlayExecution {
	timestamp: string | number;
	price: number;
	quantity?: number;
	type: "ENTRY" | "EXIT";
}
export interface TradeOverlayData {
	executions: TradeOverlayExecution[];
	entryPrice?: number;
	exitPrice?: number;
	entryTime?: string | number;
	exitTime?: string | number;
	direction?: "LONG" | "SHORT" | string;
	showAverageLines?: boolean;
	showPercent?: boolean;
	showLabels?: boolean;
}
export interface SubchartPoint {
	time: number;
	value: number;
	color?: string;
	[key: string]: unknown;
}
export interface FoundationChartProps {
	klines: KlineData[];
	visualizations: {
		levels: LevelData[];
		markers: MarkerData[];
		zones: ZoneData[];
		subcharts: Record<string, SubchartPoint[]>;
	};
	tradeOverlay?: TradeOverlayData;
	initialVisibleRange?: {
		from: number;
		to: number;
	};
}
const levelColors: { [key: string]: string } = {
	significant_level: "#2962ff",
	local_level: "#e91e63",
	round_level: "#ff9800",
	default: "#9c27b0",
};

const toTimestampSeconds = (
	value: string | number | null | undefined,
): number | null => {
	if (value == null) return null;

	if (typeof value === "number") {
		const normalized = value > 1_000_000_000_000 ? value / 1000 : value;
		return Number.isFinite(normalized) ? normalized : null;
	}

	const trimmed = value.trim();
	const hasExplicitTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
	const looksLikeIsoDateTime = /^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}/.test(
		trimmed,
	);
	const normalized =
		looksLikeIsoDateTime && !hasExplicitTimezone
			? `${trimmed.replace(" ", "T")}Z`
			: trimmed;
	const timestamp = new Date(normalized).getTime();
	return Number.isFinite(timestamp) ? timestamp / 1000 : null;
};

const getKlineTimeSeconds = (time: Time): number => {
	if (typeof time === "number") return time;
	if (typeof time === "string") return toTimestampSeconds(time) ?? 0;
	return Date.UTC(time.year, time.month - 1, time.day) / 1000;
};

const appendLine = (
	svg: SVGSVGElement,
	x1: number,
	y1: number,
	x2: number,
	y2: number,
	color: string,
) => {
	const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
	line.setAttribute("x1", String(x1));
	line.setAttribute("y1", String(y1));
	line.setAttribute("x2", String(x2));
	line.setAttribute("y2", String(y2));
	line.setAttribute("stroke", color);
	line.setAttribute("stroke-width", "1");
	line.setAttribute("stroke-dasharray", "4,4");
	svg.appendChild(line);
};

const appendPriceCircle = (
	svg: SVGSVGElement,
	x: number,
	y: number,
	color: string,
) => {
	const circle = document.createElementNS(
		"http://www.w3.org/2000/svg",
		"circle",
	);
	circle.setAttribute("cx", String(x));
	circle.setAttribute("cy", String(y));
	circle.setAttribute("r", "4");
	circle.setAttribute("fill", color);
	circle.setAttribute("stroke", "#0f172a");
	circle.setAttribute("stroke-width", "1.5");
	svg.appendChild(circle);
};

const appendTradeMarker = (
	svg: SVGSVGElement,
	x: number,
	y: number,
	type: TradeOverlayExecution["type"],
	direction: string | undefined,
	label?: string,
) => {
	const size = 8;
	const color = type === "ENTRY" ? "#22c55e" : "#ef4444";
	const isLong = String(direction || "LONG").toUpperCase() !== "SHORT";
	const pointsUp = `${x},${y - size} ${x - size},${y + size} ${x + size},${y + size}`;
	const pointsDown = `${x},${y + size} ${x - size},${y - size} ${x + size},${y - size}`;
	const points = (type === "ENTRY") === isLong ? pointsUp : pointsDown;

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

	if (label) {
		const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
		text.setAttribute("x", String(x + 10));
		text.setAttribute("y", String(y - 10));
		text.setAttribute("fill", color);
		text.setAttribute("font-size", "11");
		text.setAttribute("font-weight", "700");
		text.setAttribute("paint-order", "stroke");
		text.setAttribute("stroke", "#0f172a");
		text.setAttribute("stroke-width", "3");
		text.textContent = label;
		svg.appendChild(text);
	}
};

export const FoundationChart = ({
	klines,
	visualizations,
	tradeOverlay,
	initialVisibleRange,
}: FoundationChartProps) => {
	const chartContainerRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		if (!chartContainerRef.current || !klines || klines.length === 0) return;

		chartContainerRef.current.innerHTML = "";
		chartContainerRef.current.style.position = "relative";

		const chart = createChart(chartContainerRef.current, {
			width: chartContainerRef.current.clientWidth,
			height: chartContainerRef.current.clientHeight,
			layout: {
				background: { type: ColorType.Solid, color: "transparent" },
				textColor: "#888888",
			},
			grid: {
				vertLines: { color: "#333333" },
				horzLines: { color: "#333333" },
			},
			timeScale: {
				borderColor: "#333333",
				timeVisible: true,
			},
		});

		const candleSeries = chart.addSeries(CandlestickSeries, {
			upColor: "#22c55e",
			downColor: "#ef4444",
			borderVisible: false,
			wickUpColor: "#22c55e",
			wickDownColor: "#ef4444",
		});
		const markers = createSeriesMarkers(candleSeries);

		const sortedKlines = [...klines].sort((a, b) => a.time - b.time);
		const uniqueKlines = sortedKlines.filter(
			(k, i, arr) => i === 0 || k.time > arr[i - 1].time,
		);

		const klineData: CandlestickData[] = uniqueKlines.map((k) => ({
			time: k.time as UTCTimestamp,
			open: k.open,
			high: k.high,
			low: k.low,
			close: k.close,
		}));
		const klineTimes = klineData
			.map((k) => getKlineTimeSeconds(k.time))
			.sort((a, b) => a - b);
		const defaultInterval =
			klineTimes.length > 1 ? klineTimes[1] - klineTimes[0] : 60;

		const volumeData = uniqueKlines.map((k) => ({
			time: k.time as UTCTimestamp,
			value: k.volume,
			color:
				k.close > k.open ? "rgba(34, 197, 94, 0.5)" : "rgba(239, 68, 68, 0.5)",
		}));

		// 1. FIRST create the series and bind it to the new scale ID
		const volumeSeries = chart.addSeries(HistogramSeries, {
			priceFormat: {
				type: "volume",
			},
			priceScaleId: "volume_scale",
		});

		// 2. NOW, when the scale is created, we can access and configure it
		chart.priceScale("volume_scale").applyOptions({
			scaleMargins: {
				top: 0.8, // 80% top margin
				bottom: 0,
			},
			// Make the scale itself (lines and numbers) invisible
			visible: false,
		});

		volumeSeries.setData(volumeData);
		candleSeries.setData(
			klineData.sort((a, b) => (a.time as number) - (b.time as number)),
		);

		if (
			visualizations?.zones &&
			visualizations.zones.length > 0 &&
			klines.length > 1
		) {
			const interval = klines[1].time - klines[0].time;
			const lastKlineTime = klines[klines.length - 1].time;

			visualizations.zones.forEach((zone) => {
				if (zone.endTime === lastKlineTime) {
					zone.endTime += interval;
				}
			});
		}

		if (visualizations?.levels) {
			visualizations.levels.forEach((level) => {
				candleSeries.createPriceLine({
					price: level.price,
					color: levelColors[level.type] || levelColors.default,
					lineWidth: 2 as LineWidth,
					lineStyle: LineStyle.Dashed,
					axisLabelVisible: true,
					title: level.label,
				});
			});
		}
		if (visualizations?.markers) {
			markers.setMarkers(
				visualizations.markers.map((m) => ({
					...m,
					time: m.time as UTCTimestamp,
				})),
			);
		}
		if (visualizations?.zones && visualizations.zones.length > 0) {
			// Each zone gets its own AreaSeries to ensure they render as separate shelves,
			// even when zones overlap in time (e.g. Zone 4: 13:21-13:33 and Zone 5: 13:25-13:34).
			visualizations.zones.forEach((zone) => {
				const zoneColor = zone.label.includes("Long")
					? "rgba(0, 255, 0, 0.15)"
					: zone.label.includes("Short")
						? "rgba(255, 0, 0, 0.15)"
						: zone.color || "rgba(128, 128, 128, 0.2)";
				const zoneSeries = chart.addSeries(AreaSeries, {
					priceScaleId: "left",
					topColor: zoneColor,
					bottomColor: "rgba(0,0,0,0)",
					lineColor: "transparent",
					autoscaleInfoProvider: () => ({
						priceRange: { minValue: 0, maxValue: 1 },
					}),
				});
				const seriesData: (LineData | WhitespaceData)[] = [
					{ time: zone.startTime as UTCTimestamp, value: 1 },
					{ time: zone.endTime as UTCTimestamp, value: 1 },
					{ time: (zone.endTime + 1) as UTCTimestamp }, // Whitespace break after zone
				];
				zoneSeries.setData(seriesData);
			});
		}
		if (visualizations?.subcharts) {
			const subchartKeys = Object.keys(visualizations.subcharts);

			// 1. Identify Overlays vs Pane Indicators
			const overlayPrefixes = ["BB_", "MA_", "SMA_", "EMA_", "PA_"];
			const overlayKeys = subchartKeys.filter((k) =>
				overlayPrefixes.some((pre) => k.startsWith(pre)),
			);
			const indicatorKeys = subchartKeys.filter(
				(k) => !overlayPrefixes.some((pre) => k.startsWith(pre)),
			);

			// 2. Render Overlays on Main Chart
			overlayKeys.forEach((key) => {
				const data = visualizations.subcharts[key];
				if (data && data.length > 0) {
					let color = "#2962FF";
					const style = LineStyle.Solid;
					let lineWidth = 2;

					if (key.includes("Middle") || key.includes("Slow")) {
						color = "#f57c00"; // Orange for slower/middle
					} else if (key.includes("Fast")) {
						color = "#2962FF"; // Blue for fast
					} else if (key.includes("Lower") || key.includes("Upper")) {
						color = "#2196F3";
						lineWidth = 1;
					}

					if (key.includes("BB_")) lineWidth = 1;

					const series = chart.addSeries(LineSeries, {
						color: color,
						lineWidth: lineWidth as LineWidth,
						lineStyle: style,
						priceScaleId: "right", // Main chart scale
						title: key.replace(/_/g, " "),
					});
					series.setData(
						[...data]
							.sort((a, b) => a.time - b.time)
							.map((point) => ({
								time: point.time as UTCTimestamp,
								value: point.value,
							})),
					);
				}
			});

			// 3. Group Indicators into Panes
			// We define "Pane Groups" based on key prefixes or specific logic
			const paneGroups: Record<string, string[]> = {};

			indicatorKeys.forEach((key) => {
				let paneId = key; // Default: one pane per key

				if (key.startsWith("MACD")) paneId = "MACD";
				if (key.startsWith("Stoch")) paneId = "Stochastic";
				if (key.startsWith("RSI")) paneId = "RSI";

				if (!paneGroups[paneId]) paneGroups[paneId] = [];
				paneGroups[paneId].push(key);
			});

			const paneIds = Object.keys(paneGroups);
			const paneCount = paneIds.length;

			// 4. Render Panes
			if (paneCount > 0) {
				// Layout Logic:
				// Main Chart: 60% min, but shrinks if many panes.
				// Panes share the remaining space.
				const totalPaneHeightFraction = Math.min(0.5, paneCount * 0.15); // Max 50% for indicators
				const mainChartHeight = 1.0 - totalPaneHeightFraction;
				const singlePaneHeight = totalPaneHeightFraction / paneCount;

				// Adjust Main Chart
				candleSeries.priceScale().applyOptions({
					scaleMargins: {
						top: 0.05,
						bottom: totalPaneHeightFraction + 0.05, // Leave room at bottom
					},
				});

				paneIds.forEach((paneId, index) => {
					const keysInPane = paneGroups[paneId];

					// Calculate Geometry
					const topMargin = mainChartHeight + index * singlePaneHeight;
					const bottomMargin = 1.0 - (topMargin + singlePaneHeight);

					// Configure Scale for this Pane
					chart.priceScale(paneId).applyOptions({
						scaleMargins: {
							top: topMargin,
							bottom: bottomMargin,
						},
						visible: true,
						borderColor: "#333333",
					});

					// Render Series in this Pane
					keysInPane.forEach((key) => {
						const data = visualizations.subcharts[key];
						if (!data || data.length === 0) return;

						const sortedData = [...data].sort((a, b) => a.time - b.time);
						const uniqueData = sortedData.filter(
							(d, i, arr) => i === 0 || d.time > arr[i - 1].time,
						);

						if (key.includes("Hist")) {
							// MACD Histogram -> Histogram Series
							const series = chart.addSeries(HistogramSeries, {
								priceScaleId: paneId,
								color: "#26a69a",
								priceFormat: { type: "volume" }, // approximate
								title: key,
							});
							// Colorize histogram based on value
							const colorizedData = uniqueData.map((d) => ({
								time: d.time as UTCTimestamp,
								value: d.value,
								color: d.value >= 0 ? "#26a69a" : "#ef5350",
							}));
							series.setData(colorizedData);
						} else {
							// Line Series
							let color = "#78909C";
							if (key.includes("MACD_Line")) color = "#2962FF"; // Blue
							if (key.includes("MACD_Signal")) color = "#FF6D00"; // Orange
							if (key.includes("RSI")) color = "#E91E63";
							if (key.includes("Stoch_K")) color = "#2962FF";
							if (key.includes("Stoch_D")) color = "#FF6D00";
							if (key === "ADX") color = "#4CAF50";
							if (key === "ATR") color = "#FF5722";

							const series = chart.addSeries(LineSeries, {
								priceScaleId: paneId,
								color: color,
								lineWidth: 1,
								title: key,
							});
							series.setData(
								uniqueData.map((point) => ({
									time: point.time as UTCTimestamp,
									value: point.value,
								})),
							);
						}
					});
				});
			}
		}

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

		const syncTradeOverlay = () => {
			if (!chartContainerRef.current) return;
			const { clientWidth, clientHeight } = chartContainerRef.current;
			overlaySvg.setAttribute("width", String(clientWidth));
			overlaySvg.setAttribute("height", String(clientHeight));
			overlaySvg.setAttribute("viewBox", `0 0 ${clientWidth} ${clientHeight}`);
			overlaySvg.innerHTML = "";

			if (!tradeOverlay) return;

			const executions = [...(tradeOverlay.executions || [])]
				.map((execution) => ({
					...execution,
					timestampSec: toTimestampSeconds(execution.timestamp),
					price: Number(execution.price),
					type:
						String(execution.type).toUpperCase() === "ENTRY"
							? ("ENTRY" as const)
							: ("EXIT" as const),
				}))
				.filter(
					(execution) =>
						execution.timestampSec !== null &&
						Number.isFinite(execution.price) &&
						execution.price > 0,
				)
				.sort((a, b) => (a.timestampSec || 0) - (b.timestampSec || 0));

			const entryTime =
				toTimestampSeconds(tradeOverlay.entryTime) ??
				executions.find((execution) => execution.type === "ENTRY")
					?.timestampSec ??
				executions[0]?.timestampSec ??
				null;
			const exitTime =
				toTimestampSeconds(tradeOverlay.exitTime) ??
				[...executions].reverse().find((execution) => execution.type === "EXIT")
					?.timestampSec ??
				executions[executions.length - 1]?.timestampSec ??
				null;
			const entryPrice = Number(tradeOverlay.entryPrice);
			const exitPrice = Number(tradeOverlay.exitPrice);
			const rightEdge = Math.max(0, clientWidth - 60);

			if (
				tradeOverlay.showAverageLines &&
				Number.isFinite(entryPrice) &&
				entryPrice > 0 &&
				entryTime !== null
			) {
				const x = timeToOverlayCoordinate(entryTime);
				const y = (candleSeries as ISeriesApi<"Candlestick">).priceToCoordinate(
					entryPrice,
				);
				if (x != null && y != null) {
					appendLine(overlaySvg, x, y, rightEdge, y, "#22c55e");
					appendPriceCircle(overlaySvg, x, y, "#22c55e");
				}
			}

			if (
				tradeOverlay.showAverageLines &&
				Number.isFinite(exitPrice) &&
				exitPrice > 0 &&
				exitTime !== null
			) {
				const x = timeToOverlayCoordinate(exitTime);
				const y = (candleSeries as ISeriesApi<"Candlestick">).priceToCoordinate(
					exitPrice,
				);
				if (x != null && y != null) {
					appendLine(overlaySvg, x, y, rightEdge, y, "#ef4444");
					appendPriceCircle(overlaySvg, x, y, "#ef4444");
				}
			}

			const counters: Record<"ENTRY" | "EXIT", number> = { ENTRY: 0, EXIT: 0 };
			executions.forEach((execution) => {
				if (execution.timestampSec === null) return;
				counters[execution.type] += 1;
				const x = timeToOverlayCoordinate(execution.timestampSec);
				const y = (candleSeries as ISeriesApi<"Candlestick">).priceToCoordinate(
					execution.price,
				);
				if (x == null || y == null) return;
				appendTradeMarker(
					overlaySvg,
					x,
					y,
					execution.type,
					tradeOverlay.direction,
					tradeOverlay.showLabels
						? `${execution.type === "ENTRY" ? "E" : "X"}${counters[execution.type]}`
						: undefined,
				);
			});

			if (
				tradeOverlay.showPercent &&
				Number.isFinite(entryPrice) &&
				Number.isFinite(exitPrice) &&
				entryPrice > 0 &&
				exitPrice > 0
			) {
				const entryY = (
					candleSeries as ISeriesApi<"Candlestick">
				).priceToCoordinate(entryPrice);
				const exitY = (
					candleSeries as ISeriesApi<"Candlestick">
				).priceToCoordinate(exitPrice);
				if (entryY != null && exitY != null) {
					const isShort =
						String(tradeOverlay.direction || "").toUpperCase() === "SHORT";
					const percent = isShort
						? ((entryPrice - exitPrice) / entryPrice) * 100
						: ((exitPrice - entryPrice) / entryPrice) * 100;
					const label = `${percent >= 0 ? "+" : ""}${percent.toFixed(2)}%`;
					const labelX = Math.max(
						8,
						Math.min(clientWidth - 96, rightEdge - 90),
					);
					const labelY = Math.max(
						18,
						Math.min(clientHeight - 8, (entryY + exitY) / 2),
					);
					const rect = document.createElementNS(
						"http://www.w3.org/2000/svg",
						"rect",
					);
					rect.setAttribute("x", String(labelX - 6));
					rect.setAttribute("y", String(labelY - 15));
					rect.setAttribute("width", "84");
					rect.setAttribute("height", "22");
					rect.setAttribute("rx", "4");
					rect.setAttribute(
						"fill",
						percent >= 0
							? "rgba(34, 197, 94, 0.18)"
							: "rgba(239, 68, 68, 0.18)",
					);
					rect.setAttribute("stroke", percent >= 0 ? "#22c55e" : "#ef4444");
					rect.setAttribute("stroke-width", "1");
					overlaySvg.appendChild(rect);

					const text = document.createElementNS(
						"http://www.w3.org/2000/svg",
						"text",
					);
					text.setAttribute("x", String(labelX));
					text.setAttribute("y", String(labelY));
					text.setAttribute("fill", percent >= 0 ? "#22c55e" : "#ef4444");
					text.setAttribute("font-size", "12");
					text.setAttribute("font-weight", "700");
					text.textContent = label;
					overlaySvg.appendChild(text);
				}
			}
		};

		if (
			initialVisibleRange &&
			initialVisibleRange.from < initialVisibleRange.to
		) {
			chart.timeScale().setVisibleRange({
				from: initialVisibleRange.from as UTCTimestamp,
				to: initialVisibleRange.to as UTCTimestamp,
			});
		} else {
			chart.timeScale().fitContent();
		}
		syncTradeOverlay();
		const overlayTimers = [
			window.setTimeout(syncTradeOverlay, 0),
			window.setTimeout(syncTradeOverlay, 150),
			window.setTimeout(syncTradeOverlay, 500),
		];
		chart.timeScale().subscribeVisibleTimeRangeChange(syncTradeOverlay);

		const handleResize = () => {
			if (chartContainerRef.current) {
				chart.applyOptions({
					width: chartContainerRef.current.clientWidth,
					height: chartContainerRef.current.clientHeight,
				});
				syncTradeOverlay();
			}
		};
		window.addEventListener("resize", handleResize);

		return () => {
			overlayTimers.forEach((timer) => {
				window.clearTimeout(timer);
			});
			chart.timeScale().unsubscribeVisibleTimeRangeChange(syncTradeOverlay);
			window.removeEventListener("resize", handleResize);
			chart.remove();
		};
	}, [klines, visualizations, tradeOverlay, initialVisibleRange]);

	return (
		<div ref={chartContainerRef} style={{ height: "100%", width: "100%" }} />
	);
};
