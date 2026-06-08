// src/components/strategy-editor/ComponentPalette.tsx

import { useDraggable } from "@dnd-kit/core";
import {
	Activity,
	AlertTriangle,
	Anchor,
	AreaChart,
	BarChartHorizontal,
	CandlestickChart,
	Combine,
	Gauge,
	GitMerge,
	Globe,
	Layers,
	Move,
	Rss,
	Settings2,
	Shield,
	Sigma,
	Signal,
	Target,
	Timer,
	TrendingDown,
	TrendingUp,
	Waves,
	Wind,
} from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
	Accordion,
	AccordionContent,
	AccordionItem,
	AccordionTrigger,
} from "@/components/ui/accordion";
import { Card } from "@/components/ui/card";
import { useToast } from "@/components/ui/use-toast";
import { useBlockRestrictions } from "@/lib/api";
import { hasProPlanAccess } from "@/lib/strategyRestrictions";
import { cn } from "@/lib/utils";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import { InfoTooltip } from "./InfoTooltip";
import type { ComponentCategory, ComponentType, PlanTier } from "./types";

interface DraggablePaletteItemProps {
	type: ComponentType;
	category: ComponentCategory;
	title: string;
	description: string;
	icon: React.ReactNode;
	isPro?: boolean;
	userTier: PlanTier;
	"data-tutorial-id"?: string;
}

export const DraggablePaletteItem: React.FC<DraggablePaletteItemProps> = ({
	type,
	category,
	title,
	description,
	icon,
	isPro,
	userTier,
	"data-tutorial-id": dataTutorialId,
}) => {
	const isLocked = isPro && !hasProPlanAccess(userTier);
	const { toast } = useToast();

	const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
		id: `palette-item-${type}`,
		data: {
			isPaletteItem: true,
			componentType: type,
			category,
			title,
			description,
			icon,
		},
		disabled: isLocked, // Disable drag for locked blocks
	});

	const handleLockedClick = () => {
		toast({
			title: "Pro Feature Locked",
			description:
				"This institutional-grade block requires a Pro subscription. Upgrade to unleash its power.",
			variant: "default",
		});
	};

	return (
		<Card
			ref={setNodeRef}
			{...(isLocked
				? { onClick: handleLockedClick }
				: { ...listeners, ...attributes })}
			data-tutorial-id={dataTutorialId}
			className={cn(
				"cursor-grab p-3 transition-all duration-200 relative overflow-hidden",
				"hover:bg-accent hover:shadow-lg hover:-translate-y-0.5",
				isDragging ? "opacity-50 cursor-grabbing" : "",
				isLocked ? "opacity-75 cursor-not-allowed grayscale-[0.5]" : "",
				isPro ? "border-violet-500/30 bg-violet-500/5" : "",
			)}
		>
			{isPro && (
				<div className="absolute top-0 right-0 px-1.5 py-0.5 bg-violet-600 text-[8px] font-bold text-white rounded-bl-md uppercase tracking-wider z-10">
					Pro
				</div>
			)}
			<div className="flex items-start gap-3">
				<div
					className={cn(
						"text-muted-foreground mt-1",
						isPro ? "text-violet-500" : "",
					)}
				>
					{icon}
				</div>
				<div className="flex-grow">
					<div className="flex items-center justify-between">
						<h4 className="font-semibold text-sm">{title}</h4>
						<InfoTooltip blockType={type} className="-mr-2 -mt-2" />
					</div>
					<p className="text-xs text-muted-foreground line-clamp-2">
						{description}
					</p>
				</div>
			</div>
			{isLocked && (
				<div className="absolute inset-0 bg-background/40 backdrop-blur-[1px] flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity z-20">
					<div className="bg-violet-600 text-white text-[10px] px-2 py-1 rounded shadow-lg font-bold">
						UPGRADE TO PRO
					</div>
				</div>
			)}
		</Card>
	);
};

