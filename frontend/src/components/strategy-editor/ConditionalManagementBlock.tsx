// src/components/strategy-editor/ConditionalManagementBlock.tsx

import { useDraggable, useDroppable } from "@dnd-kit/core";
import {
	AlertTriangle,
	Anchor,
	GripVertical,
	Move,
	Plus,
	Settings2,
	Target,
	TrendingUp,
	X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import { ConditionBlock as ConditionBlockComponent } from "./ConditionBlock";
import { ManagementBlockComponent } from "./ManagementBlock";
import { ModifyStopLossBlockComponent } from "./ModifyStopLossBlock";
import type {
	ConditionalManagementBlock as BlockType,
	ComponentType,
	ConditionBlock,
	ManagementBlock,
	ModifyStopLossBlock,
	ModifyTakeProfitBlock,
} from "./types";

interface ConditionalManagementBlockProps {
	block: BlockType;
}

const QUICK_ACTIONS: Array<{ type: ComponentType; icon: React.ReactNode }> = [
	{ type: "modify_stop_loss", icon: <Move className="w-3.5 h-3.5" /> },
	{ type: "modify_take_profit", icon: <Target className="w-3.5 h-3.5" /> },
	{ type: "trailing_stop", icon: <TrendingUp className="w-3.5 h-3.5" /> },
	{ type: "move_to_breakeven", icon: <Anchor className="w-3.5 h-3.5" /> },
	{ type: "close_position", icon: <AlertTriangle className="w-3.5 h-3.5" /> },
];

const renderThenAction = (block: ManagementBlock) => {
	switch (block.type) {
		case "modify_stop_loss":
		case "modify_take_profit":
			return (
				<ModifyStopLossBlockComponent
					key={block.id}
					block={block as ModifyStopLossBlock | ModifyTakeProfitBlock}
				/>
			);
		case "close_position":
		case "trailing_stop":
		case "move_to_breakeven":
			return <ManagementBlockComponent key={block.id} block={block} />;
		default:
			return <ManagementBlockComponent key={block.id} block={block} />;
	}
};

export const ConditionalManagementBlockComponent: React.FC<
	ConditionalManagementBlockProps
> = ({ block }) => {
	const { t } = useTranslation("strategy-editor");
	const { removeBlock, addActionToConditionalManagementBlock } =
		useStrategyEditorStore();

	const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
		id: block.id,
		data: { isPaletteItem: false, category: "management", ...block },
	});

	const { setNodeRef: ifDropRef, isOver: isOverIf } = useDroppable({
		id: `${block.id}-if-drop-zone`,
		data: {
			isContainer: true,
			parentId: block.id,
			accepts: ["foundation", "indicator", "logic"],
		},
	});

	const { setNodeRef: thenDropRef, isOver: isOverThen } = useDroppable({
		id: `${block.id}-then-drop-zone`,
		data: {
			isContainer: true,
			parentId: block.id,
			accepts: ["management"],
		},
	});

	if (isDragging) {
		return (
			<div
				ref={setNodeRef}
				className="h-24 rounded-lg bg-accent opacity-70 border border-dashed border-primary"
			/>
		);
	}

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
						<Settings2 className="w-4 h-4 text-muted-foreground" />
						<span>{t("blocks.conditional_management.title")}</span>
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
				<div className="pl-8 pt-2 grid grid-cols-[auto,1fr] gap-2 items-start">
					<div className="font-bold text-sm text-muted-foreground self-center">
						{t("blocks.conditional_management.if")}
					</div>
					<div
						ref={ifDropRef}
						className={cn(
							"p-2 min-h-[50px] space-y-2 rounded-md border-2 border-dashed border-border",
							isOverIf && "border-primary bg-accent",
						)}
					>
						{block.if_conditions?.children &&
						block.if_conditions.children.length > 0 ? (
							block.if_conditions.children.map((child: ConditionBlock) => (
								<ConditionBlockComponent key={child.id} block={child} />
							))
						) : (
							<p className="text-xs text-center text-muted-foreground py-2">
								{t("canvas.dropZone.conditions")}
							</p>
						)}
					</div>

					<div className="font-bold text-sm text-muted-foreground self-center">
						{t("blocks.conditional_management.then")}
					</div>
					<div
						ref={thenDropRef}
						className={cn(
							"p-2 min-h-[50px] space-y-2 rounded-md border-2 border-dashed border-border",
							isOverThen && "border-primary bg-accent",
						)}
					>
						{block.then_actions && block.then_actions.length > 0 ? (
							block.then_actions.map((child: ManagementBlock) =>
								renderThenAction(child),
							)
						) : (
							<p className="text-xs text-center text-muted-foreground py-2">
								{t("canvas.dropZone.actions")}
							</p>
						)}
						<div className="pt-2 border-t border-border/60">
							<div className="flex items-center gap-2 mb-2 text-xs font-medium text-muted-foreground">
								<Plus className="w-3.5 h-3.5" />
								<span>{t("blocks.conditional_management.quick_actions")}</span>
							</div>
							<div className="flex flex-wrap gap-2">
								{QUICK_ACTIONS.map((action) => (
									<Button
										key={action.type}
										type="button"
										variant="outline"
										size="sm"
										className="h-8 gap-1.5"
										onClick={() =>
											addActionToConditionalManagementBlock(
												block.id,
												action.type,
											)
										}
									>
										{action.icon}
										<span>{t(`blocks.${action.type}.title`)}</span>
									</Button>
								))}
							</div>
						</div>
					</div>
				</div>
			</Card>
		</div>
	);
};
