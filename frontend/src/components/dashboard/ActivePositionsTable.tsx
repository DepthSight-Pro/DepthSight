// frontend/src/components/dashboard/ActivePositionsTable.tsx

import { AlertTriangle } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import { useNavigate } from "react-router-dom";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import { usePositions } from "@/lib/api";

import { useAccountStore } from "@/stores/accountStore";

// Component for displaying active trading positions
export const ActivePositionsTable: React.FC = () => {
	const { t } = useTranslation(["index", "common"]); // Load 'index' and 'common' namespaces
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
	});
	const navigate = useNavigate();

	const handleRowClick = (symbol: string) => {
		navigate(`/positions?symbol=${encodeURIComponent(symbol)}`);
	};

	if (isError) {
		return (
			<Alert variant="destructive" className="my-4">
				<AlertTriangle className="h-4 w-4" />
				<AlertTitle>{t("index:errors.errorLoadingActivePositions")}</AlertTitle>
				<AlertDescription>
					{error?.message || t("common:errors.unknownError")}
				</AlertDescription>
			</Alert>
		);
	}

	return (
		<Card>
			<CardHeader>
				<CardTitle>{t("index:activePositions.title")}</CardTitle>
				<CardDescription>
					{t("index:activePositions.description")}
				</CardDescription>
			</CardHeader>
			<CardContent>
				<Table>
					<TableHeader>
						<TableRow>
							<TableHead>{t("index:activePositions.colSymbol")}</TableHead>
							<TableHead>{t("index:activePositions.colSide")}</TableHead>
							<TableHead className="text-right">
								{t("index:activePositions.colSize")}
							</TableHead>
							<TableHead className="text-right">
								{t("index:activePositions.colEntry")}
							</TableHead>
							<TableHead className="text-right">
								{t("index:activePositions.colMark")}
							</TableHead>
							<TableHead className="text-right">
								{t("index:activePositions.colPnlUsd")}
							</TableHead>
							<TableHead className="text-right">
								{t("index:activePositions.colPnlPercent")}
							</TableHead>
						</TableRow>
					</TableHeader>
					<TableBody>
						{isLoading ? (
							[...Array(3)].map((_, i) => (
								<TableRow key={`skeleton-${i}`}>
									<TableCell colSpan={7}>
										<Skeleton className="h-8 w-full" />
									</TableCell>
								</TableRow>
							))
						) : positions.length === 0 ? (
							<TableRow>
								<TableCell
									colSpan={7}
									className="h-24 text-center text-muted-foreground"
								>
									{t("index:activePositions.noPositions")}
								</TableCell>
							</TableRow>
						) : (
							positions.map((pos) => (
								<TableRow
									key={pos.id}
									onClick={() => handleRowClick(pos.symbol)}
									className="cursor-pointer hover:bg-muted/50"
								>
									<TableCell className="font-medium mono">
										{pos.symbol}
									</TableCell>
									<TableCell>
										<Badge
											variant={
												pos.direction === "LONG" ? "default" : "destructive"
											}
										>
											{pos.direction}
										</Badge>
									</TableCell>
									<TableCell className="text-right mono">{pos.size}</TableCell>
									<TableCell className="text-right mono">
										${pos.entry_price.toFixed(2)}
									</TableCell>
									<TableCell className="text-right mono">
										${pos.mark_price.toFixed(2)}
									</TableCell>
									<TableCell
										className={`text-right mono font-medium ${pos.pnl >= 0 ? "text-profit" : "text-loss"}`}
									>
										{pos.pnl >= 0 ? "+" : ""}
										{pos.pnl.toFixed(2)}
									</TableCell>
									<TableCell
										className={`text-right mono font-medium ${pos.pnl_percent >= 0 ? "text-profit" : "text-loss"}`}
									>
										{pos.pnl_percent.toFixed(2)}%
									</TableCell>
								</TableRow>
							))
						)}
					</TableBody>
				</Table>
			</CardContent>
		</Card>
	);
};