interface PaletteItemConfig {
	type: ComponentType;
	category: ComponentCategory;
	titleKey: string;
	descriptionKey: string;
	icon: React.ComponentType<{ className?: string }>;
	isPro?: boolean;
}

const PALETTE_CONFIG: {
	groupKey: string;
	groupTitleKey: string;
	items: PaletteItemConfig[];
}[] = [
	{
		groupKey: "filters",
		groupTitleKey: "palette.groups.filters",
		items: [
			{
				type: "trading_session",
				category: "filter",
				titleKey: "blocks.trading_session.title",
				descriptionKey: "blocks.trading_session.desc",
				icon: Timer,
			},
			{
				type: "volatility_filter",
				category: "filter",
				titleKey: "blocks.volatility_filter.title",
				descriptionKey: "blocks.volatility_filter.desc",
				icon: Activity,
			},
			{
				type: "trend_filter",
				category: "filter",
				titleKey: "blocks.trend_filter.title",
				descriptionKey: "blocks.trend_filter.desc",
				icon: TrendingDown,
			},
			{
				type: "senior_tf_confluence",
				category: "filter",
				titleKey: "blocks.senior_tf_confluence.title",
				descriptionKey: "blocks.senior_tf_confluence.desc",
				icon: Rss,
			},
			{
				type: "btc_state_filter",
				category: "filter",
				titleKey: "blocks.btc_state_filter.title",
				descriptionKey: "blocks.btc_state_filter.desc",
				icon: Globe,
				isPro: true,
			},
			{
				type: "correlation",
				category: "filter",
				titleKey: "blocks.correlation.title",
				descriptionKey: "blocks.correlation.desc",
				icon: GitMerge,
				isPro: true,
			},
			{
				type: "natr_filter",
				category: "filter",
				titleKey: "blocks.natr_filter.title",
				descriptionKey: "blocks.natr_filter.desc",
				icon: Activity,
			},
			{
				type: "rel_vol_filter",
				category: "filter",
				titleKey: "blocks.rel_vol_filter.title",
				descriptionKey: "blocks.rel_vol_filter.desc",
				icon: Gauge,
			},
			{
				type: "volatility_squeeze",
				category: "filter",
				titleKey: "blocks.volatility_squeeze.title",
				descriptionKey: "blocks.volatility_squeeze.desc",
				icon: Activity,
			},
		],
	},
	{
		groupKey: "foundations",
		groupTitleKey: "palette.groups.foundations",
		items: [
			{
				type: "market_activity",
				category: "foundation",
				titleKey: "blocks.market_activity.title",
				descriptionKey: "blocks.market_activity.desc",
				icon: Activity,
			},
			{
				type: "tape_condition",
				category: "foundation",
				titleKey: "blocks.tape_condition.title",
				descriptionKey: "blocks.tape_condition.desc",
				icon: Wind,
				isPro: true,
			},
			{
				type: "order_book_zone_condition",
				category: "foundation",
				titleKey: "blocks.order_book_zone_condition.title",
				descriptionKey: "blocks.order_book_zone_condition.desc",
				icon: Layers,
				isPro: true,
			},
			{
				type: "level_proximity_condition",
				category: "foundation",
				titleKey: "blocks.level_proximity_condition.title",
				descriptionKey: "blocks.level_proximity_condition.desc",
				icon: AreaChart,
			},
			{
				type: "l2_microstructure",
				category: "foundation",
				titleKey: "blocks.l2_microstructure_check.title",
				descriptionKey: "blocks.l2_microstructure_check.desc",
				icon: Shield,
				isPro: true,
			},
			{
				type: "significant_level",
				category: "foundation",
				titleKey: "blocks.significant_level.title",
				descriptionKey: "blocks.significant_level.desc",
				icon: Anchor,
			},
			{
				type: "round_level",
				category: "foundation",
				titleKey: "blocks.round_level.title",
				descriptionKey: "blocks.round_level.desc",
				icon: Target,
			},
			{
				type: "trend_direction",
				category: "foundation",
				titleKey: "blocks.trend_direction.title",
				descriptionKey: "blocks.trend_direction.desc",
				icon: TrendingUp,
			},
			{
				type: "classic_pattern",
				category: "foundation",
				titleKey: "blocks.classic_pattern.title",
				descriptionKey: "blocks.classic_pattern.desc",
				icon: CandlestickChart,
			},
			{
				type: "volume_confirmation",
				category: "foundation",
				titleKey: "blocks.volume_confirmation.title",
				descriptionKey: "blocks.volume_confirmation.desc",
				icon: Signal,
			},
			{
				type: "price_consolidation",
				category: "foundation",
				titleKey: "blocks.price_consolidation.title",
				descriptionKey: "blocks.price_consolidation.desc",
				icon: Waves,
			},
			{
				type: "open_interest",
				category: "foundation",
				titleKey: "blocks.open_interest.title",
				descriptionKey: "blocks.open_interest.desc",
				icon: Rss,
				isPro: true,
			},
			{
				type: "tradingview_signal",
				category: "foundation",
				titleKey: "blocks.tradingview_signal.title",
				descriptionKey: "blocks.tradingview_signal.desc",
				icon: Signal,
			},
			{
				type: "price_action_analyzer",
				category: "foundation",
				titleKey: "blocks.price_action_analyzer.title",
				descriptionKey: "blocks.price_action_analyzer.desc",
				icon: CandlestickChart,
			},
			{
				type: "level_touch_analyzer",
				category: "foundation",
				titleKey: "blocks.level_touch_analyzer.title",
				descriptionKey: "blocks.level_touch_analyzer.desc",
				icon: Target,
			},
			{
				type: "return_to_level",
				category: "foundation",
				titleKey: "blocks.return_to_level.title",
				descriptionKey: "blocks.return_to_level.desc",
				icon: AlertTriangle,
			},
		],
	},
	{
		groupKey: "indicators",
		groupTitleKey: "palette.groups.indicators",
		items: [
			{
				type: "ma_cross_condition",
				category: "indicator",
				titleKey: "blocks.ma_cross_condition.title",
				descriptionKey: "blocks.ma_cross_condition.desc",
				icon: Move,
			},
			{
				type: "rsi_condition",
				category: "indicator",
				titleKey: "blocks.rsi_condition.title",
				descriptionKey: "blocks.rsi_condition.desc",
				icon: Settings2,
			},
			{
				type: "value_comparison",
				category: "indicator",
				titleKey: "blocks.value_comparison.title",
				descriptionKey: "blocks.value_comparison.desc",
				icon: Sigma,
			},
			{
				type: "macd_condition",
				category: "indicator",
				titleKey: "blocks.macd_condition.title",
				descriptionKey: "blocks.macd_condition.desc",
				icon: BarChartHorizontal,
			},
			{
				type: "bollinger_bands_condition",
				category: "indicator",
				titleKey: "blocks.bollinger_bands_condition.title",
				descriptionKey: "blocks.bollinger_bands_condition.desc",
				icon: Waves,
			},
			{
				type: "stochastic_condition",
				category: "indicator",
				titleKey: "blocks.stochastic_condition.title",
				descriptionKey: "blocks.stochastic_condition.desc",
				icon: Wind,
			},
			{
				type: "price_vs_level",
				category: "indicator",
				titleKey: "blocks.price_vs_level.title",
				descriptionKey: "blocks.price_vs_level.desc",
				icon: Target,
			},
		],
	},
	{
		groupKey: "logic",
		groupTitleKey: "palette.groups.logic",
		items: [
			{
				type: "AND",
				category: "logic",
				titleKey: "blocks.and.title",
				descriptionKey: "blocks.and.desc",
				icon: Combine,
			},
			{
				type: "OR",
				category: "logic",
				titleKey: "blocks.or.title",
				descriptionKey: "blocks.or.desc",
				icon: GitMerge,
			},
		],
	},
	{
		groupKey: "management",
		groupTitleKey: "palette.groups.management",
		items: [
			{
				type: "trailing_stop",
				category: "management",
				titleKey: "blocks.trailing_stop.title",
				descriptionKey: "blocks.trailing_stop.desc",
				icon: TrendingUp,
			},
			{
				type: "move_to_breakeven",
				category: "management",
				titleKey: "blocks.move_to_breakeven.title",
				descriptionKey: "blocks.move_to_breakeven.desc",
				icon: Anchor,
			},
			{
				type: "conditional_exit",
				category: "management",
				titleKey: "blocks.conditional_exit.title",
				descriptionKey: "blocks.conditional_exit.desc",
				icon: AlertTriangle,
				isPro: true,
			},
			{
				type: "scale_in",
				category: "management",
				titleKey: "blocks.scale_in.title",
				descriptionKey: "blocks.scale_in.desc",
				icon: TrendingUp,
			},
			{
				type: "dca_management",
				category: "management",
				titleKey: "blocks.dca_management.title",
				descriptionKey: "blocks.dca_management.desc",
				icon: Sigma,
			},
			{
				type: "grid_management",
				category: "management",
				titleKey: "blocks.grid_management.title",
				descriptionKey: "blocks.grid_management.desc",
				icon: Layers,
			},
			{
				type: "conditional_management",
				category: "management",
				titleKey: "blocks.conditional_management.title",
				descriptionKey: "blocks.conditional_management.desc",
				icon: Settings2,
			},
		],
	},
];

