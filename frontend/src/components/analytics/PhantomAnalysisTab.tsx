// src/components/analytics/PhantomAnalysisTab.tsx

import { format } from "date-fns";
import {
	AlertTriangle,
	CheckCircle2,
	ChevronLeft,
	ChevronRight,
	ChevronsLeft,
	ChevronsRight,
	Clock,
	ShieldCheck,
	ThumbsDown,
	TrendingDown,
	TrendingUp,
	XCircle,
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
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { usePhantomStats, usePhantomTrades } from "@/lib/api";
import { formatCryptoPrice } from "@/lib/formatters";
import type { PhantomTrade } from "@/types/api";

export const PhantomAnalysisTab: React.FC = () => {
	const { t } = useTranslation(["analytics", "common"]);

	// Stats Query
	const { data: stats, isLoading: statsLoading } = usePhantomStats({
		days: 30,
	}); // Default 30 days

	// Table State
	const [page, setPage] = useState(1);
	const PAGE_SIZE = 50;
	const { data: tradesData, isLoading: tradesLoading } = usePhantomTrades({
		limit: PAGE_SIZE,
		skip: (page - 1) * PAGE_SIZE,
	});

	const totalPages = tradesData ? Math.ceil(tradesData.total / PAGE_SIZE) : 1;

	if (statsLoading) {
		return (
			<div className="text-center p-8">
				{t("common:loading", "Loading data...")}
			</div>
		);
	}

	if (!stats) {
		return (
			<Card className="h-full">
				<CardContent className="flex flex-col items-center justify-center h-full py-20">
					<AlertTriangle className="w-16 h-16 text-muted-foreground mb-4" />
					<h3 className="text-xl font-semibold mb-2">
						{t("analytics:beAnalysis.noData")}
					</h3>
					<p className="text-muted-foreground text-center max-w-md">
						{t("analytics:beAnalysis.noDataDesc")}
					</p>
				</CardContent>
			</Card>
		);
	}

	return (
		<div className="space-y-6">
			{/* --- Summary Cards --- */}
			<div className="grid grid-cols-1 md:grid-cols-3 gap-4">
				{/* BE Saved */}
				<Card className="bg-gradient-to-br from-emerald-500/10 to-emerald-600/5 border-emerald-500/30">
					<CardContent className="p-6">
						<div className="flex items-center justify-between">
							<div>
								<p className="text-sm text-muted-foreground">
									{t("analytics:beAnalysis.saved")}
								</p>
								<p className="text-3xl font-bold text-emerald-400">
									{stats.sl_would_hit}
								</p>
								<p className="text-sm text-emerald-400">
									{stats.be_saved_pct.toFixed(1)}%
								</p>
							</div>
							<ShieldCheck className="w-12 h-12 text-emerald-400/40" />
						</div>
						<p className="text-xs text-muted-foreground mt-2">
							{t("analytics:beAnalysis.savedDesc")}
						</p>
					</CardContent>
				</Card>

				{/* BE Stolen */}
				<Card className="bg-gradient-to-br from-rose-500/10 to-rose-600/5 border-rose-500/30">
					<CardContent className="p-6">
						<div className="flex items-center justify-between">
							<div>
								<p className="text-sm text-muted-foreground">
									{t("analytics:beAnalysis.stolen")}
								</p>
								<p className="text-3xl font-bold text-rose-400">
									{stats.tp_would_hit}
								</p>
								<p className="text-sm text-rose-400">
									{stats.be_stolen_pct.toFixed(1)}%
								</p>
							</div>
							<ThumbsDown className="w-12 h-12 text-rose-400/40" />
						</div>
						<p className="text-xs text-muted-foreground mt-2">
							{t("analytics:beAnalysis.stolenDesc")}
						</p>
					</CardContent>
				</Card>

				{/* Timeout */}
				<Card className="bg-gradient-to-br from-slate-500/10 to-slate-600/5 border-slate-500/30">
					<CardContent className="p-6">
						<div className="flex items-center justify-between">
							<div>
								<p className="text-sm text-muted-foreground">
									{t("analytics:beAnalysis.timeout")}
								</p>
								<p className="text-3xl font-bold text-slate-400">
									{stats.timeout}
								</p>
								<p className="text-sm text-slate-400">
									{stats.total_be_trades > 0
										? ((stats.timeout / stats.total_be_trades) * 100).toFixed(1)
										: "0.0"}
									%
								</p>
							</div>
							<Clock className="w-12 h-12 text-slate-400/40" />
						</div>
						<p className="text-xs text-muted-foreground mt-2">
							{t("analytics:beAnalysis.timeoutDesc")}
						</p>
					</CardContent>
				</Card>
			</div>

			{/* --- Effectiveness Gauge --- */}
			<Card>
				<CardHeader>
					<CardTitle>{t("analytics:beAnalysis.effectiveness")}</CardTitle>
					<CardDescription>
						{t("analytics:beAnalysis.effectivenessDesc")}
					</CardDescription>
				</CardHeader>
				<CardContent>
					<div className="space-y-4">
						<div className="flex items-center gap-4">
							<div className="flex-1">
								<div className="flex justify-between mb-2">
									<span className="text-sm text-emerald-400 flex items-center gap-1">
										<CheckCircle2 className="w-4 h-4" />{" "}
										{t("analytics:beAnalysis.saved")}
									</span>
									<span className="text-sm text-rose-400 flex items-center gap-1">
										{t("analytics:beAnalysis.stolen")}{" "}
										<XCircle className="w-4 h-4" />
									</span>
								</div>
								<div className="relative h-8 bg-slate-800 rounded-full overflow-hidden">
									{/* Prevent zero-width issues if sum is 0, though shouldn't happen with stats check */}
									<div
										className="absolute left-0 top-0 h-full bg-gradient-to-r from-emerald-500 to-emerald-400"
										style={{ width: `${stats.be_saved_pct}%` }}
									/>
									<div
										className="absolute right-0 top-0 h-full bg-gradient-to-l from-rose-500 to-rose-400"
										style={{ width: `${stats.be_stolen_pct}%` }}
									/>
									<div className="absolute inset-0 flex items-center justify-center">
										<span className="text-sm font-bold text-white drop-shadow-lg">
											{stats.be_saved_pct >= stats.be_stolen_pct
												? `+${(stats.be_saved_pct - stats.be_stolen_pct).toFixed(1)}%`
												: `${(stats.be_saved_pct - stats.be_stolen_pct).toFixed(1)}%`}
										</span>
									</div>
								</div>
							</div>
						</div>

						{stats.be_saved_pct > stats.be_stolen_pct ? (
							<Badge
								variant="default"
								className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
							>
								{t("analytics:beAnalysis.beUseful")}
							</Badge>
						) : (
							<Badge
								variant="default"
								className="bg-rose-500/20 text-rose-400 border-rose-500/30"
							>
								{t("analytics:beAnalysis.beHarmful")}
							</Badge>
						)}
					</div>
				</CardContent>
			</Card>

			{/* --- MFE / MAE --- */}
			<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
				<Card>
					<CardHeader className="pb-2">
						<div className="flex items-center gap-2">
							<TrendingUp className="w-5 h-5 text-emerald-400" />
							<CardTitle className="text-base">
								{t("analytics:beAnalysis.avgMfe")}
							</CardTitle>
						</div>
					</CardHeader>
					<CardContent>
						<p className="text-3xl font-bold text-emerald-400">
							+{stats.avg_mfe_after_be.toFixed(2)}%
						</p>
						<p className="text-sm text-muted-foreground">
							{t("analytics:beAnalysis.mfeDesc")}
						</p>
					</CardContent>
				</Card>

				<Card>
					<CardHeader className="pb-2">
						<div className="flex items-center gap-2">
							<TrendingDown className="w-5 h-5 text-rose-400" />
							<CardTitle className="text-base">
								{t("analytics:beAnalysis.avgMae")}
							</CardTitle>
						</div>
					</CardHeader>
					<CardContent>
						<p className="text-3xl font-bold text-rose-400">
							-{stats.avg_mae_after_be.toFixed(2)}%
						</p>
						<p className="text-sm text-muted-foreground">
							{t("analytics:beAnalysis.maeDesc")}
						</p>
					</CardContent>
				</Card>
			</div>

			{/* --- Potential PnL --- */}
			<Card>
				<CardHeader>
					<CardTitle>{t("analytics:beAnalysis.phantomPnl")}</CardTitle>
					<CardDescription>
						{t("analytics:beAnalysis.phantomPnlDesc")}
					</CardDescription>
				</CardHeader>
				<CardContent>
					<div className="grid grid-cols-2 gap-8">
						<div className="text-center">
							<p className="text-sm text-muted-foreground mb-1">
								{t("analytics:beAnalysis.ifTpHit")}
							</p>
							<p className="text-2xl font-bold text-emerald-400">
								+{stats.avg_phantom_pnl_if_tp.toFixed(2)}%
							</p>
							<p className="text-xs text-muted-foreground">
								{t("analytics:beAnalysis.avgPnlPerTrade")}
							</p>
						</div>
						<div className="text-center">
							<p className="text-sm text-muted-foreground mb-1">
								{t("analytics:beAnalysis.ifSlHit")}
							</p>
							<p className="text-2xl font-bold text-rose-400">
								{stats.avg_phantom_pnl_if_sl.toFixed(2)}%
							</p>
							<p className="text-xs text-muted-foreground">
								{t("analytics:beAnalysis.avgPnlPerTrade")}
							</p>
						</div>
					</div>
				</CardContent>
			</Card>

			{/* --- Trades Table --- */}
			<Card>
				<CardHeader>
					<CardTitle>{t("analytics:beAnalysis.statistics")}</CardTitle>
				</CardHeader>
				<CardContent className="p-0">
					<ScrollArea className="h-[500px]">
						<Table>
							<TableHeader>
								<TableRow className="text-[11px] uppercase tracking-wider font-bold text-muted-foreground bg-muted/50 border-b border-border">
									<TableHead className="px-6 py-4">
										{t("analytics:tradeHistory.headers.closeTime")}
									</TableHead>
									<TableHead className="px-6 py-4">
										{t("analytics:tradeHistory.headers.symbol")}
									</TableHead>
									<TableHead className="px-6 py-4 text-center">
										{t("analytics:tradeHistory.headers.direction")}
									</TableHead>
									<TableHead className="px-6 py-4 text-right">
										BE Price
									</TableHead>
									<TableHead className="px-6 py-4 text-right">
										TP / SL
									</TableHead>{" "}
									{/* Initial SL/TP */}
									<TableHead className="px-6 py-4 text-right">Result</TableHead>
									<TableHead className="px-6 py-4 text-right">
										Phantom PnL
									</TableHead>
									<TableHead className="px-4 py-4 text-right">
										MFE / MAE
									</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody className="divide-y divide-border">
								{tradesLoading ? (
									<TableRow>
										<TableCell colSpan={8} className="text-center py-8">
											{t("common:loading")}
										</TableCell>
									</TableRow>
								) : tradesData?.trades.length === 0 ? (
									<TableRow>
										<TableCell
											colSpan={8}
											className="text-center py-8 text-muted-foreground"
										>
											{t("analytics:tradeHistory.noTradesFound")}
										</TableCell>
									</TableRow>
								) : (
									tradesData?.trades.map((trade: PhantomTrade) => {
										const isTpHit = trade.phantom_status === "TP_HIT";
										const isSlHit = trade.phantom_status === "SL_HIT";

										return (
											<TableRow
												key={trade.id}
												className="hover:bg-muted/30 transition-colors"
											>
												<TableCell className="px-6 py-4">
													<span className="text-sm font-semibold text-foreground">
														{format(
															new Date(trade.be_trigger_time),
															"dd.MM.yyyy",
														)}
													</span>
													<span className="block text-[10px] text-muted-foreground mt-0.5">
														{format(
															new Date(trade.be_trigger_time),
															"HH:mm:ss",
														)}
													</span>
												</TableCell>
												<TableCell className="px-6 py-4 font-bold text-foreground">
													{trade.symbol}
												</TableCell>
												<TableCell className="px-6 py-4 text-center">
													<span
														className={`inline-block px-2.5 py-1 rounded-lg text-[9px] font-black tracking-widest ${
															["LONG", "BUY"].includes(trade.direction)
																? "bg-profit/10 text-profit border border-profit/20"
																: "bg-loss/10 text-loss border border-loss/20"
														}`}
													>
														{trade.direction}
													</span>
												</TableCell>
												<TableCell className="px-6 py-4 text-right font-mono text-sm">
													$
													{formatCryptoPrice(
														trade.be_exit_price || trade.entry_price,
													)}
												</TableCell>
												<TableCell className="px-6 py-4 text-right font-mono text-xs">
													<div className="text-profit">
														TP: ${formatCryptoPrice(trade.initial_take_profit)}
													</div>
													<div className="text-loss">
														SL: ${formatCryptoPrice(trade.initial_stop_loss)}
													</div>
												</TableCell>
												<TableCell className="px-6 py-4 text-right">
													<Badge
														variant="outline"
														className={`
                                                        ${isTpHit ? "bg-rose-500/10 text-rose-500 border-rose-500/20" : ""}
                                                        ${isSlHit ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20" : ""}
                                                        ${trade.phantom_status === "TIMEOUT" ? "bg-slate-500/10 text-slate-500" : ""}
                                                        ${trade.phantom_status === "TRACKING" ? "bg-blue-500/10 text-blue-500" : ""}
                                                    `}
													>
														{trade.phantom_status}
													</Badge>
												</TableCell>
												<TableCell
													className={`px-6 py-4 text-right font-mono font-bold text-sm ${
														(trade.phantom_pnl_pct || 0) > 0
															? "text-profit"
															: (trade.phantom_pnl_pct || 0) < 0
																? "text-loss"
																: ""
													}`}
												>
													{trade.phantom_pnl_pct
														? `${trade.phantom_pnl_pct > 0 ? "+" : ""}${trade.phantom_pnl_pct.toFixed(2)}%`
														: "-"}
												</TableCell>
												<TableCell className="px-4 py-4 text-right font-mono text-xs">
													<div className="text-emerald-400">
														+{(trade.mfe_after_be || 0).toFixed(2)}%
													</div>
													<div className="text-rose-400">
														-{(trade.mae_after_be || 0).toFixed(2)}%
													</div>
												</TableCell>
											</TableRow>
										);
									})
								)}
							</TableBody>
						</Table>
					</ScrollArea>

					{/* Pagination */}
					{totalPages > 1 && (
						<div className="flex items-center justify-between px-6 py-4 border-t border-border bg-muted/30">
							<div className="text-sm text-muted-foreground">
								{t("analytics:pagination.page")} {page}{" "}
								{t("analytics:pagination.of")} {totalPages}
							</div>
							<div className="flex items-center gap-1">
								<Button
									variant="outline"
									size="sm"
									className="h-8 w-8 p-0"
									onClick={() => setPage(1)}
									disabled={page === 1}
								>
									<ChevronsLeft className="h-4 w-4" />
								</Button>
								<Button
									variant="outline"
									size="sm"
									className="h-8 w-8 p-0"
									onClick={() => setPage(page - 1)}
									disabled={page === 1}
								>
									<ChevronLeft className="h-4 w-4" />
								</Button>
								<span className="px-3 text-sm font-medium">{page}</span>
								<Button
									variant="outline"
									size="sm"
									className="h-8 w-8 p-0"
									onClick={() => setPage(page + 1)}
									disabled={page === totalPages}
								>
									<ChevronRight className="h-4 w-4" />
								</Button>
								<Button
									variant="outline"
									size="sm"
									className="h-8 w-8 p-0"
									onClick={() => setPage(totalPages)}
									disabled={page === totalPages}
								>
									<ChevronsRight className="h-4 w-4" />
								</Button>
							</div>
						</div>
					)}
				</CardContent>
			</Card>
		</div>
	);
};
