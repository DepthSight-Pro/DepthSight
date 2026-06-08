// src/components/dashboard/PortfolioOverview.tsx

import { AlertTriangle } from "lucide-react"; // For error icon
import { useTranslation } from "react-i18next"; // Import useTranslation
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"; // For error display
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import { usePortfolioStatus } from "@/lib/api";
import { useAccountStore } from "@/stores/accountStore";

export function PortfolioOverview() {
	const { t } = useTranslation(["index", "common"]); // Load namespaces
	const { mode } = usePortfolioMode();
	const { selectedApiKeyId, selectedMarketType } = useAccountStore();

	const {
		data: portfolioData,
		isLoading,
		isError,
		error,
	} = usePortfolioStatus({
		mode,
		apiKeyId: mode === "live" ? selectedApiKeyId : undefined,
		marketType: mode === "live" ? selectedMarketType : undefined,
	});

	// Calculate Equity = Balance + Unrealized PnL (assuming today_pnl is unrealized for the overview)
	const equity = portfolioData
		? portfolioData.balance + portfolioData.today_pnl
		: 0;

	// Define metrics using keys from index.json
	const metricsConfig = [
		{
			jsonKey: "balance",
			value: portfolioData?.balance?.toFixed(2) ?? "0.00",
			isMonetary: true,
		},
		{
			jsonKey: "unrealizedPnl",
			value: portfolioData?.today_pnl?.toFixed(2) ?? "0.00",
			isMonetary: true,
			isPnL: true,
		},
		{ jsonKey: "equity", value: equity.toFixed(2), isMonetary: true },
		{ jsonKey: "marginUsage", value: t("common:na"), isPercentage: false }, // Margin Usage not directly available
	];

	const metrics = metricsConfig.map((m) => ({
		...m,
		label: t(`index:portfolioOverview.${m.jsonKey}`),
	}));

	return (
		<Card className="h-full flex flex-col">
			<CardHeader className="pb-3">
				<CardTitle className="text-base font-medium text-foreground">
					{t("index:portfolioOverview.title")}
				</CardTitle>
			</CardHeader>
			<CardContent className="flex-grow">
				{isLoading && (
					<div className="space-y-3">
						{[...Array(metrics.length)].map((_, i) => (
							<Skeleton key={i} className="h-4 w-full" />
						))}
					</div>
				)}
				{isError && !isLoading && (
					<Alert variant="destructive" className="mt-2">
						<AlertTriangle className="h-4 w-4" />
						<AlertTitle>{t("common:errorTitle")}</AlertTitle>
						<AlertDescription>
							{error?.message ||
								t("index:errors.failedToLoadPortfolioOverview")}
						</AlertDescription>
					</Alert>
				)}
				{!isLoading &&
					!isError &&
					portfolioData &&
					metrics.map((metric) => (
						<div
							key={metric.jsonKey}
							className="flex items-center justify-between text-sm mb-1 last:mb-0"
						>
							<span className="text-muted-foreground">{metric.label}</span>
							<span
								className={`mono font-medium ${metric.isPnL ? (metric.value.startsWith("-") ? "text-loss" : "text-profit") : "text-foreground"}`}
							>
								{metric.isMonetary && "$"}
								{metric.value}
								{metric.isPercentage && "%"}
								{/* Note: Percentage formatting might need adjustment if value is 'N/A' */}
							</span>
						</div>
					))}
				{!isLoading && !isError && !portfolioData && (
					<p className="text-sm text-muted-foreground">
						{t("index:portfolioOverview.noPortfolioDataAvailable")}
					</p>
				)}
			</CardContent>
		</Card>
	);
}
