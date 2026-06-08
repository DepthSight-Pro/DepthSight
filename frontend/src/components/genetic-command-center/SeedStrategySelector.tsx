// frontend/src/components/genetic-command-center/SeedStrategySelector.tsx
// Component for selecting seed strategies for GA continuation or optimization

import { RefreshCw, Shuffle, Sprout, Upload } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import type { SeedConfig } from "@/types/genetic-types";

interface GeneticRunInfo {
	id: string;
	config_json?: { name?: string };
	status: string;
	created_at: string;
}

interface Props {
	config: SeedConfig;
	onChange: (config: SeedConfig) => void;
	availableRuns: GeneticRunInfo[];
	isLoading?: boolean;
}

const SeedStrategySelector: React.FC<Props> = ({
	config,
	onChange,
	availableRuns,
}) => {
	const { t } = useTranslation(["discovery", "common"]);

	const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
		const file = e.target.files?.[0];
		if (!file) return;

		const reader = new FileReader();
		reader.onload = (event) => {
			try {
				const data = JSON.parse(event.target?.result as string);
				// Handle both array and single strategy
				const strategies = Array.isArray(data) ? data : [data];
				onChange({ ...config, strategies, mode: "upload" });
			} catch (error) {
				console.error("Failed to parse strategy JSON:", error);
			}
		};
		reader.readAsText(file);
	};

	const completedRuns = availableRuns.filter((r) => r.status === "COMPLETED");

	return (
		<Card>
			<CardHeader className="pb-3">
				<CardTitle className="text-sm font-bold uppercase tracking-widest flex items-center">
					<Sprout className="w-4 h-4 mr-2 text-emerald-500" />
					{t("discovery:gcc.seed.title", "Seed Strategy")}
					<Tooltip>
						<TooltipTrigger asChild>
							<Badge variant="outline" className="ml-2 text-[10px]">
								OPTIONAL
							</Badge>
						</TooltipTrigger>
						<TooltipContent>
							{t(
								"discovery:gcc.seed.tooltip",
								"Seed the population with existing strategies for continuation or optimization",
							)}
						</TooltipContent>
					</Tooltip>
				</CardTitle>
				<CardDescription className="text-xs">
					{t(
						"discovery:gcc.seed.description",
						"Continue from a previous run or optimize your strategy",
					)}
				</CardDescription>
			</CardHeader>

			<CardContent className="space-y-4">
				{/* Mode Selection */}
				<RadioGroup
					value={config.mode}
					onValueChange={(v) =>
						onChange({ ...config, mode: v as SeedConfig["mode"] })
					}
					className="space-y-3"
				>
					{/* Random (New Search) */}
					<div className="flex items-center space-x-3 p-3 rounded-lg border hover:border-primary/50 transition-colors cursor-pointer">
						<RadioGroupItem value="random" id="seed-random" />
						<Label
							htmlFor="seed-random"
							className="flex items-center cursor-pointer flex-1"
						>
							<Shuffle className="w-4 h-4 mr-2 text-muted-foreground" />
							<div>
								<span className="font-medium">
									{t("discovery:gcc.seed.random", "New Search")}
								</span>
								<p className="text-xs text-muted-foreground">
									{t(
										"discovery:gcc.seed.randomDesc",
										"Start fresh with random population",
									)}
								</p>
							</div>
						</Label>
					</div>

					{/* Continue from Previous Run */}
					<div
						className={`p-3 rounded-lg border transition-colors ${config.mode === "previous_run" ? "border-primary" : "hover:border-primary/50"}`}
					>
						<div className="flex items-center space-x-3">
							<RadioGroupItem value="previous_run" id="seed-previous" />
							<Label
								htmlFor="seed-previous"
								className="flex items-center cursor-pointer flex-1"
							>
								<RefreshCw className="w-4 h-4 mr-2 text-muted-foreground" />
								<div>
									<span className="font-medium">
										{t("discovery:gcc.seed.fromRun", "Continue from Run")}
									</span>
									<p className="text-xs text-muted-foreground">
										{t(
											"discovery:gcc.seed.fromRunDesc",
											"Use top strategies from a completed run",
										)}
									</p>
								</div>
							</Label>
						</div>

						{config.mode === "previous_run" && (
							<div className="mt-3 pl-7">
								<Select
									value={config.runId || ""}
									onValueChange={(v) => onChange({ ...config, runId: v })}
								>
									<SelectTrigger className="h-9">
										<SelectValue
											placeholder={t(
												"discovery:gcc.seed.selectRun",
												"Select a completed run",
											)}
										/>
									</SelectTrigger>
									<SelectContent>
										{completedRuns.length === 0 ? (
											<div className="p-2 text-sm text-muted-foreground">
												{t(
													"discovery:gcc.seed.noRuns",
													"No completed runs available",
												)}
											</div>
										) : (
											completedRuns.map((run) => (
												<SelectItem key={run.id} value={run.id}>
													{run.config_json?.name || "Unnamed"} (
													{new Date(run.created_at).toLocaleDateString()})
												</SelectItem>
											))
										)}
									</SelectContent>
								</Select>
							</div>
						)}
					</div>

					{/* Upload JSON */}
					<div
						className={`p-3 rounded-lg border transition-colors ${config.mode === "upload" ? "border-primary" : "hover:border-primary/50"}`}
					>
						<div className="flex items-center space-x-3">
							<RadioGroupItem value="upload" id="seed-upload" />
							<Label
								htmlFor="seed-upload"
								className="flex items-center cursor-pointer flex-1"
							>
								<Upload className="w-4 h-4 mr-2 text-muted-foreground" />
								<div>
									<span className="font-medium">
										{t("discovery:gcc.seed.upload", "Upload Strategy")}
									</span>
									<p className="text-xs text-muted-foreground">
										{t(
											"discovery:gcc.seed.uploadDesc",
											"Optimize your own strategy JSON",
										)}
									</p>
								</div>
							</Label>
						</div>

						{config.mode === "upload" && (
							<div className="mt-3 pl-7 space-y-2">
								<Input
									type="file"
									accept=".json"
									onChange={handleFileUpload}
									className="h-9"
								/>
								{config.strategies && config.strategies.length > 0 && (
									<Badge variant="secondary" className="text-xs">
										{config.strategies.length}{" "}
										{t("common:strategies", "strategies")} loaded
									</Badge>
								)}
							</div>
						)}
					</div>
				</RadioGroup>

				{/* Additional Options (shown when not random) */}
				{config.mode !== "random" && (
					<div className="space-y-4 pt-4 border-t">
						{/* Top N */}
						<div className="flex items-center justify-between">
							<Label className="text-sm">
								{t("discovery:gcc.seed.topN", "Seed Strategies Count")}
							</Label>
							<Input
								type="number"
								min={1}
								max={50}
								value={config.topN}
								onChange={(e) =>
									onChange({
										...config,
										topN: parseInt(e.target.value, 10) || 10,
									})
								}
								className="w-20 h-8 text-center"
							/>
						</div>

						{/* Keep Structure */}
						<div className="flex items-start space-x-3">
							<Checkbox
								id="keep-structure"
								checked={config.keepStructure}
								onCheckedChange={(checked) =>
									onChange({ ...config, keepStructure: !!checked })
								}
							/>
							<div className="space-y-1">
								<Label
									htmlFor="keep-structure"
									className="text-sm cursor-pointer"
								>
									{t(
										"discovery:gcc.seed.keepStructure",
										"Optimize Parameters Only",
									)}
								</Label>
								<p className="text-xs text-muted-foreground">
									{t(
										"discovery:gcc.seed.keepStructureDesc",
										"Keep block structure, only mutate numeric values (periods, thresholds)",
									)}
								</p>
							</div>
						</div>
					</div>
				)}
			</CardContent>
		</Card>
	);
};

export default SeedStrategySelector;
