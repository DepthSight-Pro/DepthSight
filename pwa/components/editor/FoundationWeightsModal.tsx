// pwa/components/editor/FoundationWeightsModal.tsx

import type React from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ICONS } from "../../constants";
import { useStrategyEditorStore } from "../../stores/strategyEditorStore";
import type { ComponentType, ConditionBlock } from "../../types/strategyEditor";

interface FoundationWeightsModalProps {
	isOpen: boolean;
	onClose: () => void;
}

export interface FoundationGroupDisplay {
	id: string;
	displayName: string;
	originalBlock: ConditionBlock;
}

// Helper to ensure the ID has the 'w_' prefix if it's a foundation weight key
export const ensurePrefixedId = (id: string): string => {
	return id.startsWith("w_") ? id : `w_${id}`;
};

// Helper to recursively find all blocks that represent a foundation group
export const extractFoundationGroups = (
	block: ConditionBlock,
	t: (key: string) => string,
	parentType: ComponentType | null = null,
): FoundationGroupDisplay[] => {
	let foundations: FoundationGroupDisplay[] = [];

	// A block is considered a foundation group if:
	// 1. It's an 'AND' block and is either composite OR a direct child of an 'OR' block.
	// 2. It's NOT an 'AND' block but IS a direct child of an 'OR' block (simple weighted foundation).
	const isFoundationGroup =
		(block.type === "AND" && (block.isComposite || parentType === "OR")) ||
		(block.type !== "AND" && parentType === "OR");

	if (isFoundationGroup) {
		let displayName: string;
		if (block.compositeType) {
			displayName = t(`blocks.${block.compositeType}.title`);
		} else if (block.type !== "AND") {
			// For simple weighted foundations (e.g., volume_confirmation)
			displayName = t(`blocks.${block.type}.title`);
		} else if (block.children && block.children.length > 0) {
			// For non-composite AND blocks that are foundation groups, try to get name from first child
			const firstChildType = block.children[0].type;
			// Check if it's a type that typically forms a foundation group
			if (
				[
					"tape_analysis",
					"order_book_zone",
					"local_level",
					"significant_level",
					"volume_confirmation",
					"trend_direction",
					"classic_pattern",
				].includes(firstChildType)
			) {
				displayName = t(`blocks.${firstChildType}.title`);
			} else {
				// Fallback for generic AND blocks if no better name can be found
				displayName = t("blocks.AND.title");
			}
		} else {
			// Fallback for generic AND blocks if no better name can be found
			displayName = t("blocks.AND.title");
		}
		foundations.push({ id: block.id, displayName, originalBlock: block });
	}

	if (block.children) {
		block.children.forEach((child) => {
			foundations = foundations.concat(
				extractFoundationGroups(child, t, block.type),
			);
		});
	}
	return foundations;
};

const FoundationWeightsModal: React.FC<FoundationWeightsModalProps> = ({
	isOpen,
	onClose,
}) => {
	const { t } = useTranslation("pwa-common"); // Use pwa-common for translations
	const { entryConditions, foundationWeights, updateFoundationWeight } =
		useStrategyEditorStore();

	const activeFoundationGroups = useMemo(() => {
		if (entryConditions.type === "OR") {
			return extractFoundationGroups(entryConditions, t);
		}
		return [];
	}, [entryConditions, t]);

	const [localWeights, setLocalWeights] = useState<Record<string, number>>({});
	const [prevFoundationWeights, setPrevFoundationWeights] = useState(
		foundationWeights,
	);
	const [prevActiveGroups, setPrevActiveGroups] = useState(
		activeFoundationGroups,
	);

	if (
		foundationWeights !== prevFoundationWeights ||
		activeFoundationGroups !== prevActiveGroups
	) {
		const initialWeights: Record<string, number> = {};
		activeFoundationGroups.forEach((group) => {
			const prefixedId = ensurePrefixedId(group.id);
			initialWeights[prefixedId] = foundationWeights[prefixedId] || 0;
		});
		setLocalWeights(initialWeights);
		setPrevFoundationWeights(foundationWeights);
		setPrevActiveGroups(activeFoundationGroups);
	}

	const handleWeightChange = (blockId: string, value: string) => {
		const newWeight = parseFloat(value);
		if (!Number.isNaN(newWeight)) {
			const prefixedId = ensurePrefixedId(blockId);
			setLocalWeights((prev) => ({ ...prev, [prefixedId]: newWeight }));
			updateFoundationWeight(prefixedId, newWeight);
		}
	};

	if (!isOpen) return null;

	return (
		<div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
			<div className="bg-[hsl(var(--card))] rounded-lg shadow-lg w-full max-w-md max-h-[90vh] flex flex-col">
				<header className="p-4 border-b border-[hsl(var(--border))] flex items-center justify-between">
					<h2 className="text-xl font-medium text-[hsl(var(--card-foreground))]">
						{t("modal.configureFoundationWeights")}
					</h2>
					<button
						onClick={onClose}
						className="w-8 h-8 flex items-center justify-center rounded-full transition hover:bg-[hsl(var(--secondary))]"
					>
						<ICONS.Close className="w-5 h-5 text-[hsl(var(--muted-foreground))]" />
					</button>
				</header>
				<main className="p-4 flex-1 overflow-y-auto">
					{activeFoundationGroups.length > 0 ? (
						activeFoundationGroups.map((group) => {
							const prefixedId = ensurePrefixedId(group.id);
							return (
								<div
									key={group.id}
									className="flex items-center justify-between mb-3"
								>
									<span className="text-sm text-[hsl(var(--foreground))]">
										{group.displayName}
									</span>
									<input
										type="number"
										value={
											localWeights[prefixedId] !== undefined
												? localWeights[prefixedId]
												: ""
										}
										onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
											handleWeightChange(group.id, e.target.value)
										}
										className="w-24 p-2 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-md text-sm text-[hsl(var(--foreground))] outline-none focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary)))]"
									/>
								</div>
							);
						})
					) : (
						<p className="text-center text-sm text-[hsl(var(--muted-foreground))] py-4">
							{t("modal.noFoundationsForWeights")}
						</p>
					)}
				</main>
				<footer className="p-4 border-t border-[hsl(var(--border))] flex justify-end">
					<button
						onClick={onClose}
						className="py-2 px-4 rounded-lg text-sm font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90"
					>
						{t("buttons.close")}
					</button>
				</footer>
			</div>
		</div>
	);
};

export default FoundationWeightsModal;
