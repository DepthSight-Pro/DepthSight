// src/components/genetic-command-center/EvolutionMonitor.tsx

import {
	Activity,
	BarChart3,
	Clock,
	Cpu,
	HardDrive,
	Layers,
	TrendingUp,
	Users,
} from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
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
import { useSystemResources } from "@/lib/api";
import type { EvolutionState } from "@/types/genetic-types";

interface Props {
	evoState: EvolutionState;
	chartData: Array<{
		name: string;
		best: string;
		avg: string;
	}>;
}

const EvolutionMonitor: React.FC<Props> = ({ evoState, chartData }) => {
	const { t } = useTranslation(["discovery", "common"]);
	const { data: resources } = useSystemResources();

	return (
		<div className="space-y-6 h-full flex flex-col">
			{/* Stats Cards */}
			<div className="grid grid-cols-1 md:grid-cols-4 gap-4">
				<Card>
					<CardContent className="pt-6">
						<div className="flex items-center text-muted-foreground uppercase text-[10px] font-bold tracking-widest mb-2">
							<TrendingUp className="w-3 h-3 mr-2 text-emerald-500" />{" "}
							{t("discovery:monitor.bestFitness", "Best Fitness")}
						</div>
						<div className="text-3xl font-mono font-bold">
							{evoState.bestFitness?.toFixed(4) || "0.0000"}
						</div>
					</CardContent>
				</Card>
				<Card>
					<CardContent className="pt-6">
						<div className="flex items-center text-muted-foreground uppercase text-[10px] font-bold tracking-widest mb-2">
							<Users className="w-3 h-3 mr-2 text-primary" />{" "}
							{t("common:population", "Population")}
						</div>
						<div className="text-3xl font-mono font-bold">
							100{" "}
							<span className="text-sm font-normal text-muted-foreground">
								/ 100
							</span>
						</div>
					</CardContent>
				</Card>
				<Card>
					<CardContent className="pt-6">
						<div className="flex items-center text-muted-foreground uppercase text-[10px] font-bold tracking-widest mb-2">
							<Activity className="w-3 h-3 mr-2 text-primary" />{" "}
							{t("discovery:monitor.generation", "Generation")}
						</div>
						<div className="text-3xl font-mono font-bold">
							{evoState.generation}{" "}
							<span className="text-sm font-normal text-muted-foreground">
								/ 100
							</span>
						</div>
					</CardContent>
				</Card>
				<Card>
					<CardContent className="pt-6">
						<div className="flex items-center text-muted-foreground uppercase text-[10px] font-bold tracking-widest mb-2">
							<BarChart3 className="w-3 h-3 mr-2 text-emerald-500" />{" "}
							{t("common:searchSpace", "Search Space")}
						</div>
						<div className="text-3xl font-mono font-bold">
							{(evoState.generation * 100).toLocaleString()}{" "}
							<span className="text-sm font-normal text-muted-foreground uppercase">
								{t("common:tested", "tested")}
							</span>
						</div>
					</CardContent>
				</Card>
			</div>

			{/* System Resources */}
			{resources && (
				<div className="grid grid-cols-1 md:grid-cols-4 gap-4">
					<Card className="border-primary/20 bg-primary/5">
						<CardContent className="pt-4 pb-4">
							<div className="flex items-center justify-between">
								<div>
									<div className="flex items-center text-muted-foreground uppercase text-[10px] font-bold tracking-widest mb-1">
										<Cpu className="w-3 h-3 mr-2 text-blue-500" /> CPU
									</div>
									<div className="text-2xl font-mono font-bold">
										{resources.system.cpu_percent}%
									</div>
								</div>
								<div className="text-right">
									<div className="text-[10px] text-muted-foreground">Cores</div>
									<div className="text-sm font-mono">
										{resources.system.cpu_count}
									</div>
								</div>
							</div>
							<div className="mt-2 h-1.5 bg-muted rounded-full overflow-hidden">
								<div
									className="h-full bg-blue-500 transition-all duration-500"
									style={{ width: `${resources.system.cpu_percent}%` }}
								/>
							</div>
						</CardContent>
					</Card>

					<Card className="border-primary/20 bg-primary/5">
						<CardContent className="pt-4 pb-4">
							<div className="flex items-center justify-between">
								<div>
									<div className="flex items-center text-muted-foreground uppercase text-[10px] font-bold tracking-widest mb-1">
										<HardDrive className="w-3 h-3 mr-2 text-emerald-500" /> RAM
									</div>
									<div className="text-2xl font-mono font-bold">
										{resources.system.ram_used_gb.toFixed(1)} GB
									</div>
								</div>
								<div className="text-right">
									<div className="text-[10px] text-muted-foreground">Total</div>
									<div className="text-sm font-mono">
										{resources.system.ram_total_gb} GB
									</div>
								</div>
							</div>
							<div className="mt-2 h-1.5 bg-muted rounded-full overflow-hidden">
								<div
									className="h-full bg-emerald-500 transition-all duration-500"
									style={{ width: `${resources.system.ram_percent}%` }}
								/>
							</div>
						</CardContent>
					</Card>

					<Card className="border-primary/20 bg-primary/5">
						<CardContent className="pt-4 pb-4">
							<div className="flex items-center justify-between">
								<div>
									<div className="flex items-center text-muted-foreground uppercase text-[10px] font-bold tracking-widest mb-1">
										<Layers className="w-3 h-3 mr-2 text-amber-500" />{" "}
										{t("discovery:monitor.queue", "Queue")}
									</div>
									<div className="text-2xl font-mono font-bold">
										{resources.queue.running}{" "}
										<span className="text-sm font-normal text-muted-foreground">
											/ {resources.queue.max_concurrent}
										</span>
									</div>
								</div>
								<div className="text-right">
									<div className="text-[10px] text-muted-foreground">
										Pending
									</div>
									<div className="text-sm font-mono">
										{resources.queue.pending}
									</div>
								</div>
							</div>
							<div className="mt-2 text-[10px] text-muted-foreground">
								{resources.queue.cores_per_run} cores per run
							</div>
						</CardContent>
					</Card>

					<Card className="border-primary/20 bg-primary/5">
						<CardContent className="pt-4 pb-4">
							<div className="flex items-center justify-between">
								<div>
									<div className="flex items-center text-muted-foreground uppercase text-[10px] font-bold tracking-widest mb-1">
										<Clock className="w-3 h-3 mr-2 text-purple-500" /> Allocated
									</div>
									<div className="text-2xl font-mono font-bold">
										{resources.queue.total_allocated_cores} cores
									</div>
								</div>
								<div className="text-right">
									<div className="text-[10px] text-muted-foreground">
										Available
									</div>
									<div className="text-sm font-mono">
										{resources.system.cpu_count -
											resources.queue.total_allocated_cores}
									</div>
								</div>
							</div>
							<div className="mt-2 h-1.5 bg-muted rounded-full overflow-hidden">
								<div
									className="h-full bg-purple-500 transition-all duration-500"
									style={{
										width: `${(resources.queue.total_allocated_cores / resources.system.cpu_count) * 100}%`,
									}}
								/>
							</div>
						</CardContent>
					</Card>
				</div>
			)}

			{/* Main Chart */}
			<Card className="flex-1 min-h-[400px]">
				<CardHeader className="pb-2">
					<CardTitle className="text-sm font-bold uppercase tracking-widest flex items-center">
						<TrendingUp className="w-4 h-4 mr-2" />{" "}
						{t("discovery:monitor.title", "Evolution Progress Chart")}
					</CardTitle>
				</CardHeader>
				<CardContent className="h-[calc(100%-60px)]">
					<ResponsiveContainer width="100%" height="100%">
						<AreaChart data={chartData}>
							<defs>
								<linearGradient id="colorBest" x1="0" y1="0" x2="0" y2="1">
									<stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
									<stop offset="95%" stopColor="#10b981" stopOpacity={0} />
								</linearGradient>
								<linearGradient id="colorAvg" x1="0" y1="0" x2="0" y2="1">
									<stop
										offset="5%"
										stopColor="hsl(var(--primary))"
										stopOpacity={0.1}
									/>
									<stop
										offset="95%"
										stopColor="hsl(var(--primary))"
										stopOpacity={0}
									/>
								</linearGradient>
							</defs>
							<CartesianGrid
								strokeDasharray="3 3"
								stroke="hsl(var(--border))"
								vertical={false}
							/>
							<XAxis
								dataKey="name"
								stroke="hsl(var(--muted-foreground))"
								fontSize={10}
								axisLine={false}
								tickLine={false}
							/>
							<YAxis
								stroke="hsl(var(--muted-foreground))"
								fontSize={10}
								axisLine={false}
								tickLine={false}
							/>
							<Tooltip
								contentStyle={{
									backgroundColor: "hsl(var(--card))",
									border: "1px solid hsl(var(--border))",
									borderRadius: "8px",
									fontSize: "12px",
								}}
								itemStyle={{ fontWeight: "bold" }}
							/>
							<Area
								type="monotone"
								dataKey="best"
								stroke="#10b981"
								strokeWidth={3}
								fillOpacity={1}
								fill="url(#colorBest)"
								name={t("discovery:monitor.bestFitness", "Best Fitness")}
							/>
							<Area
								type="monotone"
								dataKey="avg"
								stroke="hsl(var(--primary))"
								strokeWidth={2}
								strokeDasharray="5 5"
								fillOpacity={1}
								fill="url(#colorAvg)"
								name={t("discovery:monitor.avgFitness", "Average Fitness")}
							/>
						</AreaChart>
					</ResponsiveContainer>
				</CardContent>
			</Card>
		</div>
	);
};

export default EvolutionMonitor;
