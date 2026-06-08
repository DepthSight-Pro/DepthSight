// src/components/genetic-command-center/FitnessLabModule.tsx

import { AlertTriangle, Dna, Info, Target, Users } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
	DEFAULT_FITNESS_CONFIG,
	type FitnessLabConfig,
	type FitnessWeights,
} from "@/types/genetic-types";

interface FitnessLabModuleProps {
	config?: FitnessLabConfig;
	onChange?: (config: FitnessLabConfig) => void;
	// Legacy props for backward compatibility
	weights?: FitnessWeights;
	setWeights?: React.Dispatch<React.SetStateAction<FitnessWeights>>;
}

const FitnessLabModule: React.FC<FitnessLabModuleProps> = ({
	config,
	onChange,
	weights: legacyWeights,
	setWeights: legacySetWeights,
}) => {
	const { t } = useTranslation(["discovery", "common"]);

	// Use internal state if no config prop, for standalone usage
	const [internalConfig, setInternalConfig] = useState<FitnessLabConfig>(
		DEFAULT_FITNESS_CONFIG,
	);

	// Determine which weights to use (new config vs legacy props vs internal)
	const currentWeights =
		config?.weights ?? legacyWeights ?? internalConfig.weights;
	const currentKillSwitches =
		config?.killSwitches ?? internalConfig.killSwitches;
	const currentEvolution = config?.evolution ?? internalConfig.evolution;

	/**
	 * Smart weight balancing - when one weight changes, others adjust proportionally to maintain sum of 100
	 */
	const handleWeightChange = (key: keyof FitnessWeights, value: number) => {
		const newValue = Math.min(100, Math.max(0, value));
		const otherKeys = (
			Object.keys(currentWeights) as (keyof FitnessWeights)[]
		).filter((k) => k !== key);

		// Remaining budget to distribute among others
		const remainingBudget = 100 - newValue;
		const currentOtherTotal = otherKeys.reduce(
			(sum, k) => sum + currentWeights[k],
			0,
		);

		const newWeights: FitnessWeights = { ...currentWeights, [key]: newValue };

		if (currentOtherTotal > 0) {
			// Distribute remainder proportionally based on current values
			otherKeys.forEach((k) => {
				newWeights[k] = Math.round(
					(currentWeights[k] / currentOtherTotal) * remainingBudget,
				);
			});
		} else {
			// If others were zero, split evenly
			const equalShare = Math.floor(remainingBudget / otherKeys.length);
			otherKeys.forEach((k, idx) => {
				newWeights[k] =
					idx === 0
						? remainingBudget - equalShare * (otherKeys.length - 1)
						: equalShare;
			});
		}

		// Fix rounding errors to ensure sum is exactly 100
		const finalTotal = Object.values(newWeights).reduce((a, b) => a + b, 0);
		if (finalTotal !== 100) {
			const diff = 100 - finalTotal;
			newWeights[otherKeys[0]] += diff;
		}

		// Prevent negative values
		const hasNegative = Object.values(newWeights).some((v) => v < 0);
		if (hasNegative) return;

		// Update via appropriate method
		if (onChange && config) {
			onChange({ ...config, weights: newWeights });
		} else if (legacySetWeights) {
			legacySetWeights(newWeights);
		} else {
			setInternalConfig((prev) => ({ ...prev, weights: newWeights }));
		}
	};

	const handleKillSwitchChange = (
		key: "maxDD" | "minTrades",
		value: number,
	) => {
		const newKillSwitches = { ...currentKillSwitches, [key]: value };
		if (onChange && config) {
			onChange({ ...config, killSwitches: newKillSwitches });
		} else {
			setInternalConfig((prev) => ({ ...prev, killSwitches: newKillSwitches }));
		}
	};

	const handleEvolutionChange = (
		key: "generations" | "populationSize",
		value: number,
	) => {
		const newEvolution = { ...currentEvolution, [key]: value };
		if (onChange && config) {
			onChange({ ...config, evolution: newEvolution });
		} else {
			setInternalConfig((prev) => ({ ...prev, evolution: newEvolution }));
		}
	};

	return (
		<Card>
			<CardHeader className="pb-3">
				<div className="flex justify-between items-center">
					<CardTitle className="text-base font-bold flex items-center">
						<Target className="w-5 h-5 mr-3 text-primary" />
						{t(
							"discovery:gcc.modules.fitness.title",
							"Fitness Objective Mixer",
						)}
					</CardTitle>
					<div className="text-xs px-2 py-1 rounded font-mono bg-emerald-500/20 text-emerald-500 border border-emerald-500/30">
						{t("common:total", "Total")}: 100%
					</div>
				</div>
			</CardHeader>

			<CardContent className="space-y-6">
				{/* Visual Weight Distribution Bar */}
				<div className="h-10 w-full rounded-xl overflow-hidden flex shadow-inner bg-muted border border-border">
					<div
						style={{ width: `${currentWeights.pnl}%` }}
						className="bg-emerald-500 flex items-center justify-center text-emerald-950 font-bold text-xs transition-all duration-300 border-r border-black/10"
					>
						{currentWeights.pnl > 10 && `PNL ${currentWeights.pnl}%`}
					</div>
					<div
						style={{ width: `${currentWeights.drawdown}%` }}
						className="bg-rose-500 flex items-center justify-center text-rose-950 font-bold text-xs transition-all duration-300 border-r border-black/10"
					>
						{currentWeights.drawdown > 10 && `DD ${currentWeights.drawdown}%`}
					</div>
					<div
						style={{ width: `${currentWeights.consistency}%` }}
						className="bg-blue-500 flex items-center justify-center text-blue-950 font-bold text-xs transition-all duration-300"
					>
						{currentWeights.consistency > 10 &&
							`STAB ${currentWeights.consistency}%`}
					</div>
				</div>

				{/* Weight Sliders */}
				<div className="grid grid-cols-1 gap-6">
					{/* PnL Weight */}
					<div className="space-y-3">
						<div className="flex justify-between items-end">
							<div>
								<span className="block text-sm font-medium">
									{t("discovery:gcc.modules.fitness.pnlLabel", "Net Profit")}
								</span>
								<span className="text-[10px] text-muted-foreground uppercase">
									{t("discovery:gcc.modules.fitness.pnlDesc", "Profit")}
								</span>
							</div>
							<span className="text-emerald-500 font-mono font-bold text-lg">
								{currentWeights.pnl}%
							</span>
						</div>
						<input
							type="range"
							min="0"
							max="100"
							step="1"
							value={currentWeights.pnl}
							onChange={(e) =>
								handleWeightChange("pnl", parseInt(e.target.value, 10))
							}
							className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-emerald-500"
						/>
					</div>

					{/* Drawdown Weight */}
					<div className="space-y-3">
						<div className="flex justify-between items-end">
							<div>
								<span className="block text-sm font-medium">
									{t("discovery:gcc.modules.fitness.drawdownLabel", "Drawdown")}
								</span>
								<span className="text-[10px] text-muted-foreground uppercase">
									{t("discovery:gcc.modules.fitness.drawdownDesc", "Drawdown")}
								</span>
							</div>
							<span className="text-rose-500 font-mono font-bold text-lg">
								{currentWeights.drawdown}%
							</span>
						</div>
						<input
							type="range"
							min="0"
							max="100"
							step="1"
							value={currentWeights.drawdown}
							onChange={(e) =>
								handleWeightChange("drawdown", parseInt(e.target.value, 10))
							}
							className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-rose-500"
						/>
					</div>

					{/* Consistency Weight */}
					<div className="space-y-3">
						<div className="flex justify-between items-end">
							<div>
								<span className="block text-sm font-medium">
									{t(
										"discovery:gcc.modules.fitness.consistencyLabel",
										"Consistency",
									)}
								</span>
								<span className="text-[10px] text-muted-foreground uppercase">
									{t(
										"discovery:gcc.modules.fitness.consistencyDesc",
										"Stability",
									)}
								</span>
							</div>
							<span className="text-blue-500 font-mono font-bold text-lg">
								{currentWeights.consistency}%
							</span>
						</div>
						<input
							type="range"
							min="0"
							max="100"
							step="1"
							value={currentWeights.consistency}
							onChange={(e) =>
								handleWeightChange("consistency", parseInt(e.target.value, 10))
							}
							className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-blue-500"
						/>
					</div>
				</div>

				{/* Evolution Parameters Section */}
				<div className="pt-4 border-t border-border border-l-4 border-l-primary pl-4 rounded-r-lg bg-primary/5">
					<div className="flex items-center gap-2 mb-4">
						<Dna className="w-5 h-5 text-primary" />
						<h4 className="text-sm font-semibold">
							{t(
								"discovery:gcc.modules.fitness.evolutionParams",
								"Evolution Parameters",
							)}
						</h4>
					</div>

					<div className="grid grid-cols-2 gap-4">
						<div className="space-y-2">
							<label className="flex items-center text-xs font-medium text-muted-foreground gap-1">
								{t("discovery:gcc.modules.fitness.generations", "GENERATIONS")}
								<Info className="w-3 h-3 cursor-help" />
							</label>
							<div className="relative">
								<input
									type="number"
									min="5"
									max="500"
									value={currentEvolution.generations}
									onChange={(e) =>
										handleEvolutionChange(
											"generations",
											parseInt(e.target.value, 10) || 10,
										)
									}
									className="w-full bg-background border border-border rounded-lg p-3 pr-8 text-sm font-mono focus:ring-2 focus:ring-primary outline-none transition-all"
								/>
								<Dna className="absolute right-3 top-3 w-4 h-4 text-muted-foreground" />
							</div>
						</div>

						<div className="space-y-2">
							<label className="flex items-center text-xs font-medium text-muted-foreground gap-1">
								{t(
									"discovery:gcc.modules.fitness.populationSize",
									"POPULATION SIZE",
								)}
								<Info className="w-3 h-3 cursor-help" />
							</label>
							<div className="relative">
								<input
									type="number"
									min="20"
									max="500"
									value={currentEvolution.populationSize}
									onChange={(e) =>
										handleEvolutionChange(
											"populationSize",
											parseInt(e.target.value, 10) || 50,
										)
									}
									className="w-full bg-background border border-border rounded-lg p-3 pr-8 text-sm font-mono focus:ring-2 focus:ring-primary outline-none transition-all"
								/>
								<Users className="absolute right-3 top-3 w-4 h-4 text-muted-foreground" />
							</div>
						</div>
					</div>

					<p className="text-[10px] text-muted-foreground italic mt-3">
						{t(
							"discovery:gcc.modules.fitness.evolutionHelp",
							"More generations = better results but longer runtime. Larger population = more diversity.",
						)}
					</p>
				</div>

				{/* Kill Switches Section */}
				<div className="pt-4 border-t border-border border-l-4 border-l-rose-500 pl-4 rounded-r-lg bg-rose-500/5">
					<div className="flex items-center gap-2 mb-4">
						<AlertTriangle className="w-5 h-5 text-rose-500" />
						<h4 className="text-sm font-semibold">
							{t(
								"discovery:gcc.modules.fitness.killSwitches",
								"Kill Switches (Hard Gates)",
							)}
						</h4>
					</div>

					<div className="grid grid-cols-2 gap-4">
						<div className="space-y-2">
							<label className="flex items-center text-xs font-medium text-muted-foreground gap-1">
								{t("discovery:gcc.modules.fitness.maxDDLabel", "MAX DRAWDOWN")}
								<Info className="w-3 h-3 cursor-help" />
							</label>
							<div className="relative">
								<input
									type="number"
									value={currentKillSwitches.maxDD}
									onChange={(e) =>
										handleKillSwitchChange(
											"maxDD",
											parseInt(e.target.value, 10) || 0,
										)
									}
									className="w-full bg-background border border-border rounded-lg p-3 pr-8 text-sm font-mono focus:ring-2 focus:ring-rose-500 outline-none transition-all"
								/>
								<span className="absolute right-3 top-3 text-muted-foreground font-mono">
									%
								</span>
							</div>
						</div>

						<div className="space-y-2">
							<label className="flex items-center text-xs font-medium text-muted-foreground gap-1">
								{t(
									"discovery:gcc.modules.fitness.minTradesLabel",
									"MIN TRADES",
								)}
								<Info className="w-3 h-3 cursor-help" />
							</label>
							<div className="relative">
								<input
									type="number"
									value={currentKillSwitches.minTrades}
									onChange={(e) =>
										handleKillSwitchChange(
											"minTrades",
											parseInt(e.target.value, 10) || 0,
										)
									}
									className="w-full bg-background border border-border rounded-lg p-3 pr-8 text-sm font-mono focus:ring-2 focus:ring-rose-500 outline-none transition-all"
								/>
								<span className="absolute right-3 top-3 text-muted-foreground font-mono">
									#
								</span>
							</div>
						</div>
					</div>

					<p className="text-[10px] text-muted-foreground italic mt-3">
						{t(
							"discovery:gcc.modules.fitness.killSwitchHelp",
							"Violating these gates sets fitness score to -9999.0 immediately.",
						)}
					</p>
				</div>
			</CardContent>
		</Card>
	);
};

export default FitnessLabModule;
