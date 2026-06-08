// src/components/dashboard/OpenPositions.tsx

import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import { usePositions } from "@/lib/api"; // Import hook for fetching positions
import { useAccountStore } from "@/stores/accountStore";

export function OpenPositions() {
	const { t } = useTranslation(["index", "common"]);
	const { mode } = usePortfolioMode();
	const { selectedApiKeyId, selectedMarketType } = useAccountStore();

	const {
		data: positions = [],
		isLoading,
		isError,
		error,
	} = usePositions({
		mode,
		apiKeyId: mode === "live" ? selectedApiKeyId : undefined,
		marketType: mode === "live" ? selectedMarketType : undefined,
		// Add automatic update every 5 seconds
		refetchInterval: 5000,
	});

	return (
		<Card className="bg-card border-border col-span-4">
			<CardHeader className="pb-3">
				<CardTitle className="text-base font-medium text-foreground">
					{t("index:activePositions.title")}
				</CardTitle>
			</CardHeader>
			<CardContent>
				{isLoading ? (
					<div className="space-y-2 pt-2">
						{[...Array(2)].map((_, i) => (
							<Skeleton key={i} className="h-8 w-full" />
						))}
					</div>
				) : isError ? (
					<Alert variant="destructive" className="my-1">
						<AlertTriangle className="h-4 w-4" />
						<AlertTitle>
							{t("index:errors.errorLoadingActivePositions")}
						</AlertTitle>
						<AlertDescription className="text-xs">
							{error?.message || t("common:errors.unknownError")}
						</AlertDescription>
					</Alert>
				) : positions.length === 0 ? (
					<div className="text-center py-8 text-muted-foreground">
						{t("index:activePositions.noOpenPositions")}
					</div>
				) : (
					<div className="space-y-1">
						<div className="grid grid-cols-7 gap-4 text-xs font-medium text-muted-foreground pb-2 border-b border-border">
							<div className="col-span-2">
								{t("index:activePositions.colSymbol")}
							</div>
							<div className="col-span-2">
								{t("index:activePositions.colStrategy")}
							</div>
							<div>{t("index:activePositions.colSide")}</div>
							<div className="text-right">
								{t("index:activePositions.colUnrealizedPnlUsd")}
							</div>
							<div>{t("common:actions")}</div>
						</div>
						{positions.map((pos) => (
							<div
								key={pos.id}
								className="grid grid-cols-7 gap-4 text-sm py-2 items-center"
							>
								<div className="col-span-2 mono font-medium">{pos.symbol}</div>
								<div className="col-span-2 text-muted-foreground truncate">
									{pos.strategy}
								</div>
								<div>
									<Badge
										variant={
											pos.direction === "LONG" ? "default" : "destructive"
										}
										className="w-fit"
									>
										{pos.direction}
									</Badge>
								</div>
								<div
									className={`col-span-1 mono font-medium text-right ${pos.pnl >= 0 ? "text-profit" : "text-loss"}`}
								>
									{pos.pnl >= 0 ? "+" : ""}${pos.pnl.toFixed(2)}
								</div>
								<div className="col-span-1">
									{/* TODO: Add a real close button or a link to details */}
									<button className="text-xs text-primary hover:underline">
										{t("index:activePositions.detailsButton")}
									</button>
								</div>
							</div>
						))}
					</div>
				)}
			</CardContent>
		</Card>
	);
}
