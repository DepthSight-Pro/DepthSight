// frontend/src/components/simulation/AssetDeepDiveView.tsx
// Deep Dive view with candlestick chart, Oracle zones, and trade point markers

import {
	type CandlestickData,
	CandlestickSeries,
	ColorType,
	CrosshairMode,
	createChart,
	type IChartApi,
	type ISeriesApi,
	type Time,
} from "lightweight-charts";
import { Activity, ArrowLeft, Loader2 } from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSimulationStore } from "./simulationStore";

const getApiBase = () => {
	return import.meta.env.VITE_PUBLIC_API_URL || "";
};

const API_BASE = getApiBase();

interface OracleZone {
	startTime: number;
	endTime: number;
	regime: "amnesia" | "paranoia";
}

interface TradePoint {
	id: string;
	entryTime: number;
	exitTime: number;
	entryPrice: number;
	exitPrice: number;
	pnlPct: number;
	variant: string;
}

interface AssetDetailData {
	klines: {
		time: number;
		open: number;
		high: number;
		low: number;
		close: number;
	}[];
	oracleZones: OracleZone[];
	trades: TradePoint[];
}

export const AssetDeepDiveView: React.FC = () => {
	const { t } = useTranslation("simulation");
	const {
		activeAsset,
		setActiveAsset,
		inspectorResult,
		strategyJson,
		config,
		selectedTradeForPreview,
		setSelectedTradeForPreview,
	} = useSimulationStore();

	const chartContainerRef = useRef<HTMLDivElement>(null);
	const overlayRef = useRef<SVGSVGElement | null>(null);
	const chartRef = useRef<IChartApi | null>(null);
	const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

	const [loading, setLoading] = useState(false);
	const [data, setData] = useState<AssetDetailData | null>(null);
	const [selectedTrade, setSelectedTrade] = useState<TradePoint | null>(null);

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

	// Load asset data from API or fallback to inspector data
	useEffect(() => {
		if (!activeAsset) return;

		// Fallback: use trades from inspectorResult if available
		const getTradesFromInspector = (): TradePoint[] => {
			if (!inspectorResult?.matrix?.[activeAsset]) return [];
			const trades: TradePoint[] = [];
			Object.entries(inspectorResult.matrix[activeAsset]).forEach(
				([variant, cell]) => {
					if (cell?.trades && Array.isArray(cell.trades)) {
						cell.trades.forEach((trade, idx) => {
							trades.push({
								id: `${activeAsset}_${variant}_${idx}`,
								entryTime: trade.entryTime || 0,
								exitTime: trade.exitTime || 0,
								entryPrice: trade.entryPrice || 0,
								exitPrice: trade.exitPrice || 0,
								pnlPct: trade.pnlPct || 0,
								variant,
							});
						});
					}
				},
			);
			return trades;
		};

		// Always try to load from API to get klines and oracle zones
		// Even without strategyJson, we can get klines for the chart

		const loadData = async () => {
			setLoading(true);
			try {
				const response = await fetch(
					`${API_BASE}/api/simulation/asset-detail/${activeAsset}`,
					{
						method: "POST",
						headers: { "Content-Type": "application/json" },
						body: JSON.stringify({
							strategy_json: strategyJson || {}, // Send an empty object if there is no strategy
							variants: strategyJson ? ["raw", "oracle_be"] : [], // Without a strategy, we don't receive trades from the backtest
							config,
						}),
					},
				);

				if (response.ok) {
					const result = await response.json();
					// Merge API trades with inspector trades for complete view
					const inspectorTrades = getTradesFromInspector();
					const apiTrades = result.trades || [];
					// Prefer inspector trades if available (they have more context)
					const mergedTrades =
						inspectorTrades.length > 0 ? inspectorTrades : apiTrades;
					setData({
						klines: result.klines || [],
						oracleZones: result.oracleZones || [],
						trades: mergedTrades,
					});
				} else {
					// Fallback to inspector trades
					const inspectorTrades = getTradesFromInspector();
					setData({
						klines: [],
						oracleZones: [],
						trades: inspectorTrades,
					});
				}
			} catch (err) {
				console.error("Failed to load asset detail:", err);
				// Fallback to inspector trades
				const inspectorTrades = getTradesFromInspector();
				setData({
					klines: [],
					oracleZones: [],
					trades: inspectorTrades,
				});
			} finally {
				setLoading(false);
			}
		};

		loadData();
	}, [activeAsset, strategyJson, config, inspectorResult]);

	// Sync overlay - draw Oracle zones and trade points
	const syncOverlay = useCallback(() => {
		if (!overlayRef.current || !chartRef.current || !seriesRef.current || !data)
			return;

		const overlay = overlayRef.current;
		overlay.innerHTML = "";

		const chart = chartRef.current;
		const series = seriesRef.current;
		const chartHeight = chartContainerRef.current?.clientHeight || 500;

		// Draw Oracle zones
		data.oracleZones.forEach((zone) => {
			const startX = chart
				.timeScale()
				.timeToCoordinate((zone.startTime / 1000) as Time);
			const endX = chart
				.timeScale()
				.timeToCoordinate((zone.endTime / 1000) as Time);

			if (startX !== null && endX !== null) {
				const rect = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"rect",
				);
				rect.setAttribute("x", String(Math.min(startX, endX)));
				rect.setAttribute("y", "0");
				rect.setAttribute("width", String(Math.abs(endX - startX)));
				rect.setAttribute("height", String(chartHeight - 30)); // Leave space for time axis

				if (zone.regime === "amnesia") {
					// Amnesia = Sideways = Yellow/Orange
					rect.setAttribute("fill", "rgba(251, 191, 36, 0.08)");
				} else {
					// Paranoia = Trend = Purple
					rect.setAttribute("fill", "rgba(139, 92, 246, 0.08)");
				}
				overlay.appendChild(rect);

				// Zone label
				const text = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"text",
				);
				text.setAttribute("x", String((startX + endX) / 2));
				text.setAttribute("y", "20");
				text.setAttribute("text-anchor", "middle");
				text.setAttribute(
					"fill",
					zone.regime === "amnesia"
						? "rgba(251, 191, 36, 0.5)"
						: "rgba(139, 92, 246, 0.5)",
				);
				text.setAttribute("font-size", "10px");
				text.setAttribute("font-weight", "bold");
				text.textContent = zone.regime === "amnesia" ? "AMNESIA" : "PARANOIA";
				overlay.appendChild(text);
			}
		});

		// Draw trade points
		data.trades.forEach((trade) => {
			const x = chart
				.timeScale()
				.timeToCoordinate((trade.entryTime / 1000) as Time);
			const y = series.priceToCoordinate(trade.entryPrice);

			if (x !== null && y !== null) {
				// Circle size based on PnL magnitude (pnlPct is decimal, so multiply by 100)
				const radius = Math.min(
					Math.max(Math.abs(trade.pnlPct * 100) * 0.5, 4),
					12,
				);
				const isProfit = trade.pnlPct > 0;

				const circle = document.createElementNS(
					"http://www.w3.org/2000/svg",
					"circle",
				);
				circle.setAttribute("cx", String(x));
				circle.setAttribute("cy", String(y));
				circle.setAttribute("r", String(radius));
				circle.setAttribute("fill", isProfit ? "#22c55e" : "#ef4444");
				circle.setAttribute(
					"stroke",
					selectedTrade?.id === trade.id ? "#fff" : "none",
				);
				circle.setAttribute("stroke-width", "2");
				circle.setAttribute("opacity", "0.8");
				circle.style.cursor = "pointer";
				circle.style.pointerEvents = "auto";

				// Click handler for trade selection
				circle.addEventListener("click", () => setSelectedTrade(trade));

				overlay.appendChild(circle);
			}
		});

		// Draw ruler if active
		if (isRulerActive && rulerStartRef.current && rulerCurrentRef.current) {
			const start = rulerStartRef.current;
			const current = rulerCurrentRef.current;

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

			// Price diff label
			const priceDiff = current.price - start.price;
			const percentDiff = (priceDiff / start.price) * 100;

			const rect = document.createElementNS(
				"http://www.w3.org/2000/svg",
				"rect",
			);
			rect.setAttribute("x", String(current.x + 10));
			rect.setAttribute("y", String(current.y - 15));
			rect.setAttribute("width", "100");
			rect.setAttribute("height", "24");
			rect.setAttribute("fill", "rgba(41, 98, 255, 0.9)");
			rect.setAttribute("rx", "4");
			overlay.appendChild(rect);

			const text = document.createElementNS(
				"http://www.w3.org/2000/svg",
				"text",
			);
			text.setAttribute("x", String(current.x + 15));
			text.setAttribute("y", String(current.y + 3));
			text.setAttribute("fill", "white");
			text.setAttribute("font-size", "11px");
			text.textContent = `${percentDiff > 0 ? "+" : ""}${percentDiff.toFixed(2)}%`;
			overlay.appendChild(text);
		}
	}, [data, isRulerActive, selectedTrade]);

	// Initialize chart
	useEffect(() => {
		if (!chartContainerRef.current || !data?.klines.length) return;
		const chartContainer = chartContainerRef.current;

		const chart = createChart(chartContainer, {
			width: chartContainer.clientWidth,
			height: 500,
			layout: {
				textColor: "#9ca3af",
				background: { type: ColorType.Solid, color: "transparent" },
			},
			grid: {
				vertLines: { color: "rgba(255,255,255,0.05)" },
				horzLines: { color: "rgba(255,255,255,0.05)" },
			},
			crosshair: { mode: CrosshairMode.Normal },
			timeScale: { borderColor: "#27272a", timeVisible: true },
			rightPriceScale: { borderColor: "#27272a" },
		});

		chartRef.current = chart;

		const candlestickSeries = chart.addSeries(CandlestickSeries, {
			upColor: "#22c55e",
			downColor: "#ef4444",
			borderVisible: false,
			wickUpColor: "#22c55e",
			wickDownColor: "#ef4444",
		});

		seriesRef.current = candlestickSeries;

		// Create SVG overlay
		const svgOverlay = document.createElementNS(
			"http://www.w3.org/2000/svg",
			"svg",
		);
		svgOverlay.style.position = "absolute";
		svgOverlay.style.top = "0";
		svgOverlay.style.left = "0";
		svgOverlay.style.width = "100%";
		svgOverlay.style.height = "100%";
		svgOverlay.style.pointerEvents = "none";
		svgOverlay.style.zIndex = "10";
		chartContainer.style.position = "relative";
		chartContainer.appendChild(svgOverlay);
		overlayRef.current = svgOverlay;

		// Set chart data
		const chartData: CandlestickData[] = data.klines.map((k) => ({
			time: (k.time / 1000) as Time,
			open: k.open,
			high: k.high,
			low: k.low,
			close: k.close,
		}));

		candlestickSeries.setData(chartData);
		chart.timeScale().fitContent();

		// Subscribe to changes for overlay sync
		chart.timeScale().subscribeVisibleTimeRangeChange(syncOverlay);
		// Also sync on crosshair move (catches price scale changes)
		chart.subscribeCrosshairMove(syncOverlay);
		setTimeout(syncOverlay, 100);

		const handleResize = () => {
			chart.resize(chartContainer.clientWidth, 500);
			syncOverlay();
		};
		window.addEventListener("resize", handleResize);

		return () => {
			window.removeEventListener("resize", handleResize);
			// Clean up SVG overlay
			if (overlayRef.current) {
				chartContainer.removeChild(overlayRef.current);
				overlayRef.current = null;
			}
			chart.remove();
		};
	}, [data, syncOverlay]);

	// Mouse handlers for ruler (Shift+Click OR Middle Mouse Button)
	const handleMouseDown = useCallback(
		(e: React.MouseEvent) => {
			// Activate ruler on: Shift+Click OR Middle mouse button (button === 1)
			if (
				(e.shiftKey || e.button === 1) &&
				chartContainerRef.current &&
				seriesRef.current
			) {
				e.preventDefault(); // Prevent default scrolling on middle click
				setIsRulerActive(true);
				const rect = chartContainerRef.current.getBoundingClientRect();
				const x = e.clientX - rect.left;
				const y = e.clientY - rect.top;
				const price = seriesRef.current.coordinateToPrice(y);

				if (price !== null) {
					rulerStartRef.current = { x, y, price };
					rulerCurrentRef.current = { x, y, price };
					chartRef.current?.applyOptions({
						handleScroll: false,
						handleScale: false,
					});
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
			chartRef.current?.applyOptions({ handleScroll: true, handleScale: true });
			syncOverlay();
		}
	}, [isRulerActive, syncOverlay]);

	// Navigate chart to specific trade
	const navigateToTrade = useCallback(
		(trade: TradePoint) => {
			if (!chartRef.current || !trade.entryTime) return;

			const chart = chartRef.current;
			const tradeTime = trade.entryTime / 1000; // Convert ms to seconds

			// Calculate visible range: 30 minutes before and after the trade
			const rangeSeconds = 30 * 60; // 30 minutes
			const from = tradeTime - rangeSeconds;
			const to = tradeTime + rangeSeconds;

			try {
				chart.timeScale().setVisibleRange({
					from: from as Time,
					to: to as Time,
				});

				// Also update the overlay after navigation
				setTimeout(syncOverlay, 100);
			} catch (e) {
				console.warn("Failed to navigate to trade:", e);
			}
		},
		[syncOverlay],
	);

	// Handle trade click - select and navigate
	const handleTradeClick = useCallback(
		(trade: TradePoint) => {
			setSelectedTrade(trade);
			navigateToTrade(trade);
		},
		[navigateToTrade],
	);

	// Auto-navigate to trade selected from Timeline (Portfolio tab)
	useEffect(() => {
		if (selectedTradeForPreview && data?.trades) {
			// Find matching trade in current data
			const matchingTrade = data.trades.find(
				(t) =>
					t.entryTime === selectedTradeForPreview.entryTime &&
					Math.abs(t.pnlPct - selectedTradeForPreview.pnlPct) < 0.0001,
			);

			if (matchingTrade) {
				setSelectedTrade(matchingTrade);
				// Wait for chart to be ready then navigate
				setTimeout(() => navigateToTrade(matchingTrade), 200);
			} else if (selectedTradeForPreview.entryTime) {
				// Create a temporary trade point for navigation
				const tempTrade: TradePoint = {
					id:
						selectedTradeForPreview.id ||
						`temp_${selectedTradeForPreview.entryTime}`,
					entryTime: selectedTradeForPreview.entryTime,
					exitTime: selectedTradeForPreview.exitTime,
					entryPrice: selectedTradeForPreview.entryPrice || 0,
					exitPrice: selectedTradeForPreview.exitPrice || 0,
					pnlPct: selectedTradeForPreview.pnlPct,
					variant: selectedTradeForPreview.variant || "unknown",
				};
				setSelectedTrade(tempTrade);
				setTimeout(() => navigateToTrade(tempTrade), 200);
			}

			// Clear the preview selection after navigation
			setSelectedTradeForPreview(null);
		}
	}, [
		selectedTradeForPreview,
		data?.trades,
		navigateToTrade,
		setSelectedTradeForPreview,
	]);

	// Asset data from inspector
	const assetData = inspectorResult?.matrix?.[activeAsset || ""];

	if (!activeAsset) {
		return (
			<div className="flex flex-col items-center justify-center h-full min-h-[400px] text-muted-foreground space-y-4">
				<Activity className="w-12 h-12 mb-4 opacity-50" />
				<h3 className="text-lg font-bold">
					{t("selectAsset", "Select an Asset")}
				</h3>
				<p className="text-sm">
					{t(
						"clickMatrixAsset",
						"Click on an asset in the Inspector Matrix to analyze it",
					)}
				</p>
			</div>
		);
	}

	return (
		<div className="space-y-6 animate-in slide-in-from-right-10 duration-500">
			{/* Header */}
			<div className="flex items-center justify-between">
				<div className="flex items-center gap-4">
					<button
						onClick={() => setActiveAsset(null)}
						className="p-2 rounded-lg border hover:bg-muted transition-colors"
					>
						<ArrowLeft size={20} />
					</button>
					<div>
						<div className="flex items-center gap-2">
							<h2 className="text-3xl font-bold font-mono">{activeAsset}</h2>
							<span className="px-2 py-0.5 rounded bg-primary/10 text-primary text-xs font-bold border border-primary/20 uppercase">
								Futures
							</span>
						</div>
						<p className="text-sm text-muted-foreground">
							{t(
								"technicalAnalysis",
								"Technical analysis & Oracle signal verification",
							)}
						</p>
					</div>
				</div>

				{/* Legend */}
				<div className="flex items-center gap-4 text-xs">
					<div className="flex items-center gap-1">
						<div className="w-3 h-3 rounded-full bg-amber-400/50" />
						<span className="text-muted-foreground">Amnesia (Sideways)</span>
					</div>
					<div className="flex items-center gap-1">
						<div className="w-3 h-3 rounded-full bg-purple-500/50" />
						<span className="text-muted-foreground">Paranoia (Trend)</span>
					</div>
					<div className="flex items-center gap-1">
						<div className="w-3 h-3 rounded-full bg-emerald-500" />
						<span className="text-muted-foreground">Profit</span>
					</div>
					<div className="flex items-center gap-1">
						<div className="w-3 h-3 rounded-full bg-rose-500" />
						<span className="text-muted-foreground">Loss</span>
					</div>
				</div>
			</div>

			<div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
				{/* Chart Area */}
				<div className="lg:col-span-3">
					<Card className="overflow-hidden">
						<CardHeader className="bg-muted/30 py-3 flex flex-row items-center justify-between">
							<div className="flex items-center gap-4">
								<CardTitle className="text-sm">
									{t("priceChart", "Price Chart")}
								</CardTitle>
								{data && (
									<span className="text-xs text-muted-foreground">
										{data.trades.length} trades | {data.oracleZones.length}{" "}
										Oracle zones
									</span>
								)}
							</div>
							<span className="text-[10px] text-muted-foreground">
								📏 Shift+Click / Wheel Click for ruler
							</span>
						</CardHeader>
						<CardContent className="p-0 h-[500px] relative">
							{loading ? (
								<div className="h-full flex items-center justify-center">
									<Loader2 className="w-8 h-8 animate-spin text-primary" />
								</div>
							) : (
								<div
									ref={chartContainerRef}
									className={`w-full h-full ${isRulerActive ? "cursor-crosshair" : ""}`}
									onMouseDown={handleMouseDown}
									onMouseMove={handleMouseMove}
									onMouseUp={handleMouseUp}
									onMouseLeave={handleMouseUp}
								/>
							)}
						</CardContent>
					</Card>
				</div>

				{/* Execution Log Sidebar */}
				<div className="lg:col-span-1">
					<Card className="h-[560px] flex flex-col">
						<CardHeader className="py-3">
							<CardTitle className="text-xs uppercase tracking-widest text-muted-foreground">
								{t("executionLog", "Execution Log")}
							</CardTitle>
						</CardHeader>
						<CardContent className="flex-1 overflow-y-auto p-2 space-y-2">
							{data?.trades.map((trade) => (
								<div
									key={trade.id}
									onClick={() => handleTradeClick(trade)}
									className={`p-3 rounded-lg border cursor-pointer transition-all ${
										selectedTrade?.id === trade.id
											? "bg-primary/10 border-primary"
											: "bg-muted/30 border-border hover:border-primary/50"
									}`}
								>
									<div className="flex items-center justify-between mb-1">
										<span className="text-[10px] font-mono text-muted-foreground">
											{new Date(trade.entryTime).toLocaleDateString()}
										</span>
										<span
											className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
												trade.pnlPct > 0
													? "bg-emerald-500/10 text-emerald-400"
													: "bg-rose-500/10 text-rose-400"
											}`}
										>
											{trade.pnlPct > 0 ? "+" : ""}
											{(trade.pnlPct * 100).toFixed(2)}%
										</span>
									</div>
									<div className="flex items-center justify-between">
										<span className="text-xs font-bold uppercase">
											{trade.variant}
										</span>
										<span className="text-[10px] font-mono text-muted-foreground">
											${trade.entryPrice.toFixed(2)}
										</span>
									</div>
								</div>
							))}

							{(!data?.trades || data.trades.length === 0) && !loading && (
								<div className="text-center text-muted-foreground text-xs py-8">
									{t("noTrades", "No trades found")}
								</div>
							)}
						</CardContent>
					</Card>
				</div>
			</div>

			{/* Variant Stats Cards */}
			{assetData && (
				<div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
					{Object.entries(assetData).map(([variant, cell]) => (
						<Card
							key={variant}
							className={`p-4 ${
								cell.pnl_pct > 0
									? "bg-emerald-500/5 border-emerald-500/20"
									: "bg-rose-500/5 border-rose-500/20"
							}`}
						>
							<h4 className="text-[10px] font-bold uppercase text-muted-foreground mb-1">
								{variant}
							</h4>
							<div
								className={`text-xl font-mono font-bold ${cell.pnl_pct > 0 ? "text-emerald-400" : "text-rose-400"}`}
							>
								{cell.pnl_pct > 0 ? "+" : ""}
								{cell.pnl_pct.toFixed(1)}%
							</div>
							<div className="text-[10px] text-muted-foreground mt-1">
								WR: {cell.win_rate.toFixed(0)}% | {cell.trades_count} trades
							</div>
						</Card>
					))}
				</div>
			)}
		</div>
	);
};

export default AssetDeepDiveView;
