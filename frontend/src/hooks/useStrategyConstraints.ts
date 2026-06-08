// src/hooks/useStrategyConstraints.ts

import type { StrategyState } from "@/components/strategy-editor/types";
import { useBlockRestrictions } from "@/lib/api";

export const useStrategyConstraints = (state: StrategyState | null) => {
	const { data: restrictions } = useBlockRestrictions();

	// We provide fallbacks while loading to safely ignore until data is available
	const proOnly = restrictions?.proOnly || [];
	const klineOnly = restrictions?.klineOnly || [];

	const hasRestricted = (blockList: string[]) => {
		if (!state || blockList.length === 0) return false;

		const restricted = new Set(blockList);

		const walk = (node: unknown): boolean => {
			if (Array.isArray(node)) {
				return node.some(walk);
			}

			if (!node || typeof node !== "object") {
				return false;
			}

			const record = node as Record<string, unknown>;
			if (typeof record.type === "string" && restricted.has(record.type)) {
				return true;
			}

			if (
				typeof record.compositeType === "string" &&
				restricted.has(record.compositeType)
			) {
				return true;
			}

			if (
				restricted.has("partial_exits") &&
				Array.isArray(record.partial_exits) &&
				record.partial_exits.length > 0
			) {
				return true;
			}

			return Object.values(record).some(walk);
		};

		return walk(state);
	};

	const isStrategyProOnly = hasRestricted(proOnly);
	const isStrategyKlineOnly = hasRestricted(klineOnly);

	return {
		isStrategyProOnly,
		isStrategyKlineOnly,
		proOnly,
		klineOnly,
	};
};
