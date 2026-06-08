// src/components/genetic-command-center/UniverseDataModule.tsx

import { Coins, Globe, Percent, Shield } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
	DEFAULT_UNIVERSE_CONFIG,
	INITIAL_ASSETS,
	type UniverseDataConfig,
} from "@/types/genetic-types";

interface UniverseDataModuleProps {
	config?: UniverseDataConfig;
	onChange?: (config: UniverseDataConfig) => void;
	availableAssets?: string[];
}

const UniverseDataModule: React.FC<UniverseDataModuleProps> = ({
	config = DEFAULT_UNIVERSE_CONFIG,
	onChange,
	availableAssets = [],
}) => {
	const { t } = useTranslation("discovery");

	// Use availableAssets if provided and not empty, otherwise fallback to INITIAL_ASSETS
	const assetsToDisplay =
		availableAssets && availableAssets.length > 0
			? availableAssets.map((id) => ({ id }))
			: INITIAL_ASSETS;

	const updateConfig = (partial: Partial<UniverseDataConfig>) => {
		if (onChange) {
			onChange({ ...config, ...partial });
		}
	};

	const toggleAsset = (assetId: string) => {
		const newAssets = config.assets.includes(assetId)
			? config.assets.filter((a) => a !== assetId)
			: [...config.assets, assetId];
		updateConfig({ assets: newAssets });
	};

	return (
		<Card>
			<CardHeader className="pb-3">
				<CardTitle className="text-base font-bold flex items-center">
					<Globe className="w-5 h-5 mr-3 text-blue-500" />
					{t("gcc.modules.universe.title", "Universe & Data Environment")}
				</CardTitle>
			</CardHeader>

			<CardContent className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
				{/* Asset Selection */}
				<div className="space-y-4">
					<label className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
						{t("gcc.modules.universe.assetBasket", "Asset Basket")}
					</label>
					<div className="grid grid-cols-2 gap-2 max-h-60 overflow-y-auto pr-1">
						{assetsToDisplay.map((asset) => (
							<button
								key={asset.id}
								onClick={() => toggleAsset(asset.id)}
								className={`px-3 py-2 text-sm rounded-lg border transition-all text-left ${
									config.assets.includes(asset.id)
										? "bg-primary/10 border-primary text-primary"
										: "bg-muted/50 border-border text-muted-foreground hover:border-primary/50"
								}`}
							>
								{asset.id}
							</button>
						))}
					</div>
				</div>

				{/* Training Slider */}
				<div className="space-y-4 pt-6 border-t border-border">
					<label className="text-sm font-semibold text-muted-foreground uppercase tracking-wider flex items-center justify-between">
						<span>
							{t("gcc.modules.universe.timeSlider", "Time-Machine Slider")}
						</span>
						<span className="text-xs font-mono text-emerald-500">
							{config.trainSplitPct}% {t("gcc.modules.universe.train", "Train")}{" "}
							/ {100 - config.trainSplitPct}%{" "}
							{t("gcc.modules.universe.oos", "OOS")}
						</span>
					</label>
					<input
						type="range"
						min="50"
						max="90"
						value={config.trainSplitPct}
						onChange={(e) =>
							updateConfig({ trainSplitPct: parseInt(e.target.value, 10) })
						}
						className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
					/>
					<div className="flex justify-between text-[10px] text-muted-foreground font-mono uppercase">
						<span>2023-01-01</span>
						<span>2024-01-01</span>
					</div>
					<div className="flex space-x-2 mt-3">
						<div
							className="h-2 bg-primary/50 rounded-full"
							style={{ width: `${config.trainSplitPct}%` }}
						/>
						<div
							className="h-2 bg-emerald-500/50 rounded-full"
							style={{ width: `${100 - config.trainSplitPct}%` }}
						/>
					</div>
				</div>

				{/* Env Config */}
				<div className="space-y-4 pt-6 border-t border-border">
					<label className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
						{t("gcc.modules.universe.environment", "Environment")}
					</label>
					<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
						<div className="p-4 bg-muted/30 border border-border rounded-lg space-y-2">
							<div className="text-[10px] text-muted-foreground uppercase font-bold">
								{t("gcc.modules.universe.tradingFee", "Trading Fee")}
							</div>
							<Percent className="w-4 h-4 text-muted-foreground" />
							<input
								className="bg-transparent text-sm outline-none w-full"
								value={config.tradingFee}
								onChange={(e) =>
									updateConfig({ tradingFee: parseFloat(e.target.value) || 0 })
								}
							/>
						</div>
						<div className="p-4 bg-muted/30 border border-border rounded-lg space-y-2">
							<div className="text-[10px] text-muted-foreground uppercase font-bold">
								{t("gcc.modules.universe.slippage", "Slippage (Model)")}
							</div>
							<Shield className="w-4 h-4 text-muted-foreground" />
							<input
								className="bg-transparent text-sm outline-none w-full"
								value={config.slippage}
								onChange={(e) =>
									updateConfig({ slippage: parseFloat(e.target.value) || 0 })
								}
							/>
						</div>
						<div className="p-4 bg-muted/30 border border-border rounded-lg space-y-2">
							<div className="text-[10px] text-muted-foreground uppercase font-bold">
								{t("gcc.modules.universe.initialCapital", "Initial Capital")}
							</div>
							<Coins className="w-4 h-4 text-muted-foreground" />
							<input
								className="bg-transparent text-sm outline-none w-full"
								value={config.initialCapital}
								onChange={(e) =>
									updateConfig({
										initialCapital:
											parseFloat(e.target.value.replace(/,/g, "")) || 0,
									})
								}
							/>
						</div>
					</div>
				</div>
			</CardContent>
		</Card>
	);
};

export default UniverseDataModule;
