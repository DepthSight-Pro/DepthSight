// src/components/strategy-editor/ManagementBlock.tsx

import { useDraggable, useDroppable } from "@dnd-kit/core";
import {
	AlertTriangle,
	Anchor,
	Calculator,
	GripVertical,
	Layers,
	Sigma,
	TrendingUp,
	X,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import { ConditionBlock as ConditionBlockComponent } from "./ConditionBlock";
import { DCACalculator } from "./calculators/DCACalculator";
import { GridCalculator } from "./calculators/GridCalculator";
import { type DynamicParam, DynamicValueInput } from "./DynamicValueInput";
import { InfoTooltip } from "./InfoTooltip";
import type { ManagementBlock as BlockType } from "./types";

interface ManagementBlockProps {
	block: BlockType;
}

interface ParamSelectProps {
	value?: string;
	onChange: (value: string) => void;
	items: { value: string; label: string }[];
	placeholder?: string;
	className?: string;
}

const ParamSelect: React.FC<ParamSelectProps> = ({
	value,
	onChange,
	items,
	placeholder,
	className,
}) => (
	<Select value={value} onValueChange={onChange}>
		<SelectTrigger className={cn("h-8", className)}>
			<SelectValue placeholder={placeholder} />
		</SelectTrigger>
		<SelectContent>
			{items.map((item) => (
				<SelectItem key={item.value} value={item.value}>
					{item.label}
				</SelectItem>
			))}
		</SelectContent>
	</Select>
);

export const ManagementBlockComponent: React.FC<ManagementBlockProps> = ({
	block,
}) => {
	const { t } = useTranslation("strategy-editor");
	const { removeBlock, updateBlockParams } = useStrategyEditorStore();
	const [isCalcOpen, setIsCalcOpen] = useState(false);

	const p = block.params || {};
	const isContainer =
		block.type === "conditional_exit" ||
		(block.type === "dca_management" && p.step_type === "custom_condition");

	const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
		id: block.id,
		data: { isPaletteItem: false, category: "management", ...block },
	});

	const { setNodeRef: dropRef, isOver } = useDroppable({
		id: `${block.id}-conditions-drop-zone`,
		data: {
			isContainer,
			parentId: block.id,
			accepts: ["foundation", "indicator", "logic"],
		},
	});

	const icons: Record<string, React.ReactNode> = {
		trailing_stop: <TrendingUp className="w-4 h-4 text-muted-foreground" />,
		move_to_breakeven: <Anchor className="w-4 h-4 text-muted-foreground" />,
		conditional_exit: (
			<AlertTriangle className="w-4 h-4 text-muted-foreground" />
		),
		close_position: <AlertTriangle className="w-4 h-4 text-muted-foreground" />,
		dca_management: <Sigma className="w-4 h-4 text-muted-foreground" />,
		grid_management: <Layers className="w-4 h-4 text-muted-foreground" />,
	};

	const updateParams = (newParams: Record<string, unknown>) =>
		updateBlockParams(block.id, newParams);

	if (isDragging) {
		return (
			<div
				ref={setNodeRef}
				className="h-12 rounded-lg bg-accent opacity-70 border border-dashed border-primary"
			/>
		);
	}

	return (
		<div ref={setNodeRef}>
			<Card className="p-2 group/block relative">
				<div className="flex items-center justify-between">
					<div className="flex items-center gap-2 flex-grow min-w-0">
						<div
							{...listeners}
							{...attributes}
							className="cursor-grab touch-none p-1 shrink-0"
						>
							<GripVertical className="w-5 h-5 text-muted-foreground" />
						</div>

						<div className="flex items-center gap-2 flex-wrap min-w-0 flex-grow">
							{icons[block.type]}

							{block.type === "trailing_stop" && (
								<>
									<span>{t("blocks.trailing_stop.text_1")}</span>
									<ParamSelect
										value={p.type}
										onChange={(value: string) => updateParams({ type: value })}
										items={[
											{
												value: "ATR",
												label: t("blocks.trailing_stop.options.atr"),
											},
											{
												value: "Percentage",
												label: t("blocks.trailing_stop.options.percent"),
											},
										]}
										className="w-28"
									/>
									<span>{t("blocks.trailing_stop.text_2")}</span>
									<div className="w-32">
										<DynamicValueInput
											value={p.value}
											onChange={(value: DynamicParam) =>
												updateParams({ value })
											}
										/>
									</div>
									<label className="flex items-center gap-1.5 ml-2 cursor-pointer">
										<input
											type="checkbox"
											checked={p.mode === "exchange"}
											onChange={(event) =>
												updateParams({
													mode: event.target.checked ? "exchange" : "local",
												})
											}
											className="w-4 h-4 rounded border-gray-300"
										/>
										<span className="text-sm text-muted-foreground">
											{t("blocks.trailing_stop.exchange_mode")}
										</span>
									</label>
								</>
							)}

							{block.type === "move_to_breakeven" && (
								<>
									<span>{t("blocks.move_to_breakeven.text_1")}</span>
									<div className="w-32">
										<DynamicValueInput
											value={p.target_value}
											onChange={(value: DynamicParam) =>
												updateParams({ target_value: value })
											}
										/>
									</div>
									<ParamSelect
										value={p.target_type}
										onChange={(value: string) =>
											updateParams({ target_type: value })
										}
										items={[
											{
												value: "atr_multiplier",
												label: t(
													"blocks.move_to_breakeven.options.atr_multiplier",
												),
											},
											{
												value: "percent_from_price",
												label: t(
													"blocks.move_to_breakeven.options.percent_from_price",
												),
											},
											{
												value: "rr_multiplier",
												label: t(
													"blocks.move_to_breakeven.options.rr_multiplier",
												),
											},
										]}
										className="w-32"
									/>
								</>
							)}

							{block.type === "conditional_exit" && (
								<span>{t("blocks.conditional_exit.text_1")}</span>
							)}
							{block.type === "close_position" && (
								<span>{t("blocks.close_position.text_1")}</span>
							)}

							{block.type === "dca_management" && (
								<div className="flex items-center gap-2 flex-wrap flex-grow">
									<span className="font-bold">DCA</span>
									<div className="flex items-center gap-1.5 border-l pl-2">
										<span className="text-[11px] text-muted-foreground font-medium whitespace-nowrap">
											{t("blocks.dca_management.so")}
										</span>
										<Input
											type="number"
											value={p.max_safety_orders || 5}
											onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
												updateParams({
													max_safety_orders: parseInt(e.target.value, 10),
												})
											}
											className="w-14 h-8 bg-background text-center"
										/>
									</div>
									<div className="flex items-center gap-1.5 border-l pl-2">
										<span className="text-[11px] text-muted-foreground font-medium whitespace-nowrap">
											{t("blocks.dca_management.mult")}
										</span>
										<Input
											type="number"
											step="0.1"
											value={p.volume_multiplier || 2.0}
											onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
												updateParams({
													volume_multiplier: parseFloat(e.target.value),
												})
											}
											className="w-16 h-8 bg-background text-center"
										/>
									</div>
									<div className="flex items-center gap-1.5 border-l pl-2">
										<ParamSelect
											value={p.step_type || "percentage"}
											onChange={(v: string) => updateParams({ step_type: v })}
											items={[
												{ value: "percentage", label: "%" },
												{ value: "atr", label: "ATR" },
												{ value: "custom_condition", label: "Custom" },
											]}
											className="w-20"
										/>
										{p.step_type !== "custom_condition" && (
											<div className="flex items-center gap-1.5 ml-1">
												<div className="w-24">
													<DynamicValueInput
														value={p.step_value}
														onChange={(v: DynamicParam) =>
															updateParams({ step_value: v })
														}
													/>
												</div>
												<span className="text-[11px] text-muted-foreground font-medium whitespace-nowrap ml-1">
													{t("blocks.dca_management.step_mult")}
												</span>
												<Input
													type="number"
													step="0.1"
													value={p.step_multiplier || 1.0}
													onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
														updateParams({
															step_multiplier: parseFloat(e.target.value),
														})
													}
													className="w-16 h-8 bg-background text-center"
												/>
											</div>
										)}
									</div>

									<Button
										variant="ghost"
										size="icon"
										className={cn(
											"h-7 w-7 transition-colors ml-auto",
											isCalcOpen
												? "text-primary bg-primary/10"
												: "text-muted-foreground",
										)}
										onClick={() => setIsCalcOpen(!isCalcOpen)}
									>
										<Calculator className="w-4 h-4" />
									</Button>
								</div>
							)}

							{block.type === "grid_management" && (
								<div className="flex items-center gap-2 flex-wrap flex-grow">
									<span className="font-bold">GRID</span>
									<div className="flex items-center gap-1.5 border-l pl-2">
										<span className="text-[11px] text-muted-foreground font-medium whitespace-nowrap">
											{t("blocks.grid_management.levels")}
										</span>
										<Input
											type="number"
											value={p.grid_levels || 10}
											onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
												updateParams({
													grid_levels: parseInt(e.target.value, 10),
												})
											}
											className="w-16 h-8 bg-background text-center"
										/>
									</div>
									<div className="flex items-center gap-1.5 border-l pl-2">
										<ParamSelect
											value={p.range_type || "percentage"}
											onChange={(v: string) => updateParams({ range_type: v })}
											items={[
												{ value: "percentage", label: "%" },
												{ value: "atr", label: "ATR" },
												{ value: "fixed_prices", label: "Price" },
											]}
											className="w-20"
										/>
									</div>
									<div className="flex items-center gap-1.5 border-l pl-2">
										<span className="text-[10px] text-muted-foreground uppercase whitespace-nowrap">
											{t("blocks.grid_management.upper")}
										</span>
										<div className="w-24">
											<DynamicValueInput
												value={p.upper_bound}
												onChange={(v: DynamicParam) =>
													updateParams({ upper_bound: v })
												}
											/>
										</div>
										<span className="text-[10px] text-muted-foreground uppercase whitespace-nowrap">
											{t("blocks.grid_management.lower")}
										</span>
										<div className="w-24">
											<DynamicValueInput
												value={p.lower_bound}
												onChange={(v: DynamicParam) =>
													updateParams({ lower_bound: v })
												}
											/>
										</div>
									</div>

									<Button
										variant="ghost"
										size="icon"
										className={cn(
											"h-7 w-7 transition-colors ml-auto",
											isCalcOpen
												? "text-primary bg-primary/10"
												: "text-muted-foreground",
										)}
										onClick={() => setIsCalcOpen(!isCalcOpen)}
									>
										<Calculator className="w-4 h-4" />
									</Button>
								</div>
							)}
						</div>
					</div>

					<div className="flex items-center shrink-0">
						<InfoTooltip blockType={block.type} />
						<Button
							variant="ghost"
							size="icon"
							className="h-7 w-7 opacity-50 hover:opacity-100"
							onClick={() => removeBlock(block.id)}
						>
							<X className="w-4 h-4" />
						</Button>
					</div>
				</div>

				{/* Expandable Calculator Area */}
				{block.type === "dca_management" &&
					(p.step_type === "percentage" || p.step_type === "atr") && (
						<DCACalculator
							maxSafetyOrders={p.max_safety_orders || 5}
							volumeMultiplier={p.volume_multiplier || 2.0}
							stepMultiplier={p.step_multiplier || 1.0}
							stepValue={p.step_value}
							stepType={p.step_type || "percentage"}
							isOpen={isCalcOpen}
						/>
					)}
				{block.type === "grid_management" && (
					<GridCalculator
						levels={p.grid_levels || 10}
						rangeType={p.range_type || "percentage"}
						upperBoundValue={p.upper_bound}
						lowerBoundValue={p.lower_bound}
						isOpen={isCalcOpen}
					/>
				)}

				{isContainer && (
					<div className="pl-8 pt-2">
						<div
							ref={dropRef}
							className={cn(
								"p-2 min-h-[50px] space-y-2 rounded-md border-2 border-dashed border-border transition-colors",
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
				)}
			</Card>
		</div>
	);
};
