// src/pages/Settings.tsx

import { format } from "date-fns";
import {
	AlertCircle,
	AlertTriangle,
	BadgeCheck,
	BadgeHelp,
	BadgeX,
	Bell,
	Database,
	Key,
	Plus,
	Save,
	Send,
	Settings as SettingsIcon,
	Shield,
	Loader2 as SpinnerIcon,
	RefreshCcwDot as TestIcon,
	Trash2,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
// --- UI & Layout Components ---
import { PageLayout } from "@/components/layout/PageLayout";
import { AddApiKeyModal } from "@/components/settings/AddApiKeyModal";
import { BlacklistSection } from "@/components/settings/BlacklistSection";
import { ConfirmationModal } from "@/components/shared/ConfirmationModal";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/use-toast";
// --- API & Types ---
import {
	useAddApiKey,
	useAddSymbol,
	useConfig,
	useDeleteApiKey,
	useDeleteSymbol,
	useTelegramBindUrl,
	useTestApiKey,
	useTestTelegramNotification,
	useUpdateConfig,
} from "@/lib/api";
import type {
	AddApiKeyPayload,
	ApiKey as ApiKeyType,
	AppConfig,
} from "@/types/api";

// --- Reusable Components for this page ---
interface SettingsSectionProps {
	title: string;
	description: string;
	children: React.ReactNode;
	footerActions?: React.ReactNode;
}

const SettingsSection: React.FC<SettingsSectionProps> = ({
	title,
	description,
	children,
	footerActions,
}) => (
	<Card>
		<CardHeader>
			<CardTitle>{title}</CardTitle>
			<CardDescription>{description}</CardDescription>
		</CardHeader>
		<CardContent>{children}</CardContent>
		{footerActions && (
			<>
				<Separator />
				<div className="p-6 pt-4">{footerActions}</div>
			</>
		)}
	</Card>
);

const InfoPanel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
	<div className="bg-accent/50 p-4 rounded-lg space-y-4 h-fit">{children}</div>
);

