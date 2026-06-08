// src/components/admin/analytics/FoundationScatterChart.tsx
import type React from "react";
import {
	CartesianGrid,
	Cell,
	ResponsiveContainer,
	Scatter,
	ScatterChart,
	Tooltip,
	XAxis,
	YAxis,
	ZAxis,
} from "recharts";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { FoundationStat } from "@/types/api";

interface Props {
	data: FoundationStat[];
	isLoading: boolean;
	title?: string;
}

interface CustomTooltipProps {
	active?: boolean;
	payload?: Array<{
		payload: {
			name: string;
			x: number;
			originalPF: number;
			count: number;
		};
	}>;
}

const CustomTooltip = ({ active, payload }: CustomTooltipProps) => {
	if (active && payload?.length) {
		const data = payload[0].payload;
		return (
			<div className="bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-lg max-w-xs">
				<p className="text-white font-medium text-sm mb-2 break-words">
					{data.name}
				</p>
				<div className="space-y-1 text-sm">
					<p className="text-gray-300">
						Win Rate:{" "}
						<span className="text-white font-bold">{data.x.toFixed(1)}%</span>
					</p>
					<p className="text-gray-300">
						Profit Factor:{" "}
						<span className="text-white font-bold">
							{data.originalPF.toFixed(2)}
						</span>
					</p>
					<p className="text-gray-300">
						Trades: <span className="text-white font-bold">{data.count}</span>
					</p>
				</div>
			</div>
		);
	}
	return null;
};

const FoundationScatterChart: React.FC<Props> = ({
	data,
	isLoading,
	title = "Condition Quality Matrix",
}) => {
	const chartData = data
		.filter((s) => s.profitFactor !== null && s.profitFactor !== undefined)
		.map((stat) => ({
			name: stat.foundationId || "Unknown",
			x: stat.avgWinRateContribution * 100, // Win Rate as percentage
			y: Math.min(stat.profitFactor, 10), // Cap profit factor at 10 for visibility
			z: stat.count, // Size based on trade count
			originalPF: stat.profitFactor,
			count: stat.count,
		}));

	// Determine color based on quality (high win rate + high PF = green)
	const getColor = (winRate: number, pf: number) => {
		if (winRate > 0 && pf > 1.5) return "#22c55e"; // Green - excellent
		if (winRate > 0 && pf > 1) return "#3b82f6"; // Blue - good
		if (pf > 1) return "#f59e0b"; // Yellow - marginal
		return "#ef4444"; // Red - poor
	};

	if (isLoading) {
		return (
			<Card>
				<CardHeader>
					<CardTitle>{title}</CardTitle>
				</CardHeader>
				<CardContent>
					<Skeleton className="h-[350px] w-full" />
				</CardContent>
			</Card>
		);
	}

	if (!data || data.length === 0) {
		return (
			<Card>
				<CardHeader>
					<CardTitle>{title}</CardTitle>
				</CardHeader>
				<CardContent className="h-[350px] flex items-center justify-center text-muted-foreground">
					No data available
				</CardContent>
			</Card>
		);
	}

	return (
		<Card>
			<CardHeader>
				<CardTitle>{title}</CardTitle>
				<CardDescription>
					Bubble size = trade count. Green = excellent, Blue = good, Yellow =
					marginal, Red = poor
				</CardDescription>
			</CardHeader>
			<CardContent>
				<ResponsiveContainer width="100%" height={350}>
					<ScatterChart margin={{ top: 20, right: 20, bottom: 40, left: 20 }}>
						<CartesianGrid strokeDasharray="3 3" stroke="#374151" />
						<XAxis
							type="number"
							dataKey="x"
							name="Win Rate"
							unit="%"
							domain={["auto", "auto"]}
							tick={{ fill: "#9ca3af" }}
							label={{
								value: "Win Rate Contribution %",
								position: "bottom",
								fill: "#9ca3af",
								offset: 20,
							}}
						/>
						<YAxis
							type="number"
							dataKey="y"
							name="Profit Factor"
							domain={[0, "auto"]}
							tick={{ fill: "#9ca3af" }}
							label={{
								value: "Profit Factor",
								angle: -90,
								position: "insideLeft",
								fill: "#9ca3af",
							}}
						/>
						<ZAxis type="number" dataKey="z" range={[50, 400]} />
						<Tooltip content={<CustomTooltip />} />
						{/* Reference lines for quality thresholds */}
						<Scatter name="Conditions" data={chartData}>
							{chartData.map((entry, index) => (
								<Cell
									key={`cell-${index}`}
									fill={getColor(entry.x, entry.y)}
									fillOpacity={0.8}
								/>
							))}
						</Scatter>
					</ScatterChart>
				</ResponsiveContainer>
			</CardContent>
		</Card>
	);
};

export default FoundationScatterChart;
