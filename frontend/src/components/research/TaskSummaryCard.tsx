// src/components/research/TaskSummaryCard.tsx

import { Copy } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BacktestRunDetailsData } from "@/types/api";
import { Button } from "../ui/button";
import { ScrollArea } from "../ui/scroll-area";
import { useToast } from "../ui/use-toast";

interface TaskSummaryCardProps {
	run: BacktestRunDetailsData;
}

const InfoItem: React.FC<{
	label: string;
	children: React.ReactNode;
	className?: string;
}> = ({ label, children, className }) => (
	<div className={className}>
		<p className="text-xs text-muted-foreground">{label}</p>
		<div className="text-sm font-medium leading-tight">{children}</div>
	</div>
);

export const TaskSummaryCard: React.FC<TaskSummaryCardProps> = ({ run }) => {
	const { t } = useTranslation(["research", "common"]); // Initialize useTranslation
	const { toast } = useToast();
	const params = run.parameters_json;
	const config =
		params?.config && typeof params.config === "object"
			? (params.config as unknown as Record<string, unknown>)
			: undefined;
	const notAvailableText = t("common:na");
	const unknownDateText = t("taskSummary.unknownDate", "?");
	const strategyDisplayName = String(
		params?.name ||
			params?.strategy_display_name ||
			config?.name ||
			run.strategy_name ||
			notAvailableText,
	);

	// Looking for a nested config that can be copied to the editor.
	// If it doesn't exist, show the entire parameters object for compatibility.
	const configToDisplay = params?.config || params;

	const getTranslatedStatusBadge = (
		status: BacktestRunDetailsData["status"],
	) => {
		const statusKey = `statuses.${status.toLowerCase()}`;
		return <Badge variant="outline">{t(statusKey, status)}</Badge>;
	};

	const handleCopy = (text: string) => {
		navigator.clipboard.writeText(text);
		toast({
			title: t("taskSummary.toastCopiedTitle"),
			description: t("taskSummary.toastCopiedDescription"),
		});
	};

	return (
		<Card className="h-full flex flex-col">
			<CardHeader className="pb-2">
				<div className="flex justify-between items-start">
					<CardTitle className="text-lg">
						{t("backtestViewer.tabSummary")}
					</CardTitle>
					<div>{getTranslatedStatusBadge(run.status)}</div>
				</div>
			</CardHeader>
			<CardContent className="flex-grow flex flex-col pt-2 space-y-3 min-h-0">
				<InfoItem label={t("taskSummary.taskIdLabel")}>
					<div className="flex items-center gap-1 font-mono text-xs">
						<span>{run.task_id}</span>
						<Button
							variant="ghost"
							size="icon"
							className="h-5 w-5"
							onClick={() => handleCopy(run.task_id)}
						>
							<Copy className="w-3 h-3" />
						</Button>
					</div>
				</InfoItem>
				<div className="grid grid-cols-2 gap-3">
					<InfoItem label={t("launchForm.strategyNameLabel")}>
						{strategyDisplayName}
					</InfoItem>
					<InfoItem label={t("launchForm.symbolLabel")}>
						{run.symbol || notAvailableText}
					</InfoItem>
				</div>
				<InfoItem
					label={t("taskSummary.dateRangeLabel")}
				>{`${run.start_date || unknownDateText} to ${run.end_date || unknownDateText}`}</InfoItem>

				{params && Object.keys(params).length > 0 && (
					<InfoItem
						label={t("launchForm.paramsLabel")}
						className="flex-grow flex flex-col min-h-0"
					>
						<ScrollArea className="mt-1 flex-grow rounded-md border bg-muted/50">
							<pre className="text-xs p-2 font-mono whitespace-pre-wrap">
								{JSON.stringify(configToDisplay, null, 2)}
							</pre>
						</ScrollArea>
					</InfoItem>
				)}
			</CardContent>
		</Card>
	);
};
