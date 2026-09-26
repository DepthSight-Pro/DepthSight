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
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { ExchangeBadge } from "@/components/layout/AccountSelector";
import { formatCryptoPrice } from "@/lib/formatters";
import { exchangeLabels, normalizeExchangeKey } from "@/lib/exchanges";
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
			<div className="glass mt-6 rounded-2xl border border-white/10 p-5 shadow-2xl backdrop-blur-xl animate-fade-up">
				<div className="text-[13px] font-semibold text-white/90">
					{t("tradeHistory.title", "Trade History")}
				</div>
				<div className="text-center text-white/40 font-mono text-xs p-8">
					{t("tradeHistory.noTradesFound", "No trades found.")}
				</div>
			</div>
		);
	}

	return (
		<div className="glass mt-6 rounded-2xl border border-white/10 overflow-hidden shadow-2xl backdrop-blur-xl animate-fade-up">
			<div className="border-b border-white/5 p-4 flex flex-row justify-between items-center flex-wrap gap-3">
				<div className="flex items-center gap-3">
					<span className="text-[13px] font-semibold text-white/90">
						{t("tradeHistory.title", "Trade History")}
					</span>
					{totalTrades !== undefined && (
						<span
							className={`text-[10px] font-mono px-2 py-0.5 rounded-md font-bold uppercase tracking-wider ${isFiltered || searchSymbol ? "bg-amber-500/10 text-amber-400 border border-amber-500/20" : "bg-cyan/10 text-cyan border border-cyan/20"}`}
						>
							{filteredTrades.length} / {totalTrades} trades
						</span>
					)}
				</div>
				<div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border bg-card dark:bg-white/[0.03] border-border dark:border-white/10 text-foreground dark:text-white">
					<Search className="w-3.5 h-3.5 text-muted-foreground dark:text-white/40" />
					<input
						type="text"
						placeholder={t("tradeHistory.searchPlaceholder", "Search symbol...")}
						className="bg-transparent border-none text-xs font-mono text-foreground dark:text-white focus:ring-0 w-32 outline-none placeholder:text-muted-foreground dark:placeholder:text-white/30"
						value={searchSymbol}
						onChange={(e) => setSearchSymbol(e.target.value)}
					/>
					{searchSymbol && (
						<button
							onClick={() => setSearchSymbol("")}
							className="hover:bg-muted dark:hover:bg-white/10 rounded p-0.5 transition-colors"
						>
							<X className="w-3.5 h-3.5 text-muted-foreground dark:text-white/40" />
						</button>
					)}
				</div>
			</div>
			<div className="w-full overflow-auto max-h-[500px]">
					<Table className="w-full min-w-[1050px]">
						<TableHeader>
							<TableRow className="text-[10.5px] uppercase tracking-wider font-mono font-semibold text-white/50 bg-white/[0.02] border-b border-white/5 hover:bg-transparent">
								<TableHead className="px-6 py-3.5 whitespace-nowrap">
									{t("tradeHistory.headers.closeTime")}
								</TableHead>
								<TableHead className="px-6 py-4 whitespace-nowrap">
									{t("tradeHistory.headers.symbol")}
								</TableHead>
								<TableHead className="px-6 py-4 whitespace-nowrap">
									{t("tradeHistory.headers.exchange", "Exchange")}
								</TableHead>
								<TableHead className="px-6 py-4 text-center whitespace-nowrap">
									{t("tradeHistory.headers.direction")}
								</TableHead>
								<TableHead className="px-6 py-4 text-right whitespace-nowrap">
									{t("tradeHistory.headers.quantity")}
								</TableHead>
								<TableHead className="px-6 py-4 text-right whitespace-nowrap">
									{t("tradeHistory.headers.entryPrice")}
								</TableHead>
								<TableHead className="px-6 py-4 text-right whitespace-nowrap">
									{t("tradeHistory.headers.exitPrice")}
								</TableHead>
								<TableHead className="px-6 py-4 text-right whitespace-nowrap">
									{t("tradeHistory.headers.netPnl")}
								</TableHead>
								<TableHead
									className="px-4 py-4 text-right whitespace-nowrap"
									title="Max Floating Profit"
								>
									{t("tradeHistory.headers.mfp", "MFP")}
								</TableHead>
								<TableHead
									className="px-4 py-4 text-right whitespace-nowrap"
									title="Max Floating Loss"
								>
									{t("tradeHistory.headers.mfl", "MFL")}
								</TableHead>
								<TableHead className="px-6 py-4 whitespace-nowrap">
									{t("tradeHistory.headers.exitReason")}
								</TableHead>
								<TableHead className="px-6 py-4 text-right whitespace-nowrap">
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
											<TableCell className="px-6 py-4 whitespace-nowrap">
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
											<TableCell className="px-6 py-4 font-bold text-foreground whitespace-nowrap">
												{trade.symbol}
											</TableCell>
											<TableCell className="px-6 py-4 whitespace-nowrap">
												<div className="flex items-center gap-2.5">
													<ExchangeBadge
														exchange={trade.exchange}
														size="sm"
														className="shadow-sm border-white/10"
													/>
													<span className="text-xs uppercase font-semibold text-white/90 leading-tight">
														{(() => {
															const ex = normalizeExchangeKey(trade.exchange);
															return (
																(ex ? exchangeLabels[ex] : null) ||
																trade.exchange ||
																"—"
															);
														})()}
													</span>
												</div>
											</TableCell>
											<TableCell className="px-6 py-4 text-center whitespace-nowrap">
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
											<TableCell className="px-6 py-4 text-right font-mono text-sm text-foreground whitespace-nowrap">
												{trade.quantity}
											</TableCell>
											<TableCell className="px-6 py-4 text-right font-mono text-sm text-foreground whitespace-nowrap">
												${formatCryptoPrice(trade.entry_price)}
											</TableCell>
											<TableCell className="px-6 py-4 text-right font-mono text-sm text-foreground whitespace-nowrap">
												${formatCryptoPrice(trade.exit_price)}
											</TableCell>
											<TableCell
												className={`px-6 py-4 text-right font-mono font-bold text-base whitespace-nowrap ${realizedPnl >= 0 ? "text-profit" : "text-loss"}`}
											>
												{realizedPnl >= 0 ? "+" : ""}
												{realizedPnl.toFixed(2)}
											</TableCell>
											<TableCell className="px-4 py-4 text-right font-mono text-sm text-profit whitespace-nowrap">
												{trade.max_floating_profit != null
													? `+${trade.max_floating_profit.toFixed(2)}`
													: "-"}
											</TableCell>
											<TableCell className="px-4 py-4 text-right font-mono text-sm text-loss whitespace-nowrap">
												{trade.max_floating_loss != null
													? `-${trade.max_floating_loss.toFixed(2)}`
													: "-"}
											</TableCell>
											<TableCell className="px-6 py-4 text-muted-foreground whitespace-nowrap">
												{trade.exit_reason}
											</TableCell>
											<TableCell className="px-6 py-4 text-right whitespace-nowrap">
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
			</div>

				{/* Pagination */}
				{onPageChange && totalPages > 1 && (
					<div className="flex flex-wrap items-center justify-between px-4 py-3 sm:px-6 sm:py-4 border-t border-border bg-muted/30 gap-2">
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
		</div>
	);
};
