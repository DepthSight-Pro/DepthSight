// frontend/src/components/analytics/DayOfWeekPnlChart.tsx

import { Calendar, MousePointerClick } from "lucide-react";
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

interface DayOfWeekPnlChartProps {
	trades: TradeData[];
	activeDays: number[];
	onToggleDay: (day: number) => void;
}

export const DayOfWeekPnlChart: React.FC<DayOfWeekPnlChartProps> = ({
	trades,
	activeDays,
	onToggleDay,
}) => {
	const { t } = useTranslation("analytics");

	const chartData = useMemo(() => {
		const dayNames = [
			t("days.sun", "Sun"),
			t("days.mon", "Mon"),
			t("days.tue", "Tue"),
			t("days.wed", "Wed"),
			t("days.thu", "Thu"),
			t("days.fri", "Fri"),
			t("days.sat", "Sat"),
		];
		const distribution = dayNames.map((day, i) => ({
			name: day,
			pnl: 0,
			dayIndex: i,
		}));
		trades.forEach((trade) => {
			const dayIdx = new Date(trade.timestamp_close).getDay();
			const realizedPnl = trade.pnl || 0;
			distribution[dayIdx].pnl += realizedPnl;
		});
		// Reorder array so Monday is first
		const mondayFirst = [...distribution.slice(1), distribution[0]];
		return mondayFirst.map((d) => ({ ...d, pnl: Number(d.pnl.toFixed(2)) }));
	}, [trades, t]);

	return (
		<Card>
			<CardHeader className="pb-2">
				<div className="flex items-center justify-between">
					<CardTitle className="flex items-center gap-2 text-base">
						<Calendar className="w-5 h-5 text-primary" />
						{t("dailyPnl", "PnL by day")}
					</CardTitle>
					<div className="flex items-center gap-1.5 text-[10px] text-primary font-bold uppercase tracking-wider bg-primary/10 px-2 py-1 rounded-lg">
						<MousePointerClick className="w-3.5 h-3.5" />
						<span>{t("excludeBadDays", "Exclude bad days")}</span>
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
									fontSize={11}
									tickLine={false}
									axisLine={false}
								/>
								<YAxis
									stroke="hsl(var(--muted-foreground))"
									fontSize={11}
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
										onToggleDay((data.payload as { dayIndex: number }).dayIndex)
									}
									style={{ cursor: "pointer" }}
								>
									{chartData.map((entry, index) => {
										const isActive = activeDays.includes(entry.dayIndex);
										const color =
											entry.pnl >= 0
												? "hsl(var(--primary))"
												: "hsl(var(--loss))";
										return (
											<Cell
												key={`day-${index}`}
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
