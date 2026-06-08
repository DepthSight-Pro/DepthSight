// src/components/strategy-editor/ModifyStopLossBlock.tsx

import { useDraggable } from "@dnd-kit/core";
import { GripVertical, Move, Target, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import { type DynamicParam, DynamicValueInput } from "./DynamicValueInput";
import type {
	ModifyStopLossBlock as ModifyStopLossBlockType,
	ModifyTakeProfitBlock as ModifyTakeProfitBlockType,
} from "./types";

interface ModifyStopLossBlockProps {
	block: ModifyStopLossBlockType | ModifyTakeProfitBlockType;
}

export const ModifyStopLossBlockComponent: React.FC<
	ModifyStopLossBlockProps
> = ({ block }) => {
	const { t } = useTranslation("strategy-editor");
	const { removeBlock, updateBlockParams } = useStrategyEditorStore();

	const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
		id: block.id,
		data: { isPaletteItem: false, ...block },
	});

	if (isDragging) {
		return (
			<div
				ref={setNodeRef}
				className="h-12 rounded-lg bg-accent opacity-70 border border-dashed border-primary"
			/>
		);
	}

	const p = block.params || {};
	const isTakeProfitBlock = block.type === "modify_take_profit";
	const valueKey = isTakeProfitBlock ? "new_tp_price" : "new_sl_price";
	const titleKey = isTakeProfitBlock
		? "blocks.modify_take_profit.title"
		: "blocks.modify_stop_loss.title";
	const fieldLabelKey = isTakeProfitBlock
		? "blocks.modify_take_profit.new_tp_price"
		: "blocks.modify_stop_loss.new_sl_price";
	const inputValue = isTakeProfitBlock
		? (p as ModifyTakeProfitBlockType["params"]).new_tp_price
		: (p as ModifyStopLossBlockType["params"]).new_sl_price;

	const updateParams = (
		newParams: Partial<
			ModifyTakeProfitBlockType["params"] & ModifyStopLossBlockType["params"]
		>,
	) => {
		updateBlockParams(block.id, { ...p, ...newParams });
	};

	return (
		<div ref={setNodeRef}>
			<Card className="p-2 group/block">
				<div className="flex items-center justify-between">
					<div className="flex items-center gap-2 flex-grow">
						<div
							{...listeners}
							{...attributes}
							className="cursor-grab touch-none p-1"
						>
							<GripVertical className="w-5 h-5 text-muted-foreground" />
						</div>
						{isTakeProfitBlock ? (
							<Target className="w-4 h-4 text-muted-foreground" />
						) : (
							<Move className="w-4 h-4 text-muted-foreground" />
						)}
						<span>{t(titleKey)}</span>
						<div className="flex items-center gap-2">
							<span>{t(fieldLabelKey)}</span>
							<div className="w-48">
								<DynamicValueInput
									value={inputValue}
									onChange={(v: DynamicParam) =>
										updateParams({ [valueKey]: v })
									}
								/>
							</div>
						</div>
					</div>
					<Button
						variant="ghost"
						size="icon"
						className="h-7 w-7 opacity-50 group-hover/block:opacity-100"
						onClick={() => removeBlock(block.id)}
					>
						<X className="w-4 h-4" />
					</Button>
				</div>
			</Card>
		</div>
	);
};
