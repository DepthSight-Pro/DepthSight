// pwa/components/editor/BlockItem.tsx

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type React from "react";
import { useTranslation } from "react-i18next";
import { ICONS } from "../../constants";
import type {
	ConditionBlock,
	ManagementBlock,
} from "../../types/strategyEditor";

interface BlockItemProps {
	block: ConditionBlock | ManagementBlock;
	onClick: (
		blockId: string,
		section: "filters" | "entryConditions" | "positionManagement",
	) => void;
	onAddCondition: (
		section: "filters" | "entryConditions" | "positionManagement",
		parentId: string | null,
	) => void;
	section: "filters" | "entryConditions" | "positionManagement";
	level?: number;
}

const formatCompositeParams = (
	block: ConditionBlock,
	t: (key: string) => string,
): string => {
	if (!block.children || block.children.length === 0)
		return t("blocks.standardParams");

	switch (block.compositeType) {
		case "tape_condition": {
			const providerParams = block.children[0]?.params || {};
			const consumerParams = block.children[1]?.params || {};
			const value =
				typeof consumerParams.rightOperand === "object" && consumerParams.rightOperand !== null
					? `x${(consumerParams.rightOperand as Record<string, unknown>).multiplier}`
					: consumerParams.rightOperand;
			return `${providerParams.time_window_sec}s, ${consumerParams.operator} ${value}`;
		}
		case "order_book_zone_condition": {
			const providerParams = block.children[0]?.params || {};
			const consumerParams = block.children[1]?.params || {};
			return `${providerParams.side}, ${consumerParams.operator} ${consumerParams.rightOperand}`;
		}
		case "level_proximity_condition": {
			const providerParams = block.children[0]?.params || {};
			return `${providerParams.timeframe}, ${providerParams.lookback_period} bars, within ${providerParams.proximity_value}${providerParams.proximity_type === "percentage" ? "%" : " ATR"}`;
		}
		default:
			return t("blocks.standardParams");
	}
};

const formatParams = (
	params: Record<string, unknown>,
	t: (key: string) => string,
): string => {
	if (Object.keys(params).length === 0) return t("blocks.standardParams");

	const paramStrings = Object.entries(params).map(([key, value]) => {
		if (typeof value === "object" && value !== null) {
			return `${key}: ${t("blocks.dynamicParam")}`;
		}
		return `${key}: ${String(value)}`;
	});

	return paramStrings.slice(0, 2).join(", "); // Show only the first two parameters for brevity
};

const BlockItem: React.FC<BlockItemProps> = ({
	block,
	onClick,
	onAddCondition,
	section,
	level = 0,
}) => {
	const { t } = useTranslation("pwa-common");
	const {
		attributes,
		listeners,
		setNodeRef,
		transform,
		transition,
		isDragging,
	} = useSortable({ id: block.id, data: { type: "BLOCK" } });

	const style = {
		transform: CSS.Transform.toString(transform),
		transition,
		marginLeft: `${level * 20}px`,
		opacity: isDragging ? 0.5 : 1, // Make the draggable element semi-transparent
	};

	// Get SVG icon. If not found, use the default icon
	const isComposite = "isComposite" in block && block.isComposite;
	const blockType = isComposite ? block.compositeType! : block.type;

	const IconComponent =
		ICONS[blockType as keyof typeof ICONS] || ICONS.Settings;
	const isContainer =
		!isComposite &&
		(block.type === "AND" ||
			block.type === "OR" ||
			block.type === "senior_tf_confluence" ||
			block.type === "conditional_exit" ||
			block.type === "scale_in" ||
			block.type === "dca_management");

	return (
		<div ref={setNodeRef} style={style} className="touch-manipulation">
			<div
				className="block-item group"
				onClick={(e) => {
					e.stopPropagation();
					onClick(block.id, section);
				}}
			>
				<div className="block-info">
					{/* Drag handle */}
					<div
						{...listeners}
						{...attributes}
						className="cursor-grab p-2 -ml-2 touch-none"
					>
						{/* An icon can be used instead of text */}
						<svg
							width="24"
							height="24"
							viewBox="0 0 24 24"
							fill="none"
							xmlns="http://www.w3.org/2000/svg"
							className="w-5 h-5 text-[hsl(var(--muted-foreground))]"
						>
							<circle cx="9" cy="6" r="1.5" fill="currentColor" />
							<circle cx="15" cy="6" r="1.5" fill="currentColor" />
							<circle cx="9" cy="12" r="1.5" fill="currentColor" />
							<circle cx="15" cy="12" r="1.5" fill="currentColor" />
							<circle cx="9" cy="18" r="1.5" fill="currentColor" />
							<circle cx="15" cy="18" r="1.5" fill="currentColor" />
						</svg>
					</div>

					<div className="block-icon bg-[hsl(var(--secondary))]">
						<IconComponent className="w-5 h-5 text-[hsl(var(--primary))]" />
					</div>
					<div className="block-details">
						<div className="block-name">{t(`blocks.${blockType}.title`)}</div>
						<div className="block-params">
							{isComposite
								? formatCompositeParams(block as ConditionBlock, t)
								: formatParams(block.params || {}, t)}
						</div>
					</div>
				</div>
				<span className="text-[hsl(var(--muted-foreground))] group-hover:text-[hsl(var(--primary))] transition-colors">
					›
				</span>
			</div>

			{/* Rendering child elements ONLY for REGULAR containers */}
			{isContainer && "children" in block && block.children && (
				<div className="pl-5 pt-2 border-l-2 border-dashed border-[hsl(var(--border))] ml-4">
					{block.children.map((childBlock, index) => (
						<BlockItem
							key={childBlock.id || index}
							block={childBlock}
							onClick={onClick}
							onAddCondition={onAddCondition}
							section={section}
							level={level} // Do not increase level because padding is already set by the parent div
						/>
					))}
					{/* Button for adding a nested condition */}
					<button
						className="add-block-btn mt-2"
						style={{ width: `calc(100% - 20px)` }} // Adapt width
						onClick={(e) => {
							e.stopPropagation();
							onAddCondition(section, block.id);
						}}
					>
						<span>+</span>
						<span>
							{t("editor.addConditionTo")} {block.type}
						</span>
					</button>
				</div>
			)}
		</div>
	);
};

export default BlockItem;
