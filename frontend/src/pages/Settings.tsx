// src/pages/Settings.tsx

import { format } from "date-fns";
import {
	AlertCircle,
	AlertTriangle,
	BadgeCheck,
	BadgeHelp,
	BadgeX,
	Bell,
	Bot,
	FlaskConical,
	Key,
	Plus,
	PowerOff,
	Radio,
	Save,
	Send,
	Settings as SettingsIcon,
	Shield,
	Loader2 as SpinnerIcon,
	RefreshCcwDot as TestIcon,
	Trash2,
} from "lucide-react";
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
// --- UI & Layout Components ---
import { ExchangeBadge } from "@/components/layout/AccountSelector";
import { PageLayout } from "@/components/layout/PageLayout";
import { AddApiKeyModal } from "@/components/settings/AddApiKeyModal";
import { BlacklistSection } from "@/components/settings/BlacklistSection";
import { McpSection } from "@/components/settings/McpSection";
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
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/apiClient";
import { authScopedQueryKey } from "@/lib/queryKeys";
// --- API & Types ---
import {
	useAddApiKey,
	useConfig,
	useDeleteApiKey,
	useTelegramBindUrl,
	useTestApiKey,
	useTestTelegramNotification,
	useToggleApiKeyStatus,
	useUpdateConfig,
} from "@/lib/api";
import { exchangeMeta, normalizeExchangeKey } from "@/lib/exchanges";
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

// Valid top-level tab values (deep-linkable via `?tab=`).
const SETTINGS_TABS = [
	"api-keys",
	"mcp",
	"risk-management",
	"notifications",
] as const;

