// frontend/src/components/analytics/HourlyPnlChart.tsx

import { Clock, MousePointerClick } from "lucide-react";
import type React from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
	Bar,
	BarChart,
	CartesianGrid,
	Cell,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TradeData } from "@/types/api";

interface HourlyPnlChartProps {
	trades: TradeData[];
	activeHours: number[];
	onToggleHour: (hour: number) => void;
}

export const HourlyPnlChart: React.FC<HourlyPnlChartProps> = ({
	trades,
	activeHours,
	onToggleHour,
}) => {
	const { t } = useTranslation("analytics");

	const chartData = useMemo(() => {
		const hours = Array.from({ length: 24 }, (_, i) => ({ hour: i, pnl: 0 }));
		trades.forEach((trade) => {
			const h = new Date(trade.timestamp_close).getHours();
			const realizedPnl = trade.pnl || 0;
			hours[h].pnl += realizedPnl;
		});
		return hours.map((h) => ({
			name: `${h.hour}:00`,
			pnl: Number(h.pnl.toFixed(2)),
			hourIndex: h.hour,
		}));
	}, [trades]);

	return (
		<Card>
			<CardHeader className="pb-2">
				<div className="flex items-center justify-between">
					<CardTitle className="flex items-center gap-2 text-base">
						<Clock className="w-5 h-5 text-primary" />
						{t("hourlyPnl", "PnL by hour")}
					</CardTitle>
					<div className="flex items-center gap-1.5 text-[10px] text-primary font-bold uppercase tracking-wider bg-primary/10 px-2 py-1 rounded-lg">
						<MousePointerClick className="w-3.5 h-3.5" />
						<span>{t("clickToToggle", "Click to Toggle")}</span>
					</div>
				</div>
			</CardHeader>
			<CardContent>
				<div className="h-[250px]">
					{!trades || trades.length === 0 ? (
						<div className="h-full flex items-center justify-center text-muted-foreground">
							{t("noData", "No Data")}
						</div>
					) : (
						<ResponsiveContainer width="100%" height="100%">
							<BarChart data={chartData}>
								<CartesianGrid
									strokeDasharray="3 3"
									stroke="hsl(var(--border))"
									vertical={false}
								/>
								<XAxis
									dataKey="name"
									stroke="hsl(var(--muted-foreground))"
									fontSize={9}
									tickLine={false}
									axisLine={false}
								/>
								<YAxis
									stroke="hsl(var(--muted-foreground))"
									fontSize={9}
									tickLine={false}
									axisLine={false}
									tickFormatter={(val) => `$${val}`}
								/>
								<Tooltip
									cursor={{ fill: "transparent" }}
									contentStyle={{
										backgroundColor: "hsl(var(--card))",
										border: "1px solid hsl(var(--border))",
										borderRadius: "12px",
									}}
									formatter={(value: unknown) => [
										`$${(Number(value) || 0).toFixed(2)}`,
										"PnL",
									]}
								/>
								<Bar
									dataKey="pnl"
									onClick={(data) =>
										onToggleHour(
											(data.payload as { hourIndex: number }).hourIndex,
										)
									}
									style={{ cursor: "pointer" }}
								>
									{chartData.map((entry, index) => {
										const isActive = activeHours.includes(entry.hourIndex);
										const color =
											entry.pnl >= 0
												? "hsl(var(--profit))"
												: "hsl(var(--loss))";
										return (
											<Cell
												key={`hour-${index}`}
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
					)}
				</div>
			</CardContent>
		</Card>
	);
};
