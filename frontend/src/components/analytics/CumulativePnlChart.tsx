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

interface CustomCumulativeTooltipProps {
	active?: boolean;
	payload?: Array<{ payload?: { tradeNumber: number; netPnl: number; date: string } }>;
}

const CustomCumulativeTooltip = ({
	active,
	payload,
}: CustomCumulativeTooltipProps) => {
	if (!active || !payload?.length || !payload[0]?.payload) return null;
	const data = payload[0].payload;
	const netPnl = Number(data.netPnl || 0);
	const isProfit = netPnl >= 0;

	return (
		<div className="rounded-xl border border-border dark:border-white/15 bg-card/95 dark:bg-[#0b0f17]/95 px-3 py-2 shadow-2xl backdrop-blur-xl font-mono text-popover-foreground">
			<div className="text-[11px] font-medium text-muted-foreground dark:text-slate-300 mb-0.5">
				Trade #{data.tradeNumber} • {data.date}
			</div>
			<div className="flex items-center gap-2 text-xs">
				<span className="text-muted-foreground dark:text-white/60">Net PnL:</span>
				<span className={`font-bold ${isProfit ? "text-emerald-500 dark:text-emerald-400" : "text-rose-500 dark:text-rose-400"}`}>
					{isProfit ? "+" : ""}${netPnl.toFixed(2)}
				</span>
			</div>
		</div>
	);
};

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
				<Tooltip content={<CustomCumulativeTooltip />} />
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
