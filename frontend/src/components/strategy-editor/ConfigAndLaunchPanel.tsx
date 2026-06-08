// src/components/strategy-editor/ConfigAndLaunchPanel.tsx

import { format } from "date-fns";
// Icons
import {
	AlertTriangle,
	CalendarIcon,
	Copy,
	Cpu,
	HelpCircle,
	Loader2,
	Play,
	Rocket,
	Sparkles,
	Zap,
} from "lucide-react";
import { memo, useEffect, useMemo, useState } from "react";
import type { DateRange } from "react-day-picker";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";

// UI Components
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/use-toast";
import { useAuth } from "@/context/AuthContext";
import { useStrategyConstraints } from "@/hooks/useStrategyConstraints";
import {
	fetchSymbolSelectionSettings,
	updateSymbolSelectionSettings as updateSymbolSelectionSettingsApi,
	useConfig,
	useRunBacktest,
	useSaveStrategyConfig,
	useSendTradingViewTestSignal,
	useStartStrategy,
	useTradingViewWebhookInfo,
	useTradingViewWebhookStatus,
	useUpdateStrategyConfig,
} from "@/lib/api";
import { hasProPlanAccess } from "@/lib/strategyRestrictions";
import { cn } from "@/lib/utils";
// State, API & Types
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import type {
	ApiKey,
	StrategyConfigCreatePayload,
	StrategyConfigData,
} from "@/types/api";
import {
	extractFoundationGroups,
	getFoundationWeightValue,
} from "./FoundationWeightsHelper";
// Custom Components
import { FoundationWeightsModal } from "./FoundationWeightsModal";
import { SymbolCombobox } from "./SymbolCombobox";
import type { ConditionBlock } from "./types";

interface ConfigAndLaunchPanelProps {
	isSaving: boolean;
}

