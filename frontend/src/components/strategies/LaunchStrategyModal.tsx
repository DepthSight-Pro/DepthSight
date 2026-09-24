// src/components/strategies/LaunchStrategyModal.tsx

import { FlaskConical, Key, Loader2, Radio, Wallet } from "lucide-react";
import type React from "react";
import { useEffect, useMemo } from "react";
import {
	Controller,
	type FieldValues,
	useForm,
	useWatch,
} from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
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
import { Slider } from "@/components/ui/slider";
import { useAuth } from "@/context/AuthContext";
import { useConfig, useMultiAccountBalances } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { CombinedStrategy } from "@/types/api";

// Feature flags: keep code completely in place, set to false to re-enable
const HIDE_DYNAMIC_SELECTION = true;
const HIDE_ADVANCED_SETTINGS = true;

interface LaunchStrategyModalProps {
	isOpen: boolean;
	onClose: () => void;
	onConfirm: (data: LaunchFormData) => void;
	strategyName?: string;
	isLoading?: boolean;
	currentSymbols?: string[];
	currentMode?: "STATIC" | "DYNAMIC";
	strategy?: CombinedStrategy | null; // Pass full strategy object to pre-fill dynamic settings
}

export interface LaunchFormData extends FieldValues {
	mode: "live" | "paper";
	symbolSelectionMode: "STATIC" | "DYNAMIC";
	symbols?: string;
	apiKeyId?: number; // Multi-account: select which API key to trade with

	// Dynamic settings
	dynamicMode: "DYNAMIC_NATR" | "DYNAMIC_ORACLE";
	minNatr?: number;
	oracleRegime?: string; // "0", "1", "2"
	oracleConfidence?: number;
	maxConcurrentSymbols?: number;

	// ML & Regime settings
	useMlConfirmation?: boolean;
	breakevenOnRegimeChange?: boolean;
}

