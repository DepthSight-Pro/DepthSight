// src/components/genetic-command-center/ExecutionRiskModule.tsx

import {
	Clock,
	MoveDiagonal,
	Plus,
	Scissors,
	Shield,
	Trash2,
	Zap,
} from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import {
	DEFAULT_EXECUTION_CONFIG,
	type ExecutionRiskConfig,
} from "@/types/genetic-types";

interface ExecutionRiskModuleProps {
	config?: ExecutionRiskConfig;
	onChange?: (config: ExecutionRiskConfig) => void;
}

const ExecutionRiskModule: React.FC<ExecutionRiskModuleProps> = ({
	config = DEFAULT_EXECUTION_CONFIG,
	onChange,
}) => {
	const { t } = useTranslation("discovery");

	const updateConfig = (partial: Partial<ExecutionRiskConfig>) => {
		if (onChange) {
			onChange({ ...config, ...partial });
		}
	};

	const addPartial = () => {
		if (config.partialTPs.length < 3) {
			const newPartials = [
				...config.partialTPs,
				{
					id: Date.now(),
					sizePctRange: [20, 40] as [number, number],
					targetRRRange: [2.0, 4.0] as [number, number],
				},
			];
			updateConfig({ partialTPs: newPartials });
		}
	};

	const removePartial = (id: number) => {
		updateConfig({ partialTPs: config.partialTPs.filter((p) => p.id !== id) });
	};

	const updatePartial = (
		id: number,
		field: "sizePctRange" | "targetRRRange",
		index: 0 | 1,
		value: number,
	) => {
		const newPartials = config.partialTPs.map((p) => {
			if (p.id !== id) return p;
			const newRange = [...p[field]] as [number, number];
			newRange[index] = value;
			return { ...p, [field]: newRange };
		});
		updateConfig({ partialTPs: newPartials });
	};

	return (
		<Card>
			<CardHeader className="pb-3">
				<CardTitle className="text-base font-bold flex items-center">
					<Shield className="w-5 h-5 mr-3 text-rose-500" />
					{t("gcc.modules.risk.title", "Execution & Risk Management")}
				</CardTitle>
			</CardHeader>

			<CardContent className="space-y-8">
				{/* Core Boundaries */}
				<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
					<div className="space-y-3">
						<label className="text-xs font-bold text-muted-foreground uppercase tracking-widest">
							{t("gcc.modules.risk.stopLossRange", "Stop Loss Range")}
						</label>
						<div className="grid grid-cols-2 gap-2">
							<div className="bg-muted/50 border border-border rounded-lg p-2">
								<div className="text-[9px] text-muted-foreground uppercase font-bold">
									{t("common:min", "Min")} ATR
								</div>
								<input
									type="number"
									step="0.1"
									value={config.slRange[0]}
									onChange={(e) =>
										updateConfig({
											slRange: [
												parseFloat(e.target.value) || 0,
												config.slRange[1],
											],
										})
									}
									className="bg-transparent text-sm outline-none w-full font-mono"
								/>
							</div>
							<div className="bg-muted/50 border border-border rounded-lg p-2">
								<div className="text-[9px] text-muted-foreground uppercase font-bold">
									{t("common:max", "Max")} ATR
								</div>
								<input
									type="number"
									step="0.1"
									value={config.slRange[1]}
									onChange={(e) =>
										updateConfig({
											slRange: [
												config.slRange[0],
												parseFloat(e.target.value) || 0,
											],
										})
									}
									className="bg-transparent text-sm outline-none w-full font-mono"
								/>
							</div>
						</div>
					</div>

					<div className="space-y-3">
						<label className="text-xs font-bold text-muted-foreground uppercase tracking-widest">
							{t("gcc.modules.risk.takeProfitRR", "Take Profit (RR)")}
						</label>
						<div className="grid grid-cols-2 gap-2">
							<div className="bg-muted/50 border border-border rounded-lg p-2">
								<div className="text-[9px] text-muted-foreground uppercase font-bold">
									{t("common:min", "Min")} RR
								</div>
								<input
									type="number"
									step="0.1"
									value={config.tpRange[0]}
									onChange={(e) =>
										updateConfig({
											tpRange: [
												parseFloat(e.target.value) || 0,
												config.tpRange[1],
											],
										})
									}
									className="bg-transparent text-sm outline-none w-full font-mono"
								/>
							</div>
							<div className="bg-muted/50 border border-border rounded-lg p-2">
								<div className="text-[9px] text-muted-foreground uppercase font-bold">
									{t("common:max", "Max")} RR
								</div>
								<input
									type="number"
									step="0.1"
									value={config.tpRange[1]}
									onChange={(e) =>
										updateConfig({
											tpRange: [
												config.tpRange[0],
												parseFloat(e.target.value) || 0,
											],
										})
									}
									className="bg-transparent text-sm outline-none w-full font-mono"
								/>
							</div>
						</div>
					</div>

					<div className="space-y-3 lg:col-span-2">
						<label className="text-xs font-bold text-muted-foreground uppercase tracking-widest">
							{t("gcc.modules.risk.trailingDynamics", "Trailing Dynamics")}
						</label>
						<div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
							<div className="flex flex-col justify-center p-3 bg-muted/30 rounded-lg border border-border">
								<div className="flex items-center justify-between mb-2">
									<span className="text-[10px] text-muted-foreground font-bold uppercase">
										{t("gcc.modules.risk.activationRR", "Activation RR")}
									</span>
									<input
										type="number"
										step="0.1"
										value={config.trailingActivationRR}
										onChange={(e) =>
											updateConfig({
												trailingActivationRR: parseFloat(e.target.value) || 0,
											})
										}
										className="bg-transparent text-xs text-right text-emerald-500 font-mono outline-none w-10"
									/>
								</div>
								<input
									type="range"
									min="0.5"
									max="5"
									step="0.1"
									value={config.trailingActivationRR}
									onChange={(e) =>
										updateConfig({
											trailingActivationRR: parseFloat(e.target.value),
										})
									}
									className="w-full h-1 bg-muted accent-emerald-500"
								/>
							</div>
							<div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg border border-border">
								<div className="flex items-center">
									<Zap className="w-4 h-4 text-emerald-500 mr-3" />
									<span className="text-xs">
										{t("gcc.modules.risk.strictTrailing", "Strict Trailing")}
									</span>
								</div>
								<Switch
									checked={config.strictTrailing}
									onCheckedChange={(checked) =>
										updateConfig({ strictTrailing: checked })
									}
								/>
							</div>
						</div>
					</div>
				</div>

				{/* Advanced Exit Logic */}
				<div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pt-6 border-t border-border">
					{/* Enhanced Breakeven */}
					<div className="bg-muted/20 border border-border rounded-xl p-5 space-y-4">
						<div className="flex items-center justify-between">
							<h4 className="text-sm font-bold uppercase tracking-widest flex items-center">
								<MoveDiagonal className="w-4 h-4 mr-2 text-primary" />{" "}
								{t("gcc.modules.risk.breakevenConfig", "Breakeven Config")}
							</h4>
							<Switch
								checked={config.breakevenEnabled}
								onCheckedChange={(checked) =>
									updateConfig({ breakevenEnabled: checked })
								}
							/>
						</div>

						<div className="space-y-3">
							<div className="space-y-1">
								<span className="text-[10px] text-muted-foreground uppercase font-bold">
									{t(
										"gcc.modules.risk.triggerThreshold",
										"Trigger Threshold (RR)",
									)}
								</span>
								<div className="grid grid-cols-2 gap-2">
									<div className="bg-background border border-border rounded-lg p-2">
										<div className="text-[9px] text-muted-foreground uppercase font-bold">
											{t("common:min", "Min")}
										</div>
										<input
											type="number"
											step="0.1"
											value={config.breakevenTriggerRRRange[0]}
											onChange={(e) =>
												updateConfig({
													breakevenTriggerRRRange: [
														parseFloat(e.target.value) || 0,
														config.breakevenTriggerRRRange[1],
													],
												})
											}
											className="w-full bg-transparent text-sm font-mono text-primary outline-none"
										/>
									</div>
									<div className="bg-background border border-border rounded-lg p-2">
										<div className="text-[9px] text-muted-foreground uppercase font-bold">
											{t("common:max", "Max")}
										</div>
										<input
											type="number"
											step="0.1"
											value={config.breakevenTriggerRRRange[1]}
											onChange={(e) =>
												updateConfig({
													breakevenTriggerRRRange: [
														config.breakevenTriggerRRRange[0],
														parseFloat(e.target.value) || 0,
													],
												})
											}
											className="w-full bg-transparent text-sm font-mono text-primary outline-none"
										/>
									</div>
								</div>
							</div>
							<div className="space-y-1">
								<span className="text-[10px] text-muted-foreground uppercase font-bold">
									{t("gcc.modules.risk.safetyBuffer", "Safety Buffer (ATR)")}
								</span>
								<div className="grid grid-cols-2 gap-2">
									<div className="bg-background border border-border rounded-lg p-2">
										<div className="text-[9px] text-muted-foreground uppercase font-bold">
											{t("common:min", "Min")}
										</div>
										<input
											type="number"
											step="0.01"
											value={config.breakevenBufferATRRange[0]}
											onChange={(e) =>
												updateConfig({
													breakevenBufferATRRange: [
														parseFloat(e.target.value) || 0,
														config.breakevenBufferATRRange[1],
													],
												})
											}
											className="w-full bg-transparent text-sm font-mono outline-none"
										/>
									</div>
									<div className="bg-background border border-border rounded-lg p-2">
										<div className="text-[9px] text-muted-foreground uppercase font-bold">
											{t("common:max", "Max")}
										</div>
										<input
											type="number"
											step="0.01"
											value={config.breakevenBufferATRRange[1]}
											onChange={(e) =>
												updateConfig({
													breakevenBufferATRRange: [
														config.breakevenBufferATRRange[0],
														parseFloat(e.target.value) || 0,
													],
												})
											}
											className="w-full bg-transparent text-sm font-mono outline-none"
										/>
									</div>
								</div>
							</div>
						</div>
						<p className="text-[10px] text-muted-foreground italic">
							{t(
								"gcc.modules.risk.breakevenHelp",
								"Moving Stop Loss to entry price + buffer once threshold is hit.",
							)}
						</p>
					</div>

					{/* Multi-Step Partial Take Profit */}
					<div className="bg-muted/20 border border-border rounded-xl p-5 space-y-4">
						<div className="flex items-center justify-between">
							<h4 className="text-sm font-bold uppercase tracking-widest flex items-center">
								<Scissors className="w-4 h-4 mr-2 text-emerald-500" />{" "}
								{t("gcc.modules.risk.partialTPs", "Partial Take Profits")}
							</h4>
							<Button
								onClick={addPartial}
								disabled={config.partialTPs.length >= 3}
								size="icon"
								variant="ghost"
								className="h-7 w-7"
							>
								<Plus className="w-4 h-4" />
							</Button>
						</div>

						<div className="space-y-3">
							{config.partialTPs.map((p, idx) => (
								<div
									key={p.id}
									className="p-3 bg-muted/30 rounded-lg border border-border space-y-2"
								>
									<div className="flex items-center justify-between">
										<span className="text-[10px] font-bold text-muted-foreground">
											#{idx + 1} Partial Exit
										</span>
										<Button
											onClick={() => removePartial(p.id)}
											size="icon"
											variant="ghost"
											className="h-6 w-6 text-muted-foreground hover:text-rose-500"
										>
											<Trash2 className="w-3 h-3" />
										</Button>
									</div>

									<div className="grid grid-cols-2 gap-3">
										{/* Size % Range */}
										<div className="space-y-1">
											<span className="text-[9px] text-muted-foreground uppercase font-bold">
												Size %
											</span>
											<div className="grid grid-cols-2 gap-1">
												<div className="bg-background border border-border rounded p-1.5">
													<div className="text-[8px] text-muted-foreground">
														Min
													</div>
													<input
														type="number"
														value={p.sizePctRange[0]}
														onChange={(e) =>
															updatePartial(
																p.id,
																"sizePctRange",
																0,
																parseInt(e.target.value, 10) || 0,
															)
														}
														className="w-full bg-transparent text-xs font-mono text-emerald-500 outline-none"
													/>
												</div>
												<div className="bg-background border border-border rounded p-1.5">
													<div className="text-[8px] text-muted-foreground">
														Max
													</div>
													<input
														type="number"
														value={p.sizePctRange[1]}
														onChange={(e) =>
															updatePartial(
																p.id,
																"sizePctRange",
																1,
																parseInt(e.target.value, 10) || 0,
															)
														}
														className="w-full bg-transparent text-xs font-mono text-emerald-500 outline-none"
													/>
												</div>
											</div>
										</div>

										{/* Target RR Range */}
										<div className="space-y-1">
											<span className="text-[9px] text-muted-foreground uppercase font-bold">
												Target RR
											</span>
											<div className="grid grid-cols-2 gap-1">
												<div className="bg-background border border-border rounded p-1.5">
													<div className="text-[8px] text-muted-foreground">
														Min
													</div>
													<input
														type="number"
														step="0.1"
														value={p.targetRRRange[0]}
														onChange={(e) =>
															updatePartial(
																p.id,
																"targetRRRange",
																0,
																parseFloat(e.target.value) || 0,
															)
														}
														className="w-full bg-transparent text-xs font-mono outline-none"
													/>
												</div>
												<div className="bg-background border border-border rounded p-1.5">
													<div className="text-[8px] text-muted-foreground">
														Max
													</div>
													<input
														type="number"
														step="0.1"
														value={p.targetRRRange[1]}
														onChange={(e) =>
															updatePartial(
																p.id,
																"targetRRRange",
																1,
																parseFloat(e.target.value) || 0,
															)
														}
														className="w-full bg-transparent text-xs font-mono outline-none"
													/>
												</div>
											</div>
										</div>
									</div>
								</div>
							))}
							{config.partialTPs.length === 0 && (
								<div className="text-center py-4 text-xs text-muted-foreground italic">
									{t("gcc.modules.risk.noPartials", "No partials configured")}
								</div>
							)}
						</div>
					</div>
				</div>

				{/* Time-Based Protection */}
				<div className="pt-6 border-t border-border">
					<div className="flex items-center justify-between p-4 bg-muted/30 rounded-xl border border-border">
						<div className="flex items-center">
							<Clock className="w-5 h-5 text-rose-500 mr-4" />
							<div>
								<div className="text-sm font-bold">
									{t("gcc.modules.risk.forceExit", "Force Exit (Time Stop)")}
								</div>
								<div className="text-xs text-muted-foreground">
									{t(
										"gcc.modules.risk.forceExitDesc",
										"Maximum trade duration in candles before auto-closure.",
									)}
								</div>
							</div>
						</div>
						<div className="flex items-center gap-2">
							<div className="bg-background border border-border rounded-lg px-3 py-2">
								<div className="text-[8px] text-muted-foreground uppercase font-bold">
									{t("common:min", "Min")}
								</div>
								<input
									type="number"
									value={config.timeStopCandlesRange[0]}
									onChange={(e) =>
										updateConfig({
											timeStopCandlesRange: [
												parseInt(e.target.value, 10) || 0,
												config.timeStopCandlesRange[1],
											],
										})
									}
									className="w-16 bg-transparent text-sm font-mono text-rose-500 outline-none"
								/>
							</div>
							<div className="bg-background border border-border rounded-lg px-3 py-2">
								<div className="text-[8px] text-muted-foreground uppercase font-bold">
									{t("common:max", "Max")}
								</div>
								<input
									type="number"
									value={config.timeStopCandlesRange[1]}
									onChange={(e) =>
										updateConfig({
											timeStopCandlesRange: [
												config.timeStopCandlesRange[0],
												parseInt(e.target.value, 10) || 0,
											],
										})
									}
									className="w-16 bg-transparent text-sm font-mono text-rose-500 outline-none"
								/>
							</div>
							<span className="text-[10px] font-bold text-muted-foreground uppercase">
								{t("common:candles", "Candles")}
							</span>
						</div>
					</div>
				</div>
			</CardContent>
		</Card>
	);
};

export default ExecutionRiskModule;
