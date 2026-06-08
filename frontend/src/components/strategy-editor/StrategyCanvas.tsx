// src/components/strategy-editor/StrategyCanvas.tsx

import { useDndContext, useDroppable } from "@dnd-kit/core";
import { Cpu, Globe, LogIn, Rocket, Shield, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/use-toast";
import { useStrategyConstraints } from "@/hooks/useStrategyConstraints";
import { useGenerateStrategyFromText } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import type { StrategyConfigData } from "@/types/api";
import { AICoPilot } from "./AICoPilot";
import { ConditionalManagementBlockComponent } from "./ConditionalManagementBlock";
import { ConditionBlock } from "./ConditionBlock";
import { InitializationEditor } from "./InitializationEditor";
import { ManagementBlockComponent } from "./ManagementBlock";
import { ModifyStopLossBlockComponent } from "./ModifyStopLossBlock";
import { ScaleInBlockComponent } from "./ScaleInBlock";
import type {
	ComponentCategory,
	ConditionalManagementBlock,
	ConditionBlock as ConditionBlockType,
	ModifyStopLossBlock,
	ModifyTakeProfitBlock,
	ScaleInBlock,
} from "./types";
import "./canvas-animations.css";

// Animated wrapper for blocks during appear animation
const AnimatedBlock = ({
	children,
	index,
	epoch,
	zone,
}: {
	children: React.ReactNode;
	index: number;
	epoch: number;
	zone: "filters" | "entry" | "management";
}) => {
	const ref = useRef<HTMLDivElement>(null);
	const [prevEpoch, setPrevEpoch] = useState(epoch);
	if (epoch !== prevEpoch) {
		setPrevEpoch(epoch);
	}
	const shouldAnimate = epoch > 0 && epoch !== prevEpoch;

	useEffect(() => {
		if (shouldAnimate && ref.current) {
			// Reset animation by triggering reflow
			ref.current.classList.remove("block-appear", `block-appear--${zone}`);
			void ref.current.offsetWidth; // force reflow
			ref.current.classList.add("block-appear", `block-appear--${zone}`);

			// Cleanup will-change after animation ends
			const el = ref.current;
			const handleEnd = () => {
				el.classList.add("block-appear-done");
				el.removeEventListener("animationend", handleEnd);
			};
			el.addEventListener("animationend", handleEnd);
		}
	}, [shouldAnimate, zone]);

	// Cap index to avoid very long waits
	const cappedIndex = Math.min(index, 15);

	return (
		<div
			ref={ref}
			style={{ "--appear-index": cappedIndex } as React.CSSProperties}
			className={
				shouldAnimate ? cn("block-appear", `block-appear--${zone}`) : undefined
			}
		>
			{children}
		</div>
	);
};

export const StrategyCanvas = () => {
	const { t, i18n } = useTranslation("strategy-editor");
	const storeState = useStrategyEditorStore();
	const {
		filters,
		entryTrigger,
		entryConditions,
		positionManagement,
		setTrigger,
		loadStrategy,
	} = storeState;
	const { active } = useDndContext();
	const { toast } = useToast();
	const canvasRef = useRef<HTMLDivElement>(null);

	const animationEpoch = useStrategyEditorStore(
		(state) => state.animationEpoch,
	);
	const isClearing = useStrategyEditorStore((state) => state.isClearing);

	const { mutate: generateStrategy, isPending: isGenerating } =
		useGenerateStrategyFromText();

	const isCanvasEmpty = useMemo(
		() =>
			filters.children?.length === 0 &&
			entryConditions.children?.length === 0 &&
			positionManagement.length === 0,
		[filters, entryConditions, positionManagement],
	);

	const { isStrategyProOnly: isProStrategy } =
		useStrategyConstraints(storeState);

	const activeCategory = active?.data?.current?.category as
		| ComponentCategory
		| undefined;
	const isDragging = !!active;

	const isFiltersTarget = useMemo(
		() =>
			isDragging &&
			activeCategory &&
			["filter", "logic"].includes(activeCategory),
		[isDragging, activeCategory],
	);
	const isEntryTarget = useMemo(
		() =>
			isDragging &&
			activeCategory &&
			["foundation", "indicator", "logic"].includes(activeCategory),
		[isDragging, activeCategory],
	);
	const isManagementTarget = useMemo(
		() =>
			isDragging && activeCategory && ["management"].includes(activeCategory),
		[isDragging, activeCategory],
	);

	// Handle clearing animation end → trigger actual reset
	useEffect(() => {
		if (!isClearing || !canvasRef.current) return;

		const timer = setTimeout(() => {
			// After the CSS animation duration, perform the actual reset
			useStrategyEditorStore.getState().reset();
		}, 350); // 250ms animation + 100ms buffer

		return () => clearTimeout(timer);
	}, [isClearing]);

	const { isOver: isOverFilters, setNodeRef: filtersDropRef } = useDroppable({
		id: "filters-drop-zone",
		data: { stateKey: "filters" },
	});
	const { isOver: isOverEntry, setNodeRef: entryDropRef } = useDroppable({
		id: "entry-conditions-drop-zone",
		data: { stateKey: "entryConditions" },
	});
	const { isOver: isOverManagement, setNodeRef: managementDropRef } =
		useDroppable({
			id: "management-drop-zone",
			data: { stateKey: "management" },
		});

	const getStrategyPayload = (): StrategyConfigData =>
		useStrategyEditorStore.getState().toJson();
	const onTickLabel = i18n.language.startsWith("ru")
		? "On every tick"
		: "On Every Tick";

	const handleAiSubmit = (text_prompt: string, modify: boolean = false) => {
		const current_config_json = modify ? getStrategyPayload() : undefined;
		const user_tier = storeState.userTier;

		generateStrategy(
			{ text_prompt, current_config_json, user_tier },
			{
				onSuccess: (data) => {
					loadStrategy(data);
					toast({
						title: t("common:successTitle"),
						description: t("ai.successToast"),
					});
					if (
						data.unsupported_features &&
						data.unsupported_features.length > 0
					) {
						toast({
							variant: "default",
							title: t("ai.unsupportedTitle"),
							description: data.unsupported_features.join(", "),
						});
					}
				},
				onError: (error) => {
					toast({
						variant: "destructive",
						title: t("common:errorTitle"),
						description: error.message,
					});
				},
			},
		);
	};

	return (
		<div
			ref={canvasRef}
			className={cn(
				"relative h-full overflow-y-auto p-4 space-y-6 bg-background",
				isClearing && "canvas-clearing",
			)}
		>
			{/* Fidelity HUD */}
			{!isCanvasEmpty && (
				<div className="sticky top-0 z-10 flex justify-end mb-4 pointer-events-none">
					<div
						className={cn(
							"pointer-events-auto flex items-center gap-2 px-3 py-1.5 rounded-full border shadow-sm backdrop-blur-md text-xs font-medium transition-all duration-300",
							isProStrategy
								? "bg-violet-500/10 border-violet-500/30 text-violet-400"
								: "bg-background/80 border-border text-muted-foreground",
						)}
					>
						{isProStrategy ? (
							<>
								<Cpu className="w-3.5 h-3.5" />
								<span>Institutional Grade (Precision Engine)</span>
							</>
						) : (
							<>
								<Zap className="w-3.5 h-3.5 text-yellow-400" />
								<span>Standard Grade (Turbo Engine)</span>
							</>
						)}
					</div>
				</div>
			)}

			{isCanvasEmpty && (
				<AICoPilot
					onSubmit={(text) => handleAiSubmit(text, false)}
					isGenerating={isGenerating}
				/>
			)}

			<section>
				<div className="flex items-center gap-3 mb-3">
					<div className="w-8 h-8 rounded-full bg-cyan-500/20 flex items-center justify-center">
						<Globe className="text-cyan-400" />
					</div>
					<div>
						<h2 className="text-xl font-semibold">
							{t("canvas.stage1.title")}
						</h2>
						<p className="text-sm text-muted-foreground">
							{t("canvas.stage1.desc")}
						</p>
					</div>
				</div>
				<div
					ref={filtersDropRef}
					className={cn(
						"drop-zone border-2 border-dashed rounded-lg p-4 space-y-3 transition-colors",
						isFiltersTarget
							? "border-cyan-500 bg-cyan-500/10"
							: "border-border",
						isOverFilters && isFiltersTarget && "ring-2 ring-cyan-500",
					)}
				>
					{filters.children && filters.children.length > 0 ? (
						filters.children.map((block: ConditionBlockType, idx: number) => (
							<AnimatedBlock
								key={block.id}
								index={idx}
								epoch={animationEpoch}
								zone="filters"
							>
								<ConditionBlock block={block} stateKey="filters" />
							</AnimatedBlock>
						))
					) : (
						<p className="text-center text-muted-foreground text-sm py-4">
							{t("canvas.dropZone.filters")}
						</p>
					)}
				</div>
			</section>

			<section>
				<div className="flex items-center gap-3 mb-3">
					<div className="w-8 h-8 rounded-full bg-yellow-500/20 flex items-center justify-center">
						<LogIn className="text-yellow-400" />
					</div>
					<div>
						<h2 className="text-xl font-semibold">
							{t("canvas.stage2.title")}
						</h2>
						<p className="text-sm text-muted-foreground">
							{t("canvas.stage2.desc")}
						</p>
					</div>
				</div>
				<Card className="bg-card/50 mb-3">
					<CardContent className="p-4">
						<div className="grid grid-cols-2 gap-4">
							<div>
								<Label>{t("canvas.triggerTypeLabel")}</Label>
								<Select
									value={entryTrigger.type}
									onValueChange={(
										v: "on_candle_close" | "on_tick" | "on_condition_met",
									) => setTrigger({ type: v })}
								>
									<SelectTrigger>
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="on_candle_close">
											{t("canvas.triggerTypeOnClose")}
										</SelectItem>
										<SelectItem value="on_tick">
											{t("canvas.triggerTypeOnTick", onTickLabel)}
										</SelectItem>
										<SelectItem value="on_condition_met">
											{t(
												"canvas.triggerTypeOnConditionMet",
												"On Condition Met (Intra-candle)",
											)}
										</SelectItem>
									</SelectContent>
								</Select>
							</div>
							<div>
								<Label>{t("canvas.timeframeLabel")}</Label>
								<Select
									value={entryTrigger.timeframe}
									onValueChange={(v) =>
										setTrigger({
											timeframe: v as "1m" | "3m" | "5m" | "15m" | "1h" | "4h",
										})
									}
								>
									<SelectTrigger>
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="1m">1m</SelectItem>
										<SelectItem value="5m">5m</SelectItem>
										<SelectItem value="15m">15m</SelectItem>
										<SelectItem value="1h">1h</SelectItem>
										<SelectItem value="4h">4h</SelectItem>
									</SelectContent>
								</Select>
							</div>
						</div>
					</CardContent>
				</Card>
				<div
					ref={entryDropRef}
					data-tutorial-id="entry-conditions-dropzone"
					className={cn(
						"drop-zone border-2 border-dashed rounded-lg p-4 space-y-3 transition-colors",
						isEntryTarget
							? "border-yellow-500 bg-yellow-500/10"
							: "border-border",
						isOverEntry && isEntryTarget && "ring-2 ring-yellow-500",
					)}
				>
					{entryConditions.children && entryConditions.children.length > 0 ? (
						entryConditions.children.map(
							(block: ConditionBlockType, idx: number) => {
								// Offset index by filter count so entry blocks animate after filters
								const globalIdx = (filters.children?.length || 0) + idx;
								return (
									<AnimatedBlock
										key={block.id}
										index={globalIdx}
										epoch={animationEpoch}
										zone="entry"
									>
										<ConditionBlock block={block} stateKey="entryConditions" />
									</AnimatedBlock>
								);
							},
						)
					) : (
						<p className="text-center text-muted-foreground text-sm py-4">
							{t("canvas.dropZone.conditions")}
						</p>
					)}
				</div>
			</section>

			<section>
				<div className="flex items-center gap-3 mb-3">
					<div className="w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center">
						<Rocket className="text-red-400" />
					</div>
					<div>
						<h2 className="text-xl font-semibold">
							{t("canvas.stage3.title")}
						</h2>
						<p className="text-sm text-muted-foreground">
							{t("canvas.stage3.desc")}
						</p>
					</div>
				</div>
				<Card className="bg-card/50">
					<CardContent className="p-4">
						<InitializationEditor />
					</CardContent>
				</Card>
			</section>

			<section>
				<div className="flex items-center gap-3 mb-3">
					<div className="w-8 h-8 rounded-full bg-purple-500/20 flex items-center justify-center">
						<Shield className="text-purple-400" />
					</div>
					<div>
						<h2 className="text-xl font-semibold">
							{t("canvas.stage4.title")}
						</h2>
						<p className="text-sm text-muted-foreground">
							{t("canvas.stage4.desc")}
						</p>
					</div>
				</div>
				<div
					ref={managementDropRef}
					className={cn(
						"drop-zone border-2 border-dashed rounded-lg p-4 space-y-3 transition-colors",
						isManagementTarget
							? "border-purple-500 bg-purple-500/10"
							: "border-border",
						isOverManagement && isManagementTarget && "ring-2 ring-purple-500",
					)}
				>
					{positionManagement.length > 0 ? (
						positionManagement.map((block, idx) => {
							// Offset index by filter + entry count so management blocks animate last
							const globalIdx =
								(filters.children?.length || 0) +
								(entryConditions.children?.length || 0) +
								idx;
							let blockComponent: React.ReactNode;
							switch (block.type) {
								case "scale_in":
									blockComponent = (
										<ScaleInBlockComponent
											key={block.id}
											block={block as unknown as ScaleInBlock}
										/>
									);
									break;
								case "conditional_management":
									blockComponent = (
										<ConditionalManagementBlockComponent
											key={block.id}
											block={block as unknown as ConditionalManagementBlock}
										/>
									);
									break;
								case "modify_stop_loss":
								case "modify_take_profit":
									blockComponent = (
										<ModifyStopLossBlockComponent
											key={block.id}
											block={
												block as unknown as
													| ModifyStopLossBlock
													| ModifyTakeProfitBlock
											}
										/>
									);
									break;
								default:
									blockComponent = (
										<ManagementBlockComponent key={block.id} block={block} />
									);
							}
							return (
								<AnimatedBlock
									key={block.id}
									index={globalIdx}
									epoch={animationEpoch}
									zone="management"
								>
									{blockComponent}
								</AnimatedBlock>
							);
						})
					) : (
						<p className="text-center text-muted-foreground text-sm py-4">
							{t("canvas.dropZone.management")}
						</p>
					)}
				</div>
			</section>
		</div>
	);
};
