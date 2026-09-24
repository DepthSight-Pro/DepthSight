// src/components/community/NodeLeaderboard.tsx

import React, { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
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
} from "lucide-react";
import type { TFunction } from "i18next";
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
import { DEFAULT_NODE_PLANS } from "@/lib/nodeLeaderboardPlans";
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
	if (!node.public_domain && !node.is_master) {
		return {};
	}
	if (node.public_plans && Object.keys(node.public_plans).length > 0) {
		return node.public_plans;
	}
	return DEFAULT_NODE_PLANS;
}

function getProPlanPrice(node: LeaderboardNode): number {
	if (!node.public_domain && !node.is_master) return 999;
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
		(n) => !n.public_domain && !n.is_master,
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
}> = ({ node }) => {
	const { t, i18n } = useTranslation(["community", "common"]);
	const isPrivate = !node.public_domain && !node.is_master;
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
							{t(
								"community:network.leaderboard.telemetry.allTimeMined",
								"All-time Mined",
							)}
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
							{t(
								"community:network.leaderboard.telemetry.activeMiners",
								"Active Miners",
							)}
						</div>
						<div className="text-sm font-black font-mono text-foreground">
							{node.active_miners || 0}
						</div>
					</div>
					<div className="p-2.5 rounded-lg bg-background/50 border border-border/30 shadow-sm">
						<div className="text-[9px] uppercase font-mono tracking-wider text-muted-foreground flex items-center gap-1 mb-1">
							<Clock className="w-3 h-3 text-indigo-400" />
							{t(
								"community:network.leaderboard.telemetry.onlineSince",
								"Online Since",
							)}
						</div>
						<div className="text-sm font-bold font-mono text-foreground">
							{node.created_at
								? new Date(node.created_at).toLocaleDateString(
										i18n.language?.startsWith("ru") ? "ru-RU" : "en-US",
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
							{t(
								"community:network.leaderboard.telemetry.version",
								"Version",
							)}
						</div>
						<div className="text-sm font-bold font-mono text-foreground">
							v{node.version || "—"}
						</div>
					</div>
				</div>

				{/* Node Subscription Plans (Only for public nodes & master hub) */}
				{isPrivate ? (
					<div className="pt-2">
						<div className="p-3.5 rounded-xl border border-border/20 bg-background/40 flex items-center justify-between gap-3">
							<div className="flex items-center gap-2.5">
								<div className="p-2 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20">
									<Lock className="w-4 h-4" />
								</div>
								<div>
									<div className="text-xs font-bold text-foreground flex items-center gap-1.5">
										{t(
											"community:network.leaderboard.privateNodeLabel",
											"Private Node",
										)}
										<Badge
											variant="outline"
											className="text-[9px] border-amber-500/30 text-amber-400 bg-amber-500/5"
										>
											{t(
												"community:network.leaderboard.privateNodeSelfHosted",
												"Self-hosted",
											)}
										</Badge>
									</div>
									<p className="text-[11px] text-muted-foreground mt-0.5">
										{t(
											"community:network.leaderboard.privateNodeDesc",
											"This node operates in private mode without public subscription plans.",
										)}
									</p>
								</div>
							</div>
						</div>
					</div>
				) : Object.keys(nodePlans).length > 0 ? (
					<div className="pt-2 space-y-3">
						<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/20 pb-2">
							<div className="flex items-center gap-2">
								<div className="p-1 rounded bg-primary/10 text-primary">
									<Layers className="w-4 h-4" />
								</div>
								<span className="text-xs font-bold uppercase tracking-wider text-foreground">
									{t(
										"community:network.leaderboard.plans.title",
										"Node Subscription Plans & Pricing",
									)}
								</span>
								<Badge variant="outline" className="text-[9px] border-primary/30 text-primary bg-primary/5">
									{t("community:network.leaderboard.plans.tiersCount", {
										count: Object.keys(nodePlans).length,
										defaultValue: `${Object.keys(nodePlans).length} tiers`,
									})}
								</Badge>
							</div>
							{node.public_domain && (
								<a
									href={`https://${node.public_domain}`}
									target="_blank"
									rel="noopener noreferrer"
									className="text-[11px] text-primary hover:underline flex items-center gap-1 font-mono"
								>
									{t(
										"community:network.leaderboard.plans.openWebApp",
										"Open Node Web App",
									)}
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
										<div>
											{/* Top header of card */}
											<div className="flex items-center justify-between gap-2 mb-2">
												<div className="flex items-center gap-1.5">
													<Zap className={cn("w-3.5 h-3.5", isPro ? "text-primary" : "text-muted-foreground")} />
													<span className="text-xs font-bold text-foreground">{plan.name}</span>
												</div>
												{isPro && (
													<Badge className="text-[8px] h-3.5 bg-primary text-primary-foreground font-bold px-1 py-0">
														{t("community:network.leaderboard.plans.popular", "POPULAR")}
													</Badge>
												)}
											</div>

											{/* Price & Billing Cycle */}
											<div className="mb-3">
												<div className="flex items-baseline gap-1">
													<span className="text-xl font-black font-mono text-foreground">${price}</span>
													<span className="text-[10px] text-muted-foreground font-mono">
														{isLifetime
															? t("community:network.leaderboard.plans.lifetime", "/ lifetime")
															: price === 0
																? ""
																: t("community:network.leaderboard.plans.perMonth", "/ month")}
													</span>
												</div>
												<p className="text-[10px] text-muted-foreground mt-0.5 line-clamp-2">
													{plan.description || t("community:network.leaderboard.plans.defaultDesc", "Node plan")}
												</p>
											</div>

											{/* Key Limits / Quotas */}
											<div className="p-2 rounded bg-background/50 border border-border/20 mb-3 space-y-1 font-mono text-[10px]">
												<div className="flex justify-between items-center text-muted-foreground">
													<span>{t("community:network.leaderboard.plans.backtests", "Backtests:")}</span>
													<span className="font-bold text-foreground">
														{plan.quotas?.run_vector_backtest_per_day === -1
															? t("community:network.leaderboard.plans.unlimited", "∞")
															: `${plan.quotas?.run_vector_backtest_per_day ?? 20}${t("community:network.leaderboard.plans.perDay", "/d")}`}
													</span>
												</div>
												<div className="flex justify-between items-center text-muted-foreground">
													<span>{t("community:network.leaderboard.plans.aiAssistant", "AI Assistant:")}</span>
													<span className="font-bold text-foreground">
														{plan.quotas?.use_ai_assistant_per_day === -1
															? t("community:network.leaderboard.plans.unlimited", "∞")
															: `${plan.quotas?.use_ai_assistant_per_day ?? 10}${t("community:network.leaderboard.plans.perDay", "/d")}`}
													</span>
												</div>
												<div className="flex justify-between items-center text-muted-foreground">
													<span>{t("community:network.leaderboard.plans.liveBots", "Live Bots:")}</span>
													<span className="font-bold text-foreground">
														{plan.limits?.max_live_strategies ?? 0}
													</span>
												</div>
											</div>

											{/* Feature Bullets */}
											{plan.features && plan.features.length > 0 && (
												<ul className="space-y-1 mb-3">
													{plan.features.slice(0, 4).map((f, fIdx) => (
														<li key={fIdx} className="text-[10px] text-muted-foreground flex items-center gap-1.5">
															<Check className="w-2.5 h-2.5 text-emerald-400 shrink-0" />
															<span className="truncate">{f}</span>
														</li>
													))}
												</ul>
											)}
										</div>

										{/* Action Button */}
										<div className="pt-2 border-t border-border/10 mt-auto">
											{node.public_domain ? (
												<a
													href={`https://${node.public_domain}`}
													target="_blank"
													rel="noopener noreferrer"
													className="block"
												>
													<Button
														size="sm"
														variant={isPro ? "default" : "outline"}
														className="w-full text-xs h-7 gap-1 font-semibold"
													>
														{t("community:network.leaderboard.plans.subscribeOnNode", "Subscribe on Node")}
														<ExternalLink className="w-3 h-3" />
													</Button>
												</a>
											) : (
												<Button
													size="sm"
													variant={isPro ? "default" : "outline"}
													className="w-full text-xs h-7 gap-1 font-semibold"
												>
													{t("community:network.leaderboard.plans.hubPlan", "Hub Plan")}
												</Button>
											)}
									</div>
								</Card>
							);
						})}
					</div>
				</div>
				) : null}
			</div>
		</motion.div>
	);
};

