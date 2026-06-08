// pwa/components/editor/BlockLinkPopover.tsx

import { useTranslation } from "react-i18next";
import { useStrategyEditorStore } from "../../stores/strategyEditorStore";
import type { ConditionBlock } from "../../types/strategyEditor";

interface BlockLinkPopoverProps {
	onLink: (source: string, key: string, block_id: string) => void;
}

const flattenBlocks = (block: ConditionBlock): ConditionBlock[] => {
	const children = block.children || [];
	return [block, ...children.flatMap(flattenBlocks)];
};

export const BlockLinkPopover: React.FC<BlockLinkPopoverProps> = ({
	onLink,
}) => {
	const { t } = useTranslation("strategy-editor");
	const { entryConditions, filters } = useStrategyEditorStore();

	const allBlocks = [
		...flattenBlocks(entryConditions),
		...flattenBlocks(filters),
	];

	const positionStateKeys = [
		"entry_price",
		"current_size_qty",
		"unrealized_pnl_pct",
		"time_in_trade_sec",
		"number_of_entries",
	];

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
		return [];
	};

	return (
		<div className="grid gap-2">
			<div>
				<h4 className="font-medium text-sm mb-1">
					{t("dynamic_sources.position_state.title")}
				</h4>
				<div className="pl-2 flex flex-col items-start">
					{positionStateKeys.map((key) => (
						<button
							key={key}
							onClick={() => onLink("position_state", key, "")}
							className="h-6 p-0 text-sm text-[hsl(var(--primary))] hover:underline"
						>
							{t(`dynamic_sources.position_state.${key}`)}
						</button>
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
						<div
							key={block.id}
							className="p-1 rounded-md hover:bg-[hsl(var(--secondary))]"
						>
							<p className="font-semibold text-sm">
								{t(`blocks.${block.type}.title`)}
							</p>
							<div className="pl-2 mt-1 flex flex-col items-start">
								{getAvailableKeysForBlock(block.type).map((key) => (
									<button
										key={key}
										onClick={() => onLink("block_result", key, block.id)}
										className="h-6 p-0 text-sm text-[hsl(var(--primary))] hover:underline"
									>
										{key}
									</button>
								))}
							</div>
						</div>
					))}
			</div>
		</div>
	);
};
