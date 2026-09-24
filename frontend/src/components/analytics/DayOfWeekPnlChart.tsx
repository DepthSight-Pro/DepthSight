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
		<div className="glass relative rounded-2xl border border-white/10 p-5 shadow-2xl backdrop-blur-xl animate-fade-up">
			<div className="flex items-center justify-between pb-3 mb-2 border-b border-white/5">
				<div className="flex items-center gap-2 text-[13px] font-semibold text-white/90">
					<Calendar className="w-4 h-4 text-cyan" />
					{t("dailyPnl", "PnL by day")}
				</div>
				<div className="flex items-center gap-1.5 text-[9px] text-cyan/80 font-mono font-bold uppercase tracking-wider bg-cyan/10 px-2 py-0.5 rounded-md border border-cyan/20">
					<MousePointerClick className="w-3.5 h-3.5" />
					<span>{t("excludeBadDays", "Exclude bad days")}</span>
				</div>
			</div>
			<div>
				<div className="h-[250px]">
					{!trades || trades.length === 0 ? (
						<div className="h-full flex items-center justify-center text-white/40 font-mono text-xs">
							{t("noData", "No Data")}
						</div>
					) : (
						<ResponsiveContainer width="100%" height="100%">
							<BarChart data={chartData}>
								<CartesianGrid
									strokeDasharray="3 3"
									stroke="rgba(255, 255, 255, 0.05)"
									vertical={false}
								/>
								<XAxis
									dataKey="name"
									stroke="rgba(255, 255, 255, 0.4)"
									fontSize={11}
									fontFamily="monospace"
									tickLine={false}
									axisLine={false}
								/>
								<YAxis
									stroke="rgba(255, 255, 255, 0.4)"
									fontSize={11}
									fontFamily="monospace"
									tickLine={false}
									axisLine={false}
									tickFormatter={(val) => `$${val}`}
								/>
								<Tooltip
									cursor={{ fill: "rgba(255, 255, 255, 0.04)" }}
									contentStyle={{
										backgroundColor: "rgba(7, 8, 11, 0.95)",
										border: "1px solid rgba(255, 255, 255, 0.15)",
										borderRadius: "12px",
										color: "#fff",
										fontFamily: "monospace",
										boxShadow: "0 8px 32px rgba(0, 0, 0, 0.6)",
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
												? "#00d4ff"
												: "#ff3b5c";
										return (
											<Cell
												key={`day-${index}`}
												fill={isActive ? color : "rgba(255, 255, 255, 0.1)"}
												fillOpacity={isActive ? 0.85 : 0.2}
												stroke={isActive ? color : "rgba(255, 255, 255, 0.15)"}
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
			</div>
		</div>
	);
};
