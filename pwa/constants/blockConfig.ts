// pwa/constants/blockConfig.ts

import type { LucideIcon } from "lucide-react";
import { ICONS } from "../constants";
import type { ComponentCategory, ComponentType } from "../types/strategyEditor";

interface PaletteItemConfig {
	type: ComponentType;
	category: ComponentCategory;
	titleKey: string;
	descriptionKey: string;
	icon: LucideIcon | React.FC;
}

export const PALETTE_CONFIG: {
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
				icon: ICONS.trading_session,
			},
			{
				type: "volatility_filter",
				category: "filter",
				titleKey: "blocks.volatility_filter.title",
				descriptionKey: "blocks.volatility_filter.desc",
				icon: ICONS.volatility_filter,
			},
			{
				type: "trend_filter",
				category: "filter",
				titleKey: "blocks.trend_filter.title",
				descriptionKey: "blocks.trend_filter.desc",
				icon: ICONS.trend_filter,
			},
			{
				type: "senior_tf_confluence",
				category: "filter",
				titleKey: "blocks.senior_tf_confluence.title",
				descriptionKey: "blocks.senior_tf_confluence.desc",
				icon: ICONS.senior_tf_confluence,
			},
			{
				type: "btc_state_filter",
				category: "filter",
				titleKey: "blocks.btc_state_filter.title",
				descriptionKey: "blocks.btc_state_filter.desc",
				icon: ICONS.btc_state_filter,
			},
			{
				type: "correlation",
				category: "filter",
				titleKey: "blocks.correlation.title",
				descriptionKey: "blocks.correlation.desc",
				icon: ICONS.correlation,
			},
			{
				type: "natr_filter",
				category: "filter",
				titleKey: "blocks.natr_filter.title",
				descriptionKey: "blocks.natr_filter.desc",
				icon: ICONS.natr_filter,
			},
			{
				type: "rel_vol_filter",
				category: "filter",
				titleKey: "blocks.rel_vol_filter.title",
				descriptionKey: "blocks.rel_vol_filter.desc",
				icon: ICONS.rel_vol_filter,
			},
			{
				type: "volatility_squeeze",
				category: "filter",
				titleKey: "blocks.volatility_squeeze.title",
				descriptionKey: "blocks.volatility_squeeze.desc",
				icon: ICONS.volatility_squeeze,
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
				icon: ICONS.market_activity,
			},
			{
				type: "tape_condition",
				category: "foundation",
				titleKey: "blocks.tape_condition.title",
				descriptionKey: "blocks.tape_condition.desc",
				icon: ICONS.tape_analysis,
			},
			{
				type: "order_book_zone_condition",
				category: "foundation",
				titleKey: "blocks.order_book_zone_condition.title",
				descriptionKey: "blocks.order_book_zone_condition.desc",
				icon: ICONS.order_book_zone,
			},
			{
				type: "level_proximity_condition",
				category: "foundation",
				titleKey: "blocks.level_proximity_condition.title",
				descriptionKey: "blocks.level_proximity_condition.desc",
				icon: ICONS.local_level,
			},
			{
				type: "l2_microstructure",
				category: "foundation",
				titleKey: "blocks.l2_microstructure_check.title",
				descriptionKey: "blocks.l2_microstructure_check.desc",
				icon: ICONS.l2_microstructure,
			},
			{
				type: "significant_level",
				category: "foundation",
				titleKey: "blocks.significant_level.title",
				descriptionKey: "blocks.significant_level.desc",
				icon: ICONS.significant_level,
			},
			{
				type: "round_level",
				category: "foundation",
				titleKey: "blocks.round_level.title",
				descriptionKey: "blocks.round_level.desc",
				icon: ICONS.round_level,
			},
			{
				type: "trend_direction",
				category: "foundation",
				titleKey: "blocks.trend_direction.title",
				descriptionKey: "blocks.trend_direction.desc",
				icon: ICONS.trend_direction,
			},
			{
				type: "classic_pattern",
				category: "foundation",
				titleKey: "blocks.classic_pattern.title",
				descriptionKey: "blocks.classic_pattern.desc",
				icon: ICONS.classic_pattern,
			},
			{
				type: "volume_confirmation",
				category: "foundation",
				titleKey: "blocks.volume_confirmation.title",
				descriptionKey: "blocks.volume_confirmation.desc",
				icon: ICONS.volume_confirmation,
			},
			{
				type: "price_consolidation",
				category: "foundation",
				titleKey: "blocks.price_consolidation.title",
				descriptionKey: "blocks.price_consolidation.desc",
				icon: ICONS.price_consolidation,
			},
			{
				type: "open_interest",
				category: "foundation",
				titleKey: "blocks.open_interest.title",
				descriptionKey: "blocks.open_interest.desc",
				icon: ICONS.open_interest,
			},
			{
				type: "tradingview_signal",
				category: "foundation",
				titleKey: "blocks.tradingview_signal.title",
				descriptionKey: "blocks.tradingview_signal.desc",
				icon: ICONS.tradingview_signal,
			},
			{
				type: "price_action_analyzer",
				category: "foundation",
				titleKey: "blocks.price_action_analyzer.title",
				descriptionKey: "blocks.price_action_analyzer.desc",
				icon: ICONS.price_action_analyzer,
			},
			{
				type: "level_touch_analyzer",
				category: "foundation",
				titleKey: "blocks.level_touch_analyzer.title",
				descriptionKey: "blocks.level_touch_analyzer.desc",
				icon: ICONS.level_touch_analyzer,
			},
			{
				type: "return_to_level",
				category: "foundation",
				titleKey: "blocks.return_to_level.title",
				descriptionKey: "blocks.return_to_level.desc",
				icon: ICONS.return_to_level,
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
				icon: ICONS.ma_cross_condition,
			},
			{
				type: "rsi_condition",
				category: "indicator",
				titleKey: "blocks.rsi_condition.title",
				descriptionKey: "blocks.rsi_condition.desc",
				icon: ICONS.rsi_condition,
			},
			{
				type: "value_comparison",
				category: "indicator",
				titleKey: "blocks.value_comparison.title",
				descriptionKey: "blocks.value_comparison.desc",
				icon: ICONS.value_comparison,
			},
			{
				type: "macd_condition",
				category: "indicator",
				titleKey: "blocks.macd_condition.title",
				descriptionKey: "blocks.macd_condition.desc",
				icon: ICONS.macd_condition,
			},
			{
				type: "bollinger_bands_condition",
				category: "indicator",
				titleKey: "blocks.bollinger_bands_condition.title",
				descriptionKey: "blocks.bollinger_bands_condition.desc",
				icon: ICONS.bollinger_bands_condition,
			},
			{
				type: "stochastic_condition",
				category: "indicator",
				titleKey: "blocks.stochastic_condition.title",
				descriptionKey: "blocks.stochastic_condition.desc",
				icon: ICONS.stochastic_condition,
			},
			{
				type: "price_vs_level",
				category: "indicator",
				titleKey: "blocks.price_vs_level.title",
				descriptionKey: "blocks.price_vs_level.desc",
				icon: ICONS.price_vs_level,
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
				icon: ICONS.AND,
			},
			{
				type: "OR",
				category: "logic",
				titleKey: "blocks.or.title",
				descriptionKey: "blocks.or.desc",
				icon: ICONS.OR,
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
				icon: ICONS.trailing_stop,
			},
			{
				type: "move_to_breakeven",
				category: "management",
				titleKey: "blocks.move_to_breakeven.title",
				descriptionKey: "blocks.move_to_breakeven.desc",
				icon: ICONS.move_to_breakeven,
			},
			{
				type: "conditional_exit",
				category: "management",
				titleKey: "blocks.conditional_exit.title",
				descriptionKey: "blocks.conditional_exit.desc",
				icon: ICONS.conditional_exit,
			},
			{
				type: "scale_in",
				category: "management",
				titleKey: "blocks.scale_in.title",
				descriptionKey: "blocks.scale_in.desc",
				icon: ICONS.scale_in,
			},
			{
				type: "conditional_management",
				category: "management",
				titleKey: "blocks.conditional_management.title",
				descriptionKey: "blocks.conditional_management.desc",
				icon: ICONS.conditional_management,
			},
			{
				type: "dca_management",
				category: "management",
				titleKey: "blocks.dca_management.title",
				descriptionKey: "blocks.dca_management.desc",
				icon: ICONS.dca_management,
			},
			{
				type: "grid_management",
				category: "management",
				titleKey: "blocks.grid_management.title",
				descriptionKey: "blocks.grid_management.desc",
				icon: ICONS.grid_management,
			},
		],
	},
];
