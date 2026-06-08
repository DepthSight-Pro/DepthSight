// src/components/strategy-editor/FoundationWeightsHelper.ts

import type { ComponentType, ConditionBlock } from "./types";

export interface FoundationGroupDisplay {
	id: string;
	displayName: string;
	originalBlock: ConditionBlock;
}

export const getLegacyPrefixedFoundationId = (id: string): string => {
	return id.startsWith("w_") ? id : `w_${id}`;
};

export const getFoundationWeightValue = (
	weights: Record<string, number>,
	id: string,
): number => {
	if (weights[id] !== undefined) {
		return weights[id];
	}

	const legacyId = getLegacyPrefixedFoundationId(id);
	return weights[legacyId] ?? 0;
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
			displayName = t(`strategy-editor:blocks.${block.compositeType}.title`);
		} else if (block.type !== "AND") {
			// For simple weighted foundations (e.g., volume_confirmation)
			displayName = t(`strategy-editor:blocks.${block.type}.title`);
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
				displayName = t(`strategy-editor:blocks.${firstChildType}.title`);
			} else {
				// Fallback for generic AND blocks if no better name can be found
				displayName = t(`strategy-editor:blocks.AND.title`);
			}
		} else {
			// Fallback for generic AND blocks if no better name can be found
			displayName = t(`strategy-editor:blocks.AND.title`);
		}
		console.log(
			`Found foundation group: ID=${block.id}, displayName=${displayName}, type=${block.type}`,
		);
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
