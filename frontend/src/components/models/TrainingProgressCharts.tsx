// src/components/models/TrainingProgressCharts.tsx

import type React from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
	CartesianGrid,
	Legend,
	Line,
	LineChart,
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
import type { TrainingRunResponse } from "@/types/api";

interface TrainingProgressChartsProps {
	run: TrainingRunResponse;
}

export const TrainingProgressCharts: React.FC<TrainingProgressChartsProps> = ({
	run,
}) => {
	const { t } = useTranslation("modelLab");
	const metrics = useMemo(
		() => run.live_metrics_json || {},
		[run.live_metrics_json],
	);
	const metricKeys = useMemo(() => Object.keys(metrics), [metrics]);

	const chartData = useMemo(() => {
		if (metricKeys.length === 0) return [];
		const firstMetricData = metrics[metricKeys[0]];
		// Ensure that firstMetricData is an array
		if (!Array.isArray(firstMetricData)) return [];

		return firstMetricData.map((entry, index) => {
			const dataPoint: { [key: string]: number } = { epoch: entry[0] };
			metricKeys.forEach((key) => {
				if (
					metrics[key] &&
					Array.isArray(metrics[key]) &&
					metrics[key][index]
				) {
					dataPoint[key] = metrics[key][index][1];
				}
			});
			return dataPoint;
		});
	}, [metrics, metricKeys]);

	if (
		run.status === "PENDING" ||
		(run.status === "RUNNING" && metricKeys.length === 0)
	) {
		return (
			<Card>
				<CardHeader>
					<CardTitle>{t("modelTrainingViewer.chartsTitle")}</CardTitle>
					<CardDescription>
						{t("modelTrainingViewer.chartsDescription")}
					</CardDescription>
				</CardHeader>
				<CardContent className="h-64 flex items-center justify-center">
					<p className="text-muted-foreground">
						Waiting for the first training metrics...
					</p>
				</CardContent>
			</Card>
		);
	}

	const COLORS = ["#8884d8", "#82ca9d", "#ffc658", "#ff8042"];

	return (
		<Card>
			<CardHeader>
				<CardTitle>{t("modelTrainingViewer.chartsTitle")}</CardTitle>
				<CardDescription>
					{t("modelTrainingViewer.chartsDescription")}
				</CardDescription>
			</CardHeader>
			<CardContent>
				<ResponsiveContainer width="100%" height={300}>
					<LineChart data={chartData}>
						<CartesianGrid strokeDasharray="3 3" />
						<XAxis
							dataKey="epoch"
							label={{ value: "Epoch", position: "insideBottom", offset: -5 }}
						/>
						<YAxis domain={[0, "auto"]} />
						<Tooltip />
						<Legend />
						{metricKeys.map((key, index) => (
							<Line
								key={key}
								type="monotone"
								dataKey={key}
								stroke={COLORS[index % COLORS.length]}
								dot={false}
							/>
						))}
					</LineChart>
				</ResponsiveContainer>
			</CardContent>
		</Card>
	);
};