// Main Component
export const NodeLeaderboard: React.FC<{
	activeNodes: LeaderboardNode[];
	isRu?: boolean;
	t?: TFunction;
}> = ({ activeNodes, t: tProp }) => {
	const { t: tHook } = useTranslation(["community", "common"]);
	const t = tProp || tHook;
	const [sortKey, setSortKey] = useState<SortKey>("reward");
	const [sortDir, setSortDir] = useState<SortDir>("desc");
	const [expandedNode, setExpandedNode] = useState<string | null>(null);

	const { allNodes, privateCount } = useMemo(
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
					av = a.latency_ms ?? 9999;
					bv = b.latency_ms ?? 9999;
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
					av = 0;
					bv = 0;
			}
			if (sortDir === "asc") return av - bv;
			return bv - av;
		});
		return nodes;
	}, [allNodes, sortKey, sortDir]);

	const handleSort = (key: SortKey) => {
		if (sortKey === key) {
			setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
		} else {
			setSortKey(key);
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
											{t("community:network.leaderboard.privateNodesCount", "private")}
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
								label={t("community:network.leaderboard.sort.reward", "Reward")}
								sortKey="reward"
								currentSort={sortKey}
								currentDir={sortDir}
								onSort={handleSort}
							/>
							<SortButton
								label={t("community:network.leaderboard.sort.proPrice", "Pro Price")}
								sortKey="pro_price"
								currentSort={sortKey}
								currentDir={sortDir}
								onSort={handleSort}
							/>
							<SortButton
								label={t("community:network.leaderboard.sort.uptime", "Uptime")}
								sortKey="uptime"
								currentSort={sortKey}
								currentDir={sortDir}
								onSort={handleSort}
							/>
							<SortButton
								label={t("community:network.leaderboard.sort.latency", "Latency")}
								sortKey="latency"
								currentSort={sortKey}
								currentDir={sortDir}
								onSort={handleSort}
							/>
							<SortButton
								label={t("community:network.leaderboard.sort.mined", "Mined")}
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
						<div>{t("community:network.leaderboard.columns.nodeAndPlans", "Node & Plans")}</div>
						<div>{t("community:network.leaderboard.columns.location", "Location")}</div>
						<div className="text-center">{t("community:network.leaderboard.columns.reward", "Reward")}</div>
						<div className="text-center">{t("community:network.leaderboard.columns.uptime", "Uptime")}</div>
						<div className="text-center">{t("community:network.leaderboard.columns.ping", "Ping")}</div>
						<div className="text-center">{t("community:network.leaderboard.columns.miners", "Miners")}</div>
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
																	★ {t("community:network.leaderboard.masterBadge", "Master")}
																</Badge>
															</TooltipTrigger>
															<TooltipContent className="text-[10px]">
																{t(
																	"community:network.leaderboard.masterHubTooltip",
																	"Central Federation Hub",
																)}
															</TooltipContent>
														</Tooltip>
													)}
													{isPrivate && (
														<Tooltip>
															<TooltipTrigger asChild>
																<Badge className="text-[8px] h-3.5 bg-amber-500/10 text-amber-400 border-amber-500/20 px-1 py-0 flex items-center gap-0.5 font-mono">
																	<Lock className="w-2.5 h-2.5" />
																	{t(
																		"community:network.leaderboard.privateBadge",
																		"Private",
																	)}
																</Badge>
															</TooltipTrigger>
															<TooltipContent className="text-[10px]">
																{t(
																	"community:network.leaderboard.privateNodeTooltip",
																	"Self-hosted private node",
																)}
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
														{t(
															"community:network.leaderboard.privateNodeLabel",
															"Private Node",
														)}
													</span>
												) : null}

												{/* Option 4: Mini-Badges with Plan Prices & Quick Tooltips */}
												{!isPrivate && Object.keys(nodePlans).length > 0 && (
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
																			{plan.name} {t("community:network.leaderboard.plans.tierBadge", "Tier")}
																		</span>
																		<span className="text-primary font-mono">${plan.price_usd}{t("community:network.leaderboard.plans.perMonthShort", "/mo")}</span>
																	</div>
																	<p className="text-[10px] text-muted-foreground">
																		{plan.description || t("community:network.leaderboard.plans.defaultDesc", "Node plan")}
																	</p>
																	<div className="text-[10px] font-mono space-y-0.5 bg-muted/30 p-1.5 rounded">
																		<div>
																			{t("community:network.leaderboard.plans.backtests", "Backtests:")}{" "}
																			{plan.quotas?.run_vector_backtest_per_day === -1
																				? t("community:network.leaderboard.plans.unlimited", "Unlimited")
																				: `${plan.quotas?.run_vector_backtest_per_day ?? 0}${t("community:network.leaderboard.plans.perDay", "/day")}`}
																		</div>
																		<div>
																			{t("community:network.leaderboard.plans.aiAssistant", "AI Assistant:")}{" "}
																			{plan.quotas?.use_ai_assistant_per_day === -1
																				? t("community:network.leaderboard.plans.unlimited", "Unlimited")
																				: `${plan.quotas?.use_ai_assistant_per_day ?? 0}${t("community:network.leaderboard.plans.perDay", "/day")}`}
																		</div>
																		<div>
																			{t("community:network.leaderboard.plans.liveBots", "Live Bots:")}{" "}
																			{plan.limits?.allow_real_trading
																				? `${plan.limits?.max_live_strategies ?? 1} ${t("community:network.leaderboard.plans.activeBots", "active bots")}`
																				: t("community:network.leaderboard.plans.simulationOnly", "Simulation only")}
																		</div>
																	</div>
																</TooltipContent>
															</Tooltip>
														);
													})}
												</div>
											)}
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
											<Tooltip>
												<TooltipTrigger asChild>
													<div className="flex items-center justify-center gap-1 cursor-help">
														<Users className="w-3 h-3 text-muted-foreground" />
														<span className="text-[11px] font-mono font-bold text-foreground">
															{node.active_miners || 0}
														</span>
													</div>
												</TooltipTrigger>
												<TooltipContent side="top" className="text-xs font-mono">
													{t(
														"community:network.leaderboard.telemetry.activeMinersTooltip",
														{
															count: node.active_miners || 0,
															defaultValue: `Active miners: ${node.active_miners || 0}`,
														},
													)}
												</TooltipContent>
											</Tooltip>
										</motion.div>

										{/* Option 1: Expanded Accordion with Plan Cards */}
										<AnimatePresence>
											{isExpanded && (
												<NodeDetailRow node={node} />
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
									{t("community:network.leaderboard.comingSoon", "Coming Soon")}
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
								title: t(
									"community:network.leaderboard.seasons.volumeChampion.title",
									"Volume Champion",
								),
								desc: t(
									"community:network.leaderboard.seasons.volumeChampion.desc",
									"Highest trade volume",
								),
								color: "text-blue-400",
								bg: "bg-blue-500/5 border-blue-500/15",
							},
							{
								icon: Shield,
								title: t(
									"community:network.leaderboard.seasons.uptimeHero.title",
									"Uptime Hero",
								),
								desc: t(
									"community:network.leaderboard.seasons.uptimeHero.desc",
									"Best uptime record",
								),
								color: "text-emerald-400",
								bg: "bg-emerald-500/5 border-emerald-500/15",
							},
							{
								icon: Users,
								title: t(
									"community:network.leaderboard.seasons.growthStar.title",
									"Growth Star",
								),
								desc: t(
									"community:network.leaderboard.seasons.growthStar.desc",
									"Most new miners onboarded",
								),
								color: "text-purple-400",
								bg: "bg-purple-500/5 border-purple-500/15",
							},
							{
								icon: Coins,
								title: t(
									"community:network.leaderboard.seasons.generosityAward.title",
									"Generosity Award",
								),
								desc: t(
									"community:network.leaderboard.seasons.generosityAward.desc",
									"Highest reward share %",
								),
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
