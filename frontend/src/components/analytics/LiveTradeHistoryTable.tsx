// frontend/src/components/analytics/LiveTradeHistoryTable.tsx

import { format } from "date-fns";
import {
	ChevronLeft,
	ChevronRight,
	ChevronsLeft,
	ChevronsRight,
	LineChart,
	Search,
	X,
} from "lucide-react";
import type React from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { formatCryptoPrice } from "@/lib/formatters";
import type { TradeData } from "@/types/api";

interface LiveTradeHistoryTableProps {
	trades: TradeData[];
	isLoading: boolean;
	totalTrades?: number;
	isFiltered?: boolean;
	onTradeSelect?: (trade: TradeData) => void;
	// Pagination props
	currentPage?: number;
	totalPages?: number;
	onPageChange?: (page: number) => void;
}

export const LiveTradeHistoryTable: React.FC<LiveTradeHistoryTableProps> = ({
	trades,
	isLoading,
	totalTrades,
	isFiltered = false,
	onTradeSelect,
	currentPage = 1,
	totalPages = 1,
	onPageChange,
}) => {
	const { t } = useTranslation("analytics");
	const [searchSymbol, setSearchSymbol] = useState("");

	// Filter trades by symbol
	const filteredTrades = useMemo(() => {
		if (!searchSymbol.trim()) return trades;
		const searchLower = searchSymbol.toLowerCase().trim();
		return trades.filter((trade) =>
			trade.symbol.toLowerCase().includes(searchLower),
		);
	}, [trades, searchSymbol]);

	if (isLoading) {
		return <div className="text-center p-8">{t("loadingTrades")}</div>;
	}

	if (!trades || trades.length === 0) {
		return (
			<Card className="mt-6">
				<CardHeader>
					<CardTitle>{t("tradeHistory.title")}</CardTitle>
				</CardHeader>
				<CardContent>
					<div className="text-center text-muted-foreground p-8">
						{t("tradeHistory.noTradesFound")}
					</div>
				</CardContent>
			</Card>
		);
	}

	return (
		<Card className="mt-6 overflow-hidden">
			<CardHeader className="border-b border-border flex flex-row justify-between items-center">
				<div className="flex items-center gap-4">
					<CardTitle>{t("tradeHistory.title")}</CardTitle>
					{totalTrades !== undefined && (
						<span
							className={`text-[11px] px-2 py-0.5 rounded font-bold ${isFiltered || searchSymbol ? "bg-amber-500/10 text-amber-500" : "bg-primary/10 text-primary"}`}
						>
							{filteredTrades.length} of {totalTrades} trades shown
						</span>
					)}
				</div>
				<div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border bg-muted/50 border-border">
					<Search className="w-4 h-4 text-muted-foreground" />
					<input
						type="text"
						placeholder={t("tradeHistory.searchPlaceholder")}
						className="bg-transparent border-none text-xs focus:ring-0 w-32 outline-none"
						value={searchSymbol}
						onChange={(e) => setSearchSymbol(e.target.value)}
					/>
					{searchSymbol && (
						<button
							onClick={() => setSearchSymbol("")}
							className="hover:bg-muted rounded p-0.5 transition-colors"
						>
							<X className="w-3.5 h-3.5 text-muted-foreground" />
						</button>
					)}
				</div>
			</CardHeader>
			<CardContent className="p-0">
				<ScrollArea className="h-[500px]">
					<Table>
						<TableHeader>
							<TableRow className="text-[11px] uppercase tracking-wider font-bold text-muted-foreground bg-muted/50 border-b border-border">
								<TableHead className="px-6 py-4">
									{t("tradeHistory.headers.closeTime")}
								</TableHead>
								<TableHead className="px-6 py-4">
									{t("tradeHistory.headers.symbol")}
								</TableHead>
								<TableHead className="px-6 py-4 text-center">
									{t("tradeHistory.headers.direction")}
								</TableHead>
								<TableHead className="px-6 py-4 text-right">
									{t("tradeHistory.headers.quantity")}
								</TableHead>
								<TableHead className="px-6 py-4 text-right">
									{t("tradeHistory.headers.entryPrice")}
								</TableHead>
								<TableHead className="px-6 py-4 text-right">
									{t("tradeHistory.headers.exitPrice")}
								</TableHead>
								<TableHead className="px-6 py-4 text-right">
									{t("tradeHistory.headers.netPnl")}
								</TableHead>
								<TableHead
									className="px-4 py-4 text-right"
									title="Max Floating Profit"
								>
									{t("tradeHistory.headers.mfp", "MFP")}
								</TableHead>
								<TableHead
									className="px-4 py-4 text-right"
									title="Max Floating Loss"
								>
									{t("tradeHistory.headers.mfl", "MFL")}
								</TableHead>
								<TableHead className="px-6 py-4">
									{t("tradeHistory.headers.exitReason")}
								</TableHead>
								<TableHead className="px-6 py-4 text-right">
									{t("tradeHistory.action")}
								</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody className="divide-y divide-border">
							{filteredTrades.length > 0 ? (
								filteredTrades.map((trade) => {
									const realizedPnl = trade.pnl || 0;
									return (
										<TableRow
											key={trade.id}
											className="hover:bg-muted/30 transition-colors group"
										>
											<TableCell className="px-6 py-4">
												<span className="text-sm font-semibold text-foreground">
													{format(
														new Date(trade.timestamp_close),
														"dd.MM.yyyy",
													)}
												</span>
												<span className="block text-[10px] text-muted-foreground mt-0.5">
													{format(new Date(trade.timestamp_close), "HH:mm:ss")}
												</span>
											</TableCell>
											<TableCell className="px-6 py-4 font-bold text-foreground">
												{trade.symbol}
											</TableCell>
											<TableCell className="px-6 py-4 text-center">
												<span
													className={`inline-block px-2.5 py-1 rounded-lg text-[9px] font-black tracking-widest ${
														["LONG", "BUY"].includes(trade.direction as string)
															? "bg-profit/10 text-profit border border-profit/20"
															: "bg-loss/10 text-loss border border-loss/20"
													}`}
												>
													{trade.direction}
												</span>
											</TableCell>
											<TableCell className="px-6 py-4 text-right font-mono text-sm text-foreground">
												{trade.quantity}
											</TableCell>
											<TableCell className="px-6 py-4 text-right font-mono text-sm text-foreground">
												${formatCryptoPrice(trade.entry_price)}
											</TableCell>
											<TableCell className="px-6 py-4 text-right font-mono text-sm text-foreground">
												${formatCryptoPrice(trade.exit_price)}
											</TableCell>
											<TableCell
												className={`px-6 py-4 text-right font-mono font-bold text-base ${realizedPnl >= 0 ? "text-profit" : "text-loss"}`}
											>
												{realizedPnl >= 0 ? "+" : ""}
												{realizedPnl.toFixed(2)}
											</TableCell>
											<TableCell className="px-4 py-4 text-right font-mono text-sm text-profit">
												{trade.max_floating_profit != null
													? `+${trade.max_floating_profit.toFixed(2)}`
													: "-"}
											</TableCell>
											<TableCell className="px-4 py-4 text-right font-mono text-sm text-loss">
												{trade.max_floating_loss != null
													? `-${trade.max_floating_loss.toFixed(2)}`
													: "-"}
											</TableCell>
											<TableCell className="px-6 py-4 text-muted-foreground">
												{trade.exit_reason}
											</TableCell>
											<TableCell className="px-6 py-4 text-right">
												<Button
													variant="outline"
													size="sm"
													className="px-4 py-2 text-xs font-bold transition-all hover:bg-primary hover:text-primary-foreground"
													onClick={() => onTradeSelect?.(trade)}
												>
													<LineChart className="w-3.5 h-3.5 mr-1.5" />
													{t("tradeHistory.analyze")}
												</Button>
											</TableCell>
										</TableRow>
									);
								})
							) : (
								<TableRow>
									<TableCell
										colSpan={11}
										className="text-center text-muted-foreground py-8"
									>
										{t("tradeHistory.noSearchResults")} "{searchSymbol}"
									</TableCell>
								</TableRow>
							)}
						</TableBody>
					</Table>
				</ScrollArea>

				{/* Pagination */}
				{onPageChange && totalPages > 1 && (
					<div className="flex items-center justify-between px-6 py-4 border-t border-border bg-muted/30">
						<div className="text-sm text-muted-foreground">
							{t("pagination.page", "Page")} {currentPage}{" "}
							{t("pagination.of", "of")} {totalPages}
						</div>
						<div className="flex items-center gap-1">
							<Button
								variant="outline"
								size="sm"
								className="h-8 w-8 p-0"
								onClick={() => onPageChange(1)}
								disabled={currentPage === 1}
								title={t("pagination.first", "First")}
							>
								<ChevronsLeft className="h-4 w-4" />
							</Button>
							<Button
								variant="outline"
								size="sm"
								className="h-8 w-8 p-0"
								onClick={() => onPageChange(currentPage - 1)}
								disabled={currentPage === 1}
								title={t("pagination.previous", "Previous")}
							>
								<ChevronLeft className="h-4 w-4" />
							</Button>
							<span className="px-3 text-sm font-medium">{currentPage}</span>
							<Button
								variant="outline"
								size="sm"
								className="h-8 w-8 p-0"
								onClick={() => onPageChange(currentPage + 1)}
								disabled={currentPage === totalPages}
								title={t("pagination.next", "Next")}
							>
								<ChevronRight className="h-4 w-4" />
							</Button>
							<Button
								variant="outline"
								size="sm"
								className="h-8 w-8 p-0"
								onClick={() => onPageChange(totalPages)}
								disabled={currentPage === totalPages}
								title={t("pagination.last", "Last")}
							>
								<ChevronsRight className="h-4 w-4" />
							</Button>
						</div>
					</div>
				)}
			</CardContent>
		</Card>
	);
};
