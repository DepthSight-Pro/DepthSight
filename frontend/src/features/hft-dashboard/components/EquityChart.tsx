// src/features/hft-dashboard/components/EquityChart.tsx

import { format } from "date-fns";
import * as LucideIcons from "lucide-react";
import { TrendingUp } from "lucide-react";
import type React from "react";
import { useMemo } from "react";
import {
	Area,
	AreaChart,
	CartesianGrid,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { usePortfolioStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useHftStore } from "../hooks/useHftStore";

interface CompactStatProps {
	label: string;
	value: string;
	subValue?: string;
	icon: string;
	colorClass: string;
}

const CompactStat = ({
	label,
	value,
	subValue,
	icon: IconName,
	colorClass,
}: CompactStatProps) => {
	const Icon = (
		LucideIcons as unknown as Record<
			string,
			React.ComponentType<{ size?: number; className?: string }>
		>
	)[IconName];
	const textColor = colorClass.replace("bg-", "text-");
	return (
		<div className="bg-card/30 border border-border/20 p-4 rounded-xl flex flex-col gap-1 min-w-0 transition-all hover:bg-card/50 hover:border-border/40 group">
			<div className="flex items-center justify-between mb-1">
				<span className="text-xs uppercase font-black text-muted-foreground/40 truncate tracking-widest leading-none">
					{label}
				</span>
				{Icon && (
					<Icon
						size={14}
						className="opacity-20 group-hover:opacity-50 transition-opacity"
					/>
				)}
			</div>
			<div className="flex flex-col">
				<span
					className={cn(
						"text-xl font-black font-mono tracking-tighter leading-none filter drop-shadow-[0_0_8px_rgba(0,0,0,0.5)]",
						textColor,
					)}
				>
					{value}
				</span>
				{subValue && (
					<div className="flex items-center gap-1 mt-2">
						<div
							className={cn(
								"w-1 h-1 rounded-full animate-pulse",
								textColor.replace("text-", "bg-"),
							)}
						></div>
						<span className="text-[10px] text-muted-foreground/50 truncate font-bold uppercase tracking-tight">
							{subValue}
						</span>
					</div>
				)}
			</div>
		</div>
	);
};

export const EquityChart: React.FC = () => {
	const { equityHistory, selectedApiKeyId } = useHftStore();

	// Fetch real-time portfolio status for the selected API key to provide immediate balance feedback
	const { data: portfolio } = usePortfolioStatus({
		mode: "live",
		apiKeyId: selectedApiKeyId || undefined,
	});

	// Calculate metrics from latest data
	const lastSummary = equityHistory[equityHistory.length - 1] || {
		equity: 0,
		unrealized_pnl: 0,
		balance: 0,
	};

	// Fallback to API balance if bot hasn't reported equity yet
	const displayEquity =
		lastSummary.equity > 0 ? lastSummary.equity : portfolio?.balance || 0;
	const equityVal = displayEquity;
	const pnlVal = lastSummary.unrealized_pnl;

	// Prepare chart data with unique timestamps to avoid Recharts key warnings
	const chartData = useMemo(() => {
		const uniqueData = new Map<number, { time: number; equity: number }>();
		equityHistory.forEach((p) => {
			uniqueData.set(p.timestamp * 1000, {
				time: p.timestamp * 1000,
				equity: p.equity,
			});
		});
		return Array.from(uniqueData.values()).sort((a, b) => a.time - b.time);
	}, [equityHistory]);

	return (
		<div className="flex flex-col gap-1.5 p-2 h-full overflow-hidden">
			{/* Stats Cards - Enlarged for better readability */}
			<div className="grid grid-cols-2 lg:grid-cols-4 gap-2 shrink-0">
				<CompactStat
					label="Total Equity"
					value={`$${equityVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
					icon="DollarSign"
					colorClass="text-cyan-500"
					subValue="USDT Bal"
				/>
				<CompactStat
					label="Unrealized PnL"
					value={`${pnlVal >= 0 ? "+" : ""}$${pnlVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
					icon="TrendingUp"
					colorClass={pnlVal >= 0 ? "text-emerald-500" : "text-rose-500"}
					subValue="Open Pos"
				/>
				<CompactStat
					label="Exposure"
					value={`$${(lastSummary.total_exposure || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
					icon="Zap"
					colorClass="text-violet-500"
					subValue={`x${((lastSummary.total_exposure || 0) / (lastSummary.equity || 1)).toFixed(1)} Lev`}
				/>
				<CompactStat
					label="Drawdown"
					value={`${(lastSummary.drawdown_pct || 0).toFixed(2)}%`}
					icon="Activity"
					colorClass={
						(lastSummary.drawdown_pct || 0) > 2
							? "text-amber-500"
							: "text-cyan-500"
					}
					subValue="Sess Peak"
				/>
			</div>

			{/* Chart */}
			<Card className="flex-1 min-h-0 flex flex-col border-border/40 shadow-sm">
				<CardHeader className="py-1 px-3 border-b border-border/40">
					<CardTitle className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
						<TrendingUp className="w-3 h-3 text-cyan-500" />
						Equity Performance Stream
					</CardTitle>
				</CardHeader>
				<CardContent className="flex-1 min-h-0 pt-4 pb-2">
					<ResponsiveContainer width="100%" height="100%">
						<AreaChart data={chartData}>
							<defs>
								<linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
									<stop offset="5%" stopColor="#06b6d4" stopOpacity={0.2} />
									<stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
								</linearGradient>
							</defs>
							<CartesianGrid
								strokeDasharray="3 3"
								stroke="hsl(var(--border) / 0.3)"
							/>
							<XAxis
								dataKey="time"
								type="number"
								domain={["dataMin", "dataMax"]}
								scale="time"
								stroke="#71717a"
								fontSize={10}
								tickLine={false}
								axisLine={false}
								tickFormatter={(unixTime) =>
									format(new Date(unixTime), "HH:mm:ss")
								}
							/>
							<YAxis
								stroke="#71717a"
								fontSize={10}
								tickLine={false}
								axisLine={false}
								domain={["auto", "auto"]}
								width={60}
								tickFormatter={(value) => `$${value}`}
							/>
							<Tooltip
								contentStyle={{
									backgroundColor: "#09090b",
									borderColor: "#27272a",
									borderRadius: "0.5rem",
									fontSize: "12px",
								}}
								labelFormatter={(label) => format(new Date(label), "HH:mm:ss")}
								formatter={(value: unknown) => {
									const num =
										typeof value === "number"
											? value
											: parseFloat(String(value)) || 0;
									return [`$${num.toFixed(2)}`, "Equity"];
								}}
							/>
							<Area
								type="monotone"
								dataKey="equity"
								stroke="#06b6d4"
								strokeWidth={2}
								fillOpacity={1}
								fill="url(#equityGradient)"
								isAnimationActive={false}
							/>
						</AreaChart>
					</ResponsiveContainer>
				</CardContent>
			</Card>
		</div>
	);
};
