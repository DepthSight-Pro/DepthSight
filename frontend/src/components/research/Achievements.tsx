// frontend/src/components/research/Achievements.tsx

import { useQuery } from "@tanstack/react-query";
import {
	Activity,
	AreaChart,
	Award,
	BarChart3,
	Beaker,
	Binary,
	Blocks,
	Bomb,
	BookOpenCheck,
	Box,
	BrainCircuit,
	Building2,
	CalendarClock,
	CheckCircle2,
	CircleDollarSign,
	CircleSlash,
	CloudLightning,
	Coins,
	Crosshair,
	Crown,
	Diamond,
	Dna,
	DollarSign,
	Eye,
	Fish,
	Flame,
	Gauge,
	GitBranchPlus,
	Globe,
	GraduationCap,
	Hand,
	HandHeart,
	Handshake,
	History,
	Hourglass,
	KeyRound,
	Library,
	Lightbulb,
	Lock,
	Medal,
	Network,
	Paperclip,
	Pickaxe,
	PieChart,
	PlugZap,
	Printer,
	Radio,
	RefreshCw,
	Rocket,
	Save,
	Scale,
	Scissors,
	Search,
	Server,
	Share2,
	Shield,
	ShieldCheck,
	Shuffle,
	SlidersHorizontal,
	Sparkles,
	Star,
	TestTube,
	TestTubes,
	Ticket,
	TrendingUp,
	Trophy,
	UserPlus,
	Users,
	Wallet,
	WandSparkles,
	Zap,
} from "lucide-react";
import React, { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { AppLoader } from "@/components/shared/AppLoader";
import { Segmented } from "@/components/ui/quant-ui";
import { useAuth } from "@/context/AuthContext";
import { useMyGenes } from "@/lib/api";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/utils";
import type { Achievement, UserAchievement } from "@/types/api";
import { UserProgressCard } from "./UserProgressCard";

const iconMap: { [key: string]: React.ElementType } = {
	// Onboarding
	first_backtest: History,
	first_save: Save,
	used_ai_assistant: WandSparkles,
	first_optimization: SlidersHorizontal,
	first_api_key: KeyRound,
	two_factor_enabled: ShieldCheck,
	first_paper_trade: Paperclip,
	reset_paper: RefreshCw,
	// Grinding
	"10_backtests": TestTube,
	"100_backtests": TestTubes,
	"500_backtests": Beaker,
	"1000_trades_backtests": BarChart3,
	"10000_trades_backtests": AreaChart,
	"50_optimizations": BrainCircuit,
	save_10_strategies: Library,
	// Performance
	sniper: Crosshair,
	marathon_runner: CalendarClock,
	hard_nut: ShieldCheck,
	alpha_hunter: Trophy,
	money_printer: Printer,
	winning_streak: TrendingUp,
	phoenix: Flame,
	flawless_victory: Crown,
	// Exploration
	clairvoyant: Eye,
	diversifier: PieChart,
	show_off: Share2,
	contender: Medal,
	the_intervention: Hand,
	pulling_the_plug: PlugZap,
	the_professor: GraduationCap,
	// Complexity
	strategy_5_blocks: Blocks,
	the_architect: Building2,
	logician: Binary,
	inventor: Lightbulb,
	order_flow_purist: BookOpenCheck,
	prudent_manager: Scissors,
	// Genome
	"10_strategies_discovery": Search,
	the_spark: Sparkles,
	gem_hunter: Diamond,
	treasure_hunter: Box,
	myth_buster: Zap,
	gene_collector: Dna,
	geneticist: Shuffle,
	natural_selection: GitBranchPlus,
	// Community
	recruiter: UserPlus,
	first_commission: DollarSign,
	partner: Handshake,
	// Easter Eggs
	underminer: Bomb,
	the_pacifist: CircleSlash,
	perfectly_balanced: Scale,
	diamond_hands: HandHeart,
	// Trade Mining
	mining_activated: Pickaxe,
	mining_wallet_linked: Wallet,
	mining_first_trade: Sparkles,
	welcome_bonus_claimed: Ticket,
	mining_volume_1k: CircleDollarSign,
	mining_volume_10k: Coins,
	mining_volume_100k: TrendingUp,
	mining_volume_1m: Fish,
	mining_volume_10m: Crown,
	mining_daily_volume_10k: Activity,
	mining_daily_volume_100k: CloudLightning,
	mining_daily_top_miner: Trophy,
	mining_daily_top5_miner: Medal,
	mining_first_referral: UserPlus,
	mining_5_referrals: Users,
	mining_10_referrals: Network,
	mining_50_referrals: Building2,
	mining_active_squad: Radio,
	mining_mentor_bonus: GraduationCap,
	mining_ref_volume_100k: Share2,
	mining_ref_earnings_100k: Diamond,
	mining_streak_7d: Flame,
	mining_streak_30d: Shield,
	mining_epochs_100: Award,
	mining_halving_survivor: Hourglass,
	mining_depth_1k: Coins,
	mining_depth_10k: Box,
	mining_depth_100k: Crown,
	mining_jackpot_epoch: Zap,
	mining_flawless_telemetry: CheckCircle2,
	mining_high_speed_turnover: Gauge,
	mining_profitable: TrendingUp,
	mining_multi_exchange: Shuffle,
	mining_all_exchanges: Globe,
	mining_node_operator: Server,
	mining_boost_active: Rocket,
	mining_diamond_staker: HandHeart,
};

const rarityColor: Record<string, string> = {
	common: "#8b93a7",
	rare: "#00d4ff",
	epic: "#a78bfa",
	legendary: "#ffb547",
};

const rarityIcon: Record<string, React.ElementType> = {
	common: Medal,
	rare: Star,
	epic: Crown,
	legendary: Trophy,
};

const Achievements = () => {
	const { t } = useTranslation(["account"]);
	const { user } = useAuth();
	const { data: genesData } = useMyGenes();

	const { data: allAchievements, isLoading: isLoadingAll } = useQuery<
		Achievement[],
		Error
	>({
		queryKey: ["achievements"],
		queryFn: () => apiClient<Achievement[]>("/achievements"),
	});

	const { data: userAchievements, isLoading: isLoadingUser } = useQuery<
		UserAchievement[],
		Error
	>({
		queryKey: ["userAchievements", user?.id],
		queryFn: () =>
			apiClient<UserAchievement[]>(`/users/${user?.id}/achievements`),
		enabled: !!user,
	});

	const [filter, setFilter] = useState<"all" | "unlocked" | "locked">("all");

	const unlockedAchievementIds = useMemo(
		() => new Set(userAchievements?.map((ua) => ua.achievement_id)),
		[userAchievements],
	);
	const unlockedCount = userAchievements?.length || 0;
	const totalCount = allAchievements?.length || 0;

	const filteredAchievements = useMemo(() => {
		if (!allAchievements) return [];
		if (filter === "unlocked") {
			return allAchievements.filter((a) => unlockedAchievementIds.has(a.id));
		}
		if (filter === "locked") {
			return allAchievements.filter((a) => !unlockedAchievementIds.has(a.id));
		}
		return allAchievements;
	}, [allAchievements, filter, unlockedAchievementIds]);

	if (isLoadingAll || isLoadingUser) {
		return (
			<div className="flex items-center justify-center h-[60vh]">
				<AppLoader fullLogo size="xl" text={t("achievements.loading")} />
			</div>
		);
	}

	return (
		<div className="space-y-6">
			{/* User Progress Card */}
			<UserProgressCard
				level={user?.level || 1}
				xp={user?.xp || 0}
				totalGenes={genesData?.total || 0}
			/>

			{/* Achievement Stats */}
			<div className="grid grid-cols-2 md:grid-cols-4 gap-3">
				<div className="glass rounded-2xl border border-white/10 p-4 text-center">
					<div className="font-mono text-2xl font-bold text-cyan">
						{unlockedCount}
					</div>
					<div className="text-[10.5px] uppercase tracking-wider text-white/40 mt-1 font-mono">
						{t("achievements.unlocked", "Unlocked")}
					</div>
				</div>
				<div className="glass rounded-2xl border border-white/10 p-4 text-center">
					<div className="font-mono text-2xl font-bold text-white/40">
						{totalCount - unlockedCount}
					</div>
					<div className="text-[10.5px] uppercase tracking-wider text-white/40 mt-1 font-mono">
						{t("achievements.locked", "Locked")}
					</div>
				</div>
				<div className="glass rounded-2xl border border-white/10 p-4 text-center">
					<div className="font-mono text-2xl font-bold text-emerald-400">
						{totalCount > 0
							? Math.round((unlockedCount / totalCount) * 100)
							: 0}%
					</div>
					<div className="text-[10.5px] uppercase tracking-wider text-white/40 mt-1 font-mono">
						{t("achievements.progress", "Progress")}
					</div>
				</div>
				<div className="glass rounded-2xl border border-white/10 p-4 text-center">
					<div className="font-mono text-2xl font-bold text-amber-400">
						{(user?.xp || 0).toLocaleString()}
					</div>
					<div className="text-[10.5px] uppercase tracking-wider text-white/40 mt-1 font-mono">
						{t("achievements.totalXP", "Total XP")}
					</div>
				</div>
			</div>

			{/* Filter Header */}
			<div className="flex items-center justify-between gap-3 flex-wrap pt-2">
				<div className="text-xs font-semibold text-white/60 uppercase tracking-wider font-mono">
					{t("achievementsListTitle", "Achievements")} ({filteredAchievements.length})
				</div>
				<Segmented
					size="sm"
					value={filter}
					onChange={(v) => setFilter(v as "all" | "unlocked" | "locked")}
					options={[
						{ value: "all", label: `${t("filterAll", "All")} (${totalCount})` },
						{ value: "unlocked", label: `${t("filterUnlocked", "Unlocked")} (${unlockedCount})` },
						{ value: "locked", label: `${t("filterLocked", "Locked")} (${totalCount - unlockedCount})` },
					]}
				/>
			</div>

			{/* Achievements Grid */}
			<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
				{filteredAchievements.map((achievement) => {
					const isUnlocked = unlockedAchievementIds.has(achievement.id);
					const rKey = achievement.rarity?.toLowerCase() || "common";
					const c = rarityColor[rKey] || "#8b93a7";
					const Icon = iconMap[achievement.id] || rarityIcon[rKey] || Award;
					const userAchievement = userAchievements?.find(
						(ua) => ua.achievement_id === achievement.id,
					);

					return (
						<div
							key={achievement.id}
							className={cn(
								"glass group relative overflow-hidden rounded-2xl p-4 flex items-center gap-4 transition-all hover:-translate-y-0.5",
								!isUnlocked && "opacity-50 grayscale hover:opacity-80 hover:grayscale-0 transition-opacity",
							)}
						>
							{/* Ambient glow in top-right */}
							<div
								className="pointer-events-none absolute -right-8 -top-8 h-28 w-28 rounded-full blur-2xl opacity-25"
								style={{ background: c }}
							/>

							{/* Icon container with rarity border and neon glow */}
							<div
								className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border transition-all"
								style={{
									borderColor: c + "55",
									background: c + "14",
									boxShadow: isUnlocked ? `0 0 24px -6px ${c}` : undefined,
								}}
							>
								{isUnlocked ? (
									<Icon size={22} style={{ color: c }} />
								) : (
									<Lock size={18} className="text-white/40" />
								)}
							</div>

							{/* Text block */}
							<div className="min-w-0 flex-1">
								<div className="flex items-center justify-between gap-2">
									<span className="text-[13px] font-semibold text-white truncate">
										{t(`${achievement.id}.name`, {
											defaultValue: achievement.name,
										})}
									</span>
									<div className="flex items-center gap-1.5 shrink-0">
										<span
											className="text-[9px] uppercase tracking-wider font-bold font-mono px-1.5 py-0.5 rounded border leading-none"
											style={{
												color: c,
												borderColor: c + "40",
												background: c + "12",
											}}
										>
											{achievement.rarity}
										</span>
										<span className="text-[10px] font-mono text-cyan/90 font-medium">
											+{achievement.xp_reward} XP
										</span>
									</div>
								</div>

								<div className="text-[11px] text-white/50 mt-1 leading-relaxed line-clamp-2">
									{t(`${achievement.id}.description`, {
										defaultValue: achievement.description,
									})}
								</div>

								{isUnlocked && userAchievement && (
									<div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-emerald-400 font-mono">
										<CheckCircle2 className="w-3 h-3" />
										<span>
											{new Date(
												userAchievement.unlocked_at,
											).toLocaleDateString()}
										</span>
									</div>
								)}
							</div>
						</div>
					);
				})}
			</div>
		</div>
	);
};

export default Achievements;
