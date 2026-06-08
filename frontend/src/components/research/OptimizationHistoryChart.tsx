// src/components/research/OptimizationHistoryChart.tsx

import type React from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import {
	CartesianGrid,
	Cell,
	ResponsiveContainer,
	Scatter,
	ScatterChart,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import type { OptimizationTrial } from "@/types/api";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

type OptimizationTooltipProps = {
	active?: boolean;
	payload?: Array<{ payload: OptimizationTrial }>;
	t: (key: string) => string;
};

const CustomTooltip = ({ active, payload, t }: OptimizationTooltipProps) => {
	// Pass t to CustomTooltip
	if (active && payload?.length) {
		const data = payload[0].payload;
		return (
			<div className="bg-card border border-border p-3 rounded-lg shadow-xl text-sm">
				<p className="font-mono">
					<span className="text-muted-foreground">
						{t("trialsTable.colTrial")}
					</span>
					<span className="text-foreground font-semibold">
						{data.trial_number}
					</span>
				</p>
				<p className="font-mono mt-1">
					<span className="text-muted-foreground">
						{t("trialsTable.colValue")}
					</span>
					<span className="text-foreground font-semibold">
						{data.value?.toFixed(4)}
					</span>
				</p>
			</div>
		);
	}
	return null;
};

interface OptimizationHistoryChartProps {
	trials: OptimizationTrial[];
	bestTrialId?: number;
}

export const OptimizationHistoryChart: React.FC<
	OptimizationHistoryChartProps
> = ({ trials, bestTrialId }) => {
	const { t } = useTranslation("research"); // Initialize useTranslation

	if (!trials || trials.length === 0) {
		return (
			<div className="flex items-center justify-center h-[300px] text-muted-foreground">
				{t("optimizationViewer.noBestTrial")}
			</div>
		);
	}
	return (
		<Card>
			<CardHeader>
				<CardTitle>{t("optimizationViewer.tabOverview")}</CardTitle>
			</CardHeader>
			<CardContent>
				<ResponsiveContainer width="100%" height={300}>
					<ScatterChart>
						<CartesianGrid
							strokeDasharray="3 3"
							stroke="hsl(var(--border) / 0.5)"
						/>
						<XAxis
							type="number"
							dataKey="trial_number"
							name={t("trialsTable.colTrial")}
							unit=""
							stroke="hsl(var(--muted-foreground))"
						/>
						<YAxis
							type="number"
							dataKey="value"
							name={t("trialsTable.colValue")}
							unit=""
							stroke="hsl(var(--muted-foreground))"
							domain={["auto", "auto"]}
						/>
						<Tooltip
							cursor={{ stroke: "hsl(var(--border))", strokeDasharray: "3 3" }}
							content={<CustomTooltip t={t} />} // Pass t to CustomTooltip
						/>
						<Scatter
							name={t("trialsTable.colTrial")}
							data={trials.filter((t) => t.value != null)}
						>
							{trials.map((trial) => (
								<Cell
									key={`cell-${trial.trial_number}`}
									fill={
										trial.trial_number === bestTrialId
											? "hsl(var(--primary))"
											: "hsl(var(--muted-foreground))"
									}
								/>
							))}
						</Scatter>
					</ScatterChart>
				</ResponsiveContainer>
			</CardContent>
		</Card>
	);
};
