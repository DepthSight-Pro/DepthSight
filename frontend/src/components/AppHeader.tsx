// src/components/AppHeader.tsx

import { FlaskConical, Radio, Sparkles } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { AccountSelector } from "@/components/layout/AccountSelector";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import {
	useConfig,
	useMultiAccountBalances,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAccountStore } from "@/stores/accountStore";
import { useAiCopilotStore } from "@/stores/aiCopilotStore";
import type { AccountBalance } from "@/types/api";
import { UserNav } from "./UserNav";

export const AppHeader = () => {
	const { mode, setMode } = usePortfolioMode();
	const { data: config, isSuccess: isConfigSuccess } = useConfig();
	const {
		selectedApiKeyId,
		selectedMarketType,
		setSelectedApiKeyId,
		setSelectedMarketType,
	} = useAccountStore();
	const { data: balances } = useMultiAccountBalances(selectedMarketType);
	const { t } = useTranslation(["common", "account"]);
	const { widgetState, setWidgetState } = useAiCopilotStore();

	const apiKeys = config?.apiKeys;
	const hasApiKeys = Boolean(apiKeys?.length);

	// Filter API keys for the selector (prioritize active keys, fallback to all valid keys)
	const activeApiKeys = useMemo(() => {
		if (!apiKeys || apiKeys.length === 0) return [];
		const active = apiKeys.filter((key) => key.isActive && key.status !== "invalid");
		if (active.length > 0) return active;
		return apiKeys.filter((key) => key.status !== "invalid");
	}, [apiKeys]);

	// Transform balances array to Record<number, AccountBalance>
	const balanceAccounts = balances?.accounts;
	const balancesRecord = useMemo(() => {
		if (!balanceAccounts) return {};
		return balanceAccounts.reduce(
			(acc, bal) => {
				const existing = acc[bal.apiKeyId];
				if (existing) {
					if (bal.exchange === "bybit" || bal.exchange === "okx") {
						if (bal.marketType === "futures_usdtm") {
							acc[bal.apiKeyId] = {
								...bal,
								assets: [...(existing.assets ?? []), ...(bal.assets ?? [])],
							};
						} else {
							acc[bal.apiKeyId] = {
								...existing,
								assets: [...(existing.assets ?? []), ...(bal.assets ?? [])],
							};
						}
					} else {
						acc[bal.apiKeyId] = {
							...existing,
							balance: existing.balance + bal.balance,
							availableBalance: existing.availableBalance + bal.availableBalance,
							unrealizedPnl: existing.unrealizedPnl + bal.unrealizedPnl,
							marginUsed: existing.marginUsed + bal.marginUsed,
							totalEquity: existing.totalEquity + bal.totalEquity,
							assets: [...(existing.assets ?? []), ...(bal.assets ?? [])],
						};
					}
				} else {
					acc[bal.apiKeyId] = bal;
				}
				return acc;
			},
			{} as Record<number, AccountBalance>,
		);
	}, [balanceAccounts]);

	useEffect(() => {
		if (isConfigSuccess && !hasApiKeys && mode === "live") {
			setMode("paper");
		}
	}, [hasApiKeys, isConfigSuccess, mode, setMode]);

	const handleModeChange = (targetMode: "live" | "paper") => {
		if (targetMode === "live") {
			if (hasApiKeys) {
				setMode("live");
			} else {
				toast.error(t("common:errors.connectApiKeys"));
			}
		} else if (targetMode === "paper") {
			setMode("paper");
		}
	};

	return (
		<header className="relative z-20 flex h-12 sm:h-14 shrink-0 items-center justify-between gap-1.5 sm:gap-3 border-b border-white/5 bg-obsidian/75 px-2 sm:px-4 backdrop-blur-xl text-white">
			{mode === "live" && (
				<div className="pointer-events-none absolute inset-x-0 bottom-0 z-30 h-[1.5px] bg-gradient-to-r from-transparent via-rose-500/90 to-transparent shadow-[0_0_12px_rgba(244,63,94,0.9)]" />
			)}
			{/* Left section: Market scope switcher */}
			<div className="flex items-center gap-1 sm:gap-2.5 min-w-0 shrink">
				<ToggleGroup
					type="single"
					size="sm"
					value={selectedMarketType}
					onValueChange={(value) => {
						if (
							value === "all" ||
							value === "futures_usdtm" ||
							value === "spot"
						) {
							setSelectedMarketType(value);
						}
					}}
					className="bg-white/[0.03] border border-white/5 rounded-lg p-0.5 h-7 sm:h-8 gap-0.5"
				>
					<ToggleGroupItem
						value="all"
						aria-label="All markets"
						className="h-6 sm:h-7 px-1.5 sm:px-2.5 text-[10px] sm:text-[11px] font-medium text-white/60 data-[state=on]:bg-white/[0.08] data-[state=on]:text-white rounded-md"
					>
						All
					</ToggleGroupItem>
					<ToggleGroupItem
						value="futures_usdtm"
						aria-label="Futures market"
						className="h-6 sm:h-7 px-1.5 sm:px-2.5 text-[10px] sm:text-[11px] font-medium text-white/60 data-[state=on]:bg-white/[0.08] data-[state=on]:text-white rounded-md"
					>
						<span className="hidden sm:inline">Futures</span>
						<span className="sm:hidden">Fut</span>
					</ToggleGroupItem>
					<ToggleGroupItem
						value="spot"
						aria-label="Spot market"
						className="h-6 sm:h-7 px-1.5 sm:px-2.5 text-[10px] sm:text-[11px] font-medium text-white/60 data-[state=on]:bg-white/[0.08] data-[state=on]:text-white rounded-md"
					>
						Spot
					</ToggleGroupItem>
				</ToggleGroup>
			</div>

			{/* Right section: mode toggle, account/key switcher, co-pilot, user */}
			<div className="flex items-center gap-1 sm:gap-2.5 shrink-0">
				{/* Neon Sliding Live / Paper Mode Toggle */}
				<div className="relative flex h-7 sm:h-8 items-center rounded-lg border border-white/8 bg-white/[0.03] p-0.5 shadow-inner">
					<span
						className={cn(
							"absolute top-0.5 bottom-0.5 w-[calc(50%-2px)] rounded-md transition-all duration-300",
							mode === "live"
								? "left-0.5 bg-gradient-to-r from-rose-500/85 to-amber-500/85 shadow-[0_0_18px_-2px_rgba(244,63,94,0.7)]"
								: "left-[calc(50%+0px)] bg-gradient-to-r from-azure to-cyan shadow-[0_0_18px_-2px_rgba(0,212,255,0.7)]",
						)}
					/>
					<button
						type="button"
						onClick={() => handleModeChange("live")}
						className={cn(
							"relative z-10 flex h-full w-[44px] sm:w-[64px] items-center justify-center gap-1 sm:gap-1.5 text-[10px] sm:text-[11px] font-semibold uppercase tracking-wider transition-colors",
							mode === "live"
								? "text-white"
								: "text-white/40 hover:text-white/80",
						)}
					>
						<Radio
							size={11}
							className={cn(
								"w-2.5 h-2.5 sm:w-3 sm:h-3",
								mode === "live" && "animate-pulse text-white",
							)}
						/>
						Live
					</button>
					<button
						type="button"
						onClick={() => handleModeChange("paper")}
						className={cn(
							"relative z-10 flex h-full w-[44px] sm:w-[64px] items-center justify-center gap-1 sm:gap-1.5 text-[10px] sm:text-[11px] font-semibold uppercase tracking-wider transition-colors",
							mode === "paper"
								? "text-white"
								: "text-white/40 hover:text-white/80",
						)}
					>
						<FlaskConical size={11} className="w-2.5 h-2.5 sm:w-3 sm:h-3" />
						Paper
					</button>
				</div>

				{/* Cyber-Quant Exchange Account / API Key Selector */}
				<AccountSelector
					accounts={activeApiKeys}
					balances={balancesRecord}
					selectedAccountId={selectedApiKeyId}
					onSelect={setSelectedApiKeyId}
					showBalances={true}
				/>

				{/* AI Co-Pilot Toggle Button */}
				<button
					type="button"
					onClick={() =>
						setWidgetState(widgetState === "open" ? "minimized" : "open")
					}
					className={cn(
						"group relative flex h-7 sm:h-8 items-center gap-1 sm:gap-1.5 overflow-hidden rounded-lg px-2 sm:px-3 text-[10px] sm:text-[11.5px] font-semibold text-white transition-all shrink-0",
						widgetState === "open"
							? "bg-white/10 border border-cyan/40 text-cyan shadow-[0_0_15px_-3px_rgba(0,212,255,0.5)]"
							: "bg-gradient-to-r from-azure to-cyan shadow-[0_0_20px_-5px_rgba(0,212,255,0.85)] hover:shadow-[0_0_28px_-3px_rgba(0,212,255,1)] hover:brightness-110",
					)}
				>
					<span className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
					<Sparkles size={12} className="animate-pulse" />
					<span className="hidden md:inline">Co-Pilot</span>
				</button>

				{/* User Nav with Account Dropdown */}
				<UserNav />
			</div>
		</header>
	);
};
