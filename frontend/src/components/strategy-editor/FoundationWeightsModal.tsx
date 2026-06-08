// src/components/strategy-editor/FoundationWeightsModal.tsx

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import {
	extractFoundationGroups,
	getFoundationWeightValue,
} from "./FoundationWeightsHelper";

interface FoundationWeightsModalProps {
	isOpen: boolean;
	onClose: () => void;
}

export const FoundationWeightsModal: React.FC<FoundationWeightsModalProps> = ({
	isOpen,
	onClose,
}) => {
	const { t } = useTranslation();
	const {
		foundationWeights,
		updateFoundationWeight,
		saveFoundationWeights,
		entryConditions,
	} = useStrategyEditorStore();

	const activeFoundationGroups = useMemo(() => {
		// Only extract foundation groups if entryConditions is an 'OR' block
		// as weights are only applicable in an 'OR' context
		if (entryConditions.type === "OR") {
			const groups = extractFoundationGroups(entryConditions, t);
			console.log("Active foundation groups:", groups);
			console.log("Current foundation weights:", foundationWeights);
			return groups;
		}
		return [];
	}, [entryConditions, t, foundationWeights]);

	const handleSave = () => {
		saveFoundationWeights();
		onClose();
	};

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent className="sm:max-w-[425px]">
				<DialogHeader>
					<DialogTitle>
						{t("strategy-editor:configPanel.foundationWeightsTitle")}
					</DialogTitle>
				</DialogHeader>
				<ScrollArea className="h-72 pr-6">
					<div className="grid gap-4 py-4">
						{activeFoundationGroups.length === 0 && (
							<p className="text-center text-muted-foreground">
								{t("strategy-editor:configPanel.noFoundationsAdded")}
							</p>
						)}
						{activeFoundationGroups.map((group) => {
							const inputId = `foundation-weight-${group.id}`;
							return (
								<div
									key={group.id}
									className="grid grid-cols-4 items-center gap-4"
								>
									<label htmlFor={inputId} className="text-right col-span-2">
										{group.displayName}
										{` (ID: ${group.id.substring(0, 8)}...)`}
									</label>
									<Input
										id={inputId}
										type="number"
										value={
											getFoundationWeightValue(foundationWeights, group.id) ||
											""
										}
										onChange={(e) =>
											updateFoundationWeight(
												group.id,
												parseFloat(e.target.value) || 0,
											)
										}
										className="col-span-2"
									/>
								</div>
							);
						})}
					</div>
				</ScrollArea>
				<DialogFooter>
					<Button variant="outline" onClick={onClose}>
						{t("cancel")}
					</Button>
					<Button onClick={handleSave}>{t("save")}</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
};
