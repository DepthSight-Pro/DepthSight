// src/lib/strategyRestrictions.ts

export interface BlockRestrictionsConfig {
	proOnly: string[];
	klineOnly: string[];
}

const DEFAULT_PRO_ONLY_BLOCKS = [
	"btc_state_filter",
	"correlation",
	"open_interest",
	"tape_condition",
	"order_book_zone_condition",
	"l2_microstructure",
	"conditional_exit",
] as const;

const DEFAULT_KLINE_ONLY_BLOCKS = [
	"senior_tf_confluence",
	"tape_condition",
	"tape_analysis",
	"order_book_zone_condition",
	"order_book_zone",
	"l2_microstructure",
	"l2_microstructure_check",
	"trailing_stop",
	"conditional_exit",
] as const;

export const DEFAULT_BLOCK_RESTRICTIONS: BlockRestrictionsConfig = {
	proOnly: [...DEFAULT_PRO_ONLY_BLOCKS],
	klineOnly: [...DEFAULT_KLINE_ONLY_BLOCKS],
};

const toStringArray = (value: unknown): string[] => {
	if (!Array.isArray(value)) {
		return [];
	}

	return value.filter((item): item is string => typeof item === "string");
};

export const normalizeBlockRestrictions = (
	raw: unknown,
): BlockRestrictionsConfig => {
	if (!raw || typeof raw !== "object") {
		return DEFAULT_BLOCK_RESTRICTIONS;
	}

	const record = raw as Record<string, unknown>;
	const proOnly = toStringArray(record.proOnly ?? record.pro_only);
	const klineOnly = toStringArray(record.klineOnly ?? record.kline_only);

	return {
		proOnly: proOnly.length > 0 ? proOnly : DEFAULT_BLOCK_RESTRICTIONS.proOnly,
		klineOnly:
			klineOnly.length > 0 ? klineOnly : DEFAULT_BLOCK_RESTRICTIONS.klineOnly,
	};
};

export const hasProPlanAccess = (plan?: string | null): boolean => {
	return plan === "pro" || plan === "institutional";
};
