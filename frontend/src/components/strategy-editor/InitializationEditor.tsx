// src/components/strategy-editor/InitializationEditor.tsx

import { AlertTriangle, Info, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { useBlockRestrictions } from "@/lib/api";
import { hasProPlanAccess } from "@/lib/strategyRestrictions";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import { DynamicValueInput } from "./DynamicValueInput";
import type { PartialExit } from "./types";

export const InitializationEditor = () => {
	const { t, i18n } = useTranslation("strategy-editor");
	const params = useStrategyEditorStore((s) => s.initialization.params);
	const positionManagement = useStrategyEditorStore(
		(s) => s.positionManagement,
	);
	const userTier = useStrategyEditorStore((s) => s.userTier);
	const setInitializationParam = useStrategyEditorStore(
		(s) => s.setInitializationParam,
	);
	const addPartialExit = useStrategyEditorStore((s) => s.addPartialExit);
	const updatePartialExit = useStrategyEditorStore((s) => s.updatePartialExit);
	const removePartialExit = useStrategyEditorStore((s) => s.removePartialExit);
	const { data: restrictions } = useBlockRestrictions();
	const limitBreakLabel = i18n.language.startsWith("ru")
		? "Limit Break"
		: "Limit Break";

	const dcaBlock = useMemo(
		() => positionManagement.find((b) => b.type === "dca_management"),
		[positionManagement],
	);
	const gridBlock = useMemo(
		() => positionManagement.find((b) => b.type === "grid_management"),
		[positionManagement],
	);
	const hasComplexManagement = !!dcaBlock || !!gridBlock;

	const dcaTotalDrop = useMemo(() => {
		if (!dcaBlock) return 0;
		const p = dcaBlock.params || {};
		const maxSos = Number(p.max_safety_orders) || 0;
		const stepValueRaw = p.step_value;
		const stepMultiplier = Number(p.step_multiplier) || 1;

		if (
			p.params_type === "atr" ||
			!stepValueRaw ||
			typeof stepValueRaw !== "number"
		)
			return 0;

		let drop = 0;
		for (let i = 0; i < maxSos; i++) {
			drop += stepValueRaw * stepMultiplier ** i;
		}
		return Number(drop.toFixed(2));
	}, [dcaBlock]);

	const showSlWarning = useMemo(() => {
		return (
			!!dcaBlock &&
			params.sl_type === "percent_from_price" &&
			typeof params.sl_value === "number" &&
			params.sl_value > 0 &&
			params.sl_value < dcaTotalDrop
		);
	}, [dcaBlock, params.sl_type, params.sl_value, dcaTotalDrop]);

	const partialExitsLocked = useMemo(() => {
		return (
			(restrictions?.proOnly || []).includes("partial_exits") &&
			!hasProPlanAccess(userTier)
		);
	}, [restrictions?.proOnly, userTier]);

	// Logic: if SL is 0, TP must be percent and RR is disabled
	useEffect(() => {
		if (params.sl_value === 0) {
			if (params.tp_type === "rr_multiplier") {
				setInitializationParam("tp_type", "percent_from_price");
			}
			if (params.partial_exits) {
				params.partial_exits.forEach((exit: PartialExit) => {
					if (exit.tp_type === "rr_multiplier") {
						updatePartialExit(exit.id, "tp_type", "percent_from_price");
					}
				});
			}
		}
	}, [
		params.sl_value,
		params.tp_type,
		params.partial_exits,
		setInitializationParam,
		updatePartialExit,
	]);

	return (
		<div className="space-y-4">
			<div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4">
				<div className="space-y-4">
					<div>
						<Label>{t("canvas.actionDirectionLabel")}</Label>
						<div className="mt-1 grid grid-cols-2 gap-1 p-1 rounded-md bg-secondary border border-input">
							<Button
								size="sm"
								variant={params.direction === "LONG" ? "default" : "ghost"}
								onClick={() => setInitializationParam("direction", "LONG")}
								className={
									params.direction === "LONG"
										? "bg-green-600 hover:bg-green-700"
										: ""
								}
								data-tutorial-id="direction-long-button"
							>
								LONG
							</Button>
							<Button
								size="sm"
								variant={params.direction === "SHORT" ? "destructive" : "ghost"}
								onClick={() => setInitializationParam("direction", "SHORT")}
								className={
									params.direction === "SHORT"
										? "bg-red-600 hover:bg-red-700"
										: ""
								}
							>
								SHORT
							</Button>
						</div>
					</div>
					<div>
						<Label>{t("canvas.actionPositionSizeLabel")}</Label>
						<div className="flex items-center gap-2 mt-1">
							<Select
								value={params.risk_type}
								onValueChange={(v) => setInitializationParam("risk_type", v)}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="percent_balance">
										{t("canvas.actionRiskTypePercent")}
									</SelectItem>
									<SelectItem value="fixed_usd">
										{t("canvas.actionRiskTypeFixedUsd")}
									</SelectItem>
								</SelectContent>
							</Select>
							<Input
								type="number"
								value={params.risk_value}
								onChange={(e) =>
									setInitializationParam(
										"risk_value",
										parseFloat(e.target.value) || 0,
									)
								}
								className="w-24"
							/>
						</div>
						{hasComplexManagement && (
							<div className="mt-2 text-[10px] text-muted-foreground flex gap-1.5 p-2 bg-secondary/30 rounded-md border border-border/50">
								<Info className="w-3.5 h-3.5 text-cyan-500 shrink-0" />
								<span>{t("canvas.complexRiskWarning")}</span>
							</div>
						)}
					</div>
					<div>
						<Label>{t("canvas.actionOrderTypeLabel")}</Label>
						<Select
							value={params.order_type || "MARKET"}
							onValueChange={(v) => setInitializationParam("order_type", v)}
						>
							<SelectTrigger>
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								<SelectItem value="MARKET">
									{t("canvas.actionOrderTypeMarket")}
								</SelectItem>
								<SelectItem value="LIMIT_BREAK">
									{t("canvas.actionOrderTypeLimitBreak", limitBreakLabel)}
								</SelectItem>
								<SelectItem value="LIMIT_RETEST">
									{t("canvas.actionOrderTypeLimitRetest")}
								</SelectItem>
							</SelectContent>
						</Select>
					</div>
					{["LIMIT_RETEST", "LIMIT_BREAK"].includes(
						params.order_type || "MARKET",
					) && (
						<div>
							<Label>{t("canvas.actionEntryPriceLabel")}</Label>
							<DynamicValueInput
								value={params.entry_price}
								onChange={(v) => setInitializationParam("entry_price", v)}
							/>
						</div>
					)}
				</div>
				<div className="space-y-4">
					<div className="space-y-2">
						<div className="flex items-center gap-2">
							<Label>{t("canvas.slLabel")}</Label>
							{params.sl_value === 0 && (
								<span className="text-[10px] text-muted-foreground italic">
									{t("canvas.slHintNoStop")}
								</span>
							)}
						</div>
						<div className="flex items-center gap-2 mt-1">
							<Select
								value={params.sl_type}
								onValueChange={(v) => setInitializationParam("sl_type", v)}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="atr_multiplier">
										{t("canvas.slTypeAtr")}
									</SelectItem>
									<SelectItem value="percent_from_price">
										{t("canvas.slTypePercent")}
									</SelectItem>
								</SelectContent>
							</Select>
							<DynamicValueInput
								value={params.sl_value}
								onChange={(v) => setInitializationParam("sl_value", v)}
							/>
						</div>
						{showSlWarning && (
							<Alert
								variant="destructive"
								className="mt-2 py-1.5 px-3 border-orange-500/50 bg-orange-500/10 text-orange-600 dark:text-orange-400"
							>
								<AlertTriangle className="h-3.5 w-3.5" />
								<AlertDescription className="text-[10px] leading-tight ml-2">
									{t("canvas.slDcaWarning", { drop: dcaTotalDrop })}
								</AlertDescription>
							</Alert>
						)}
					</div>
					<div>
						<Label>{t("canvas.tpLabel")}</Label>
						<div className="flex items-center gap-2 mt-1">
							<Select
								value={params.tp_type}
								onValueChange={(v) => setInitializationParam("tp_type", v)}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem
										value="rr_multiplier"
										disabled={params.sl_value === 0}
									>
										{t("canvas.tpTypeRr")}
									</SelectItem>
									<SelectItem value="percent_from_price">
										{t("canvas.tpTypePercent")}
									</SelectItem>
								</SelectContent>
							</Select>
							<DynamicValueInput
								value={params.tp_value}
								onChange={(v) => setInitializationParam("tp_value", v)}
							/>
						</div>
					</div>
				</div>
			</div>
			<div className="pt-4 border-t border-border">
				<Label>{t("canvas.partialExitsLabel")}</Label>
				{partialExitsLocked && (
					<Alert className="mt-2 py-2 px-3 border-violet-500/40 bg-violet-500/10">
						<AlertTriangle className="h-3.5 w-3.5 text-violet-400" />
						<AlertDescription className="text-[10px] leading-tight ml-2 text-violet-800 dark:text-violet-100/80">
							Partial exits are available on the Pro plan only.
						</AlertDescription>
					</Alert>
				)}
				<div className="space-y-2 mt-2">
					{(params.partial_exits || []).map((exit: PartialExit) => (
						<div
							key={exit.id}
							className="flex items-center gap-2 p-2 rounded-md bg-secondary/50"
						>
							<Input
								placeholder="Size %"
								type="number"
								value={exit.size_pct}
								onChange={(e) =>
									updatePartialExit(
										exit.id,
										"size_pct",
										parseFloat(e.target.value) || 0,
									)
								}
								className="w-24 h-8"
								disabled={partialExitsLocked}
							/>
							<span>{t("canvas.partialExitAtTp")}</span>
							<Select
								value={exit.tp_type}
								onValueChange={(v) => updatePartialExit(exit.id, "tp_type", v)}
								disabled={partialExitsLocked}
							>
								<SelectTrigger className="w-[150px] h-8">
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem
										value="rr_multiplier"
										disabled={params.sl_value === 0}
									>
										{t("canvas.tpTypeRr")}
									</SelectItem>
									<SelectItem value="percent_from_price">
										{t("canvas.tpTypePercent")}
									</SelectItem>
								</SelectContent>
							</Select>
							<div className="w-32">
								<DynamicValueInput
									value={exit.tp_value}
									onChange={(newValue) =>
										updatePartialExit(exit.id, "tp_value", newValue)
									}
									disabled={partialExitsLocked}
								/>
							</div>
							<Button
								variant="ghost"
								size="icon"
								className="h-8 w-8 text-destructive"
								onClick={() => removePartialExit(exit.id)}
							>
								<Trash2 className="w-4 h-4" />
							</Button>
						</div>
					))}
				</div>
				<Button
					variant="outline"
					size="sm"
					className="mt-2 w-full text-muted-foreground"
					onClick={addPartialExit}
					disabled={partialExitsLocked}
				>
					<Plus className="w-4 h-4 mr-2" /> {t("canvas.addPartialExitButton")}
				</Button>
			</div>
		</div>
	);
};