export const ConfigAndLaunchPanel = memo(
	({ isSaving }: ConfigAndLaunchPanelProps) => {
		const { t } = useTranslation(["strategy-editor", "common"]);
		const { toast } = useToast();
		const navigate = useNavigate();
		const { id: strategyIdFromParams } = useParams<{ id?: string }>();
		const { user, isLoading: isAuthLoading } = useAuth();

		// Store state
		const store = useStrategyEditorStore();
		const {
			setStrategyField,
			useFoundationWeights,
			setUseFoundationWeights,
			entryConditions,
			foundationWeights,
			oracleRegime,
			oracleConfidence,
			setOracleRegime,
			setOracleConfidence,
			use_ml_confirmation,
			setUseMlConfirmation,
			breakeven_on_regime_change,
			setBreakevenOnRegimeChange,
			symbol_selection_mode,
			max_concurrent_symbols,
			min_natr,
			name,
			description,
			symbol,
			marketType,
			signal_source,
			min_foundation_weight_threshold,
		} = store;

		// Permissions
		const isAdmin = user?.role === "admin";
		const hasPrecisionAccess = hasProPlanAccess(user?.plan);
		const canUseOracle = isAdmin || hasPrecisionAccess;

		// API & Multi-account
		const { mutate: runBacktest, isPending: isBacktesting } = useRunBacktest();
		const { mutate: startStrategy, isPending: isStarting } = useStartStrategy();
		const { mutate: saveNewStrategy, isPending: isSavingNew } =
			useSaveStrategyConfig();
		const { mutate: updateStrategy, isPending: isUpdating } =
			useUpdateStrategyConfig();
		const { data: config } = useConfig();
		const [selectedApiKeyId, setSelectedApiKeyId] = useState<number | null>(
			null,
		);

		const activeApiKeys: ApiKey[] = useMemo(() => {
			if (!config?.apiKeys) return [];
			return config.apiKeys.filter(
				(key) => key.isActive && key.status === "valid",
			);
		}, [config]);

		// Render-phase sync of selectedApiKeyId
		const [prevActiveApiKeys, setPrevActiveApiKeys] = useState<ApiKey[]>([]);
		if (activeApiKeys !== prevActiveApiKeys) {
			setPrevActiveApiKeys(activeApiKeys);
			if (activeApiKeys.length === 1 && !selectedApiKeyId) {
				setSelectedApiKeyId(activeApiKeys[0].id);
			}
		}

		// UI state
		const [isWeightsModalOpen, setIsWeightsModalOpen] = useState(false);
		const [dateRange, setDateRange] = useState<DateRange | undefined>({
			from: new Date(new Date().setMonth(new Date().getMonth() - 1)),
			to: new Date(),
		});
		const [backtestEngine, setBacktestEngine] = useState<"vector" | "kline">(
			"vector",
		);

		const {
			isStrategyProOnly: strategyIsPro,
			isStrategyKlineOnly: strategyIsKlineOnly,
		} = useStrategyConstraints(store);

		// Auto-switch to Precision if strategy uses Kline-only blocks
		const [prevStrategyIsKlineOnly, setPrevStrategyIsKlineOnly] =
			useState(false);
		if (strategyIsKlineOnly !== prevStrategyIsKlineOnly) {
			setPrevStrategyIsKlineOnly(strategyIsKlineOnly);
			if (strategyIsKlineOnly && backtestEngine === "vector") {
				setBacktestEngine("kline");
			}
		}

		const isAnythingLoading =
			isBacktesting || isStarting || isSavingNew || isUpdating || isSaving;
		const isTradingViewWebhookMode = signal_source === "tradingview_webhook";

		const hasTradingViewSignalBlock = useMemo(() => {
			const findTVBlock = (
				node: ConditionBlock | null | undefined,
			): boolean => {
				if (!node) return false;
				if (node.type === "tradingview_signal") return true;
				if (node.children) return node.children.some(findTVBlock);
				const b = node as unknown as Record<string, unknown>;
				if (b.if_conditions)
					return findTVBlock(b.if_conditions as ConditionBlock);
				return false;
			};
			return findTVBlock(entryConditions);
		}, [entryConditions]);

		const shouldShowWebhookInfo =
			isTradingViewWebhookMode || hasTradingViewSignalBlock;

		// TradingView Webhook Logic
		const { data: tradingViewWebhookInfo } = useTradingViewWebhookInfo(
			shouldShowWebhookInfo ? (strategyIdFromParams ?? null) : null,
			selectedApiKeyId,
		);
		const {
			data: tradingViewWebhookStatus,
			refetch: refetchTradingViewWebhookStatus,
		} = useTradingViewWebhookStatus(
			shouldShowWebhookInfo ? (strategyIdFromParams ?? null) : null,
		);
		const { mutate: sendTradingViewTestSignal } =
			useSendTradingViewTestSignal();

		// Force STATIC mode for non-pro users
		useEffect(() => {
			if (isAuthLoading) return;
			if (!canUseOracle && symbol_selection_mode !== "STATIC") {
				setStrategyField("symbol_selection_mode", "STATIC");
			}
		}, [canUseOracle, symbol_selection_mode, setStrategyField, isAuthLoading]);

		useEffect(() => {
			fetchSymbolSelectionSettings()
				.then((settings) => {
					if (settings.mode)
						setStrategyField("symbol_selection_mode", settings.mode);
					if (settings.min_natr !== undefined)
						setStrategyField("min_natr", settings.min_natr);
					if (settings.oracle_regime !== undefined)
						setOracleRegime(settings.oracle_regime);
					if (settings.oracle_confidence !== undefined)
						setOracleConfidence(settings.oracle_confidence);
					if (settings.max_concurrent_symbols !== undefined)
						setStrategyField(
							"max_concurrent_symbols",
							settings.max_concurrent_symbols,
						);
				})
				.catch((err) => console.error("Failed to fetch settings:", err));
		}, [setOracleConfidence, setOracleRegime, setStrategyField]);

		const totalFoundationWeight = useMemo(() => {
			if (!useFoundationWeights || entryConditions.type !== "OR") return 0;
			const activeGroups = extractFoundationGroups(entryConditions, t);
			return activeGroups.reduce(
				(acc, group) =>
					acc + getFoundationWeightValue(foundationWeights, group.id),
				0,
			);
		}, [entryConditions, foundationWeights, useFoundationWeights, t]);

		const getStrategyPayload = (): StrategyConfigData => {
			const base = store.toJson();
			return { ...base, enabled: true };
		};

		const handleCopy = async (label: string, text: string) => {
			try {
				await navigator.clipboard.writeText(text);
				toast({
					title: "Copied",
					description: `${label} copied to clipboard.`,
				});
			} catch {
				toast({ variant: "destructive", title: "Copy failed" });
			}
		};

		const handleSendTestSignal = (action: "buy" | "sell") => {
			if (!strategyIdFromParams) return;
			sendTradingViewTestSignal(
				{
					config_id: strategyIdFromParams,
					action,
					api_key_id: selectedApiKeyId,
				},
				{
					onSuccess: (data) => {
						toast({
							title: "Test signal queued",
							description: `Status: ${data.status}`,
						});
						void refetchTradingViewWebhookStatus();
					},
				},
			);
		};

		const handleRunBacktest = () => {
			if (!name || !symbol) {
				toast({
					variant: "destructive",
					title: t("common:errorTitle"),
					description: t("configPanel.toasts.nameAndSymbolRequiredBacktest"),
				});
				return;
			}

			// Check if user is trying to use Precision without Pro plan
			if (backtestEngine === "kline" && !hasPrecisionAccess) {
				toast({
					variant: "destructive",
					title: "Pro Feature",
					description:
						"Precision Engine (Kline) is available for Pro users only. Please upgrade to unlock institutional-grade testing.",
				});
				return;
			}

			const configPayload = getStrategyPayload();
			runBacktest(
				{
					name,
					strategy_name: configPayload.strategy_name || "VisualBuilderStrategy",
					symbol,
					market_type: marketType.toLowerCase() as "futures" | "spot",
					start_date: dateRange?.from
						? format(dateRange.from, "yyyy-MM-dd'T'HH:mm:ss'Z'")
						: "",
					end_date: dateRange?.to
						? format(dateRange.to, "yyyy-MM-dd'T'HH:mm:ss'Z'")
						: "",
					min_foundation_weight_threshold,
					foundation_weights: useFoundationWeights ? foundationWeights : null,
					params: {
						name,
						config: configPayload,
						backtest_engine: backtestEngine, // Pass engine choice to backend
					},
				},
				{
					onSuccess: (data) => {
						toast({
							title: t("common:successTitle"),
							description: t("common:taskSubmittedWithId", {
								taskId: data.task_id,
							}),
						});
						navigate("/research");
					},
				},
			);
		};

		const handleDeploy = async () => {
			if (!name) {
				toast({
					variant: "destructive",
					title: t("common:errorTitle"),
					description: t("configPanel.toasts.nameRequired"),
				});
				return;
			}

			try {
				await updateSymbolSelectionSettingsApi({
					mode: symbol_selection_mode,
					min_natr,
					oracle_regime:
						oracleRegime === null ? undefined : (oracleRegime as 0 | 1 | 2),
					oracle_confidence: oracleConfidence,
					max_concurrent_symbols,
				});
			} catch (e) {
				console.error(e);
			}

			const configData = getStrategyPayload();
			if (symbol_selection_mode === "DYNAMIC_NATR")
				configData.natr_settings = { min_natr };
			else if (symbol_selection_mode === "DYNAMIC_ORACLE")
				configData.oracle_settings = {
					regime: oracleRegime,
					confidence: oracleConfidence,
				};

			if (symbol_selection_mode !== "STATIC")
				configData.max_concurrent_symbols = max_concurrent_symbols;

			const getPaymode = (): "STATIC" | "DYNAMIC" =>
				isTradingViewWebhookMode || symbol_selection_mode === "STATIC"
					? "STATIC"
					: "DYNAMIC";

			const payload: StrategyConfigCreatePayload = {
				name,
				description,
				config_data: configData,
				symbol_selection_mode: getPaymode(),
				symbols: getPaymode() === "STATIC" ? [symbol] : [],
				use_ml_confirmation: use_ml_confirmation,
				foundation_weights: useFoundationWeights ? foundationWeights : null,
				oracle_regime: oracleRegime,
				oracle_confidence: oracleConfidence,
			};

			const performDeploy = (configId: string) => {
				startStrategy(
					{
						configId,
						mode: "live",
						symbol_selection_mode: getPaymode(),
						symbols: getPaymode() === "STATIC" ? [symbol] : [],
						apiKeyId: selectedApiKeyId ?? undefined,
					},
					{
						onSuccess: () =>
							navigate(
								isTradingViewWebhookMode
									? `/editor/${configId}`
									: "/strategies",
							),
						onError: () => navigate(`/editor/${configId}`, { replace: true }),
					},
				);
			};

			if (strategyIdFromParams) {
				updateStrategy(
					{ id: strategyIdFromParams, payload },
					{
						onSuccess: (updated) => {
							toast({
								title: t("common:successTitle"),
								description: t("configPanel.toasts.updateSuccess"),
							});
							performDeploy(updated.id);
						},
					},
				);
			} else {
				saveNewStrategy(payload, {
					onSuccess: (created) => {
						toast({
							title: t("common:successTitle"),
							description: t("configPanel.toasts.saveSuccess"),
						});
						performDeploy(created.id);
					},
				});
			}
		};

		// TradingView Payloads
		const tradingViewPayloadText = useMemo(() => {
			if (!tradingViewWebhookInfo) return "";
			const p: Record<string, unknown> = {
				...tradingViewWebhookInfo.sample_payload,
				action: "buy",
				symbol,
			};
			if (selectedApiKeyId) p.api_key_id = selectedApiKeyId;
			return JSON.stringify(p, null, 2);
		}, [tradingViewWebhookInfo, symbol, selectedApiKeyId]);

		const getWebhookStatusClasses = (status?: string | null) => {
			if (status === "queued_for_execution" || status === "accepted_by_api")
				return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
			return "border-amber-500/30 bg-amber-500/10 text-amber-200";
		};

		return (
			<TooltipProvider>
				<div className="h-full overflow-y-auto p-4 flex flex-col justify-between">
					<FoundationWeightsModal
						isOpen={isWeightsModalOpen}
						onClose={() => setIsWeightsModalOpen(false)}
					/>
					<div className="space-y-4">
						<Card>
							<CardHeader>
								<CardTitle>{t("configPanel.paramsTitle")}</CardTitle>
							</CardHeader>
							<CardContent className="space-y-4">
								<div>
									<Label>{t("configPanel.nameLabel")}</Label>
									<Input
										value={name}
										onChange={(e) => setStrategyField("name", e.target.value)}
										disabled={isAnythingLoading}
									/>
								</div>
								<div>
									<Label>{t("configPanel.descriptionLabel")}</Label>
									<Textarea
										value={description}
										onChange={(e) =>
											setStrategyField("description", e.target.value)
										}
										disabled={isAnythingLoading}
										placeholder={t("configPanel.descriptionPlaceholder")}
										className="h-24"
									/>
								</div>
								<div>
									<Label>{t("configPanel.symbolLabel")}</Label>
									<SymbolCombobox
										value={symbol}
										onChange={(v) =>
											setStrategyField("symbol", v.toUpperCase())
										}
										disabled={isAnythingLoading}
									/>
								</div>
								<div>
									<Label>{t("configPanel.marketTypeLabel")}</Label>
									<Select
										value={marketType || "FUTURES"}
										onValueChange={(v: "FUTURES" | "SPOT") =>
											setStrategyField("marketType", v)
										}
										disabled={isAnythingLoading}
									>
										<SelectTrigger>
											<SelectValue />
										</SelectTrigger>
										<SelectContent>
											<SelectItem value={"FUTURES" as string}>
												FUTURES
											</SelectItem>
											<SelectItem value={"SPOT" as string}>SPOT</SelectItem>
										</SelectContent>
									</Select>
								</div>

								{shouldShowWebhookInfo && tradingViewWebhookInfo && (
									<div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 space-y-3">
										<div className="text-xs text-amber-200/70 leading-relaxed italic">
											{t("canvas.tradingViewWebhookHelpText")}
										</div>
										<div>
											<div className="flex items-center justify-between mb-2">
												<span className="text-sm font-medium">
													{t("configPanel.webhookUrlLabel")}
												</span>
												<Button
													size="sm"
													variant="secondary"
													onClick={() =>
														handleCopy("URL", tradingViewWebhookInfo.url)
													}
												>
													<Copy className="w-4 h-4 mr-2" />
													{t("configPanel.copyButton")}
												</Button>
											</div>
											<Input value={tradingViewWebhookInfo.url} readOnly />
										</div>
										<Textarea
											readOnly
											value={tradingViewPayloadText}
											className="h-32 font-mono text-xs"
										/>
										{strategyIdFromParams && (
											<div className="flex gap-2">
												<Button
													size="sm"
													onClick={() => handleSendTestSignal("buy")}
													disabled={isAnythingLoading}
												>
													<Play className="w-4 h-4 mr-2" />
													{t("configPanel.testBuyButton")}
												</Button>
												<Button
													size="sm"
													onClick={() => handleSendTestSignal("sell")}
													disabled={isAnythingLoading}
												>
													<Play className="w-4 h-4 mr-2" />
													{t("configPanel.testSellButton")}
												</Button>
											</div>
										)}
										{tradingViewWebhookStatus && (
											<div
												className={cn(
													"p-2 rounded border text-xs",
													getWebhookStatusClasses(
														tradingViewWebhookStatus.status,
													),
												)}
											>
												{t("configPanel.lastStatusLabel")}:{" "}
												{tradingViewWebhookStatus.status}
											</div>
										)}
									</div>
								)}
							</CardContent>
						</Card>

						<Card>
							<CardHeader className="flex flex-row items-center justify-between space-y-0">
								<CardTitle>
									{t("configPanel.symbolSelectionModeTitle")}
								</CardTitle>
								<Tooltip>
									<TooltipTrigger asChild>
										<HelpCircle className="h-4 w-4 text-muted-foreground cursor-help" />
									</TooltipTrigger>
									<TooltipContent
										side="left"
										className="max-w-[300px] text-xs leading-relaxed"
									>
										{t("configPanel.symbolSelectionModeTooltip")}
									</TooltipContent>
								</Tooltip>
							</CardHeader>
							<CardContent className="space-y-4">
								<Tooltip>
									<TooltipTrigger asChild>
										<div className="w-full">
											<Select
												value={symbol_selection_mode || "STATIC"}
												onValueChange={(
													v: "STATIC" | "DYNAMIC_NATR" | "DYNAMIC_ORACLE",
												) => setStrategyField("symbol_selection_mode", v)}
												disabled={
													isAnythingLoading ||
													isTradingViewWebhookMode ||
													!canUseOracle
												}
											>
												<SelectTrigger
													className={cn(!canUseOracle && "opacity-80")}
												>
													<div className="flex items-center justify-between w-full pr-2">
														<SelectValue />
														{!canUseOracle && (
															<div className="px-1.5 py-0.5 bg-violet-600 text-[8px] font-bold text-white rounded uppercase ml-2">
																Pro
															</div>
														)}
													</div>
												</SelectTrigger>
												<SelectContent>
													<SelectItem value={"STATIC" as string}>
														{t("configPanel.symbolSelectionModeStatic")}
													</SelectItem>
													{canUseOracle && (
														<>
															<SelectItem value={"DYNAMIC_NATR" as string}>
																{t(
																	"configPanel.symbolSelectionModeDynamicNatr",
																)}
															</SelectItem>
															<SelectItem value={"DYNAMIC_ORACLE" as string}>
																{t(
																	"configPanel.symbolSelectionModeDynamicOracle",
																)}
															</SelectItem>
														</>
													)}
												</SelectContent>
											</Select>
										</div>
									</TooltipTrigger>
									{!canUseOracle && (
										<TooltipContent side="top">
											<p className="text-xs">
												{t("configPanel.dynamicSelectionProOnly") ||
													"Dynamic selection is available for Pro users only"}
											</p>
										</TooltipContent>
									)}
								</Tooltip>

								{symbol_selection_mode === "DYNAMIC_NATR" && (
									<div className="space-y-2">
										<div className="flex justify-between text-xs">
											<Label>Min NATR</Label>
											<span>{min_natr.toFixed(1)}</span>
										</div>
										<Slider
											min={0}
											max={10}
											step={0.1}
											value={[min_natr]}
											onValueChange={(v) => setStrategyField("min_natr", v[0])}
										/>
									</div>
								)}

								{symbol_selection_mode === "DYNAMIC_ORACLE" && (
									<div className="space-y-3">
										<Label>
											{t(
												"configPanel.requiredOracleRegimeLabel",
												"Required Regime",
											)}
										</Label>
										<Select
											value={oracleRegime !== null ? String(oracleRegime) : ""}
											onValueChange={(v) => setOracleRegime(Number(v))}
										>
											<SelectTrigger>
												<SelectValue />
											</SelectTrigger>
											<SelectContent>
												<SelectItem value={"0" as string}>
													{t("configPanel.oracleRegimeParanoiaFull")}
												</SelectItem>
												<SelectItem value={"1" as string}>
													{t("configPanel.oracleRegimeAmnesiaFull")}
												</SelectItem>
												<SelectItem value={"2" as string}>
													{t("configPanel.oracleRegimeSchizophreniaFull")}
												</SelectItem>
											</SelectContent>
										</Select>
										<div className="flex justify-between text-xs">
											<Label>Min Confidence</Label>
											<span>{oracleConfidence}%</span>
										</div>
										<Slider
											min={0}
											max={100}
											value={[oracleConfidence]}
											onValueChange={(v) => setOracleConfidence(v[0])}
										/>
									</div>
								)}

								<div>
									<Label>
										{t(
											"configPanel.maxConcurrentSymbolsLabel",
											"Max Concurrent Symbols",
										)}
									</Label>
									<Input
										type="number"
										value={max_concurrent_symbols}
										onChange={(e) =>
											setStrategyField(
												"max_concurrent_symbols",
												Number(e.target.value),
											)
										}
									/>
								</div>

								<div className="pt-2 border-t space-y-3">
									{isAdmin && (
										<div className="flex items-center space-x-2">
											<Checkbox
												id="use-ml"
												checked={use_ml_confirmation}
												onCheckedChange={(c) => setUseMlConfirmation(!!c)}
											/>
											<Label htmlFor="use-ml">
												{t("configPanel.enableMlConfirmationLabel")}
											</Label>
											<Tooltip>
												<TooltipTrigger asChild>
													<HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" />
												</TooltipTrigger>
												<TooltipContent
													side="top"
													className="max-w-[250px] text-[10px] leading-tight"
												>
													{t("configPanel.enableMlConfirmationTooltip")}
												</TooltipContent>
											</Tooltip>
										</div>
									)}

									{canUseOracle && (
										<div className="flex items-center space-x-2">
											<Checkbox
												id="be-regime"
												checked={breakeven_on_regime_change}
												onCheckedChange={(c) => setBreakevenOnRegimeChange(!!c)}
											/>
											<Label htmlFor="be-regime">
												{t("configPanel.breakevenOnRegimeChangeLabel")}
											</Label>
										</div>
									)}
								</div>
							</CardContent>
						</Card>

						<Card>
							<CardHeader className="flex flex-row items-center justify-between space-y-0">
								<CardTitle>
									{t("configPanel.foundationWeightsSectionTitle")}
								</CardTitle>
								<Tooltip>
									<TooltipTrigger asChild>
										<HelpCircle className="h-4 w-4 text-muted-foreground cursor-help" />
									</TooltipTrigger>
									<TooltipContent
										side="left"
										className="max-w-[300px] text-xs leading-relaxed"
									>
										{t("configPanel.foundationWeightsTooltip")}
									</TooltipContent>
								</Tooltip>
							</CardHeader>
							<CardContent className="space-y-4">
								<div className="flex items-center space-x-2">
									<Checkbox
										id="use-weights"
										checked={useFoundationWeights}
										onCheckedChange={(c) => setUseFoundationWeights(!!c)}
									/>
									<Label htmlFor="use-weights">
										{t("configPanel.activateWeightsLabel")}
									</Label>
								</div>
								{useFoundationWeights && (
									<div className="space-y-2">
										<div className="flex justify-between text-xs">
											<Label>Threshold</Label>
											<span>
												{min_foundation_weight_threshold} /{" "}
												{totalFoundationWeight}
											</span>
										</div>
										<Slider
											min={0}
											max={totalFoundationWeight || 100}
											value={[min_foundation_weight_threshold]}
											onValueChange={(v) =>
												setStrategyField(
													"min_foundation_weight_threshold",
													v[0],
												)
											}
										/>
										<Button
											variant="outline"
											className="w-full"
											onClick={() => setIsWeightsModalOpen(true)}
										>
											{t("configPanel.foundationWeightsButton")}
										</Button>
									</div>
								)}
							</CardContent>
						</Card>

						<Card>
							<CardHeader>
								<CardTitle>{t("configPanel.backtestTitle")}</CardTitle>
							</CardHeader>
							<CardContent className="space-y-4">
								<Popover>
									<PopoverTrigger asChild>
										<Button
											variant="outline"
											className={cn(
												"w-full justify-start text-left font-normal",
												!dateRange && "text-muted-foreground",
											)}
										>
											<CalendarIcon className="mr-2 h-4 w-4" />
											{dateRange?.from ? (
												dateRange.to ? (
													<>
														{format(dateRange.from, "LLL dd, y")}
														{" - "}
														{format(dateRange.to, "LLL dd, y")}
													</>
												) : (
													format(dateRange.from, "LLL dd, y")
												)
											) : (
												<span>
													{t("configPanel.selectPeriodPlaceholder") ||
														"Pick a date"}
												</span>
											)}
										</Button>
									</PopoverTrigger>
									<PopoverContent className="w-auto p-0" align="start">
										<Calendar
											mode="range"
											selected={dateRange}
											onSelect={setDateRange}
											disabled={{ after: new Date() }}
										/>
									</PopoverContent>
								</Popover>
								{hasTradingViewSignalBlock && (
									<div className="flex items-start gap-2 p-2 rounded border border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-200/80 leading-tight">
										<AlertTriangle className="w-4 h-4 text-amber-500 shrink-0" />
										<span>
											{t("configPanel.backtestTvWarning") ||
												"Warning: TradingView signals are not available during backtests. These blocks will have 0 weight."}
										</span>
									</div>
								)}
								<div className="flex flex-col gap-2 mb-4">
									<Label className="text-xs text-muted-foreground uppercase tracking-wider font-bold mb-1">
										{t("configPanel.engineLabel")}
									</Label>
									<div className="grid grid-cols-2 gap-2">
										<Tooltip>
											<TooltipTrigger asChild>
												<div className="w-full">
													<Button
														variant={
															backtestEngine === "vector"
																? "default"
																: "outline"
														}
														size="sm"
														className={cn(
															"flex flex-col h-14 w-full items-center justify-center gap-1",
															backtestEngine === "vector" &&
																" ring-2 ring-primary ring-offset-2 ring-offset-background",
															strategyIsKlineOnly && "opacity-50 grayscale",
														)}
														onClick={() => setBacktestEngine("vector")}
														disabled={strategyIsKlineOnly}
													>
														<div className="flex items-center gap-1.5 font-bold">
															<Zap
																className={cn(
																	"w-4 h-4",
																	backtestEngine === "vector"
																		? "text-yellow-400"
																		: "text-muted-foreground",
																)}
															/>
															{t("configPanel.engineTurboTitle")}
														</div>
														<span className="text-[9px] opacity-70">
															{t("configPanel.engineTurboDesc")}
														</span>
													</Button>
												</div>
											</TooltipTrigger>
											{strategyIsKlineOnly && (
												<TooltipContent>
													<p className="max-w-[200px] text-xs leading-tight">
														{t("configPanel.engineTurboTooltipDisabled")}
													</p>
												</TooltipContent>
											)}
										</Tooltip>

										<Tooltip>
											<TooltipTrigger asChild>
												<div className="w-full">
													<Button
														variant={
															backtestEngine === "kline"
																? "secondary"
																: "outline"
														}
														size="sm"
														className={cn(
															"flex flex-col h-14 w-full items-center justify-center gap-1 relative overflow-hidden",
															backtestEngine === "kline" &&
																"bg-violet-600/20 border-violet-500 text-violet-900 dark:text-violet-100 ring-2 ring-violet-500 ring-offset-2 ring-offset-background hover:bg-violet-600/30",
															!hasPrecisionAccess && "opacity-50 grayscale",
														)}
														onClick={() => setBacktestEngine("kline")}
														disabled={!hasPrecisionAccess}
													>
														{!hasPrecisionAccess && (
															<div className="absolute top-0 right-0 px-1 pt-0.5 bg-violet-600 text-[7px] font-bold text-white rounded-bl-md uppercase">
																Pro
															</div>
														)}
														<div className="flex items-center gap-1.5 font-bold">
															<Cpu
																className={cn(
																	"w-4 h-4",
																	backtestEngine === "kline"
																		? "text-violet-400"
																		: "text-muted-foreground",
																)}
															/>
															{t("configPanel.enginePrecisionTitle")}
														</div>
														<span className="text-[9px] opacity-70">
															{t("configPanel.enginePrecisionDesc")}
														</span>
													</Button>
												</div>
											</TooltipTrigger>
											{!hasPrecisionAccess && (
												<TooltipContent>
													<p className="max-w-[200px] text-xs leading-tight">
														{t("configPanel.enginePrecisionTooltipPro")}
													</p>
												</TooltipContent>
											)}
										</Tooltip>
									</div>
									{strategyIsPro && (
										<div className="text-[10px] text-violet-400 mt-1 flex items-center gap-1">
											<AlertTriangle className="w-3 h-3" />
											<span>{t("configPanel.proBlocksWarning")}</span>
										</div>
									)}
								</div>

								<Button
									className="w-full"
									onClick={handleRunBacktest}
									disabled={isAnythingLoading}
								>
									{isBacktesting ? (
										<Loader2 className="animate-spin mr-2" />
									) : (
										<Play className="mr-2" />
									)}
									{t("configPanel.runBacktestButton", "Run Backtest")}
								</Button>
								<div className="space-y-2 mt-2 pt-2 border-t border-border/40">
									<div className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider mb-1 px-1">
										{t(
											"configPanel.optimizationSectionTitle",
											"Parameter Optimization",
										)}
									</div>
									<Button
										variant="outline"
										className="w-full border-emerald-500/30 hover:bg-emerald-500/10 text-emerald-600 dark:text-emerald-300 flex items-center justify-center gap-2 text-xs font-semibold py-5"
										onClick={() => {
											const strategyJson = getStrategyPayload();
											navigate("/discovery", {
												state: { seedStrategy: strategyJson },
											});
										}}
										disabled={isAnythingLoading}
									>
										<Sparkles className="w-3.5 h-3.5 text-emerald-500 dark:text-emerald-400 shrink-0" />
										<span className="truncate">
											{t(
												"configPanel.optimizeGeneticButton",
												"Genetic Optimization",
											)}
										</span>
									</Button>

									<Button
										variant="outline"
										className="w-full border-violet-500/30 hover:bg-violet-500/10 text-violet-600 dark:text-violet-300 flex items-center justify-center gap-2 text-xs font-semibold py-5"
										onClick={() => {
											const strategyJson = getStrategyPayload();
											navigate("/research", {
												state: { seedStrategy: strategyJson },
											});
										}}
										disabled={isAnythingLoading}
									>
										<Cpu className="w-3.5 h-3.5 text-violet-500 dark:text-violet-400 shrink-0" />
										<span className="truncate">
											{t(
												"configPanel.optimizeBayesianButton",
												"Bayesian Search (Optuna)",
											)}
										</span>
									</Button>
								</div>
							</CardContent>
						</Card>

						<Card>
							<CardHeader>
								<CardTitle>
									{t("configPanel.deployTitle", "Deployment")}
								</CardTitle>
							</CardHeader>
							<CardContent className="space-y-4">
								{activeApiKeys.length > 0 && (
									<Select
										value={
											selectedApiKeyId !== null ? String(selectedApiKeyId) : ""
										}
										onValueChange={(v) => setSelectedApiKeyId(Number(v))}
									>
										<SelectTrigger>
											<SelectValue
												placeholder={t(
													"configPanel.selectAccountPlaceholder",
													"Select Account",
												)}
											/>
										</SelectTrigger>
										<SelectContent>
											{activeApiKeys.map((k) => (
												<SelectItem key={k.id} value={String(k.id) as string}>
													{k.name}
												</SelectItem>
											))}
										</SelectContent>
									</Select>
								)}
								<Button
									className="w-full"
									variant="destructive"
									onClick={handleDeploy}
									disabled={isAnythingLoading || activeApiKeys.length === 0}
								>
									{isStarting ? (
										<Loader2 className="animate-spin mr-2" />
									) : (
										<Rocket className="mr-2" />
									)}
									{t("configPanel.deployButton", "Deploy Strategy")}
								</Button>
							</CardContent>
						</Card>
					</div>
				</div>
			</TooltipProvider>
		);
	},
);
