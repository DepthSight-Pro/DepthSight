// src/components/strategy-editor/InfoTooltip.tsx

import { HelpCircle } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { ComponentType } from "./types";

interface InfoTooltipProps {
	blockType: ComponentType;
	className?: string;
}

interface TooltipParam {
	name: string;
	desc: string;
}

interface TooltipData {
	explanation?: string;
	params?: TooltipParam[];
	defaults?: string;
}

export const InfoTooltip: React.FC<InfoTooltipProps> = ({
	blockType,
	className,
}) => {
	const { t } = useTranslation("strategy-editor");
	const translationBlockType =
		blockType === "l2_microstructure" ? "l2_microstructure_check" : blockType;

	const tooltipData = t(`blocks.${translationBlockType}.tooltip`, {
		returnObjects: true,
	}) as unknown as TooltipData;

	// Do not render anything if there is no data for the tooltip
	if (
		!tooltipData ||
		typeof tooltipData !== "object" ||
		!tooltipData.explanation
	) {
		return null;
	}

	return (
		<Popover>
			<PopoverTrigger asChild>
				<Button
					variant="ghost"
					size="icon"
					className={cn(
						"h-6 w-6 text-muted-foreground hover:bg-accent/50 shrink-0",
						className,
					)}
				>
					<HelpCircle className="w-4 h-4" />
				</Button>
			</PopoverTrigger>
			<PopoverContent side="right" align="start" className="w-80 z-50">
				<div className="space-y-4">
					<div>
						<h4 className="font-semibold text-base mb-1">
							{t(`blocks.${translationBlockType}.title`)}
						</h4>
						<p className="text-sm text-muted-foreground">
							{tooltipData.explanation}
						</p>
					</div>

					{tooltipData.params &&
						Array.isArray(tooltipData.params) &&
						tooltipData.params.length > 0 && (
							<div>
								<h5 className="font-semibold text-sm mb-2">Parameters</h5>
								<ul className="space-y-2 text-xs list-disc pl-4">
									{tooltipData.params.map(
										(param: TooltipParam, index: number) => (
											<li key={index}>
												<strong className="font-medium">{param.name}:</strong>
												<span className="text-muted-foreground ml-1">
													{param.desc}
												</span>
											</li>
										),
									)}
								</ul>
							</div>
						)}

					{tooltipData.defaults && (
						<div>
							<h5 className="font-semibold text-sm mb-1">By default</h5>
							<p className="text-xs text-muted-foreground font-mono bg-secondary p-2 rounded-md">
								{tooltipData.defaults}
							</p>
						</div>
					)}
				</div>
			</PopoverContent>
		</Popover>
	);
};
