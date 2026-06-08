// pwa/components/editor/ComponentPaletteModal.tsx

import type React from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ICONS } from "../../constants";
import { useStrategyEditorStore } from "../../stores/strategyEditorStore";
import {
	type ComponentType,
	type ConditionBlock,
	TOP_LEVEL_MANAGEMENT_BLOCK_TYPES,
} from "../../types/strategyEditor";

interface ComponentPaletteModalProps {
	isOpen: boolean;
	onClose: () => void;
	targetSection: "filters" | "entryConditions" | "positionManagement";
	parentId: string | null;
}

import { PALETTE_CONFIG } from "../../constants/blockConfig";

// Function to determine relevant block groups
const getPrimaryGroupKeys = (
	section: "filters" | "entryConditions" | "positionManagement",
): string[] => {
	switch (section) {
		case "filters":
			return ["filters", "logic"];
		case "entryConditions":
			return ["foundations", "indicators", "logic"];
		case "positionManagement":
			return ["management"];
		default:
			return [];
	}
};

const ComponentPaletteModal: React.FC<ComponentPaletteModalProps> = ({
	isOpen,
	onClose,
	targetSection,
	parentId,
}) => {
	const { t } = useTranslation("pwa-common");
	const {
		addCondition,
		addManagementBlock,
		addConditionToManagementBlock,
		addCompositeCondition,
	} = useStrategyEditorStore();
	const [isExpanded, setIsExpanded] = useState(false);

	useEffect(() => {
		if (isOpen) {
			const timer = setTimeout(() => {
				setIsExpanded(false);
			}, 0);
			return () => clearTimeout(timer);
		}
	}, [isOpen]);

	const handleAddComponent = (type: ComponentType) => {
		if (
			[
				"tape_condition",
				"order_book_zone_condition",
				"level_proximity_condition",
			].includes(type)
		) {
			if (targetSection === "filters" || targetSection === "entryConditions") {
				addCompositeCondition(
					targetSection,
					type as NonNullable<ConditionBlock["compositeType"]>,
				);
			}
		} else if (targetSection === "positionManagement") {
			if (parentId && !parentId.includes("root")) {
				addConditionToManagementBlock(parentId, type);
			} else if (
				TOP_LEVEL_MANAGEMENT_BLOCK_TYPES.includes(
					type as (typeof TOP_LEVEL_MANAGEMENT_BLOCK_TYPES)[number],
				)
			) {
				addManagementBlock(type);
			}
		} else {
			addCondition(targetSection, type, parentId);
		}
		onClose();
	};

	const renderGroup = (group: (typeof PALETTE_CONFIG)[0]) => (
		<div className="mb-6" key={group.groupKey}>
			<h2 className="text-base font-medium text-[hsl(var(--foreground))] mb-3">
				{t(group.groupTitleKey)}
			</h2>
			<div className="grid grid-cols-3 gap-3">
				{group.items.map((item) => {
					const IconComponent = item.icon;
					return (
						<button
							key={item.type}
							onClick={() => handleAddComponent(item.type)}
							className="bg-[hsl(var(--card))] rounded-xl p-3 flex flex-col items-center justify-center gap-2 aspect-square text-center transition-all hover:shadow-md hover:border-[hsl(var(--primary))] border border-transparent active:scale-95"
						>
							<div className="w-10 h-10 rounded-full bg-[hsl(var(--secondary))] flex items-center justify-center">
								<IconComponent className="w-5 h-5 text-[hsl(var(--primary))]" />
							</div>
							<div className="text-xs font-medium text-[hsl(var(--card-foreground))] leading-tight">
								{t(item.titleKey)}
							</div>
						</button>
					);
				})}
			</div>
		</div>
	);

	const primaryGroupKeys =
		targetSection === "positionManagement" &&
		parentId &&
		!parentId.includes("root")
			? ["foundations", "indicators", "logic"]
			: getPrimaryGroupKeys(targetSection);
	const primaryGroups = PALETTE_CONFIG.filter((g) =>
		primaryGroupKeys.includes(g.groupKey),
	);
	const secondaryGroups = PALETTE_CONFIG.filter(
		(g) => !primaryGroupKeys.includes(g.groupKey),
	);

	return (
		<div
			className={`fixed inset-0 bg-[hsl(var(--background))] z-50 flex flex-col transition-transform duration-300 ease-out ${isOpen ? "translate-y-0" : "translate-y-full"}`}
		>
			<header className="sticky top-0 bg-[hsl(var(--background))] p-4 shadow-sm flex items-center gap-4 z-10 border-b border-[hsl(var(--border))]">
				<button
					className="w-10 h-10 rounded-full flex items-center justify-center transition hover:bg-[hsl(var(--secondary))]"
					onClick={onClose}
				>
					<ICONS.Close className="w-6 h-6 text-[hsl(var(--foreground))]" />
				</button>
				<h1 className="text-xl font-normal flex-1 text-[hsl(var(--foreground))]">
					{t("modal.addBlock")}
				</h1>
			</header>

			<main className="flex-1 overflow-y-auto p-4">
				{primaryGroups.map(renderGroup)}

				{!isExpanded && secondaryGroups.length > 0 && (
					<div className="my-6">
						<button
							onClick={() => setIsExpanded(true)}
							className="w-full py-3 rounded-lg border-none text-sm font-medium bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] transition hover:opacity-90"
						>
							{t("editor.showAllBlocks")}
						</button>
					</div>
				)}

				{isExpanded && secondaryGroups.map(renderGroup)}
			</main>
		</div>
	);
};

export default ComponentPaletteModal;
