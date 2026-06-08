// src/components/research/DecisionTraceDialog.tsx

import { Loader2 } from "lucide-react";
import React from "react";
import { useTranslation } from "react-i18next";
import {
	FoundationChart,
	type KlineData,
	type LevelData,
	type MarkerData,
	type SubchartPoint,
	type TradeOverlayData,
	type ZoneData,
} from "@/components/diagnostics/FoundationChart";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import {
	ResizableHandle,
	ResizablePanel,
	ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useKlines } from "@/lib/api";
import type {
	BacktestRunDetailsData,
	BacktestTrade,
	TradeExecution,
} from "@/types/api";
import { DecisionTraceTree, type TraceNode } from "./DecisionTraceTree";

interface DecisionTraceDialogProps {
	trade: BacktestTrade | null;
	run: BacktestRunDetailsData;
	isOpen: boolean;
	onClose: () => void;
}

interface TraceVisualizationDetails {
	detected_level?: unknown;
	zone_start_time?: unknown;
	zone_end_time?: unknown;
	trend?: unknown;
	timestamp?: unknown;
	series?: SubchartPoint[];
	correlation_series?: SubchartPoint[];
	oi_series?: SubchartPoint[];
}

const TIMEFRAME_OPTIONS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
type ChartTimeframe = (typeof TIMEFRAME_OPTIONS)[number];

const TIMEFRAME_MS: Record<ChartTimeframe, number> = {
	"1m": 60 * 1000,
	"5m": 5 * 60 * 1000,
	"15m": 15 * 60 * 1000,
	"1h": 60 * 60 * 1000,
	"4h": 4 * 60 * 60 * 1000,
	"1d": 24 * 60 * 60 * 1000,
};

const toTimestampMs = (
	value: string | number | null | undefined,
): number | null => {
	if (value == null) return null;
	if (typeof value === "number") {
		const normalized = value > 1_000_000_000_000 ? value : value * 1000;
		return Number.isFinite(normalized) ? normalized : null;
	}

	const timestamp = new Date(value).getTime();
	return Number.isFinite(timestamp) ? timestamp : null;
};

const parseTraceForVisualizations = (
	trace: TraceNode | null,
	tradeEntryTime: number,
) => {
	const visualizations: {
		levels: LevelData[];
		markers: MarkerData[];
		zones: ZoneData[];
		subcharts: Record<string, SubchartPoint[]>;
	} = { levels: [], markers: [], zones: [], subcharts: {} };

	if (!trace) return visualizations;

	function traverse(node: TraceNode) {
		if (node.details && typeof node.details === "object") {
			const details = node.details as TraceVisualizationDetails;

			if (
				["significant_level", "local_level", "round_level"].includes(
					node.type,
				) &&
				typeof details.detected_level === "number"
			) {
				visualizations.levels.push({
					time: tradeEntryTime,
					price: details.detected_level,
					type: node.type,
					label: node.type.replace("_level", "").toUpperCase(),
				});
			}

			if (
				["trend_direction", "price_consolidation"].includes(node.type) &&
				details.zone_start_time &&
				details.zone_end_time
			) {
				visualizations.zones.push({
					startTime: new Date(String(details.zone_start_time)).getTime() / 1000,
					endTime: new Date(String(details.zone_end_time)).getTime() / 1000,
					type: node.type,
					label:
						typeof details.trend === "string" ? details.trend : "Consolidation",
				});
			}

			if (
				[
					"volume_confirmation",
					"tape_acceleration",
					"classic_pattern",
				].includes(node.type) &&
				details.timestamp
			) {
				visualizations.markers.push({
					time: new Date(String(details.timestamp)).getTime() / 1000,
					text: node.type.charAt(0).toUpperCase(),
					position: "belowBar",
					shape: "circle",
					color: node.type === "tape_acceleration" ? "#2196F3" : "#ff9800",
				});
			}

			if (details.series && Array.isArray(details.series)) {
				const subchartName = node.type.replace("_filter", "");
				visualizations.subcharts[subchartName] = details.series;
			}
			if (
				node.type === "correlation" &&
				Array.isArray(details.correlation_series)
			) {
				visualizations.subcharts.correlation = details.correlation_series;
			}
			if (node.type === "open_interest" && Array.isArray(details.oi_series)) {
				visualizations.subcharts.open_interest = details.oi_series;
			}
		}

		if (node.children) {
			node.children.forEach(traverse);
		}
	}

	traverse(trace);
	return visualizations;
};

