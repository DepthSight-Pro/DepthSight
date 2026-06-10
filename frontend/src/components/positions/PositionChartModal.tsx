// src/components/positions/PositionChartModal.tsx

import { format } from "date-fns";
import {
	type AutoscaleInfo,
	type CandlestickData,
	CandlestickSeries,
	ColorType,
	CrosshairMode,
	createChart,
	type IChartApi,
	type ISeriesApi,
	type Time,
} from "lightweight-charts";
import {
	AlertTriangle,
	ChevronLeft,
	ChevronRight,
	RefreshCw,
	Save,
	X,
} from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
	DecisionTraceTree,
	type TraceNode,
} from "@/components/research/DecisionTraceTree";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import {
	fetchKlines,
	KLINE_INTERVALS,
	type Kline,
	type KlineInterval,
} from "@/services/binanceService";
import type { PositionData } from "@/types/api";

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
	const { t } = useTranslation(["positions", "common"]);
	const chartContainerRef = useRef<HTMLDivElement>(null);
	const chartRef = useRef<IChartApi | null>(null);
	const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
	const overlayRef = useRef<SVGSVGElement | null>(null);
	const syncOverlayRef = useRef<() => void>(() => {});

	const [klines, setKlines] = useState<Kline[]>([]);
	const [loading, setLoading] = useState(true);
	const [interval, setInterval] = useState<KlineInterval>("1m");

	// Editable SL/TP state
	const [slPrice, setSlPrice] = useState<number | null>(
		position.stop_loss || null,
	);
	const [tpPrice, setTpPrice] = useState<number | null>(
		position.take_profit || null,
	);
	const [hasChanges, setHasChanges] = useState(false);

	// Decision Tree state (collapsed by default)
	const [showTree, setShowTree] = useState(false);

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

	// Update refs when state changes
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
		}
	}, [position]);

	// Load Klines
	const loadData = useCallback(async () => {
		if (!isOpen) return;
		setLoading(true);
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

			const data = await fetchKlines(position.symbol, startTime, now, interval);
			setKlines(data);
		} catch (e) {
			console.error("Failed to load chart data", e);
			toast.error(t("common:errors.unknownError"));
		} finally {
			setLoading(false);
		}
	}, [isOpen, position.symbol, position.entry_time, interval, t]);

	useEffect(() => {
		loadData();
	}, [loadData]);

	// Sync Overlay (drawing lines)
	const syncOverlay = useCallback(() => {
		if (
			!chartRef.current ||
			!seriesRef.current ||
			!overlayRef.current ||
			!chartContainerRef.current
		)
			return;

		const series = seriesRef.current;
		const overlay = overlayRef.current;
		const containerWidth = chartContainerRef.current.clientWidth;

		// Clear existing
		overlay.innerHTML = "";

		const drawLine = (
			price: number,
			color: string,
			type: "ENTRY" | "SL" | "TP",
			isDashed = false,
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
			line.setAttribute("stroke-width", type === "ENTRY" ? "1" : "2");
			if (isDashed) line.setAttribute("stroke-dasharray", "4,4");

			// Add Data attributes for hit testing
			if (type !== "ENTRY") {
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

			const labelText = `${type}: ${price}`;
			text.textContent = labelText;
			text.setAttribute("fill", "white");
			text.setAttribute("font-size", "10px");
			text.setAttribute("font-weight", "bold");

			// Approx text width
			const textWidth = labelText.length * 6 + 10;

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
			if (type !== "ENTRY") {
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

		// 4. Draw Ruler if active
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
	}, [slPrice, tpPrice, position.entry_price]); // Removed isRulerActive dependency

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
				textColor: "#d1d5db",
				background: { type: ColorType.Solid, color: "#09090b" },
			},
			grid: {
				vertLines: { color: "#27272a" },
				horzLines: { color: "#27272a" },
			},
			crosshair: {
				mode: CrosshairMode.Normal,
			},
			timeScale: {
				borderColor: "#27272a",
				timeVisible: true,
			},
			rightPriceScale: {
				borderColor: "#27272a",
			},
			handleScroll: {
				vertTouchDrag: false,
			},
		});

		const candleSeries = chart.addSeries(CandlestickSeries, {
			upColor: "#22c55e",
			downColor: "#ef4444",
			borderVisible: false,
			wickUpColor: "#22c55e",
			wickDownColor: "#ef4444",
		});

		// Apply autoscale provider ONCE here
		candleSeries.applyOptions({
			autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
				const res = original();
				if (res?.priceRange) {
					let min = res.priceRange.minValue;
					let max = res.priceRange.maxValue;

					// Use refs
					const currentSl = slPriceRef.current;
					const currentTp = tpPriceRef.current;

					if (currentSl !== null) {
						min = Math.min(min, currentSl);
						max = Math.max(max, currentSl);
					}
					if (currentTp !== null) {
						min = Math.min(min, currentTp);
						max = Math.max(max, currentTp);
					}

					const range = max - min;
					return {
						priceRange: {
							minValue: min - range * 0.05,
							maxValue: max + range * 0.05,
						},
					};
				}
				return res;
			},
		});

		seriesRef.current = candleSeries;
		chartRef.current = chart;

		// Overlay
		const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
		svg.style.position = "absolute";
		svg.style.top = "0";
		svg.style.left = "0";
		svg.style.width = "100%";
		svg.style.height = "100%";
		svg.style.pointerEvents = "none"; // Default none, elements will override
		svg.style.zIndex = "5";
		chartContainerRef.current.appendChild(svg);
		overlayRef.current = svg;

		const handleResize = () => {
			if (container) {
				const w = container.clientWidth;
				const h = container.clientHeight;
				if (w > 0 && h > 0) {
					chart.resize(w, h);
					syncOverlayRef.current();
				}
			}
		};

		// Use ResizeObserver for container resizing
		const resizeObserver = new ResizeObserver(() => {
			handleResize();
		});
		resizeObserver.observe(chartContainerRef.current);

		window.addEventListener("resize", handleResize);

		// Sync Events
		const syncOverlayWrapper = () => syncOverlayRef.current();
		chart.timeScale().subscribeVisibleTimeRangeChange(syncOverlayWrapper);
		chart.subscribeCrosshairMove(syncOverlayWrapper); // Added crosshair move subscription

		return () => {
			window.removeEventListener("resize", handleResize);
			resizeObserver.disconnect();
			chart.remove();
			if (overlayRef.current) overlayRef.current.remove();
		};
	}, [isOpen]);

	// Update Data
	useEffect(() => {
		if (seriesRef.current && klines.length > 0) {
			const data: CandlestickData[] = klines.map((k) => ({
				time: Math.floor(k.time / 1000) as Time,
				open: k.open,
				high: k.high,
				low: k.low,
				close: k.close,
			}));
			seriesRef.current.setData(data);
			if (chartRef.current) chartRef.current.timeScale().fitContent();
		}
	}, [klines]);

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
									onClick={() => setInterval(tf.value)}
									className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${
										interval === tf.value
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
							variant="ghost"
							size="sm"
							onClick={loadData}
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
									"flex-1 relative bg-zinc-950",
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

								<div
									ref={chartContainerRef}
									className="w-full h-full relative"
								/>

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
