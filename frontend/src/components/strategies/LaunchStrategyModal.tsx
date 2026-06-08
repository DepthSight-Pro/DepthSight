// src/components/strategies/LaunchStrategyModal.tsx

import { Key, Loader2, Wallet } from "lucide-react";
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
import type { CombinedStrategy } from "@/types/api";

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
				(key) => key.isActive && key.status === "valid",
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
			symbolSelectionMode: currentMode,
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
				"symbolSelectionMode",
				strategy.symbol_selection_mode || currentMode,
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

			if (strategy.symbols && strategy.symbols.length > 0) {
				setValue("symbols", strategy.symbols.join(", "));
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
			<DialogContent className="sm:max-w-[500px] max-h-[80vh] overflow-y-auto">
				<DialogHeader>
					<DialogTitle>
						{t("launchModal.title", { name: strategyName })}
					</DialogTitle>
					<DialogDescription>
						{t(
							"launchModal.description",
							"Configure launch parameters for this strategy",
						)}
					</DialogDescription>
				</DialogHeader>

				<form onSubmit={handleSubmit(onSubmit)} className="space-y-6 py-4">
					{/* Trading Mode */}
					<div className="space-y-3">
						<Label className="text-base font-semibold">
							{t("launchModal.tradingModeLabel", "Trading Mode")}
						</Label>
						<Controller
							name="mode"
							control={control}
							render={({ field }) => (
								<RadioGroup
									value={field.value}
									onValueChange={field.onChange}
									className="space-y-2"
								>
									<div className="flex items-center space-x-2 p-3 border rounded-lg hover:bg-accent cursor-pointer">
										<RadioGroupItem value="paper" id="mode-paper" />
										<Label
											htmlFor="mode-paper"
											className="flex-1 cursor-pointer"
										>
											<div className="font-medium">
												{t("launchModal.paperMode", "Paper Trading")}
											</div>
											<div className="text-xs text-muted-foreground">
												{t(
													"launchModal.paperModeDesc",
													"Test with virtual funds",
												)}
											</div>
										</Label>
									</div>
									<div className="flex items-center space-x-2 p-3 border rounded-lg hover:bg-accent cursor-pointer">
										<RadioGroupItem value="live" id="mode-live" />
										<Label
											htmlFor="mode-live"
											className="flex-1 cursor-pointer"
										>
											<div className="font-medium text-orange-600 dark:text-orange-400">
												{t("launchModal.liveMode", "Live Trading")}
											</div>
											<div className="text-xs text-muted-foreground">
												{t("launchModal.liveModeDesc", "Trade with real funds")}
											</div>
										</Label>
									</div>
								</RadioGroup>
							)}
						/>
					</div>

					{/* API Key Selection for Live Mode - only show if multiple active keys */}
					{tradingMode === "live" && activeApiKeys.length === 0 && (
						<div className="p-3 border border-destructive/50 rounded-lg bg-destructive/10">
							<p className="text-sm text-destructive">
								{t(
									"launchModal.noActiveKeysWarning",
									"No valid API keys available. Please add and verify an API key in Settings.",
								)}
							</p>
						</div>
					)}

					{tradingMode === "live" && activeApiKeys.length > 1 && (
						<div className="space-y-3">
							<Label className="text-base font-semibold flex items-center gap-2">
								<Key className="h-4 w-4" />
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
										<SelectTrigger>
											<SelectValue
												placeholder={t(
													"launchModal.selectAccountPlaceholder",
													"Select trading account",
												)}
											/>
										</SelectTrigger>
										<SelectContent>
											{activeApiKeys.map((key) => {
												const keyBalance = balances?.accounts?.find(
													(a) => a.apiKeyId === key.id,
												);
												return (
													<SelectItem key={key.id} value={String(key.id)}>
														<div className="flex items-center justify-between w-full gap-4">
															<div className="flex items-center gap-2">
																<Wallet className="h-4 w-4 text-muted-foreground" />
																<span>{key.name}</span>
															</div>
															{keyBalance && (
																<span className="text-xs text-muted-foreground">
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
								<p className="text-sm text-destructive">
									{errors.apiKeyId.message}
								</p>
							)}
						</div>
					)}

					{/* Symbol Selection Mode */}
					<div className="space-y-3">
						<Label className="text-base font-semibold">
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
									<div className="flex items-center space-x-2 p-3 border rounded-lg hover:bg-accent cursor-pointer">
										<RadioGroupItem value="DYNAMIC" id="symbol-dynamic" />
										<Label
											htmlFor="symbol-dynamic"
											className="flex-1 cursor-pointer"
										>
											<div className="font-medium">
												{t(
													"launchModal.symbolModeDynamic",
													"Dynamic (from Screener)",
												)}
											</div>
											<div className="text-xs text-muted-foreground">
												{t(
													"launchModal.symbolModeDynamicDesc",
													"Automatically select symbols based on market conditions",
												)}
											</div>
										</Label>
									</div>
									<div className="flex items-center space-x-2 p-3 border rounded-lg hover:bg-accent cursor-pointer">
										<RadioGroupItem value="STATIC" id="symbol-static" />
										<Label
											htmlFor="symbol-static"
											className="flex-1 cursor-pointer"
										>
											<div className="font-medium">
												{t(
													"launchModal.symbolModeStatic",
													"Static (Manual List)",
												)}
											</div>
											<div className="text-xs text-muted-foreground">
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

					{/* DYNAMIC MODE SETTINGS */}
					{symbolSelectionMode === "DYNAMIC" && (
						<div className="p-4 border rounded-lg space-y-4 bg-secondary/20">
							<Label className="font-semibold text-sm">
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
										<SelectTrigger>
											<SelectValue placeholder="Select Logic" />
										</SelectTrigger>
										<SelectContent>
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
										<Label className="text-xs">Required Regime</Label>
										<Controller
											name="oracleRegime"
											control={control}
											render={({ field }) => (
												<Select
													onValueChange={field.onChange}
													defaultValue={field.value}
													value={field.value}
												>
													<SelectTrigger>
														<SelectValue />
													</SelectTrigger>
													<SelectContent>
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
											<Label className="text-xs">Min Confidence (%)</Label>
											<span className="text-xs text-muted-foreground">
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
									<Label className="text-xs">Min NATR</Label>
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
											/>
										)}
									/>
								</div>
							)}

							{/* Max Concurrent */}
							<div className="space-y-2 border-t pt-2">
								<Label className="text-xs">Max Concurrent Symbols</Label>
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
										/>
									)}
								/>
							</div>
						</div>
					)}

					{/* Symbols Input (only for STATIC mode) */}
					{symbolSelectionMode === "STATIC" && (
						<div className="space-y-2">
							<Label htmlFor="symbols">
								{t("launchModal.symbolsLabel", "Symbols List")}
							</Label>
							<Controller
								name="symbols"
								control={control}
								rules={{
									required:
										symbolSelectionMode === "STATIC"
											? t(
													"launchModal.errors.symbolsRequired",
													"Symbols are required for Static mode",
												)
											: false,
								}}
								render={({ field }) => (
									<Input
										id="symbols"
										placeholder={t(
											"launchModal.symbolsPlaceholder",
											"BTCUSDT, ETHUSDT, SOLUSDT...",
										)}
										{...field}
									/>
								)}
							/>
							{errors.symbols && (
								<p className="text-sm text-destructive">
									{errors.symbols.message}
								</p>
							)}
							<p className="text-xs text-muted-foreground">
								{t(
									"launchModal.symbolsHelp",
									"Separate multiple symbols with commas",
								)}
							</p>
						</div>
					)}

					{/* Advanced Settings: ML & Regime */}
					<div className="space-y-3 p-4 border rounded-lg bg-secondary/10">
						<Label className="text-base font-semibold">
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
								className="text-sm cursor-pointer"
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
									className="text-sm cursor-pointer"
								>
									{t(
										"launchModal.breakevenOnRegimeChangeLabel",
										"Breakeven on Regime Change",
									)}
								</Label>
							</div>
						)}
					</div>

					<DialogFooter>
						<Button
							type="button"
							variant="outline"
							onClick={onClose}
							disabled={isLoading}
						>
							{t("common:cancel")}
						</Button>
						<Button type="submit" disabled={isLoading}>
							{isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
							{t("launchModal.launchButton", "Launch Strategy")}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
};
