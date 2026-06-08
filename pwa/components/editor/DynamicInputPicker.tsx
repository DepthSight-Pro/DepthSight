// pwa/components/editor/DynamicInputPicker.tsx

import type React from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ICONS } from "../../constants";
import { useStrategyEditorStore } from "../../stores/strategyEditorStore";
import type { ComponentType, ConditionBlock } from "../../types/strategyEditor";

interface DynamicInputPickerProps {
	onLink: (source: string, key: string, block_id?: string) => void;
	isVisible: boolean;
}

type Category = "position" | "candle" | "blocks" | "market";

// --- Helper functions ---

// Get all blocks from the condition tree
const flattenBlocks = (block: ConditionBlock): ConditionBlock[] => {
	if (!block) return [];
	const children = block.children || [];
	return [block, ...children.flatMap(flattenBlocks)];
};

// Determine which keys are available for each block type
const getAvailableKeysForBlock = (blockType: ComponentType): string[] => {
	if (blockType === "local_level" || blockType === "significant_level") {
		return ["detected_level"];
	}
	if (blockType === "tape_analysis") {
		return [
			"buy_volume_usd",
			"sell_volume_usd",
			"delta_volume_usd",
			"acceleration_multiplier_volume",
		];
	}
	if (blockType === "order_book_zone") {
		return ["total_volume_usd", "largest_level_usd", "level_count"];
	}
	return [];
};

// --- Components ---

interface CategoryItemProps {
	icon: React.FC<React.SVGProps<SVGSVGElement>>;
	label: string;
	isActive: boolean;
	onClick: () => void;
}

const CategoryItem: React.FC<CategoryItemProps> = ({
	icon: Icon,
	label,
	isActive,
	onClick,
}) => (
	<button
		onClick={onClick}
		className={`flex flex-col items-center justify-center p-2 rounded-lg border-none flex-shrink-0 gap-1 w-20 h-20 transition-all ${
			isActive
				? "bg-[hsl(var(--primary))] text-white"
				: "bg-transparent text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
		}`}
	>
		<Icon className="w-6 h-6" />
		<span className="text-xs font-medium text-center">{label}</span>
	</button>
);

export const DynamicInputPicker: React.FC<DynamicInputPickerProps> = ({
	onLink,
	isVisible,
}) => {
	const { t } = useTranslation("pwa-common");
	const [activeCategory, setActiveCategory] = useState<Category>("position");
	const { entryConditions, filters } = useStrategyEditorStore();

	// Selecting icons that most likely exist in your ICONS
	const categories: {
		id: Category;
		label: string;
		icon: React.FC<React.SVGProps<SVGSVGElement>>;
	}[] = [
		{
			id: "position",
			label: t("dynamicPicker.categories.position"),
			icon: ICONS.Dollar,
		},
		{
			id: "candle",
			label: t("dynamicPicker.categories.candle"),
			icon: ICONS.TrendingDown,
		}, // Replaced from CandlestickChart
		{
			id: "blocks",
			label: t("dynamicPicker.categories.blocks"),
			icon: ICONS.Settings,
		}, // Replaced from Blocks
		{
			id: "market",
			label: t("dynamicPicker.categories.market"),
			icon: ICONS.Research,
		}, // Replaced from BarChart
	];

	const allBlocks = useMemo(
		() => [...flattenBlocks(entryConditions), ...flattenBlocks(filters)],
		[entryConditions, filters],
	);

	const positionStateKeys = [
		"entry_price",
		"current_size_qty",
		"unrealized_pnl_pct",
		"time_in_trade_sec",
		"number_of_entries",
	];
	const candleStateKeys = ["open", "high", "low", "close", "volume"];
	const marketStateKeys = ["btc_dominance", "funding_rate"];

	const blocksWithKeys = useMemo(
		() => allBlocks.filter((b) => getAvailableKeysForBlock(b.type).length > 0),
		[allBlocks],
	);

	const renderContent = () => {
		switch (activeCategory) {
			case "position":
				return positionStateKeys.map((key) => (
					<button
						key={key}
						onClick={() => onLink("position_state", key)}
						className="param-item"
					>
						{t(`dynamic_sources.position_state.${key}`, key)}
					</button>
				));
			case "candle":
				return candleStateKeys.map((key) => (
					<button
						key={key}
						onClick={() => onLink("candle", key)}
						className="param-item"
					>
						{t(`dynamic_sources.candle.${key}`, key)}
					</button>
				));
			case "blocks":
				if (blocksWithKeys.length === 0) {
					return (
						<p className="text-center text-sm text-[hsl(var(--muted-foreground))] p-4">
							{t("dynamicPicker.noBlocks")}
						</p>
					);
				}
				return blocksWithKeys.map((block) => (
					<div key={block.id} className="p-1 rounded-md">
						<p className="font-semibold text-sm px-2 text-[hsl(var(--muted-foreground))]">
							{t(`blocks.${block.type}.title`)}
						</p>
						<div className="pl-2 mt-1 flex flex-col items-start">
							{getAvailableKeysForBlock(block.type).map((key) => (
								<button
									key={key}
									onClick={() => onLink("block_result", key, block.id)}
									className="param-item text-[hsl(var(--primary))]"
								>
									{key}
								</button>
							))}
						</div>
					</div>
				));
			case "market":
				return marketStateKeys.map((key) => (
					<button
						key={key}
						onClick={() => onLink("market_info", key)}
						className="param-item"
					>
						{t(`dynamic_sources.market.${key}`, key)}
					</button>
				));
			default:
				return null;
		}
	};

	return (
		<div
			className={`bg-[hsl(var(--secondary))] rounded-lg mt-2 transition-all duration-300 ease-out overflow-hidden ${
				isVisible ? "opacity-100 max-h-96" : "opacity-0 max-h-0"
			}`}
		>
			<div className="p-2">
				{/* Category carousel */}
				<div className="flex overflow-x-auto space-x-2 pb-2">
					{categories.map((cat) => (
						<CategoryItem
							key={cat.id}
							icon={cat.icon}
							label={cat.label}
							isActive={activeCategory === cat.id}
							onClick={() => setActiveCategory(cat.id)}
						/>
					))}
				</div>

				{/* Parameter list */}
				<div className="border-t border-[hsl(var(--border))] mt-1 pt-1 max-h-60 overflow-y-auto">
					<style>{`.param-item { display: block; width: 100%; text-align: left; padding: 10px; background: none; border: none; font-size: 0.9rem; border-radius: 6px; cursor: pointer; color: hsl(var(--foreground)); } .param-item:hover { background-color: hsl(var(--accent)); }`}</style>
					{renderContent()}
				</div>
			</div>
		</div>
	);
};
