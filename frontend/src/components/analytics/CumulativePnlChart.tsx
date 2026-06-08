// src/components/analytics/CumulativePnlChart.tsx

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
	Area,
	AreaChart,
	CartesianGrid,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import type { TradeData } from "@/types/api";

interface CumulativePnlChartProps {
	tradeData: TradeData[];
}

export const CumulativePnlChart = ({ tradeData }: CumulativePnlChartProps) => {
	const { t } = useTranslation("analytics");
	const chartData = useMemo(() => {
		const result: { tradeNumber: number; netPnl: number; date: string }[] = [];
		let cumulativeNet = 0;
		for (let i = 0; i < tradeData.length; i++) {
			const trade = tradeData[i];
			const realizedPnl = trade.pnl || 0;
			cumulativeNet += realizedPnl;
			result.push({
				tradeNumber: i + 1,
				netPnl: cumulativeNet,
				date: new Date(trade.timestamp_close).toLocaleDateString(),
			});
		}
		return result;
	}, [tradeData]);

	if (tradeData.length === 0) {
		return (
			<div className="text-center text-muted-foreground p-8">
				{t("noDataForChart")}
			</div>
		);
	}

	return (
		<ResponsiveContainer width="100%" height={400}>
			<AreaChart data={chartData}>
				<defs>
					<linearGradient id="colorNetPnl" x1="0" y1="0" x2="0" y2="1">
						<stop
							offset="5%"
							stopColor="var(--color-primary)"
							stopOpacity={0.4}
						/>
						<stop
							offset="95%"
							stopColor="var(--color-primary)"
							stopOpacity={0}
						/>
					</linearGradient>
				</defs>
				<CartesianGrid
					strokeDasharray="3 3"
					stroke="hsl(var(--border) / 0.5)"
				/>
				<XAxis
					dataKey="tradeNumber"
					stroke="hsl(var(--muted-foreground))"
					fontSize={12}
					tickLine={false}
					axisLine={false}
				/>
				<YAxis
					stroke="hsl(var(--muted-foreground))"
					fontSize={12}
					tickLine={false}
					axisLine={false}
					tickFormatter={(value) => `$${value}`}
				/>
				<Tooltip
					contentStyle={{
						background: "hsl(var(--card))",
						borderColor: "hsl(var(--border))",
						borderRadius: "var(--radius)",
					}}
					labelStyle={{ color: "hsl(var(--foreground))" }}
				/>
				<Area
					type="monotone"
					dataKey="netPnl"
					stroke="hsl(var(--primary))"
					fillOpacity={1}
					fill="url(#colorNetPnl)"
				/>
			</AreaChart>
		</ResponsiveContainer>
	);
};