export const DecisionTraceDialog: React.FC<DecisionTraceDialogProps> = ({
	trade,
	run,
	isOpen,
	onClose,
}) => {
	const { t } = useTranslation("research");
	const [timeframe, setTimeframe] = React.useState<ChartTimeframe>("1m");

	const timeRange = React.useMemo(() => {
		if (!trade) return null;
		const allTimestamps = [
			toTimestampMs(trade.timestamp_entry),
			toTimestampMs(trade.timestamp_exit),
			...(trade.executions?.map((execution) =>
				toTimestampMs(execution.timestamp),
			) || []),
		].filter((timestamp): timestamp is number => timestamp !== null);

		if (allTimestamps.length === 0) return null;

		const entryTime = Math.min(...allTimestamps);
		const exitTime = Math.max(...allTimestamps);
		const duration = exitTime - entryTime;
		const padding = Math.max(
			duration * 1.5,
			TIMEFRAME_MS[timeframe] * 90,
			30 * 60 * 1000,
		);
		return {
			startTime: entryTime - padding,
			endTime: exitTime + padding,
		};
	}, [trade, timeframe]);

	const initialVisibleRange = React.useMemo(() => {
		if (!trade) return undefined;
		const allTimestamps = [
			toTimestampMs(trade.timestamp_entry),
			toTimestampMs(trade.timestamp_exit),
			...(trade.executions?.map((execution) =>
				toTimestampMs(execution.timestamp),
			) || []),
		].filter((timestamp): timestamp is number => timestamp !== null);

		if (allTimestamps.length === 0) return undefined;

		const entryTime = Math.min(...allTimestamps);
		const exitTime = Math.max(...allTimestamps);
		const duration = Math.max(exitTime - entryTime, TIMEFRAME_MS[timeframe]);
		const paddingBefore = Math.max(
			duration * 0.35,
			TIMEFRAME_MS[timeframe] * 20,
			5 * 60 * 1000,
		);
		const paddingAfter = Math.max(
			duration * 0.65,
			TIMEFRAME_MS[timeframe] * 30,
			10 * 60 * 1000,
		);

		return {
			from: Math.floor((entryTime - paddingBefore) / 1000),
			to: Math.floor((exitTime + paddingAfter) / 1000),
		};
	}, [trade, timeframe]);

	const { data: klines, isLoading } = useKlines(
		{
			symbol: run.symbol,
			interval: timeframe,
			startTime: timeRange?.startTime,
			endTime: timeRange?.endTime,
			runId: run.id,
		},
		{ enabled: isOpen && !!trade && !!timeRange },
	);

	const tradeEntryTimestamp = React.useMemo(
		() => (trade ? new Date(trade.timestamp_entry).getTime() / 1000 : 0),
		[trade],
	);

	const visualizations = React.useMemo(() => {
		if (!trade) return { levels: [], markers: [], zones: [], subcharts: {} };
		const trace = trade.decision_trace_json as TraceNode | null;
		return parseTraceForVisualizations(trace, tradeEntryTimestamp);
	}, [trade, tradeEntryTimestamp]);

	const tradeOverlay = React.useMemo<TradeOverlayData | undefined>(() => {
		if (!trade) return undefined;
		const executions: TradeExecution[] =
			trade.executions && trade.executions.length > 0
				? trade.executions
				: [
						{
							timestamp: trade.timestamp_entry,
							price: trade.entry_price,
							quantity: trade.quantity,
							type: "ENTRY",
						},
						{
							timestamp: trade.timestamp_exit,
							price: trade.exit_price,
							quantity: trade.quantity,
							type: "EXIT",
						},
					];

		return {
			executions,
			entryPrice: trade.entry_price,
			exitPrice: trade.exit_price,
			entryTime: trade.timestamp_entry,
			exitTime: trade.timestamp_exit,
			direction: trade.direction,
			showAverageLines: true,
			showPercent: true,
			showLabels: true,
		};
	}, [trade]);

	const klineData: KlineData[] | undefined = klines?.map((kline) => ({
		time: Number(kline[0]) / 1000,
		open: Number(kline[1]),
		high: Number(kline[2]),
		low: Number(kline[3]),
		close: Number(kline[4]),
		volume: Number(kline[5]),
	}));

	if (!trade) {
		return null;
	}

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent className="max-w-[90vw] w-full h-[90vh] flex flex-col p-4">
				<DialogHeader className="flex-shrink-0">
					<div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
						<div className="min-w-0">
							<DialogTitle>
								{t("decisionTraceDialog.title", { tradeId: trade.id })}
							</DialogTitle>
							<DialogDescription>
								{t("decisionTraceDialog.description", {
									direction: trade.direction,
									entryPrice: trade.entry_price.toFixed(2),
									pnl: trade.pnl.toFixed(2),
								})}
							</DialogDescription>
						</div>
						<ToggleGroup
							type="single"
							aria-label="Timeframe"
							value={timeframe}
							onValueChange={(value) => {
								if (value) setTimeframe(value as ChartTimeframe);
							}}
							className="justify-start rounded-md border bg-background p-1 sm:justify-center"
							size="sm"
						>
							{TIMEFRAME_OPTIONS.map((option) => (
								<ToggleGroupItem
									key={option}
									value={option}
									aria-label={`Select ${option}`}
									className="px-3"
								>
									{option}
								</ToggleGroupItem>
							))}
						</ToggleGroup>
					</div>
				</DialogHeader>

				<ResizablePanelGroup
					direction="horizontal"
					className="flex-grow min-h-0 rounded-lg border mt-2"
				>
					<ResizablePanel defaultSize={30} minSize={20}>
						<div className="flex flex-col h-full p-2">
							<h3 className="text-lg font-semibold mb-2 flex-shrink-0">
								{t("decisionTraceDialog.treeTitle")}
							</h3>
							<ScrollArea className="flex-grow">
								{trade.decision_trace_json ? (
									<DecisionTraceTree
										trace={trade.decision_trace_json as unknown as TraceNode}
									/>
								) : (
									<p className="text-muted-foreground p-4">
										{t("decisionTraceDialog.noTraceData")}
									</p>
								)}
							</ScrollArea>
						</div>
					</ResizablePanel>
					<ResizableHandle withHandle />
					<ResizablePanel defaultSize={70}>
						<div className="h-full w-full p-2">
							{isLoading && (
								<div className="h-full flex items-center justify-center">
									<Loader2 className="w-8 h-8 animate-spin" />
								</div>
							)}
							{klineData && !isLoading && (
								<FoundationChart
									klines={klineData}
									visualizations={visualizations}
									tradeOverlay={tradeOverlay}
									initialVisibleRange={initialVisibleRange}
								/>
							)}
							{!klineData && !isLoading && (
								<div className="h-full flex items-center justify-center text-muted-foreground">
									{t("decisionTraceDialog.noKlineData")}
								</div>
							)}
						</div>
					</ResizablePanel>
				</ResizablePanelGroup>
			</DialogContent>
		</Dialog>
	);
};
