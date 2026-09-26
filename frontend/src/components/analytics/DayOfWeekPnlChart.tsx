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

interface CustomDayTooltipProps {
	active?: boolean;
	payload?: Array<{ payload?: { name: string; pnl: number; dayIndex: number } }>;
}

const CustomDayTooltip = ({ active, payload }: CustomDayTooltipProps) => {
	if (!active || !payload?.length || !payload[0]?.payload) return null;
	const data = payload[0].payload;
	const pnl = Number(data.pnl || 0);
	const isProfit = pnl >= 0;

	return (
		<div className="rounded-xl border border-border dark:border-white/15 bg-card/95 dark:bg-[#0b0f17]/95 px-3 py-2 shadow-2xl backdrop-blur-xl font-mono text-popover-foreground">
			<div className="text-[11px] font-semibold text-muted-foreground dark:text-white/70 mb-1">{data.name}</div>
			<div className="flex items-center gap-2 text-xs">
				<span className="text-muted-foreground dark:text-white/50">PnL:</span>
				<span className={`font-bold ${isProfit ? "text-emerald-500 dark:text-emerald-400" : "text-rose-500 dark:text-rose-400"}`}>
					{isProfit ? "+" : ""}${pnl.toFixed(2)}
				</span>
			</div>
		</div>
	);
};

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
		<div className="glass relative rounded-2xl border border-border/80 dark:border-white/10 p-5 shadow-2xl backdrop-blur-xl animate-fade-up">
			<div className="flex items-center justify-between pb-3 mb-2 border-b border-border/60 dark:border-white/5">
				<div className="flex items-center gap-2 text-[13px] font-semibold text-foreground dark:text-white/90">
					<Calendar className="w-4 h-4 text-cyan" />
					{t("dailyPnl", "PnL by day")}
				</div>
				<div className="flex items-center gap-1.5 text-[9px] text-cyan-700 dark:text-cyan/80 font-mono font-bold uppercase tracking-wider bg-cyan-500/10 px-2 py-0.5 rounded-md border border-cyan-500/20">
					<MousePointerClick className="w-3.5 h-3.5" />
					<span>{t("excludeBadDays", "Exclude bad days")}</span>
				</div>
			</div>
			<div>
				<div className="h-[250px]">
					{!trades || trades.length === 0 ? (
						<div className="h-full flex items-center justify-center text-muted-foreground dark:text-white/40 font-mono text-xs">
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
									content={<CustomDayTooltip />}
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
