// frontend/src/components/research/DecisionTraceTree.tsx

import {
	AreaChart,
	CandlestickChart,
	CheckCircle2,
	ChevronDown,
	ChevronRight,
	Combine,
	Gauge,
	GitMerge,
	Layers,
	Move,
	Settings2,
	Sigma,
	Signal,
	Target,
	TrendingUp,
	XCircle,
} from "lucide-react";
import React from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

export interface TraceNode {
	id: string;
	type: string;
	result: boolean;
	details?: Record<string, unknown> | string;
	children?: TraceNode[];
}

const ICONS: Record<string, React.ElementType> = {
	AND: Combine,
	OR: GitMerge,
	market_activity: Gauge,
	order_book_analysis: Layers,
	significant_level: AreaChart,
	trend_direction: TrendingUp,
	round_level: Target,
	volume_confirmation: Signal,
	pattern: CandlestickChart,
	price_condition: Sigma,
	ma_cross_condition: Move,
	rsi_condition: Settings2,
	tape_acceleration: Gauge,
	local_level: AreaChart,
	open_interest: Layers,
	price_consolidation: TrendingUp,
};

const NodeTitle: React.FC<{ type: string }> = ({ type }) => {
	const Icon = ICONS[type] || CandlestickChart;
	const { t, i18n } = useTranslation("strategy-editor");

	// Safety check for undefined type
	if (!type) {
		return (
			<div className="flex flex-shrink-0 items-center gap-2 font-semibold">
				<CandlestickChart className="w-5 h-5" />
				<span>Unknown</span>
			</div>
		);
	}

	const titleKey = `components.${type}_title`;
	const formattedType = i18n.exists(titleKey, { ns: "strategy-editor" })
		? t(titleKey)
		: type.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());

	return (
		<div className="flex flex-shrink-0 items-center gap-2 font-semibold">
			<Icon className="w-5 h-5" />
			<span>{formattedType}</span>
		</div>
	);
};

const ResultBadge: React.FC<{ result: boolean }> = ({ result }) => {
	const { t } = useTranslation("research");
	const commonClasses =
		"flex flex-shrink-0 items-center justify-center w-6 h-6 rounded-full";
	return result ? (
		<div
			className={cn(commonClasses, "bg-profit/20 text-profit")}
			title={t("decisionTraceTree.conditionMet")}
		>
			<CheckCircle2 className="w-4 h-4" />
		</div>
	) : (
		<div
			className={cn(commonClasses, "bg-loss/20 text-loss")}
			title={t("decisionTraceTree.conditionNotMet")}
		>
			<XCircle className="w-4 h-4" />
		</div>
	);
};

const NodeDetails: React.FC<{ details: Record<string, unknown> | string }> = ({
	details,
}) => {
	if (!details) return null;
	let detailString: string;

	if (typeof details === "string") {
		detailString = details;
	} else if (typeof details === "object") {
		detailString = Object.entries(details)
			.map(([key, value]) => {
				const formattedValue =
					typeof value === "number"
						? parseFloat(value.toFixed(4))
						: JSON.stringify(value);
				return `${key}: ${formattedValue}`;
			})
			.join(", ");
	} else {
		return null;
	}

	// Allow wrapping for better readability in narrow tree panel
	return (
		<p className="text-xs text-muted-foreground break-all whitespace-normal">
			({detailString})
		</p>
	);
};

interface TraceNodeProps {
	node: TraceNode;
}

const TraceNodeComponent: React.FC<TraceNodeProps> = ({ node }) => {
	const [isExpanded, setIsExpanded] = React.useState(true);
	const isContainer = node.type === "AND" || node.type === "OR";
	const nodeColorClass = isContainer
		? node.type === "AND"
			? "border-primary/40"
			: "border-yellow-500/40"
		: "border-border";

	const hasChildren = node.children && node.children.length > 0;

	return (
		<div
			className={cn(
				"bg-secondary/20 border rounded-lg transition-all duration-200 min-w-0 w-full overflow-hidden",
				nodeColorClass,
				isContainer ? "p-1.5" : "p-2",
			)}
		>
			<div className="flex justify-between items-start gap-2">
				<div className="flex items-start gap-1.5 flex-grow min-w-0">
					{isContainer && hasChildren && (
						<button
							onClick={() => setIsExpanded(!isExpanded)}
							className="mt-1 flex-shrink-0 text-muted-foreground hover:text-foreground transition-colors"
						>
							{isExpanded ? (
								<ChevronDown className="w-4 h-4" />
							) : (
								<ChevronRight className="w-4 h-4" />
							)}
						</button>
					)}
					<div className="flex-grow min-w-0 overflow-hidden">
						<NodeTitle type={node.type} />
						{isExpanded && node.details !== undefined && (
							<NodeDetails details={node.details} />
						)}
					</div>
				</div>
				<ResultBadge result={node.result} />
			</div>

			{isContainer && hasChildren && isExpanded && (
				<div className="pl-3.5 pt-1.5 space-y-2 border-l border-dashed border-muted-foreground/20 ml-2 min-w-0">
					{node.children?.map((childNode, index) => (
						<TraceNodeComponent
							key={`${childNode.id}-${index}`}
							node={childNode}
						/>
					))}
				</div>
			)}
		</div>
	);
};

interface DecisionTraceTreeProps {
	trace: TraceNode;
}

export const DecisionTraceTree: React.FC<DecisionTraceTreeProps> = ({
	trace,
}) => {
	return (
		<div className="font-sans text-foreground p-1 space-y-2">
			<TraceNodeComponent node={trace} />
		</div>
	);
};
