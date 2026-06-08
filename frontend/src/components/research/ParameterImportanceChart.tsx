// src/components/research/ParameterImportanceChart.tsx

import type React from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import {
	Bar,
	BarChart,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import type { ParameterImportanceData } from "@/types/api";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface ParameterImportanceChartProps {
	importanceData: ParameterImportanceData | null;
}

export const ParameterImportanceChart: React.FC<
	ParameterImportanceChartProps
> = ({ importanceData }) => {
	const { t } = useTranslation("research"); // Initialize useTranslation
	const data = importanceData
		? Object.entries(importanceData)
				.map(([name, value]) => ({ name, value }))
				.sort((a, b) => b.value - a.value)
		: [];

	return (
		<Card>
			<CardHeader>
				<CardTitle>{t("parameterImportanceTitle")}</CardTitle>
			</CardHeader>
			<CardContent>
				{data.length > 0 ? (
					<ResponsiveContainer width="100%" height={300}>
						<BarChart data={data} layout="vertical">
							<XAxis type="number" stroke="hsl(var(--muted-foreground))" />
							<YAxis
								type="category"
								dataKey="name"
								stroke="hsl(var(--muted-foreground))"
								width={120}
							/>
							<Tooltip
								contentStyle={{
									background: "hsl(var(--background))",
									border: "1px solid hsl(var(--border))",
								}}
							/>
							<Bar dataKey="value" fill="hsl(var(--primary))" />
						</BarChart>
					</ResponsiveContainer>
				) : (
					<div className="flex items-center justify-center h-[300px] text-muted-foreground">
						{t("parameterImportanceNoData")}
					</div>
				)}
			</CardContent>
		</Card>
	);
};
