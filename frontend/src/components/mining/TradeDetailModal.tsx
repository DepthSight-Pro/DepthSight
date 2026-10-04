import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
	DialogDescription,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Copy,
	Check,
	AlertCircle,
	ShieldCheck,
	Activity,
	Layers,
	BarChart3,
	Server,
	DollarSign,
	TrendingUp,
	TrendingDown,
	Zap,
	Code2,
} from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import type { MiningAnalyticsTradeItem } from "@/types/api";

interface TradeDetailModalProps {
	trade: MiningAnalyticsTradeItem | null;
	isOpen: boolean;
	onClose: () => void;
}

export const TradeDetailModal: React.FC<TradeDetailModalProps> = ({
	trade,
	isOpen,
	onClose,
}) => {
	const { t } = useTranslation("mining");
	const { toast } = useToast();
	const [copiedField, setCopiedField] = useState<string | null>(null);
	const [showRawStrategy, setShowRawStrategy] = useState(false);
	const [showRawMarket, setShowRawMarket] = useState(false);

	if (!trade) return null;

	const handleCopy = (text: string, fieldName: string) => {
		navigator.clipboard.writeText(text);
		setCopiedField(fieldName);
		toast({
			title: "Copied",
			description: `${fieldName} copied to clipboard`,
			duration: 2000,
		});
		setTimeout(() => setCopiedField(null), 2000);
	};

	const isLong = trade.direction?.toUpperCase() === "LONG";
	const isVerified = trade.verificationStatus === "VERIFIED";
	const isPending = trade.verificationStatus === "PENDING";

	return (
		<Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
			<DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto p-6 bg-card/95 border border-border/80 dark:border-white/10 rounded-2xl shadow-2xl backdrop-blur-xl">
				<DialogHeader className="pb-4 border-b border-border/40">
					<div className="flex flex-wrap items-center justify-between gap-3">
						<div className="flex items-center gap-2">
							<span className="text-xl font-bold font-mono tracking-tight text-foreground">
								{trade.symbol}
							</span>
							<Badge
								variant="outline"
								className={`font-mono text-xs px-2.5 py-0.5 font-bold uppercase ${
									isLong
										? "border-emerald-500/30 text-emerald-500 bg-emerald-500/10"
										: "border-rose-500/30 text-rose-500 bg-rose-500/10"
								}`}
							>
								{trade.direction}
							</Badge>
							<Badge
								variant="outline"
								className={`font-mono text-xs px-2.5 py-0.5 font-bold ${
									isVerified
										? "border-emerald-500/30 text-emerald-500 bg-emerald-500/10"
										: isPending
										? "border-amber-500/30 text-amber-500 bg-amber-500/10"
										: "border-rose-500/30 text-rose-500 bg-rose-500/10"
								}`}
							>
								{trade.verificationStatus}
							</Badge>
							<Badge variant="secondary" className="text-xs font-mono">
								{trade.tradeMode}
							</Badge>
						</div>
						<div className="text-xs text-muted-foreground font-mono">
							{new Date(trade.createdAt).toLocaleString()}
						</div>
					</div>
					<DialogTitle className="text-sm font-medium text-muted-foreground pt-1">
						{t("analyticsTradeModalSubtitle")}
					</DialogTitle>
					<DialogDescription className="sr-only">
						Trade Telemetry Details
					</DialogDescription>
				</DialogHeader>

				<div className="space-y-6 pt-4 text-sm">
					{/* Error Alert Banner if present */}
					{trade.verificationError && (
						<div className="p-3.5 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-400 flex items-start gap-3">
							<AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5 text-rose-400" />
							<div>
								<div className="font-semibold text-xs uppercase tracking-wider text-rose-300">
									{t("analyticsTradeError")}
								</div>
								<div className="font-mono text-xs mt-1 text-rose-200">
									{trade.verificationError}
								</div>
							</div>
						</div>
					)}

					{/* Section 1: Basic Trade Info */}
					<div className="space-y-3">
						<div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
							<Activity className="w-4 h-4 text-primary" />
							<span>{t("analyticsTradeModalBasicSection")}</span>
						</div>
						<div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-4 rounded-xl border border-border/50 bg-muted/20">
							<div>
								<div className="text-xs text-muted-foreground">Entry Price</div>
								<div className="font-mono font-medium text-foreground">
									${trade.entryPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Exit Price</div>
								<div className="font-mono font-medium text-foreground">
									${trade.exitPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">PnL %</div>
								<div className={`font-mono font-semibold ${
									(trade.pnlPercent ?? 0) >= 0 ? "text-emerald-500" : "text-rose-500"
								}`}>
									{trade.pnlPercent != null
										? `${trade.pnlPercent >= 0 ? "+" : ""}${trade.pnlPercent.toFixed(2)}%`
										: "—"}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Duration</div>
								<div className="font-mono text-foreground">
									{trade.tradeDurationSec != null ? `${trade.tradeDurationSec}s` : "—"}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Exit Reason</div>
								<div className="font-mono text-foreground font-medium">
									{trade.exitReason || "—"}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Timeframe</div>
								<div className="font-mono text-foreground">
									{trade.timeframe || "—"}
								</div>
							</div>
							<div className="sm:col-span-2">
								<div className="text-xs text-muted-foreground">Telemetry Report ID</div>
								<div className="flex items-center gap-2 font-mono text-xs text-foreground/80 truncate">
									<span className="truncate">{trade.id}</span>
									<Button
										variant="ghost"
										size="icon"
										className="h-6 w-6"
										onClick={() => handleCopy(trade.id, "Report ID")}
									>
										{copiedField === "Report ID" ? (
											<Check className="h-3 w-3 text-emerald-400" />
										) : (
											<Copy className="h-3 w-3" />
										)}
									</Button>
								</div>
							</div>
						</div>
					</div>

					{/* Section 2: Mining Info & Rewards */}
					<div className="space-y-3">
						<div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
							<DollarSign className="w-4 h-4 text-emerald-400" />
							<span>{t("analyticsTradeModalMiningSection")}</span>
						</div>
						<div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-4 rounded-xl border border-border/50 bg-muted/20">
							<div>
								<div className="text-xs text-muted-foreground">Exchange</div>
								<div className="font-mono font-medium text-foreground">
									{trade.exchangeId || "—"}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Trade Volume</div>
								<div className="font-mono font-semibold text-foreground">
									${(trade.tradeVolumeUsdt ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Est. Rebate</div>
								<div className="font-mono font-medium text-emerald-500">
									${(trade.estimatedRebateUsdt ?? 0).toFixed(4)}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Reward Mined</div>
								<div className="font-mono font-bold text-primary flex items-center gap-1">
									<Zap className="h-3.5 w-3.5 text-amber-400" />
									{(trade.rewardTokens ?? 0).toLocaleString()} $DEPTH
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Mining Eligible</div>
								<div className="font-medium">
									{trade.isMiningEligible ? (
										<span className="text-emerald-400 font-mono">✓ Yes</span>
									) : (
										<span className="text-muted-foreground font-mono">✗ No (Quality Gated)</span>
									)}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Multiplier</div>
								<div className="font-mono font-medium text-foreground">
									{trade.miningMultiplier != null && trade.miningMultiplier > 1 ? (
										<span className="text-amber-400 font-bold">x{trade.miningMultiplier}</span>
									) : (
										<span>x{trade.miningMultiplier != null ? trade.miningMultiplier : 1}</span>
									)}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Trade Score</div>
								<div className="font-mono font-medium text-foreground">
									{trade.score != null ? trade.score.toFixed(3) : "—"}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Epoch Date</div>
								<div className="font-mono text-foreground">
									{trade.epochDate || "—"}
								</div>
							</div>
						</div>
					</div>

					{/* Section 3: Broker Verification */}
					<div className="space-y-3">
						<div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
							<ShieldCheck className="w-4 h-4 text-emerald-400" />
							<span>{t("analyticsTradeModalVerificationSection")}</span>
						</div>
						<div className="space-y-3 p-4 rounded-xl border border-border/50 bg-muted/20">
							<div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
								<div>
									<div className="text-xs text-muted-foreground">Verification Status</div>
									<div className="font-mono font-semibold text-foreground">
										{trade.verificationStatus}
									</div>
								</div>
								<div>
									<div className="text-xs text-muted-foreground">Verified Volume</div>
									<div className="font-mono font-semibold text-foreground">
										{trade.verifiedVolumeUsdt != null
											? `$${trade.verifiedVolumeUsdt.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
											: "—"}
									</div>
								</div>
								<div>
									<div className="text-xs text-muted-foreground">Verified At</div>
									<div className="font-mono text-xs text-foreground">
										{trade.verifiedAt ? new Date(trade.verifiedAt).toLocaleString() : "—"}
									</div>
								</div>
							</div>

							<div className="border-t border-border/40 pt-3 space-y-2">
								<div>
									<div className="text-xs text-muted-foreground">Broker Trade ID</div>
									<div className="flex items-center gap-2 font-mono text-xs text-foreground/90">
										<span className="truncate">{trade.brokerTradeId || "Not provided / pending"}</span>
										{trade.brokerTradeId && (
											<Button
												variant="ghost"
												size="icon"
												className="h-6 w-6"
												onClick={() => handleCopy(trade.brokerTradeId!, "Broker Trade ID")}
											>
												{copiedField === "Broker Trade ID" ? (
													<Check className="h-3 w-3 text-emerald-400" />
												) : (
													<Copy className="h-3 w-3" />
												)}
											</Button>
										)}
									</div>
								</div>

								{Boolean(trade.entryBrokerTradeIds) && (
									<div>
										<div className="text-xs text-muted-foreground">Entry Broker IDs</div>
										<div className="font-mono text-xs text-muted-foreground bg-background/50 p-2 rounded border border-border/30 overflow-x-auto">
											{JSON.stringify(trade.entryBrokerTradeIds)}
										</div>
									</div>
								)}

								{Boolean(trade.closeBrokerTradeIds) && (
									<div>
										<div className="text-xs text-muted-foreground">Close Broker IDs</div>
										<div className="font-mono text-xs text-muted-foreground bg-background/50 p-2 rounded border border-border/30 overflow-x-auto">
											{JSON.stringify(trade.closeBrokerTradeIds)}
										</div>
									</div>
								)}
							</div>
						</div>
					</div>

					{/* Section 4: Node & Infrastructure */}
					<div className="space-y-3">
						<div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
							<Server className="w-4 h-4 text-cyan-400" />
							<span>{t("analyticsTradeModalInfrastructureSection")}</span>
						</div>
						<div className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-4 rounded-xl border border-border/50 bg-muted/20">
							<div>
								<div className="text-xs text-muted-foreground">Miner Node</div>
								<div className="font-medium text-foreground">
									{trade.nodeName || "Unknown Node"}
								</div>
								<div className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground mt-0.5 truncate">
									<span>{trade.nodeUuid || "—"}</span>
									{trade.nodeUuid && (
										<Button
											variant="ghost"
											size="icon"
											className="h-5 w-5"
											onClick={() => handleCopy(trade.nodeUuid!, "Node UUID")}
										>
											{copiedField === "Node UUID" ? (
												<Check className="h-3 w-3 text-emerald-400" />
											) : (
												<Copy className="h-3 w-3" />
											)}
										</Button>
									)}
								</div>
							</div>
							<div>
								<div className="text-xs text-muted-foreground">Source Relay Node</div>
								<div className="font-mono text-xs text-foreground mt-1 truncate">
									{trade.sourceNodeUuid ? (
										<div className="flex items-center gap-1.5">
											<span className="truncate">{trade.sourceNodeUuid}</span>
											<Button
												variant="ghost"
												size="icon"
												className="h-5 w-5"
												onClick={() => handleCopy(trade.sourceNodeUuid!, "Source Node UUID")}
											>
												{copiedField === "Source Node UUID" ? (
													<Check className="h-3 w-3 text-emerald-400" />
												) : (
													<Copy className="h-3 w-3" />
												)}
											</Button>
										</div>
									) : (
										<span className="text-muted-foreground italic">Central Hub (Direct)</span>
									)}
								</div>
							</div>
						</div>
					</div>

					{/* Section 5: Floating P/L (MFP / MFL) */}
					{(trade.maxFloatingProfit != null || trade.maxFloatingLoss != null) && (
						<div className="space-y-3">
							<div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
								<BarChart3 className="w-4 h-4 text-purple-400" />
								<span>{t("analyticsTradeModalFloatingSection")}</span>
							</div>
							<div className="grid grid-cols-2 gap-3 p-4 rounded-xl border border-border/50 bg-muted/20">
								<div>
									<div className="text-xs text-muted-foreground flex items-center gap-1">
										<TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
										<span>Max Floating Profit (MFE)</span>
									</div>
									<div className="font-mono font-semibold text-emerald-400 mt-1">
										${(trade.maxFloatingProfit ?? 0).toFixed(2)}
									</div>
								</div>
								<div>
									<div className="text-xs text-muted-foreground flex items-center gap-1">
										<TrendingDown className="w-3.5 h-3.5 text-rose-400" />
										<span>Max Floating Loss (MAE)</span>
									</div>
									<div className="font-mono font-semibold text-rose-400 mt-1">
										-${Math.abs(trade.maxFloatingLoss ?? 0).toFixed(2)}
									</div>
								</div>
							</div>
						</div>
					)}

					{/* Section 6: Strategy Blocks & Logic */}
					{trade.strategyBlocks && trade.strategyBlocks.length > 0 && (
						<div className="space-y-3">
							<div className="flex items-center justify-between">
								<div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
									<Layers className="w-4 h-4 text-amber-400" />
									<span>{t("analyticsTradeModalStrategySection")} ({trade.strategyBlocks.length})</span>
								</div>
								<Button
									variant="ghost"
									size="sm"
									className="h-6 px-2 text-xs text-muted-foreground hover:text-foreground gap-1"
									onClick={() => setShowRawStrategy(!showRawStrategy)}
								>
									<Code2 className="w-3.5 h-3.5" />
									<span>{showRawStrategy ? t("analyticsTradeModalHideJson") : t("analyticsTradeModalRawJson")}</span>
								</Button>
							</div>

							{trade.strategyBlocks.length === 1 &&
							trade.strategyBlocks[0].type === "VisualBuilderStrategy" &&
							(!trade.strategyBlocks[0].params || Object.keys(trade.strategyBlocks[0].params).length === 0) ? (
								<div className="p-3.5 rounded-xl border border-amber-500/20 bg-amber-500/5 space-y-1.5">
									<div className="flex items-center gap-2">
										<Badge variant="outline" className="border-amber-500/40 text-amber-400 font-mono text-xs">
											VisualBuilderStrategy
										</Badge>
										<span className="text-xs text-muted-foreground">({t("analyticsTradeModalDefaultParams")})</span>
									</div>
									<div className="text-xs text-muted-foreground">
										{t("analyticsTradeModalVisualBuilderNotice")}
									</div>
								</div>
							) : (
								<div className="space-y-2 max-h-56 overflow-y-auto pr-1">
									{trade.strategyBlocks.map((block, idx) => {
										const paramsObj = (block.params && typeof block.params === "object" ? block.params : {}) as Record<string, unknown>;
										const hasParams = Object.keys(paramsObj).length > 0;
										return (
											<div key={idx} className="p-3 rounded-xl border border-border/50 bg-muted/20 space-y-2">
												<div className="flex items-center justify-between">
													<div className="font-mono text-xs font-bold text-foreground flex items-center gap-1.5">
														<span className="text-amber-400 font-semibold">#{idx + 1}</span>
														<span>{String(block.type)}</span>
													</div>
												</div>
												{hasParams ? (
													<div className="flex flex-wrap gap-1.5">
														{Object.entries(paramsObj).map(([k, v]) => (
															<span
																key={k}
																className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-background/60 border border-border/40 font-mono text-[11px] text-muted-foreground"
															>
																<span className="text-foreground/70">{k}:</span>
																<span className="text-amber-300 font-medium truncate max-w-[200px]">
																	{typeof v === "object" ? JSON.stringify(v) : String(v)}
																</span>
															</span>
														))}
													</div>
												) : (
													<div className="text-[11px] text-muted-foreground italic">
														{t("analyticsTradeModalDefaultParams")}
													</div>
												)}
											</div>
										);
									})}
								</div>
							)}

							{showRawStrategy && (
								<div className="p-3.5 rounded-xl border border-border/50 bg-background/80 max-h-48 overflow-y-auto">
									<pre className="font-mono text-xs text-muted-foreground whitespace-pre-wrap">
										{JSON.stringify(trade.strategyBlocks, null, 2)}
									</pre>
								</div>
							)}
						</div>
					)}

					{/* Section 7: Market Context */}
					{trade.marketContext && Object.keys(trade.marketContext).length > 0 && (
						<div className="space-y-3">
							<div className="flex items-center justify-between">
								<div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
									<Activity className="w-4 h-4 text-blue-400" />
									<span>{t("analyticsTradeModalMarketSection")}</span>
								</div>
								<Button
									variant="ghost"
									size="sm"
									className="h-6 px-2 text-xs text-muted-foreground hover:text-foreground gap-1"
									onClick={() => setShowRawMarket(!showRawMarket)}
								>
									<Code2 className="w-3.5 h-3.5" />
									<span>{showRawMarket ? t("analyticsTradeModalHideJson") : t("analyticsTradeModalRawJson")}</span>
								</Button>
							</div>

							<div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-4 rounded-xl border border-border/50 bg-muted/20">
								<div>
									<div className="text-xs text-muted-foreground">{t("analyticsTradeModalMarketSession")}</div>
									<div className="mt-1">
										{trade.marketContext.session ? (
											<Badge variant="outline" className="border-blue-500/40 text-blue-400 font-mono text-xs uppercase bg-blue-500/10">
												{String(trade.marketContext.session)}
											</Badge>
										) : (
											<span className="font-mono text-foreground">—</span>
										)}
									</div>
								</div>
								<div>
									<div className="text-xs text-muted-foreground">{t("analyticsTradeModalMarketNATR")}</div>
									<div className="font-mono font-semibold text-foreground mt-1">
										{trade.marketContext.natr != null ? `${Number(trade.marketContext.natr).toFixed(3)}%` : "—"}
									</div>
								</div>
								<div>
									<div className="text-xs text-muted-foreground">{t("analyticsTradeModalMarketADX")}</div>
									<div className="font-mono font-semibold text-foreground mt-1">
										{trade.marketContext.adx != null ? Number(trade.marketContext.adx).toFixed(1) : "—"}
									</div>
								</div>
								<div>
									<div className="text-xs text-muted-foreground">{t("analyticsTradeModalMarketVolRatio")}</div>
									<div className="font-mono font-semibold text-foreground mt-1">
										{trade.marketContext.volume_ratio != null ? `${Number(trade.marketContext.volume_ratio).toFixed(2)}x` : "—"}
									</div>
								</div>
							</div>

							{trade.marketContext.session == null &&
							trade.marketContext.natr == null &&
							trade.marketContext.adx == null &&
							trade.marketContext.volume_ratio == null && (
								<div className="text-xs text-muted-foreground italic px-1">
									{t("analyticsTradeModalMarketNoData")}
								</div>
							)}

							{showRawMarket && (
								<div className="p-3.5 rounded-xl border border-border/50 bg-background/80 max-h-48 overflow-y-auto">
									<pre className="font-mono text-xs text-muted-foreground whitespace-pre-wrap">
										{JSON.stringify(trade.marketContext, null, 2)}
									</pre>
								</div>
							)}
						</div>
					)}
				</div>
			</DialogContent>
		</Dialog>
	);
};
