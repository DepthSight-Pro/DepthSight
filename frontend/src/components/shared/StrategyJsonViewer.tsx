// src/components/shared/StrategyJsonViewer.tsx

import type React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import type { FoundStrategyData } from "@/types/api";
import { ScrollArea } from "../ui/scroll-area";
import { useToast } from "../ui/use-toast";

interface StrategyJsonViewerProps {
	isOpen: boolean;
	onOpenChange: (isOpen: boolean) => void;
	strategy: FoundStrategyData | null;
}

const StrategyJsonViewer: React.FC<StrategyJsonViewerProps> = ({
	isOpen,
	onOpenChange,
	strategy,
}) => {
	const { t } = useTranslation(["discovery", "common"]);
	const { toast } = useToast();
	if (!strategy) return null;

	// Use strategy_json, as defined in the current FoundStrategyData type
	const strategyJsonString = JSON.stringify(strategy.strategy_json, null, 2);

	const handleCopy = () => {
		navigator.clipboard.writeText(strategyJsonString);
		toast({
			title: t("runViewer.toastCopied"),
			description: t("runViewer.jsonViewerDesc", {
				rank: strategy.rank,
				fitnessScore: strategy.fitness_score.toFixed(4),
			}),
		});
	};

	return (
		<Dialog open={isOpen} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[600px]">
				<DialogHeader>
					<DialogTitle>{t("runViewer.jsonViewerTitle")}</DialogTitle>
					<DialogDescription>
						{t("runViewer.jsonViewerDesc", {
							rank: strategy.rank,
							fitnessScore: strategy.fitness_score.toFixed(4),
						})}
					</DialogDescription>
				</DialogHeader>
				<ScrollArea className="max-h-[60vh] my-4">
					<div className="rounded-md bg-muted p-4">
						<pre className="text-sm whitespace-pre-wrap break-all">
							{strategyJsonString}
						</pre>
					</div>
				</ScrollArea>
				<DialogFooter>
					<Button variant="outline" onClick={handleCopy}>
						{t("runViewer.copyButton")}
					</Button>
					<Button onClick={() => onOpenChange(false)}>
						{t("common:close")}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
};

export default StrategyJsonViewer;
