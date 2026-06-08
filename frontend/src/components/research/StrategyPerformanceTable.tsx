// src/components/research/StrategyPerformanceTable.tsx

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
import type { StrategyPerformanceData } from "@/types/api";

interface StrategyPerformanceTableProps {
	performanceData: StrategyPerformanceData[];
}

const StrategyPerformanceTable: React.FC<StrategyPerformanceTableProps> = ({
	performanceData,
}) => {
	const { t } = useTranslation("research"); // Initialize useTranslation
	const notAvailableText = t("notAvailableShort", "N/A");

	if (!performanceData || performanceData.length === 0) {
		return (
			<p className="text-center text-muted-foreground py-4">
				{t("noStrategyPerformanceDataToDisplay")}
			</p>
		);
	}

	return (
		<>
			<Table>
				<TableHeader>
					<TableRow>
						<TableHead>{t("tableHeaderStrategyName")}</TableHead>
						<TableHead>{t("tableHeaderTotalPnl")}</TableHead>
						<TableHead>{t("tableHeaderWinRate")}</TableHead>
						<TableHead>{t("tableHeaderTotalTrades")}</TableHead>
						<TableHead>{t("tableHeaderSharpeRatio")}</TableHead>
						<TableHead>{t("tableHeaderMaxDD")}</TableHead>
					</TableRow>
				</TableHeader>
				<TableBody>
					{performanceData.map((perf) => (
						<TableRow key={perf.strategy_id}>
							<TableCell>{perf.strategy_name || perf.strategy_id}</TableCell>
							<TableCell
								className={perf.total_pnl >= 0 ? "text-profit" : "text-loss"}
							>
								{perf.total_pnl.toFixed(2)}
							</TableCell>
							<TableCell>{(perf.win_rate * 100).toFixed(2)}%</TableCell>
							<TableCell>{perf.total_trades}</TableCell>
							<TableCell>
								{perf.sharpe_ratio != null
									? perf.sharpe_ratio.toFixed(3)
									: notAvailableText}
							</TableCell>
							<TableCell>
								{perf.max_drawdown != null
									? `${(perf.max_drawdown * 100).toFixed(2)}%`
									: notAvailableText}
							</TableCell>
						</TableRow>
					))}
				</TableBody>
			</Table>
			{performanceData.length > 10 && (
				<TableCaption>
					{t("tableCaptionDisplayingStrategyPerformance", {
						count: performanceData.length,
					})}
				</TableCaption>
			)}
		</>
	);
};

export default StrategyPerformanceTable;
