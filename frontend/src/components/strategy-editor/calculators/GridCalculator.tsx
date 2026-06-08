// src/components/strategy-editor/calculators/GridCalculator.tsx

import { AlertTriangle } from "lucide-react";
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
	CartesianGrid,
	ComposedChart,
	ResponsiveContainer,
	Scatter,
	XAxis,
	YAxis,
	ZAxis,
} from "recharts";
import { apiClient } from "@/lib/api";
import { fetchBinanceKlines } from "@/lib/binanceApi";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";

interface GridCalculatorProps {
	levels: number;
	rangeType: "percentage" | "atr" | "fixed_prices";
	upperBoundValue: number | { value?: number } | null | undefined;
	lowerBoundValue: number | { value?: number } | null | undefined;
	isOpen: boolean;
}

export const GridCalculator: React.FC<GridCalculatorProps> = ({
	levels,
	rangeType,
	upperBoundValue,
	lowerBoundValue,
	isOpen,
}) => {
	const { t } = useTranslation("strategy-editor");
	const [baseOrderSize, setBaseOrderSize] = useState<number>(10);
	const [totalDeposit, setTotalDeposit] = useState<number>(100);
	const [feePercent, setFeePercent] = useState<number>(0.1);
	const [simulatedAtrUsd, setSimulatedAtrUsd] = useState<number>(0);
	const [currentPriceSim, setCurrentPriceSim] = useState<number>(100.0);

	const symbol = useStrategyEditorStore((state) => state.symbol);

	useEffect(() => {
		if (symbol) {
			const fetchData = async () => {
				try {
					const klines = await fetchBinanceKlines(
						symbol,
						"1m",
						undefined,
						undefined,
						1,
					);
					if (klines && klines.length > 0) {
						setCurrentPriceSim(parseFloat(klines[0][4] as string));
						if (rangeType === "atr") {
							const metrics = await apiClient<{ atr: number }>(
								`/metrics/${symbol}`,
							);
							if (metrics && typeof metrics.atr === "number") {
								setSimulatedAtrUsd(metrics.atr);
							}
						}
					}
				} catch {
					void 0;
				}
			};
			fetchData();
		}
	}, [symbol, rangeType]);

	const calculations = useMemo(() => {
		let topPrice: number;
		let bottomPrice: number;
		const startPrice = 100.0;

		const getVal = (
			val: number | { value?: number } | null | undefined,
		): number => {
			if (val === null || val === undefined) return 0;
			if (typeof val === "number") return val;
			if (typeof val === "object" && "value" in val) {
				return typeof val.value === "number" ? val.value : 0;
			}
			return 0;
		};

		const upperVal = getVal(upperBoundValue);
		const lowerVal = getVal(lowerBoundValue);

		if (rangeType === "percentage") {
			topPrice = startPrice * (1 + (upperVal || 5) / 100);
			bottomPrice = startPrice * (1 - (lowerVal || 5) / 100);
		} else if (rangeType === "atr") {
			const atrPct = (simulatedAtrUsd / currentPriceSim) * 100 || 1.5;
			topPrice = startPrice * (1 + (atrPct * (upperVal || 2)) / 100);
			bottomPrice = startPrice * (1 - (atrPct * (lowerVal || 2)) / 100);
		} else {
			topPrice = upperVal > 0 ? upperVal : startPrice * 1.05;
			bottomPrice = lowerVal > 0 ? lowerVal : startPrice * 0.95;
		}

		if (topPrice < bottomPrice) {
			[topPrice, bottomPrice] = [bottomPrice, topPrice];
		}

		const priceRange = topPrice - bottomPrice;
		const safeLevels = Math.max(1, levels);
		const stepAmountUsd = safeLevels > 1 ? priceRange / (safeLevels - 1) : 0;
		const orderSizeUsd = baseOrderSize;
		const totalVolume = orderSizeUsd * safeLevels;
		const calculatedLeverage =
			totalDeposit > 0 ? totalVolume / totalDeposit : 1;
		const mmr = 0.005;

		const gridOrders = [];
		const chartData = [];

		let cumBuyQty = 0;
		let cumBuyVol = 0;
		let maxLiqDropPct = 0;

		for (let i = 0; i < safeLevels; i++) {
			const orderPrice =
				safeLevels <= 1 ? topPrice : topPrice - stepAmountUsd * i;
			const orderType =
				orderPrice > startPrice
					? "Sell"
					: orderPrice < startPrice
						? "Buy"
						: "Current";
			const tokenQty = orderSizeUsd / orderPrice;

			let liqDistPct = "---";
			if (orderType === "Buy") {
				cumBuyQty += tokenQty;
				cumBuyVol += orderSizeUsd;
				const avgEntry = cumBuyVol / cumBuyQty;
				const liqPrice = avgEntry * (1 - 1 / calculatedLeverage + mmr);
				const dist = ((orderPrice - liqPrice) / orderPrice) * 100;
				liqDistPct = dist.toFixed(2);
				maxLiqDropPct = Math.abs(((liqPrice - startPrice) / startPrice) * 100);
			} else if (orderType === "Sell") {
				const liqPrice = orderPrice * (1 + 1 / calculatedLeverage - mmr);
				const dist = ((liqPrice - orderPrice) / orderPrice) * 100;
				liqDistPct = dist.toFixed(2);
			}

			gridOrders.push({
				index: i + 1,
				price: orderPrice.toFixed(2),
				type: orderType,
				sizeUsd: orderSizeUsd.toFixed(2),
				liqDistPct,
			});

			chartData.push({
				name: `L${i + 1}`,
				price: parseFloat(orderPrice.toFixed(2)),
				orderSizeUsd: parseFloat(orderSizeUsd.toFixed(2)),
				type: orderType === "Current" ? "Buy" : orderType,
			});
		}

		return {
			netProfitPerStepPct: (stepAmountUsd / startPrice) * 100 - 2 * feePercent,
			gridOrders,
			chartData: chartData.reverse(),
			buyOrdersCount: gridOrders.filter((o) => o.type === "Buy").length,
			sellOrdersCount: gridOrders.filter((o) => o.type === "Sell").length,
			orderSizeUsd,
			totalVolume,
			calculatedLeverage,
			maxLiqDropPct,
		};
	}, [
		levels,
		rangeType,
		upperBoundValue,
		lowerBoundValue,
		currentPriceSim,
		feePercent,
		simulatedAtrUsd,
		baseOrderSize,
		totalDeposit,
	]);

	if (!isOpen) return null;

	return (
		<div className="w-full mt-2 border rounded-md bg-background overflow-hidden relative shadow-md">
			<div className="p-4 border-t bg-card/20 space-y-4">
				<div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
					<div className="space-y-1">
						<label className="text-[10px] text-muted-foreground font-bold uppercase">
							{t("calculator.baseOrder", "Base")}
						</label>
						<input
							type="number"
							value={baseOrderSize}
							onChange={(e) =>
								setBaseOrderSize(Math.max(1, parseFloat(e.target.value) || 0))
							}
							className="h-8 w-full rounded border px-2 text-xs bg-background outline-none focus:ring-1 focus:ring-primary"
						/>
					</div>
					<div className="space-y-1">
						<label className="text-[10px] text-muted-foreground font-bold uppercase">
							{t("calculator.totalDeposit", "Deposit")}
						</label>
						<input
							type="number"
							value={totalDeposit}
							onChange={(e) =>
								setTotalDeposit(Math.max(1, parseFloat(e.target.value) || 0))
							}
							className="h-8 w-full rounded border px-2 text-xs bg-background outline-none focus:ring-1 focus:ring-primary"
						/>
					</div>
					<div className="space-y-1">
						<label className="text-[10px] text-muted-foreground font-bold uppercase">
							{t("gridCalculator.exchangeFee")}
						</label>
						<input
							type="number"
							step="0.01"
							value={feePercent}
							onChange={(e) =>
								setFeePercent(Math.max(0, parseFloat(e.target.value) || 0))
							}
							className="h-8 w-full rounded border px-2 text-xs bg-background outline-none focus:ring-1 focus:ring-primary"
						/>
					</div>
					<div className="flex flex-col p-2 bg-primary/5 rounded border border-primary/20">
						<span className="text-[9px] text-muted-foreground uppercase font-bold text-primary/80">
							Vol / Lev
						</span>
						<span className="text-sm font-black text-primary">
							$
							{calculations.totalVolume.toLocaleString(undefined, {
								maximumFractionDigits: 0,
							})}{" "}
							/ {calculations.calculatedLeverage.toFixed(2)}x
						</span>
					</div>
					<div className="flex flex-col p-2 bg-emerald-500/5 rounded border border-emerald-500/20">
						<span className="text-[9px] text-muted-foreground uppercase font-bold">
							{t("gridCalculator.netProfit")}
						</span>
						<span
							className={`text-md font-black ${calculations.netProfitPerStepPct <= 0 ? "text-red-500" : "text-emerald-500"}`}
						>
							{calculations.netProfitPerStepPct.toFixed(2)}%
						</span>
					</div>
					<div className="flex flex-col p-2 bg-red-500/5 rounded border border-red-500/20">
						<span className="text-[9px] text-muted-foreground uppercase font-bold text-red-500/80">
							Total Liq. Drop
						</span>
						<span className="text-md font-black text-red-500 leading-none mt-0.5">
							{calculations.maxLiqDropPct.toFixed(1)}%
						</span>
					</div>
				</div>

				{calculations.netProfitPerStepPct <= 0 && levels > 1 && (
					<div className="p-2.5 bg-red-500/10 border border-red-500/20 rounded-md flex items-center gap-2 text-red-500 text-[11px] font-medium">
						<AlertTriangle className="w-4 h-4 flex-shrink-0" />
						{t(
							"gridCalculator.profitWarning",
							"Warning: Exchange fee is higher than grid step profit!",
						)}
					</div>
				)}

				<div className="h-64 w-full pointer-events-none opacity-80">
					<ResponsiveContainer width="100%" height="100%">
						<ComposedChart
							data={calculations.chartData}
							layout="vertical"
							margin={{ top: 5, right: 30, left: 10, bottom: 5 }}
						>
							<CartesianGrid
								strokeDasharray="3 3"
								horizontal={true}
								vertical={false}
								className="opacity-10"
							/>
							<XAxis
								type="number"
								hide
								domain={[0, calculations.orderSizeUsd * 2]}
							/>
							<YAxis
								dataKey="price"
								type="category"
								tick={{ fontSize: 10 }}
								tickFormatter={(val) => `${val}%`}
								width={60}
							/>
							<ZAxis dataKey="type" />
							<Scatter
								dataKey="orderSizeUsd"
								shape={(props: unknown) => {
									const p = props as Record<string, unknown> & {
										payload?: { type: string };
									};
									const cx = Number(p.cx ?? 0);
									const cy = Number(p.cy ?? 0);
									const payload = p.payload;
									if (!payload) return null;
									const isSell = payload.type === "Sell";
									const isCurrent = payload.type === "Current";
									const color = isCurrent
										? "#a8a29e"
										: isSell
											? "#ef4444"
											: "#10b981";
									return (
										<g>
											<line
												x1={0}
												y1={cy}
												x2={cx + 500}
												y2={cy}
												stroke={color}
												strokeWidth={isCurrent ? 2 : 1}
												strokeDasharray={isCurrent ? "0" : "4 4"}
												opacity={0.4}
											/>
											{!isCurrent && (
												<circle cx={cx + 10} cy={cy} r={3} fill={color} />
											)}
										</g>
									);
								}}
							/>
						</ComposedChart>
					</ResponsiveContainer>
				</div>

				<div className="overflow-x-auto rounded border border-border/60">
					<table className="w-full text-left text-[11px]">
						<thead className="bg-muted/40 text-[9px] uppercase text-muted-foreground border-b border-border/60">
							<tr>
								<th className="p-2.5 font-bold">Lvl</th>
								<th className="p-2.5 font-bold">Type</th>
								<th className="p-2.5 font-bold">Price</th>
								<th className="p-2.5 font-bold">Size ($)</th>
								<th className="p-2.5 font-bold border-l border-red-500/10 text-red-500/80 uppercase">
									Liq Dist %
								</th>
							</tr>
						</thead>
						<tbody>
							{calculations.gridOrders.map((o) => {
								const isLiquidated =
									o.liqDistPct !== "---" && parseFloat(o.liqDistPct) <= 0;
								return (
									<tr
										key={o.index}
										className={`border-b last:border-0 hover:bg-white/5 transition-colors ${isLiquidated ? "bg-red-500/10" : ""}`}
									>
										<td className="p-2.5 text-muted-foreground">{o.index}</td>
										<td className="p-2.5">
											<span
												className={`px-1.5 rounded-[2px] text-[10px] ${o.type === "Sell" ? "bg-red-500/10 text-red-500" : o.type === "Buy" ? "bg-emerald-500/10 text-emerald-500" : "bg-muted text-muted-foreground"}`}
											>
												{o.type}
											</span>
										</td>
										<td className="p-2.5 font-semibold">{o.price}%</td>
										<td className="p-2.5 font-medium">${o.sizeUsd}</td>
										<td
											className={`p-2.5 font-bold border-l border-red-500/10 ${o.liqDistPct !== "---" && parseFloat(o.liqDistPct) < 1 ? "text-red-500 animate-pulse" : "text-red-500/70"}`}
										>
											{o.liqDistPct !== "---"
												? isLiquidated
													? "❌ LIQUIDATED"
													: `${o.liqDistPct}%`
												: "---"}
										</td>
									</tr>
								);
							})}
						</tbody>
					</table>
				</div>
			</div>
		</div>
	);
};
