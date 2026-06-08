// src/components/dashboard/MultiAccountOverview.tsx

import {
	AlertCircle,
	Key,
	TrendingDown,
	TrendingUp,
	Wallet,
} from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useMultiAccountBalances } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAccountStore } from "@/stores/accountStore";

const MultiAccountOverviewSkeleton: React.FC = () => (
	<Card>
		<CardHeader>
			<Skeleton className="h-6 w-40" />
		</CardHeader>
		<CardContent className="space-y-4">
			<div className="grid grid-cols-3 gap-4">
				{[1, 2, 3].map((i) => (
					<Skeleton key={i} className="h-20 rounded-lg" />
				))}
			</div>
			<div className="grid grid-cols-2 gap-3">
				{[1, 2].map((i) => (
					<Skeleton key={i} className="h-16 rounded-lg" />
				))}
			</div>
		</CardContent>
	</Card>
);

export const MultiAccountOverview: React.FC = () => {
	const { t } = useTranslation(["index", "common"]);
	const { selectedMarketType } = useAccountStore();
	const {
		data: overview,
		isLoading,
		isError,
	} = useMultiAccountBalances(selectedMarketType);

	if (isLoading) {
		return <MultiAccountOverviewSkeleton />;
	}

	if (isError || !overview) {
		return (
			<Card>
				<CardHeader>
					<CardTitle className="flex items-center gap-2">
						<Wallet className="h-5 w-5" />
						{t("index:portfolioOverview.title")}
					</CardTitle>
				</CardHeader>
				<CardContent>
					<div className="flex items-center gap-2 text-muted-foreground">
						<AlertCircle className="h-4 w-4" />
						<span>{t("common:errorLoadingData")}</span>
					</div>
				</CardContent>
			</Card>
		);
	}

	const hasMultipleAccounts = overview.accounts.length > 1;
	const marketBreakdown = overview.marketBreakdown ?? [];
	const displayTotal = overview.totalEquity ?? overview.totalBalance;

	return (
		<Card>
			<CardHeader className="pb-2">
				<CardTitle className="flex items-center gap-2 text-lg">
					<Wallet className="h-5 w-5 text-primary" />
					{t("index:portfolioOverview.title")}
					{hasMultipleAccounts && (
						<Badge variant="secondary" className="ml-2">
							{overview.accounts.length} {t("common:accounts")}
						</Badge>
					)}
				</CardTitle>
			</CardHeader>
			<CardContent className="space-y-4">
				{/* Total Stats */}
				<div className="grid grid-cols-3 gap-4">
					<div className="text-center p-4 bg-gradient-to-br from-primary/10 to-primary/5 rounded-xl border border-primary/20">
						<p className="text-xs text-muted-foreground mb-1">
							{t("index:portfolioOverview.totalBalance")}
						</p>
						<p className="text-2xl font-bold text-primary">
							$
							{displayTotal.toLocaleString(undefined, {
								minimumFractionDigits: 2,
								maximumFractionDigits: 2,
							})}
						</p>
					</div>
					<div className="text-center p-4 bg-secondary/30 rounded-xl">
						<p className="text-xs text-muted-foreground mb-1">
							{t("index:portfolioOverview.available")}
						</p>
						<p className="text-2xl font-bold">
							$
							{overview.totalAvailable.toLocaleString(undefined, {
								minimumFractionDigits: 2,
								maximumFractionDigits: 2,
							})}
						</p>
					</div>
					<div className="text-center p-4 bg-secondary/30 rounded-xl">
						<p className="text-xs text-muted-foreground mb-1">
							{t("index:portfolioOverview.unrealizedPnl")}
						</p>
						<p
							className={cn(
								"text-2xl font-bold flex items-center justify-center gap-1",
								overview.totalUnrealizedPnl >= 0
									? "text-green-500"
									: "text-red-500",
							)}
						>
							{overview.totalUnrealizedPnl >= 0 ? (
								<TrendingUp className="h-5 w-5" />
							) : (
								<TrendingDown className="h-5 w-5" />
							)}
							{overview.totalUnrealizedPnl >= 0 ? "+" : ""}$
							{Math.abs(overview.totalUnrealizedPnl).toLocaleString(undefined, {
								minimumFractionDigits: 2,
								maximumFractionDigits: 2,
							})}
						</p>
					</div>
				</div>

				{marketBreakdown.length > 1 && (
					<div className="grid grid-cols-1 md:grid-cols-2 gap-3">
						{marketBreakdown.map((market) => (
							<div
								key={market.marketType}
								className="p-3 border rounded-lg bg-secondary/10"
							>
								<div className="flex items-center justify-between">
									<Badge variant="outline">
										{market.marketType === "spot" ? "Spot" : "Futures"}
									</Badge>
									<span className="text-sm font-semibold">
										$
										{(market.totalEquity ?? market.totalBalance).toLocaleString(
											undefined,
											{ minimumFractionDigits: 2, maximumFractionDigits: 2 },
										)}
									</span>
								</div>
								<div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
									<span>
										Available: $
										{market.totalAvailable.toLocaleString(undefined, {
											maximumFractionDigits: 2,
										})}
									</span>
									<span>
										PnL: {market.totalUnrealizedPnl >= 0 ? "+" : ""}$
										{market.totalUnrealizedPnl.toLocaleString(undefined, {
											maximumFractionDigits: 2,
										})}
									</span>
								</div>
							</div>
						))}
					</div>
				)}

				{/* Individual Accounts - Only show if multiple accounts */}
				{hasMultipleAccounts && (
					<div className="space-y-3">
						<h4 className="text-sm font-semibold text-muted-foreground">
							{t("index:portfolioOverview.accountBreakdown")}
						</h4>
						<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
							{overview.accounts.map((account) => (
								<div
									key={`${account.apiKeyId}-${account.marketType}`}
									className="p-3 border rounded-lg hover:bg-secondary/20 transition-colors"
								>
									<div className="flex justify-between items-start">
										<div className="flex items-center gap-2">
											<Key className="h-4 w-4 text-muted-foreground" />
											<div>
												<p className="font-medium text-sm">
													{account.apiKeyName}
												</p>
												<p className="text-xs text-muted-foreground">
													{account.exchange} /{" "}
													{account.marketType === "spot" ? "Spot" : "Futures"}
												</p>
												<p className="text-lg font-bold">
													$
													{(
														account.totalEquity ?? account.balance
													).toLocaleString(undefined, {
														minimumFractionDigits: 2,
														maximumFractionDigits: 2,
													})}
												</p>
												{account.marketType === "spot" &&
													account.assets?.length > 0 && (
														<p className="text-xs text-muted-foreground">
															{account.assets
																.slice(0, 3)
																.map(
																	(asset) =>
																		`${asset.asset}: ${asset.total.toLocaleString(undefined, { maximumFractionDigits: 4 })}`,
																)
																.join(" · ")}
														</p>
													)}
											</div>
										</div>
										<Badge
											variant={
												account.unrealizedPnl >= 0 ? "default" : "destructive"
											}
											className={cn(
												"text-xs",
												account.unrealizedPnl >= 0
													? "bg-green-500/10 text-green-500 border-green-500/20"
													: "bg-red-500/10 text-red-500 border-red-500/20",
											)}
										>
											{account.unrealizedPnl >= 0 ? "+" : ""}$
											{account.unrealizedPnl.toLocaleString(undefined, {
												minimumFractionDigits: 2,
												maximumFractionDigits: 2,
											})}
										</Badge>
									</div>
								</div>
							))}
						</div>
					</div>
				)}
			</CardContent>
		</Card>
	);
};

export default MultiAccountOverview;
