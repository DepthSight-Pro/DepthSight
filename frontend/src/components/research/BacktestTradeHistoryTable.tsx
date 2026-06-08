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
	Card,
	CardContent,
	CardDescription,
	CardFooter,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
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
		<Card className="h-full flex flex-col">
			<CardHeader className="shrink-0">
				<CardTitle>{t("tradeHistoryTable.title")}</CardTitle>
				<CardDescription>{t("tradeHistoryTable.description")}</CardDescription>
			</CardHeader>
			<CardContent className="flex-grow overflow-auto p-0">
				{/* --- Wrapper for tooltips --- */}
				<TooltipProvider>
					<Table>
						<TableHeader className="sticky top-0 bg-card z-10">
							<TableRow>
								<TableHead>{t("tradeHistoryTable.headerExitTime")}</TableHead>
								<TableHead>{t("tradeHistoryTable.headerDirection")}</TableHead>
								<TableHead className="text-right">
									{t("tradeHistoryTable.headerEntry")}
								</TableHead>
								<TableHead className="text-right">
									{t("tradeHistoryTable.headerExit")}
								</TableHead>
								<TableHead className="text-right">
									{t("tradeHistoryTable.headerPnl")}
								</TableHead>
								<TableHead className="text-center">
									{t("tradeHistoryTable.headerTrace")}
								</TableHead>
								<TableHead className="text-center">
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
										className="h-24 text-center text-destructive"
									>
										Error loading trades
									</TableCell>
								</TableRow>
							) : trades.length === 0 ? (
								<TableRow>
									<TableCell
										colSpan={7}
										className="h-24 text-center text-muted-foreground"
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
										<TableCell className="font-mono text-xs text-muted-foreground">
											{trade.timestamp_exit
												? format(new Date(trade.timestamp_exit), "HH:mm:ss", {
														locale: currentLocale === "ru" ? ru : enUS,
													})
												: t("tradeHistoryTable.inProgress", "Running...")}
										</TableCell>
										<TableCell>
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
										<TableCell className="text-right font-mono text-xs">
											${trade.entry_price.toFixed(2)}
										</TableCell>
										<TableCell className="text-right font-mono text-xs">
											${trade.exit_price.toFixed(2)}
										</TableCell>
										<TableCell
											className={`text-right font-mono text-sm font-medium ${trade.pnl >= 0 ? "text-profit" : "text-loss"}`}
										>
											{trade.pnl >= 0 ? "+" : ""}
											{trade.pnl.toFixed(2)}
										</TableCell>
										<TableCell className="text-center">
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
										<TableCell className="text-center">
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
			</CardContent>
			{totalTrades > 0 && (
				<CardFooter className="flex items-center justify-between border-t pt-4">
					<div className="text-sm text-muted-foreground">
						{t("common:pagination.totalItems", { count: totalTrades })}
					</div>
					<div className="flex items-center space-x-2">
						<Button
							variant="outline"
							size="sm"
							onClick={() => setPage((p) => Math.max(1, p - 1))}
							disabled={page <= 1}
						>
							<ChevronLeft className="h-4 w-4" />
						</Button>
						<span className="text-sm font-medium">
							{t("common:pagination.pageInfo", {
								page: page,
								totalPages: totalPages > 0 ? totalPages : 1,
							})}
						</span>
						<Button
							variant="outline"
							size="sm"
							onClick={() => setPage((p) => p + 1)}
							disabled={page >= totalPages}
						>
							<ChevronRight className="h-4 w-4" />
						</Button>
					</div>
				</CardFooter>
			)}
		</Card>
	);
};
