// src/components/strategies/StrategyTradeHistoryTab.tsx

import { format } from "date-fns"; // For formatting timestamp
import { AlertTriangle } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { useTradeHistory } from "@/lib/api";
import { formatCryptoPrice } from "@/lib/formatters";

interface StrategyTradeHistoryTabProps {
	strategyId: string;
}

export const StrategyTradeHistoryTab: React.FC<
	StrategyTradeHistoryTabProps
> = ({ strategyId }) => {
	const { t } = useTranslation("strategies"); // Use 'strategies' namespace
	const { data, isLoading, isError, error } = useTradeHistory({ strategyId });
	const trades = data?.trades || [];

	if (isLoading) {
		return (
			<div className="space-y-2 mt-4">
				{[...Array(5)].map((_, i) => (
					<Skeleton key={i} className="h-10 w-full" />
				))}
			</div>
		);
	}

	if (isError) {
		return (
			<Alert variant="destructive" className="mt-4">
				<AlertTriangle className="h-4 w-4" />
				<AlertTitle>{t("tradeHistoryTab.errorTitle")}</AlertTitle>
				<AlertDescription>
					{error?.message || "An unknown error occurred."}
				</AlertDescription>
			</Alert>
		);
	}

	if (trades.length === 0) {
		return (
			<p className="text-muted-foreground mt-4">
				{t("tradeHistoryTab.noTrades")}
			</p>
		);
	}

	return (
		<div className="mt-4">
			<Table>
				<TableHeader>
					<TableRow className="text-[11px] uppercase tracking-wider font-bold text-muted-foreground bg-muted/50 border-b border-border">
						<TableHead>{t("tradeHistoryTab.colTimestamp")}</TableHead>
						<TableHead>{t("tradeHistoryTab.colSymbol")}</TableHead>
						<TableHead className="text-center">
							{t("tradeHistoryTab.colDirection")}
						</TableHead>
						<TableHead className="text-right">
							{t("tradeHistoryTab.colQuantity")}
						</TableHead>
						<TableHead className="text-right">
							{t("tradeHistoryTab.colEntry")}
						</TableHead>
						<TableHead className="text-right">
							{t("tradeHistoryTab.colExit")}
						</TableHead>
						<TableHead className="text-right">
							{t("tradeHistoryTab.colPnl")}
						</TableHead>
						<TableHead>{t("tradeHistoryTab.colExitReason")}</TableHead>
					</TableRow>
				</TableHeader>
				<TableBody className="divide-y divide-border">
					{trades.map((trade) => (
						<TableRow
							key={trade.id}
							className="hover:bg-muted/30 transition-colors group"
						>
							<TableCell className="px-6 py-4">
								<span className="text-sm font-semibold text-foreground">
									{trade.timestamp_close
										? format(new Date(trade.timestamp_close), "dd.MM.yyyy")
										: "N/A"}
								</span>
								<span className="block text-[10px] text-muted-foreground mt-0.5">
									{trade.timestamp_close
										? format(new Date(trade.timestamp_close), "HH:mm:ss")
										: ""}
								</span>
							</TableCell>
							<TableCell className="px-6 py-4 font-bold text-foreground font-mono text-sm">
								{trade.symbol}
							</TableCell>
							<TableCell className="px-6 py-4 text-center">
								<span
									className={`inline-block px-2.5 py-1 rounded-lg text-[9px] font-black tracking-widest ${
										["LONG", "BUY"].includes(trade.direction)
											? "bg-profit/10 text-profit border border-profit/20"
											: "bg-loss/10 text-loss border border-loss/20"
									}`}
								>
									{trade.direction}
								</span>
							</TableCell>
							<TableCell className="px-6 py-4 text-right font-mono text-sm text-foreground">
								{trade.quantity}
							</TableCell>
							<TableCell className="px-6 py-4 text-right font-mono text-sm text-foreground">
								${formatCryptoPrice(trade.entry_price)}
							</TableCell>
							<TableCell className="px-6 py-4 text-right font-mono text-sm text-foreground">
								${formatCryptoPrice(trade.exit_price)}
							</TableCell>
							<TableCell
								className={`px-6 py-4 text-right font-mono font-bold text-base ${(trade.pnl || 0) >= 0 ? "text-profit" : "text-loss"}`}
							>
								{(trade.pnl || 0) >= 0 ? "+" : ""}
								{trade.pnl?.toFixed(2) ?? "0.00"}
							</TableCell>
							<TableCell className="px-6 py-4 text-muted-foreground text-xs">
								{trade.exit_reason}
							</TableCell>
						</TableRow>
					))}
				</TableBody>
			</Table>
		</div>
	);
};
