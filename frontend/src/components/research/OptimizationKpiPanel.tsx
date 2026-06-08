// src/components/research/OptimizationKpiPanel.tsx

import type React from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { OptimizationProgressInfo, TaskData } from "@/types/api";
import { Progress } from "../ui/progress";

const KpiItem: React.FC<{ label: string; value: React.ReactNode }> = ({
	label,
	value,
}) => (
	<div className="flex justify-between items-baseline text-sm">
		<p className="text-muted-foreground">{label}</p>
		<p className="font-mono font-medium">{value}</p>
	</div>
);

// Type guard to check if progress is for optimization
function isOptimizationProgress(
	progress: unknown,
): progress is OptimizationProgressInfo {
	return (
		!!progress &&
		typeof progress === "object" &&
		"current_trial_number" in progress &&
		typeof progress.current_trial_number === "number"
	);
}

export const OptimizationKpiPanel: React.FC<{ run: TaskData }> = ({ run }) => {
	const { t } = useTranslation("research");
	const progress = run.progress_info;

	// Use the type guard
	const optimizationProgress = isOptimizationProgress(progress)
		? progress
		: null;
	const notAvailableText = t("notAvailableShort", "N/A");

	const progressValue = optimizationProgress?.total_trials_planned
		? (optimizationProgress.current_trial_number /
				optimizationProgress.total_trials_planned) *
			100
		: run.status.toUpperCase() === "SUCCESS" ||
				run.status.toUpperCase() === "COMPLETED"
			? 100
			: 0;

	// TODO: Consider translating status text if backend provides fixed keys
	const statusText = t(
		`statuses.${run.status.toLowerCase()}`,
		run.status.toUpperCase(),
	);

	return (
		<Card>
			<CardHeader>
				<CardTitle>{t("runOverviewTitle")}</CardTitle>
			</CardHeader>
			<CardContent className="space-y-3">
				<div className="space-y-1">
					<div className="flex justify-between text-sm font-medium">
						<span>
							{t("kpiProgressLabel", {
								current: optimizationProgress?.current_trial_number ?? 0,
								total:
									optimizationProgress?.total_trials_planned ??
									notAvailableText,
							})}
						</span>
						<span>{progressValue.toFixed(1)}%</span>
					</div>
					<Progress value={progressValue} />
				</div>
				<KpiItem label={t("kpiStatus")} value={statusText} />
				{/* Check that results is a dict before accessing */}
				<KpiItem
					label={t("kpiFitnessMetric")}
					value={
						typeof run.results === "object" &&
						run.results &&
						"metric_name" in run.results
							? run.results.metric_name
							: notAvailableText
					}
				/>
				<KpiItem
					label={t("kpiBestValue")}
					value={
						typeof run.results === "object" &&
						run.results &&
						"best_value" in run.results
							? (run.results.best_value?.toFixed(4) ?? notAvailableText)
							: notAvailableText
					}
				/>
				<KpiItem
					label={t("kpiPeriod")}
					value={`${run.request_params?.start_date} to ${run.request_params?.end_date}`}
				/>
			</CardContent>
		</Card>
	);
};
