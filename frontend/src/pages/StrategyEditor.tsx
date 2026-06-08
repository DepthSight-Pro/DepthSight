// src/pages/StrategyEditor.tsx

import {
	closestCenter,
	DndContext,
	type DragEndEvent,
	DragOverlay,
	type DragStartEvent,
	PointerSensor,
	useSensor,
	useSensors,
} from "@dnd-kit/core";
import {
	Code,
	Download,
	Eye,
	Loader2,
	PencilRuler,
	Save,
	Sparkles,
	Trash2,
	Upload,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
// UI Components
import { PageLayout } from "@/components/layout/PageLayout";
import {
	ComponentPalette,
	DraggablePaletteItem,
} from "@/components/strategy-editor/ComponentPalette";
import { ConditionBlock } from "@/components/strategy-editor/ConditionBlock";
import { ConfigAndLaunchPanel } from "@/components/strategy-editor/ConfigAndLaunchPanel";
import { JsonEditor } from "@/components/strategy-editor/JsonEditor";
import { StrategyCanvas } from "@/components/strategy-editor/StrategyCanvas";
import {
	CONDITIONAL_MANAGEMENT_ACTION_TYPES,
	type ComponentCategory,
	type ComponentType,
	type ConditionBlock as ConditionBlockType,
	TOP_LEVEL_MANAGEMENT_BLOCK_TYPES,
} from "@/components/strategy-editor/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import {
	ResizableHandle,
	ResizablePanel,
	ResizablePanelGroup,
} from "@/components/ui/resizable";
import { useToast } from "@/components/ui/use-toast";
// State & API
import { useAuth } from "@/context/AuthContext";
import {
	useGetStrategy,
	useSaveStrategyConfig,
	useUpdateStrategyConfig,
} from "@/lib/api";
import { useOnboardingStore } from "@/stores/onboardingStore";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import type {
	StrategyConfigCreatePayload,
	StrategyConfigData,
} from "@/types/api";

const PALETTE_GROUPS = [
	"filters",
	"foundations",
	"indicators",
	"logic",
	"management",
];

