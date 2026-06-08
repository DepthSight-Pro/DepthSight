// src/components/strategy-editor/ScaleInBlock.tsx

import { useDraggable, useDroppable } from "@dnd-kit/core";
import { GripVertical, TrendingUp, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import { ConditionBlock as ConditionBlockComponent } from "./ConditionBlock";
import type { ScaleInBlock as BlockType } from "./types";

interface ScaleInBlockProps {
	block: BlockType;
}

export const ScaleInBlockComponent: React.FC<ScaleInBlockProps> = ({
	block,
}) => {
	const { t } = useTranslation("strategy-editor");
	const { removeBlock, updateBlockParams } = useStrategyEditorStore();

	const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
		id: block.id,
		data: { isPaletteItem: false, category: "management", ...block },
	});

	// --- Activate the drop zone ---
	const { setNodeRef: dropRef, isOver } = useDroppable({
		id: `${block.id}-conditions-drop-zone`,
		data: {
			isContainer: true,
			parentId: block.id,
			accepts: ["foundation", "indicator", "logic"], // Explicitly specify what we accept
		},
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

	const updateParams = (newParams: Partial<BlockType["params"]>) => {
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
						<TrendingUp className="w-4 h-4 text-muted-foreground" />
						<span>{t("blocks.scale_in.title")}</span>
						<div className="flex items-center gap-2">
							<span>{t("blocks.scale_in.add_size_pct_of_initial_risk")}</span>
							<Input
								type="number"
								value={p.add_size_pct_of_initial_risk || 100}
								onChange={(e) =>
									updateParams({
										add_size_pct_of_initial_risk: parseInt(e.target.value, 10),
									})
								}
								className="w-24 h-8"
							/>
							<span>{t("blocks.scale_in.max_entries")}</span>
							<Input
								type="number"
								value={p.max_entries || 3}
								onChange={(e) =>
									updateParams({ max_entries: parseInt(e.target.value, 10) })
								}
								className="w-24 h-8"
							/>
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
				{/* --- Render nested blocks --- */}
				<div className="pl-8 pt-2">
					<div
						ref={dropRef}
						className={cn(
							"p-2 min-h-[50px] space-y-2 rounded-md border-2 border-dashed border-border",
							isOver && "border-primary bg-accent",
						)}
					>
						{block.children && block.children.length > 0 ? (
							block.children.map((child) => (
								<ConditionBlockComponent key={child.id} block={child} />
							))
						) : (
							<p className="text-xs text-center text-muted-foreground py-2">
								{t("canvas.dropZone.conditions")}
							</p>
						)}
					</div>
				</div>
			</Card>
		</div>
	);
};
