// src/components/admin/analytics/MarketSentimentChart.tsx
import type React from "react";
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
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { MarketSentimentStat } from "@/types/api";

interface Props {
	data: MarketSentimentStat[];
	isLoading: boolean;
	title?: string;
}

interface CustomTooltipProps {
	active?: boolean;
	payload?: Array<{
		payload: {
			name: string;
			pnl: number;
		};
	}>;
}

const CustomTooltip = ({ active, payload }: CustomTooltipProps) => {
	if (active && payload?.length) {
		const data = payload[0].payload;
		return (
			<div className="bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-lg">
				<p className="text-white font-bold text-lg">{data.name}</p>
				<p
					className={`text-xl font-bold ${data.pnl >= 0 ? "text-green-400" : "text-red-400"}`}
				>
					$
					{data.pnl.toLocaleString(undefined, {
						minimumFractionDigits: 2,
						maximumFractionDigits: 2,
					})}
				</p>
			</div>
		);
	}
	return null;
};

const MarketSentimentChart: React.FC<Props> = ({
	data,
	isLoading,
	title = "Market Sentiment",
}) => {
	const chartData = data?.map((item) => ({
		name:
			item.direction === "long"
				? "LONG"
				: item.direction === "short"
					? "SHORT"
					: item.direction.toUpperCase(),
		pnl: item.totalPnl,
		fill: item.totalPnl >= 0 ? "#22c55e" : "#ef4444", // Bright green/red
	}));

	// Calculate totals for display
	const totalPnl = data?.reduce((sum, item) => sum + item.totalPnl, 0) || 0;

	if (isLoading) {
		return (
			<Card>
				<CardHeader>
					<CardTitle>{title}</CardTitle>
				</CardHeader>
				<CardContent>
					<Skeleton className="h-[250px] w-full" />
				</CardContent>
			</Card>
		);
	}

	if (!chartData || chartData.length === 0) {
		return (
			<Card>
				<CardHeader>
					<CardTitle>{title}</CardTitle>
				</CardHeader>
				<CardContent>
					<div className="h-[250px] flex items-center justify-center">
						<p className="text-sm text-muted-foreground">
							No market sentiment data available.
						</p>
					</div>
				</CardContent>
			</Card>
		);
	}

	return (
		<Card>
			<CardHeader>
				<CardTitle>{title}</CardTitle>
				<CardDescription>
					Total PnL:{" "}
					<span
						className={`font-bold ${totalPnl >= 0 ? "text-green-400" : "text-red-400"}`}
					>
						$
						{totalPnl.toLocaleString(undefined, {
							minimumFractionDigits: 2,
							maximumFractionDigits: 2,
						})}
					</span>
				</CardDescription>
			</CardHeader>
			<CardContent>
				<ResponsiveContainer width="100%" height={250}>
					<BarChart
						data={chartData}
						margin={{ top: 20, right: 30, left: 20, bottom: 20 }}
					>
						<CartesianGrid
							strokeDasharray="3 3"
							stroke="#374151"
							vertical={false}
						/>
						<XAxis
							dataKey="name"
							tick={{ fill: "#f3f4f6", fontSize: 14, fontWeight: "bold" }}
							axisLine={false}
							tickLine={false}
						/>
						<YAxis
							tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
							tick={{ fill: "#9ca3af" }}
							axisLine={false}
							tickLine={false}
						/>
						<Tooltip
							content={<CustomTooltip />}
							cursor={{ fill: "rgba(255,255,255,0.1)" }}
						/>
						<Bar dataKey="pnl" radius={[8, 8, 0, 0]} maxBarSize={100}>
							{chartData.map((entry, index) => (
								<Cell
									key={`cell-${index}`}
									fill={entry.fill}
									stroke={entry.pnl >= 0 ? "#16a34a" : "#dc2626"}
									strokeWidth={2}
								/>
							))}
						</Bar>
					</BarChart>
				</ResponsiveContainer>

				{/* Legend */}
				<div className="flex justify-center gap-8 mt-4">
					{chartData.map((item) => (
						<div key={item.name} className="flex items-center gap-2">
							<div
								className="w-4 h-4 rounded"
								style={{ backgroundColor: item.fill }}
							/>
							<span className="text-sm text-gray-300">{item.name}</span>
							<span
								className={`text-sm font-bold ${item.pnl >= 0 ? "text-green-400" : "text-red-400"}`}
							>
								$
								{item.pnl.toLocaleString(undefined, {
									minimumFractionDigits: 0,
									maximumFractionDigits: 0,
								})}
							</span>
						</div>
					))}
				</div>
			</CardContent>
		</Card>
	);
};

export default MarketSentimentChart;
