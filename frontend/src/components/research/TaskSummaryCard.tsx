// src/components/research/TaskSummaryCard.tsx

import { Copy } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import { Badge } from "@/components/ui/badge";
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
		<p className="text-xs text-white/50">{label}</p>
		<div className="text-sm font-medium text-white/90 leading-tight mt-0.5">{children}</div>
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
		return <Badge variant="outline" className="border-white/10 text-white/80">{t(statusKey, status)}</Badge>;
	};

	const handleCopy = (text: string) => {
		navigator.clipboard.writeText(text);
		toast({
			title: t("taskSummary.toastCopiedTitle"),
			description: t("taskSummary.toastCopiedDescription"),
		});
	};

	return (
		<div className="h-full flex flex-col rounded-2xl border border-white/10 glass shadow-xl p-6">
			<div className="flex justify-between items-start pb-4 border-b border-white/5 mb-4">
				<h3 className="text-lg font-bold text-white tracking-wide">
					{t("backtestViewer.tabSummary")}
				</h3>
				<div>{getTranslatedStatusBadge(run.status)}</div>
			</div>
			<div className="flex-grow flex flex-col space-y-4 min-h-0">
				<InfoItem label={t("taskSummary.taskIdLabel")}>
					<div className="flex items-center gap-1 font-mono text-xs text-cyan">
						<span>{run.task_id}</span>
						<Button
							variant="ghost"
							size="icon"
							className="h-5 w-5 hover:bg-white/10 text-white/60 hover:text-white"
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
						<ScrollArea className="mt-2 flex-grow rounded-xl border border-white/10 bg-white/[0.02] p-1">
							<pre className="text-xs p-3 font-mono whitespace-pre-wrap text-white/80">
								{JSON.stringify(configToDisplay, null, 2)}
							</pre>
						</ScrollArea>
					</InfoItem>
				)}
			</div>
		</div>
	);
};
