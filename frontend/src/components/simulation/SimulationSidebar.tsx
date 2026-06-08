// frontend/src/components/simulation/SimulationSidebar.tsx
// Configuration sidebar for simulation parameters

import {
	BarChart3,
	Calendar,
	CheckSquare,
	Loader2,
	Play,
	Search,
	Settings,
	Square,
	Upload,
} from "lucide-react";
import type React from "react";
import { useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/use-toast";
import { DownloadDataDialog } from "./DownloadDataDialog";
import { useSimulationStore } from "./simulationStore";
import { VariantPanel } from "./VariantPanel";

interface SimulationSidebarProps {
	onRunInspector: () => void;
	onRunSimulation: () => void;
}

export const SimulationSidebar: React.FC<SimulationSidebarProps> = ({
	onRunInspector,
	onRunSimulation,
}) => {
	const { t } = useTranslation("simulation");
	const { toast } = useToast();
	const fileInputRef = useRef<HTMLInputElement>(null);

	const {
		availableAssets,
		selectedAssets,
		toggleAsset,
		selectAllAssets,
		clearAssets,
		config,
		updateConfig,
		strategyJson,
		setStrategyJson,
		isLoading,
		setView,
		inspectorResult,
		startDate,
		endDate,
		setStartDate,
		setEndDate,
	} = useSimulationStore();

	const handleFileUpload = useCallback(
		async (e: React.ChangeEvent<HTMLInputElement>) => {
			const file = e.target.files?.[0];
			if (!file) return;

			try {
				const text = await file.text();
				const json = JSON.parse(text);
				setStrategyJson(json);
				toast({
					title: t("strategyLoaded", "Strategy Loaded"),
					description: file.name,
				});
			} catch {
				toast({
					title: t("error", "Error"),
					description: t("invalidJson", "Invalid JSON file"),
					variant: "destructive",
				});
			}

			// Reset input
			if (fileInputRef.current) {
				fileInputRef.current.value = "";
			}
		},
		[setStrategyJson, toast, t],
	);

	const handleRun = () => {
		if (!strategyJson) {
			toast({
				title: t("error", "Error"),
				description: t("uploadStrategy", "Please upload a strategy JSON first"),
				variant: "destructive",
			});
			return;
		}

		if (selectedAssets.length === 0) {
			toast({
				title: t("error", "Error"),
				description: t("selectAssets", "Please select at least one asset"),
				variant: "destructive",
			});
			return;
		}

		onRunInspector();
		setView("matrix");
	};

	return (
		<Card className="h-full flex flex-col">
			<CardHeader className="pb-4 border-b">
				<CardTitle className="flex items-center gap-2 text-lg">
					<Settings className="w-5 h-5 text-primary" />
					{t("simulationConfig", "Simulation Config")}
				</CardTitle>
			</CardHeader>

			<ScrollArea className="flex-1">
				<CardContent className="space-y-6 p-4">
					{/* Strategy Upload */}
					<section>
						<Label className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider mb-3">
							<Upload className="w-4 h-4" />
							{t("strategy", "Strategy")}
						</Label>
						<input
							type="file"
							ref={fileInputRef}
							accept=".json"
							onChange={handleFileUpload}
							className="hidden"
						/>
						<Button
							variant="outline"
							className="w-full"
							onClick={() => fileInputRef.current?.click()}
						>
							<Upload className="w-4 h-4 mr-2" />
							{strategyJson
								? t("changeStrategy", "Change Strategy")
								: t("uploadJson", "Upload JSON")}
						</Button>
						{strategyJson && (
							<Badge variant="secondary" className="mt-2 w-full justify-center">
								✓ {t("strategyLoaded", "Strategy loaded")}
							</Badge>
						)}
					</section>

					{/* Date Range Selection */}
					<section>
						<Label className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider mb-3">
							<Calendar className="w-4 h-4" />
							{t("dateRange", "Date Range")}
						</Label>
						<div className="space-y-2">
							<div className="grid grid-cols-2 gap-2">
								<div>
									<Label className="text-[10px] text-muted-foreground uppercase">
										{t("startDate", "Start Date")}
									</Label>
									<Input
										type="date"
										className="h-8 text-xs"
										value={startDate || ""}
										onChange={(e) => setStartDate(e.target.value || null)}
									/>
								</div>
								<div>
									<Label className="text-[10px] text-muted-foreground uppercase">
										{t("endDate", "End Date")}
									</Label>
									<Input
										type="date"
										className="h-8 text-xs"
										value={endDate || ""}
										onChange={(e) => setEndDate(e.target.value || null)}
									/>
								</div>
							</div>
						</div>
					</section>

					{/* Asset Selection */}
					<section>
						<div className="flex items-center justify-between mb-3">
							<Label className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider">
								<Search className="w-4 h-4" />
								{t("assets", "Assets")}
							</Label>
							<Badge variant="outline">{selectedAssets.length}</Badge>
						</div>

						<div className="mb-2">
							<DownloadDataDialog />
						</div>

						<div className="flex gap-2 mb-2">
							<Button
								size="sm"
								variant="outline"
								onClick={selectAllAssets}
								className="flex-1"
							>
								<CheckSquare className="w-3 h-3 mr-1" /> All
							</Button>
							<Button
								size="sm"
								variant="outline"
								onClick={clearAssets}
								className="flex-1"
							>
								<Square className="w-3 h-3 mr-1" /> None
							</Button>
						</div>
						<div className="grid grid-cols-2 gap-1.5 max-h-[200px] overflow-y-auto">
							{availableAssets.map((asset) => (
								<Button
									key={asset}
									size="sm"
									variant={
										selectedAssets.includes(asset) ? "default" : "outline"
									}
									className="text-xs font-mono h-8"
									onClick={() => toggleAsset(asset)}
								>
									{asset.replace("USDT", "")}
								</Button>
							))}
						</div>
					</section>

					{/* Strategy Variants */}
					<VariantPanel />

					{/* Simulation Config */}
					<section>
						<Label className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider mb-3">
							<Settings className="w-4 h-4" />
							{t("parameters", "Parameters")}
						</Label>
						<div className="space-y-4">
							<div>
								<div className="flex justify-between text-sm mb-1">
									<span>{t("initialCapital", "Initial Capital")}</span>
									<input
										type="number"
										min="10"
										step="10"
										value={config.initialCapital}
										onChange={(e) =>
											updateConfig({ initialCapital: Number(e.target.value) })
										}
										className="w-24 text-right font-mono text-primary bg-transparent border-b border-primary/50 focus:outline-none focus:border-primary"
									/>
								</div>
								<Slider
									value={[config.initialCapital]}
									onValueChange={([v]) => updateConfig({ initialCapital: v })}
									min={10}
									max={50000}
									step={10}
								/>
							</div>

							<div>
								<div className="flex justify-between text-sm mb-1">
									<span>{t("maxPositions", "Max Positions")}</span>
									<span className="font-mono text-primary">
										{config.maxConcurrentPositions}
									</span>
								</div>
								<Slider
									value={[config.maxConcurrentPositions]}
									onValueChange={([v]) =>
										updateConfig({ maxConcurrentPositions: v })
									}
									min={1}
									max={20}
									step={1}
								/>
							</div>

							<div>
								<div className="flex justify-between text-sm mb-1">
									<span>{t("riskPerTrade", "Risk per Trade")}</span>
									<span className="font-mono text-primary">
										{config.baseRiskPct}%
									</span>
								</div>
								<Slider
									value={[config.baseRiskPct]}
									onValueChange={([v]) => updateConfig({ baseRiskPct: v })}
									min={0.1}
									max={10}
									step={0.1}
								/>
							</div>

							<div>
								<div className="flex justify-between text-sm mb-1">
									<span>{t("leverage", "Leverage")}</span>
									<span className="font-mono text-primary">
										{config.leverage}x
									</span>
								</div>
								<Slider
									value={[config.leverage]}
									onValueChange={([v]) => updateConfig({ leverage: v })}
									min={1}
									max={125}
									step={1}
								/>
							</div>

							<div className="flex items-center justify-between">
								<span className="text-sm">
									{t("adaptiveRisk", "Adaptive Risk")}
								</span>
								<Switch
									checked={config.adaptiveRisk}
									onCheckedChange={(v) => updateConfig({ adaptiveRisk: v })}
								/>
							</div>

							<div className="flex items-center justify-between">
								<span className="text-sm">
									{t("compounding", "Compounding")}
								</span>
								<Switch
									checked={config.compounding}
									onCheckedChange={(v) => updateConfig({ compounding: v })}
								/>
							</div>
						</div>
					</section>
				</CardContent>
			</ScrollArea>

			{/* Run Buttons */}
			<div className="p-4 border-t space-y-2">
				<Button
					className="w-full"
					size="lg"
					variant="default"
					onClick={handleRun}
					disabled={isLoading || !strategyJson || selectedAssets.length === 0}
				>
					{isLoading ? (
						<>
							<Loader2 className="w-4 h-4 mr-2 animate-spin" />
							{t("running", "Running...")}
						</>
					) : (
						<>
							<Play className="w-4 h-4 mr-2" fill="currentColor" />
							{t("runInspector", "RUN INSPECTOR")}
						</>
					)}
				</Button>

				{/* Show only after inspector completion */}
				{inspectorResult && inspectorResult.assets.length > 0 && (
					<Button
						className="w-full"
						size="lg"
						variant="outline"
						onClick={onRunSimulation}
						disabled={isLoading}
					>
						<BarChart3 className="w-4 h-4 mr-2" />
						{t("runSingleDepositSim", "SINGLE DEPOSIT TRADING SIMULATOR")}
					</Button>
				)}
			</div>
		</Card>
	);
};
