import type React from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import {
	Cell,
	Legend,
	Pie,
	PieChart,
	ResponsiveContainer,
	Tooltip,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface PieChartDataItem {
	name: string;
	value: number;
	fill?: string; // Optional: if you want to pre-define colors
}

interface GenericPieChartProps {
	data: PieChartDataItem[];
	title?: string;
	// Recharts' Pie component can accept a 'cx', 'cy', 'outerRadius', etc.
	// We can expose some of these if needed, or keep it simple for now.
	cx?: string | number;
	cy?: string | number;
	outerRadius?: string | number;
	innerRadius?: string | number; // For doughnut charts
	showLegend?: boolean;
	showTooltip?: boolean;
}

const COLORS = [
	"#0088FE",
	"#00C49F",
	"#FFBB28",
	"#FF8042",
	"#8884D8",
	"#82CA9D",
	"#FFC0CB",
	"#A52A2A",
];

const GenericPieChart: React.FC<GenericPieChartProps> = ({
	data,
	title,
	cx = "50%",
	cy = "50%",
	outerRadius = "80%",
	innerRadius = "0%", // Makes it a pie chart by default, set for doughnut
	showLegend = true,
	showTooltip = true,
}) => {
	const { t } = useTranslation("research"); // Initialize useTranslation

	if (!data || data.length === 0) {
		return (
			<Card>
				{title && (
					<CardHeader>
						<CardTitle className="text-base">{title}</CardTitle>
					</CardHeader>
				)}
				<CardContent className="h-64 flex items-center justify-center">
					<p className="text-sm text-muted-foreground">
						{t("noDataForPieChart")}
					</p>
				</CardContent>
			</Card>
		);
	}

	return (
		<ResponsiveContainer width="100%" height={300}>
			<PieChart>
				<Pie
					data={data}
					cx={cx}
					cy={cy}
					innerRadius={innerRadius}
					outerRadius={outerRadius}
					fill="#8884d8"
					dataKey="value"
					labelLine={false}
					// label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`} // Simple label
				>
					{data.map((entry, index) => (
						<Cell
							key={`cell-${index}`}
							fill={entry.fill || COLORS[index % COLORS.length]}
						/>
					))}
				</Pie>
				{showTooltip && <Tooltip />}
				{showLegend && (
					<Legend layout="horizontal" verticalAlign="bottom" align="center" />
				)}
			</PieChart>
		</ResponsiveContainer>
	);
};

export default GenericPieChart;
