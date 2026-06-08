// frontend/src/components/research/BacktestStructuredAnalyticsTab.tsx

import { AlertCircle } from "lucide-react";
import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import type { BacktestRunDetailsData } from "@/types/api";

interface BacktestStructuredAnalyticsTabProps {
	run: BacktestRunDetailsData;
}

type RejectionCounters = Record<
	string,
	number | Record<string, number> | undefined
> & {
	by_filter?: Record<string, number>;
	by_risk_manager_reasons?: Record<string, number>;
};

type AnalyticsReport = {
	event_counters?: {
		foundation_trigger_counts?: Record<string, number>;
		rejections?: RejectionCounters;
		signals_generated_total?: number;
		trades_opened?: number;
	};
	anomalies?: Array<{
		timestamp?: string | number;
		type?: string;
		message?: string;
	}>;
};

export const BacktestStructuredAnalyticsTab: React.FC<
	BacktestStructuredAnalyticsTabProps
> = ({ run }) => {
	const { t } = useTranslation("research");
	const analytics = run.analytics_report_json as
		| AnalyticsReport
		| null
		| undefined;

	const foundationTriggers = useMemo(() => {
		const counts = analytics?.event_counters?.foundation_trigger_counts;
		if (!counts) return [];
		return Object.entries(counts)
			.map(([id, count]) => ({
				id: id.replace("w_", ""),
				count: count as number,
			}))
			.sort((a, b) => b.count - a.count);
	}, [analytics]);

	if (!analytics) {
		return (
			<Alert variant="default">
				<AlertCircle className="h-4 w-4" />
				<AlertTitle>{t("structuredReport.noDataTitle")}</AlertTitle>
				<AlertDescription>
					{t("structuredReport.noDataDescription")}
				</AlertDescription>
			</Alert>
		);
	}

	const { event_counters, anomalies } = analytics;
	const rejections: RejectionCounters = event_counters?.rejections || {};
	const byFilterRejections = rejections.by_filter || {};

	const totalRejections = Object.values(rejections).reduce(
		(acc: number, value) => {
			if (typeof value === "number") {
				return acc + value;
			}
			if (typeof value === "object" && value !== null) {
				return (
					acc +
					Object.values(value).reduce(
						(sum: number, count) => sum + (count as number),
						0,
					)
				);
			}
			return acc;
		},
		0,
	);

	const byRiskManagerRejections = rejections.by_risk_manager_reasons || {};

	const eventCounterRows = [
		{
			event: t("structuredReport.events.signalsGenerated"),
			count: event_counters?.signals_generated_total || 0,
		},
		{
			event: t("structuredReport.events.tradesOpened"),
			count: event_counters?.trades_opened || 0,
		},
		{
			event: t("structuredReport.events.totalRejections"),
			count: totalRejections,
			isBold: true,
		},
		{
			event: t("structuredReport.events.rejectionGlobalRisk"),
			count: (rejections.by_global_risk_limit as number) || 0,
			isSub: true,
		},
		{
			event: t("structuredReport.events.rejectionCooldown"),
			count: (rejections.by_cooldown as number) || 0,
			isSub: true,
		},
		{
			event: t("structuredReport.events.rejectionWeight"),
			count: (rejections.by_weight_threshold as number) || 0,
			isSub: true,
		},
		{
			event: t("structuredReport.events.rejectionCalculation"),
			count: (rejections.by_position_calculation as number) || 0,
			isSub: true,
		},
		{
			event: t("structuredReport.events.rejectionSlippage"),
			count: (rejections.by_slippage_beyond_sl as number) || 0,
			isSub: true,
		},
		{
			event: t("structuredReport.events.rejectionByRiskManager"),
			count: (rejections.by_risk_manager as number) || 0,
			isSub: true,
			subRows: byRiskManagerRejections,
		},
		...Object.entries(byFilterRejections).map(([filterName, count]) => ({
			event: t("structuredReport.events.rejectionByFilter", { filterName }),
			count: count as number,
			isSub: true,
		})),
	];

	return (
		<div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
			<Card>
				<CardHeader>
					<CardTitle>{t("structuredReport.eventCountersTitle")}</CardTitle>
				</CardHeader>
				<CardContent>
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>
									{t("structuredReport.tableHeaders.event")}
								</TableHead>
								<TableHead className="text-right">
									{t("structuredReport.tableHeaders.count")}
								</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{eventCounterRows.map(
								({ event, count, isBold, isSub, subRows }) => (
									<React.Fragment key={event}>
										<TableRow>
											<TableCell
												className={`${isBold ? "font-bold" : ""} ${isSub ? "pl-8" : ""}`}
											>
												{event}
											</TableCell>
											<TableCell className="text-right">{count}</TableCell>
										</TableRow>
										{subRows &&
											Object.entries(subRows).map(([reason, reasonCount]) => (
												<TableRow key={`${event}-${reason}`}>
													<TableCell className="pl-12 text-muted-foreground">
														{reason}
													</TableCell>
													<TableCell className="text-right text-muted-foreground">
														{reasonCount as number}
													</TableCell>
												</TableRow>
											))}
									</React.Fragment>
								),
							)}
						</TableBody>
					</Table>
				</CardContent>
			</Card>

			<Card>
				<CardHeader>
					<CardTitle>{t("structuredReport.foundationTriggersTitle")}</CardTitle>
					<CardDescription>
						{t("structuredReport.foundationTriggersDescription")}
					</CardDescription>
				</CardHeader>
				<CardContent>
					{foundationTriggers.length > 0 ? (
						<Table>
							<TableHeader>
								<TableRow>
									<TableHead>
										{t("structuredReport.tableHeaders.foundation")}
									</TableHead>
									<TableHead className="text-right">
										{t("structuredReport.tableHeaders.triggerCount")}
									</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{foundationTriggers.map(({ id, count }) => (
									<TableRow key={id}>
										<TableCell className="font-medium">{id}</TableCell>
										<TableCell className="text-right">{count}</TableCell>
									</TableRow>
								))}
							</TableBody>
						</Table>
					) : (
						<p className="text-muted-foreground text-sm">
							{t("structuredReport.noFoundationTriggers")}
						</p>
					)}
				</CardContent>
			</Card>

			<Card>
				<CardHeader>
					<CardTitle>{t("structuredReport.anomaliesTitle")}</CardTitle>
				</CardHeader>
				<CardContent>
					{anomalies && anomalies.length > 0 ? (
						<Table>
							<TableHeader>
								<TableRow>
									<TableHead>
										{t("structuredReport.tableHeaders.timestamp")}
									</TableHead>
									<TableHead>
										{t("structuredReport.tableHeaders.type")}
									</TableHead>
									<TableHead>
										{t("structuredReport.tableHeaders.message")}
									</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{(
									anomalies as Array<{
										timestamp?: string | number;
										type?: string;
										message?: string;
									}>
								).map((anomaly, index) => (
									<TableRow key={index}>
										<TableCell>
											{anomaly.timestamp
												? new Date(anomaly.timestamp).toLocaleString()
												: t("common.notAvailable")}
										</TableCell>
										<TableCell>{anomaly.type}</TableCell>
										<TableCell>{anomaly.message}</TableCell>
									</TableRow>
								))}
							</TableBody>
						</Table>
					) : (
						<p className="text-muted-foreground">
							{t("structuredReport.noAnomalies")}
						</p>
					)}
				</CardContent>
			</Card>
		</div>
	);
};

export default BacktestStructuredAnalyticsTab;
