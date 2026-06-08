// pwa/screens/EditorScreen.tsx

import {
	closestCenter,
	DndContext,
	type DragEndEvent,
	KeyboardSensor,
	PointerSensor,
	useSensor,
	useSensors,
} from "@dnd-kit/core";
import {
	SortableContext,
	verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import type React from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import BacktestModal from "../components/BacktestModal";
import BlockInspectorModal from "../components/editor/BlockInspectorModal";
import BlockItem from "../components/editor/BlockItem";
import CollapsibleSection from "../components/editor/CollapsibleSection";
import ComponentPaletteModal from "../components/editor/ComponentPaletteModal";
import FoundationWeightsModal, {
	ensurePrefixedId,
	extractFoundationGroups,
	type FoundationGroupDisplay,
} from "../components/editor/FoundationWeightsModal";
import InitializationBlock from "../components/editor/InitializationBlock";
import { ICONS } from "../constants";
import { useSymbolSelectionSettings } from "../contexts/SymbolSelectionSettingsContext";
import {
	type StateKey,
	useStrategyEditorStore,
} from "../stores/strategyEditorStore";
import type { ConditionBlock, ManagementBlock } from "../types/strategyEditor";

interface EditorScreenProps {
	onSave: () => Promise<void>;
	isSaving: boolean;
	onInitiateBacktest?: (details: {
		symbol: string;
		startDate: string;
		endDate: string;
	}) => void;
}

const EditorScreen: React.FC<EditorScreenProps> = ({
	onSave,
	isSaving,
	onInitiateBacktest,
}) => {
	const {
		name: storeName,
		description: storeDescription,
		filters,
		entryConditions,
		positionManagement,
		min_foundation_weight_threshold,
		useFoundationWeights,
		foundationWeights,
		setStrategyField,
		setUseFoundationWeights,
		moveCondition,
		use_ml_confirmation,
		setUseMlConfirmation,
	} = useStrategyEditorStore();

	const {
		settings: symbolSelectionSettings,
		updateSettings: updateSymbolSelectionSettings,
		isLoading: isSettingsLoading,
	} = useSymbolSelectionSettings();

	const [name, setName] = useState(storeName);
	const [description, setDescription] = useState(storeDescription);

	// Sync local state with store if store values change externally
	const [prevStoreName, setPrevStoreName] = useState(storeName);
	const [prevStoreDescription, setPrevStoreDescription] =
		useState(storeDescription);

	if (
		storeName !== prevStoreName ||
		storeDescription !== prevStoreDescription
	) {
		setPrevStoreName(storeName);
		setPrevStoreDescription(storeDescription);
		setName(storeName);
		setDescription(storeDescription);
	}

	const [isPaletteOpen, setIsPaletteOpen] = useState(false);
	const [paletteTargetSection, setPaletteTargetSection] = useState<
		"filters" | "entryConditions" | "positionManagement"
	>("filters");
	const [paletteParentId, setPaletteParentId] = useState<string | null>(null);

	const [inspectorInitialDisplayMode, setInspectorInitialDisplayMode] =
		useState<"simplified" | "expanded" | undefined>(undefined);
	const [isInspectorOpen, setIsInspectorOpen] = useState(false);
	const [inspectorBlockId, setInspectorBlockId] = useState<string | null>(null);
	const [inspectorSection, setInspectorSection] = useState<
		"filters" | "entryConditions" | "positionManagement"
	>("filters");
	const [isFoundationWeightsModalOpen, setIsFoundationWeightsModalOpen] =
		useState(false);
	const [isBacktestModalOpen, setIsBacktestModalOpen] = useState(false);

	const { t } = useTranslation("pwa-common");

	const sensors = useSensors(
		useSensor(PointerSensor),
		useSensor(KeyboardSensor),
	);

	const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
		setName(e.target.value);
	};

	const handleDescriptionChange = (
		e: React.ChangeEvent<HTMLTextAreaElement>,
	) => {
		setDescription(e.target.value);
	};

	const handleBlur = () => {
		setStrategyField("name", name);
		setStrategyField("description", description);
	};

	const openComponentPalette = (
		section: "filters" | "entryConditions" | "positionManagement",
		parentId: string | null = null,
	) => {
		setPaletteTargetSection(section);
		setPaletteParentId(parentId);
		setIsPaletteOpen(true);
	};

	const closeComponentPalette = () => {
		setIsPaletteOpen(false);
		setPaletteParentId(null);
	};

	const openBlockInspector = (
		blockId: string,
		section: "filters" | "entryConditions" | "positionManagement",
	) => {
		const block = useStrategyEditorStore.getState().findBlock(blockId);
		setInspectorBlockId(blockId);
		setInspectorSection(section);
		setInspectorInitialDisplayMode(block?.displayMode);
		setIsInspectorOpen(true);
	};

	const closeBlockInspector = () => {
		setIsInspectorOpen(false);
		setInspectorBlockId(null);
		setInspectorInitialDisplayMode(undefined);
	};

	const handleDragEnd = (event: DragEndEvent) => {
		const { active, over } = event;

		if (over && active.id !== over.id) {
			const activeSection = active.data.current?.sortable
				.containerId as StateKey;
			const overSection = over.data.current?.sortable.containerId as StateKey;

			if (activeSection && activeSection === overSection) {
				console.log(`Move ${active.id} over ${over.id} in ${activeSection}`);
				moveCondition(activeSection, active.id as string, over.id as string);
			}
		}
	};

	const handleSaveStrategy = () => {
		handleBlur();
		onSave();
	};

	const handleRunBacktest = () => {
		handleBlur();
		setIsBacktestModalOpen(true);
	};

	const handleBacktestSubmit = (details: {
		symbol: string;
		startDate: string;
		endDate: string;
	}) => {
		if (onInitiateBacktest) {
			onInitiateBacktest(details);
		}
		setIsBacktestModalOpen(false);
	};

	const totalFoundationWeight = useMemo(() => {
		if (!useFoundationWeights || entryConditions.type !== "OR") return 0;

		const activeGroups: FoundationGroupDisplay[] = extractFoundationGroups(
			entryConditions,
			t,
		);
		let totalWeight = 0;
		activeGroups.forEach((group: FoundationGroupDisplay) => {
			const prefixedId = ensurePrefixedId(group.id);
			totalWeight += foundationWeights[prefixedId] || 0;
		});
		return totalWeight;
	}, [entryConditions, foundationWeights, useFoundationWeights, t]);

	const renderSection = (
		title: string,
		icon: React.ElementType,
		sectionKey: "filters" | "entryConditions" | "positionManagement",
		blocks: (ConditionBlock | ManagementBlock)[],
	) => {
		return (
			<CollapsibleSection title={title} icon={icon} className="mb-6">
				<SortableContext
					items={blocks.map((block) => block.id)}
					strategy={verticalListSortingStrategy}
					id={sectionKey}
				>
					<div className="section-blocks">
						{blocks.map((block) => (
							<BlockItem
								key={block.id}
								block={block}
								section={sectionKey}
								onClick={openBlockInspector}
								onAddCondition={openComponentPalette}
							/>
						))}
						<button
							className="add-block-btn"
							onClick={() =>
								openComponentPalette(sectionKey, `${sectionKey}_root`)
							}
						>
							<span>+</span>
							<span>{t("editor.add")}</span>
						</button>
					</div>
				</SortableContext>
			</CollapsibleSection>
		);
	};

	console.log("[EditorScreen] foundationWeights:", foundationWeights);
	console.log("[EditorScreen] totalFoundationWeight:", totalFoundationWeight);
	console.log("[EditorScreen] useFoundationWeights:", useFoundationWeights);

	return (
		<div className="constructor p-4">
			<CollapsibleSection
				title={t("editor.strategyInfo")}
				icon={ICONS.FileText}
				className="mb-6"
			>
				<div className="p-4 space-y-4">
					<div>
						<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
							{t("editor.strategyName")}
						</label>
						<input
							className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
							value={name}
							onChange={handleNameChange}
							onBlur={handleBlur}
							placeholder={t("editor.namePlaceholder")}
						/>
					</div>
					<div>
						<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
							{t("editor.description")}
						</label>
						<textarea
							className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))] resize-y"
							value={description}
							onChange={handleDescriptionChange}
							onBlur={handleBlur}
							placeholder={t("editor.descriptionPlaceholder")}
							rows={3}
						/>
					</div>
					<div>
						<label className="flex items-center cursor-pointer">
							<span className="mr-2 text-sm text-[hsl(var(--foreground))]">
								Enable ML Confirmation
							</span>
							<input
								type="checkbox"
								className="sr-only peer"
								checked={use_ml_confirmation}
								onChange={(e) => setUseMlConfirmation(e.target.checked)}
							/>
							<div className="relative w-11 h-6 bg-[hsl(var(--secondary))] peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-[hsl(var(--primary))]/30 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-[hsl(var(--border))] after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[hsl(var(--primary))]"></div>
						</label>
					</div>
				</div>
			</CollapsibleSection>

			<CollapsibleSection
				title="Symbol Selection"
				icon={ICONS.Strategies}
				className="mb-6"
			>
				<div className="p-4 space-y-4">
					<div>
						<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
							Mode
						</label>
						<select
							value={symbolSelectionSettings?.mode || "STATIC"}
							onChange={(e) =>
								updateSymbolSelectionSettings({
									mode: e.target.value as "STATIC" | "DYNAMIC_NATR",
								})
							}
							disabled={isSettingsLoading || isSaving}
							className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
						>
							<option value="STATIC">Static List</option>
							<option value="DYNAMIC_NATR">Dynamic Filter by NATR</option>
						</select>
					</div>

					{symbolSelectionSettings?.mode === "DYNAMIC_NATR" && (
						<div>
							<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
								Minimum NATR 1/30 (1m)
							</label>
							<input
								type="number"
								value={symbolSelectionSettings.min_natr || 0}
								onChange={(e) =>
									updateSymbolSelectionSettings({
										min_natr: parseFloat(e.target.value),
									})
								}
								disabled={isSettingsLoading || isSaving}
								className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
								step="0.1"
								min="0"
								max="10"
							/>
						</div>
					)}

					<div>
						<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
							Max Concurrent Symbols
						</label>
						<input
							type="number"
							value={symbolSelectionSettings?.max_concurrent_symbols || 5}
							onChange={(e) =>
								updateSymbolSelectionSettings({
									max_concurrent_symbols: parseInt(e.target.value, 10),
								})
							}
							disabled={isSettingsLoading || isSaving}
							className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
							min="1"
						/>
					</div>
				</div>
			</CollapsibleSection>

			<DndContext
				sensors={sensors}
				collisionDetection={closestCenter}
				onDragEnd={handleDragEnd}
			>
				{renderSection(
					t("editor.filtersSectionTitle"),
					ICONS.btc_state_filter,
					"filters",
					filters.children || [],
				)}
				{renderSection(
					t("editor.entryConditionsSectionTitle"),
					ICONS.Play,
					"entryConditions",
					entryConditions.children || [],
				)}

				{/* Initialization Section */}
				<CollapsibleSection
					title={t("editor.initialization")}
					icon={ICONS.Play}
					className="mb-6"
				>
					<InitializationBlock />
				</CollapsibleSection>

				{/* New Foundation Weights Section */}
				<CollapsibleSection
					title={t("editor.foundationsAndWeights")}
					icon={ICONS.Sigma}
					className="mb-6"
				>
					<div className="p-4 space-y-4">
						<label className="flex items-center cursor-pointer">
							<span className="mr-2 text-sm text-[hsl(var(--foreground))]">
								{t("editor.useWeights")}
							</span>
							<input
								type="checkbox"
								className="sr-only peer"
								checked={useFoundationWeights}
								onChange={(e) => {
									const checked = e.target.checked;
									setUseFoundationWeights(checked);
									if (checked && totalFoundationWeight > 0) {
										setStrategyField(
											"min_foundation_weight_threshold",
											totalFoundationWeight,
										);
									}
								}}
							/>
							<div className="relative w-11 h-6 bg-[hsl(var(--secondary))] peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-[hsl(var(--primary))]/30 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-[hsl(var(--border))] after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[hsl(var(--primary))]"></div>
						</label>
					</div>
					{useFoundationWeights && (
						<div className="p-4 border border-[hsl(var(--border))] rounded-lg mt-4">
							<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
								{t("editor.minWeightThreshold")}{" "}
								{min_foundation_weight_threshold} / {totalFoundationWeight}
							</label>
							<input
								type="range"
								min="0"
								max={totalFoundationWeight > 0 ? totalFoundationWeight : 1}
								value={min_foundation_weight_threshold}
								onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
									setStrategyField(
										"min_foundation_weight_threshold",
										parseFloat(e.target.value),
									)
								}
								className="w-full h-2 bg-[hsl(var(--secondary))] rounded-lg appearance-none cursor-pointer accent-[hsl(var(--primary))]"
							/>
							<button
								onClick={() => setIsFoundationWeightsModalOpen(true)}
								className="mt-4 w-full py-2 rounded-lg border-none text-sm font-medium bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] transition hover:opacity-90"
							>
								{t("editor.foundationsWeightsButton")}
							</button>
						</div>
					)}
				</CollapsibleSection>

				{renderSection(
					t("editor.positionManagementSectionTitle"),
					ICONS.Settings,
					"positionManagement",
					positionManagement,
				)}
			</DndContext>

			<div className="sticky bottom-0 bg-[hsl(var(--background))] py-4 flex gap-3 mt-2">
				<button
					onClick={handleSaveStrategy}
					disabled={isSaving}
					className="flex-1 py-3 rounded-full border-none text-sm font-medium bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] transition hover:opacity-90 disabled:opacity-50"
				>
					{isSaving ? t("buttons.saving") : t("buttons.save")}
				</button>
				<button
					onClick={handleRunBacktest}
					disabled={isSaving}
					className="flex-1 py-3 rounded-full border-none text-sm font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90 disabled:opacity-50"
				>
					{t("editor.runBacktest")}
				</button>
			</div>

			<ComponentPaletteModal
				isOpen={isPaletteOpen}
				onClose={closeComponentPalette}
				targetSection={paletteTargetSection}
				parentId={paletteParentId}
			/>

			<BlockInspectorModal
				isOpen={isInspectorOpen}
				onClose={closeBlockInspector}
				blockId={inspectorBlockId}
				section={inspectorSection}
				initialDisplayMode={inspectorInitialDisplayMode}
			/>

			<FoundationWeightsModal
				isOpen={isFoundationWeightsModalOpen}
				onClose={() => setIsFoundationWeightsModalOpen(false)}
			/>

			<BacktestModal
				isOpen={isBacktestModalOpen}
				onClose={() => setIsBacktestModalOpen(false)}
				onSubmit={handleBacktestSubmit}
				strategy={null}
			/>
		</div>
	);
};

export default EditorScreen;
