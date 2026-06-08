// src/components/models/DatasetDetailModal.tsx

import { Copy } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/use-toast";
import type { DatasetRunResponse } from "@/types/api";

interface DatasetDetailModalProps {
	isOpen: boolean;
	onClose: () => void;
	dataset: DatasetRunResponse | null;
}

const InfoItem: React.FC<{
	label: string;
	children: React.ReactNode;
	className?: string;
}> = ({ label, children, className }) => (
	<div className={className}>
		<p className="text-sm text-muted-foreground">{label}</p>
		<div className="text-base font-medium leading-tight">{children}</div>
	</div>
);

export const DatasetDetailModal: React.FC<DatasetDetailModalProps> = ({
	isOpen,
	onClose,
	dataset,
}) => {
	const { t } = useTranslation("modelLab");
	const { toast } = useToast();

	if (!dataset) return null;

	const handleCopy = (text: string) => {
		navigator.clipboard.writeText(text);
		toast({ title: "Copied to clipboard" });
	};

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent className="sm:max-w-2xl">
				<DialogHeader>
					<DialogTitle>
						{t("datasetModal.title", { name: dataset.name })}
					</DialogTitle>
					<DialogDescription>{t("datasetModal.description")}</DialogDescription>
				</DialogHeader>
				<div className="py-4 space-y-4">
					<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
						<InfoItem label={t("datasetModal.runIdLabel")}>
							<div className="flex items-center gap-1 font-mono text-sm">
								<span>{dataset.id}</span>
								<Button
									variant="ghost"
									size="icon"
									className="h-5 w-5"
									onClick={() => handleCopy(dataset.id)}
								>
									<Copy className="w-3 h-3" />
								</Button>
							</div>
						</InfoItem>
						<InfoItem label={t("tasksTable.colStatus")}>
							<Badge
								variant={
									dataset.status === "COMPLETED" ? "default" : "secondary"
								}
								className={dataset.status === "COMPLETED" ? "bg-green-500" : ""}
							>
								{t(`statuses.${dataset.status}`, dataset.status)}
							</Badge>
						</InfoItem>
					</div>
					<InfoItem label={t("datasetModal.filePathLabel")}>
						<div className="flex items-center gap-1 font-mono text-sm break-all">
							<span>{dataset.file_path || "N/A"}</span>
							{dataset.file_path && (
								<Button
									variant="ghost"
									size="icon"
									className="h-5 w-5 flex-shrink-0"
									onClick={() => handleCopy(dataset.file_path!)}
								>
									<Copy className="w-3 h-3" />
								</Button>
							)}
						</div>
					</InfoItem>
					<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
						<InfoItem label={t("launchForm.symbolsLabel")}>
							{dataset.parameters_json.symbols.join(", ")}
						</InfoItem>
						<InfoItem
							label={t("launchForm.dateRangeLabel")}
						>{`${dataset.parameters_json.start_date} - ${dataset.parameters_json.end_date}`}</InfoItem>
					</div>
					<InfoItem label={t("launchForm.featureTypesLabel")}>
						<div className="flex flex-wrap gap-2">
							{dataset.parameters_json.feature_types.map((ft) => (
								<Badge key={ft} variant="outline">
									{ft}
								</Badge>
							))}
						</div>
					</InfoItem>
					<InfoItem label={t("launchForm.targetVariableLabel")}>
						{dataset.parameters_json.target_variable}
					</InfoItem>
				</div>
				<DialogFooter>
					<Button onClick={onClose}>Close</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
};
