// src/components/research/PortfolioTradeHistoryTable.tsx

import { format } from "date-fns"; // For formatting timestamps
import { enUS, ru } from "date-fns/locale"; // Import locales
import type React from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import {
	Table,
	TableBody,
	TableCaption,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import type { PortfolioTrade } from "@/types/api"; // Assuming PortfolioTrade is defined with necessary fields

interface PortfolioTradeHistoryTableProps {
	trades: PortfolioTrade[];
}

const PortfolioTradeHistoryTable: React.FC<PortfolioTradeHistoryTableProps> = ({
	trades,
}) => {
	const { t, i18n } = useTranslation(["research", "common"]); // Initialize useTranslation
	const currentLocale = i18n.language;
	const dateFnsLocale = currentLocale.startsWith("ru") ? ru : enUS;
	const notAvailableText = t("common:notAvailableShort", "N/A"); // Using common notAvailableShort

	if (!trades || trades.length === 0) {
		return (
			<p className="text-center text-muted-foreground py-4">
				{t("noTradesToDisplay")}
			</p>
		);
	}

	return (
		<>
			<Table>
				<TableHeader>
					<TableRow>
						<TableHead>{t("tableHeaderTimestampEntry")}</TableHead>
						<TableHead>{t("tableHeaderStrategy")}</TableHead>
						<TableHead>{t("labelSymbol")}</TableHead>{" "}
						{/* Reusing labelSymbol from LaunchTaskForm */}
						<TableHead>{t("tableHeaderDirection")}</TableHead>
						<TableHead>{t("tableHeaderEntryPrice")}</TableHead>
						<TableHead>{t("tableHeaderExitPrice")}</TableHead>
						<TableHead>{t("tableHeaderQuantity")}</TableHead>
						<TableHead>{t("tableHeaderPnl")}</TableHead>
						<TableHead>{t("tableHeaderExitReason")}</TableHead>
					</TableRow>
				</TableHeader>
				<TableBody>
					{trades.map((trade) => (
						<TableRow key={trade.id}>
							<TableCell className="text-xs">
								{format(
									new Date(trade.timestamp_entry),
									"yyyy-MM-dd HH:mm:ss",
									{ locale: dateFnsLocale },
								)}
							</TableCell>
							<TableCell>{trade.strategy_name || trade.strategy_id}</TableCell>
							<TableCell>{trade.symbol}</TableCell>
							<TableCell
								className={
									trade.direction === "LONG" ? "text-green-600" : "text-red-600"
								}
							>
								{trade.direction}
							</TableCell>
							<TableCell>{trade.entry_price.toFixed(2)}</TableCell>
							<TableCell>
								{trade.exit_price
									? trade.exit_price.toFixed(2)
									: notAvailableText}
							</TableCell>
							<TableCell>{trade.quantity.toString()}</TableCell>
							<TableCell
								className={trade.pnl >= 0 ? "text-profit" : "text-loss"}
							>
								{trade.pnl.toFixed(2)}
							</TableCell>
							<TableCell className="text-xs">{trade.exit_reason}</TableCell>
						</TableRow>
					))}
				</TableBody>
			</Table>
			{trades.length > 10 && (
				<TableCaption>
					{t("tableCaptionDisplayingTrades", { count: trades.length })}
				</TableCaption>
			)}
		</>
	);
};

export default PortfolioTradeHistoryTable;
