// frontend/src/components/analytics/InteractiveAssetChart.tsx

import { BarChart3, MousePointerClick } from "lucide-react";
import type React from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
	Bar,
	BarChart,
	Cell,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TradeData } from "@/types/api";

interface InteractiveAssetChartProps {
	trades: TradeData[];
	activeTickers: string[];
	onToggleTicker: (ticker: string) => void;
}

export const InteractiveAssetChart: React.FC<InteractiveAssetChartProps> = ({
	trades,
	activeTickers,
	onToggleTicker,
}) => {
	const { t } = useTranslation("analytics");

	const chartData = useMemo(() => {
		if (!trades || trades.length === 0) return [];

		const map = new Map<string, number>();
		trades.forEach((trade) => {
			// Robust check for symbol
			if (!trade?.symbol) return;
			const realizedPnl = Number(trade.pnl);
			if (Number.isNaN(realizedPnl)) return;

			map.set(
				String(trade.symbol),
				(map.get(String(trade.symbol)) || 0) + realizedPnl,
			);
		});

		return Array.from(map.entries())
			.map(([ticker, pnl]) => ({ ticker, pnl: Number(pnl.toFixed(2)) }))
			.sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))
			.slice(0, 15);
	}, [trades]);

	if (!trades || trades.length === 0) {
		return (
			<Card>
				<CardHeader className="pb-2">
					<CardTitle className="text-base">
						{t("assetPerformance", "PnL by assets")}
					</CardTitle>
				</CardHeader>
				<CardContent>
					<div className="h-[350px] flex items-center justify-center text-muted-foreground">
						{t("noData", "No Data")}
					</div>
				</CardContent>
			</Card>
		);
	}

	return (
		<Card>
			<CardHeader className="pb-2">
				<div className="flex items-center justify-between">
					<CardTitle className="flex items-center gap-2 text-base">
						<BarChart3 className="w-5 h-5 text-primary" />
						{t("assetPerformance", "PnL by assets")}
					</CardTitle>
					<div className="flex items-center gap-1 text-[9px] text-muted-foreground font-bold uppercase">
						<MousePointerClick className="w-3 h-3" />
						<span>{t("toggleCoins", "Toggle Coins")}</span>
					</div>
				</div>
			</CardHeader>
			<CardContent>
				<div className="h-[350px]">
					<ResponsiveContainer width="100%" height="100%">
						<BarChart layout="vertical" data={chartData}>
							<XAxis type="number" hide />
							<YAxis
								dataKey="ticker"
								type="category"
								stroke="hsl(var(--muted-foreground))"
								fontSize={10}
								width={80}
								tickLine={false}
								axisLine={false}
							/>
							<Tooltip
								cursor={{ fill: "transparent" }}
								contentStyle={{
									backgroundColor: "hsl(var(--card))",
									border: "1px solid hsl(var(--border))",
									borderRadius: "12px",
								}}
								formatter={(value: unknown) => [
									`$${Number(value ?? 0).toFixed(2)}`,
									"PnL",
								]}
							/>
							<Bar
								dataKey="pnl"
								radius={[0, 4, 4, 0]}
								onClick={(data) =>
									onToggleTicker((data.payload as { ticker: string }).ticker)
								}
								style={{ cursor: "pointer" }}
							>
								{chartData.map((entry, index) => {
									const isActive = activeTickers.includes(entry.ticker);
									const color =
										entry.pnl >= 0 ? "hsl(var(--profit))" : "hsl(var(--loss))";
									return (
										<Cell
											key={`cell-${index}`}
											fill={isActive ? color : "hsl(var(--muted))"}
											fillOpacity={isActive ? 0.8 : 0.2}
											stroke={isActive ? color : "hsl(var(--border))"}
											strokeWidth={isActive ? 0 : 1}
											strokeDasharray={isActive ? "0" : "4 2"}
										/>
									);
								})}
							</Bar>
						</BarChart>
					</ResponsiveContainer>
				</div>
			</CardContent>
		</Card>
	);
};