export const ComponentPalette = ({
	value,
	onValueChange,
}: {
	value: string[];
	onValueChange: (value: string[]) => void;
}) => {
	const { t } = useTranslation("strategy-editor");
	const userTier = useStrategyEditorStore((state) => state.userTier);
	const { data: restrictions } = useBlockRestrictions();
	const proRestricted = useMemo(() => {
		return new Set([
			...(restrictions?.proOnly || []),
			...(restrictions?.klineOnly || []),
		]);
	}, [restrictions?.proOnly, restrictions?.klineOnly]);

	return (
		<div className="flex flex-col h-full bg-background border-r">
			<div className="flex items-center gap-2 p-4 pb-2 px-6 flex-shrink-0">
				<Globe className="w-6 h-6 text-primary" />
				<h3 className="text-lg font-semibold">{t("palette.title")}</h3>
			</div>
			<div className="flex-1 overflow-y-auto px-4 pb-4 min-h-0">
				<Accordion
					type="multiple"
					value={value}
					onValueChange={onValueChange}
					className="w-full"
				>
					{PALETTE_CONFIG.map((group) => (
						<AccordionItem
							key={group.groupKey}
							value={group.groupKey}
							className="border-b-0"
						>
							<AccordionTrigger
								data-tutorial-id={
									group.groupKey === "indicators"
										? "indicators-accordion"
										: undefined
								}
								className="text-sm font-bold text-muted-foreground hover:no-underline px-2"
							>
								{t(group.groupTitleKey)}
							</AccordionTrigger>
							<AccordionContent>
								<div className="space-y-2">
									{group.items.map((item) => (
										<DraggablePaletteItem
											key={item.type}
											type={item.type}
											category={item.category}
											title={t(item.titleKey)}
											description={t(item.descriptionKey)}
											icon={<item.icon className="w-5 h-5" />}
											isPro={proRestricted.has(item.type)}
											userTier={userTier}
											data-tutorial-id={
												item.type === "rsi_condition" ? "rsi-block" : undefined
											}
										/>
									))}
								</div>
							</AccordionContent>
						</AccordionItem>
					))}
				</Accordion>
			</div>
		</div>
	);
};
