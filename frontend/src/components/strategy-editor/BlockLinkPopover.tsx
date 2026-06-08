// frontend/src/components/strategy-editor/BlockLinkPopover.tsx

import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import type {
	ConditionalManagementBlock,
	ConditionBlock,
	ManagementBlock,
} from "./types";

interface BlockLinkPopoverProps {
	onLink: (source: string, key: string, block_id: string) => void;
}

const flattenBlocks = (block: ConditionBlock): ConditionBlock[] => {
	const children = block.children || [];
	return [block, ...children.flatMap(flattenBlocks)];
};

const flattenManagementBlocks = (
	blocks: ManagementBlock[],
): ConditionBlock[] => {
	return blocks.flatMap((block) => {
		const conditions = Array.isArray(block.children)
			? block.children.flatMap(flattenBlocks)
			: [];
		const conditionalBlock = block as ConditionalManagementBlock;
		const ifConditions = conditionalBlock.if_conditions
			? flattenBlocks(conditionalBlock.if_conditions)
			: [];
		const thenConditions = Array.isArray(conditionalBlock.then_actions)
			? flattenManagementBlocks(
					conditionalBlock.then_actions as ManagementBlock[],
				)
			: [];

		return [...conditions, ...ifConditions, ...thenConditions];
	});
};

export const BlockLinkPopover: React.FC<BlockLinkPopoverProps> = ({
	onLink,
}) => {
	const { t } = useTranslation("strategy-editor");
	const { entryConditions, filters, positionManagement } =
		useStrategyEditorStore();

	const allBlocks = [
		...flattenBlocks(entryConditions),
		...flattenBlocks(filters),
		...flattenManagementBlocks(positionManagement),
	];

	const positionStateKeys = [
		"entry_price",
		"current_size_qty",
		"unrealized_pnl_pct",
		"unrealized_pnl_rr",
		"time_in_trade_sec",
		"number_of_entries",
		"partial_exits_count",
	];

	// This should be more sophisticated, mapping block types to available output keys
	const getAvailableKeysForBlock = (blockType: string): string[] => {
		if (blockType === "local_level" || blockType === "significant_level") {
			return ["detected_level"];
		}
		if (blockType === "tape_analysis") {
			return [
				"buy_volume_usd",
				"sell_volume_usd",
				"total_volume_usd",
				"buy_count",
				"sell_count",
				"total_count",
				"delta_volume_usd",
				"delta_count",
				"buy_sell_ratio_volume",
				"buy_sell_ratio_count",
				"avg_trade_size_usd",
				"acceleration_multiplier_volume",
				"acceleration_multiplier_count",
			];
		}
		if (blockType === "order_book_zone") {
			return ["total_volume_usd", "largest_level_usd", "level_count"];
		}
		if (blockType === "level_touch_analyzer") {
			return [
				"level",
				"touches_count",
				"is_valid",
				"touch_tolerance_pct",
				"tolerance",
				"pierce_detected",
				"min_touches",
			];
		}
		if (blockType === "volatility_squeeze") {
			return [
				"is_squeezing",
				"current_range_pct",
				"past_range_pct",
				"squeeze_ratio",
			];
		}
		if (blockType === "price_action_analyzer") {
			return [
				"is_valid",
				"highs_count",
				"lows_count",
				"last_high",
				"prev_high",
				"last_low",
				"prev_low",
				"min_points",
			];
		}
		return []; // Returns an empty array if the block does not provide data
	};

	return (
		<div className="grid gap-2">
			<div>
				<h4 className="font-medium text-sm mb-1">
					{t("dynamic_sources.position_state.title")}
				</h4>
				<div className="pl-2 flex flex-col items-start">
					{positionStateKeys.map((key) => (
						<Button
							key={key}
							variant="link"
							className="h-6 p-0"
							onClick={() => onLink("position_state", key, "")}
						>
							{t(`dynamic_sources.position_state.${key}`)}
						</Button>
					))}
				</div>
			</div>
			<div>
				<h4 className="font-medium text-sm mb-1">
					{t("dynamic_sources.block_results.title", "Block Results")}
				</h4>
				{allBlocks
					.filter((b) => getAvailableKeysForBlock(b.type).length > 0)
					.map((block) => (
						<div key={block.id} className="p-1 rounded-md hover:bg-accent">
							<p className="font-semibold text-sm">
								{t(`blocks.${block.type}.title`)}
							</p>
							<div className="pl-2 mt-1 flex flex-col items-start">
								{getAvailableKeysForBlock(block.type).map((key) => (
									<Button
										key={key}
										variant="link"
										className="h-6 p-0"
										onClick={() => onLink("block_result", key, block.id)}
									>
										{key}
									</Button>
								))}
							</div>
						</div>
					))}
			</div>
		</div>
	);
};
