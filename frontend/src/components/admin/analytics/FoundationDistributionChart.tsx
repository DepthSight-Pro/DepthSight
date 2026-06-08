// src/components/admin/analytics/FoundationDistributionChart.tsx
import type React from "react";
import {
	Cell,
	Legend,
	Pie,
	PieChart,
	ResponsiveContainer,
	Tooltip,
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

const COLORS = [
	"#22c55e",
	"#3b82f6",
	"#f59e0b",
	"#ef4444",
	"#a855f7",
	"#06b6d4",
	"#ec4899",
	"#84cc16",
	"#f97316",
	"#6366f1",
	"#14b8a6",
	"#f43f5e",
	"#8b5cf6",
	"#eab308",
	"#0ea5e9",
];

interface CustomTooltipProps {
	active?: boolean;
	payload?: Array<{
		payload: {
			name: string;
			value: number;
			totalTrades?: number;
		};
	}>;
}

const CustomTooltip = ({ active, payload }: CustomTooltipProps) => {
	if (active && payload?.length) {
		const data = payload[0].payload;
		const totalTrades = data.totalTrades || 0;
		const percentage =
			totalTrades > 0 ? ((data.value / totalTrades) * 100).toFixed(1) : "0.0";
		return (
			<div className="bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-lg">
				<p className="text-white font-medium">{data.name}</p>
				<p className="text-gray-300">
					Trades: <span className="text-white font-bold">{data.value}</span>
				</p>
				<p className="text-gray-300">
					Share: <span className="text-white font-bold">{percentage}%</span>
				</p>
			</div>
		);
	}
	return null;
};

const FoundationDistributionChart: React.FC<Props> = ({
	data,
	isLoading,
	title = "Trade Distribution by Condition",
}) => {
	// Take top 8 and group the rest as "Other"
	const sorted = [...data].sort((a, b) => b.count - a.count);
	const top8 = sorted.slice(0, 8);
	const others = sorted.slice(8);

	const otherCount = others.reduce((sum, s) => sum + s.count, 0);

	const totalTrades = sorted.reduce((sum, d) => sum + d.count, 0);

	const chartData = [
		...top8.map((stat, index) => ({
			name: stat.foundationId || `Condition ${index + 1}`,
			value: stat.count,
			color: COLORS[index % COLORS.length],
			totalTrades,
		})),
		...(otherCount > 0
			? [
					{
						name: "Other",
						value: otherCount,
						color: "#6b7280",
						totalTrades,
					},
				]
			: []),
	];

	if (isLoading) {
		return (
			<Card>
				<CardHeader>
					<CardTitle>{title}</CardTitle>
				</CardHeader>
				<CardContent>
					<Skeleton className="h-[300px] w-full" />
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
				<CardContent className="h-[300px] flex items-center justify-center text-muted-foreground">
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
					Total: {totalTrades.toLocaleString()} trades across {data.length}{" "}
					conditions
				</CardDescription>
			</CardHeader>
			<CardContent>
				<ResponsiveContainer width="100%" height={350}>
					<PieChart>
						<Pie
							data={chartData}
							cx="50%"
							cy="50%"
							innerRadius={60}
							outerRadius={120}
							paddingAngle={2}
							dataKey="value"
							label={({
								name,
								percent,
							}: {
								name?: string;
								percent?: number;
							}) =>
								percent && percent > 0.05
									? `${(name || "").slice(0, 10)}...`
									: ""
							}
							labelLine={false}
						>
							{chartData.map((entry, index) => (
								<Cell
									key={`cell-${index}`}
									fill={entry.color}
									strokeWidth={0}
								/>
							))}
						</Pie>
						<Tooltip content={<CustomTooltip />} />
						<Legend
							layout="vertical"
							align="right"
							verticalAlign="middle"
							formatter={(value) => (
								<span className="text-gray-300 text-sm">{value}</span>
							)}
						/>
					</PieChart>
				</ResponsiveContainer>
			</CardContent>
		</Card>
	);
};

export default FoundationDistributionChart;
