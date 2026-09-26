// src/components/analytics/PnlBySymbolChart.tsx

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
	Bar,
	BarChart,
	CartesianGrid,
	Cell,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import type { TradeData } from "@/types/api";

interface PnlBySymbolChartProps {
	tradeData: TradeData[];
}

interface CustomSymbolTooltipProps {
	active?: boolean;
	payload?: Array<{ payload?: { symbol: string; netPnl: number } }>;
}

const CustomSymbolTooltip = ({ active, payload }: CustomSymbolTooltipProps) => {
	if (!active || !payload?.length || !payload[0]?.payload) return null;
	const data = payload[0].payload;
	const netPnl = Number(data.netPnl || 0);
	const isProfit = netPnl >= 0;

	return (
		<div className="rounded-xl border border-white/15 bg-[#0b0f17]/95 px-3 py-2 shadow-2xl backdrop-blur-xl font-mono">
			<div className="text-[11px] font-semibold text-white/70 mb-1">{data.symbol}</div>
			<div className="flex items-center gap-2 text-xs">
				<span className="text-white/50">Net PnL:</span>
				<span className={`font-bold ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
					{isProfit ? "+" : ""}${netPnl.toFixed(2)}
				</span>
			</div>
		</div>
	);
};

export const PnlBySymbolChart = ({ tradeData }: PnlBySymbolChartProps) => {
	const { t } = useTranslation("analytics");
	const chartData = useMemo(() => {
		const pnlBySymbol: { [key: string]: number } = {};
		tradeData.forEach((trade) => {
			// Use exchange realized PnL from the trade
			const realizedPnl = trade.pnl || 0;
			pnlBySymbol[trade.symbol] =
				(pnlBySymbol[trade.symbol] || 0) + realizedPnl;
		});
		return Object.entries(pnlBySymbol)
			.map(([symbol, netPnl]) => ({ symbol, netPnl }))
			.sort((a, b) => b.netPnl - a.netPnl);
	}, [tradeData]);

	if (chartData.length === 0) {
		return (
			<div className="text-center text-muted-foreground p-8">
				{t("noDataToDisplay")}
			</div>
		);
	}

	return (
		<ResponsiveContainer width="100%" height={400}>
			<BarChart data={chartData} layout="vertical">
				<CartesianGrid
					strokeDasharray="3 3"
					stroke="hsl(var(--border) / 0.5)"
				/>
				<XAxis
					type="number"
					stroke="hsl(var(--muted-foreground))"
					fontSize={12}
				/>
				<YAxis
					type="category"
					dataKey="symbol"
					stroke="hsl(var(--muted-foreground))"
					fontSize={12}
					width={80}
				/>
				<Tooltip
					cursor={{ fill: "rgba(255, 255, 255, 0.05)" }}
					content={<CustomSymbolTooltip />}
				/>
				<Bar dataKey="netPnl" name="Net PnL">
					{chartData.map((entry, index) => (
						<Cell
							key={`cell-${index}`}
							fill={
								entry.netPnl >= 0 ? "hsl(var(--profit))" : "hsl(var(--loss))"
							}
						/>
					))}
				</Bar>
			</BarChart>
		</ResponsiveContainer>
	);
};
