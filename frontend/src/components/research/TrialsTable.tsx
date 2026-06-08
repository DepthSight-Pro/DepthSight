// src/components/research/TrialsTable.tsx

import type React from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import type { OptimizationTrial } from "@/types/api";

export const TrialsTable: React.FC<{ trials: OptimizationTrial[] }> = ({
	trials,
}) => {
	const { t } = useTranslation("research"); // Initialize useTranslation
	const notAvailableText = t("common:na"); // Use translated 'N/A'

	return (
		<Card className="h-full flex flex-col">
			<CardContent className="p-0 flex-grow">
				<ScrollArea className="h-[500px]">
					<Table>
						<TableHeader className="sticky top-0 bg-card">
							<TableRow>
								<TableHead>{t("trialsTable.colTrial")}</TableHead>
								<TableHead className="text-right">
									{t("trialsTable.colValue")}
								</TableHead>
								<TableHead>{t("trialsTable.colParameters")}</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{trials.length > 0 ? (
								trials.map((trial) => (
									<TableRow key={trial.trial_number}>
										<TableCell>{trial.trial_number}</TableCell>
										<TableCell className="text-right font-mono">
											{trial.value?.toFixed(4) ?? notAvailableText}
										</TableCell>
										<TableCell className="font-mono text-xs">
											{JSON.stringify(trial.params)}
										</TableCell>
									</TableRow>
								))
							) : (
								<TableRow>
									<TableCell colSpan={3} className="h-24 text-center">
										{t("trialsTable.waitingForTrials")}
									</TableCell>
								</TableRow>
							)}
						</TableBody>
					</Table>
				</ScrollArea>
			</CardContent>
		</Card>
	);
};
