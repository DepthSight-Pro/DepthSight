// frontend/src/components/simulation/BEAnalysisView.tsx
// Breakeven Analysis View — analyzing phantom trades after BE exit

import {
	AlertTriangle,
	CheckCircle2,
	Clock,
	ShieldCheck,
	ThumbsDown,
	TrendingDown,
	TrendingUp,
	XCircle,
} from "lucide-react";
import type React from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { useSimulationStore } from "./simulationStore";
import type { PhantomTrade } from "./types";

interface BEAnalysisStats {
	totalBeTrades: number;
	tpWouldHit: number; // BE "stole" profit
	slWouldHit: number; // BE "saved" from loss
	timeout: number; // Reached neither TP nor SL

	beSavedPct: number; // % of trades where BE saved from loss
	beStolenPct: number; // % of trades where BE stole profit

	avgMfeAfterBe: number;
	avgMaeAfterBe: number;
	avgPhantomPnlIfTp: number;
	avgPhantomPnlIfSl: number;
	avgCandlesToResolution: number;
}

function calculateBEStats(phantomTrades: PhantomTrade[]): BEAnalysisStats {
	if (phantomTrades.length === 0) {
		return {
			totalBeTrades: 0,
			tpWouldHit: 0,
			slWouldHit: 0,
			timeout: 0,
			beSavedPct: 0,
			beStolenPct: 0,
			avgMfeAfterBe: 0,
			avgMaeAfterBe: 0,
			avgPhantomPnlIfTp: 0,
			avgPhantomPnlIfSl: 0,
			avgCandlesToResolution: 0,
		};
	}

	const tpHits = phantomTrades.filter((p) => p.phantomStatus === "TP_HIT");
	const slHits = phantomTrades.filter((p) => p.phantomStatus === "SL_HIT");
	const timeouts = phantomTrades.filter((p) => p.phantomStatus === "TIMEOUT");

	const totalBeTrades = phantomTrades.length;
	const tpWouldHit = tpHits.length;
	const slWouldHit = slHits.length;
	const timeout = timeouts.length;

	const beSavedPct = (slWouldHit / totalBeTrades) * 100;
	const beStolenPct = (tpWouldHit / totalBeTrades) * 100;

	const avgMfeAfterBe =
		phantomTrades.reduce((sum, p) => sum + (p.mfeAfterBe || 0), 0) /
		totalBeTrades;
	const avgMaeAfterBe =
		phantomTrades.reduce((sum, p) => sum + (p.maeAfterBe || 0), 0) /
		totalBeTrades;

	const avgPhantomPnlIfTp =
		tpHits.length > 0
			? tpHits.reduce((sum, p) => sum + (p.phantomPnlPct || 0), 0) /
				tpHits.length
			: 0;
	const avgPhantomPnlIfSl =
		slHits.length > 0
			? slHits.reduce((sum, p) => sum + (p.phantomPnlPct || 0), 0) /
				slHits.length
			: 0;

	const avgCandlesToResolution =
		phantomTrades.reduce((sum, p) => sum + (p.candlesToResolution || 0), 0) /
		totalBeTrades;

	return {
		totalBeTrades,
		tpWouldHit,
		slWouldHit,
		timeout,
		beSavedPct,
		beStolenPct,
		avgMfeAfterBe,
		avgMaeAfterBe,
		avgPhantomPnlIfTp,
		avgPhantomPnlIfSl,
		avgCandlesToResolution,
	};
}

