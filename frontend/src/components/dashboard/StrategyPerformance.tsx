// src/components/dashboard/StrategyPerformance.tsx

import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface StrategyData {
	name: string;
	symbol: string;
	pnl24h: number;
	trades: number;
	winRate: number;
}

const mockStrategies: StrategyData[] = [
	{
		name: "VolumeBreakout",
		symbol: "BTCUSDT",
		pnl24h: 125.5,
		trades: 8,
		winRate: 75.0,
	},
	{
		name: "MeanReversion",
		symbol: "ETHUSDT",
		pnl24h: -23.8,
		trades: 12,
		winRate: 58.3,
	},
	{
		name: "TrendFollowing",
		symbol: "SOLUSDT",
		pnl24h: 89.2,
		trades: 6,
		winRate: 83.3,
	},
];

export function StrategyPerformance() {
	const { t } = useTranslation(["index", "common"]);

	return (
		<Card className="h-full flex flex-col">
			<CardHeader className="pb-3">
				<CardTitle className="text-base font-medium text-foreground">
					{t("index:topStrategies.title24h")}
				</CardTitle>
			</CardHeader>
			<CardContent className="flex-grow">
				<div className="space-y-3">
					{/* Header */}
					<div className="grid grid-cols-5 gap-2 text-xs font-medium text-muted-foreground border-b border-border pb-2">
						<div>{t("index:topStrategies.colName")}</div>
						<div>{t("index:topStrategies.colSymbol")}</div>
						<div>{t("index:topStrategies.colPnl24h")}</div>
						<div>{t("index:topStrategies.colTrades")}</div>
						<div>{t("index:topStrategies.colWinRate")}</div>
					</div>

					{/* Strategy rows */}
					{mockStrategies.map((strategy, index) => (
						<div key={index} className="grid grid-cols-5 gap-2 text-sm">
							<div className="font-medium text-foreground truncate">
								{strategy.name}
							</div>
							<div className="mono text-muted-foreground">
								{strategy.symbol}
							</div>
							<div
								className={`mono font-medium ${strategy.pnl24h >= 0 ? "pnl-positive" : "pnl-negative"}`}
							>
								{strategy.pnl24h >= 0 ? "+" : ""}${strategy.pnl24h.toFixed(2)}
							</div>
							<div className="mono text-foreground">{strategy.trades}</div>
							<div className="mono text-foreground">
								{strategy.winRate.toFixed(1)}%
							</div>
						</div>
					))}
				</div>
			</CardContent>
		</Card>
	);
}
