// frontend/src/components/simulation/InspectorMatrix.tsx
// Heatmap view showing strategy variants performance across assets

import {
	LayoutGrid,
	List,
	Loader2,
	TrendingDown,
	TrendingUp,
} from "lucide-react";
import type React from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useSimulationStore } from "./simulationStore";
import { BUILT_IN_VARIANTS, type InspectorCell } from "./types";

const getHeatmapColor = (pnl: number): string => {
	if (pnl > 30) return "text-emerald-400 bg-emerald-500/20";
	if (pnl > 15) return "text-emerald-400 bg-emerald-500/10";
	if (pnl > 0) return "text-emerald-400 bg-emerald-500/5";
	if (pnl < -10) return "text-rose-400 bg-rose-500/20";
	if (pnl < 0) return "text-rose-400 bg-rose-500/10";
	return "text-muted-foreground bg-muted/50";
};

export const InspectorMatrix: React.FC = () => {
	const { t } = useTranslation("simulation");
	const {
		inspectorResult,
		selectedVariants,
		customVariants,
		isLoading,
		progress,
		setActiveAsset,
	} = useSimulationStore();

	// Combine built-in and custom variants, filter by selected
	const allVariants = useMemo(
		() => [...BUILT_IN_VARIANTS, ...customVariants],
		[customVariants],
	);

	const activeVariants = useMemo(
		() => allVariants.filter((v) => selectedVariants.includes(v.id)),
		[allVariants, selectedVariants],
	);

	// Show progress bar during loading (even with partial data)
	const showProgress = isLoading && progress < 100;

	// View mode state
	const [viewMode, setViewMode] = useState<"matrix" | "summary">("matrix");

	// Variant Summary (as in inspector_v3.py)
	const variantSummary = useMemo(() => {
		if (!inspectorResult?.matrix) return [];

		return activeVariants
			.map((variant) => {
				const assetPnls: number[] = [];
				const assetWrs: number[] = [];
				const assetDDs: number[] = [];
				let totalTrades = 0;
				let totalCommission = 0;

				Object.values(inspectorResult.matrix).forEach((variants) => {
					const cell = variants[variant.id];
					if (cell && cell.trades_count > 0) {
						assetPnls.push(cell.pnl_pct);
						assetWrs.push(cell.win_rate);
						if (cell.max_dd && cell.max_dd > 0) {
							assetDDs.push(cell.max_dd);
						}
						totalTrades += cell.trades_count;
						totalCommission += cell.commission || 0;
					}
				});

				const totalPnl = assetPnls.reduce((sum, p) => sum + p, 0);
				const avgWr =
					assetWrs.length > 0
						? assetWrs.reduce((sum, w) => sum + w, 0) / assetWrs.length
						: 0;
				const avgDD =
					assetDDs.length > 0
						? assetDDs.reduce((sum, d) => sum + d, 0) / assetDDs.length
						: 0;
				const avgTrade = totalTrades > 0 ? totalPnl / totalTrades : 0;

				return {
					variant: variant.id,
					variantName: variant.name,
					color: variant.color,
					totalPnl,
					totalTrades,
					avgWinRate: avgWr,
					avgDrawdown: avgDD,
					avgTrade,
					totalCommission,
					assetsCount: assetPnls.length,
				};
			})
			.sort((a, b) => b.totalPnl - a.totalPnl);
	}, [inspectorResult, activeVariants]);

	if (!inspectorResult || inspectorResult.assets.length === 0) {
		return (
			<div className="flex flex-col items-center justify-center h-full min-h-[400px] text-muted-foreground space-y-4">
				<div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center animate-bounce">
					<TrendingUp size={32} className="text-primary" />
				</div>
				<div className="text-center">
					<h3 className="text-xl font-bold text-foreground">
						{t("noData", "No Inspector Data")}
					</h3>
					<p className="max-w-xs mx-auto text-sm">
						{t(
							"runInspectorPrompt",
							"Select assets and run the inspector to see results.",
						)}
					</p>
				</div>
			</div>
		);
	}

	const { matrix, assets } = inspectorResult;

	return (
		<div className="space-y-6 animate-in fade-in duration-500">
			<div className="flex items-center justify-between flex-wrap gap-4">
				<div>
					<h2 className="text-2xl font-bold">
						{t("inspectorMatrix", "Inspector Matrix")}
					</h2>
					<p className="text-sm text-muted-foreground">
						{t(
							"heatmapDescription",
							"Heatmap comparison of strategy variants across your selected portfolio",
						)}
					</p>
				</div>
				<div className="flex items-center gap-4">
					{/* View Mode Switcher */}
					<Tabs
						value={viewMode}
						onValueChange={(v) => setViewMode(v as "matrix" | "summary")}
						className="w-[200px]"
					>
						<TabsList className="grid w-full grid-cols-2">
							<TabsTrigger value="matrix" className="text-xs">
								<LayoutGrid size={14} className="mr-1" />
								{t("matrix", "Matrix")}
							</TabsTrigger>
							<TabsTrigger value="summary" className="text-xs">
								<List size={14} className="mr-1" />
								{t("summary", "Summary")}
							</TabsTrigger>
						</TabsList>
					</Tabs>

					{/* Legend - only for matrix view */}
					{viewMode === "matrix" && (
						<div className="flex items-center gap-4 text-xs">
							<div className="flex items-center gap-1.5">
								<span className="w-2 h-2 rounded-full bg-emerald-500" />
								{t("profit", "Profit")} &gt; 30%
							</div>
							<div className="flex items-center gap-1.5">
								<span className="w-2 h-2 rounded-full bg-rose-500" />
								{t("loss", "Loss")} &gt; 10%
							</div>
						</div>
					)}
				</div>
			</div>

			{/* Progress Bar */}
			{showProgress && (
				<div className="space-y-2">
					<div className="flex items-center justify-between text-sm">
						<div className="flex items-center gap-2">
							<Loader2 className="w-4 h-4 animate-spin text-primary" />
							<span className="text-muted-foreground">
								{t("running", "Running backtests...")}
							</span>
						</div>
						<span className="font-mono text-primary">
							{progress.toFixed(0)}%
						</span>
					</div>
					<Progress value={progress} className="h-2" />
				</div>
			)}

			{/* Summary View */}
			{viewMode === "summary" && (
				<div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xl">
					<table className="w-full text-left border-collapse">
						<thead>
							<tr className="bg-muted/50 border-b border-border">
								<th className="p-4 text-xs font-bold text-muted-foreground uppercase tracking-wider">
									{t("variant", "Variant")}
								</th>
								<th className="p-4 text-xs font-bold text-muted-foreground uppercase tracking-wider text-right">
									Total PnL
								</th>
								<th className="p-4 text-xs font-bold text-muted-foreground uppercase tracking-wider text-right">
									{t("trades", "Trades")}
								</th>
								<th className="p-4 text-xs font-bold text-muted-foreground uppercase tracking-wider text-right">
									{t("winRate", "WinRate")}
								</th>
								<th className="p-4 text-xs font-bold text-muted-foreground uppercase tracking-wider text-right">
									{t("avgTrade", "Avg Trade")}
								</th>
								<th className="p-4 text-xs font-bold text-muted-foreground uppercase tracking-wider text-right">
									Avg DD
								</th>
								<th className="p-4 text-xs font-bold text-muted-foreground uppercase tracking-wider text-right">
									Commission
								</th>
								<th className="p-4 text-xs font-bold text-muted-foreground uppercase tracking-wider text-right">
									Assets
								</th>
							</tr>
						</thead>
						<tbody>
							{variantSummary.map((row, index) => (
								<tr
									key={row.variant}
									className={`border-b border-border/50 hover:bg-muted/30 transition-colors ${index === 0 ? "bg-emerald-500/10" : ""}`}
								>
									<td className="p-4">
										<div className="flex items-center gap-3">
											<div
												className="w-3 h-3 rounded-full"
												style={{ backgroundColor: row.color }}
											/>
											<span className="font-bold">{row.variantName}</span>
										</div>
									</td>
									<td
										className={`p-4 text-right font-mono font-bold text-lg ${row.totalPnl > 0 ? "text-emerald-400" : row.totalPnl < 0 ? "text-rose-400" : ""}`}
									>
										{row.totalPnl > 0 ? "+" : ""}
										{row.totalPnl.toFixed(0)}%
									</td>
									<td className="p-4 text-right font-mono">
										{row.totalTrades}
									</td>
									<td className="p-4 text-right font-mono">
										{row.avgWinRate.toFixed(1)}%
									</td>
									<td
										className={`p-4 text-right font-mono ${row.avgTrade > 0 ? "text-emerald-400" : row.avgTrade < 0 ? "text-rose-400" : ""}`}
									>
										{row.avgTrade > 0 ? "+" : ""}
										{row.avgTrade.toFixed(2)}%
									</td>
									<td className="p-4 text-right font-mono text-rose-400">
										{row.avgDrawdown > 0
											? `-${row.avgDrawdown.toFixed(1)}%`
											: "0%"}
									</td>
									<td className="p-4 text-right font-mono text-muted-foreground">
										{row.totalCommission.toFixed(2)}%
									</td>
									<td className="p-4 text-right font-mono text-muted-foreground">
										{row.assetsCount}
									</td>
								</tr>
							))}
						</tbody>
					</table>
				</div>
			)}

			{/* Matrix View */}
			{viewMode === "matrix" && (
				<div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xl">
					<table className="w-full text-left border-collapse">
						<thead>
							<tr className="bg-muted/50 border-b border-border">
								<th className="p-4 text-xs font-bold text-muted-foreground uppercase tracking-wider sticky left-0 z-10 bg-muted/50">
									{t("asset", "Asset")}
								</th>
								{activeVariants.map((v) => (
									<th
										key={v.id}
										className="p-4 text-xs font-bold text-muted-foreground uppercase tracking-wider min-w-[140px]"
									>
										<div className="flex flex-col">
											<span>{v.name}</span>
											<span className="text-[10px] font-normal lowercase opacity-50">
												PnL %
											</span>
										</div>
									</th>
								))}
								<th className="p-4 text-xs font-bold text-muted-foreground uppercase tracking-wider text-right">
									{t("avgPnl", "Avg PnL")}
								</th>
							</tr>
						</thead>
						<tbody>
							{assets.map((asset) => {
								const assetData = matrix[asset] || {};
								const pnlValues = activeVariants.map(
									(v) => assetData[v.id]?.pnl_pct || 0,
								);
								const avgPnl =
									pnlValues.reduce((a, b) => a + b, 0) / pnlValues.length;

								return (
									<tr
										key={asset}
										className="border-b border-border/50 hover:bg-muted/30 transition-colors group"
									>
										<td
											className="p-4 sticky left-0 z-10 bg-card group-hover:bg-muted/30 border-r border-border/30 cursor-pointer"
											onClick={() => setActiveAsset(asset)}
										>
											<div className="flex items-center gap-3">
												<div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary font-bold text-xs border border-primary/20">
													{asset.slice(0, 2)}
												</div>
												<span className="font-mono font-bold">{asset}</span>
											</div>
										</td>
										{activeVariants.map((v) => {
											const cell: InspectorCell = assetData[v.id] || {
												pnl_pct: 0,
												win_rate: 0,
												trades_count: 0,
												sharpe: 0,
												max_dd: 0,
												commission: 0,
											};
											return (
												<td key={v.id} className="p-2">
													<div
														className={`h-12 flex flex-col items-center justify-center rounded-lg transition-transform hover:scale-105 cursor-pointer ${getHeatmapColor(cell.pnl_pct)}`}
														onClick={() => setActiveAsset(asset)}
													>
														<span className="text-sm font-mono font-bold">
															{cell.pnl_pct > 0 ? "+" : ""}
															{cell.pnl_pct.toFixed(1)}%
														</span>
														<span className="text-[10px] opacity-60">
															WR: {cell.win_rate.toFixed(0)}%
														</span>
													</div>
												</td>
											);
										})}
										<td className="p-4 text-right">
											<div
												className={`flex items-center justify-end gap-2 font-mono font-bold ${avgPnl > 0 ? "text-emerald-400" : "text-rose-400"}`}
											>
												{avgPnl > 0 ? (
													<TrendingUp size={14} />
												) : (
													<TrendingDown size={14} />
												)}
												{avgPnl.toFixed(2)}%
											</div>
										</td>
									</tr>
								);
							})}
						</tbody>
						<tfoot>
							<tr className="bg-muted/50 font-bold">
								<td className="p-4 sticky left-0 z-10 bg-muted/50 text-muted-foreground uppercase text-xs">
									{t("portfolioTotal", "Portfolio Total")}
								</td>
								{activeVariants.map((v) => {
									const variantAvg =
										assets.reduce(
											(acc, asset) =>
												acc + (matrix[asset]?.[v.id]?.pnl_pct || 0),
											0,
										) / assets.length;
									return (
										<td key={v.id} className="p-4 text-center">
											<span
												className={`text-sm font-mono ${variantAvg > 0 ? "text-emerald-400" : "text-rose-400"}`}
											>
												{variantAvg > 0 ? "+" : ""}
												{variantAvg.toFixed(2)}%
											</span>
										</td>
									);
								})}
								<td className="p-4" />
							</tr>
						</tfoot>
					</table>
				</div>
			)}
		</div>
	);
};
