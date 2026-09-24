// src/components/research/BacktestTradeHistoryTable.tsx

import { format } from "date-fns";
import { enUS, ru } from "date-fns/locale";
import {
	ChevronLeft,
	ChevronRight,
	GitBranchPlus,
	TestTube2,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { usePaginatedTrades } from "@/lib/api";
import type { BacktestTrade } from "@/types/api";
import { Skeleton } from "../ui/skeleton";
import { DecisionTraceTree, type TraceNode } from "./DecisionTraceTree";

// --- Updating the props interface ---
interface BacktestTradeHistoryTableProps {
	runId: string;
	status: "pending" | "running" | "completed" | "failed";
	onViewTradeOnChart: (trade: BacktestTrade) => void; // New prop for opening the modal window
}

const PAGE_SIZE = 20;

const hasTradeChartData = (trade: BacktestTrade): boolean => {
	return Boolean(
		(trade.executions && trade.executions.length > 0) ||
			(trade.timestamp_entry &&
				trade.timestamp_exit &&
				trade.entry_price != null &&
				trade.exit_price != null),
	);
};

export const BacktestTradeHistoryTable: React.FC<
	BacktestTradeHistoryTableProps
> = ({ runId, status, onViewTradeOnChart }) => {
	const { t, i18n } = useTranslation(["research", "common"]);
	const [page, setPage] = useState(1);

	const { data, isLoading, isError, isFetching } = usePaginatedTrades(
		runId,
		page,
		PAGE_SIZE,
		status,
	);

	const trades = data?.trades || [];
	const totalTrades = data?.total || 0;
	const totalPages = Math.ceil(totalTrades / PAGE_SIZE);
	const currentLocale = i18n.language;

	const renderSkeletons = () => {
		return Array.from({ length: 5 }).map((_, index) => (
			<TableRow key={`skeleton-${index}`}>
				<TableCell colSpan={7}>
					<Skeleton className="h-6 w-full" />
				</TableCell>
			</TableRow>
		));
	};

	return (
		<div className="h-full glass rounded-2xl border border-white/10 shadow-xl overflow-hidden flex flex-col">
			<div className="p-4 sm:p-6 border-b border-white/5 shrink-0">
				<h3 className="text-base font-bold text-white tracking-tight">{t("tradeHistoryTable.title")}</h3>
				<p className="text-xs text-white/50 mt-1">{t("tradeHistoryTable.description")}</p>
			</div>
			<div className="flex-grow overflow-x-auto p-0">
				{/* --- Wrapper for tooltips --- */}
				<TooltipProvider>
					<Table className="min-w-[650px]">
						<TableHeader className="sticky top-0 bg-white/[0.03] backdrop-blur-md border-b border-white/5 z-10">
							<TableRow className="hover:bg-transparent border-b border-white/5">
								<TableHead className="whitespace-nowrap">{t("tradeHistoryTable.headerExitTime")}</TableHead>
								<TableHead className="whitespace-nowrap">{t("tradeHistoryTable.headerDirection")}</TableHead>
								<TableHead className="text-right whitespace-nowrap">
									{t("tradeHistoryTable.headerEntry")}
								</TableHead>
								<TableHead className="text-right whitespace-nowrap">
									{t("tradeHistoryTable.headerExit")}
								</TableHead>
								<TableHead className="text-right whitespace-nowrap">
									{t("tradeHistoryTable.headerPnl")}
								</TableHead>
								<TableHead className="text-center whitespace-nowrap">
									{t("tradeHistoryTable.headerTrace")}
								</TableHead>
								<TableHead className="text-center whitespace-nowrap">
									{t("tradeHistoryTable.headerVisualize")}
								</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{isLoading ? (
								renderSkeletons()
							) : isError ? (
								<TableRow>
									<TableCell
										colSpan={7}
										className="h-24 text-center text-destructive whitespace-nowrap"
									>
										Error loading trades
									</TableCell>
								</TableRow>
							) : trades.length === 0 ? (
								<TableRow>
									<TableCell
										colSpan={7}
										className="h-24 text-center text-muted-foreground whitespace-nowrap"
									>
										{status === "running"
											? t("tradeHistoryTable.waitingForFirstTrade")
											: t("tradeHistoryTable.noTradesGenerated")}
									</TableCell>
								</TableRow>
							) : (
								trades.map((trade: BacktestTrade) => (
									<TableRow
										key={trade.id}
										className={isFetching ? "opacity-50" : ""}
									>
										<TableCell className="font-mono text-xs text-muted-foreground whitespace-nowrap">
											{trade.timestamp_exit
												? format(new Date(trade.timestamp_exit), "HH:mm:ss", {
														locale: currentLocale === "ru" ? ru : enUS,
													})
												: t("tradeHistoryTable.inProgress", "Running...")}
										</TableCell>
										<TableCell className="whitespace-nowrap">
											<Badge
												variant={
													trade.direction === "LONG" ? "default" : "destructive"
												}
												className={
													trade.direction === "LONG"
														? "bg-green-500 hover:bg-green-600"
														: "bg-red-500 hover:bg-red-600"
												}
											>
												{trade.direction}
											</Badge>
										</TableCell>
										<TableCell className="text-right font-mono text-xs whitespace-nowrap">
											${trade.entry_price.toFixed(2)}
										</TableCell>
										<TableCell className="text-right font-mono text-xs whitespace-nowrap">
											${trade.exit_price.toFixed(2)}
										</TableCell>
										<TableCell
											className={`text-right font-mono text-sm font-medium whitespace-nowrap ${trade.pnl >= 0 ? "text-profit" : "text-loss"}`}
										>
											{trade.pnl >= 0 ? "+" : ""}
											{trade.pnl.toFixed(2)}
										</TableCell>
										<TableCell className="text-center whitespace-nowrap">
											<Popover>
												<PopoverTrigger asChild>
													<Button
														variant="ghost"
														size="icon"
														className="h-6 w-6"
														disabled={!trade.decision_trace_json}
													>
														<GitBranchPlus className="w-4 h-4" />
													</Button>
												</PopoverTrigger>
												<PopoverContent className="w-auto max-w-xl max-h-[60vh] p-0 overflow-hidden">
													<div className="h-full p-4 overflow-auto">
														{trade.decision_trace_json ? (
															<DecisionTraceTree
																trace={
																	trade.decision_trace_json as unknown as TraceNode
																}
															/>
														) : (
															<div className="text-center text-muted-foreground p-4">
																{t("tradeHistoryTable.noDecisionTrace")}
															</div>
														)}
													</div>
												</PopoverContent>
											</Popover>
										</TableCell>
										{/* --- New cell with button and tooltip --- */}
										<TableCell className="text-center whitespace-nowrap">
											<Tooltip>
												<TooltipTrigger asChild>
													<Button
														variant="ghost"
														size="icon"
														className="h-6 w-6"
														onClick={() => onViewTradeOnChart(trade)}
														disabled={!hasTradeChartData(trade)}
													>
														<TestTube2 className="w-4 h-4" />
													</Button>
												</TooltipTrigger>
												<TooltipContent>
													<p>{t("tradeHistoryTable.visualizeTooltip")}</p>
												</TooltipContent>
											</Tooltip>
										</TableCell>
									</TableRow>
								))
							)}
						</TableBody>
					</Table>
				</TooltipProvider>
			</div>
			{totalTrades > 0 && (
				<div className="flex items-center justify-between border-t border-white/5 p-4 shrink-0">
					<div className="text-xs font-mono text-white/50">
						{t("common:pagination.totalItems", { count: totalTrades })}
					</div>
					<div className="flex items-center space-x-2">
						<Button
							variant="outline"
							size="sm"
							className="h-8 w-8 p-0 rounded-lg bg-white/[0.03] border-white/10 text-white hover:bg-white/10"
							onClick={() => setPage((p) => Math.max(1, p - 1))}
							disabled={page <= 1}
						>
							<ChevronLeft className="h-4 w-4" />
						</Button>
						<span className="text-xs font-mono text-white/70">
							{t("common:pagination.pageInfo", {
								page: page,
								totalPages: totalPages > 0 ? totalPages : 1,
							})}
						</span>
						<Button
							variant="outline"
							size="sm"
							className="h-8 w-8 p-0 rounded-lg bg-white/[0.03] border-white/10 text-white hover:bg-white/10"
							onClick={() => setPage((p) => p + 1)}
							disabled={page >= totalPages}
						>
							<ChevronRight className="h-4 w-4" />
						</Button>
					</div>
				</div>
			)}
		</div>
	);
};
