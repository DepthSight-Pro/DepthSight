// src/components/community/NodeLeaderboard.tsx

import React, { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
	Trophy,
	Globe,
	Lock,
	ChevronDown,
	ChevronUp,
	ArrowUpDown,
	ExternalLink,
	Zap,
	Clock,
	Users,
	Coins,
	TrendingUp,
	Shield,
	Server,
	Award,
	Layers,
	Check,
	Sparkles,
} from "lucide-react";
import {
	Card,
	CardContent,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { AdminPlanItem } from "@/types/api";

export interface LeaderboardNode {
	name: string;
	latitude?: number;
	longitude?: number;
	city?: string;
	country?: string;
	latency_ms?: number;
	version?: string;
	is_master: boolean;
	// Extended fields for leaderboard
	user_reward_share_percent?: number;
	public_domain?: string;
	uptime_percent?: number;
	active_miners?: number;
	total_mined?: number;
	is_mining_server?: boolean;
	created_at?: string;
	public_plans?: Record<string, AdminPlanItem>;
}

type SortKey = "reward" | "uptime" | "latency" | "mined" | "pro_price";
type SortDir = "asc" | "desc";

// Default baseline plans for nodes that have not customized their tiers yet
export const DEFAULT_NODE_PLANS: Record<string, AdminPlanItem> = {
	free: {
		name: "Free",
		price_usd: 0,
		active: true,
		description: "Basic capabilities and standard strategy blocks.",
		features: ["20 fast backtests per day", "Standard blocks (Logic, Indicators, Proximity)", "Limited history (90 days)", "10 AI Assistant queries per day"],
		quotas: {
			run_vector_backtest_per_day: 20,
			use_ai_assistant_per_day: 10,
		},
		limits: {
			allow_real_trading: false,
			max_live_strategies: 0,
			max_backtest_duration_days: 90,
		},
	},
	standard: {
		name: "Standard",
		price_usd: 19,
		active: true,
		description: "For active traders. Live trading and standard blocks.",
		features: ["50 backtests per day", "35 AI Assistant queries per day", "Live trading enabled", "10 live trading strategies"],
		quotas: {
			run_vector_backtest_per_day: 50,
			use_ai_assistant_per_day: 35,
		},
		limits: {
			allow_real_trading: true,
			max_live_strategies: 10,
			max_backtest_duration_days: 365,
		},
	},
	pro: {
		name: "Professional",
		price_usd: 49,
		active: true,
		description: "Maximum power. Access to all PRO blocks and genetic search.",
		features: ["Unlimited backtests", "50 AI Assistant queries per day", "Access to PRO blocks (Tape, Book, OI)", "30 live trading strategies"],
		quotas: {
			run_vector_backtest_per_day: -1,
			use_ai_assistant_per_day: 50,
		},
		limits: {
			allow_real_trading: true,
			max_live_strategies: 30,
			max_backtest_duration_days: -1,
			allow_intracandle_triggers: true,
		},
		billing: {
			lifetime: {
				enabled: true,
				price_usd: 99,
				slot_limit: 50,
			},
		},
	},
};


// Country code to flag emoji mapping
const countryFlags: Record<string, string> = {
	Germany: "🇩🇪",
	DE: "🇩🇪",
	"United States": "🇺🇸",
	US: "🇺🇸",
	Singapore: "🇸🇬",
	SG: "🇸🇬",
	Japan: "🇯🇵",
	JP: "🇯🇵",
	Australia: "🇦🇺",
	AU: "🇦🇺",
	"United Kingdom": "🇬🇧",
	GB: "🇬🇧",
	Canada: "🇨🇦",
	CA: "🇨🇦",
	Netherlands: "🇳🇱",
	NL: "🇳🇱",
	France: "🇫🇷",
	FR: "🇫🇷",
	Finland: "🇫🇮",
	FI: "🇫🇮",
	Ukraine: "🇺🇦",
	UA: "🇺🇦",
	Poland: "🇵🇱",
	PL: "🇵🇱",
	"South Korea": "🇰🇷",
	KR: "🇰🇷",
	India: "🇮🇳",
	IN: "🇮🇳",
	Brazil: "🇧🇷",
	BR: "🇧🇷",
	Russia: "🇷🇺",
	RU: "🇷🇺",
};

function getFlag(country?: string): string {
	if (!country) return "🌍";
	return countryFlags[country] || "🌍";
}

function getRewardColor(pct: number): string {
	if (pct >= 85) return "text-emerald-400 border-emerald-500/30";
	if (pct >= 75) return "text-blue-400 border-blue-500/30";
	if (pct >= 60) return "text-amber-400 border-amber-500/30";
	return "text-rose-400 border-rose-500/30";
}

function getRewardBg(pct: number): string {
	if (pct >= 85) return "bg-emerald-500/10";
	if (pct >= 75) return "bg-blue-500/10";
	if (pct >= 60) return "bg-amber-500/10";
	return "bg-rose-500/10";
}

function getUptimeColor(pct: number): string {
	if (pct >= 99.5) return "text-emerald-400";
	if (pct >= 98.0) return "text-blue-400";
	if (pct >= 95.0) return "text-amber-400";
	return "text-rose-400";
}

function getLatencyColor(ms?: number): string {
	if (!ms) return "text-muted-foreground";
	if (ms < 50) return "text-emerald-400";
	if (ms < 120) return "text-blue-400";
	if (ms < 250) return "text-amber-400";
	return "text-rose-400";
}

function getRankDisplay(rank: number): React.ReactNode {
	if (rank === 1) {
		return (
			<span className="flex items-center justify-center w-6 h-6 rounded-full bg-amber-400/20 text-amber-300 font-bold text-xs border border-amber-400/40">
				🥇
			</span>
		);
	}
	if (rank === 2) {
		return (
			<span className="flex items-center justify-center w-6 h-6 rounded-full bg-slate-400/20 text-slate-300 font-bold text-xs border border-slate-400/40">
				🥈
			</span>
		);
	}
	if (rank === 3) {
		return (
			<span className="flex items-center justify-center w-6 h-6 rounded-full bg-amber-700/20 text-amber-600 font-bold text-xs border border-amber-700/40">
				🥉
			</span>
		);
	}
	return (
		<span className="text-xs font-mono text-muted-foreground w-6 text-center">
			#{rank}
		</span>
	);
}

function getNodePlans(node: LeaderboardNode): Record<string, AdminPlanItem> {
	if (node.public_plans && Object.keys(node.public_plans).length > 0) {
		return node.public_plans;
	}
	return DEFAULT_NODE_PLANS;
}

function getProPlanPrice(node: LeaderboardNode): number {
	const plans = getNodePlans(node);
	if (plans.pro?.price_usd !== undefined) return plans.pro.price_usd;
	if (plans.standard?.price_usd !== undefined) return plans.standard.price_usd;
	return 999;
}

function processLeaderboardData(activeNodes: LeaderboardNode[]) {
	const masterHub: LeaderboardNode = {
		name: "Central Master Hub",
		city: "Lauterbourg",
		country: "France",
		latency_ms: 0,
		version: "v0.5.0",
		is_master: true,
		user_reward_share_percent: 75,
		public_domain: "app.depthsight.pro",
		uptime_percent: 99.99,
		active_miners: 0,
		total_mined: 0.0,
		is_mining_server: true,
		created_at: "2025-06-01T00:00:00Z",
		public_plans: DEFAULT_NODE_PLANS,
	};

	const hasMaster = activeNodes.some((n) => n.is_master);
	const allNodes = hasMaster ? [...activeNodes] : [masterHub, ...activeNodes];

	const publicCount = allNodes.filter(
		(n) => Boolean(n.public_domain) || n.is_master,
	).length;
	const privateCount = allNodes.filter(
		(n) => !Boolean(n.public_domain) && !n.is_master,
	).length;

	return { allNodes, publicCount, privateCount };
}

// Sort button component
const SortButton: React.FC<{
	label: string;
	sortKey: SortKey;
	currentSort: SortKey;
	currentDir: SortDir;
	onSort: (key: SortKey) => void;
}> = ({ label, sortKey, currentSort, currentDir, onSort }) => (
	<button
		onClick={() => onSort(sortKey)}
		className={cn(
			"flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-bold uppercase tracking-wider transition-all",
			currentSort === sortKey
				? "bg-primary/15 text-primary border border-primary/30"
				: "text-muted-foreground hover:text-foreground hover:bg-muted/30 border border-transparent",
		)}
	>
		{label}
		{currentSort === sortKey && (
			<span className="text-primary">
				{currentDir === "desc" ? (
					<ChevronDown className="w-3 h-3" />
				) : (
					<ChevronUp className="w-3 h-3" />
				)}
			</span>
		)}
	</button>
);

// Expanded row detail (Option 1: Rich Plan Cards Accordion)
const NodeDetailRow: React.FC<{
	node: LeaderboardNode;
	isRu: boolean;
}> = ({ node, isRu }) => {
	const nodePlans = getNodePlans(node);

	return (
		<motion.div
			initial={{ opacity: 0, height: 0 }}
			animate={{ opacity: 1, height: "auto" }}
			exit={{ opacity: 0, height: 0 }}
			transition={{ duration: 0.2 }}
			className="overflow-hidden bg-muted/10 border-t border-border/10"
		>
			<div className="px-4 pb-5 pt-3 space-y-4">
				{/* 4 Node Telemetry Cards */}
				<div className="grid grid-cols-2 md:grid-cols-4 gap-3">
					<div className="p-2.5 rounded-lg bg-background/50 border border-border/30 shadow-sm">
						<div className="text-[9px] uppercase font-mono tracking-wider text-muted-foreground flex items-center gap-1 mb-1">
							<Coins className="w-3 h-3 text-amber-400" />
							{isRu ? "Всего добыто" : "All-time Mined"}
						</div>
						<div className="text-sm font-black font-mono text-amber-400">
							{(node.total_mined || 0).toLocaleString("en-US", {
								maximumFractionDigits: 0,
							})}{" "}
							<span className="text-[10px] text-muted-foreground">
								$DEPTH
							</span>
						</div>
					</div>
					<div className="p-2.5 rounded-lg bg-background/50 border border-border/30 shadow-sm">
						<div className="text-[9px] uppercase font-mono tracking-wider text-muted-foreground flex items-center gap-1 mb-1">
							<Users className="w-3 h-3 text-blue-400" />
							{isRu ? "Активных майнеров" : "Active Miners"}
						</div>
						<div className="text-sm font-black font-mono text-foreground">
							{node.active_miners || 0}
						</div>
					</div>
					<div className="p-2.5 rounded-lg bg-background/50 border border-border/30 shadow-sm">
						<div className="text-[9px] uppercase font-mono tracking-wider text-muted-foreground flex items-center gap-1 mb-1">
							<Clock className="w-3 h-3 text-indigo-400" />
							{isRu ? "Работает с" : "Online Since"}
						</div>
						<div className="text-sm font-bold font-mono text-foreground">
							{node.created_at
								? new Date(node.created_at).toLocaleDateString(
										isRu ? "ru-RU" : "en-US",
										{
											month: "short",
											day: "numeric",
											year: "numeric",
										},
									)
								: "—"}
						</div>
					</div>
					<div className="p-2.5 rounded-lg bg-background/50 border border-border/30 shadow-sm">
						<div className="text-[9px] uppercase font-mono tracking-wider text-muted-foreground flex items-center gap-1 mb-1">
							<Server className="w-3 h-3 text-emerald-400" />
							{isRu ? "Версия" : "Version"}
						</div>
						<div className="text-sm font-bold font-mono text-foreground">
							v{node.version || "—"}
						</div>
					</div>
				</div>

				{/* Option 1: Node Subscription Plans & Pricing Cards */}
				<div className="pt-2 space-y-3">
					<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/20 pb-2">
						<div className="flex items-center gap-2">
							<div className="p-1 rounded bg-primary/10 text-primary">
								<Layers className="w-4 h-4" />
							</div>
							<span className="text-xs font-bold uppercase tracking-wider text-foreground">
								{isRu ? "Тарифные планы и расценки ноды" : "Node Subscription Plans & Pricing"}
							</span>
							<Badge variant="outline" className="text-[9px] border-primary/30 text-primary bg-primary/5">
								{Object.keys(nodePlans).length} {isRu ? "тарифов" : "tiers"}
							</Badge>
						</div>
						{node.public_domain && (
							<a
								href={`https://${node.public_domain}`}
								target="_blank"
								rel="noopener noreferrer"
								className="text-[11px] text-primary hover:underline flex items-center gap-1 font-mono"
							>
								{isRu ? "Открыть веб-интерфейс ноды" : "Open Node Web App"}
								<ExternalLink className="w-3 h-3" />
							</a>
						)}
					</div>

					{/* Plan Cards Grid */}
					<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
						{Object.entries(nodePlans).map(([planKey, plan]) => {
							const isPro = planKey === "pro" || planKey === "ultra";
							const isLifetime = plan.billing?.lifetime?.enabled;
							const price = plan.price_usd ?? 0;

							return (
								<Card
									key={planKey}
									className={cn(
										"border relative flex flex-col justify-between p-3.5 bg-card/60 backdrop-blur-sm transition-all rounded-lg",
										isPro ? "border-primary/50 shadow-md bg-primary/[0.04]" : "border-border/40 hover:border-border/80",
										!plan.active && "opacity-60",
									)}
								>
									{isPro && (
										<div className="absolute top-0 right-0 bg-primary text-primary-foreground text-[8px] font-bold uppercase px-2 py-0.5 rounded-bl rounded-tr-lg flex items-center gap-1">
											<Sparkles className="w-2.5 h-2.5" />
											Popular
										</div>
									)}

									<div className="space-y-3">
										<div className="flex justify-between items-start">
											<div>
												<span className="text-sm font-bold text-foreground block">{plan.name}</span>
												<span className="text-[10px] text-muted-foreground line-clamp-1">
													{plan.description || "Subscription tier"}
												</span>
											</div>
											<div className="text-right">
												<span className="text-xl font-black text-primary">${price}</span>
												<span className="text-[9px] text-muted-foreground block font-mono">/month</span>
											</div>
										</div>

										{isLifetime && (
											<div className="text-[9px] bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-1 rounded flex items-center justify-between font-mono">
												<span>⚡ Lifetime Slot:</span>
												<span className="font-bold">${plan.billing?.lifetime?.price_usd}</span>
											</div>
										)}

										{/* Quotas & Operational Limits */}
										<div className="text-[10px] bg-background/50 border border-border/20 p-2.5 rounded space-y-1 font-mono">
											<div className="flex justify-between text-muted-foreground">
												<span>Backtests:</span>
												<span className="font-semibold text-foreground">
													{plan.quotas?.run_vector_backtest_per_day === -1
														? "Unlimited"
														: `${plan.quotas?.run_vector_backtest_per_day ?? 0}/day`}
												</span>
											</div>
											<div className="flex justify-between text-muted-foreground">
												<span>AI Queries:</span>
												<span className="font-semibold text-foreground">
													{plan.quotas?.use_ai_assistant_per_day === -1
														? "Unlimited"
														: `${plan.quotas?.use_ai_assistant_per_day ?? 0}/day`}
												</span>
											</div>
											<div className="flex justify-between text-muted-foreground">
												<span>Live Bots:</span>
												<span className="font-semibold text-foreground">
													{plan.limits?.allow_real_trading
														? `${plan.limits?.max_live_strategies ?? 1} bots`
														: "Sim only"}
												</span>
											</div>
											<div className="flex justify-between text-muted-foreground">
												<span>History Depth:</span>
												<span className="font-semibold text-foreground">
													{plan.limits?.max_backtest_duration_days === -1
														? "Full history"
														: `${plan.limits?.max_backtest_duration_days ?? 90} days`}
												</span>
											</div>
										</div>

										{/* Feature Checklist */}
										{(plan.features || []).length > 0 && (
											<ul className="text-[10px] space-y-1">
												{(plan.features || []).slice(0, 3).map((feat, fi) => (
													<li key={fi} className="flex items-center gap-1.5 text-muted-foreground">
														<Check className="w-3 h-3 text-emerald-400 shrink-0" />
														<span className="truncate">{feat}</span>
													</li>
												))}
											</ul>
										)}
									</div>

									{/* Action Button */}
									<div className="pt-3 mt-2 border-t border-border/20">
										{node.public_domain ? (
											<a
												href={`https://${node.public_domain}`}
												target="_blank"
												rel="noopener noreferrer"
												className="block w-full"
											>
												<Button
													size="sm"
													variant={isPro ? "default" : "outline"}
													className="w-full text-xs h-7 gap-1 font-semibold"
												>
													{isRu ? "Подключиться" : "Subscribe on Node"}
													<ExternalLink className="w-3 h-3" />
												</Button>
											</a>
										) : node.is_master ? (
											<Button
												size="sm"
												variant={isPro ? "default" : "outline"}
												className="w-full text-xs h-7 gap-1 font-semibold"
											>
												{isRu ? "Тариф хаба" : "Hub Plan"}
											</Button>
										) : (
											<Button
												size="sm"
												variant="secondary"
												disabled
												className="w-full text-xs h-7 opacity-50"
											>
												<Lock className="w-3 h-3 mr-1" />
												{isRu ? "Приватный узел" : "Private Node"}
											</Button>
										)}
									</div>
								</Card>
							);
						})}
					</div>
				</div>
			</div>
		</motion.div>
	);
};

// Main Component
export const NodeLeaderboard: React.FC<{
	activeNodes: LeaderboardNode[];
	isRu: boolean;
	t: (key: string, fallback?: string) => string;
}> = ({ activeNodes, isRu, t }) => {
	const [sortKey, setSortKey] = useState<SortKey>("reward");
	const [sortDir, setSortDir] = useState<SortDir>("desc");
	const [expandedNode, setExpandedNode] = useState<string | null>(null);

	const { allNodes, publicCount, privateCount } = useMemo(
		() => processLeaderboardData(activeNodes),
		[activeNodes],
	);

	const sortedNodes = useMemo(() => {
		const nodes = [...allNodes];
		nodes.sort((a, b) => {
			let av: number, bv: number;
			switch (sortKey) {
				case "reward":
					av = a.user_reward_share_percent || 0;
					bv = b.user_reward_share_percent || 0;
					break;
				case "uptime":
					av = a.uptime_percent || 0;
					bv = b.uptime_percent || 0;
					break;
				case "latency":
					av = a.latency_ms || 0;
					bv = b.latency_ms || 0;
					break;
				case "mined":
					av = a.total_mined || 0;
					bv = b.total_mined || 0;
					break;
				case "pro_price":
					av = getProPlanPrice(a);
					bv = getProPlanPrice(b);
					break;
				default:
					return 0;
			}
			return sortDir === "desc" ? bv - av : av - bv;
		});
		return nodes;
	}, [allNodes, sortKey, sortDir]);

	const handleSort = (key: SortKey) => {
		if (sortKey === key) {
			setSortDir((d) => (d === "desc" ? "asc" : "desc"));
		} else {
			setSortKey(key);
			// Latency and Pro Price default to ascending (cheapest / fastest first)
			setSortDir(key === "latency" || key === "pro_price" ? "asc" : "desc");
		}
	};

	const toggleExpand = (name: string) => {
		setExpandedNode((prev) => (prev === name ? null : name));
	};

	return (
		<div className="space-y-4">
			{/* Nodes Leaderboard Table */}
			<Card className="border border-border/30 bg-card/25 backdrop-blur-sm overflow-hidden shadow-sm">
				<CardHeader className="pb-3 border-b border-border/10">
					<div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
						<div className="flex items-center gap-3">
							<div className="p-2 rounded-lg bg-primary/10 border border-primary/20">
								<Trophy className="w-4.5 h-4.5 text-primary" />
							</div>
							<div>
								<CardTitle className="text-sm font-bold tracking-tight text-foreground/90 flex items-center gap-2">
									<Globe className="w-4 h-4 text-emerald-400" />
									{t(
										"community:network.leaderboard.publicTitle",
										"Federation Node Leaderboard & Marketplace",
									)}
									<Badge
										variant="outline"
										className="text-[9px] h-4 border-primary/30 text-primary bg-primary/5 px-1.5 uppercase tracking-wider font-bold"
									>
										{allNodes.length}
									</Badge>
									{privateCount > 0 && (
										<Badge
											variant="secondary"
											className="text-[9px] h-4 bg-amber-500/10 text-amber-400 border-amber-500/20 px-1.5 font-mono flex items-center gap-1"
										>
											<Lock className="w-2.5 h-2.5" />
											{privateCount}{" "}
											{isRu ? "приватных" : "private"}
										</Badge>
									)}
								</CardTitle>
								<p className="text-[10px] text-muted-foreground mt-0.5 font-mono">
									{t(
										"community:network.leaderboard.publicDesc",
										"Compare federation nodes by mining yields, latency, and subscription pricing",
									)}
								</p>
							</div>
						</div>

						{/* Sort controls */}
						<div className="flex items-center gap-1.5 flex-wrap">
							<ArrowUpDown className="w-3 h-3 text-muted-foreground mr-0.5" />
							<SortButton
								label={isRu ? "Награда" : "Reward"}
								sortKey="reward"
								currentSort={sortKey}
								currentDir={sortDir}
								onSort={handleSort}
							/>
							<SortButton
								label={isRu ? "Цена Pro" : "Pro Price"}
								sortKey="pro_price"
								currentSort={sortKey}
								currentDir={sortDir}
								onSort={handleSort}
							/>
							<SortButton
								label={isRu ? "Аптайм" : "Uptime"}
								sortKey="uptime"
								currentSort={sortKey}
								currentDir={sortDir}
								onSort={handleSort}
							/>
							<SortButton
								label={isRu ? "Задержка" : "Latency"}
								sortKey="latency"
								currentSort={sortKey}
								currentDir={sortDir}
								onSort={handleSort}
							/>
							<SortButton
								label={isRu ? "Добыто" : "Mined"}
								sortKey="mined"
								currentSort={sortKey}
								currentDir={sortDir}
								onSort={handleSort}
							/>
						</div>
					</div>
				</CardHeader>

				<CardContent className="p-0">
					{/* Table Header */}
					<div className="hidden md:grid grid-cols-[2.5rem_1.4fr_1fr_5.5rem_5.5rem_5rem_5.5rem] gap-2 px-4 py-2.5 border-b border-border/10 text-[9px] font-mono uppercase tracking-wider text-muted-foreground">
						<div className="text-center">#</div>
						<div>{isRu ? "Нода и Тарифы" : "Node & Plans"}</div>
						<div>{isRu ? "Локация" : "Location"}</div>
						<div className="text-center">{isRu ? "Награда" : "Reward"}</div>
						<div className="text-center">{isRu ? "Аптайм" : "Uptime"}</div>
						<div className="text-center">{isRu ? "Пинг" : "Ping"}</div>
						<div className="text-center">{isRu ? "Майнеры" : "Miners"}</div>
					</div>

					{/* Rows */}
					<TooltipProvider delayDuration={200}>
						<div className="divide-y divide-border/10">
							{sortedNodes.map((node, idx) => {
								const rank = idx + 1;
								const isExpanded = expandedNode === node.name;
								const isPrivate = !node.public_domain && !node.is_master;
								const nodePlans = getNodePlans(node);

								return (
									<div key={node.name}>
										{/* Main Row */}
										<motion.div
											initial={{ opacity: 0, y: 8 }}
											animate={{ opacity: 1, y: 0 }}
											transition={{ delay: idx * 0.03 }}
											onClick={() => toggleExpand(node.name)}
											className={cn(
												"grid grid-cols-1 md:grid-cols-[2.5rem_1.4fr_1fr_5.5rem_5.5rem_5rem_5.5rem] gap-2 px-4 py-3 cursor-pointer transition-all group",
												isExpanded ? "bg-primary/5" : "hover:bg-muted/20",
												rank <= 3 && "border-l-2 border-l-transparent hover:border-l-primary/40",
												rank === 1 && "border-l-amber-400/50",
											)}
										>
											{/* Rank */}
											<div className="flex items-center justify-center">
												{getRankDisplay(rank)}
											</div>

											{/* Node Name, Domain & Option 4 Mini Plan Badges */}
											<div className="flex flex-col min-w-0 justify-center">
												<div className="flex items-center gap-1.5 flex-wrap">
													<span className="text-xs font-bold text-foreground group-hover:text-primary transition-colors truncate">
														{node.name}
													</span>
													{node.is_master && (
														<Tooltip>
															<TooltipTrigger asChild>
																<Badge className="text-[8px] h-3.5 bg-blue-500/10 text-blue-400 border-blue-500/20 px-1 py-0">
																	★ Master
																</Badge>
															</TooltipTrigger>
															<TooltipContent className="text-[10px]">
																{isRu
																	? "Центральный хаб федерации"
																	: "Central Federation Hub"}
															</TooltipContent>
														</Tooltip>
													)}
													{isPrivate && (
														<Tooltip>
															<TooltipTrigger asChild>
																<Badge className="text-[8px] h-3.5 bg-amber-500/10 text-amber-400 border-amber-500/20 px-1 py-0 flex items-center gap-0.5 font-mono">
																	<Lock className="w-2.5 h-2.5" />
																	{isRu ? "Приватная" : "Private"}
																</Badge>
															</TooltipTrigger>
															<TooltipContent className="text-[10px]">
																{isRu
																	? "Локальный/приватный узел без открытого домена"
																	: "Self-hosted private node"}
															</TooltipContent>
														</Tooltip>
													)}
												</div>

												{node.public_domain ? (
													<span className="text-[10px] font-mono text-muted-foreground truncate">
														{node.public_domain}
													</span>
												) : isPrivate ? (
													<span className="text-[10px] font-mono text-muted-foreground/60 truncate flex items-center gap-1">
														<Lock className="w-2.5 h-2.5 text-amber-400/70" />
														{isRu ? "Приватная нода" : "Private Node"}
													</span>
												) : null}

												{/* Option 4: Mini-Badges with Plan Prices & Quick Tooltips */}
												<div className="flex items-center gap-1 mt-1.5 flex-wrap">
													{Object.entries(nodePlans).slice(0, 4).map(([planKey, plan]) => {
														const isPro = planKey === "pro" || planKey === "ultra";
														const isFree = plan.price_usd === 0;
														const isLifetime = plan.billing?.lifetime?.enabled;

														return (
															<Tooltip key={planKey}>
																<TooltipTrigger asChild>
																	<span
																		className={cn(
																			"text-[9px] font-mono px-1.5 py-0.5 rounded border transition-all flex items-center gap-1",
																			isFree && "bg-muted/40 text-muted-foreground border-border/40",
																			isPro && "bg-purple-500/10 text-purple-400 border-purple-500/30 font-bold",
																			!isFree && !isPro && "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
																		)}
																	>
																		<span className="uppercase text-[8px]">{plan.name}:</span>
																		<span className="font-bold">${plan.price_usd}</span>
																		{isLifetime && (
																			<span className="text-[8px] text-amber-400 border-l border-border/40 pl-1">
																				⚡${plan.billing?.lifetime?.price_usd}
																			</span>
																		)}
																	</span>
																</TooltipTrigger>
																<TooltipContent className="text-xs p-2.5 max-w-xs space-y-1.5 bg-popover/95 backdrop-blur-sm border shadow-lg">
																	<div className="font-bold flex items-center justify-between gap-2 border-b border-border/20 pb-1">
																		<span className="flex items-center gap-1">
																			<Zap className="w-3 h-3 text-primary" />
																			{plan.name} Tier
																		</span>
																		<span className="text-primary font-mono">${plan.price_usd}/mo</span>
																	</div>
																	<p className="text-[10px] text-muted-foreground">
																		{plan.description || "Node subscription plan"}
																	</p>
																	<div className="text-[10px] font-mono space-y-0.5 bg-muted/30 p-1.5 rounded">
																		<div>
																			Backtests:{" "}
																			{plan.quotas?.run_vector_backtest_per_day === -1
																				? "Unlimited"
																				: `${plan.quotas?.run_vector_backtest_per_day ?? 0}/day`}
																		</div>
																		<div>
																			AI Queries:{" "}
																			{plan.quotas?.use_ai_assistant_per_day === -1
																				? "Unlimited"
																				: `${plan.quotas?.use_ai_assistant_per_day ?? 0}/day`}
																		</div>
																		<div>
																			Live Bots:{" "}
																			{plan.limits?.allow_real_trading
																				? `${plan.limits?.max_live_strategies ?? 1} active bots`
																				: "Simulation only"}
																		</div>
																	</div>
																</TooltipContent>
															</Tooltip>
														);
													})}
												</div>
											</div>

											{/* Location */}
											<div className="flex items-center gap-1.5">
												<span className="text-sm">{getFlag(node.country)}</span>
												<span className="text-[11px] text-muted-foreground font-mono truncate">
													{node.city || "—"}
													{node.country && node.city && `, ${node.country}`}
												</span>
											</div>

											{/* Reward % */}
											<div className="flex items-center justify-center">
												<span
													className={cn(
														"text-xs font-black font-mono px-2 py-0.5 rounded border",
														getRewardColor(node.user_reward_share_percent || 0),
														getRewardBg(node.user_reward_share_percent || 0),
													)}
												>
													{node.user_reward_share_percent || 0}%
												</span>
											</div>

											{/* Uptime */}
											<div className="flex items-center justify-center gap-1">
												<span
													className={cn(
														"w-1.5 h-1.5 rounded-full",
														(node.uptime_percent || 0) >= 99.5
															? "bg-emerald-400 animate-pulse"
															: (node.uptime_percent || 0) >= 95
																? "bg-yellow-400"
																: "bg-rose-400",
													)}
												/>
												<span
													className={cn(
														"text-[11px] font-mono font-bold",
														getUptimeColor(node.uptime_percent || 0),
													)}
												>
													{(node.uptime_percent || 0).toFixed(1)}%
												</span>
											</div>

											{/* Latency */}
											<div className="flex items-center justify-center">
												<span
													className={cn(
														"text-[11px] font-mono font-bold",
														getLatencyColor(node.latency_ms || 0),
													)}
												>
													{node.is_master ? "—" : `${node.latency_ms || 0}ms`}
												</span>
											</div>

											{/* Active Miners */}
											<div className="flex items-center justify-center gap-1">
												<Users className="w-3 h-3 text-muted-foreground" />
												<span className="text-[11px] font-mono font-bold text-foreground">
													{node.active_miners || 0}
												</span>
											</div>
										</motion.div>

										{/* Option 1: Expanded Accordion with Plan Cards */}
										<AnimatePresence>
											{isExpanded && (
												<NodeDetailRow node={node} isRu={isRu} />
											)}
										</AnimatePresence>
									</div>
								);
							})}
						</div>
					</TooltipProvider>
				</CardContent>
			</Card>

			{/* Operator Seasons Teaser Block */}
			<Card className="border border-border/20 bg-card/15 backdrop-blur-sm relative overflow-hidden">
				<div className="absolute top-0 right-0 p-5 opacity-5">
					<Award className="h-28 w-28 text-primary" />
				</div>
				<CardContent className="p-5">
					<div className="flex items-center gap-3 mb-4">
						<div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
							<Trophy className="w-4.5 h-4.5 text-amber-400" />
						</div>
						<div>
							<div className="text-sm font-bold text-foreground flex items-center gap-2">
								{t(
									"community:network.leaderboard.seasonsTitle",
									"Operator Seasons",
								)}
								<Badge
									variant="outline"
									className="text-[8px] h-4 border-amber-500/30 text-amber-400 bg-amber-500/5 px-1.5 uppercase tracking-wider font-bold"
								>
									{isRu ? "Скоро" : "Coming Soon"}
								</Badge>
							</div>
							<p className="text-[10px] text-muted-foreground mt-0.5">
								{t(
									"community:network.leaderboard.seasonsDesc",
									"Compete for seasonal bonuses! Top node operators earn $DEPTH prizes for uptime, volume, and growth.",
								)}
							</p>
						</div>
					</div>

					{/* Season Preview Categories */}
					<div className="grid grid-cols-2 md:grid-cols-4 gap-2">
						{[
							{
								icon: TrendingUp,
								title: isRu ? "Чемпион объёмов" : "Volume Champion",
								desc: isRu ? "Наибольший торговый объём" : "Highest trade volume",
								color: "text-blue-400",
								bg: "bg-blue-500/5 border-blue-500/15",
							},
							{
								icon: Shield,
								title: isRu ? "Герой аптайма" : "Uptime Hero",
								desc: isRu ? "Лучшая стабильность" : "Best uptime record",
								color: "text-emerald-400",
								bg: "bg-emerald-500/5 border-emerald-500/15",
							},
							{
								icon: Users,
								title: isRu ? "Звезда роста" : "Growth Star",
								desc: isRu ? "Больше всего новых майнеров" : "Most new miners onboarded",
								color: "text-purple-400",
								bg: "bg-purple-500/5 border-purple-500/15",
							},
							{
								icon: Coins,
								title: isRu ? "Награда щедрости" : "Generosity Award",
								desc: isRu ? "Лучший reward share" : "Highest reward share %",
								color: "text-amber-400",
								bg: "bg-amber-500/5 border-amber-500/15",
							},
						].map((cat, idx) => (
							<div
								key={idx}
								className={cn(
									"p-3 rounded-lg border flex items-start gap-2.5 transition-all hover:bg-card/40",
									cat.bg,
								)}
							>
								<cat.icon className={cn("w-4 h-4 shrink-0 mt-0.5", cat.color)} />
								<div>
									<div className="text-xs font-bold text-foreground">
										{cat.title}
									</div>
									<div className="text-[10px] text-muted-foreground">
										{cat.desc}
									</div>
								</div>
							</div>
						))}
					</div>
				</CardContent>
			</Card>
		</div>
	);
};

export default NodeLeaderboard;