// --- Main Page Component ---
export default function Settings() {
	const { t } = useTranslation(["settings", "common"]);
	const { toast } = useToast();
	const { data: config, isLoading, isError, error } = useConfig();
	const { mutate: updateConfig, isPending: isSavingConfig } = useUpdateConfig();
	const { mutate: testTelegramNotification, isPending: isTestingNotification } =
		useTestTelegramNotification();
	const { mutate: getTelegramBindUrl, isPending: isGettingBindUrl } =
		useTelegramBindUrl();
	const { mutate: addApiKey, isPending: isAddingApiKey } = useAddApiKey();
	const { mutate: deleteApiKey, isPending: isDeletingApiKey } =
		useDeleteApiKey();
	const { mutate: testApiKey } = useTestApiKey();
	const { mutate: addSymbol, isPending: isAddingSymbol } = useAddSymbol();
	const { mutate: deleteSymbol, isPending: isDeletingSymbol } =
		useDeleteSymbol();

	const [testingApiKeyId, setTestingApiKeyId] = useState<number | null>(null);
	const [apiKeyToDelete, setApiKeyToDelete] = useState<ApiKeyType | null>(null);

	const [isAddApiKeyModalOpen, setIsAddApiKeyModalOpen] = useState(false);
	const [deletingSymbolValue, setDeletingSymbolValue] = useState<string | null>(
		null,
	);

	const [symbols, setSymbols] = useState<string[]>([]);
	const [newSymbol, setNewSymbol] = useState("");

	const [riskMaxDrawdown, setRiskMaxDrawdown] = useState<number | string>("");
	const [riskMaxConsecutiveLosses, setRiskMaxConsecutiveLosses] = useState<
		number | string
	>("");
	const [riskMaxConcurrentTrades, setRiskMaxConcurrentTrades] = useState<
		number | string
	>("");
	const [riskStopLossEnabled, setRiskStopLossEnabled] =
		useState<boolean>(false);
	const [riskDefaultStopLossPercent, setRiskDefaultStopLossPercent] = useState<
		number | string
	>("");
	const [riskMaxStopDistancePct, setRiskMaxStopDistancePct] = useState<
		number | string
	>("");
	const [riskDailyMaxLossPercent, setRiskDailyMaxLossPercent] = useState<
		number | string
	>("");

	const [adaptiveRmEnabled, setAdaptiveRmEnabled] = useState<boolean>(false);
	const [windowSize, setWindowSize] = useState<number | string>("");
	const [minTrades, setMinTrades] = useState<number | string>("");
	const [pnlThreshold, setPnlThreshold] = useState<number | string>("");
	const [winRateThreshold, setWinRateThreshold] = useState<number | string>("");
	const [maxConsecLosses, setMaxConsecLosses] = useState<number | string>("");
	const [recoveryWins, setRecoveryWins] = useState<number | string>("");
	const [recoveryPnl, setRecoveryPnl] = useState<number | string>("");
	const [cooldownSeconds, setCooldownSeconds] = useState<number | string>("");
	const [adaptiveRmEnabledForBacktest, setAdaptiveRmEnabledForBacktest] =
		useState<boolean>(false);

	const [backtestRiskMaxDrawdown, setBacktestRiskMaxDrawdown] = useState<
		number | string
	>("");
	const [
		backtestRiskMaxConsecutiveLosses,
		setBacktestRiskMaxConsecutiveLosses,
	] = useState<number | string>("");
	const [backtestRiskMaxConcurrentTrades, setBacktestRiskMaxConcurrentTrades] =
		useState<number | string>("");
	const [backtestRiskStopLossEnabled, setBacktestRiskStopLossEnabled] =
		useState<boolean>(false);
	const [
		backtestRiskDefaultStopLossPercent,
		setBacktestRiskDefaultStopLossPercent,
	] = useState<number | string>("");
	const [backtestRiskMaxStopDistancePct, setBacktestRiskMaxStopDistancePct] =
		useState<number | string>("");
	const [backtestRiskDailyMaxLossPercent, setBacktestRiskDailyMaxLossPercent] =
		useState<number | string>("");
	const [backtestRiskPerTrade, setBacktestRiskPerTrade] = useState<
		number | string
	>("");
	const [backtestLeverage, setBacktestLeverage] = useState<number | string>("");

	const [notifEmailEnabled, setNotifEmailEnabled] = useState<boolean>(false);
	const [notifTelegramEnabled, setNotifTelegramEnabled] =
		useState<boolean>(false);
	const [notifTelegramChatId, setNotifTelegramChatId] = useState<string>("");
	const [notifTelegramUsername, setNotifTelegramUsername] =
		useState<string>("");

	// Granular Telegram notification settings
	const [notifyNewPosition, setNotifyNewPosition] = useState<boolean>(true);
	const [notifyPositionClosed, setNotifyPositionClosed] =
		useState<boolean>(true);
	const [notifyPartialTp, setNotifyPartialTp] = useState<boolean>(true);
	const [notifySlMovedToBe, setNotifySlMovedToBe] = useState<boolean>(true);
	const [notifyRiskAlerts, setNotifyRiskAlerts] = useState<boolean>(true);
	const [notifyOrderErrors, setNotifyOrderErrors] = useState<boolean>(true);
	const [notifyBotErrors, setNotifyBotErrors] = useState<boolean>(true);
	const [notifyBlacklistAlerts, setNotifyBlacklistAlerts] =
		useState<boolean>(true);

	const [confirmAction, setConfirmAction] = useState<{
		open: boolean;
		title: string;
		description: string;
		onConfirm: () => void;
		isLoading?: boolean;
	}>({
		open: false,
		title: "",
		description: "",
		onConfirm: () => {},
		isLoading: false,
	});

	const [prevConfig, setPrevConfig] = useState<AppConfig | undefined>(
		undefined,
	);
	if (config !== prevConfig) {
		setPrevConfig(config);
		if (config) {
			setSymbols(config.dataSources?.symbols || []);
			const rm = config.riskManagement;
			setRiskMaxDrawdown(rm?.maxDrawdown ?? "");
			setRiskMaxConsecutiveLosses(rm?.maxConsecutiveLosses ?? "");
			setRiskMaxConcurrentTrades(rm?.maxConcurrentTrades ?? "");
			setRiskStopLossEnabled(rm?.stopLossEnabled ?? false);
			setRiskDefaultStopLossPercent(rm?.defaultStopLossPercent ?? "");
			setRiskMaxStopDistancePct(rm?.maxStopDistancePct ?? 10);
			setRiskDailyMaxLossPercent(rm?.dailyMaxLossPercent ?? 5);

			setAdaptiveRmEnabled(rm?.strategySymbolAdjustmentEnabled ?? false);
			setWindowSize(rm?.strategySymbolWindowSize ?? "");
			setMinTrades(rm?.strategySymbolMinTradesForAssessment ?? "");
			setPnlThreshold(rm?.strategySymbolPnlThresholdPct ?? "");
			setWinRateThreshold(rm?.strategySymbolWinRateThresholdPct ?? "");
			setMaxConsecLosses(rm?.strategySymbolMaxConsecutiveLosses ?? "");
			setRecoveryWins(rm?.strategySymbolRecoveryConsecutiveWins ?? "");
			setRecoveryPnl(rm?.strategySymbolRecoveryPnlThresholdPct ?? "");
			setCooldownSeconds(rm?.strategySymbolCooldownAfterPenaltySeconds ?? "");

			const brm = config.backtestRiskManagement || {};
			setBacktestRiskMaxDrawdown(String(brm?.maxDrawdown ?? ""));
			setBacktestRiskMaxConsecutiveLosses(
				String(brm?.maxConsecutiveLosses ?? ""),
			);
			setBacktestRiskMaxConcurrentTrades(
				String(brm?.maxConcurrentTrades ?? ""),
			);
			setBacktestRiskStopLossEnabled(brm?.stopLossEnabled ?? false);
			setBacktestRiskDefaultStopLossPercent(
				String(brm?.defaultStopLossPercent ?? ""),
			);
			setBacktestRiskMaxStopDistancePct(String(brm?.maxStopDistancePct ?? 10));
			setBacktestRiskDailyMaxLossPercent(String(brm?.dailyMaxLossPercent ?? 5));
			setBacktestRiskPerTrade(String(brm?.riskPerTradePercent ?? 1));
			setBacktestLeverage(String(brm?.leverage ?? 10));
			setAdaptiveRmEnabledForBacktest(
				brm?.strategySymbolAdjustmentEnabledForBacktest ?? false,
			);

			setNotifEmailEnabled(config.notifications?.emailEnabled || false);
			setNotifTelegramEnabled(config.notifications?.telegramEnabled || false);
			setNotifTelegramChatId(config.notifications?.telegramChatId || "");
			setNotifTelegramUsername(config.notifications?.telegramUsername || "");

			// Granular Telegram notification settings (default to true if not set)
			setNotifyNewPosition(config.notifications?.notifyNewPosition ?? true);
			setNotifyPositionClosed(
				config.notifications?.notifyPositionClosed ?? true,
			);
			setNotifyPartialTp(config.notifications?.notifyPartialTp ?? true);
			setNotifySlMovedToBe(config.notifications?.notifySlMovedToBe ?? true);
			setNotifyRiskAlerts(config.notifications?.notifyRiskAlerts ?? true);
			setNotifyOrderErrors(config.notifications?.notifyOrderErrors ?? true);
			setNotifyBotErrors(config.notifications?.notifyBotErrors ?? true);
			setNotifyBlacklistAlerts(
				config.notifications?.notifyBlacklistAlerts ?? true,
			);
		}
	}

	const handleAddApiKeySubmit = (data: AddApiKeyPayload) => {
		addApiKey(data, {
			onSuccess: () => setIsAddApiKeyModalOpen(false),
		});
	};

	// --- API KEY HANDLERS ---
	const handleDeleteApiKeyConfirm = (apiKeyId: number) => {
		if (apiKeyId) {
			setConfirmAction((prev) => ({ ...prev, isLoading: true }));
			deleteApiKey(apiKeyId, {
				onSettled: () => {
					setApiKeyToDelete(null);
					setConfirmAction({
						open: false,
						title: "",
						description: "",
						onConfirm: () => {},
						isLoading: false,
					});
				},
			});
		}
	};

	const openDeleteApiKeyModal = (apiKey: ApiKeyType) => {
		setApiKeyToDelete(apiKey);
		setConfirmAction({
			open: true,
			title: `Delete API Key: ${apiKey.name}`,
			description: `Are you sure you want to delete the API key "${apiKey.name}"? This action cannot be undone.`,
			onConfirm: () => handleDeleteApiKeyConfirm(apiKey.id),
			isLoading: false,
		});
	};

	const handleTestApiKey = (apiKeyId: number) => {
		setTestingApiKeyId(apiKeyId);
		testApiKey(apiKeyId, {
			onSettled: () => setTestingApiKeyId(null),
		});
	};

	const handleAddSymbolSubmit = () => {
		const symbolToAdd = newSymbol.toUpperCase().trim();
		if (symbolToAdd && !symbols.includes(symbolToAdd)) {
			addSymbol(symbolToAdd, {
				onSuccess: () => setNewSymbol(""),
			});
		} else if (symbols.includes(symbolToAdd)) {
			toast({
				title: t("toasts.symbolExistsTitle"),
				description: t("toasts.symbolExistsDescription", {
					symbol: symbolToAdd,
				}),
				variant: "default",
			});
		}
	};

	const handleDeleteSymbolConfirm = (symbolToDelete: string) => {
		if (symbolToDelete) {
			setConfirmAction((prev) => ({ ...prev, isLoading: true }));
			deleteSymbol(symbolToDelete, {
				onSettled: () => {
					setConfirmAction({
						open: false,
						title: "",
						description: "",
						onConfirm: () => {},
						isLoading: false,
					});
					setDeletingSymbolValue(null);
				},
			});
		}
	};

	const openDeleteSymbolModal = (symbolToRemove: string) => {
		setDeletingSymbolValue(symbolToRemove);
		setConfirmAction({
			open: true,
			title: `Remove Symbol: ${symbolToRemove}`,
			description: `Are you sure you want to remove ${symbolToRemove} from monitored symbols? The bot will stop collecting market data for it.`,
			onConfirm: () => handleDeleteSymbolConfirm(symbolToRemove),
			isLoading: false,
		});
	};

	const handleSave = (section: string) => {
		let payload: Partial<AppConfig>;
		switch (section) {
			case "Risk Management":
				payload = {
					riskManagement: {
						maxDrawdown: parseFloat(riskMaxDrawdown as string) || 0,
						maxConsecutiveLosses:
							parseInt(riskMaxConsecutiveLosses as string, 10) || 0,
						maxConcurrentTrades:
							parseInt(riskMaxConcurrentTrades as string, 10) || 0,
						stopLossEnabled: riskStopLossEnabled,
						defaultStopLossPercent: riskDefaultStopLossPercent
							? parseFloat(riskDefaultStopLossPercent as string)
							: undefined,
						maxStopDistancePct:
							parseFloat(riskMaxStopDistancePct as string) || 10,
						dailyMaxLossPercent:
							parseFloat(riskDailyMaxLossPercent as string) || 5,
						strategySymbolAdjustmentEnabled: adaptiveRmEnabled,
						strategySymbolWindowSize: parseInt(windowSize as string, 10) || 20,
						strategySymbolMinTradesForAssessment:
							parseInt(minTrades as string, 10) || 10,
						strategySymbolPnlThresholdPct:
							parseFloat(pnlThreshold as string) || -150.0,
						strategySymbolWinRateThresholdPct:
							parseFloat(winRateThreshold as string) || 35.0,
						strategySymbolMaxConsecutiveLosses:
							parseInt(maxConsecLosses as string, 10) || 5,
						strategySymbolRecoveryConsecutiveWins:
							parseInt(recoveryWins as string, 10) || 3,
						strategySymbolRecoveryPnlThresholdPct:
							parseFloat(recoveryPnl as string) || 50.0,
						strategySymbolCooldownAfterPenaltySeconds:
							parseInt(cooldownSeconds as string, 10) || 86400,
					},
				};
				break;
			case "Backtest Risk Management":
				payload = {
					backtestRiskManagement: {
						maxDrawdown: parseFloat(backtestRiskMaxDrawdown as string) || 0,
						dailyMaxLossPercent:
							parseFloat(backtestRiskDailyMaxLossPercent as string) || 0,
						maxConsecutiveLosses:
							parseInt(backtestRiskMaxConsecutiveLosses as string, 10) || 0,
						maxConcurrentTrades:
							parseInt(backtestRiskMaxConcurrentTrades as string, 10) || 0,
						stopLossEnabled: backtestRiskStopLossEnabled,
						defaultStopLossPercent: backtestRiskDefaultStopLossPercent
							? parseFloat(backtestRiskDefaultStopLossPercent as string)
							: undefined,
						maxStopDistancePct:
							parseFloat(backtestRiskMaxStopDistancePct as string) || 10,
						riskPerTradePercent:
							parseFloat(backtestRiskPerTrade as string) || 1,
						leverage: parseFloat(backtestLeverage as string) || 10,
						strategySymbolAdjustmentEnabledForBacktest:
							adaptiveRmEnabledForBacktest,
					},
				};
				break;
			case "Notifications":
				payload = {
					notifications: {
						emailEnabled: notifEmailEnabled,
						telegramEnabled: notifTelegramEnabled,
						telegramChatId: notifTelegramChatId,
						telegramUsername: notifTelegramUsername,
						// Granular Telegram notification settings
						notifyNewPosition,
						notifyPositionClosed,
						notifyPartialTp,
						notifySlMovedToBe,
						notifyRiskAlerts,
						notifyOrderErrors,
						notifyBotErrors,
						notifyBlacklistAlerts,
					},
				};
				break;
			default:
				toast({
					title: t("common:errorTitle"),
					description: t("errors.unknownSection"),
					variant: "destructive",
				});
				return;
		}
		updateConfig(payload);
	};

	const handleConnectTelegram = () => {
		getTelegramBindUrl(undefined, {
			onSuccess: (data) => {
				if (data.url) {
					window.open(data.url, "_blank");
					toast({
						title: t("notifications.telegramBindingStartedTitle"),
						description: t("notifications.telegramBindingStartedDesc"),
					});
				}
			},
			onError: (err) => {
				toast({
					variant: "destructive",
					title: "Error",
					description: err.message,
				});
			},
		});
	};

	if (isLoading) {
		return (
			<PageLayout title={t("pageTitle")} icon={SettingsIcon}>
				<div className="space-y-4">
					{[...Array(3)].map((_, i) => (
						<Skeleton key={i} className="h-48 w-full rounded-lg" />
					))}
				</div>
			</PageLayout>
		);
	}

	if (isError || !config) {
		return (
			<PageLayout title={t("pageTitle")} icon={SettingsIcon}>
				<Alert variant="destructive">
					<AlertCircle className="h-4 w-4" />
					<AlertTitle>{t("loadingError")}</AlertTitle>
					<AlertDescription>
						{error?.message || t("common:errors.unknownError")}
					</AlertDescription>
				</Alert>
			</PageLayout>
		);
	}

	return (
		<PageLayout title={t("pageTitle")} icon={SettingsIcon}>
			<Tabs defaultValue="api-keys" className="w-full">
				<TabsList className="grid w-full grid-cols-2 md:grid-cols-4">
					<TabsTrigger value="api-keys">
						<Key className="w-4 h-4 mr-2" />
						{t("tabs.apiKeys")}
					</TabsTrigger>
					<TabsTrigger value="risk-management">
						<Shield className="w-4 h-4 mr-2" />
						{t("tabs.risk")}
					</TabsTrigger>
					<TabsTrigger value="notifications">
						<Bell className="w-4 h-4 mr-2" />
						{t("tabs.notifications")}
					</TabsTrigger>
					<TabsTrigger value="data-sources">
						<Database className="w-4 h-4 mr-2" />
						{t("tabs.dataSources")}
					</TabsTrigger>
				</TabsList>

				{/* === API Keys Tab (UPDATED) === */}
				<TabsContent value="api-keys" className="mt-6">
					<SettingsSection
						title={t("apiKeys.title")}
						description={t("apiKeys.description")}
					>
						<Alert className="mb-6">
							<AlertTriangle className="h-4 w-4" />
							<AlertTitle>{t("apiKeys.securityNotice.title")}</AlertTitle>
							<AlertDescription>
								{t("apiKeys.securityNotice.description")}{" "}
								<a
									href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/terms-of-service`}
									target="_blank"
									rel="noopener noreferrer"
									className="underline hover:text-primary font-semibold"
								>
									{t("common:termsOfService")}
								</a>
								.
							</AlertDescription>
						</Alert>
						<div className="mb-6">
							<Button
								onClick={() => setIsAddApiKeyModalOpen(true)}
								disabled={isAddingApiKey}
							>
								{isAddingApiKey ? (
									<SpinnerIcon className="mr-2 h-4 w-4 animate-spin" />
								) : (
									<Plus className="w-4 h-4 mr-2" />
								)}
								{t("apiKeys.addButton")}
							</Button>
						</div>
						{!config.apiKeys || config.apiKeys.length === 0 ? (
							<p className="text-muted-foreground">{t("apiKeys.noKeys")}</p>
						) : (
							<Table>
								<TableHeader>
									<TableRow>
										<TableHead>{t("apiKeys.colName")}</TableHead>
										<TableHead>{t("apiKeys.colExchange")}</TableHead>
										<TableHead>{t("apiKeys.colPrefix")}</TableHead>
										<TableHead>{t("apiKeys.colStatus")}</TableHead>
										<TableHead>{t("apiKeys.colCreated")}</TableHead>
										<TableHead className="text-right">
											{t("common:actions")}
										</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{config.apiKeys.map((key) => {
										const isCurrentlyTesting = testingApiKeyId === key.id;
										const isCurrentlyDeleting =
											isDeletingApiKey && apiKeyToDelete?.id === key.id;

										let statusBadge;
										switch (key.status) {
											case "valid":
												statusBadge = (
													<Badge className="bg-green-500 hover:bg-green-600">
														<BadgeCheck className="w-3 h-3 mr-1" />
														{t("apiKeys.statusValid")}
													</Badge>
												);
												break;
											case "invalid":
												statusBadge = (
													<Badge variant="destructive">
														<BadgeX className="w-3 h-3 mr-1" />
														{t("apiKeys.statusInvalid")}
													</Badge>
												);
												break;
											case "testing":
												statusBadge = (
													<Badge variant="secondary">
														<SpinnerIcon className="w-3 h-3 mr-1 animate-spin" />
														{t("apiKeys.statusTesting")}
													</Badge>
												);
												break;
											default:
												statusBadge = (
													<Badge variant="outline">
														<BadgeHelp className="w-3 h-3 mr-1" />
														{t("apiKeys.statusUntested")}
													</Badge>
												);
												break;
										}
										return (
											<TableRow key={key.id}>
												<TableCell>{key.name}</TableCell>
												<TableCell>{key.exchange || t("common:na")}</TableCell>
												<TableCell className="font-mono">
													{key.keyPrefix}
												</TableCell>
												<TableCell>{statusBadge}</TableCell>
												<TableCell>
													{format(new Date(key.createdAt), "PP")}
												</TableCell>
												<TableCell className="text-right space-x-1">
													<Button
														variant="outline"
														size="sm"
														className="h-8"
														onClick={() => handleTestApiKey(key.id)}
														disabled={isCurrentlyTesting || isCurrentlyDeleting}
													>
														{isCurrentlyTesting ? (
															<SpinnerIcon className="w-4 h-4 animate-spin" />
														) : (
															<TestIcon size={14} />
														)}
														<span className="ml-2 hidden sm:inline">
															{t("apiKeys.testButton")}
														</span>
													</Button>
													<Button
														variant="ghost"
														size="icon"
														className="h-8 w-8 text-destructive hover:text-destructive"
														onClick={() => openDeleteApiKeyModal(key)}
														disabled={isCurrentlyDeleting || isCurrentlyTesting}
													>
														{isCurrentlyDeleting ? (
															<SpinnerIcon className="h-4 w-4 animate-spin" />
														) : (
															<Trash2 size={16} />
														)}
													</Button>
												</TableCell>
											</TableRow>
										);
									})}
								</TableBody>
							</Table>
						)}
					</SettingsSection>
				</TabsContent>

				{/* === Data Sources Tab === */}
				<TabsContent value="data-sources" className="mt-6">
					<SettingsSection
						title={t("dataSources.title")}
						description={t("dataSources.description")}
					>
						<div className="grid md:grid-cols-5 gap-8">
							<div className="md:col-span-3 space-y-4">
								<div>
									<Label htmlFor="add-symbol">
										{t("dataSources.addSymbolLabel")}
									</Label>
									<div className="flex space-x-2 mt-2">
										<Input
											id="add-symbol"
											placeholder={t("dataSources.addSymbolPlaceholder")}
											value={newSymbol}
											onChange={(e) => setNewSymbol(e.target.value)}
											onKeyDown={(e) =>
												e.key === "Enter" && handleAddSymbolSubmit()
											}
										/>
										<Button
											onClick={handleAddSymbolSubmit}
											disabled={!newSymbol.trim() || isAddingSymbol}
										>
											{isAddingSymbol ? (
												<SpinnerIcon className="mr-2 h-4 w-4 animate-spin" />
											) : (
												<Plus className="w-4 h-4" />
											)}
											<span className="ml-1">{t("dataSources.addButton")}</span>
										</Button>
									</div>
								</div>
								<div className="space-y-2">
									<Label>{t("dataSources.monitoredSymbolsLabel")}</Label>
									<div className="p-2 border rounded-md min-h-[200px] max-h-[400px] overflow-y-auto">
										{symbols.length > 0 ? (
											<div className="flex flex-wrap gap-2">
												{symbols.map((symbolItem) => (
													<div
														key={symbolItem}
														className="flex items-center gap-1 bg-secondary py-1 pl-3 pr-1 rounded-full"
													>
														<span className="font-mono text-sm">
															{symbolItem}
														</span>
														<Button
															variant="ghost"
															size="icon"
															className="h-6 w-6 text-muted-foreground hover:text-destructive"
															onClick={() => openDeleteSymbolModal(symbolItem)}
															disabled={
																deletingSymbolValue === symbolItem ||
																isDeletingSymbol
															}
														>
															{deletingSymbolValue === symbolItem &&
															isDeletingSymbol ? (
																<SpinnerIcon className="h-3 w-3 animate-spin" />
															) : (
																<Trash2 className="w-3 h-3" />
															)}
														</Button>
													</div>
												))}
											</div>
										) : (
											<p className="text-sm text-muted-foreground text-center p-4">
												{t("dataSources.noSymbols")}
											</p>
										)}
									</div>
								</div>
							</div>

							<div className="md:col-span-2 space-y-4">
								<InfoPanel>
									<h4 className="font-semibold">
										{t("dataSources.statusPanelTitle")}
									</h4>
									{config.dataSources?.statuses.map((status) => (
										<div
											key={status.name}
											className="space-y-2 text-sm p-2 border-b"
										>
											<div className="flex justify-between font-medium">
												<span>{status.name}</span>{" "}
												<span
													className={`flex items-center gap-2 ${status.connected ? "text-profit" : "text-loss"}`}
												>
													<div
														className={
															"w-2 h-2 rounded-full " +
															(status.connected ? "bg-profit" : "bg-loss")
														}
													></div>
													{status.connected
														? t("dataSources.statusConnected")
														: t("dataSources.statusDisconnected")}
												</span>
											</div>
											{status.lastSync && (
												<div className="flex justify-between">
													<span className="text-muted-foreground">
														{t("dataSources.statusLastSync")}
													</span>
													<span>
														{new Date(status.lastSync).toLocaleString()}
													</span>
												</div>
											)}
											{status.error && (
												<div className="text-loss text-xs">{status.error}</div>
											)}
										</div>
									))}
									<div className="flex justify-between text-sm mt-2">
										<span className="text-muted-foreground">
											{t("dataSources.statusTotalSymbols")}
										</span>
										<span className="font-mono">{symbols.length}</span>
									</div>
								</InfoPanel>
							</div>
						</div>
					</SettingsSection>
				</TabsContent>

				{/* === Risk Management Tab === */}
				<TabsContent value="risk-management" className="mt-6">
					<Tabs defaultValue="live-trading" className="w-full">
						<TabsList className="grid w-full grid-cols-2">
							<TabsTrigger value="live-trading">Live Trading</TabsTrigger>
							<TabsTrigger value="backtesting">Backtesting</TabsTrigger>
						</TabsList>
						<TabsContent value="live-trading" className="mt-6">
							<SettingsSection
								title={t("risk.live.title")}
								description={t("risk.live.description")}
								footerActions={
									<Button
										onClick={() => handleSave("Risk Management")}
										disabled={isSavingConfig}
									>
										<Save className="w-4 h-4 mr-2" />
										{isSavingConfig
											? t("common:loading")
											: t("risk.saveButton")}
									</Button>
								}
							>
								<div className="grid md:grid-cols-5 gap-8">
									<div className="md:col-span-3 space-y-6">
										<div className="space-y-2">
											<Label htmlFor="riskMaxDrawdown">
												{t("risk.maxDrawdownLabel")}
											</Label>
											<Input
												type="number"
												value={riskMaxDrawdown}
												onChange={(e) => setRiskMaxDrawdown(e.target.value)}
												id="riskMaxDrawdown"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.maxDrawdownDesc")}
											</p>
										</div>
										<div className="space-y-2">
											<Label htmlFor="riskDailyMaxLossPercent">
												{t("risk.dailyMaxLossPercentLabel")}
											</Label>
											<Input
												type="number"
												value={riskDailyMaxLossPercent}
												onChange={(e) =>
													setRiskDailyMaxLossPercent(e.target.value)
												}
												id="riskDailyMaxLossPercent"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.dailyMaxLossPercentDesc")}
											</p>
										</div>
										<div className="space-y-2">
											<Label htmlFor="riskMaxConsecutiveLosses">
												{t("risk.maxConsecutiveLossesLabel")}
											</Label>
											<Input
												type="number"
												value={riskMaxConsecutiveLosses}
												onChange={(e) =>
													setRiskMaxConsecutiveLosses(e.target.value)
												}
												id="riskMaxConsecutiveLosses"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.maxConsecutiveLossesDesc")}
											</p>
										</div>
										<div className="space-y-2">
											<Label htmlFor="maxConcurrentTrades">
												{t("risk.maxTradesLabel")}
											</Label>
											<Input
												type="number"
												value={riskMaxConcurrentTrades}
												onChange={(e) =>
													setRiskMaxConcurrentTrades(e.target.value)
												}
												id="maxConcurrentTrades"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.maxTradesDesc")}
											</p>
										</div>
										<div className="flex items-center space-x-2">
											<Switch
												id="stopLossEnabled"
												checked={riskStopLossEnabled}
												onCheckedChange={setRiskStopLossEnabled}
											/>{" "}
											<Label htmlFor="stopLossEnabled">
												{t("risk.slEnabledLabel")}
											</Label>
										</div>
										{riskStopLossEnabled && (
											<div className="space-y-2 pl-8">
												<Label htmlFor="defaultStopLossPercent">
													{t("risk.defaultSlLabel")}
												</Label>
												<Input
													type="number"
													value={riskDefaultStopLossPercent}
													onChange={(e) =>
														setRiskDefaultStopLossPercent(e.target.value)
													}
													id="defaultStopLossPercent"
													placeholder={t("risk.defaultSlPlaceholder")}
												/>
												<p className="text-xs text-muted-foreground">
													{t("risk.defaultSlDesc")}
												</p>
											</div>
										)}
										<div className="space-y-2">
											<Label htmlFor="maxStopDistancePct">
												{t("risk.maxStopDistancePctLabel")}
											</Label>
											<Input
												type="number"
												value={riskMaxStopDistancePct}
												onChange={(e) =>
													setRiskMaxStopDistancePct(e.target.value)
												}
												id="maxStopDistancePct"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.maxStopDistancePctDesc")}
											</p>
										</div>

										<Separator />
										<div className="space-y-4 pt-4">
											<div className="space-y-2">
												<h3 className="text-lg font-semibold">
													{t("risk.adaptive.title")}
												</h3>
												<p className="text-sm text-muted-foreground">
													{t("risk.adaptive.description")}
												</p>
											</div>
											<div className="flex items-center space-x-2">
												<Switch
													id="adaptiveRmEnabled"
													checked={adaptiveRmEnabled}
													onCheckedChange={setAdaptiveRmEnabled}
												/>
												<Label htmlFor="adaptiveRmEnabled">
													{t("risk.adaptive.enableLabel")}
												</Label>
											</div>
											{adaptiveRmEnabled && (
												<div className="pl-8 space-y-6 border-l-2 ml-2 pt-4">
													<div>
														<h4 className="font-semibold mb-3">
															{t("risk.adaptive.reductionRulesTitle")}
														</h4>
														<div className="space-y-4">
															<div className="space-y-2">
																<Label htmlFor="windowSize">
																	{t("risk.adaptive.windowSizeLabel")}
																</Label>
																<Input
																	type="number"
																	id="windowSize"
																	value={windowSize}
																	onChange={(e) =>
																		setWindowSize(e.target.value)
																	}
																/>
																<p className="text-xs text-muted-foreground">
																	{t("risk.adaptive.windowSizeDesc")}
																</p>
															</div>
															<div className="space-y-2">
																<Label htmlFor="minTrades">
																	{t("risk.adaptive.minTradesLabel")}
																</Label>
																<Input
																	type="number"
																	id="minTrades"
																	value={minTrades}
																	onChange={(e) => setMinTrades(e.target.value)}
																/>
																<p className="text-xs text-muted-foreground">
																	{t("risk.adaptive.minTradesDesc")}
																</p>
															</div>
															<div className="space-y-2">
																<Label htmlFor="pnlThreshold">
																	{t("risk.adaptive.pnlThresholdLabel")}
																</Label>
																<Input
																	type="number"
																	id="pnlThreshold"
																	value={pnlThreshold}
																	onChange={(e) =>
																		setPnlThreshold(e.target.value)
																	}
																/>
																<p className="text-xs text-muted-foreground">
																	{t("risk.adaptive.pnlThresholdDesc")}
																</p>
															</div>
															<div className="space-y-2">
																<Label htmlFor="winRateThreshold">
																	{t("risk.adaptive.winRateThresholdLabel")}
																</Label>
																<Input
																	type="number"
																	id="winRateThreshold"
																	value={winRateThreshold}
																	onChange={(e) =>
																		setWinRateThreshold(e.target.value)
																	}
																/>
																<p className="text-xs text-muted-foreground">
																	{t("risk.adaptive.winRateThresholdDesc")}
																</p>
															</div>
															<div className="space-y-2">
																<Label htmlFor="maxConsecLosses">
																	{t("risk.adaptive.maxConsecLossesLabel")}
																</Label>
																<Input
																	type="number"
																	id="maxConsecLosses"
																	value={maxConsecLosses}
																	onChange={(e) =>
																		setMaxConsecLosses(e.target.value)
																	}
																/>
																<p className="text-xs text-muted-foreground">
																	{t("risk.adaptive.maxConsecLossesDesc")}
																</p>
															</div>
														</div>
													</div>
													<div>
														<h4 className="font-semibold mb-3">
															{t("risk.adaptive.recoveryRulesTitle")}
														</h4>
														<div className="space-y-4">
															<div className="space-y-2">
																<Label htmlFor="recoveryWins">
																	{t("risk.adaptive.recoveryWinsLabel")}
																</Label>
																<Input
																	type="number"
																	id="recoveryWins"
																	value={recoveryWins}
																	onChange={(e) =>
																		setRecoveryWins(e.target.value)
																	}
																/>
																<p className="text-xs text-muted-foreground">
																	{t("risk.adaptive.recoveryWinsDesc")}
																</p>
															</div>
															<div className="space-y-2">
																<Label htmlFor="recoveryPnl">
																	{t("risk.adaptive.recoveryPnlLabel")}
																</Label>
																<Input
																	type="number"
																	id="recoveryPnl"
																	value={recoveryPnl}
																	onChange={(e) =>
																		setRecoveryPnl(e.target.value)
																	}
																/>
																<p className="text-xs text-muted-foreground">
																	{t("risk.adaptive.recoveryPnlDesc")}
																</p>
															</div>
															<div className="space-y-2">
																<Label htmlFor="cooldownSeconds">
																	{t("risk.adaptive.cooldownLabel")}
																</Label>
																<Input
																	type="number"
																	id="cooldownSeconds"
																	value={cooldownSeconds}
																	onChange={(e) =>
																		setCooldownSeconds(e.target.value)
																	}
																/>
																<p className="text-xs text-muted-foreground">
																	{t("risk.adaptive.cooldownDesc")}
																</p>
															</div>
														</div>
													</div>
												</div>
											)}
										</div>
									</div>

									<div className="md:col-span-2 space-y-6">
										<InfoPanel>
											<div className="flex items-start space-x-3">
												<AlertCircle className="w-5 h-5 mt-0.5 text-primary flex-shrink-0" />
												<div className="space-y-1">
													<h4 className="font-semibold">
														{t("risk.infoPanelTitle")}
													</h4>
													<p className="text-sm text-muted-foreground">
														{t("risk.infoPanelDesc")}
													</p>
												</div>
											</div>
										</InfoPanel>

										{/* === Blacklist Section === */}
										<div className="h-fit">
											<BlacklistSection />
										</div>
									</div>
								</div>
							</SettingsSection>
						</TabsContent>
						<TabsContent value="backtesting" className="mt-6">
							<SettingsSection
								title={t("risk.backtesting.title")}
								description={t("risk.backtesting.description")}
								footerActions={
									<Button
										onClick={() => handleSave("Backtest Risk Management")}
										disabled={isSavingConfig}
									>
										<Save className="w-4 h-4 mr-2" />
										{isSavingConfig
											? t("common:loading")
											: t("risk.saveButton")}
									</Button>
								}
							>
								<div className="grid md:grid-cols-5 gap-8">
									<div className="md:col-span-3 space-y-6">
										<div className="space-y-2">
											<Label htmlFor="backtestRiskMaxDrawdown">
												{t("risk.maxDrawdownLabel")}
											</Label>
											<Input
												type="number"
												value={backtestRiskMaxDrawdown}
												onChange={(e) =>
													setBacktestRiskMaxDrawdown(e.target.value)
												}
												id="backtestRiskMaxDrawdown"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.maxDrawdownDesc")}
											</p>
										</div>
										<div className="space-y-2">
											<Label htmlFor="backtestRiskDailyMaxLossPercent">
												{t("risk.dailyMaxLossPercentLabel")}
											</Label>
											<Input
												type="number"
												value={backtestRiskDailyMaxLossPercent}
												onChange={(e) =>
													setBacktestRiskDailyMaxLossPercent(e.target.value)
												}
												id="backtestRiskDailyMaxLossPercent"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.dailyMaxLossPercentDesc")}
											</p>
										</div>
										<div className="space-y-2">
											<Label htmlFor="backtestRiskMaxConsecutiveLosses">
												{t("risk.maxConsecutiveLossesLabel")}
											</Label>
											<Input
												type="number"
												value={backtestRiskMaxConsecutiveLosses}
												onChange={(e) =>
													setBacktestRiskMaxConsecutiveLosses(e.target.value)
												}
												id="backtestRiskMaxConsecutiveLosses"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.maxConsecutiveLossesDesc")}
											</p>
										</div>
										<div className="space-y-2">
											<Label htmlFor="backtestMaxConcurrentTrades">
												{t("risk.maxTradesLabel")}
											</Label>
											<Input
												type="number"
												value={backtestRiskMaxConcurrentTrades}
												onChange={(e) =>
													setBacktestRiskMaxConcurrentTrades(e.target.value)
												}
												id="backtestMaxConcurrentTrades"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.maxTradesDesc")}
											</p>
										</div>
										<div className="flex items-center space-x-2">
											<Switch
												id="backtestStopLossEnabled"
												checked={backtestRiskStopLossEnabled}
												onCheckedChange={setBacktestRiskStopLossEnabled}
											/>{" "}
											<Label htmlFor="backtestStopLossEnabled">
												{t("risk.slEnabledLabel")}
											</Label>
										</div>
										{backtestRiskStopLossEnabled && (
											<div className="space-y-2 pl-8">
												<Label htmlFor="backtestDefaultStopLossPercent">
													{t("risk.defaultSlLabel")}
												</Label>
												<Input
													type="number"
													value={backtestRiskDefaultStopLossPercent}
													onChange={(e) =>
														setBacktestRiskDefaultStopLossPercent(
															e.target.value,
														)
													}
													id="backtestDefaultStopLossPercent"
													placeholder={t("risk.defaultSlPlaceholder")}
												/>
												<p className="text-xs text-muted-foreground">
													{t("risk.defaultSlDesc")}
												</p>
											</div>
										)}
										<div className="space-y-2">
											<Label htmlFor="backtestRiskMaxStopDistancePct">
												{t("risk.maxStopDistancePctLabel")}
											</Label>
											<Input
												type="number"
												value={backtestRiskMaxStopDistancePct}
												onChange={(e) =>
													setBacktestRiskMaxStopDistancePct(e.target.value)
												}
												id="backtestMaxStopDistancePct"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.maxStopDistancePctDesc")}
											</p>
										</div>

										<Separator />

										<div className="space-y-2 pt-4">
											<Label htmlFor="backtestRiskPerTrade">
												{t("risk.riskPerTradeLabel")}
											</Label>
											<Input
												type="number"
												value={backtestRiskPerTrade}
												onChange={(e) =>
													setBacktestRiskPerTrade(e.target.value)
												}
												id="backtestRiskPerTrade"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.riskPerTradeDesc")}
											</p>
										</div>
										<div className="space-y-2">
											<Label htmlFor="backtestLeverage">
												{t("risk.leverageLabel")}
											</Label>
											<Input
												type="number"
												value={backtestLeverage}
												onChange={(e) => setBacktestLeverage(e.target.value)}
												id="backtestLeverage"
											/>
											<p className="text-xs text-muted-foreground">
												{t("risk.leverageDesc")}
											</p>
										</div>

										<Separator />

										<div className="space-y-4 pt-4">
											<h3 className="text-lg font-semibold">
												{t("risk.adaptive.title")}
											</h3>
											<div className="flex items-center space-x-2">
												<Switch
													id="adaptiveRmEnabledForBacktest"
													checked={adaptiveRmEnabledForBacktest}
													onCheckedChange={setAdaptiveRmEnabledForBacktest}
												/>
												<Label htmlFor="adaptiveRmEnabledForBacktest">
													{t("risk.adaptive.enableForBacktestLabel")}
												</Label>
											</div>
										</div>
									</div>

									<div className="md:col-span-2">
										<InfoPanel>
											<div className="flex items-start space-x-3">
												<AlertCircle className="w-5 h-5 mt-0.5 text-primary flex-shrink-0" />
												<div className="space-y-1">
													<h4 className="font-semibold">
														{t("risk.infoPanelTitle")}
													</h4>
													<p className="text-sm text-muted-foreground">
														{t("risk.infoPanelDesc")}
													</p>
												</div>
											</div>
										</InfoPanel>
									</div>
								</div>
							</SettingsSection>
						</TabsContent>
					</Tabs>
				</TabsContent>

				{/* === Notifications Tab === */}
				<TabsContent value="notifications" className="mt-6">
					<SettingsSection
						title={t("notifications.title")}
						description={t("notifications.description")}
						footerActions={
							<Button
								onClick={() => handleSave("Notifications")}
								disabled={isSavingConfig}
							>
								<Save className="w-4 h-4 mr-2" />
								{isSavingConfig
									? t("common:loading")
									: t("notifications.saveButton")}
							</Button>
						}
					>
						<div className="space-y-6">
							<div className="space-y-4">
								<div className="flex items-center space-x-2">
									<Switch
										id="email-notifications"
										checked={notifEmailEnabled}
										onCheckedChange={setNotifEmailEnabled}
									/>{" "}
									<Label htmlFor="email-notifications">
										{t("notifications.emailLabel")}
									</Label>
								</div>
								<div className="flex items-center space-x-2">
									<Switch
										id="telegram-notifications"
										checked={notifTelegramEnabled}
										onCheckedChange={setNotifTelegramEnabled}
									/>{" "}
									<Label htmlFor="telegram-notifications">
										{t("notifications.telegramLabel")}
									</Label>
								</div>
							</div>

							{notifTelegramEnabled && (
								<div className="space-y-6 pl-8 border-l-2 ml-2">
									<div className="space-y-2">
										<Label htmlFor="telegram-chat-id">
											{t("notifications.telegramIdLabel")}
										</Label>
										<div className="flex flex-col gap-4">
											<div className="flex items-center gap-4">
												{notifTelegramChatId ? (
													<div className="flex flex-col gap-2">
														<div className="flex items-center gap-2 bg-profit/10 border border-profit/20 px-3 py-2 rounded-lg">
															<BadgeCheck className="w-5 h-5 text-profit" />
															<div className="flex flex-col">
																<span className="text-sm font-medium">
																	{t("notifications.telegramConnectedTitle")}
																</span>
																<span className="text-xs text-muted-foreground font-mono">
																	@
																	{notifTelegramUsername || notifTelegramChatId}
																</span>
															</div>
														</div>
														<div className="flex items-center gap-2">
															<Button
																variant="outline"
																size="sm"
																onClick={handleConnectTelegram}
																disabled={isGettingBindUrl}
																className="h-8 text-xs"
															>
																{isGettingBindUrl ? (
																	<SpinnerIcon className="mr-2 h-3 w-3 animate-spin" />
																) : (
																	<TestIcon className="mr-2 h-3 w-3" />
																)}
																{t("notifications.reconnectButton")}
															</Button>
															<Button
																variant="ghost"
																size="sm"
																onClick={() =>
																	testTelegramNotification(notifTelegramChatId)
																}
																disabled={isTestingNotification}
																className="h-8 text-xs text-muted-foreground hover:text-primary"
															>
																{isTestingNotification ? (
																	<SpinnerIcon className="mr-2 h-3 w-3 animate-spin" />
																) : (
																	<Send className="mr-2 h-3 w-3" />
																)}
																{t("notifications.sendTestButton")}
															</Button>
														</div>
													</div>
												) : (
													<Button
														onClick={handleConnectTelegram}
														disabled={isGettingBindUrl}
														className="w-full sm:w-fit py-5 px-6"
													>
														{isGettingBindUrl ? (
															<SpinnerIcon className="mr-2 h-5 w-5 animate-spin" />
														) : (
															<Send className="mr-2 h-5 w-5" />
														)}
														<span className="text-base">
															{t("notifications.telegramConnectButton")}
														</span>
													</Button>
												)}
											</div>
											<p className="text-xs text-muted-foreground leading-relaxed">
												{notifTelegramChatId
													? t("notifications.telegramActiveDesc")
													: t("notifications.telegramBotLinkDesc")}
											</p>
										</div>
									</div>

									<Separator />

									<div className="space-y-4">
										<h4 className="font-semibold text-sm">
											{t("notifications.notificationTypesTitle")}
										</h4>
										<p className="text-xs text-muted-foreground">
											{t("notifications.notificationTypesDesc")}
										</p>

										<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
											<div className="flex items-center space-x-2">
												<Switch
													id="notify-new-position"
													checked={notifyNewPosition}
													onCheckedChange={setNotifyNewPosition}
												/>
												<Label
													htmlFor="notify-new-position"
													className="text-sm"
												>
													{t("notifications.types.newPosition")}
												</Label>
											</div>
											<div className="flex items-center space-x-2">
												<Switch
													id="notify-position-closed"
													checked={notifyPositionClosed}
													onCheckedChange={setNotifyPositionClosed}
												/>
												<Label
													htmlFor="notify-position-closed"
													className="text-sm"
												>
													{t("notifications.types.positionClosed")}
												</Label>
											</div>
											<div className="flex items-center space-x-2">
												<Switch
													id="notify-partial-tp"
													checked={notifyPartialTp}
													onCheckedChange={setNotifyPartialTp}
												/>
												<Label htmlFor="notify-partial-tp" className="text-sm">
													{t("notifications.types.partialTp")}
												</Label>
											</div>
											<div className="flex items-center space-x-2">
												<Switch
													id="notify-sl-moved-to-be"
													checked={notifySlMovedToBe}
													onCheckedChange={setNotifySlMovedToBe}
												/>
												<Label
													htmlFor="notify-sl-moved-to-be"
													className="text-sm"
												>
													{t("notifications.types.slMovedToBe")}
												</Label>
											</div>
											<div className="flex items-center space-x-2">
												<Switch
													id="notify-risk-alerts"
													checked={notifyRiskAlerts}
													onCheckedChange={setNotifyRiskAlerts}
												/>
												<Label htmlFor="notify-risk-alerts" className="text-sm">
													{t("notifications.types.riskAlerts")}
												</Label>
											</div>
											<div className="flex items-center space-x-2">
												<Switch
													id="notify-order-errors"
													checked={notifyOrderErrors}
													onCheckedChange={setNotifyOrderErrors}
												/>
												<Label
													htmlFor="notify-order-errors"
													className="text-sm"
												>
													{t("notifications.types.orderErrors")}
												</Label>
											</div>
											<div className="flex items-center space-x-2">
												<Switch
													id="notify-bot-errors"
													checked={notifyBotErrors}
													onCheckedChange={setNotifyBotErrors}
												/>
												<Label htmlFor="notify-bot-errors" className="text-sm">
													{t("notifications.types.botErrors")}
												</Label>
											</div>
											<div className="flex items-center space-x-2">
												<Switch
													id="notify-blacklist-alerts"
													checked={notifyBlacklistAlerts}
													onCheckedChange={setNotifyBlacklistAlerts}
												/>
												<Label
													htmlFor="notify-blacklist-alerts"
													className="text-sm"
												>
													{t("notifications.types.blacklistAlerts")}
												</Label>
											</div>
										</div>
									</div>
								</div>
							)}
						</div>
					</SettingsSection>
				</TabsContent>
			</Tabs>

			<ConfirmationModal
				open={confirmAction.open}
				onOpenChange={(openState) =>
					setConfirmAction((prev) => ({
						...prev,
						open: openState,
						isLoading: openState ? prev.isLoading : false,
					}))
				}
				title={confirmAction.title}
				description={confirmAction.description}
				onConfirm={confirmAction.onConfirm}
				loading={isDeletingApiKey || isDeletingSymbol}
			/>
			<AddApiKeyModal
				isOpen={isAddApiKeyModalOpen}
				onClose={() => setIsAddApiKeyModalOpen(false)}
				onAdd={handleAddApiKeySubmit}
				isLoading={isAddingApiKey}
			/>
		</PageLayout>
	);
}