// --- Main Page Component ---
export default function Settings() {
	const { t } = useTranslation(["settings", "common"]);
	const { toast } = useToast();
	const [searchParams] = useSearchParams();
	// Deep-link support: `?tab=mcp` opens the MCP tab (e.g. via the AI widget MCP button).
	// Synced during render (React-endorsed pattern for adjusting state on navigation),
	// so same-page navigations like /settings -> /settings?tab=mcp also switch tabs.
	const [activeSettingsTab, setActiveSettingsTab] =
		useState<string>("api-keys");
	const [syncedTabParam, setSyncedTabParam] = useState<string | null>(null);
	const tabParam = searchParams.get("tab");
	if (tabParam !== syncedTabParam) {
		setSyncedTabParam(tabParam);
		if (tabParam && (SETTINGS_TABS as readonly string[]).includes(tabParam)) {
			setActiveSettingsTab(tabParam);
		}
	}
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
	const { mutate: toggleApiKeyStatus } = useToggleApiKeyStatus();
	const queryClient = useQueryClient();
	const [isWaitingTelegramBinding, setIsWaitingTelegramBinding] =
		useState<boolean>(false);
	const telegramPollRef = useRef<number | null>(null);

	const stopTelegramPolling = () => {
		if (telegramPollRef.current !== null) {
			window.clearInterval(telegramPollRef.current);
			telegramPollRef.current = null;
		}
		setIsWaitingTelegramBinding(false);
	};

	useEffect(() => {
		return () => {
			if (telegramPollRef.current !== null) {
				window.clearInterval(telegramPollRef.current);
				telegramPollRef.current = null;
			}
		};
	}, []);

	const [testingApiKeyId, setTestingApiKeyId] = useState<number | null>(null);
	const [togglingApiKeyId, setTogglingApiKeyId] = useState<number | null>(null);
	const [apiKeyToDelete, setApiKeyToDelete] = useState<ApiKeyType | null>(null);

	const [isAddApiKeyModalOpen, setIsAddApiKeyModalOpen] = useState(false);

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
	const [shareTelemetry, setShareTelemetry] = useState<boolean>(false);

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
			setShareTelemetry(config.notifications?.shareTelemetry || false);
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

	const handleToggleApiKey = (keyId: number, nextActive: boolean) => {
		setTogglingApiKeyId(keyId);
		toggleApiKeyStatus(
			{ keyId, isActive: nextActive },
			{
				onSettled: () => setTogglingApiKeyId(null),
			},
		);
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
						shareTelemetry,
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
		const baselineChatId = notifTelegramChatId;
		const baselineUsername = notifTelegramUsername;
		getTelegramBindUrl(undefined, {
			onSuccess: (data) => {
				if (data.url) {
					window.open(data.url, "_blank");
					toast({
						title: t("notifications.telegramBindingStartedTitle"),
						description: t("notifications.telegramBindingStartedDesc"),
					});
					// Poll /config until the bot writes the new chat id
					// (binding happens server-side, UI would otherwise stay stale).
					stopTelegramPolling();
					setIsWaitingTelegramBinding(true);
					let attempts = 0;
					const maxAttempts = 20; // ~60s with 3s interval
					telegramPollRef.current = window.setInterval(async () => {
						attempts += 1;
						try {
							const fresh = await apiClient<AppConfig>("/config");
							const freshId = fresh?.notifications?.telegramChatId || "";
							const freshUsername =
								fresh?.notifications?.telegramUsername || "";
							if (
								freshId &&
								(freshId !== baselineChatId ||
									freshUsername !== baselineUsername)
							) {
								stopTelegramPolling();
								await queryClient.invalidateQueries({
									queryKey: authScopedQueryKey("config"),
								});
								toast({
									title: t("notifications.telegramBindingSuccessTitle"),
									description: t(
										"notifications.telegramBindingSuccessDesc",
									),
								});
							} else if (attempts >= maxAttempts) {
								stopTelegramPolling();
								toast({
									title: t("notifications.telegramBindingTimeoutTitle"),
									description: t(
										"notifications.telegramBindingTimeoutDesc",
									),
								});
							}
						} catch {
							if (attempts >= maxAttempts) {
								stopTelegramPolling();
								toast({
									title: t("notifications.telegramBindingTimeoutTitle"),
									description: t(
										"notifications.telegramBindingTimeoutDesc",
									),
								});
							}
							// Transient fetch errors are ignored until attempts run out.
						}
					}, 3000);
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
			<Tabs
			value={activeSettingsTab}
			onValueChange={setActiveSettingsTab}
			className="w-full"
		>
				<div className="flex items-center overflow-x-auto pb-1">
					<TabsList className="inline-flex h-auto w-auto items-center justify-start rounded-xl bg-white/[0.04] border border-white/5 p-1 gap-1 shadow-inner backdrop-blur-md">
						<TabsTrigger
							value="api-keys"
							className="group relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs sm:text-sm font-medium transition-all text-white/50 hover:text-white/80 hover:bg-white/[0.03] data-[state=active]:bg-white/[0.08] data-[state=active]:text-white data-[state=active]:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] data-[state=active]:border data-[state=active]:border-white/10"
						>
							<Key className="w-4 h-4 text-cyan/60 group-hover:text-cyan group-data-[state=active]:text-cyan group-data-[state=active]:drop-shadow-[0_0_8px_rgba(0,212,255,0.85)] transition-all shrink-0" />
							<span>{t("tabs.apiKeys")}</span>
						</TabsTrigger>
						<TabsTrigger
							value="mcp"
							className="group relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs sm:text-sm font-medium transition-all text-white/50 hover:text-white/80 hover:bg-white/[0.03] data-[state=active]:bg-white/[0.08] data-[state=active]:text-white data-[state=active]:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] data-[state=active]:border data-[state=active]:border-white/10"
						>
							<Bot className="w-4 h-4 text-cyan/60 group-hover:text-cyan group-data-[state=active]:text-cyan group-data-[state=active]:drop-shadow-[0_0_8px_rgba(0,212,255,0.85)] transition-all shrink-0" />
							<span>{t("tabs.mcp", "AI Agents (MCP)")}</span>
						</TabsTrigger>
						<TabsTrigger
							value="risk-management"
							className="group relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs sm:text-sm font-medium transition-all text-white/50 hover:text-white/80 hover:bg-white/[0.03] data-[state=active]:bg-white/[0.08] data-[state=active]:text-white data-[state=active]:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] data-[state=active]:border data-[state=active]:border-white/10"
						>
							<Shield className="w-4 h-4 text-cyan/60 group-hover:text-cyan group-data-[state=active]:text-cyan group-data-[state=active]:drop-shadow-[0_0_8px_rgba(0,212,255,0.85)] transition-all shrink-0" />
							<span>{t("tabs.risk")}</span>
						</TabsTrigger>
						<TabsTrigger
							value="notifications"
							className="group relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs sm:text-sm font-medium transition-all text-white/50 hover:text-white/80 hover:bg-white/[0.03] data-[state=active]:bg-white/[0.08] data-[state=active]:text-white data-[state=active]:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] data-[state=active]:border data-[state=active]:border-white/10"
						>
							<Bell className="w-4 h-4 text-cyan/60 group-hover:text-cyan group-data-[state=active]:text-cyan group-data-[state=active]:drop-shadow-[0_0_8px_rgba(0,212,255,0.85)] transition-all shrink-0" />
							<span>{t("tabs.notifications")}</span>
						</TabsTrigger>
					</TabsList>
				</div>

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
									<TableRow className="border-white/10 hover:bg-transparent">
										<TableHead className="text-white/60">{t("apiKeys.colName")}</TableHead>
										<TableHead className="text-white/60">{t("apiKeys.colExchange")}</TableHead>
										<TableHead className="text-white/60">{t("apiKeys.colPrefix")}</TableHead>
										<TableHead className="text-white/60">{t("apiKeys.colStatus")}</TableHead>
										<TableHead className="text-center text-white/60">{t("apiKeys.colActive")}</TableHead>
										<TableHead className="text-white/60">{t("apiKeys.colCreated")}</TableHead>
										<TableHead className="text-right text-white/60">
											{t("common:actions")}
										</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{config.apiKeys.map((key) => {
										const isCurrentlyTesting = testingApiKeyId === key.id;
										const isCurrentlyDeleting =
											isDeletingApiKey && apiKeyToDelete?.id === key.id;
										const isCurrentlyToggling = togglingApiKeyId === key.id;
										const isKeyActive =
											key.isActive ??
											(key as unknown as { is_active?: boolean }).is_active ??
											true;

										const baseKey = normalizeExchangeKey(key.exchange);
										const isTestnet = key.exchange?.toLowerCase().includes("testnet");
										const exchangeLabel =
											baseKey && exchangeMeta[baseKey]
												? exchangeMeta[baseKey].label
												: (key.exchange || t("common:na"));

										let statusBadge;
										switch (key.status) {
											case "valid":
												statusBadge = (
													<Badge className="bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30 shadow-[0_0_10px_-2px_rgba(16,185,129,0.3)]">
														<BadgeCheck className="w-3 h-3 mr-1" />
														{t("apiKeys.statusValid")}
													</Badge>
												);
												break;
											case "invalid":
												statusBadge = (
													<Badge variant="destructive" className="bg-rose-500/20 text-rose-300 border border-rose-500/30">
														<BadgeX className="w-3 h-3 mr-1" />
														{t("apiKeys.statusInvalid")}
													</Badge>
												);
												break;
											case "testing":
												statusBadge = (
													<Badge variant="secondary" className="bg-cyan/15 text-cyan border border-cyan/30">
														<SpinnerIcon className="w-3 h-3 mr-1 animate-spin" />
														{t("apiKeys.statusTesting")}
													</Badge>
												);
												break;
											default:
												statusBadge = (
													<Badge variant="outline" className="border-white/10 text-white/50 bg-white/[0.02]">
														<BadgeHelp className="w-3 h-3 mr-1" />
														{t("apiKeys.statusUntested")}
													</Badge>
												);
												break;
										}
										return (
											<TableRow
												key={key.id}
												className={`border-white/5 transition-opacity duration-200 ${
													!isKeyActive ? "opacity-60 hover:opacity-90" : ""
												}`}
											>
												<TableCell className="font-medium text-white/90">
													{key.name}
												</TableCell>
												<TableCell>
													<div className="flex items-center gap-2.5">
														<ExchangeBadge exchange={key.exchange} size="sm" />
														<div className="flex items-center gap-1.5 flex-wrap">
															<span className="font-medium text-white/90">
																{exchangeLabel}
															</span>
															{isTestnet && (
																<span className="px-1.5 py-0.5 text-[10px] font-semibold tracking-wider uppercase rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
																	Testnet
																</span>
															)}
														</div>
													</div>
												</TableCell>
												<TableCell className="font-mono text-xs text-white/70">
													{key.keyPrefix}
												</TableCell>
												<TableCell>
													<div className="flex items-center gap-1.5 flex-wrap">
														{statusBadge}
														{!isKeyActive && (
															<Badge
																variant="outline"
																className="border-amber-500/25 text-amber-400/90 bg-amber-500/10 text-[11px] py-0 px-1.5 font-normal"
															>
																<PowerOff className="w-2.5 h-2.5 mr-1 text-amber-400/70" />
																{t("apiKeys.statusDisabled")}
															</Badge>
														)}
													</div>
												</TableCell>
												<TableCell className="text-center">
													<div className="flex items-center justify-center gap-1.5">
														<Switch
															checked={isKeyActive}
															disabled={
																isCurrentlyToggling || isCurrentlyDeleting
															}
															onCheckedChange={(checked) =>
																handleToggleApiKey(key.id, checked)
															}
															className="data-[state=checked]:bg-cyan"
															aria-label={
																isKeyActive
																	? t("apiKeys.statusValid")
																	: t("apiKeys.statusDisabled")
															}
														/>
														{isCurrentlyToggling && (
															<SpinnerIcon className="w-3.5 h-3.5 animate-spin text-cyan" />
														)}
													</div>
												</TableCell>
												<TableCell className="text-xs text-white/60">
													{format(new Date(key.createdAt), "PP")}
												</TableCell>
												<TableCell className="text-right space-x-1">
													<Button
														variant="outline"
														size="sm"
														className="h-8 rounded-lg border-white/10 bg-white/[0.03] text-white/70 hover:bg-white/[0.08] hover:text-white transition-colors"
														onClick={() => handleTestApiKey(key.id)}
														disabled={
															isCurrentlyTesting ||
															isCurrentlyDeleting ||
															isCurrentlyToggling
														}
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
														className="h-8 w-8 rounded-lg text-destructive hover:text-destructive hover:bg-rose-500/10 transition-colors"
														onClick={() => openDeleteApiKeyModal(key)}
														disabled={
															isCurrentlyDeleting ||
															isCurrentlyTesting ||
															isCurrentlyToggling
														}
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

				{/* === AI Agents (MCP) Tab === */}
				<TabsContent value="mcp" className="mt-6">
					<McpSection />
				</TabsContent>



				{/* === Risk Management Tab === */}
				<TabsContent value="risk-management" className="mt-6">
					<Tabs defaultValue="live-trading" className="w-full">
						<div className="flex items-center overflow-x-auto pb-1 mb-6">
							<TabsList className="inline-flex h-auto w-auto items-center justify-start rounded-xl bg-white/[0.04] border border-white/5 p-1 gap-1 shadow-inner backdrop-blur-md">
								<TabsTrigger
									value="live-trading"
									className="group relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs sm:text-sm font-medium transition-all text-white/50 hover:text-white/80 hover:bg-white/[0.03] data-[state=active]:bg-white/[0.08] data-[state=active]:text-white data-[state=active]:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] data-[state=active]:border data-[state=active]:border-white/10 whitespace-nowrap"
								>
									<Radio className="w-3.5 h-3.5 text-cyan/60 group-hover:text-cyan group-data-[state=active]:text-cyan group-data-[state=active]:drop-shadow-[0_0_8px_rgba(0,212,255,0.85)] transition-all shrink-0" />
									<span>Live Trading</span>
								</TabsTrigger>
								<TabsTrigger
									value="backtesting"
									className="group relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs sm:text-sm font-medium transition-all text-white/50 hover:text-white/80 hover:bg-white/[0.03] data-[state=active]:bg-white/[0.08] data-[state=active]:text-white data-[state=active]:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] data-[state=active]:border data-[state=active]:border-white/10 whitespace-nowrap"
								>
									<FlaskConical className="w-3.5 h-3.5 text-cyan/60 group-hover:text-cyan group-data-[state=active]:text-cyan group-data-[state=active]:drop-shadow-[0_0_8px_rgba(0,212,255,0.85)] transition-all shrink-0" />
									<span>Backtesting</span>
								</TabsTrigger>
							</TabsList>
						</div>
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

							<div className="pt-4 border-t border-border space-y-4">
								<div className="flex items-start space-x-3">
									<Switch
										id="share-telemetry"
										checked={shareTelemetry}
										onCheckedChange={setShareTelemetry}
										className="mt-1"
									/>
									<div className="space-y-1">
										<Label htmlFor="share-telemetry" className="font-semibold text-base">
											{"Join Swarm Intelligence & Trade Mining"}
										</Label>
										<p className="text-xs text-muted-foreground max-w-xl">
											{"Required while Trade Mining is active: your closed trades (symbol, entry/exit prices, volume, PnL, duration, order IDs) and strategy parameters (blocks, NATR/ADX) are shared with the Central Hub, linked to your node's wallet address and exchange UID. Your exchange API keys, passwords and asset balances are never transmitted. Deactivate Trade Mining to turn this off."}
										</p>
									</div>
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
																disabled={
																	isGettingBindUrl || isWaitingTelegramBinding
																}
																className="h-8 text-xs"
															>
																{isGettingBindUrl ||
																isWaitingTelegramBinding ? (
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
														disabled={
															isGettingBindUrl || isWaitingTelegramBinding
														}
														className="w-full sm:w-fit py-5 px-6"
													>
														{isGettingBindUrl ||
														isWaitingTelegramBinding ? (
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
											{isWaitingTelegramBinding && (
												<p className="text-xs text-muted-foreground leading-relaxed flex items-center gap-2">
													<SpinnerIcon className="h-3 w-3 animate-spin" />
													{t("notifications.telegramBindingWaitingDesc")}
												</p>
											)}
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
			loading={isDeletingApiKey}
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
