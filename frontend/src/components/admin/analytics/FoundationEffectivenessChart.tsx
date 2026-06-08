// src/components/admin/analytics/FoundationEffectivenessChart.tsx
import type React from "react";
import {
	Bar,
	BarChart,
	CartesianGrid,
	Legend,
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
];

const FoundationEffectivenessChart: React.FC<Props> = ({
	data,
	isLoading,
	title = "Entry Conditions Performance",
}) => {
	// Sort by count and take top 10
	const chartData = [...data]
		.sort((a, b) => b.count - a.count)
		.slice(0, 10)
		.map((stat, index) => ({
			name: stat.foundationId || `Condition ${index + 1}`,
			shortName: (stat.foundationId || `C${index + 1}`).slice(0, 15),
			winRate: (stat.avgWinRateContribution * 100).toFixed(1),
			profitFactor: stat.profitFactor?.toFixed(2) || 0,
			count: stat.count,
			color: COLORS[index % COLORS.length],
		}));

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
				<CardDescription>Top 10 conditions by trade count</CardDescription>
			</CardHeader>
			<CardContent>
				<ResponsiveContainer width="100%" height={350}>
					<BarChart
						data={chartData}
						margin={{ top: 20, right: 30, left: 20, bottom: 60 }}
					>
						<CartesianGrid strokeDasharray="3 3" stroke="#374151" />
						<XAxis
							dataKey="shortName"
							angle={-45}
							textAnchor="end"
							height={80}
							tick={{ fill: "#9ca3af", fontSize: 11 }}
						/>
						<YAxis
							yAxisId="left"
							tick={{ fill: "#9ca3af" }}
							label={{
								value: "Win Rate %",
								angle: -90,
								position: "insideLeft",
								fill: "#9ca3af",
							}}
						/>
						<YAxis
							yAxisId="right"
							orientation="right"
							tick={{ fill: "#9ca3af" }}
							label={{
								value: "Profit Factor",
								angle: 90,
								position: "insideRight",
								fill: "#9ca3af",
							}}
						/>
						<Tooltip
							contentStyle={{
								backgroundColor: "#1f2937",
								border: "1px solid #374151",
								borderRadius: "8px",
							}}
							labelStyle={{ color: "#f3f4f6" }}
							formatter={(value: unknown, name: unknown) => [
								name === "winRate"
									? `${Number(value ?? 0)}%`
									: Number(value ?? 0),
								name === "winRate" ? "Win Rate" : "Profit Factor",
							]}
						/>
						<Legend />
						<Bar
							yAxisId="left"
							dataKey="winRate"
							name="Win Rate %"
							fill="#22c55e"
							radius={[4, 4, 0, 0]}
						/>
						<Bar
							yAxisId="right"
							dataKey="profitFactor"
							name="Profit Factor"
							fill="#3b82f6"
							radius={[4, 4, 0, 0]}
						/>
					</BarChart>
				</ResponsiveContainer>
			</CardContent>
		</Card>
	);
};

export default FoundationEffectivenessChart;
