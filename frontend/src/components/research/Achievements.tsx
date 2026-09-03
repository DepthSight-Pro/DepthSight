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
import type React from "react";
import { useTranslation } from "react-i18next";
import { AppLoader } from "@/components/shared/AppLoader";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
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

const getRarityColor = (rarity: string) => {
	switch (rarity?.toLowerCase()) {
		case "legendary":
			return "from-yellow-500 to-orange-500";
		case "epic":
			return "from-purple-500 to-pink-500";
		case "rare":
			return "from-blue-500 to-cyan-500";
		default:
			return "from-gray-500 to-gray-600";
	}
};

const getRarityBadgeClass = (rarity: string) => {
	switch (rarity?.toLowerCase()) {
		case "legendary":
			return "bg-yellow-500/10 text-yellow-500 border-yellow-500/30";
		case "epic":
			return "bg-purple-500/10 text-purple-500 border-purple-500/30";
		case "rare":
			return "bg-blue-500/10 text-blue-500 border-blue-500/30";
		default:
			return "bg-gray-500/10 text-gray-500 border-gray-500/30";
	}
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

	if (isLoadingAll || isLoadingUser) {
		return (
			<div className="flex items-center justify-center h-[60vh]">
				<AppLoader fullLogo size="xl" text={t("achievements.loading")} />
			</div>
		);
	}

	const unlockedAchievementIds = new Set(
		userAchievements?.map((ua) => ua.achievement_id),
	);
	const unlockedCount = userAchievements?.length || 0;
	const totalCount = allAchievements?.length || 0;

	return (
		<div className="space-y-6">
			{/* User Progress Card */}
			<UserProgressCard
				level={user?.level || 1}
				xp={user?.xp || 0}
				totalGenes={genesData?.total || 0}
			/>

			{/* Achievement Stats */}
			<div className="grid grid-cols-2 md:grid-cols-4 gap-4">
				<Card>
					<CardContent className="pt-6 text-center">
						<div className="text-3xl font-bold text-primary">
							{unlockedCount}
						</div>
						<div className="text-sm text-muted-foreground">
							{t("achievements.unlocked")}
						</div>
					</CardContent>
				</Card>
				<Card>
					<CardContent className="pt-6 text-center">
						<div className="text-3xl font-bold text-muted-foreground">
							{totalCount - unlockedCount}
						</div>
						<div className="text-sm text-muted-foreground">
							{t("achievements.locked")}
						</div>
					</CardContent>
				</Card>
				<Card>
					<CardContent className="pt-6 text-center">
						<div className="text-3xl font-bold text-green-500">
							{totalCount > 0
								? Math.round((unlockedCount / totalCount) * 100)
								: 0}
							%
						</div>
						<div className="text-sm text-muted-foreground">
							{t("achievements.progress")}
						</div>
					</CardContent>
				</Card>
				<Card>
					<CardContent className="pt-6 text-center">
						<div className="text-3xl font-bold text-yellow-500">
							{user?.xp || 0}
						</div>
						<div className="text-sm text-muted-foreground">
							{t("achievements.totalXP")}
						</div>
					</CardContent>
				</Card>
			</div>

			{/* Achievements Grid */}
			<TooltipProvider>
				<div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
					{allAchievements?.map((achievement) => {
						const isUnlocked = unlockedAchievementIds.has(achievement.id);
						const Icon = iconMap[achievement.id] || Award;
						const rarityGradient = getRarityColor(achievement.rarity);
						const userAchievement = userAchievements?.find(
							(ua) => ua.achievement_id === achievement.id,
						);

						return (
							<Tooltip key={achievement.id}>
								<TooltipTrigger asChild>
									<Card
										className={cn(
											"relative overflow-hidden transition-all cursor-pointer hover:scale-105",
											isUnlocked
												? "border-2 shadow-lg"
												: "opacity-50 grayscale",
										)}
									>
										{/* Rarity gradient top border */}
										{isUnlocked && (
											<div
												className={cn(
													"absolute top-0 left-0 right-0 h-1 bg-gradient-to-r",
													rarityGradient,
												)}
											/>
										)}

										<CardContent className="p-6 flex flex-col items-center justify-center space-y-3">
											{/* Icon */}
											<div
												className={cn(
													"relative p-4 rounded-full",
													isUnlocked
														? cn("bg-gradient-to-br", rarityGradient)
														: "bg-muted",
												)}
											>
												{isUnlocked ? (
													<Icon className="w-8 h-8 text-white" />
												) : (
													<Lock className="w-8 h-8 text-muted-foreground" />
												)}

												{/* Sparkle effect for unlocked */}
												{isUnlocked && (
													<Sparkles className="absolute -top-1 -right-1 w-4 h-4 text-yellow-400 animate-pulse" />
												)}
											</div>

											{/* XP Badge */}
											<Badge
												variant={isUnlocked ? "default" : "secondary"}
												className="text-xs"
											>
												+{achievement.xp_reward} XP
											</Badge>

											{/* Date unlocked */}
											{isUnlocked && userAchievement && (
												<div className="text-xs text-muted-foreground text-center">
													{new Date(
														userAchievement.unlocked_at,
													).toLocaleDateString()}
												</div>
											)}
										</CardContent>
									</Card>
								</TooltipTrigger>
								<TooltipContent side="bottom" className="max-w-xs">
									<div className="space-y-2">
										<div className="font-bold flex items-center gap-2">
											{t(`${achievement.id}.name`, {
												defaultValue: achievement.name,
											})}
											<Badge
												variant="outline"
												className={cn(
													"text-xs",
													getRarityBadgeClass(achievement.rarity),
												)}
											>
												{achievement.rarity}
											</Badge>
										</div>
										<p className="text-sm text-muted-foreground">
											{t(`${achievement.id}.description`, {
												defaultValue: achievement.description,
											})}
										</p>
										{isUnlocked ? (
											<div className="text-xs text-green-500 flex items-center gap-1">
												<Award className="w-3 h-3" />
												{t("achievements.tooltip.unlocked")}
											</div>
										) : (
											<div className="text-xs text-muted-foreground flex items-center gap-1">
												<Lock className="w-3 h-3" />
												{t("achievements.tooltip.locked")}
											</div>
										)}
									</div>
								</TooltipContent>
							</Tooltip>
						);
					})}
				</div>
			</TooltipProvider>
		</div>
	);
};

export default Achievements;
