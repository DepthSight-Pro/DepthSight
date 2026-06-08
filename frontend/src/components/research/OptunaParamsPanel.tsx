// src/components/research/OptunaParamsPanel.tsx

import { Cpu, HelpCircle, Sparkles, Zap } from "lucide-react";
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
	Accordion,
	AccordionContent,
	AccordionItem,
	AccordionTrigger,
} from "@/components/ui/accordion";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";

interface OptunaParamsPanelProps {
	seedStrategy: Record<string, unknown> | null;
	onChange: (config: Record<string, unknown>) => void;
}

const HEAVY_BLOCK_TYPES = new Set([
	"l2_microstructure",
	"l2_microstructure_check",
	"order_book_zone",
	"orderbook_imbalance",
	"tape_acceleration",
	"tape_analysis",
	"tape_condition",
	"dca_grid",
	"dca_management",
	"dca_orders",
	"bookdepth",
	"aggtrade",
]);

export const OptunaParamsPanel: React.FC<OptunaParamsPanelProps> = ({
	seedStrategy,
	onChange,
}) => {
	const { t } = useTranslation(["research", "common"]);

	// 1. Detect if the strategy is dynamic and has heavy blocks
	const isVisual = useMemo(() => {
		if (!seedStrategy) return false;
		return (
			"entryConditions" in seedStrategy ||
			"filters" in seedStrategy ||
			"initialization" in seedStrategy
		);
	}, [seedStrategy]);

	const hasHeavyBlocks = useMemo(() => {
		if (!seedStrategy || !isVisual) return false;

		const checkNode = (node: unknown): boolean => {
			if (Array.isArray(node)) {
				return node.some(checkNode);
			}
			if (!node || typeof node !== "object") {
				return false;
			}

			const nodeObj = node as Record<string, unknown>;
			const blockType = String(nodeObj.type || "")
				.trim()
				.toLowerCase();
			if (HEAVY_BLOCK_TYPES.has(blockType)) {
				return true;
			}

			for (const key in nodeObj) {
				if (
					[
						"children",
						"entryConditions",
						"filters",
						"initialization",
						"positionManagement",
						"conditions",
					].includes(key)
				) {
					if (checkNode(nodeObj[key])) return true;
				}
			}
			return false;
		};

		return checkNode(seedStrategy);
	}, [seedStrategy, isVisual]);

	// 2. Set default values based on engine routing
	const defaultTrials = hasHeavyBlocks ? 30 : 100;
	const [trials, setTrials] = useState(defaultTrials);
	const [searchWidth, setSearchWidth] = useState(50);
	const [metric, setMetric] = useState("sharpe_ratio");

	// 3. Trigger change on setting updates
	useEffect(() => {
		onChange({
			n_trials: trials,
			metric_name: metric,
			search_width_pct: searchWidth,
			visual_strategy: isVisual ? seedStrategy : undefined,
		});
	}, [trials, searchWidth, metric, seedStrategy, isVisual, onChange]);

	return (
		<div className="space-y-6 rounded-xl border border-border/60 bg-card p-6 shadow-sm">
			{/* Strategy Info Header */}
			{isVisual && (
				<div className="flex flex-col gap-2 p-3.5 rounded-lg bg-secondary/35 border border-border/30">
					<div className="flex items-center gap-2">
						<Sparkles className="w-4 h-4 text-emerald-500" />
						<span className="text-xs font-bold text-emerald-700 dark:text-emerald-300 uppercase tracking-wider">
							{t(
								"research:optunaVisualStrategyBadge",
								"Visual Strategy Loaded",
							)}
						</span>
					</div>

					{hasHeavyBlocks ? (
						<div className="flex items-center gap-2 text-amber-600 dark:text-amber-400 mt-1">
							<Cpu className="w-4 h-4 shrink-0" />
							<div className="text-xs leading-tight">
								<span className="font-bold">
									{t(
										"research:optunaPrecisionEngine",
										"Precision Mode (DepthSightBacktester)",
									)}
								</span>
								<p className="opacity-80 text-[10px] mt-0.5">
									{t(
										"research:optunaPrecisionDesc",
										"Heavy L2/DCA blocks detected. Calculation will take a bit longer (~2 min).",
									)}
								</p>
							</div>
						</div>
					) : (
						<div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400 mt-1">
							<Zap className="w-4 h-4 shrink-0" />
							<div className="text-xs leading-tight">
								<span className="font-bold">
									{t(
										"research:optunaTurboEngine",
										"Turbo Mode (FastVectorBacktester)",
									)}
								</span>
								<p className="opacity-80 text-[10px] mt-0.5">
									{t(
										"research:optunaTurboDesc",
										"Lightweight blocks. Vector optimization will take only ~15 seconds.",
									)}
								</p>
							</div>
						</div>
					)}
				</div>
			)}

			{/* Trials Slider */}
			<div className="space-y-3">
				<div className="flex items-center justify-between">
					<div className="flex items-center gap-1.5">
						<Label className="text-sm font-semibold text-foreground">
							{t("research:optunaTrialsLabel", "Number of Trials")}
						</Label>
						<TooltipProvider>
							<Tooltip>
								<TooltipTrigger asChild>
									<HelpCircle className="w-3.5 h-3.5 text-muted-foreground opacity-60 cursor-pointer" />
								</TooltipTrigger>
								<TooltipContent className="max-w-[240px] text-xs">
									{t(
										"research:optunaTrialsTooltip",
										"The more trials, the better the Optuna algorithm will converge to an optimal result.",
									)}
								</TooltipContent>
							</Tooltip>
						</TooltipProvider>
					</div>
					<span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-muted text-muted-foreground">
						{trials}
					</span>
				</div>
				<Slider
					value={[trials]}
					onValueChange={(val) => setTrials(val[0])}
					min={20}
					max={500}
					step={5}
					className="py-1"
				/>
				<div className="flex justify-between text-[10px] text-muted-foreground opacity-60 font-medium">
					<span>20</span>
					<span>250</span>
					<span>500</span>
				</div>
			</div>

			{/* Search Width Slider */}
			<div className="space-y-3">
				<div className="flex items-center justify-between">
					<div className="flex items-center gap-1.5">
						<Label className="text-sm font-semibold text-foreground">
							{t(
								"research:optunaSearchWidthLabel",
								"Search Width",
							)}
						</Label>
						<TooltipProvider>
							<Tooltip>
								<TooltipTrigger asChild>
									<HelpCircle className="w-3.5 h-3.5 text-muted-foreground opacity-60 cursor-pointer" />
								</TooltipTrigger>
								<TooltipContent className="max-w-[240px] text-xs">
									{t(
										"research:optunaSearchWidthTooltip",
										"Range of initial parameter variation. ±50% means the optimizer will search for solutions in the interval from 0.5x to 1.5x of the current parameter values.",
									)}
								</TooltipContent>
							</Tooltip>
						</TooltipProvider>
					</div>
					<span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-muted text-emerald-600 dark:text-emerald-400">
						±{searchWidth}%
					</span>
				</div>
				<Slider
					value={[searchWidth]}
					onValueChange={(val) => setSearchWidth(val[0])}
					min={10}
					max={100}
					step={5}
					className="py-1"
				/>
				<div className="flex justify-between text-[10px] text-muted-foreground opacity-60 font-medium">
					<span>±10%</span>
					<span>±50%</span>
					<span>±100%</span>
				</div>
			</div>

			{/* Advanced Settings Accordion */}
			<Accordion type="single" collapsible className="w-full">
				<AccordionItem value="advanced-settings" className="border-none">
					<AccordionTrigger className="text-xs font-semibold text-muted-foreground hover:no-underline py-2">
						{t("research:optunaAdvancedSettings", "Advanced Settings")}
					</AccordionTrigger>
					<AccordionContent className="pt-3 pb-1 space-y-4">
						{/* Objective Metric Selector */}
						<div className="space-y-2">
							<Label className="text-xs font-semibold text-muted-foreground">
								{t("research:optunaMetricLabel", "Optimization Target Metric")}
							</Label>
							<Select value={metric} onValueChange={setMetric}>
								<SelectTrigger className="w-full text-xs">
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="sharpe_ratio" className="text-xs">
										{t(
											"research:optunaMetricSharpe",
											"Sharpe Ratio",
										)}
									</SelectItem>
									<SelectItem value="sortino_ratio" className="text-xs">
										{t(
											"research:optunaMetricSortino",
											"Sortino Ratio",
										)}
									</SelectItem>
									<SelectItem value="profit_factor" className="text-xs">
										{t(
											"research:optunaMetricProfitFactor",
											"Profit Factor",
										)}
									</SelectItem>
									<SelectItem value="total_pnl_pct" className="text-xs">
										{t(
											"research:optunaMetricTotalPnl",
											"Total PnL %",
										)}
									</SelectItem>
								</SelectContent>
							</Select>
						</div>
					</AccordionContent>
				</AccordionItem>
			</Accordion>
		</div>
	);
};