const StrategyEditorPage = () => {
	const { t } = useTranslation("strategy-editor");
	const { id } = useParams<{ id?: string }>();
	const navigate = useNavigate();
	const { toast } = useToast();

	const loadStrategy = useStrategyEditorStore((state) => state.loadStrategy);
	const reset = useStrategyEditorStore((state) => state.reset);
	const startClearing = useStrategyEditorStore((state) => state.startClearing);
	const addCondition = useStrategyEditorStore((state) => state.addCondition);
	const addManagementBlock = useStrategyEditorStore(
		(state) => state.addManagementBlock,
	);
	const addConditionToManagementBlock = useStrategyEditorStore(
		(state) => state.addConditionToManagementBlock,
	);
	const addConditionToConditionalManagementBlock = useStrategyEditorStore(
		(state) => state.addConditionToConditionalManagementBlock,
	);
	const addActionToConditionalManagementBlock = useStrategyEditorStore(
		(state) => state.addActionToConditionalManagementBlock,
	);
	const findBlock = useStrategyEditorStore((state) => state.findBlock);
	const removeBlock = useStrategyEditorStore((state) => state.removeBlock);
	const addCompositeCondition = useStrategyEditorStore(
		(state) => state.addCompositeCondition,
	);
	const toJson = useStrategyEditorStore((state) => state.toJson);

	// Subscribe only to the necessary state fields
	const storeId = useStrategyEditorStore((state) => state.id);
	const strategyName = useStrategyEditorStore((state) => state.name);
	const description = useStrategyEditorStore((state) => state.description);
	const symbol = useStrategyEditorStore((state) => state.symbol);
	const useFoundationWeights = useStrategyEditorStore(
		(state) => state.useFoundationWeights,
	);
	const foundationWeights = useStrategyEditorStore(
		(state) => state.foundationWeights,
	);
	const oracleRegime = useStrategyEditorStore((state) => state.oracleRegime);
	const oracleConfidence = useStrategyEditorStore(
		(state) => state.oracleConfidence,
	);
	const use_ml_confirmation = useStrategyEditorStore(
		(state) => state.use_ml_confirmation,
	);
	const isStatePristine = useStrategyEditorStore(
		(state) =>
			(!state.filters.children || state.filters.children.length === 0) &&
			(!state.entryConditions.children ||
				state.entryConditions.children.length === 0) &&
			(!state.positionManagement || state.positionManagement.length === 0),
	);

	const [viewMode, setViewMode] = useState<"visual" | "json">("visual");
	const [activeDragItem, setActiveDragItem] = useState<Record<
		string,
		unknown
	> | null>(null);
	const [showOnboardingModal, setShowOnboardingModal] = useState(false);
	const {
		start: startOnboarding,
		end: endOnboarding,
		isActive: isOnboardingActive,
	} = useOnboardingStore();
	const fileInputRef = useRef<HTMLInputElement>(null);

	const [openPaletteGroups, setOpenPaletteGroups] = useState(PALETTE_GROUPS);

	useEffect(() => {
		setOpenPaletteGroups(isOnboardingActive ? [] : PALETTE_GROUPS);
	}, [isOnboardingActive]);

	const { data: fetchedStrategy, isLoading: isLoadingStrategy } =
		useGetStrategy(id || null);
	const { mutate: saveNewStrategy, isPending: isSavingNew } =
		useSaveStrategyConfig();
	const { mutate: updateStrategy, isPending: isUpdating } =
		useUpdateStrategyConfig();

	const isSaving = isSavingNew || isUpdating;

	const sensors = useSensors(
		useSensor(PointerSensor, {
			activationConstraint: {
				distance: 8,
			},
		}),
	);

	// Strategy load/reset logic
	useEffect(() => {
		if (id) {
			// Edit mode: if ID exists and data from API is loaded
			if (fetchedStrategy && storeId !== id) {
				loadStrategy(
					fetchedStrategy as unknown as Parameters<typeof loadStrategy>[0],
				);
			}
		} else {
			// Creation mode: reset only if state is NOT empty

			if (!isLoadingStrategy && !isStatePristine && storeId !== null) {
				reset();
			}
		}
	}, [
		id,
		fetchedStrategy,
		isLoadingStrategy,
		loadStrategy,
		reset,
		storeId,
		isStatePristine,
	]);

	const { user } = useAuth();
	const setUserTier = useStrategyEditorStore((state) => state.setUserTier);

	// Sync user tier from AuthContext
	useEffect(() => {
		if (user?.plan) {
			setUserTier(user.plan as "free" | "standard" | "pro");
		}
	}, [user?.plan, setUserTier]);

	// Onboarding logic
	useEffect(() => {
		const completed = localStorage.getItem("onboardingCompleted");
		// Run only if it's a new strategy (no id) and the tutorial hasn't been completed
		if (!id && !completed) {
			// Give a small delay so the UI has time to render
			setTimeout(() => {
				setShowOnboardingModal(true);
			}, 1000);
		}
	}, [id]);

	const handleDragStart = (event: DragStartEvent) => {
		setActiveDragItem(
			(event.active.data.current as Record<string, unknown>) || null,
		);
	};

	const handleDragEnd = (event: DragEndEvent) => {
		const { active, over } = event;
		setActiveDragItem(null);

		if (!over) return;

		const isPaletteItem = active.data.current?.isPaletteItem;

		if (isPaletteItem) {
			// --- LOGIC FOR ADDING A NEW BLOCK FROM THE PALETTE ---
			const componentType = active.data.current?.componentType as ComponentType;
			const category = active.data.current?.category as ComponentCategory;
			const overId = over.id as string;
			// stateKey is passed in the data of each droppable (block or drop-zone)
			const overStateKey = over.data.current?.stateKey as
				| "filters"
				| "entryConditions"
				| undefined;
			const overIsContainer = over.data.current?.isContainer as
				| boolean
				| undefined;
			let isValidDrop = false;

			// ── 1. inner-drop-zone of the expanded container (id: inner-{UUID}) ──────
			// Zone inside AND/OR/senior_tf_confluence — parentId is already correct
			if (overId.startsWith("inner-") && overStateKey) {
				const innerParentId = over.data.current?.parentId as string;
				if (["filter", "logic", "indicator", "foundation"].includes(category)) {
					addCondition(overStateKey, componentType, innerParentId);
					isValidDrop = true;
				}
			}
			// ── 2. Composite blocks — only to the root of zones ─────────────────────────
			else if (
				[
					"tape_condition",
					"order_book_zone_condition",
					"level_proximity_condition",
				].includes(componentType)
			) {
				const compositeType = componentType as NonNullable<
					ConditionBlockType["compositeType"]
				>;
				// Accept into the filters root (drop-zone or any block in the filters zone)
				if (overId === "filters-drop-zone" || overStateKey === "filters") {
					addCompositeCondition("filters", compositeType);
					isValidDrop = true;
				} else if (
					overId === "entry-conditions-drop-zone" ||
					overStateKey === "entryConditions"
				) {
					addCompositeCondition("entryConditions", compositeType);
					isValidDrop = true;
				}
			}
			// ── 3. Filters Zone (drop-zone, block-container or leaf block) ───
			else if (
				(overId === "filters-drop-zone" || overStateKey === "filters") &&
				["filter", "logic", "indicator", "foundation"].includes(category)
			) {
				// If the target is a container (AND/OR/senior_tf_confluence), nest INTO it
				// If the target is a leaf block, add to its parent (will fallback to root)
				const targetParentId = overIsContainer
					? overId === "filters-drop-zone"
						? null
						: overId
					: (over.data.current?.parentId ?? null);
				addCondition(
					"filters",
					componentType,
					targetParentId === "filters-drop-zone" ? null : targetParentId,
				);
				isValidDrop = true;
			}
			// ── 4. Entry Conditions Zone ───────────────────────────────────────────
			else if (
				(overId === "entry-conditions-drop-zone" ||
					overStateKey === "entryConditions") &&
				["foundation", "indicator", "logic"].includes(category)
			) {
				const targetParentId = overIsContainer
					? overId === "entry-conditions-drop-zone"
						? null
						: overId
					: (over.data.current?.parentId ?? null);
				addCondition(
					"entryConditions",
					componentType,
					targetParentId === "entry-conditions-drop-zone"
						? null
						: targetParentId,
				);
				isValidDrop = true;
			}
			// ── 5. Management zone ────────────────────────────────────────────────
			else if (overId.startsWith("management") && category === "management") {
				if (
					!TOP_LEVEL_MANAGEMENT_BLOCK_TYPES.includes(
						componentType as unknown as (typeof TOP_LEVEL_MANAGEMENT_BLOCK_TYPES)[number],
					)
				) {
					isValidDrop = false;
				} else {
					addManagementBlock(componentType);
					isValidDrop = true;
				}
			} else if (
				overId.endsWith("-conditions-drop-zone") &&
				["foundation", "indicator", "logic"].includes(category)
			) {
				const blockId = over.data.current?.parentId;
				addConditionToManagementBlock(blockId, componentType);
				isValidDrop = true;
			} else if (
				overId.endsWith("-if-drop-zone") &&
				["foundation", "indicator", "logic"].includes(category)
			) {
				const blockId = over.data.current?.parentId;
				addConditionToConditionalManagementBlock(blockId, componentType);
				isValidDrop = true;
			} else if (
				overId.endsWith("-then-drop-zone") &&
				category === "management"
			) {
				const blockId = over.data.current?.parentId;
				if (
					CONDITIONAL_MANAGEMENT_ACTION_TYPES.includes(
						componentType as unknown as (typeof CONDITIONAL_MANAGEMENT_ACTION_TYPES)[number],
					)
				) {
					addActionToConditionalManagementBlock(blockId, componentType);
					isValidDrop = true;
				}
			} else if (
				overId.startsWith("inner-") &&
				["foundation", "indicator", "logic"].includes(category)
			) {
				const blockId = over.data.current?.parentId;
				const stateKey = over.data.current?.stateKey as
					| "filters"
					| "entryConditions"
					| undefined;
				if (stateKey) {
					addCondition(stateKey, componentType, blockId);
				} else {
					addConditionToManagementBlock(blockId, componentType);
				}
				isValidDrop = true;
			}

			if (!isValidDrop) {
				toast({
					variant: "destructive",
					title: t("dnd.invalidDropTitle"),
					description: t("dnd.invalidDropDesc", { category, zone: overId }),
				});
			}

			// Onboarding logic
			const { isActive, currentStep, nextStep } = useOnboardingStore.getState();
			if (
				isActive &&
				currentStep === 3 &&
				(over?.id as string)?.startsWith("entry-conditions")
			) {
				const componentType = active.data.current?.componentType;
				if (componentType === "rsi_condition") {
					setTimeout(() => nextStep(), 300);
				}
			}
		} else {
			// --- LOGIC FOR MOVING AN EXISTING BLOCK ---
			const activeId = active.id as string;
			const overId = over.id as string;
			if (activeId === overId) return;

			const activeBlock = findBlock(activeId) as ConditionBlockType;
			if (!activeBlock) return;

			// Determine stateKey before deleting the block
			const activeStateKey = active.data.current?.stateKey as
				| "filters"
				| "entryConditions"
				| undefined;
			const overStateKey = over.data.current?.stateKey as
				| "filters"
				| "entryConditions"
				| undefined;

			// 1. Remove the block from its old location
			removeBlock(activeId);

			// For inner-drop-zone, we take parentId directly from the drop data
			let parentId: string | undefined;
			if (overId.startsWith("inner-")) {
				parentId = over.data.current?.parentId;
			} else {
				const overIsContainer = over.data.current?.isContainer;
				parentId = overIsContainer ? overId : over.data.current?.parentId;
			}

			// 2. Determine the target zone based on stateKey or ID
			let targetZone: "filters" | "entryConditions" | null = null;

			if (overStateKey) {
				// If the target element has a stateKey, use it
				targetZone = overStateKey;
			} else if (overId.startsWith("filters")) {
				targetZone = "filters";
			} else if (overId.startsWith("entry-conditions")) {
				targetZone = "entryConditions";
			}

			// 3. Insert the block into the new location
			if (targetZone) {
				addCondition(
					targetZone,
					activeBlock.type,
					parentId ?? null,
					activeBlock,
				);
			} else if (overId.endsWith("-conditions-drop-zone")) {
				const blockId = over.data.current?.parentId;
				addConditionToManagementBlock(blockId, activeBlock);
			} else if (overId.startsWith("inner-")) {
				const blockId = over.data.current?.parentId;
				const stateKey = over.data.current?.stateKey as
					| "filters"
					| "entryConditions"
					| undefined;
				if (stateKey) {
					addCondition(stateKey, activeBlock.type, blockId, activeBlock);
				} else {
					addConditionToManagementBlock(blockId, activeBlock);
				}
			} else if (overId.endsWith("-if-drop-zone")) {
				const blockId = over.data.current?.parentId;
				addConditionToConditionalManagementBlock(blockId, activeBlock);
			} else if (overId.endsWith("-then-drop-zone")) {
				const blockId = over.data.current?.parentId;
				// Only allow management blocks to be dropped into 'then' zone
				if (
					active.data.current?.category === "management" &&
					CONDITIONAL_MANAGEMENT_ACTION_TYPES.includes(
						activeBlock.type as unknown as (typeof CONDITIONAL_MANAGEMENT_ACTION_TYPES)[number],
					)
				) {
					addActionToConditionalManagementBlock(blockId, activeBlock as never);
				}
			} else {
				// Fallback: if the zone could not be determined, return the block to its original one
				console.warn(
					`[handleDragEnd] Could not determine target zone for ${overId}. Returning to original zone.`,
				);
				if (activeStateKey) {
					addCondition(activeStateKey, activeBlock.type, null, activeBlock);
				}
			}
		}
	};

	const getStrategyPayload = (): StrategyConfigData => {
		return toJson();
	};

	const handleSave = () => {
		if (!strategyName) {
			toast({
				variant: "destructive",
				title: t("common:errorTitle"),
				description: t("configPanel.toasts.nameRequired"),
			});
			return;
		}

		const configData = getStrategyPayload();
		const payload: StrategyConfigCreatePayload = {
			name: strategyName,
			description: description,
			config_data: configData,
			symbol_selection_mode: "STATIC",
			symbols: [symbol],
			use_ml_confirmation: use_ml_confirmation,
			foundation_weights: useFoundationWeights ? foundationWeights : null,
			oracle_regime: oracleRegime,
			oracle_confidence: oracleConfidence,
		};

		if (id) {
			// Update mode for an existing strategy
			updateStrategy(
				{ id, payload },
				{
					onSuccess: () => {
						toast({
							title: t("common:successTitle"),
							description: t("configPanel.toasts.updateSuccess"),
						});
					},
				},
			);
		} else {
			// Save mode for a new strategy
			saveNewStrategy(payload, {
				onSuccess: (data) => {
					toast({
						title: t("common:successTitle"),
						description: t("configPanel.toasts.saveSuccess"),
					});
					// Load the data received from the server into the state, including the new ID
					loadStrategy(data as unknown as Parameters<typeof loadStrategy>[0]);
					// Redirect to the editing page with the new ID
					navigate(`/editor/${data.id}`, { replace: true });
				},
			});
		}
	};

	const handleReset = () => {
		startClearing();
		// Navigate and toast immediately; actual reset happens after clearing animation
		navigate("/editor", { replace: true });
		toast({
			title: t("configPanel.toasts.resetTitle"),
			description: t("configPanel.toasts.toastReset"),
		});
	};

	const handleExport = () => {
		const config = toJson();
		const dataStr = JSON.stringify(config, null, 2);

		// Create a Blob and a download link
		const blob = new Blob([dataStr], { type: "application/json" });
		const url = URL.createObjectURL(blob);

		const exportFileDefaultName = `${strategyName.replace(/\s+/g, "_")}_config.json`;

		const linkElement = document.createElement("a");
		linkElement.setAttribute("href", url);
		linkElement.setAttribute("download", exportFileDefaultName);
		linkElement.click();

		// Cleanup
		URL.revokeObjectURL(url);
	};

	const handleImportClick = () => {
		fileInputRef.current?.click();
	};

	const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
		const file = event.target.files?.[0];
		if (!file) return;

		const reader = new FileReader();
		reader.onload = (e) => {
			try {
				const content = e.target?.result as string;
				const parsedJson = JSON.parse(content);

				// Minimal structure validation
				if (!parsedJson.strategy_name && !parsedJson.entryConditions) {
					throw new Error("Invalid strategy format");
				}

				loadStrategy(parsedJson);
				toast({
					title: t("configPanel.toasts.importSuccess"),
					variant: "default",
				});
			} catch (err) {
				console.error("Import error:", err);
				toast({
					title: t("configPanel.toasts.importError"),
					variant: "destructive",
				});
			}
			// Reset the value so the same file can be selected again
			if (fileInputRef.current) fileInputRef.current.value = "";
		};
		reader.readAsText(file);
	};

	const headerActions = (
		<>
			<Button
				variant="outline"
				size="sm"
				onClick={handleSave}
				disabled={isSaving}
				className="mr-2"
			>
				{isSaving ? (
					<Loader2 className="w-4 h-4 mr-2 animate-spin" />
				) : (
					<Save className="w-4 h-4 mr-2" />
				)}
				{id ? t("configPanel.updateButton") : t("configPanel.saveButton")}
			</Button>
			<Button
				variant="ghost"
				size="sm"
				onClick={handleReset}
				disabled={isSaving}
				className="mr-2 text-muted-foreground"
			>
				<Trash2 className="w-4 h-4 mr-2" />
				{t("configPanel.resetButton")}
			</Button>

			<div className="h-6 w-[1px] bg-border mx-2 self-center hidden sm:block" />

			<Button
				variant="outline"
				size="sm"
				onClick={handleImportClick}
				className="mr-2"
			>
				<Upload className="w-4 h-4 mr-2" />
				{t("configPanel.importButton")}
			</Button>
			<Button
				variant="outline"
				size="sm"
				onClick={handleExport}
				className="mr-2"
			>
				<Download className="w-4 h-4 mr-2" />
				{t("configPanel.exportButton")}
			</Button>

			<div className="h-6 w-[1px] bg-border mx-2 self-center hidden sm:block" />

			<Button
				variant="outline"
				size="sm"
				onClick={() => setViewMode((v) => (v === "visual" ? "json" : "visual"))}
			>
				{viewMode === "visual" ? (
					<Code className="w-4 h-4 mr-2" />
				) : (
					<Eye className="w-4 h-4 mr-2" />
				)}
				{viewMode === "visual" ? t("jsonView") : t("visualView")}
			</Button>
		</>
	);

	if (isLoadingStrategy) {
		return (
			<PageLayout title={t("pageTitle")} icon={PencilRuler}>
				<div className="flex items-center justify-center h-full">
					<Loader2 className="w-8 h-8 animate-spin text-primary" />
					<span className="ml-4 text-lg">{t("loading")}</span>
				</div>
			</PageLayout>
		);
	}

	return (
		<PageLayout
			title={id ? t("pageTitleEdit") : t("pageTitleNew")}
			icon={PencilRuler}
			headerActions={headerActions}
		>
			<DndContext
				sensors={sensors}
				onDragStart={handleDragStart}
				onDragEnd={handleDragEnd}
				collisionDetection={closestCenter}
			>
				<div className="w-full h-full">
					<ResizablePanelGroup
						direction="horizontal"
						className="h-full rounded-lg border bg-card"
					>
						<ResizablePanel defaultSize={20} minSize={15} className="h-full">
							<ComponentPalette
								value={openPaletteGroups}
								onValueChange={setOpenPaletteGroups}
							/>
						</ResizablePanel>
						<ResizableHandle withHandle />
						<ResizablePanel defaultSize={55} minSize={30}>
							{viewMode === "visual" ? <StrategyCanvas /> : <JsonEditor />}
						</ResizablePanel>
						<ResizableHandle withHandle />
						<ResizablePanel defaultSize={25} minSize={20}>
							<ConfigAndLaunchPanel isSaving={isSaving} />
						</ResizablePanel>
					</ResizablePanelGroup>
				</div>
				{activeDragItem && (
					<DragOverlay>
						{activeDragItem ? (
							activeDragItem.isPaletteItem ? (
								<DraggablePaletteItem
									{...(activeDragItem as unknown as Record<string, unknown>)}
								/>
							) : (
								<Card className="p-2 shadow-lg opacity-90">
									<ConditionBlock
										block={activeDragItem as unknown as ConditionBlockType}
										stateKey={
											(activeDragItem as Record<string, unknown>).stateKey as
												| "filters"
												| "entryConditions"
										}
									/>
								</Card>
							)
						) : null}
					</DragOverlay>
				)}
			</DndContext>
			<Dialog open={showOnboardingModal} onOpenChange={setShowOnboardingModal}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle className="flex items-center">
							<Sparkles className="w-6 h-6 mr-2 text-yellow-400" />
							{t("welcomeDialog.title")}
						</DialogTitle>
						<DialogDescription>
							{t("welcomeDialog.description")}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button
							variant="outline"
							onClick={() => {
								setShowOnboardingModal(false);
								endOnboarding();
							}}
						>
							{t("welcomeDialog.cancelButton")}
						</Button>
						<Button
							onClick={() => {
								setShowOnboardingModal(false);
								startOnboarding();
							}}
						>
							{t("welcomeDialog.confirmButton")}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
			<input
				type="file"
				ref={fileInputRef}
				className="hidden"
				accept=".json"
				onChange={handleFileChange}
			/>
		</PageLayout>
	);
};

export default StrategyEditorPage;
