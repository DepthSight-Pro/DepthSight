// pwa/components/LaunchStrategyModal.tsx

import type React from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../contexts/AuthContext";
import type { DisplayStrategy } from "../types";

interface LaunchStrategyModalProps {
	isOpen: boolean;
	onClose: () => void;
	onSubmit: (details: LaunchFormData) => void;
	strategy: DisplayStrategy | null;
}

export interface LaunchFormData {
	mode: "live" | "paper";
	symbolSelectionMode: "STATIC" | "DYNAMIC";
	symbols?: string;

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

const LaunchStrategyModal: React.FC<LaunchStrategyModalProps> = ({
	isOpen,
	onClose,
	onSubmit,
	strategy,
}) => {
	const { t } = useTranslation("pwa-common");
	const { user } = useAuth();
	const isAdmin = user?.role === "admin";
	const isPro = user?.plan === "pro";
	const canUseOracle = isAdmin || isPro; // Oracle is available to admins and Pro users

	const [mode, setMode] = useState<"paper" | "live">("paper");
	const [symbolSelectionMode, setSymbolSelectionMode] = useState<
		"STATIC" | "DYNAMIC"
	>("DYNAMIC");
	const [symbols, setSymbols] = useState("");

	// Dynamic settings
	const [dynamicMode, setDynamicMode] = useState<
		"DYNAMIC_NATR" | "DYNAMIC_ORACLE"
	>("DYNAMIC_NATR");
	const [minNatr, setMinNatr] = useState(1.5);
	const [oracleRegime, setOracleRegime] = useState("1");
	const [oracleConfidence, setOracleConfidence] = useState(95);
	const [maxConcurrentSymbols, setMaxConcurrentSymbols] = useState(5);

	// ML & Regime settings
	const [useMlConfirmation, setUseMlConfirmation] = useState(false);
	const [breakevenOnRegimeChange, setBreakevenOnRegimeChange] = useState(false);

	useEffect(() => {
		const timer = setTimeout(() => {
			if (strategy) {
				const currentSymbols = strategy.symbols?.join(", ") || "";
				setSymbols(currentSymbols);

				if (strategy.symbol_selection_mode) {
					setSymbolSelectionMode(
						strategy.symbol_selection_mode as "STATIC" | "DYNAMIC",
					);
				}

				// Load dynamic settings from strategy config
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				const configData = strategy.config_data as Record<string, any>;
				if (configData) {
					// Determine dynamic mode
					if (configData.natr_settings) {
						setDynamicMode("DYNAMIC_NATR");
						setMinNatr(configData.natr_settings.min_natr || 1.5);
					} else if (canUseOracle) {
						setDynamicMode("DYNAMIC_ORACLE");
					}

					if (configData.oracle_settings) {
						setOracleRegime(
							configData.oracle_settings.regime?.toString() || "1",
						);
						setOracleConfidence(configData.oracle_settings.confidence || 95);
					}

					setMaxConcurrentSymbols(configData.max_concurrent_symbols || 5);
					setUseMlConfirmation(configData.use_ml_confirmation ?? false);
					setBreakevenOnRegimeChange(
						configData.breakeven_on_regime_change ?? false,
					);
				}
			}
		}, 0);
		return () => clearTimeout(timer);
	}, [strategy, canUseOracle]);

	if (!isOpen) return null;

	const handleSubmit = () => {
		if (symbolSelectionMode === "STATIC" && !symbols.trim()) {
			alert(t("launchStrategyModal.fillSymbolsForStatic"));
			return;
		}

		onSubmit({
			mode,
			symbolSelectionMode,
			symbols: symbolSelectionMode === "STATIC" ? symbols : undefined,
			dynamicMode,
			minNatr,
			oracleRegime,
			oracleConfidence,
			maxConcurrentSymbols,
			useMlConfirmation,
			breakevenOnRegimeChange,
		});
	};

	return (
		<>
			<div
				className={`fixed inset-0 bg-black/50 z-40 transition-opacity duration-300 ${
					isOpen
						? "opacity-100 pointer-events-auto"
						: "opacity-0 pointer-events-none"
				}`}
				onClick={onClose}
			></div>
			<div
				className={`fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[90%] max-w-md max-h-[85vh] overflow-y-auto bg-[hsl(var(--card))] rounded-3xl shadow-[-4px_0_20px_rgba(0,0,0,0.1)] p-6 z-50 transition-all duration-300 ease-out ${
					isOpen ? "scale-100 opacity-100" : "scale-95 opacity-0"
				}`}
			>
				<h2 className="text-xl font-medium mb-1 text-[hsl(var(--card-foreground))]">
					{t("launchStrategyModal.launchStrategy")}
				</h2>
				<p className="text-sm text-[hsl(var(--muted-foreground))] mb-5">
					{strategy?.name}
				</p>

				{/* Trading Mode */}
				<div className="mb-5">
					<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block font-medium">
						{t("launchStrategyModal.tradingMode")}
					</label>
					<div className="space-y-2">
						<RadioOption
							selected={mode === "paper"}
							onClick={() => setMode("paper")}
							title={t("launchStrategyModal.paperTrading")}
							description={t("launchStrategyModal.paperTradingDescription")}
						/>
						<RadioOption
							selected={mode === "live"}
							onClick={() => setMode("live")}
							title={t("launchStrategyModal.liveTrading")}
							description={t("launchStrategyModal.liveTradingDescription")}
							highlight={true}
						/>
					</div>
				</div>

				{/* Symbol Selection Mode */}
				<div className="mb-5">
					<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block font-medium">
						{t("launchStrategyModal.symbolSelection")}
					</label>
					<div className="space-y-2">
						<RadioOption
							selected={symbolSelectionMode === "DYNAMIC"}
							onClick={() => setSymbolSelectionMode("DYNAMIC")}
							title={t("launchStrategyModal.dynamicFromScreener")}
							description={t(
								"launchStrategyModal.dynamicFromScreenerDescription",
							)}
						/>
						<RadioOption
							selected={symbolSelectionMode === "STATIC"}
							onClick={() => setSymbolSelectionMode("STATIC")}
							title={t("launchStrategyModal.staticManualList")}
							description={t("launchStrategyModal.staticManualListDescription")}
						/>
					</div>
				</div>

				{/* DYNAMIC MODE SETTINGS */}
				{symbolSelectionMode === "DYNAMIC" && (
					<div className="mb-5 p-4 bg-[hsl(var(--secondary)/0.3)] rounded-lg space-y-4">
						<label className="text-sm font-medium text-[hsl(var(--card-foreground))] block">
							{t(
								"launchStrategyModal.dynamicSettings",
								"Dynamic Selection Settings",
							)}
						</label>

						{/* Dynamic Sub-Mode Selection */}
						<select
							className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] outline-none transition-all focus:border-[hsl(var(--primary))]"
							value={dynamicMode}
							onChange={(e) =>
								setDynamicMode(
									e.target.value as "DYNAMIC_NATR" | "DYNAMIC_ORACLE",
								)
							}
						>
							{canUseOracle && (
								<option value="DYNAMIC_ORACLE">
									{t("launchStrategyModal.oracleFilter", "Oracle Filter")}
								</option>
							)}
							<option value="DYNAMIC_NATR">
								{t(
									"launchStrategyModal.lowVolatilityNatr",
									"Low Volatility (NATR)",
								)}
							</option>
						</select>

						{/* ORACLE SPECIFIC */}
						{dynamicMode === "DYNAMIC_ORACLE" && canUseOracle && (
							<>
								<div>
									<label className="text-xs text-[hsl(var(--muted-foreground))] mb-1 block">
										{t("launchStrategyModal.requiredRegime", "Required Regime")}
									</label>
									<select
										className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] outline-none"
										value={oracleRegime}
										onChange={(e) => setOracleRegime(e.target.value)}
									>
										<option value="0">
											{t("launchStrategyModal.oracleRegimeParanoiaFull")}
										</option>
										<option value="1">
											{t("launchStrategyModal.oracleRegimeAmnesiaFull")}
										</option>
										<option value="2">
											{t("launchStrategyModal.oracleRegimeSchizophreniaFull")}
										</option>
									</select>
								</div>
								<div>
									<div className="flex justify-between mb-1">
										<label className="text-xs text-[hsl(var(--muted-foreground))]">
											{t(
												"launchStrategyModal.minConfidence",
												"Min Confidence (%)",
											)}
										</label>
										<span className="text-xs text-[hsl(var(--muted-foreground))]">
											{oracleConfidence}%
										</span>
									</div>
									<input
										type="range"
										min="0"
										max="100"
										value={oracleConfidence}
										onChange={(e) =>
											setOracleConfidence(parseInt(e.target.value, 10))
										}
										className="w-full accent-[hsl(var(--primary))]"
									/>
								</div>
							</>
						)}

						{/* NATR SPECIFIC */}
						{dynamicMode === "DYNAMIC_NATR" && (
							<div>
								<label className="text-xs text-[hsl(var(--muted-foreground))] mb-1 block">
									{t("launchStrategyModal.minNatr", "Min NATR")}
								</label>
								<input
									type="number"
									step="0.1"
									className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] outline-none"
									value={minNatr}
									onChange={(e) => setMinNatr(parseFloat(e.target.value))}
								/>
							</div>
						)}

						{/* Max Concurrent */}
						<div className="border-t border-[hsl(var(--border))] pt-3">
							<label className="text-xs text-[hsl(var(--muted-foreground))] mb-1 block">
								{t(
									"launchStrategyModal.maxConcurrentSymbols",
									"Max Concurrent Symbols",
								)}
							</label>
							<input
								type="number"
								className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] outline-none"
								value={maxConcurrentSymbols}
								onChange={(e) =>
									setMaxConcurrentSymbols(parseInt(e.target.value, 10))
								}
							/>
						</div>
					</div>
				)}

				{/* Symbols Input (only for STATIC mode) */}
				{symbolSelectionMode === "STATIC" && (
					<div className="mb-5">
						<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
							{t("launchStrategyModal.symbolList")}
						</label>
						<input
							type="text"
							className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
							placeholder={t("launchStrategyModal.symbolPlaceholder")}
							value={symbols}
							onChange={(e) => setSymbols(e.target.value)}
						/>
						<p className="text-xs text-[hsl(var(--muted-foreground))] mt-1">
							{t("launchStrategyModal.separateByCommas")}
						</p>
					</div>
				)}

				{/* Advanced Settings: ML & Regime */}
				<div className="mb-5 p-4 bg-[hsl(var(--secondary)/0.2)] rounded-lg space-y-3">
					<label className="text-sm font-medium text-[hsl(var(--card-foreground))] block">
						{t("launchStrategyModal.advancedSettings", "Advanced Settings")}
					</label>

					<CheckboxOption
						checked={useMlConfirmation}
						onChange={setUseMlConfirmation}
						label={t(
							"launchStrategyModal.enableMlConfirmation",
							"Enable ML Confirmation",
						)}
					/>

					{canUseOracle && (
						<CheckboxOption
							checked={breakevenOnRegimeChange}
							onChange={setBreakevenOnRegimeChange}
							label={t(
								"launchStrategyModal.breakevenOnRegimeChange",
								"Breakeven on Regime Change",
							)}
						/>
					)}
				</div>

				<div className="flex gap-3 mt-6">
					<button
						className="flex-1 py-3 rounded-lg border-none text-sm font-medium bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] transition hover:opacity-90"
						onClick={onClose}
					>
						{t("buttons.cancel")}
					</button>
					<button
						className="flex-1 py-3 rounded-lg border-none text-sm font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90"
						onClick={handleSubmit}
					>
						{t("launchStrategyModal.launchStrategy")}
					</button>
				</div>
			</div>
		</>
	);
};

