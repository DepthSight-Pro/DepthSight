// src/components/genetic-command-center/HallOfFame.tsx

import {
	AlertCircle,
	Binary,
	ChevronRight,
	Download,
	ExternalLink,
	FlaskConical,
	LineChart,
	Search,
	Trophy,
} from "lucide-react";
import type React from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useSimulationStore } from "@/components/simulation/simulationStore";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import type { EvolutionState } from "@/types/genetic-types";

interface Props {
	evoState: EvolutionState;
}

// Type for real strategy data from API
interface RealStrategy {
	id: string;
	rank: number;
	fitness: number;
	strategy: Record<string, unknown>;
	kpis: {
		total_pnl_pct?: number;
		max_drawdown_pct?: number;
		sharpe_ratio?: number;
		total_trades?: number;
		win_rate?: number;
		profit_factor?: number;
	};
}

const HallOfFame: React.FC<Props> = ({ evoState }) => {
	const { t } = useTranslation(["discovery", "common"]);
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const navigate = useNavigate();
	const { setStrategyJson } = useSimulationStore();
	const { toast } = useToast();

	// Get strategies from evoState.population (real data from API)
	const strategies: RealStrategy[] = useMemo(() => {
		return (evoState.population || []).map((item: unknown, i: number) => {
			const s =
				item && typeof item === "object"
					? (item as Record<string, unknown>)
					: {};
			return {
				id: typeof s.id === "string" ? s.id : `STRAT-${i + 1}`,
				rank: typeof s.rank === "number" ? s.rank : i + 1,
				fitness: typeof s.fitness === "number" ? s.fitness : 0,
				strategy:
					s.strategy && typeof s.strategy === "object"
						? (s.strategy as Record<string, unknown>)
						: {},
				kpis:
					s.kpis && typeof s.kpis === "object"
						? (s.kpis as RealStrategy["kpis"])
						: {},
			};
		});
	}, [evoState.population]);

	const selectedStrategy = useMemo(
		() => strategies.find((s) => s.id === selectedId),
		[selectedId, strategies],
	);

	// Helper to format strategy logic for display
	const formatStrategyLogic = (strategy: Record<string, unknown>) => {
		if (!strategy) return "No strategy data";

		try {
			// Try to extract conditions from strategy JSON
			const conditions = strategy.conditions || strategy.entry_conditions || [];
			if (Array.isArray(conditions) && conditions.length > 0) {
				return conditions
					.map((c: unknown) => {
						if (typeof c === "string") return c;
						return JSON.stringify(c);
					})
					.join(" AND ");
			}
			return `${JSON.stringify(strategy, null, 2).slice(0, 200)}...`;
		} catch {
			return "Unable to parse strategy";
		}
	};

	// Export all strategies as JSON
	const handleExportAll = () => {
		const dataStr = JSON.stringify(strategies, null, 2);
		const dataBlob = new Blob([dataStr], { type: "application/json" });
		const url = URL.createObjectURL(dataBlob);
		const link = document.createElement("a");
		link.href = url;
		link.download = `hall_of_fame_${new Date().toISOString().split("T")[0]}.json`;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		URL.revokeObjectURL(url);
	};

	// Export single strategy config
	const handleExportStrategy = (strategy: RealStrategy) => {
		const dataStr = JSON.stringify(strategy, null, 2);
		const dataBlob = new Blob([dataStr], { type: "application/json" });
		const url = URL.createObjectURL(dataBlob);
		const link = document.createElement("a");
		link.href = url;
		link.download = `strategy_${strategy.id}_${new Date().toISOString().split("T")[0]}.json`;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		URL.revokeObjectURL(url);
	};

	// Test strategy in simulator
	const handleTestStrategy = (strategy: RealStrategy) => {
		// Loading the strategy into simulationStore
		// strategy.strategy contains the strategy itself (filters, entryConditions, etc.)
		setStrategyJson(strategy.strategy);

		toast({
			title: t("common:strategyLoaded", "Strategy Loaded"),
			description: t(
				"discovery:hallOfFame.navigatingToSimulator",
				"Navigating to Inspector Matrix...",
			),
		});

		// Navigate to the Research page with the simulator tab
		navigate("/research?tab=simulator");
	};

	// Empty state if no strategies
	if (strategies.length === 0) {
		return (
			<div className="flex items-center justify-center h-full">
				<Card className="p-8 text-center border-2 border-dashed">
					<AlertCircle className="w-12 h-12 mx-auto mb-4 text-muted-foreground opacity-50" />
					<h3 className="text-lg font-bold mb-2">
						{t("discovery:hallOfFame.noStrategies", "No Strategies Found")}
					</h3>
					<p className="text-sm text-muted-foreground">
						{t(
							"discovery:hallOfFame.noStrategiesDesc",
							"Start a genetic search to discover winning strategies",
						)}
					</p>
				</Card>
			</div>
		);
	}

	return (
		<div className="grid grid-cols-1 lg:grid-cols-12 gap-6 h-full">
			{/* Top Strategies List */}
			<div className="lg:col-span-7">
				<Card className="h-full">
					<CardHeader className="pb-3 flex flex-row items-center justify-between">
						<CardTitle className="text-base font-bold flex items-center">
							<Trophy className="w-5 h-5 mr-3 text-amber-500" />
							{t("discovery:hallOfFame.title", "Elite Hall of Fame")}
							<Badge variant="secondary" className="ml-2">
								{strategies.length}
							</Badge>
						</CardTitle>
						<Button
							variant="ghost"
							size="sm"
							className="text-xs font-bold uppercase"
							onClick={handleExportAll}
						>
							<Download className="w-3 h-3 mr-1" />{" "}
							{t("common:export", "EXPORT")} JSON
						</Button>
					</CardHeader>

					<CardContent className="p-0">
						<Table>
							<TableHeader>
								<TableRow className="text-[10px] uppercase tracking-widest">
									<TableHead className="px-4">
										{t("common:id", "Strategy ID")}
									</TableHead>
									<TableHead className="text-center">
										{t("discovery:monitor.fitness", "Fitness")}
									</TableHead>
									<TableHead className="text-center">
										PnL ({t("common:train", "Train")})
									</TableHead>
									<TableHead className="text-center">
										{t("common:maxDD", "Max DD")}
									</TableHead>
									<TableHead className="text-center">Sharpe</TableHead>
									<TableHead></TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{strategies.map((strat, i) => (
									<TableRow
										key={strat.id}
										onClick={() => setSelectedId(strat.id)}
										className={`cursor-pointer ${selectedId === strat.id ? "bg-primary/5" : ""}`}
									>
										<TableCell className="px-4">
											<div className="flex items-center">
												<Badge
													variant="outline"
													className="w-6 h-6 flex items-center justify-center text-[10px] mr-3 font-mono"
												>
													{strat.rank || i + 1}
												</Badge>
												<div>
													<div className="text-sm font-bold">{strat.id}</div>
													<div className="text-[10px] text-muted-foreground truncate max-w-[150px] font-mono">
														{strat.kpis?.total_trades || 0} trades
													</div>
												</div>
											</div>
										</TableCell>
										<TableCell className="text-center font-mono text-sm font-bold text-emerald-500">
											{strat.fitness?.toFixed(2) || "N/A"}
										</TableCell>
										<TableCell
											className={`text-center font-mono text-sm ${(strat.kpis?.total_pnl_pct || 0) >= 0 ? "text-emerald-500" : "text-rose-500"}`}
										>
											{strat.kpis?.total_pnl_pct !== undefined
												? `${strat.kpis.total_pnl_pct >= 0 ? "+" : ""}${strat.kpis.total_pnl_pct.toFixed(1)}%`
												: "N/A"}
										</TableCell>
										<TableCell className="text-center font-mono text-sm text-rose-500">
											{strat.kpis?.max_drawdown_pct !== undefined
												? `-${Math.abs(strat.kpis.max_drawdown_pct).toFixed(1)}%`
												: "N/A"}
										</TableCell>
										<TableCell className="text-center font-mono text-sm text-primary">
											{strat.kpis?.sharpe_ratio?.toFixed(2) || "N/A"}
										</TableCell>
										<TableCell className="text-right">
											<ChevronRight
												className={`w-4 h-4 transition-transform ${selectedId === strat.id ? "rotate-90 text-primary" : "text-muted-foreground"}`}
											/>
										</TableCell>
									</TableRow>
								))}
							</TableBody>
						</Table>
					</CardContent>
				</Card>
			</div>

			{/* Strategy Inspector */}
			<div className="lg:col-span-5">
				{selectedStrategy ? (
					<Card className="h-full flex flex-col">
						<CardHeader className="pb-3 flex flex-row items-start justify-between">
							<div>
								<CardTitle className="text-xl font-bold">
									{selectedStrategy.id}
								</CardTitle>
								<p className="text-[10px] text-primary font-bold uppercase tracking-widest">
									{t("discovery:hallOfFame.inspector", "Candidate Inspector")}
								</p>
							</div>
							<div className="flex space-x-2">
								<Button
									variant="outline"
									size="icon"
									className="h-8 w-8"
									onClick={() => handleTestStrategy(selectedStrategy)}
									title={t("common:test", "Test")}
								>
									<FlaskConical className="w-4 h-4" />
								</Button>
								<Button
									variant="outline"
									size="icon"
									className="h-8 w-8"
									onClick={() => handleExportStrategy(selectedStrategy)}
									title={t("common:export", "Export")}
								>
									<Download className="w-4 h-4" />
								</Button>
								<Button
									variant="outline"
									size="icon"
									className="h-8 w-8"
									title={t("common:openInEditor", "Open in Editor")}
								>
									<ExternalLink className="w-4 h-4" />
								</Button>
							</div>
						</CardHeader>

						<CardContent className="space-y-6 flex-1 overflow-y-auto">
							{/* DNA Visualizer */}
							<div className="space-y-3">
								<h4 className="text-xs font-bold text-muted-foreground uppercase tracking-widest flex items-center">
									<Binary className="w-4 h-4 mr-2" />{" "}
									{t(
										"discovery:hallOfFame.dnaStructure",
										"Logic DNA Structure",
									)}
								</h4>
								<div className="bg-muted/50 p-4 rounded-lg border font-mono text-xs text-emerald-500 leading-relaxed overflow-x-auto">
									<pre className="whitespace-pre-wrap">
										{formatStrategyLogic(selectedStrategy.strategy)}
									</pre>
								</div>
							</div>

							{/* Advanced Metrics */}
							<div className="grid grid-cols-2 gap-3">
								<div className="bg-muted/30 p-4 rounded-lg border">
									<div className="text-[10px] text-muted-foreground font-bold uppercase mb-1">
										{t("common:totalTrades", "Total Trades")}
									</div>
									<div className="text-xl font-mono">
										{selectedStrategy.kpis?.total_trades || 0}
									</div>
								</div>
								<div className="bg-muted/30 p-4 rounded-lg border">
									<div className="text-[10px] text-muted-foreground font-bold uppercase mb-1">
										{t("common:winRate", "Win Rate")}
									</div>
									<div className="text-xl font-mono text-emerald-500">
										{selectedStrategy.kpis?.win_rate?.toFixed(1) || 0}%
									</div>
								</div>
								<div className="bg-muted/30 p-4 rounded-lg border">
									<div className="text-[10px] text-muted-foreground font-bold uppercase mb-1">
										Profit Factor
									</div>
									<div className="text-xl font-mono text-primary">
										{selectedStrategy.kpis?.profit_factor?.toFixed(2) || "N/A"}
									</div>
								</div>
								<div className="bg-muted/30 p-4 rounded-lg border">
									<div className="text-[10px] text-muted-foreground font-bold uppercase mb-1">
										Fitness Score
									</div>
									<div className="text-xl font-mono text-amber-500">
										{selectedStrategy.fitness?.toFixed(2) || 0}
									</div>
								</div>
							</div>

							{/* Full Strategy JSON Preview */}
							<div className="space-y-3">
								<h4 className="text-xs font-bold text-muted-foreground uppercase tracking-widest flex items-center">
									<LineChart className="w-4 h-4 mr-2" /> Strategy JSON
								</h4>
								<div className="bg-muted/30 p-3 rounded-lg border max-h-40 overflow-y-auto">
									<pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap">
										{JSON.stringify(selectedStrategy.strategy, null, 2)}
									</pre>
								</div>
							</div>
						</CardContent>

						<div className="p-4 border-t flex gap-2">
							<Button
								className="flex-1 font-bold uppercase"
								variant="default"
								onClick={() => handleTestStrategy(selectedStrategy)}
							>
								<FlaskConical className="w-4 h-4 mr-2" />
								{t("common:testInSimulator", "TEST IN SIMULATOR")}
							</Button>
							<Button
								className="flex-1 font-bold uppercase"
								variant="outline"
								onClick={() => handleExportStrategy(selectedStrategy)}
							>
								<Download className="w-4 h-4 mr-2" />
								{t("common:export", "EXPORT")}
							</Button>
						</div>
					</Card>
				) : (
					<Card className="h-full flex flex-col items-center justify-center text-muted-foreground border-2 border-dashed">
						<div className="p-4 bg-muted/30 rounded-full mb-4">
							<Search className="w-12 h-12 opacity-20" />
						</div>
						<p className="text-sm font-medium">
							{t(
								"discovery:hallOfFame.selectPrompt",
								"Select a strategy to inspect details",
							)}
						</p>
					</Card>
				)}
			</div>
		</div>
	);
};

export default HallOfFame;
