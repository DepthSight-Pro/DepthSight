// pwa/screens/SettingsScreen.tsx

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import SettingsSection from "../components/SettingsSection";
import Tabs from "../components/Tabs";
import { Logo } from "../components/ui/logo";
import { api } from "../services/api";
import type {
	AppConfig,
	BacktestRiskManagementSettings,
	RiskManagementSettings,
} from "../types";

const SettingsScreen = () => {
	const [config, setConfig] = useState<AppConfig | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const { t } = useTranslation("pwa-common");
	const [activeTab, setActiveTab] = useState(0);

	// State for Risk Management
	const [riskManagement, setRiskManagement] = useState<
		Partial<RiskManagementSettings>
	>({});
	const [backtestRiskManagement, setBacktestRiskManagement] = useState<
		Partial<BacktestRiskManagementSettings>
	>({});

	useEffect(() => {
		const fetchConfig = async () => {
			try {
				setLoading(true);
				const configData = await api.getConfig();
				setConfig(configData);
				setRiskManagement(configData.riskManagement || {});
				setBacktestRiskManagement(configData.backtestRiskManagement || {});
			} catch (err) {
				setError(err instanceof Error ? err.message : String(err));
			} finally {
				setLoading(false);
			}
		};

		fetchConfig();
	}, []);

	const handleUpdateConfig = async (
		section: "riskManagement" | "backtestRiskManagement",
	) => {
		try {
			const data =
				section === "riskManagement" ? riskManagement : backtestRiskManagement;
			const updatedConfig = await api.updateConfig({ [section]: data });
			setConfig(updatedConfig);
			if (section === "riskManagement") {
				setRiskManagement(updatedConfig.riskManagement || {});
			} else {
				setBacktestRiskManagement(updatedConfig.backtestRiskManagement || {});
			}
			// Optionally show a success message
		} catch {
			// Optionally show an error message
		}
	};

	const handleRiskManagementChange = <K extends keyof RiskManagementSettings>(
		field: K,
		value: RiskManagementSettings[K],
	) => {
		setRiskManagement((prev) => ({ ...prev, [field]: value }));
	};

	const handleBacktestRiskManagementChange = <
		K extends keyof BacktestRiskManagementSettings,
	>(
		field: K,
		value: BacktestRiskManagementSettings[K],
	) => {
		setBacktestRiskManagement((prev) => ({ ...prev, [field]: value }));
	};

	const renderInputField = (
		label: string,
		value: number | undefined,
		setter: (val: number) => void,
		description?: string,
	) => (
		<div className="space-y-2">
			<label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
				{label}
			</label>
			<input
				type="number"
				value={value || ""}
				onChange={(e) => setter(parseFloat(e.target.value))}
				className="w-full p-2 border rounded mt-1 bg-white dark:bg-gray-700 dark:border-gray-600 dark:text-white"
			/>
			{description && (
				<p className="text-xs text-gray-500 dark:text-gray-400">
					{description}
				</p>
			)}
		</div>
	);

	const renderSwitchField = (
		label: string,
		value: boolean,
		setter: (val: boolean) => void,
	) => (
		<div className="flex items-center">
			<input
				type="checkbox"
				checked={value || false}
				onChange={(e) => setter(e.target.checked)}
				className="h-4 w-4 text-blue-600 border-gray-300 rounded bg-white dark:bg-gray-700 dark:border-gray-600"
			/>
			<label className="ml-2 block text-sm text-gray-900 dark:text-gray-200">
				{label}
			</label>
		</div>
	);

	const liveTradingContent = (
		<SettingsSection
			title={t("settings.liveTradingRiskManagement")}
			description={t("settings.riskManagementDescription")}
			footerActions={
				<button
					onClick={() => handleUpdateConfig("riskManagement")}
					className="bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] px-4 py-2 rounded-lg hover:opacity-90 transition"
				>
					{t("buttons.save")}
				</button>
			}
		>
			<div className="space-y-4">
				{renderInputField(
					t("settings.maxDrawdown"),
					riskManagement.maxDrawdown,
					(val) => handleRiskManagementChange("maxDrawdown", val),
				)}
				{renderInputField(
					t("settings.maxConsecutiveLosses"),
					riskManagement.maxConsecutiveLosses,
					(val) => handleRiskManagementChange("maxConsecutiveLosses", val),
				)}
				{renderInputField(
					t("settings.maxConcurrentTrades"),
					riskManagement.maxConcurrentTrades,
					(val) => handleRiskManagementChange("maxConcurrentTrades", val),
				)}
				{renderSwitchField(
					t("settings.enableStopLoss"),
					riskManagement.stopLossEnabled || false,
					(val) => handleRiskManagementChange("stopLossEnabled", val),
				)}
				{riskManagement.stopLossEnabled &&
					renderInputField(
						t("settings.defaultStopLossPercent"),
						riskManagement.defaultStopLossPercent,
						(val) => handleRiskManagementChange("defaultStopLossPercent", val),
					)}
				{renderInputField(
					t("settings.maxStopDistancePercent"),
					riskManagement.maxStopDistancePct,
					(val) => handleRiskManagementChange("maxStopDistancePct", val),
				)}
				<hr className="border-[hsl(var(--border))]" />
				<h3 className="text-lg font-semibold text-[hsl(var(--card-foreground))]">
					{t("settings.adaptiveRiskManagement")}
				</h3>
				{renderSwitchField(
					t("settings.enableAdaptiveRM"),
					riskManagement.strategySymbolAdjustmentEnabled || false,
					(val) =>
						handleRiskManagementChange("strategySymbolAdjustmentEnabled", val),
				)}
				{riskManagement.strategySymbolAdjustmentEnabled && (
					<div className="pl-4 space-y-4 border-l-2 ml-2 pt-4 border-[hsl(var(--border))]">
						{renderInputField(
							t("settings.windowSize"),
							riskManagement.strategySymbolWindowSize,
							(val) =>
								handleRiskManagementChange("strategySymbolWindowSize", val),
						)}
						{renderInputField(
							t("settings.minTrades"),
							riskManagement.strategySymbolMinTradesForAssessment,
							(val) =>
								handleRiskManagementChange(
									"strategySymbolMinTradesForAssessment",
									val,
								),
						)}
						{renderInputField(
							t("settings.pnlThreshold"),
							riskManagement.strategySymbolPnlThresholdPct,
							(val) =>
								handleRiskManagementChange(
									"strategySymbolPnlThresholdPct",
									val,
								),
						)}
						{renderInputField(
							t("settings.winRateThreshold"),
							riskManagement.strategySymbolWinRateThresholdPct,
							(val) =>
								handleRiskManagementChange(
									"strategySymbolWinRateThresholdPct",
									val,
								),
						)}
						{renderInputField(
							t("settings.maxConsecutiveLosses"),
							riskManagement.strategySymbolMaxConsecutiveLosses,
							(val) =>
								handleRiskManagementChange(
									"strategySymbolMaxConsecutiveLosses",
									val,
								),
						)}
						{renderInputField(
							t("settings.recoveryWins"),
							riskManagement.strategySymbolRecoveryConsecutiveWins,
							(val) =>
								handleRiskManagementChange(
									"strategySymbolRecoveryConsecutiveWins",
									val,
								),
						)}
						{renderInputField(
							t("settings.recoveryPnl"),
							riskManagement.strategySymbolRecoveryPnlThresholdPct,
							(val) =>
								handleRiskManagementChange(
									"strategySymbolRecoveryPnlThresholdPct",
									val,
								),
						)}
						{renderInputField(
							t("settings.cooldownSeconds"),
							riskManagement.strategySymbolCooldownAfterPenaltySeconds,
							(val) =>
								handleRiskManagementChange(
									"strategySymbolCooldownAfterPenaltySeconds",
									val,
								),
						)}
					</div>
				)}
			</div>
		</SettingsSection>
	);

	const backtestingContent = (
		<SettingsSection
			title={t("settings.backtestingRiskManagement")}
			description={t("settings.backtestingRiskManagementDescription")}
			footerActions={
				<button
					onClick={() => handleUpdateConfig("backtestRiskManagement")}
					className="bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] px-4 py-2 rounded-lg hover:opacity-90 transition"
				>
					{t("buttons.save")}
				</button>
			}
		>
			<div className="space-y-4">
				{renderInputField(
					t("settings.maxDrawdown"),
					backtestRiskManagement.maxDrawdown,
					(val) => handleBacktestRiskManagementChange("maxDrawdown", val),
				)}
				{renderInputField(
					t("settings.dailyMaxLossPercent"),
					backtestRiskManagement.dailyMaxLossPercent,
					(val) =>
						handleBacktestRiskManagementChange("dailyMaxLossPercent", val),
				)}
				{renderInputField(
					t("settings.maxConsecutiveLosses"),
					backtestRiskManagement.maxConsecutiveLosses,
					(val) =>
						handleBacktestRiskManagementChange("maxConsecutiveLosses", val),
				)}
				{renderInputField(
					t("settings.maxConcurrentTrades"),
					backtestRiskManagement.maxConcurrentTrades,
					(val) =>
						handleBacktestRiskManagementChange("maxConcurrentTrades", val),
				)}
				{renderSwitchField(
					t("settings.enableStopLoss"),
					backtestRiskManagement.stopLossEnabled || false,
					(val) => handleBacktestRiskManagementChange("stopLossEnabled", val),
				)}
				{backtestRiskManagement.stopLossEnabled &&
					renderInputField(
						t("settings.defaultStopLossPercent"),
						backtestRiskManagement.defaultStopLossPercent,
						(val) =>
							handleBacktestRiskManagementChange("defaultStopLossPercent", val),
					)}
				{renderInputField(
					t("settings.maxStopDistancePercent"),
					backtestRiskManagement.maxStopDistancePct,
					(val) =>
						handleBacktestRiskManagementChange("maxStopDistancePct", val),
				)}
				<hr className="border-[hsl(var(--border))]" />
				{renderInputField(
					t("settings.riskPerTradePercent"),
					backtestRiskManagement.riskPerTradePercent,
					(val) =>
						handleBacktestRiskManagementChange("riskPerTradePercent", val),
				)}
				{renderInputField(
					t("settings.leverage"),
					backtestRiskManagement.leverage,
					(val) => handleBacktestRiskManagementChange("leverage", val),
				)}
				<hr className="border-[hsl(var(--border))]" />
				<h3 className="text-lg font-semibold text-[hsl(var(--card-foreground))]">
					{t("settings.adaptiveRiskManagement")}
				</h3>
				{renderSwitchField(
					t("settings.enableAdaptiveRMForBacktest"),
					backtestRiskManagement.strategySymbolAdjustmentEnabledForBacktest ||
						false,
					(val) =>
						handleBacktestRiskManagementChange(
							"strategySymbolAdjustmentEnabledForBacktest",
							val,
						),
				)}
			</div>
		</SettingsSection>
	);

	if (loading || !config) {
		return (
			<div className="flex justify-center items-center min-h-screen">
				<Logo size="lg" className="mb-8 animate-pulse" />
			</div>
		);
	}

	if (error) {
		return (
			<div className="p-4 text-red-500">
				{t("profile.error")}
				{error}
			</div>
		);
	}

	return (
		<div className="p-4 space-y-4">
			<h1 className="text-2xl font-bold dark:text-white">
				{t("settings.riskManagement")}
			</h1>
			<Tabs
				activeTab={activeTab}
				setActiveTab={setActiveTab}
				tabs={[
					{ label: t("settings.liveTrading"), content: liveTradingContent },
					{ label: t("settings.backtesting"), content: backtestingContent },
				]}
			/>
		</div>
	);
};

export default SettingsScreen;
