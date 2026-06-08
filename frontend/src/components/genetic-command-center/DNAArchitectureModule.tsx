// src/components/genetic-command-center/DNAArchitectureModule.tsx

import {
	Activity,
	Dna,
	Filter,
	GitBranch,
	Layers,
	Scale,
	Settings2,
	ShieldCheck,
	Zap,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import type { DNAArchitectureConfig } from "@/types/genetic-types";
import GenePoolSettingsModal from "./GenePoolSettingsModal";

interface DNAArchitectureModuleProps {
	config?: DNAArchitectureConfig;
	onChange?: (config: DNAArchitectureConfig) => void;
}

const DNAArchitectureModule: React.FC<DNAArchitectureModuleProps> = ({
	config = DEFAULT_DNA_CONFIG,
	onChange,
}) => {
	const { t } = useTranslation("discovery");
	const [expandedId, setExpandedId] = useState<string | null>(null);
	const [modalOpen, setModalOpen] = useState(false);

	const updateConfig = (partial: Partial<DNAArchitectureConfig>) => {
		if (onChange) {
			onChange({ ...config, ...partial });
		}
	};

	const toggleIndicator = (id: string) => {
		const newIndicators = config.indicators.map((ind: IndicatorConfig) =>
			ind.id === id ? { ...ind, active: !ind.active } : ind,
		);
		updateConfig({ indicators: newIndicators });
	};

	const updateIndicatorRange = (
		id: string,
		field: "minPeriod" | "maxPeriod",
		val: number,
	) => {
		const newIndicators = config.indicators.map((ind: IndicatorConfig) =>
			ind.id === id ? { ...ind, [field]: val } : ind,
		);
		updateConfig({ indicators: newIndicators });
	};

	const toggleTimeframe = (indId: string, tf: string) => {
		const newIndicators = config.indicators.map((ind: IndicatorConfig) => {
			if (ind.id !== indId) return ind;
			const newTfs = ind.timeframes.includes(tf)
				? ind.timeframes.filter((t) => t !== tf)
				: [...ind.timeframes, tf];
			return { ...ind, timeframes: newTfs };
		});
		updateConfig({ indicators: newIndicators });
	};

	return (
		<Card>
			<CardHeader className="pb-3">
				<div className="flex items-center justify-between">
					<CardTitle className="text-base font-bold flex items-center">
						<Dna className="w-5 h-5 mr-3 text-emerald-500" />
						{t("gcc.modules.dna.title", "DNA Architecture & Gene Editor")}
					</CardTitle>
					<Button
						variant="outline"
						size="sm"
						onClick={() => setModalOpen(true)}
						className="flex items-center gap-2"
					>
						<Layers className="w-4 h-4" />
						{t("gcc.modules.dna.advancedSettings", "Advanced Settings")}
					</Button>
				</div>
			</CardHeader>

			<CardContent className="space-y-8">
				{/* Indicators Manager with Gene Overrides */}
				<div className="space-y-3">
					<label className="text-sm font-semibold text-muted-foreground uppercase tracking-wider block">
						{t("gcc.modules.dna.genePool", "Gene Pool (Indicator Overrides)")}
					</label>
					<div className="grid grid-cols-1 gap-3">
						{config.indicators.map((ind) => (
							<div key={ind.id} className="group">
								<div
									className={`p-4 rounded-lg border transition-all flex items-center justify-between ${
										ind.active
											? "bg-emerald-500/5 border-emerald-500/30"
											: "bg-muted/30 border-border"
									}`}
								>
									<div className="flex items-center space-x-4">
										<input
											type="checkbox"
											checked={ind.active}
											onChange={() => toggleIndicator(ind.id)}
											className="w-5 h-5 rounded accent-emerald-500 cursor-pointer"
										/>
										<div>
											<div
												className={`text-sm font-bold ${ind.active ? "text-emerald-500" : "text-muted-foreground"}`}
											>
												{ind.name}
											</div>
											<div className="text-[10px] text-muted-foreground font-mono">
												{t("gcc.modules.dna.indicatorRange", "Range")}:{" "}
												{ind.minPeriod}-{ind.maxPeriod} | TFs:{" "}
												{ind.timeframes.join(", ")}
											</div>
										</div>
									</div>
									<button
										onClick={() =>
											setExpandedId(expandedId === ind.id ? null : ind.id)
										}
										className={`p-2 rounded-lg transition-colors ${expandedId === ind.id ? "bg-emerald-500/20 text-emerald-500" : "hover:bg-muted text-muted-foreground"}`}
									>
										<Settings2 className="w-4 h-4" />
									</button>
								</div>

								{expandedId === ind.id && (
									<div className="mt-2 p-4 bg-muted/30 border border-border rounded-lg grid grid-cols-1 md:grid-cols-2 gap-4">
										<div className="space-y-2">
											<div className="text-xs font-bold text-muted-foreground uppercase">
												{t(
													"gcc.modules.dna.searchRange",
													"Search Range (Period)",
												)}
											</div>
											<div className="flex items-center space-x-4">
												<div className="flex-1 space-y-1">
													<span className="text-[10px] text-muted-foreground">
														{t("common:min", "Min")}
													</span>
													<input
														type="number"
														value={ind.minPeriod}
														onChange={(e) =>
															updateIndicatorRange(
																ind.id,
																"minPeriod",
																parseInt(e.target.value, 10) || 1,
															)
														}
														className="w-full bg-background border border-border rounded-lg p-2 text-sm font-mono text-emerald-500 outline-none"
													/>
												</div>
												<div className="flex-1 space-y-1">
													<span className="text-[10px] text-muted-foreground">
														{t("common:max", "Max")}
													</span>
													<input
														type="number"
														value={ind.maxPeriod}
														onChange={(e) =>
															updateIndicatorRange(
																ind.id,
																"maxPeriod",
																parseInt(e.target.value, 10) || 1,
															)
														}
														className="w-full bg-background border border-border rounded-lg p-2 text-sm font-mono text-emerald-500 outline-none"
													/>
												</div>
											</div>
										</div>
										<div className="space-y-2">
											<div className="text-xs font-bold text-muted-foreground uppercase">
												{t("gcc.modules.dna.allowedTFs", "Allowed Timeframes")}
											</div>
											<div className="flex flex-wrap gap-2">
												{["1m", "5m", "15m", "1h", "4h"].map((tf) => (
													<button
														key={tf}
														onClick={() => toggleTimeframe(ind.id, tf)}
														className={`px-2 py-1 text-[10px] rounded border ${ind.timeframes.includes(tf) ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-500" : "bg-muted border-border text-muted-foreground"}`}
													>
														{tf}
													</button>
												))}
											</div>
										</div>
									</div>
								)}
							</div>
						))}
					</div>
				</div>

				{/* Advanced Filters */}
				<div className="pt-6 border-t border-border space-y-4">
					<label className="text-sm font-semibold text-muted-foreground uppercase tracking-wider block flex items-center">
						<Filter className="w-4 h-4 mr-2 text-amber-500" />
						{t("gcc.modules.dna.discoveryFilters", "Genetic Discovery Filters")}
					</label>
					<div className="grid grid-cols-1 md:grid-cols-3 gap-4">
						<div className="p-4 bg-muted/30 border border-border rounded-lg space-y-2">
							<div className="flex items-center justify-between">
								<div className="flex items-center text-xs font-bold text-primary uppercase tracking-wider">
									<Scale className="w-3 h-3 mr-2" />{" "}
									{t(
										"gcc.modules.dna.filters.correlationLimit",
										"Correlation Limit",
									)}
								</div>
								<Switch
									checked={config.correlationLimit > 0}
									onCheckedChange={(checked) =>
										updateConfig({ correlationLimit: checked ? 0.7 : 0 })
									}
								/>
							</div>
							<div className="flex items-center space-x-2">
								<input
									type="range"
									min="0"
									max="100"
									value={config.correlationLimit * 100}
									onChange={(e) =>
										updateConfig({
											correlationLimit: parseInt(e.target.value, 10) / 100,
										})
									}
									className="flex-1 h-1 bg-muted accent-primary"
								/>
								<span className="text-[10px] font-mono text-muted-foreground">
									{config.correlationLimit.toFixed(2)}
								</span>
							</div>
							<p className="text-[9px] text-muted-foreground">
								{t(
									"gcc.modules.dna.filters.correlationLimitDesc",
									"Filters out strategies using highly correlated indicators.",
								)}
							</p>
						</div>

						<div className="p-4 bg-muted/30 border border-border rounded-lg space-y-2">
							<div className="flex items-center justify-between">
								<div className="flex items-center text-xs font-bold text-emerald-500 uppercase tracking-wider">
									<Zap className="w-3 h-3 mr-2" />{" "}
									{t("gcc.modules.dna.filters.signalPruning", "Signal Pruning")}
								</div>
								<Switch
									checked={config.signalPruning}
									onCheckedChange={(checked) =>
										updateConfig({ signalPruning: checked })
									}
								/>
							</div>
							<p className="text-[9px] text-muted-foreground">
								{t(
									"gcc.modules.dna.filters.signalPruningDesc",
									"Removes redundant logic nodes that don't change signal outcome.",
								)}
							</p>
						</div>

						<div className="p-4 bg-muted/30 border border-border rounded-lg space-y-2">
							<div className="flex items-center justify-between">
								<div className="flex items-center text-xs font-bold text-amber-500 uppercase tracking-wider">
									<Activity className="w-3 h-3 mr-2" />{" "}
									{t(
										"gcc.modules.dna.filters.outlierRejection",
										"Outlier Rejection",
									)}
								</div>
								<Switch
									checked={config.outlierRejection}
									onCheckedChange={(checked) =>
										updateConfig({ outlierRejection: checked })
									}
								/>
							</div>
							<p className="text-[9px] text-muted-foreground">
								{t(
									"gcc.modules.dna.filters.outlierRejectionDesc",
									'Ignores strategies that depend on single "lucky" huge trades.',
								)}
							</p>
						</div>
					</div>
				</div>

				{/* Tree Complexity */}
				<div className="pt-6 border-t border-border grid grid-cols-1 md:grid-cols-2 gap-6">
					<div className="space-y-3">
						<h4 className="text-xs font-bold text-muted-foreground uppercase tracking-widest flex items-center">
							<GitBranch className="w-3 h-3 mr-2" />{" "}
							{t(
								"gcc.modules.dna.logicTreeDepth",
								"Logic Tree Depth (Complexity)",
							)}
						</h4>
						<div className="flex items-center space-x-4 bg-muted/30 p-4 rounded-lg border border-border">
							<input
								type="range"
								min="1"
								max="7"
								value={config.logicTreeDepth}
								onChange={(e) =>
									updateConfig({ logicTreeDepth: parseInt(e.target.value, 10) })
								}
								className="flex-1 h-1.5 bg-muted rounded-lg appearance-none accent-emerald-500"
							/>
							<div className="px-3 py-1 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
								<span className="text-sm font-bold text-emerald-500 font-mono">
									D-{config.logicTreeDepth}
								</span>
							</div>
						</div>
					</div>

					<div className="space-y-3">
						<h4 className="text-xs font-bold text-muted-foreground uppercase tracking-widest flex items-center">
							<ShieldCheck className="w-3 h-3 mr-2" />{" "}
							{t(
								"gcc.modules.dna.diversityEnforcement",
								"Diversity Enforcement",
							)}
						</h4>
						<div className="flex items-center justify-between p-4 bg-muted/30 rounded-lg border border-border">
							<span className="text-xs">
								{t("gcc.modules.dna.penalizeSimilarity", "Penalize Similarity")}
							</span>
							<Switch
								checked={config.diversityPenalty}
								onCheckedChange={(checked) =>
									updateConfig({ diversityPenalty: checked })
								}
							/>
						</div>
					</div>
				</div>
			</CardContent>

			{/* Advanced Gene Pool Settings Modal */}
			<GenePoolSettingsModal
				open={modalOpen}
				onOpenChange={setModalOpen}
				config={config.genePool}
				onChange={(newGenePool) => updateConfig({ genePool: newGenePool })}
			/>
		</Card>
	);
};

export default DNAArchitectureModule;
