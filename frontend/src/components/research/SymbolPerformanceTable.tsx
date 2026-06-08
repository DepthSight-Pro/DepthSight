// src/components/research/SymbolPerformanceTable.tsx

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
import type { SymbolPerformanceData } from "@/types/api";

interface SymbolPerformanceTableProps {
	performanceData: SymbolPerformanceData[];
}

const SymbolPerformanceTable: React.FC<SymbolPerformanceTableProps> = ({
	performanceData,
}) => {
	const { t } = useTranslation("research"); // Initialize useTranslation

	if (!performanceData || performanceData.length === 0) {
		return (
			<p className="text-center text-muted-foreground py-4">
				{t("noSymbolPerformanceDataToDisplay")}
			</p>
		);
	}

	return (
		<>
			<Table>
				<TableHeader>
					<TableRow>
						<TableHead>{t("labelSymbol")}</TableHead> {/* Reusing key */}
						<TableHead>{t("tableHeaderTotalPnl")}</TableHead>
						<TableHead>{t("tableHeaderWinRate")}</TableHead>
						<TableHead>{t("tableHeaderTotalTrades")}</TableHead>
					</TableRow>
				</TableHeader>
				<TableBody>
					{performanceData.map((perf) => (
						<TableRow key={perf.symbol}>
							<TableCell>{perf.symbol}</TableCell>
							<TableCell
								className={perf.total_pnl >= 0 ? "text-profit" : "text-loss"}
							>
								{perf.total_pnl.toFixed(2)}
							</TableCell>
							<TableCell>{(perf.win_rate * 100).toFixed(2)}%</TableCell>
							<TableCell>{perf.total_trades}</TableCell>
						</TableRow>
					))}
				</TableBody>
			</Table>
			{performanceData.length > 10 && (
				<TableCaption>
					{t("tableCaptionDisplayingSymbolPerformance", {
						count: performanceData.length,
					})}
				</TableCaption>
			)}
		</>
	);
};

export default SymbolPerformanceTable;
