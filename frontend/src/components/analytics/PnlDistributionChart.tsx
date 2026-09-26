// src/components/analytics/PnlDistributionChart.tsx

import { useMemo } from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import {
	Bar,
	BarChart,
	CartesianGrid,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import type { TradeData } from "@/types/api";

interface PnlDistributionChartProps {
	tradeData: TradeData[];
}

interface CustomDistTooltipProps {
	active?: boolean;
	payload?: Array<{ dataKey?: string; value?: unknown }>;
	label?: string;
	profitableText: string;
	losingText: string;
}

const CustomDistTooltip = ({
	active,
	payload,
	label,
	profitableText,
	losingText,
}: CustomDistTooltipProps) => {
	if (!active || !payload?.length) return null;
	const positive = Number(payload.find((p) => p.dataKey === "positive")?.value || 0);
	const negative = Number(payload.find((p) => p.dataKey === "negative")?.value || 0);

	return (
		<div className="rounded-xl border border-white/15 bg-[#0b0f17]/95 px-3 py-2 shadow-2xl backdrop-blur-xl font-mono">
			<div className="text-[11px] font-semibold text-white/70 mb-1.5">
				Range: ${label}
			</div>
			<div className="space-y-1 text-xs">
				<div className="flex items-center justify-between gap-4">
					<span className="text-emerald-400 font-medium">{profitableText}:</span>
					<span className="font-bold text-white">{positive}</span>
				</div>
				<div className="flex items-center justify-between gap-4">
					<span className="text-rose-400 font-medium">{losingText}:</span>
					<span className="font-bold text-white">{negative}</span>
				</div>
			</div>
		</div>
	);
};

export const PnlDistributionChart = ({
	tradeData,
}: PnlDistributionChartProps) => {
	const { t } = useTranslation("analytics"); // Initialize useTranslation
	const chartData = useMemo(() => {
		if (tradeData.length === 0) return [];

		// Calculate realized PnL: subtract commission from PnL
		const pnlValues = tradeData.map((t) => (t.pnl || 0) - (t.commission || 0));
		const maxPnl = Math.max(...pnlValues);
		const minPnl = Math.min(...pnlValues);
		const range = maxPnl - minPnl;
		const binCount = Math.min(20, Math.ceil(Math.sqrt(tradeData.length))); // Heuristic for number of bins
		const binSize = range > 0 ? Math.ceil(range / binCount / 10) * 10 : 10; // Round bin size

		const bins: {
			[key: string]: { range: string; positive: number; negative: number };
		} = {};

		pnlValues.forEach((pnl) => {
			const binStart = Math.floor(pnl / binSize) * binSize;
			const binEnd = binStart + binSize;
			const rangeLabel = `${binStart}..${binEnd}`;
			if (!bins[rangeLabel]) {
				bins[rangeLabel] = { range: rangeLabel, positive: 0, negative: 0 };
			}
			if (pnl >= 0) {
				bins[rangeLabel].positive += 1;
			} else {
				bins[rangeLabel].negative += 1;
			}
		});

		return Object.values(bins).sort(
			(a, b) => parseInt(a.range, 10) - parseInt(b.range, 10),
		);
	}, [tradeData]);

	if (tradeData.length === 0) {
		return (
			<div className="text-center text-muted-foreground p-8">
				{t("noTradesForDistribution")}
			</div>
		);
	}

	return (
		<ResponsiveContainer width="100%" height={400}>
			<BarChart
				data={chartData}
				margin={{ top: 5, right: 20, left: -10, bottom: 5 }}
			>
				<CartesianGrid
					strokeDasharray="3 3"
					stroke="hsl(var(--border) / 0.5)"
				/>
				<XAxis
					dataKey="range"
					stroke="hsl(var(--muted-foreground))"
					fontSize={12}
				/>
				<YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
				<Tooltip
					cursor={{ fill: "rgba(255, 255, 255, 0.05)" }}
					content={
						<CustomDistTooltip
							profitableText={t("profitableTrades")}
							losingText={t("losingTrades")}
						/>
					}
				/>
				<Bar
					dataKey="positive"
					stackId="a"
					fill="hsl(var(--profit))"
					name={t("profitableTrades")}
				/>
				<Bar
					dataKey="negative"
					stackId="a"
					fill="hsl(var(--loss))"
					name={t("losingTrades")}
				/>
			</BarChart>
		</ResponsiveContainer>
	);
};
