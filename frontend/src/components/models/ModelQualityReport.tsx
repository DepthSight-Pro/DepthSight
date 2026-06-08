// src/components/models/ModelQualityReport.tsx

import type React from "react";
import { useTranslation } from "react-i18next";
import {
	Bar,
	BarChart,
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
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useGetTrainingRunReport } from "@/lib/api";
import { AppLoader } from "../shared/AppLoader";

interface ModelQualityReportProps {
	runId: string;
}

export const ModelQualityReport: React.FC<ModelQualityReportProps> = ({
	runId,
}) => {
	const { t } = useTranslation("modelLab");
	const {
		data: report,
		isLoading,
		isError,
	} = useGetTrainingRunReport(runId, true);

	if (isLoading)
		return (
			<div className="h-full flex items-center justify-center">
				<AppLoader text="Loading report..." />
			</div>
		);
	if (isError || !report)
		return (
			<div className="h-full flex items-center justify-center">
				<p className="text-destructive">Failed to load report.</p>
			</div>
		);

	const importanceData = Object.entries(report.feature_importance)
		.map(([name, value]) => ({ name, value }))
		.sort((a, b) => b.value - a.value);

	return (
		<Card>
			<CardHeader>
				<CardTitle>{t("modelTrainingViewer.reportTitle")}</CardTitle>
				<CardDescription>
					{t("modelTrainingViewer.reportDescription")}
				</CardDescription>
			</CardHeader>
			<CardContent>
				<Tabs defaultValue="classification">
					<TabsList className="grid w-full grid-cols-3">
						<TabsTrigger value="classification">Classification</TabsTrigger>
						<TabsTrigger value="confusion">Confusion Matrix</TabsTrigger>
						<TabsTrigger value="importance">Feature Importance</TabsTrigger>
					</TabsList>
					<TabsContent value="classification" className="pt-4">
						<Table>
							<TableHeader>
								<TableRow>
									<TableHead>Metric</TableHead>
									<TableHead>Precision</TableHead>
									<TableHead>Recall</TableHead>
									<TableHead>F1-Score</TableHead>
									<TableHead>Support</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{Object.entries(report.classification_report)
									.filter(
										([key]) =>
											typeof report.classification_report[key] === "object",
									)
									.map(([key, value]) => {
										const entry = value as {
											precision: number;
											recall: number;
											"f1-score": number;
											support: number;
										};
										return (
											<TableRow key={key}>
												<TableCell>{key}</TableCell>
												<TableCell>{entry.precision.toFixed(2)}</TableCell>
												<TableCell>{entry.recall.toFixed(2)}</TableCell>
												<TableCell>{entry["f1-score"].toFixed(2)}</TableCell>
												<TableCell>{entry.support}</TableCell>
											</TableRow>
										);
									})}
							</TableBody>
						</Table>
					</TabsContent>
					<TabsContent value="confusion" className="pt-4">
						{/* A simple table for confusion matrix. Could be enhanced with colors. */}
						<Table>
							<TableHeader>
								<TableRow>
									<TableHead>Predicted \ Actual</TableHead>
									{report.confusion_matrix[0].map((_, i) => (
										<TableHead key={i}>{i}</TableHead>
									))}
								</TableRow>
							</TableHeader>
							<TableBody>
								{report.confusion_matrix.map((row, i) => (
									<TableRow key={i}>
										<TableCell>{i}</TableCell>
										{row.map((cell, j) => (
											<TableCell key={j}>{cell}</TableCell>
										))}
									</TableRow>
								))}
							</TableBody>
						</Table>
					</TabsContent>
					<TabsContent value="importance" className="pt-4">
						<ResponsiveContainer width="100%" height={300}>
							<BarChart data={importanceData} layout="vertical">
								<YAxis
									type="category"
									dataKey="name"
									width={150}
									tick={{ fontSize: 10 }}
								/>
								<XAxis type="number" />
								<Tooltip />
								<Bar dataKey="value" fill="hsl(var(--primary))" />
							</BarChart>
						</ResponsiveContainer>
					</TabsContent>
				</Tabs>
			</CardContent>
		</Card>
	);
};
