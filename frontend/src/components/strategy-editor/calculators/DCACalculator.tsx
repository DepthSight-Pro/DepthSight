// src/components/strategy-editor/calculators/DCACalculator.tsx

import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
	Bar,
	CartesianGrid,
	ComposedChart,
	Legend,
	Line,
	Tooltip as RechartsTooltip,
	ResponsiveContainer,
	XAxis,
	YAxis,
} from "recharts";
import { apiClient } from "@/lib/apiClient";
import { fetchBinanceKlines } from "@/lib/binanceApi";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";

interface DCACalculatorProps {
	maxSafetyOrders: number;
	volumeMultiplier: number;
	stepMultiplier: number;
	stepValue: number | { value?: number } | null | undefined;
	stepType: "percentage" | "atr" | "custom_condition";
	isOpen: boolean; // Managed by parent now
}

interface DCAOrder {
	index: number;
	price: string;
	size: string;
	cumDrop: string;
	avgPrice: string;
	cumInv: string;
	reqBounce: string;
	liqDist: string;
	deadZone: boolean;
	stepLeverage: string;
}

export const DCACalculator: React.FC<DCACalculatorProps> = ({
	maxSafetyOrders,
	volumeMultiplier,
	stepMultiplier,
	stepValue,
	stepType,
	isOpen,
}) => {
	const { t } = useTranslation("strategy-editor");
	const [baseOrderSize, setBaseOrderSize] = useState<number>(10);
	const [tpPercent, setTpPercent] = useState<number>(2.0);
	const [totalDeposit, setTotalDeposit] = useState<number>(100);
	const [simulatedAtrPercent, setSimulatedAtrPercent] = useState<number>(1.5);

	const symbol = useStrategyEditorStore((state) => state.symbol);
	const direction =
		useStrategyEditorStore((state) => state.initialization.params.direction) ||
		"LONG";

	useEffect(() => {
		if (stepType === "atr" && symbol) {
			const fetchAtrData = async () => {
				try {
					const metrics = await apiClient<{ atr: number }>(
						`/metrics/${symbol}`,
					);
					if (metrics && typeof metrics.atr === "number") {
						const klines = await fetchBinanceKlines(
							symbol,
							"1m",
							undefined,
							undefined,
							1,
						);
						if (klines && klines.length > 0) {
							const currentPrice = parseFloat(klines[0][4] as string);
							const atrPercentage = (metrics.atr / currentPrice) * 100;
							setSimulatedAtrPercent(parseFloat(atrPercentage.toFixed(2)));
						}
					}
				} catch {
					// ignore error
				}
			};
			fetchAtrData();
		}
	}, [symbol, stepType]);

	const calculations = useMemo(() => {
		let tempTotalVol = 0;
		for (let i = 0; i <= maxSafetyOrders; i++) {
			tempTotalVol += baseOrderSize * volumeMultiplier ** i;
		}
		const calculatedLeverage =
			totalDeposit > 0 ? tempTotalVol / totalDeposit : 1;

		const orders: DCAOrder[] = [];
		const chartData = [];
		let cumDropPct = 0;
		let totalVol = 0;
		let totalQty = 0;
		const startPrice = 100.0;
		let currentPrice = startPrice;
		const mmr = 0.005;

		const baseStepValue =
			parseFloat(
				typeof stepValue === "object"
					? String(stepValue?.value)
					: String(stepValue),
			) || 1.0;
		const initialStepPct =
			stepType === "atr" ? baseStepValue * simulatedAtrPercent : baseStepValue;
		let currentStepPct = initialStepPct;

		for (let i = 0; i <= maxSafetyOrders; i++) {
			const orderSize = baseOrderSize * volumeMultiplier ** i;

			if (i > 0) {
				cumDropPct += currentStepPct;
				if (direction === "LONG") {
					currentPrice = startPrice * (1 - cumDropPct / 100);
				} else {
					currentPrice = startPrice * (1 + cumDropPct / 100);
				}
				currentStepPct *= stepMultiplier;
			}

			if (direction === "LONG" && currentPrice <= 0) {
				orders.push({
					index: i,
					deadZone: true,
					price: "0",
					size: "0",
					cumDrop: "100",
					avgPrice: "0",
					cumInv: "0",
					reqBounce: "0",
					liqDist: "-1",
					stepLeverage: "-",
				});
				break;
			}

			const qty = orderSize / currentPrice;
			totalVol += orderSize;
			totalQty += qty;
			const avgPrice = totalVol / totalQty;

			const tpLevel =
				avgPrice * (1 + (direction === "LONG" ? tpPercent : -tpPercent) / 100);
			const reqBounce =
				direction === "LONG"
					? (tpLevel / currentPrice - 1) * 100
					: (1 - tpLevel / currentPrice) * 100;

			let liqPriceVal: number;
			let liqDistancePct: number;
			const stepLeverageVal = totalDeposit > 0 ? totalVol / totalDeposit : 1;

			if (direction === "LONG") {
				liqPriceVal = avgPrice * (1 - 1 / calculatedLeverage + mmr);
				liqDistancePct = ((currentPrice - liqPriceVal) / currentPrice) * 100;
			} else {
				liqPriceVal = avgPrice * (1 + 1 / calculatedLeverage - mmr);
				liqDistancePct = ((liqPriceVal - currentPrice) / currentPrice) * 100;
			}

			orders.push({
				index: i,
				price: currentPrice.toFixed(2),
				size: orderSize.toFixed(2),
				cumDrop: cumDropPct.toFixed(2),
				avgPrice: avgPrice.toFixed(2),
				cumInv: totalVol.toFixed(2),
				reqBounce: reqBounce.toFixed(2),
				liqDist: liqDistancePct.toFixed(2),
				deadZone: false,
				stepLeverage: stepLeverageVal.toFixed(2),
			});

			chartData.push({
				name: i === 0 ? t("calculator.table.base") : `SO${i}`,
				cumDrop: parseFloat(cumDropPct.toFixed(2)),
				size: parseFloat(orderSize.toFixed(2)),
				cumInv: parseFloat(totalVol.toFixed(2)),
				reqBounce: parseFloat(reqBounce.toFixed(2)),
			});
		}

		const lastOrder = orders[orders.length - 1];
		let totalLiqDrop = 0;
		if (lastOrder && !lastOrder.deadZone) {
			const avgPriceNum = parseFloat(lastOrder.avgPrice);
			const liqPrice =
				direction === "LONG"
					? avgPriceNum * (1 - 1 / calculatedLeverage + mmr)
					: avgPriceNum * (1 + 1 / calculatedLeverage - mmr);
			totalLiqDrop = Math.abs(((liqPrice - startPrice) / startPrice) * 100);
		}

		return {
			orders,
			chartData,
			totalInv: totalVol,
			maxDrop: cumDropPct,
			totalLiqDrop,
			calculatedLeverage,
		};
	}, [
		maxSafetyOrders,
		volumeMultiplier,
		stepMultiplier,
		stepValue,
		stepType,
		baseOrderSize,
		tpPercent,
		totalDeposit,
		direction,
		simulatedAtrPercent,
		t,
	]);

	if (!isOpen) return null;

	return (
		<div className="w-full mt-2 border rounded-md bg-background overflow-hidden relative shadow-md">
			<div className="p-4 bg-card/20 space-y-6">
				<div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
					<div className="space-y-1">
						<label className="text-[10px] text-muted-foreground font-bold uppercase">
							{t("calculator.baseOrder")}
						</label>
						<input
							type="number"
							value={baseOrderSize}
							onChange={(e) =>
								setBaseOrderSize(Math.max(1, parseFloat(e.target.value) || 0))
							}
							className="h-8 w-full rounded bg-background border px-2 text-sm focus:ring-1 focus:ring-primary outline-none"
						/>
					</div>
					<div className="space-y-1">
						<label className="text-[10px] text-muted-foreground font-bold uppercase">
							{t("calculator.takeProfit")}
						</label>
						<input
							type="number"
							step="0.1"
							value={tpPercent}
							onChange={(e) =>
								setTpPercent(Math.max(0, parseFloat(e.target.value) || 0))
							}
							className="h-8 w-full rounded bg-background border px-2 text-sm focus:ring-1 focus:ring-primary outline-none"
						/>
					</div>
					<div className="space-y-1">
						<label className="text-[10px] text-muted-foreground font-bold uppercase">
							{t("calculator.totalDeposit", "Deposit ($)")}
						</label>
						<input
							type="number"
							value={totalDeposit}
							onChange={(e) =>
								setTotalDeposit(Math.max(1, parseFloat(e.target.value) || 0))
							}
							className="h-8 w-full rounded bg-background border px-2 text-sm focus:ring-1 focus:ring-primary outline-none"
						/>
					</div>
					<div className="flex flex-col p-2 bg-primary/5 rounded border border-primary/20">
						<span className="text-[9px] text-muted-foreground uppercase font-bold text-primary/80">
							Vol / Lev
						</span>
						<span className="text-sm font-black text-primary">
							$
							{calculations.totalInv.toLocaleString(undefined, {
								maximumFractionDigits: 0,
							})}{" "}
							/ {calculations.calculatedLeverage.toFixed(2)}x
						</span>
					</div>
					<div className="flex flex-col p-2 bg-orange-500/5 rounded border border-orange-500/20">
						<span className="text-[9px] text-muted-foreground uppercase font-bold">
							Max Drawdown
						</span>
						<span className="text-md font-black text-orange-500">
							{calculations.maxDrop.toFixed(1)}%
						</span>
					</div>
					<div className="flex flex-col p-2 bg-red-500/5 rounded border border-red-500/20">
						<span className="text-[9px] text-muted-foreground uppercase font-bold text-red-500/80">
							Total Liq. Drop
						</span>
						<span className="text-md font-black text-red-500">
							{calculations.totalLiqDrop.toFixed(1)}%
						</span>
					</div>
				</div>

				<div className="h-56 w-full opacity-80 mt-2">
					<ResponsiveContainer width="100%" height="100%">
						<ComposedChart
							data={calculations.chartData}
							margin={{ top: 5, right: 5, left: -20, bottom: 5 }}
						>
							<CartesianGrid
								strokeDasharray="3 3"
								vertical={false}
								stroke="currentColor"
								className="opacity-10"
							/>
							<XAxis dataKey="name" tick={{ fontSize: 10 }} />
							<YAxis
								yAxisId="left"
								tick={{ fontSize: 10 }}
								tickFormatter={(val) => `$${val}`}
							/>
							<YAxis
								yAxisId="right"
								orientation="right"
								tick={{ fontSize: 10 }}
								tickFormatter={(val) => `${val}%`}
							/>
							<RechartsTooltip
								contentStyle={{
									backgroundColor: "hsl(var(--card))",
									borderColor: "hsl(var(--border))",
									fontSize: "11px",
								}}
							/>
							<Legend iconSize={8} wrapperStyle={{ fontSize: "10px" }} />
							<Bar
								yAxisId="left"
								dataKey="size"
								name={t("calculator.chart.orderSize")}
								fill="#3b82f6"
								opacity={0.6}
								radius={[2, 2, 0, 0]}
							/>
							<Line
								yAxisId="left"
								type="monotone"
								dataKey="cumInv"
								name={t("calculator.chart.totalInv")}
								stroke="#8b5cf6"
								strokeWidth={2}
								dot={{ r: 2 }}
							/>
							<Line
								yAxisId="right"
								type="stepAfter"
								dataKey="reqBounce"
								name={t("calculator.chart.reqBounce")}
								stroke="#10b981"
								strokeWidth={2}
								strokeDasharray="4 4"
								dot={{ r: 2 }}
							/>
						</ComposedChart>
					</ResponsiveContainer>
				</div>

				<div className="overflow-x-auto rounded border border-border/60">
					<table className="w-full text-left text-[11px]">
						<thead className="bg-muted/40 text-[9px] uppercase text-muted-foreground border-b border-border/60">
							<tr>
								<th className="p-2.5 font-bold">{t("calculator.table.so")}</th>
								<th className="p-2.5 font-bold">
									{t("calculator.table.drop")}
								</th>
								<th className="p-2.5 font-bold">
									{t("calculator.table.size")}
								</th>
								<th className="p-2.5 font-bold">
									{t("calculator.table.cumInv")}
								</th>
								<th className="p-2.5 font-bold">
									{t("calculator.table.leverage", "Lev")}
								</th>
								<th className="p-2.5 font-bold text-emerald-500">
									{t("calculator.table.bounce")}
								</th>
								<th className="p-2.5 font-bold border-l border-red-500/10 text-red-500/80 uppercase">
									{t("calculator.table.liqPrice")}
								</th>
							</tr>
						</thead>
						<tbody>
							{calculations.orders.map((o) => {
								const isLiquidated =
									!o.deadZone && parseFloat(o.liqDist || "0") <= 0;
								return (
									<tr
										key={o.index}
										className={`border-b last:border-0 hover:bg-white/5 transition-colors ${isLiquidated ? "bg-red-500/10" : ""}`}
									>
										{o.deadZone ? (
											<td
												colSpan={7}
												className="p-2.5 text-center text-red-500 font-bold bg-red-500/10 uppercase tracking-widest text-[10px]"
											>
												[ ! Price Hits Zero ! ]
											</td>
										) : (
											<>
												<td className="p-2.5 font-bold">
													{o.index === 0 ? t("calculator.table.base") : o.index}
												</td>
												<td className="p-2.5 text-muted-foreground">
													-{o.cumDrop}%
												</td>
												<td className="p-2.5 font-medium">${o.size}</td>
												<td className="p-2.5 font-medium">
													${parseFloat(o.cumInv).toLocaleString()}
												</td>
												<td className="p-2.5 font-medium text-primary/80">
													{o.stepLeverage}x
												</td>
												<td className="p-2.5 text-emerald-500 font-bold">
													{o.reqBounce}%
												</td>
												<td
													className={`p-2.5 font-bold border-l border-red-500/10 ${parseFloat(o.liqDist) < 2 ? "text-red-500 animate-pulse" : "text-red-500/70"}`}
												>
													{isLiquidated ? "❌ LIQUIDATED" : `${o.liqDist}%`}
												</td>
											</>
										)}
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