export const BEAnalysisView: React.FC = () => {
	const { t } = useTranslation("simulation");
	const { inspectorResult, selectedVariants } = useSimulationStore();

	// Collect all phantom trades from inspector matrix
	const allPhantomTrades = useMemo<PhantomTrade[]>(() => {
		if (!inspectorResult?.matrix) return [];

		const phantoms: PhantomTrade[] = [];

		Object.values(inspectorResult.matrix).forEach((variants) => {
			selectedVariants.forEach((variantId) => {
				const cell = variants[variantId];
				if (cell?.phantomTrades && Array.isArray(cell.phantomTrades)) {
					phantoms.push(...cell.phantomTrades);
				}
			});
		});

		return phantoms;
	}, [inspectorResult, selectedVariants]);

	const stats = useMemo(
		() => calculateBEStats(allPhantomTrades),
		[allPhantomTrades],
	);

	if (allPhantomTrades.length === 0) {
		return (
			<Card className="h-full">
				<CardContent className="flex flex-col items-center justify-center h-full py-20">
					<AlertTriangle className="w-16 h-16 text-muted-foreground mb-4" />
					<h3 className="text-xl font-semibold mb-2">
						{t("beAnalysis.noData", "No data for analysis")}
					</h3>
					<p className="text-muted-foreground text-center max-w-md">
						{t(
							"beAnalysis.noDataDesc",
							"Run Inspector with variants using BE (breakeven). Phantom trades will appear after BREAKEVEN exits.",
						)}
					</p>
				</CardContent>
			</Card>
		);
	}

	return (
		<div className="space-y-6">
			{/* Summary Cards */}
			<div className="grid grid-cols-1 md:grid-cols-3 gap-4">
				{/* BE Saved */}
				<Card className="bg-gradient-to-br from-emerald-500/10 to-emerald-600/5 border-emerald-500/30">
					<CardContent className="p-6">
						<div className="flex items-center justify-between">
							<div>
								<p className="text-sm text-muted-foreground">
									{t("beAnalysis.saved", "BE Saved")}
								</p>
								<p className="text-3xl font-bold text-emerald-400">
									{stats.slWouldHit}
								</p>
								<p className="text-sm text-emerald-400">
									{stats.beSavedPct.toFixed(1)}%
								</p>
							</div>
							<ShieldCheck className="w-12 h-12 text-emerald-400/40" />
						</div>
						<p className="text-xs text-muted-foreground mt-2">
							{t(
								"beAnalysis.savedDesc",
								"Price would have reached SL without BE",
							)}
						</p>
					</CardContent>
				</Card>

				{/* BE Stolen */}
				<Card className="bg-gradient-to-br from-rose-500/10 to-rose-600/5 border-rose-500/30">
					<CardContent className="p-6">
						<div className="flex items-center justify-between">
							<div>
								<p className="text-sm text-muted-foreground">
									{t("beAnalysis.stolen", "BE Stole")}
								</p>
								<p className="text-3xl font-bold text-rose-400">
									{stats.tpWouldHit}
								</p>
								<p className="text-sm text-rose-400">
									{stats.beStolenPct.toFixed(1)}%
								</p>
							</div>
							<ThumbsDown className="w-12 h-12 text-rose-400/40" />
						</div>
						<p className="text-xs text-muted-foreground mt-2">
							{t(
								"beAnalysis.stolenDesc",
								"Price would have reached TP without BE",
							)}
						</p>
					</CardContent>
				</Card>

				{/* Timeout */}
				<Card className="bg-gradient-to-br from-slate-500/10 to-slate-600/5 border-slate-500/30">
					<CardContent className="p-6">
						<div className="flex items-center justify-between">
							<div>
								<p className="text-sm text-muted-foreground">
									{t("beAnalysis.timeout", "Timeout")}
								</p>
								<p className="text-3xl font-bold text-slate-400">
									{stats.timeout}
								</p>
								<p className="text-sm text-slate-400">
									{((stats.timeout / stats.totalBeTrades) * 100).toFixed(1)}%
								</p>
							</div>
							<Clock className="w-12 h-12 text-slate-400/40" />
						</div>
						<p className="text-xs text-muted-foreground mt-2">
							{t("beAnalysis.timeoutDesc", "Reached neither TP nor SL")}
						</p>
					</CardContent>
				</Card>
			</div>

			{/* BE Effectiveness Gauge */}
			<Card>
				<CardHeader>
					<CardTitle>
						{t("beAnalysis.effectiveness", "BE efficiency")}
					</CardTitle>
					<CardDescription>
						{t(
							"beAnalysis.effectivenessDesc",
							"Ratio of saved and stolen trades",
						)}
					</CardDescription>
				</CardHeader>
				<CardContent>
					<div className="space-y-4">
						<div className="flex items-center gap-4">
							<div className="flex-1">
								<div className="flex justify-between mb-2">
									<span className="text-sm text-emerald-400 flex items-center gap-1">
										<CheckCircle2 className="w-4 h-4" />{" "}
										{t("beAnalysis.saved", "Saved")}
									</span>
									<span className="text-sm text-rose-400 flex items-center gap-1">
										{t("beAnalysis.stolen", "Stole")}{" "}
										<XCircle className="w-4 h-4" />
									</span>
								</div>
								<div className="relative h-8 bg-slate-800 rounded-full overflow-hidden">
									<div
										className="absolute left-0 top-0 h-full bg-gradient-to-r from-emerald-500 to-emerald-400"
										style={{ width: `${stats.beSavedPct}%` }}
									/>
									<div
										className="absolute right-0 top-0 h-full bg-gradient-to-l from-rose-500 to-rose-400"
										style={{ width: `${stats.beStolenPct}%` }}
									/>
									<div className="absolute inset-0 flex items-center justify-center">
										<span className="text-sm font-bold text-white drop-shadow-lg">
											{stats.beSavedPct > stats.beStolenPct
												? `+${(stats.beSavedPct - stats.beStolenPct).toFixed(1)}%`
												: `${(stats.beSavedPct - stats.beStolenPct).toFixed(1)}%`}
										</span>
									</div>
								</div>
							</div>
						</div>

						{stats.beSavedPct > stats.beStolenPct ? (
							<Badge
								variant="default"
								className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
							>
								{t("beAnalysis.beUseful", "BE is beneficial")}
							</Badge>
						) : (
							<Badge
								variant="default"
								className="bg-rose-500/20 text-rose-400 border-rose-500/30"
							>
								{t("beAnalysis.beHarmful", "BE hurts the result")}
							</Badge>
						)}
					</div>
				</CardContent>
			</Card>

			{/* MFE/MAE Statistics */}
			<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
				<Card>
					<CardHeader className="pb-2">
						<div className="flex items-center gap-2">
							<TrendingUp className="w-5 h-5 text-emerald-400" />
							<CardTitle className="text-base">
								{t("beAnalysis.avgMfe", "Average MFE after BE")}
							</CardTitle>
						</div>
					</CardHeader>
					<CardContent>
						<p className="text-3xl font-bold text-emerald-400">
							+{stats.avgMfeAfterBe.toFixed(2)}%
						</p>
						<p className="text-sm text-muted-foreground">
							{t("beAnalysis.mfeDesc", "Maximum Favorable Excursion")}
						</p>
					</CardContent>
				</Card>

				<Card>
					<CardHeader className="pb-2">
						<div className="flex items-center gap-2">
							<TrendingDown className="w-5 h-5 text-rose-400" />
							<CardTitle className="text-base">
								{t("beAnalysis.avgMae", "Average MAE after BE")}
							</CardTitle>
						</div>
					</CardHeader>
					<CardContent>
						<p className="text-3xl font-bold text-rose-400">
							-{stats.avgMaeAfterBe.toFixed(2)}%
						</p>
						<p className="text-sm text-muted-foreground">
							{t("beAnalysis.maeDesc", "Maximum Adverse Excursion")}
						</p>
					</CardContent>
				</Card>
			</div>

			{/* Phantom PnL Analysis */}
			<Card>
				<CardHeader>
					<CardTitle>{t("beAnalysis.phantomPnl", "Potential PnL")}</CardTitle>
					<CardDescription>
						{t(
							"beAnalysis.phantomPnlDesc",
							"What would happen if BE did not trigger",
						)}
					</CardDescription>
				</CardHeader>
				<CardContent>
					<div className="grid grid-cols-2 gap-8">
						<div className="text-center">
							<p className="text-sm text-muted-foreground mb-1">
								{t("beAnalysis.ifTpHit", "If TP had triggered")}
							</p>
							<p className="text-2xl font-bold text-emerald-400">
								+{stats.avgPhantomPnlIfTp.toFixed(2)}%
							</p>
							<p className="text-xs text-muted-foreground">
								{t("beAnalysis.avgPnlPerTrade", "average PnL per trade")}
							</p>
						</div>
						<div className="text-center">
							<p className="text-sm text-muted-foreground mb-1">
								{t("beAnalysis.ifSlHit", "If SL had triggered")}
							</p>
							<p className="text-2xl font-bold text-rose-400">
								{stats.avgPhantomPnlIfSl.toFixed(2)}%
							</p>
							<p className="text-xs text-muted-foreground">
								{t("beAnalysis.avgPnlPerTrade", "average PnL per trade")}
							</p>
						</div>
					</div>
				</CardContent>
			</Card>

			{/* Statistics Table */}
			<Card>
				<CardHeader>
					<CardTitle>{t("beAnalysis.statistics", "Statistics")}</CardTitle>
				</CardHeader>
				<CardContent>
					<div className="grid grid-cols-2 md:grid-cols-4 gap-4">
						<div>
							<p className="text-sm text-muted-foreground">
								{t("beAnalysis.totalBeTrades", "Total BE exits")}
							</p>
							<p className="text-xl font-bold">{stats.totalBeTrades}</p>
						</div>
						<div>
							<p className="text-sm text-muted-foreground">
								{t("beAnalysis.avgCandles", "Average time to outcome")}
							</p>
							<p className="text-xl font-bold">
								{stats.avgCandlesToResolution.toFixed(0)}{" "}
								<span className="text-sm text-muted-foreground">candles</span>
							</p>
						</div>
						<div>
							<p className="text-sm text-muted-foreground">
								{t("beAnalysis.netEffect", "Net effect")}
							</p>
							<p
								className={`text-xl font-bold ${stats.beSavedPct > stats.beStolenPct ? "text-emerald-400" : "text-rose-400"}`}
							>
								{stats.beSavedPct > stats.beStolenPct ? "+" : ""}
								{(stats.beSavedPct - stats.beStolenPct).toFixed(1)}%
							</p>
						</div>
						<div>
							<p className="text-sm text-muted-foreground">
								{t("beAnalysis.recommendation", "Recommendation")}
							</p>
							<p className="text-xl font-bold">
								{stats.beSavedPct > stats.beStolenPct * 1.5
									? `✅ ${t("beAnalysis.keepBe", "Keep BE")}`
									: stats.beStolenPct > stats.beSavedPct * 1.5
										? `⚠️ ${t("beAnalysis.adjustBe", "Review BE")}`
										: `🔄 ${t("beAnalysis.testMore", "Need more data")}`}
							</p>
						</div>
					</div>
				</CardContent>
			</Card>
		</div>
	);
};

export default BEAnalysisView;
