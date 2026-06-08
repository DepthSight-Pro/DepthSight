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
					cursor={{ fill: "hsl(var(--accent))" }}
					contentStyle={{
						background: "hsl(var(--card))",
						borderColor: "hsl(var(--border))",
					}}
					formatter={(value: unknown) => `$${Number(value ?? 0).toFixed(2)}`}
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
