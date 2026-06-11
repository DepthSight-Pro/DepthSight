// src/components/AppHeader.tsx

import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { AccountSelector } from "@/components/layout/AccountSelector";
import { ConnectionStatusIndicator } from "@/components/shared/ConnectionStatusIndicator";
import { Badge } from "@/components/ui/badge";
import { Logo } from "@/components/ui/logo";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import {
	useAccountStatus,
	useConfig,
	useMultiAccountBalances,
} from "@/lib/api";
import { useAccountStore } from "@/stores/accountStore";
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
	const { data: accountStatus } = useAccountStatus();
	const { t } = useTranslation(["common", "account"]);

	const apiKeys = config?.apiKeys;
	const hasApiKeys = Boolean(apiKeys?.length);

	// Filter only active and valid API keys for the selector
	const activeApiKeys = useMemo(() => {
		if (!apiKeys) return [];
		return apiKeys.filter((key) => key.isActive && key.status === "valid");
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
						// For unified accounts, keep the one with futures_usdtm if it exists, otherwise keep spot.
						// We combine assets, but do not sum wallet balances, equity, etc.
						if (bal.marketType === "futures_usdtm") {
							acc[bal.apiKeyId] = {
								...bal,
								assets: [...(existing.assets ?? []), ...(bal.assets ?? [])],
							};
						} else {
							// If the new one is spot, keep existing (which might be futures_usdtm) but merge assets
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

	// Calculate the number of remaining plan days
	const planExpiresAt = accountStatus?.planExpiresAt;
	const daysLeft = useMemo(() => {
		if (!planExpiresAt) return null;
		const expiresAt = new Date(planExpiresAt);
		const now = new Date();
		const diffTime = expiresAt.getTime() - now.getTime();
		return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
	}, [planExpiresAt]);

	useEffect(() => {
		if (isConfigSuccess && !hasApiKeys && mode === "live") {
			setMode("paper");
		}
	}, [hasApiKeys, isConfigSuccess, mode, setMode]);

	const handleModeChange = (value: string) => {
		if (value === "live") {
			if (hasApiKeys) {
				setMode("live");
			} else {
				toast.error(t("common:errors.connectApiKeys"));
			}
		} else if (value === "paper") {
			setMode("paper");
		}
	};

	return (
		<header className="flex h-20 items-center border-b bg-sidebar px-4 shrink-0">
			<div className="flex-1">
				{mode === "live" && activeApiKeys.length > 0 && (
					<div className="flex items-center gap-2">
						{activeApiKeys.length > 1 && (
							<AccountSelector
								accounts={activeApiKeys}
								balances={balancesRecord}
								selectedAccountId={selectedApiKeyId}
								onSelect={setSelectedApiKeyId}
								showBalances={true}
							/>
						)}
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
							className="bg-background rounded-md p-1"
						>
							<ToggleGroupItem value="all" aria-label="All markets">
								All
							</ToggleGroupItem>
							<ToggleGroupItem
								value="futures_usdtm"
								aria-label="Futures market"
							>
								Futures
							</ToggleGroupItem>
							<ToggleGroupItem value="spot" aria-label="Spot market">
								Spot
							</ToggleGroupItem>
						</ToggleGroup>
					</div>
				)}
			</div>

			<div className="flex items-center justify-center">
				<Link to="/" className="flex items-center space-x-2">
					<Logo className="h-12" />
					<Badge variant="secondary" className="mt-[3px]">
						<span className="-translate-y-px inline-block">BETA</span>
					</Badge>
				</Link>
			</div>

			<div className="flex flex-1 justify-end items-center space-x-4">
				{daysLeft !== null && daysLeft >= 0 && (
					<div className="flex items-center text-sm mr-1 hidden sm:flex bg-muted/50 px-3 py-1.5 rounded-full border border-border/50 shadow-sm">
						<span className="text-muted-foreground mr-2 text-xs font-medium">
							{t("common:daysLeft", "Days left:")}
						</span>
						<span
							className={
								"font-bold text-xs " +
								(daysLeft <= 3
									? "text-red-500"
									: daysLeft <= 7
										? "text-amber-500"
										: "text-emerald-500")
							}
						>
							{daysLeft}
						</span>
					</div>
				)}
				<ConnectionStatusIndicator />
				<ToggleGroup
					type="single"
					size="sm"
					value={mode}
					onValueChange={handleModeChange}
					className="bg-background rounded-md p-1"
				>
					<ToggleGroupItem
						value="live"
						aria-label="Live mode"
						onClick={() => {
							if (!hasApiKeys) {
								toast.error("Connect API keys in settings");
							} else {
								setMode("live");
							}
						}}
					>
						<span className="mr-2">💵</span> Live
					</ToggleGroupItem>
					<ToggleGroupItem value="paper" aria-label="Paper mode">
						<span className="mr-2">📄</span> Paper
					</ToggleGroupItem>
				</ToggleGroup>
				<UserNav />
			</div>
		</header>
	);
};
