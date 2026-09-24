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
			<div className="glass relative rounded-2xl border border-white/10 p-5 shadow-2xl backdrop-blur-xl animate-fade-up">
				<div className="text-[13px] font-semibold text-white/90 pb-2">
					{t("assetPerformance", "PnL by assets")}
				</div>
				<div className="h-[350px] flex items-center justify-center text-white/40 font-mono text-xs">
					{t("noData", "No Data")}
				</div>
			</div>
		);
	}

	return (
		<div className="glass relative rounded-2xl border border-white/10 p-5 shadow-2xl backdrop-blur-xl animate-fade-up">
			<div className="flex items-center justify-between pb-3 mb-2 border-b border-white/5">
				<div className="flex items-center gap-2 text-[13px] font-semibold text-white/90">
					<BarChart3 className="w-4 h-4 text-cyan" />
					{t("assetPerformance", "PnL by assets")}
				</div>
				<div className="flex items-center gap-1 text-[9px] text-cyan/80 font-mono font-bold uppercase tracking-wider bg-cyan/10 px-2 py-0.5 rounded-md border border-cyan/20">
					<MousePointerClick className="w-3 h-3" />
					<span>{t("toggleCoins", "Toggle Coins")}</span>
				</div>
			</div>
			<div className="h-[350px]">
				<ResponsiveContainer width="100%" height="100%">
					<BarChart layout="vertical" data={chartData}>
						<XAxis type="number" hide />
						<YAxis
							dataKey="ticker"
							type="category"
							stroke="rgba(255, 255, 255, 0.4)"
							fontSize={10}
							fontFamily="monospace"
							width={80}
							tickLine={false}
							axisLine={false}
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
									entry.pnl >= 0 ? "#10e0a0" : "#ff3b5c";
								return (
									<Cell
										key={`cell-${index}`}
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
			</div>
		</div>
	);
};
