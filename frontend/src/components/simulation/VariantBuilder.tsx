// frontend/src/components/simulation/VariantBuilder.tsx
// Custom variant configuration modal

import {
	ChevronDown,
	ChevronUp,
	Clock,
	Plus,
	Shield,
	Sparkles,
	Target,
	Trash2,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { type CustomVariant, type PartialTP, VARIANT_COLORS } from "./types";

interface VariantBuilderProps {
	isOpen: boolean;
	onClose: () => void;
	variant: CustomVariant | null;
	onSave: (variant: CustomVariant) => void;
	existingIds: string[];
}

type VariantSection = "oracle" | "takeProfit" | "risk" | "time";

const SectionHeader: React.FC<{
	title: string;
	icon: React.ReactNode;
	section: VariantSection;
	expanded: boolean;
	onToggle: (section: VariantSection) => void;
	badge?: string;
}> = ({ title, icon, section, expanded, onToggle, badge }) => (
	<button
		onClick={() => onToggle(section)}
		className="w-full flex items-center justify-between p-3 bg-muted/30 rounded-lg hover:bg-muted/50 transition-colors"
	>
		<div className="flex items-center gap-2">
			{icon}
			<span className="font-medium text-sm">{title}</span>
			{badge && (
				<span className="text-[10px] px-1.5 py-0.5 bg-primary/20 text-primary rounded-full">
					{badge}
				</span>
			)}
		</div>
		{expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
	</button>
);

export const VariantBuilder: React.FC<VariantBuilderProps> = ({
	isOpen,
	onClose,
	variant,
	onSave,
	existingIds,
}) => {
	const { t } = useTranslation("simulation");

	const [idSuffix] = useState(() => Date.now());
	const defaultVariant: CustomVariant = {
		id: `custom_${idSuffix}`,
		name: "Custom Variant",
		color: VARIANT_COLORS[existingIds.length % VARIANT_COLORS.length],
		isBuiltIn: false,
		oracle: {
			enabled: false,
			threshold: 0.95,
			entryRegime: "amnesia",
			onRegimeChange: "none",
		},
		takeProfit: { partials: [], finalTP_RR: 2.0 },
		riskManagement: {
			breakeven: { mode: "disabled", triggerRR: 1.0 },
			trailingStop: { enabled: false, trailPercent: 0.01 },
			maxHoldCandles: 0,
		},
		timeFilter: {
			enabled: false,
			startHourUTC: 14,
			endHourUTC: 7,
			mode: "include",
		},
	};

	const [config, setConfig] = useState<CustomVariant>(
		variant || defaultVariant,
	);
	const [expandedSections, setExpandedSections] = useState({
		oracle: true,
		takeProfit: true,
		risk: true,
		time: false,
	});

	const toggleSection = (section: VariantSection) => {
		setExpandedSections((prev) => ({ ...prev, [section]: !prev[section] }));
	};

	const updateOracle = (updates: Partial<CustomVariant["oracle"]>) => {
		setConfig((prev) => ({ ...prev, oracle: { ...prev.oracle, ...updates } }));
	};

	const updateTP = (updates: Partial<CustomVariant["takeProfit"]>) => {
		setConfig((prev) => ({
			...prev,
			takeProfit: { ...prev.takeProfit, ...updates },
		}));
	};

	const updateRisk = (updates: Partial<CustomVariant["riskManagement"]>) => {
		setConfig((prev) => ({
			...prev,
			riskManagement: { ...prev.riskManagement, ...updates },
		}));
	};

	const updateTime = (updates: Partial<CustomVariant["timeFilter"]>) => {
		setConfig((prev) => ({
			...prev,
			timeFilter: { ...prev.timeFilter, ...updates },
		}));
	};

	const addPartialTP = () => {
		const currentSum = config.takeProfit.partials.reduce(
			(s, p) => s + p.closePercent,
			0,
		);
		if (currentSum >= 100) return;
		const remaining = 100 - currentSum;
		const newTP: PartialTP = {
			triggerRR: 1.5,
			closePercent: Math.min(30, remaining),
		};
		updateTP({ partials: [...config.takeProfit.partials, newTP] });
	};

	const removePartialTP = (index: number) => {
		updateTP({
			partials: config.takeProfit.partials.filter((_, i) => i !== index),
		});
	};

	const updatePartialTP = (index: number, updates: Partial<PartialTP>) => {
		const newPartials = config.takeProfit.partials.map((tp, i) =>
			i === index ? { ...tp, ...updates } : tp,
		);
		updateTP({ partials: newPartials });
	};

	const handleSave = () => {
		if (!config.name.trim()) {
			alert("Please enter a variant name");
			return;
		}
		onSave(config);
		onClose();
	};

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
				<DialogHeader>
					<DialogTitle className="flex items-center gap-2">
						<Sparkles className="text-primary" size={20} />
						{variant
							? t("editVariant", "Edit Variant")
							: t("createCustomVariant", "Create Custom Variant")}
					</DialogTitle>
				</DialogHeader>

				<div className="space-y-4">
					{/* Name & Color */}
					<div className="flex gap-3">
						<div className="flex-1">
							<Label className="text-xs text-muted-foreground">
								{t("variantName", "Name")}
							</Label>
							<Input
								value={config.name}
								onChange={(e) =>
									setConfig((prev) => ({ ...prev, name: e.target.value }))
								}
								placeholder="My Custom Variant"
								className="mt-1"
							/>
						</div>
						<div>
							<Label className="text-xs text-muted-foreground">
								{t("variantColor", "Color")}
							</Label>
							<div className="flex flex-wrap gap-1 mt-2 max-w-[140px]">
								{VARIANT_COLORS.map((color) => (
									<button
										key={color}
										onClick={() => setConfig((prev) => ({ ...prev, color }))}
										className={`w-5 h-5 rounded-full border-2 transition-all ${
											config.color === color
												? "border-white scale-110"
												: "border-transparent"
										}`}
										style={{ backgroundColor: color }}
									/>
								))}
							</div>
						</div>
					</div>

					{/* Oracle Section */}
					<div className="space-y-2">
						<SectionHeader
							title="Oracle"
							icon={<Sparkles size={14} className="text-purple-400" />}
							section="oracle"
							expanded={expandedSections.oracle}
							onToggle={toggleSection}
							badge={config.oracle.enabled ? "ON" : undefined}
						/>
						{expandedSections.oracle && (
							<div className="p-3 border rounded-lg space-y-3 animate-in fade-in duration-200">
								<div className="flex items-center justify-between">
									<Label className="text-sm">
										{t("enableOracle", "Enable Oracle")}
									</Label>
									<Switch
										checked={config.oracle.enabled}
										onCheckedChange={(v) => updateOracle({ enabled: v })}
									/>
								</div>

								{config.oracle.enabled && (
									<>
										<div>
											<Label className="text-xs text-muted-foreground">
												{t("confidenceThreshold", "Confidence Threshold")}
											</Label>
											<div className="flex items-center gap-3 mt-1">
												<Slider
													value={[config.oracle.threshold * 100]}
													onValueChange={([v]) =>
														updateOracle({ threshold: v / 100 })
													}
													min={50}
													max={99}
													step={1}
													className="flex-1"
												/>
												<span className="text-xs font-mono w-10 text-right">
													{(config.oracle.threshold * 100).toFixed(0)}%
												</span>
											</div>
										</div>

										<div>
											<Label className="text-xs text-muted-foreground">
												{t("onRegimeChange", "On Regime Change")}
											</Label>
											<Select
												value={config.oracle.onRegimeChange}
												onValueChange={(v) =>
													updateOracle({
														onRegimeChange:
															v as CustomVariant["oracle"]["onRegimeChange"],
													})
												}
											>
												<SelectTrigger className="mt-1">
													<SelectValue />
												</SelectTrigger>
												<SelectContent>
													<SelectItem value="none">
														{t("doNothing", "Do Nothing")}
													</SelectItem>
													<SelectItem value="breakeven">
														{t("moveToBreakeven", "Move to Breakeven")}
													</SelectItem>
													<SelectItem value="close">
														{t("closePosition", "Close Position")}
													</SelectItem>
												</SelectContent>
											</Select>
										</div>
									</>
								)}
							</div>
						)}
					</div>

					{/* Take Profit Section */}
					<div className="space-y-2">
						<SectionHeader
							title={t("takeProfits", "Take Profits")}
							icon={<Target size={14} className="text-emerald-400" />}
							section="takeProfit"
							expanded={expandedSections.takeProfit}
							onToggle={toggleSection}
							badge={
								config.takeProfit.partials.length > 0
									? `${config.takeProfit.partials.length} TP`
									: undefined
							}
						/>
						{expandedSections.takeProfit && (
							<div className="p-3 border rounded-lg space-y-3 animate-in fade-in duration-200">
								{/* Partial TPs */}
								{config.takeProfit.partials.map((tp, idx) => (
									<div
										key={idx}
										className="flex items-center gap-2 p-2 bg-muted/30 rounded"
									>
										<span className="text-xs font-medium w-8">TP{idx + 1}</span>
										<Input
											type="number"
											value={tp.triggerRR}
											onChange={(e) =>
												updatePartialTP(idx, {
													triggerRR: parseFloat(e.target.value) || 0,
												})
											}
											className="w-16 h-8 text-xs"
											step={0.1}
											min={0.5}
										/>
										<span className="text-xs text-muted-foreground">R →</span>
										<Input
											type="number"
											value={tp.closePercent}
											onChange={(e) =>
												updatePartialTP(idx, {
													closePercent: parseInt(e.target.value, 10) || 0,
												})
											}
											className="w-16 h-8 text-xs"
											min={1}
											max={100}
										/>
										<span className="text-xs text-muted-foreground">%</span>
										<Button
											variant="ghost"
											size="icon"
											className="h-6 w-6"
											onClick={() => removePartialTP(idx)}
										>
											<Trash2 size={12} />
										</Button>
									</div>
								))}

								<Button
									variant="outline"
									size="sm"
									onClick={addPartialTP}
									disabled={
										config.takeProfit.partials.reduce(
											(s, p) => s + p.closePercent,
											0,
										) >= 100
									}
									className="w-full"
								>
									<Plus size={14} className="mr-1" />{" "}
									{t("addPartialTP", "Add Partial TP")}
								</Button>

								<div className="flex items-center gap-2">
									<Label className="text-xs text-muted-foreground flex-1">
										{t("finalTP", "Final TP")} (remaining)
									</Label>
									<Input
										type="number"
										value={config.takeProfit.finalTP_RR}
										onChange={(e) =>
											updateTP({ finalTP_RR: parseFloat(e.target.value) || 2 })
										}
										className="w-20 h-8 text-xs"
										step={0.5}
										min={0.5}
									/>
									<span className="text-xs text-muted-foreground">R</span>
								</div>
							</div>
						)}
					</div>

					{/* Risk Management Section */}
					<div className="space-y-2">
						<SectionHeader
							title={t("riskManagement", "Risk Management")}
							icon={<Shield size={14} className="text-amber-400" />}
							section="risk"
							expanded={expandedSections.risk}
							onToggle={toggleSection}
							badge={
								config.riskManagement.breakeven.mode !== "disabled" ||
								config.riskManagement.trailingStop.enabled
									? "Active"
									: undefined
							}
						/>
						{expandedSections.risk && (
							<div className="p-3 border rounded-lg space-y-3 animate-in fade-in duration-200">
								<div>
									<Label className="text-xs text-muted-foreground">
										{t("breakevenMode", "Breakeven Mode")}
									</Label>
									<Select
										value={config.riskManagement.breakeven.mode}
										onValueChange={(v) =>
											updateRisk({
												breakeven: {
													...config.riskManagement.breakeven,
													mode: v as CustomVariant["riskManagement"]["breakeven"]["mode"],
												},
											})
										}
									>
										<SelectTrigger className="mt-1">
											<SelectValue />
										</SelectTrigger>
										<SelectContent>
											<SelectItem value="disabled">
												{t("disabled", "Disabled")}
											</SelectItem>
											<SelectItem value="at_rr">
												{t("atRiskReward", "At X Risk-Reward")}
											</SelectItem>
											<SelectItem value="at_first_tp">
												{t("atFirstTP", "At First TP Hit")}
											</SelectItem>
											<SelectItem value="by_oracle">
												{t("byOracle", "By Oracle Regime Change")}
											</SelectItem>
										</SelectContent>
									</Select>
								</div>

								{config.riskManagement.breakeven.mode === "at_rr" && (
									<div className="flex items-center gap-2">
										<Label className="text-xs text-muted-foreground flex-1">
											{t("triggerAt", "Trigger at")}
										</Label>
										<Input
											type="number"
											value={config.riskManagement.breakeven.triggerRR}
											onChange={(e) =>
												updateRisk({
													breakeven: {
														...config.riskManagement.breakeven,
														triggerRR: parseFloat(e.target.value) || 1,
													},
												})
											}
											className="w-20 h-8 text-xs"
											step={0.5}
											min={0.5}
										/>
										<span className="text-xs text-muted-foreground">R</span>
									</div>
								)}

								<div className="flex items-center justify-between">
									<Label className="text-sm">
										{t("trailingStop", "Trailing Stop")}
									</Label>
									<Switch
										checked={config.riskManagement.trailingStop.enabled}
										onCheckedChange={(v) =>
											updateRisk({
												trailingStop: {
													...config.riskManagement.trailingStop,
													enabled: v,
												},
											})
										}
									/>
								</div>

								{config.riskManagement.trailingStop.enabled && (
									<div className="flex items-center gap-2">
										<Label className="text-xs text-muted-foreground flex-1">
											{t("trailDistance", "Trail Distance")}
										</Label>
										<Input
											type="number"
											value={
												config.riskManagement.trailingStop.trailPercent * 100
											}
											onChange={(e) =>
												updateRisk({
													trailingStop: {
														...config.riskManagement.trailingStop,
														trailPercent:
															(parseFloat(e.target.value) || 1) / 100,
													},
												})
											}
											className="w-20 h-8 text-xs"
											step={0.1}
											min={0.1}
										/>
										<span className="text-xs text-muted-foreground">%</span>
									</div>
								)}

								<div className="flex items-center gap-2">
									<Label className="text-xs text-muted-foreground flex-1">
										{t("maxHold", "Max Hold")} (0 = no limit)
									</Label>
									<Input
										type="number"
										value={config.riskManagement.maxHoldCandles}
										onChange={(e) =>
											updateRisk({
												maxHoldCandles: parseInt(e.target.value, 10) || 0,
											})
										}
										className="w-20 h-8 text-xs"
										min={0}
									/>
									<span className="text-xs text-muted-foreground">
										{t("candles", "candles")}
									</span>
								</div>
							</div>
						)}
					</div>

					{/* Time Filter Section */}
					<div className="space-y-2">
						<SectionHeader
							title={t("timeFilter", "Time Filter")}
							icon={<Clock size={14} className="text-blue-400" />}
							section="time"
							expanded={expandedSections.time}
							onToggle={toggleSection}
							badge={
								config.timeFilter.enabled
									? `${config.timeFilter.startHourUTC}-${config.timeFilter.endHourUTC} UTC`
									: undefined
							}
						/>
						{expandedSections.time && (
							<div className="p-3 border rounded-lg space-y-3 animate-in fade-in duration-200">
								<div className="flex items-center justify-between">
									<Label className="text-sm">
										{t("enableTimeFilter", "Enable Time Filter")}
									</Label>
									<Switch
										checked={config.timeFilter.enabled}
										onCheckedChange={(v) => updateTime({ enabled: v })}
									/>
								</div>

								{config.timeFilter.enabled && (
									<div className="flex items-center gap-2">
										<span className="text-xs">
											{t("tradeFrom", "Trade from")}
										</span>
										<Input
											type="number"
											value={config.timeFilter.startHourUTC}
											onChange={(e) =>
												updateTime({
													startHourUTC: parseInt(e.target.value, 10) || 0,
												})
											}
											className="w-14 h-8 text-xs"
											min={0}
											max={23}
										/>
										<span className="text-xs">{t("tradeTo", "to")}</span>
										<Input
											type="number"
											value={config.timeFilter.endHourUTC}
											onChange={(e) =>
												updateTime({
													endHourUTC: parseInt(e.target.value, 10) || 0,
												})
											}
											className="w-14 h-8 text-xs"
											min={0}
											max={23}
										/>
										<span className="text-xs text-muted-foreground">UTC</span>
									</div>
								)}
							</div>
						)}
					</div>
				</div>

				<DialogFooter className="mt-4">
					<Button variant="outline" onClick={onClose}>
						{t("cancel", "Cancel")}
					</Button>
					<Button onClick={handleSave}>
						{variant
							? t("saveChanges", "Save Changes")
							: t("createCustomVariant", "Create Variant")}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
};

export default VariantBuilder;
