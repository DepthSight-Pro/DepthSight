// src/components/dashboard/PortfolioOverviewWidget.tsx

import { AlertTriangle } from "lucide-react";
import type React from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import { usePortfolioStatus, usePositions } from "@/lib/api";

interface StatCardProps {
	title: string;
	value: string | number;
	isLoading?: boolean;
	prefix?: string;
	suffix?: string;
	colorClass?: string;
}

const StatCard: React.FC<StatCardProps> = ({
	title,
	value,
	isLoading,
	prefix = "",
	suffix = "",
	colorClass = "text-foreground",
}) => {
	return (
		<Card>
			<CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
				<CardTitle className="text-sm font-medium text-muted-foreground">
					{title}
				</CardTitle>
			</CardHeader>
			<CardContent>
				{isLoading ? (
					<Skeleton className="h-8 w-3/4" />
				) : (
					<div className={`text-2xl font-bold mono ${colorClass}`}>
						{prefix}
						{value}
						{suffix}
					</div>
				)}
			</CardContent>
		</Card>
	);
};

import { useAccountStore } from "@/stores/accountStore";

export const PortfolioOverviewWidget: React.FC = () => {
	const { t, i18n } = useTranslation(["index", "common"]);
	const { mode } = usePortfolioMode();
	const { selectedApiKeyId, selectedMarketType } = useAccountStore();

	// Get BOTH data sources considering the selected account
	const hookParams = {
		mode,
		apiKeyId: mode === "live" ? selectedApiKeyId : undefined,
		marketType: mode === "live" ? selectedMarketType : undefined,
	};

	const {
		data: portfolioStatus,
		isLoading: isLoadingStatus,
		isError: isErrorStatus,
		error: errorStatus,
	} = usePortfolioStatus(hookParams);
	const {
		data: positions,
		isLoading: isLoadingPositions,
		isError: isErrorPositions,
		error: errorPositions,
	} = usePositions(hookParams);

	const isLoading = isLoadingStatus || isLoadingPositions;
	const isError = isErrorStatus || isErrorPositions;
	const error = errorStatus || errorPositions;

	// Calculate unrealized PnL manually, as on the "Positions" page
	const unrealizedPnl = useMemo(() => {
		if (!positions || positions.length === 0) {
			return 0;
		}
		return positions.reduce((acc, pos) => acc + pos.pnl, 0);
	}, [positions]);

	const marginUsed = useMemo(() => {
		if (!positions || positions.length === 0) {
			return 0;
		}
		return positions.reduce((acc, pos) => {
			const size = Number(pos.size) || 0;
			const price = Number(pos.mark_price || pos.entry_price) || 0;
			return acc + Math.abs(size * price);
		}, 0);
	}, [positions]);

	if (isError) {
		return (
			<Alert variant="destructive" className="mb-4">
				<AlertTriangle className="h-4 w-4" />
				<AlertTitle>
					{t("index:errors.failedToLoadPortfolioOverview")}
				</AlertTitle>
				<AlertDescription>
					{error?.message || t("common:errors.unknownError")}
				</AlertDescription>
			</Alert>
		);
	}

	// Adding ?? 0 to avoid undefined error
	const equity = portfolioStatus ? portfolioStatus.balance + unrealizedPnl : 0;

	return (
		<div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
			<StatCard
				title={t("index:portfolioOverview.balance")}
				value={
					portfolioStatus?.balance.toLocaleString(i18n.language, {
						style: "currency",
						currency: "USD",
					}) ?? "0.00"
				}
				isLoading={isLoading}
			/>
			<StatCard
				title={t("index:portfolioOverview.unrealizedPnl")}
				value={unrealizedPnl.toLocaleString(i18n.language, {
					style: "currency",
					currency: "USD",
					signDisplay: "always",
				})}
				isLoading={isLoading}
				colorClass={unrealizedPnl >= 0 ? "text-profit" : "text-loss"}
			/>
			<StatCard
				title={t("index:portfolioOverview.equity")}
				value={
					equity.toLocaleString(i18n.language, {
						style: "currency",
						currency: "USD",
					}) ?? "0.00"
				}
				isLoading={isLoading}
			/>
			<StatCard
				title={t("index:portfolioOverview.marginUsage")}
				value={marginUsed.toLocaleString(i18n.language, {
					style: "currency",
					currency: "USD",
				})}
				isLoading={isLoading}
			/>
		</div>
	);
};