// Radio Button Component
const RadioOption = ({
	selected,
	onClick,
	title,
	description,
	highlight = false,
}: {
	selected: boolean;
	onClick: () => void;
	title: string;
	description: string;
	highlight?: boolean;
}) => (
	<div
		className={`p-3 border rounded-lg cursor-pointer transition-all ${
			selected
				? "bg-[hsl(var(--primary)/0.1)] border-[hsl(var(--primary))]"
				: "bg-[hsl(var(--secondary))] border-[hsl(var(--border))]"
		}`}
		onClick={onClick}
	>
		<div className="flex items-center gap-3">
			<div
				className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
					selected
						? "border-[hsl(var(--primary))]"
						: "border-[hsl(var(--border))]"
				}`}
			>
				{selected && (
					<div className="w-2 h-2 bg-[hsl(var(--primary))] rounded-full"></div>
				)}
			</div>
			<div className="flex-1">
				<div
					className={`font-medium ${highlight ? "text-orange-600 dark:text-orange-400" : "text-[hsl(var(--card-foreground))]"}`}
				>
					{title}
				</div>
				<div className="text-xs text-[hsl(var(--muted-foreground))]">
					{description}
				</div>
			</div>
		</div>
	</div>
);

// Checkbox Component
const CheckboxOption = ({
	checked,
	onChange,
	label,
}: {
	checked: boolean;
	onChange: (checked: boolean) => void;
	label: string;
}) => (
	<div
		className="flex items-center gap-3 cursor-pointer"
		onClick={() => onChange(!checked)}
	>
		<div
			className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-all ${
				checked
					? "bg-[hsl(var(--primary))] border-[hsl(var(--primary))]"
					: "bg-transparent border-[hsl(var(--border))]"
			}`}
		>
			{checked && (
				<svg
					className="w-3 h-3 text-white"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
				>
					<path
						strokeLinecap="round"
						strokeLinejoin="round"
						strokeWidth={3}
						d="M5 13l4 4L19 7"
					/>
				</svg>
			)}
		</div>
		<span className="text-sm text-[hsl(var(--card-foreground))]">{label}</span>
	</div>
);

export default LaunchStrategyModal;