export const LaunchStrategyModal: React.FC<LaunchStrategyModalProps> = ({
	isOpen,
	onClose,
	onConfirm,
	strategyName = "Strategy",
	isLoading = false,
	currentSymbols = [],
	currentMode = "DYNAMIC",
	strategy,
}) => {
	const { t } = useTranslation(["strategies", "common"]);
	const { user } = useAuth();
	const { data: config } = useConfig();
	const { data: balances } = useMultiAccountBalances();
	const isAdmin = user?.role === "admin";
	const isPro = user?.plan === "pro";
	const canUseOracle = isAdmin || isPro; // Oracle is available to admins and Pro users

	// Get active API keys for live trading
	const activeApiKeys = useMemo(() => {
		return (
			config?.apiKeys?.filter(
				(key) => key.isActive && key.status !== "invalid",
			) ?? []
		);
	}, [config?.apiKeys]);

	// Extract initial values from strategy config
	// For non-admins/non-pro, force NATR unless they are already in Oracle mode (which creates a conflict if they can't see it).
	const initialDynamicMode = strategy?.config_data?.natr_settings
		? "DYNAMIC_NATR"
		: canUseOracle
			? "DYNAMIC_ORACLE"
			: "DYNAMIC_NATR";

	const initialMinNatr =
		(strategy?.config_data?.natr_settings?.min_natr as number) || 1.5;
	const initialOracleRegime =
		(
			strategy?.config_data?.oracle_settings?.regime as string | number
		)?.toString() || "1";
	const initialOracleConfidence =
		(strategy?.config_data?.oracle_settings?.confidence as number) || 95;
	const initialMaxConcurrent =
		(strategy?.config_data?.max_concurrent_symbols as number) || 5;
	const initialUseMlConfirmation =
		strategy?.config_data?.use_ml_confirmation ??
		strategy?.use_ml_confirmation ??
		false;
	const initialBreakevenOnRegimeChange =
		strategy?.config_data?.breakeven_on_regime_change ?? false;

	const {
		control,
		handleSubmit,
		setValue,
		formState: { errors },
	} = useForm<LaunchFormData>({
		defaultValues: {
			mode: "paper",
			symbolSelectionMode: HIDE_DYNAMIC_SELECTION ? "STATIC" : currentMode,
			symbols: currentSymbols.join(", "),
			dynamicMode: initialDynamicMode,
			minNatr: initialMinNatr,
			oracleRegime: initialOracleRegime,
			oracleConfidence: initialOracleConfidence,
			maxConcurrentSymbols: initialMaxConcurrent,
			useMlConfirmation: initialUseMlConfirmation,
			breakevenOnRegimeChange: initialBreakevenOnRegimeChange,
		},
	});

	// Reset form values when strategy prop changes (e.g. reopening modal for different strategy)
	useEffect(() => {
		if (isOpen && strategy) {
			const dMode = strategy.config_data?.natr_settings
				? "DYNAMIC_NATR"
				: canUseOracle
					? "DYNAMIC_ORACLE"
					: "DYNAMIC_NATR";
			setValue("dynamicMode", dMode);
			setValue(
				"minNatr",
				(strategy.config_data?.natr_settings?.min_natr as number) || 1.5,
			);
			setValue(
				"oracleRegime",
				(
					strategy.config_data?.oracle_settings?.regime as string | number
				)?.toString() || "1",
			);
			setValue(
				"oracleConfidence",
				(strategy.config_data?.oracle_settings?.confidence as number) || 95,
			);
			setValue(
				"maxConcurrentSymbols",
				(strategy.config_data?.max_concurrent_symbols as number) || 5,
			);
			setValue(
				"useMlConfirmation",
				strategy.config_data?.use_ml_confirmation ??
					strategy.use_ml_confirmation ??
					false,
			);
			setValue(
				"breakevenOnRegimeChange",
				strategy.config_data?.breakeven_on_regime_change ?? false,
			);

			const effectiveMode = HIDE_DYNAMIC_SELECTION
				? "STATIC"
				: (strategy.symbol_selection_mode as "STATIC" | "DYNAMIC") ||
					currentMode;
			setValue("symbolSelectionMode", effectiveMode);

			if (strategy.symbols && strategy.symbols.length > 0) {
				setValue("symbols", strategy.symbols.join(", "));
			} else if (
				Array.isArray(strategy.config_data?.symbols) &&
				strategy.config_data.symbols.length > 0
			) {
				setValue("symbols", strategy.config_data.symbols.join(", "));
			}
		}
	}, [isOpen, strategy, setValue, currentMode, canUseOracle]);

	const tradingMode = useWatch({ control, name: "mode" });
	const symbolSelectionMode = useWatch({
		control,
		name: "symbolSelectionMode",
	});
	const dynamicMode = useWatch({ control, name: "dynamicMode" });
	const oracleConfidence = useWatch({ control, name: "oracleConfidence" });

	// Auto-select API key if only one is active
	useEffect(() => {
		if (tradingMode === "live" && activeApiKeys.length === 1) {
			setValue("apiKeyId", activeApiKeys[0].id);
		}
	}, [tradingMode, activeApiKeys, setValue]);

	const onSubmit = (data: LaunchFormData) => {
		onConfirm(data);
	};

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent className="sm:max-w-[500px] max-h-[85vh] overflow-y-auto bg-obsidian/95 border border-white/10 text-white shadow-2xl backdrop-blur-2xl rounded-2xl p-6">
				<DialogHeader className="space-y-1">
					<DialogTitle className="text-lg font-bold text-white tracking-wide">
						{t("launchModal.title", { name: strategyName })}
					</DialogTitle>
					<DialogDescription className="text-xs text-white/40">
						{t(
							"launchModal.description",
							"Configure launch parameters for this strategy",
						)}
					</DialogDescription>
				</DialogHeader>

				<form onSubmit={handleSubmit(onSubmit)} className="space-y-5 py-3">
					{/* Trading Mode */}
					<div className="space-y-2.5">
						<Label className="text-[11px] uppercase tracking-wider font-semibold text-white/60">
							{t("launchModal.tradingModeLabel", "Trading Mode")}
						</Label>
						<Controller
							name="mode"
							control={control}
							render={({ field }) => (
								<div className="grid grid-cols-2 gap-2.5">
									<button
										type="button"
										onClick={() => field.onChange("paper")}
										className={cn(
											"group flex items-center space-x-2.5 p-3 border rounded-xl cursor-pointer transition-all text-left outline-none",
											field.value === "paper"
												? "border-cyan/50 bg-cyan/[0.08] shadow-[0_0_20px_-5px_rgba(0,212,255,0.4)]"
												: "border-white/10 bg-white/[0.02] hover:bg-white/[0.05] hover:border-white/20",
										)}
									>
										<div
											className={cn(
												"h-4 w-4 shrink-0 rounded-full border flex items-center justify-center transition-all",
												field.value === "paper"
													? "border-cyan bg-cyan/20"
													: "border-white/30 bg-transparent group-hover:border-white/50",
											)}
										>
											{field.value === "paper" && (
												<div className="h-2 w-2 rounded-full bg-cyan shadow-[0_0_6px_rgba(0,212,255,0.9)]" />
											)}
										</div>
										<div className="flex-1 min-w-0">
											<div className="font-semibold text-xs text-white flex items-center gap-1.5">
												<FlaskConical size={12} className="text-cyan" />
												{t("launchModal.paperMode", "Paper Trading")}
											</div>
											<div className="text-[10px] text-white/40 mt-0.5 leading-tight">
												{t(
													"launchModal.paperModeDesc",
													"Virtual funds",
												)}
											</div>
										</div>
									</button>

									<button
										type="button"
										onClick={() => field.onChange("live")}
										className={cn(
											"group flex items-center space-x-2.5 p-3 border rounded-xl cursor-pointer transition-all text-left outline-none",
											field.value === "live"
												? "border-rose-500/50 bg-rose-500/[0.08] shadow-[0_0_20px_-5px_rgba(244,63,94,0.4)]"
												: "border-white/10 bg-white/[0.02] hover:bg-white/[0.05] hover:border-white/20",
										)}
									>
										<div
											className={cn(
												"h-4 w-4 shrink-0 rounded-full border flex items-center justify-center transition-all",
												field.value === "live"
													? "border-rose-500 bg-rose-500/20"
													: "border-white/30 bg-transparent group-hover:border-white/50",
											)}
										>
											{field.value === "live" && (
												<div className="h-2 w-2 rounded-full bg-rose-500 shadow-[0_0_6px_rgba(244,63,94,0.9)]" />
											)}
										</div>
										<div className="flex-1 min-w-0">
											<div className="font-semibold text-xs text-rose-400 flex items-center gap-1.5">
												<Radio size={12} className="animate-pulse" />
												{t("launchModal.liveMode", "Live Trading")}
											</div>
											<div className="text-[10px] text-white/40 mt-0.5 leading-tight">
												{t("launchModal.liveModeDesc", "Real funds")}
											</div>
										</div>
									</button>
								</div>
							)}
						/>
					</div>

					{/* API Key Selection for Live Mode - only show if multiple active keys */}
					{tradingMode === "live" && activeApiKeys.length === 0 && (
						<div className="p-3 border border-rose-500/30 rounded-xl bg-rose-500/10">
							<p className="text-xs text-rose-400">
								{t(
									"launchModal.noActiveKeysWarning",
									"No valid API keys available. Please add and verify an API key in Settings.",
								)}
							</p>
						</div>
					)}

					{tradingMode === "live" && activeApiKeys.length > 1 && (
						<div className="space-y-2">
							<Label className="text-[11px] uppercase tracking-wider font-semibold text-white/60 flex items-center gap-1.5">
								<Key className="h-3.5 w-3.5 text-cyan" />
								{t("launchModal.accountLabel", "Trading Account")}
							</Label>
							<Controller
								name="apiKeyId"
								control={control}
								rules={{
									required:
										tradingMode === "live"
											? t(
													"launchModal.errors.apiKeyRequired",
													"Please select a trading account",
												)
											: false,
								}}
								render={({ field }) => (
									<Select
										onValueChange={(v) => field.onChange(parseInt(v, 10))}
										value={field.value?.toString()}
									>
										<SelectTrigger className="h-9 rounded-xl border border-white/10 bg-white/[0.03] text-xs text-white focus:border-cyan/50 focus:ring-1 focus:ring-cyan/30">
											<SelectValue
												placeholder={t(
													"launchModal.selectAccountPlaceholder",
													"Select trading account",
												)}
											/>
										</SelectTrigger>
										<SelectContent className="border border-white/10 bg-obsidian/95 text-white backdrop-blur-xl">
											{activeApiKeys.map((key) => {
												const keyBalance = balances?.accounts?.find(
													(a) => a.apiKeyId === key.id,
												);
												return (
													<SelectItem
														key={key.id}
														value={String(key.id)}
														className="text-xs hover:bg-white/5 focus:bg-white/10"
													>
														<div className="flex items-center justify-between w-full gap-4">
															<div className="flex items-center gap-2">
																<Wallet className="h-3.5 w-3.5 text-white/40" />
																<span>{key.name}</span>
															</div>
															{keyBalance && (
																<span className="text-[11px] font-mono text-white/40">
																	$
																	{keyBalance.balance.toLocaleString(
																		undefined,
																		{
																			minimumFractionDigits: 0,
																			maximumFractionDigits: 0,
																		},
																	)}
																</span>
															)}
														</div>
													</SelectItem>
												);
											})}
										</SelectContent>
									</Select>
								)}
							/>
							{errors.apiKeyId && (
								<p className="text-xs text-rose-400">
									{errors.apiKeyId.message}
								</p>
							)}
						</div>
					)}

					{/* Symbol Selection Mode (TEMPORARILY HIDDEN via flag) */}
					{!HIDE_DYNAMIC_SELECTION && (
						<div className="space-y-3">
							<Label className="text-[11px] uppercase tracking-wider font-semibold text-white/60">
								{t("launchModal.symbolModeLabel", "Symbol Selection")}
							</Label>
							<Controller
								name="symbolSelectionMode"
								control={control}
								render={({ field }) => (
									<RadioGroup
										value={field.value}
										onValueChange={field.onChange}
										className="space-y-2"
									>
										<div className="flex items-center space-x-2 p-3 border border-white/10 rounded-xl bg-white/[0.02] hover:bg-white/[0.05] cursor-pointer">
											<RadioGroupItem value="DYNAMIC" id="symbol-dynamic" />
											<Label
												htmlFor="symbol-dynamic"
												className="flex-1 cursor-pointer"
											>
												<div className="font-medium text-xs text-white">
													{t(
														"launchModal.symbolModeDynamic",
														"Dynamic (from Screener)",
													)}
												</div>
												<div className="text-[11px] text-white/40">
													{t(
														"launchModal.symbolModeDynamicDesc",
														"Automatically select symbols based on market conditions",
													)}
												</div>
											</Label>
										</div>
										<div className="flex items-center space-x-2 p-3 border border-white/10 rounded-xl bg-white/[0.02] hover:bg-white/[0.05] cursor-pointer">
											<RadioGroupItem value="STATIC" id="symbol-static" />
											<Label
												htmlFor="symbol-static"
												className="flex-1 cursor-pointer"
											>
												<div className="font-medium text-xs text-white">
													{t(
														"launchModal.symbolModeStatic",
														"Static (Manual List)",
													)}
												</div>
												<div className="text-[11px] text-white/40">
													{t(
														"launchModal.symbolModeStaticDesc",
														"Trade specific symbols only",
													)}
												</div>
											</Label>
										</div>
									</RadioGroup>
								)}
							/>
						</div>
					)}

					{/* DYNAMIC MODE SETTINGS (TEMPORARILY HIDDEN via flag) */}
					{!HIDE_DYNAMIC_SELECTION && symbolSelectionMode === "DYNAMIC" && (
						<div className="p-4 border border-white/10 rounded-xl space-y-4 bg-white/[0.02]">
							<Label className="font-semibold text-xs text-white">
								Dynamic Selection Settings
							</Label>

							{/* Dynamic Sub-Mode Selection */}
							<Controller
								name="dynamicMode"
								control={control}
								render={({ field }) => (
									<Select
										onValueChange={field.onChange}
										defaultValue={field.value}
										value={field.value}
									>
										<SelectTrigger className="h-9 rounded-lg border border-white/10 bg-white/[0.03] text-xs text-white">
											<SelectValue placeholder="Select Logic" />
										</SelectTrigger>
										<SelectContent className="border border-white/10 bg-obsidian/95 text-white">
											{canUseOracle && (
												<SelectItem value="DYNAMIC_ORACLE">
													Oracle Filter
												</SelectItem>
											)}
											<SelectItem value="DYNAMIC_NATR">
												Low Volatility (NATR)
											</SelectItem>
										</SelectContent>
									</Select>
								)}
							/>

							{/* ORACLE SPECIFIC */}
							{dynamicMode === "DYNAMIC_ORACLE" && canUseOracle && (
								<>
									<div className="space-y-2">
										<Label className="text-xs text-white/70">
											Required Regime
										</Label>
										<Controller
											name="oracleRegime"
											control={control}
											render={({ field }) => (
												<Select
													onValueChange={field.onChange}
													defaultValue={field.value}
													value={field.value}
												>
													<SelectTrigger className="h-9 rounded-lg border border-white/10 bg-white/[0.03] text-xs text-white">
														<SelectValue />
													</SelectTrigger>
													<SelectContent className="border border-white/10 bg-obsidian/95 text-white">
														<SelectItem value="0">
															{t("launchModal.oracleRegimeParanoiaFull")}
														</SelectItem>
														<SelectItem value="1">
															{t("launchModal.oracleRegimeAmnesiaFull")}
														</SelectItem>
														<SelectItem value="2">
															{t("launchModal.oracleRegimeSchizophreniaFull")}
														</SelectItem>
													</SelectContent>
												</Select>
											)}
										/>
									</div>
									<div className="space-y-2">
										<div className="flex justify-between">
											<Label className="text-xs text-white/70">
												Min Confidence (%)
											</Label>
											<span className="text-xs text-cyan font-mono">
												{oracleConfidence}%
											</span>
										</div>
										<Controller
											name="oracleConfidence"
											control={control}
											render={({ field }) => (
												<Slider
													defaultValue={[field.value || 95]}
													value={[field.value || 95]}
													max={100}
													step={1}
													onValueChange={(vals) => field.onChange(vals[0])}
												/>
											)}
										/>
									</div>
								</>
							)}

							{/* NATR SPECIFIC */}
							{dynamicMode === "DYNAMIC_NATR" && (
								<div className="space-y-2">
									<Label className="text-xs text-white/70">Min NATR</Label>
									<Controller
										name="minNatr"
										control={control}
										render={({ field }) => (
											<Input
												type="number"
												step="0.1"
												{...field}
												onChange={(e) =>
													field.onChange(parseFloat(e.target.value))
												}
												className="h-9 rounded-lg border border-white/10 bg-white/[0.03] text-xs text-white"
											/>
										)}
									/>
								</div>
							)}

							{/* Max Concurrent */}
							<div className="space-y-2 border-t border-white/10 pt-2">
								<Label className="text-xs text-white/70">
									Max Concurrent Symbols
								</Label>
								<Controller
									name="maxConcurrentSymbols"
									control={control}
									render={({ field }) => (
										<Input
											type="number"
											{...field}
											onChange={(e) =>
												field.onChange(parseInt(e.target.value, 10))
											}
											className="h-9 rounded-lg border border-white/10 bg-white/[0.03] text-xs text-white"
										/>
									)}
								/>
							</div>
						</div>
					)}

					{/* Symbols Input (Always visible when dynamic is hidden, or in STATIC mode) */}
					{(HIDE_DYNAMIC_SELECTION || symbolSelectionMode === "STATIC") && (
						<div className="space-y-2">
							<Label
								htmlFor="symbols"
								className="text-[11px] uppercase tracking-wider font-semibold text-white/60"
							>
								{t("launchModal.symbolsLabel", "Symbols List")}
							</Label>
							<Controller
								name="symbols"
								control={control}
								rules={{
									required: t(
										"launchModal.errors.symbolsRequired",
										"Symbols are required",
									),
								}}
								render={({ field }) => (
									<Input
										id="symbols"
										placeholder={t(
											"launchModal.symbolsPlaceholder",
											"BTCUSDT, ETHUSDT, SOLUSDT...",
										)}
										className="h-9 rounded-xl border border-white/10 bg-white/[0.03] px-3 font-mono text-xs text-white placeholder-white/25 focus:border-cyan/50 focus:ring-1 focus:ring-cyan/30 transition-colors"
										{...field}
									/>
								)}
							/>
							{errors.symbols && (
								<p className="text-xs text-rose-400">
									{errors.symbols.message}
								</p>
							)}
							<p className="text-[11px] text-white/40">
								{t(
									"launchModal.symbolsHelp",
									"Separate multiple symbols with commas",
								)}
							</p>
						</div>
					)}

					{/* Advanced Settings: ML & Regime (TEMPORARILY HIDDEN via flag) */}
					{!HIDE_ADVANCED_SETTINGS && (
						<div className="space-y-3 p-4 border border-white/10 rounded-xl bg-white/[0.02]">
							<Label className="text-xs font-semibold text-white uppercase tracking-wider">
								{t("launchModal.advancedSettingsLabel", "Advanced Settings")}
							</Label>

							{/* ML Confirmation */}
							<div className="flex items-center space-x-2">
								<Controller
									name="useMlConfirmation"
									control={control}
									render={({ field }) => (
										<Checkbox
											id="use-ml-confirmation"
											checked={field.value}
											onCheckedChange={field.onChange}
										/>
									)}
								/>
								<Label
									htmlFor="use-ml-confirmation"
									className="text-xs text-white/80 cursor-pointer"
								>
									{t(
										"launchModal.useMlConfirmationLabel",
										"Enable ML Confirmation",
									)}
								</Label>
							</div>

							{/* Breakeven on Regime Change - Oracle users only */}
							{canUseOracle && (
								<div className="flex items-center space-x-2">
									<Controller
										name="breakevenOnRegimeChange"
										control={control}
										render={({ field }) => (
											<Checkbox
												id="breakeven-on-regime-change"
												checked={field.value}
												onCheckedChange={field.onChange}
											/>
										)}
									/>
									<Label
										htmlFor="breakeven-on-regime-change"
										className="text-xs text-white/80 cursor-pointer"
									>
										{t(
											"launchModal.breakevenOnRegimeChangeLabel",
											"Breakeven on Regime Change",
										)}
									</Label>
								</div>
							)}
						</div>
					)}

					<DialogFooter className="gap-2 pt-3 sm:gap-2">
						<Button
							type="button"
							variant="ghost"
							onClick={onClose}
							disabled={isLoading}
							className="rounded-xl border border-white/10 bg-white/[0.02] hover:bg-white/[0.06] text-white/60 hover:text-white text-xs h-9 px-4"
						>
							{t("common:cancel")}
						</Button>
						<Button
							type="submit"
							disabled={isLoading}
							className="rounded-xl bg-gradient-to-r from-azure to-cyan text-white font-semibold text-xs h-9 px-5 shadow-[0_0_20px_-4px_rgba(0,212,255,0.6)] hover:shadow-[0_0_25px_-2px_rgba(0,212,255,0.85)] hover:brightness-110 transition-all"
						>
							{isLoading && <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />}
							{t("launchModal.launchButton", "Launch Strategy")}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
};
